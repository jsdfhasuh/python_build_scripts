"""Keep immutable source modules while qualifying only excluded EXE receipt hashes."""

import base64
from copy import deepcopy
import csv
import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
import zipfile

from build_config import BuildConfigError
from build_records import fileHash
from build_records import scanFiles
from vision_train_module_inventory import readDistributions
from vision_train_modular_archive import compressPackage
from vision_train_modular_build import loadContract
from vision_train_modular_receipts import qualifyReceiptRows
from vision_train_modular_receipts import recordProjection
from vision_train_modular_receipts import selectSourceStaging
from vision_train_modular_reuse import reuseArchive


def recordBytes(rows):
  stream = io.StringIO(newline='')
  csv.writer(stream).writerows(rows)
  return stream.getvalue().encode('utf-8')


def receiptInventory(data):
  _, records, omitted = recordProjection(data)
  return {'records': records, 'preparation_only_files': omitted}


class ReceiptCsvTests(unittest.TestCase):
  def setUp(self):
    self.rows = [
      ['../../Scripts/example.exe', 'sha256=' + 'a' * 43, '108287'],
      ['example/__init__.py', 'sha256=' + 'b' * 43, '8'],
      ['example/__pycache__/__init__.cpython-312.pyc', '', ''],
      ['example-1.0.0.dist-info/RECORD', '', ''],
    ]
    self.original = recordBytes(self.rows)
    freshRows = deepcopy(self.rows)
    freshRows[0][1] = 'sha256=' + 'c' * 43
    self.fresh = recordBytes(freshRows)

  def qualify(self, original=None, fresh=None):
    original = self.original if original is None else original
    fresh = self.fresh if fresh is None else fresh
    return qualifyReceiptRows(original, fresh, receiptInventory(original), receiptInventory(fresh))

  def test_only_existing_generated_entry_hash_changes_are_qualified(self):
    result = self.qualify()
    self.assertEqual(len(result), 1)
    self.assertEqual(result[0]['path'], '../../Scripts/example.exe')
    self.assertEqual(result[0]['size'], 108287)
    self.assertFalse(result[0]['distributed'])
    self.assertEqual(result[0]['source_hash'], 'sha256=' + 'a' * 43)
    self.assertEqual(result[0]['fresh_hash'], 'sha256=' + 'c' * 43)

  def test_runtime_rows_script_size_path_row_count_and_order_cannot_change(self):
    for change in ('runtime', 'size', 'path', 'add', 'remove', 'order'):
      rows = list(csv.reader(self.fresh.decode().splitlines()))
      if change == 'runtime':
        rows[1][1] = 'sha256=' + 'd' * 43
      elif change == 'size':
        rows[0][2] = '108288'
      elif change == 'path':
        rows[0][0] = '../../Scripts/another.exe'
      elif change == 'add':
        rows.append(['../../Scripts/extra.exe', 'sha256=' + 'd' * 43, '10'])
      elif change == 'remove':
        del rows[-1]
      else:
        rows[0], rows[1] = rows[1], rows[0]
      with self.subTest(change=change), self.assertRaises(BuildConfigError):
        self.qualify(fresh=recordBytes(rows))

  def test_other_excluded_files_and_pyc_receipts_are_not_relaxed(self):
    for path in ('../../elsewhere/example.exe', '../../Scripts/example.py',
                 '../../Scripts/../example.exe', '../../Scripts/example.EXE',
                 '..\\..\\Scripts\\example.exe', 'example/__pycache__/generated.pyc'):
      old = deepcopy(self.rows)
      old[0][0] = path
      fresh = deepcopy(old)
      fresh[0][1] = 'sha256=' + 'c' * 43
      with self.subTest(path=path), self.assertRaisesRegex(BuildConfigError, 'Unqualified'):
        self.qualify(recordBytes(old), recordBytes(fresh))

  def test_csv_format_line_endings_hash_scheme_and_blank_sizes_are_not_relaxed(self):
    variants = [self.fresh.replace(b'\r\n', b'\n'),
                self.fresh.replace(b'../../Scripts/example.exe', b'"../../Scripts/example.exe"'),
                self.fresh.replace(b'sha256=' + b'c' * 43, b'sha512=' + b'c' * 43),
                self.fresh.replace(b',108287', b','),
                self.fresh + b'\r\n']
    for value in variants:
      with self.subTest(value=value[:90]), self.assertRaises(BuildConfigError):
        self.qualify(fresh=value)

  def test_unchanged_record_and_inventory_mismatch_do_not_qualify_an_exception(self):
    with self.assertRaisesRegex(BuildConfigError, 'no qualified'):
      self.qualify(fresh=self.original)
    inventory = receiptInventory(self.original)
    inventory['preparation_only_files'] = []
    with self.assertRaisesRegex(BuildConfigError, 'source inventories'):
      qualifyReceiptRows(self.original, self.fresh, inventory, receiptInventory(self.fresh))


@unittest.skipUnless(os.environ.get('VISIONWORKSHOP_MODULE_SOURCE'),
                     'requires the exact application contract checkout')
class ReceiptArchiveTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.contract = loadContract(Path(os.environ['VISIONWORKSHOP_MODULE_SOURCE']))
    self.moduleId = 'runtime.example'
    self.module = self.root / 'original'
    self.payload = self.module / 'payload'
    self.site = self.payload / 'site-packages'
    self.recordPath = 'site-packages/example-1.0.0.dist-info/RECORD'
    data = {'example/__init__.py': b'VALUE=1\n',
            'example-1.0.0.dist-info/METADATA':
              b'Metadata-Version: 2.1\nName: example\nVersion: 1.0.0\n'}
    rows = [['../../Scripts/example.exe', 'sha256=' + 'a' * 43, '108287']]
    for name, value in data.items():
      path = self.site / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(value)
      digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip('=')
      rows.append([name, 'sha256=' + digest, str(len(value))])
    rows += [['example/__pycache__/__init__.cpython-312.pyc', '', ''],
             ['example-1.0.0.dist-info/RECORD', '', '']]
    self.originalRecord = recordBytes(rows)
    (self.payload / self.recordPath).write_bytes(self.originalRecord)
    self.originalInstalled = readDistributions(self.site)
    self.provenance = {'example': {'version': '1.0.0', 'sha256': '1' * 64,
                                   'url': 'https://example.test/example-1.0.0.whl',
                                   'report_sha256': '2' * 64}}
    self.declaration = {'label': 'Receipt fixture', 'kind': 'runtime', 'requires': [],
                        'import_roots': ['example'], 'distributions': {'example': '1.0.0'}}
    self.core = {'protocol_version': 4, 'module_api': 1, 'type': 'visionworkshop-core',
                 'version': '0.0.0', 'entrypoint': 'VisionWorkshop.exe',
                 'python': {'version': '3.12.10', 'abi': 'cp312', 'platform': 'win_amd64'},
                 'dependency_lock_sha256': '3' * 64,
                 'build': {'app_sha': 'a' * 40, 'packager_sha': 'b' * 40,
                           'build_id': 'candidate-123-1'},
                 'python_paths': ['python', 'site-packages'], 'dll_dirs': [], 'preload_dlls': [],
                 'distributions': {}, 'import_roots': [], 'catalog': {self.moduleId: self.declaration}}
    self.manifest = {'protocol_version': 4, 'module_api': 1, 'type': 'visionworkshop-module',
                     'module_id': self.moduleId, 'version': '0.0.0',
                     'python': deepcopy(self.core['python']),
                     'dependency_lock_sha256': self.core['dependency_lock_sha256'],
                     'build': deepcopy(self.core['build']),
                     'core_versions': {'min': '0.0.0', 'max_exclusive': '0.0.1'},
                     **{key: value for key, value in self.declaration.items() if key != 'label'},
                     'python_paths': ['site-packages'], 'dll_dirs': [], 'resources': {},
                     **self.inventory(self.payload)}
    self.contract.validate_core(self.core)
    self.contract.validate_manifest(self.manifest, self.core)
    self.manifestBytes = self.contract.canonical_json(self.manifest)
    (self.module / 'module.json').write_bytes(self.manifestBytes)
    self.archive = self.root / 'source.zip'
    self.package = compressPackage(self.module, self.archive, dictionaryMiB=1)
    self.package.update(module_id=self.moduleId,
                        manifest_sha256=self.contract.manifest_digest(self.manifest))
    self.source = {'root': self.root, 'summary': {'core': deepcopy(self.core)},
                   'packages': {self.moduleId: self.package},
                   'installed': {'distributions': deepcopy(self.originalInstalled),
                                 'provenance': deepcopy(self.provenance)},
                   'receipt': {'source_run': {'id': 123, 'conclusion': 'failure'},
                     'source_product_acceptance': {'status': 'FAIL'},
                     'modules': {self.moduleId: dict(self.package, archive_path=self.archive.name,
                                                     artifact={'id': 2})}}}
    self.newCore = deepcopy(self.core)
    self.newCore['build'] = {'app_sha': 'c' * 40, 'packager_sha': 'd' * 40,
                            'build_id': 'candidate-456-1'}
    self.fresh = self.root / 'fresh/payload'
    shutil.copytree(self.payload, self.fresh)
    rows[0][1] = 'sha256=' + 'c' * 43
    self.freshRecord = recordBytes(rows)
    (self.fresh / self.recordPath).write_bytes(self.freshRecord)
    self.distributions = readDistributions(self.fresh / 'site-packages')
    self.expected = dict(deepcopy(self.manifest), build=self.newCore['build'], **self.inventory(self.fresh))
    self.selected = self.root / 'selected/payload'
    self.evidence = self.root / 'reports'

  def inventory(self, payload):
    files = [{'path': name, **record} for name, record in scanFiles(payload).items()]
    return {'files': files, 'expanded_size': sum(item['size'] for item in files)}

  def select(self):
    return selectSourceStaging(self.source, self.moduleId, self.fresh, self.expected, self.newCore,
                               self.selected, self.contract, self.distributions,
                               self.provenance, self.evidence)

  def test_selected_original_stage_passes_unchanged_strict_zip_gate_and_keeps_both_receipts(self):
    freshBefore = scanFiles(self.fresh)
    zipBefore = self.archive.read_bytes()
    selected, proof = self.select()
    self.assertEqual((self.selected / self.recordPath).read_bytes(), self.originalRecord)
    self.assertEqual((self.fresh / self.recordPath).read_bytes(), self.freshRecord)
    self.assertEqual(scanFiles(self.fresh), freshBefore)
    self.assertEqual((self.evidence / 'example.source.RECORD').read_bytes(), self.originalRecord)
    self.assertEqual((self.evidence / 'example.fresh.RECORD').read_bytes(), self.freshRecord)
    original, artifact, report, manifestBytes = reuseArchive(
      self.source, self.moduleId, self.selected, selected, self.newCore,
      self.root / 'reused.zip', self.contract)
    self.assertEqual(manifestBytes, self.manifestBytes)
    self.assertEqual(original, self.manifest)
    self.assertEqual(Path(artifact['path']).read_bytes(), zipBefore)
    self.assertEqual(self.archive.read_bytes(), zipBefore)
    self.assertFalse(proof['fresh_payload_identical'])
    self.assertTrue(proof['non_record_payload_identical'])
    self.assertTrue(proof['fresh_staging_unchanged'])
    self.assertEqual(proof['source_build'], self.core['build'])
    self.assertEqual(report['source_product_acceptance']['status'], 'FAIL')
    self.assertEqual(report['target_core_build'], self.newCore['build'])

  def test_fresh_stage_cannot_pass_strict_reuse_without_original_source_selection(self):
    with self.assertRaisesRegex(BuildConfigError, 'metadata, version, compatibility or payload'):
      reuseArchive(self.source, self.moduleId, self.fresh, self.expected, self.newCore,
                    self.root / 'rejected.zip', self.contract)

  def test_any_non_record_payload_difference_is_rejected(self):
    (self.fresh / 'site-packages/example/__init__.py').write_bytes(b'VALUE=2\n')
    self.expected.update(self.inventory(self.fresh))
    with self.assertRaisesRegex(BuildConfigError, 'Non-receipt'):
      self.select()
    self.assertFalse(self.selected.exists())

  def test_different_wheel_distribution_owner_or_report_record_hash_is_rejected(self):
    originals = deepcopy(self.source), deepcopy(self.distributions), deepcopy(self.provenance)
    for change in ('wheel', 'version', 'owner', 'source-record', 'fresh-record', 'metadata', 'build'):
      self.source, self.distributions, self.provenance = deepcopy(originals)
      if change == 'wheel':
        self.provenance['example']['sha256'] = 'f' * 64
      elif change == 'version':
        self.distributions['example']['version'] = '1.0.1'
      elif change == 'owner':
        self.source['installed']['distributions']['different'] = self.source['installed']['distributions'].pop('example')
      elif change == 'source-record':
        self.source['installed']['distributions']['example']['record_sha256'] = 'f' * 64
      elif change == 'fresh-record':
        self.distributions['example']['record_sha256'] = 'f' * 64
      elif change == 'metadata':
        self.distributions['example']['metadata_path'] = 'other.dist-info'
      else:
        self.source['summary']['core']['build']['app_sha'] = 'f' * 40
      with self.subTest(change=change), self.assertRaises(BuildConfigError):
        self.select()
      self.assertFalse(self.selected.exists())

  def test_bad_raw_excluded_entry_keeps_original_and_fresh_evidence(self):
    data = self.freshRecord.replace(b',108287', b',108288')
    (self.fresh / self.recordPath).write_bytes(data)
    self.distributions = readDistributions(self.fresh / 'site-packages')
    self.expected.update(self.inventory(self.fresh))
    with self.assertRaisesRegex(BuildConfigError, 'Unqualified'):
      self.select()
    self.assertEqual((self.evidence / 'example.source.RECORD').read_bytes(), self.originalRecord)
    self.assertEqual((self.evidence / 'example.fresh.RECORD').read_bytes(), data)
    self.assertFalse(self.selected.exists())

  def test_source_zip_tamper_and_undeclared_staging_bytes_cannot_be_selected(self):
    (self.fresh / 'extra').write_bytes(b'undeclared')
    with self.assertRaisesRegex(BuildConfigError, 'independently generated inventory'):
      self.select()
    (self.fresh / 'extra').unlink()
    self.archive.write_bytes(self.archive.read_bytes() + b'changed')
    with self.assertRaisesRegex(BuildConfigError, 'original verified module ZIP'):
      self.select()

  def test_member_types_and_complete_size_inventory_are_checked_before_extraction(self):
    before = self.archive.read_bytes()
    with zipfile.ZipFile(self.archive) as archive:
      entries = [(entry.filename, archive.read(entry)) for entry in archive.infolist()]
    with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_LZMA) as archive:
      for name, data in entries:
        entry = zipfile.ZipInfo(name)
        entry.compress_type = zipfile.ZIP_LZMA
        entry.external_attr = ((stat.S_IFLNK | 0o777) if name.startswith('payload/')
                               else (stat.S_IFREG | 0o644)) << 16
        archive.writestr(entry, data)
    self.source['receipt']['modules'][self.moduleId].update(
      bytes=self.archive.stat().st_size, sha256=fileHash(self.archive))
    with self.assertRaisesRegex(BuildConfigError, 'invalid file type'):
      self.select()
    self.assertFalse(self.selected.exists())
    self.archive.write_bytes(before)
    self.source['receipt']['modules'][self.moduleId].update(
      bytes=len(before), sha256=fileHash(self.archive))
    self.source['packages'][self.moduleId]['expanded_bytes'] += 1
    with self.assertRaisesRegex(BuildConfigError, 'complete size inventory'):
      self.select()
    self.assertFalse(self.selected.exists())


if __name__ == '__main__':
  unittest.main()
