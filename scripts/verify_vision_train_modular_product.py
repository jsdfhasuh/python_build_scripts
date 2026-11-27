"""Exercise the actual protocol-4 EXE, offline ZIP manager and fixed CPU cases."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_records import fileHash
from build_records import objectHash
from build_records import rejectLinks
from build_records import scanFiles
from vision_train_modular_build import loadContract
from vision_train_modular_index import verifyModuleIndex
from scripts.verify_vision_train_modules import cleanEnvironment
from scripts.verify_vision_train_modules import writeReport


def productEnvironment(output: Path) -> dict:
  environment = cleanEnvironment(output)
  environment['QT_QPA_PLATFORM'] = 'windows'
  return environment


def terminateTree(process, directory: Path) -> None:
  if process.poll() is not None:
    return
  command = [str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'),
             '/PID', str(process.pid), '/T', '/F']
  with (directory / ('terminate-' + str(process.pid) + '.txt')).open('w', encoding='utf-8') as stream:
    subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False, timeout=30)
  if process.poll() is None:
    process.kill()
  process.wait(timeout=15)


def invoke(executable: Path, arguments: list[str], reports: Path, name: str,
           environment: dict, *, timeout: int = 300, expectedExit: int | None = 0) -> tuple[dict, dict]:
  output = reports / (name + '.json')
  if output.exists():
    raise RuntimeError('Acceptance report must be new: ' + str(output))
  command = [str(executable), *arguments, '--output', str(output)]
  started = time.monotonic()
  record = {'status': 'FAIL', 'command': command, 'timeout_seconds': timeout}
  with (reports / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
       (reports / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen(command, cwd=reports.parent / 'empty-cwd', env=environment,
                               stdout=stdout, stderr=stderr)
    record['pid'] = process.pid
    try:
      code = process.wait(timeout=timeout)
      record['exit_code'] = code
      if expectedExit is not None and code != expectedExit:
        raise RuntimeError(name + ' exited with ' + str(code))
      result = json.loads(output.read_text(encoding='utf-8-sig'))
      record['status'] = 'PASS'
      record['report_sha256'] = fileHash(output)
      return result, record
    except subprocess.TimeoutExpired:
      record['status'] = 'TIMEOUT'
      terminateTree(process, reports)
      raise
    finally:
      record['elapsed_seconds'] = round(time.monotonic() - started, 3)
      writeReport(reports / (name + '.process.json'), record)
      terminateTree(process, reports)


def cli(executable, arguments, reports, name, environment, *, expected=True, timeout=900):
  report, process = invoke(executable, ['--offline-modules', *arguments], reports, name,
                           environment, timeout=timeout, expectedExit=0 if expected else 1)
  if report.get('ok') is not expected:
    raise RuntimeError('Offline module CLI reported the wrong outcome: ' + name)
  return report, process


def activeIdentity(status: dict, coreDigest: str) -> dict:
  value = status['result']
  return {'core_sha256': coreDigest, 'generation': value['generation'],
          'modules': {item['module_id']: item['active_manifest'] for item in value['modules']
                      if item['active_manifest']}}


def verifyDefaultCliOutput(executable, initial, reports, environment, identity):
  name = 'empty-status-default-output'
  output = Path(environment['LOCALAPPDATA']) / 'VisionWorkshop/offline-modules/last-result.json'
  if output.exists():
    raise RuntimeError('The default CLI result must not predate its actual EXE invocation')
  command = [str(executable), '--offline-modules', 'status']
  started = time.monotonic()
  record = {'name': name, 'status': 'FAIL', 'command': command, 'timeout_seconds': 300,
            'default_result_file': str(output), 'result_existed_before': False,
            'standard_handles': 'NULL', 'detached_process': True}
  # Redirected files create real Python streams and exercise the stdout-only CLI instead.
  startup = subprocess.STARTUPINFO()
  startup.dwFlags |= subprocess.STARTF_USESTDHANDLES
  startup.hStdInput = startup.hStdOutput = startup.hStdError = 0
  process = subprocess.Popen(command, cwd=reports.parent / 'empty-cwd', env=environment,
                             startupinfo=startup, creationflags=subprocess.DETACHED_PROCESS)
  record['pid'] = process.pid
  try:
    code = process.wait(timeout=300)
    record['exit_code'] = code
    if code != 0:
      raise RuntimeError('Windowed CLI without --output exited with ' + str(code))
    result = json.loads(output.read_text(encoding='utf-8-sig'))
    if (result.get('ok') is not True or result.get('result') != initial['result']
        or Path(result.get('result_file', '')).resolve() != output.resolve()
        or activeIdentity(result, identity['core_sha256']) != identity):
      raise RuntimeError('Windowed CLI default JSON does not identify the initial empty selection')
    copy = reports / (name + '.json')
    copy.write_bytes(output.read_bytes())
    record.update(status='PASS', report=copy.name, report_sha256=fileHash(copy),
                  runtime_identity=identity,
                  scope='Actual windowed EXE with null standard handles, waited by process handle')
    return record
  except subprocess.TimeoutExpired:
    record['status'] = 'TIMEOUT'
    terminateTree(process, reports)
    raise
  finally:
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    writeReport(reports / (name + '.process.json'), record)
    terminateTree(process, reports)


def coreInventory(root: Path) -> dict:
  inventory = {}
  for child in root.iterdir():
    if child.name in {'.module-state', 'modules'}:
      continue
    rejectLinks(child)
    if child.is_dir():
      inventory.update({child.name + '/' + name: record for name, record in scanFiles(child).items()})
    elif child.is_file():
      inventory[child.name] = {'size': child.stat().st_size, 'sha256': fileHash(child)}
    else:
      raise RuntimeError('Unexpected non-file Core entry: ' + str(child))
  return dict(sorted(inventory.items()))


def verifyCoreUnchanged(root: Path, baseline: dict, reports: Path, name: str) -> dict:
  actual = coreInventory(root)
  record = {'status': 'PASS' if actual == baseline else 'FAIL',
            'checkpoint': name, 'inventory_sha256': objectHash(actual),
            'file_count': len(actual), 'bytes': sum(item['size'] for item in actual.values()),
            'missing': sorted(set(baseline) - set(actual)),
            'extra': sorted(set(actual) - set(baseline)),
            'changed': sorted(path for path in set(actual) & set(baseline)
                              if actual[path] != baseline[path])}
  path = reports / ('core-unchanged-' + name + '.json')
  writeReport(path, record)
  if record['status'] != 'PASS':
    raise RuntimeError('Immutable Core changed during offline module acceptance: ' + name)
  return dict(record, report=path.name, report_sha256=fileHash(path))


def verifyColdRepair(executable, archive, reports, environment, identity):
  name = 'cold-ort-repair'
  digest = identity['modules']['runtime.ort']
  root = executable.parent / 'modules/runtime.ort' / digest
  manifestPath = root / 'module.json'
  manifestDigest = fileHash(manifestPath)
  document = json.loads(manifestPath.read_text(encoding='utf-8'))
  expected = {item['path']: {key: item[key] for key in ('size', 'sha256')}
              for item in document['files']}
  if manifestDigest != digest or scanFiles(root / 'payload') != expected:
    raise RuntimeError('Repair fixture did not start with a verified active ORT payload')
  selected = next((item for item in document['files']
                   if item['path'] == 'site-packages/onnxruntime/__init__.py'
                   and 0 < item['size'] <= 65536), None)
  if selected is None:
    raise RuntimeError('The pinned ORT module has no reviewed small repair fixture file')
  target = root / 'payload' / selected['path']
  damaged = target.read_bytes() + b'\n# Deliberate cold offline repair fixture corruption.\n'
  target.write_bytes(damaged)
  badCopy = reports / (name + '-damaged-file.bin')
  badCopy.write_bytes(damaged)
  record = {'name': name, 'status': 'FAIL', 'module_id': 'runtime.ort',
            'manifest_sha256': digest, 'runtime_identity_before': identity,
            'damaged_file': {'path': selected['path'], 'declared': expected[selected['path']],
                             'size': target.stat().st_size, 'sha256': fileHash(target),
                             'saved_copy': badCopy.name, 'saved_copy_sha256': fileHash(badCopy)},
            'scope': 'Actual EXE cold repair in a disposable candidate installation'}
  evidence = reports / (name + '.json')
  writeReport(evidence, record)
  broken, _ = cli(executable, ['status'], reports, name + '-broken-status', environment)
  row = next(item for item in broken['result']['modules'] if item['module_id'] == 'runtime.ort')
  if row['status'] != 'broken' or activeIdentity(broken, identity['core_sha256']) != identity:
    raise RuntimeError('Payload corruption was not reported as broken without changing its identity')
  refused, _ = cli(executable, ['install', str(archive)], reports, name + '-install-denied',
                    environment, expected=False)
  if refused.get('code') != 'MODULE_REPAIR_REQUIRED':
    raise RuntimeError('Ordinary same-version install did not require explicit cold repair')
  repaired, _ = cli(executable, ['repair', str(archive)], reports, name + '-repair', environment)
  if repaired['result']['repaired'] != [{'module_id': 'runtime.ort', 'manifest_sha256': digest}]:
    raise RuntimeError('The actual EXE did not report repairing the selected exact ORT version')
  current, _ = cli(executable, ['status'], reports, name + '-restored-status', environment)
  actual = scanFiles(root / 'payload')
  if (activeIdentity(current, identity['core_sha256']) != identity
      or fileHash(manifestPath) != manifestDigest or actual != expected
      or current['result']['pending']):
    raise RuntimeError('Cold repair changed the active identity or did not restore the full payload')
  restored = next(item for item in current['result']['modules'] if item['module_id'] == 'runtime.ort')
  if restored['status'] != 'installed':
    raise RuntimeError('Repaired ORT is not reported as installed')
  record.update(status='PASS', ordinary_install='MODULE_REPAIR_REQUIRED',
                full_payload_restored=True, payload_inventory_sha256=objectHash(actual),
                payload_file_count=len(actual), runtime_identity_after=activeIdentity(current, identity['core_sha256']))
  writeReport(evidence, record)
  return dict(record, report=evidence.name, report_sha256=fileHash(evidence))


def createResourceUpdateFixture(archive: Path, destination: Path, core: dict, contract) -> dict:
  markerPath = 'resources/visionworkshop-offline-update-fixture.txt'
  with zipfile.ZipFile(archive) as original:
    document = json.loads(original.read('module.json').decode('utf-8'))
    contract.validate_manifest(document, core)
    if document['module_id'] != 'resource.edgesam':
      raise RuntimeError('The update fixture must derive from the reviewed EdgeSAM resource archive')
    previous = contract.manifest_digest(document)
    files = {item['path']: item for item in document['files']}
    names = [item.filename for item in original.infolist()]
    if (len(names) != len(set(names)) or set(names) != {'module.json', *('payload/' + path for path in files)}
        or markerPath in files):
      raise RuntimeError('The original resource archive has unexpected fixture content')
    marker = ('DIAGNOSTIC OFFLINE UPDATE FIXTURE ONLY\n'
              'All original weights are byte-identical; no new business-model qualification.\n'
              'Original manifest: ' + previous + '\n').encode('ascii')
    version = list(contract.stable_version(document['version']))
    originalVersion = document['version']
    version[-1] += 1
    document['version'] = '.'.join(map(str, version))
    document['build']['build_id'] += '-offline-update-fixture'
    entry = {'path': markerPath, 'size': len(marker), 'sha256': hashlib.sha256(marker).hexdigest()}
    document['files'] = sorted([*document['files'], entry], key=lambda item: item['path'])
    document['expanded_size'] += len(marker)
    contract.validate_manifest(document, core)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as result:
      result.writestr('module.json', contract.canonical_json(document))
      for relative, expected in sorted(files.items()):
        digest, size = hashlib.sha256(), 0
        name = 'payload/' + relative
        with original.open(name) as source, result.open(name, 'w') as target:
          for chunk in iter(lambda: source.read(1024 * 1024), b''):
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        if size != expected['size'] or digest.hexdigest() != expected['sha256']:
          raise RuntimeError('Update fixture source payload differs from its original manifest: ' + relative)
      result.writestr('payload/' + markerPath, marker)
  return {'scope': 'Diagnostic version lifecycle only; original model weights unchanged',
          'distributed_archive': {'path': str(archive), 'sha256': fileHash(archive),
                                  'manifest_sha256': previous, 'version': originalVersion},
          'diagnostic_archive': {'path': str(destination), 'sha256': fileHash(destination),
                                 'manifest_sha256': contract.manifest_digest(document),
                                 'version': document['version'], 'published': False},
          'marker': entry, 'original_payload_files': list(files.values()), 'manifest': document}


def verifySingleModuleUpdate(executable, archive, reports, environment, identity, core, checkpoint):
  name = 'edgesam-single-module-update'
  record = {'name': name, 'status': 'FAIL', 'runtime_identity_before': identity}
  started = time.monotonic()
  evidence = reports / (name + '.json')
  try:
    contract = loadContract(executable.parent / 'python')
    fixture = createResourceUpdateFixture(archive, reports.parent / 'lifecycle-fixtures'
      / 'resource.edgesam-diagnostic-update.zip', core, contract)
    record['fixture'] = fixture
    if fixture['distributed_archive']['manifest_sha256'] != identity['modules']['resource.edgesam']:
      raise RuntimeError('Update fixture does not derive from the active original resource version')
    roots = {module: executable.parent / 'modules' / module / digest
             for module, digest in identity['modules'].items()}
    original = {module: scanFiles(root) for module, root in roots.items()}
    record['original_version_inventories'] = original
    cli(executable, ['install', fixture['diagnostic_archive']['path']], reports,
        name + '-install', environment)
    pending, _ = cli(executable, ['status'], reports, name + '-pending', environment)
    row = next(item for item in pending['result']['modules'] if item['module_id'] == 'resource.edgesam')
    if (activeIdentity(pending, identity['core_sha256']) != identity or row['status'] != 'pending_update'
        or row['pending_version'] != fixture['diagnostic_archive']['version']):
      raise RuntimeError('A different resource manifest was not prepared as a pending update')
    activated, _ = cli(executable, ['activate'], reports, name + '-activate', environment)
    updated = activeIdentity(activated, identity['core_sha256'])
    wanted = dict(identity['modules'], **{'resource.edgesam': fixture['diagnostic_archive']['manifest_sha256']})
    if updated['modules'] != wanted or updated['generation'] != identity['generation'] + 1:
      raise RuntimeError('Single-module activation changed another module or has the wrong generation')
    newRoot = executable.parent / 'modules/resource.edgesam' / wanted['resource.edgesam']
    expected = {item['path']: {key: item[key] for key in ('size', 'sha256')}
                for item in fixture['manifest']['files']}
    if (newRoot == roots['resource.edgesam'] or scanFiles(newRoot / 'payload') != expected
        or fileHash(newRoot / 'module.json') != wanted['resource.edgesam']
        or any(scanFiles(roots[module]) != files for module, files in original.items())):
      raise RuntimeError('The updated resource directory or original Core/shared-resource inputs changed')
    record.update(runtime_identity_updated=updated, original_versions_unchanged_after_update=True,
                  fixture_payload_verified=True, installed_fixture_path=str(newRoot))
    checkpoint('single-module-update')
    cli(executable, ['rollback'], reports, name + '-rollback-plan', environment)
    restored, _ = cli(executable, ['activate'], reports, name + '-rollback-activate', environment)
    rolled = activeIdentity(restored, identity['core_sha256'])
    if (rolled['modules'] != identity['modules'] or rolled['generation'] != updated['generation'] + 1
        or restored['result']['pending']
        or any(scanFiles(roots[module]) != files for module, files in original.items())
        or scanFiles(newRoot / 'payload') != expected):
      raise RuntimeError('Cold rollback did not restore the exact original module versions')
    checkpoint('single-module-version-rollback')
    record.update(status='PASS', runtime_identity_restored=rolled,
                  original_versions_unchanged_after_rollback=True,
                  updated_model_computation='NOT_RUN; this fixture tests version transactions only')
  except Exception as error:
    record['error'] = str(error)
    raise
  finally:
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    writeReport(evidence, record)
  return dict(record, report=evidence.name, report_sha256=fileHash(evidence)), rolled


def checkCase(executable, case, reports, name, environment, core, expectedIdentity, timeout=300):
  # A registered .pth must remain inert even when its opt-in variable is enabled.
  environment = dict(environment, COLOREDLOGS_AUTO_INSTALL='1')
  report, process = invoke(executable, ['--modular-runtime-check', '--case', case],
                           reports, name, environment, timeout=timeout)
  if (report.get('status') != 'PASS' or report.get('case') != case
      or report.get('frozen') is not True or report.get('python') != '3.12.10'
      or report.get('platform') != 'win32' or report.get('pid') != process['pid']
      or Path(report.get('executable', '')).resolve() != executable.resolve()
      or report.get('runtime_identity') != expectedIdentity or report.get('network_attempts')):
    raise RuntimeError('Fixed product check has inconsistent execution identity or status: ' + name)
  if 'runtime.ort' in expectedIdentity['modules']:
    auxiliary = report.get('inert_pth', {})
    if (auxiliary.get('status') != 'PASS' or auxiliary.get('module_id') != 'runtime.ort'
        or auxiliary.get('manifest_sha256') != expectedIdentity['modules']['runtime.ort']
        or auxiliary.get('COLOREDLOGS_AUTO_INSTALL') != '1'
        or auxiliary.get('imported_during_mount') is not False
        or auxiliary.get('normal_import_succeeded') is not True):
      raise RuntimeError('The retained .pth boundary was not exercised by the actual EXE: ' + name)
  if case == 'dino-worker':
    result = report.get('result', {})
    if (result.get('status') != 'PASS' or result.get('runtime_identity') != expectedIdentity
        or result.get('successful_model_session') != 'NOT_RUN'
        or result.get('prediction_and_numerics') != 'NOT_RUN'
        or not str(result.get('worker_full_import_audit', '')).startswith('NOT_RUN;')
        or result.get('torch_module_installed') is not ('runtime.torch' in expectedIdentity['modules'])):
      raise RuntimeError('DINO worker lifecycle evidence overstates or mismatches its tested scope: ' + name)
  for package, origin in report['loaded_packages'].items():
    owner = 'core' if package in core['import_roots'] else next(
      (module for module, item in core['catalog'].items() if package in item['import_roots']), None)
    if owner is None:
      raise RuntimeError('Package has no catalog owner: ' + package)
    base = executable.parent if owner == 'core' else executable.parent / 'modules' / owner \
      / expectedIdentity['modules'][owner] / 'payload'
    if not origin or not Path(origin).resolve().is_relative_to(base.resolve()):
      raise RuntimeError('Package loaded outside its exact installed owner: ' + package)
  return {'name': name, 'status': 'PASS', 'pid': process['pid'], 'report': name + '.json',
          'sha256': process['report_sha256'], 'runtime_identity': report['runtime_identity'],
          'inert_pth': report.get('inert_pth'),
          'scope': report.get('scope'), 'result': report.get('result')}


def verifyGuiLease(executable, ortArchive, reports, environment):
  name = 'gui-runtime-lease'
  with (reports / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
       (reports / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen([str(executable)], cwd=reports.parent / 'empty-cwd', env=environment,
                               stdout=stdout, stderr=stderr)
    try:
      deadline, attempt = time.monotonic() + 45, 0
      observed = False
      while time.monotonic() < deadline:
        if process.poll() is not None:
          raise RuntimeError('GUI exited before its runtime lease was observed')
        attempt += 1
        report, _ = invoke(executable, ['--offline-modules', 'activate'], reports,
                            name + '-observe-' + str(attempt), environment,
                            timeout=60, expectedExit=None)
        if report.get('ok') is False and report.get('code') == 'LOCK_BUSY':
          observed = True
          break
        if report.get('ok') is not True:
          raise RuntimeError('Unexpected error while observing the real GUI lease')
      if not observed:
        raise RuntimeError('No runtime lease was observed from the product GUI')
      installed, _ = cli(executable, ['install', str(ortArchive)], reports,
                          name + '-install', environment)
      if installed['result'].get('pending') is not True:
        raise RuntimeError('Installation while GUI is active was not left pending')
      busy, _ = cli(executable, ['activate'], reports, name + '-activate-denied',
                     environment, expected=False)
      if busy.get('code') != 'LOCK_BUSY':
        raise RuntimeError('Pending activation failed for a reason other than the active lease')
      result = {'name': name, 'status': 'PASS', 'gui_pid': process.pid,
                'pending_install_while_running': True, 'activation_denied': 'LOCK_BUSY',
                'termination': 'disposable GUI process tree terminated after observation',
                'scope': 'Real GUI lifetime lease and pending module install, not graceful UI shutdown'}
      writeReport(reports / (name + '.json'), result)
      return result
    finally:
      terminateTree(process, reports)


def extractCore(archive: Path, destination: Path) -> Path:
  with zipfile.ZipFile(archive) as source:
    names = set()
    for item in source.infolist():
      parts = item.filename.split('/')
      if (item.is_dir() or parts[0] != 'VisionWorkshop' or '\\' in item.filename
          or any(part in ('', '.', '..') for part in parts)
          or item.filename.casefold() in names):
        raise RuntimeError('Invalid candidate Core archive path')
      names.add(item.filename.casefold())
      path = destination.joinpath(*parts)
      path.parent.mkdir(parents=True, exist_ok=True)
      with source.open(item) as reader, path.open('xb') as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
          writer.write(chunk)
  return destination / 'VisionWorkshop/VisionWorkshop.exe'


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--build-summary', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--pt-timeout', type=int, default=1200)
  args = parser.parse_args(argv)
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  reports = output / 'reports'
  reports.mkdir()
  (output / 'empty-cwd').mkdir()
  summary = {'status': 'FAIL', 'published': False, 'gpu_hardware': 'NOT_RUN', 'cases': [],
             'core_integrity_checks': [],
             'scope': 'Actual product EXE and offline-module controlled fixtures, not a Release'}
  started = time.monotonic()
  try:
    if os.name != 'nt':
      raise RuntimeError('Product acceptance requires Windows')
    build = json.loads(args.build_summary.read_text(encoding='utf-8'))
    if build['status'] != 'BUILT':
      raise RuntimeError('No successful modular candidate build')
    archives = {item['module_id']: Path(item['path']) for item in build['module_archives']}
    if fileHash(Path(build['core_archive']['path'])) != build['core_archive']['sha256']:
      raise RuntimeError('The Core archive changed before its verified contract could be loaded')
    executable = extractCore(Path(build['core_archive']['path']), output / '中文 模块验收')
    core = json.loads((executable.parent / 'core.json').read_text(encoding='utf-8'))
    coreDigest = fileHash(executable.parent / 'core.json')
    if core != build['core'] or coreDigest != build['core_sha256']:
      raise RuntimeError('Extracted Core differs from build identity')
    contract = loadContract(executable.parent / 'python')
    indexPath = Path(build['module_index']['path'])
    summary['module_index'] = verifyModuleIndex(indexPath, build, contract)
    writeReport(reports / 'module-index-verification.json', summary['module_index'])
    baseline = coreInventory(executable.parent)
    writeReport(reports / 'core-inventory-before.json', {'files': baseline})
    summary['core_inventory_before'] = {'inventory_sha256': objectHash(baseline),
      'file_count': len(baseline), 'report': 'core-inventory-before.json',
      'report_sha256': fileHash(reports / 'core-inventory-before.json')}

    def checkpoint(name):
      summary['core_integrity_checks'].append(
        verifyCoreUnchanged(executable.parent, baseline, reports, name))

    environment = productEnvironment(output)
    summary.update(core_sha256=coreDigest, build=core['build'],
                    qt_platform_requested=environment['QT_QPA_PLATFORM'],
                    module_builds=build.get('module_builds', {
                      name: core['build'] for name in archives}),
                    module_reuse=build.get('module_reuse', {'enabled': False}),
                    executable=str(executable), executable_sha256=fileHash(executable))
    initial, _ = cli(executable, ['status'], reports, 'empty-status', environment)
    identity = activeIdentity(initial, coreDigest)
    if identity['modules']:
      raise RuntimeError('Fresh Core unexpectedly has active optional modules')
    summary['cases'].append(verifyDefaultCliOutput(executable, initial, reports,
                                                 environment, identity))
    summary['cases'].append(checkCase(executable, 'core', reports, 'core-without-modules',
                                      environment, core, identity))
    summary['cases'].append(checkCase(executable, 'annotation', reports,
                                      'annotation-without-modules', environment, core, identity))
    summary['cases'].append(checkCase(executable, 'patchcore-lite', reports,
                                      'patchcore-lite-without-modules', environment, core, identity))
    checkpoint('fresh-core-and-annotation')
    summary['cases'].append(verifyGuiLease(executable, archives['runtime.ort'], reports, environment))
    checkpoint('ort-pending-install')
    active, _ = cli(executable, ['activate'], reports, 'ort-activate', environment)
    identity = activeIdentity(active, coreDigest)
    if set(identity['modules']) != {'runtime.ort'}:
      raise RuntimeError('CPU ORT required unrelated optional modules')
    checkpoint('ort-activation')
    summary['cases'].append(verifyColdRepair(executable, archives['runtime.ort'], reports,
                                            environment, identity))
    summary['cases'].append(checkCase(executable, 'ort', reports, 'ort-after-repair-without-torch',
                                      environment, core, identity))
    summary['cases'].append(checkCase(executable, 'dino', reports, 'dino-without-torch',
                                      environment, core, identity))
    summary['cases'].append(checkCase(executable, 'dino-worker', reports,
                                      'dino-worker-without-torch', environment, core, identity,
                                      timeout=600))
    checkpoint('ort-repair-and-native-reload')
    cli(executable, ['install', str(archives['resource.edgesam'])], reports,
        'edgesam-install', environment)
    edge, _ = cli(executable, ['activate'], reports, 'edgesam-activate', environment)
    identity = activeIdentity(edge, coreDigest)
    if set(identity['modules']) != {'runtime.ort', 'resource.edgesam'}:
      raise RuntimeError('Offline EdgeSAM CPU required unrelated optional modules')
    summary['cases'].append(checkCase(executable, 'edgesam', reports, 'edgesam-without-torch',
                                      environment, core, identity, timeout=180))
    checkpoint('edgesam-resource-install-and-cpu')
    versionUpdate, identity = verifySingleModuleUpdate(executable, archives['resource.edgesam'], reports,
                                                       environment, identity, core, checkpoint)
    summary['cases'].append(versionUpdate)
    summary['cases'].append(checkCase(executable, 'edgesam', reports, 'edgesam-after-version-rollback',
                                      environment, core, identity, timeout=180))
    checkpoint('edgesam-after-version-rollback-computation')
    cli(executable, ['remove', 'runtime.ort', 'resource.edgesam'], reports,
        'ort-and-edgesam-remove', environment)
    empty, _ = cli(executable, ['activate'], reports, 'ort-and-edgesam-remove-activate', environment)
    summary['cases'].append(checkCase(executable, 'core', reports, 'core-after-remove',
                                      environment, core, activeIdentity(empty, coreDigest)))
    checkpoint('ort-and-edgesam-removal')
    cli(executable, ['install', *map(str, archives.values())], reports, 'install-all', environment,
        timeout=1200)
    active, _ = cli(executable, ['activate'], reports, 'activate-all', environment, timeout=1200)
    identity = activeIdentity(active, coreDigest)
    if set(identity['modules']) != set(archives):
      raise RuntimeError('The complete candidate set did not activate')
    checkpoint('complete-install-and-activation')
    for case, timeout in (('torch', 300), ('dataloader-spawn', 360), ('ort', 300),
                          ('dino', 300), ('dino-worker', 600), ('sklearn', 180),
                          ('image-simplification', 240),
                          # The previous exact-Core CI run hit 180s; local same-Core supplement measured 147.5s.
                          # Keep the model, inputs and assertions unchanged; allow bounded Windows-runner headroom.
                          ('cnn-pretrained', 300),
                          ('dino-pretrained', 240), ('yolo-pretrained', 300),
                          ('yolo', 900), ('pt', args.pt_timeout)):
      summary['cases'].append(checkCase(executable, case, reports, case + '-full',
                                        environment, core, identity, timeout=timeout))
    checkpoint('complete-native-and-worker-matrix')
    cli(executable, ['rollback'], reports, 'rollback-plan', environment, timeout=1200)
    rolled, _ = cli(executable, ['activate'], reports, 'rollback-activate', environment, timeout=1200)
    identity = activeIdentity(rolled, coreDigest)
    if identity['modules']:
      raise RuntimeError('Rollback did not restore the previously empty selection')
    summary['cases'].append(checkCase(executable, 'core', reports, 'core-after-rollback',
                                      environment, core, identity))
    checkpoint('rollback')
    summary.update(status='LIMITED', cpu_product_fixtures='PASS',
                    compatibility_findings=build['compatibility_findings'],
                    release_gate='NOT_QUALIFIED', limitations=[
                      'Physical GPU execution not qualified',
                      'Pinned Ultralytics metadata excludes the selected Torch version',
                      'Controlled fixtures do not qualify existing business models or all annotation workflows',
                      'DINO worker checks cover CPU inspect and negative/cancelled sessions, not model predictions or full worker import auditing',
                      'Core upgrades and power-loss recovery are not covered by this matrix'])
    return 0
  except Exception as error:
    summary.update(error=str(error), traceback=traceback.format_exc())
    print(summary['traceback'], file=sys.stderr)
    return 1
  finally:
    summary['elapsed_seconds'] = round(time.monotonic() - started, 3)
    writeReport(reports / 'modular-product-summary.json', summary)


if __name__ == '__main__':
  raise SystemExit(main())
