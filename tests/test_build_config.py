import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branding_fixtures import makeIco
from branding_fixtures import writeProject
from build_config import BuildConfigError
from build_config import createBuildContext
from build_config import readJsonObject
from build_config import resolveBuildConfig
from build_config import validateExtraArgs
from build_config import validateIcon
from build_config import validateProgramName


class ConfigTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.config, self.icon, self.profile = writeProject(self.root)

  def resolve(self, **kwargs):
    return resolveBuildConfig(self.config, packagerRoot=self.root, **kwargs)

  def modify(self, path: Path, **values) -> None:
    data = readJsonObject(path)
    data.update(values)
    path.write_text(json.dumps(data), encoding='utf-8')

  def test_profile_applies_name_icon_and_asset_template(self) -> None:
    result = self.resolve(profilePath=str(self.profile))
    self.assertEqual(result.programName, 'VisionWorkshop')
    self.assertEqual(result.config['icon'], str(self.icon))
    self.assertEqual(result.assetName('v1.2.3'), 'VisionWorkshop-windows-v1.2.3.zip')
    self.assertEqual(result.iconSha256, hashlib.sha256(self.icon.read_bytes()).hexdigest())
    self.assertNotIn('installer', result.config)

  def test_cli_values_override_profile(self) -> None:
    other = self.root / 'other.ico'
    other.write_bytes(makeIco(png=True))
    result = self.resolve(profilePath=str(self.profile), programName='视觉工坊 Test',
                          iconPath=str(other), releaseAssetName='${PROGRAM_NAME}-${RELEASE_TAG}.zip')
    self.assertEqual(result.programName, '视觉工坊 Test')
    self.assertEqual(result.config['icon'], str(other))
    self.assertEqual(result.assetName('v2'), '视觉工坊 Test-v2.zip')

  def test_original_files_are_not_modified(self) -> None:
    before = (self.config.read_bytes(), self.profile.read_bytes())
    self.resolve(profilePath=str(self.profile))
    self.assertEqual(before, (self.config.read_bytes(), self.profile.read_bytes()))

  def test_name_only_and_icon_only_are_independent(self) -> None:
    renamed = self.resolve(programName='VisionWorkshop')
    self.assertIsNone(renamed.config['icon'])
    iconOnly = self.resolve(iconPath=str(self.icon))
    self.assertEqual(iconOnly.programName, 'emo-vision-train')

  def test_names_are_literal_not_environment_expansions(self) -> None:
    with patch.dict(os.environ, {'HOME': 'unexpected', 'VERSION': 'unexpected'}):
      name = '$HOME-%VERSION%-视觉工坊'
      result = self.resolve(programName=name, releaseAssetName='${PROGRAM_NAME}-${RELEASE_TAG}.zip')
      self.assertEqual(result.programName, name)
      self.assertEqual(result.assetName('v2'), f'{name}-v2.zip')

  def test_no_profile_is_implicitly_selected(self) -> None:
    self.assertEqual(self.resolve().programName, 'emo-vision-train')
    self.assertIsNone(self.resolve().config['icon'])

  def test_missing_profile_fails(self) -> None:
    with self.assertRaisesRegex(BuildConfigError, 'Cannot read'):
      self.resolve(profilePath='missing.json')

  def test_profile_target_mismatch_fails(self) -> None:
    self.modify(self.profile, target='emo-master')
    with self.assertRaisesRegex(BuildConfigError, 'target'):
      self.resolve(profilePath=str(self.profile))

  def test_profile_unknown_fields_fail(self) -> None:
    for field in ('source_repo', 'entry', 'release_repo', 'extra_args', 'installer'):
      with self.subTest(field=field):
        config, icon, profile = writeProject(self.root)
        self.modify(profile, **{field: 'must not apply'})
        with self.assertRaisesRegex(BuildConfigError, 'Unsupported'):
          self.resolve(profilePath=str(profile))

  def test_profile_schema_version_is_strict(self) -> None:
    for value in (True, '1', 0, 2, None):
      with self.subTest(value=value):
        self.modify(self.profile, schema_version=value)
        with self.assertRaisesRegex(BuildConfigError, 'schema_version'):
          self.resolve(profilePath=str(self.profile))

  def test_duplicate_json_fields_fail(self) -> None:
    self.profile.write_text('{"target":"a","target":"b"}', encoding='utf-8')
    with self.assertRaisesRegex(BuildConfigError, 'Duplicate'):
      self.resolve(profilePath=str(self.profile))

  def test_json_array_and_malformed_json_fail(self) -> None:
    for text in ('[]', '{broken'):
      with self.subTest(text=text):
        self.profile.write_text(text, encoding='utf-8')
        with self.assertRaises(BuildConfigError):
          self.resolve(profilePath=str(self.profile))

  def test_profile_relative_icon_is_packager_relative(self) -> None:
    nested = self.root / 'elsewhere'
    nested.mkdir()
    profile = nested / 'profile.json'
    profile.write_text(self.profile.read_text(), encoding='utf-8')
    self.modify(profile, icon_path=self.icon.name)
    self.assertEqual(self.resolve(profilePath=str(profile)).config['icon'], str(self.icon))

  def test_explicit_path_macros(self) -> None:
    with patch.dict(os.environ, {'SOURCE_ROOT': str(self.root)}):
      for macro in ('PACKAGER_ROOT', 'SOURCE_ROOT'):
        with self.subTest(macro=macro):
          result = self.resolve(iconPath=f'${{{macro}}}/{self.icon.name}')
          self.assertEqual(result.config['icon'], str(self.icon))

  def test_undefined_path_macros_fail(self) -> None:
    for text in ('${UNDEFINED}/icon.ico', '${SOURCE_ROOT}/icon.ico', '${BROKEN/icon.ico'):
      with self.subTest(text=text), patch.dict(os.environ, {}, clear=True):
        with self.assertRaises(BuildConfigError):
          self.resolve(iconPath=text)

  def test_profile_missing_icon_can_be_overridden(self) -> None:
    self.modify(self.profile, icon_path='missing.ico')
    with self.assertRaisesRegex(BuildConfigError, 'existing'):
      self.resolve(profilePath=str(self.profile))
    result = self.resolve(profilePath=str(self.profile), iconPath=str(self.icon))
    self.assertEqual(result.config['icon'], str(self.icon))

  def test_asset_tag_not_required_for_exe_preview(self) -> None:
    with patch.dict(os.environ, {}, clear=True):
      result = self.resolve(profilePath=str(self.profile))
      self.assertIn('${RELEASE_TAG}', result.assetTemplate)

  def test_only_supported_target_allows_branding(self) -> None:
    master = self.root / 'emo-master.json'
    master.write_text(self.config.read_text(), encoding='utf-8')
    with self.assertRaisesRegex(BuildConfigError, 'only'):
      resolveBuildConfig(master, programName='VisionWorkshop')

  def test_main_onefile_and_installer_combinations_fail(self) -> None:
    self.modify(self.config, onefile=True)
    with self.assertRaisesRegex(BuildConfigError, 'onedir'):
      self.resolve(programName='VisionWorkshop')
    self.modify(self.config, onefile=False, installer={'enabled': True})
    with self.assertRaisesRegex(BuildConfigError, 'Installer'):
      self.resolve(programName='VisionWorkshop')

  def test_main_and_updater_spec_files_fail(self) -> None:
    self.modify(self.config, entry='custom.spec')
    with self.assertRaisesRegex(BuildConfigError, 'spec'):
      self.resolve(programName='VisionWorkshop')
    self.modify(self.config, entry=str(self.root / 'main.py'),
                updater={'enabled': True, 'entry': 'updater.spec'})
    with self.assertRaisesRegex(BuildConfigError, 'spec'):
      self.resolve(programName='VisionWorkshop')

  def test_updater_name_and_copy_target_collisions_fail(self) -> None:
    self.modify(self.config, updater={'enabled': True, 'name': 'update-helper', 'onefile': True})
    for name in ('UPDATE-HELPER', 'Updater', 'updater'):
      with self.subTest(name=name):
        with self.assertRaisesRegex(BuildConfigError, 'collides'):
          self.resolve(programName=name)

  def test_updater_must_remain_onefile(self) -> None:
    self.modify(self.config, updater={'enabled': True, 'onefile': False})
    with self.assertRaisesRegex(BuildConfigError, 'onefile updater'):
      self.resolve(programName='VisionWorkshop')

  def test_managed_extra_options_and_abbreviations_fail(self) -> None:
    values = ('--name', '--name=Other', '-nOther', '-n', '-iother.ico', '--icon=x',
              '--distpath=x', '--workpath', '--specpath=x', '--onefile', '-F',
              '--onedir', '-D', '--na', '--ico=x', '--dist=x', '-ynOther', '--')
    for option in values:
      with self.subTest(option=option):
        with self.assertRaises(BuildConfigError):
          validateExtraArgs({'extra_args': [option]}, 'main')

  def test_unrelated_extra_options_are_unchanged(self) -> None:
    arguments = ['--runtime-hook', 'hook.py', '--collect-all', 'torch', '--noupx',
                 '--copy-metadata', 'torch', '--paths=src', '-p', 'src']
    config = {'extra_args': arguments}
    validateExtraArgs(config, 'main')
    self.assertEqual(config['extra_args'], arguments)

  def test_bad_extra_args_type_fails(self) -> None:
    for args in ('--name=x', [4]):
      with self.subTest(args=args):
        with self.assertRaises(BuildConfigError):
          validateExtraArgs({'extra_args': args}, 'main')

  def test_asset_path_traversal_and_non_zip_fail(self) -> None:
    for template in ('../x.zip', '/x.zip', 'C:\\x.zip', 'folder/x.zip', 'x.exe',
                     'x-${BAD}.zip', '${BROKEN.zip'):
      with self.subTest(template=template):
        with self.assertRaises(BuildConfigError):
          self.resolve(releaseAssetName=template)

  def test_asset_and_manifest_collision_fails(self) -> None:
    result = self.resolve(releaseAssetName='VisionWorkshop.zip')
    with self.assertRaisesRegex(BuildConfigError, 'collide'):
      result.assetName('v1', 'visionworkshop.ZIP')
    with self.assertRaises(BuildConfigError):
      result.assetName('v1', '../manifest.json')

  def test_unsafe_tag_in_asset_fails(self) -> None:
    result = self.resolve(profilePath=str(self.profile))
    with self.assertRaises(BuildConfigError):
      result.assetName('../v1')

  def test_renamed_updater_publication_check_fails(self) -> None:
    result = self.resolve(programName='VisionWorkshop')
    with self.assertRaisesRegex(BuildConfigError, 'unverified'):
      result.assertPublicationAllowed()
    self.assertFalse(result.summary()['runtime_updates_disabled'])

  def test_icon_only_does_not_trigger_rename_check(self) -> None:
    result = self.resolve(iconPath=str(self.icon))
    result.assertPublicationAllowed()
    self.assertFalse(result.renamed)

  def test_fingerprint_changes_with_icon_bytes_same_path(self) -> None:
    original = self.resolve(iconPath=str(self.icon)).fingerprint
    self.icon.write_bytes(makeIco(png=True))
    self.assertNotEqual(original, self.resolve(iconPath=str(self.icon)).fingerprint)

  def test_fingerprint_does_not_include_build_id(self) -> None:
    result = self.resolve(programName='VisionWorkshop')
    first = createBuildContext(result)
    second = createBuildContext(result)
    self.assertNotEqual(first.distRoot, second.distRoot)
    self.assertEqual(result.fingerprint, self.resolve(programName='VisionWorkshop').fingerprint)
    self.assertFalse(first.distRoot.exists())
    self.assertFalse(first.workRoot.exists())

  def test_context_paths_stay_separate_for_main_and_updater(self) -> None:
    context = createBuildContext(self.resolve(programName='VisionWorkshop'))
    self.assertNotEqual(context.specPath('main'), context.specPath('updater'))
    self.assertNotEqual(context.workPath('main'), context.workPath('updater'))
    self.assertTrue(context.distRoot.is_relative_to(self.root))

  def test_context_refuses_existing_work_directory(self) -> None:
    result = self.resolve(programName='VisionWorkshop')
    context = createBuildContext(result)
    context.prepare(result)
    with self.assertRaises(FileExistsError):
      context.prepare(result)
    self.assertEqual(readJsonObject(context.workRoot / 'effective-config.json')['name'],
                     'VisionWorkshop')


class NameTests(unittest.TestCase):
  def test_valid_names(self) -> None:
    for name in ('VisionWorkshop', '视觉工坊', 'Vision Workshop', 'vision.v2', '$name-%VERSION%'):
      with self.subTest(name=name):
        self.assertEqual(validateProgramName(name), name)

  def test_invalid_names(self) -> None:
    for name in ('', ' ', 'CON', 'con.data', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT9',
                 'COM¹', 'LPT²', 'name.exe', 'Name.EXE', 'name.', 'name ', ' name',
                 'name\n', 'a/b', 'a\\b', 'C:name', 'a?b', 'a*b', 'a<b', 'a>b',
                 'a|b', 'a"b', 'a\0b', '-name', '.', '..', 'a' * 252):
      with self.subTest(name=name):
        with self.assertRaises(BuildConfigError):
          validateProgramName(name)

  def test_utf16_length_is_checked(self) -> None:
    validateProgramName('a' * 251)
    with self.assertRaises(BuildConfigError):
      validateProgramName('😀' * 126)


class IconTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.icon = Path(temp.name) / 'test.ico'

  def test_dib_icon_decodes(self) -> None:
    data = makeIco()
    self.icon.write_bytes(data)
    self.assertEqual(validateIcon(self.icon), hashlib.sha256(data).hexdigest())

  def test_png_icon_decodes(self) -> None:
    data = makeIco(256, png=True)
    self.icon.write_bytes(data)
    self.assertEqual(validateIcon(self.icon), hashlib.sha256(data).hexdigest())

  def test_multiple_dib_and_png_entries_decode(self) -> None:
    first, second = makeIco(), makeIco(32, png=True)
    data = struct.pack('<HHH', 0, 1, 2)
    data += first[6:18] + struct.pack('<I', 38)
    data += second[6:18] + struct.pack('<I', 38 + len(first) - 22)
    data += first[22:] + second[22:]
    self.icon.write_bytes(data)
    self.assertEqual(validateIcon(self.icon), hashlib.sha256(data).hexdigest())

  def test_second_duplicate_size_entry_is_also_decoded(self) -> None:
    first, second = makeIco(), bytearray(makeIco(png=True))
    second[22 + 41:22 + 45] = b'FAIL'
    data = struct.pack('<HHH', 0, 1, 2)
    data += first[6:18] + struct.pack('<I', 38)
    data += second[6:18] + struct.pack('<I', 38 + len(first) - 22)
    data += first[22:] + second[22:]
    self.icon.write_bytes(data)
    with self.assertRaises(BuildConfigError):
      validateIcon(self.icon)

  def test_missing_and_directory_fail(self) -> None:
    with self.assertRaises(BuildConfigError):
      validateIcon(self.icon)
    self.icon.mkdir()
    with self.assertRaises(BuildConfigError):
      validateIcon(self.icon)

  def test_fake_extension_and_truncation_fail(self) -> None:
    for data in (b'not an icon' * 10, makeIco()[:30], b''):
      with self.subTest(length=len(data)):
        self.icon.write_bytes(data)
        with self.assertRaises(BuildConfigError):
          validateIcon(self.icon)

  def test_invalid_image_offsets_fail(self) -> None:
    data = bytearray(makeIco())
    struct.pack_into('<I', data, 18, 4)
    self.icon.write_bytes(data)
    with self.assertRaisesRegex(BuildConfigError, 'bounds'):
      validateIcon(self.icon)

  def test_wrong_dimensions_fail_before_decode(self) -> None:
    data = bytearray(makeIco(png=True))
    struct.pack_into('>I', data, 22 + 16, 500000)
    self.icon.write_bytes(data)
    with self.assertRaisesRegex(BuildConfigError, 'dimensions'):
      validateIcon(self.icon)

  def test_corrupt_payload_with_valid_directory_fails(self) -> None:
    data = bytearray(makeIco(png=True))
    data[22 + 41:22 + 45] = b'FAIL'
    self.icon.write_bytes(data)
    with self.assertRaises(BuildConfigError):
      validateIcon(self.icon)

  def test_missing_decoder_gives_actionable_error(self) -> None:
    self.icon.write_bytes(makeIco())
    with patch.dict('sys.modules', {'PIL': None}):
      with self.assertRaisesRegex(BuildConfigError, 'Pillow'):
        validateIcon(self.icon)


if __name__ == '__main__':
  unittest.main()
