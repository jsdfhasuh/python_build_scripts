import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from branding_fixtures import writeProject
from build_config import BuildConfigError
from build_config import createBuildContext
from build_config import resolveBuildConfig
from build_environment import preventSourceBytecode
from build_records import completeRecord
from build_records import inputSnapshot
from build_records import scanFiles
from test_portable_release import initializeGit
import portable_release


class InputDiagnosticTests(unittest.TestCase):
  def test_local_protocol_mandatory_is_rejected_before_build_or_network(self):
    with tempfile.TemporaryDirectory() as directory:
      args = portable_release.makeParser().parse_args([
        '--source-root', directory, '--release-tag', 'v1.0.0', '--mandatory', '--publish',
      ])
      with patch('portable_release.resolveBuildConfig',
                 return_value=SimpleNamespace(config={'update_protocol': 2})), \
           patch('portable_release.gitState') as state, \
           patch('portable_release.runChecked') as run, patch.dict(os.environ):
        with self.assertRaisesRegex(BuildConfigError, 'does not support --mandatory'):
          portable_release.resolveRequest(args)
      state.assert_not_called()
      run.assert_not_called()

  def test_changes_report_exact_files_without_weakening_the_guard(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      source, packager = root / 'source', root / 'packager'
      config, _, _ = writeProject(source)
      packager.mkdir()
      (packager / 'helper.py').write_text('VALUE = 1\n')
      resources = source / 'resources'
      resources.mkdir()
      (resources / 'removed.txt').write_text('removed')
      (resources / 'changed.txt').write_text('before')
      data = json.loads(config.read_text())
      data['add_data'] = [f'{resources}:resources']
      config.write_text(json.dumps(data))
      initializeGit(source)
      resolved = resolveBuildConfig(config, packagerRoot=packager)
      context = createBuildContext(resolved)
      context.prepare(resolved)
      beforeDetails = {}
      before = inputSnapshot(resolved, source, details=beforeDetails)
      (resources / 'added.txt').write_text('added')
      (resources / 'removed.txt').unlink()
      (resources / 'changed.txt').write_text('after')
      (source / 'main.py').write_text('print("changed")\n')
      (packager / 'helper.py').write_text('VALUE = 2\n')
      with self.assertRaisesRegex(BuildConfigError, 'Changed categories:') as error:
        completeRecord(resolved, context, source, before, beforeDetails)
      report = json.loads((context.workRoot / 'input-changes.json').read_text())
      changes = report['changes']
      self.assertIn(str((resources / 'added.txt').resolve()), changes['resource_files']['added'])
      self.assertIn(str((resources / 'removed.txt').resolve()), changes['resource_files']['removed'])
      self.assertIn(str((resources / 'removed.txt').resolve()), changes['source_files']['removed'])
      self.assertIn(str((resources / 'changed.txt').resolve()), changes['resource_files']['modified'])
      self.assertIn(str((source / 'main.py').resolve()), changes['source_files']['modified'])
      self.assertEqual(changes['packager_files']['modified'], ['helper.py'])
      self.assertIn('resources/changed.txt', str(error.exception))
      self.assertNotIn(before['declared_inputs'][str(resources.resolve())], str(error.exception))
      self.assertFalse((context.workRoot / 'build-record.json').exists())

  def test_tool_change_is_identified_and_rejected(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      config, _, _ = writeProject(root / 'source')
      packager = root / 'packager'
      packager.mkdir()
      resolved = resolveBuildConfig(config, packagerRoot=packager)
      context = createBuildContext(resolved)
      context.prepare(resolved)
      with patch('build_records.toolVersions', return_value={'packages_sha256': 'before'}):
        before = inputSnapshot(resolved, root / 'source')
      with patch('build_records.toolVersions', return_value={'packages_sha256': 'after'}):
        with self.assertRaisesRegex(BuildConfigError, 'Changed categories: tools'):
          completeRecord(resolved, context, root / 'source', before)


class BytecodeTests(unittest.TestCase):
  def test_real_import_reproduces_resource_drift_and_suppression_prevents_it(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      for name in ('control', 'protected'):
        folder = root / name
        folder.mkdir()
        (folder / 'probe.py').write_text('VALUE = 1\n')
      with patch.dict(os.environ):
        os.environ.pop('PYTHONDONTWRITEBYTECODE', None)
        os.environ.pop('PYTHONPYCACHEPREFIX', None)
        before = scanFiles(root / 'control')
        subprocess.run([sys.executable, '-c', 'import probe'], cwd=root / 'control', check=True)
        self.assertNotEqual(before, scanFiles(root / 'control'))
        before = scanFiles(root / 'protected')
        with preventSourceBytecode():
          subprocess.run([sys.executable, '-c', 'import probe'], cwd=root / 'protected', check=True)
        self.assertEqual(before, scanFiles(root / 'protected'))
        self.assertNotIn('PYTHONDONTWRITEBYTECODE', os.environ)

  def test_environment_and_interpreter_flag_are_restored_on_failure(self):
    previous = sys.dont_write_bytecode
    with patch.dict(os.environ, {'PYTHONDONTWRITEBYTECODE': '0'}):
      with self.assertRaisesRegex(RuntimeError, 'fixture'):
        with preventSourceBytecode():
          self.assertTrue(sys.dont_write_bytecode)
          self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '1')
          raise RuntimeError('fixture')
      self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '0')
      self.assertEqual(sys.dont_write_bytecode, previous)
