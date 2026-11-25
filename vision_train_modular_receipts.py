"""Select original module payloads without rewriting either installation's RECORD."""

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import zipfile

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from build_records import scanFiles
from vision_train_module_inventory import recordPath
from vision_train_modular_reuse import boundedLzmaMember
from vision_train_modular_reuse import validateReuseCore


ENTRY_RECEIPT = re.compile(r'\.\./\.\./Scripts/[A-Za-z0-9_.-]+\.exe')
RECORD_HASH = re.compile(r'sha256=[A-Za-z0-9_-]{43}')


def recordProjection(data: bytes) -> tuple[list[list[str]], dict, list[str]]:
  rows = list(csv.reader(data.decode('utf-8').splitlines(), strict=True))
  retained, omitted = {}, []
  if len(rows) != len(data.splitlines(keepends=True)):
    raise BuildConfigError('Receipt qualification does not accept multiline CSV fields')
  for row in rows:
    if len(row) != 3:
      raise BuildConfigError('Malformed original installed RECORD')
    path = recordPath(row[0])
    if path is None or '__pycache__' in PurePosixPath(path).parts or path.endswith('.pyc'):
      omitted.append(row[0])
      continue
    previous = retained.get(path)
    if previous and previous[1:] != row[1:] and all(previous[1:]) and all(row[1:]):
      raise BuildConfigError('Contradictory RECORD alias in source receipt')
    if not previous or row[1]:
      retained[path] = row
  return rows, retained, omitted


def qualifyReceiptRows(original: bytes, fresh: bytes, sourceDistribution: dict,
                       freshDistribution: dict) -> list[dict]:
  sourceRows, sourceRuntime, sourceOmitted = recordProjection(original)
  freshRows, freshRuntime, freshOmitted = recordProjection(fresh)
  if (sourceRuntime != sourceDistribution['records']
      or freshRuntime != freshDistribution['records'] or sourceRuntime != freshRuntime
      or sourceOmitted != sourceDistribution['preparation_only_files']
      or freshOmitted != freshDistribution['preparation_only_files']
      or sourceOmitted != freshOmitted or len(sourceRows) != len(freshRows)):
    raise BuildConfigError('Original and fresh RECORD rows do not match their source inventories')
  sourceLines, freshLines = original.splitlines(keepends=True), fresh.splitlines(keepends=True)
  changes = []
  for before, after, oldLine, newLine in zip(sourceRows, freshRows, sourceLines, freshLines):
    if oldLine == newLine:
      continue
    name = before[0]
    if (after[0] != name or before[2] != after[2]
        or name not in sourceOmitted or not ENTRY_RECEIPT.fullmatch(name)
        or not RECORD_HASH.fullmatch(before[1]) or not RECORD_HASH.fullmatch(after[1])
        or before[1] == after[1] or not re.fullmatch(r'[1-9][0-9]*', before[2])):
      raise BuildConfigError('Unqualified installed RECORD byte difference: ' + name)
    ending = b'\r\n' if oldLine.endswith(b'\r\n') else b'\n' if oldLine.endswith(b'\n') else b''
    if (oldLine != ','.join(before).encode('utf-8') + ending
        or newLine != ','.join(after).encode('utf-8') + ending):
      raise BuildConfigError('RECORD changed CSV formatting or fields outside the generated EXE hash')
    changes.append({'path': name, 'size': int(before[2]), 'source_hash': before[1],
                    'fresh_hash': after[1], 'distributed': False,
                    'classification': 'already excluded generated Windows console entry receipt'})
  if not changes:
    raise BuildConfigError('Different RECORD bytes have no qualified generated-entry hash change')
  return changes


def qualifyInstalledReceipt(source: dict, moduleId: str, relative: str, oldBytes: bytes,
                            freshBytes: bytes, originalFile: dict, freshFile: dict,
                            distributions: dict, provenance: dict, evidence: Path) -> dict:
  sourceDistributions = source['installed']['distributions']
  names = [name for name, value in sourceDistributions.items()
           if relative == 'site-packages/' + value['metadata_path'] + '/RECORD']
  catalog = source['summary']['core']['catalog'][moduleId]['distributions']
  if len(names) != 1 or names[0] not in catalog or names[0] not in distributions:
    raise BuildConfigError('Changed RECORD has no exact original distribution owner: ' + relative)
  name = names[0]
  old, new = sourceDistributions[name], distributions[name]
  if ({key: value for key, value in old.items() if key != 'record_sha256'}
      != {key: value for key, value in new.items() if key != 'record_sha256'}
      or old['version'] != catalog[name]):
    raise BuildConfigError('Source distribution or runtime RECORD projection changed: ' + name)
  oldOrigin = source['installed']['provenance'].get(name, {})
  newOrigin = provenance.get(name, {})
  if (any(not oldOrigin.get(key) or oldOrigin[key] != newOrigin.get(key)
          for key in ('version', 'url', 'sha256')) or oldOrigin['version'] != old['version']):
    raise BuildConfigError('Changed RECORD does not come from the same exact wheel: ' + name)
  if (len(oldBytes) != originalFile['size'] or len(freshBytes) != freshFile['size']
      or originalFile['size'] != freshFile['size']
      or hashlib.sha256(oldBytes).hexdigest() != originalFile['sha256']
      or hashlib.sha256(freshBytes).hexdigest() != freshFile['sha256']
      or old['record_sha256'] != originalFile['sha256']
      or new['record_sha256'] != freshFile['sha256']):
    raise BuildConfigError('RECORD original bytes are not bound to both manifests/inventories: ' + name)
  evidence.mkdir(parents=True, exist_ok=True)
  originalReport = evidence / (name + '.source.RECORD')
  freshReport = evidence / (name + '.fresh.RECORD')
  originalReport.write_bytes(oldBytes)
  freshReport.write_bytes(freshBytes)
  changes = qualifyReceiptRows(oldBytes, freshBytes, old, new)
  return {'path': relative, 'distribution': name, 'version': old['version'],
          'source_record': dict(originalFile, evidence_file=originalReport.name),
          'fresh_record': dict(freshFile, evidence_file=freshReport.name),
          'wheel': {key: oldOrigin[key] for key in ('version', 'url', 'sha256')},
          'runtime_rows_identical': True, 'preparation_only_lists_identical': True,
          'changed_generated_entry_receipts': changes}


def selectSourceStaging(source: dict, moduleId: str, freshPayload: Path, expected: dict,
                        core: dict, destination: Path, contract, distributions: dict,
                        provenance: dict, evidence: Path) -> tuple[dict, dict]:
  validateReuseCore(source, core)
  item = source['receipt']['modules'][moduleId]
  archivePath = source['root'] / item['archive_path']
  rejectLinks(archivePath)
  if (archivePath.stat().st_size != item['bytes'] or not 0 < item['bytes'] <= contract.MAX_ARCHIVE_BYTES
      or fileHash(archivePath) != item['sha256']):
    raise BuildConfigError('Source staging requires the original verified module ZIP')
  freshFiles = scanFiles(freshPayload)
  declared = {row['path']: {key: row[key] for key in ('size', 'sha256')} for row in expected['files']}
  if freshFiles != declared:
    raise BuildConfigError('Fresh staging no longer matches its independently generated inventory')
  if destination.exists():
    raise BuildConfigError('Original module staging must use a separate new directory')
  if (destination.resolve().is_relative_to(freshPayload.resolve())
      or freshPayload.resolve().is_relative_to(destination.resolve())):
    raise BuildConfigError('Original and fresh module staging must remain separate')
  receipts = []
  with zipfile.ZipFile(archivePath) as archive:
    members = archive.infolist()
    names = [entry.filename for entry in members]
    if len(names) != len(set(names)) or names.count('module.json') != 1:
      raise BuildConfigError('Original source staging archive has duplicate or missing manifest entries')
    manifestInfo = archive.getinfo('module.json')
    if not 0 < manifestInfo.file_size <= contract.MAX_METADATA:
      raise BuildConfigError('Original source staging manifest exceeds its metadata bound')
    boundedLzmaMember(archive, manifestInfo)
    originalBytes = archive.read(manifestInfo)
    original = json.loads(originalBytes)
    if (contract.canonical_json(original) != originalBytes
        or contract.manifest_digest(original) != item['manifest_sha256']):
      raise BuildConfigError('Original staging manifest no longer has its exact source identity')
    contract.validate_manifest(original, core)
    sourceBuild = source['summary'].get('module_builds', {}).get(
      moduleId, source['summary']['core']['build'])
    if original['build'] != sourceBuild:
      raise BuildConfigError('Original staging manifest does not belong to its recorded source build')
    ignored = {'build', 'files', 'expanded_size'}
    if ({key: value for key, value in original.items() if key not in ignored}
        != {key: value for key, value in expected.items() if key not in ignored}):
      raise BuildConfigError('Original module metadata differs from the current candidate recipe')
    originalFiles = {row['path']: {key: row[key] for key in ('size', 'sha256')}
                     for row in original['files']}
    if (set(originalFiles) != set(freshFiles)
        or set(names) != {'module.json', *('payload/' + name for name in originalFiles)}):
      raise BuildConfigError('Original and fresh module payload path sets differ')
    expanded = len(originalBytes)
    for entry in members:
      boundedLzmaMember(archive, entry)
      if entry.filename == 'module.json':
        continue
      record = originalFiles[entry.filename.removeprefix('payload/')]
      if entry.file_size != record['size']:
        raise BuildConfigError('Source payload member size differs from the original manifest')
      expanded += entry.file_size
    package = source['packages'][moduleId]
    if (expanded != original['expanded_size'] + len(originalBytes)
        or expanded > contract.MAX_MODULE_BYTES + contract.MAX_METADATA
        or len(members) != package['file_count'] or expanded != package['expanded_bytes']
        or sum(entry.compress_size for entry in members) != package['compressed_payload_bytes']):
      raise BuildConfigError('Source staging archive exceeds or differs from its complete size inventory')
    for relative, record in originalFiles.items():
      if record == freshFiles[relative]:
        continue
      if (not relative.endswith('.dist-info/RECORD') or record['size'] > contract.MAX_METADATA
          or freshFiles[relative]['size'] != record['size']):
        raise BuildConfigError('Non-receipt module payload changed: ' + moduleId + '/' + relative)
      info = archive.getinfo('payload/' + relative)
      boundedLzmaMember(archive, info)
      if info.file_size != record['size']:
        raise BuildConfigError('Source RECORD size differs from its immutable manifest')
      receipts.append(qualifyInstalledReceipt(source, moduleId, relative, archive.read(info),
        (freshPayload / relative).read_bytes(), record, freshFiles[relative],
        distributions, provenance, evidence))
    destination.mkdir(parents=True)
    for entry in members:
      boundedLzmaMember(archive, entry)
      if entry.filename == 'module.json':
        continue
      relative = entry.filename.removeprefix('payload/')
      record = originalFiles[relative]
      if entry.file_size != record['size']:
        raise BuildConfigError('Source payload member size differs from the original manifest')
      path = destination / relative
      path.parent.mkdir(parents=True, exist_ok=True)
      digest = hashlib.sha256()
      with archive.open(entry) as reader, path.open('xb') as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
          digest.update(chunk)
          writer.write(chunk)
      if digest.hexdigest() != record['sha256']:
        raise BuildConfigError('Original source staging member bytes changed: ' + relative)
  if (scanFiles(destination) != originalFiles or scanFiles(freshPayload) != freshFiles
      or fileHash(archivePath) != item['sha256']):
    raise BuildConfigError('Source artifact, original staging or fresh staging changed during qualification')
  selected = deepcopy(expected)
  selected['files'] = deepcopy(original['files'])
  selected['expanded_size'] = original['expanded_size']
  report = {'status': 'PASS', 'module_id': moduleId,
            'staging_origin': 'immutable original module archive', 'source_build': original['build'],
            'source_manifest_sha256': item['manifest_sha256'], 'source_archive_sha256': item['sha256'],
            'fresh_staging_unchanged': True, 'fresh_payload_identical': not receipts,
            'non_record_payload_identical': True, 'file_count': len(originalFiles),
            'original_install_receipts_retained': receipts,
            'scope': 'Original module retains its own RECORD bytes; fresh installation receipts are not rewritten'}
  return selected, report
