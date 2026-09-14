import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from build_config import BuildConfigError
from update_protocol_publish import artifactRecords, publishProtocolAssets


class ProtocolPublishTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    names = ['fixture-full.zip', 'fixture-release_identity.json', 'fixture-package_files.json']
    for name in names:
      (self.root / name).write_bytes(name.encode())
    self.summary = {'protocol_asset_names': names,
                    'protocol_assets': artifactRecords([self.root / name for name in names])}
    self.args = SimpleNamespace(release_repo='', release_tag='v1.0.2')
    self.resolved = SimpleNamespace(config={'release_repo': 'jsdfhasuh/emo-vision-train-release'})
    self.content = SimpleNamespace(title='Fixture', body='Fixture notes')
    self.calls = []
    self.published = False
    self.corrupt = False

  def release(self, repo, tag):
    return {'id': 17, 'tag_name': tag, 'draft': not self.published, 'prerelease': False}

  def runCommand(self, args):
    self.calls.append(args)
    if args[:3] == ['gh', 'release', 'edit']:
      self.published = True
    if args[:2] == ['gh', 'api']:
      assets = [{'name': name, 'state': 'uploaded', **record}
                for name, record in self.summary['protocol_assets'].items()]
      if self.corrupt:
        assets[0]['digest'] = 'sha256:' + '0' * 64
      return json.dumps([assets])
    return ''

  def publish(self):
    publishProtocolAssets(self.args, self.resolved, self.summary, self.root,
                          self.root / 'notes.md', self.content, self.runCommand, self.release)

  def test_draft_verification_precedes_publication_and_rechecks(self):
    self.publish()
    self.assertIn('--draft', self.calls[0])
    self.assertEqual(self.calls[1][:2], ['gh', 'api'])
    self.assertEqual(self.calls[2][:3], ['gh', 'release', 'edit'])
    self.assertEqual(self.calls[3][:2], ['gh', 'api'])
    self.assertTrue(self.published)

  def test_digest_mismatch_retains_draft(self):
    self.corrupt = True
    with self.assertRaisesRegex(BuildConfigError, 'SHA-256'):
      self.publish()
    self.assertFalse(self.published)
    self.assertEqual(len(self.calls), 2)

  def test_mutated_local_assets_fail_before_remote_write(self):
    (self.root / 'fixture-full.zip').write_bytes(b'changed')
    with self.assertRaisesRegex(BuildConfigError, 'changed'):
      self.publish()
    self.assertEqual(self.calls, [])

  def test_different_repository_is_rejected(self):
    self.args.release_repo = 'someone/else'
    with self.assertRaises(BuildConfigError):
      self.publish()
    self.assertEqual(self.calls, [])
