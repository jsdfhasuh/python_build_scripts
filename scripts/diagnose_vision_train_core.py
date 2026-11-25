"""Repeat an immutable Core's exit failure and read matching Windows crash events.

This is a diagnostic, not a new candidate build or complete product qualification.
"""

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_config import BuildConfigError, readJsonObject, validateFileName
from build_records import fileHash, objectHash, scanFiles
from vision_train_modular_build import loadContract
from vision_train_modular_reuse import (
  apiJson, boundedLzmaMember, downloadArtifact, readEvidenceMember,
  selectArtifact, sourceRun, writeJson, MAX_EVIDENCE_ARTIFACT_BYTES,
)
from scripts.verify_vision_train_modular_product import (
  checkCase, coreInventory, productEnvironment, terminateTree, verifyCoreUnchanged,
)
from scripts.vision_train_native_debug import debugProcess

SUMMARY = 'modular-candidate/reports/modular-build-summary.json'
INVENTORY = 'modular-candidate/reports/core-files.json'
PRODUCT = 'modular-acceptance/reports/modular-product-summary.json'
MAX_CORE_ZIP = 512 * 1024**2
MAX_CORE_EXPANDED = 2 * 1024**3
MAX_EVENTS = 64
EVENT_NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}


def require(value, message):
  if not value:
    raise BuildConfigError(message)


def digest(data):
  return hashlib.sha256(data).hexdigest()


def relativePath(value):
  require(isinstance(value, str) and value and '\\' not in value,
          'Expected a relative POSIX inventory path')
  path = PurePosixPath(value)
  require(not path.is_absolute() and path.as_posix() == value
          and all(part not in ('.', '..') for part in path.parts), 'Unsafe Core path')
  for part in path.parts:
    validateFileName(part, 'Diagnostic Core path')
  return path


def validateRequest(request):
  fields = {'schema_version', 'diagnostic_attempt', 'source_run_id',
            'source_run_attempt', 'source_head_sha', 'source_app_sha', 'core_sha256',
            'core_archive', 'artifacts', 'normal_gui_comparison'}
  if request.get('schema_version') == 2:
    fields.update(('debugger_observed', 'dll_search_probe'))
    require(request.get('debugger_observed') is True and request.get('dll_search_probe') is True,
            'Schema 2 requires explicit debugger and DLL-search observations')
  require(set(request) == fields, 'Unexpected diagnostic request fields')
  require(type(request['schema_version']) is int and request['schema_version'] in (1, 2),
          'Unknown diagnostic request schema')
  for key in ('diagnostic_attempt', 'source_run_id', 'source_run_attempt'):
    require(type(request[key]) is int and request[key] > 0, 'Expected a positive exact run/attempt')
  for key, count in (('source_head_sha', 40), ('source_app_sha', 40), ('core_sha256', 64)):
    require(isinstance(request[key], str) and re.fullmatch('[a-f0-9]{' + str(count) + '}', request[key]),
            'Invalid exact source identity')
  require(type(request['normal_gui_comparison']) is bool, 'GUI comparison must be explicit')
  require(set(request['artifacts']) == {'core', 'evidence'}, 'Only Core and evidence may be downloaded')
  for role, record in [('archive', request['core_archive']), *request['artifacts'].items()]:
    require(set(record) == ({'name', 'bytes', 'sha256'} if role == 'archive'
                            else {'id', 'name', 'bytes', 'sha256'}), 'Unexpected asset fields')
    require(isinstance(record['name'], str) and len(relativePath(record['name']).parts) == 1,
            'Asset name must be one safe basename')
    maximum = MAX_EVIDENCE_ARTIFACT_BYTES if role == 'evidence' else MAX_CORE_ZIP + 1024**2
    require(type(record['bytes']) is int and 0 < record['bytes'] <= maximum,
            'Diagnostic asset exceeds its fixed size bound')
    require(isinstance(record['sha256'], str) and re.fullmatch('[a-f0-9]{64}', record['sha256']),
            'Asset requires an exact SHA256')
    if role != 'archive':
      require(type(record['id']) is int and record['id'] > 0, 'Artifact ID must be a positive integer')
  require(request['core_archive']['name'].startswith('VisionWorkshop-Core-')
          and request['core_archive']['name'].endswith('.zip')
          and request['core_archive']['bytes'] <= MAX_CORE_ZIP, 'Unexpected Core archive')
  return request


def assetMatches(path, record):
  require(path.is_file() and path.stat().st_size == record['bytes']
          and fileHash(path) == record['sha256'], 'Source asset size/SHA256 changed')


def sourceEvidence(path, request):
  assetMatches(path, request['artifacts']['evidence'])
  with zipfile.ZipFile(path) as archive:
    raw = {name: readEvidenceMember(archive, name) for name in (SUMMARY, INVENTORY, PRODUCT)}
  summary, inventory, product = (json.loads(raw[name]) for name in (SUMMARY, INVENTORY, PRODUCT))
  build = {'app_sha': request['source_app_sha'], 'packager_sha': request['source_head_sha'],
           'build_id': 'candidate-' + str(request['source_run_id']) + '-' + str(request['source_run_attempt'])}
  require(summary.get('status') == 'BUILT' and summary['core']['build'] == build
          and summary.get('source', {}).get('commit') == build['app_sha']
          and summary.get('packager', {}).get('commit') == build['packager_sha']
          and summary.get('core_sha256') == request['core_sha256'], 'Source build identity is not exact')
  archive = summary['core_archive']
  require(PureWindowsPath(archive['path']).name == request['core_archive']['name']
          and all(archive[key] == request['core_archive'][key] for key in ('bytes', 'sha256'))
          and archive.get('verified') is True and archive.get('compression') == 'zip/lzma',
          'Source Core ZIP is not the verified requested archive')
  require(product.get('build') == build and product.get('core_sha256') == request['core_sha256'],
          'Original product result belongs to a different Core')
  files = {}
  folded = set()
  for item in inventory['files']:
    require(set(item) == {'path', 'size', 'sha256'}, 'Unexpected Core inventory fields')
    name = str(relativePath(item['path']))
    require(name.casefold() not in folded and type(item['size']) is int and item['size'] >= 0
            and re.fullmatch('[a-f0-9]{64}', item['sha256']), 'Duplicate or invalid Core inventory')
    require(PurePosixPath(name).parts[0] not in ('.module-state', 'modules'),
            'Original Core must not contain installed module state')
    files[name] = {key: item[key] for key in ('size', 'sha256')}
    folded.add(name.casefold())
  require(len(files) == archive['file_count'] and 0 < len(files) <= 100000
          and sum(item['size'] for item in files.values()) == archive['expanded_bytes']
          and 0 < archive['expanded_bytes'] <= MAX_CORE_EXPANDED
          and files['core.json']['sha256'] == request['core_sha256'],
          'Original Core inventory does not match its archive/manifest')
  return {'summary': summary, 'files': files, 'product': product,
          'reports': {name: {'bytes': len(data), 'sha256': digest(data)} for name, data in raw.items()}}


def prepare(requestPath, output):
  require(not output.exists(), 'Diagnostic preparation directory must be new')
  request = validateRequest(readJsonObject(requestPath))
  output.mkdir(parents=True)
  run = sourceRun(apiJson('/actions/runs/' + str(request['source_run_id'])),
                  request['source_run_id'], request['source_run_attempt'])
  require(run['head_sha'] == request['source_head_sha'], 'Source run head differs from request')
  listing = apiJson('/actions/runs/' + str(run['id']) + '/artifacts?per_page=100')
  require(listing['total_count'] == len(listing['artifacts']), 'Source artifact listing is incomplete')
  receipt = {'schema_version': 1, 'status': 'PREPARED', 'request': request, 'source_run': run,
             'diagnostic_builder_sha': os.environ.get('GITHUB_SHA'), 'artifacts': {}}
  for role in ('evidence', 'core'):
    expected = request['artifacts'][role]
    artifact = selectArtifact(listing['artifacts'], expected['name'], run)
    require(artifact['id'] == expected['id'] and artifact['size_in_bytes'] == expected['bytes']
            and artifact['digest'] == 'sha256:' + expected['sha256'], 'Artifact differs from reviewed request')
    target = output / (role + '-artifact.zip')
    downloadArtifact(artifact, target, maximumBytes=(MAX_EVIDENCE_ARTIFACT_BYTES
                     if role == 'evidence' else MAX_CORE_ZIP + 1024**2))
    receipt['artifacts'][role] = artifact
  evidence = sourceEvidence(output / 'evidence-artifact.zip', request)
  receipt.update(source_build=evidence['summary']['core']['build'],
                 source_product_status=evidence['product']['status'], reports=evidence['reports'])
  with zipfile.ZipFile(output / 'core-artifact.zip') as archive:
    members = archive.infolist()
    require(len(members) == 1 and members[0].filename == request['core_archive']['name']
            and not members[0].is_dir() and members[0].file_size == request['core_archive']['bytes']
            and members[0].compress_type == zipfile.ZIP_STORED and not members[0].flag_bits & 1,
            'Core artifact must contain only the original uncompressed ZIP member')
    with archive.open(members[0]) as reader, (output / request['core_archive']['name']).open('xb') as writer:
      shutil.copyfileobj(reader, writer, 1024**2)
  assetMatches(output / request['core_archive']['name'], request['core_archive'])
  writeJson(output / 'source-receipt.json', receipt)
  return receipt


def extractCore(source, evidence, request, output):
  require(not output.exists(), 'Every diagnostic installation must be freshly extracted')
  archivePath = source / request['core_archive']['name']
  assetMatches(archivePath, request['core_archive'])
  expected = {'VisionWorkshop/' + name: record for name, record in evidence['files'].items()}
  with zipfile.ZipFile(archivePath) as archive:
    members = archive.infolist()
    require(len(members) == len(expected) and {x.filename for x in members} == set(expected),
            'Core ZIP has missing, duplicate or extra members')
    require(sum(x.file_size for x in members) == evidence['summary']['core_archive']['expanded_bytes']
            and sum(x.compress_size for x in members)
            == evidence['summary']['core_archive']['compressed_payload_bytes'], 'Core ZIP totals differ')
    for member in members:
      boundedLzmaMember(archive, member)
      relativePath(member.filename)
      require(member.file_size == expected[member.filename]['size'], 'Core ZIP member size differs')
    output.mkdir(parents=True)
    for member in members:
      target = output / member.filename
      target.parent.mkdir(parents=True, exist_ok=True)
      h, total = hashlib.sha256(), 0
      with archive.open(member) as reader, target.open('xb') as writer:
        for chunk in iter(lambda: reader.read(1024**2), b''):
          total += len(chunk)
          require(total <= member.file_size, 'Core ZIP member expanded beyond its bound')
          h.update(chunk)
          writer.write(chunk)
      require(total == member.file_size and h.hexdigest() == expected[member.filename]['sha256'],
              'Extracted Core file differs from original source inventory')
  assetMatches(archivePath, request['core_archive'])
  root = output / 'VisionWorkshop'
  require(scanFiles(root) == evidence['files'], 'Extracted Core inventory changed')
  core = readJsonObject(root / 'core.json')
  require(core == evidence['summary']['core'] and fileHash(root / 'core.json') == request['core_sha256'],
          'Extracted Core identity differs from source')
  # Only now may code from the original Core be imported by the diagnostic driver.
  contract = loadContract(root / 'python')
  contract.validate_core(core)
  require(contract.manifest_digest(core) == request['core_sha256'], 'Noncanonical Core identity')
  require(scanFiles(root) == evidence['files'], 'Importing the verified contract altered Core')
  return root, core


def eventTime(value):
  return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def failureReportId(value):
  if not isinstance(value, str):
    return None
  pattern = r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}'
  if not re.fullmatch('(?:' + pattern + r'|\{' + pattern + r'\})', value):
    return None
  parsed = uuid.UUID(value.strip('{}'))
  return str(parsed) if parsed.int else None


def matchEvents(raw, pid, executable, start, end):
  require(type(pid) is int and pid > 0 and len(raw) <= 8 * 1024**2, 'Invalid event query bound')
  if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
    decoded = raw.decode('utf-16')
  elif raw.startswith(b'<\x00'):
    decoded = raw.decode('utf-16-le')
  elif raw.startswith(b'\x00<'):
    decoded = raw.decode('utf-16-be')
  else:
    decoded = raw.decode('utf-8-sig')
  require('<!DOCTYPE' not in decoded.upper(), 'Event XML must not contain a document type')
  root = ET.fromstring(raw)
  records = []
  for event in root.findall('e:Event', EVENT_NS):
    system = event.find('e:System', EVENT_NS)
    fields = {}
    for node in event.findall('e:EventData/e:Data', EVENT_NS):
      name = node.get('Name')
      require(name and name not in fields, 'Ambiguous unnamed/duplicate crash event data')
      fields[name] = node.text or ''
    created = system.find('e:TimeCreated', EVENT_NS).get('SystemTime')
    if not start <= eventTime(created) <= end:
      continue
    records.append({'event_id': int(system.findtext('e:EventID', namespaces=EVENT_NS)),
                    'provider': system.find('e:Provider', EVENT_NS).get('Name'),
                    'record_id': system.findtext('e:EventRecordID', namespaces=EVENT_NS),
                    'time_utc': created, 'fields': fields,
                    'xml': ET.tostring(event, encoding='unicode')})
  require(len(records) <= MAX_EVENTS, 'Event query returned too many records')
  matches = []
  for record in records:
    fields = record['fields']
    try:
      targetPid = int(fields.get('ProcessId', ''), 16 if fields.get('ProcessId', '').lower().startswith('0x') else 10)
    except ValueError:
      continue
    if (record['event_id'] == 1000 and record['provider'] == 'Application Error' and targetPid == pid
        and ntpath.normcase(ntpath.normpath(fields.get('AppPath', ''))) == ntpath.normcase(ntpath.normpath(executable))):
      matches.append(dict(record, correlation='target PID, complete EXE path and bounded UTC window'))
  reportIds = {failureReportId(r['fields'].get('IntegratorReportId')) for r in matches} - {None}
  related = [dict(r, correlation='same ReportId as the exact PID/EXE/time-bound Application Error')
             for r in records if r['event_id'] == 1001 and r['provider'] == 'Windows Error Reporting'
             and failureReportId(r['fields'].get('ReportId')) in reportIds
             and r['fields'].get('P1', '').casefold() == PureWindowsPath(executable).name.casefold()]
  return {'status': 'MATCHED' if matches else 'NO_MATCH', 'application_errors': matches,
          'related_wer': related, 'queried_events': len(records),
          'scope': 'Read-only event correlation; no native stack or current revocation claim'}


def collectEvents(pid, executable, start, end, reports, name):
  result = {'status': 'ERROR', 'pid': pid, 'executable': str(executable),
            'start_utc': start.isoformat(), 'process_end_utc': end.isoformat()}
  try:
    # Allow event delivery without changing WER/Defender settings or retrying the product.
    time.sleep(5)
    queryEnd = datetime.now(timezone.utc)
    query = "*[System[(EventID=1000 or EventID=1001) and TimeCreated[@SystemTime>='" \
      + start.isoformat().replace('+00:00', 'Z') + "' and @SystemTime<='" \
      + queryEnd.isoformat().replace('+00:00', 'Z') + "']]]"
    command = [str(Path(os.environ['SystemRoot']) / 'System32/wevtutil.exe'), 'qe', 'Application',
               '/q:' + query, '/f:xml', '/e:Events', '/rd:true', '/uni:true', '/c:' + str(MAX_EVENTS)]
    rawPath = reports / (name + '-events.xml')
    with rawPath.open('xb') as stdout, (reports / (name + '-events.stderr.txt')).open('xb') as stderr:
      completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=30, check=False)
    result.update(query=command, query_exit_code=completed.returncode, query_end_utc=queryEnd.isoformat())
    require(completed.returncode == 0 and rawPath.stat().st_size <= 8 * 1024**2,
            'Windows event query failed or exceeded its bound')
    result.update(matchEvents(rawPath.read_bytes(), pid, str(executable), start, queryEnd),
                  raw_xml={'path': rawPath.name, 'bytes': rawPath.stat().st_size, 'sha256': fileHash(rawPath)})
  except Exception as error:
    result.update(error=str(error), traceback=traceback.format_exc())
  writeJson(reports / (name + '-events.json'), result)
  return result


def visibleProductWindows(pid):
  from ctypes import wintypes
  api = ctypes.WinDLL('user32', use_last_error=True)
  callbackType = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
  api.EnumWindows.argtypes = [callbackType, wintypes.LPARAM]
  api.EnumWindows.restype = wintypes.BOOL
  api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
  api.GetWindowThreadProcessId.restype = wintypes.DWORD
  for name in ('IsWindowVisible', 'IsWindowEnabled'):
    getattr(api, name).argtypes = [wintypes.HWND]
    getattr(api, name).restype = wintypes.BOOL
  for name in ('GetWindowTextW', 'GetClassNameW'):
    getattr(api, name).argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    getattr(api, name).restype = ctypes.c_int
  records = []
  @callbackType
  def visit(hwnd, _):
    owner = wintypes.DWORD()
    api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value == pid:
      title, kind = ctypes.create_unicode_buffer(1024), ctypes.create_unicode_buffer(256)
      api.GetWindowTextW(hwnd, title, len(title))
      api.GetClassNameW(hwnd, kind, len(kind))
      records.append({'hwnd': int(hwnd), 'pid': owner.value, 'title': title.value, 'class': kind.value,
                      'visible': bool(api.IsWindowVisible(hwnd)), 'enabled': bool(api.IsWindowEnabled(hwnd))})
    return True
  require(api.EnumWindows(visit, 0), 'Cannot enumerate the owned product windows')
  return records


def selectWindow(records, pid):
  matches = [r for r in records if r.get('pid') == pid and r.get('title') == 'VisionWorkshop'
             and r.get('visible') is True and r.get('enabled') is True]
  require(len(matches) <= 1, 'Ambiguous visible product window')
  return matches[0] if matches else None


def stableWindow(records, pid, state, now):
  window = selectWindow(records, pid)
  if window is None:
    state.clear()
    return None
  if state.get('window') != window:
    state.update(window=window, since=now, observations=1, stable_seconds=0)
  else:
    state['observations'] += 1
    state['stable_seconds'] = now - state['since']
  return window if state['stable_seconds'] >= 1.0 else None


def cleanupGuiProcess(process, reports, record):
  record.setdefault('exit_code', process.poll())
  if process.poll() is None:
    record.update(status='FAIL', forced_cleanup=True, cleanup_errors=[])
    try:
      terminateTree(process, reports)
    except Exception as error:
      record['cleanup_errors'].append(type(error).__name__ + ': ' + str(error))
    finally:
      if process.poll() is None:
        try:
          process.kill()
        except Exception as error:
          record['cleanup_errors'].append(type(error).__name__ + ': ' + str(error))
      try:
        process.wait(timeout=15)
      except Exception as error:
        record['cleanup_errors'].append(type(error).__name__ + ': ' + str(error))
    record['cleanup_exit_code'] = process.returncode


def normalGui(executable, environment, reports):
  from ctypes import wintypes
  record = {'status': 'FAIL', 'command': [str(executable)], 'forced_cleanup': False,
            'scope': 'Unmodified no-argument GUI, owned visible enabled window, normal WM_CLOSE exit only'}
  with (reports / 'gui-close.stdout.txt').open('w', encoding='utf-8') as stdout, \
       (reports / 'gui-close.stderr.txt').open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen(record['command'], cwd=reports.parent / 'empty-cwd', env=environment,
                               stdout=stdout, stderr=stderr)
    record['pid'] = process.pid
    try:
      deadline = time.monotonic() + 90
      window = None
      stability = {}
      while process.poll() is None and time.monotonic() < deadline:
        record['observed_windows'] = visibleProductWindows(process.pid)
        window = stableWindow(record['observed_windows'], process.pid, stability, time.monotonic())
        record['window_stability'] = dict(stability, minimum_seconds=1.0)
        if window is not None:
          break
        time.sleep(0.2)
      require(window is not None and process.poll() is None, 'The normal GUI did not expose its owned window')
      # Re-observe immediately before posting; never close another PID or a disabled dialog.
      require(window in visibleProductWindows(process.pid) and process.poll() is None,
              'The selected window changed before WM_CLOSE')
      api = ctypes.WinDLL('user32', use_last_error=True)
      api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
      api.PostMessageW.restype = wintypes.BOOL
      require(api.PostMessageW(window['hwnd'], 0x0010, 0, 0), 'WM_CLOSE was not posted')
      record.update(close_window=window, close_message='WM_CLOSE')
      record['exit_code'] = process.wait(timeout=45)
      require(record['exit_code'] == 0, 'Normal GUI exited with ' + str(record['exit_code']))
      record['status'] = 'PASS'
    except Exception as error:
      record.update(error=str(error), traceback=traceback.format_exc())
    finally:
      try:
        cleanupGuiProcess(process, reports, record)
      finally:
        writeJson(reports / 'gui-close.process.json', record)
  return record


def debugCase(executable, environment, reports, name, coreDigest):
  output = reports / (name + '.json')
  require(not output.exists(), 'Debugger case output must be new')
  command = [str(executable)]
  closeWindow = None
  if name == 'core-without-modules':
    command.extend(['--modular-runtime-check', '--case', 'core', '--output', str(output)])
  else:
    stability = {}
    def closeWindow(pid, record, elapsed):
      gui = record.setdefault('gui', {})
      if gui.get('close_message'):
        return
      require(elapsed < 90, 'Debugger-observed GUI did not expose a stable owned window')
      records = visibleProductWindows(pid)
      gui['observed_windows'] = records
      window = stableWindow(records, pid, stability, time.monotonic())
      gui['window_stability'] = dict(stability, minimum_seconds=1.0)
      if window is None:
        return
      require(window in visibleProductWindows(pid), 'Owned debugger-observed window changed before close')
      from ctypes import wintypes
      api = ctypes.WinDLL('user32', use_last_error=True)
      api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
      api.PostMessageW.restype = wintypes.BOOL
      require(api.PostMessageW(window['hwnd'], 0x0010, 0, 0), 'Debugger-observed WM_CLOSE failed')
      gui.update(close_message='WM_CLOSE', close_window=window)
  native = debugProcess(command, reports, environment, timeout=300 if closeWindow is None else 135,
                        closeWindow=closeWindow)
  process = {key: native.get(key) for key in ('status', 'command', 'pid', 'exit_code',
             'debug_exit_code', 'elapsed_seconds', 'debugger_observed', 'forced_cleanup', 'error')}
  process['native_report'] = {'path': 'native-debug.json', 'sha256': fileHash(reports / 'native-debug.json')}
  writeJson(reports / (name + '.process.json'), process)
  result = {'status': 'FAIL', 'process': process}
  try:
    require(native['status'] == 'PASS' and native.get('exit_code') == 0,
            'Debugger-observed process did not exit successfully: ' + str(native.get('exit_code')))
    if name == 'core-without-modules':
      report = readJsonObject(output)
      require(report.get('status') == 'PASS' and report.get('case') == 'core'
              and report.get('pid') == native['pid'] and report.get('frozen') is True
              and Path(report.get('executable', '')).resolve() == executable.resolve()
              and report.get('runtime_identity') == {'core_sha256': coreDigest, 'generation': 0, 'modules': {}},
              'Debugger-observed Core report is incomplete or has a different identity')
      result['internal_report_sha256'] = fileHash(output)
    else:
      require(native.get('gui', {}).get('close_message') == 'WM_CLOSE', 'No owned normal close was observed')
    result['status'] = 'PASS'
  except Exception as error:
    result.update(error=str(error), traceback=traceback.format_exc())
  if output.is_file() and name == 'core-without-modules':
    result['internal_report'] = readJsonObject(output)
  return result


def dllSearchProbe(source, output, evidence, request):
  # Retain the first diagnostic's longer path for this separate API observation.
  case = output / 'core-without-modules'
  reports = case / 'reports'
  reports.mkdir(parents=True)
  (case / 'empty-cwd').mkdir()
  root, _ = extractCore(source, evidence, request, case / '中文 模块验收')
  plan = reports / 'dll-search-input.json'
  writeJson(plan, {'core_root': str(root), 'core_sha256': request['core_sha256']})
  result = {'status': 'FAIL', 'root': str(root), 'root_unicode_characters': len(str(root)),
            'root_utf16_bytes': len(str(root).encode('utf-16-le')), 'observations': []}
  try:
    for mode in ('duplicate', 'unique'):
      destination = reports / ('dll-search-' + mode + '.json')
      command = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve().with_name('vision_train_dll_search_probe.py')),
                 '--input', str(plan), '--mode', mode, '--output', str(destination)]
      process = subprocess.Popen(command, cwd=case / 'empty-cwd', env=productEnvironment(case),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      record = {'mode': mode, 'pid': process.pid, 'command': command}
      try:
        stdout, stderr = process.communicate(timeout=60)
        (reports / ('dll-search-' + mode + '.stdout.txt')).write_bytes(stdout)
        (reports / ('dll-search-' + mode + '.stderr.txt')).write_bytes(stderr)
        record['exit_code'] = process.returncode
        require(process.returncode == 0, 'DLL registration observer failed')
        observation = readJsonObject(destination)
        require(observation.get('status') == 'OBSERVED' and observation.get('pid') == process.pid
                and observation.get('core_sha256') == request['core_sha256']
                and observation.get('input_sha256') == fileHash(plan) and observation.get('mode') == mode
                and observation.get('handles_closed') == observation.get('successful_directory_count')
                and not observation.get('cleanup_errors'), 'DLL observation identity or cleanup failed')
        record['observation'] = observation
        record['report_sha256'] = fileHash(destination)
      finally:
        if process.poll() is None:
          process.kill()
          process.wait(timeout=15)
        result['observations'].append(record)
    result['status'] = 'OBSERVED'
  except Exception as error:
    result.update(error=str(error), traceback=traceback.format_exc())
  finally:
    result['core_unchanged'] = verifyCoreUnchanged(root, evidence['files'], reports, 'after-dll-probe')
    writeJson(reports / 'dll-search-summary.json', result)
  return result


def run(source, output, requestPath):
  require(os.name == 'nt', 'Core exit diagnostics require actual Windows')
  require(not output.exists(), 'Diagnostic run directory must be new')
  output.mkdir(parents=True)
  receipt = readJsonObject(source / 'source-receipt.json')
  request = validateRequest(readJsonObject(requestPath))
  require(receipt.get('status') == 'PREPARED' and receipt.get('request') == request,
          'Prepared source differs from the independently reviewed request')
  origin = receipt['source_run']
  require(origin.get('id') == request['source_run_id'] and origin.get('run_attempt') == request['source_run_attempt']
          and origin.get('head_sha') == request['source_head_sha'] and origin.get('status') == 'completed',
          'Prepared source run identity changed')
  for role in ('evidence', 'core'):
    expected = request['artifacts'][role]
    actual = selectArtifact([receipt['artifacts'][role]], expected['name'], origin)
    require(actual['id'] == expected['id'] and actual['size_in_bytes'] == expected['bytes']
            and actual['digest'] == 'sha256:' + expected['sha256'], 'Prepared artifact identity changed')
    assetMatches(source / (role + '-artifact.zip'), expected)
  evidence = sourceEvidence(source / 'evidence-artifact.zip', request)
  require(receipt.get('reports') == evidence['reports']
          and receipt.get('source_build') == evidence['summary']['core']['build']
          and receipt.get('source_product_status') == evidence['product']['status'],
          'Prepared evidence binding changed')
  result = {'status': 'FAIL', 'published': False, 'source_request': request,
            'source_build': evidence['summary']['core']['build'],
            'source_product_status': evidence['product']['status'],
            'diagnostic_builder_sha': os.environ.get('GITHUB_SHA'), 'cases': [],
            'debugger_observed': request.get('debugger_observed', False),
            'scope': 'Original immutable Core diagnostic observations; no rebuild/modules/full candidate matrix'}
  try:
    if request.get('dll_search_probe'):
      result['dll_search_probe'] = dllSearchProbe(source, output, evidence, request)
    for name in (['core-without-modules', 'gui-close'] if request['normal_gui_comparison'] else ['core-without-modules']):
      observed = request.get('debugger_observed', False)
      caseOutput = output / (('c' if name == 'core-without-modules' else 'g') if observed else name)
      reports = caseOutput / 'reports'
      reports.mkdir(parents=True)
      (caseOutput / 'empty-cwd').mkdir()
      root, core = extractCore(source, evidence, request, caseOutput / ('中 文' if observed else '中文 模块验收'))
      executable = root / 'VisionWorkshop.exe'
      environment = productEnvironment(caseOutput)
      start = datetime.now(timezone.utc)
      record = {'name': name, 'status': 'FAIL', 'executable_sha256': fileHash(executable),
                'core_inventory_sha256': objectHash(evidence['files']), 'start_utc': start.isoformat(),
                'root_unicode_characters': len(str(root)), 'root_utf16_bytes': len(str(root).encode('utf-16-le')),
                'source_root_unicode_characters': len(str(PureWindowsPath(evidence['product']['executable']).parent)),
                'debugger_observed': observed}
      try:
        if observed:
          require(record['root_unicode_characters'] <= record['source_root_unicode_characters'],
                  'Debugger installation path exceeds the original candidate root length')
          record['result'] = debugCase(executable, environment, reports, name, request['core_sha256'])
          record['status'] = record['result']['status']
        elif name == 'core-without-modules':
          record['result'] = checkCase(executable, 'core', reports, name, environment, core,
            {'core_sha256': request['core_sha256'], 'generation': 0, 'modules': {}}, timeout=300)
          record['status'] = 'PASS'
        else:
          record['result'] = normalGui(executable, environment, reports)
          record['status'] = record['result']['status']
      except Exception as error:
        record.update(error=str(error), traceback=traceback.format_exc())
      finally:
        end = datetime.now(timezone.utc)
        record['end_utc'] = end.isoformat()
        processPath = reports / (name + '.process.json')
        if processPath.is_file():
          record['process'] = readJsonObject(processPath)
          if type(record['process'].get('pid')) is int and record['process']['pid'] > 0:
            record['events'] = collectEvents(record['process']['pid'], executable, start, end, reports, name)
        record['core_unchanged'] = verifyCoreUnchanged(root, evidence['files'], reports, 'after-exit')
        writeJson(reports / 'diagnostic-case.json', record)
        result['cases'].append(record)
    result['status'] = 'PASS' if (all(x['status'] == 'PASS' for x in result['cases'])
      and result.get('dll_search_probe', {}).get('status', 'OBSERVED') == 'OBSERVED') else 'FAIL'
  except Exception as error:
    result.update(error=str(error), traceback=traceback.format_exc())
  finally:
    writeJson(output / 'diagnostic-summary.json', result)
  return 0 if result['status'] == 'PASS' else 1


def main():
  sys.dont_write_bytecode = True
  parser = argparse.ArgumentParser(description=__doc__)
  modes = parser.add_subparsers(dest='mode', required=True)
  download = modes.add_parser('prepare')
  download.add_argument('--request', type=Path, required=True)
  download.add_argument('--output', type=Path, required=True)
  repeat = modes.add_parser('run')
  repeat.add_argument('--source', type=Path, required=True)
  repeat.add_argument('--output', type=Path, required=True)
  repeat.add_argument('--request', type=Path, required=True)
  args = parser.parse_args()
  if args.mode == 'prepare':
    prepare(args.request.resolve(), args.output.resolve())
    return 0
  return run(args.source.resolve(), args.output.resolve(), args.request.resolve())


if __name__ == '__main__':
  raise SystemExit(main())
