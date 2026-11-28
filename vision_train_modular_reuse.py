"""Reuse completed candidate ZIP bytes only after checking their complete payload."""

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import zipfile
from pathlib import Path
from pathlib import PureWindowsPath
from urllib.request import Request
from urllib.request import urlopen

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from build_records import scanFiles


REPOSITORY = 'jsdfhasuh/python_build_scripts'
API = 'https://api.github.com/repos/' + REPOSITORY
SUMMARY_MEMBER = 'modular-candidate/reports/modular-build-summary.json'
PRODUCT_MEMBER = 'modular-acceptance/reports/modular-product-summary.json'
INVENTORY_MEMBER = 'modular-candidate/reports/installed-distributions.json'
MAX_MODULE_ARCHIVE_BYTES = 2 * 1024**3 - 1
MAX_MODULE_ARTIFACT_BYTES = MAX_MODULE_ARCHIVE_BYTES + 1024**2
MAX_EVIDENCE_ARTIFACT_BYTES = 128 * 1024**2


def writeJson(path: Path, value: dict) -> None:
  path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def readJson(path: Path, *, maximumBytes: int = 32 * 1024**2) -> dict:
  rejectLinks(path)
  if not path.is_file() or not 0 < path.stat().st_size <= maximumBytes:
    raise BuildConfigError('Reuse metadata is missing or too large: ' + path.name)
  value = json.loads(path.read_bytes())
  if not isinstance(value, dict):
    raise BuildConfigError('Reuse metadata must be an object: ' + path.name)
  return value


def sourceRun(run: dict, runId: int, attempt: int) -> dict:
  if (run.get('id') != runId or run.get('status') != 'completed'
      or run.get('run_attempt') != attempt
      or not re.fullmatch(r'[a-f0-9]{40}', run.get('head_sha', ''))
      or run.get('repository', {}).get('full_name') != REPOSITORY):
    raise BuildConfigError('Reuse requires the exact completed run and attempt in this repository')
  return {key: run.get(key) for key in
          ('id', 'run_attempt', 'status', 'conclusion', 'head_sha', 'html_url')}


def selectArtifact(artifacts: list[dict], name: str, run: dict) -> dict:
  matches = [item for item in artifacts if item.get('name') == name]
  if len(matches) != 1:
    raise BuildConfigError('Reuse artifact is absent or ambiguous: ' + name)
  item = matches[0]
  source = item.get('workflow_run', {})
  if (item.get('expired') is not False or type(item.get('id')) is not int
      or type(item.get('size_in_bytes')) is not int or item['size_in_bytes'] <= 0
      or not re.fullmatch(r'sha256:[a-f0-9]{64}', item.get('digest', ''))
      or source.get('id') != run['id'] or source.get('head_sha') != run['head_sha']):
    raise BuildConfigError('Reuse artifact provenance or digest is incomplete: ' + name)
  return {key: item[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run', 'expired')}


def apiRequest(path: str) -> Request:
  token = os.environ.get('GH_TOKEN')
  if not token:
    raise BuildConfigError('The artifact downloader requires its scoped GitHub Actions read token')
  request = Request(API + path, headers={
    'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'VisionWorkshop-candidate-reuse'})
  # Redirected artifact downloads must not forward the API credential to storage.
  request.add_unredirected_header('Authorization', 'Bearer ' + token)
  return request


def apiJson(path: str) -> dict:
  with urlopen(apiRequest(path), timeout=120) as stream:
    data = stream.read(16 * 1024**2 + 1)
  if len(data) > 16 * 1024**2:
    raise BuildConfigError('GitHub source metadata exceeded its bound')
  return json.loads(data)


def downloadArtifact(artifact: dict, destination: Path, *, maximumBytes: int) -> None:
  if (type(artifact.get('size_in_bytes')) is not int
      or not 0 < artifact['size_in_bytes'] <= maximumBytes):
    raise BuildConfigError('Source artifact exceeds its preparation download bound')
  digest, total = hashlib.sha256(), 0
  with urlopen(apiRequest('/actions/artifacts/' + str(artifact['id']) + '/zip'), timeout=120) as reader, \
       destination.open('xb') as writer:
    for chunk in iter(lambda: reader.read(1024 * 1024), b''):
      total += len(chunk)
      if total > artifact['size_in_bytes']:
        raise BuildConfigError('Artifact download exceeded its declared size')
      digest.update(chunk)
      writer.write(chunk)
  if total != artifact['size_in_bytes'] or 'sha256:' + digest.hexdigest() != artifact['digest']:
    raise BuildConfigError('Artifact download does not match its exact API size/SHA256')


def readEvidenceMember(archive: zipfile.ZipFile, name: str, *, optional: bool = False) -> bytes | None:
  matches = [item for item in archive.infolist() if item.filename == name]
  if not matches and optional:
    return None
  if len(matches) != 1 or matches[0].is_dir() or not 0 < matches[0].file_size <= 32 * 1024**2:
    raise BuildConfigError('Source evidence has an invalid or missing report: ' + name)
  return archive.read(matches[0])


def prepareReuse(runId: int, attempt: int, output: Path) -> dict:
  if output.exists():
    raise BuildConfigError('Use a new directory for reusable candidate artifacts')
  output.mkdir(parents=True)
  run = sourceRun(apiJson('/actions/runs/' + str(runId)), runId, attempt)
  artifacts = []
  for page in range(1, 11):
    data = apiJson('/actions/runs/' + str(runId) + '/artifacts?per_page=100&page=' + str(page))
    artifacts.extend(data['artifacts'])
    if len(artifacts) >= data['total_count']:
      break
  else:
    raise BuildConfigError('Source run has too many artifacts to select without ambiguity')
  suffix = str(runId) + '-' + str(attempt)
  evidence = selectArtifact(artifacts, 'visionworkshop-modular-evidence-' + suffix, run)
  temporary = output / 'source-evidence.zip'
  downloadArtifact(evidence, temporary, maximumBytes=MAX_EVIDENCE_ARTIFACT_BYTES)
  with zipfile.ZipFile(temporary) as archive:
    summaryBytes = readEvidenceMember(archive, SUMMARY_MEMBER)
    productBytes = readEvidenceMember(archive, PRODUCT_MEMBER, optional=True)
    inventoryBytes = readEvidenceMember(archive, INVENTORY_MEMBER)
  temporary.unlink()
  (output / 'source-build-summary.json').write_bytes(summaryBytes)
  (output / 'source-installed-distributions.json').write_bytes(inventoryBytes)
  summary = json.loads(summaryBytes)
  if (summary.get('status') != 'BUILT'
      or summary.get('core', {}).get('build', {}).get('packager_sha') != run['head_sha']):
    raise BuildConfigError('Source run does not have a completed build bound to its real commit')
  packages = summary.get('module_archives', [])
  ids = [item.get('module_id') for item in packages]
  if not packages or len(ids) != len(set(ids)) or set(ids) != set(summary['core']['catalog']):
    raise BuildConfigError('Source build does not identify its complete unique module set')
  if any(type(item.get('bytes')) is not int or not 0 < item['bytes'] <= MAX_MODULE_ARCHIVE_BYTES
         for item in packages):
    raise BuildConfigError('Source module ZIP exceeds its preparation size bound')
  receipt = {'schema_version': 1, 'type': 'visionworkshop-module-reuse-source',
             'repository': REPOSITORY, 'source_run': run, 'evidence_artifact': evidence,
             'build_summary': {'path': 'source-build-summary.json', 'size': len(summaryBytes),
                               'sha256': hashlib.sha256(summaryBytes).hexdigest()},
             'installed_distributions': {'path': 'source-installed-distributions.json',
                                        'size': len(inventoryBytes),
                                        'sha256': hashlib.sha256(inventoryBytes).hexdigest()},
             'source_product_acceptance': {'status': 'NOT_RECORDED'}, 'modules': {}}
  if productBytes is not None:
    (output / 'source-product-summary.json').write_bytes(productBytes)
    product = json.loads(productBytes)
    receipt['source_product_acceptance'] = {
      'status': product.get('status'), 'gpu_hardware': product.get('gpu_hardware'),
      'path': 'source-product-summary.json', 'size': len(productBytes),
      'sha256': hashlib.sha256(productBytes).hexdigest()}
  (output / 'modules').mkdir()
  for package in packages:
    moduleId = package['module_id']
    if not re.fullmatch(r'(?:runtime|feature|resource)\.[a-z0-9][a-z0-9.-]*', moduleId):
      raise BuildConfigError('Source build has an invalid module identity')
    artifact = selectArtifact(artifacts, 'visionworkshop-module-' + moduleId + '-' + suffix, run)
    name = PureWindowsPath(package['path']).name
    if not name.endswith('.zip') or '/' in name or '\\' in name:
      raise BuildConfigError('Source build has an invalid archive filename')
    temporary = output / 'source-module-artifact.zip'
    downloadArtifact(artifact, temporary, maximumBytes=MAX_MODULE_ARTIFACT_BYTES)
    target = output / 'modules' / name
    with zipfile.ZipFile(temporary) as archive:
      members = archive.infolist()
      if len(members) != 1 or members[0].filename != name or members[0].is_dir():
        raise BuildConfigError('Source module artifact must contain its one original ZIP')
      if members[0].file_size != package['bytes']:
        raise BuildConfigError('Source module artifact has a different inner ZIP size')
      with archive.open(members[0]) as reader, target.open('xb') as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
    temporary.unlink()
    if target.stat().st_size != package['bytes'] or fileHash(target) != package['sha256']:
      raise BuildConfigError('Inner module ZIP differs from the source build summary')
    receipt['modules'][moduleId] = {'artifact': artifact, 'archive_path': 'modules/' + name,
                                  'bytes': package['bytes'], 'sha256': package['sha256'],
                                  'manifest_sha256': package['manifest_sha256']}
  writeJson(output / 'reuse-source.json', receipt)
  return receipt


def readReuseSource(root: Path, contract, expectedModules: set[str]) -> dict:
  rejectLinks(root)
  receipt = readJson(root / 'reuse-source.json')
  if (receipt.get('schema_version') != 1 or receipt.get('type') != 'visionworkshop-module-reuse-source'
      or receipt.get('repository') != REPOSITORY or receipt.get('source_run', {}).get('status') != 'completed'
      or set(receipt.get('modules', {})) != expectedModules):
    raise BuildConfigError('Reuse receipt does not identify the completed source and exact module set')
  run = receipt['source_run']
  if (type(run.get('id')) is not int or run['id'] <= 0
      or type(run.get('run_attempt')) is not int or run['run_attempt'] <= 0
      or not re.fullmatch(r'[a-f0-9]{40}', run.get('head_sha', ''))):
    raise BuildConfigError('Reuse receipt has an invalid source run identity')
  suffix = str(run['id']) + '-' + str(run['run_attempt'])
  selectArtifact([receipt['evidence_artifact']], 'visionworkshop-modular-evidence-' + suffix, run)
  record = receipt['build_summary']
  if record['path'] != 'source-build-summary.json':
    raise BuildConfigError('Unexpected source build report path')
  path = root / record['path']
  summary = readJson(path)
  if path.stat().st_size != record['size'] or fileHash(path) != record['sha256']:
    raise BuildConfigError('The source build report changed after verified artifact extraction')
  if (summary.get('status') != 'BUILT' or summary['core']['build']['packager_sha'] != run['head_sha']
      or summary['core']['build']['build_id'] != 'candidate-' + suffix
      or summary.get('core_sha256') != contract.manifest_digest(summary['core'])
      or summary.get('source', {}).get('commit') != summary['core']['build']['app_sha']
      or summary.get('packager', {}).get('commit') != run['head_sha']
      or hashlib.sha256(contract.canonical_json(summary['dependency_lock'])).hexdigest()
      != summary['core']['dependency_lock_sha256']):
    raise BuildConfigError('Source Core identity does not match its completed build report')
  contract.validate_core(summary['core'])
  inventoryRecord = receipt['installed_distributions']
  if inventoryRecord['path'] != 'source-installed-distributions.json':
    raise BuildConfigError('Unexpected source installed-distribution report path')
  inventoryPath = root / inventoryRecord['path']
  installed = readJson(inventoryPath)
  if (inventoryPath.stat().st_size != inventoryRecord['size']
      or fileHash(inventoryPath) != inventoryRecord['sha256']
      or not isinstance(installed.get('distributions'), dict)
      or not isinstance(installed.get('provenance'), dict)):
    raise BuildConfigError('Source installed-distribution evidence changed after artifact extraction')
  acceptance = receipt['source_product_acceptance']
  if acceptance.get('path'):
    if acceptance['path'] != 'source-product-summary.json':
      raise BuildConfigError('Unexpected source product report path')
    path = root / acceptance['path']
    product = readJson(path)
    if (path.stat().st_size != acceptance['size'] or fileHash(path) != acceptance['sha256']
        or product.get('status') != acceptance['status']
        or product.get('core_sha256') != summary['core_sha256']
        or product.get('build') != summary['core']['build']):
      raise BuildConfigError('Source product result no longer matches its original evidence')
  elif acceptance.get('status') != 'NOT_RECORDED':
    raise BuildConfigError('Source product qualification is not backed by its original report')
  packages = {item['module_id']: item for item in summary['module_archives']}
  if len(packages) != len(summary['module_archives']) or set(packages) != expectedModules:
    raise BuildConfigError('Source build archive set differs from the selected modules')
  builds = summary.get('module_builds')
  if builds is not None and set(builds) != expectedModules:
    raise BuildConfigError('Source build does not identify every original module build')
  for moduleId, item in receipt['modules'].items():
    package = packages[moduleId]
    selectArtifact([item['artifact']], 'visionworkshop-module-' + moduleId + '-' + suffix, run)
    expectedPath = 'modules/' + PureWindowsPath(package['path']).name
    if (item['archive_path'] != expectedPath
        or any(item[key] != package[key] for key in ('bytes', 'sha256', 'manifest_sha256'))
        or package.get('verified') is not True or package.get('compression') != 'zip/lzma'):
      raise BuildConfigError('Reuse ZIP does not match its original completed archive record')
  return {'root': root, 'receipt': receipt, 'summary': summary, 'packages': packages,
          'installed': installed}


def boundedLzmaMember(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> None:
  if (member.is_dir() or member.compress_type != zipfile.ZIP_LZMA or member.flag_bits & 1
      or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)):
    raise BuildConfigError('Reusable ZIP contains an invalid file type or compression method')
  archive.fp.seek(member.header_offset)
  header = archive.fp.read(30)
  if len(header) != 30 or header[:4] != b'PK\x03\x04':
    raise BuildConfigError('Reusable ZIP local member header is invalid')
  nameLength, extraLength = struct.unpack_from('<HH', header, 26)
  archive.fp.seek(nameLength + extraLength, 1)
  properties = archive.fp.read(9)
  if (len(properties) != 9 or properties[:5] != bytes((9, 4, 5, 0, 93))
      or not 1024**2 <= struct.unpack_from('<I', properties, 5)[0] <= 256 * 1024**2):
    raise BuildConfigError('Reusable ZIP has unreviewed LZMA properties or dictionary size')


def validateReuseCore(source: dict, core: dict) -> None:
  if any(source['summary']['core'][key] != core[key]
         for key in ('protocol_version', 'module_api', 'python', 'dependency_lock_sha256', 'catalog')):
    raise BuildConfigError('Reusable module source has a different schema, lock, catalog or ABI')


def reuseArchive(source: dict, moduleId: str, payload: Path, expected: dict,
                 core: dict, destination: Path, contract) -> tuple[dict, dict, dict, bytes]:
  validateReuseCore(source, core)
  item = source['receipt']['modules'][moduleId]
  archivePath = source['root'] / item['archive_path']
  rejectLinks(archivePath)
  if (archivePath.stat().st_size != item['bytes'] or not 0 < item['bytes'] <= contract.MAX_ARCHIVE_BYTES
      or fileHash(archivePath) != item['sha256']):
    raise BuildConfigError('Reusable module ZIP differs from its verified source artifact')
  staged = scanFiles(payload)
  expectedFiles = {record['path']: {key: record[key] for key in ('size', 'sha256')}
                   for record in expected['files']}
  if staged != expectedFiles:
    raise BuildConfigError('New staged module payload differs from its declared file inventory')
  with zipfile.ZipFile(archivePath) as archive:
    members = archive.infolist()
    names = [member.filename for member in members]
    if len(names) != len(set(names)) or names.count('module.json') != 1:
      raise BuildConfigError('Reusable ZIP has duplicate entries or no unique manifest')
    manifestInfo = archive.getinfo('module.json')
    if not 0 < manifestInfo.file_size <= contract.MAX_METADATA:
      raise BuildConfigError('Reusable manifest exceeds the metadata bound')
    boundedLzmaMember(archive, manifestInfo)
    originalBytes = archive.read(manifestInfo)
    original = json.loads(originalBytes)
    if (contract.canonical_json(original) != originalBytes
        or contract.manifest_digest(original) != item['manifest_sha256']):
      raise BuildConfigError('Reusable manifest bytes differ from their original canonical identity')
    contract.validate_manifest(original, core)
    sourceBuild = source['summary'].get('module_builds', {}).get(
      moduleId, source['summary']['core']['build'])
    if (original.get('build') != sourceBuild
        or {key: value for key, value in original.items() if key != 'build'}
        != {key: value for key, value in expected.items() if key != 'build'}):
      raise BuildConfigError('Reusable module metadata, version, compatibility or payload changed')
    records = {'payload/' + name: record for name, record in staged.items()}
    records['module.json'] = {'size': len(originalBytes), 'sha256': hashlib.sha256(originalBytes).hexdigest()}
    if set(names) != set(records):
      raise BuildConfigError('Reusable ZIP has missing or undeclared payload entries')
    for member in members:
      boundedLzmaMember(archive, member)
      record = records[member.filename]
      if member.file_size != record['size']:
        raise BuildConfigError('Reusable ZIP member size differs from new staging')
      with archive.open(member) as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
          raise BuildConfigError('Reusable ZIP member bytes differ from new staging')
    compressed = sum(member.compress_size for member in members)
  package = source['packages'][moduleId]
  if (package['file_count'] != len(records) or package['expanded_bytes'] != sum(r['size'] for r in records.values())
      or package['compressed_payload_bytes'] != compressed
      or scanFiles(payload) != staged or fileHash(archivePath) != item['sha256']):
    raise BuildConfigError('Reusable ZIP or staged payload changed during complete verification')
  destination.parent.mkdir(parents=True, exist_ok=True)
  with archivePath.open('rb') as reader, destination.open('xb') as writer:
    shutil.copyfileobj(reader, writer, 1024 * 1024)
  if destination.stat().st_size != item['bytes'] or fileHash(destination) != item['sha256']:
    raise BuildConfigError('The reused output ZIP differs from its original bytes')
  report = {'status': 'PASS', 'module_id': moduleId, 'archive_bytes_unchanged': True,
            'manifest_bytes_unchanged': True, 'manifest_sha256': item['manifest_sha256'],
            'payload_files_verified': len(staged), 'source_run': source['receipt']['source_run'],
            'source_artifact': item['artifact'], 'source_build': original['build'],
            'target_core_build': core['build'], 'source_product_acceptance': source['receipt']['source_product_acceptance'],
            'prior_reuse': package.get('reuse_from'),
            'scope': 'Verified original ZIP bytes only; native qualification is not inherited'}
  return original, dict(package, path=str(destination), reuse_from=report), report, originalBytes
