"""Frozen standard-library entry; the builder embeds the exact Core metadata."""

import ctypes
import hashlib
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path
from pathlib import PurePosixPath


EMBEDDED_CORE_JSON = '__BUILD_CORE_JSON__'
DLL_HANDLES = []


def checkedFile(root: Path, relative: str) -> Path:
  parts = relative.split('/')
  if (not parts or PurePosixPath(relative).is_absolute() or '\\' in relative
      or ':' in relative or any(part in ('', '.', '..') for part in parts)):
    raise RuntimeError('Invalid Core file path: ' + relative)
  path = root.joinpath(*parts)
  for component in (path, *path.parents):
    if component == root.parent:
      break
    status = component.lstat()
    if component.is_symlink() or getattr(status, 'st_file_attributes', 0) & 0x400:
      raise RuntimeError('Core file cannot use a link or reparse point: ' + relative)
  if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
    raise RuntimeError('Core file is missing or outside the installation: ' + relative)
  return path


def verifyFile(root: Path, record: dict) -> Path:
  path = checkedFile(root, record['path'])
  if 'size' in record and path.stat().st_size != record['size']:
    raise RuntimeError('Core file size changed: ' + record['path'])
  with path.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
  if actual != record['sha256']:
    raise RuntimeError('Core file integrity check failed: ' + record['path'])
  return path


def verifyCore(root: Path, embedded: str) -> dict:
  actual = checkedFile(root, 'core.json').read_bytes()
  if actual != embedded.encode('utf-8'):
    raise RuntimeError('Core metadata does not match this executable')
  core = json.loads(embedded)
  if (core.get('protocol_version') != 4 or core.get('python') != {
      'version': '3.12.10', 'abi': 'cp312', 'platform': 'win_amd64'}):
    raise RuntimeError('Unsupported embedded Core identity')
  records = core.get('source_files', [])
  if not records:
    raise RuntimeError('Core has no source integrity inventory')
  for record in records:
    verifyFile(root, record)
  expected = {record['path'] for record in records if record['path'].endswith('.py')}
  actual = {path.relative_to(root).as_posix() for path in (root / 'python').rglob('*.py')}
  if actual != expected:
    raise RuntimeError('Unexpected or missing Core Python source files')
  runtime = core.get('runtime_files', [])
  if runtime:
    for record in runtime:
      verifyFile(root, record)
    expected = {record['path'] for record in runtime}
    actual = {path.relative_to(root).as_posix() for name in ('python', 'site-packages', 'native')
              for path in (root / name).rglob('*') if path.is_file()}
    if actual != expected:
      raise RuntimeError('Unexpected or missing Core runtime files')
  lock = checkedFile(root, 'dependency-lock.json')
  with lock.open('rb') as stream:
    if hashlib.file_digest(stream, 'sha256').hexdigest() != core['dependency_lock_sha256']:
      raise RuntimeError('Core dependency lock does not match its metadata')
  for record in core.get('native_dlls', []):
    verifyFile(root, record)
  return core


def configureCore(root: Path, core: dict) -> None:
  internal = Path(sys._MEIPASS).resolve()
  if not internal.is_relative_to(root):
    raise RuntimeError('The frozen interpreter is outside this Core')
  kept = [entry for entry in sys.path if entry and Path(entry).resolve().is_relative_to(root)]
  paths = []
  for relative in core['python_paths']:
    path = root / relative
    if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(root):
      raise RuntimeError('Core import directory is missing or outside this installation')
    paths.append(str(path))
  sys.path[:] = paths + [entry for entry in kept if entry not in paths]
  for directory in [internal, *(root / item for item in core['dll_dirs'])]:
    if not directory.is_dir() or not directory.resolve().is_relative_to(root):
      raise RuntimeError('Core native directory is missing or outside this installation')
  # Only the frozen standard library needs a search directory before the manager.
  # RuntimeGuard.mount owns the one registration of verified Core/module dirs.
  # Registering those dirs here too can exhaust the Windows search-path budget.
  DLL_HANDLES.append(os.add_dll_directory(str(internal)))
  for record in core.get('preload_dlls', []):
    path = verifyFile(root, record)
    DLL_HANDLES.append(ctypes.CDLL(str(path), winmode=0x1100))
  qt = root / 'site-packages/PyQt5/Qt5'
  plugins = qt / 'plugins'
  webengine = qt / 'bin/QtWebEngineProcess.exe'
  if not plugins.is_dir() or not webengine.is_file():
    raise RuntimeError('Core Qt plugins or WebEngine process are missing')
  os.environ['QT_PLUGIN_PATH'] = str(plugins)
  os.environ['QTWEBENGINEPROCESS_PATH'] = str(webengine)
  os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
  os.environ['PYTHONNOUSERSITE'] = '1'
  os.environ['HF_HUB_OFFLINE'] = '1'
  os.environ['TRANSFORMERS_OFFLINE'] = '1'
  os.environ['YOLO_AUTOINSTALL'] = 'false'
  sys.dont_write_bytecode = True


def main() -> int:
  if (not getattr(sys, 'frozen', False) or os.name != 'nt'
      or platform.python_version() != '3.12.10'):
    raise RuntimeError('This entry requires the built Windows CPython 3.12.10 Core')
  root = Path(sys.executable).resolve().parent
  core = verifyCore(root, EMBEDDED_CORE_JSON)
  configureCore(root, core)
  import module_runtime

  if Path(module_runtime.__file__).resolve() != root / 'python/module_runtime.py':
    raise RuntimeError('The module manager was not loaded from this verified Core')
  return module_runtime.launch(root, core)


def reportFailure(error: Exception) -> int:
  record = {'status': 'FAIL', 'stage': 'modular-core-bootstrap',
            'error_type': type(error).__name__, 'error': str(error),
            'traceback': traceback.format_exc(), 'executable': sys.executable,
            'python': platform.python_version()}
  destination = None
  try:
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
    directory = base / 'VisionWorkshop/logs'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ('modular-bootstrap-' + time.strftime('%Y%m%dT%H%M%S')
                               + '-' + str(os.getpid()) + '.json')
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
  except OSError:
    destination = None
  output = json.dumps(dict(record, diagnostic_file=str(destination) if destination else None),
                       ensure_ascii=False) + '\n'
  if sys.stderr is not None:
    sys.stderr.write(output)
    sys.stderr.flush()
  elif os.name == 'nt':
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    kernel.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
    data = output.encode('utf-8')
    buffer = ctypes.create_string_buffer(data)
    written = ctypes.c_ulong()
    kernel.WriteFile(kernel.GetStdHandle(-12), buffer, len(data), ctypes.byref(written), None)
  flags = {'--offline-modules', '--modular-runtime-check', '--cnn-patchcore-onnx-worker',
           '--dino-onnx-worker', '--cnn-patchcore-pt-worker', '--multiprocessing-fork', '-c'}
  if os.name == 'nt' and not any(argument in flags for argument in sys.argv[1:]):
    message = ('VisionWorkshop could not verify or start this Core.\n\n' + str(error)
               + '\n\nDiagnostic: ' + (str(destination) if destination else 'Cannot write diagnostic')
               + '\n\nFor a module rollback, close all application processes, then run:\n'
               + 'VisionWorkshop.exe --offline-modules rollback\n'
               + 'VisionWorkshop.exe --offline-modules activate\n'
               + 'If Core integrity failed, restore the matching Core package.')
    ctypes.windll.user32.MessageBoxW(None, message, 'VisionWorkshop startup failed', 0x10)
  return 1


if __name__ == '__main__':
  try:
    raise SystemExit(main())
  except Exception as error:
    raise SystemExit(reportFailure(error))
