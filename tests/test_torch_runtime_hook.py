import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


HOOK = Path(__file__).resolve().parents[1] / 'pyi_rth_torch_dll.py'


class TorchRuntimeHookTests(unittest.TestCase):
  def runHook(self, *, debug=False, stream=None, workerFlag=None, extraArgs=(),
              crtPresent=True, loadError=None):
    code = compile(HOOK.read_text(encoding='utf-8'), str(HOOK), 'exec')
    runtime = 'fixture-runtime'
    crtPath = os.path.abspath(os.path.join(runtime, 'msvcp140.dll'))
    environment = {'PATH': 'original-path'}
    if debug:
      environment['PYI_TORCH_DLL_DEBUG'] = '1'
    imports = []
    realImport = __import__

    def trackImport(name, *args, **kwargs):
      imports.append(name)
      return realImport(name, *args, **kwargs)

    with contextlib.ExitStack() as stack:
      stack.enter_context(patch.dict(os.environ, environment, clear=True))
      stack.enter_context(patch.object(sys, '_MEIPASS', runtime, create=True))
      stack.enter_context(patch.object(sys, 'stderr', stream))
      arguments = ['app'] + ([workerFlag] if workerFlag else []) + list(extraArgs)
      stack.enter_context(patch.object(sys, 'argv', arguments))
      stack.enter_context(patch('os.path.isdir', return_value=True))
      isFile = stack.enter_context(patch('os.path.isfile',
                                        side_effect=lambda path: crtPresent or path != crtPath))
      addDirectory = stack.enter_context(patch('os.add_dll_directory', create=True))
      preload = stack.enter_context(patch('ctypes.CDLL', side_effect=loadError))
      openFile = stack.enter_context(patch('builtins.open'))
      stack.enter_context(patch('builtins.__import__', side_effect=trackImport))
      namespace = {}
      exec(code, namespace)
      openFile.assert_not_called()
      directories = [runtime, os.path.join(runtime, 'torch', 'lib'),
                     os.path.join(runtime, '_internal'),
                     os.path.join(runtime, '_internal', 'torch', 'lib')]
      self.assertEqual(addDirectory.call_args_list, [call(path) for path in directories])
      if workerFlag == '--dino-onnx-worker':
        expected = [call(crtPath, winmode=0x1100)] if crtPresent else []
        self.assertEqual(preload.call_args_list, expected)
        self.assertEqual(isFile.call_args_list, [call(crtPath)])
        self.assertTrue(os.path.isabs(crtPath))
      else:
        expected = [call(os.path.join(directory, name)) for directory in directories[1::2]
                    for name in ('torch_global_deps.dll', 'c10.dll', 'torch_cpu.dll',
                                 'torch_python.dll')]
        self.assertCountEqual(preload.call_args_list, expected)
      self.assertFalse(any(name == 'torch' or name.startswith('torch.') for name in imports))
      self.assertIn('fixture-runtime', os.environ['PATH'])
      self.assertTrue(os.environ['PATH'].endswith('original-path'))
      self.assertEqual(os.environ['KMP_DUPLICATE_LIB_OK'], 'TRUE')
      self.assertEqual(os.environ['OMP_WAIT_POLICY'], 'PASSIVE')
    return crtPath

  def test_default_startup_does_not_write_logs(self):
    for flag in (None, '--dino-onnx-worker'):
      with self.subTest(flag=flag):
        stream = io.StringIO()
        self.runHook(stream=stream, workerFlag=flag)
        self.assertEqual(stream.getvalue(), '')

  def test_dino_preloads_only_absolute_bundled_msvcp_with_safe_flags_and_no_torch(self):
    self.runHook(workerFlag='--dino-onnx-worker')

  def test_dino_missing_bundled_msvcp_logs_without_searching_other_crts_or_torch(self):
    for debug in (False, True):
      with self.subTest(debug=debug):
        stream = io.StringIO()
        path = self.runHook(debug=debug, stream=stream, workerFlag='--dino-onnx-worker',
                            crtPresent=False)
        if debug:
          self.assertIn('[torch-dll] DINO CRT preload missing: ' + path, stream.getvalue())
        else:
          self.assertEqual(stream.getvalue(), '')

  def test_dino_msvcp_load_failure_keeps_skip_and_reports_original_error_without_fallback(self):
    for debug in (False, True):
      with self.subTest(debug=debug):
        stream = io.StringIO()
        error = OSError('[WinError 1114] DLL initialization failed')
        path = self.runHook(debug=debug, stream=stream, workerFlag='--dino-onnx-worker',
                            loadError=error)
        if debug:
          self.assertIn('[torch-dll] DINO CRT preload fail: ' + path, stream.getvalue())
          self.assertIn(str(error), stream.getvalue())
        else:
          self.assertEqual(stream.getvalue(), '')

  def test_other_workers_keep_existing_preloads(self):
    for flag in ('--cnn-patchcore-onnx-worker', '--multiprocessing-fork', '--dino-onnx-worker-other'):
      with self.subTest(flag=flag):
        self.runHook(workerFlag=flag)

  def test_dino_flag_outside_entrypoint_position_does_not_change_other_preloads(self):
    self.runHook(workerFlag='--other-mode', extraArgs=['--dino-onnx-worker'])

  def test_explicit_debug_uses_stderr_without_opening_files(self):
    stream = io.StringIO()
    self.runHook(debug=True, stream=stream)
    self.assertIn('[torch-dll] base=fixture-runtime', stream.getvalue())
    self.assertIn('[torch-dll] preload ok:', stream.getvalue())

  def test_dino_debug_reports_the_exact_crt_load(self):
    stream = io.StringIO()
    path = self.runHook(debug=True, stream=stream, workerFlag='--dino-onnx-worker')
    self.assertIn('[torch-dll] DINO CRT preload ok: ' + path, stream.getvalue())

  def test_windowed_app_without_stderr_still_initializes_dlls(self):
    for flag in (None, '--dino-onnx-worker'):
      with self.subTest(flag=flag):
        self.runHook(debug=True, workerFlag=flag)

  def test_broken_stderr_does_not_break_dll_initialization(self):
    for flag in (None, '--dino-onnx-worker'):
      with self.subTest(flag=flag):
        stream = Mock()
        stream.write.side_effect = OSError('closed stream')
        self.runHook(debug=True, stream=stream, workerFlag=flag)

  def test_real_subprocess_does_not_create_installation_files(self):
    script = (
      'import runpy, sys\n'
      'hook, executable, runtime, flag = sys.argv[1:]\n'
      'sys.executable = executable\n'
      'sys._MEIPASS = runtime\n'
      'sys.argv = [executable] + ([flag] if flag else [])\n'
      'runpy.run_path(hook)\n'
    )
    with tempfile.TemporaryDirectory(prefix='torch-hook-startup-') as directory:
      root = Path(directory)
      runtime = root / '_internal'
      runtime.mkdir()
      executable = root / 'Application.exe'
      executable.write_bytes(b'test placeholder, never executed')
      before = set(root.rglob('*'))
      for debug in ('0', '1'):
        for flag in ('', '--dino-onnx-worker'):
          with self.subTest(debug=debug, flag=flag):
            environment = dict(os.environ, PYI_TORCH_DLL_DEBUG=debug, PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run(
              [sys.executable, '-B', '-c', script, str(HOOK), str(executable), str(runtime), flag],
              cwd=root, env=environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(root.rglob('*')), before)
            self.assertFalse((root / 'torch_dll_hook.log').exists())
            self.assertEqual('[torch-dll]' in result.stderr, debug == '1')


if __name__ == '__main__':
  unittest.main()
