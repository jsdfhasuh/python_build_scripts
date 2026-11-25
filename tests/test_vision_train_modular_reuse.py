"""Real ZIP reuse verifies original artifacts and every new staged payload byte."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request
import warnings
import zipfile

from build_config import BuildConfigError
from build_records import fileHash
from build_records import scanFiles
from vision_train_modular_archive import compressPackage
from vision_train_modular_build import loadContract
from vision_train_modular_reuse import PRODUCT_MEMBER
from vision_train_modular_reuse import MAX_MODULE_ARCHIVE_BYTES
from vision_train_modular_reuse import MAX_MODULE_ARTIFACT_BYTES
from vision_train_modular_reuse import REPOSITORY
from vision_train_modular_reuse import SUMMARY_MEMBER
from vision_train_modular_reuse import downloadArtifact
from vision_train_modular_reuse import prepareReuse
from vision_train_modular_reuse import readReuseSource
from vision_train_modular_reuse import reuseArchive
from vision_train_modular_reuse import selectArtifact
from vision_train_modular_reuse import sourceRun
from vision_train_modular_reuse import validateReuseCore


@unittest.skipUnless(os.environ.get('VISIONWORKSHOP_MODULE_SOURCE'),
                     'requires the exact application contract checkout')
class ModuleReuseTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.contract = loadContract(Path(os.environ['VISIONWORKSHOP_MODULE_SOURCE']))
    self.run = {'id': 123, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
                'head_sha': 'b' * 40, 'repository': {'full_name': REPOSITORY},
                'html_url': 'https://github.com/' + REPOSITORY + '/actions/runs/123'}
    self.lock = {'type': 'explicit-test-recipe', 'version': 1}
    declaration = {'label': '测试模块', 'kind': 'resource', 'requires': [],
                   'import_roots': [], 'distributions': {}}
    self.core = {'protocol_version': 4, 'module_api': 1, 'type': 'visionworkshop-core',
                 'version': '0.0.0', 'entrypoint': 'VisionWorkshop.exe',
                 'python': {'version': '3.12.10', 'abi': 'cp312', 'platform': 'win_amd64'},
                 'dependency_lock_sha256': self.contract.manifest_digest(self.lock),
                 'build': {'app_sha': 'a' * 40, 'packager_sha': 'b' * 40,
                           'build_id': 'candidate-123-1'},
                 'python_paths': ['python', 'site-packages'], 'dll_dirs': [], 'preload_dlls': [],
                 'distributions': {}, 'import_roots': [],
                 'catalog': {'resource.example': declaration}}
    self.contract.validate_core(self.core)
    self.module = self.root / 'original'
    self.payload = self.module / 'payload'
    for name, data in {'resources/中文 空格/weights.bin': b'explicit fixture bytes\x00' * 1000,
                       'resources/empty': b''}.items():
      path = self.payload / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(data)
    files = [{'path': name, **record} for name, record in scanFiles(self.payload).items()]
    self.manifest = {'protocol_version': 4, 'module_api': 1, 'type': 'visionworkshop-module',
                     'module_id': 'resource.example', 'version': '0.0.0',
                     'python': deepcopy(self.core['python']),
                     'dependency_lock_sha256': self.core['dependency_lock_sha256'],
                     'build': deepcopy(self.core['build']),
                     'core_versions': {'min': '0.0.0', 'max_exclusive': '0.0.1'},
                     **{key: value for key, value in declaration.items() if key != 'label'},
                     'python_paths': [], 'dll_dirs': [],
                     'resources': {'static/models/example': 'resources'},
                     'files': files, 'expanded_size': sum(item['size'] for item in files)}
    self.contract.validate_manifest(self.manifest, self.core)
    self.manifestBytes = self.contract.canonical_json(self.manifest)
    (self.module / 'module.json').write_bytes(self.manifestBytes)
    self.zip = self.root / 'resource.example-0.0.0.zip'
    package = compressPackage(self.module, self.zip, dictionaryMiB=1)
    package.update(module_id='resource.example',
                   manifest_sha256=self.contract.manifest_digest(self.manifest))
    self.summary = {'status': 'BUILT', 'core': self.core,
                    'core_sha256': self.contract.manifest_digest(self.core),
                    'dependency_lock': self.lock,
                    'source': {'commit': self.core['build']['app_sha']},
                    'packager': {'commit': self.core['build']['packager_sha']},
                    'module_archives': [package]}
    self.product = {'status': 'FAIL', 'gpu_hardware': 'NOT_RUN', 'cases': [],
                    'error': 'Explicit original native failure fixture',
                    'core_sha256': self.summary['core_sha256'], 'build': self.core['build']}
    self.outerEvidence = self.root / 'evidence-artifact.zip'
    with zipfile.ZipFile(self.outerEvidence, 'w') as archive:
      archive.writestr(SUMMARY_MEMBER, json.dumps(self.summary).encode())
      archive.writestr(PRODUCT_MEMBER, json.dumps(self.product).encode())
    self.outerModule = self.root / 'module-artifact.zip'
    with zipfile.ZipFile(self.outerModule, 'w') as archive:
      archive.write(self.zip, self.zip.name)
    self.artifacts = [self.artifact(1, self.outerEvidence, 'visionworkshop-modular-evidence-123-1'),
                      self.artifact(2, self.outerModule, 'visionworkshop-module-resource.example-123-1')]
    self.downloads = {'/actions/artifacts/1/zip': self.outerEvidence,
                      '/actions/artifacts/2/zip': self.outerModule}
    self.reuseRoot = self.root / 'reuse'
    with patch('vision_train_modular_reuse.apiJson', side_effect=self.api), \
         patch('vision_train_modular_reuse.apiRequest', side_effect=self.request):
      prepareReuse(123, 1, self.reuseRoot)
    self.source = readReuseSource(self.reuseRoot, self.contract, {'resource.example'})
    self.newCore = deepcopy(self.core)
    self.newCore['build'] = {'app_sha': 'c' * 40, 'packager_sha': 'd' * 40,
                            'build_id': 'candidate-456-1'}
    self.expected = deepcopy(self.manifest)
    self.expected['build'] = deepcopy(self.newCore['build'])
    self.newPayload = self.root / 'new-staging/payload'
    shutil.copytree(self.payload, self.newPayload)

  def artifact(self, number, path, name):
    return {'id': number, 'name': name, 'expired': False, 'size_in_bytes': path.stat().st_size,
            'digest': 'sha256:' + fileHash(path),
            'workflow_run': {'id': self.run['id'], 'head_sha': self.run['head_sha']}}

  def api(self, path):
    if path == '/actions/runs/123':
      return deepcopy(self.run)
    if path == '/actions/runs/123/artifacts?per_page=100&page=1':
      return {'artifacts': deepcopy(self.artifacts), 'total_count': len(self.artifacts)}
    raise AssertionError('Unexpected API path: ' + path)

  def request(self, path):
    return Request(self.downloads[path].as_uri())

  def reuse(self, *, expected=None, core=None, destination=None):
    return reuseArchive(self.source, 'resource.example', self.newPayload,
                         expected or self.expected, core or self.newCore,
                         destination or self.root / 'reused.zip', self.contract)

  def rewriteZip(self, transform):
    path = self.reuseRoot / self.source['receipt']['modules']['resource.example']['archive_path']
    with zipfile.ZipFile(path) as archive:
      entries = [(item.filename, archive.read(item), item.external_attr) for item in archive.infolist()]
    with warnings.catch_warnings():
      warnings.simplefilter('ignore', UserWarning)
      with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_LZMA) as archive:
        for name, data, mode in transform(entries):
          info = zipfile.ZipInfo(name)
          info.compress_type = zipfile.ZIP_LZMA
          info.external_attr = mode
          archive.writestr(info, data)
    item = self.source['receipt']['modules']['resource.example']
    item.update(bytes=path.stat().st_size, sha256=fileHash(path))
    return path

  def test_completed_failed_run_reuses_exact_zip_and_manifest_with_new_core_identity(self):
    before = scanFiles(self.newPayload)
    original, artifact, report, data = self.reuse()
    self.assertEqual((self.root / 'reused.zip').read_bytes(), self.zip.read_bytes())
    self.assertEqual(data, self.manifestBytes)
    self.assertEqual(original['build'], self.core['build'])
    self.assertNotEqual(original['build'], self.newCore['build'])
    self.assertEqual(report['source_run']['conclusion'], 'failure')
    self.assertEqual(report['source_product_acceptance']['status'], 'FAIL')
    self.assertEqual(report['target_core_build'], self.newCore['build'])
    self.assertEqual(report['payload_files_verified'], 2)
    self.assertEqual(artifact['sha256'], fileHash(self.zip))
    self.assertEqual(scanFiles(self.newPayload), before)
    self.assertEqual(self.source['receipt']['evidence_artifact']['digest'],
                     'sha256:' + fileHash(self.outerEvidence))

  def test_in_progress_wrong_attempt_or_repository_cannot_be_a_source(self):
    for field, value in [('status', 'in_progress'), ('run_attempt', 2),
                          ('repository', {'full_name': 'someone/else'})]:
      with self.subTest(field=field):
        run = dict(self.run, **{field: value})
        with self.assertRaises(BuildConfigError):
          sourceRun(run, 123, 1)

  def test_ambiguous_missing_digest_expired_or_other_head_artifacts_are_rejected(self):
    original = self.artifacts[0]
    for field, value in [('digest', ''), ('expired', True),
                          ('workflow_run', {'id': 123, 'head_sha': 'f' * 40})]:
      with self.subTest(field=field), self.assertRaises(BuildConfigError):
        selectArtifact([dict(original, **{field: value})], original['name'], self.run)
    with self.assertRaises(BuildConfigError):
      selectArtifact([original, original], original['name'], self.run)

  def test_changed_outer_artifact_bytes_fail_before_use(self):
    self.outerModule.write_bytes(self.outerModule.read_bytes() + b'changed')
    with patch('vision_train_modular_reuse.apiRequest', side_effect=self.request), \
         self.assertRaisesRegex(BuildConfigError, 'declared size'):
      downloadArtifact(self.artifacts[1], self.root / 'bad-download.zip',
                        maximumBytes=MAX_MODULE_ARTIFACT_BYTES)

  def test_oversized_outer_artifact_is_rejected_before_opening_network(self):
    artifact = dict(self.artifacts[1], size_in_bytes=MAX_MODULE_ARTIFACT_BYTES + 1)
    with patch('vision_train_modular_reuse.apiRequest') as request, \
         self.assertRaisesRegex(BuildConfigError, 'download bound'):
      downloadArtifact(artifact, self.root / 'oversized.zip', maximumBytes=MAX_MODULE_ARTIFACT_BYTES)
    request.assert_not_called()

  def test_oversized_or_boolean_inner_size_is_rejected_before_module_download(self):
    for index, size in enumerate((MAX_MODULE_ARCHIVE_BYTES + 1, True)):
      summary = deepcopy(self.summary)
      summary['module_archives'][0]['bytes'] = size
      with zipfile.ZipFile(self.outerEvidence, 'w') as archive:
        archive.writestr(SUMMARY_MEMBER, json.dumps(summary).encode())
        archive.writestr(PRODUCT_MEMBER, json.dumps(self.product).encode())
      self.artifacts[0] = self.artifact(1, self.outerEvidence, 'visionworkshop-modular-evidence-123-1')
      with patch('vision_train_modular_reuse.apiJson', side_effect=self.api), \
           patch('vision_train_modular_reuse.apiRequest', side_effect=self.request), \
           patch('vision_train_modular_reuse.downloadArtifact', wraps=downloadArtifact) as download, \
           self.subTest(size=size), self.assertRaisesRegex(BuildConfigError, 'preparation size bound'):
        prepareReuse(123, 1, self.root / ('oversized-source-' + str(index)))
      self.assertEqual(download.call_count, 1)
      self.assertEqual(download.call_args.args[0]['id'], 1)

  def test_source_report_result_or_build_evidence_cannot_change_after_extraction(self):
    for name in ('source-build-summary.json', 'source-product-summary.json'):
      path = self.reuseRoot / name
      original = path.read_bytes()
      path.write_bytes(original + b' ')
      with self.subTest(name=name), self.assertRaises(BuildConfigError):
        readReuseSource(self.reuseRoot, self.contract, {'resource.example'})
      path.write_bytes(original)

  def test_source_build_must_be_built_even_with_consistent_report_hashes(self):
    path = self.reuseRoot / 'source-build-summary.json'
    report = json.loads(path.read_bytes())
    report['status'] = 'FAIL'
    path.write_text(json.dumps(report), encoding='utf-8')
    receiptPath = self.reuseRoot / 'reuse-source.json'
    receipt = json.loads(receiptPath.read_bytes())
    receipt['build_summary'].update(size=path.stat().st_size, sha256=fileHash(path))
    receiptPath.write_text(json.dumps(receipt), encoding='utf-8')
    with self.assertRaisesRegex(BuildConfigError, 'Core identity'):
      readReuseSource(self.reuseRoot, self.contract, {'resource.example'})

  def test_schema_lock_abi_or_catalog_change_rejects_reuse(self):
    for field, value in [('protocol_version', 5), ('module_api', 2),
                          ('dependency_lock_sha256', 'f' * 64),
                          ('python', dict(self.core['python'], version='3.12.11')),
                          ('catalog', {})]:
      with self.subTest(field=field), self.assertRaises(BuildConfigError):
        validateReuseCore(self.source, dict(self.newCore, **{field: value}))

  def test_changed_staged_bytes_or_extra_file_rejects_reuse(self):
    path = self.newPayload / 'resources/empty'
    path.write_bytes(b'changed')
    with self.assertRaisesRegex(BuildConfigError, 'staged module payload'):
      self.reuse()
    path.write_bytes(b'')
    (self.newPayload / 'resources/extra').write_bytes(b'undeclared')
    with self.assertRaisesRegex(BuildConfigError, 'staged module payload'):
      self.reuse()

  def test_equal_inventory_with_changed_declared_payload_still_rejects_old_zip(self):
    path = self.newPayload / 'resources/empty'
    path.write_bytes(b'new weight')
    expected = deepcopy(self.expected)
    expected['files'] = [{'path': name, **record} for name, record in scanFiles(self.newPayload).items()]
    expected['expanded_size'] = sum(item['size'] for item in expected['files'])
    with self.assertRaisesRegex(BuildConfigError, 'metadata, version, compatibility or payload changed'):
      self.reuse(expected=expected)

  def test_changed_module_version_or_core_range_rejects_reuse(self):
    for field, value in [('version', '0.0.1'),
                          ('core_versions', {'min': '0.0.0', 'max_exclusive': '0.0.2'})]:
      expected = dict(self.expected, **{field: value})
      with self.subTest(field=field), self.assertRaisesRegex(BuildConfigError, 'metadata, version'):
        self.reuse(expected=expected)

  def test_whole_zip_tampering_is_detected_before_member_validation(self):
    path = self.reuseRoot / self.source['receipt']['modules']['resource.example']['archive_path']
    path.write_bytes(path.read_bytes() + b'extra')
    with self.assertRaisesRegex(BuildConfigError, 'verified source artifact'):
      self.reuse()

  def test_duplicate_or_undeclared_zip_member_is_rejected(self):
    original = (self.reuseRoot / 'modules' / self.zip.name).read_bytes()
    for duplicate in (True, False):
      (self.reuseRoot / 'modules' / self.zip.name).write_bytes(original)
      def change(entries):
        return entries + ([entries[-1]] if duplicate else [('extra.txt', b'extra', 0o100644 << 16)])
      self.rewriteZip(change)
      with self.subTest(duplicate=duplicate), self.assertRaisesRegex(BuildConfigError, 'duplicate|undeclared'):
        self.reuse()

  def test_noncanonical_original_manifest_is_rejected_without_rewriting(self):
    self.rewriteZip(lambda entries: [(name, data + b'\n' if name == 'module.json' else data, mode)
                                     for name, data, mode in entries])
    with self.assertRaisesRegex(BuildConfigError, 'canonical identity'):
      self.reuse()

  def test_symlink_zip_entry_is_rejected_even_when_payload_bytes_match(self):
    self.rewriteZip(lambda entries: [(name, data, (stat.S_IFLNK | 0o777) << 16
                                     if name.startswith('payload/') else mode)
                                     for name, data, mode in entries])
    with self.assertRaisesRegex(BuildConfigError, 'invalid file type'):
      self.reuse()

  def test_reused_source_can_preserve_its_earlier_original_module_build(self):
    self.source['summary']['module_builds'] = {'resource.example': deepcopy(self.core['build'])}
    self.source['summary']['core']['build'] = {
      'app_sha': 'e' * 40, 'packager_sha': 'f' * 40, 'build_id': 'candidate-234-1'}
    original, _, report, data = self.reuse()
    self.assertEqual(data, self.manifestBytes)
    self.assertEqual(original['build']['build_id'], 'candidate-123-1')
    self.assertEqual(report['source_build']['build_id'], 'candidate-123-1')


if __name__ == '__main__':
  unittest.main()
