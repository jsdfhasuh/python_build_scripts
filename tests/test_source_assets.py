import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import branding_build
from build_config import BuildConfigError


class SourceAssetTests(unittest.TestCase):
  def test_script_uses_build_interpreter_and_source_directory(self):
    with tempfile.TemporaryDirectory() as folder:
      root = Path(folder)
      script = root / 'prepare.py'
      script.write_text('pass')
      resolved = SimpleNamespace(config={'prepare_source_assets': 'prepare.py'})
      with patch.object(branding_build.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
        branding_build.prepareSourceAssets(resolved, root)
      run.assert_called_once_with([branding_build.sys.executable, '-B', str(script)],
                                 cwd=root, check=False)

  def test_preparation_failure_stops_before_compiler_and_snapshot(self):
    resolved = SimpleNamespace(config={})
    with patch.object(branding_build.sys, 'platform', 'win32'), \
         patch.object(branding_build, 'prepareSourceAssets', side_effect=BuildConfigError('bad hash')), \
         patch.object(branding_build, 'buildCommands') as compiler, \
         patch.object(branding_build, 'inputSnapshot') as snapshot:
      with self.assertRaisesRegex(BuildConfigError, 'bad hash'):
        branding_build.executeBuild(resolved, None, Path.cwd())
    compiler.assert_not_called()
    snapshot.assert_not_called()

  def test_nonzero_script_and_escaping_path_are_rejected(self):
    with tempfile.TemporaryDirectory() as folder:
      root = Path(folder)
      (root / 'prepare.py').write_text('pass')
      resolved = SimpleNamespace(config={'prepare_source_assets': 'prepare.py'})
      with patch.object(branding_build.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
        with self.assertRaisesRegex(BuildConfigError, 'exit code 1'):
          branding_build.prepareSourceAssets(resolved, root)
      resolved.config['prepare_source_assets'] = '../prepare.py'
      with patch.object(branding_build.subprocess, 'run') as run:
        with self.assertRaises(BuildConfigError):
          branding_build.prepareSourceAssets(resolved, root)
      run.assert_not_called()

  def test_unconfigured_products_do_not_run_preparation(self):
    with patch.object(branding_build.subprocess, 'run') as run:
      branding_build.prepareSourceAssets(SimpleNamespace(config={}), Path.cwd())
    run.assert_not_called()
