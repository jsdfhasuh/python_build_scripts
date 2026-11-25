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
claims. At this implementation checkpoint, no actual Windows candidate has yet
generated this index. Build/native/Release qualifications remain distinct;
the index records `NOT_QUALIFIED` for Release and points native execution to its
separate report.
The complete focused source check was 69 tests, zero failures/errors/skips;
input hashes and the exact 12/10/35/12 group counts are recorded in
`docs/evidence/visionworkshop-modular-index-source-tests.json`.

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

## Known vendor declaration gate

Ultralytics commit `74b2b91e5c4420af47875801b8e13333ab7026ac` declares
`torch>=1.8.0,<2.10` (and a Windows variant). The baseline is Torch 2.10.0. Its
source and requirements are preserved exactly; source-tree distribution metadata
is generated faithfully from the pinned pyproject and explicitly identifies
itself as a source inventory, not an upstream wheel. This discrepancy remains an
`observed/unqualified` compatibility finding and a release gate.

The product fixture performs actual CPU YOLO training, prediction, ONNX export
and reload parity. Passing that bounded fixture does not turn the vendor's
declared dependency interval into a supported combination or establish that a
full `pip check` including this source vendor passed. The preparation-environment
`pip check` occurs before the source-only vendor is added and is labelled as such.

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
explicitly supplying `reuse_run_id` and `reuse_run_attempt`. The current request
selects application `591f8bef7b2292caf50f4848e3047518e490742c` and the original
module ZIPs from run `45616400076`, attempt 1. That source run failed its first
EXE CLI check; its build was `BUILT`. Reuse preserves that failure status and
does not transfer native qualification to the new candidate.

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
expectations to `os.linesep`; production encoding behavior is unchanged. The
explicit candidate request continues to select the original `45616400076` ZIPs.

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
Further Core-only candidates continue to select the original `45616400076`
source. A reused run's fresh installed report is not automatically treated as
the original module's retained RECORD provenance.

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
