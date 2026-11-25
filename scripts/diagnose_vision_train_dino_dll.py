"""Read-only DLL observations from one original Windows artifact; never product acceptance."""

import argparse
import ctypes
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


sys.dont_write_bytecode = True
CRT_NAMES = ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll')
TORCH_NAMES = ('torch_global_deps.dll', 'c10.dll', 'torch_cpu.dll', 'torch_python.dll')
CASES = ('baseline', 'numpy-first', 'root-crt', 'system32-crt', 'qt-crt',
         'torch-native', 'libiomp-only', 'qt-core-first', 'root-msvcp-qt', 'root-crt-qt')
SCOPE = ('DLL loading diagnosis only. No product files, dependency pins or runtime hooks '
         'are modified. A successful native load is not frozen product acceptance.')


def writeReport(path: Path, value: dict) -> None:
  path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fileHash(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open('rb') as stream:
    for block in iter(lambda: stream.read(4 * 1024 ** 2), b''):
      digest.update(block)
  return digest.hexdigest()


def exceptionRecord(error: Exception) -> dict:
  return {'type': type(error).__name__, 'message': str(error),
          'winerror': getattr(error, 'winerror', None), 'errno': getattr(error, 'errno', None)}


def modulePaths(pid: int | None = None) -> list[str]:
  import psutil

  process = psutil.Process(pid or os.getpid())
  return sorted({item.path for item in process.memory_maps(grouped=True)
                 if Path(item.path).suffix.lower() in ('.dll', '.pyd', '.exe')},
                key=str.casefold)


def isCrt(path: str) -> bool:
  return Path(path).name.lower().startswith(('msvcp', 'vcruntime', 'concrt', 'ucrtbase'))


def pythonScene() -> dict:
  return {'executable': sys.executable, 'version': sys.version, 'prefix': sys.prefix,
          'path': list(sys.path), 'frozen': bool(getattr(sys, 'frozen', False)),
          'torch_python_imported': any(k == 'torch' or k.startswith('torch.') for k in sys.modules),
          'onnxruntime_python_imported': 'onnxruntime' in sys.modules,
          'numpy_file': getattr(sys.modules.get('numpy'), '__file__', None)}


def matrixWorker(argv: list[str]) -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument('--internal', required=True, type=Path)
  parser.add_argument('--case', required=True, choices=CASES)
  parser.add_argument('--target', required=True, choices=('core', 'pyd'))
  parser.add_argument('--report', required=True, type=Path)
  args = parser.parse_args(argv)
  internal = args.internal.resolve()
  qt = internal / 'PyQt5/Qt5/bin'
  report = {'scope': SCOPE, 'case': args.case, 'target': args.target,
            'status': 'ERROR', 'steps': [], 'python_before': pythonScene(),
            'module_paths_initial': modulePaths(), 'selected_dlls': [],
            'interpretation_limits': [
              'The CPython host has already loaded its own Python/CRT before this script.',
              'NumPy-first uses the diagnostic interpreter NumPy, not a Python import from PYZ.',
              'System32 CRT and Torch preloads are diagnostic controls, not delivery fixes.',
              'WinDLL tests native loading, not PyInit or full onnxruntime Python import.']}
  handles = []
  writeReport(args.report, report)
  try:
    if os.name != 'nt' or sys.version_info[:3] != (3, 12, 10):
      raise RuntimeError('Matrix workers require Windows CPython 3.12.10')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.restype = ctypes.c_int
    if not kernel.SetDllDirectoryW(str(internal)):
      raise ctypes.WinError(ctypes.get_last_error())
    candidates = [internal, internal / 'torch/lib', internal / '_internal',
                  internal / '_internal/torch/lib']
    report['hook_search_path_simulation'] = []
    os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
    os.environ.setdefault('OMP_WAIT_POLICY', 'PASSIVE')
    for directory in candidates:
      item = {'path': str(directory), 'exists': directory.is_dir()}
      if directory.is_dir():
        try:
          # Match the existing hook call; do not infer cookie lifetime as a cause.
          os.add_dll_directory(str(directory))
          item['add_dll_directory'] = 'CALLED'
        except OSError as error:
          item['error'] = exceptionRecord(error)
        os.environ['PATH'] = str(directory) + os.pathsep + os.environ.get('PATH', '')
      report['hook_search_path_simulation'].append(item)
    report['path_after_hook'] = os.environ.get('PATH', '')
    report['set_dll_directory'] = str(internal)

    def loadDll(path: Path, role: str) -> bool:
      before = modulePaths()
      step = {'operation': 'ctypes.WinDLL', 'role': role, 'path': str(path),
              'winmode': 0x1100, 'exists': path.is_file(), 'module_paths_before': before,
              'status': 'LOADING'}
      report['selected_dlls'].append(str(path))
      report['steps'].append(step)
      writeReport(args.report, report)
      started = time.monotonic()
      try:
        # Match CPython extension loading: DEFAULT_DIRS plus DLL_LOAD_DIR.
        handles.append(ctypes.WinDLL(str(path), winmode=0x1100, use_last_error=True))
        step['status'] = 'LOADED'
      except OSError as error:
        step.update(status='LOAD_FAILED', error=exceptionRecord(error))
      step.update(module_paths_after=modulePaths(),
                  elapsed_seconds=round(time.monotonic() - started, 4))
      writeReport(args.report, report)
      return step['status'] == 'LOADED'

    if args.case == 'numpy-first':
      step = {'operation': 'import numpy', 'module_paths_before': modulePaths(),
              'status': 'IMPORTING'}
      report['steps'].append(step)
      writeReport(args.report, report)
      try:
        import numpy
        step.update(status='IMPORTED', version=numpy.__version__, file=numpy.__file__)
      except Exception as error:
        step.update(status='IMPORT_FAILED', error=exceptionRecord(error))
      step['module_paths_after'] = modulePaths()
    if args.case in ('root-crt', 'root-crt-qt'):
      for name in CRT_NAMES:
        loadDll(internal / name, 'root CRT control')
    elif args.case == 'root-msvcp-qt':
      loadDll(internal / 'msvcp140.dll', 'minimal root MSVCP control')
    elif args.case in ('system32-crt', 'qt-crt'):
      directory = Path(os.environ['SystemRoot']) / 'System32' if args.case == 'system32-crt' else qt
      for name in (*CRT_NAMES, 'msvcp140_1.dll'):
        loadDll(directory / name, args.case + ' diagnostic-only control')
    elif args.case == 'torch-native':
      for name in TORCH_NAMES:
        loadDll(internal / 'torch/lib' / name, 'CNN native preload control; no Torch Python')
    elif args.case == 'libiomp-only':
      loadDll(internal / 'torch/lib/libiomp5md.dll', 'OpenMP-only control')
    if args.case in ('qt-core-first', 'root-msvcp-qt', 'root-crt-qt'):
      loadDll(qt / 'Qt5Core.dll', 'Qt runtime-hook ordering control')
    capi = internal / 'onnxruntime/capi'
    targets = ([capi / 'onnxruntime.dll'] if args.target == 'core' else
               sorted(capi.glob('onnxruntime_pybind11_state*.pyd')))
    if len(targets) != 1 or not targets[0].is_file():
      raise RuntimeError('Expected exactly one original ORT target: ' + str(targets))
    loaded = loadDll(targets[0], 'ORT diagnostic target')
    report['status'] = 'TARGET_LOADED' if loaded else 'TARGET_LOAD_FAILED'
    report['preload_failures'] = [step.get('path', step['operation']) for step in report['steps'][:-1]
                                  if step.get('status') in ('LOAD_FAILED', 'IMPORT_FAILED')]
    return 0
  except Exception as error:
    report.update(status='ERROR', error=exceptionRecord(error), traceback=traceback.format_exc())
    return 1
  finally:
    report.update(python_after=pythonScene(), module_paths_final=modulePaths())
    writeReport(args.report, report)


def observeProcess(command: list[str], name: str, cwd: Path, output: Path,
                   env: dict, timeout: int, helper, work: Path) -> dict:
  import psutil

  result = {'command': command, 'status': 'STARTING', 'observations': {},
            'sampling_interval_seconds': .02, 'sampling_errors': []}
  started = time.monotonic()
  with (output / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
       (output / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
    child = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    result['pid'] = child.pid
    try:
      process = psutil.Process(child.pid)
    except psutil.NoSuchProcess:
      process = None
    try:
      while True:
        elapsed = time.monotonic() - started
        try:
          processes = [process, *process.children(recursive=True)] if process is not None else []
          for current in processes:
            try:
              key = str(current.pid) + ':' + str(current.create_time())
              row = result['observations'].setdefault(key, {
                'pid': current.pid, 'exe': current.exe(), 'modules': {}})
              for path in modulePaths(current.pid):
                seen = row['modules'].setdefault(path, {'first_seen_seconds': round(elapsed, 4)})
                seen['last_seen_seconds'] = round(elapsed, 4)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
              message = str(error)
              if message not in result['sampling_errors'] and len(result['sampling_errors']) < 20:
                result['sampling_errors'].append(message)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
          pass
        code = child.poll()
        if code is not None:
          result.update(status='EXITED', exit_code=code)
          break
        if elapsed >= timeout:
          result['status'] = 'TIMEOUT'
          helper.stop_owned(work)
          if child.poll() is None:
            child.kill()
          result['exit_code'] = child.wait(timeout=10)
          break
        time.sleep(.02)
    finally:
      if child.poll() is None:
        helper.stop_owned(work)
        if child.poll() is None:
          child.kill()
        child.wait(timeout=10)
  result['elapsed_seconds'] = round(time.monotonic() - started, 3)
  writeReport(output / (name + '.process.json'), result)
  return result


def loadSmoke(packager: Path):
  sys.path.insert(0, str(packager))
  source = packager / 'scripts/verify_vision_train_frozen.py'
  spec = importlib.util.spec_from_file_location('visionTrainDllSmoke', source)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def fileEvidence(path: str, cache: dict, install: Path, record: dict) -> dict:
  key = os.path.normcase(path)
  if key in cache:
    return cache[key]
  value = {'path': path}
  cache[key] = value
  try:
    import pefile

    target = Path(path)
    value.update(size=target.stat().st_size, sha256=fileHash(target))
    with pefile.PE(str(target), fast_load=True) as pe:
      pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
      fixed = getattr(pe, 'VS_FIXEDFILEINFO', [])
      if fixed:
        info = fixed[0]
        value['file_version'] = '.'.join(str(x) for x in (
          info.FileVersionMS >> 16, info.FileVersionMS & 65535,
          info.FileVersionLS >> 16, info.FileVersionLS & 65535))
      else:
        value['file_version'] = None
      value['pe_imports'] = [entry.dll.decode('ascii', errors='replace')
                            for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])]
    try:
      relative = target.relative_to(install).as_posix()
    except ValueError:
      relative = None
    expected = record.get('files', {}).get(relative)
    if expected is not None:
      value.update(build_record_path=relative, build_record_expected=expected,
                    matches_build_record=(expected['size'] == value['size']
                                          and expected['sha256'] == value['sha256']))
      if not value['matches_build_record']:
        raise ValueError('Observed product DLL differs from original build record: ' + relative)
  except Exception as error:
    value['evidence_error'] = exceptionRecord(error)
  return value


def enrichReports(report: dict, cache: dict, install: Path, record: dict) -> None:
  for process in report.get('processes', {}).values():
    for observed in process.get('observations', {}).values():
      for path in observed['modules']:
        fileEvidence(path, cache, install, record)
  for case in report.get('matrix', {}).values():
    paths = set(case.get('module_paths_initial', []) + case.get('module_paths_final', [])
                + case.get('selected_dlls', []))
    for step in case.get('steps', []):
      paths.update(step.get('module_paths_before', []))
      paths.update(step.get('module_paths_after', []))
      step['crt_before'] = [fileEvidence(p, cache, install, record)
                            for p in step.get('module_paths_before', []) if isCrt(p)]
      step['crt_after'] = [fileEvidence(p, cache, install, record)
                           for p in step.get('module_paths_after', []) if isCrt(p)]
    for path in sorted(paths):
      fileEvidence(path, cache, install, record)
    case['selected_dll_evidence'] = [fileEvidence(p, cache, install, record)
                                      for p in case.get('selected_dlls', [])]
    case['initial_crt'] = [fileEvidence(p, cache, install, record)
                            for p in case.get('module_paths_initial', []) if isCrt(p)]
    case['final_crt'] = [fileEvidence(p, cache, install, record)
                          for p in case.get('module_paths_final', []) if isCrt(p)]


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--zip', required=True, type=Path, dest='archive')
  parser.add_argument('--source-root', required=True, type=Path)
  parser.add_argument('--packager-root', required=True, type=Path)
  parser.add_argument('--output', required=True, type=Path)
  parser.add_argument('--build-record', required=True, type=Path)
  args = parser.parse_args(argv)
  for key in ('archive', 'source_root', 'packager_root', 'output', 'build_record'):
    setattr(args, key, getattr(args, key).resolve())
  args.output.mkdir(parents=True, exist_ok=False)
  report = {'status': 'ERROR', 'scope': SCOPE, 'processes': {}, 'matrix': {},
            'product_acceptance': 'NOT_RUN', 'GPU_execution': 'NOT_RUN',
            'diagnostic_success_is_product_success': False}
  cache = {}
  started = time.monotonic()
  try:
    if os.name != 'nt' or sys.version_info[:3] != (3, 12, 10):
      raise RuntimeError('Run with Windows CPython 3.12.10')
    smoke = loadSmoke(args.packager_root)
    helper = smoke.loadHelpers(args.source_root)
    records = ([args.build_record] if args.build_record.is_file() else
               list(args.build_record.rglob('build-record.json')))
    if len(records) != 1:
      raise ValueError('Expected exactly one build-record.json')
    record = json.loads(records[0].read_bytes())
    report['build_record'] = {'path': str(records[0]), 'sha256': fileHash(records[0]),
                              'build_id': record.get('build_id')}
    report['archive'] = {'path': str(args.archive), 'size': args.archive.stat().st_size,
                         'sha256': fileHash(args.archive)}
    report['diagnostic_python'] = pythonScene()
    report['diagnostic_packages'] = {name: importlib.metadata.version(name)
                                      for name in ('psutil', 'pefile', 'numpy', 'onnx', 'Pillow')}
    with tempfile.TemporaryDirectory(prefix='vision-train-dll-',
                                     dir=os.environ.get('RUNNER_TEMP')) as directory:
      work = Path(directory)
      try:
        install, inventory = smoke.extractPackage(args.archive, work / 'unpacked')
        report['archive']['inventory'] = inventory
        app = install / 'app'
        internal = app / '_internal'
        identity = json.loads((app / 'release_identity.json').read_bytes())
        sourceCommit = subprocess.check_output(
          ['git', '-C', str(args.source_root), 'rev-parse', 'HEAD'], text=True).strip()
        if (identity.get('build_id') != record.get('build_id')
            or identity.get('source', {}).get('commit') != sourceCommit):
          raise ValueError('Artifact identity differs from build record or source checkout')
        report.update(build_identity=identity, source_commit=sourceCommit)
        env = helper.environment(work)
        env.update(PYI_TORCH_DLL_DEBUG='1', PYTHONDONTWRITEBYTECODE='1',
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', YOLO_AUTOINSTALL='false')
        report['launcher_observation'] = smoke.observeLauncher(
          install, work, args.output, env, helper, 180)
        if report['launcher_observation']['status'] != 'PASS':
          raise RuntimeError('Normal launcher registration did not complete')
        executable = str(app / 'VisionWorkshopApp.exe')
        report['processes']['dino-inspect'] = observeProcess(
          [executable, '--dino-onnx-worker', 'inspect', 'CPUExecutionProvider'],
          'dino-inspect', app, args.output, env, 60, helper, work)
        micro = smoke.makeMicroJob(work / 'micro-model')
        report['processes']['cnn-micro'] = observeProcess(
          [executable, '--cnn-patchcore-onnx-worker', '--job', str(micro),
           '--report', str(args.output / 'cnn-micro.worker.json')],
          'cnn-micro', app, args.output, env, 60, helper, work)
        for case in CASES:
          for target in ('core', 'pyd'):
            name = 'matrix-' + case + '-' + target
            resultPath = args.output / (name + '.json')
            command = [sys.executable, '-I', '-B', '-X', 'utf8', str(Path(__file__).resolve()),
                       '--matrix-worker', '--internal', str(internal), '--case', case,
                       '--target', target, '--report', str(resultPath)]
            report['processes'][name] = observeProcess(
              command, name, app, args.output, env, 60, helper, work)
            report['matrix'][name] = (json.loads(resultPath.read_bytes()) if resultPath.is_file()
                                      else {'status': 'NO_WORKER_REPORT'})
        enrichReports(report, cache, install, record)
        for name, case in report['matrix'].items():
          writeReport(args.output / (name + '.json'), case)
        report['files'] = list(cache.values())
        mismatches = [x['path'] for x in cache.values() if x.get('matches_build_record') is False]
        if mismatches:
          raise ValueError('Original extracted binaries changed: ' + str(mismatches))
        report['status'] = 'COLLECTED'
      finally:
        helper.stop_owned(work)
    report['archive']['sha256_after'] = fileHash(args.archive)
    if report['archive']['sha256_after'] != report['archive']['sha256']:
      raise ValueError('Original ZIP changed during diagnosis')
    return 0
  except Exception as error:
    report.update(status='ERROR', error=exceptionRecord(error), traceback=traceback.format_exc())
    return 1
  finally:
    report.update(elapsed_seconds=round(time.monotonic() - started, 3), files=list(cache.values()))
    writeReport(args.output / 'dll-diagnostic.json', report)
    print(json.dumps({'status': report['status'], 'report': str(args.output / 'dll-diagnostic.json'),
                      'scope': SCOPE}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
  if sys.argv[1:2] == ['--matrix-worker']:
    raise SystemExit(matrixWorker(sys.argv[2:]))
  raise SystemExit(main())
