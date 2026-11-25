"""Protocol-4 inventory, source bootstrap and actual ZIP boundary regressions."""

import base64
import csv
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from build_config import BuildConfigError
from build_records import fileHash
from vision_train_modular_archive import compressPackage
from vision_train_modular_build import canonicalBytes
from vision_train_modular_build import copyBranding
from vision_train_modular_build import copyUltralytics
from vision_train_modular_build import dependencyRecipe
from vision_train_modular_build import loadProfile
from vision_train_modular_build import loadContract
from vision_train_modular_build import nativeDirectories
from vision_train_modular_build import pinnedSeeds
from vision_train_modular_build import prepareAssets
from vision_train_modular_build import PROFILE
from vision_train_modular_build import writeCanonical
from vision_train_modular_build import verifyPreparedCoreResource
from vision_train_module_inventory import buildDependencyLock
from vision_train_module_inventory import inventoryPayload
from vision_train_module_inventory import readDistributions
from vision_train_module_inventory import readProvenance
from vision_train_module_inventory import recordPath
from vision_train_module_inventory import resolveOwnership
from scripts.verify_vision_train_modular_product import coreInventory
from scripts.verify_vision_train_modular_product import verifyCoreUnchanged


ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location(
  'tested_modular_product_launcher', ROOT / 'scripts/modular_product_launcher.py')
launcher = importlib.util.module_from_spec(specification)
specification.loader.exec_module(launcher)


class ModularBuildTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.site = self.root / 'site-packages'
    self.site.mkdir()

  def distribution(self, name, files, *, version='1.0', requires=()):
    metadata = self.site / (name.replace('-', '_') + '-' + version + '.dist-info')
    metadata.mkdir()
    text = 'Metadata-Version: 2.1\nName: ' + name + '\nVersion: ' + version + '\n'
    text += ''.join('Requires-Dist: ' + item + '\n' for item in requires)
    payload = dict(files)
    payload[metadata.relative_to(self.site).as_posix() + '/METADATA'] = text.encode()
    rows = []
    for relative, data in payload.items():
      path = self.site / relative
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(data)
      digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
      rows.append([relative, 'sha256=' + digest, str(len(data))])
    record = metadata / 'RECORD'
    rows.append([record.relative_to(self.site).as_posix(), '', ''])
    with record.open('w', encoding='utf-8', newline='') as stream:
      csv.writer(stream).writerows(rows)
    return metadata

  def ownership(self, distributions, seeds, providers=None, source=None):
    return resolveOwnership(distributions, seeds, providers=providers or {},
                             sourceRequirements=source or {})

  def test_installed_records_and_pip_windows_alias_have_one_payload(self):
    metadata = self.distribution('example', {'example/__init__.py': b'VALUE=1\n'})
    record = metadata / 'RECORD'
    rows = list(csv.reader(record.read_text().splitlines()))
    rows[0][0] = rows[0][0].replace('/', '\\')
    rows.append(['example/__init__.py', '', ''])
    with record.open('w', newline='') as stream:
      csv.writer(stream).writerows(rows)
    distributions = readDistributions(self.site)
    self.assertEqual(distributions['example']['import_roots'], ['example'])
    ownership = self.ownership(distributions, {'core': ['example']})
    inventory = inventoryPayload(self.site, distributions, ownership,
                                 namespaceProviders={}, omittedPython=[])
    self.assertEqual(len(inventory['files']), 3)

  def test_conflicting_record_alias_is_rejected(self):
    metadata = self.distribution('example', {'example/__init__.py': b'VALUE=1\n'})
    with (metadata / 'RECORD').open('a') as stream:
      stream.write('example\\__init__.py,sha256=wrong,8\n')
    with self.assertRaisesRegex(BuildConfigError, 'Contradictory'):
      readDistributions(self.site)

  def test_unsafe_record_paths_fail_while_preparation_scripts_are_not_payload(self):
    self.assertIsNone(recordPath('../../Scripts/example.exe'))
    for text in ('/etc/passwd', 'C:/outside', 'package/../escape', 'package//x', 'package/./x'):
      with self.subTest(text=text), self.assertRaises(BuildConfigError):
        recordPath(text)

  def test_namespace_provider_keeps_metadata_and_only_selected_binary(self):
    self.distribution('opencv-python-headless', {'cv2/__init__.py': b'old',
                                                'opencv_python_headless.libs/unused.dll': b'old'})
    self.distribution('opencv-contrib-python-headless', {'cv2/__init__.py': b'new'})
    distributions = readDistributions(self.site)
    ownership = self.ownership(distributions, {
      'core': ['opencv-contrib-python-headless'],
      'feature.patchcore': ['opencv-python-headless']},
      {'opencv-python-headless': 'opencv-contrib-python-headless'})
    inventory = inventoryPayload(self.site, distributions, ownership,
      namespaceProviders={'cv2': 'opencv-contrib-python-headless'}, omittedPython=[])
    self.assertEqual(inventory['files']['cv2/__init__.py']['distributions'],
                     ['opencv-contrib-python-headless'])
    self.assertNotIn('opencv_python_headless.libs/unused.dll', inventory['files'])
    self.assertIn('opencv_python_headless-1.0.dist-info/METADATA', inventory['files'])
    self.assertEqual(ownership['distribution_owners']['opencv-python-headless'], 'core')

  def test_unreviewed_interpreter_and_changed_native_bytes_are_rejected(self):
    self.distribution('example', {'example/__init__.py': b'', 'example/python311.dll': b'dll'})
    distributions = readDistributions(self.site)
    ownership = self.ownership(distributions, {'runtime.example': ['example']})
    with self.assertRaisesRegex(BuildConfigError, 'Another Python'):
      inventoryPayload(self.site, distributions, ownership, namespaceProviders={}, omittedPython=[])

  def test_alias_metadata_cannot_hide_the_actual_provider_version(self):
    self.distribution('client', {'client.py': b''}, requires=['onnxruntime<2'])
    self.distribution('onnxruntime', {'onnxruntime/__init__.py': b'cpu'}, version='1.0')
    self.distribution('onnxruntime-gpu', {'onnxruntime/__init__.py': b'gpu'}, version='3.0')
    with self.assertRaisesRegex(BuildConfigError, 'provider versions differ'):
      self.ownership(readDistributions(self.site),
        {'runtime.ort': ['client', 'onnxruntime-gpu']}, {'onnxruntime': 'onnxruntime-gpu'})

  def test_payload_tampering_is_not_hidden_by_metadata(self):
    self.distribution('example', {'example/native.pyd': b'good'})
    distributions = readDistributions(self.site)
    (self.site / 'example/native.pyd').write_bytes(b'evil')
    ownership = self.ownership(distributions, {'runtime.example': ['example']})
    with self.assertRaisesRegex(BuildConfigError, 'digest differs'):
      inventoryPayload(self.site, distributions, ownership, namespaceProviders={}, omittedPython=[])

  def test_namespace_cannot_be_split_between_module_owners(self):
    self.distribution('part-a', {'namespace/part_a.py': b''})
    self.distribution('part-b', {'namespace/part_b.py': b''})
    with self.assertRaisesRegex(BuildConfigError, 'split across'):
      self.ownership(readDistributions(self.site), {'feature.a': ['part-a'], 'feature.b': ['part-b']})

  def test_selected_extra_closure_stays_with_core_without_optional_cycle(self):
    self.distribution('http-client', {'client/__init__.py': b''},
                      requires=['socks; extra == "socks"'])
    self.distribution('socks', {'socks.py': b''})
    self.distribution('feature', {'feature/__init__.py': b''}, requires=['http-client[socks]'])
    ownership = self.ownership(readDistributions(self.site),
                              {'core': ['http-client'], 'feature.example': ['feature']})
    self.assertEqual(ownership['distribution_owners']['socks'], 'core')
    self.assertEqual(ownership['requires']['feature.example'], [])

  def test_ort_shared_light_dependency_does_not_require_torch(self):
    self.distribution('torch', {'torch/__init__.py': b''}, requires=['sympy'])
    self.distribution('ort', {'ort/__init__.py': b''}, requires=['sympy'])
    self.distribution('sympy', {'sympy/__init__.py': b''})
    ownership = self.ownership(readDistributions(self.site),
                              {'core': [], 'runtime.torch': ['torch'], 'runtime.ort': ['ort']})
    self.assertEqual(ownership['distribution_owners']['sympy'], 'core')
    self.assertEqual(ownership['requires']['runtime.ort'], [])

  def test_vendor_torch_conflict_is_recorded_without_altering_requirement(self):
    self.distribution('torch', {'torch/__init__.py': b''}, version='2.10.0+cu128')
    requirement = 'torch>=1.8.0,<2.10'
    ownership = self.ownership(readDistributions(self.site),
      {'core': [], 'runtime.torch': ['torch'], 'feature.yolo': []},
      source={'feature.yolo': [requirement]})
    self.assertEqual(ownership['compatibility_findings'][0]['requirement'], requirement)
    self.assertEqual(ownership['compatibility_findings'][0]['status'], 'observed/unqualified')
    self.assertEqual(ownership['requires']['feature.yolo'], ['runtime.torch'])

  def test_ordinary_unsatisfied_dependency_is_rejected(self):
    self.distribution('a', {'a.py': b''}, requires=['b<2'])
    self.distribution('b', {'b.py': b''}, version='2.0')
    with self.assertRaisesRegex(BuildConfigError, 'violates dependency'):
      self.ownership(readDistributions(self.site), {'core': ['a']})

  def test_dependency_lock_excludes_machine_specific_installation_receipts(self):
    self.distribution('example', {'example.py': b''})
    distributions = readDistributions(self.site)
    ownership = self.ownership(distributions, {'core': ['example']})
    inventory = inventoryPayload(self.site, distributions, ownership,
                                 namespaceProviders={}, omittedPython=[])
    origin = {'example': {'version': '1.0', 'url': 'https://files.pythonhosted.org/example.whl',
                          'sha256': '1' * 64, 'report_sha256': '2' * 64}}
    first = buildDependencyLock(distributions, origin, ownership, inventory, inputs={})
    origin['example']['report_sha256'] = '3' * 64
    distributions['example']['record_sha256'] = '4' * 64
    second = buildDependencyLock(distributions, origin, ownership, inventory, inputs={})
    self.assertEqual(first, second)

  def test_provenance_requires_an_exact_archive_digest(self):
    report = self.root / 'report.json'
    report.write_text(json.dumps({'version': '1', 'install': [{'metadata': {
      'name': 'example', 'version': '1.0'}, 'download_info': {'url': 'https://example.invalid/a'}}]}))
    with self.assertRaisesRegex(BuildConfigError, 'no SHA256'):
      readProvenance([report])

  def test_complete_source_package_metadata_preserves_upstream_constraint(self):
    source = self.root / 'source'
    vendor = source / 'ultralytics'
    package = vendor / 'ultralytics'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('__version__ = "8.4.0"\n')
    (package / 'model.py').write_text('MODEL = "complete source"\n')
    project = ('[project]\nname="ultralytics"\ndescription="Source fixture"\n'
               'requires-python=">=3.8"\ndependencies=["torch<2.10"]\n')
    (vendor / 'pyproject.toml').write_text(project)
    (vendor / 'LICENSE').write_text('fixture license')
    (vendor / 'README.md').write_text('fixture readme')
    info = {'path': 'ultralytics', 'owner': 'feature.yolo', 'commit': 'a' * 40}
    result = copyUltralytics(source, self.root / 'modules', info)
    installed = self.root / 'modules/feature.yolo/payload/site-packages'
    self.assertEqual((installed / 'ultralytics/model.py').read_text(), 'MODEL = "complete source"\n')
    self.assertIn('Requires-Dist: torch<2.10', (installed / 'ultralytics-8.4.0.dist-info/METADATA').read_text())
    self.assertEqual((vendor / 'pyproject.toml').read_text(), project)
    self.assertEqual(result['requires_dist'], ['torch<2.10'])

  def makeCore(self):
    root = self.root / 'VisionWorkshop'
    (root / 'python').mkdir(parents=True)
    code = root / 'python/module_runtime.py'
    code.write_text('raise RuntimeError("must not execute before verification")\n')
    lock = root / 'dependency-lock.json'
    lock.write_text('{}')
    document = {'protocol_version': 4, 'python': {
      'version': '3.12.10', 'abi': 'cp312', 'platform': 'win_amd64'},
      'dependency_lock_sha256': fileHash(lock),
      'source_files': [{'path': 'python/module_runtime.py', 'size': code.stat().st_size,
                        'sha256': fileHash(code)}], 'native_dlls': []}
    embedded = canonicalBytes(document).decode()
    (root / 'core.json').write_bytes(embedded.encode())
    return root, document, embedded

  def test_stdlib_source_verification_runs_without_importing_the_manager(self):
    root, document, embedded = self.makeCore()
    self.assertEqual(launcher.verifyCore(root, embedded), document)
    (root / 'python/module_runtime.py').write_text('changed\n')
    with self.assertRaisesRegex(RuntimeError, 'size changed'):
      launcher.verifyCore(root, embedded)

  def test_unlisted_python_source_cannot_shadow_verified_core(self):
    root, _, embedded = self.makeCore()
    (root / 'python/unlisted.py').write_text('VALUE=1\n')
    with self.assertRaisesRegex(RuntimeError, 'Unexpected or missing'):
      launcher.verifyCore(root, embedded)

  def test_core_metadata_is_bound_to_the_frozen_entry(self):
    root, document, embedded = self.makeCore()
    document['dependency_lock_sha256'] = '0' * 64
    (root / 'core.json').write_bytes(canonicalBytes(document))
    with self.assertRaisesRegex(RuntimeError, 'does not match this executable'):
      launcher.verifyCore(root, embedded)

  def test_serialized_metadata_limit_uses_encoded_bytes_and_never_truncates(self):
    output = self.root / 'metadata/core.json'
    document = {'label': '中文'}
    encoded = canonicalBytes(document)
    with self.assertRaisesRegex(BuildConfigError, 'metadata exceeds'):
      writeCanonical(output, document, maximumBytes=len(encoded) - 1)
    self.assertFalse(output.exists())
    writeCanonical(output, document, maximumBytes=len(encoded))
    self.assertEqual(output.read_bytes(), encoded)

  def test_resource_preparation_does_not_modify_the_exact_source_checkout(self):
    source = self.root / 'source'
    cache = self.root / 'verified-cache'
    cache.mkdir()
    (cache / 'model.bin').write_bytes(b'dino')
    sources = {
      'static/models/tracked.bin': 'tracked',
      'anomaly_func/pretrained_weights.py':
        'def prepare_pretrained_weights(root):\n'
        '    (root / "static/models/cnn.bin").write_bytes(b"cnn")\n',
      'scripts/prepare_image_simplification_weights.py':
        'from pathlib import Path\nWEIGHT_RELATIVE_PATH="static/models/image/model.bin"\n'
        'def prepare(path, download=False):\n'
        '    target=Path(path)\n    target.parent.mkdir(parents=True)\n'
        '    target.write_bytes(b"image")\n',
      'anomaly_func/dinov2_resources.py':
        'from pathlib import Path\nREVISION="revision"\n'
        'def prepare_default():\n    return Path(' + repr(str(cache)) + ')\n'
        'def verify_default(path):\n    assert (path / "model.bin").read_bytes() == b"dino"\n',
      'project__func/image_simplification/pretrained_weights.py': '# fixed input\n',
    }
    for name, text in sources.items():
      path = source / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(text)
    before = {name: fileHash(source / name) for name in sources}
    profile, _ = loadProfile(PROFILE)
    profile['core_prepared_resources'] = []
    profilePath = self.root / 'profile.json'
    profilePath.write_text(json.dumps(profile))
    args = SimpleNamespace(source_root=source, assets_root=self.root / 'prepared',
                           output=self.root / 'resource-preparation.json', profile=profilePath)
    result = prepareAssets(args)
    self.assertEqual(before, {path.relative_to(source).as_posix(): fileHash(path)
                              for path in source.rglob('*') if path.is_file()})
    self.assertEqual({row['path'] for row in result['files']}, {
      'static/models/tracked.bin', 'static/models/cnn.bin', 'static/models/image/model.bin',
      'static/models/dinov2-small/revision/model.bin'})
    with self.assertRaisesRegex(BuildConfigError, 'isolated directory'):
      prepareAssets(SimpleNamespace(source_root=source, assets_root=source / 'dirty',
                                    output=args.output, profile=profilePath))

  def test_prepared_core_resource_requires_size_git_blob_and_sha256(self):
    path = self.root / 'font.fixture'
    data = b'explicit source validation fixture, not a real font'
    path.write_bytes(data)
    declared = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'git_blob_sha1': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}
    verifyPreparedCoreResource(path, declared)
    for field, changed in (('size', len(data) + 1), ('sha256', '0' * 64), ('git_blob_sha1', '0' * 40)):
      with self.subTest(field=field), self.assertRaisesRegex(BuildConfigError, 'differs'):
        verifyPreparedCoreResource(path, dict(declared, **{field: changed}))

  def test_core_runtime_inventory_checks_native_extensions_and_metadata(self):
    root, document, _ = self.makeCore()
    package = root / 'site-packages/example'
    package.mkdir(parents=True)
    extension = package / 'native.pyd'
    extension.write_bytes(b'valid native fixture')
    document['runtime_files'] = [*document['source_files'], {
      'path': 'site-packages/example/native.pyd', 'size': extension.stat().st_size,
      'sha256': fileHash(extension)}]
    embedded = canonicalBytes(document).decode()
    (root / 'core.json').write_bytes(embedded.encode())
    launcher.verifyCore(root, embedded)
    extension.write_bytes(b'other native fixture')
    with self.assertRaisesRegex(RuntimeError, 'integrity check failed'):
      launcher.verifyCore(root, embedded)

  def test_extra_core_runtime_file_is_rejected(self):
    root, document, _ = self.makeCore()
    document['runtime_files'] = document['source_files']
    extra = root / 'site-packages/requests.py'
    extra.parent.mkdir()
    extra.write_bytes(b'shadow')
    embedded = canonicalBytes(document).decode()
    (root / 'core.json').write_bytes(embedded.encode())
    with self.assertRaisesRegex(RuntimeError, 'Unexpected or missing Core runtime'):
      launcher.verifyCore(root, embedded)

  def test_product_lifecycle_inventory_excludes_only_root_module_state(self):
    root, _, _ = self.makeCore()
    internal = root / '_internal/native.dll'
    internal.parent.mkdir()
    internal.write_bytes(b'original native')
    before = coreInventory(root)
    for name in ('.module-state/registry.json', 'modules/runtime.ort/version/payload/file'):
      path = root / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(b'expected mutable module state')
    self.assertEqual(before, coreInventory(root))
    reports = self.root / 'reports'
    reports.mkdir()
    verifyCoreUnchanged(root, before, reports, 'after-install')
    internal.write_bytes(b'changed native!')
    with self.assertRaisesRegex(RuntimeError, 'Immutable Core changed'):
      verifyCoreUnchanged(root, before, reports, 'after-bad-write')
    failure = json.loads((reports / 'core-unchanged-after-bad-write.json').read_text())
    self.assertEqual(failure['changed'], ['_internal/native.dll'])
    internal.write_bytes(b'original native')
    (root / 'unexpected.py').write_bytes(b'extra file')
    with self.assertRaisesRegex(RuntimeError, 'Immutable Core changed'):
      verifyCoreUnchanged(root, before, reports, 'after-extra-file')

  @unittest.skipUnless(os.environ.get('VISIONWORKSHOP_MODULE_SOURCE'), 'requires exact application contract checkout')
  def test_actual_application_canonical_identity_matches_frozen_core_bytes(self):
    contract = loadContract(Path(os.environ['VISIONWORKSHOP_MODULE_SOURCE']))
    root, document, _ = self.makeCore()
    document.update(type='visionworkshop-core', module_api=1, version='0.0.0',
      entrypoint='VisionWorkshop.exe', build={'app_sha': 'a' * 40, 'packager_sha': 'b' * 40,
      'build_id': 'fixture'}, distributions={}, import_roots=['module_runtime'], catalog={},
      python_paths=['python'], dll_dirs=[], runtime_files=document['source_files'],
      fixture_label='中文身份')
    contract.validate_core(document)
    writeCanonical(root / 'core.json', document, encoder=contract.canonical_json)
    self.assertEqual(fileHash(root / 'core.json'), contract.manifest_digest(document))
    self.assertEqual(launcher.verifyCore(root, (root / 'core.json').read_text()), document)

  def test_top_level_native_extension_does_not_add_invalid_module_dll_directory(self):
    records = [{'path': 'site-packages/_native.cp312-win_amd64.pyd'},
               {'path': 'site-packages/other/native.dll'}]
    self.assertEqual(nativeDirectories(records, modulePayload=True), ['site-packages/other'])

  def test_archive_is_lzma_files_only_and_round_trips_unicode_and_empty_files(self):
    source = self.root / 'module'
    (source / 'payload/resources').mkdir(parents=True)
    (source / 'module.json').write_bytes(b'{}')
    (source / 'payload/resources/中文 空格.txt').write_bytes(b'abcdef' * 1000)
    (source / 'payload/resources/empty').write_bytes(b'')
    result = compressPackage(source, self.root / 'module.zip', dictionaryMiB=1)
    self.assertTrue(result['verified'])
    with zipfile.ZipFile(self.root / 'module.zip') as archive:
      self.assertTrue(all(not item.is_dir() and item.compress_type == zipfile.ZIP_LZMA
                          for item in archive.infolist()))
      self.assertEqual(archive.read('payload/resources/中文 空格.txt'), b'abcdef' * 1000)
      self.assertEqual(archive.read('payload/resources/empty'), b'')

  def test_oversized_archive_fails_the_actual_compressed_size_gate(self):
    source = self.root / 'module'
    source.mkdir()
    (source / 'module.json').write_bytes(b'{}')
    with self.assertRaisesRegex(BuildConfigError, 'per-file download limit'):
      compressPackage(source, self.root / 'too-large.zip', dictionaryMiB=1, maximumBytes=1)

  def test_profile_has_complete_seed_pins_without_heavy_core_or_osam_ort(self):
    profile, pins = loadProfile(PROFILE)
    seeds = pinnedSeeds(profile, pins)
    self.assertFalse({'torch', 'torchvision', 'onnxruntime-gpu', 'scipy', 'matplotlib'}
                     & {value.split('==')[0] for value in seeds['core']})
    self.assertNotIn('osam', profile['seeds']['runtime.ort'])
    self.assertIn('runtime.science', seeds)
    self.assertIn('resource.patchcore-dino', profile['resources'])

  def test_core_stages_the_existing_approved_branding_without_changing_source(self):
    profile, _ = loadProfile(PROFILE)
    source = self.root / 'source'
    source.mkdir()
    original = source / 'branding.json'
    original.write_bytes(b'original source branding')
    core = self.root / 'Core'
    result = copyBranding(source, core, profile)
    self.assertEqual(original.read_bytes(), b'original source branding')
    self.assertEqual((core / 'python/branding.json').read_bytes(), (ROOT / 'assets/branding.json').read_bytes())
    icon = core / 'python' / result['window_icon']
    self.assertEqual(fileHash(icon), result['window_icon_sha256'])
    self.assertEqual(icon.read_bytes(), Path(result['icon_source']).read_bytes())

  def test_core_code_and_labels_do_not_invalidate_shared_dependency_recipe(self):
    profile, _ = loadProfile(PROFILE)
    first = canonicalBytes(dependencyRecipe(profile))
    profile['vendor']['anylabeling']['commit'] = 'e' * 40
    profile['labels']['runtime.torch'] = 'Updated display text'
    profile['core_source_directories'].append('new_core_adapter')
    self.assertEqual(first, canonicalBytes(dependencyRecipe(profile)))
    profile['vendor']['ultralytics']['commit'] = 'f' * 40
    self.assertNotEqual(first, canonicalBytes(dependencyRecipe(profile)))


if __name__ == '__main__':
  unittest.main()
