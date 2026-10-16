import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

import vision_train_runtime as runtime
from build_config import BuildConfigError


class RequirementsTests(unittest.TestCase):
  def test_ci_overrides_are_resolved_together_without_changing_unrelated_pins(self):
    result = runtime.makeRequirements(
      '# source\ntorch==2.5.1\nnumpy<=1.26.4\nplatformdirs==4.5.1\nkaggle\n',
      ['torchvision==0.20.1', 'kagglesdk==0.1.31', 'onnxruntime-gpu==1.23.2'],
      runtime.loadProfile())
    for text in ('numpy<=1.26.4', 'torch==2.5.1+cu121', 'torchvision==0.20.1+cu121',
                 'kaggle==2.2.4', 'kagglesdk==0.1.37', 'platformdirs==4.10.0',
                 'onnxruntime-gpu==1.23.2'):
      self.assertIn(text, result)
    self.assertNotIn('torch==2.5.1', result)
    self.assertNotIn('kagglesdk==0.1.31', result)
    self.assertEqual(result.count('kaggle==2.2.4'), 1)

  def test_unrecognized_pip_directives_fail_instead_of_reading_wrong_relative_files(self):
    for text in ('-r other.txt', '--index-url https://example.invalid', './local-wheel.whl'):
      with self.subTest(text=text), self.assertRaises(BuildConfigError):
        runtime.makeRequirements(text, [], runtime.loadProfile())

  def test_requirements_bom_encodings(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'requirements.txt'
      for encoding in ('utf-8', 'utf-8-sig', 'utf-16'):
        path.write_text('torch==2.5.1\n', encoding=encoding)
        self.assertEqual(runtime.readRequirements(path).splitlines(), ['torch==2.5.1'])

  def test_gpu_install_precedes_one_combined_resolver_and_pip_check(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      path = root / 'requirements.txt'
      path.write_text('torch==2.5.1\n', encoding='utf-8')
      commands = []
      def record(command):
        commands.append(command)
        if '-r' in command:
          text = Path(command[command.index('-r') + 1]).read_text(encoding='utf-8')
          self.assertIn('kagglesdk==0.1.37', text)
          self.assertNotIn('kagglesdk==0.1.31', text)
      with patch.object(runtime, 'checkPlatform'), patch.object(runtime, 'runCommand', record):
        runtime.installRuntime(root)
      self.assertIn('--index-url', commands[0])
      self.assertIn('torch==2.5.1+cu121', commands[0])
      self.assertIn('-r', commands[1])
      self.assertIn('--force-reinstall', commands[2])
      self.assertIn('onnxruntime-gpu==1.23.2', commands[2])
      self.assertEqual(commands[3][-1], 'check')
      self.assertEqual(path.read_text(), 'torch==2.5.1\n')

  def test_install_failure_stops_before_next_step(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      (root / 'requirements.txt').write_text('torch==2.5.1\n')
      with patch.object(runtime, 'checkPlatform'), \
           patch.object(runtime, 'runCommand', side_effect=BuildConfigError('pip failed')) as run:
        with self.assertRaisesRegex(BuildConfigError, 'pip failed'):
          runtime.installRuntime(root)
        self.assertEqual(run.call_count, 1)

  def test_nonzero_exit_is_fatal(self):
    with patch.object(runtime.subprocess, 'run', return_value=Mock(returncode=1)), \
         contextlib.redirect_stdout(io.StringIO()):
      with self.assertRaises(BuildConfigError):
        runtime.runCommand(['python', '-m', 'pip', 'check'])


class EnvironmentTests(unittest.TestCase):
  def test_cpu_environment_cannot_reach_functional_import_check(self):
    cpu = SimpleNamespace(__version__='2.5.1+cpu', version=SimpleNamespace(cuda=None))
    with patch.object(runtime, 'checkPlatform'), patch.object(runtime, 'runCommand') as run, \
         patch.object(runtime.importlib, 'import_module', return_value=cpu):
      with self.assertRaisesRegex(BuildConfigError, 'Expected torch'):
        runtime.validateEnvironment(Path('source'))
      self.assertEqual(run.call_count, 1)
      self.assertEqual(run.call_args.args[0][-1], 'check')

  def test_functional_import_failure_is_fatal_without_requiring_a_gpu(self):
    profile = runtime.loadProfile()
    packages = (profile['torch_packages'] + profile['packages'] + profile['binary_owners']
                + list(profile['overrides'].values()))
    versions = dict(text.split('==', 1) for text in packages)
    gpu = SimpleNamespace(__version__='2.5.1+cu121', version=SimpleNamespace(cuda='12.1'),
                          __file__='site-packages/torch/__init__.py')
    with patch.object(runtime, 'checkPlatform'), \
         patch.object(runtime.importlib, 'import_module', return_value=gpu), \
         patch.object(runtime.importlib.metadata, 'version', side_effect=versions.__getitem__), \
         patch.object(runtime, 'requireFiles'), \
         patch.object(runtime, 'runCommand', side_effect=[None, BuildConfigError('import failed')]) \
         as run:
      with self.assertRaisesRegex(BuildConfigError, 'import failed'):
        runtime.validateEnvironment(Path('source'))
      code = run.call_args.args[0][-1]
      self.assertIn('from anomalib.models import Patchcore', code)
      self.assertIn('ApiGetSubmissionLimitsRequest', code)
      self.assertNotIn('cuda.is_available', code)


class PackageTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.app = Path(temporary.name)
    self.internal = self.app / '_internal'
    self.profile = runtime.loadProfile()
    self.write('torch/version.py', "__version__ = '2.5.1+cu121'\ncuda: str = '12.1'\n")
    self.write('onnxruntime/capi/onnxruntime_providers_cuda.dll')
    self.write('_polars_runtime_32/_polars_runtime.pyd')
    for name in self.profile['torch_dlls']:
      self.write('torch/lib/' + name)
    for name in self.profile['models']:
      self.write('static/models/' + name)
    for name in set(runtime.IMAGE_SIMPLIFICATION_DISTRIBUTIONS + runtime.DINO_MAIN_METADATA):
      self.write(f'{name.lower()}-1.0.dist-info/METADATA',
                 f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n')
    for name in runtime.KAGGLE_SOURCE_FILES:
      self.write(name)
    for name in ('python311.dll', 'onnxruntime/capi/onnxruntime_pybind11_state.pyd',
                 'onnxruntime/capi/onnxruntime_providers_shared.dll'):
      self.write(name)
    stack = contextlib.ExitStack()
    self.addCleanup(stack.close)
    self.readModules = stack.enter_context(patch.object(
      runtime, 'readPackagedModules', return_value=set(self.profile['modules'] + runtime.DINO_MAIN_MODULES)))
    self.readImports = stack.enter_context(patch.object(runtime, 'readDllImports', return_value=[]))

  def write(self, name, text='fixture'):
    path = self.internal / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')

  def test_complete_package_reports_no_gpu_execution_claim(self):
    report = runtime.validatePackage(self.app, 'VisionWorkshop')
    self.assertEqual(report['status'], 'passed')
    self.assertEqual(report['gpu_execution'], 'not-run')
    self.readModules.assert_called_once_with(self.app / 'VisionWorkshop.exe')

  def test_cpu_build_is_rejected_before_archive_inspection(self):
    self.write('torch/version.py', "__version__ = '2.5.1+cpu'\ncuda = None\n")
    with self.assertRaisesRegex(BuildConfigError, 'Expected torch'):
      runtime.validatePackage(self.app, 'VisionWorkshop')
    self.readModules.assert_not_called()

  def configureSharedDinoRuntime(self, extraNames=()):
    self.configureLegacyDinoRuntime()
    from build_records import fileHash
    binding = 'onnxruntime/capi/onnxruntime_pybind11_state.cp312-win_amd64.pyd'
    names = [binding, *('onnxruntime/capi/' + name for name in (
      'onnxruntime.dll', 'onnxruntime_providers_shared.dll',
      'onnxruntime_providers_cuda.dll', 'onnxruntime_providers_tensorrt.dll')),
      'torch/lib/cudart64_12.dll', 'torch/lib/cudnn64_9.dll',
      'torch/lib/cublas64_12.dll', 'torch/lib/cublasLt64_12.dll', *extraNames]
    for name in names:
      self.write(name)
    shared = {name: {'size': (self.internal / name).stat().st_size,
                     'sha256': fileHash(self.internal / name)} for name in names}
    path = self.internal / 'dino_runtime/runtime.json'
    document = json.loads(path.read_text())
    document.update(format='dino_windows_runtime_p7_v2', finalized=True,
                    distribution='onnxruntime-gpu',
                    providers=['CPUExecutionProvider', 'CUDAExecutionProvider'],
                    shared_files=shared, binding=shared[binding])
    path.write_text(json.dumps(document))
    return path, document

  def test_shared_dino_libraries_are_verified_without_loading_gpu(self):
    path, document = self.configureSharedDinoRuntime()
    runtime.validateDinoRuntime(path.parent)
    self.write('torch/lib/cudnn64_9.dll', 'changed')
    with self.assertRaisesRegex(BuildConfigError, 'shared library hash'):
      runtime.validateDinoRuntime(path.parent)
    document['shared_files']['../escape.dll'] = document['binding']
    self.write('torch/lib/cudnn64_9.dll')
    path.write_text(json.dumps(document))
    with self.assertRaisesRegex(BuildConfigError, 'Unexpected DINO'):
      runtime.validateDinoRuntime(path.parent)

  def test_shared_dino_cuda_filenames_allow_windows_mixed_case(self):
    path, _ = self.configureSharedDinoRuntime([
      'torch/lib/nvJitLink_120_0.dll', 'torch/lib/NVRTC64_120_0.DLL',
      'torch/lib/cuDNN_ops64_9.dll',
    ])
    runtime.validateDinoRuntime(path.parent)

  def test_shared_dino_mixed_case_library_still_requires_matching_hash(self):
    name = 'torch/lib/nvJitLink_120_0.dll'
    path, _ = self.configureSharedDinoRuntime([name])
    self.write(name, 'changed')  # Same size as the original fixture.
    with self.assertRaisesRegex(BuildConfigError, 'shared library hash mismatch'):
      runtime.validateDinoRuntime(path.parent)

  def test_shared_dino_mixed_case_library_must_exist(self):
    name = 'torch/lib/nvJitLink_120_0.dll'
    path, _ = self.configureSharedDinoRuntime([name])
    (self.internal / name).unlink()
    with self.assertRaises(FileNotFoundError):
      runtime.validateDinoRuntime(path.parent)

  def test_shared_dino_filename_case_does_not_relax_path_or_library_allowlist(self):
    path, document = self.configureSharedDinoRuntime()
    for name in ('torch/lib/../nvJitLink_120_0.dll', 'torch/lib/sub/nvJitLink_120_0.dll',
                 'torch\\lib\\nvJitLink_120_0.dll', '/torch/lib/nvJitLink_120_0.dll',
                 'TORCH/lib/nvJitLink_120_0.dll', 'torch/lib/unrelated.dll',
                 'torch/lib/nvJitLink_120_0.exe', 'torch/lib/nvJitLink_120_0.dll:stream',
                 'torch/lib/nvJitLink_\u0130.dll'):
      with self.subTest(name=name):
        document['shared_files'][name] = document['binding']
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(BuildConfigError, 'Unexpected DINO'):
          runtime.validateDinoRuntime(path.parent)
        del document['shared_files'][name]

  def configureLegacyDinoRuntime(self):
    for name in runtime.DINO_RUNTIME_FILES:
      self.write('dino_runtime/' + name)
    self.write('dino_runtime/runtime.json', json.dumps({
      'format': 'dino_windows_runtime_p7_v1',
      'files': runtime.scanFiles(self.internal / 'dino_runtime'),
    }))

  def test_legacy_missing_dino_runtime_is_rejected(self):
    self.configureLegacyDinoRuntime()
    (self.internal / 'dino_runtime/python.exe').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'python.exe'):
      runtime.validateDinoRuntime(self.internal / 'dino_runtime')

  def test_dino_runtime_corruption_or_extra_file_blocks_packaging(self):
    self.configureLegacyDinoRuntime()
    for name in ('python312.dll', 'extra.pth'):
      with self.subTest(name=name):
        self.write('dino_runtime/' + name, 'changed')
        with self.assertRaisesRegex(BuildConfigError, 'DINO runtime inventory/hash'):
          runtime.validateDinoRuntime(self.internal / 'dino_runtime')
        if name == 'python312.dll':
          self.write('dino_runtime/' + name)
        else:
          (self.internal / 'dino_runtime' / name).unlink()

  def test_main_runtime_rejects_obsolete_second_environment(self):
    self.configureLegacyDinoRuntime()
    with self.assertRaisesRegex(BuildConfigError, 'Obsolete DINO'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_main_runtime_requires_worker_modules(self):
    self.readModules.return_value.remove('dino_onnx_entry')
    with self.assertRaisesRegex(BuildConfigError, 'dino_onnx_entry'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_main_runtime_requires_native_binding(self):
    (self.internal / 'onnxruntime/capi/onnxruntime_pybind11_state.pyd').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'onnxruntime_pybind11_state'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_main_runtime_requires_metadata(self):
    (self.internal / 'psutil-1.0.dist-info/METADATA').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'DINO main-runtime metadata: psutil'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_missing_cudnn_component_is_fatal(self):
    (self.internal / 'torch/lib/cudnn_ops64_9.dll').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'cudnn_ops64_9.dll'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_hidden_import_must_exist_in_exe_not_just_build_environment(self):
    self.readModules.return_value.remove('anomalib')
    with self.assertRaisesRegex(BuildConfigError, 'Missing EXE modules: anomalib'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_polars_native_binary_is_required(self):
    (self.internal / '_polars_runtime_32/_polars_runtime.pyd').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'Polars native'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_source_model_is_required(self):
    (self.internal / 'static/models/edge_sam_encoder.onnx').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'edge_sam_encoder.onnx'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_image_simplification_weight_is_required(self):
    (self.internal / 'static/models/image_simplification/dinov2_vits14/model.safetensors').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'dinov2_vits14/model.safetensors'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_metadata_must_be_bundled_even_when_installed_in_build_environment(self):
    for name in runtime.IMAGE_SIMPLIFICATION_DISTRIBUTIONS:
      with self.subTest(name=name):
        path = self.internal / f'{name.lower()}-1.0.dist-info/METADATA'
        text = path.read_text(encoding='utf-8')
        path.unlink()
        with self.assertRaisesRegex(BuildConfigError, f'distribution metadata: {name}'):
          runtime.validatePackage(self.app, 'VisionWorkshop')
        path.write_text(text, encoding='utf-8')

  def test_safetensors_adapter_must_be_in_the_executable(self):
    self.readModules.return_value.remove('safetensors.torch')
    with self.assertRaisesRegex(BuildConfigError, 'Missing EXE modules: safetensors.torch'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_builder_source_must_exist_as_data_even_when_imports_are_available(self):
    for name in runtime.KAGGLE_SOURCE_FILES:
      with self.subTest(name=name):
        (self.internal / name).unlink()
        with self.assertRaisesRegex(BuildConfigError, 'Missing'):
          runtime.validatePackage(self.app, 'VisionWorkshop')
        self.write(name)

  def test_pe_dependency_check_finds_unlisted_cuda_dependency(self):
    self.readImports.return_value = ['cudnn_new64_9.dll']
    with self.assertRaisesRegex(BuildConfigError, 'cudnn_new64_9.dll'):
      runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_driver_dll_is_not_required_in_distribution(self):
    self.readImports.return_value = ['nvcuda.dll', 'kernel32.dll']
    runtime.validatePackage(self.app, 'VisionWorkshop')

  def test_version_file_is_parsed_not_executed(self):
    self.write('torch/version.py', "raise RuntimeError('must not execute')\n"
               "__version__ = '2.5.1+cu121'\ncuda = '12.1'\n")
    runtime.validatePackage(self.app, 'VisionWorkshop')


if __name__ == '__main__':
  unittest.main()
