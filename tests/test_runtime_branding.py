import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build
from branding_fixtures import makeIco
from branding_fixtures import writeProject
from build_config import BuildConfigError
from build_config import readJsonObject
from build_config import resolveBuildConfig
from build_records import fileHash
from build_records import inputSnapshot


class RuntimeBrandingTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.config, self.icon, self.profile = writeProject(self.root)
    self.branding = self.root / 'branding.json'
    self.writeBranding()
    profile = readJsonObject(self.profile)
    profile['runtime_branding_path'] = str(self.branding)
    profile['program_name'] = 'emo-vision-train'
    self.profile.write_text(json.dumps(profile), encoding='utf-8')

  def writeBranding(self, **overrides) -> None:
    data = {'display_name': 'VisionWorkshop', 'window_icon': self.icon.name}
    data.update(overrides)
    self.branding.write_text(json.dumps(data), encoding='utf-8')

  def resolve(self):
    return resolveBuildConfig(self.config, profilePath=str(self.profile), packagerRoot=self.root)

  def test_resources_are_main_only_and_identity_is_unchanged(self) -> None:
    before = self.config.read_bytes()
    resolved = self.resolve()
    main, updater = build.create_build_jobs(resolved.config)
    self.assertIn(f'{self.branding}:.', main.add_data)
    self.assertIn(f'{self.icon}:.', main.add_data)
    self.assertEqual(updater.add_data, [])
    self.assertEqual(resolved.programName, 'emo-vision-train')
    resolved.assertPublicationAllowed()
    self.assertEqual(resolved.summary()['runtime_branding']['display_name'], 'VisionWorkshop')
    self.assertEqual(self.config.read_bytes(), before)

  def test_nested_windows_icon_path_preserves_bundle_destination(self) -> None:
    icon = self.root / 'icons' / 'window.ico'
    icon.parent.mkdir()
    icon.write_bytes(self.icon.read_bytes())
    self.writeBranding(window_icon=r'icons\window.ico')
    self.assertIn(f'{icon}:icons', self.resolve().config['add_data'])

  def test_default_does_not_bundle_branding(self) -> None:
    resolved = resolveBuildConfig(self.config, packagerRoot=self.root)
    self.assertNotIn('runtime_branding', resolved.config)
    self.assertNotIn('add_data', resolved.config)

  def test_configuration_and_icon_content_affect_fingerprint(self) -> None:
    original = self.resolve().fingerprint
    self.writeBranding(display_name='Another display name')
    self.assertNotEqual(original, self.resolve().fingerprint)
    original = self.resolve().fingerprint
    self.icon.write_bytes(makeIco(png=True))
    self.assertNotEqual(original, self.resolve().fingerprint)

  def test_runtime_icon_is_hashed_independently_of_exe_icon(self) -> None:
    other = self.root / 'window.ico'
    other.write_bytes(self.icon.read_bytes())
    self.writeBranding(window_icon=other.name)
    original = self.resolve().fingerprint
    other.write_bytes(makeIco(png=True))
    resolved = self.resolve()
    self.assertNotEqual(original, resolved.fingerprint)
    with patch('build_records.gitState', return_value={}), \
         patch('build_records.gitCommit', return_value=None), \
         patch('build_records.toolVersions', return_value={}):
      inputs = inputSnapshot(resolved, self.root)['declared_inputs']
    self.assertEqual(inputs[str(self.branding)], fileHash(self.branding))
    self.assertEqual(inputs[str(other)], fileHash(other))

  def test_invalid_names_and_unknown_fields_fail(self) -> None:
    for name in ('', ' ', 'x' * 81, 'bad\nname', None, 42):
      with self.subTest(name=name), self.assertRaises(BuildConfigError):
        self.writeBranding(display_name=name)
        self.resolve()
    self.writeBranding(update_url='must not be applied')
    with self.assertRaisesRegex(BuildConfigError, 'only display_name'):
      self.resolve()

  def test_missing_config_bad_json_and_missing_icon_fail(self) -> None:
    self.branding.unlink()
    with self.assertRaises(BuildConfigError):
      self.resolve()
    self.branding.write_text('{bad json', encoding='utf-8')
    with self.assertRaises(BuildConfigError):
      self.resolve()
    self.writeBranding(window_icon='missing.ico')
    with self.assertRaisesRegex(BuildConfigError, 'existing .ico'):
      self.resolve()

  def test_unsafe_runtime_paths_fail(self) -> None:
    for name in ('../test-icon.ico', 'icons/../../test-icon.ico', '/test-icon.ico',
                 r'C:\test-icon.ico', 'C:test-icon.ico', r'\\server\icon.ico',
                 'https://example.invalid/icon.ico', 'test-icon.ico:stream', '', None):
      with self.subTest(name=name), self.assertRaises(BuildConfigError):
        self.writeBranding(window_icon=name)
        self.resolve()

  def test_existing_file_and_directory_mappings_cannot_override_branding(self) -> None:
    for mapping in (f'{self.branding}:.', f'{self.root}:.', f'{self.icon}:.'):
      config = readJsonObject(self.config)
      config['add_data'] = [mapping]
      self.config.write_text(json.dumps(config), encoding='utf-8')
      with self.subTest(mapping=mapping), self.assertRaisesRegex(BuildConfigError, 'conflicts'):
        self.resolve()


if __name__ == '__main__':
  unittest.main()
