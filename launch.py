#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess

from codex_provider_tools.common import (
    API_KEY_ENV,
    CODEX_HOME,
    ELECTRON_DIR,
    LOG_DIR,
    ToolError,
    ensure_config,
    ensure_directories,
    find_desktop_executable,
    is_windows,
    load_dotenv,
    read_api_key,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Codex Desktop with an isolated local profile.")
    parser.add_argument("--app", help="Path to Codex.app or Codex.exe.")
    args = parser.parse_args()
    ensure_directories()
    ensure_config()
    executable = find_desktop_executable(args.app)
    environment = os.environ.copy()
    environment.update(load_dotenv())
    environment["CODEX_HOME"] = str(CODEX_HOME)
    environment[API_KEY_ENV] = read_api_key()

    stdout = (LOG_DIR / "desktop.stdout.log").open("ab")
    stderr = (LOG_DIR / "desktop.stderr.log").open("ab")
    kwargs = {"env": environment, "stdout": stdout, "stderr": stderr, "stdin": subprocess.DEVNULL}
    if is_windows():
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([str(executable), f"--user-data-dir={ELECTRON_DIR}"], **kwargs)
    stdout.close()
    stderr.close()
    print(f"Started an isolated Codex Desktop instance (PID {process.pid}).")
    print(f"Local state: {CODEX_HOME.parent}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ToolError, OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Error: {error}")
