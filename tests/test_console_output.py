import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from branding_fixtures import writeProject
from console_utils import configureConsole


ROOT = Path(__file__).resolve().parents[1]


class ConsoleOutputTests(unittest.TestCase):
  def test_redirected_ascii_streams_emit_utf8_without_losing_names(self) -> None:
    result = subprocess.run([
      sys.executable, '-c',
      'from console_utils import configureConsole; import sys; configureConsole(); '
      'print("视觉 工坊"); print("图标路径", file=sys.stderr)',
    ], cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'ascii'},
       capture_output=True, check=False, timeout=20)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stdout.decode('utf-8').strip(), '视觉 工坊')
    self.assertEqual(result.stderr.decode('utf-8').strip(), '图标路径')

  def test_config_resolver_accepts_chinese_with_legacy_output_encoding(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      config, _, _ = writeProject(Path(directory))
      result = subprocess.run([
        sys.executable, str(ROOT / 'scripts/resolve_build_config.py'),
        '--config', str(config), '--program-name', '视觉 工坊',
      ], env={**os.environ, 'PYTHONIOENCODING': 'cp1252'},
         capture_output=True, check=False, timeout=20)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(json.loads(result.stdout.decode('utf-8'))['config']['name'], '视觉 工坊')

  def test_embedding_streams_without_reconfigure_are_preserved(self) -> None:
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
      configureConsole()
      print('视觉 工坊')
    self.assertEqual(output.getvalue(), '视觉 工坊\n')


if __name__ == '__main__':
  unittest.main()
