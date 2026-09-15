import contextlib
import io
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
    stack = contextlib.ExitStack()
    self.addCleanup(stack.close)
    self.readModules = stack.enter_context(patch.object(
      runtime, 'readPackagedModules', return_value=set(self.profile['modules'])))
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
