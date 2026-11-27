# VisionWorkshop protocol-4 modular candidate

This opt-in builder creates a real product Core and independent offline module
ZIPs. It does not change the protocol-3 portable publisher, other target configs,
or create a Release. Actual sizes come from verified Windows build artifacts;
product behavior requires the separate real EXE matrix to pass.

## Prerequisite and scope

The separate [B2 loader evidence](evidence/visionworkshop-modular-loader.md)
records actual Windows EXE CPU loading, native operations, metadata, Chinese and
space paths, process restarts and a single Core Python interpreter. B2 does not
qualify the product GUI, offline installer or GPU execution. The product workflow
uses the same pinned CPython 3.12.10 and the same reviewed CUDA-enabled Torch
2.10.0 / TorchVision 0.25.0 preparation baseline. It does not manufacture a CPU
distribution by removing CUDA libraries.

## Ownership and layout

The frozen EXE contains the standard-library launcher and embedded `core.json`.
First-party adapters remain regular source under `VisionWorkshop/python`; light
desktop dependencies stay under `VisionWorkshop/site-packages`. Optional
third-party packages are copied as whole top-level packages, including their
metadata and native files. No optional module includes its own interpreter.
The existing VisionWorkshop branding profile supplies the same validated icon
to the EXE and Core's runtime branding files, without editing the app checkout.

| Owner | Contents |
| --- | --- |
| Core | First-party application/adapters, AnyLabeling, Qt/WebEngine, NumPy, OpenCV, Pillow, client and annotation dependency closure |
| `runtime.torch` | One shared Torch, TorchVision and TorchAudio set with the actual matching CUDA libraries |
| `runtime.ort` | ONNX, ONNX Runtime GPU distribution and ONNX simplification closure; its CPU path does not require the Torch module |
| `runtime.science` | Shared SciPy and Matplotlib closure |
| `runtime.vision` | Shared timm, Transformers, tokenizers, Hugging Face Hub and safetensors closure |
| `feature.yolo` | Pinned full Ultralytics source, its original requirements, and YOLO-specific dependencies |
| `feature.patchcore` | Anomalib, Lightning and PatchCore-specific dependencies |
| Five `resource.*` modules | YOLO, CNN PatchCore, image simplification, EdgeSAM, and the distinct PatchCore DINO Small resources |

`ci/visionworkshop-modular.json` declares direct seeds and resource ownership.
The final dependency closure comes from the actual installed `Requires-Dist`
metadata, using Windows CPython 3.12 markers. Shared light dependencies receive a
single Core owner; explicit shared heavy seeds retain their declared owner.
The builder rejects missing dependencies, unpinned versions, split namespaces,
unassigned model files and cross-owner native DLL conflicts. The application
`module_contract.py` is the single schema and compatibility validator.

Each module ZIP contains only `module.json` and files below
`payload/{site-packages,resources,native,licenses}/`. Manifest file paths are
relative to `payload`, and ZIP directory entries or extra files are not emitted.
The application installs an immutable version at
`VisionWorkshop/modules/<module-id>/<manifest-sha256>/payload`. The Core ZIP has
the `VisionWorkshop/` prefix and one `VisionWorkshop.exe` entry point.

## Independent module index

The builder writes `archives/module-index.json` only after all Core and module
ZIPs have completed their existing whole-archive and per-file verification.
This separate canonical JSON index contains no temporary download URL or
artifact ID that is unknown at build time. Its safe archive basenames identify
the files to prepare for offline use; each entry includes the actual compressed
byte count, SHA-256, file count and expanded size.

The header binds the current Core's application SHA, builder SHA, build ID,
Python version/ABI/platform and dependency-lock SHA. The Core entry binds its
version, exact `core.json` SHA and complete ZIP identity. Each module entry
retains its actual original manifest SHA and build identity, including when an
older compatible ZIP is reused, together with its ID, label, kind, version,
Core version range, dependencies, package versions, import roots and resources.
The original module ZIP and metadata are never rewritten to match a newer Core.

Construction requires exactly the complete Core catalog, unique module IDs and
Windows-safe unique asset basenames. It rechecks each ZIP's size/SHA, canonical
metadata and declared member inventory, then applies the application's existing
Core/module/combined compatibility validators. Per-payload-file hashing remains
the prior `compressPackage`/`reuseArchive` verification; this new index check does
not relabel its own work as another native or per-file execution test.

The index uses the shared contract's canonical JSON format and metadata byte
limit. Its own size/SHA is stored in `modular-build-summary.json`; the index is
outside all ZIPs and never includes its own hash, avoiding a self-reference.
The product driver binds and verifies it against the current Core and complete
actual module ZIP set before starting any product process, and writes
`module-index-verification.json`. A separate small Actions artifact delivers the
index, with a byte-identical copy in the evidence artifact.

The 12 focused source tests use real small LZMA ZIPs and cover new Core/original
module builds, independent asset corruption, missing/duplicate modules,
ABI/lock/Core-range/dependency conflicts, source-build substitution, unsafe or
colliding asset paths, canonical/size/type boundaries and false qualification
claims. The source-only implementation checkpoint is retained in the test report
below; actual Windows run `45659615499` subsequently generated this index and its
product driver verified it before invoking the EXE. Build/native/Release
qualifications remain distinct;
the index records `NOT_QUALIFIED` for Release and points native execution to its
separate report.
The complete focused source check was 69 tests, zero failures/errors/skips;
input hashes and the exact 12/10/35/12 group counts are recorded in
`docs/evidence/visionworkshop-modular-index-source-tests.json`.

That actual index is 14,561 bytes, SHA-256
`dd97cbd92475136c4263a0c9677aa44c98958b601c71a9bc1041c0f471008aab`,
delivered independently as artifact `15044844880`. It binds the new Core and all
eleven byte-preserved original module ZIPs with their original build identities.
Its successful construction and consumption do not override that run's failed
Core process exit described below.

## Input and bootstrap integrity

The build requires exact clean application, vendor and builder commits. Model
preparation writes to a separate resource staging directory, so downloading the
reviewed weights never changes the source checkout. Each weight loader verifies
its established size and digest. Actual resource bytes receive their own
manifest entries even when their source location is ignored by Git.

Core also carries the real Noto Sans CJK SC Regular font and its unchanged SIL
OFL license, prepared from official `notofonts/noto-cjk` commit
`523d033d6cb47f4a80c58a35753646f5c3608a78`. The immutable URL, exact size, Git
blob ID and SHA-256 are fixed in the profile and verified before staging. The
font SHA-256 is `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`;
the license SHA-256 is `6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2`.
Both enter the Core runtime inventory. The application prepares byte-identical
user-cache aliases before activating YOLO, so its font lookup does not need an
online download or a write into the immutable Core.

Installation reports bind distribution versions to downloaded archive URLs and
SHA-256 values. The selected distribution RECORD verifies its installed payload.
Pip's Windows path aliases and preparation-only scripts are handled explicitly;
the evidence retains the installed RECORD and report hashes. Those installation
receipt hashes are excluded from the compatibility lock because they can vary
without changing dependency inputs. Core-only source, branding labels and the
Core AnyLabeling commit are likewise recorded in build evidence rather than
invalidating every optional module's dependency lock.

The OpenCV and ORT alternate distribution names use explicit namespace
providers. If alias metadata remains installed, its version must equal the
selected actual provider version. Only the provider supplies importable payload;
original metadata is preserved and the substitution is recorded.

The only reviewed standard-library-name compatibility provider is Windows
`readline.py` from `pyreadline3==3.5.4`, owned by `runtime.ort` for humanfriendly's
Windows dependency. The application contract fixes its wheel hash, file hash,
size and unique owner. The builder preserves the original payload/RECORD and
requires a separate `-I -S` compiler process to prove that this Windows Python
has no native `readline` implementation. Other standard-library overrides and
alternate readline directories or native extensions remain rejected.

The stdlib launcher compares on-disk Core metadata with its exact embedded bytes
before importing application code. It verifies the complete external Core
`runtime_files` inventory (first-party files, third-party Python/PYD/DLL files,
metadata and Qt helper programs), rejects additional files in those owned
directories, checks the dependency lock, then preloads the fixed Core CRT
in dependency order. Metadata is serialized with the application's canonical
encoder and must fit its shared 32 MiB limit; oversized documents fail the build.
The frozen `_internal` files and EXE are separately tied to the compiler source
audit and final archive hashes, avoiding an EXE self-hash cycle.
After freezing, the builder also checks the complete Core DLL inventory,
including `_internal`, against every module owner before creating any ZIP.

The product candidate uses the official Microsoft 14.52.37029.0 base CRT family,
whose toolset is newer than the selected sklearn 14.51 binaries. The separate
historical B2 probe keeps its original CRT recipe. The product preparation
verifies a fixed Microsoft archive URL/hash, slices the pinned CAB container,
and uses Windows `expand.exe` for its two layers; it never executes the
redistributable installer. All twelve source DLL identities and the original
license document are retained in provenance. Core selects nine base runtime
DLLs and leaves sklearn's OpenMP runtime with that feature. The two VCRUNTIME
DLLs enter PyInstaller's Analysis before EXE/COLLECT, with original and replacement
source evidence, and their final `_internal` bytes must match. Qt and sklearn
retain their original private MSVCP copies because vendor loaders use those
paths. The shared contract allows only the exact reviewed Core/feature paths,
sizes and hashes with the fixed Core preload; it does not permit general
cross-owner DLL collisions. Static import coverage is followed by actual product
native operations and K32 loaded-file checks, and is not itself runtime qualification.

Only the already audited TorchVision wheel's exact redundant `python312.dll` is
omitted. Its wheel origin, file size, digest and ABI evidence are recorded by the
reused B2 validator. Every other Python executable or DLL in optional payloads is
rejected. Actual product checks additionally inspect loaded Python and compute
DLL paths and hashes.

## Ultralytics 8.4.9 / Torch 2.10 metadata compatibility

The previous application vendor pin `74b2b91e5c4420af47875801b8e13333ab7026ac`
declared `torch>=1.8.0,<2.10`, which conflicted with the selected Torch 2.10.0
runtime. Application PR #5 updates the fixed Ultralytics source to official
v8.4.9 commit
`a8b639bc35aa3d43efdde6691e5706a5525d8db6`. Its original
[pyproject.toml](https://github.com/ultralytics/ultralytics/blob/a8b639bc35aa3d43efdde6691e5706a5525d8db6/pyproject.toml#L71-L72)
declares `torch>=1.8.0` and the Windows-specific
`torch>=1.8.0,!=2.4.0; sys_platform == 'win32'`; it no longer declares the
global `<2.10` upper bound. The vendor source and its declared requirements are
kept intact rather than patched locally.

The latest application candidate (PR #5 head
`3508a6911e0e12873e85bb06fac89ebb53a9c3e2`) adds a runtime metadata check that
reads the installed Ultralytics distribution's actual `Requires-Dist` entries,
evaluates active PEP 508 platform markers, checks the installed Torch version
against every active Torch requirement, and records the exact requirements and
violations in the product report. Its source tests accept
`2.10.0+cu128` with the Windows `!=2.4.0` exclusion and reject the old
`torch<2.10` constraint.

The latest builder candidate (PR #6 head
`27489026136701649c694084c6d76f9fc409a14e`) requires the YOLO product report to
show `metadata_compatibility.status == PASS`, exact Ultralytics/Torch versions
matching the Core catalog, non-empty active requirements and an empty violation
list. This is a report-level check of the actual installed distribution
metadata; it does not claim that all business models or GPU inference are
qualified.

The in-flight candidate run `45949863344` was started from earlier builder
`5e878559` and application `964b1be`. It uses the v8.4.9 source pin, but those
earlier app/builder commits do not yet include the new runtime metadata report
and product assertion. Its module ZIPs may be reused only if the completed run
actually uploads all 11 archives and the strict source-run, manifest, dependency
lock, catalog, RECORD and payload checks pass. The next Core candidate must use
the exact app head `3508a691` and current builder branch, then execute the
metadata-aware product check. If the in-flight run is cancelled by its old
150-minute job limit before artifact upload, its in-memory module outputs are
not reusable and the corrected 210-minute workflow must perform a full build.

The bounded CPU YOLO fixture covers training, prediction, ONNX export and reload
parity. It is not business-model qualification, T1000 GPU inference, a full
production training qualification, or physical power-loss recovery evidence.

## Build commands

The independent workflow is
`.github/workflows/visionworkshop-modular-candidate.yml`. It pins an exact app
commit, checks out both fixed vendors and LFS resources, and creates separate
compiler and dependency preparation environments. Start it by workflow dispatch,
or by changing the explicit three-field request in
`ci/visionworkshop-modular-candidate.json` on the candidate branch. Ordinary code
and documentation pushes do not start another heavy candidate; the independent
portable regression still runs on pushes. The request file binds an exact app
commit and an optional source run/attempt. Dispatch uses its own inputs and leaves
reuse disabled by default. The CLI steps are:

```powershell
python scripts/build_vision_train_modular.py prepare --output modular-input
python scripts/build_vision_train_modular.py crt --source-root <exact-source> `
  --output <prepared-official-crt>
python scripts/build_vision_train_modular.py assets `
  --source-root <exact-source> --assets-root <isolated-resource-staging> `
  --output <reports/resource-preparation.json>
python scripts/build_vision_train_modular.py build `
  --source-root <exact-source> --assets-root <isolated-resource-staging> `
  --output <new-candidate-directory> `
  --build-python <compiler-python.exe> --runtime-python <preparation-python.exe> `
  --install-report <runtime-install.json> --install-report <provider-install.json> `
  --torch-install-report <runtime-install.json> --crt-root <prepared-official-crt>
python scripts/verify_vision_train_modular_product.py `
  --build-summary <new-candidate-directory/reports/modular-build-summary.json> `
  --output <new-acceptance-directory> --pt-timeout 1200
```

The workflow contains the exact environment installation commands. It saves pip
downloads before construction, and records the provenance of reused inputs.
`build` requires Windows, fresh output paths and the reviewed separate environments.
No operation publishes anything.

### Optional byte-preserving module ZIP reuse

A Core-only source fix can reuse a completed candidate's module archives by
explicitly supplying `reuse_run_id` and `reuse_run_attempt`, but only when the
dependency lock, catalog, manifests and payloads remain compatible.

The earlier request using app `591f8bef7b2292caf50f4848e3047518e490742c` and
module ZIPs from run `45616400076`, attempt 1, is historical. That source used
the pre-v8.4.9 dependency identity and is not eligible for the current Torch
2.10 / Ultralytics 8.4.9 candidate. Its build was `BUILT` but its first EXE CLI
check failed; that failure remains historical evidence and is not transferred
into a new candidate.

Current request (2026-11-27) uses app `964b1be` and an empty
`reuse_run_id`, so the 11 modules are built fresh. Run `45949863344` has
completed the Core/module build step and is still in product acceptance; no
artifacts have yet been uploaded. If it completes and all 11 module ZIPs pass
strict source-run, manifest, dependency-lock, catalog, RECORD and payload
validation, the next Core-only candidate may reuse those ZIPs with app head
`4b3f7fc`. If the run times out before upload or any artifact is missing or
invalid, the next candidate must build all modules with the updated 210-minute
early-upload workflow.

The scoped Actions read token is available only to the downloader. It requires
the exact completed run/attempt, source commit, unique nonexpired artifact names
and API SHA-256 digests. It verifies each outer artifact, original inner ZIP and
source build report. Evidence is bounded at 128 MiB; each inner ZIP must be a
positive integer size no larger than 2 GiB minus one byte before its artifact is
downloaded. Module outer artifacts have a further fixed 1 MiB container allowance.
An earlier attempt of a subsequently rerun source is deliberately refused.

Construction still reproduces the complete new dependency/model staging. It
retains this fresh staging and its own manifest separately from an immutable
source-module staging extracted from the verified original ZIP. Version, schema,
ABI, dependency lock, catalog ownership and Core compatibility range must agree.
Every non-RECORD payload path, size and SHA-256 must match the fresh staging.

Installed `*.dist-info/RECORD` files can describe preparation-only entry EXEs that
are not distributed. [Pip 25.0.1's launcher generator](https://github.com/pypa/pip/blob/25.0.1/src/pip/_vendor/distlib/scripts.py)
appends a ZIP containing `__main__.py`; when no fixed epoch is supplied,
[CPython 3.12.10's ZIP writer](https://github.com/python/cpython/blob/v3.12.10/Lib/zipfile/__init__.py)
uses the current time for that member. This appended ZIP timestamp can change
the generated EXE receipt hash between otherwise identical installations; it
does not describe a PE compilation timestamp. Qualification still requires the actual original and fresh
raw CSV bytes. Both reports must identify the same wheel URL/version/SHA, the
same installed metadata and retained runtime rows, and the same excluded-file
list. Changed rows must already exist in both lists, have exactly the same
`../../Scripts/<name>.exe` path, positive size, row order and CSV formatting, and
differ only in their SHA-256 field. No `.pyc` or other receipt differences are
allowed. Original/fresh RECORD size and SHA are tied to their own inventories;
both raw files are saved as evidence before the row qualification. A different
payload, unproven receipt or size mismatch fails without rewriting anything.

The final strict ZIP verifier still compares every original byte against the
separately selected source staging, including the original RECORDs. All members
must be unique regular LZMA files within the declared size budget; source build
identity, manifest bytes, complete member inventory and archive SHA are checked.
The copied output ZIP and manifest retain their original identities. Fresh
installation files and manifests are never overwritten with older receipts,
and the report distinguishes receipt differences from byte-identical payloads.

`module-reuse-validation.json` and the build/product summaries record the source
run, artifact and original module build separately from the new Core build.
Core is always frozen, compressed and verified again, and the full real EXE
matrix runs again. This optimization does not implement an installed Core
upgrade or registry migration. The default CLI remains a full construction when
`--reuse-root` is absent.

## Candidate acceptance and reports

The Windows workflow first runs the shared module contract and actual Windows
ZIP/transaction/lease and cold-repair tests, plus the legacy fixed-worker
run-permission tests and annotation diagnostic guards.
After preparing the runtime dependencies, a separate interpreter probe creates
a real `QApplication` with the native `windows` platform. It records the default
font and available families, actual fallback glyph indexes, and ASCII/Chinese
`QPainter.drawText` pixels on a `QImage` compared with a blank baseline. PNGs and
process/report identities are saved before downloading reuse assets or freezing
Core. Empty
rendering or unsupported ASCII fails; visible Chinese missing-glyph boxes are
explicitly `UNSUPPORTED`, with the probe marked `LIMITED`, not Chinese visual
acceptance. No system font or product UI is changed by the probe.

The probe also binds each fresh invocation to a nonce, selected `pyvenv.cfg`
bytes and the observed native process/parent images, commands and PIDs. Windows
CPython virtual environments use a redirector: the selected venv executable may
launch the base interpreter while `sys.executable` still names the venv. The
check accepts only the exact direct process, or the driver, selected venv
launcher and its one base-Python child, with matching script/output/nonce and
interpreter prefix/base paths. Different PIDs alone never waive this check.

Only this probe and the actual product acceptance use `QT_QPA_PLATFORM=windows`.
The product driver overrides the shared clean environment's `offscreen` value
and records the requested platform; the app independently checks the actual Qt
platform. Source tests and the original B2 probe retain `offscreen`. The early
interpreter result does not replace inspection of the actual frozen product's
screenshots.

It then builds the windowed product EXE and round-trips every LZMA ZIP, checking
the actual compressed per-file size against the shared download limit.

The acceptance driver runs that EXE from a Chinese and space-containing install
path with isolated user directories and an empty current directory. It checks:

- A separate detached windowed CLI invocation with null standard handles and
  without `--output`: its new
  `%LOCALAPPDATA%/VisionWorkshop/offline-modules/last-result.json` must contain the
  initial empty selection and identify that result file. The driver waits for
  the actual process handle and copies the exact JSON into acceptance evidence.
- Core-only startup, Qt and native operations with optional packages absent.
- A separate Core-only annotation process: a real rectangle is saved with the
  window's Save action, reread and reopened, then closed through the existing
  shutdown barrier. The fixture's files are outside Core and Core must remain
  unchanged. This does not qualify every annotation workflow.
- A real GUI process's lifetime lease: ZIP installation may prepare a pending
  selection, but activation while that process is alive must return `LOCK_BUSY`.
- ORT CPU and the fixed DINO native fixture with no Torch module installed.
- Separate DINO worker lifecycle processes in both the ORT-only and full-module
  combinations, each with a ten-minute limit: the real CPU inspector and two
  real session children exercise a missing deployment and cancellation. The
  helper checks child cleanup and inherited module identity. Successful model
  loading, prediction/numerics and full worker import auditing remain `NOT_RUN`.
- With all modules active, a separate 360-second CPU DataLoader diagnostic uses
  one spawned worker, the same product EXE and verified runtime snapshot, then
  checks normal child cleanup. This controlled data-loading case does not
  qualify every training pipeline, GPU operation or cancellation behavior.
- Cold repair through the real EXE: deliberately corrupt one registered small
  ORT file in the disposable installation, require `status` to report `broken`
  and ordinary same-version installation to return `MODULE_REPAIR_REQUIRED`,
  then restore the exact original ZIP with `repair`. The complete manifest and
  every payload hash must recover without changing generation or active
  identity, and a new EXE process must execute the ORT native fixture afterward.
- Cold removal and a fresh Core-only process, then complete offline installation.
- EdgeSAM's actual encoder and decoder from its separate resource ZIP with only
  ORT installed, explicitly selecting CPU and keeping Torch absent. Both modules
  are then removed before the fresh Core-only check.
- A separate resource-version transaction: derive a diagnostic second EdgeSAM
  manifest with one explicit marker, keeping every original weight unchanged.
  Real EXE install/activate must preserve Core, ORT and the prior EdgeSAM version,
  create a distinct verified version directory and advance the registry
  generation. Cold rollback restores the original selection; a new EXE then
  performs the original EdgeSAM CPU computation. The diagnostic ZIP is excluded
  from downloadable module artifacts and does not qualify changed model weights.
- Actual loading and CPU execution of the image-simplification, CNN pretrained
  and DINO pretrained resources using the production loaders and registered
  weights, with separate time limits and weight/manifest provenance reports.
- All four registered YOLO preset weights, each with actual CPU forward and
  prediction, retained payload identity and isolated verified font-cache sources.
- Actual Torch, ORT, DINO, YOLO and native PT fixture entry points using the same
  EXE and exact Core/generation/module identities.
- Actual sklearn DBSCAN native computation with the retained vendor DLLs and
  the selected Core CRT, followed by loaded-library path/hash checks.
- A cold rollback followed by another fresh Core-only process.

Reports bind executable SHA, process ID, runtime generation, manifest hashes,
observed origins, network attempts and child-process logs. The PT case has a
20-minute limit; timeouts terminate the process tree and fail with saved logs.
The GUI lease observation deliberately terminates a disposable GUI process after
the observation and is not evidence of graceful user-driven shutdown.
The Python socket/DNS audit is an application-level offline check; it does not
claim a physically disconnected machine or whole-system network capture.
The DINO runtime case covers environment inspection and a small native ORT
graph. Its separate worker case adds the real CPU inspector and bounded
negative/cancelled session lifecycle. Neither that lifecycle fixture nor the
pretrained-resource/PT cases qualifies successful DINO ONNX model sessions or
prediction/numerics. Full child-process import auditing also remains `NOT_RUN`.
The driver records a complete initial Core inventory, including EXE and
`_internal`, and compares it after pending installation, activation, repair,
removal, complete native/worker execution and rollback. Only the explicit root
`modules` and `.module-state` stores are excluded. The deliberately corrupted
file and its before/after digests are retained in the repair evidence.

The workflow uploads evidence, Core and each of the eleven optional module ZIPs
as fourteen separate reviewable Actions artifacts, including the independent
module index. Reports and selected offline
modules can be downloaded independently. Existing ZIPs are uploaded with outer
compression disabled.
A successful bounded CPU matrix is `LIMITED`; GPU hardware execution, existing
business-model qualification, Core upgrades and power-loss recovery require
separate evidence. Every unrun check remains explicit. Archive sizes are taken
from these actual artifacts, never from the earlier arithmetic size remainder.
This builder does not implement a Core-upgrade transaction or migration of an
installed registry to a new Core identity. A stable dependency lock makes old
module manifests compatible where declared; it does not itself perform that
registry migration.

## Actual ZIP build and first product process

[Run 45616400076](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45616400076)
at builder `f9703a9c6a0c0370a10eed0afadd39e677770547`, app
`c8c0fbe98a055620ddc5488be6835cf216b4800e`, completed the actual Core freeze,
official CRT source checks and all twelve ZIP/LZMA round-trip checks in 3,964.5
seconds. Every ZIP is below the individual 2 GiB minus one byte limit.

| Original candidate ZIP | Compressed bytes |
| --- | ---: |
| Core | 180,416,446 |
| `runtime.torch` | 1,865,186,577 |
| `runtime.ort` | 113,428,219 |
| `runtime.science` | 35,208,316 |
| `runtime.vision` | 14,281,587 |
| `feature.yolo` | 28,828,485 |
| `feature.patchcore` | 76,634,413 |
| `resource.yolo` | 32,296,740 |
| `resource.patchcore-cnn` | 248,193,522 |
| `resource.image-simplification` | 80,567,081 |
| `resource.edgesam` | 35,560,937 |
| `resource.patchcore-dino` | 80,604,327 |
| **All archives together** | **2,791,206,650** |

The 180.42 MB Core is a real artifact, not the earlier arithmetic remainder.
Installing every optional module still requires the complete 2.79 GB compressed
set. These sizes do not establish that the product is usable: the first EXE
`--offline-modules status --output ...` wrote an `ok: true` empty-selection JSON,
then failed while also printing Chinese JSON to its actual cp1252 stdout.
`UnicodeEncodeError` caused exit 1 before any native/GUI/module-lifecycle case.
The product summary remains `FAIL`, with zero completed cases or Core-unchanged
checkpoints. The prepared-font Pillow check passed separately in the Windows
preparation Python; it is not an EXE font-path result.

All thirteen artifacts were uploaded independently. Evidence artifact
`15028274168` is 46,050,507 bytes, with verified outer SHA-256
`409bf843e05c7d408ee32f136ac3e8505997157ef245275764ca595e425ae877`.
The original archive sizes, hashes, all artifact IDs, exact dependency graph and
failure/report bindings are retained in
`docs/evidence/visionworkshop-modular-candidate-45616400076.json`.
The subsequent app/driver corrections are source fixes awaiting a new complete
Windows matrix; the original failure is retained even when its ZIPs are reused.

[Run 45633041291](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45633041291)
at builder `a63aa98ed1c55ee65cff59fcdcd96a04bf95ff2a`, app
`f1557cb1a8ca57314e617bea9f340eaa3a2e3f90`, passed 34 builder, 17 real-ZIP reuse
and 37 shared-contract checks on Windows. The source CLI regression for success
and failure with cp1252 redirected output also passed. Two new stream tests then
failed because their complete-string assertions expected LF while the actual
Windows TextIOWrapper correctly emitted CRLF. The candidate stopped at this
source gate before downloading reusable artifacts, freezing Core or invoking
the product EXE. Evidence artifact `15032501325` is 238,312 bytes, with API SHA-256
`e703bf063a5cc06d2da2aa88159c603bab6490f45168b8589367a17cd3a8fc87`.
App `fa92b08720726ccf984fdf90d03dc4071a1adf68` updates those three exact string
expectations to `os.linesep`; production encoding behavior is unchanged. The historical request was superseded when the Ultralytics source and dependency lock changed for v8.4.9. Run `45949863344` is the first fresh module build under that dependency identity; its archives are not reusable until the run completes and the exact artifacts pass the strict verifier.

[Run 45634156750](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45634156750)
at builder `baf33237b9613f69758415ace80f969b0c8a01b4`, app
`fa92b08720726ccf984fdf90d03dc4071a1adf68`, passed preparation and downloaded
all eleven original module artifacts with their outer and inner digests verified.
The unchanged strict reuse verifier then rejected a fresh manifest difference
before Core freezing. Independent old/new inventory comparison found the same
42,519 installed paths, with 34 equal-size `*.dist-info/RECORD` files changed and
all 42,485 other file inventories identical. All 137 distribution runtime-row
projections, excluded-file lists and wheel provenance records were unchanged.
The previous evidence did not contain the fresh raw RECORD bytes, so the exact
changed CSV rows were not yet qualified. The new separate source-staging path
above must prove those rows on the next actual Windows run; projected equality
alone is insufficient. The rejection is preserved in
`docs/evidence/visionworkshop-modular-candidate-45634156750.json` with report
hashes, all changed receipt identities and evidence artifact `15034115936`
(34,697,589 bytes; verified SHA-256
`11b7c8d8e200ae55adf82d52045b4e5cdc94e906a3b5aec20389695bdc5fe4ea`).
This run produced no new Core ZIP or product EXE acceptance result.

[Run 45643325579](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45643325579)
at builder `abad01f6457c8f051006342259206e60acd7aea6`, app
`b1201a03313da762cdd2854a0cd1ff4f87ed87b1`, completed the actual immutable
source-module qualification and new Core construction in 1,120.796 seconds.
All eleven original module ZIPs and manifests, including their original build
identities, remained unchanged. The actual fifteen original/fresh RECORD pairs
contain 28,693 rows; exactly 22 already excluded `Scripts/*.exe` SHA fields
differed. Every other raw row/field, retained runtime inventory and non-RECORD
payload matched. Both raw receipts and the unchanged-fresh-staging checks are
saved in this run's evidence; this is now observed qualification rather than
an inference from projected inventories.

The newly frozen Core ZIP is 180,430,293 bytes, SHA-256
`b52de8727769c0b34ce432b3188394bc555b1f1a00f8c616411a701a2f29d259`.
All twelve ZIPs total 2,791,220,497 bytes. The real EXE's explicit-output status
command exited zero, and a separate detached process with null standard handles
and no `--output` passed the default-result-file check. The Core case then
created the actual GUI and missing-module controls, closed its window/workers,
and recorded no optional-framework imports or Python network attempts. However,
its subsequent native-source audit rejected the observed Windows Defender
`MpOAV.dll` under `C:/ProgramData/Microsoft/Windows Defender/Platform/` because
that path was outside the original product and Windows system roots. The run
did not collect this external DLL's signature or OS registration, so the full
Core case and product remain **FAIL**. Annotation, module lifecycle, model and
worker cases were not reached; no assertion is waived by these observations.

Visual inspection of `core-window.png` and `core-yolo-local.png` found widget
outlines/icons but no rendered text, despite correct Chinese Qt properties in
the JSON. This run used the `offscreen` Qt platform, so its control-state and
screenshot-existence observations are not visual acceptance. The next candidate
uses the native Windows platform and the early font probe described above; the
old blank-text images and failed Core result remain evidence of this run.

Evidence artifact `15039047778` is 73,329,961 bytes, with downloaded SHA-256
`85b35f95373c067fd695ca8f2710548aac60e270ec4127a61f51d0ab76e6649a`.
The complete archive identities, receipt proof, actual CLI results, failure and
report bindings are preserved in
`docs/evidence/visionworkshop-modular-candidate-45643325579.json`.
The original `45616400076` source is not eligible for the v8.4.9 dependency
identity. Only the completed `45949863344` run may become a source for the next
Core build, and only after the strict archive/manifest/RECORD/payload checks.
A reused run's fresh installed report is not automatically treated as the
original module's retained RECORD provenance.

[Run 45652987042](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45652987042)
at builder `0d48c66b90bf95df45ae8f0a12cc882c87f58b16`, app
`e44eacec0e3732801e872a69a318c74dd5e03bba`, stopped at the early font probe's
parent identity check, before CRT/model preparation, module reuse or freezing.
Its actual Qt child reported `windows`, 155 font families, 1,783 changed ASCII
pixels and 1,684 changed Chinese pixels, with valid nonzero fallback glyphs.
Both PNGs contain visible text. These are prepared-interpreter observations;
the frozen product visual result remains `NOT_RUN` for this run.

The parent expected its `Popen.pid` (1840) to equal the Python child's reported
PID (5160), despite an exit code of zero. The discrepancy is consistent with
the [fixed CPython 3.12.10 venv redirector](https://github.com/python/cpython/blob/v3.12.10/PC/launcher.c)
creating a base-Python child and waiting for it. The old report contains no
parent PID or native image/command observations, so that explanation remains an
inference for this run. The new exact process-chain gate described above must
collect and prove those fields in the next actual run; no identity assertion is
removed and no old report is rewritten as passed.

The source-guard JUnit records 242 passes and one skip: only the real official
font test was skipped before asset preparation. The actual Windows registered
Defender signature API test executed and passed in 0.052 seconds; this is not a
claim that the later product EXE native audit ran. All three protocol-3 worker
permission checks also passed. Evidence artifact `15041344101` is 4,565,634
bytes with downloaded SHA-256
`d2fe73b974e7db48aee807a2ebf5342a75e10361626ff512ad84c6a5583ec0a6`.
Original child/parent reports, JUnit results and PNG/report hashes are preserved
in `docs/evidence/visionworkshop-modular-candidate-45652987042.json`.

[Run 45659615499](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45659615499)
at builder `d3ace70e41a41b4334a9e44d2dbec0d4907f077d`, app
`591f8bef7b2292caf50f4848e3047518e490742c`, completed the new Core build,
unchanged original module ZIP qualification and first actual independent index
in 991.343 seconds. Core is 180,443,076 compressed bytes, SHA-256
`14e62ed16acb684c1ed09573c24ec7b52482dd0d867dbf52df254275d9c7c0d9`;
all twelve ZIPs total 2,791,233,280 bytes. The eleven module ZIPs, their individual
canonical manifests and their original build identities remain identical to
`45616400076`. The aggregate evidence report `module-manifests.json` has a
different JSON key order; its parsed content is equal, not its raw report bytes.

The early Qt probe observed the exact driver PID 8276, selected venv launcher
PID 7672 and its base-Python child PID 3948, including native images, complete
arguments, prefixes and nonce. This is now a measured single-child redirector
chain. Both ASCII and Chinese drawing passed, with 1,783 and 1,684 changed
pixels respectively and valid nonzero glyphs. The Windows source guard set had
293 passes and one pre-assets font skip; the prepared official-font test then
ran separately with one pass and no skips. All three legacy worker permission
checks passed. The actual registered Defender signature probe also ran and
passed, rather than being skipped.

Both empty CLI forms exited zero. The actual Core process created the Windows
GUI, exercised its missing-module controls, completed the native-file/unique
Python audit and verified the registered Defender provider's offline signature.
It wrote and printed its complete internal `PASS` JSON, including a completed
window/worker cleanup record. However, its real process then exited with
**3221225477 (`0xC0000005`)**. The driver correctly kept the Core case and overall
product **FAIL**. There is no native stack or faulting-module record in this
candidate evidence, so the exact cause is not established by the successful
internal JSON. No annotation, module installation/update/repair/rollback,
controlled DataLoader, optional-runtime/model or worker case was reached.

The actual `core-window.png` and `core-yolo-local.png` now visibly contain their
Chinese menus, buttons, titles and forms, resolving the earlier blank-text
observation. This is a visual observation of those two Windows screenshots,
not a successful process-exit or complete workflow result. Evidence artifact
`15046836955` is 73,474,221 bytes with downloaded SHA-256
`eed972a2d2a487445335d09722fb62bdaa926efd75ba1db5ad911864829ebf81`.
The separate index artifact is also downloaded and verified. Exact archive,
artifact, process, report and screenshot identities are retained in
`docs/evidence/visionworkshop-modular-candidate-45659615499.json`.

### Immutable Core exit diagnostic

The independent `visionworkshop-core-diagnostic.yml` workflow is explicitly
triggered by its reviewed `ci/visionworkshop-core-diagnostic.json` request, or
manually, and does not rebuild or retag the original Core. It downloads only the
specified Core artifact and its source evidence. API run/attempt/head,
application/build identity, both outer artifact hashes, the inner Core ZIP,
original full-file inventory and Core manifest must match before any code from
that Core is imported. The read token is available only to the download step.

One fresh Chinese/space path repeats the same `core` EXE check and preserves its
real exit code. A second fresh extraction starts the same unmodified EXE without
arguments, observes only its own visible enabled `VisionWorkshop` top-level
window remaining stable for at least one second, posts `WM_CLOSE`, and waits for
a normal exit. Timeout cleanup cannot be
reported as a pass. Both installations are checked against the original Core
inventory after exit; this comparison does not alter any original file.

After each process, the diagnostic uses the Windows
[read-only `wevtutil query-events` command](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil)
to collect bounded Application Error/Windows Error Reporting events.
Unicode output preserves Chinese paths as original XML bytes. An Application
Error must match its EventData target PID, complete EXE path and UTC
window; the event writer's `System/Execution` PID is not the target PID. WER is
associated only by the same valid nonzero GUID report ID as an exact matched
error, together with
the application name and time window. Missing events or collector errors are
recorded explicitly; they do not erase a nonzero product exit. Original Core
identity and the later diagnostic driver identity remain separate. This
diagnostic has now run on Windows as
[45668883424](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45668883424),
controller `841ba103fe10ad62bdcc5206b784e186fd14552e`. Its 16 source guards and
exact source verification passed. The fixed Core check then exited 1 before
GUI creation: NumPy's AddDllDirectory call returned WinError 206 for a
136-character / 272-byte UTF16 directory. This observation does not prove a
MAX_PATH cause. The normal no-argument GUI, PID 8824, exposed its stable owned
window and received WM_CLOSE; it exited with `0xC0000005` without forced cleanup.
Thus the native failure is also observed on the normal application close path.

Both read-only event queries exited 0 but returned zero events; faulting module,
offset and stack remain uncollected. Both 11,322-file / 627,769,495-byte Core
copies were unchanged. Artifact `15049276123` is 15,951 bytes with verified SHA256
`f08de528c65dea47175af87a0de0b432686d83a9b2d35ed400a7aec023a3935a`.
The compact, explicitly failed observation is in
`docs/evidence/visionworkshop-core-exit-diagnostic-45668883424.json`.

### Debugger-observed follow-up request

Diagnostic request schema 2 / attempt 2 continues to bind the same original
Core/run/app/builder; it creates no new product build. Its two executable cases
use shorter Chinese/space roots and assert their actual path lengths do not
exceed the original candidate's 88-character root. The longer first-diagnostic
path remains as a third verified extraction for a separate stdlib
AddDllDirectory experiment. Separate child processes register the original
launcher + runtime + NumPy sequence and a unique-directory sequence, retain
every cookie until the observation ends, and close all returned cookies.
The report records the first error/index, Windows error, successful count and
cumulative UTF16 name bytes. Those byte totals are a defined diagnostic measure,
not an assumed internal Windows buffer layout. An observed registration failure
is retained; the comparison does not itself qualify a product fix.

The exception controller uses the documented
[DEBUG_ONLY_THIS_PROCESS flag](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
and same-thread
[WaitForDebugEventEx](https://learn.microsoft.com/en-us/windows/win32/api/debugapi/nf-debugapi-waitfordebugeventex) /
[ContinueDebugEvent](https://learn.microsoft.com/en-us/windows/win32/api/debugapi/nf-debugapi-continuedebugevent).
All DWORD/BOOL fields have explicit 32-bit widths and the Win64 structures have
size/offset assertions. Only the first expected initial-thread breakpoint in
the actual system ntdll is continued as handled. Every other exception,
including second-chance access violations, is passed back as
DBG_EXCEPTION_NOT_HANDLED. Exception code/address, read/write/execute target,
PID/TID, active DLL intervals and load/unload sequence are retained; previously
unloaded address candidates are labelled separately. ReadProcessMemory is
limited to validated AMD64 PE headers for SizeOfImage. No memory/register
writes, symbol downloads, security-setting changes or WER reconfiguration occur.

Normal EXIT is continued before waiting on Popen. Failure cleanup remains
attached, terminates only the owned child, and performs a bounded event drain
through EXIT; image-file handles are closed explicitly and Windows closes
event process/thread handles on the EXIT continuation. A debug-API failure may
fall back to detach, explicitly marking handle ownership unverified and the
case failed. Cleanup never turns a process failure into a pass.

Before downloading or executing Core, the Windows workflow must run the source
guards and two actual base-CPython fixtures: normal exit and an unhandled null
thread-start execution access violation. The latter must expose second-chance
`0xC0000005` and preserve that real exit code; expected fixture failure is not
reported as a successful product process. The debugger's presence is explicit
instrumentation, not complete candidate acceptance.

The editing executor became unavailable while this follow-up was being built.
The final reviewed source is reconstructed from exact `841ba103` files and
the recorded patches using Git objects. **New local tests are NOT_RUN**; prior
29-test results apply only to the earlier controller. The Windows source guards
and actual fixture gates must pass before this follow-up can supply any new
native evidence.

[Attempt 2 / run 45675786871](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45675786871)
stopped at the source guard: the existing 16 tests passed, while one of the new
17 tests errored because its temporary directory root was not resolved before
a resolved-path containment comparison. The native helper's actual fixtures,
Core download, exception observation and DLL-search observation were all
skipped. Artifact `15051088204` is only the 751-byte request artifact
(SHA256 `7eed7b346abd0ed25c853afb1fec34e5bdfd4f63c68d398be954c512b33f27f6`).
The failure is preserved in
`docs/evidence/visionworkshop-core-exit-diagnostic-45675786871.json`.

Request attempt 3 resolves the test fixture root and logs its raw/canonical
spelling; the production containment rule is unchanged. The workflow also
always emits read-only, bounded JSON projections into its log, since the editing
executor cannot currently extract downloaded evidence. Every available source
report has size/SHA256, and complete native exception records retain module,
offset, memory-access and actual-exit fields. DLL registration summaries retain
the complete first failure and counts. Full successful registration lists and
LOAD/UNLOAD inventories remain in the artifact. Numbered 2,048-character chunks
bind each projection with a SHA256; budgets fail explicitly rather than truncate
exception fields. Four focused projection guards join the existing 33 guards
before the actual Windows fixtures. This follow-up's new local tests remain
NOT_RUN, and the earlier failure is not replaced with a presumed success.

Attempt 3 / [45678371316](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45678371316)
stopped even earlier: a test incorrectly hardcoded diagnostic nonce 2 while the
request was 3. The existing group ran 16 tests with one failure; all subsequent
guards and native/Core stages were skipped. The always-log reader executed and
its nine MISSING projections were independently reconstructed and SHA-verified.
Request attempt 4 checks the nonce as a positive exact integer, with bool/zero/
negative rejection, while preserving all original Core/run-attempt/app/head/
artifact pins. The native controllers and logging implementation do not change.
This correction and the failed run are recorded in
`docs/evidence/visionworkshop-core-exit-diagnostic-45678371316.json`.

The independent cross-product Git-object baseline is preserved in
`docs/evidence/visionworkshop-modular-other-product-baseline-d3ace70.json`.
EmoMaster configs/release workflows and shared `build.py` match the original
plan baseline. Earlier PR4 changes to cross-target oversize diagnostics and the
shared test interpreter are recorded separately; this is not a broad claim that
every other product's runtime is unaffected.

## Initial Windows gate result

[Run 45597748141](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45597748141)
at builder `2e1678b6def0cf519f3a3344d82e2059e16b8035` passed all 30 builder checks,
10 shared-contract checks and 13 actual Windows transaction checks. It stopped
before dependency preparation because the repair test used an unqualified
`test_module_runtime` import which failed with the complete `tests` package.
Application `c07785a66d18851cd6a3a0fd737f50e91579be0f` changes the three affected
test/helper imports to package-qualified names; it does not change production
behavior or assertions. Artifact `15014710476` preserves the failure evidence.
This run produced no candidate product ZIP and no product EXE acceptance result.

The simultaneous B2 path-filter regression
[45597747875](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45597747875)
also stopped at its test harness. Its existing broad `test_*modul*.py` pattern
selected the new product branding test, while the diagnostic compiler correctly
has no Pillow. The B2 workflow now selects its exact 17-test probe file; the full
product builder tests still run in the dedicated candidate and portable suites.
No loader assertion or dependency was removed to obtain a pass. B2 artifact
`15014386635` preserves that separate gate failure.

[Run 45598784332](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45598784332)
then passed the same 30/10/13 Windows gates and all 28 repair/annotation guards.
Its three protocol-3 fixed-worker checks failed on a missing `requests` import
in the isolated compiler/test environment. The workflow adds the existing pinned
`requests==2.32.5` test dependency; no worker permission assertion is removed.
Artifact `15013174037` preserves this result (ZIP SHA-256
`be3dc742569941440e447237f51dc5966d1004f91e7c6b37fbb0cb01e262bb7d`).
This second gate run also produced no product candidate or native product result.

[Run 45603279133](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45603279133)
passed 31 builder checks, 10 contract checks, 17 Windows transaction checks,
71 repair/annotation/font/resource guards and all three legacy worker checks.
The one early real-font skip occurred before resource preparation; the later
official-font test ran separately and passed with zero skips. Dependency
preparation, its pre-vendor `pip check`, model preparation and official font
verification also passed. Construction then stopped before freezing at the
previous blanket standard-library-name rejection of the actual Windows
pyreadline3 shim. Its independent evidence artifact is `15018160038`, 26,722,760
bytes, SHA-256 `3be479ee83497a1d816dde26368604cfdafdffac9046941bc7cf215551a2068a`.
The same installed inventory exposed sklearn's private MSVCP copy, motivating
the explicit official CRT provenance/compatibility work described above.
This run produced no Core/module ZIP or product EXE acceptance result.
The checked artifact identity, exact source gates and actual module dependency
edges are preserved in
`docs/evidence/visionworkshop-modular-candidate-45603279133.json`.

[Run 45611806903](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45611806903)
passed 33 builder checks, 29 contract checks, 17 Windows transaction checks,
92 source guards and all three legacy worker checks. Its separate prepared-font
check passed with zero skips. The official CRT's two CAB extraction steps,
complete source hashes and static native import coverage passed, as did the
isolated Windows readline absence observation and original shim validation.
Construction then stopped before freezing because the original wheel's
`coloredlogs.pth` was classified as an import root. A complete installed-inventory
review also identified SciPy's original, empty top-level wheel-name marker;
both files require exact auxiliary-file ownership, not a new import namespace.
Their original wheel members and RECORD entries have been checked. No generic
`.pth` or `.whl` allowance, automatic `.pth` execution or payload rewriting is
introduced. The native acceptance driver explicitly enables
`COLOREDLOGS_AUTO_INSTALL=1` so the product must prove the retained hook stays
inert before third-party imports.

This run produced no Core/module ZIP and no product EXE execution result.
Evidence artifact `15021865959` is 31,976,487 bytes, SHA-256
`150d27439957f7acb76b0326666b4443f368f4303b6e5f14d78460c9768eabb5`;
its source gates and report hashes are recorded in
`docs/evidence/visionworkshop-modular-candidate-45611806903.json`.

## Immutable Core diagnostic 45678937362 and the directory-registration fix

[Diagnostic attempt 4](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45678937362), at builder `cb98e222c5accce762fc074fe21c1b8fb196c704`, completed its 37 Windows source guards with no skips, the actual normal/NULL-execution-AV child fixtures, exact original Core provenance/inventory checks, and the bounded observations. The [compact evidence](evidence/visionworkshop-core-exit-diagnostic-45678937362.json) preserves all nine complete log projections, their source-report identities, and independently verified chunk byte counts/SHA256 values. The artifact is 15054350469, 206,118 bytes; the API reports SHA256 `690c9934025f5bf5fc82c47f87a1fb143c0db7509bcf7c39d823fa7bb2ee2b09`. Its outer ZIP was not downloaded/rehashed locally while the executor was unavailable.

The unchanged original Core (`591f8bef` application / `d3ace70e` builder, original full candidate 45659615499) exited with code 0 for both the Core diagnostic (PID 1400, 36.172 seconds) and normal GUI WM_CLOSE observation (PID 9148, 19.719 seconds) **under DEBUG_ONLY_THIS_PROCESS**. Only the expected initial ntdll breakpoint occurred; neither case required forced cleanup. Their installation roots were 88 Unicode characters, matching the original full candidate's root length. This does not identify or repair the prior ordinary `0xc0000005` exit: the original full candidate and ordinary GUI diagnostic remain FAIL.

The separate standard-library directory-registration experiment reproduced the startup error at the same 111-character original Core path. Keeping the launcher and manager's duplicate cookies caused the NumPy registration at zero-based index 217 to raise WinError 206: 217 of 218 registrations succeeded, with a measured 65,408 UTF-16 bytes including NULs before the 65,682-byte attempted total. The unique sequence registered all 109 directories (32,826 measured bytes), without errors. All 217/109 cookies were closed. These are measured directory sums, not a claim about Windows' undocumented internal buffer representation. All three original-Core inventories remained unchanged: 11,322 files / 627,769,495 bytes.

The product change is limited to `modular_product_launcher.configureCore`: it still validates the frozen internal directory and every declared Core DLL directory, then registers only `_internal`. Its nine exact, hash-verified CRT preloads and `winmode=0x1100` stay in their existing order. The unchanged application's `RuntimeGuard.mount` registers the verified Core and selected module directories once. The fixed application's path from the launcher through module-store validation is standard-library-only; optional packages load after mounting.

Three regression guards exercise real temporary directories and hashed fixture files: one internal registration with all nine ordered preloads, rejection of missing/outside/non-directory declarations before registration, and rejection of an equal-size changed preload. Their operating-system registration/load calls are mocked, so they are source guards rather than native qualification. With the local executor unavailable they are **NOT_RUN locally**; the candidate's existing Windows builder gate must execute all 38 builder tests before construction.

The active candidate `45949863344` is a fresh build using app `964b1be` and builder `5e878559`; its Core and 11 module ZIPs were built, while product acceptance and artifact upload remain pending. The next candidate must use app head `4b3f7fc` and latest builder code baseline `274890` (subsequent commits only update documentation), rebuild Core, and run the metadata-aware product matrix. It may reuse the 11 ZIPs from `45949863344` only after the source run completes, all artifacts are present, and immutable-source checks pass. Otherwise it must perform a full 11-module build using the 210-minute workflow that uploads build artifacts before product acceptance. The full ordinary-EXE acceptance matrix, including real exit codes, remains mandatory. Qt object lifetimes and release qualification remain separate gates.

The candidate workflow now also prints read-only, bounded report projections after the ordinary product step, even if construction or acceptance fails. They bind each original report's byte count/SHA256 and each chunked projection's separate SHA256. Core/module archive and index identities, all completed case names, discovered process exit reports, complete case results/errors, and the DataLoader finally/worker evidence are retained; large native and file-inventory tables remain in the artifact. Missing reports stay MISSING. Oversized sources/projections or a combined budget breach produce an explicit report ERROR without truncating fields. Six small source-report regressions and the workflow ordering guard are added; these new guards are NOT_RUN locally and run in Windows CI before the long build. The new helper does not change any product result or original evidence file.
For every nonzero, timed-out or otherwise failed process receipt, the logger also reads the sibling stdout/stderr files derived from its fixed receipt basename. Empty streams are valid; each full stream has its own size/SHA and a 64 KiB read limit. A missing case JSON therefore cannot hide the original startup traceback. Unknown UTF-8 bytes are explicitly escaped without guessing a codepage; excess source/projection budgets remain errors, never truncation.
