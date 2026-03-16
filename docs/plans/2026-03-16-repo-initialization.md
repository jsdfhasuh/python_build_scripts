# Repository Initialization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `AGENTS.md` and `README.md` tailored to the build-only PyInstaller repository.

**Architecture:** Two documentation files at repo root describing build usage and code style, aligned with existing `build.py` and `pyinstaller_config.json` behavior. No tooling changes.

**Tech Stack:** Python 3, PyInstaller, JSON configuration.

---

### Task 1: Draft `AGENTS.md`

**Files:**
- Create: `AGENTS.md`

**Step 1: Write the failing test**
No automated test framework exists for documentation creation.

**Step 2: Run test to verify it fails**
Not applicable.

**Step 3: Write minimal implementation**
Create `AGENTS.md` with:
- Repository scope and non-goals.
- Build commands: `python build.py`, `--dry-run`, `--clean`, `--specpath`.
- Single-test guidance: explicitly state no automated tests; provide minimal validation steps.
- Code style rules: 2-space indentation, camelCase variables, verb-led function names, clear error handling, avoid `any` and ignore pragmas.
- Reference to `pyinstaller_config.json` fields.

**Step 4: Run test to verify it passes**
Manual validation: ensure all required sections are present and accurate to `build.py`.

**Step 5: Commit**
Skipped (repository is not a Git repo).

### Task 2: Draft `README.md`

**Files:**
- Create: `README.md`

**Step 1: Write the failing test**
No automated test framework exists for documentation creation.

**Step 2: Run test to verify it fails**
Not applicable.

**Step 3: Write minimal implementation**
Create `README.md` with:
- 项目简介（1-2 段）
- 使用说明：
  - `python build.py` 与常用参数示例
  - `pyinstaller_config.json` 字段说明（`entry/name/onefile/console/icon/add_data/hidden_imports/excludes/collect_binaries/extra_args`）

**Step 4: Run test to verify it passes**
Manual validation: ensure examples match actual CLI options.

**Step 5: Commit**
Skipped (repository is not a Git repo).
