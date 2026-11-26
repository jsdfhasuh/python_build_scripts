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


def stage(root, scope):
  prepare(root, (CORE, EDGE) if scope == 'edge' else (CORE,))
  (root / 'empty-cwd').mkdir()
  if scope == 'all':
    original = prepareReuse(45616400076, 1, root / 'original')
    require(original['source_run']['head_sha'] == EDGE['head'] and len(original['modules']) == 11,
            'The complete original module set is required')
    writeReport(root / 'reports/original-module-archives.json', original)
    # The EdgeSAM case already covers cold archive extraction while disconnected.
    # Prepare only Core here so the bounded cut covers the full install/activate.
    extractCore(root / CORE['name'], root / '中文 断网')


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


def lifecycle(root, scope):
  reports = root / 'reports'
  summary = {'status': 'FAIL', 'scope': scope,
             'core_sha256': CORE_MANIFEST, 'exe_sha256': CORE_EXE, 'integrity': []}
  try:
    require((reports / 'network-disconnected.json').is_file(), 'The offline controller did not start this phase')
    checkAsset(root / CORE['name'], CORE)
    destination = root / '中文 断网'
    if scope == 'edge':
      executable = extractCore(root / CORE['name'], destination)
      archive = root / EDGE['name']
      checkAsset(archive, EDGE)
      archives = {'resource.edgesam': str(archive)}
      hashes = {'resource.edgesam': EDGE['sha256']}
      manifests = {'resource.edgesam': EDGE_MANIFEST}
    else:
      executable = destination / 'VisionWorkshop/VisionWorkshop.exe'
      original = json.loads((reports / 'original-module-archives.json').read_bytes())
      modules = original['modules']
      require(len(modules) == 11 and original['source_run']['id'] == 45616400076
              and original['source_run']['run_attempt'] == 1, 'The frozen archive set differs')
      archives = {module: str(root / 'original' / entry['archive_path']) for module, entry in modules.items()}
      hashes = {module: entry['sha256'] for module, entry in modules.items()}
      manifests = {module: entry['manifest_sha256'] for module, entry in modules.items()}
    require(fileHash(executable) == CORE_EXE and fileHash(executable.parent / 'core.json') == CORE_MANIFEST,
            'The staged executable or Core identity changed')
    baseline = coreInventory(executable.parent)
    metadata = json.loads((executable.parent / 'core.json').read_bytes())
    environment = productEnvironment(root)

    def checkpoint(name):
      summary['integrity'].append(verifyCoreUnchanged(executable.parent, baseline, reports, name))

    first, _ = cli(executable, ['status'], reports, 'empty', environment)
    initial = activeIdentity(first, CORE_MANIFEST)
    require(initial['generation'] == 0 and not initial['modules'], 'Expected a fresh empty Core')
    installed, _ = cli(executable, ['install', *archives.values()], reports, 'original-install', environment)
    accepted = installed['result']['archives']
    require(installed['result']['pending'] and len(accepted) == len(hashes)
            and {row['module_id']: row['sha256'] for row in accepted} == hashes, 'Unexpected original install receipt')
    activated, _ = cli(executable, ['activate'], reports, 'original-activate', environment)
    identity = activeIdentity(activated, CORE_MANIFEST)
    require(identity['generation'] == 1 and identity['modules'] == manifests, 'Wrong original modules are active')
    summary.update(initial=initial, installed=identity)
    if scope == 'edge':
      summary['repair'] = repairEdge(executable, archive, reports, environment, identity)
      checkpoint('original-resource-repair')
      transaction, restored = verifySingleModuleUpdate(executable, archive, reports, environment, identity,
                                                       metadata, checkpoint)
      summary.update(restored=restored, update_report_sha256=transaction['report_sha256'])
    else:
      require(set(manifests) == set(metadata['catalog']), 'The full original snapshot differs from the catalog')
      checkpoint('full-original-activation')
    summary['status'] = 'PASS'
  finally:
    writeReport(reports / 'disconnected-product-summary.json', summary)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('mode', choices=('stage', 'lifecycle'))
  parser.add_argument('output', type=Path)
  parser.add_argument('--scope', choices=('edge', 'all'), required=True)
  args = parser.parse_args()
  {'stage': stage, 'lifecycle': lifecycle}[args.mode](args.output.resolve(), args.scope)
