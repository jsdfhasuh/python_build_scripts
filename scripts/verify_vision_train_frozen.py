"""Observe a real Windows package in one disposable extraction; never publish it."""

import argparse
import ctypes
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from build_config import validateFileName
from build_records import fileHash
from path_boundary import ioPath


def writeReport(path: Path, value: dict) -> None:
  path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def extractPackage(archivePath: Path, destination: Path) -> tuple[Path, dict]:
  """Read the ZIP directory once, then extract its files once without touching dist."""
  with zipfile.ZipFile(archivePath) as archive:
    entries = archive.infolist()
    seen, roots, records = set(), set(), []
    for item in entries:
      name = item.filename
      parts = PurePosixPath(name).parts
      if ('\\' in name or '\x00' in name or not parts or name.startswith('/')
          or any(part in ('.', '..') for part in name.split('/') if part)
          or name.rstrip('/') != '/'.join(parts)):
        raise ValueError('Unsafe ZIP member: ' + repr(name))
      for part in parts:
        validateFileName(part, 'ZIP member')
      key = name.rstrip('/').casefold()
      if key in seen:
        raise ValueError('Duplicate ZIP member: ' + name)
      seen.add(key)
      roots.add(parts[0])
      mode = (item.external_attr >> 16) & 0o170000
      if mode not in (0, 0o040000, 0o100000):
        raise ValueError('Special ZIP member: ' + name)
      if not item.is_dir():
        records.append({'path': '/'.join(parts[1:]), 'bytes': item.file_size,
                        'compressed_bytes': item.compress_size})
    if len(roots) != 1:
      raise ValueError('Expected one portable package root')
    total = sum(item['bytes'] for item in records)
    if shutil.disk_usage(destination.parent).free < total + 256 * 1024 ** 2:
      raise OSError('Insufficient disk space for one disposable package extraction')
    destination.mkdir()
    for item in entries:
      target = ioPath(destination.joinpath(*PurePosixPath(item.filename).parts))
      if item.is_dir():
        target.mkdir(parents=True, exist_ok=True)
      else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as source, target.open('xb') as output:
          shutil.copyfileobj(source, output, 4 * 1024 ** 2)
    install = destination / next(iter(roots))
  if not (install / 'VisionWorkshop.exe').is_file():
    raise ValueError('Package has no fixed VisionWorkshop.exe launcher')
  return install, {
    'file_count': len(records), 'uncompressed_bytes': total,
    'compressed_member_bytes': sum(item['compressed_bytes'] for item in records),
    'largest_files': sorted(records, key=lambda item: item['bytes'], reverse=True)[:20],
    'model_resources': [item for item in records if '/static/models/' in item['path']],
  }


def loadHelpers(source: Path):
  sys.path.insert(0, str(source))
  from update_process import ProcessHandle
  from update_diagnostics import read_startup_trace

  path = ROOT / 'scripts/verify_release_transition_windows.py'
  spec = importlib.util.spec_from_file_location('visionTrainFrozenHelpers', path)
  helper = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(helper)
  helper.ProcessHandle = ProcessHandle
  helper.read_startup_trace = read_startup_trace
  return helper


def requestWindowClose(pid: int) -> int:
  """Ask only this disposable product process to close through its normal window handler."""
  from ctypes import wintypes

  user32 = ctypes.WinDLL('user32', use_last_error=True)
  callbackType = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
  user32.EnumWindows.argtypes = [callbackType, wintypes.LPARAM]
  user32.EnumWindows.restype = wintypes.BOOL
  user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
  user32.GetWindowThreadProcessId.restype = wintypes.DWORD
  user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
  user32.PostMessageW.restype = wintypes.BOOL
  windows = []

  @callbackType
  def visit(window, _parameter):
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
    if owner.value == pid and user32.PostMessageW(window, 0x0010, 0, 0):
      windows.append(int(window))
    return True

  user32.EnumWindows(visit, 0)
  return len(windows)


def observeLauncher(install: Path, work: Path, output: Path, env: dict,
                    helper, timeout: int) -> dict:
  import psutil

  app = install / 'app'
  result = {'status': 'FAIL', 'scope': 'CREATING_WINDOW and continued process survival',
            'gui_ready': 'NOT_OBSERVED', 'interactive_gui': 'NOT_RUN',
            'normal_exit': 'NOT_OBSERVED', 'forced_cleanup': False}
  with (output / 'launcher.stdout.txt').open('w', encoding='utf-8') as stdout, \
       (output / 'launcher.stderr.txt').open('w', encoding='utf-8') as stderr:
    launcher = subprocess.Popen([str(install / 'VisionWorkshop.exe')], cwd=install, env=env,
                                stdout=stdout, stderr=stderr,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    try:
      process = helper.wait_until(lambda: helper.find_product_process(app),
                                  'Frozen application process', timeout)

      def started():
        trace = helper.read_startup_trace(app, process)
        if not trace:
          return None
        stages = [item['stage'] for item in trace['events']]
        if 'FAILED' in stages:
          writeReport(output / 'launcher-trace.json', trace)
          raise RuntimeError('Frozen startup reported FAILED')
        return trace if 'CREATING_WINDOW' in stages else None

      helper.wait_until(started, 'Frozen application reached CREATING_WINDOW', timeout)
      deadline = time.monotonic() + 5
      while time.monotonic() < deadline:
        with helper.ProcessHandle(process['pid'], process) as handle:
          if handle.exited():
            raise RuntimeError('Frozen application exited during startup observation')
        started()
        time.sleep(.2)
      trace = started()
      writeReport(output / 'launcher-trace.json', trace)
      result.update(status='PASS', startup_stages=[item['stage'] for item in trace['events']],
                    observation_seconds=5)
      result['close_messages'] = requestWindowClose(process['pid'])
      if result['close_messages']:
        try:
          code = psutil.Process(process['pid']).wait(timeout=20)
          result.update(normal_exit='PASS' if code == 0 else 'FAIL', product_exit_code=code)
        except psutil.NoSuchProcess:
          result['normal_exit'] = 'EXITED_CODE_UNAVAILABLE'
        except psutil.TimeoutExpired:
          pass
      result['forced_cleanup'] = helper.find_product_process(app) is not None
      if result['normal_exit'] == 'FAIL':
        result['status'] = 'FAIL'
      return result
    finally:
      if helper.find_product_process(app) is not None or launcher.poll() is None:
        result['forced_cleanup'] = True
      helper.stop_owned(work)
      try:
        result['launcher_exit_code'] = launcher.wait(timeout=10)
      except subprocess.TimeoutExpired:
        result['forced_cleanup'] = True
        raise RuntimeError('Owned launcher did not exit after cleanup')
      writeReport(output / 'launcher-observation.json', result)


def runFrozen(command: list[str], name: str, output: Path, env: dict,
              work: Path, helper, timeout: int) -> str:
  start = time.monotonic()
  with (output / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
       (output / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
    child = subprocess.Popen(command, cwd=Path(command[0]).parent, env=env,
                             stdout=stdout, stderr=stderr,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
      code = child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
      helper.stop_owned(work)
      child.wait(timeout=10)
      writeReport(output / (name + '.process.json'), {'status': 'TIMEOUT',
                  'elapsed_seconds': round(time.monotonic() - start, 3)})
      raise
  writeReport(output / (name + '.process.json'), {'exit_code': code,
              'elapsed_seconds': round(time.monotonic() - start, 3)})
  if code:
    raise RuntimeError(f'{name} exited with {code}; see its captured stderr')
  return (output / (name + '.stdout.txt')).read_text(encoding='utf-8-sig')


def checkDinoReport(document: dict, validEnvironment) -> dict:
  environment = document.get('environment', {})
  if (not validEnvironment(environment, 'CPUExecutionProvider')
      or environment.get('training_modules_imported') != []
      or not isinstance(document.get('files_sha256'), str)
      or len(document['files_sha256']) != 64 or document.get('bytes', 0) <= 0):
    raise ValueError('Frozen DINO inspection does not satisfy the main-runtime contract')
  return {'status': 'PASS', 'environment': environment,
          'files_sha256': document['files_sha256'], 'bytes': document['bytes'],
          'model_inference': 'NOT_RUN'}


def makeMicroJob(root: Path) -> Path:
  import onnx
  from onnx import TensorProto, helper

  root.mkdir()
  package = root / 'package'
  package.mkdir()
  graph = helper.make_graph([
    helper.make_node('ReduceMean', ['image'], ['plane'], axes=[1], keepdims=0),
    helper.make_node('Add', ['plane', 'one'], ['shifted']),
    helper.make_node('MatMul', ['shifted', 'weights'], ['product']),
    helper.make_node('Unsqueeze', ['product', 'axis'], ['anomaly_map']),
    helper.make_node('ReduceMean', ['anomaly_map'], ['pred_score'], axes=[1, 2, 3], keepdims=0),
  ], 'frozen-cpu-schema-smoke',
    [helper.make_tensor_value_info('image', TensorProto.FLOAT, [1, 3, 4, 4])],
    [helper.make_tensor_value_info('pred_score', TensorProto.FLOAT, [1]),
     helper.make_tensor_value_info('anomaly_map', TensorProto.FLOAT, [1, 1, 4, 4])],
    [helper.make_tensor('weights', TensorProto.FLOAT, [4, 4], list(range(16))),
     helper.make_tensor('one', TensorProto.FLOAT, [], [1.0]),
     helper.make_tensor('axis', TensorProto.INT64, [1], [1])])
  model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
  model.ir_version = 9
  onnx.checker.check_model(model)
  onnx.save_model(model, package / 'model.onnx')
  (root / 'reference.json').write_text('[]\n', encoding='utf-8')
  job = root / 'verify.json'
  writeReport(job, {'phase': 'verify', 'trusted_source': True, 'run_id': 'frozen-cpu-smoke',
                   'work': str(root), 'package': str(package), 'location': 'synthetic-frozen-smoke',
                   'source': {'params': {'image_size': 4}, 'model_threshold': 0.0}})
  return job


def checkMicroReport(document: dict) -> dict:
  if (document.get('ok') is not True or document.get('phase') != 'verify'
      or document.get('run_id') != 'frozen-cpu-smoke'
      or document.get('status') != 'PENDING' or document.get('samples') != []
      or document.get('provider') != ['CPUExecutionProvider']):
    raise ValueError('Synthetic CPU worker did not return the expected unqualified schema result')
  return {'status': 'PASS', 'scope': 'Real frozen ORT CPU session; output shape/dtype/finiteness',
          'product_model_qualification': 'PENDING', 'checkpoint_restore': 'NOT_RUN',
          'numerical_parity': 'NOT_RUN', 'worker_report': document}


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--zip', type=Path, required=True, dest='archive')
  parser.add_argument('--source-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--timeout-seconds', type=int, default=180)
  args = parser.parse_args(argv)
  args.archive, args.source_root, args.output = (
    path.resolve() for path in (args.archive, args.source_root, args.output))
  args.output.mkdir(parents=True, exist_ok=False)
  report = {'status': 'FAIL', 'scope': 'Disposable real frozen Windows artifact smoke',
            'checks': {}, 'GPU_execution': 'NOT_RUN',
            'GPU_scope': 'CPU-only smoke; no physical GPU execution attempted',
            'full_product_acceptance': 'NOT_RUN',
            'trained_model_numerical_acceptance': 'NOT_RUN', 'build_summary_modified': False}
  started = time.monotonic()
  try:
    if os.name != 'nt':
      report.update(status='NOT_RUN', reason='Windows is required; no substitute result')
      return 2
    if args.timeout_seconds <= 0:
      raise ValueError('Timeout must be positive')
    report['archive'] = {'name': args.archive.name, 'bytes': args.archive.stat().st_size,
                         'sha256': fileHash(args.archive)}
    helper = loadHelpers(args.source_root)
    with tempfile.TemporaryDirectory(prefix='vision-train-frozen-',
                                     dir=os.environ.get('RUNNER_TEMP')) as directory:
      work = Path(directory)
      try:
        install, inventory = extractPackage(args.archive, work / 'unpacked')
        report['archive'].update(inventory)
        app = install / 'app'
        identity = json.loads((app / 'release_identity.json').read_bytes())
        report['build_identity'] = identity
        sourceCommit = subprocess.check_output(
          ['git', '-C', str(args.source_root), 'rev-parse', 'HEAD'], text=True).strip()
        if identity.get('source', {}).get('commit') != sourceCommit:
          raise ValueError('Inspection source checkout differs from the frozen build identity')
        report['source_commit'] = sourceCommit
        from vision_train_runtime import validatePackage
        report['checks']['static_runtime'] = validatePackage(app, 'VisionWorkshopApp')
        for sourceName, function, relative in (
          ('anomaly_func/pretrained_weights.py', 'verify_pretrained_weights',
           'static/models/patchcore_wide_resnet50_2.racm_in1k.safetensors'),
          ('project__func/image_simplification/pretrained_weights.py', 'validate_weight_file',
           'static/models/image_simplification/dinov2_vits14/model.safetensors'),
        ):
          runpy.run_path(str(args.source_root / sourceName))[function](app / '_internal' / relative)
        report['checks']['pinned_model_resources'] = {'status': 'PASS', 'sha256_verified': True}
        env = helper.environment(work)
        for name, action in (
          ('launcher_observation', lambda: observeLauncher(install, work, args.output, env,
                                                           helper, args.timeout_seconds)),
          ('dino_inspection', lambda: inspectDino(app, work, args.output, env, helper,
                                                args.timeout_seconds)),
          ('onnx_cpu_schema', lambda: inspectCpu(app, work, args.output, env, helper,
                                               args.timeout_seconds)),
        ):
          try:
            report['checks'][name] = action()
          except Exception as error:
            report['checks'][name] = {'status': 'FAIL', 'error': str(error),
                                     'error_type': type(error).__name__}
            (args.output / (name + '.failure.txt')).write_text(traceback.format_exc(), encoding='utf-8')
        report['status'] = ('PASS' if all(item.get('status') in ('PASS', 'passed')
                                        for item in report['checks'].values()) else 'FAIL')
      finally:
        helper.stop_owned(work)
    return 0 if report['status'] == 'PASS' else 1
  except Exception as error:
    report.update(status='FAIL', error=str(error), error_type=type(error).__name__)
    (args.output / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    return 1
  finally:
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    writeReport(args.output / 'frozen-smoke.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def inspectDino(app: Path, work: Path, output: Path, env: dict, helper, timeout: int) -> dict:
  from anomaly_func.dinov2_main_runtime import valid_environment

  stdout = runFrozen([str(app / 'VisionWorkshopApp.exe'), '--dino-onnx-worker', 'inspect',
                      'CPUExecutionProvider'], 'dino-inspect', output, env, work, helper, timeout)
  document = json.loads(stdout)
  writeReport(output / 'dino-inspection.json', document)
  return checkDinoReport(document, valid_environment)


def inspectCpu(app: Path, work: Path, output: Path, env: dict, helper, timeout: int) -> dict:
  job = makeMicroJob(work / 'micro-model')
  resultPath = output / 'onnx-cpu-worker.json'
  runFrozen([str(app / 'VisionWorkshopApp.exe'), '--cnn-patchcore-onnx-worker',
             '--job', str(job), '--report', str(resultPath)], 'onnx-cpu', output,
            env, work, helper, timeout)
  return checkMicroReport(json.loads(resultPath.read_bytes()))


if __name__ == '__main__':
  raise SystemExit(main())
