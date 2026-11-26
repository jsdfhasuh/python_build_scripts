"""Exercise unchanged product archives with an exact-program outbound block on a fresh runner."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import uuid
import zipfile

from build_records import fileHash
from scripts.verify_vision_train_modular_product import (activeIdentity, cli, coreInventory, extractCore,
  productEnvironment, verifyColdRepair, verifyCoreUnchanged, verifySingleModuleUpdate)
from scripts.verify_vision_train_modules import writeReport
from vision_train_modular_reuse import apiJson, downloadArtifact, selectArtifact, sourceRun


CORE_MANIFEST = 'e71ea34e9fda8b684645f28f4934c25342ddf7edc9207f6cc4f00c125f62f78a'
CORE_EXE = 'c75d26221bd14565089a5832176901ee52996b3e00acb36131ee3efa156e423f'
EDGE_MANIFEST = '742cdb3ec4cec487a805db0b9b66b75aed8d0fddc2f64b3aee379d0755dac70f'
ORT_MANIFEST = '0e195f8718ea5c1f42401e99845f018a5f8e4022b4eb9cf1f237a5f4a26ec52a'
ASSETS = (
  {'run': 45828010095, 'head': '92aa9e0ca76bf28b2aa43eebbf3cfe4d8e6fc2b2',
   'artifact': 'visionworkshop-core-candidate-45828010095-1', 'id': 15128429321,
   'outer_bytes': 180449661, 'outer_sha256': '3d8d63f307f683f1e5a008bb829a52894dcf9ac6ccf8834db6e5e1e6a3edd2d7',
   'name': 'VisionWorkshop-Core-0.0.0.zip', 'bytes': 180449489,
   'sha256': '5908f21e927b47f228cb60262bbe32b2c7271a4f149d5aa8497ada749b1222ec'},
  {'run': 45616400076, 'head': 'f9703a9c6a0c0370a10eed0afadd39e677770547',
   'artifact': 'visionworkshop-module-resource.edgesam-45616400076-1', 'id': 15029996683,
   'outer_bytes': 35561103, 'outer_sha256': '4189832f2263c43b39cbdcc32230a52886818ee70e93c9b9248f847062cab9b7',
   'name': 'resource.edgesam-0.0.0.zip', 'bytes': 35560937,
   'sha256': 'fc8f55a868dc640adea28d1a18f7be0416c069e2a5a2870db82b701daac4b553'},
  {'run': 45616400076, 'head': 'f9703a9c6a0c0370a10eed0afadd39e677770547',
   'artifact': 'visionworkshop-module-runtime.ort-45616400076-1', 'id': 15029901741,
   'outer_bytes': 113428375, 'outer_sha256': '19a0a8ce5e3e54f85f810902b48e7ffd9ca2858204a6626bc3b3d345ba3272cd',
   'name': 'runtime.ort-0.0.0.zip', 'bytes': 113428219,
   'sha256': 'cb52bcffd03aefac8fd7aa3ce7b8ce80ac9509ed4f87c776b218c0439d903d5a'},
)


def require(condition, message):
  if not condition:
    raise RuntimeError(message)


def checkAsset(path, record):
  require(path.stat().st_size == record['bytes'] and fileHash(path) == record['sha256'],
          'The staged original archive differs: ' + path.name)


def prepare(root, assets=ASSETS):
  root.mkdir(parents=True, exist_ok=False)
  reports = root / 'reports'
  reports.mkdir()
  receipts = []
  try:
    for record in assets:
      endpoint = '/actions/runs/' + str(record['run'])
      run = sourceRun(apiJson(endpoint), record['run'], 1)
      require(run['head_sha'] == record['head'], 'Artifact source commit changed')
      artifact = selectArtifact(apiJson(endpoint + '/artifacts?per_page=100')['artifacts'], record['artifact'], run)
      require((artifact['id'], artifact['size_in_bytes'], artifact['digest']) ==
              (record['id'], record['outer_bytes'], 'sha256:' + record['outer_sha256']),
              'Artifact identity changed')
      outer = root / (str(artifact['id']) + '.zip')
      downloadArtifact(artifact, outer, maximumBytes=record['outer_bytes'])
      with zipfile.ZipFile(outer) as archive:
        members = archive.infolist()
        require(len(members) == 1 and (members[0].filename, members[0].file_size, members[0].compress_type) ==
                (record['name'], record['bytes'], zipfile.ZIP_STORED), 'Unexpected outer artifact entry')
        target = root / record['name']
        with archive.open(members[0]) as source, target.open('xb') as destination:
          shutil.copyfileobj(source, destination)
      checkAsset(target, record)
      receipts.append({'run': run, 'artifact': artifact, 'archive': record['name'], 'sha256': record['sha256']})
  finally:
    writeReport(reports / 'archived-inputs.json', {'files': receipts})


def powershell(reports, label, environment, command):
  shell = shutil.which('pwsh')
  require(shell is not None, 'PowerShell is absent on the hosted runner')
  process = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command',
                            "$ErrorActionPreference='Stop'; " + command], capture_output=True,
                           env=environment, timeout=45, check=False)
  (reports / (label + '.stdout.txt')).write_bytes(process.stdout)
  (reports / (label + '.stderr.txt')).write_bytes(process.stderr)
  require(process.returncode == 0, 'Firewall operation failed: ' + label)


def verify(root):
  reports = root / 'reports'
  summary = {'status': 'FAIL', 'scope': 'Hosted Windows native outbound application firewall block',
             'all_network_adapters_disconnected': False, 'gpu': 'NOT_RUN', 'probes': {}, 'integrity': []}
  try:
    require(os.name == 'nt' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted',
            'Firewall diagnostic must run in a disposable GitHub-hosted Windows VM')
    for record in ASSETS:
      checkAsset(root / record['name'], record)
    executable = extractCore(root / ASSETS[0]['name'], root / 'extracted')
    core = executable.parent
    require(fileHash(executable) == CORE_EXE and fileHash(core / 'core.json') == CORE_MANIFEST,
            'Original frozen Core identity is incorrect')
    baseline = coreInventory(core)
    metadata = json.loads((core / 'core.json').read_bytes())
    edgeArchive, ortArchive = (root / item['name'] for item in ASSETS[1:])
    (root / 'empty-cwd').mkdir()
    environment = productEnvironment(root)
    environment.update(VW_NET_TEST_RULE='VisionWorkshop offline CI ' + uuid.uuid4().hex,
                       VW_NET_TEST_EXE=str(executable))
    address = socket.getaddrinfo('api.github.com', 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    curl = Path(os.environ['SystemRoot']) / 'System32/curl.exe'
    probe = root / 'probe-control.exe'
    shutil.copyfile(curl, probe)

    def networkProbe(name, program, expected):
      result = subprocess.run([program, '--silent', '--show-error', '--output', os.devnull,
        '--ipv4', '--noproxy', '*', '--connect-timeout', '5', '--max-time', '10',
        '--resolve', 'api.github.com:443:' + address, 'https://api.github.com/'],
        capture_output=True, timeout=15, env=environment, check=False)
      summary['probes'][name] = {'exit_code': result.returncode,
                                 'stderr': result.stderr.decode('utf-8', errors='replace')}
      require(result.returncode in expected, 'Unexpected live TCP/TLS control: ' + name)

    held = root / 'verified-original.exe'
    executable.replace(held)
    shutil.copyfile(curl, executable)
    try:
      networkProbe('before-program-rule', executable, {0})
      powershell(reports, 'apply-exact-program-block', environment, """
        $rule = New-NetFirewallRule -DisplayName $env:VW_NET_TEST_RULE -Name $env:VW_NET_TEST_RULE `
          -Program $env:VW_NET_TEST_EXE -Profile Any -Direction Outbound -Protocol Any -Action Block -Enabled True
        $active = Get-NetFirewallRule -PolicyStore ActiveStore -Name $rule.Name
        $application = $active | Get-NetFirewallApplicationFilter
        if ($active.Direction -ne 'Outbound' -or $active.Enabled -ne 'True' -or $active.Action -ne 'Block' `
            -or $application.Program -ne $env:VW_NET_TEST_EXE) { throw 'Unexpected program rule' }
        $active | Format-List Name, Enabled, Direction, Profile, Action
        $application | Format-List Program
        """)
      networkProbe('exact-program-blocked', executable, {7, 28})
      networkProbe('sibling-program-unaffected', probe, {0})
      held.replace(executable)
      require(fileHash(executable) == CORE_EXE, 'App path no longer holds the original EXE')

      first, _ = cli(executable, ['status'], reports, 'empty', environment)
      initial = activeIdentity(first, CORE_MANIFEST)
      require(not initial['modules'], 'Expected an empty Core')
      installed, _ = cli(executable, ['install', str(edgeArchive), str(ortArchive)], reports,
                         'original-install', environment)
      recorded = {row['module_id']: row['sha256'] for row in installed['result']['archives']}
      require(installed['result']['pending'] and len(installed['result']['archives']) == 2 and
              recorded == {'resource.edgesam': ASSETS[1]['sha256'], 'runtime.ort': ASSETS[2]['sha256']},
              'Unexpected original install receipt')
      activated, _ = cli(executable, ['activate'], reports, 'original-activate', environment)
      identity = activeIdentity(activated, CORE_MANIFEST)
      require(identity['modules'] == {'resource.edgesam': EDGE_MANIFEST, 'runtime.ort': ORT_MANIFEST},
              'Wrong original modules are active')

      def checkpoint(name):
        summary['integrity'].append(verifyCoreUnchanged(core, baseline, reports, name))

      summary['repair'] = verifyColdRepair(executable, ortArchive, reports, environment, identity)
      checkpoint('cold-ort-repair')
      transaction, restored = verifySingleModuleUpdate(executable, edgeArchive, reports, environment, identity,
                                                       metadata, checkpoint)
      summary.update(initial=initial, installed=identity, restored=restored, transaction=transaction['status'])
      executable.replace(held)
      shutil.copyfile(curl, executable)
      networkProbe('program-still-blocked-after-lifecycle', executable, {7, 28})
    finally:
      try:
        powershell(reports, 'remove-exact-program-block', environment, """
          $rule = Get-NetFirewallRule -Name $env:VW_NET_TEST_RULE -ErrorAction SilentlyContinue
          if ($rule) { $rule | Remove-NetFirewallRule }
          if (Get-NetFirewallRule -Name $env:VW_NET_TEST_RULE -ErrorAction SilentlyContinue) { throw 'Test rule remains' }
          """)
        summary['firewall_cleanup'] = 'PASS'
        if held.is_file():
          networkProbe('connectivity-restored', executable, {0})
      finally:
        if held.is_file():
          held.replace(executable)
    checkpoint('final')
    summary['status'] = 'PASS'
  except BaseException as error:
    summary['error'] = str(error)
    raise
  finally:
    writeReport(reports / 'outbound-block-summary.json', summary)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('mode', choices=('prepare', 'verify'))
  parser.add_argument('output', type=Path)
  args = parser.parse_args()
  {'prepare': prepare, 'verify': verify}[args.mode](args.output.resolve())
