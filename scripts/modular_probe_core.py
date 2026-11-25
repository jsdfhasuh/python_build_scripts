"""A stdlib-only frozen probe for external CP312 packages; not a product launcher."""

import argparse
import ctypes
import hashlib
import importlib
import importlib.metadata
import json
import marshal
import os
from pathlib import Path
import platform
import struct
import sys
import time
import traceback
import types
import uuid
import zlib


SCHEMA_VERSION = 1
PYTHON_VERSION = '3.12.10'
CRT_SHA256 = 'a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde'
FORBIDDEN_DINO = ('torch', 'torchvision', 'anomalib', 'lightning', 'lightning_fabric',
                  'pytorch_lightning', 'transformers')
DLL_HANDLES = []
NETWORK_ATTEMPTS = []
BOOTSTRAP_NAMES = ('struct', 'pyimod01_archive', 'pyimod02_importers',
                   'pyimod03_ctypes', 'pyimod04_pywin32')
# Capture identities before adding any external package or application path.
BOOTSTRAP_AT_START = {name: sys.modules.get(name) for name in BOOTSTRAP_NAMES}
CARCHIVE_MAGIC = b'MEI\x0c\x0b\x0a\x0b\x0e'
CARCHIVE_COOKIE = struct.Struct('!8sIIII64s')
CARCHIVE_ENTRY = struct.Struct('!IIIIBc')


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


def readBootstrapArchive(executable: Path) -> dict:
  # PyInstaller 6.18 imports CArchive module entries with PyImport_ExecCodeModule.
  # Their relative co_filename becomes __file__; it does not identify a CWD file.
  image = executable.read_bytes()
  cookieOffset = image.rfind(CARCHIVE_MAGIC)
  require(0 <= cookieOffset <= len(image) - CARCHIVE_COOKIE.size,
          'Core executable has no complete CArchive cookie')
  _, archiveBytes, tocOffset, tocBytes, pythonVersion, pythonLibrary = (
    CARCHIVE_COOKIE.unpack_from(image, cookieOffset))
  archiveStart = cookieOffset + CARCHIVE_COOKIE.size - archiveBytes
  tocStart = archiveStart + tocOffset
  tocEnd = tocStart + tocBytes
  require(0 <= archiveStart <= tocStart <= tocEnd == cookieOffset,
          'Core CArchive has invalid TOC bounds')
  pythonLibrary = pythonLibrary.rstrip(b'\0').decode('ascii')
  require(pythonVersion == 312 and pythonLibrary.casefold() == 'python312.dll',
          'Core CArchive does not target the selected CPython ABI')
  modules = {}
  cursor = tocStart
  while cursor < tocEnd:
    require(cursor + CARCHIVE_ENTRY.size <= tocEnd, 'Truncated Core CArchive TOC header')
    entryBytes, offset, storedBytes, rawBytes, compression, archiveType = (
      CARCHIVE_ENTRY.unpack_from(image, cursor))
    require(CARCHIVE_ENTRY.size < entryBytes <= tocEnd - cursor,
            'Invalid Core CArchive TOC entry length')
    nameBytes = image[cursor + CARCHIVE_ENTRY.size:cursor + entryBytes]
    require(nameBytes.endswith(b'\0'), 'Unterminated Core CArchive member name')
    name = nameBytes.rstrip(b'\0').decode('utf-8')
    cursor += entryBytes
    if name not in BOOTSTRAP_NAMES:
      continue
    require(name not in modules, 'Duplicate Core CArchive bootstrap member: ' + name)
    require(archiveType in (b'm', b'M') and compression in (0, 1),
            'Core bootstrap entry is not a CArchive Python module: ' + name)
    require(0 < rawBytes <= 8 * 1024 ** 2 and 0 < storedBytes
            and 0 <= offset <= tocOffset - storedBytes,
            'Invalid Core CArchive bootstrap payload bounds: ' + name)
    payload = image[archiveStart + offset:archiveStart + offset + storedBytes]
    if compression:
      decoder = zlib.decompressobj()
      payload = decoder.decompress(payload, rawBytes + 1)
      require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
              'Invalid Core CArchive bootstrap compression: ' + name)
    require(len(payload) == rawBytes, 'Core bootstrap payload size mismatch: ' + name)
    code = marshal.loads(payload)
    require(isinstance(code, types.CodeType) and code.co_filename == name + '.py',
            'Unexpected Core CArchive bootstrap code filename: ' + name)
    modules[name] = {'archive_type': archiveType.decode('ascii'),
                     'payload_sha256': hashlib.sha256(payload).hexdigest(),
                     'code_filename': code.co_filename}
  require(set(modules) == set(BOOTSTRAP_NAMES), 'Core CArchive is missing bootstrap modules')
  return {'bootstrap_archive': {'path': str(executable.resolve()),
                                 'sha256': hashlib.sha256(image).hexdigest(),
                                 'python_version': pythonVersion,
                                 'python_library': pythonLibrary},
          'bootstrap_modules': modules}


def recordBootstrapOrigins(report: dict) -> set[str]:
  modules = report.get('bootstrap_modules', {})
  require(set(modules) == set(BOOTSTRAP_NAMES), 'Verified Core bootstrap evidence is missing')
  for name, evidence in modules.items():
    module = sys.modules.get(name)
    require(module is not None and module is BOOTSTRAP_AT_START[name],
            'Core CArchive bootstrap module was replaced: ' + name)
    moduleFile = getattr(module, '__file__', None)
    require(moduleFile == evidence['code_filename'] == name + '.py',
            'Core CArchive bootstrap origin changed: ' + name)
    evidence['module_file'] = moduleFile
    evidence['module_spec_origin'] = getattr(getattr(module, '__spec__', None), 'origin', None)
  return set(modules)


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


def generatedTorchOrigin(name: str, module, runtimeRoot: Path) -> dict:
  descriptions = {'torch.ops': ('torch._ops', '_Ops', 'ops', '_ops.py'),
                  'torch.classes': ('torch._classes', '_Classes', 'classes', '_classes.py')}
  require(name in descriptions, 'Unreviewed generated module: ' + name)
  implementationName, className, attribute, filename = descriptions[name]
  implementation = sys.modules.get(implementationName)
  torch = sys.modules.get('torch')
  require(implementation is not None and torch is not None,
          'Generated Torch namespace has no implementation module: ' + name)
  implementationFile = vars(implementation).get('__file__')
  torchFile = vars(torch).get('__file__')
  require(bool(implementationFile) and Path(implementationFile).is_absolute()
          and Path(implementationFile).resolve() == (runtimeRoot / 'torch' / filename).resolve()
          and bool(torchFile) and Path(torchFile).is_absolute()
          and isWithin(Path(torchFile), runtimeRoot),
          'Generated Torch namespace implementation escaped external runtime: ' + name)
  require(type(module) is vars(implementation).get(className)
          and vars(implementation).get(attribute) is module and vars(torch).get(attribute) is module
          and getattr(module, '__file__', None) == filename,
          'Generated Torch namespace identity was replaced: ' + name)
  return {'kind': 'generated_module', 'module_file': filename,
          'implementation_module': implementationName, 'implementation_class': className,
          'implementation_file': str(Path(implementationFile).resolve())}


def recordOrigins(report: dict, runtimeRoot: Path, sourceRoot: Path | None) -> None:
  bootstrap = recordBootstrapOrigins(report)
  coreRoot = Path(sys.executable).resolve().parent
  permitted = [coreRoot, runtimeRoot]
  if sourceRoot is not None:
    permitted.append(sourceRoot)
  origins = {}
  external = {}
  unexpected = {}
  embedded = {}
  generated = {}
  for name, module in tuple(sys.modules.items()):
    if name in bootstrap:
      embedded[name] = 'carchive'
      continue
    if name in ('torch.ops', 'torch.classes'):
      generated[name] = generatedTorchOrigin(name, module, runtimeRoot)
      continue
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
  report['generated_module_origins'] = generated
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
  require(sum(Path(path).name.casefold() == 'python312.dll' for path in pythonDlls) == 1,
          'The frozen process must load exactly one python312.dll')
  require(all(isWithin(Path(path), coreRoot) for path in pythonDlls),
          'A second external Python DLL entered the frozen process')
  report['python_files'] = [{'path': path, 'sha256': fileHash(Path(path)),
                             'bytes': Path(path).stat().st_size} for path in pythonDlls]
  vcRuntimeDlls = [path for path in report['loaded_libraries']
                   if Path(path).name.casefold().startswith('vcruntime140')
                   and Path(path).suffix.casefold() == '.dll']
  report['vcruntime_dlls'] = vcRuntimeDlls
  require(any(Path(path).name.casefold() == 'vcruntime140.dll' for path in vcRuntimeDlls),
          'The frozen process did not load its VCRUNTIME140 ABI dependency')
  require(all(isWithin(Path(path), coreRoot) for path in vcRuntimeDlls),
          'A VCRUNTIME140 DLL loaded outside the CPython Core')
  report['vcruntime_files'] = [{'path': path, 'sha256': fileHash(Path(path)),
                               'bytes': Path(path).stat().st_size} for path in vcRuntimeDlls]
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
  for name in ('vcruntime140.dll', 'vcruntime140_1.dll'):
    library = coreLibraries / name
    require(library.is_file(), 'Core is missing its exact CPython ABI dependency: ' + name)
    DLL_HANDLES.append(ctypes.CDLL(str(library), winmode=0x1100))
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
  imageOps = importExternal('torchvision.io', runtimeRoot)
  pixels = torch.arange(12, dtype=torch.uint8).reshape(3, 2, 2)
  encoded = imageOps.encode_png(pixels)
  require(torch.equal(imageOps.decode_png(encoded), pixels),
          'TorchVision native image extension failed with the Core-owned Python DLL')
  recordDistribution(report, 'torch', runtimeRoot)
  recordDistribution(report, 'torchvision', runtimeRoot)
  report['checks'].update(torch_cpu='PASS', torchvision_cpu_nms='PASS',
                          torchvision_image_roundtrip='PASS',
                          torch_version=torch.__version__, torchvision_version=vision.__version__,
                          cuda_build=torch.version.cuda)
  available = torch.cuda.is_available()
  devices = cudaDeviceCount()
  report['checks'].update(torch_cuda_available=available, cuda_driver_probe=devices)
  if available:
    report['gpu'] = {'status': 'FAIL', 'scope': 'Torch matmul and TorchVision NMS',
                     'driver_probe': devices}
    actual = (left.cuda() @ right.cuda()).cpu().tolist()
    chosen = ops.nms(boxes.cuda(), scores.cuda(), 0.5).cpu().tolist()
    torch.cuda.synchronize()
    require(actual == expected and chosen == [0, 2], 'External Torch GPU operation failed')
    report['gpu'] = {'status': 'PASS', 'scope': 'Torch matmul and TorchVision NMS',
                     'device': torch.cuda.get_device_name(0), 'driver_probe': devices}
  else:
    if devices['available']:
      report['gpu'] = {'status': 'FAIL', 'driver_probe': devices,
                       'reason': 'CUDA driver exposes a device but Torch cannot use CUDA'}
      raise RuntimeError(report['gpu']['reason'])
    report['gpu'] = {'status': 'NOT_RUN', 'reason': 'torch.cuda.is_available() is false',
                     'device_count': torch.cuda.device_count(), 'driver_probe': devices}


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
    report.update(readBootstrapArchive(Path(sys.executable)))
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
