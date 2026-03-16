# Repository Initialization Design

## Goal
Create minimal, high-signal documentation for a build-only repository that maintains `build.py` and `pyinstaller_config.json`.

## Scope
- Add `AGENTS.md` with build/lint/test guidance and code style rules.
- Add `README.md` with project overview and usage instructions.
- No new tooling, CI, or test framework added.

## Context
The repository currently contains:
- `build.py` (JSON-driven PyInstaller builder)
- `pyinstaller_config.json`
- `ui_main.spec`
- `build/`, `dist/`
There is no Git repository metadata and no existing README.

## Options Considered
1) **Lightweight documentation only (recommended)**
   - Add `AGENTS.md` + `README.md` only.
   - Pros: minimal maintenance, aligns with repo purpose.
   - Cons: no standardized structure for future growth.

2) Documentation + structural placeholders
   - Add `docs/` + a placeholder scripts directory.
   - Pros: prepares for expansion.
   - Cons: introduces unused structure.

3) Documentation + dependency files
   - Add `requirements.txt` or `pyproject.toml` placeholders.
   - Pros: clearer dependency story.
   - Cons: may become stale if not maintained.

## Chosen Approach
Option 1: lightweight documentation only.

## Design Details
### AGENTS.md
Include:
- Repository purpose and scope.
- Build commands from `build.py`:
  - `python build.py`
  - `python build.py --dry-run`
  - `python build.py --clean`
  - `python build.py --specpath <dir>`
- Single-test guidance:
  - If no test framework, explicitly state “no automated tests”.
  - Provide minimal validation steps (dry-run + build).
- Code style rules:
  - 2-space indentation, camelCase, verb-led function names.
  - Avoid `any`, avoid `eslint-disable` / `@ts-ignore`.
  - Prefer clarity, remove unused code, no commented-out blocks.
  - Error handling: fail fast with actionable messages, avoid broad except.

### README.md
Include:
- Short project overview.
- Usage:
  - Build command examples.
  - Configuration fields explanation for `pyinstaller_config.json`.
  - Examples of common options.

## Testing/Verification
No automated tests. Minimum validation steps:
- `python build.py --dry-run` to verify command generation.
- `python build.py` to execute PyInstaller.

## Out of Scope
- Adding CI, linters, or test frameworks.
- Changing `build.py` behavior.
