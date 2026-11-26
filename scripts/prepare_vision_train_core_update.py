"""Prepare a protocol-4 Core update in scratch. This diagnostic never applies it."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_records import fileHash, objectHash, rejectLinks
from scripts.diagnose_vision_train_core import MAX_CORE_EXPANDED, MAX_CORE_ZIP, require
from scripts.verify_vision_train_modular_product import (
  cli, coreInventory, extractCore, productEnvironment, verifyCoreUnchanged,
)
from scripts.verify_vision_train_modules import writeReport
from vision_train_modular_build import loadContract
from vision_train_modular_index import readMetadata, validateMembers
from vision_train_runtime import ioPath


CORE_ROOTS = {'VisionWorkshop.exe', 'core.json', 'dependency-lock.json',
              '_internal', 'native', 'python', 'site-packages'}
REGISTRY = '.module-state/registry.json'
STATE_FILES = (REGISTRY, '.module-state/registry.lock', '.module-state/runtime.lock')


def shaArgument(value: str) -> str:
  if not re.fullmatch(r'[0-9a-f]{64}', value):
    raise argparse.ArgumentTypeError('Expected a lowercase SHA-256 digest')
  return value


def resolvePath(path: Path, *, strict: bool = True) -> Path:
  rejectLinks(path.absolute())
  return path.resolve(strict=strict)


def loadSourceTools(source: Path):
  # Import only after the caller's pinned inventory has verified the entire source Core.
  python = source / 'python'
  contract = loadContract(python)
  sys.path.insert(0, str(python))
  try:
    import update_filesystem
    import update_process
    import update_storage
  finally:
    sys.path.pop(0)
  for module in (update_filesystem, update_process, update_storage):
    require(Path(module.__file__).resolve().parent == python, 'Unexpected source tooling origin')
  return contract, update_filesystem, update_process, update_storage


def stateProof(source: Path, filesystem) -> dict:
  return {name: {'file_identity': list(filesystem.file_identity(source / name)),
                 'sha256': fileHash(source / name)} for name in STATE_FILES}


def targetDescriptor(indexPath: Path, indexSha: str, archivePath: Path, contract, storage):
  raw = storage.read_bytes(indexPath, contract.MAX_METADATA)
  require(hashlib.sha256(raw).hexdigest() == indexSha, 'Target module index SHA-256 mismatch')
  index = contract.parse_json(raw, contract.MAX_METADATA)
  require(index.get('type') == 'visionworkshop-module-index' and index.get('schema_version') == 1
          and index.get('protocol_version') == contract.PROTOCOL_VERSION, 'Invalid target module index')
  descriptor = index['core']['archive']
  require(descriptor['name'] == archivePath.name and descriptor['compression'] == 'zip/lzma',
          'Target archive name or format differs from the index')
  bounds = {'bytes': MAX_CORE_ZIP, 'file_count': contract.MAX_MODULE_FILES,
            'expanded_bytes': MAX_CORE_EXPANDED, 'compressed_payload_bytes': MAX_CORE_ZIP}
  for key, maximum in bounds.items():
    require(type(descriptor[key]) is int and 0 < descriptor[key] <= maximum,
            'Target archive exceeds the indexed bound for ' + key)
  contract.sha256(descriptor['sha256'])
  return index, descriptor


def stageTarget(archivePath: Path, output: Path, index: dict, descriptor: dict, contract, storage):
  with storage.protected_reader(archivePath) as stream:
    require(os.fstat(stream.fileno()).st_size == descriptor['bytes']
            and hashlib.file_digest(stream, 'sha256').hexdigest() == descriptor['sha256'],
            'Target Core archive size or SHA-256 mismatch')
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
      members = validateMembers(archive, descriptor, contract, core=True)
      relative = {name.removeprefix('VisionWorkshop/'): member.file_size
                  for name, member in members.items()}
      require({name.split('/', 1)[0] for name in relative} == CORE_ROOTS,
              'Target archive contains unexpected Core roots')
      target, raw = readMetadata(archive, 'VisionWorkshop/core.json', contract)
      _, lockRaw = readMetadata(archive, 'VisionWorkshop/dependency-lock.json', contract)
      contract.validate_core(target)
      coreSha = hashlib.sha256(raw).hexdigest()
      lockSha = hashlib.sha256(lockRaw).hexdigest()
      require(coreSha == index['core']['manifest_sha256'] and target['build'] == index['build']
              and target['version'] == index['core']['version'], 'Target Core identity differs from index')
      require(lockSha == target['dependency_lock_sha256'] == index['dependency_lock_sha256'],
              'Target dependency lock differs from index')
    stream.seek(0)
    executable = extractCore(stream, output / 'staged')
  inventory = coreInventory(executable.parent)
  require({name: item['size'] for name, item in inventory.items()} == relative,
          'Extracted Core inventory differs from verified archive')
  require(inventory['core.json']['sha256'] == coreSha
          and inventory['dependency-lock.json']['sha256'] == lockSha,
          'Extracted target Core metadata changed')
  return executable, inventory, {
    'archive': descriptor, 'build': target['build'], 'core_sha256': coreSha,
    'dependency_lock_sha256': lockSha, 'version': target['version'],
    'exe_sha256': inventory['VisionWorkshop.exe']['sha256'],
    'python_dll_sha256': inventory['_internal/python312.dll']['sha256'],
  }


def prepare(args, source: Path, archive: Path, indexPath: Path, output: Path, reports: Path):
  baseline = coreInventory(source)
  require(objectHash(baseline) == args.source_inventory_sha256,
          'Source Core inventory does not match its pinned digest')
  contract, filesystem, process, storage = loadSourceTools(source)
  process.require_local_ntfs(source)
  process.require_local_ntfs(output)
  sourceId = list(filesystem.directory_identity(source))
  require(filesystem.directory_identity(output)[0] == sourceId[0],
          'Source and preparation directory must be on the same local NTFS volume')
  before = stateProof(source, filesystem)
  registryBytes = storage.read_record_bytes(source / REGISTRY, contract.MAX_METADATA)
  state = contract.parse_json(registryBytes, contract.MAX_METADATA)
  require(state.get('pending') is None and 'pending' in state,
          'Resolve pending module changes before preparing a Core update')
  require(hashlib.sha256(registryBytes).hexdigest() == before[REGISTRY]['sha256'],
          'Source registry changed during capture')
  sourceCore = baseline['core.json']['sha256']
  index, descriptor = targetDescriptor(indexPath, args.target_index_sha256, archive, contract, storage)
  product, child = cli(source / 'VisionWorkshop.exe', ['check-core', str(archive), descriptor['sha256']],
                       reports, 'source-check-core', productEnvironment(output), timeout=args.timeout)
  result = product['result']
  registry = {key: state[key] for key in ('generation', 'revision', 'transaction_id')}
  registry['sha256'] = before[REGISTRY]['sha256']
  selections = {key: state[key] for key in ('active', 'previous', 'pending')}
  identities = {item for selection in selections.values() if selection for item in selection.items()}
  require(result['scope'] == 'core-and-module-compatibility' and result['source_core_sha256'] == sourceCore
          and result['source_registry'] == registry and result['selections'] == selections
          and result['verified_module_versions'] == len(identities), 'Frozen preflight snapshot differs')
  executable, inventory, target = stageTarget(archive, output, index, descriptor, contract, storage)
  require(target['core_sha256'] != sourceCore, 'Source and target Core identities are the same')
  preflightTarget = {key: target[key] for key in (
    'core_sha256', 'dependency_lock_sha256', 'version', 'exe_sha256', 'python_dll_sha256',
  )}
  preflightTarget['archive_sha256'] = descriptor['sha256']
  require(result['target'] == preflightTarget, 'Staged Core differs from frozen preflight target')
  unchanged = verifyCoreUnchanged(source, baseline, reports, 'after-prepare')
  require(fileHash(archive) == descriptor['sha256'] and fileHash(indexPath) == args.target_index_sha256,
          'Target inputs changed during preparation')
  writeReport(reports / 'staged-core-files.json', inventory)
  require(before == stateProof(source, filesystem)
          and sourceId == list(filesystem.directory_identity(source)), 'Source installation changed')
  plan = {
    'schema_version': 1, 'protocol_version': 4, 'scope': 'diagnostic-prepare-only',
    'cutover': 'NOT_RUN', 'requires_revalidation_before_cutover': True,
    'source': {'path': str(source), 'directory_identity': sourceId, 'core_sha256': sourceCore,
               'exe_sha256': baseline['VisionWorkshop.exe']['sha256'],
               'dependency_lock_sha256': baseline['dependency-lock.json']['sha256'],
               'inventory_sha256': args.source_inventory_sha256, 'registry': registry,
               'selections': selections, 'state_files': before},
    'target': {**target, 'archive_path': str(archive), 'index_sha256': args.target_index_sha256,
               'index_path': str(indexPath), 'staged_core': str(executable.parent),
               'directory_identity': list(filesystem.directory_identity(executable.parent)),
               'inventory_sha256': objectHash(inventory), 'file_count': len(inventory)},
    'source_preflight': child, 'source_core_unchanged': unchanged,
    'staged_inventory_report_sha256': fileHash(reports / 'staged-core-files.json'),
  }
  storage.atomic_json(output / 'core-prepare-plan.json', plan, create_only=True)
  return {'status': 'PASS', 'cutover': 'NOT_RUN', 'target_executed': False,
          'plan_sha256': fileHash(output / 'core-prepare-plan.json')}


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source-core', type=Path, required=True)
  parser.add_argument('--source-inventory-sha256', type=shaArgument, required=True)
  parser.add_argument('--target-core-zip', type=Path, required=True)
  parser.add_argument('--target-index', type=Path, required=True)
  parser.add_argument('--target-index-sha256', type=shaArgument, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--timeout', type=int, default=900)
  args = parser.parse_args(argv)
  require(os.name == 'nt', 'This Core preparation diagnostic requires Windows')
  source, archive, indexPath = map(resolvePath, (args.source_core, args.target_core_zip, args.target_index))
  output = resolvePath(args.output, strict=False)
  require(not output.is_relative_to(source) and not source.is_relative_to(output),
          'Preparation output and source installation must be separate')
  ioPath(output).mkdir()
  reports = output / 'reports'
  reports.mkdir()
  (output / 'empty-cwd').mkdir()
  try:
    result = prepare(args, source, archive, indexPath, output, reports)
  except Exception as error:
    writeReport(reports / 'core-prepare-summary.json', {'status': 'FAIL', 'cutover': 'NOT_RUN',
                                                       'error': str(error), 'traceback': traceback.format_exc()})
    raise
  writeReport(reports / 'core-prepare-summary.json', result)
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
