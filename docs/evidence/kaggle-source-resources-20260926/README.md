# Kaggle builder source resources

Base: `7b6a5f10b9130702b80a9667d41119d3a44a085c`; isolated branch `codex/kaggle-builder-resources`. Original packager checkout was clean and remains unchanged. Application source is the existing `feat/kaggle-job-build-foundation` checkout; no application/submodule changes were made from this repository.

The release base config now collects eight missing Python source data files read by the frozen builder: job_builder, build_errors, runtime_builder, runtime_bootstrap, and the four runtime modules. Existing template and anomaly support mappings remain. Hidden imports cannot substitute these data files. Package validation also requires all 13 source/template/support files under `_internal`; an importable PYZ module alone no longer satisfies this check. This is a resource check, not full frozen EXE acceptance.

`effective-config.json` was produced by the actual `scripts/resolve_build_config.py` with `SOURCE_ROOT=D:/training_platform-kaggle-foundation`, `--branding-profile profiles/visionworkshop.json --program-name VisionWorkshop --release-tag v0.0.0-local`; exit 0. All 13 mapped source files exist and map exactly to the builder's read paths; their hashes are in `verification.json`. Tests additionally resolve the base alone and profile plus explicit overrides. No release tag was created or published.

Interpreter: existing `C:/Users/jsdfhasuh/.conda/envs/emo-vision-train/python.exe`.

- `-m unittest discover -s tests -p test_kaggle_source_resources.py -v`: 1 PASS, exit 0.
- `-m unittest discover -s tests -p test_vision_train_runtime.py -v`: 18 PASS, exit 0, including missing source data despite available modules.
- `-m unittest discover -s tests -v`: 335 cases, 1 skipped and 1 failure, exit 1. The sole failure was the intentionally pinned config digest after the authorized eight add_data additions; updated only that target's pin after reviewing the config diff.
- `-m unittest discover -s tests -p test_build_baseline.py -v` after pin update: 8 PASS, exit 0. No unresolved failure; the entire slow suite was not repeated after this expected-value-only correction.
- `build.py --config configs/emo-vision-train.json --dry-run`: exit 1, missing source worktree `ultralytics/ultralytics` submodule. This is recorded as RESOURCE_MISSING; no submodule initialization or dependency installation was attempted.
- Full frozen product build/EXE acceptance: NOT_RUN. No package published. The application V4 revision requires that acceptance before any new package publication, independently of continued development.

Normal runtime hooks, dependency versions, updater protocol and other target configs are unchanged. Logs from the full offline unit suite are in `unit-tests.zip`; fixtures and mocked compilers do not establish frozen product success.
