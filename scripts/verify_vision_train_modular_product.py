"""Exercise the actual protocol-4 EXE, offline ZIP manager and fixed CPU cases."""

import argparse
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
from scripts.verify_vision_train_modules import cleanEnvironment
from scripts.verify_vision_train_modules import writeReport


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


def checkCase(executable, case, reports, name, environment, core, expectedIdentity, timeout=300):
  report, process = invoke(executable, ['--modular-runtime-check', '--case', case],
                           reports, name, environment, timeout=timeout)
  if (report.get('status') != 'PASS' or report.get('case') != case
      or report.get('frozen') is not True or report.get('python') != '3.12.10'
      or report.get('platform') != 'win32' or report.get('pid') != process['pid']
      or Path(report.get('executable', '')).resolve() != executable.resolve()
      or report.get('runtime_identity') != expectedIdentity or report.get('network_attempts')):
    raise RuntimeError('Fixed product check has inconsistent execution identity or status: ' + name)
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
    for item in [build['core_archive'], *build['module_archives']]:
      if fileHash(Path(item['path'])) != item['sha256']:
        raise RuntimeError('A candidate archive changed since its build verification')
    executable = extractCore(Path(build['core_archive']['path']), output / '中文 模块验收')
    core = json.loads((executable.parent / 'core.json').read_text(encoding='utf-8'))
    coreDigest = fileHash(executable.parent / 'core.json')
    if core != build['core'] or coreDigest != build['core_sha256']:
      raise RuntimeError('Extracted Core differs from build identity')
    baseline = coreInventory(executable.parent)
    writeReport(reports / 'core-inventory-before.json', {'files': baseline})
    summary['core_inventory_before'] = {'inventory_sha256': objectHash(baseline),
      'file_count': len(baseline), 'report': 'core-inventory-before.json',
      'report_sha256': fileHash(reports / 'core-inventory-before.json')}

    def checkpoint(name):
      summary['core_integrity_checks'].append(
        verifyCoreUnchanged(executable.parent, baseline, reports, name))

    environment = cleanEnvironment(output)
    summary.update(core_sha256=coreDigest, build=core['build'],
                    executable=str(executable), executable_sha256=fileHash(executable))
    initial, _ = cli(executable, ['status'], reports, 'empty-status', environment)
    identity = activeIdentity(initial, coreDigest)
    if identity['modules']:
      raise RuntimeError('Fresh Core unexpectedly has active optional modules')
    summary['cases'].append(checkCase(executable, 'core', reports, 'core-without-modules',
                                      environment, core, identity))
    summary['cases'].append(checkCase(executable, 'annotation', reports,
                                      'annotation-without-modules', environment, core, identity))
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
    checkpoint('ort-repair-and-native-reload')
    cli(executable, ['remove', 'runtime.ort'], reports, 'ort-remove', environment)
    empty, _ = cli(executable, ['activate'], reports, 'ort-remove-activate', environment)
    summary['cases'].append(checkCase(executable, 'core', reports, 'core-after-remove',
                                      environment, core, activeIdentity(empty, coreDigest)))
    checkpoint('ort-removal')
    cli(executable, ['install', *map(str, archives.values())], reports, 'install-all', environment,
        timeout=1200)
    active, _ = cli(executable, ['activate'], reports, 'activate-all', environment, timeout=1200)
    identity = activeIdentity(active, coreDigest)
    if set(identity['modules']) != set(archives):
      raise RuntimeError('The complete candidate set did not activate')
    checkpoint('complete-install-and-activation')
    for case, timeout in (('torch', 300), ('ort', 300), ('dino', 300), ('yolo', 900), ('pt', args.pt_timeout)):
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
