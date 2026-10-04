import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


HOOK = Path(__file__).resolve().parents[1] / 'pyi_rth_torch_dll.py'


class TorchRuntimeHookTests(unittest.TestCase):
  def runHook(self, *, debug=False, stream=None):
    code = compile(HOOK.read_text(encoding='utf-8'), str(HOOK), 'exec')
    environment = {'PATH': 'original-path'}
    if debug:
      environment['PYI_TORCH_DLL_DEBUG'] = '1'
    with contextlib.ExitStack() as stack:
      stack.enter_context(patch.dict(os.environ, environment, clear=True))
      stack.enter_context(patch.object(sys, '_MEIPASS', 'fixture-runtime', create=True))
      stack.enter_context(patch.object(sys, 'stderr', stream))
      stack.enter_context(patch('os.path.isdir', return_value=True))
      stack.enter_context(patch('os.path.isfile', return_value=True))
      addDirectory = stack.enter_context(patch('os.add_dll_directory', create=True))
      preload = stack.enter_context(patch('ctypes.CDLL'))
      openFile = stack.enter_context(patch('builtins.open'))
      namespace = {}
      exec(code, namespace)
      openFile.assert_not_called()
      self.assertEqual(addDirectory.call_count, 4)
      self.assertEqual(preload.call_count, 8)
      self.assertIn('fixture-runtime', os.environ['PATH'])
      self.assertTrue(os.environ['PATH'].endswith('original-path'))
      self.assertEqual(os.environ['KMP_DUPLICATE_LIB_OK'], 'TRUE')
      self.assertEqual(os.environ['OMP_WAIT_POLICY'], 'PASSIVE')

  def test_default_startup_does_not_write_logs(self):
    stream = io.StringIO()
    self.runHook(stream=stream)
    self.assertEqual(stream.getvalue(), '')

  def test_explicit_debug_uses_stderr_without_opening_files(self):
    stream = io.StringIO()
    self.runHook(debug=True, stream=stream)
    self.assertIn('[torch-dll] base=fixture-runtime', stream.getvalue())
    self.assertIn('[torch-dll] preload ok:', stream.getvalue())

  def test_windowed_app_without_stderr_still_initializes_dlls(self):
    self.runHook(debug=True)

  def test_broken_stderr_does_not_break_dll_initialization(self):
    stream = Mock()
    stream.write.side_effect = OSError('closed stream')
    self.runHook(debug=True, stream=stream)

  def test_real_subprocess_does_not_create_installation_files(self):
    script = (
      'import runpy, sys\n'
      'sys.executable = sys.argv[2]\n'
      'sys._MEIPASS = sys.argv[3]\n'
      'runpy.run_path(sys.argv[1])\n'
    )
    with tempfile.TemporaryDirectory(prefix='torch-hook-startup-') as directory:
      root = Path(directory)
      runtime = root / '_internal'
      runtime.mkdir()
      executable = root / 'Application.exe'
      executable.write_bytes(b'test placeholder, never executed')
      before = set(root.rglob('*'))
      for debug in ('0', '1'):
        with self.subTest(debug=debug):
          environment = dict(os.environ, PYI_TORCH_DLL_DEBUG=debug, PYTHONDONTWRITEBYTECODE='1')
          result = subprocess.run(
            [sys.executable, '-B', '-c', script, str(HOOK), str(executable), str(runtime)],
            cwd=root, env=environment, capture_output=True, text=True, timeout=30,
          )
          self.assertEqual(result.returncode, 0, result.stderr)
          self.assertEqual(set(root.rglob('*')), before)
          self.assertFalse((root / 'torch_dll_hook.log').exists())
          self.assertEqual('[torch-dll]' in result.stderr, debug == '1')


if __name__ == '__main__':
  unittest.main()
