"""A stdlib-only frozen probe for external CP312 packages; not a product launcher."""

import argparse
import ctypes
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import uuid


SCHEMA_VERSION = 1
PYTHON_VERSION = '3.12.10'
CRT_SHA256 = 'a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde'
FORBIDDEN_DINO = ('torch', 'torchvision', 'anomalib', 'lightning', 'lightning_fabric',
                  'pytorch_lightning', 'transformers')
DLL_HANDLES = []
NETWORK_ATTEMPTS = []


def require(condition: bool, message: str) -> None:
  if not condition:
    raise RuntimeError(message)


def isWithin(path: Path, parent: Path) -> bool:
  try:
    path.resolve().relative_to(parent.resolve())
    return True
  except ValueError:
    return False


def fileHash(path: Path) -> str:
  hasher = hashlib.sha256()
  with path.open('rb') as stream:
    for block in iter(lambda: stream.read(4 * 1024 ** 2), b''):
      hasher.update(block)
  return hasher.hexdigest()


def writeReport(path: Path, value: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_name(path.name + '.writing')
  temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
  os.replace(temporary, path)


def denyPythonNetwork(event: str, _arguments: tuple) -> None:
  if event in ('socket.connect', 'socket.connect_ex', 'socket.sendto', 'socket.getaddrinfo',
               'socket.gethostbyname', 'socket.gethostbyaddr'):
    NETWORK_ATTEMPTS.append(event)
    raise RuntimeError('Network use is forbidden in the frozen module probe: ' + event)


def loadedLibraries() -> list[str]:
  if os.name != 'nt':
    return []
  kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
  kernel32.GetCurrentProcess.restype = ctypes.c_void_p
  kernel32.K32EnumProcessModulesEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                              ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                              ctypes.c_ulong]
  kernel32.K32EnumProcessModulesEx.restype = ctypes.c_int
  kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
  kernel32.GetModuleFileNameW.restype = ctypes.c_ulong
  process = kernel32.GetCurrentProcess()
  count = 1024
  while True:
    handles = (ctypes.c_void_p * count)()
    needed = ctypes.c_ulong()
    if not kernel32.K32EnumProcessModulesEx(process, handles, ctypes.sizeof(handles),
                                           ctypes.byref(needed), 3):
      raise ctypes.WinError(ctypes.get_last_error())
    if needed.value <= ctypes.sizeof(handles):
      break
    count = needed.value // ctypes.sizeof(ctypes.c_void_p) + 16
  paths = []
  for handle in handles[:needed.value // ctypes.sizeof(ctypes.c_void_p)]:
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetModuleFileNameW(handle, buffer, len(buffer))
    if not length:
      raise ctypes.WinError(ctypes.get_last_error())
    require(length < len(buffer), 'Loaded module path was truncated')
    paths.append(str(Path(buffer.value).resolve()))
  return sorted(set(paths), key=str.casefold)


def recordOrigins(report: dict, runtimeRoot: Path, sourceRoot: Path | None) -> None:
  coreRoot = Path(sys.executable).resolve().parent
  permitted = [coreRoot, runtimeRoot]
  if sourceRoot is not None:
    permitted.append(sourceRoot)
  origins = {}
  external = {}
  unexpected = {}
  embedded = {}
  for name, module in tuple(sys.modules.items()):
    specification = getattr(module, '__spec__', None)
    if getattr(specification, 'origin', None) in ('built-in', 'frozen'):
      embedded[name] = specification.origin
      continue
    origin = getattr(module, '__file__', None)
    if not origin or str(origin).startswith('<'):
      continue
    path = Path(origin).resolve()
    origins[name] = str(path)
    if isWithin(path, runtimeRoot):
      external[name] = str(path)
    if not any(isWithin(path, parent) for parent in permitted):
      unexpected[name] = str(path)
  report['imports'] = origins
  report['module_origins'] = origins
  report['external_module_origins'] = external
  report['embedded_module_origins'] = embedded
  report['unexpected_module_origins'] = unexpected
  report['sys_path'] = list(sys.path)
  report['loaded_libraries'] = loadedLibraries()
  require(not unexpected, 'Imported modules outside the frozen Core/runtime/source boundary')
  pythonDlls = [path for path in report['loaded_libraries']
                if Path(path).name.casefold().startswith('python')
                and Path(path).suffix.casefold() == '.dll']
  report['python_dlls'] = pythonDlls
  require(all(Path(path).name.casefold() in ('python312.dll', 'python3.dll')
              for path in pythonDlls), 'An unexpected Python runtime DLL entered the process')
  require(any(Path(path).name.casefold() == 'python312.dll' for path in pythonDlls),
          'The frozen process did not load python312.dll')
  require(all(isWithin(Path(path), coreRoot) for path in pythonDlls),
          'A second external Python DLL entered the frozen process')
  nativePrefixes = ('torch', 'c10', 'cublas', 'cudnn', 'cudart', 'cufft', 'curand',
                    'cusolver', 'cusparse', 'nvrtc', 'nvjitlink', 'onnxruntime', 'qt5',
                    'libiomp', 'libscipy_openblas', 'msvcp140')
  runtimeLibraries = [path for path in report['loaded_libraries']
                      if Path(path).name.casefold().startswith(nativePrefixes)]
  unexpectedLibraries = [path for path in runtimeLibraries
                         if not isWithin(Path(path), runtimeRoot)]
  report['external_native_libraries'] = runtimeLibraries
  report['unexpected_native_libraries'] = unexpectedLibraries
  require(not unexpectedLibraries, 'A computation or Qt DLL loaded outside the external runtime')


def importExternal(name: str, runtimeRoot: Path):
  module = importlib.import_module(name)
  origin = getattr(module, '__file__', None)
  require(bool(origin) and isWithin(Path(origin), runtimeRoot),
          'Module did not load from the external runtime: ' + name)
  return module


def recordDistribution(report: dict, name: str, runtimeRoot: Path) -> str:
  distribution = importlib.metadata.distribution(name)
  location = Path(getattr(distribution, '_path', distribution.locate_file(''))).resolve()
  require(isWithin(location, runtimeRoot), 'Metadata did not load from runtime: ' + name)
  value = {'version': distribution.version, 'path': str(location)}
  report['metadata'][name] = value
  report['distributions'][name] = value
  return distribution.version


def configureRuntime(runtimeRoot: Path, report: dict) -> None:
  require(runtimeRoot.is_dir(), 'External runtime directory is missing')
  coreRoot = Path(sys.executable).resolve().parent
  require(not isWithin(runtimeRoot, coreRoot), 'The external runtime must be outside Core')
  sys.path[:] = [entry for entry in sys.path if entry and isWithin(Path(entry), coreRoot)]
  sys.path.insert(0, str(runtimeRoot))
  importlib.invalidate_caches()
  coreLibraries = Path(sys._MEIPASS).resolve()
  require(isWithin(coreLibraries, coreRoot), 'Frozen standard library is outside Core')
  DLL_HANDLES.append(os.add_dll_directory(str(coreLibraries)))
  crt = runtimeRoot / 'msvcp140.dll'
  require(crt.is_file(), 'External runtime has no explicitly owned msvcp140.dll')
  digest = fileHash(crt)
  require(digest == CRT_SHA256, 'External MSVCP does not match the validated payload')
  DLL_HANDLES.append(os.add_dll_directory(str(runtimeRoot)))
  DLL_HANDLES.append(ctypes.CDLL(str(crt), winmode=0x1100))
  actual = [path for path in loadedLibraries()
            if Path(path).name.casefold() == 'msvcp140.dll']
  require(len(actual) == 1 and Path(actual[0]).resolve() == crt.resolve(),
          'Another MSVCP DLL occupied the process before the runtime-owned CRT')
  report['crt_preload'] = {'status': 'PASS', 'path': str(crt), 'sha256': digest,
                           'loaded_path': actual[0]}
  candidates = [runtimeRoot / 'torch' / 'lib', runtimeRoot / 'torchvision',
                runtimeRoot / 'onnxruntime' / 'capi', runtimeRoot / 'PyQt5' / 'Qt5' / 'bin']
  candidates.extend(sorted(runtimeRoot.glob('*.libs')))
  report['dll_directories'] = [str(coreLibraries), str(runtimeRoot)]
  for directory in candidates:
    if directory.is_dir():
      DLL_HANDLES.append(os.add_dll_directory(str(directory)))
      report['dll_directories'].append(str(directory))


def checkPure(runtimeRoot: Path, report: dict, job: dict) -> None:
  fixture = importExternal('vw_external_fixture', runtimeRoot)
  version = recordDistribution(report, 'vw-external-fixture', runtimeRoot)
  marker = getattr(fixture, 'MARKER', None)
  require(isinstance(marker, str) and bool(marker), 'External fixture marker is missing')
  if 'expected_marker' in job:
    require(marker == job['expected_marker'], 'A stale external fixture marker was loaded')
  if 'expected_fixture_version' in job:
    require(version == job['expected_fixture_version'], 'Stale package metadata was loaded')
  report['checks'].update(marker=marker, fixture_version=version,
                          pure_python='PASS', external_metadata='PASS')


def checkNative(runtimeRoot: Path, report: dict) -> None:
  np = importExternal('numpy', runtimeRoot)
  psutil = importExternal('psutil', runtimeRoot)
  qt = importExternal('PyQt5.QtCore', runtimeRoot)
  importExternal('PyQt5.sip', runtimeRoot)
  matrix = np.asarray([[1, 2], [3, 4]], dtype=np.float32)
  result = (matrix @ matrix).tolist()
  require(result == [[7.0, 10.0], [15.0, 22.0]], 'External NumPy native operation failed')
  require(psutil.Process().pid == os.getpid(), 'External psutil native operation failed')
  application = qt.QCoreApplication.instance() or qt.QCoreApplication([])
  require(application is not None, 'External Qt failed to construct QCoreApplication')
  require(qt.QByteArray(b'external-native').data() == b'external-native', 'Qt operation failed')
  for name in ('numpy', 'psutil', 'PyQt5', 'PyQt5-Qt5', 'PyQt5-sip'):
    recordDistribution(report, name, runtimeRoot)
  report['checks'].update(numpy_matmul=result, psutil_pid=psutil.Process().pid,
                          qt_runtime_version=qt.qVersion(), qt_bindings_version=qt.PYQT_VERSION_STR,
                          native_extensions='PASS', qt_core='PASS', interactive_gui='NOT_RUN')


def checkTorch(runtimeRoot: Path, report: dict) -> None:
  torch = importExternal('torch', runtimeRoot)
  vision = importExternal('torchvision', runtimeRoot)
  ops = importExternal('torchvision.ops', runtimeRoot)
  left = torch.tensor([[1, 2], [3, 4]], dtype=torch.float32)
  right = torch.tensor([[2, 0], [1, 2]], dtype=torch.float32)
  expected = [[4.0, 4.0], [10.0, 8.0]]
  require((left @ right).tolist() == expected, 'External Torch CPU operation failed')
  boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 9, 9], [20, 20, 30, 30]],
                       dtype=torch.float32)
  scores = torch.tensor([0.9, 0.8, 0.7], dtype=torch.float32)
  require(ops.nms(boxes, scores, 0.5).tolist() == [0, 2], 'External TorchVision NMS failed')
  recordDistribution(report, 'torch', runtimeRoot)
  recordDistribution(report, 'torchvision', runtimeRoot)
  report['checks'].update(torch_cpu='PASS', torchvision_cpu_nms='PASS',
                          torch_version=torch.__version__, torchvision_version=vision.__version__,
                          cuda_build=torch.version.cuda)
  available = torch.cuda.is_available()
  if available:
    actual = (left.cuda() @ right.cuda()).cpu().tolist()
    chosen = ops.nms(boxes.cuda(), scores.cuda(), 0.5).cpu().tolist()
    torch.cuda.synchronize()
    require(actual == expected and chosen == [0, 2], 'External Torch GPU operation failed')
    report['gpu'] = {'status': 'PASS', 'scope': 'Torch matmul and TorchVision NMS',
                     'device': torch.cuda.get_device_name(0)}
  else:
    report['gpu'] = {'status': 'NOT_RUN', 'reason': 'torch.cuda.is_available() is false',
                     'device_count': torch.cuda.device_count()}


def loadQtBeforeCompute(runtimeRoot: Path, report: dict) -> None:
  qt = importExternal('PyQt5.QtCore', runtimeRoot)
  require(qt.QDate.currentDate().isValid(), 'Qt native call failed before computation imports')
  for name in ('PyQt5', 'PyQt5-Qt5', 'PyQt5-sip'):
    recordDistribution(report, name, runtimeRoot)
  report['checks'].update(qt_before_compute='PASS', qt_runtime_version=qt.qVersion())


def cudaDeviceCount() -> dict:
  try:
    driver = ctypes.WinDLL('nvcuda.dll', use_last_error=True)
  except OSError as error:
    return {'available': False, 'reason': 'NVIDIA driver DLL unavailable', 'error': str(error)}
  driver.cuInit.argtypes = [ctypes.c_uint]
  driver.cuInit.restype = ctypes.c_int
  driver.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
  driver.cuDeviceGetCount.restype = ctypes.c_int
  initialized = driver.cuInit(0)
  if initialized:
    return {'available': False, 'reason': 'CUDA driver initialization did not succeed',
            'cuda_driver_code': initialized}
  count = ctypes.c_int()
  code = driver.cuDeviceGetCount(ctypes.byref(count))
  return {'available': code == 0 and count.value > 0,
          'device_count': count.value, 'cuda_driver_code': code}


def checkOrt(runtimeRoot: Path, report: dict, reportPath: Path, allowGpu: bool) -> None:
  np = importExternal('numpy', runtimeRoot)
  onnx = importExternal('onnx', runtimeRoot)
  ort = importExternal('onnxruntime', runtimeRoot)
  recordDistribution(report, 'numpy', runtimeRoot)
  recordDistribution(report, 'onnx', runtimeRoot)
  recordDistribution(report, 'onnxruntime-gpu', runtimeRoot)
  helper = importExternal('onnx.helper', runtimeRoot)
  tensorType = onnx.TensorProto.FLOAT
  weights = helper.make_tensor('weights', tensorType, [2, 2], [2.0, 0.0, 1.0, 2.0])
  bias = helper.make_tensor('bias', tensorType, [2], [0.5, -0.5])
  graph = helper.make_graph(
    [helper.make_node('MatMul', ['input', 'weights'], ['product']),
     helper.make_node('Add', ['product', 'bias'], ['output'])],
    'external-runtime-fixture',
    [helper.make_tensor_value_info('input', tensorType, [2, 2])],
    [helper.make_tensor_value_info('output', tensorType, [2, 2])], [weights, bias])
  model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)])
  model.ir_version = 8
  payload = model.SerializeToString()
  sample = np.asarray([[1, 2], [3, 4]], dtype=np.float32)
  expected = np.asarray([[4.5, 3.5], [10.5, 7.5]], dtype=np.float32)
  options = ort.SessionOptions()
  options.intra_op_num_threads = 1
  options.inter_op_num_threads = 1
  options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
  session = ort.InferenceSession(payload, sess_options=options, providers=['CPUExecutionProvider'])
  actual = session.run(['output'], {'input': sample})[0]
  require(actual.shape == (2, 2) and actual.dtype == np.float32,
          'External ORT returned the wrong tensor schema')
  require(bool(np.isfinite(actual).all()) and bool(np.array_equal(actual, expected)),
          'External ORT CPU calculation differs from the fixed reference')
  report['checks'].update(ort_cpu='PASS', ort_output=actual.tolist(),
                          ort_model_sha256=hashlib.sha256(payload).hexdigest(),
                          ort_available_providers=ort.get_available_providers(),
                          ort_session_providers=session.get_providers())
  if not allowGpu:
    report['gpu'] = {'status': 'NOT_RUN', 'reason': 'This mode only requests CPU execution'}
    return
  devices = cudaDeviceCount()
  if not devices['available']:
    report['gpu'] = dict(devices, status='NOT_RUN')
    return
  require('CUDAExecutionProvider' in ort.get_available_providers(), 'ORT CUDA provider missing')
  ort.preload_dlls(directory=str(runtimeRoot / 'torch' / 'lib'))
  options.enable_profiling = True
  options.profile_file_prefix = str(reportPath.parent / ('ort-cuda-' + report['run_id']))
  cuda = ort.InferenceSession(payload, sess_options=options,
                             providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
  cuda.disable_fallback()
  require(cuda.get_providers()[0] == 'CUDAExecutionProvider', 'ORT silently rejected CUDA')
  actual = cuda.run(['output'], {'input': sample})[0]
  require(bool(np.array_equal(actual, expected)), 'ORT GPU result differs from reference')
  profilePath = Path(cuda.end_profiling())
  profile = json.loads(profilePath.read_text(encoding='utf-8'))
  executed = [item.get('name') for item in profile
              if item.get('args', {}).get('provider') == 'CUDAExecutionProvider']
  require(bool(executed), 'No ORT kernel was observed executing on CUDA')
  report['gpu'] = dict(devices, status='PASS', scope='Profiled ORT synthetic MatMul/Add',
                       cuda_kernels=executed, profile_path=str(profilePath))


def checkDino(runtimeRoot: Path, sourceRoot: Path | None, report: dict,
              reportPath: Path) -> None:
  require(sourceRoot is not None and sourceRoot.is_dir(), 'DINO requires the exact source checkout')
  sys.path.insert(1, str(sourceRoot))
  importlib.invalidate_caches()
  module = importlib.import_module('anomaly_func.dinov2_main_runtime')
  require(isWithin(Path(module.__file__), sourceRoot), 'DINO module escaped the source checkout')
  module.enable()
  environment = module.environment('CPUExecutionProvider')
  require(module.valid_environment(environment, 'CPUExecutionProvider'),
          'First-party DINO environment rejected the external runtime')
  checkOrt(runtimeRoot, report, reportPath, allowGpu=False)
  forbidden = sorted(name for name in sys.modules
                      if any(name == root or name.startswith(root + '.') for root in FORBIDDEN_DINO))
  require(not forbidden, 'DINO probe imported forbidden training modules: ' + repr(forbidden))
  report['checks'].update(dino_environment='PASS', environment=environment,
                          training_modules_imported=forbidden, model_inference='NOT_RUN',
                          production_worker_protocol='NOT_RUN')
  report['scope'] = ('Exact first-party DINO environment() and external ORT CPU fixture; '
                     'not the product worker protocol or model inference')


def checkHold(runtimeRoot: Path, sourceRoot: Path | None, report: dict,
              reportPath: Path, job: dict) -> None:
  psutil = importExternal('psutil', runtimeRoot)
  extension = importExternal('psutil._psutil_windows', runtimeRoot)
  require(psutil.Process().pid == os.getpid(), 'psutil native call failed before lock observation')
  recordDistribution(report, 'psutil', runtimeRoot)
  releasePath = Path(job['release_path']).resolve()
  require(not releasePath.exists(), 'Hold release file already exists')
  report['hold_target'] = str(Path(extension.__file__).resolve())
  report['status'] = 'READY'
  recordOrigins(report, runtimeRoot, sourceRoot)
  writeReport(reportPath, report)
  if job.get('ready_file'):
    writeReport(Path(job['ready_file']), report)
  timeout = float(job.get('timeout_seconds', 60))
  require(0 < timeout <= 120, 'Hold timeout must be between 0 and 120 seconds')
  deadline = time.monotonic() + timeout
  while not releasePath.exists():
    require(time.monotonic() < deadline, 'Host did not release the loaded-extension probe')
    time.sleep(0.1)
  report['checks']['loaded_extension_hold'] = 'PASS'


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--runtime-root', type=Path, required=True)
  parser.add_argument('--mode', choices=('core', 'pure', 'native', 'torch', 'ort', 'dino', 'hold'),
                      required=True)
  parser.add_argument('--report', type=Path, required=True)
  parser.add_argument('--source-root', type=Path)
  parser.add_argument('--job', type=Path)
  args = parser.parse_args()
  reportPath = args.report.resolve()
  runtimeRoot = args.runtime_root.resolve()
  sourceRoot = args.source_root.resolve() if args.source_root else None
  job = json.loads(args.job.read_text(encoding='utf-8-sig')) if args.job else {}
  runId = job.get('run_id') or uuid.uuid4().hex
  require(isinstance(runId, str) and runId.isascii()
          and all(character.isalnum() or character in '-_' for character in runId),
          'Invalid probe run_id')
  report = {'schema_version': SCHEMA_VERSION, 'status': 'FAIL', 'mode': args.mode,
            'run_id': runId, 'pid': os.getpid(), 'python': platform.python_version(),
            'frozen': bool(getattr(sys, 'frozen', False)), 'sys_executable': sys.executable,
            'executable': sys.executable, 'runtime_root': str(runtimeRoot),
            'source_root': str(sourceRoot) if sourceRoot else None,
            'checks': {}, 'metadata': {}, 'distributions': {},
            'scope': 'Frozen external module loading experiment, not product acceptance',
            'gpu': {'status': 'NOT_RUN', 'reason': 'Mode does not request GPU execution'},
            'network_policy': 'Python socket connection/DNS denied; OS networking not isolated'}
  started = time.monotonic()
  try:
    require(report['frozen'], 'Acceptance requires the actual frozen EXE, not host Python')
    require(os.name == 'nt', 'This probe targets Windows DLL loading')
    require(report['python'] == PYTHON_VERSION, 'Probe requires exact CPython ' + PYTHON_VERSION)
    require(not isWithin(reportPath, runtimeRoot), 'Reports cannot modify the external runtime')
    reportPath.parent.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONNOUSERSITE'] = '1'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['YOLO_AUTOINSTALL'] = 'false'
    sys.addaudithook(denyPythonNetwork)
    if args.mode == 'core':
      report['checks'].update(core_startup='PASS', optional_runtime_available=runtimeRoot.is_dir())
      optional = [name for name in ('torch', 'torchvision', 'numpy', 'onnxruntime', 'PyQt5')
                  if name in sys.modules]
      require(not optional, 'Minimal Core imported optional modules')
      report['checks']['optional_modules_imported'] = optional
    else:
      configureRuntime(runtimeRoot, report)
      if args.mode in ('torch', 'ort', 'dino'):
        loadQtBeforeCompute(runtimeRoot, report)
      if args.mode == 'pure':
        checkPure(runtimeRoot, report, job)
      elif args.mode == 'native':
        checkNative(runtimeRoot, report)
      elif args.mode == 'torch':
        checkTorch(runtimeRoot, report)
      elif args.mode == 'ort':
        checkOrt(runtimeRoot, report, reportPath, allowGpu=True)
      elif args.mode == 'dino':
        checkDino(runtimeRoot, sourceRoot, report, reportPath)
      elif args.mode == 'hold':
        checkHold(runtimeRoot, sourceRoot, report, reportPath, job)
    recordOrigins(report, runtimeRoot, sourceRoot)
    require(not NETWORK_ATTEMPTS, 'The runtime attempted network access')
    report['status'] = 'PASS'
  except Exception as error:
    report['status'] = 'FAIL'
    report['error'] = {'type': type(error).__name__, 'message': str(error),
                       'traceback': traceback.format_exc()}
    try:
      report['loaded_libraries_at_failure'] = loadedLibraries()
    except OSError as libraryError:
      report['library_inventory_error'] = str(libraryError)
  finally:
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    report['network_attempts'] = list(NETWORK_ATTEMPTS)
    writeReport(reportPath, report)
  return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
  raise SystemExit(main())
