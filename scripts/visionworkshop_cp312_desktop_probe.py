#!/usr/bin/env python
"""Read-only CPython 3.12 desktop-baseline compatibility probe."""
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
    "kaggle", "kagglesdk",
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
PINS = [
    "torch==2.5.1+cu121",
    "torchvision==0.20.1+cu121",
    "torchaudio==2.5.1+cu121",
    "onnxruntime==1.23.2",
    "opencv-python-headless==4.11.0.86",
    "numpy==1.26.4",
    "opencv-contrib-python-headless==4.11.0.86",
    "onnxruntime-gpu==1.23.2",
    "kaggle==2.2.4",
    "kagglesdk==0.1.37",
]
EXPECTED = {
    "torch": "2.5.1+cu121", "torchvision": "0.20.1+cu121", "torchaudio": "2.5.1+cu121",
    "sympy": "1.13.1", "lapx": "0.5.5", "onnxruntime": "1.23.2",
    "opencv-python-headless": "4.11.0.86",
    "numpy": "1.26.4", "onnx": "1.16.0", "onnxruntime-gpu": "1.23.2",
    "opencv-contrib-python-headless": "4.11.0.86", "anomalib": "2.5.1",
    "huggingface-hub": "1.3.3", "tokenizers": "0.22.2",
    "lightning": "2.6.5", "pytorch-lightning": "2.6.5",
    "torchmetrics": "1.9.0", "timm": "1.0.27", "safetensors": "0.8.0",
    "Pillow": "12.0.0", "psutil": "7.2.1", "polars": "1.37.1",
    "av": "18.0.0", "kaggle": "2.2.4", "kagglesdk": "0.1.37",
    "imagecodecs": "2025.3.30", "PyQt5": "5.15.9",
    "PyQtWebEngine": "5.15.7", "PyInstaller": "6.18.0",
}
IMPORTS = [
    "torch", "torchvision", "torchaudio", "numpy", "cv2", "scipy", "onnx",
    "onnxruntime", "anomalib.data", "anomalib.engine", "anomalib.models",
    "lightning", "pytorch_lightning", "torchmetrics", "timm",
    "safetensors.torch", "huggingface_hub", "tokenizers", "polars", "av",
    "kaggle", "kagglesdk", "imagecodecs", "PyQt5.QtCore",
    "PyQt5.QtWebEngineWidgets", "qimage2ndarray", "natsort", "termcolor",
    "lap", "shapely", "pyclipper", "jsonlines", "json_repair", "onnxslim",
    "ultralytics", "anylabeling",
]

def read_requirements(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")

def build_requirements(source_root: Path, output: Path) -> dict:
    source_file = source_root / "requirements.txt"
    kept, removed, unparsed = [], [], []
    for raw in read_requirements(source_file).splitlines():
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
    output.write_text("\n".join(kept + PINS) + "\n", encoding="utf-8")
    return {"source": str(source_file), "candidate": str(output),
            "kept_count": len(kept), "removed_count": len(removed),
            "removed": removed, "overrides": PINS}

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
    for name, expected in EXPECTED.items():
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
        if not hasattr(cv2, "ximgproc"):
            report["failures"].append("cv2.ximgproc is missing")
        report["runtime_checks"]["cpu_ops"] = {
            "status": "PASS", "torchvision_nms": nms,
            "torchaudio_resample_shape": list(audio.shape),
            "onnx_cpu": "PASS", "onnx_providers": providers,
            "opencv_version": cv2.__version__, "opencv_ximgproc": hasattr(cv2, "ximgproc"),
        }
        report["runtime_checks"]["torch_cuda"] = {
            "status": "NOT_RUN_NO_GPU" if not torch.cuda.is_available() else "AVAILABLE",
            "available": torch.cuda.is_available(), "torch_cuda_build": torch.version.cuda,
        }
        if torch.version.cuda != "12.1":
            report["failures"].append(f"expected Torch CUDA build 12.1, found {torch.version.cuda}")
    except Exception as exc:
        report["runtime_checks"]["cpu_ops"] = {
            "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
        report["failures"].append(f"CPU/native smoke: {type(exc).__name__}: {exc}")

    try:
        import lap
        import numpy as np
        costs = np.array([[4., 1., 3.], [2., 0., 5.], [3., 2., 2.]], dtype=np.float64)
        total, rows, columns = lap.lapjv(costs)
        np.testing.assert_allclose(total, 5.0)
        np.testing.assert_array_equal(rows, [1, 0, 2])
        np.testing.assert_array_equal(columns, [1, 0, 2])
        rectangular = np.array([[0.1, 4., 3.], [4., 0.2, 3.]], dtype=np.float64)
        limited, matched, reverse = lap.lapjv(rectangular, extend_cost=True, cost_limit=0.5)
        np.testing.assert_allclose(limited, 0.3)
        np.testing.assert_array_equal(matched, [0, 1])
        np.testing.assert_array_equal(reverse, [0, 1, -1])
        report["runtime_checks"]["lap_assignment"] = {
            "status": "PASS", "distribution": version_of("lapx"),
            "square_cost": float(total), "square_assignment": rows.tolist(),
            "rectangular_cost": float(limited), "unmatched_columns": reverse.tolist(),
        }
    except Exception as exc:
        report["runtime_checks"]["lap_assignment"] = {
            "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
            "traceback": traceback.format_exc(limit=4),
        }
        report["failures"].append(f"LAP assignment: {type(exc).__name__}: {exc}")

    owners = inspectBinaryOwners(EXPECTED)
    report["runtime_checks"]["binary_owners"] = owners
    if owners["status"] != "PASS":
        report["failures"].append("ONNX Runtime or OpenCV native owner verification failed")

    try:
        from anomaly_func.dinov2_main_runtime import CORE, PROFILE, valid_environment
        packages = {
            **{name: version_of(name) for name in CORE},
            **owners["distribution_versions"],
        }
        core_matches = all(packages.get(name) == version for name, version in {
            **CORE, "onnxruntime-gpu": "1.23.2",
            "opencv-contrib-python-headless": "4.11.0.86",
        }.items())
        fake = {"runtime_profile": PROFILE, "python": "3.11.99", "packages": packages,
                "scope": "windows", "platform": "win32", "provider": "CPUExecutionProvider",
                "threads": 2, "inter_threads": 1}
        package_contract = valid_environment(fake, "CPUExecutionProvider")
        report["runtime_checks"]["dino_legacy_dependency_contract"] = {
            "status": "PASS" if core_matches and package_contract else "FAIL",
            "scope": "VERSION_COMPARISON_ONLY", "synthetic_python": "3.11.99",
            "actual_python": sys.version.split()[0],
            "actual": packages, "core_pins_match": core_matches,
            "package_contract_match": package_contract,
        }
        if not core_matches or not package_contract:
            report["failures"].append("DINO main-runtime package pins do not match desktop candidate")
    except Exception as exc:
        report["runtime_checks"]["dino_legacy_dependency_contract"] = {
            "status": "FAIL", "error": type(exc).__name__ + ": " + str(exc)
        }
        report["failures"].append("DINO main-runtime dependency pin probe failed")

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
            "but dinov2_main_runtime.py still hard-codes Python 3.11."
        )
    else:
        report["runtime_checks"]["dino_main_python_gate"] = {
            "status": "FAIL", "stdout": child.stdout, "stderr": child.stderr,
            "returncode": child.returncode,
        }
        report["failures"].append("DINO main-runtime Python gate probe did not match")

    report["status"] = "PASS" if not report["failures"] else "FAIL"
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--requirements-out", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.requirements_out:
        print(json.dumps(build_requirements(args.source_root, args.requirements_out), indent=2))
    if args.report:
        result = smoke(args.source_root)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        if result["status"] != "PASS":
            raise SystemExit(1)

if __name__ == "__main__":
    main()

