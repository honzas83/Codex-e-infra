#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from codex_provider_tools.catalog import build_catalog, model_ids
from codex_provider_tools.common import (
    MODEL_CATALOG,
    ToolError,
    configured_base_url,
    configured_model,
    ensure_config,
    find_codex_cli,
    read_api_key,
    set_configured_model,
)


PROBE_NAME = "codex_compatibility_probe"
PROBE_PROMPT = "Call codex_compatibility_probe exactly once. Do not answer directly."
PROBE_TOOL = {
    "type": "function",
    "name": PROBE_NAME,
    "description": "Return a fixed value used only to verify function calling compatibility.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    "strict": False,
}
EFFORTS = ("none", "medium", "low", "high")
TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


def request_json(base_url: str, path: str, api_key: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> tuple[int, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        method="POST" if payload is not None else "GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "codex-provider-tools/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"error": raw[:1000]}
        return error.code, parsed


def error_text(response: Any, api_key: str = "") -> str:
    value = response.get("error", response) if isinstance(response, dict) else response
    if isinstance(value, dict):
        value = value.get("message", value)
    text = str(value).replace("\n", " ")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"(?i)(api[_ -]?key(?: fingerprint)?\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text[:400]


def request_with_retry(
    base_url: str,
    path: str,
    api_key: str,
    payload: dict[str, Any] | None,
    timeout: int,
    retries: int,
) -> tuple[int, Any]:
    status, response = 0, {}
    for attempt in range(retries + 1):
        status, response = request_json(base_url, path, api_key, payload, timeout)
        if status not in TRANSIENT_STATUSES or attempt == retries:
            return status, response
        time.sleep(min(2**attempt, 8))
    return status, response


def is_effort_error(response: Any, api_key: str) -> bool:
    message = error_text(response, api_key).lower()
    return "reasoning_effort" in message or "reasoning effort" in message


def probe_model(model: str, base_url: str, api_key: str, timeout: int, retries: int) -> tuple[bool | None, str, str | None]:
    user_item = {"role": "user", "content": [{"type": "input_text", "text": PROBE_PROMPT}]}
    last_effort_error = ""
    for effort in EFFORTS:
        common = {
            "model": model,
            "instructions": "You are a helpful coding assistant.",
            "tools": [PROBE_TOOL],
            "parallel_tool_calls": False,
            "reasoning": {"effort": effort},
            "include": ["reasoning.encrypted_content"],
            "store": False,
        }
        first_status, first = request_with_retry(
            base_url,
            "responses",
            api_key,
            {**common, "input": [user_item], "tool_choice": "required", "max_output_tokens": 128},
            timeout,
            retries,
        )
        if first_status in TRANSIENT_STATUSES:
            return None, f"transient HTTP {first_status}: {error_text(first, api_key)}", None
        if first_status != 200:
            if is_effort_error(first, api_key):
                last_effort_error = f"HTTP {first_status}: {error_text(first, api_key)}"
                continue
            return False, f"initial Responses request returned HTTP {first_status}: {error_text(first, api_key)}", None

        output = first.get("output", []) if isinstance(first, dict) else []
        if not isinstance(output, list):
            return False, "Responses API did not return an output array", None
        calls = [
            item for item in output
            if isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("name") == PROBE_NAME
            and isinstance(item.get("call_id"), str)
        ]
        if not calls:
            return False, "model did not return the requested function_call", None

        replay = [user_item, *output]
        replay.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Compatibility probe is running."}],
            }
        )
        replay.extend(
            {"type": "function_call_output", "call_id": call["call_id"], "output": "OK"}
            for call in calls
        )
        replay.extend([
            {"role": "developer", "content": "The tool has finished. Reply briefly."},
            {"role": "user", "content": "Confirm the tool result."},
        ])
        second_status, second = request_with_retry(
            base_url,
            "responses",
            api_key,
            {**common, "input": replay, "tool_choice": "auto", "max_output_tokens": 32},
            timeout,
            retries,
        )
        if second_status in TRANSIENT_STATUSES:
            return None, f"transient HTTP {second_status}: {error_text(second, api_key)}", None
        if second_status != 200:
            return False, f"tool result replay returned HTTP {second_status}: {error_text(second, api_key)}", None
        return True, "Responses API and stateless function-call round trip", effort

    return False, f"no supported reasoning effort ({last_effort_error})", None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test a provider and publish only Codex-compatible models to the local catalog.")
    parser.add_argument("--model", help="Preferred default model if it passes the compatibility test.")
    parser.add_argument("--workers", type=int, default=1, help="Number of models tested concurrently (default: 1).")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout for each API request in seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Retries for rate limits and temporary server errors (default: 3).")
    args = parser.parse_args(argv)
    if args.workers < 1 or args.timeout < 1 or args.retries < 0:
        raise ToolError("--workers and --timeout must be positive; --retries cannot be negative.")

    base_url = configured_base_url()
    ensure_config(base_url=base_url)
    api_key = read_api_key()

    print(f"Loading models from {base_url} ...")
    status, models = request_with_retry(base_url, "models", api_key, None, args.timeout, args.retries)
    if status != 200:
        raise ToolError(f"GET /models returned HTTP {status}: {error_text(models, api_key)}")

    info_status, info = request_with_retry(base_url, "model/info", api_key, None, args.timeout, args.retries)
    if info_status != 200:
        print(f"Model metadata is unavailable (HTTP {info_status}); continuing with /models only.")
        info = {}
    candidates = model_ids(models)
    if not candidates:
        raise ToolError("GET /models did not contain any likely conversational model IDs.")

    print(f"Testing {len(candidates)} candidate models with API-only, harmless function calls ...")
    results: dict[str, tuple[bool | None, str, str | None]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = {
            executor.submit(probe_model, model, base_url, api_key, args.timeout, args.retries): model
            for model in candidates
        }
        for future in concurrent.futures.as_completed(pending):
            model = pending[future]
            try:
                result = future.result()
            except (OSError, ValueError, urllib.error.URLError) as error:
                result = (None, error_text(error, api_key), None)
            results[model] = result
            state, reason, effort = result
            label = "PASS" if state is True else "FAIL" if state is False else "RETRY"
            suffix = f" (reasoning: {effort})" if effort else f": {reason}"
            print(f"  {label:<5} {model}{suffix}")

    inconclusive = [model for model in candidates if results[model][0] is None]
    if inconclusive:
        print("Temporarily unavailable models omitted: " + ", ".join(inconclusive))
    compatible = [model for model in candidates if results[model][0] is True]
    if not compatible:
        raise ToolError("No model passed the Responses API function-call round trip.")

    efforts = {model: results[model][2] for model in compatible if results[model][2]}
    included = build_catalog(models, info, find_codex_cli(), MODEL_CATALOG, allowed_ids=compatible, reasoning_efforts=efforts)
    preferred = args.model or configured_model()
    selected = preferred if preferred in compatible else ("agentic" if "agentic" in compatible else compatible[0])
    set_configured_model(selected)

    print(f"\nPublished {len(included)} compatible models to the local catalog.")
    print(f"Default model: {selected}")
    print("Restart the isolated Codex desktop instance to reload the catalog.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ToolError, OSError, ValueError, urllib.error.URLError) as error:
        raise SystemExit(f"Error: {error}")
