"""Real small ZIPs bind a current Core to compatible original module builds."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build_config import BuildConfigError
from build_records import fileHash
from build_records import scanFiles
from vision_train_modular_archive import compressPackage
from vision_train_modular_build import loadContract
from vision_train_modular_index import INDEX_FILE
from vision_train_modular_index import verifyModuleIndex
from vision_train_modular_index import writeModuleIndex


@unittest.skipUnless(os.environ.get('VISIONWORKSHOP_MODULE_SOURCE'),
                     'requires the exact application contract checkout')
class ModuleIndexTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.archives = self.root / 'archives'
    self.archives.mkdir()
    self.path = self.archives / INDEX_FILE
    self.contract = loadContract(Path(os.environ['VISIONWORKSHOP_MODULE_SOURCE']))
    self.oldBuild = {'app_sha': 'a' * 40, 'packager_sha': 'b' * 40, 'build_id': 'old-123'}
    self.newBuild = {'app_sha': 'c' * 40, 'packager_sha': 'd' * 40, 'build_id': 'new-456'}
    self.lock = {'fixture': 'index-only ZIP test', 'compatibility_findings': [
      {'status': 'unqualified', 'description': 'Explicit source-fixture compatibility finding'}]}
    self.core = {
      'protocol_version': 4, 'module_api': 1, 'type': 'visionworkshop-core', 'version': '1.2.0',
      'entrypoint': 'VisionWorkshop.exe', 'build': self.newBuild,
      'python': {'version': '3.12.10', 'abi': 'cp312', 'platform': 'win_amd64'},
      'dependency_lock_sha256': self.contract.manifest_digest(self.lock),
      'distributions': {}, 'import_roots': [], 'python_paths': ['python'], 'dll_dirs': [],
      'preload_dlls': [], 'catalog': {
        'runtime.example': {'label': '共享示例库', 'kind': 'runtime', 'requires': [],
          'distributions': {'index-fixture': '1.0'}, 'import_roots': ['index_fixture']},
        'resource.example': {'label': '离线示例权重', 'kind': 'resource',
          'requires': ['runtime.example'], 'distributions': {}, 'import_roots': []},
      },
    }
    coreRoot = self.root / 'core'
    (coreRoot / 'python').mkdir(parents=True)
    (coreRoot / 'python/main.py').write_text('# Explicit fixture, never a product EXE\n')
    (coreRoot / 'VisionWorkshop.exe').write_bytes(b'Not a native executable; ZIP fixture only')
    (coreRoot / 'core.json').write_bytes(self.contract.canonical_json(self.core))
    (coreRoot / 'dependency-lock.json').write_bytes(self.contract.canonical_json(self.lock))
    coreArchive = compressPackage(coreRoot, self.archives / 'VisionWorkshop-Core-1.2.0.zip',
                                   prefix='VisionWorkshop', dictionaryMiB=1)
    self.roots, self.manifests = {}, {}
    for name, declaration in self.core['catalog'].items():
      root = self.root / name
      relative = ('site-packages/index_fixture/__init__.py' if name.startswith('runtime')
                   else 'resources/中文 空格/weights.bin')
      child = root / 'payload' / relative
      child.parent.mkdir(parents=True)
      child.write_bytes(b'original module bytes\x00\n')
      files = [{'path': path, **record} for path, record in scanFiles(root / 'payload').items()]
      manifest = {
        'protocol_version': 4, 'module_api': 1, 'type': 'visionworkshop-module',
        'module_id': name, 'version': '1.0.0', 'build': deepcopy(self.oldBuild),
        'python': self.core['python'], 'dependency_lock_sha256': self.core['dependency_lock_sha256'],
        'core_versions': {'min': '1.0.0', 'max_exclusive': '2.0.0'},
        **{key: declaration[key] for key in ('kind', 'requires', 'distributions', 'import_roots')},
        'python_paths': ['site-packages'] if name.startswith('runtime') else [], 'dll_dirs': [],
        'resources': {} if name.startswith('runtime') else {'static/models/example': 'resources'},
        'files': files, 'expanded_size': sum(item['size'] for item in files),
      }
      self.roots[name], self.manifests[name] = root, manifest
    self.summary = {'status': 'BUILT', 'core': deepcopy(self.core),
      'core_sha256': self.contract.manifest_digest(self.core), 'dependency_lock': deepcopy(self.lock),
      'core_archive': coreArchive, 'module_archives': [],
      'module_builds': {name: deepcopy(self.oldBuild) for name in self.manifests}}
    for name in self.manifests:
      self.rebuildModule(name)

  def rebuildModule(self, name, change=None):
    manifest = deepcopy(self.manifests[name])
    if change:
      change(manifest)
    root = self.roots[name]
    (root / 'module.json').write_bytes(self.contract.canonical_json(manifest))
    path = self.archives / (name + '-1.0.0.zip')
    path.unlink(missing_ok=True)
    package = compressPackage(root, path, dictionaryMiB=1)
    package.update(module_id=name, manifest_sha256=self.contract.manifest_digest(manifest))
    self.summary['module_archives'] = [item for item in self.summary['module_archives']
                                       if item['module_id'] != name] + [package]

  def write(self):
    self.summary['module_index'] = writeModuleIndex(self.path, self.summary, self.contract)
    return json.loads(self.path.read_bytes())

  def verify(self):
    return verifyModuleIndex(self.path, self.summary, self.contract)

  def test_core_admission_anchor_is_bound_to_its_core_manifest(self):
    root = self.root / 'core'
    state = root / '.core-update'
    state.mkdir()
    lock = state / 'launch.lock'
    marker = state / 'current-trial.json'
    for guarded, anchor, recovery, expected in (
        (False, b'', False, 'unguarded'), (True, None, False, 'empty startup lock'),
        (True, b'bad', False, 'empty startup lock'), (True, b'', True, 'empty startup lock'),
        (True, b'', False, None)):
      with self.subTest(guarded=guarded, anchor=anchor, recovery=recovery):
        core = deepcopy(self.core)
        if guarded:
          core['admission_bootloader_sha256'] = 'a' * 64
        (root / 'core.json').write_bytes(self.contract.canonical_json(core))
        lock.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        if anchor is not None:
          lock.write_bytes(anchor)
        if recovery:
          marker.write_bytes(b'{}')
        path = Path(self.summary['core_archive']['path'])
        path.unlink()
        self.summary['core_archive'] = compressPackage(root, path, prefix='VisionWorkshop', dictionaryMiB=1)
        self.summary.update(core=core, core_sha256=self.contract.manifest_digest(core))
        if expected:
          with self.assertRaisesRegex(BuildConfigError, expected):
            self.write()
        else:
          self.write()
          self.verify()

  def replaceIndex(self, document):
    data = self.contract.canonical_json(document)
    self.path.write_bytes(data)
    self.summary['module_index'].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

  def test_round_trip_keeps_new_core_and_original_module_builds_and_bytes(self):
    before = {path.name: path.read_bytes() for path in self.archives.glob('*.zip')}
    document = self.write()
    self.assertEqual(document['build'], self.newBuild)
    self.assertEqual(document['core']['manifest_sha256'], self.summary['core_sha256'])
    self.assertEqual(document['core']['version'], '1.2.0')
    self.assertEqual(document['modules'][0]['module_id'], 'resource.example')
    self.assertTrue(all(item['build'] == self.oldBuild for item in document['modules']))
    self.assertTrue(all(item['version'] == '1.0.0' for item in document['modules']))
    self.assertEqual(document['compatibility_findings'], self.lock['compatibility_findings'])
    self.assertEqual(document['qualification']['release'], 'NOT_QUALIFIED')
    self.assertEqual(document['qualification']['native_execution'], 'SEPARATE_REPORT')
    self.assertEqual(self.verify()['status'], 'PASS')
    self.assertEqual(self.path.read_bytes(), self.contract.canonical_json(document))
    self.assertEqual(before, {path.name: path.read_bytes() for path in self.archives.glob('*.zip')})
    self.assertNotIn('module-index.json', json.dumps(document))
    self.assertEqual(document['asset_count'], 3)
    self.assertEqual(document['total_archive_bytes'], sum(len(data) for data in before.values()))

  def test_asset_byte_corruption_is_rejected_independently(self):
    self.write()
    for path in self.archives.glob('*.zip'):
      data = path.read_bytes()
      with self.subTest(archive=path.name):
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        try:
          with self.assertRaisesRegex(BuildConfigError, 'size/SHA256'):
            self.verify()
        finally:
          path.write_bytes(data)

  def test_index_raw_bytes_and_canonical_format_are_bound(self):
    document = self.write()
    self.path.write_bytes(self.path.read_bytes() + b' ')
    with self.assertRaises(BuildConfigError):
      self.verify()
    noncanonical = json.dumps(document, indent=2).encode()
    self.path.write_bytes(noncanonical)
    self.summary['module_index'].update(bytes=len(noncanonical), sha256=fileHash(self.path))
    with self.assertRaisesRegex(BuildConfigError, 'canonical'):
      self.verify()

  def test_index_cannot_claim_different_compatibility_deps_or_builds(self):
    original = self.write()
    changes = {
      'new_module_build': lambda value: value['modules'][0].update(build=self.newBuild),
      'lock': lambda value: value.update(dependency_lock_sha256='e' * 64),
      'abi': lambda value: value['python'].update(abi='cp313'),
      'core': lambda value: value['core'].update(manifest_sha256='f' * 64),
      'range': lambda value: value['modules'][0]['core_versions'].update(min='1.3.0'),
      'deps': lambda value: value['modules'][0].update(requires=[]),
      'sha': lambda value: value['modules'][0]['archive'].update(sha256='f' * 64),
      'basename': lambda value: value['modules'][0]['archive'].update(name='../other.zip'),
      'missing': lambda value: value['modules'].pop(),
      'duplicate': lambda value: value['modules'].append(deepcopy(value['modules'][0])),
      'unknown': lambda value: value['modules'][0].update(module_id='resource.unknown'),
      'bool_schema': lambda value: value.update(schema_version=True),
      'self_hash': lambda value: value.update(index_sha256='a' * 64),
      'release': lambda value: value['qualification'].update(release='PASS'),
    }
    for name, change in changes.items():
      with self.subTest(field=name):
        value = deepcopy(original)
        change(value)
        self.replaceIndex(value)
        with self.assertRaisesRegex(BuildConfigError, 'actual Core/module ZIP set'):
          self.verify()

  def test_full_catalog_is_required_even_for_a_missing_unreferenced_resource(self):
    self.summary['module_archives'] = [item for item in self.summary['module_archives']
                                       if item['module_id'] != 'resource.example']
    with self.assertRaisesRegex(BuildConfigError, 'complete unique Core catalog'):
      self.write()
    self.assertFalse(self.path.exists())

  def test_duplicate_archive_id_and_original_build_substitution_are_rejected(self):
    packages = deepcopy(self.summary['module_archives'])
    self.summary['module_archives'].append(deepcopy(packages[0]))
    with self.assertRaisesRegex(BuildConfigError, 'complete unique Core catalog'):
      self.write()
    self.summary['module_archives'] = packages
    self.summary['module_builds']['resource.example'] = deepcopy(self.newBuild)
    with self.assertRaisesRegex(BuildConfigError, 'original archive identity'):
      self.write()

  def test_true_archive_abi_lock_range_and_dependency_mismatch_are_rejected(self):
    changes = {
      'abi': lambda value: value['python'].update(abi='cp313'),
      'lock': lambda value: value.update(dependency_lock_sha256='f' * 64),
      'range': lambda value: value['core_versions'].update(min='1.3.0'),
      'deps': lambda value: value.update(requires=[]),
    }
    for name, change in changes.items():
      with self.subTest(field=name):
        self.rebuildModule('resource.example', change)
        with self.assertRaises(self.contract.ModuleError):
          self.write()
        self.assertFalse(self.path.exists())

  def test_archive_basenames_and_locations_cannot_alias_or_escape(self):
    package = self.summary['module_archives'][0]
    original = deepcopy(package)
    package.update(self.summary['core_archive'])
    with self.assertRaisesRegex(BuildConfigError, 'basenames collide'):
      self.write()
    package.clear()
    package.update(original)
    source = Path(package['path'])
    external = self.root / source.name
    external.write_bytes(source.read_bytes())
    package['path'] = str(external)
    with self.assertRaisesRegex(BuildConfigError, 'directly beside'):
      self.write()

  def test_archive_bounds_reject_bool_and_oversize_before_file_read(self):
    package = self.summary['core_archive']
    original = deepcopy(package)
    for field, value in [('bytes', True), ('bytes', 0),
                          ('bytes', self.contract.MAX_ARCHIVE_BYTES + 1),
                          ('file_count', True), ('expanded_bytes', 0)]:
      with self.subTest(field=field, value=value):
        package.clear()
        package.update(original)
        package[field] = value
        with patch('vision_train_modular_index.fileHash') as read, \
             self.assertRaisesRegex(BuildConfigError, 'archive bound'):
          self.write()
        read.assert_not_called()

  def test_index_record_bounds_and_schema_do_not_accept_booleans(self):
    self.write()
    original = deepcopy(self.summary['module_index'])
    for field in ('bytes', 'schema_version', 'asset_count'):
      with self.subTest(field=field):
        self.summary['module_index'] = dict(original, **{field: True})
        with self.assertRaises(BuildConfigError):
          self.verify()

  def test_index_metadata_limit_fails_before_creating_an_output(self):
    bound = max(len(self.contract.canonical_json(item)) for item in
                 [self.core, self.lock, *self.manifests.values()]) + 1
    with patch.object(self.contract, 'MAX_METADATA', bound), \
         self.assertRaisesRegex(BuildConfigError, 'index exceeds the metadata bound'):
      self.write()
    self.assertFalse(self.path.exists())

  def test_core_manifest_digest_is_not_the_whole_core_zip_digest(self):
    self.summary['core_sha256'] = self.summary['core_archive']['sha256']
    with self.assertRaisesRegex(BuildConfigError, 'current build identity'):
      self.write()


if __name__ == '__main__':
  unittest.main()
