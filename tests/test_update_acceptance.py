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
from update_acceptance import ACCEPTANCE_CHECKS, verifyAcceptance


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
        {'path': 'evidence.txt', 'sha256': fileHash(self.evidence)}]} for name in ACCEPTANCE_CHECKS}}

  def writeReport(self):
    (self.root / 'update-acceptance.json').write_text(json.dumps(self.report))

  def test_missing_report_is_not_run_and_does_not_block(self):
    result = verifyAcceptance(self.root, self.protocol)
    self.assertEqual(result['status'], 'not-run')
    self.assertEqual(set(result['checks'].values()), {'not-run'})

  def test_power_loss_not_run_cannot_be_replaced_by_process_tests(self):
    self.report['checks']['power_loss_recovery']['status'] = 'not-run'
    self.writeReport()
    result = verifyAcceptance(self.root, self.protocol)
    self.assertEqual(result['status'], 'not-verified')
    self.assertEqual(result['checks']['power_loss_recovery'], 'not-run')

  def test_failed_and_missing_checks_are_recorded_without_blocking(self):
    self.report['checks'] = {'power_loss_recovery': {'status': 'failed', 'evidence': []}}
    self.writeReport()
    result = verifyAcceptance(self.root, self.protocol)
    self.assertEqual(result['status'], 'failed')
    self.assertEqual(result['checks']['two_successive_updates'], 'not-run')

  def test_passed_check_still_requires_evidence(self):
    self.report['checks']['power_loss_recovery']['evidence'] = []
    self.writeReport()
    with self.assertRaisesRegex(BuildConfigError, 'requires evidence'):
      verifyAcceptance(self.root, self.protocol)

  def test_malformed_report_is_not_treated_as_missing(self):
    (self.root / 'update-acceptance.json').write_text('{broken')
    with self.assertRaisesRegex(BuildConfigError, 'Cannot read acceptance'):
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
