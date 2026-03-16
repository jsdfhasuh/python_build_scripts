# Repository Agent Guide

## Scope
This repository maintains the PyInstaller build helper (`build.py`) and its JSON config.
Do not modify the application code that is referenced by `pyinstaller_config.json`.

## Build / Lint / Test Commands
There is no lint or test framework in this repository.

### Build
- Build: `python build.py`
- Dry run (print PyInstaller command only): `python build.py --dry-run`
- Clean build artifacts: `python build.py --clean`
- Write spec to custom directory: `python build.py --specpath <dir>`

### Single Test
- No automated tests are defined.
- Minimal validation:
  - `python build.py --dry-run`
  - `python build.py`

## Configuration
`pyinstaller_config.json` fields used by `build.py`:
- `entry`: absolute path to entry script
- `name`: output name
- `onefile`: true/false, onefile or onedir
- `console`: true/false, console window
- `icon`: icon path or null
- `add_data`: list of data mappings
- `hidden_imports`: list of hidden imports
- `excludes`: list of excluded modules
- `collect_binaries`: list of modules to collect binaries from
- `extra_args`: raw PyInstaller args

## Code Style
Follow these rules when editing Python in this repository.

### Formatting
- Indentation: 2 spaces
- Line length: prefer <= 100 chars
- Use single quotes for strings unless clarity requires double quotes

### Imports
- Standard library first, third-party next, local last
- One import per line when possible
- Avoid wildcard imports

### Types
- Avoid `Any`
- Prefer explicit types for public functions
- Keep type hints simple and readable

### Naming
- Variables: camelCase
- Functions: verb-led names (e.g., `getConfig`, `loadConfig`)
- Constants: UPPER_SNAKE_CASE

### Error Handling
- Fail fast with actionable messages
- Avoid broad `except Exception` unless logging and re-raising
- Do not swallow exceptions silently

### Comments
- Only add comments for non-obvious logic
- Comments must be in English

### Cleanup
- Remove unused code
- Do not comment out dead code; delete it

## Build Script Conventions
- Keep `build.py` behavior deterministic
- Prefer configuration in `pyinstaller_config.json` over hardcoding
- Keep PyInstaller arguments explicit and logged

## Cursor / Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` found

## Safety
- Do not modify `build/` or `dist/` by hand
- Do not hardcode machine-specific paths beyond `pyinstaller_config.json`
