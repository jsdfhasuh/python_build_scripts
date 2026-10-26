# Emo Master v0.6.2 dual-product release

Date: 2026-10-26, Asia/Shanghai. Published at 18:03:22.

## Published identity

- Release: https://github.com/jsdfhasuh/emo_master/releases/tag/v0.6.2
- Release ID: `424086414`; public, non-prerelease, confirmed as latest.
- Source: `da072110c227ab8043c7bf8955101baba246af56` on
  `agent/runtime-workflow-architecture-v1`.
- Product build packager: `3ef28d7f581dfff09fc900ba64df34b275cc1dcd`.
- Build and publication run:
  https://github.com/jsdfhasuh/python_build_scripts/actions/runs/40302779051
- Source tag `v0.6.2` resolves to the exact built source commit. The previous
  annotated `v0.6.1` tag still resolves to `e1ab52b365ccba2a0347a9354af20e92176bc6f1`.

## Delivered changes

- Runtime now has a current-user Inno Setup installer, with a separate AppId,
  install directory, Start menu and uninstall entry from Designer.
- Both portable ZIPs use Deflate for Explorer/PowerShell extraction.
- Runtime's explicit publication switch reaches the legacy publisher rather than
  the unrelated Vision Train branding path.
- The combined workflow resolves and pins both checkouts, builds both products
  without individual publication, verifies their public files, uploads to a new
  draft without clobbering, verifies GitHub asset digests and only then publishes.
- Public manifests are `manifest.json` and `runtime-manifest.json`; build-only
  artifacts retain the old manifest name for source verifier compatibility.
- Release notes reuse the Vision Train generator and its title, short notes,
  update/fix groups, download section, exact comparison and full commit history.
- The version migration is included: `src/emo_master/app_version.py` defines
  `APP_VERSION = "0.6.2"`; the package export and package metadata read that value.
  Only migration/release files were committed in the source repository. Unrelated
  local functional changes were preserved and are not part of this release.

## Public assets

| File | Bytes | SHA256 |
| --- | ---: | --- |
| emo-master-setup-v0.6.2.exe | 80282960 | 0f23aa90c324567757ac062e250dd163d8aae8a3e3d3e231e043afef497f11f0 |
| emo-master-runtime-setup-v0.6.2.exe | 79393976 | b055557b06fe0752ad1f7822f75684971c90307ddcf76cebc90f5e619cb9c676 |
| emo-master-windows-v0.6.2.zip | 125135868 | 599c455678a248595c2c6efaf839e01f0b96096a6cba169faff99031f3bca59c |
| emo-master-runtime-windows-v0.6.2.zip | 125138928 | 1d5f87d9031b6803a5a7c88e3ff9c2b166539c63c54a26935dd88d5717e960ee |
| manifest.json | 1250 | d21776216dfa6b76aa29c9dc7328e10dceda4a692b85b08ab5dcd47e2db99d05 |
| runtime-manifest.json | 1290 | 6cbc362d0bd14d6f10f9c67fe662950102e6a3744a8be55726e6faa30865fd56 |

## Verified

- Final local packager suite: 416 tests, 415 passed, one directory-symlink skip,
  373.800 seconds. A separate isolated Python 3.10 test environment was used.
- Local real Windows portable fixture compilation, extraction, icon and launch
  checks: passed. This fixture is not either application product.
- Clean detached source checkout: 20 tests and two subtests passed in 48.65 seconds.
- Cloud Runtime source regression: 122 passed in 105.43 seconds.
- Both actual product builds passed portable self-test, installer compilation,
  silent installation, installed self-test, uninstall and user-data-marker checks.
- Runtime's frozen pre-compression check, extracted archive check and native Qt
  60-second / 10-restart synthetic check passed.
- Designer's extracted-package custom-icon check passed before publication.
- Release assembly verified both manifests, source identity, portable/installer
  names, URLs and SHA256, plus Runtime archive/native evidence.
- After publication, both public manifests were downloaded and checked against
  GitHub asset digests. Their source, version, asset URLs and SHA256 match the
  six public assets. The release body matches the prepared fingerprint:
  `475399e15d9916b8cdd4469713d4eced1a7c565f939a51a721fd661ebd767b45`.
- Final Windows and Ubuntu packager CI is green:
  https://github.com/jsdfhasuh/python_build_scripts/actions/runs/40303306789

## Earlier failures retained

- After the initial passing 416-test run, Designer compression was deliberately
  changed to Deflate to preserve its PowerShell extracted-icon check. The fixed
  JSON fingerprint in `test_build_baseline.py` was initially not updated.
- Both platforms in run `40302475292` failed only that configuration fingerprint
  assertion. The failure log is retained locally as
  `artifacts/master-packager-ci-40302475292-failed.log`.
- Test-only commit `7d6c55fcf58f659fd4e8081ea25eca715a181e33` updates the expected
  digest while preserving the full equality assertion. Its only difference from
  the product build packager is that test baseline; product build code/configs
  are unchanged. Local full-suite and cloud CI reruns passed.
- The first local clean-worktree checkout failed on Windows long paths. Retrying
  with command-local `git -c core.longpaths=true` succeeded. The clean source
  tests then passed and that temporary checkout was removed. This was not a
  product build failure and no application working-tree changes were discarded.

## Evidence and boundaries

Local raw outputs remain under `artifacts/`: `master-release-unit-tests.log`,
`master-release-unit-tests-final.log`, `master-source-clean-tests.log`,
`master-release-windows-fixture.log`, `windows-portable-acceptance.json`,
`master-designer-build.log`, `master-runtime-build.log`, `master-release-publish.log`,
`emo-master-v0.6.2-release.json`, `master-release-request-v0.6.2/` and
`master-release-public-manifests/`. Product logs and reports also remain in the
linked Actions run; they are not public Release assets.

Not run: full application pytest suite in this task, manual product GUI acceptance,
real camera/PLC/hardware tests, field-model accuracy, long-duration operation,
clean consumer-Windows installation acceptance and update-transition acceptance.
Synthetic and fixture results must not be reported as those checks passing.
