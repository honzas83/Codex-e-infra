#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass

from test_connection import main as refresh_models
from codex_provider_tools.common import (
    ENV_PATH,
    ToolError,
    configured_base_url,
    configured_model,
    ensure_config,
    provider_name,
    read_api_key,
    write_env,
)


def prompt_value(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure an isolated Codex installation for a custom OpenAI-compatible provider.")
    parser.add_argument("--base-url", help="Provider API base URL, including /v1 when required.")
    parser.add_argument("--provider-name", help="Display name used in the generated Codex configuration.")
    parser.add_argument("--model", help="Initial model ID used before compatibility testing.")
    parser.add_argument("--no-key", action="store_true", help="Keep the existing API key and do not prompt for one.")
    args = parser.parse_args()

    current_url = configured_base_url(required=False)
    base_url = args.base_url or prompt_value("API base URL", current_url)
    name = args.provider_name or prompt_value("Provider name", provider_name())
    model = args.model or prompt_value("Initial model ID", configured_model())

    api_key = read_api_key(required=False)
    if not args.no_key:
        entered = getpass.getpass("API key (leave empty to keep the current value): ").strip()
        api_key = entered or api_key
    write_env(base_url=base_url, api_key=api_key, name=name)
    config = ensure_config(base_url=base_url, name=name)

    refresh_models(["--model", model])
    print(f"Environment: {ENV_PATH}")
    print(f"Configuration: {config}")
    print("Next step: python launch.py or python codex_cli.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ToolError, OSError, ValueError) as error:
        raise SystemExit(f"Error: {error}")
