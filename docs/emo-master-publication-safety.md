# Emo Master publication provenance

The legacy publisher's strict guards apply only to `-Target emo-master`.
Other legacy targets keep their prior behavior.

- `-BuildOnly` continues to package local source without publication. It can use
  an already existing version such as `v0.6.1`, even when that remote tag points
  to different source. Generated download URLs do not imply publication.
- Publication requires `release_repo == source_repo`. Separate release
  repositories are deliberately unsupported: a tag in another repository
  cannot prove which application source produced the assets.
- Publication requires a clean source checkout, the same HEAD before and after
  building, and verification that the commit exists in the configured source
  repository. An explicit `SourceRef` must resolve to that HEAD.
- `-SkipBuild` cannot publish Emo Master: the legacy dist directory has no
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
