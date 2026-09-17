import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branding_fixtures import writeProject
from branding_build import buildCommands
from build_config import BuildConfigError, createBuildContext, resolveBuildConfig
from build_records import validateApplication
from path_boundary import ioPath


class ProtocolLayoutTests(unittest.TestCase):
  def setUp(self):
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.config, self.icon, self.profile = writeProject(self.root)
    data = json.loads(self.config.read_text())
    data.update(name='VisionWorkshop', update_protocol=3, layout_version=1, launcher_min_capability=1)
    data['updater']['name'] = 'VisionWorkshopUpdater'
    self.config.write_text(json.dumps(data))
    (self.root / 'launcher.py').write_text('pass')

  def resolve(self):
    return resolveBuildConfig(self.config, packagerRoot=self.root)

  def test_protocol_three_compiles_three_entries_without_aliases(self):
    resolved = self.resolve()
    resolved.assertPublicationAllowed()
    with patch('build._find_python_dll', return_value=None), \
         patch('build._collect_python_runtime_dlls', return_value=[]):
      context = createBuildContext(resolved)
      commands = buildCommands(resolved, context)
    self.assertEqual([job.name for job, _ in commands],
                     ['VisionWorkshop', 'VisionWorkshopApp', 'VisionWorkshopUpdater'])
    self.assertIn('--onefile', commands[0][1])
    self.assertIn('--onefile', commands[2][1])
    self.assertNotIn('--runtime-hook', commands[0][1])
    for job, command in commands:
      for option, path in (('--distpath', context.distRoot),
                           ('--workpath', context.workPath(job.label)),
                           ('--specpath', context.specPath(job.label))):
        self.assertEqual(command[command.index(option) + 1], str(ioPath(path)))

  def test_layout_requires_only_root_launcher_and_application_contents(self):
    resolved = self.resolve()
    app = self.root / 'output'
    for name in ('VisionWorkshop.exe', 'app/VisionWorkshopApp.exe', 'app/VisionWorkshopUpdater.exe',
                 'app/release_identity.json', 'app/package_files.json'):
      path = app / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(b'fixture')
    validateApplication(resolved, app)
    (app / 'updater.exe').write_bytes(b'obsolete')
    with self.assertRaises(BuildConfigError):
      validateApplication(resolved, app)

  def test_alias_settings_and_protocol_two_are_rejected(self):
    data = json.loads(self.config.read_text())
    data['legacy_program_names'] = ['training_platform']
    self.config.write_text(json.dumps(data))
    with self.assertRaises(BuildConfigError):
      self.resolve()
    data.pop('legacy_program_names')
    data['update_protocol'] = 2
    self.config.write_text(json.dumps(data))
    with self.assertRaises(BuildConfigError):
      self.resolve().assertPublicationAllowed()
