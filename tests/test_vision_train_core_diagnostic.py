"""Real small ZIP and event identity guards; these are not Windows product results."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from scripts import diagnose_vision_train_core as diagnostic
from scripts import verify_vision_train_modular_product as product
from vision_train_modular_archive import compressPackage
from build_records import fileHash, scanFiles


class CoreExitDiagnosticTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.payload = self.root / 'original'
    (self.payload / 'python').mkdir(parents=True)
    self.build = {'app_sha': '1' * 40, 'packager_sha': '2' * 40, 'build_id': 'candidate-123-1'}
    self.core = {'build': self.build}
    (self.payload / 'core.json').write_text(json.dumps(self.core), encoding='utf-8')
    (self.payload / 'VisionWorkshop.exe').write_bytes(b'fixture-only, not an EXE')
    (self.payload / 'python/module_contract.py').write_bytes(b'A' * 20)
    (self.payload / 'python/module_runtime.py').write_bytes(b'B' * 20)
    self.archive = self.root / 'VisionWorkshop-Core-0.0.0.zip'
    self.archiveRecord = compressPackage(self.payload, self.archive, prefix='VisionWorkshop', dictionaryMiB=1)
    self.files = scanFiles(self.payload)
    self.coreSha = self.files['core.json']['sha256']
    self.summary = {'status': 'BUILT', 'core': self.core, 'core_sha256': self.coreSha,
                    'source': {'commit': self.build['app_sha']},
                    'packager': {'commit': self.build['packager_sha']}, 'core_archive': self.archiveRecord}
    self.product = {'status': 'FAIL', 'core_sha256': self.coreSha, 'build': self.build}
    self.inventory = {'files': [{'path': name, **value} for name, value in self.files.items()]}
    self.request = {'schema_version': 1, 'diagnostic_attempt': 1, 'source_run_id': 123,
                    'source_run_attempt': 1, 'source_head_sha': '2' * 40, 'source_app_sha': '1' * 40,
                    'core_sha256': self.coreSha, 'normal_gui_comparison': True,
                    'core_archive': {'name': self.archive.name, 'bytes': self.archive.stat().st_size,
                                     'sha256': fileHash(self.archive)}, 'artifacts': {}}
    outer = self.root / 'core-artifact.zip'
    with zipfile.ZipFile(outer, 'w', compression=zipfile.ZIP_STORED) as archive:
      archive.write(self.archive, self.archive.name)
    self.request['artifacts']['core'] = {'id': 111, 'name': 'visionworkshop-core-candidate-123-1',
                                        'bytes': outer.stat().st_size, 'sha256': fileHash(outer)}
    self.writeEvidence()

  def writeEvidence(self):
    path = self.root / 'evidence-artifact.zip'
    with zipfile.ZipFile(path, 'w') as archive:
      for name, value in ((diagnostic.SUMMARY, self.summary), (diagnostic.INVENTORY, self.inventory),
                          (diagnostic.PRODUCT, self.product)):
        archive.writestr(name, json.dumps(value).encode())
    self.request['artifacts']['evidence'] = {'id': 222, 'name': 'visionworkshop-modular-evidence-123-1',
                                            'bytes': path.stat().st_size, 'sha256': fileHash(path)}

  def evidence(self):
    return diagnostic.sourceEvidence(self.root / 'evidence-artifact.zip', self.request)

  def contract(self):
    return SimpleNamespace(validate_core=lambda value: None, manifest_digest=lambda value: self.coreSha)

  def test_reviewed_current_request_has_exact_source_and_only_two_artifacts(self):
    path = Path(__file__).resolve().parents[1] / 'ci/visionworkshop-core-diagnostic.json'
    value = diagnostic.validateRequest(diagnostic.readJsonObject(path))
    self.assertEqual(value['source_run_id'], 45659615499)
    self.assertEqual(value['source_head_sha'], 'd3ace70e41a41b4334a9e44d2dbec0d4907f077d')
    self.assertEqual(value['core_archive']['bytes'], 180443076)
    self.assertEqual(set(value['artifacts']), {'core', 'evidence'})
    self.assertEqual(value['schema_version'], 3)
    self.assertIs(value['same_path_comparison'], True)
    self.assertEqual(value['expected_root_characters'], 88)
    self.assertIs(type(value['diagnostic_attempt']), int)
    self.assertGreater(value['diagnostic_attempt'], 0)
    self.assertIs(value['debugger_observed'], True)
    self.assertIs(value['dll_search_probe'], True)
    for key in ('debugger_observed', 'dll_search_probe'):
      for wrong in (False, 1, 'true', None):
        changed = dict(value, **{key: wrong})
        with self.subTest(key=key, wrong=wrong), self.assertRaises(diagnostic.BuildConfigError):
          diagnostic.validateRequest(changed)

  def test_request_rejects_unknown_bool_oversized_and_unsafe_inputs(self):
    variants = []
    for key, value in [('diagnostic_attempt', True), ('diagnostic_attempt', 0), ('diagnostic_attempt', -1),
                       ('source_run_id', True), ('source_run_attempt', 0), ('source_head_sha', 'main'),
                       ('source_app_sha', 'a' * 39), ('normal_gui_comparison', 1)]:
      changed = copy.deepcopy(self.request); changed[key] = value; variants.append(changed)
    for role, key, value in [('core', 'bytes', True), ('core', 'bytes', diagnostic.MAX_CORE_ZIP + 1024**2 + 1),
                             ('evidence', 'bytes', diagnostic.MAX_EVIDENCE_ARTIFACT_BYTES + 1),
                             ('core', 'name', '../other.zip'), ('core', 'name', 'C:other.zip')]:
      changed = copy.deepcopy(self.request); changed['artifacts'][role][key] = value; variants.append(changed)
    changed = copy.deepcopy(self.request); changed['artifacts']['runtime.torch'] = {}; variants.append(changed)
    for changed in variants:
      with self.subTest(changed=changed), self.assertRaises(diagnostic.BuildConfigError):
        diagnostic.validateRequest(changed)

  def test_real_zip_inventory_is_verified_before_original_contract_import(self):
    before = scanFiles(self.payload)
    with patch.object(diagnostic, 'loadContract', return_value=self.contract()) as loaded:
      root, core = diagnostic.extractCore(self.root, self.evidence(), self.request, self.root / 'case')
    loaded.assert_called_once_with(root / 'python')
    self.assertEqual(core, self.core)
    self.assertEqual(scanFiles(root), before)
    self.assertEqual(scanFiles(self.payload), before)

  def test_source_reports_cannot_relabel_app_builder_or_manifest(self):
    for target, key, value in [('build', 'app_sha', 'f' * 40), ('build', 'packager_sha', 'e' * 40),
                              ('summary', 'core_sha256', 'd' * 64), ('product', 'core_sha256', 'c' * 64)]:
      with self.subTest(target=target, key=key):
        summary, productReport = copy.deepcopy(self.summary), copy.deepcopy(self.product)
        if target == 'build':
          self.summary['core']['build'] = dict(self.build, **{key: value})
        elif target == 'summary':
          self.summary[key] = value
        else:
          self.product[key] = value
        self.writeEvidence()
        with self.assertRaises(diagnostic.BuildConfigError):
          self.evidence()
        self.summary, self.product = summary, productReport

  def test_actual_archive_corruption_and_extra_file_cannot_reach_import(self):
    evidence = self.evidence()
    original = self.archive.read_bytes()
    self.archive.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with patch.object(diagnostic, 'loadContract') as loaded, self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.extractCore(self.root, evidence, self.request, self.root / 'bad-hash')
    loaded.assert_not_called()
    self.archive.write_bytes(original)
    with zipfile.ZipFile(self.archive, 'a', compression=zipfile.ZIP_LZMA) as archive:
      archive.writestr('VisionWorkshop/unlisted.py', b'not in original inventory')
    self.request['core_archive'].update(bytes=self.archive.stat().st_size, sha256=fileHash(self.archive))
    with patch.object(diagnostic, 'loadContract') as loaded, self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.extractCore(self.root, evidence, self.request, self.root / 'bad-members')
    loaded.assert_not_called()

  def test_same_size_payload_change_cannot_reach_import_even_with_new_zip_digest(self):
    evidence = self.evidence()
    (self.payload / 'python/module_contract.py').write_bytes(b'C' * 20)
    self.archive.unlink()
    record = compressPackage(self.payload, self.archive, prefix='VisionWorkshop', dictionaryMiB=1)
    evidence['summary']['core_archive'] = record
    self.request['core_archive'].update(bytes=record['bytes'], sha256=record['sha256'])
    with patch.object(diagnostic, 'loadContract') as loaded, self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.extractCore(self.root, evidence, self.request, self.root / 'bad-payload')
    loaded.assert_not_called()

  def test_contract_import_cannot_silently_modify_extracted_core(self):
    def modifies(source):
      (source / 'injected.py').write_bytes(b'changed')
      return self.contract()
    with patch.object(diagnostic, 'loadContract', side_effect=modifies), self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.extractCore(self.root, self.evidence(), self.request, self.root / 'changed')

  def test_native_exit_remains_failure_even_after_internal_pass_report(self):
    reports = self.root / 'reports'; reports.mkdir()
    (self.root / 'empty-cwd').mkdir()
    def starts(command, **kwargs):
      Path(command[-1]).write_text('{"status":"PASS"}', encoding='utf-8')
      return SimpleNamespace(pid=208, returncode=0xC0000005, wait=lambda timeout: 0xC0000005,
                             poll=lambda: 0xC0000005)
    with patch.object(product.subprocess, 'Popen', side_effect=starts), self.assertRaisesRegex(RuntimeError, '3221225477'):
      product.invoke(self.payload / 'VisionWorkshop.exe', ['--modular-runtime-check', '--case', 'core'],
                     reports, 'native-exit', {}, timeout=30)
    result = json.loads((reports / 'native-exit.process.json').read_text())
    self.assertEqual(result['status'], 'FAIL')
    self.assertEqual(result['exit_code'], 0xC0000005)

  def test_gui_cleanup_reaps_the_owned_child_when_taskkill_itself_fails(self):
    events = []
    class Child:
      returncode = None
      def poll(self):
        return self.returncode
      def kill(self):
        events.append('kill'); self.returncode = -1
      def wait(self, timeout):
        events.append(('wait', timeout)); return self.returncode
    record = {'status': 'PASS', 'forced_cleanup': False}
    with patch.object(diagnostic, 'terminateTree', side_effect=subprocess.TimeoutExpired('taskkill', 30)):
      diagnostic.cleanupGuiProcess(Child(), self.root, record)
    self.assertEqual(events, ['kill', ('wait', 15)])
    self.assertEqual(record['status'], 'FAIL')
    self.assertTrue(record['forced_cleanup'])
    self.assertIsNone(record['exit_code'])
    self.assertEqual(record['cleanup_exit_code'], -1)
    self.assertTrue(record['cleanup_errors'])



  def test_schema3_comparison_controls_preserve_legacy_and_reject_nonexact_values(self):
    self.assertEqual(diagnostic.validateRequest(self.request)['schema_version'], 1)
    schema2 = dict(self.request, schema_version=2, debugger_observed=True, dll_search_probe=True)
    self.assertEqual(diagnostic.validateRequest(schema2)['schema_version'], 2)
    schema3 = dict(schema2, schema_version=3, same_path_comparison=True, expected_root_characters=88)
    self.assertEqual(diagnostic.validateRequest(schema3), schema3)
    for key, value in [('same_path_comparison', False), ('same_path_comparison', 1),
                       ('normal_gui_comparison', False), ('expected_root_characters', True),
                       ('expected_root_characters', 87), ('expected_root_characters', 89),
                       ('expected_root_characters', '88'), ('expected_root_characters', None)]:
      with self.subTest(key=key, value=value), self.assertRaises(diagnostic.BuildConfigError):
        diagnostic.validateRequest(dict(schema3, **{key: value}))
    with self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.validateRequest(dict(schema2, same_path_comparison=True))

  def test_case_specific_environment_and_receipt_do_not_expose_secret_values(self):
    base = {'PATH': 'system-only', '_no_debug_heap': 'inherited', 'ColoredLogs_Auto_Install': 'inherited',
            'SECRET_FOR_TEST': 'a-value-that-must-not-appear'}
    for name in ('core-without-modules', 'gui-close'):
      for mode in diagnostic.COMPARISON_MODES:
        with self.subTest(name=name, mode=mode), patch.object(
            diagnostic, 'productEnvironment', return_value=base):
          environment = diagnostic.comparisonEnvironment(self.root, name, mode)
        self.assertEqual(environment.get('COLOREDLOGS_AUTO_INSTALL'),
                         '1' if name == 'core-without-modules' else None)
        self.assertEqual(environment.get('_NO_DEBUG_HEAP'), '1' if mode == 'debug-noheap' else None)
        self.assertNotIn('_no_debug_heap', environment)
        self.assertNotIn('ColoredLogs_Auto_Install', environment)
        receipt = diagnostic.environmentReceipt(environment)
        self.assertEqual(receipt['sha256'], diagnostic.objectHash(environment))
        self.assertEqual(receipt['heap_behavior'], 'NOT_MEASURED')
        self.assertEqual(receipt['target_environment_readback'], 'NOT_MEASURED')
        self.assertNotIn(base['SECRET_FOR_TEST'], json.dumps(receipt))
    self.assertEqual(base['_no_debug_heap'], 'inherited')
    with self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.environmentReceipt({'PATH': 'first', 'Path': 'ambiguous'})
    with self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.comparisonEnvironment(self.root, 'unknown-case', 'plain-before')

  def test_comparison_extracts_once_per_case_and_reuses_path_in_the_exact_order(self):
    output = self.root / 'comparison-order'
    output.mkdir()
    # Controller-only fixture: the schema guard separately pins actual Windows roots to 88.
    root = self.payload.resolve()
    request = dict(self.request, expected_root_characters=len(str(root)))
    observed = []
    def observe(actualRoot, core, files, requested, name, mode, destination, sequence):
      observed.append((actualRoot, name, mode, destination, sequence))
      return {'name': name, 'mode': mode, 'status': 'PASS', 'process_exited': True,
              'core_unchanged': {'status': 'PASS'}}
    result = {'cases': []}
    with patch.object(diagnostic, 'extractCore', return_value=(root, self.core)) as extract, \
         patch.object(diagnostic, 'comparisonObservation', side_effect=observe):
      diagnostic.compareCases(self.root, output, {'files': self.files}, request, result)
    self.assertEqual(extract.call_count, 2)
    self.assertEqual([call.args[3] for call in extract.call_args_list],
                     [output / 'c/中 文', output / 'g/中 文'])
    expected = [(name, mode) for name in ('core-without-modules', 'gui-close')
                for mode in diagnostic.COMPARISON_MODES]
    self.assertEqual([(name, mode) for _, name, mode, _, _ in observed], expected)
    self.assertEqual([sequence for *_, sequence in observed], list(range(1, 9)))
    self.assertTrue(all(actualRoot == root for actualRoot, *_ in observed))
    self.assertEqual(len({destination for _, _, _, destination, _ in observed}), 8)
    self.assertEqual(result['comparison']['expected_observations'], 8)
    self.assertTrue(all(item['extraction_count'] == 1 for item in result['comparison']['installations']))

  def test_exited_failure_is_retained_while_later_controls_still_run(self):
    output = self.root / 'comparison-failure'
    output.mkdir()
    root = self.payload.resolve()
    request = dict(self.request, expected_root_characters=len(str(root)))
    def observe(actualRoot, core, files, requested, name, mode, destination, sequence):
      return {'name': name, 'mode': mode, 'status': 'FAIL' if sequence == 1 else 'PASS',
              'process': {'pid': 100 + sequence, 'exit_code': 0xc0000005 if sequence == 1 else 0},
              'process_exited': True, 'core_unchanged': {'status': 'PASS'}}
    result = {'cases': []}
    with patch.object(diagnostic, 'extractCore', return_value=(root, self.core)), \
         patch.object(diagnostic, 'comparisonObservation', side_effect=observe):
      diagnostic.compareCases(self.root, output, {'files': self.files}, request, result)
    self.assertEqual(len(result['cases']), 8)
    self.assertEqual(result['cases'][0]['status'], 'FAIL')
    self.assertEqual(result['cases'][0]['process']['exit_code'], 0xc0000005)
    self.assertFalse(all(item['status'] == 'PASS' for item in result['cases']))

  def test_unconfirmed_exit_or_changed_core_stops_before_a_later_process(self):
    root = self.payload.resolve()
    request = dict(self.request, expected_root_characters=len(str(root)))
    for index, (exited, unchanged) in enumerate(((False, 'PASS'), (True, 'FAIL'))):
      output = self.root / ('comparison-unsafe-' + str(index))
      output.mkdir()
      result = {'cases': []}
      record = {'name': 'core-without-modules', 'mode': 'plain-before', 'status': 'FAIL',
                'process_exited': exited, 'core_unchanged': {'status': unchanged}}
      with self.subTest(exited=exited, unchanged=unchanged), \
           patch.object(diagnostic, 'extractCore', return_value=(root, self.core)), \
           patch.object(diagnostic, 'comparisonObservation', return_value=record) as observe:
        with self.assertRaises(diagnostic.BuildConfigError):
          diagnostic.compareCases(self.root, output, {'files': self.files}, request, result)
        observe.assert_called_once()
      self.assertEqual(result['cases'], [record])

  def test_changed_installation_length_is_rejected_before_any_process(self):
    output = self.root / 'comparison-path'
    output.mkdir()
    root = self.payload.resolve()
    request = dict(self.request, expected_root_characters=len(str(root)) + 1)
    with patch.object(diagnostic, 'extractCore', return_value=(root, self.core)), \
         patch.object(diagnostic, 'comparisonObservation') as observe:
      with self.assertRaisesRegex(diagnostic.BuildConfigError, 'path length'):
        diagnostic.compareCases(self.root, output, {'files': self.files}, request, {'cases': []})
      observe.assert_not_called()

  def test_plain_core_records_internal_pass_and_real_failure_exit_separately(self):
    root = self.payload.resolve()
    def failed(executable, case, reports, name, environment, core, identity, timeout):
      self.assertEqual(environment['COLOREDLOGS_AUTO_INSTALL'], '1')
      self.assertNotIn('_NO_DEBUG_HEAP', environment)
      diagnostic.writeJson(reports / (name + '.json'), {'status': 'PASS', 'case': 'core', 'pid': 42})
      diagnostic.writeJson(reports / (name + '.process.json'),
                           {'status': 'FAIL', 'pid': 42, 'exit_code': 0xc0000005})
      raise RuntimeError('real child exit guard failed')
    with patch.object(diagnostic, 'productEnvironment', return_value={'PATH': 'system-only'}), \
         patch.object(diagnostic, 'checkCase', side_effect=failed), \
         patch.object(diagnostic, 'collectEvents', return_value={'status': 'NO_MATCH'}):
      result = diagnostic.comparisonObservation(root, self.core, self.files, self.request,
        'core-without-modules', 'plain-before', self.root / 'observation-native-failure', 1)
    self.assertEqual(result['status'], 'FAIL')
    self.assertEqual(result['internal_report_summary']['status'], 'PASS')
    self.assertEqual(result['process']['exit_code'], 0xc0000005)
    self.assertTrue(result['process_exited'])
    self.assertEqual(result['core_before']['status'], 'PASS')
    self.assertEqual(result['core_unchanged']['status'], 'PASS')
    self.assertEqual(result['executable'], str(root / 'VisionWorkshop.exe'))

  def test_plain_gui_preserves_unset_opt_in_and_records_its_owned_close(self):
    root = self.payload.resolve()
    def closed(executable, environment, reports):
      self.assertNotIn('COLOREDLOGS_AUTO_INSTALL', environment)
      self.assertNotIn('_NO_DEBUG_HEAP', environment)
      record = {'status': 'PASS', 'pid': 43, 'exit_code': 0, 'close_message': 'WM_CLOSE',
                'close_window': {'pid': 43, 'hwnd': 123}, 'forced_cleanup': False}
      diagnostic.writeJson(reports / 'gui-close.process.json', record)
      return record
    with patch.object(diagnostic, 'productEnvironment', return_value={'PATH': 'system-only'}), \
         patch.object(diagnostic, 'normalGui', side_effect=closed), \
         patch.object(diagnostic, 'collectEvents', return_value={'status': 'NO_MATCH'}):
      result = diagnostic.comparisonObservation(root, self.core, self.files, self.request,
        'gui-close', 'plain-before', self.root / 'observation-gui', 1)
    self.assertEqual(result['status'], 'PASS')
    self.assertEqual(result['process']['close_message'], 'WM_CLOSE')
    self.assertIsNone(result['environment']['selected']['COLOREDLOGS_AUTO_INSTALL'])
    self.assertEqual(result['heap_behavior'], 'NOT_MEASURED')

  def test_core_mutation_cannot_be_hidden_by_a_successful_child(self):
    root = self.payload.resolve()
    def mutate(executable, case, reports, name, environment, core, identity, timeout):
      executable.write_bytes(executable.read_bytes() + b'changed')
      diagnostic.writeJson(reports / (name + '.json'), {'status': 'PASS', 'case': 'core', 'pid': 44})
      diagnostic.writeJson(reports / (name + '.process.json'), {'status': 'PASS', 'pid': 44, 'exit_code': 0})
      return {'status': 'PASS'}
    with patch.object(diagnostic, 'productEnvironment', return_value={'PATH': 'system-only'}), \
         patch.object(diagnostic, 'checkCase', side_effect=mutate), \
         patch.object(diagnostic, 'collectEvents', return_value={'status': 'NO_MATCH'}):
      result = diagnostic.comparisonObservation(root, self.core, self.files, self.request,
        'core-without-modules', 'plain-after', self.root / 'observation-mutation', 4)
    self.assertEqual(result['status'], 'FAIL')
    self.assertEqual(result['process']['exit_code'], 0)
    self.assertEqual(result['core_unchanged']['status'], 'FAIL')

  def test_missing_or_malformed_process_report_cannot_become_a_pass(self):
    root = self.payload.resolve()
    for index, malformed in enumerate((False, True)):
      def incomplete(executable, case, reports, name, environment, core, identity, timeout):
        if malformed:
          (reports / (name + '.process.json')).write_text('bad JSON', encoding='utf-8')
        return {'status': 'PASS'}
      with self.subTest(malformed=malformed), \
           patch.object(diagnostic, 'productEnvironment', return_value={'PATH': 'system-only'}), \
           patch.object(diagnostic, 'checkCase', side_effect=incomplete):
        result = diagnostic.comparisonObservation(root, self.core, self.files, self.request,
          'core-without-modules', 'plain-before', self.root / ('observation-missing-' + str(index)), 1)
      self.assertEqual(result['status'], 'FAIL')
      self.assertFalse(result['process_exited'])
      self.assertTrue(result['observation_errors'])


class WindowsEventCorrelationTests(unittest.TestCase):
  start = datetime(2026, 11, 25, 17, 24, tzinfo=timezone.utc)
  end = datetime(2026, 11, 25, 17, 25, tzinfo=timezone.utc)
  executable = r'D:\中文 模块验收\VisionWorkshop\VisionWorkshop.exe'
  reportId = '11111111-2222-3333-4444-555555555555'

  def event(self, *, kind=1000, provider='Application Error', fields=None, created='2026-11-25T17:24:31.0000000Z'):
    namespace = diagnostic.EVENT_NS['e']
    node = ET.Element('{' + namespace + '}Event')
    system = ET.SubElement(node, '{' + namespace + '}System')
    ET.SubElement(system, '{' + namespace + '}Provider', Name=provider)
    ET.SubElement(system, '{' + namespace + '}EventID').text = str(kind)
    ET.SubElement(system, '{' + namespace + '}EventRecordID').text = '10'
    ET.SubElement(system, '{' + namespace + '}TimeCreated', SystemTime=created)
    ET.SubElement(system, '{' + namespace + '}Execution', ProcessID='208')
    data = ET.SubElement(node, '{' + namespace + '}EventData')
    values = fields if fields is not None else {'AppPath': self.executable, 'ProcessId': '0xd0',
      'ModuleName': 'Qt5Gui.dll', 'FaultingOffset': '00001234', 'ExceptionCode': 'c0000005',
      'IntegratorReportId': self.reportId}
    for key, value in values.items():
      ET.SubElement(data, '{' + namespace + '}Data', Name=key).text = value
    return node

  def parse(self, *events):
    root = ET.Element('Events'); root.extend(events)
    return diagnostic.matchEvents(ET.tostring(root), 208, self.executable, self.start, self.end)

  def test_target_pid_full_path_and_report_id_correlate_actual_event_fields(self):
    result = self.parse(self.event(), self.event(kind=1001, provider='Windows Error Reporting',
      fields={'ReportId': '{' + self.reportId.upper() + '}', 'P1': 'VisionWorkshop.exe'}))
    self.assertEqual(result['status'], 'MATCHED')
    self.assertEqual(result['application_errors'][0]['fields']['ModuleName'], 'Qt5Gui.dll')
    self.assertEqual(len(result['related_wer']), 1)

  def test_neighbor_pid_path_provider_or_time_cannot_match(self):
    for changes in ({'ProcessId': '0xd1'}, {'AppPath': r'D:\other\VisionWorkshop.exe'}):
      fields = {'AppPath': self.executable, 'ProcessId': '0xd0'} | changes
      self.assertEqual(self.parse(self.event(fields=fields))['status'], 'NO_MATCH')
    self.assertEqual(self.parse(self.event(provider='Other provider'))['status'], 'NO_MATCH')
    self.assertEqual(self.parse(self.event(created='2026-11-25T17:23:59Z'))['status'], 'NO_MATCH')

  def test_wer_cannot_claim_target_from_execution_pid_or_unrelated_report_id(self):
    for fields in ({'ReportId': 'another-report', 'P1': 'VisionWorkshop.exe'},
                   {'ReportId': self.reportId, 'P1': 'Other.exe'}):
      result = self.parse(self.event(), self.event(kind=1001, provider='Windows Error Reporting', fields=fields))
      self.assertEqual(result['related_wer'], [])
    result = self.parse(self.event(kind=1001, provider='Windows Error Reporting',
                        fields={'ReportId': self.reportId, 'P1': 'VisionWorkshop.exe'}))
    self.assertEqual(result['status'], 'NO_MATCH')
    self.assertEqual(result['related_wer'], [])

  def test_zero_or_invalid_placeholder_report_ids_cannot_correlate_wer(self):
    for reportId in ('00000000-0000-0000-0000-000000000000', 'placeholder', ''):
      with self.subTest(report_id=reportId):
        error = self.event(fields={'AppPath': self.executable, 'ProcessId': '208',
                                   'IntegratorReportId': reportId})
        wer = self.event(kind=1001, provider='Windows Error Reporting',
                         fields={'ReportId': reportId, 'P1': 'VisionWorkshop.exe'})
        result = self.parse(error, wer)
        self.assertEqual(result['status'], 'MATCHED')
        self.assertEqual(result['related_wer'], [])

  def test_utf16_event_stream_and_empty_query_remain_explicit(self):
    root = ET.Element('Events'); root.append(self.event())
    result = diagnostic.matchEvents(ET.tostring(root, encoding='utf-16'), 208, self.executable, self.start, self.end)
    self.assertEqual(result['status'], 'MATCHED')
    self.assertEqual(result['application_errors'][0]['fields']['AppPath'], self.executable)
    self.assertEqual(diagnostic.matchEvents(ET.tostring(root, encoding='utf-16'), 208,
      self.executable.replace('中文', 'other'), self.start, self.end)['status'], 'NO_MATCH')
    for encoding in ('utf-16', 'utf-16-le', 'utf-16-be'):
      with self.subTest(encoding=encoding), self.assertRaises(diagnostic.BuildConfigError):
        diagnostic.matchEvents('<!DOCTYPE Events><Events/>'.encode(encoding), 208,
                               self.executable, self.start, self.end)
    self.assertEqual(self.parse()['status'], 'NO_MATCH')

  def test_only_exact_owned_visible_enabled_product_window_is_selected(self):
    window = {'pid': 208, 'hwnd': 123, 'title': 'VisionWorkshop', 'visible': True, 'enabled': True}
    self.assertEqual(diagnostic.selectWindow([window], 208), window)
    for key, value in [('pid', 209), ('title', 'VisionWorkshop startup failed'),
                       ('visible', False), ('enabled', False)]:
      self.assertIsNone(diagnostic.selectWindow([dict(window, **{key: value})], 208))
    with self.assertRaises(diagnostic.BuildConfigError):
      diagnostic.selectWindow([window, dict(window, hwnd=456)], 208)

  def test_owned_window_must_remain_visible_enabled_and_same_hwnd_for_one_second(self):
    window = {'pid': 208, 'hwnd': 123, 'title': 'VisionWorkshop', 'visible': True, 'enabled': True}
    state = {}
    self.assertIsNone(diagnostic.stableWindow([window], 208, state, 10.0))
    self.assertIsNone(diagnostic.stableWindow([window], 208, state, 10.8))
    self.assertIsNone(diagnostic.stableWindow([dict(window, enabled=False)], 208, state, 10.9))
    self.assertIsNone(diagnostic.stableWindow([window], 208, state, 11.0))
    self.assertIsNone(diagnostic.stableWindow([window], 208, state, 11.9))
    self.assertEqual(diagnostic.stableWindow([window], 208, state, 12.0), window)
    self.assertIsNone(diagnostic.stableWindow([dict(window, hwnd=456)], 208, state, 12.1))


if __name__ == '__main__':
  unittest.main()
