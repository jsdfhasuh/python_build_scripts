"""Read-only candidate summaries must retain identities, exits and failures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import report_vision_train_modular_candidate as reports


class CandidateReportTests(unittest.TestCase):
  def roots(self, directory):
    root = Path(directory).resolve()
    build, product = root / 'build', root / 'product'
    build.mkdir()
    product.mkdir()
    return build, product

  def write(self, root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
    path.write_bytes(raw)
    return raw

  def payloads(self, lines):
    groups = {}
    for line in lines:
      if line.startswith(reports.common.PREFIX):
        value = json.loads(line[len(reports.common.PREFIX):])
        groups.setdefault(value['label'], []).append(value)
    result = {}
    for label, pieces in groups.items():
      pieces.sort(key=lambda value: value['chunk'])
      self.assertEqual([p['chunk'] for p in pieces], list(range(1, len(pieces) + 1)))
      self.assertTrue(all(p['chunks'] == len(pieces) for p in pieces))
      text = ''.join(p['text'] for p in pieces)
      digest = hashlib.sha256(text.encode('ascii')).hexdigest()
      self.assertTrue(all(p['projection_sha256'] == digest and p['projection_bytes'] == len(text)
                          for p in pieces))
      result[label] = json.loads(text)
    return result

  def test_latest_core_and_original_module_build_and_archive_identities_remain_distinct(self):
    old = {'app_sha': 'a' * 40, 'packager_sha': 'b' * 40, 'build_id': 'source'}
    new = {'app_sha': 'c' * 40, 'packager_sha': 'd' * 40, 'build_id': 'candidate'}
    source = {'status': 'BUILT', 'published': False,
      'core': {'build': new, 'python': {'abi': 'cp312'}, 'runtime_files': ['large inventory']},
      'core_archive': {'bytes': 123, 'sha256': 'e' * 64, 'path': 'Core.zip'},
      'module_archives': [{'module_id': 'runtime.ort', 'bytes': 456, 'sha256': 'f' * 64,
                           'manifest_sha256': '1' * 64, 'reuse_from': {'source_build': old}}],
      'module_index': {'sha256': '2' * 64, 'bytes': 789}, 'module_builds': {'runtime.ort': old},
      'module_reuse': {'enabled': True, 'files': [{'module_id': 'runtime.ort',
        'source_build': old, 'target_core_build': new, 'source_product_acceptance': 'FAIL',
        'manifest_bytes_unchanged': True, 'staging_selection': {'raw_receipts': 'large'}}]}}
    before = deepcopy(source)
    projected = reports.buildProjection(source)
    self.assertEqual(source, before)
    self.assertEqual(projected['core']['build'], new)
    self.assertEqual(projected['module_builds']['runtime.ort'], old)
    self.assertEqual(projected['module_archives'], source['module_archives'])
    self.assertEqual(projected['module_index'], source['module_index'])
    self.assertEqual(projected['module_reuse']['files'][0]['source_product_acceptance'], 'FAIL')
    self.assertNotIn('runtime_files', projected['core'])

  def test_actual_process_failure_is_not_hidden_by_internal_case_pass_and_sources_are_unchanged(self):
    with tempfile.TemporaryDirectory() as directory:
      build, product = self.roots(directory)
      detail = {'case': 'core', 'status': 'PASS', 'pid': 42,
                'runtime_identity': {'generation': 0}, 'result': {'gui': '中文已绘制'}}
      process = {'status': 'FAIL', 'pid': 42, 'exit_code': 0xc0000005,
                 'command': ['VisionWorkshop.exe', '--modular-runtime-check'],
                 'forced_cleanup': False}
      summary = {'status': 'FAIL', 'published': False, 'error': 'core native exit 3221225477',
                 'traceback': 'complete traceback\nfailure', 'cases': []}
      raws = {}
      for name, value in [('core-without-modules.json', detail),
                           ('core-without-modules.process.json', process),
                           ('modular-product-summary.json', summary)]:
        raws[name] = self.write(product, name, value)
      lines = []
      self.assertEqual(reports.collectReports(build, product, lines.append), 0)
      payloads = self.payloads(lines)
      self.assertEqual(payloads['candidate-product']['projection']['status'], 'FAIL')
      self.assertEqual(payloads['candidate-product']['projection']['traceback'], summary['traceback'])
      observed = payloads['candidate-process:core-without-modules']
      self.assertEqual(observed['projection'], process)
      self.assertEqual(payloads['candidate-case:core-without-modules']['projection']['status'], 'PASS')
      self.assertEqual(observed['source']['sha256'],
                       hashlib.sha256(raws['core-without-modules.process.json']).hexdigest())
      self.assertEqual(payloads['candidate-build']['source']['status'], 'MISSING')
      self.assertIsNone(payloads['candidate-build']['projection'])
      for name, raw in raws.items():
        self.assertEqual((product / name).read_bytes(), raw)

  def test_failed_process_without_case_json_keeps_complete_unicode_stderr_and_empty_stdout(self):
    with tempfile.TemporaryDirectory() as directory:
      build, product = self.roots(directory)
      self.write(product, 'core-without-modules.process.json',
                 {'status': 'FAIL', 'pid': 77, 'exit_code': 1})
      error = 'Traceback:\nModuleNotFoundError: 缺失模块 中文路径\n'
      raw = error.encode('utf-8')
      (product / 'core-without-modules.stderr.txt').write_bytes(raw)
      (product / 'core-without-modules.stdout.txt').write_bytes(b'')
      lines = []
      self.assertEqual(reports.collectReports(build, product, lines.append), 0)
      payloads = self.payloads(lines)
      self.assertEqual(payloads['candidate-case:core-without-modules']['source']['status'], 'MISSING')
      stderr = payloads['candidate-process-output:core-without-modules:stderr']
      self.assertEqual(stderr['projection']['text'], error)
      self.assertEqual(stderr['source']['bytes'], len(raw))
      self.assertEqual(stderr['source']['sha256'], hashlib.sha256(raw).hexdigest())
      stdout = payloads['candidate-process-output:core-without-modules:stdout']
      self.assertEqual(stdout['projection']['text'], '')
      self.assertEqual(stdout['source']['bytes'], 0)
      self.assertEqual(stdout['source']['sha256'], hashlib.sha256(b'').hexdigest())
      self.assertEqual((product / 'core-without-modules.stderr.txt').read_bytes(), raw)
      with patch.object(reports, 'MAX_PROCESS_LOG_BYTES', len(raw) - 1):
        with self.assertRaisesRegex(ValueError, 'fixed read budget'):
          reports.readProcessOutput(product, 'core-without-modules.stderr.txt')
      with self.assertRaisesRegex(ValueError, 'Unsafe process output'):
        reports.readProcessOutput(product, '../outside.stderr.txt')

  def test_spawn_finally_report_preserves_worker_identity_normal_exit_and_failed_cleanup(self):
    with tempfile.TemporaryDirectory() as directory:
      build, product = self.roots(directory)
      identity = {'core_sha256': 'a' * 64, 'generation': 2, 'modules': {'runtime.torch': 'b' * 64}}
      report = {'status': 'FAIL', 'runtime_identity': identity, 'error': 'cleanup failed',
                'traceback': 'complete spawn failure\n', 'steps': {
                  'worker': {'callback': {'pid': 43, 'ppid': 42, 'runtime_identity': identity},
                             'parent_observed': {'pid': 43, 'command': ['VisionWorkshop.exe']}},
                  'normal_exit': {'status': 'PASS', 'exitcode': 0},
                  'cleanup': {'status': 'FAIL', 'errors': ['owned queue remains'],
                              'worker_processes_gone': True, 'queues_released': False}}}
      raw = self.write(product, 'dataloader-spawn-full-files/dataloader-spawn-check.json', report)
      self.write(product, 'dataloader-spawn-full-files/worker-0.json', report['steps']['worker']['callback'])
      lines = []
      self.assertEqual(reports.collectReports(build, product, lines.append), 0)
      payloads = self.payloads(lines)
      self.assertEqual(payloads['candidate-spawn-detail']['projection'], report)
      self.assertEqual(payloads['candidate-spawn-detail']['source']['sha256'], hashlib.sha256(raw).hexdigest())
      self.assertEqual(payloads['candidate-spawn-worker']['projection']['pid'], 43)
      self.assertEqual(payloads['candidate-case:dataloader-spawn-full']['source']['status'], 'MISSING')

  def test_oversized_result_or_combined_budget_is_an_explicit_error_without_partial_payload(self):
    with tempfile.TemporaryDirectory() as directory:
      build, product = self.roots(directory)
      raw = self.write(product, 'core-without-modules.json',
                       {'status': 'FAIL', 'error': 'x' * 4000, 'traceback': 'complete'})
      lines = []
      with patch.object(reports.common, 'MAX_PROJECTION_BYTES', 1000):
        self.assertEqual(reports.collectReports(build, product, lines.append), 1)
      self.assertTrue(any(line.startswith('VW_CANDIDATE_REPORT_ERROR ')
                          and 'candidate-case:core-without-modules' in line for line in lines))
      self.assertNotIn('candidate-case:core-without-modules', self.payloads(lines))
      self.assertEqual((product / 'core-without-modules.json').read_bytes(), raw)
      lines = []
      with patch.object(reports.common, 'MAX_TOTAL_PROJECTION_BYTES', 1):
        self.assertEqual(reports.collectReports(build, product, lines.append), 1)
      self.assertFalse(any(line.startswith(reports.common.PREFIX) for line in lines))
      self.assertTrue(any('Combined candidate log budget exceeded' in line for line in lines))

  def test_excess_process_report_count_and_malformed_reports_are_explicit_errors(self):
    with tempfile.TemporaryDirectory() as directory:
      build, product = self.roots(directory)
      for index in range(3):
        self.write(product, str(index) + '.process.json', {'pid': index, 'exit_code': 0})
      (build / 'modular-build-summary.json').write_text('not JSON', encoding='utf-8')
      lines = []
      with patch.object(reports, 'MAX_PROCESS_REPORTS', 2):
        self.assertEqual(reports.collectReports(build, product, lines.append), 1)
      self.assertTrue(any('candidate-process-discovery' in line and 'ERROR' in line for line in lines))
      self.assertTrue(any('candidate-build' in line and 'JSONDecodeError' in line for line in lines))
      self.assertFalse(any(label.startswith('candidate-process:') for label in self.payloads(lines)))


if __name__ == '__main__':
  unittest.main()
