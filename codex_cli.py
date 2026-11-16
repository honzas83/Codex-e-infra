#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys

from codex_provider_tools.common import (
    API_KEY_ENV,
    CODEX_HOME,
    ToolError,
    ensure_config,
    codex_command,
    find_codex_cli,
    load_dotenv,
    read_api_key,
)


def main() -> int:
    ensure_config()
    executable = find_codex_cli()
    environment = os.environ.copy()
    environment.update(load_dotenv())
    environment["CODEX_HOME"] = str(CODEX_HOME)
    environment[API_KEY_ENV] = read_api_key()
    arguments = ["-C", os.getcwd(), *sys.argv[1:]]
    if os.name == "nt":
        return subprocess.run(codex_command(executable, arguments), env=environment, check=False).returncode
    os.execve(executable, [str(executable), *arguments], environment)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ToolError, OSError, ValueError) as error:
        raise SystemExit(f"Error: {error}")
