"""Build a disposable frozen Core and observe external runtime loading on Windows."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = '3.12.10'
BUILD_VERSIONS = {'pyinstaller': '6.18.0', 'pyinstaller-hooks-contrib': '2026.0'}
RUNTIME_VERSIONS = {
  'torch': '2.10.0+cu128', 'torchvision': '0.25.0+cu128', 'numpy': '2.0.2',
  'onnx': '1.16.0', 'onnxruntime-gpu': '1.23.2', 'pillow': '12.0.0',
  'psutil': '7.2.1', 'pyqt5': '5.15.9', 'pyqt5-qt5': '5.15.2',
  'pyqt5-sip': '12.18.0',
}
CRT_SHA256 = 'a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde'
CRT_WHEEL_SHA256 = 'a16dcec078a01eeef8ee61bf64074b4e524a2a3f4b3be9326420cabe59c4778b'
CRT_WHEEL_MEMBER = 'pandas.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll'
EXCLUDED_ROOTS = {'pip', 'pip.py', 'pyinstaller', '_pyinstaller_hooks_contrib',
                  'altgraph', 'pefile.py', 'peutils.py', 'pytest', '_pytest'}
STDLIB_EXCLUDED = {'site-packages', 'test', 'tests', 'idlelib', 'tkinter', '_tkinter', 'turtle', 'turtledemo',
                   'ensurepip', 'venv', '__pycache__', '__phello__'}


def writeReport(path: Path, document: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fileHash(path: Path) -> str:
  result = hashlib.sha256()
  with path.open('rb') as stream:
    for chunk in iter(lambda: stream.read(4 * 1024 ** 2), b''):
      result.update(chunk)
  return result.hexdigest()


def objectHash(document) -> str:
  payload = json.dumps(document, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False).encode('utf-8')
  return hashlib.sha256(payload).hexdigest()


def canonicalName(name: str) -> str:
  return re.sub(r'[-_.]+', '-', name).lower()


def isInside(path: Path, parent: Path) -> bool:
  try:
    path.resolve().relative_to(parent.resolve())
    return True
  except ValueError:
    return False


def rejectLink(path: Path) -> None:
  stat = path.lstat()
  if path.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
    raise ValueError('Probe payload cannot contain links/reparse points: ' + str(path))


def isInterpreterFile(path: Path) -> bool:
  return bool(re.fullmatch(r'python(?:w|\d+(?:_d)?)?\.(?:exe|dll)', path.name.lower()))


def isExcluded(relative: Path) -> bool:
  root = relative.parts[0].lower()
  if '__pycache__' in relative.parts or relative.suffix.lower() == '.pyc':
    return True
  if root in EXCLUDED_ROOTS:
    return True
  if root.endswith(('.dist-info', '.egg-info')):
    distribution = canonicalName(root.split('-')[0])
    return distribution in {'pip', 'pyinstaller', 'altgraph', 'pefile', 'pytest'} or root.startswith(
      ('pyinstaller_hooks_contrib-', 'pyinstaller-hooks-contrib-'))
  return False


def runCommand(command: list[str], logRoot: Path, name: str,
               timeout: int = 600, cwd: Path | None = None, env: dict | None = None) -> str:
  logRoot.mkdir(parents=True, exist_ok=True)
  started = time.monotonic()
  with (logRoot / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
       (logRoot / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
    try:
      code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
      process.kill()
      process.wait(timeout=15)
      writeReport(logRoot / (name + '.process.json'), {
        'status': 'TIMEOUT', 'pid': process.pid, 'timeout_seconds': timeout,
        'elapsed_seconds': round(time.monotonic() - started, 3),
      })
      raise
  writeReport(logRoot / (name + '.process.json'), {
    'status': 'PASS' if code == 0 else 'FAIL', 'pid': process.pid, 'exit_code': code,
    'elapsed_seconds': round(time.monotonic() - started, 3), 'command': command,
  })
  output = (logRoot / (name + '.stdout.txt')).read_text(encoding='utf-8-sig')
  if code:
    raise RuntimeError(f'{name} exited with {code}; see captured process/stdout/stderr reports')
  return output


def inspectPython(executable: Path, reports: Path, name: str) -> dict:
  program = (
    'import importlib.metadata as m,json,sys,sysconfig; '
    'print(json.dumps({"executable":sys.executable,"version":sys.version.split()[0],'
    '"prefix":sys.prefix,"base_prefix":sys.base_prefix,"platform":sys.platform,'
    '"purelib":sysconfig.get_path("purelib"),"stdlib":sysconfig.get_path("stdlib"),'
    '"stdlib_names":sorted(sys.stdlib_module_names),'
    '"distributions":[{"name":d.metadata["Name"],"version":d.version,'
    '"path":str(d._path)} for d in m.distributions()]}))'
  )
  result = json.loads(runCommand([str(executable), '-I', '-B', '-c', program], reports, name))
  if result['version'] != PYTHON_VERSION or result['platform'] != 'win32':
    raise ValueError(f'{name} must be Windows CPython {PYTHON_VERSION}')
  if result['prefix'] == result['base_prefix']:
    raise ValueError(name + ' must be a dedicated build-only virtual environment')
  writeReport(reports / (name + '.json'), result)
  return result


def validateVersions(info: dict, expected: dict) -> None:
  found = {}
  for item in info['distributions']:
    name = canonicalName(item['name'])
    if name in found:
      raise ValueError('Duplicate installed distribution: ' + name)
    found[name] = item['version']
  for name, version in expected.items():
    if found.get(name) != version:
      raise ValueError(f'Unexpected runtime version: {name}: {found.get(name)!r} != {version}')
  if 'onnxruntime-gpu' in expected and 'onnxruntime' in found:
    raise ValueError('Probe requires one ORT distribution; CPU/GPU packages cannot coexist')


def collectStdlibModules(info: dict) -> list[str]:
  stdlib = Path(info['stdlib'])
  names = set(info['stdlib_names'])
  for path in stdlib.rglob('*.py'):
    relative = path.relative_to(stdlib)
    if any(part in STDLIB_EXCLUDED for part in relative.parts):
      continue
    parts = list(relative.with_suffix('').parts)
    if parts[-1] in {'__main__', 'setup'}:
      continue
    if parts[-1] == '__init__':
      parts.pop()
    if parts and all(part.isidentifier() for part in parts):
      names.add('.'.join(parts))
  return sorted(name for name in names if name.split('.')[0] not in STDLIB_EXCLUDED
                and not name.startswith(('_test', 'test.')))


def inventory(root: Path) -> list[dict]:
  records = []
  for path in sorted(root.rglob('*')):
    rejectLink(path)
    if path.is_file():
      records.append({'path': path.relative_to(root).as_posix(),
                      'bytes': path.stat().st_size, 'sha256': fileHash(path)})
  return sorted(records, key=lambda item: item['path'])


def summarizeFiles(records: list[dict]) -> dict:
  return {'file_count': len(records), 'bytes': sum(item['bytes'] for item in records),
          'files_sha256': objectHash(records)}


def extractCrt(wheel: Path, destination: Path) -> dict:
  if fileHash(wheel) != CRT_WHEEL_SHA256:
    raise ValueError('CRT source wheel does not match the reviewed CP312 Windows wheel')
  with zipfile.ZipFile(wheel) as archive:
    member = archive.getinfo(CRT_WHEEL_MEMBER)
    payload = archive.read(member)
    if len(payload) != 575056 or hashlib.sha256(payload).hexdigest() != CRT_SHA256:
      raise ValueError('Pinned MSVCP source does not match the validated runtime')
    crt = destination / 'msvcp140.dll'
    with crt.open('xb') as stream:
      stream.write(payload)
    licenseNames = [name for name in archive.namelist()
                    if name == 'pandas-2.3.3.dist-info/LICENSE'
                    or (name.startswith('pandas-2.3.3.dist-info/licenses/') and not name.endswith('/'))]
    if not licenseNames:
      raise ValueError('The verified CRT wheel has no packaged license evidence')
    licenses = []
    for name in licenseNames:
      relative = ('LICENSE' if name == 'pandas-2.3.3.dist-info/LICENSE'
                  else name.removeprefix('pandas-2.3.3.dist-info/licenses/'))
      target = destination / 'vw_probe_native_licenses/pandas' / relative
      target.parent.mkdir(parents=True, exist_ok=True)
      with target.open('xb') as stream:
        stream.write(archive.read(name))
      licenses.append({'path': target.relative_to(destination).as_posix(),
                       'sha256': fileHash(target)})
  return {'wheel': wheel.name, 'wheel_sha256': CRT_WHEEL_SHA256,
          'member': CRT_WHEEL_MEMBER, 'destination': 'msvcp140.dll',
          'bytes': 575056, 'sha256': CRT_SHA256, 'licenses': licenses,
          'reason': 'Known product CRT loaded before Qt; no host/system fallback'}


def copyRuntime(source: Path, destination: Path, crtWheel: Path) -> tuple[list[dict], dict]:
  if destination.exists():
    raise FileExistsError('Runtime destination must be new')
  destination.mkdir(parents=True)
  records = []
  for path in sorted(source.rglob('*')):
    relative = path.relative_to(source)
    if isExcluded(relative):
      continue
    rejectLink(path)
    if path.is_dir():
      continue
    if isInterpreterFile(path):
      raise ValueError('External runtime must not contain another Python: ' + str(relative))
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    records.append({'path': relative.as_posix(), 'bytes': target.stat().st_size,
                    'sha256': fileHash(target)})
  crt = extractCrt(crtWheel, destination)
  for relative in ['msvcp140.dll', *[item['path'] for item in crt['licenses']]]:
    target = destination / relative
    records.append({'path': relative, 'bytes': target.stat().st_size, 'sha256': fileHash(target)})
  records.sort(key=lambda item: item['path'])
  return records, crt


def writePureFixture(runtime: Path, marker: str, version: str) -> None:
  package = runtime / 'vw_external_fixture'
  package.mkdir(exist_ok=True)
  (package / '__init__.py').write_text('MARKER = ' + repr(marker) + '\n', encoding='utf-8')
  for previous in runtime.glob('vw_external_fixture-*.dist-info'):
    shutil.rmtree(previous)
  metadata = runtime / ('vw_external_fixture-' + version + '.dist-info')
  metadata.mkdir()
  (metadata / 'METADATA').write_text(
    'Metadata-Version: 2.1\nName: vw-external-fixture\nVersion: ' + version + '\n',
    encoding='utf-8',
  )


def cleanEnvironment(output: Path) -> dict:
  environment = os.environ.copy()
  for key in list(environment):
    if key.upper().startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV')):
      environment.pop(key)
  system = Path(os.environ['SystemRoot'])
  user = output / 'isolated-user'
  temporary = output / 'isolated-temp'
  for folder in (user, temporary, user / 'AppData/Local', user / 'AppData/Roaming'):
    folder.mkdir(parents=True, exist_ok=True)
  environment.update({
    'PATH': str(system / 'System32') + os.pathsep + str(system),
    'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
    'PYTHONIOENCODING': 'utf-8', 'QT_QPA_PLATFORM': 'offscreen',
    'USERPROFILE': str(user), 'LOCALAPPDATA': str(user / 'AppData/Local'),
    'APPDATA': str(user / 'AppData/Roaming'), 'TEMP': str(temporary), 'TMP': str(temporary),
    'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1', 'YOLO_AUTOINSTALL': 'false',
    'TORCH_HOME': str(user / 'torch-cache'), 'HF_HOME': str(user / 'huggingface-cache'),
    'XDG_CACHE_HOME': str(user / 'cache'),
  })
  return environment


def validateProbeReport(report: dict, *, mode: str, runId: str, pid: int,
                        executable: Path, runtime: Path, source: Path) -> None:
  if (report.get('schema_version') != 1 or report.get('status') != 'PASS'
      or report.get('mode') != mode or report.get('run_id') != runId
      or report.get('pid') != pid or report.get('frozen') is not True
      or report.get('python') != PYTHON_VERSION):
    raise ValueError('Frozen probe identity/status mismatch')
  reportedExe = report.get('sys_executable', report.get('executable', ''))
  if not reportedExe or Path(reportedExe).resolve() != executable.resolve():
    raise ValueError('Frozen probe did not execute the selected Core executable')
  origins = report.get('module_origins', report.get('imports', {}))
  if not isinstance(origins, dict):
    raise ValueError('Frozen probe must expose actual imported file origins')
  for name, origin in origins.items():
    if not isinstance(origin, str) or not Path(origin).is_absolute():
      raise ValueError('Invalid import origin: ' + name)
    if not any(isInside(Path(origin), allowed) for allowed in (runtime, executable.parent, source)):
      raise ValueError('Import escaped Core/external runtime/first-party source: ' + origin)
    if not name.startswith(('anomaly_func', 'dino_', 'patchcore_')) and isInside(Path(origin), source):
      raise ValueError('Third-party dependency resolved from application checkout: ' + name)
  required = {'pure': ('vw_external_fixture',), 'native': ('numpy', 'psutil', 'PyQt5.QtCore'),
              'torch': ('torch', 'torchvision'), 'ort': ('onnxruntime',),
              'dino': ('onnxruntime',), 'hold': ('psutil',)}.get(mode, ())
  for name in required:
    if name not in origins or not isInside(Path(origins[name]), runtime):
      raise ValueError('Required dependency was not loaded from the external runtime: ' + name)


def runProbe(executable: Path, runtime: Path, source: Path, reports: Path,
             environment: dict, mode: str, name: str, timeout: int,
             extraJob: dict | None = None) -> dict:
  runId = uuid.uuid4().hex
  job = {'run_id': runId, **(extraJob or {})}
  jobPath = reports / (name + '.job.json')
  reportPath = reports / (name + '.json')
  writeReport(jobPath, job)
  command = [str(executable), '--runtime-root', str(runtime), '--source-root', str(source),
             '--mode', mode, '--report', str(reportPath), '--job', str(jobPath)]
  runCommand(command, reports, name, timeout=timeout, cwd=reports.parent / 'empty-cwd',
             env=environment)
  report = json.loads(reportPath.read_text(encoding='utf-8-sig'))
  process = json.loads((reports / (name + '.process.json')).read_text(encoding='utf-8'))
  validateProbeReport(report, mode=mode, runId=runId, pid=process['pid'],
                      executable=executable, runtime=runtime, source=source)
  return {'name': name, 'mode': mode, 'report': reportPath.name,
          'process': name + '.process.json', 'status': 'PASS', 'run_id': runId,
          'gpu': report.get('gpu', {'status': 'NOT_RUN'})}


def openForWrite(path: Path) -> tuple[bool, int]:
  from ctypes import wintypes

  kernel = ctypes.WinDLL('kernel32', use_last_error=True)
  kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
  kernel.CreateFileW.restype = wintypes.HANDLE
  kernel.CloseHandle.argtypes = [wintypes.HANDLE]
  kernel.CloseHandle.restype = wintypes.BOOL
  ctypes.set_last_error(0)
  handle = kernel.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x80, None)
  if handle == wintypes.HANDLE(-1).value:
    return False, ctypes.get_last_error()
  kernel.CloseHandle(handle)
  return True, 0


def verifyLoadedFileLock(executable: Path, runtime: Path, source: Path, reports: Path,
                         environment: dict, timeout: int) -> dict:
  name, runId = 'loaded-pyd-lock', uuid.uuid4().hex
  release = reports / (name + '.release')
  reportPath = reports / (name + '.json')
  jobPath = reports / (name + '.job.json')
  writeReport(jobPath, {'run_id': runId, 'release_path': str(release),
                        'timeout_seconds': min(timeout, 120)})
  command = [str(executable), '--runtime-root', str(runtime), '--source-root', str(source),
             '--mode', 'hold', '--report', str(reportPath), '--job', str(jobPath)]
  started = time.monotonic()
  with (reports / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
       (reports / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen(command, cwd=reports.parent / 'empty-cwd', env=environment,
                               stdout=stdout, stderr=stderr)
    try:
      deadline = time.monotonic() + min(timeout, 90)
      ready = None
      while time.monotonic() < deadline:
        if reportPath.exists():
          try:
            candidate = json.loads(reportPath.read_text(encoding='utf-8-sig'))
          except json.JSONDecodeError:
            candidate = {}
          if candidate.get('status') == 'READY':
            ready = candidate
            break
        if process.poll() is not None:
          raise RuntimeError('Hold worker exited before its native extension was ready')
        time.sleep(.1)
      if ready is None or ready.get('run_id') != runId or ready.get('pid') != process.pid:
        raise RuntimeError('No matching READY report from the hold worker')
      target = Path(ready.get('hold_target', ''))
      if target.suffix.lower() != '.pyd' or not isInside(target, runtime):
        raise ValueError('Hold worker did not identify an external native extension')
      before = fileHash(target)
      writable, error = openForWrite(target)
      if writable or error not in (5, 32, 33):
        raise RuntimeError(f'Loaded .pyd write lock not observed: writable={writable}, error={error}')
      release.write_text('release\n', encoding='utf-8')
      code = process.wait(timeout=30)
      if code:
        raise RuntimeError('Hold worker failed to exit cleanly')
      afterWritable, afterError = openForWrite(target)
      if not afterWritable or fileHash(target) != before:
        raise RuntimeError('Native extension lock did not release without modifying its bytes')
      report = json.loads(reportPath.read_text(encoding='utf-8-sig'))
      validateProbeReport(report, mode='hold', runId=runId, pid=process.pid,
                          executable=executable, runtime=runtime, source=source)
      result = {'name': name, 'status': 'PASS', 'run_id': runId, 'pid': process.pid,
                'exit_code': code, 'target': str(target), 'sha256': before,
                'write_access_while_loaded': False, 'windows_error': error,
                'write_access_after_exit': True, 'after_exit_error': afterError,
                'bytes_written': 0, 'elapsed_seconds': round(time.monotonic() - started, 3)}
      writeReport(reports / (name + '.process.json'), result)
      return result
    finally:
      if process.poll() is None:
        release.write_text('release\n', encoding='utf-8')
        try:
          process.wait(timeout=10)
        except subprocess.TimeoutExpired:
          process.kill()
          process.wait(timeout=15)


def windowsFileVersion(path: Path) -> str:
  from ctypes import wintypes

  version = ctypes.WinDLL('version', use_last_error=True)
  version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
  version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
  version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                        wintypes.DWORD, wintypes.LPVOID]
  version.GetFileVersionInfoW.restype = wintypes.BOOL
  version.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                    ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(wintypes.UINT)]
  version.VerQueryValueW.restype = wintypes.BOOL
  ignored = wintypes.DWORD()
  size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
  if not size:
    raise ctypes.WinError(ctypes.get_last_error())
  data = ctypes.create_string_buffer(size)
  if not version.GetFileVersionInfoW(str(path), 0, size, data):
    raise ctypes.WinError(ctypes.get_last_error())
  pointer, length = ctypes.c_void_p(), wintypes.UINT()
  if not version.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)):
    raise ctypes.WinError(ctypes.get_last_error())
  if length.value < 13 * ctypes.sizeof(wintypes.DWORD):
    raise ValueError('Native file has no complete version record: ' + str(path))
  fixed = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents
  if fixed[0] != 0xFEEF04BD:
    raise ValueError('Native file version record has invalid signature')
  return '.'.join(map(str, (fixed[2] >> 16, fixed[2] & 65535,
                           fixed[3] >> 16, fixed[3] & 65535)))


def buildCore(python: Path, info: dict, output: Path, reports: Path) -> Path:
  import pprint

  specRoot = output / 'compiler-input'
  specRoot.mkdir()
  entry = ROOT / 'scripts/modular_probe_core.py'
  hiddenImports = collectStdlibModules(info)
  writeReport(reports / 'stdlib-hidden-imports.json', {'modules': hiddenImports})
  nativeFiles = []
  for name in ('python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
    path = Path(info['base_prefix']) / name
    rejectLink(path)
    nativeFiles.append({'path': str(path), 'destination': name, 'bytes': path.stat().st_size,
                        'sha256': fileHash(path), 'file_version': windowsFileVersion(path)})
  writeReport(reports / 'core-native-sources.json', {
    'python': info['version'], 'base_prefix': info['base_prefix'], 'files': nativeFiles,
    'scope': 'CPython stable ABI forwarder and CRT from exact build Python, no system fallback',
  })
  binaries = [(item['path'], '.') for item in nativeFiles]
  spec = specRoot / 'VisionWorkshopProbeCore.spec'
  spec.write_text(
    'import json\nfrom pathlib import Path\n'
    'a = Analysis(' + repr([str(entry)]) + ', pathex=[], binaries=' + repr(binaries) + ', datas=[],\n'
    '  hiddenimports=' + pprint.pformat(hiddenImports) + ',\n'
    '  hookspath=[], runtime_hooks=[], excludes=' + repr(sorted(STDLIB_EXCLUDED)) + ',\n'
    '  noarchive=False)\n'
    'Path(' + repr(str(reports / 'core-analysis.json')) + ').write_text(json.dumps({\n'
    '  "pure": list(a.pure), "binaries": list(a.binaries), "datas": list(a.datas)\n'
    '}), encoding="utf-8")\n'
    'pyz = PYZ(a.pure)\n'
    'exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VisionWorkshopProbeCore",\n'
    '  debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)\n'
    'coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,\n'
    '  name="VisionWorkshopProbeCore")\n', encoding='utf-8')
  command = [str(python), '-I', '-B', '-m', 'PyInstaller', '--clean', '--noconfirm',
             '--distpath', str(output / 'compiler-output'), '--workpath', str(output / 'compiler-work'),
             str(spec)]
  runCommand(command, reports, 'core-build', timeout=900, cwd=specRoot)
  built = output / 'compiler-output/VisionWorkshopProbeCore'
  install = output / 'probe-install/外置 模块/Core'
  install.parent.mkdir(parents=True)
  shutil.copytree(built, install)
  executable = install / 'VisionWorkshopProbeCore.exe'
  if not executable.is_file() or not (install / '_internal/python312.dll').is_file():
    raise RuntimeError('Minimal frozen Core was not created')
  for item in nativeFiles:
    if fileHash(install / '_internal' / item['destination']) != item['sha256']:
      raise RuntimeError('Core native file differs from exact build Python input')
  banned = {'torch', 'torchvision', 'onnxruntime', 'numpy', 'PyQt5', 'pandas'}
  if any((install / '_internal' / name).exists() for name in banned):
    raise RuntimeError('Core unexpectedly bundled an optional third-party package')
  analysis = json.loads((reports / 'core-analysis.json').read_text(encoding='utf-8'))
  if any(item[0].split('.')[0] in banned for item in analysis['pure']):
    raise RuntimeError('Core PYZ unexpectedly bundled an optional third-party package')
  return executable


def archiveCore(root: Path, output: Path) -> dict:
  output.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(root.rglob('*')):
      if path.is_file():
        archive.write(path, (Path('VisionWorkshopProbeCore') / path.relative_to(root)).as_posix())
  return {'path': str(output), 'bytes': output.stat().st_size, 'sha256': fileHash(output),
          'scope': 'B2 diagnostic Core only; not the product application or module installer'}


def parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--runtime-python', required=True, type=Path)
  parser.add_argument('--build-python', required=True, type=Path)
  parser.add_argument('--source-root', required=True, type=Path)
  parser.add_argument('--output', required=True, type=Path)
  parser.add_argument('--constraints', required=True, type=Path)
  parser.add_argument('--crt-wheel', required=True, type=Path)
  parser.add_argument('--timeout', type=int, default=180)
  return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
  args = parseArgs(argv)
  output = args.output.resolve()
  if output.exists() and any(output.iterdir()):
    raise FileExistsError('Use a new empty probe output directory: ' + str(output))
  output.mkdir(parents=True, exist_ok=True)
  reports = output / 'reports'
  reports.mkdir()
  summary = {'schema_version': 1, 'status': 'FAIL', 'scope': 'B2 frozen external runtime experiment',
             'product_acceptance': 'NOT_RUN', 'module_installation': 'NOT_IMPLEMENTED',
             'published': False, 'cases': [], 'gpu_hardware': 'NOT_RUN'}
  started = time.monotonic()
  try:
    if os.name != 'nt':
      raise RuntimeError('This experiment requires Windows; no Windows result was produced')
    source = args.source_root.resolve()
    runtimePython, buildPython = args.runtime_python.resolve(), args.build_python.resolve()
    if runtimePython == buildPython:
      raise ValueError('Use separate temporary runtime-staging and compiler environments')
    constraints = args.constraints.resolve()
    summary['constraints'] = {'path': str(constraints), 'sha256': fileHash(constraints)}
    summary['app_sha'] = runCommand(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                     reports, 'app-revision').strip()
    summary['packager_sha'] = runCommand(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                          reports, 'packager-revision').strip()
    runtimeInfo = inspectPython(runtimePython, reports, 'runtime-python')
    buildInfo = inspectPython(buildPython, reports, 'build-python')
    validateVersions(runtimeInfo, RUNTIME_VERSIONS)
    validateVersions(buildInfo, BUILD_VERSIONS)
    summary['python'] = PYTHON_VERSION
    summary['build_tools'] = BUILD_VERSIONS
    summary['runtime_distribution_inventory_sha256'] = objectHash(runtimeInfo['distributions'])
    runCommand([str(runtimePython), '-m', 'pip', 'check'], reports, 'runtime-pip-check')
    executable = buildCore(buildPython, buildInfo, output, reports)
    coreFiles = inventory(executable.parent)
    writeReport(reports / 'core-files.json', {'files': coreFiles})
    summary['core'] = summarizeFiles(coreFiles)
    runtime = executable.parent.parent / 'runtime/site-packages'
    environment = cleanEnvironment(output)
    (output / 'empty-cwd').mkdir()
    summary['cases'].append(runProbe(executable, runtime, source, reports, environment,
                                      'core', 'core-without-runtime', args.timeout))
    runtimeFiles, crt = copyRuntime(Path(runtimeInfo['purelib']), runtime, args.crt_wheel.resolve())
    summary['runtime'] = summarizeFiles(runtimeFiles)
    summary['runtime']['crt'] = crt
    writeReport(reports / 'runtime-files.json', {'files': runtimeFiles, 'crt': crt})
    writePureFixture(runtime, 'v1', '1.0.0')
    for mode in ('pure', 'native', 'torch', 'ort', 'dino'):
      extra = {'expected_marker': 'v1', 'expected_fixture_version': '1.0.0'} if mode == 'pure' else {}
      summary['cases'].append(runProbe(executable, runtime, source, reports, environment,
                                        mode, mode + '-external', args.timeout, extra))
    summary['cases'].append(verifyLoadedFileLock(executable, runtime, source, reports,
                                                environment, args.timeout))
    writePureFixture(runtime, 'v2', '2.0.0')
    summary['cases'].append(runProbe(executable, runtime, source, reports, environment,
                                      'pure', 'pure-fresh-reload', args.timeout,
                                      {'expected_marker': 'v2', 'expected_fixture_version': '2.0.0'}))
    summary['cases'].append(runProbe(executable, runtime, source, reports, environment,
                                      'ort', 'ort-fresh-reload', args.timeout))
    hidden = runtime.with_name('site-packages-not-installed')
    runtime.rename(hidden)
    try:
      summary['cases'].append(runProbe(executable, runtime, source, reports, environment,
                                        'core', 'core-after-runtime-removal', args.timeout))
    finally:
      hidden.rename(runtime)
    finalFiles = inventory(runtime)
    baseFiles = [item for item in finalFiles if not item['path'].startswith(
      ('vw_external_fixture/', 'vw_external_fixture-'))]
    if baseFiles != runtimeFiles or inventory(executable.parent) != coreFiles:
      raise RuntimeError('The probe changed Core or shared runtime payload bytes')
    summary['core_and_shared_runtime_unchanged'] = True
    summary['archive'] = archiveCore(executable.parent, output / 'archives/VisionWorkshopProbeCore.zip')
    summary['gpu_hardware'] = 'NOT_RUN'
    gpuReports = [case.get('gpu', {}).get('status') for case in summary['cases']
                  if case.get('mode') in ('torch', 'ort')]
    if gpuReports and all(status == 'PASS' for status in gpuReports):
      summary['gpu_hardware'] = 'PASS'
    summary['status'] = 'PASS' if summary['gpu_hardware'] == 'PASS' else 'LIMITED'
    summary['cpu_external_loader'] = 'PASS'
    summary['limitations'] = ['Diagnostic frozen Core, not complete product Core',
                              'No formal module installation/update/rollback implementation',
                              'No business model, training or full GUI acceptance']
    if summary['gpu_hardware'] != 'PASS':
      summary['limitations'].append('Physical CUDA operation not qualified')
    return 0
  except Exception as error:
    summary['error'] = str(error)
    summary['traceback'] = traceback.format_exc()
    print(summary['traceback'], file=sys.stderr)
    return 1
  finally:
    summary['elapsed_seconds'] = round(time.monotonic() - started, 3)
    writeReport(reports / 'modular-loader-summary.json', summary)
    print(json.dumps({'status': summary['status'], 'report': str(reports / 'modular-loader-summary.json')},
                      ensure_ascii=False), flush=True)


if __name__ == '__main__':
  raise SystemExit(main())
