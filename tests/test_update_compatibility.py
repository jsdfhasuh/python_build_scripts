import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import branding_build
import legacy_launcher
from branding_fixtures import writeProject
from build_config import BuildConfigError
from build_config import createBuildContext
from build_config import readJsonObject
from build_config import resolveBuildConfig
from build_records import validateApplication

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.config, self.icon, self.profile = writeProject(self.root)
    shutil.copy2(ROOT / 'legacy_launcher.py', self.root / 'legacy_launcher.py')
    self.modify(updater_program_name='VisionWorkshopUpdater',
                legacy_program_names=['emo-vision-train', 'training_platform'])

  def modify(self, **values) -> None:
    data = readJsonObject(self.profile)
    data.update(values)
    self.profile.write_text(json.dumps(data), encoding='utf-8')

  def resolve(self, **kwargs):
    return resolveBuildConfig(self.config, profilePath=str(self.profile),
                              packagerRoot=self.root, **kwargs)

  def test_alias_contract_retains_both_old_names_and_allows_publication_preflight(self) -> None:
    resolved = self.resolve()
    resolved.assertPublicationAllowed()
    self.assertEqual(resolved.updateCompatibility, 'legacy-launcher-contract')
    self.assertEqual(resolved.config['updater']['name'], 'VisionWorkshopUpdater')
    self.assertEqual(resolved.legacyProgramNames, ['emo-vision-train', 'training_platform'])

  def test_alias_schema_and_collisions_are_rejected(self) -> None:
    for names in (True, [], ['another'], ['emo-vision-train', 'updater'],
                  ['emo-vision-train', 'VisionWorkshop'],
                  ['emo-vision-train', 'VisionWorkshopUpdater'],
                  ['emo-vision-train', 'EMO-VISION-TRAIN'], ['../escape']):
      with self.subTest(names=names), self.assertRaises(BuildConfigError):
        self.modify(legacy_program_names=names)
        self.resolve()

  def test_unrelated_custom_names_cannot_use_the_fixed_launcher(self) -> None:
    with self.assertRaisesRegex(BuildConfigError, 'only VisionWorkshop'):
      self.resolve(programName='Another Product')

  def test_missing_launcher_source_fails_preflight(self) -> None:
    (self.root / 'legacy_launcher.py').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'source is missing'):
      self.resolve()

  def test_real_profile_brands_the_updater_and_bundles_its_runtime_resources(self) -> None:
    resolved = resolveBuildConfig(ROOT / 'configs/emo-vision-train.json',
                                 profilePath=str(ROOT / 'profiles/visionworkshop.json'))
    self.assertEqual(resolved.programName, 'VisionWorkshop')
    updater = resolved.config['updater']
    self.assertEqual(updater['name'], 'VisionWorkshopUpdater')
    self.assertEqual(updater['icon'], resolved.config['icon'])
    self.assertTrue(any('branding.json' in item for item in updater['add_data']))
    resolved.assertPublicationAllowed()

  def test_command_preview_includes_one_isolated_launcher_compile(self) -> None:
    resolved = self.resolve()
    context = createBuildContext(resolved)
    with patch('build._find_python_dll', return_value=None), \
         patch('build._collect_python_runtime_dlls', return_value=[]):
      commands = branding_build.buildCommands(resolved, context)
    self.assertEqual([job.label for job, _ in commands], ['main', 'updater', 'legacy-launcher'])
    job, command = commands[-1]
    self.assertEqual(job.name, 'emo-vision-train')
    self.assertIn('--onefile', command)
    self.assertIn('--noconsole', command)
    self.assertIn(str(context.workPath('legacy-launcher')), command)
    self.assertFalse(context.workRoot.exists())

  def test_copies_and_validation_require_all_compatibility_entrypoints(self) -> None:
    resolved = self.resolve()
    context = createBuildContext(resolved)
    app = context.distRoot / resolved.programName
    app.mkdir(parents=True)
    (app / 'VisionWorkshop.exe').write_bytes(b'new primary')
    (app / 'updater.exe').write_bytes(b'new updater')
    (context.distRoot / 'VisionWorkshopUpdater.exe').write_bytes(b'new updater')
    (context.distRoot / 'emo-vision-train.exe').write_bytes(b'launcher')
    branding_build.copyCompatibilityEntrypoints(resolved, context)
    validateApplication(resolved, app)
    (app / 'training_platform.exe').write_bytes(b'tampered launcher')
    with self.assertRaisesRegex(BuildConfigError, 'identical bytes'):
      validateApplication(resolved, app)
    (app / 'training_platform.exe').unlink()
    with self.assertRaisesRegex(BuildConfigError, 'missing or empty'):
      validateApplication(resolved, app)

  def test_launcher_uses_a_sibling_exe_and_forwards_arguments_without_a_shell(self) -> None:
    target = self.root / 'VisionWorkshop.exe'
    target.write_bytes(b'new primary')
    with patch('legacy_launcher.subprocess.Popen') as launch:
      legacy_launcher.launchMain(self.root, ['--file', 'project with spaces.json'])
    launch.assert_called_once_with(
      [str(target), '--file', 'project with spaces.json'], cwd=str(self.root), close_fds=True,
    )

  def test_missing_primary_does_not_start_another_process(self) -> None:
    with patch('legacy_launcher.subprocess.Popen') as launch:
      with self.assertRaises(FileNotFoundError):
        legacy_launcher.launchMain(self.root, [])
    launch.assert_not_called()


if __name__ == '__main__':
  unittest.main()
