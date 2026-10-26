# Emo Master publication provenance

The legacy publisher's strict guards apply to `-Target emo-master` and
`-Target emo-master-runtime`. Other legacy targets keep their prior behavior.
The independent Runtime produces its own directory-based portable package and
current-user installer, with a separate AppId, directory and shortcuts. The
standalone application caller always requests a build-only artifact; central
Actions also treats Runtime `auto` as build-only. Publication requires explicit
`true` and the provenance checks below. Both local Runtime publishers default to
build-only too; publication additionally requires their explicit `-Publish` switch.
The Designer target retains its existing local defaults.

## Combined Designer and Runtime release

Use `release-emo-master.yml` to build both targets from one resolved source commit.
`publish_release` defaults to false. The workflow reads the version through the
shared AST reader, including `src/emo_master/app_version.py`, and pins both builds
to the same packager commit. Tags must still match the application version.

Both builds must succeed before publication. Each installer uses the existing
portable self-test, silent installation, installed self-test, uninstall and
user-data-preservation checks. Runtime also retains its extracted-archive and
native-cycle validation. No camera, PLC, real-model or field acceptance is implied.

Only six files are public: two installers, two ZIPs, Designer `manifest.json` and
`runtime-manifest.json`. Build-only target artifacts keep their original
`manifest.json` names for compatibility with source-owned validation scripts;
the combined release stages the Runtime manifest under its distinct public name.
Explicit standalone Runtime publication also defaults to `runtime-manifest.json`.

The combined publisher checks a new release and matching source/tag before build,
then rechecks immediately before creating a draft. It uploads without clobbering,
verifies the complete asset set against GitHub's sizes and SHA256 digests, and only
then makes the draft public. Failed uploads leave the draft for inspection; reruns
do not overwrite it. Logs, screenshots and private request state stay in Actions
artifacts rather than Release assets.

Release title, short `notes`, `previous_source_ref`, `changelog_all` and an optional
packager-local Markdown `release_body_path` follow the Vision Train workflow.
Automatic notes reuse `release_content.generateBody`, including update/fix groups,
download instructions, exact source comparison and the complete commit list.
Without an explicit range, the previous release manifest determines the base.

Cross-repository publication requires `RELEASE_REPO_TOKEN` with write access to
`jsdfhasuh/emo_master`. A caller running in that source repository can use its own
write-scoped `GITHUB_TOKEN`. Neither existing tags nor existing assets are moved
or replaced. Source callers must pin the reusable workflow and `packager_ref`.

- `-BuildOnly` continues to package local source without publication. It can use
  an already existing version such as `v0.6.1`, even when that remote tag points
  to different source. Generated download URLs do not imply publication.
- Publication requires `release_repo == source_repo`. Separate release
  repositories are deliberately unsupported: a tag in another repository
  cannot prove which application source produced the assets.
- Publication requires a clean source checkout, the same HEAD before and after
  building, and verification that the commit exists in the configured source
  repository. An explicit `SourceRef` must resolve to that HEAD.
- `-SkipBuild` cannot publish either Master target: the legacy dist directory has no
  independently verified source/build provenance. Rebuild or use `-BuildOnly`.
- Existing remote tags, including annotated tags, must resolve to the built
  source commit. Mismatches fail before build; tags are never moved.
- New releases specify the complete built commit with `gh release create
  --target`; preexisting matching tags also use `--verify-tag`.
- Existing asset names are rejected before any upload, and Master uploads never
  use `--clobber`. A concurrent conflicting upload also fails instead of replacing
  an asset. An existing asset requires a new version, not an overwrite override.
- Explicit `-NotesOnly` can update notes only when repository and source/tag
  provenance match. It does not replace assets.
- GitHub lookup errors fail closed. Release lookup is bounded to 1000 releases;
  an older release outside that window cannot be overwritten because create
  fails if the release already exists.

The GitHub API does not provide an atomic compare-and-publish operation for tags
and release assets. Checks run immediately before mutation, but repository
permissions must also prevent external actors moving tags during publication.
A multi-asset upload can partially succeed; on error, inspect it and use a new
version rather than replacing uploaded assets.

## Runtime build verification

The Runtime target config supplies `verification_script`. The publisher executes
that source-owned script against the newly built EXE before compression or any
publication. Failed frozen plugin, migration, CPU ONNX, spawn, project-package,
custom-page or stop/restart checks fail the build. This synthetic check is not
camera/PLC, real-model, long-duration, clean-OS or field acceptance.

Runtime ZIPs use `archive_compression=deflate` for Explorer/PowerShell extraction.
All other targets retain their existing compression policy and installer settings.

For Runtime, the cloud workflow records the actual source and packager commits in
`runtime-build.json`, retains source JUnit/build/process logs, verifies the manifest
and ZIP, then runs the extracted EXE and a 60-second, 10-restart native Qt synthetic
check. Artifact upload runs even after failure. Existing version strings are used
only for build-only filenames; this does not create a tag or a Release. The source
checkout supplies the Runtime-only validation scripts; other targets do not run
these checks.

## Safe focused verification

Run `python -m unittest discover -s tests -p test_master_release_provenance.py -v`.
When PowerShell is available this also runs the isolated fake-GitHub harness.
Alternatively on Windows run:

```powershell
powershell -NoProfile -NonInteractive -File tests/powershell/test_master_release_provenance.ps1
```

The harness parses the publisher and loads only function declarations. All Git
and GitHub calls are mocked; it never builds, creates tags, edits releases, or
uploads assets. It covers lightweight and annotated tags, mismatched/absent
tags, failed lookups, conflicting assets, separate repositories, stale build
reuse, dirty source, changed HEAD, and mismatched source refs.
