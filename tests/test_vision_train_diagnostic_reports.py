"""Check read-only bounded CI projections without running a native product."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import report_vision_train_core_diagnostic as reports


class DiagnosticReportTests(unittest.TestCase):
  def test_exception_and_access_mappings_are_preserved_in_full(self):
    exception = {'code': 0xc0000005, 'first_chance': False, 'pid': 42, 'tid': 43,
      'parameters': [8, 4096], 'instruction': {'active_module': None,
        'unloaded_candidates': [{'path': 'Qt.dll', 'base': 4096, 'size': 4096, 'offset': 23}]},
      'memory_access': {'kind': 'execute', 'address': 4096}, 'continuation': 'DBG_EXCEPTION_NOT_HANDLED'}
    source = {'status': 'FAIL', 'exit_code': 0xc0000005, 'forced_cleanup': False,
              'exceptions': [exception], 'events': [{'event': 6}], 'active_modules': [1], 'unloaded_modules': [2]}
    projection = reports.nativeProjection(source)
    self.assertEqual(projection['exceptions'], [exception])
    self.assertEqual(projection['exit_code'], 0xc0000005)
    self.assertFalse(projection['forced_cleanup'])
    self.assertEqual(projection['event_count'], 1)
    self.assertNotIn('events', projection)
    failure = {'index': 218, 'winerror': 206, 'path': '中文 路径',
               'attempted_cumulative_utf16_bytes_with_nul': 65536}
    projected = reports.dllProjection({'status': 'OBSERVED', 'observations': [
      {'mode': 'duplicate', 'observation': {'status': 'OBSERVED', 'first_failure': failure,
       'successful_directory_count': 218, 'handles_closed': 218, 'entries': [{}, {}]}}]})
    self.assertEqual(projected['observations'][0]['observation']['first_failure'], failure)
    self.assertEqual(projected['observations'][0]['source_entry_count'], 2)
    self.assertNotIn('entries', projected['observations'][0]['observation'])

  def test_real_json_bytes_and_chunk_reassembly_bind_both_hashes(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory).resolve()
      raw = json.dumps({'status': 'FAIL', 'error': '中文 ' + 'x' * 6000}, ensure_ascii=False).encode('utf-8')
      (root / 'report.json').write_bytes(raw)
      identity, value = reports.readReport(root, 'report.json')
      self.assertEqual(identity['bytes'], len(raw))
      self.assertEqual(identity['sha256'], hashlib.sha256(raw).hexdigest())
      text = reports.payloadText('fixture', identity, value, 'complete')
      lines = []
      reports.emitPayload('fixture', text, lines.append)
      chunks = [json.loads(line[len(reports.PREFIX):]) for line in lines]
      self.assertGreater(len(chunks), 1)
      self.assertTrue(all(chunk['chunks'] == len(chunks) for chunk in chunks))
      self.assertEqual([chunk['chunk'] for chunk in chunks], list(range(1, len(chunks) + 1)))
      reconstructed = ''.join(chunk['text'] for chunk in chunks)
      self.assertEqual(reconstructed, text)
      self.assertEqual(hashlib.sha256(text.encode('ascii')).hexdigest(), chunks[0]['projection_sha256'])
      self.assertEqual(json.loads(reconstructed)['projection'], value)

  def test_missing_malformed_outside_and_oversized_sources_are_not_passes(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory).resolve()
      identity, value = reports.readReport(root, 'missing.json')
      self.assertEqual(identity['status'], 'MISSING')
      self.assertIsNone(value)
      with self.assertRaises(ValueError):
        reports.readReport(root, '../neighbor.json')
      (root / 'bad.json').write_text('not JSON', encoding='utf-8')
      with self.assertRaises(json.JSONDecodeError):
        reports.readReport(root, 'bad.json')
      (root / 'large.json').write_text('{"value": "' + 'x' * 40 + '"}', encoding='utf-8')
      with self.assertRaisesRegex(ValueError, 'read budget'):
        reports.readReport(root, 'large.json', maximumBytes=16)

  def test_projection_size_limit_rejects_without_silently_dropping_exception_fields(self):
    value = {'exceptions': [{'code': 0xc0000005, 'error': 'x' * 1000}]}
    with patch.object(reports, 'MAX_PROJECTION_BYTES', 100):
      with self.assertRaisesRegex(ValueError, 'no fields or exception records'):
        reports.payloadText('large', {'status': 'READ'}, value, 'native')


if __name__ == '__main__':
  unittest.main()
