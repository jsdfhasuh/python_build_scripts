"""Source paths must be visible before PyInstaller executes spec collectors."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build


class BuildCollectPathsTests(unittest.TestCase):
  def test_declared_paths_reach_child_without_changing_parent_environment(self):
    with patch.dict(os.environ, {'PYTHONPATH': 'existing-source'}):
      command = [*build.PYINSTALLER_CMD, '--paths=first source', '-p',
                 os.pathsep.join(['second-source', 'third-source']), 'entry.py']
      with patch('build.subprocess.run') as run:
        run.return_value.returncode = 7
        self.assertEqual(build.run_command(command), 7)
      run.assert_called_once_with(command, env=run.call_args.kwargs['env'])
      self.assertEqual(run.call_args.kwargs['env']['PYTHONPATH'].split(os.pathsep),
                       [os.path.abspath(path) for path in
                        ['first source', 'second-source', 'third-source']] + ['existing-source'])
      self.assertEqual(os.environ['PYTHONPATH'], 'existing-source')

  def test_jobs_without_declared_paths_keep_inherited_environment(self):
    self.assertIsNone(build.getBuildEnvironment([*build.PYINSTALLER_CMD, 'entry.py']))

  @unittest.skipUnless(importlib.util.find_spec('PyInstaller'), 'PyInstaller is not installed')
  def test_external_plugin_dependency_is_collected_before_analysis(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      source = root / 'external source'
      plugin = source / 'fixture_plugins' / 'classification'
      plugin.mkdir(parents=True)
      (plugin.parent / '__init__.py').write_text('', encoding='utf-8')
      (plugin / '__init__.py').write_text('', encoding='utf-8')
      (plugin / 'backend.py').write_text(
        'def load():\n  from PIL import Image\n  return Image\n', encoding='utf-8')
      probe = (
        'import json\n'
        'from PyInstaller.utils.hooks import collect_submodules\n'
        'from PyInstaller.lib.modulegraph.modulegraph import ModuleGraph\n'
        'modules = collect_submodules("fixture_plugins")\n'
        'graph = ModuleGraph()\n'
        'for name in modules:\n  graph.import_hook(name)\n'
        'image = graph.find_node("PIL.Image")\n'
        'print(json.dumps({"modules": modules, "image": image.filename if image else None}))\n'
      )
      command = [sys.executable, '-c', probe]
      baseline = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
      self.assertEqual(baseline.returncode, 0, baseline.stderr)
      self.assertEqual(json.loads(baseline.stdout), {'modules': [], 'image': None})
      environment = build.getBuildEnvironment(
        [*build.PYINSTALLER_CMD, '--paths', str(source), 'entry.py'])
      fixed = subprocess.run(command, cwd=root, env=environment,
                             capture_output=True, text=True, timeout=60)
      self.assertEqual(fixed.returncode, 0, fixed.stderr)
      result = json.loads(fixed.stdout)
      self.assertIn('fixture_plugins.classification.backend', result['modules'])
      self.assertEqual(Path(result['image']).name, 'Image.py')


if __name__ == '__main__':
  unittest.main()
