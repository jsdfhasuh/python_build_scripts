import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_config import BuildConfigError
from build_records import gitState
from build_records import readJsonObject
from build_records import rejectLinks
from build_records import writeJsonNew
from test_portable_release import PortableTests
from test_portable_release import git
from test_portable_release import initializeGit


class RecordReviewTests(PortableTests):
  # Run only these added cases; inherited tests are covered by their original class.
  __unittest_skip__ = False

  def test_actual_submodule_state_preserves_leading_status_character(self) -> None:
    child = self.root / 'child'
    child.mkdir()
    (child / 'helper.py').write_text('x = 1\n')
    initializeGit(child)
    git(self.source, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(child), 'child')
    git(self.source, 'commit', '-am', 'submodule fixture')
    before = gitState(self.source)
    self.assertTrue(before['submodules_ready'])
    self.assertFalse(before['dirty'])
    (self.source / 'child/helper.py').write_text('x = 2\n')
    after = gitState(self.source)
    self.assertTrue(after['dirty'])
    self.assertNotEqual(before['working_files_sha256'], after['working_files_sha256'])

  def test_nested_private_build_record_is_not_archived(self) -> None:
    def compiler(command):
      result = self.compile(command)
      if '--onefile' not in command:
        dist = Path(command[command.index('--distpath') + 1])
        (dist / 'VisionWorkshop/_internal/build-record.json').write_text('{}')
      return result
    self.compiler.side_effect = compiler
    with self.assertRaisesRegex(BuildConfigError, 'Private build record'):
      self.runLocal()
    self.compressor.assert_not_called()

  def test_malformed_record_data_fails_with_actionable_error(self) -> None:
    self.runLocal()
    path = self.recordPath()
    record = readJsonObject(path)
    record['inputs'] = []
    path.write_text(json.dumps(record))
    with self.assertRaisesRegex(BuildConfigError, 'Malformed'):
      self.runLocal('--skip-build', '--build-record-path', str(path))

  def test_version_mismatch_is_detected_before_compilation(self) -> None:
    (self.source / 'version.py').write_text('__version__ = "1.0.0"\n')
    config = json.loads(self.config.read_text())
    config['source_version_file'] = str(self.source / 'version.py')
    self.config.write_text(json.dumps(config))
    with self.assertRaisesRegex(BuildConfigError, 'source version'):
      self.runLocal()
    self.compiler.assert_not_called()

  def test_arbitrary_output_beneath_packager_does_not_dirty_binary_provenance(self) -> None:
    result = self.runLocal('--output-directory', str(self.packager / 'custom-output'))
    self.assertFalse(result['published'])

  def test_unversioned_source_cannot_be_called_a_proven_build(self) -> None:
    source = self.root / 'not-versioned'
    source.mkdir()
    with self.assertRaisesRegex(BuildConfigError, 'repository root'):
      self.runLocal('--source-root', str(source))
    self.compiler.assert_not_called()

  def test_missing_executable_fails_even_after_success_exit_code(self) -> None:
    self.compiler.side_effect = None
    self.compiler.return_value = 0
    with self.assertRaises((OSError, BuildConfigError)):
      self.runLocal()
    self.assertFalse(list(self.packager.rglob('build-record.json')))

  def test_manifest_path_traversal_fails_before_compilation(self) -> None:
    with self.assertRaises(BuildConfigError):
      self.runLocal('--manifest-name', '../manifest.json')
    self.compiler.assert_not_called()

  def test_output_dotdot_cannot_bypass_source_boundary(self) -> None:
    alias = self.root / 'alias'
    alias.mkdir()
    output = alias / '..' / 'source' / 'new-output'
    with self.assertRaisesRegex(BuildConfigError, 'outside source'):
      self.runLocal('--output-directory', str(output))
    self.compiler.assert_not_called()
    self.assertFalse((self.source / 'new-output').exists())

  def test_output_dotdot_cannot_bypass_private_directory_boundary(self) -> None:
    alias = self.root / 'alias'
    alias.mkdir()
    output = alias / '..' / 'packager' / 'build' / 'leaked-output'
    with self.assertRaisesRegex(BuildConfigError, 'outside source'):
      self.runLocal('--output-directory', str(output))
    self.compiler.assert_not_called()

  def test_invalid_schema_does_not_become_valid_via_bool_integer_coercion(self) -> None:
    self.runLocal()
    path = self.recordPath()
    data = readJsonObject(path)
    data['schema_version'] = True
    path.write_text(json.dumps(data))
    with self.assertRaises(BuildConfigError):
      self.runLocal('--skip-build', '--build-record-path', str(path))


def load_tests(loader, tests, pattern):
  # Avoid counting inherited PortableTests again as new coverage.
  suite = unittest.TestSuite()
  for name in RecordReviewTests.__dict__:
    if name.startswith('test_'):
      suite.addTest(RecordReviewTests(name))
  suite.addTests(loader.loadTestsFromTestCase(LinkTests))
  return suite


class LinkTests(unittest.TestCase):
  def test_reparse_point_attribute_is_checked_even_without_path_is_junction(self) -> None:
    class FakeStat:
      st_file_attributes = 1024
    with patch.object(Path, 'lstat', return_value=FakeStat()):
      with self.assertRaises(BuildConfigError):
        rejectLinks(Path('/some/junction'))


if __name__ == '__main__':
  unittest.main()
