# VisionWorkshop protocol-4 modular candidate

This opt-in builder creates a real product Core and independent offline module
ZIPs. It does not change the protocol-3 portable publisher, other target configs,
or create a Release. The first candidate must pass the independent Windows
workflow before its product behavior or actual compressed size is reported.

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

The stdlib launcher compares on-disk Core metadata with its exact embedded bytes
before importing application code. It verifies the complete external Core
`runtime_files` inventory (first-party files, third-party Python/PYD/DLL files,
metadata and Qt helper programs), rejects additional files in those owned
directories, checks the dependency lock, then preloads the established Core CRT
and canonical MSVCP DLL. Metadata is serialized with the application's canonical
encoder and must fit its shared 32 MiB limit; oversized documents fail the build.
The frozen `_internal` files and EXE are separately tied to the compiler source
audit and final archive hashes, avoiding an EXE self-hash cycle.
After freezing, the builder also checks the complete Core DLL inventory,
including `_internal`, against every module owner before creating any ZIP.

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
compiler and dependency preparation environments. The CLI steps are:

```powershell
python scripts/build_vision_train_modular.py prepare --output modular-input
python scripts/build_vision_train_modular.py assets `
  --source-root <exact-source> --assets-root <isolated-resource-staging> `
  --output <reports/resource-preparation.json>
python scripts/build_vision_train_modular.py build `
  --source-root <exact-source> --assets-root <isolated-resource-staging> `
  --output <new-candidate-directory> `
  --build-python <compiler-python.exe> --runtime-python <preparation-python.exe> `
  --install-report <runtime-install.json> --install-report <provider-install.json> `
  --torch-install-report <runtime-install.json> --crt-wheel <reviewed-pandas-wheel>
python scripts/verify_vision_train_modular_product.py `
  --build-summary <new-candidate-directory/reports/modular-build-summary.json> `
  --output <new-acceptance-directory> --pt-timeout 1200
```

The workflow contains the exact environment installation commands. It saves pip
downloads before construction, and records the provenance of reused inputs.
`build` requires Windows, fresh output paths and the reviewed separate environments.
No operation publishes anything.

## Candidate acceptance and reports

The Windows workflow first runs the shared module contract and actual Windows
ZIP/transaction/lease and cold-repair tests, plus the legacy fixed-worker
run-permission tests and annotation diagnostic guards.
It then builds the windowed product EXE and round-trips every LZMA ZIP, checking
the actual compressed per-file size against the shared download limit.

The acceptance driver runs that EXE from a Chinese and space-containing install
path with isolated user directories and an empty current directory. It checks:

- A separate windowed CLI invocation without `--output`: its new
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
- Actual loading and CPU execution of the image-simplification, CNN pretrained
  and DINO pretrained resources using the production loaders and registered
  weights, with separate time limits and weight/manifest provenance reports.
- Actual Torch, ORT, DINO, YOLO and native PT fixture entry points using the same
  EXE and exact Core/generation/module identities.
- A cold rollback followed by another fresh Core-only process.

Reports bind executable SHA, process ID, runtime generation, manifest hashes,
observed origins, network attempts and child-process logs. The PT case has a
20-minute limit; timeouts terminate the process tree and fail with saved logs.
The GUI lease observation deliberately terminates a disposable GUI process after
the observation and is not evidence of graceful user-driven shutdown.
The driver records a complete initial Core inventory, including EXE and
`_internal`, and compares it after pending installation, activation, repair,
removal, complete native/worker execution and rollback. Only the explicit root
`modules` and `.module-state` stores are excluded. The deliberately corrupted
file and its before/after digests are retained in the repair evidence.

The workflow uploads evidence, Core and each of the eleven optional module ZIPs
as thirteen separate reviewable Actions artifacts. Reports and selected offline
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
