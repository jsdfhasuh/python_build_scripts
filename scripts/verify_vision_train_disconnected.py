"""Use verified, pre-downloaded archives under the isolated Windows guest controller."""

import argparse
import json
from pathlib import Path

from build_records import fileHash
from scripts.verify_vision_train_modular_product import (
  activeIdentity, cli, coreInventory, extractCore, productEnvironment,
  verifyCoreUnchanged, verifySingleModuleUpdate,
)
from scripts.verify_vision_train_modules import writeReport
from scripts.verify_vision_train_offline_network import ASSETS, EDGE_MANIFEST, checkAsset, prepare, require
from vision_train_modular_reuse import prepareReuse


CORE = {
  'run': 45871218823, 'head': 'a4eba55b3c2925fa7623e559a17a4dfb6c869044',
  'artifact': 'visionworkshop-core-candidate-45871218823-1', 'id': 15150785246,
  'outer_bytes': 180451794, 'outer_sha256': 'b5735ba92abdd66bf332f02686641bbed91a5f465636cdd7ff48f630ec9ac794',
  'name': 'VisionWorkshop-Core-0.0.0.zip', 'bytes': 180451622,
  'sha256': '05c9a62f10d4c05a3e6955e7186ccc85d38885964c358cf2c0062d85e0bbd205',
}
CORE_MANIFEST = '240ce1e8faeb31e78823d8ce4407ff778550ce37afb324c940e54a05bdd53da9'
CORE_EXE = 'ac1aed86df6c93222be8bd02cc1d68522250547034eb949a2d1bcb4947eebe49'
EDGE = ASSETS[1]
TORCH = 'runtime.torch'
PHASES = {'edge': ('edge',), 'all': ('torch', 'remaining', 'activate'), 'activation': ('activate',)}


def stage(root, scope):
  prepare(root, (CORE, EDGE) if scope == 'edge' else (CORE,))
  (root / 'reports/empty-cwd').mkdir()
  if scope != 'edge':
    original = prepareReuse(45616400076, 1, root / 'original')
    require(original['source_run']['head_sha'] == EDGE['head'] and len(original['modules']) == 11,
            'The complete original module set is required')
    writeReport(root / 'reports/original-module-archives.json', original)
    executable = extractCore(root / CORE['name'], root / '中文 断网')
    writeReport(root / 'reports/core-baseline.json', coreInventory(executable.parent))


def installOriginal(executable, archives, hashes, reports, environment):
  installed, _ = cli(executable, ['install', *archives.values()], reports, 'original-install', environment)
  accepted = installed['result']['archives']
  require(installed['result']['pending'] and len(accepted) == len(hashes)
          and {row['module_id']: row['sha256'] for row in accepted} == hashes, 'Unexpected original install receipt')


def verifyCoreIdentity(executable):
  require(fileHash(executable) == CORE_EXE and fileHash(executable.parent / 'core.json') == CORE_MANIFEST,
          'The staged executable or Core identity changed')


def verifyRegistry(executable, pending, active, generation):
  path = executable.parent / '.module-state/registry.json'
  state = json.loads(path.read_bytes())
  require(state['core_sha256'] == CORE_MANIFEST and state['generation'] == generation
          and state['pending'] == pending and state['active'] == active and state['last_error'] is None,
          'Unexpected on-disk registry after the frozen command')
  return {'sha256': fileHash(path), 'generation': generation, 'pending': pending, 'active': active}


def fullPhase(root, phase, reports, summary):
  executable = root / '中文 断网/VisionWorkshop/VisionWorkshop.exe'
  verifyCoreIdentity(executable)
  original = json.loads((root / 'reports/original-module-archives.json').read_bytes())
  modules = original['modules']
  metadata = json.loads((executable.parent / 'core.json').read_bytes())
  require(set(modules) == set(metadata['catalog']) and len(modules) == 11
          and original['source_run']['id'] == 45616400076
          and original['source_run']['run_attempt'] == 1, 'The frozen archive set differs')
  manifests = {module: entry['manifest_sha256'] for module, entry in modules.items()}
  environment = productEnvironment(root)
  if phase == 'activate':
    summary['registry_before'] = verifyRegistry(executable, manifests, {}, 0)
    activated, _ = cli(executable, ['activate'], reports, 'original-activate', environment)
    identity = activeIdentity(activated, CORE_MANIFEST)
    require(identity['generation'] == 1 and identity['modules'] == manifests, 'Wrong original modules are active')
    summary['registry'] = verifyRegistry(executable, None, manifests, 1)
    return

  torch = {TORCH: manifests[TORCH]}
  if phase == 'torch':
    first, _ = cli(executable, ['status'], reports, 'empty', environment)
    summary['registry_before'] = verifyRegistry(executable, None, {}, 0)
    require(activeIdentity(first, CORE_MANIFEST) == {'core_sha256': CORE_MANIFEST, 'generation': 0, 'modules': {}},
            'Expected a fresh empty Core')
    selected = [TORCH]
    pending = torch
  else:
    summary['registry_before'] = verifyRegistry(executable, torch, {}, 0)
    selected = [module for module in modules if module != TORCH]
    pending = manifests
  archives = {module: str(root / 'original' / modules[module]['archive_path']) for module in selected}
  hashes = {module: modules[module]['sha256'] for module in selected}
  installOriginal(executable, archives, hashes, reports, environment)
  summary['original_archives'] = hashes
  summary['registry'] = verifyRegistry(executable, pending, {}, 0)


def repairEdge(executable, archive, reports, environment, identity):
  module = executable.parent / 'modules/resource.edgesam' / EDGE_MANIFEST
  manifest = json.loads((module / 'module.json').read_bytes())
  expected = {row['path']: row['sha256'] for row in manifest['files']}
  relative = 'resources/edge_sam_decoder.onnx'
  victim = module / 'payload' / relative
  require(fileHash(victim) == expected[relative], 'Repair must start with the original installed decoder')
  with victim.open('r+b') as stream:
    original = stream.read(1)
    require(len(original) == 1, 'The backed decoder is empty')
    stream.seek(0)
    stream.write(bytes([original[0] ^ 1]))
  damaged = fileHash(victim)
  require(damaged != expected[relative], 'The independent copy was not damaged')

  broken, _ = cli(executable, ['status'], reports, 'edge-repair-broken', environment)
  row = next(item for item in broken['result']['modules'] if item['module_id'] == 'resource.edgesam')
  require(row['status'] == 'broken' and activeIdentity(broken, CORE_MANIFEST) == identity,
          'Broken resource must retain the active identity')
  denied, _ = cli(executable, ['install', str(archive)], reports, 'edge-repair-install-denied', environment, expected=False)
  require(denied['code'] == 'MODULE_REPAIR_REQUIRED', 'The normal install bypassed explicit repair')
  repaired, _ = cli(executable, ['repair', str(archive)], reports, 'edge-repair', environment)
  require(repaired['result']['repaired'] == [{'module_id': 'resource.edgesam', 'manifest_sha256': EDGE_MANIFEST}],
          'The exact active resource was not repaired')
  current, _ = cli(executable, ['status'], reports, 'edge-repair-restored', environment)
  row = next(item for item in current['result']['modules'] if item['module_id'] == 'resource.edgesam')
  require(row['status'] == 'installed' and activeIdentity(current, CORE_MANIFEST) == identity
          and fileHash(module / 'module.json') == EDGE_MANIFEST
          and all(fileHash(module / 'payload' / path) == digest for path, digest in expected.items()),
          'The original file bytes or active version were not restored')
  return {'status': 'PASS', 'file': relative, 'damaged_sha256': damaged,
          'restored_sha256': expected[relative], 'files_verified': len(expected), 'runtime_identity': identity}


def lifecycle(root, scope, phase):
  reports = root / 'reports' / phase
  summary = {'status': 'FAIL', 'scope': scope, 'phase': phase,
             'core_sha256': CORE_MANIFEST, 'exe_sha256': CORE_EXE, 'integrity': []}
  try:
    require((reports / 'network-disconnected.json').is_file(), 'The offline controller did not start this phase')
    if scope != 'edge':
      fullPhase(root, phase, reports, summary)
      summary['status'] = 'PASS'
      return

    checkAsset(root / CORE['name'], CORE)
    destination = root / '中文 断网'
    executable = extractCore(root / CORE['name'], destination)
    archive = root / EDGE['name']
    checkAsset(archive, EDGE)
    manifests = {'resource.edgesam': EDGE_MANIFEST}
    verifyCoreIdentity(executable)
    baseline = coreInventory(executable.parent)
    metadata = json.loads((executable.parent / 'core.json').read_bytes())
    environment = productEnvironment(root)

    def checkpoint(name):
      summary['integrity'].append(verifyCoreUnchanged(executable.parent, baseline, reports, name))

    first, _ = cli(executable, ['status'], reports, 'empty', environment)
    initial = activeIdentity(first, CORE_MANIFEST)
    require(initial['generation'] == 0 and not initial['modules'], 'Expected a fresh empty Core')
    installOriginal(executable, {'resource.edgesam': str(archive)}, {'resource.edgesam': EDGE['sha256']}, reports, environment)
    activated, _ = cli(executable, ['activate'], reports, 'original-activate', environment)
    identity = activeIdentity(activated, CORE_MANIFEST)
    require(identity['generation'] == 1 and identity['modules'] == manifests, 'Wrong original modules are active')
    summary.update(initial=initial, installed=identity)
    summary['repair'] = repairEdge(executable, archive, reports, environment, identity)
    checkpoint('original-resource-repair')
    transaction, restored = verifySingleModuleUpdate(executable, archive, reports, environment, identity,
                                                     metadata, checkpoint)
    summary.update(restored=restored, update_report_sha256=transaction['report_sha256'])
    summary['status'] = 'PASS'
  finally:
    writeReport(reports / 'disconnected-product-summary.json', summary)


def prepareActivation(root):
  for phase in ('torch', 'remaining'):
    reports = root / 'reports' / ('fixture-' + phase)
    reports.mkdir()
    product = {'scope': 'online-staging-for-activation'}
    fullPhase(root, phase, reports, product)
    writeReport(reports / 'prepared-online.json', product)


def finish(root, scope):
  reports = root / 'reports'
  executable = root / '中文 断网/VisionWorkshop/VisionWorkshop.exe'
  phaseReports = {}
  phases = PHASES[scope]
  for phase in phases:
    path = reports / phase / 'disconnected-product-summary.json'
    product = json.loads(path.read_bytes())
    after = json.loads((path.parent / 'network-after.json').read_bytes())
    exited = json.loads((path.parent / 'product-processes.json').read_bytes())
    require(product['status'] == 'PASS' and after['offlineWindowPassed'] and after['watcherRestored']
            and exited == {'activeBefore': 0, 'activeBeforeRestoration': 0, 'forcedCleanup': 0},
            'A full-install phase has no verified disconnected product and restored network')
    phaseReports[phase] = {'sha256': fileHash(path), 'before': product['registry_before'], 'after': product['registry']}
  for left, right in zip(phases, phases[1:]):
    require(phaseReports[left]['after'] == phaseReports[right]['before'],
            'The frozen registry changed between the disconnected phases')
  if scope == 'activation':
    prepared = json.loads((reports / 'fixture-remaining/prepared-online.json').read_bytes())
    require(prepared['registry'] == phaseReports['activate']['before'], 'The online fixture changed before activation')
  baseline = json.loads((reports / 'core-baseline.json').read_bytes())
  checkpoint = verifyCoreUnchanged(executable.parent, baseline, reports, 'full-original-activation')
  classification = 'separate-disconnected-windows' if scope == 'all' else 'disconnected-activation-with-online-staging'
  writeReport(reports / 'full-disconnected-phased-summary.json',
              {'status': 'PASS', 'scope': classification, 'phases': phaseReports,
               'core_integrity': checkpoint})


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('mode', choices=('stage', 'prepare-activation', 'lifecycle', 'finish'))
  parser.add_argument('output', type=Path)
  parser.add_argument('--scope', choices=PHASES, required=True)
  parser.add_argument('--phase')
  args = parser.parse_args()
  root = args.output.resolve()
  if args.mode == 'stage':
    stage(root, args.scope)
  elif args.mode == 'prepare-activation' and args.scope == 'activation':
    prepareActivation(root)
  elif args.mode == 'finish' and args.scope != 'edge':
    finish(root, args.scope)
  elif args.mode == 'lifecycle' and args.phase in PHASES[args.scope]:
    lifecycle(root, args.scope, args.phase)
  else:
    parser.error('Use a supported mode, scope and phase combination.')
