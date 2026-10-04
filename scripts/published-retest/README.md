# Exact published Windows updater retest

## Installation in an isolated test branch

Copy this directory to `scripts/published-retest/` in the isolated packager test branch. Also copy `published-update-retest.yml` to `.github/workflows/published-update-retest.yml`. Keep the workflow copy in the script directory for its safety unit test. Do not change the source branch, original release workflow, release tags, or release assets.

The workflow checks out:

- The test harness at `${{ github.sha }}`
- Packager baseline `cc548366fc8e574ba3eb66398bf17dba9311a800`
- Product source `014626e0dbbb8f7f90d08e9a2c9776606bc77025`

The published baseline and target are locked by release ID, complete asset inventory, asset ID, name, byte count and SHA-256, build identity, and source identity. No `latest` endpoint determines the target. Replacement or editing of either release's asset set fails closed.

## What is actually exercised

1. Public anonymous production release discovery and digest-bound baseline download
2. Real v1.0.28 product and copied frozen updater; a harness-created unknown user file causes `USER_FILES_UNCLASSIFIED`, with no durable plan, no full fallback, no changed user bytes, and no replaced baseline file identities
3. That session's verified downloaded delta is corrupted in-place without changing its length. A new real frozen session must reject it, fetch the exact public delta, install v1.0.29, receive protected `GUI_READY` and `RUN_ALLOWED`, and advance the registry's trusted next-session baseline
4. Read-only custom update configuration retains its content, file identity, and Windows read-only attribute. Unchanged immutable files retain identity, and the transaction's unchanged-copy count is zero
5. Two subsequent ordinary cold launches pass their startup guard, reach GUI construction, and remain alive 15 seconds. Normal startup does not emit the protected-update-only `GUI_READY`/`RUN_ALLOWED` signals, so these checks are intentionally described as cold-start smoke checks
6. A fresh independent v1.0.28 installation selects the actual published full package through the production no-baseline selection path, downloads it from an empty cache, updates through the real frozen updater, and confirms target startup with the same integrity/configuration checks
7. Portable tests additionally exercise a corrupted download followed by successful retry and permanently corrupt downloads failing closed

The full test is a full-package selection/application test. It does not certify the interactive dynamic fallback prompt. Repeated launch is not a second version upgrade. GPU/training workloads, real user task draining, and physical power-loss recovery are not tested here.

## Isolation and evidence

The harness requires Windows and a previously nonexistent work directory, checks both immutable checkouts, extracts only SHA-verified public ZIPs, and uses fresh user-profile/AppData directories. Frozen children receive no token/password/secret environment variables, and only processes whose executable is under the isolated install are stopped. There are no build or publication calls and workflow permission is `contents: read`.

The sole uploaded artifact is `retest-report.json`. It contains allowlisted status values, hashes, stage names and counts. Do not upload the work directory, raw session/request/status/launch records, raw logs, or private profiles: they contain session authorization material. Errors in the summary intentionally omit raw exception messages and tracebacks.

Timeouts: 60 minutes for the job and 52 for actual retesting. Individual frozen sessions allow up to 20 minutes for full download, preparation, application, and launch. A delta-case failure still permits the independent full case to run. A failure anywhere keeps the aggregate result failed.

## Local checks (not Windows acceptance)

From the audit workspace:

    RETEST_SOURCE_ROOT="$PWD/source" venv/bin/python -m unittest discover -s harness/retest -p test_retest_helpers.py -v
    python -m py_compile harness/retest/retest_published_windows.py harness/retest/test_retest_helpers.py

The ten portable checks validate lock rejection, helper integrity/importability, read-only workflow safeguards, report redaction, cache repair, transfer retries, and fail-closed permanent corruption. A green portable result does not mean the Windows EXEs ran.
