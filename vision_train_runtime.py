"""Install and validate the dedicated Windows Vision Train CI runtime."""

import argparse
import ast
import importlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from build_config import BuildConfigError
from build_environment import pythonChildEnvironment


ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / 'ci/vision-train-runtime.json'


def loadProfile() -> dict:
  return json.loads(PROFILE.read_text(encoding='utf-8'))


def readRequirements(path: Path) -> str:
  data = path.read_bytes()
  encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
  return data.decode(encoding)


def makeRequirements(sourceText: str, extras: list[str], profile: dict) -> list[str]:
  from packaging.requirements import Requirement
  from packaging.utils import canonicalize_name

  replacements = dict(profile['overrides'])
  for text in profile['torch_packages'] + profile['packages'] + profile['binary_owners']:
    replacements[canonicalize_name(Requirement(text).name)] = text
  result = []
  for text in sourceText.splitlines() + extras:
    text = text.strip()
    if not text or text.startswith('#'):
      continue
    # Do not reinterpret pip directives or relative files from another checkout.
    try:
      requirement = Requirement(text)
    except ValueError as exc:
      raise BuildConfigError(f'Unsupported source requirement: {text}') from exc
    name = canonicalize_name(requirement.name)
    if name not in replacements:
      result.append(text)
  return result + list(replacements.values())


def runCommand(command: list[str], *, cwd: Path | None = None) -> None:
  print(subprocess.list2cmdline(command), flush=True)
  result = subprocess.run(command, cwd=cwd, check=False, env=pythonChildEnvironment(),
                          timeout=3600)
  if result.returncode:
    raise BuildConfigError('Runtime dependency command failed; publication is blocked')


def checkPlatform(profile: dict) -> None:
  version = '.'.join(str(part) for part in sys.version_info[:2])
  if sys.platform != 'win32' or version != profile['python'] or sys.maxsize <= 2**32:
    raise BuildConfigError(f'Vision Train CI requires Windows x64 Python {profile["python"]}')


def installRuntime(source: Path, *, dryRun: bool = False) -> None:
  profile = loadProfile()
  checkPlatform(profile)
  config = json.loads((ROOT / 'configs/emo-vision-train.json').read_text(encoding='utf-8'))
  requirements = makeRequirements(readRequirements(source / 'requirements.txt'),
                                  config['ci_extra_packages'], profile)
  with tempfile.TemporaryDirectory(prefix='vision-train-dependencies-') as directory:
    path = Path(directory) / 'requirements.txt'
    path.write_text('\n'.join(requirements) + '\n', encoding='utf-8')
    pip = [sys.executable, '-m', 'pip']
    if dryRun:
      runCommand(pip + ['install', '--dry-run', '--extra-index-url', profile['torch_index'],
                        '-r', str(path)])
      return
    # Install exact GPU wheels first; the combined resolution cannot substitute CPU wheels.
    runCommand(pip + ['install', '--no-deps', '--index-url', profile['torch_index'],
                      *profile['torch_packages']])
    runCommand(pip + ['install', '-r', str(path)])
    # CPU/GPU ORT and headless/contrib OpenCV share import paths. Select their final owners.
    runCommand(pip + ['install', '--force-reinstall', '--no-deps', *profile['binary_owners']])
    runCommand(pip + ['check'])


def validateTorch(version: str, cuda: str | None, profile: dict) -> None:
  expected = profile['torch_packages'][0].split('==', 1)[1]
  if version != expected or cuda != profile['cuda']:
    raise BuildConfigError(f'Expected torch {expected} / CUDA {profile["cuda"]}; '
                           f'found {version} / CUDA {cuda}')


def requireFiles(root: Path, names: list[str]) -> None:
  missing = [name for name in names
             if not (root / name).is_file() or (root / name).stat().st_size == 0]
  if missing:
    raise BuildConfigError('Missing runtime files: ' + ', '.join(missing))


def validateEnvironment(source: Path) -> None:
  profile = loadProfile()
  checkPlatform(profile)
  runCommand([sys.executable, '-m', 'pip', 'check'])
  torch = importlib.import_module('torch')
  validateTorch(torch.__version__, torch.version.cuda, profile)
  packages = (profile['torch_packages'] + profile['packages'] + profile['binary_owners']
              + list(profile['overrides'].values()))
  for text in packages:
    name, expected = text.split('==', 1)
    actual = importlib.metadata.version(name)
    if actual != expected:
      raise BuildConfigError(f'Expected {name}=={expected}, found {actual}')
  requireFiles(Path(torch.__file__).parent / 'lib', profile['torch_dlls'])
  requireFiles(source / 'static/models', profile['models'])
  # Import checks do not require credentials, model downloads or a physical GPU.
  code = '\n'.join(['import torch'] + [f'import {name}' for name in profile['modules']]
                   + profile['imports'] + [
    'import onnxruntime as ort',
    'import cv2',
    'assert hasattr(cv2, "ximgproc"), "OpenCV contrib modules are missing"',
    'assert "CUDAExecutionProvider" in ort.get_available_providers(), '
    '"ONNX Runtime GPU provider is missing"',
  ])
  runCommand([sys.executable, '-B', '-c', code])
  print('Runtime environment verified; physical GPU execution remains untested.', flush=True)


def readTorchVersion(path: Path) -> tuple[str, str | None]:
  values = {}
  for node in ast.parse(path.read_text(encoding='utf-8')).body:
    targets = node.targets if isinstance(node, ast.Assign) else []
    if isinstance(node, ast.AnnAssign):
      targets = [node.target]
    for target in targets:
      if isinstance(target, ast.Name) and target.id in ('__version__', 'cuda'):
        values[target.id] = ast.literal_eval(node.value)
  return values.get('__version__', ''), values.get('cuda')


def readPackagedModules(executable: Path) -> set[str]:
  from PyInstaller.archive.readers import CArchiveReader

  archive = CArchiveReader(str(executable))
  return set(archive.open_embedded_archive('PYZ.pyz').toc)


def validateModules(modules: set[str], required: list[str]) -> None:
  missing = sorted(set(required) - modules)
  if missing:
    raise BuildConfigError('Missing EXE modules: ' + ', '.join(missing))


def readDllImports(path: Path) -> list[str]:
  import pefile

  with pefile.PE(str(path), fast_load=True) as image:
    image.parse_data_directories(directories=[
      pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
      pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT'],
    ])
    return [entry.dll.decode('ascii').lower()
            for field in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
            for entry in getattr(image, field, [])]


def validateCudaDependencies(internal: Path) -> None:
  libraries = list((internal / 'torch/lib').glob('*.dll'))
  libraries.append(internal / 'onnxruntime/capi/onnxruntime_providers_cuda.dll')
  available = {path.name.lower() for path in libraries if path.is_file()}
  # nvcuda.dll belongs to the NVIDIA driver, not the distributable CUDA runtime.
  vendor = re.compile(r'^(?:cublas|cudnn|cudart|cufft|curand|cusolver|cusparse|nvrtc|nvjitlink)')
  for path in libraries:
    for dependency in readDllImports(path):
      if vendor.match(dependency) and dependency not in available:
        raise BuildConfigError(f'{path.name} requires missing bundled DLL {dependency}')


def validatePackage(appDir: Path, programName: str) -> dict:
  profile = loadProfile()
  internal = appDir / '_internal'
  requireFiles(internal, ['torch/version.py', 'onnxruntime/capi/onnxruntime_providers_cuda.dll'])
  version, cuda = readTorchVersion(internal / 'torch/version.py')
  validateTorch(version, cuda, profile)
  requireFiles(internal / 'torch/lib', profile['torch_dlls'])
  requireFiles(internal / 'static/models', profile['models'])
  validateModules(readPackagedModules(appDir / f'{programName}.exe'), profile['modules'])
  if not list((internal / '_polars_runtime_32').glob('*.pyd')):
    raise BuildConfigError('Missing packaged Polars native extension')
  validateCudaDependencies(internal)
  return {'status': 'passed', 'torch': version, 'cuda': cuda,
          'required_modules': profile['modules'], 'gpu_execution': 'not-run'}


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('action', choices=('install', 'verify', 'package'))
  parser.add_argument('--source-root', type=Path)
  parser.add_argument('--app-dir', type=Path)
  parser.add_argument('--program-name', default='emo-vision-train')
  parser.add_argument('--dry-run', action='store_true')
  args = parser.parse_args()
  try:
    if args.action == 'package':
      if args.app_dir is None:
        parser.error('package requires --app-dir')
      print(json.dumps(validatePackage(args.app_dir, args.program_name), indent=2))
    else:
      if args.source_root is None:
        parser.error('install/verify requires --source-root')
      if args.action == 'install':
        installRuntime(args.source_root, dryRun=args.dry_run)
      else:
        validateEnvironment(args.source_root)
    return 0
  except (BuildConfigError, OSError, ValueError, ImportError, KeyError,
          subprocess.TimeoutExpired) as exc:
    print(f'Vision Train runtime check failed: {exc}', file=sys.stderr)
    return 1


if __name__ == '__main__':
  raise SystemExit(main())
