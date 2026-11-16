from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
CODEX_HOME = STATE_DIR / "codex-home"
ELECTRON_DIR = STATE_DIR / "electron"
LOG_DIR = STATE_DIR / "logs"
CONFIG_TEMPLATE = ROOT / "config" / "config.toml"
CONFIG_PATH = CODEX_HOME / "config.toml"
MODEL_CATALOG = CODEX_HOME / "models.json"
ENV_PATH = ROOT / ".env"
BASE_URL_ENV = "CODEX_PROVIDER_BASE_URL"
API_KEY_ENV = "CODEX_PROVIDER_API_KEY"
PROVIDER_NAME_ENV = "CODEX_PROVIDER_NAME"
LEGACY_API_KEY_ENV = "EINFRA_AI_TOKEN"
DEFAULT_PROVIDER_NAME = "Custom Responses Provider"
PLACEHOLDER_BASE_URL = "https://example.invalid/v1"
MODEL_CATALOG_FORMAT_VERSION = 2


class ToolError(RuntimeError):
    pass


def model_comp_hash(model_id: str, effort: str) -> str:
    value = f"{MODEL_CATALOG_FORMAT_VERSION}:{model_id}:{effort}:no-reasoning-summary"
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_windows() -> bool:
    return platform.system() == "Windows"


def ensure_directories() -> None:
    for path in (STATE_DIR, CODEX_HOME, ELECTRON_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        if os.name != "nt":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for number, raw_line in enumerate(ENV_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ToolError(f"Invalid line {number} in {ENV_PATH.name}.")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ToolError(f"Invalid variable name on line {number} in {ENV_PATH.name}.")
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise ToolError(f"Invalid quoted value on line {number} in {ENV_PATH.name}.") from error
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        values[key] = value
    return values


def _env_value(name: str) -> str | None:
    return os.environ.get(name) or load_dotenv().get(name)


def validate_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("The provider base URL must be an absolute HTTP or HTTPS URL.")
    return normalized


def configured_base_url(required: bool = True) -> str:
    value = _env_value(BASE_URL_ENV)
    if not value:
        for path in (CONFIG_PATH, CONFIG_TEMPLATE):
            if path.exists():
                match = re.search(r'(?m)^base_url\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"))
                if match and match.group(1) != PLACEHOLDER_BASE_URL:
                    value = match.group(1)
                    break
    if not value:
        if required:
            raise ToolError(f"Missing {BASE_URL_ENV}. Run setup.py first.")
        return ""
    return validate_base_url(value)


def provider_name() -> str:
    return _env_value(PROVIDER_NAME_ENV) or DEFAULT_PROVIDER_NAME


def read_api_key(required: bool = True) -> str:
    key = _env_value(API_KEY_ENV) or _env_value(LEGACY_API_KEY_ENV)
    if not key and required:
        raise ToolError(f"Missing {API_KEY_ENV}. Run setup.py or edit {ENV_PATH}.")
    return key or ""


def write_env(*, base_url: str, api_key: str, name: str) -> None:
    values = {
        BASE_URL_ENV: validate_base_url(base_url),
        API_KEY_ENV: api_key,
        PROVIDER_NAME_ENV: name.strip() or DEFAULT_PROVIDER_NAME,
    }
    remove = (LEGACY_API_KEY_ENV,)
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ToolError("Environment values must not contain line breaks.")
    content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines = content.splitlines()
    managed = set(values) | set(remove)
    kept = []
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if not match or match.group(1) not in managed:
            kept.append(line)
    for key, value in values.items():
        kept.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    atomic_write(ENV_PATH, "\n".join(kept).rstrip() + "\n")


def _provider_block(base_url: str, name: str) -> str:
    return "\n".join(
        [
            "[model_providers.custom]",
            f"name = {json.dumps(name)}",
            f"base_url = {json.dumps(base_url)}",
            f'env_key = "{API_KEY_ENV}"',
            'env_key_instructions = "Run setup.py; the key is stored in the local .env file."',
            'wire_api = "responses"',
            "requires_openai_auth = false",
            "request_max_retries = 2",
            "stream_max_retries = 2",
            "",
        ]
    )


def _disable_reasoning_metadata(content: str) -> str:
    updated = re.sub(r"(?m)^model_reasoning_effort\s*=.*\n?", "", content)
    updated = re.sub(r"(?m)^model_supports_reasoning_summaries\s*=.*\n?", "", updated)
    settings = {
        "model_reasoning_summary": '"none"',
    }
    missing: list[str] = []
    for key, value in settings.items():
        if re.search(rf"(?m)^{key}\s*=", updated):
            updated = re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", updated, count=1)
        else:
            missing.append(f"{key} = {value}")
    if missing:
        first_section = re.search(r"(?m)^\[", updated)
        position = first_section.start() if first_section else len(updated)
        updated = updated[:position].rstrip() + "\n" + "\n".join(missing) + "\n\n" + updated[position:]
    return updated


def ensure_config(base_url: str | None = None, name: str | None = None) -> Path:
    ensure_directories()
    base_url = validate_base_url(base_url) if base_url else configured_base_url()
    name = name.strip() if name and name.strip() else provider_name()
    content = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else CONFIG_TEMPLATE.read_text(encoding="utf-8")
    updated = re.sub(r'(?m)^model_provider\s*=.*$', 'model_provider = "custom"', content, count=1)
    catalog_line = f"model_catalog_json = {json.dumps(str(MODEL_CATALOG))}"
    if re.search(r"(?m)^model_catalog_json\s*=", updated):
        updated = re.sub(r"(?m)^model_catalog_json\s*=.*$", catalog_line, updated, count=1)
    else:
        updated = re.sub(r"(?m)^(model_provider\s*=.*)$", rf"\1\n{catalog_line}", updated, count=1)
    updated = _disable_reasoning_metadata(updated)
    provider_pattern = re.compile(r"(?ms)^\[model_providers\.[^\]]+\]\n.*?(?=^\[|\Z)")
    if provider_pattern.search(updated):
        updated = provider_pattern.sub(_provider_block(base_url, name), updated, count=1)
    else:
        updated = updated.rstrip() + "\n\n" + _provider_block(base_url, name)
    if not CONFIG_PATH.exists() or updated != content:
        atomic_write(CONFIG_PATH, updated)
    normalize_model_catalog()
    return CONFIG_PATH


def normalize_model_catalog() -> None:
    if not MODEL_CATALOG.exists():
        return
    try:
        catalog = json.loads(MODEL_CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    changed = False
    for model in catalog.get("models", []) if isinstance(catalog, dict) else []:
        if not isinstance(model, dict):
            continue
        if model.get("default_reasoning_summary") != "none":
            model["default_reasoning_summary"] = "none"
            changed = True
        if model.get("supports_reasoning_summary_parameter") is not False:
            model["supports_reasoning_summary_parameter"] = False
            changed = True
        slug = model.get("slug")
        effort = model.get("default_reasoning_level")
        if isinstance(slug, str) and isinstance(effort, str):
            expected_hash = model_comp_hash(slug, effort)
            if model.get("comp_hash") != expected_hash:
                model["comp_hash"] = expected_hash
                changed = True
    if changed:
        atomic_write(MODEL_CATALOG, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")


def configured_model() -> str:
    if CONFIG_PATH.exists():
        match = re.search(r'(?m)^model\s*=\s*"([^"]+)"', CONFIG_PATH.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return "default"


def set_configured_model(model: str) -> None:
    content = ensure_config().read_text(encoding="utf-8")
    updated, count = re.subn(r"(?m)^model\s*=.*$", f"model = {json.dumps(model)}", content, count=1)
    if count == 0:
        updated = f"model = {json.dumps(model)}\n" + content
    if updated != content:
        atomic_write(CONFIG_PATH, updated)


def codex_command(executable: Path, arguments: list[str]) -> list[str]:
    command = [str(executable), *arguments]
    if is_windows() and executable.suffix.lower() in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(command)]
    return command


def find_desktop_executable(explicit: str | None = None) -> Path:
    override = explicit or _env_value("CODEX_APP_PATH")
    candidates: list[Path] = []
    if override:
        supplied = Path(override).expanduser()
        candidates.append(supplied / "Contents/MacOS/ChatGPT" if is_macos() and supplied.suffix == ".app" else supplied)
    if is_macos():
        candidates.extend([Path("/Applications/Codex.app/Contents/MacOS/ChatGPT"), Path.home() / "Applications/Codex.app/Contents/MacOS/ChatGPT"])
    elif is_windows():
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", ""))
        candidates.extend([local / "Programs/Codex/Codex.exe", local / "Programs/ChatGPT/ChatGPT.exe", program_files / "Codex/Codex.exe", program_files / "ChatGPT/ChatGPT.exe"])
        for executable_name in ("Codex.exe", "ChatGPT.exe"):
            found = shutil.which(executable_name)
            if found:
                candidates.append(Path(found))
    else:
        raise ToolError("Only macOS and Microsoft Windows are supported.")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ToolError("Codex Desktop was not found. Set CODEX_APP_PATH in .env.")


def find_codex_cli(explicit: str | None = None) -> Path:
    override = explicit or _env_value("CODEX_CLI_PATH")
    candidates: list[Path] = [Path(override).expanduser()] if override else []
    if is_macos():
        candidates.append(Path("/Applications/Codex.app/Contents/Resources/codex"))
    elif is_windows():
        try:
            desktop = find_desktop_executable()
            candidates.extend([desktop.parent.parent / "resources/codex.exe", desktop.parent / "resources/codex.exe"])
        except ToolError:
            pass
    found = shutil.which("codex")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ToolError("Codex CLI was not found. Set CODEX_CLI_PATH in .env.")
