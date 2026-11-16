# Codex-e-infra

Run Codex Desktop or Codex CLI with the **e-INFRA CZ AI API**, using a separate local profile and a model picker built from the models your own API key can access.

For students, teachers, and researchers who want to work with scientific code, explore unfamiliar repositories, and develop reproducible analysis scripts with an AI coding assistant.

This is an independent community project, not an official OpenAI, CESNET, CERIT-SC, or e-INFRA CZ product. It does not include Codex itself, models, or an API subscription.

## What it does

- Keeps its Codex configuration, sessions, and Desktop profile under this project's `state/` directory.
- Connects Codex directly to the configured Responses API, without a local proxy.
- Fetches the current model list during setup and tests candidates before adding them to the picker.
- Checks a function call, its returned result, reasoning settings, and a developer instruction inserted after conversation history.
- Uses the installed Codex catalog as the template instead of depending on one hard-coded OpenAI model version.
- Starts Desktop and CLI from the saved catalog, without repeating model discovery on every launch.
- Uses only Python's standard library. There are no Python packages to install.

**Profile isolation is not a security boundary.** Codex and its tools still run with your operating-system account's permissions, subject to the configured approval and sandbox policies.

## Contents

- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Launch Desktop or CLI](#launch-desktop-or-cli)
- [Refresh and select models](#refresh-and-select-models)
- [Configuration and local files](#configuration-and-local-files)
- [Model compatibility and limitations](#model-compatibility-and-limitations)
- [Teaching and research workflows](#teaching-and-research-workflows)
- [Troubleshooting](#troubleshooting)
- [Development and reporting issues](#development-and-reporting-issues)
- [License and official references](#license-and-official-references)

## Requirements

| Requirement | Notes |
| --- | --- |
| Python 3.10 or newer | No virtual environment or `pip install` is required. |
| Codex Desktop or Codex CLI | Install separately using the [official Codex documentation](https://developers.openai.com/codex/). A CLI binary is required during setup, even if you plan to use Desktop. |
| macOS or Microsoft Windows | Launch helpers target these systems. See the verification notes below. |
| Git | Used to clone and update this repository; a downloaded ZIP also works. |
| An e-INFRA CZ API key | Obtain your own key through [Chat AI](https://chat.ai.e-infra.cz). Eligibility and service rules are defined by the provider. |
| Network access | Setup and model requests need access to the provider. Other Codex features may contact their own services. |

An OpenAI API key is not needed for the configured e-INFRA model requests. Other Codex integrations and account features are outside the scope of these tools.

### Get your API key

Follow the [official e-INFRA API guide](https://docs.cerit-sc.cz/en/docs/ai-as-a-service/ai-api). Sign in to Chat AI and open **Settings**, then **Account**, then **API keys**. Use an API key, not the separately displayed JWT token. Access depends on your eligible institutional account.

Each student or colleague should use their own account and key. Do not distribute a shared key with course materials.

## Quick start

### 1. Download the project

```sh
git clone https://github.com/honzas83/Codex-e-infra.git
cd Codex-e-infra
```

Alternatively, download and extract the repository ZIP, then open a terminal in the extracted directory.

### 2. Check Python and Codex

On macOS:

```sh
python3 --version
codex --version
```

On Windows, in PowerShell:

```powershell
py -3 --version
codex --version
```

If Codex is bundled with Desktop but is not on `PATH`, the tools try common installation locations. If automatic detection fails, see [Executable paths](#executable-paths).

### 3. Run setup

On macOS:

```sh
python3 setup.py --base-url https://llm.ai.e-infra.cz/v1 --provider-name "e-INFRA CZ"
```

On Windows:

```powershell
py -3 setup.py --base-url https://llm.ai.e-infra.cz/v1 --provider-name "e-INFRA CZ"
```

Setup asks for an initial model preference and your API key. Key entry is hidden: no characters appearing while you type is normal.

If you do not know a model ID, accept the initial preference. Setup selects a compatible model when the preference is absent from the passing results. Model IDs come from the live API; names shown in the web chat may differ.

Setup saves your local credentials, fetches `/models` and optional `/model/info`, probes the candidates, writes a filtered catalog, and selects a default. This can take several minutes and consumes provider API tokens. Tests run serially by default to reduce account-limit problems.

A `PASS` means the focused compatibility checks passed. A `FAIL` explains an incompatibility. A `RETRY` indicates a temporary or inconclusive failure; that model is omitted until a later successful refresh. If no model passes, setup fails without replacing the previous catalog.

### 4. Start Codex

```sh
python3 launch.py
```

Or use the CLI:

```sh
python3 codex_cli.py
```

On Windows, replace `python3` with `py -3` in these and the following Python commands.

## Launch Desktop or CLI

### Desktop

```sh
python3 launch.py
```

Choose your research or teaching project in the application. Both its Electron profile and its Codex home are separate from your regular profile. Existing accounts, plugins, and preferences from a regular Codex profile are not automatically copied.

Use this launcher whenever you want the isolated configuration. Opening Codex normally does not select this profile.

Desktop output goes to `state/logs/`. Restart the isolated Desktop instance after refreshing models so its picker reloads. If your platform reuses an existing running instance, close it and launch again with this script.

### CLI

```sh
python3 codex_cli.py
python3 codex_cli.py -m MODEL_ID
python3 codex_cli.py --help
```

Replace `MODEL_ID` with an ID in your generated catalog. CLI arguments are forwarded to Codex; an explicit model override is not checked by this wrapper.

The CLI starts in your current terminal directory. To work in another project, change directory first and run the launcher by its absolute path:

```sh
cd /path/to/research-project
python3 /path/to/Codex-e-infra/codex_cli.py
```

Desktop and CLI share the same isolated Codex configuration. Neither launcher fetches or probes models at startup. They still require the provider for inference.

## Refresh and select models

Rerun setup when changing the provider or credentials. To keep the existing key:

```sh
python3 setup.py --no-key
```

To refresh the model list without repeating setup questions:

```sh
python3 test_connection.py
```

To request a default model, if it passes:

```sh
python3 test_connection.py --model MODEL_ID
```

For a busy service, adjust the timeout and retry count:

```sh
python3 test_connection.py --timeout 90 --retries 4
```

Optional parallel testing:

```sh
python3 test_connection.py --workers 2
```

`--model` chooses the preferred default; it does **not** restrict probing to that model. Higher concurrency may trigger provider limits. Temporary failures can produce a smaller catalog; rerun the refresh when the service recovers.

The published catalog always derives from the latest successful discovery, rather than a fixed model list committed to GitHub. It is a snapshot from setup or the last manual refresh, not a continuously updated service.

## Configuration and local files

Setup creates `.env` in the project directory:

```dotenv
CODEX_PROVIDER_BASE_URL="https://llm.ai.e-infra.cz/v1"
CODEX_PROVIDER_API_KEY="your-own-api-key"
CODEX_PROVIDER_NAME="e-INFRA CZ"
```

`.env.example` contains placeholders only. The tools read `.env` themselves; you do not need to load it into your shell. Existing process environment variables take precedence when the configuration helpers resolve credentials and provider settings, so remove old overrides before switching providers.

### Executable paths

Set absolute paths in `.env` if automatic detection cannot locate your installation:

```dotenv
# macOS examples
CODEX_APP_PATH="/Applications/Codex.app"
CODEX_CLI_PATH="/absolute/path/to/codex"
```

For Windows, forward slashes avoid quoting problems:

```dotenv
CODEX_APP_PATH="C:/path/to/Codex.exe"
CODEX_CLI_PATH="C:/path/to/codex.cmd"
```

Use paths that actually exist on your machine; installation layouts vary. `CODEX_APP_PATH` can point to a macOS app bundle or a Windows executable. The CLI override must point to the CLI executable or command file.

### File layout

```text
Codex-e-infra/
  setup.py                    Interactive configuration and model refresh
  launch.py                   Isolated Desktop launcher
  codex_cli.py                Isolated CLI launcher
  test_connection.py          Live compatibility tests and catalog refresh
  codex_provider_tools/       Shared configuration and catalog code
  config/config.toml          Initial configuration template
  tests/                      Offline automated tests
  .env.example                Public credential template
  .env                        Private local credentials; never committed
  state/                      Private local runtime files; never committed
    codex-home/config.toml    Generated Codex user configuration
    codex-home/models.json    Generated model picker catalog
    electron/                 Isolated Desktop profile
    logs/                     Desktop process output
```

The provider is written into the isolated **user-level** Codex configuration. Update the endpoint through setup rather than putting provider settings in a research project's `.codex/config.toml`.

On Unix, managed credential and configuration files use restrictive permissions. The API key is still stored as plaintext, not in an encrypted vault. Windows permissions follow the local filesystem's access controls.

Do not upload `.env`, `state/`, API keys, or unredacted session logs. A Git ignore rule protects normal commits, not manual uploads or forced staging.

To reset this profile, close its running processes and move `state/` to a backup location, then rerun setup. Keep `.env` only if you want to retain the credentials. Moving or deleting `state/` also removes the active profile's access to its saved sessions and preferences.

## Model compatibility and limitations

Codex needs more than an OpenAI-compatible chat endpoint. This project requires a compatible **Responses API**, function calling, and replay of tool outputs. A model appearing in `/models` is not a guarantee that it supports those features.

The probe requests a virtual function and returns the constant `OK`. It does not execute shell commands, read research data, or run a real model-generated tool. It then tests a developer instruction added after conversation history. This last check is deliberately stricter than a simple chat or basic tool-call test.

### Qwen and agentic: “System message must be at the beginning”

Some gateway/model combinations reject a developer instruction after conversation history, reporting that a system message must appear first. This is a server-side compatibility restriction, not evidence that every request to that model fails.

In local checks on **2026-11-16**, `qwen3.8-27b` and `qwen3.8-flash-next` answered a short request through Codex and passed a basic function-call round trip without the added developer instruction. They failed the stricter mid-conversation instruction check. `agentic` also failed that check.

These models can therefore work for some tasks while remaining excluded by this project's conservative filter. Removing the check would hide a known failure mode. This repository does not rewrite message order or run a compatibility proxy. A gateway-side fix may allow them to pass on a later refresh.

### Other compatibility adjustments

- Reasoning summaries are disabled because some gateways translate the Responses reasoning object incorrectly.
- The probe discovers an accepted reasoning effort for each model. An accepted value does not prove that every backend interprets it identically.
- OpenAI-specific code-mode and multi-agent overrides are removed from inherited model metadata.
- Responses Lite and experimental context capabilities are disabled in generated entries.
- The grammar-based `apply_patch` custom tool is disabled for gateway compatibility. Codex can still use its shell tools to edit files.
- Missing context metadata falls back to 128,000 tokens. That is an assumption, not a measured provider limit.

A passing probe does not establish scientific quality, correct answers, support for every Codex tool, reliable long sessions, image support, parallel agents, or compatibility with all future Codex releases.

### Verification baseline

The integration was checked locally with **Codex CLI 0.164.0 on macOS**. A real short Codex request using `deepseek-v4.1-flash-thinking` completed successfully after the compatibility adjustments. This is a dated observation, not a permanent recommendation or promise of availability.

Windows launch paths are implemented, but real Windows Desktop launches have not been manually verified here. Automated tests use mocks for platform and network operations; they do not replace a live platform check.

## Teaching and research workflows

### A first classroom exercise

Start with a small repository and synthetic data. Ask the assistant:

> Explain this project's structure and identify its inputs, outputs, and assumptions. Do not change any files yet.

Then request one change that is easy to inspect:

> Add a check for missing values to this CSV analysis. Show the proposed behavior, preserve the input file, and include a small example that demonstrates the check.

Have students review the change, run it, and explain why the result is correct. Use separate credentials and local profiles for each learner.

### Working with scientific code

Useful starting tasks include understanding inherited scripts, documenting parameters, checking units, adding a regression test for a numerical bug, and preparing a reproducible command sequence. Keep the original data unchanged and work on a version-controlled copy.

For each result you intend to publish or rely on, record:

- The code commit and relevant software versions, including Codex.
- The exact provider model ID and the date of use; aliases may change backend models.
- The prompt, relevant context, and material model settings.
- Input-data provenance and the commands used to reproduce the result.
- The independent checks you performed on calculations and scientific claims.

Verify citations against real publications and calculations against known cases. Do not treat plausible explanations as scientific validation. Follow your institution's rules for confidential data and AI assistance, and the disclosure requirements of your course or publication.

The isolated profile does not guarantee that all application traffic stays with e-INFRA CZ. Model requests use the configured endpoint, while Codex plugins, authentication, updates, or other enabled features can have separate services and data flows. Consult the provider's [data privacy policy](https://docs.cerit-sc.cz/en/docs/ai-as-a-service/ai-data-privacy) and your institution's requirements before using restricted data.

## Troubleshooting

| Symptom | Explanation and next step |
| --- | --- |
| Python command not found | Use `python3` on macOS or `py -3` on Windows; install Python 3.10+ if missing. |
| Codex executable not found | Install Codex or set an existing absolute executable path in `.env`. Setup needs the CLI catalog command. |
| HTTP 401 or 403 | Verify your own API key and service eligibility. Use the API key, not the JWT token. Check old environment overrides. |
| Invalid model name | The ID may have been renamed or removed. Refresh the catalog and choose a currently passing model. |
| System message must be at the beginning | See the Qwen/agentic explanation above. A plain chat test can pass while the stricter check fails. |
| HTTP 429, timeout, or transient server failure | Retry later, keep one worker, and consider a longer timeout. Temporarily failing models are omitted. |
| No model passes | Check access, endpoint, and failure messages. A generic chat-compatible endpoint may lack the required Responses features. |
| Model picker has old entries | Restart the isolated Desktop process after refresh. Make sure you used this project's launcher. |
| Changes appear in the wrong profile | Use `launch.py` or `codex_cli.py`; a normal Codex launch uses its own configuration. |
| Unknown configuration field or catalog parsing error | Check the Codex version, update this project, and rerun setup. The catalog is derived from the locally installed CLI. |
| Grammar-format custom tools are rejected | Refresh to regenerate the catalog with grammar-based `apply_patch` disabled. |
| Plugins or OpenAI account features fail | Those services are separate from model inference and are not configured by this project. |

Monitor your own API consumption through the [e-INFRA usage dashboard](https://llm.ai.e-infra.cz/usage). Model testing itself generates API usage.

## Development and reporting issues

Run the offline tests without an API key:

```sh
python3 -m unittest discover -s tests -v
```

The GitHub Actions workflow runs these tests on macOS and Windows. It never runs live provider probes or needs a provider secret.

To update a cloned checkout:

```sh
git pull --ff-only
python3 setup.py --no-key
```

When reporting a problem, include your OS, Python and Codex versions, model ID, whether it occurs in setup/Desktop/CLI, and a redacted error message. Explain whether a basic request works and whether the failure needs a tool call or a later instruction. Never attach `.env`, your full `state/` directory, authentication headers, or private research inputs.

Keep contributions small and dependency-free where practical. Add a focused test when changing behavior. Live compatibility depends on the current provider, so date any empirical model observations instead of treating them as permanent supported-model lists.

## License and official references

The wrapper scripts and documentation in this repository are released under the [MIT License](LICENSE). Codex, the hosted service, and the models have their own terms and licenses.

- [Official Codex documentation](https://developers.openai.com/codex/)
- [Connecting Codex to a gateway](https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway?gateway-auth=api-key)
- [e-INFRA CZ API documentation](https://docs.cerit-sc.cz/en/docs/ai-as-a-service/ai-api)
- [e-INFRA CZ Chat AI](https://chat.ai.e-infra.cz)
- [e-INFRA CZ API usage dashboard](https://llm.ai.e-infra.cz/usage)

The official e-INFRA guide documents the service endpoint, key acquisition, and usage dashboard. This README's Codex compatibility observations come from local checks of these scripts, not from an official support guarantee.
