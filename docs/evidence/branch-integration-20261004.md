# Safe branch integration — 2026-10-04

## Scope and recovery points

This integration retains the complete histories of all six non-default remote branches.
The original master was `ab4a33e586138fb381a87ae21cc83b5e8d79adbe`.
All seven branches were unprotected and the repository had no rulesets at inventory time.
Before deleting a branch, compare its current remote tip with this table and verify that
that tip is an ancestor of the final remote master. Skip a branch that changed or became protected.

| Branch | Retained tip / restore point |
|---|---|
| `codex/kaggle-builder-resources` | `790e1bdc3e825dcc0a73acaef2cd3f53a98ddb83` |
| `docs/build-branding-plan-20260908` | `32ab479e8d574b9cf1380b016d11043c2439ac06` |
| `feat/visionworkshop-portable-branding` | `7b6a5f10b9130702b80a9667d41119d3a44a085c` |
| `release-test/published-update-retest-20261004` | `e75a880e94ddfe227f3e1a6607c5e0822e6e5ada` |
| `release-test/v1.0.28-startup-diagnostic-20261004` | `cea99accb77a07c0f5bc9a9ddf28b1f4599e27a9` |
| `release-test/v1.0.29-incremental-20261004` | `cc548366fc8e574ba3eb66398bf17dba9311a800` |

A branch can be restored by creating a new ref at its retained tip. The integration
merge parents keep every listed commit reachable after branch deletion. Never delete master.

## Conflict resolutions and retained behavior

- Retain portable branding, protocol-3 full/delta packaging, Kaggle frozen resources,
  planning documents, exact-byte test helpers, and all branch history.
- Restore the production `release-windows.yml` entry. Startup diagnostics and published
  asset retesting have distinct manual-only, read-only workflows.
- Remove test-release-only hardcoded v1.0.28 requirements from the normal production
  portable workflow. First releases, full-only releases and incremental releases retain
  their own baseline selection paths. Normal builds do not require historical test evidence.
- Retain the explicit opt-in Windows acceptance helper separately from advisory product,
  GPU and physical power-loss evidence. Report only the checks actually performed.
- Preserve the startup diagnostic's split-profile experiment explicitly. The newer shared
  helper now uses a coherent Windows profile; regression tests prevent the two diagnostic
  cases from silently becoming identical after integration.
- Push/PR CI runs tests and fixture compilation, never production publication.
- No application-source changes, release tags, release assets or deployments are part
  of this integration.

## Validation and limits

The integration PR records the exact commit and terminal CI results before master is
updated. Final branch deletion follows an exact-remote-master ancestry and tip recheck.
Local validation includes the complete unit/CLI suite, workflow safety regressions,
Python compilation and the ten immutable published-retest helper checks. CI covers
Linux/Windows unit tests, PowerShell parsing and the real Windows fixture build/launch.

Historical production Windows evidence: release run 37177242864 and read-only retest
37186007574 both succeeded for the pinned v1.0.28 → v1.0.29 transition. These are
historical evidence, not a newly built production release from this integration.
GPU/training, physical power loss, interactive task exit and two successive product
version upgrades are not certified by the fixture or historical retest.

Local pre-PR result: 357 unit/CLI tests ran successfully (355 passed, 2 Windows-only skips); all 10
published-retest helper tests passed in the dependency-ready test environment.
Python compileall and git diff --check passed. Independent review found and verified
the corrected profile-layout regression, production/diagnostic separation, public
acceptance-summary allowlist and reusable workflow permissions. Hosted Windows fixture
execution remains a required PR/master CI check, not a claimed local result.
