"""Build a disposable frozen Core and observe external runtime loading on Windows."""

import argparse
import base64
import csv
import ctypes
import hashlib
import importlib.metadata
import io
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
BOOTSTRAP_MODULES = {'struct', 'pyimod01_archive', 'pyimod02_importers',
                     'pyimod03_ctypes', 'pyimod04_pywin32'}
TORCHVISION_PYTHON = {
  'path': 'torchvision/python312.dll', 'bytes': 7470920,
  'sha256': '3436d46bb65a87ba3d215df065f010d9fdab18c994caa275b546b8877b5205b2',
  'machine': 0x8664, 'file_version': '3.12.12150.1013', 'product_version': '3.12.12',
}
TORCHVISION_WHEEL_SHA256 = '068e519838b4a8b32a09521244b170edd8c2ac9eeb6538b7bf492cd70e57ebf5'
TORCHVISION_WHEEL_URL = (
  'https://download-r2.pytorch.org/whl/cu128/'
  'torchvision-0.25.0%2Bcu128-cp312-cp312-win_amd64.whl')


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


def nativeIdentity(path: Path) -> dict:
  import pefile

  with pefile.PE(str(path)) as binary:
    fixed = binary.VS_FIXEDFILEINFO[0]
    versions = {}
    for block in getattr(binary, 'FileInfo', []):
      for item in block:
        for table in getattr(item, 'StringTable', []):
          versions.update(table.entries)
    return {
      'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': fileHash(path),
      'machine': binary.FILE_HEADER.Machine,
      'file_version': '.'.join(map(str, (fixed.FileVersionMS >> 16,
        fixed.FileVersionMS & 65535, fixed.FileVersionLS >> 16, fixed.FileVersionLS & 65535))),
      'product_version': versions.get(b'ProductVersion', b'').decode('utf-8'),
    }


def verifyPythonConsumer(consumer: Path, owner: Path) -> dict:
  import pefile

  with pefile.PE(str(consumer)) as binary, pefile.PE(str(owner)) as python:
    imports = [symbol.name for entry in binary.DIRECTORY_ENTRY_IMPORT
                if entry.dll.lower() == b'python312.dll' for symbol in entry.imports]
    exports = {symbol.name for symbol in python.DIRECTORY_ENTRY_EXPORT.symbols if symbol.name}
    if not imports or any(name is None or name not in exports for name in imports):
      raise ValueError('TorchVision image extension requires Python symbols absent from Core')
    return {'path': str(consumer.resolve()), 'sha256': fileHash(consumer),
            'python_import_count': len(imports), 'missing_python_exports': [],
            'owner_sha256': fileHash(owner)}


def qualifyVendoredPython(source: Path, relative: Path, corePython: Path | None,
                          torchInstallReport: Path | None) -> dict:
  if relative.as_posix() != TORCHVISION_PYTHON['path']:
    raise ValueError('External runtime must not contain another Python: ' + str(relative))
  if corePython is None or torchInstallReport is None:
    raise ValueError('Known TorchVision Python duplicate requires Core and wheel provenance')
  report = json.loads(torchInstallReport.read_text(encoding='utf-8-sig'))
  installed = [item for item in report['install']
                if canonicalName(item['metadata']['name']) == 'torchvision']
  if (len(installed) != 1 or installed[0]['metadata']['version'] != RUNTIME_VERSIONS['torchvision']
      or installed[0]['download_info']['url'] != TORCHVISION_WHEEL_URL
      or installed[0]['download_info']['archive_info']['hashes'].get('sha256')
        != TORCHVISION_WHEEL_SHA256):
    raise ValueError('TorchVision duplicate does not identify the reviewed wheel')
  distributions = [item for item in importlib.metadata.distributions(path=[str(source)])
                    if canonicalName(item.metadata.get('Name', '')) == 'torchvision']
  if len(distributions) != 1 or distributions[0].version != RUNTIME_VERSIONS['torchvision']:
    raise ValueError('TorchVision duplicate has ambiguous or unexpected installed owner')
  records = [row for row in csv.reader(io.StringIO(distributions[0].read_text('RECORD') or ''))
              if row and row[0].replace('\\', '/') == TORCHVISION_PYTHON['path']]
  digest = base64.urlsafe_b64encode(bytes.fromhex(TORCHVISION_PYTHON['sha256'])).decode().rstrip('=')
  hashed = [row for row in records if row[1:] == [
    'sha256=' + digest, str(TORCHVISION_PYTHON['bytes'])]]
  aliases = [row for row in records if row == [TORCHVISION_PYTHON['path'], '', '']]
  # The wheel uses a backslash RECORD path. pip preserves it and adds the
  # installed slash path with blank hash/size; both identify this same file.
  if len(hashed) != 1 or len(aliases) > 1 or len(records) != len(hashed) + len(aliases):
    raise ValueError('TorchVision duplicate has conflicting installed RECORD ownership: '
                     + repr(records[:4]))
  duplicate = nativeIdentity(source / relative)
  if any(duplicate[key] != expected for key, expected in TORCHVISION_PYTHON.items() if key != 'path'):
    raise ValueError('TorchVision duplicate DLL bytes, PE architecture or version changed')
  rejectLink(corePython)
  owner = nativeIdentity(corePython)
  if (corePython.name != 'python312.dll' or isInside(corePython, source)
      or owner['machine'] != 0x8664 or owner['product_version'] != PYTHON_VERSION):
    raise ValueError('Core must own the selected AMD64 CPython ' + PYTHON_VERSION)
  consumer = verifyPythonConsumer(source / 'torchvision/image.pyd', corePython)
  return {
    'path': relative.as_posix(), 'excluded_file': duplicate, 'owner': owner,
    'distribution': 'torchvision', 'distribution_version': RUNTIME_VERSIONS['torchvision'],
    'wheel_url': TORCHVISION_WHEEL_URL, 'wheel_sha256': TORCHVISION_WHEEL_SHA256,
    'wheel_record': hashed[0], 'installed_record_aliases': aliases, 'consumer': consumer,
    'reason': 'Reviewed CP312 wheel duplicate omitted; the frozen Core is the only Python owner',
    'runtime_acceptance': 'Requires actual image encode/decode and Core-only Python DLL loading',
  }


def copyRuntime(source: Path, destination: Path, crtWheel: Path, *,
                corePython: Path | None = None,
                torchInstallReport: Path | None = None) -> tuple[list[dict], dict, list[dict]]:
  if destination.exists():
    raise FileExistsError('Runtime destination must be new')
  destination.mkdir(parents=True)
  records = []
  omitted = []
  for path in sorted(source.rglob('*')):
    relative = path.relative_to(source)
    if isExcluded(relative):
      continue
    rejectLink(path)
    if path.is_dir():
      continue
    if isInterpreterFile(path):
      omitted.append(qualifyVendoredPython(source, relative, corePython, torchInstallReport))
      continue
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
  return records, crt, omitted


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
    if key.upper() == 'PATH' or key.upper().startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV')):
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


def cleanBuildEnvironment(info: dict, output: Path) -> dict:
  environment = cleanEnvironment(output)
  base = Path(info['base_prefix']).resolve()
  system = Path(os.environ['SystemRoot']).resolve()
  environment['PATH'] = os.pathsep.join(str(path) for path in (
    base, base / 'DLLs', system / 'System32', system))
  return environment


def validateBinarySources(analysis: dict, info: dict, system: Path) -> list[dict]:
  owners = [('build_venv', Path(info['prefix'])), ('python_base', Path(info['base_prefix'])),
            ('windows_system', system / 'System32'), ('windows_system', system / 'WinSxS')]
  records = []
  for destination, source, kind in analysis['binaries']:
    path = Path(source)
    owner = next((name for name, root in owners if isInside(path, root)), None)
    if not path.is_absolute() or owner is None:
      raise ValueError('Core native dependency came from an unapproved build source: ' + source)
    rejectLink(path)
    records.append({'destination': destination, 'path': str(path.resolve()), 'owner': owner,
                    'kind': kind, 'bytes': path.stat().st_size, 'sha256': fileHash(path)})
  return sorted(records, key=lambda item: item['destination'])


def validateArchiveInventory(record: dict, executable: Path) -> None:
  identity = record.get('executable', {})
  archive = record.get('archive', {})
  if (record.get('schema_version') != 1
      or record.get('reader_version') != BUILD_VERSIONS['pyinstaller']
      or identity.get('path') != str(executable.resolve())
      or identity.get('bytes') != executable.stat().st_size
      or identity.get('sha256') != fileHash(executable)
      or archive.get('python_version') != 312
      or archive.get('python_library') != 'python312.dll'):
    raise ValueError('CArchive build evidence does not identify the selected frozen Core')
  modules = record.get('bootstrap_modules', {})
  members = record.get('members', [])
  indexed = {item['name']: item for item in members}
  embedded = {name for name, item in indexed.items() if item['archive_type'] in {'m', 'M'}}
  if (set(modules) != BOOTSTRAP_MODULES or embedded != BOOTSTRAP_MODULES
      or len(indexed) != len(members)):
    raise ValueError('CArchive bootstrap inventory must contain exactly the pinned module set')
  for name, module in modules.items():
    member = indexed[name]
    if (module.get('archive_type') != member['archive_type']
        or module.get('payload_sha256') != member['payload_sha256']
        or not re.fullmatch('[0-9a-f]{64}', module.get('payload_sha256', ''))
        or module.get('code_filename') != name + '.py'):
      raise ValueError('CArchive bootstrap payload evidence mismatch: ' + name)


def validateBootstrapReport(report: dict, record: dict, executable: Path) -> None:
  archive = report.get('bootstrap_archive', {})
  expected = record['archive']
  if (archive.get('path') != str(executable.resolve())
      or archive.get('sha256') != record['executable']['sha256']
      or archive.get('python_version') != expected['python_version']
      or archive.get('python_library') != expected['python_library']):
    raise ValueError('Frozen bootstrap archive differs from the independently inspected Core')
  modules = report.get('bootstrap_modules', {})
  if set(modules) != BOOTSTRAP_MODULES:
    raise ValueError('Frozen bootstrap report must contain exactly the pinned module set')
  for name, module in modules.items():
    expectedModule = record['bootstrap_modules'][name]
    if (any(module.get(key) != expectedModule[key] for key in (
        'archive_type', 'payload_sha256', 'code_filename'))
        or module.get('module_file') != expectedModule['code_filename']):
      raise ValueError('Frozen bootstrap does not match the embedded code payload: ' + name)


def validateProbeReport(report: dict, *, mode: str, runId: str, pid: int,
                        executable: Path, runtime: Path, source: Path, archive: dict) -> None:
  if (report.get('schema_version') != 1 or report.get('status') != 'PASS'
      or report.get('mode') != mode or report.get('run_id') != runId
      or report.get('pid') != pid or report.get('frozen') is not True
      or report.get('python') != PYTHON_VERSION):
    raise ValueError('Frozen probe identity/status mismatch')
  reportedExe = report.get('sys_executable', report.get('executable', ''))
  if not reportedExe or Path(reportedExe).resolve() != executable.resolve():
    raise ValueError('Frozen probe did not execute the selected Core executable')
  validateBootstrapReport(report, archive, executable)
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
                      executable=executable, runtime=runtime, source=source,
                      archive=json.loads((reports / 'core-carchive.json').read_text(encoding='utf-8')))
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
                          executable=executable, runtime=runtime, source=source,
                          archive=json.loads((reports / 'core-carchive.json').read_text(encoding='utf-8')))
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


def inspectCoreArchive(python: Path, executable: Path, reports: Path,
                       environment: dict) -> dict:
  program = '''import hashlib
import importlib.metadata
import json
import marshal
from pathlib import Path
import struct
import sys
import types
from PyInstaller.archive.readers import CArchiveReader

executable = Path(sys.argv[1]).resolve()
archive = CArchiveReader(str(executable))
with executable.open('rb') as stream:
  executableHash = hashlib.file_digest(stream, 'sha256').hexdigest()
  stream.seek(archive._end_offset - archive._COOKIE_LENGTH)
  cookie = struct.unpack(archive._COOKIE_FORMAT, stream.read(archive._COOKIE_LENGTH))
record = {
  'schema_version': 1, 'reader': 'PyInstaller.archive.readers.CArchiveReader',
  'reader_version': importlib.metadata.version('pyinstaller'),
  'executable': {'path': str(executable), 'bytes': executable.stat().st_size,
                 'sha256': executableHash},
  'archive': {'python_version': cookie[4],
              'python_library': cookie[5].rstrip(b'\\0').decode('utf-8'),
              'start_offset': archive._start_offset, 'end_offset': archive._end_offset},
  'options': archive.options, 'members': [], 'bootstrap_modules': {},
}
for name, (offset, packed, unpacked, compression, kind) in sorted(archive.toc.items()):
  payload = archive.extract(name)
  if len(payload) != unpacked:
    raise ValueError('CArchive member length mismatch: ' + name)
  payloadHash = hashlib.sha256(payload).hexdigest()
  record['members'].append({
    'name': name, 'archive_type': kind, 'offset': offset, 'compressed_bytes': packed,
    'bytes': unpacked, 'compression': compression, 'payload_sha256': payloadHash,
  })
  if kind in {'m', 'M'}:
    code = marshal.loads(payload)
    if not isinstance(code, types.CodeType):
      raise ValueError('CArchive bootstrap member is not a code object: ' + name)
    record['bootstrap_modules'][name] = {
      'archive_type': kind, 'payload_sha256': payloadHash, 'code_filename': code.co_filename,
    }
Path(sys.argv[2]).write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\\n',
                            encoding='utf-8')
print(json.dumps({'members': len(record['members']),
                  'bootstrap_modules': sorted(record['bootstrap_modules'])}))
'''
  destination = reports / 'core-carchive.json'
  runCommand([str(python), '-I', '-B', '-c', program, str(executable), str(destination)],
             reports, 'core-carchive-inspection', cwd=reports.parent / 'compiler-input',
             env=environment)
  record = json.loads(destination.read_text(encoding='utf-8'))
  validateArchiveInventory(record, executable)
  return record


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
  environment = cleanBuildEnvironment(info, output)
  writeReport(reports / 'core-build-environment.json', {
    'executable': str(python), 'cwd': str(specRoot), 'path': environment['PATH'].split(os.pathsep),
    'removed_inherited_variable_names': sorted(key for key in os.environ
      if key.upper() == 'PATH' or key.upper().startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV'))),
    'python_isolated_mode': True,
  })
  runCommand(command, reports, 'core-build', timeout=900, cwd=specRoot, env=environment)
  analysis = json.loads((reports / 'core-analysis.json').read_text(encoding='utf-8'))
  sources = validateBinarySources(analysis, info, Path(os.environ['SystemRoot']).resolve())
  writeReport(reports / 'core-binary-sources.json', {
    'status': 'PASS', 'python_base': info['base_prefix'], 'build_venv': info['prefix'],
    'windows_system_roots': [str(Path(os.environ['SystemRoot']) / name)
                             for name in ('System32', 'WinSxS')],
    'files': sources,
  })
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
  if any(item[0].split('.')[0] in banned for item in analysis['pure']):
    raise RuntimeError('Core PYZ unexpectedly bundled an optional third-party package')
  inspectCoreArchive(python, executable, reports, environment)
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
  parser.add_argument('--torch-install-report', required=True, type=Path)
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
    interpreterPreflight = qualifyVendoredPython(
      Path(runtimeInfo['purelib']), Path(TORCHVISION_PYTHON['path']),
      Path(buildInfo['base_prefix']) / 'python312.dll', args.torch_install_report.resolve())
    writeReport(reports / 'interpreter-ownership-preflight.json', {
      'scope': 'Compiler/runtime inputs before freezing; final Core and loaded DLLs checked later',
      'status': 'PASS', 'reviewed_duplicate': interpreterPreflight,
    })
    executable = buildCore(buildPython, buildInfo, output, reports)
    coreFiles = inventory(executable.parent)
    writeReport(reports / 'core-files.json', {'files': coreFiles})
    summary['core'] = summarizeFiles(coreFiles)
    runtime = executable.parent.parent / 'runtime/site-packages'
    environment = cleanEnvironment(output)
    (output / 'empty-cwd').mkdir()
    summary['cases'].append(runProbe(executable, runtime, source, reports, environment,
                                      'core', 'core-without-runtime', args.timeout))
    runtimeFiles, crt, omitted = copyRuntime(
      Path(runtimeInfo['purelib']), runtime, args.crt_wheel.resolve(),
      corePython=executable.parent / '_internal/python312.dll',
      torchInstallReport=args.torch_install_report.resolve())
    summary['runtime'] = summarizeFiles(runtimeFiles)
    summary['runtime']['crt'] = crt
    summary['runtime']['excluded_vendored_python'] = omitted
    writeReport(reports / 'runtime-files.json', {'files': runtimeFiles, 'crt': crt,
                                                'excluded_vendored_python': omitted})
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
