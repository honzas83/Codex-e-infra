from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .common import ToolError, codex_command, model_comp_hash, provider_name


NON_CHAT_MARKERS = (
    "embed",
    "rerank",
    "whisper",
    "transcription",
    "speech",
    "tts",
    "multilingual-e5",
    "all-proxy-models",
)


def model_ids(payload: Any) -> list[str]:
    entries = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    found: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        value = entry.get("id") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value.strip() and not any(marker in value.lower() for marker in NON_CHAT_MARKERS):
            found.add(value.strip())
    return sorted(found, key=str.lower)


def _metadata(payload: Any) -> dict[str, dict[str, Any]]:
    entries = payload.get("data", []) if isinstance(payload, dict) else []
    result = {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            name = entry.get("model_name") or entry.get("id")
            if isinstance(name, str):
                result[name] = entry
    return result


def _info(entry: dict[str, Any]) -> dict[str, Any]:
    value = entry.get("model_info", {})
    return value if isinstance(value, dict) else {}


def _capabilities(entry: dict[str, Any]) -> list[str]:
    value = _info(entry).get("capabilities", entry.get("capabilities", []))
    return [str(item).lower() for item in value] if isinstance(value, list) else []


def _context(entry: dict[str, Any]) -> int:
    info = _info(entry)
    for key in ("context_size", "context_window", "max_input_tokens"):
        value = info.get(key, entry.get(key))
        if isinstance(value, int) and value > 0:
            return value
    return 128_000


def build_catalog(
    models: Any,
    model_info: Any,
    codex_binary: Path | None,
    output: Path,
    allowed_ids: list[str] | None = None,
    reasoning_efforts: dict[str, str] | None = None,
) -> list[str]:
    ids = allowed_ids if allowed_ids is not None else model_ids(models)
    if not ids:
        raise ToolError("The /models response does not contain any usable model IDs.")
    info_by_name = _metadata(model_info)
    if codex_binary is None:
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ToolError("The bootstrap catalog is missing. Run setup.py first.") from error
        template = next((item for item in existing.get("models", []) if isinstance(item, dict)), None)
    else:
        result = subprocess.run(codex_command(codex_binary, ["debug", "models", "--bundled"]), check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise ToolError(f"Codex did not provide a model catalog template: {result.stderr.strip()}")
        bundled = json.loads(result.stdout)
        templates = [item for item in bundled.get("models", [])
                     if isinstance(item, dict) and item.get("visibility") == "list"
                     and item.get("supported_in_api")]
        template = min(templates, key=lambda item: item.get("priority", 1000), default=None)
    if not isinstance(template, dict):
        raise ToolError("No usable Codex model catalog template was found.")

    generated = []
    included = []
    display_provider = provider_name()
    for index, model_id in enumerate(ids, start=1):
        metadata = info_by_name.get(model_id, {})
        capabilities = set(_capabilities(metadata))
        context = _context(metadata)
        multimodal = bool(capabilities & {"multimodal", "vision", "image"})
        details = [f"{context:,} token context"]
        if capabilities:
            details.insert(0, ", ".join(sorted(capabilities)))
        quantization = _info(metadata).get("quantization")
        if isinstance(quantization, str) and quantization:
            details.append(quantization)
        effort = (reasoning_efforts or {}).get(model_id, "none")

        item = copy.deepcopy(template)
        # Custom providers use standard function tools, not OpenAI-only code mode.
        for key in ("tool_mode", "multi_agent_version", "multi_agent_reasoning_effort"):
            item.pop(key, None)
        item.update(
            {
                "slug": model_id,
                "display_name": model_id,
                "description": f"{display_provider}; {'; '.join(details)}.",
                "priority": index,
                "visibility": "list",
                "supported_in_api": True,
                "additional_speed_tiers": [],
                "service_tiers": [],
                "availability_nux": None,
                "upgrade": None,
                "supported_reasoning_levels": [],
                "default_reasoning_level": effort,
                "supports_reasoning_summary_parameter": False,
                "default_reasoning_summary": "none",
                "support_verbosity": False,
                "supports_search_tool": False,
                "context_window": context,
                "max_context_window": context,
                "effective_context_window_percent": 90,
                "input_modalities": ["text", "image"] if multimodal else ["text"],
                "apply_patch_tool_type": None,
                "use_responses_lite": False,
                "supports_experimental_context": False,
                "supports_reasoning_effort_updates": False,
                "comp_hash": model_comp_hash(model_id, effort),
            }
        )
        instructions = item.get("model_messages", {}).get("instructions_template")
        if isinstance(instructions, str):
            item["model_messages"]["instructions_template"] = instructions.replace(
                "You are Codex, a coding agent based on GPT-5.",
                "You are Codex, a coding agent using the configured model provider.",
            )
        generated.append(item)
        included.append(model_id)

    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({"models": generated}, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(prefix="models.", suffix=".json", dir=output.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return included
