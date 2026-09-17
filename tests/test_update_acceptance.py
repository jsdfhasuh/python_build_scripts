import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_config import BuildConfigError
from build_records import fileHash, scanFiles
from path_boundary import ioPath
from portable_release import compressArchive, verifyArchive
from update_acceptance import REQUIRED_CHECKS, verifyAcceptance


class AcceptanceTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.protocol = {'protocol_version': 3, 'build_id': 'fixture',
                     'identity_sha256': 'a' * 64, 'files_sha256': 'b' * 64}
    self.evidence = self.root / 'evidence.txt'
    self.evidence.write_text('fixture evidence; no real acceptance claimed')
    self.report = {'schema_version': 1, 'protocol': self.protocol,
      'checks': {name: {'status': 'passed', 'evidence': [
        {'path': 'evidence.txt', 'sha256': fileHash(self.evidence)}]} for name in REQUIRED_CHECKS}}

  def writeReport(self):
    (self.root / 'update-acceptance.json').write_text(json.dumps(self.report))

  def test_missing_report_blocks_publication(self):
    with self.assertRaises(BuildConfigError):
      verifyAcceptance(self.root, self.protocol)

  def test_power_loss_not_run_cannot_be_replaced_by_process_tests(self):
    self.report['checks']['power_loss_recovery']['status'] = 'not-run'
    self.writeReport()
    with self.assertRaisesRegex(BuildConfigError, 'power_loss_recovery'):
      verifyAcceptance(self.root, self.protocol)

  def test_report_is_bound_to_build_and_evidence(self):
    self.writeReport()
    self.assertEqual(verifyAcceptance(self.root, self.protocol)['status'], 'passed')
    with self.assertRaises(BuildConfigError):
      verifyAcceptance(self.root, {**self.protocol, 'build_id': 'other'})
    self.evidence.write_text('changed')
    with self.assertRaisesRegex(BuildConfigError, 'evidence changed'):
      verifyAcceptance(self.root, self.protocol)

  def test_extended_path_fallback_archive_round_trip(self):
    app = self.root / 'VisionWorkshop'
    deep = app / 'app' / ('a' * 120) / ('b' * 120) / 'payload.dat'
    ioPath(deep.parent).mkdir(parents=True)
    self.assertEqual(app.parent.resolve(), self.root.resolve())
    self.addCleanup(shutil.rmtree, ioPath(app))
    ioPath(deep).write_bytes(b'long-path payload')
    files = scanFiles(app)
    output = self.root / 'package.zip'
    with patch('portable_release.shutil.which', return_value=None):
      self.assertEqual(compressArchive(app, output), 'zip/deflate')
    self.assertGreater(verifyArchive(output, 'VisionWorkshop', files).size, 0)
