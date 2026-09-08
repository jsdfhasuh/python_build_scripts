# Repository Agent Guide

## Scope
This repository maintains the PyInstaller build helper (`build.py`), target JSON configs,
and GitHub Actions workflows for external source repositories.
Do not modify the application code that is referenced by target configs.

## Build / Lint / Test Commands
Tests use standard-library unittest; no separate lint framework is configured.
Unit tests use Pillow and PyYAML, without Torch or Qt. Windows fixture acceptance also uses
PyInstaller and pefile in a separate test environment.

### Build
- Build: `python build.py`
- Dry run (print PyInstaller command only): `python build.py --dry-run`
- Clean build artifacts: `python build.py --clean`
- Write spec to custom directory: `python build.py --specpath <dir>`
- Local Release fallback: `.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.2.3 -SourceRoot D:\training_platform`
- Emo Master artifacts: `.\scripts\publish-local-release.ps1 -Target emo-master -ReleaseTag v0.6.0 -SourceRoot <emo_master> -BuildOnly -OutputDirectory <dir>`
- Vision Train wizard: `python scripts\release_wizard_emo_vision_train.py`
- Emo Master wizard: `python scripts\release_wizard_emo_master.py`

For local validation of external source targets, set `SOURCE_ROOT` first. Example:
`$env:SOURCE_ROOT='D:\training_platform'; $env:RELEASE_TAG='v0.0.0-local'; python build.py --config configs\emo-vision-train.json --dry-run`

### Single Test
- Full unit/CLI suite: `python -m unittest discover -s tests -v`
- Default-target baseline: `python -m unittest discover -s tests -p test_build_baseline.py -v`
- Tests use fixtures and mocked compilers, not real Windows EXEs or a production Release.
- Minimal validation:
  - `python -m py_compile build.py`
  - `python build.py --config configs\emo-vision-train.json --dry-run` with `SOURCE_ROOT` set
  - `python build.py --config configs\emo-master.json --dry-run` with `SOURCE_ROOT` set
  - `python build.py`

## Configuration
`configs/*.json` fields used by `build.py`:
- `source_repo`: external source repository in `owner/repo` form
- `release_repo`: optional default GitHub Release repository in `owner/repo` form
- `python_version`: Python version used by GitHub Actions
- `pyinstaller_version`: optional pinned PyInstaller version metadata
- `release_asset_name`: GitHub Release asset name template
- `source_version_file`: optional source file used to validate release tag against `__version__`
- `ci_extra_packages`: extra packages installed by GitHub Actions after source requirements
- `entry`: path to entry script, usually using `${SOURCE_ROOT}`
- `name`: output name
- `onefile`: true/false, onefile or onedir
- `console`: true/false, console window
- `collect_conda_runtime_dlls`: collect the full Conda runtime DLL set; defaults to true
- `icon`: icon path or null
- `add_data`: list of data mappings
- `hidden_imports`: list of hidden imports
- `excludes`: list of excluded modules
- `collect_binaries`: list of modules to collect binaries from
- `extra_args`: raw PyInstaller args
- `installer`: optional Inno Setup configuration and installer smoke-test settings

## VisionWorkshop Opt-in Portable Branding
- Usage: `docs/visionworkshop-branding.md`; review: `docs/evidence/visionworkshop-branding-review.md`.
- The new CLI is `python scripts/publish_visionworkshop.py`; no publication without `--publish`.
- `build.py` supports directory-only branding; the shared portable CLI adds ZIP and build records.
- Select a profile explicitly. Never write overlays back to target JSON or silently reuse dist.
- Private build records are not public artifacts. Verify configuration, source, tools and files.
- Reject EXE-renaming publication with unverified updater compatibility. Runtime updates are NOT disabled.
- The production ICO is not included. Test fixture icons are not product branding assets.
- Keep configs, existing runtime hooks, installer code and dependency versions unchanged.
- Original PowerShell publisher is preserved verbatim as `publish-local-release-legacy.ps1`.
  The public wrapper routes only portable requests; master and old defaults keep their old logic.
- New workflows are `visionworkshop-portable.yml` and `visionworkshop-tests.yml`.
  Cross-repository callers must supply packager_ref; do not infer it from a source-repository SHA.
- Run `python -m unittest discover -s tests -v`. On Windows also run
  `python scripts/verify_windows_portable.py` for real fixture compilation and EXE checks.
- Fixture success is not product GUI/GPU/hardware/update acceptance. Record skipped/not-run checks honestly.

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
