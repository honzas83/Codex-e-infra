from __future__ import annotations

import unittest
import json
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch

import test_connection
import launch
import codex_cli
import setup
from codex_provider_tools.catalog import build_catalog, model_ids
from codex_provider_tools.common import _disable_reasoning_metadata


class ProbeTests(unittest.TestCase):
    def test_launchers_only_prepare_local_config(self) -> None:
        for module in (launch, codex_cli):
            with self.subTest(launcher=module.__name__), patch.object(
                module, "ensure_config", side_effect=RuntimeError("stop before launch")
            ) as configure, patch("sys.argv", [module.__name__]):
                self.assertFalse(hasattr(module, "refresh_models"))
                with self.assertRaisesRegex(RuntimeError, "stop before launch"):
                    module.main()
                configure.assert_called_once_with()

    def test_setup_refreshes_models_with_selected_preference(self) -> None:
        with patch("sys.argv", ["setup.py", "--base-url", "https://example.test/v1",
                                "--provider-name", "Test", "--model", "qwen", "--no-key"]), \
             patch.object(setup, "configured_base_url", return_value=""), \
             patch.object(setup, "read_api_key", return_value="secret"), \
             patch.object(setup, "write_env"), patch.object(setup, "ensure_config"), \
             patch.object(setup, "refresh_models", return_value=0) as refresh:
            self.assertEqual(setup.main(), 0)
        refresh.assert_called_once_with(["--model", "qwen"])

    def test_reasoning_metadata_is_force_disabled(self) -> None:
        source = '''model = "agentic"
model_reasoning_summary = "detailed"
model_reasoning_effort = "none"
model_supports_reasoning_summaries = false

[model_providers.custom]
wire_api = "responses"
'''
        rendered = _disable_reasoning_metadata(source)
        self.assertIn('model_reasoning_summary = "none"', rendered)
        self.assertNotIn("model_supports_reasoning_summaries", rendered)
        self.assertNotIn("model_reasoning_effort", rendered)

    def test_model_listing_removes_obvious_non_chat_entries(self) -> None:
        payload = {
            "data": [
                {"id": "agentic"},
                {"id": "mxbai-embed-large:latest"},
                {"id": "multilingual-e5-large-instruct"},
                {"id": "qwen3-reranker-4b"},
                {"id": "whisper-large-v3"},
                {"id": "all-proxy-models"},
            ]
        }
        self.assertEqual(model_ids(payload), ["agentic"])

    def test_generated_models_disable_reasoning_summary_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "models.json"
            output.write_text(
                json.dumps({"models": [{"slug": "template", "model_messages": {}}]}),
                encoding="utf-8",
            )
            build_catalog(
                {"data": [{"id": "agentic"}]},
                {},
                None,
                output,
                allowed_ids=["agentic"],
                reasoning_efforts={"agentic": "none"},
            )
            generated = json.loads(output.read_text(encoding="utf-8"))["models"][0]

        self.assertIs(generated["supports_reasoning_summary_parameter"], False)
        self.assertEqual(generated["default_reasoning_summary"], "none")
        self.assertNotEqual(generated["comp_hash"], "")

    def test_catalog_uses_current_bundled_template_without_code_mode(self) -> None:
        bundled = {"models": [
            {"slug": "old", "visibility": "list", "supported_in_api": True, "priority": 9},
            {"slug": "current", "visibility": "list", "supported_in_api": True,
             "priority": 1, "tool_mode": "code_mode_only", "multi_agent_version": "v2",
             "base_instructions": "current instructions"},
        ]}
        result = subprocess.CompletedProcess([], 0, json.dumps(bundled), "")
        with tempfile.TemporaryDirectory() as directory, patch(
            "codex_provider_tools.catalog.subprocess.run", return_value=result
        ):
            output = Path(directory) / "models.json"
            build_catalog({"data": [{"id": "new-model"}]}, {}, Path("codex"), output)
            model = json.loads(output.read_text())["models"][0]
        self.assertEqual(model["base_instructions"], "current instructions")
        self.assertNotIn("tool_mode", model)
        self.assertNotIn("multi_agent_version", model)
        self.assertFalse(model["use_responses_lite"])
        self.assertIsNone(model["apply_patch_tool_type"])

    def test_stateless_replay_keeps_user_query_and_names_tool(self) -> None:
        first = {
            "output": [
                {
                    "type": "function_call",
                    "name": test_connection.PROBE_NAME,
                    "call_id": "call-1",
                    "arguments": "{}",
                }
            ]
        }
        with patch.object(test_connection, "request_with_retry", side_effect=[(200, first), (200, {"output": []})]) as request:
            passed, _, effort = test_connection.probe_model("model-a", "https://example.test/v1", "secret", 10, 0)

        self.assertTrue(passed)
        self.assertEqual(effort, "none")
        replay = request.call_args_list[1].args[3]["input"]
        self.assertEqual(replay[0]["role"], "user")
        self.assertEqual(replay[1]["name"], test_connection.PROBE_NAME)
        self.assertEqual(replay[-2]["role"], "developer")
        self.assertEqual(replay[-1]["role"], "user")
        self.assertEqual(request.call_args_list[0].args[3]["instructions"], "You are a helpful coding assistant.")
        self.assertEqual(replay[-3], {"type": "function_call_output", "call_id": "call-1", "output": "OK"})

    def test_probe_falls_back_to_supported_reasoning_effort(self) -> None:
        unsupported = {"error": {"message": "reasoning_effort must be low, medium, or high"}}
        first = {
            "output": [
                {
                    "type": "function_call",
                    "name": test_connection.PROBE_NAME,
                    "call_id": "call-2",
                    "arguments": "{}",
                }
            ]
        }
        with patch.object(
            test_connection,
            "request_with_retry",
            side_effect=[(400, unsupported), (200, first), (200, {"output": []})],
        ):
            passed, _, effort = test_connection.probe_model("model-b", "https://example.test/v1", "secret", 10, 0)

        self.assertTrue(passed)
        self.assertEqual(effort, "medium")

    def test_probe_rejects_late_system_instruction_failure(self) -> None:
        first = {"output": [{"type": "function_call", "name": test_connection.PROBE_NAME,
                             "call_id": "call-1", "arguments": "{}"}]}
        error = {"error": {"message": "System message must be at the beginning."}}
        with patch.object(test_connection, "request_with_retry",
                          side_effect=[(200, first), (400, error)]):
            passed, reason, effort = test_connection.probe_model(
                "agentic", "https://example.test/v1", "secret", 10, 0)
        self.assertFalse(passed)
        self.assertIn("System message must be at the beginning", reason)
        self.assertIsNone(effort)

    def test_error_text_redacts_credentials_and_fingerprints(self) -> None:
        message = {"error": {"message": "token secret-value; api_key fingerprint: abc123"}}
        rendered = test_connection.error_text(message, "secret-value")
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertIn("[REDACTED]", rendered)


if __name__ == "__main__":
    unittest.main()
