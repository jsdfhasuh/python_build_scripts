import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import actions_release
import branding_build
import portable_release
import test_portable_release as fixtures
import update_protocol_build
from build_config import BuildConfigError
from update_protocol_build import ASSET_PREFIX


def writeDelta(output: Path, buildId: str, filesSha256: str) -> dict:
  # Wire fields from update_release.py at source efeaf5d49558ad8463c195260dabf21ee4feff24.
  name = f'{ASSET_PREFIX}-{buildId}-from-baseline-delta.zip'
  payload = b'fixture delta bytes'
  result = {
    'schema_version': 1, 'product_id': 'training_platform', 'platform': 'windows',
    'architecture': 'x86_64',
    'update_protocol_min': 2, 'update_protocol_max': 2,
    'from_build_id': 'baseline', 'to_build_id': buildId,
    'base_files_sha256': 'a' * 64, 'target_files_sha256': filesSha256,
    'zip_asset_name': name, 'zip_size': len(payload),
    'zip_sha256': hashlib.sha256(payload).hexdigest(),
  }
  (output / name).write_bytes(payload)
  (output / (name[:-4] + '_descriptor.json')).write_text(json.dumps(result), encoding='utf-8')
  return {**result, 'verified_target_sha256': filesSha256}


class DeltaValidationTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.output = Path(temporary.name)
    self.delta = writeDelta(self.output, 'target', 'b' * 64)

  def validate(self, result=None):
    return portable_release.validateDeltaAssets(
      self.delta if result is None else result, 'target', 'b' * 64, self.output,
    )

  def test_accepts_wire_name_and_existing_descriptor(self):
    self.assertNotIn('zip_name', self.delta)
    self.assertEqual(self.validate(), [self.delta['zip_asset_name'],
                                     self.delta['zip_asset_name'][:-4] + '_descriptor.json'])

  def test_missing_legacy_or_unsafe_name_is_actionable(self):
    for name in (None, '../outside.zip', 'C:\\outside.zip', 'other-delta.zip'):
      result = {**self.delta, 'zip_asset_name': name, 'zip_name': self.delta['zip_asset_name']}
      with self.subTest(name=name), self.assertRaisesRegex(BuildConfigError, 'zip_asset_name'):
        self.validate(result)
    result = dict(self.delta)
    del result['zip_asset_name']
    with self.assertRaisesRegex(BuildConfigError, 'zip_asset_name'):
      self.validate(result)

  def test_wrong_target_or_baseline_identity_fails(self):
    for field, value in (('verified_target_sha256', 'c' * 64),
                         ('target_files_sha256', 'c' * 64),
                         ('to_build_id', 'other'), ('from_build_id', 'target'),
                         ('from_build_id', '../outside')):
      with self.subTest(field=field), self.assertRaises(BuildConfigError):
        self.validate({**self.delta, field: value})

  def test_changed_zip_or_descriptor_is_rejected(self):
    archive = self.output / self.delta['zip_asset_name']
    original = archive.read_bytes()
    archive.write_bytes(b'x' * len(original))
    with self.assertRaisesRegex(BuildConfigError, 'size or SHA-256'):
      self.validate()
    archive.write_bytes(original)
    descriptor = self.output / (archive.stem + '_descriptor.json')
    data = json.loads(descriptor.read_text())
    data['base_files_sha256'] = 'c' * 64
    descriptor.write_text(json.dumps(data))
    with self.assertRaisesRegex(BuildConfigError, 'descriptor differs'):
      self.validate()
    descriptor.unlink()
    with self.assertRaisesRegex(BuildConfigError, 'output is missing'):
      self.validate()

  def test_invalid_json_and_zip_metadata_are_actionable(self):
    for field, value in (('zip_size', True), ('zip_size', 0), ('zip_sha256', 'invalid')):
      with self.subTest(field=field), self.assertRaisesRegex(BuildConfigError, 'size or SHA-256'):
        self.validate({**self.delta, field: value})
    descriptor = self.output / (self.delta['zip_asset_name'][:-4] + '_descriptor.json')
    descriptor.write_text('{broken')
    with self.assertRaisesRegex(BuildConfigError, 'valid UTF-8 JSON'):
      self.validate()

  def test_producer_non_object_or_bad_json_never_reaches_dictionary_access(self):
    (self.output / 'update_release.py').write_text('# fixture')
    context = Mock(workRoot=self.output, distRoot=self.output)
    resolved = Mock(programName='fixture')
    for payload in ('[]', 'null', '{broken'):
      with self.subTest(payload=payload), \
           patch.object(update_protocol_build.subprocess, 'run',
                        return_value=Mock(returncode=0, stdout=payload)), \
           self.assertRaisesRegex(BuildConfigError, 'Protocol producer delta'):
        update_protocol_build.runProducer(resolved, context, self.output, 'delta')


class DeltaReleaseIntegrationTests(unittest.TestCase):
  def setUp(self):
    self.fixture = fixtures.PortableTests()
    self.addCleanup(self.fixture.doCleanups)
    self.fixture.setUp()
    self.dropName = False

  def compile(self, *args, **kwargs):
    record = branding_build.executeBuild(*args, **kwargs)
    record['update_protocol'] = {'protocol_version': 2, 'files_sha256': record['files_sha256']}
    return record

  def produce(self, resolved, context, sourceRoot, action, *arguments):
    output = Path(arguments[arguments.index('--output') + 1])
    if action == 'export':
      for suffix in ('release_identity.json', 'package_files.json'):
        (output / (ASSET_PREFIX + '-' + suffix)).write_text('{}')
      return {}
    self.assertEqual(action, 'delta')
    record = json.loads(self.fixture.recordPath().read_text())
    result = writeDelta(output, context.buildId, record['files_sha256'])
    if self.dropName:
      del result['zip_asset_name']
    return result

  def runRelease(self):
    with patch.object(portable_release, 'protocolEnabled', return_value=True), \
         patch.object(portable_release, 'executeBuild', side_effect=self.compile), \
         patch.object(portable_release, 'runProducer', side_effect=self.produce):
      return self.fixture.runLocal('--build-only', '--delta-base-tag=v1.0.0')

  def test_real_wire_fields_flow_through_summary_and_public_staging(self):
    with patch.object(portable_release, 'publishAssets') as publish:
      summary = self.runRelease()
    publish.assert_not_called()
    output = next(self.fixture.packager.glob('release-output/**/build-summary.json')).parent
    staged = self.fixture.root / 'public'
    actions_release.stageAssets(output, staged, expectedCount=5)
    self.assertEqual(len(summary['protocol_asset_names']), 5)
    self.assertEqual({path.name for path in staged.iterdir()},
                     set(summary['protocol_asset_names']) | {'build-summary.json'})
    self.assertEqual(summary['delta_reconstruction_sha256'], summary['files_sha256'])

  def test_missing_wire_name_never_writes_success_summary_or_publishes(self):
    self.dropName = True
    with patch.object(portable_release, 'publishAssets') as publish:
      with self.assertRaisesRegex(BuildConfigError, 'zip_asset_name'):
        self.runRelease()
    publish.assert_not_called()
    self.assertFalse(list(self.fixture.packager.glob('release-output/**/build-summary.json')))
