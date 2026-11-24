#!/usr/bin/env python
"""Read-only CPython 3.12 compatibility probe for VisionWorkshop source."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import importlib.metadata as metadata
import json
import platform
import subprocess
import sys
import traceback
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

OVERRIDES = {
    "torch", "torchvision", "torchaudio", "numpy",
    "onnxruntime", "onnxruntime-gpu",
    "opencv-python", "opencv-python-headless",
    "opencv-contrib-python", "opencv-contrib-python-headless",
    "tokenizers", "huggingface-hub", "transformers", "kaggle", "kagglesdk", "sympy",
}
DEV_ONLY = {
    "notebook", "notebook-shim", "jupyterlab", "jupyterlab-server",
    "jupyter-server", "jupyter-server-terminals", "jupytext", "ipykernel",
    "ipython", "ipython-pygments-lexers", "ipywidgets", "jupyter-console",
    "jupyter-events", "jupyter-lsp", "jupyter-client", "jupyter-core",
    "jupyterlab-pygments", "jupyterlab-widgets", "widgetsnbextension",
    "nbconvert", "nbformat", "pandocfilters", "pywinpty", "pyzmq",
    "terminado", "send2trash", "debugpy", "qt5-applications", "qt5-tools",
    "pyqt5-tools", "pyinstaller", "pyinstaller-hooks-contrib", "pefile",
    "asttokens", "comm", "decorator", "executing", "jedi",
    "matplotlib-inline", "mistune", "nest-asyncio", "parso", "pure-eval",
    "prompt-toolkit", "stack-data", "traitlets", "wcwidth", "bleach",
    "defusedxml", "beautifulsoup4", "soupsieve", "jsonschema",
    "jsonschema-specifications", "referencing", "rpds-py", "fastjsonschema",
    "rfc3339-validator", "rfc3986-validator", "rfc3987-syntax",
    "isoduration", "uri-template", "webencodings",
}
PINNED_OVERRIDES = [
    "torch==2.10.0+cu128",
    "torchvision==0.25.0+cu128",
    "torchaudio==2.10.0+cu128",
    "onnxruntime==1.23.2",
    "opencv-python-headless==4.11.0.86",
    "sympy==1.14.0",
    "numpy==2.0.2",
    "opencv-contrib-python-headless==4.11.0.86",
    "onnxruntime-gpu==1.23.2",
    "transformers==4.46.3",
    "huggingface-hub==0.26.5",
    "tokenizers==0.20.3",
    "kaggle==2.2.4",
    "kagglesdk==0.1.37",
]
EXPECTED_VERSIONS = {
    "torch": "2.10.0+cu128", "torchvision": "0.25.0+cu128", "torchaudio": "2.10.0+cu128",
    "sympy": "1.14.0", "onnxruntime": "1.23.2",
    "opencv-python-headless": "4.11.0.86",
    "numpy": "2.0.2", "onnx": "1.16.0", "onnxruntime-gpu": "1.23.2",
    "opencv-contrib-python-headless": "4.11.0.86", "anomalib": "2.5.1",
    "transformers": "4.46.3", "huggingface-hub": "0.26.5",
    "tokenizers": "0.20.3", "lightning": "2.6.5",
    "pytorch-lightning": "2.6.5", "torchmetrics": "1.9.0",
    "timm": "1.0.27", "safetensors": "0.8.0", "Pillow": "12.0.0",
    "psutil": "7.2.1", "polars": "1.37.1", "av": "18.0.0",
    "kaggle": "2.2.4", "kagglesdk": "0.1.37",
    "imagecodecs": "2025.3.30", "PyQt5": "5.15.9",
    "PyQtWebEngine": "5.15.7", "PyInstaller": "6.18.0",
}
IMPORTS = [
    "torch", "torchvision", "torchaudio", "numpy", "cv2", "scipy", "onnx",
    "onnxruntime", "anomalib.data", "anomalib.engine", "anomalib.models",
    "lightning", "pytorch_lightning", "torchmetrics", "timm",
    "safetensors.torch", "transformers", "huggingface_hub", "tokenizers",
    "polars", "av", "kaggle", "kagglesdk", "imagecodecs",
    "PyQt5.QtCore", "PyQt5.QtWebEngineWidgets", "qimage2ndarray",
    "natsort", "termcolor", "lap", "shapely", "pyclipper",
    "jsonlines", "json_repair", "onnxslim", "ultralytics", "anylabeling",
]

def build_requirements(source_root: Path, output: Path) -> dict:
    source_file = source_root / "requirements.txt"
    raw_bytes = source_file.read_bytes()
    source_text = raw_bytes.decode("utf-16") if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")) else raw_bytes.decode("utf-8-sig")
    kept, removed, unparsed = [], [], []
    for raw in source_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            req = Requirement(line)
        except Exception:
            unparsed.append(line)
            continue
        name = canonicalize_name(req.name)
        if name in OVERRIDES or name in DEV_ONLY:
            removed.append({"name": name, "line": line})
        else:
            kept.append(line)
    if unparsed:
        raise ValueError("Unparsed requirements: " + repr(unparsed))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(kept + PINNED_OVERRIDES) + "\n", encoding="utf-8")
    return {
        "source": str(source_file), "candidate": str(output),
        "kept_count": len(kept), "removed_count": len(removed),
        "removed": removed, "overrides": PINNED_OVERRIDES,
    }

def version_of(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None

def inspectNativeRecords(distributionName: str, prefix: str) -> list:
  distribution = metadata.distribution(distributionName)
  records = [entry for entry in distribution.files or []
             if str(entry).replace('\\', '/').startswith(prefix)
             and str(entry).lower().endswith('.pyd')]
  if not records:
    raise RuntimeError(f'{distributionName}: no native extension in wheel RECORD')
  checks = []
  for entry in records:
    path = Path(distribution.locate_file(entry)).resolve()
    if not entry.hash:
      raise RuntimeError(f'{distributionName}: missing RECORD hash for {entry}')
    with path.open('rb') as stream:
      digest = hashlib.file_digest(stream, entry.hash.mode).digest()
    actual = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    checks.append({'path': str(path), 'algorithm': entry.hash.mode,
                   'expected_hash': entry.hash.value, 'actual_hash': actual,
                   'status': 'PASS' if actual == entry.hash.value else 'FAIL'})
  return checks


def inspectBinaryOwners(expectedVersions: dict) -> dict:
  aliases = ('onnxruntime', 'onnxruntime-gpu', 'opencv-python',
             'opencv-python-headless', 'opencv-contrib-python',
             'opencv-contrib-python-headless')
  versions = {name: version_of(name) for name in aliases if version_of(name) is not None}
  result = {
    'status': 'PASS', 'distribution_versions': versions,
    'coinstalled_metadata': [name for name in versions
                            if name not in ('onnxruntime-gpu',
                                            'opencv-contrib-python-headless')],
    'note': 'Dependency metadata may coexist; native files must match the final owners.',
    'owners': {},
  }
  owners = (
    ('onnxruntime-gpu', 'onnxruntime', 'onnxruntime/capi/onnxruntime_pybind11_state'),
    ('opencv-contrib-python-headless', 'cv2', 'cv2/'),
  )
  for distributionName, moduleName, nativePrefix in owners:
    try:
      module = importlib.import_module(moduleName)
      nativeChecks = inspectNativeRecords(distributionName, nativePrefix)
      packageDir = Path(metadata.distribution(distributionName).locate_file(moduleName)).resolve()
      modulePath = Path(module.__file__).resolve()
      expected = expectedVersions[distributionName]
      if moduleName == 'cv2':
        expected = '.'.join(expected.split('.')[:3])
        capabilities = {'ximgproc': hasattr(module, 'ximgproc')}
        capabilityMatches = capabilities['ximgproc']
      else:
        capabilities = {'providers': module.get_available_providers()}
        capabilityMatches = 'CUDAExecutionProvider' in capabilities['providers']
      matches = (module.__version__ == expected and modulePath.parent == packageDir
                 and capabilityMatches
                 and all(check['status'] == 'PASS' for check in nativeChecks))
      result['owners'][distributionName] = {
        'status': 'PASS' if matches else 'FAIL', 'module_path': str(modulePath),
        'expected_module_version': expected, 'actual_module_version': module.__version__,
        'package_path_matches': modulePath.parent == packageDir,
        'capabilities': capabilities, 'native_record_checks': nativeChecks,
      }
      if not matches:
        result['status'] = 'FAIL'
    except Exception as exc:
      result['status'] = 'FAIL'
      result['owners'][distributionName] = {
        'status': 'FAIL', 'error': type(exc).__name__ + ': ' + str(exc),
        'traceback': traceback.format_exc(limit=4),
      }
  return result


def smoke(source_root: Path) -> dict:
    source_root = source_root.resolve()
    for path in (source_root / "ultralytics", source_root / "X-AnyLabeling"):
        if path.is_dir():
            sys.path.insert(0, str(path))
    sys.path.insert(0, str(source_root))
    report = {
        "python": sys.version, "platform": platform.platform(),
        "executable": sys.executable, "versions": {}, "version_checks": {},
        "scope": "SOURCE_RUNTIME_PROBE_NOT_PRODUCT_ACCEPTANCE",
        "frozen_execution": "NOT_RUN",
        "imports": {}, "runtime_checks": {}, "expected_migration_blockers": [],
        "failures": [],
    }
    for name, expected in EXPECTED_VERSIONS.items():
        actual = version_of(name)
        report["versions"][name] = actual
        ok = actual == expected
        report["version_checks"][name] = {
            "expected": expected, "actual": actual, "status": "PASS" if ok else "FAIL"
        }
        if not ok:
            report["failures"].append(f"{name}: expected {expected}, found {actual}")

    for module in IMPORTS:
        try:
            importlib.import_module(module)
            report["imports"][module] = "PASS"
        except (Exception, SystemExit) as exc:
            report["imports"][module] = {
                "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
                "traceback": traceback.format_exc(limit=4),
            }
            report["failures"].append(f"import {module}: {type(exc).__name__}: {exc}")

    try:
        import torch
        import torchvision
        import torchaudio
        import numpy as np
        import cv2
        import onnxruntime as ort
        from onnx import TensorProto, helper

        nms = torchvision.ops.nms(
            torch.tensor([[0., 0., 10., 10.], [1., 1., 9., 9.]]),
            torch.tensor([0.9, 0.8]), 0.5,
        ).tolist()
        audio = torchaudio.functional.resample(torch.randn(1, 1600), 16000, 8000)
        values = np.arange(16, dtype=np.float32).reshape(4, 4)
        cv2.resize(values, (8, 8))
        graph = helper.make_graph(
            [helper.make_node("MatMul", ["x", "x"], ["y"])], "cp312-cpu-smoke",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [4, 4])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [4, 4])],
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        model.ir_version = 9
        session = ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])
        actual = session.run(None, {"x": values})[0]
        np.testing.assert_allclose(actual, values @ values, rtol=1e-5, atol=1e-5)
        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" not in providers:
            report["failures"].append("onnxruntime-gpu does not expose CUDAExecutionProvider")
        report["runtime_checks"]["cpu_ops"] = {
            "status": "PASS", "torchvision_nms": nms,
            "torchaudio_resample_shape": list(audio.shape),
            "onnx_cpu": "PASS", "onnx_providers": providers,
        }
        report["runtime_checks"]["opencv_contrib"] = {
            "status": "PASS" if hasattr(cv2, "ximgproc") else "FAIL",
            "version": cv2.__version__, "has_ximgproc": hasattr(cv2, "ximgproc"),
        }
        if not hasattr(cv2, "ximgproc"):
            report["failures"].append("cv2.ximgproc is missing")
        report["runtime_checks"]["torch_cuda"] = {
            "status": "NOT_RUN_NO_GPU" if not torch.cuda.is_available() else "AVAILABLE",
            "available": torch.cuda.is_available(), "torch_cuda_build": torch.version.cuda,
        }
        if torch.version.cuda != "12.8":
            report["failures"].append(f"expected CUDA 12.8 Torch build, found {torch.version.cuda}")
    except Exception as exc:
        report["runtime_checks"]["cpu_ops"] = {
            "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
        report["failures"].append(f"CPU/native smoke: {type(exc).__name__}: {exc}")

    owners = inspectBinaryOwners(EXPECTED_VERSIONS)
    report["runtime_checks"]["binary_owners"] = owners
    if owners["status"] != "PASS":
        report["failures"].append("ONNX Runtime or OpenCV native owner verification failed")

    try:
        code = """
import sys
from anomaly_func import dinov2_main_runtime
from anomaly_func.dinov2_execution import CPU
dinov2_main_runtime.enable()
from anomaly_func.dinov2_onnx_session import lightweight_environment
assert 'torch' not in sys.modules
try:
    lightweight_environment('windows', CPU)
except RuntimeError as exc:
    assert 'Python 3.11' in str(exc)
    print('EXPECTED_PYTHON_VERSION_BLOCKER')
else:
    raise AssertionError('legacy main runtime unexpectedly accepted Python 3.12')
"""
        child = subprocess.run([sys.executable, "-c", code], cwd=source_root,
                               capture_output=True, text=True, timeout=60)
        if child.returncode == 0 and "EXPECTED_PYTHON_VERSION_BLOCKER" in child.stdout:
            report["runtime_checks"]["dino_main_python_gate"] = "EXPECTED_MIGRATION_BLOCKER"
            report["expected_migration_blockers"].append(
                "DINO main runtime worker is already routed through the shared sys.executable, "
                "but dinov2_main_runtime.py still hard-codes Python 3.11; changed CORE pins "
                "also require numerical acceptance."
            )
            from anomaly_func.dinov2_main_runtime import CORE
            actual_core = {name: version_of(name) for name in CORE}
            mismatches = {name: {"expected": expected, "actual": actual_core.get(name)}
                          for name, expected in CORE.items() if actual_core.get(name) != expected}
            report["runtime_checks"]["dino_main_core_pins"] = {
                "status": "EXPECTED_MIGRATION_REQUIRED" if mismatches else "PASS",
                "actual": actual_core, "mismatches": mismatches,
            }
        else:
            report["runtime_checks"]["dino_main_python_gate"] = {
                "status": "FAIL", "stdout": child.stdout, "stderr": child.stderr,
                "returncode": child.returncode,
            }
            report["failures"].append("DINO main-runtime Python gate probe did not match")

    except Exception as exc:
        report["runtime_checks"]["dino_main_python_gate"] = {
            "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(limit=4),
        }
        report["failures"].append(f"DINO main runtime probe: {type(exc).__name__}: {exc}")

    try:
        from patchcore_dino_runtime.environment import diagnose_environment, require_environment
        diagnostic = diagnose_environment()
        report["runtime_checks"]["patchcore_dino_profile"] = diagnostic
        require_environment()
        from patchcore_dino_runtime.model_factory import create_encoder
        from patchcore_dino_runtime.features import DinoFeatures
        import torch
        encoder = create_encoder()
        output = DinoFeatures(encoder)(torch.zeros(1, 3, 28, 28, dtype=torch.float32))
        shapes = {key: list(value.shape) for key, value in output.items()}
        expected = {"dino_layer_9": [1, 384, 2, 2], "dino_layer_12": [1, 384, 2, 2]}
        if shapes != expected:
            raise AssertionError(f"unexpected DINO feature shapes: {shapes}")
        report["runtime_checks"]["patchcore_dino_encoder"] = {
            "status": "PASS", "feature_shapes": shapes,
        }
    except Exception as exc:
        report["runtime_checks"]["patchcore_dino_encoder"] = {
            "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
        report["failures"].append(f"PatchCore DINO encoder: {type(exc).__name__}: {exc}")

    report["status"] = "PASS" if not report["failures"] else "FAIL"
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--requirements-out", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.requirements_out:
        result = build_requirements(args.source_root, args.requirements_out)
        print(json.dumps(result, indent=2))
    if args.report:
        result = smoke(args.source_root)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        if result["status"] != "PASS":
            raise SystemExit(1)

if __name__ == "__main__":
    main()

