"""Bind a downloadable module index to verified ZIPs without changing their bytes."""

import hashlib
from pathlib import Path
import zipfile

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from vision_train_modular_reuse import boundedLzmaMember


INDEX_FILE = 'module-index.json'
INDEX_SCHEMA = 1
ARCHIVE_FIELDS = ('bytes', 'sha256', 'compression', 'file_count', 'expanded_bytes',
                  'compressed_payload_bytes')
MODULE_FIELDS = ('module_id', 'version', 'kind', 'core_versions', 'python',
                 'dependency_lock_sha256', 'requires', 'distributions', 'import_roots',
                 'resources', 'build')


def verifyArchiveBytes(path: Path, descriptor: dict) -> None:
  if (not path.is_file() or path.stat().st_size != descriptor['bytes']
      or fileHash(path) != descriptor['sha256']):
    raise BuildConfigError('An indexed ZIP differs from its verified size/SHA256: ' + path.name)


def archiveDescriptor(record: dict, directory: Path, contract) -> tuple[Path, dict]:
  if not isinstance(record, dict) or record.get('verified') is not True:
    raise BuildConfigError('The module index requires a verified archive record')
  if record.get('compression') != 'zip/lzma':
    raise BuildConfigError('The module index requires the actual ZIP/LZMA format')
  for field, maximum in (('bytes', contract.MAX_ARCHIVE_BYTES),
                          ('file_count', contract.MAX_MODULE_FILES + 1),
                          ('expanded_bytes', contract.MAX_MODULE_BYTES + contract.MAX_METADATA),
                          ('compressed_payload_bytes', contract.MAX_ARCHIVE_BYTES)):
    if type(record.get(field)) is not int or not 0 < record[field] <= maximum:
      raise BuildConfigError('Invalid indexed archive bound: ' + field)
  contract.sha256(record.get('sha256'))
  if not isinstance(record.get('path'), str):
    raise BuildConfigError('The indexed archive must identify its actual file')
  path = Path(record['path'])
  rejectLinks(path)
  if path.resolve().parent != directory.resolve():
    raise BuildConfigError('Every indexed ZIP must be directly beside the module index')
  contract.relative_path(path.name)
  if '/' in path.name or '\\' in path.name or not path.name.endswith('.zip'):
    raise BuildConfigError('Indexed assets require a safe ZIP basename')
  verifyArchiveBytes(path, record)
  return path, {'name': path.name, **{key: record[key] for key in ARCHIVE_FIELDS}}


def readMetadata(archive: zipfile.ZipFile, name: str, contract) -> tuple[dict, bytes]:
  member = archive.getinfo(name)
  if not 0 < member.file_size <= contract.MAX_METADATA:
    raise BuildConfigError('Indexed ZIP metadata exceeds the application bound: ' + name)
  boundedLzmaMember(archive, member)
  with archive.open(member) as stream:
    data = stream.read(contract.MAX_METADATA + 1)
  value = contract.parse_json(data, maximum=contract.MAX_METADATA)
  if not isinstance(value, dict) or contract.canonical_json(value) != data:
    raise BuildConfigError('Indexed ZIP metadata must retain its original canonical bytes: ' + name)
  return value, data


def validateMembers(archive: zipfile.ZipFile, descriptor: dict, contract,
                    *, core: bool = False) -> dict:
  members = archive.infolist()
  if (len(members) != descriptor['file_count']
      or sum(item.file_size for item in members) != descriptor['expanded_bytes']
      or sum(item.compress_size for item in members) != descriptor['compressed_payload_bytes']):
    raise BuildConfigError('Indexed ZIP member statistics differ from its verified record')
  names = [item.filename for item in members]
  if len(names) != len(set(names)):
    raise BuildConfigError('Indexed ZIP has duplicate members')
  contract.validate_path_set(names)
  for member in members:
    if core and not member.filename.startswith('VisionWorkshop/'):
      raise BuildConfigError('Indexed Core ZIP contains a file outside its product prefix')
    boundedLzmaMember(archive, member)
  return dict(zip(names, members))


def buildIndexDocument(summary: dict, directory: Path, contract) -> dict:
  corePath, coreArchive = archiveDescriptor(summary['core_archive'], directory, contract)
  with zipfile.ZipFile(corePath) as archive:
    members = validateMembers(archive, coreArchive, contract, core=True)
    for name in ('VisionWorkshop/' + contract.CORE_FILE, 'VisionWorkshop/' + contract.LOCK_FILE):
      if name not in members:
        raise BuildConfigError('Indexed Core ZIP is missing bound metadata: ' + name)
    core, coreBytes = readMetadata(archive, 'VisionWorkshop/' + contract.CORE_FILE, contract)
    lock, lockBytes = readMetadata(archive, 'VisionWorkshop/' + contract.LOCK_FILE, contract)
  verifyArchiveBytes(corePath, coreArchive)
  contract.validate_core(core)
  coreDigest = hashlib.sha256(coreBytes).hexdigest()
  if (core != summary.get('core') or coreDigest != summary.get('core_sha256')
      or hashlib.sha256(lockBytes).hexdigest() != core['dependency_lock_sha256']
      or lock != summary.get('dependency_lock')):
    raise BuildConfigError('Indexed Core/lock bytes differ from the current build identity')
  packages = summary.get('module_archives')
  if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages):
    raise BuildConfigError('The module index requires the complete module archive list')
  ids = [item.get('module_id') for item in packages]
  if (any(not isinstance(name, str) for name in ids) or len(ids) != len(set(ids))
      or set(ids) != set(core['catalog'])):
    raise BuildConfigError('The module index must contain the complete unique Core catalog')
  builds = summary.get('module_builds')
  if not isinstance(builds, dict) or set(builds) != set(ids):
    raise BuildConfigError('The module index requires every original module build identity')
  manifests, archives = {}, {}
  names = {coreArchive['name'].casefold()}
  for package in packages:
    path, descriptor = archiveDescriptor(package, directory, contract)
    folded = descriptor['name'].casefold()
    if folded in names:
      raise BuildConfigError('Indexed asset basenames collide on Windows')
    names.add(folded)
    with zipfile.ZipFile(path) as archive:
      members = validateMembers(archive, descriptor, contract)
      if contract.MANIFEST_FILE not in members:
        raise BuildConfigError('An indexed module ZIP is missing its manifest')
      manifest, data = readMetadata(archive, contract.MANIFEST_FILE, contract)
      contract.validate_manifest(manifest, core)
      name = package['module_id']
      if (manifest['module_id'] != name or manifest['build'] != builds[name]
          or hashlib.sha256(data).hexdigest() != package.get('manifest_sha256')):
        raise BuildConfigError('Indexed module manifest/build differs from its original archive identity')
      expected = {'payload/' + item['path']: item['size'] for item in manifest['files']}
      expected[contract.MANIFEST_FILE] = len(data)
      if (set(members) != set(expected)
          or any(member.file_size != expected[name] for name, member in members.items())):
        raise BuildConfigError('Indexed module ZIP has missing, extra or wrong-sized payload files')
    verifyArchiveBytes(path, descriptor)
    manifests[name], archives[name] = manifest, descriptor
  contract.validate_module_set(core, manifests)
  findings = lock.get('compatibility_findings', [])
  if not isinstance(findings, list):
    raise BuildConfigError('The locked compatibility findings must be a list')
  moduleEntries = []
  for name in sorted(manifests):
    manifest = manifests[name]
    moduleEntries.append({**{key: manifest[key] for key in MODULE_FIELDS},
      'label': core['catalog'][name]['label'], 'manifest_sha256': contract.manifest_digest(manifest),
      'archive': archives[name]})
  return {
    'type': 'visionworkshop-module-index', 'schema_version': INDEX_SCHEMA,
    'protocol_version': core['protocol_version'], 'module_api': core['module_api'],
    'build': core['build'], 'python': core['python'],
    'dependency_lock_sha256': core['dependency_lock_sha256'],
    'core': {'version': core['version'], 'manifest_sha256': coreDigest, 'archive': coreArchive},
    'modules': moduleEntries, 'asset_count': len(moduleEntries) + 1,
    'total_archive_bytes': coreArchive['bytes'] + sum(item['bytes'] for item in archives.values()),
    'compatibility_findings': findings,
    'qualification': {'release': 'NOT_QUALIFIED', 'native_execution': 'SEPARATE_REPORT',
      'scope': 'Archive identities and compatibility only; reused module builds remain original'},
  }


def writeModuleIndex(path: Path, summary: dict, contract) -> dict:
  rejectLinks(path)
  document = buildIndexDocument(summary, path.parent, contract)
  data = contract.canonical_json(document)
  if not 0 < len(data) <= contract.MAX_METADATA:
    raise BuildConfigError('The canonical module index exceeds the metadata bound')
  with path.open('xb') as stream:
    stream.write(data)
  digest = hashlib.sha256(data).hexdigest()
  if path.stat().st_size != len(data) or fileHash(path) != digest:
    raise BuildConfigError('The written module index changed during verification')
  return {'path': str(path), 'bytes': len(data), 'sha256': digest,
          'schema_version': INDEX_SCHEMA, 'asset_count': document['asset_count'], 'verified': True}


def verifyModuleIndex(path: Path, summary: dict, contract) -> dict:
  record = summary.get('module_index', {})
  rejectLinks(path)
  if (not isinstance(record, dict) or record.get('verified') is not True
      or type(record.get('schema_version')) is not int or record['schema_version'] != INDEX_SCHEMA
      or type(record.get('bytes')) is not int or not 0 < record['bytes'] <= contract.MAX_METADATA
      or not path.is_file() or path.stat().st_size != record['bytes']):
    raise BuildConfigError('The module index is absent or exceeds its exact metadata bound')
  contract.sha256(record.get('sha256'))
  data = path.read_bytes()
  if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
    raise BuildConfigError('The module index differs from the current build size/SHA256')
  document = contract.parse_json(data, maximum=contract.MAX_METADATA)
  if not isinstance(document, dict) or contract.canonical_json(document) != data:
    raise BuildConfigError('The module index must retain its canonical bytes')
  expected = buildIndexDocument(summary, path.parent, contract)
  if (data != contract.canonical_json(expected) or type(record.get('asset_count')) is not int
      or record['asset_count'] != expected['asset_count']):
    raise BuildConfigError('The module index differs from the actual Core/module ZIP set')
  return {'status': 'PASS', 'path': str(path), 'bytes': len(data), 'sha256': record['sha256'],
          'asset_count': document['asset_count'], 'core_sha256': summary['core_sha256'],
          'build': document['build'],
          'scope': 'Index and complete ZIP size/SHA256, metadata and declared member inventory'}
