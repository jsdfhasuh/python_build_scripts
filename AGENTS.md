# Repository Agent Guide

## Scope
This repository maintains the PyInstaller build helper (`build.py`), target JSON configs,
and GitHub Actions workflows for external source repositories.
Do not modify the application code that is referenced by target configs.

## Build / Lint / Test Commands
There is no lint or test framework in this repository.

### Build
- Build: `python build.py`
- Dry run (print PyInstaller command only): `python build.py --dry-run`
- Clean build artifacts: `python build.py --clean`
- Write spec to custom directory: `python build.py --specpath <dir>`
- Local Release fallback: `.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.2.3 -SourceRoot D:\training_platform`

For local validation of external source targets, set `SOURCE_ROOT` first. Example:
`$env:SOURCE_ROOT='D:\training_platform'; $env:RELEASE_TAG='v0.0.0-local'; python build.py --config configs\emo-vision-train.json --dry-run`

### Single Test
- No automated tests are defined.
- Minimal validation:
  - `python -m py_compile build.py`
  - `python build.py --config configs\emo-vision-train.json --dry-run` with `SOURCE_ROOT` set
  - `python build.py`

## Configuration
`configs/*.json` fields used by `build.py`:
- `source_repo`: external source repository in `owner/repo` form
- `release_repo`: optional default GitHub Release repository in `owner/repo` form
- `python_version`: Python version used by GitHub Actions
- `release_asset_name`: GitHub Release asset name template
- `ci_extra_packages`: extra packages installed by GitHub Actions after source requirements
- `entry`: path to entry script, usually using `${SOURCE_ROOT}`
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
- Prefer configuration in `configs/*.json` over hardcoding
- Keep PyInstaller arguments explicit and logged

## Cursor / Copilot Rules
- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` found

## Safety
- Do not modify `build/` or `dist/` by hand
- Do not hardcode machine-specific paths beyond target config files
