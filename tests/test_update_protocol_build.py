import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from build_config import BuildConfigError
from update_protocol_build import prepareProtocol


class ProtocolBuildVersionTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.resolved = SimpleNamespace(config={'updater': {'name': 'VisionWorkshopUpdater'}},
                                    programName='VisionWorkshop')
    self.context = SimpleNamespace(buildId='fixture')
    environment = patch.dict(os.environ, {'RELEASE_TAG': 'v1.0.23'})
    environment.start()
    self.addCleanup(environment.stop)
    producer = patch('update_protocol_build.runProducer', return_value={})
    self.producer = producer.start()
    self.addCleanup(producer.stop)

  def prepare(self, source, *, filename='app_version.py', encoding='utf-8'):
    (self.root / filename).write_text(source, encoding=encoding)
    return prepareProtocol(self.resolved, self.context, self.root, 'a' * 40)

  def assertVersion(self, value):
    args = self.producer.call_args.args
    self.assertEqual(args[args.index('--version') + 1], value)

  def test_application_version_is_used_without_importing_source(self):
    self.prepare('APP_VERSION = \'1.0.23\'\nraise RuntimeError(\'must not execute\')\n')
    self.assertVersion('1.0.23')

  def test_typed_assignment_and_utf8_bom_are_supported(self):
    self.prepare('APP_VERSION: str = \'1.0.23\'\n', encoding='utf-8-sig')
    self.assertVersion('1.0.23')

  def test_default_file_prefers_app_version_and_supports_legacy_fallback(self):
    for source in ('APP_VERSION = \'1.0.23\'\n__version__ = \'0.0.1\'\n',
                   '__version__ = \'1.0.23\'\n'):
      with self.subTest(source=source):
        self.prepare(source)
        self.assertVersion('1.0.23')

  def test_explicit_version_file_retains_legacy_precedence(self):
    self.resolved.config['source_version_file'] = 'version.py'
    self.prepare('APP_VERSION = \'0.0.1\'\n__version__ = \'1.0.23\'\n', filename='version.py')
    self.assertVersion('1.0.23')

  def test_comments_dynamic_values_and_nested_assignments_are_not_versions(self):
    for source in ('# __version__ = \'1.0.23\'\n',
                   'APP_VERSION = str(123)\n',
                   'def example():\n  APP_VERSION = \'1.0.23\'\n',
                   'APP_VERSION = \'1.0.23\'\nAPP_VERSION = calculate()\n'):
      with self.subTest(source=source), self.assertRaisesRegex(BuildConfigError, 'determine'):
        self.prepare(source)
    self.producer.assert_not_called()

  def test_tag_mismatch_still_rejected(self):
    with self.assertRaisesRegex(BuildConfigError, 'tag differs'):
      self.prepare('APP_VERSION = \'1.0.22\'\n')
    self.producer.assert_not_called()

  def test_missing_or_invalid_file_reports_its_path(self):
    with self.assertRaisesRegex(BuildConfigError, 'app_version.py'):
      prepareProtocol(self.resolved, self.context, self.root, 'a' * 40)
    with self.assertRaisesRegex(BuildConfigError, 'source version file'):
      self.prepare('APP_VERSION = (\n')
    self.producer.assert_not_called()
