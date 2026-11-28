"""Emit bounded, hash-bound diagnostic report projections into CI logs.

Full source reports and the complete LOAD/UNLOAD inventory stay in the artifact.
This read-only log projection never changes a product or test result.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


MAX_SOURCE_BYTES = 8 * 1024**2
MAX_PROJECTION_BYTES = 128 * 1024
MAX_TOTAL_PROJECTION_BYTES = 1024 * 1024
CHUNK_CHARACTERS = 2048
PREFIX = 'VW_DIAGNOSTIC_CHUNK '


def require(value, message):
  if not value:
    raise ValueError(message)


def selected(value, keys):
  return {key: value[key] for key in keys if key in value}


def readReport(root, relative, maximumBytes=MAX_SOURCE_BYTES):
  parts = PurePosixPath(relative).parts
  require(parts and not PurePosixPath(relative).is_absolute() and '\\' not in relative
          and ':' not in relative and all(part not in ('.', '..') for part in parts), 'Unsafe report path')
  path = root.joinpath(*parts)
  require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(),
          'Report is outside its declared output root')
  if not path.exists():
    return {'path': relative, 'status': 'MISSING'}, None
  require(path.is_file(), 'Report is not a regular file')
  size = path.stat().st_size
  require(0 < size <= maximumBytes, 'Report exceeds its fixed read budget')
  raw = path.read_bytes()
  require(len(raw) == size, 'Report size changed during the read')
  identity = {'path': relative, 'status': 'READ', 'bytes': size,
              'sha256': hashlib.sha256(raw).hexdigest()}
  value = json.loads(raw)
  require(isinstance(value, dict), 'Report JSON must be an object')
  return identity, value


def nativeProjection(value):
  result = selected(value, ('status', 'debugger_observed', 'command', 'pid', 'timeout_seconds',
    'elapsed_seconds', 'exit_code', 'debug_exit_code', 'forced_cleanup', 'error', 'traceback',
    'stage', 'layout', 'initial_break_seen', 'gui', 'cleanup_errors', 'cleanup_events',
    'cleanup_exit_event_continued', 'cleanup_debug_exit_code', 'cleanup_exit_code',
    'cleanup_detached', 'cleanup_handle_ownership', 'scope'))
  # Keep every exception field, including active and unloaded instruction/access mappings.
  result['exceptions'] = value.get('exceptions', [])
  result['event_count'] = len(value.get('events', []))
  result['active_module_count'] = len(value.get('active_modules', []))
  result['unloaded_module_count'] = len(value.get('unloaded_modules', []))
  result['projection_scope'] = 'All exception records and exit/cleanup fields; full module/event inventory retained in source artifact'
  return result


def dllProjection(value):
  result = selected(value, ('status', 'root', 'root_unicode_characters', 'root_utf16_bytes',
                            'error', 'traceback', 'core_unchanged'))
  result['observations'] = []
  for item in value.get('observations', []):
    record = selected(item, ('mode', 'pid', 'command', 'exit_code', 'report_sha256'))
    data = item.get('observation', {})
    record['observation'] = selected(data, (
      'status', 'mode', 'pid', 'executable', 'input_sha256', 'core_sha256', 'core_root',
      'root_unicode_characters', 'root_utf16_bytes', 'planned_directory_count',
      'successful_directory_count', 'successful_utf16_bytes_with_nul', 'first_failure',
      'handles_closed', 'cleanup_errors', 'scope', 'budget_definition'))
    record['source_entry_count'] = len(data.get('entries', []))
    result['observations'].append(record)
  result['projection_scope'] = 'Complete first-failure and registration-count/budget/cleanup summary; individual successful registrations remain in artifact'
  return result



def caseProjection(value):
  return selected(value, (
    'name', 'mode', 'sequence', 'status', 'executable', 'executable_sha256',
    'core_inventory_sha256', 'installation_root', 'start_utc', 'end_utc', 'elapsed_seconds',
    'root_unicode_characters', 'root_utf16_bytes', 'source_root_unicode_characters',
    'debugger_observed', 'reports', 'cwd', 'environment', 'heap_behavior', 'error', 'traceback',
    'process', 'process_exited', 'core_before', 'core_unchanged', 'observation_errors',
    'internal_report_sha256', 'internal_report_summary',
  ))


def comparisonReportPaths(diagnostic):
  paths = []
  for name, folder in (('core-without-modules', 'c'), ('gui-close', 'g')):
    for mode in ('plain-before', 'debug-default', 'debug-noheap', 'plain-after'):
      label = folder + '-' + mode
      base = folder + '/' + mode + '/reports/'
      paths.append((label + '-case', diagnostic, base + 'diagnostic-case.json', 'comparison-case'))
      if mode.startswith('debug-'):
        paths.append((label + '-native', diagnostic, base + 'native-debug.json', 'native'))
      if name == 'core-without-modules':
        paths.append((label + '-internal', diagnostic, base + name + '.json', 'core'))
  return paths


def project(value, kind):
  if kind == 'comparison-case':
    return caseProjection(value)
  if kind == 'native':
    return nativeProjection(value)
  if kind == 'dll':
    return dllProjection(value)
  if kind == 'source':
    result = selected(value, ('status', 'request', 'diagnostic_builder_sha', 'source_build',
                              'source_product_status', 'reports'))
    result['source_run'] = selected(value.get('source_run', {}),
      ('id', 'run_attempt', 'head_sha', 'status', 'conclusion'))
    result['artifacts'] = {name: selected(item, ('id', 'name', 'size_in_bytes', 'digest'))
                           for name, item in value.get('artifacts', {}).items()}
    return result
  if kind == 'diagnostic':
    result = selected(value, ('status', 'published', 'source_request', 'source_build',
      'source_product_status', 'diagnostic_builder_sha', 'debugger_observed', 'comparison', 'error', 'traceback', 'scope'))
    result['cases'] = [caseProjection(item) for item in value.get('cases', [])]
    if 'dll_search_probe' in value:
      result['dll_search_probe'] = dllProjection(value['dll_search_probe'])
    return result
  if kind == 'core':
    return selected(value, ('case', 'status', 'pid', 'executable', 'frozen', 'python', 'platform',
      'error', 'traceback', 'runtime_identity', 'elapsed_seconds', 'network_attempts', 'result'))
  require(kind == 'complete', 'Unknown report projection')
  return value


def payloadText(label, identity, value, kind):
  payload = {'label': label, 'source': identity, 'projection_kind': kind,
             'projection': project(value, kind) if value is not None else None}
  text = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
  require(len(text.encode('ascii')) <= MAX_PROJECTION_BYTES,
          'Projection exceeds its budget; no fields or exception records were silently truncated')
  return text


def emitPayload(label, text, writer=print):
  digest = hashlib.sha256(text.encode('ascii')).hexdigest()
  pieces = [text[index:index + CHUNK_CHARACTERS] for index in range(0, len(text), CHUNK_CHARACTERS)]
  for index, piece in enumerate(pieces):
    writer(PREFIX + json.dumps({'label': label, 'chunk': index + 1, 'chunks': len(pieces),
      'projection_bytes': len(text), 'projection_sha256': digest, 'text': piece}, ensure_ascii=True))


def collectReports(diagnostic, fixtures, source):
  noheap = fixtures.parent / 'native-noheap-fixtures'
  paths = [
    ('source', source, 'source-receipt.json', 'source'),
    ('fixtures', fixtures, 'native-fixture-summary.json', 'complete'),
    ('fixture-normal', fixtures, 'normal/reports/native-debug.json', 'native'),
    ('fixture-access-violation', fixtures, 'access-violation/reports/native-debug.json', 'native'),
    ('fixtures-noheap', noheap, 'native-fixture-summary.json', 'complete'),
    ('fixture-noheap-normal', noheap, 'normal/reports/native-debug.json', 'native'),
    ('fixture-noheap-access-violation', noheap, 'access-violation/reports/native-debug.json', 'native'),
    ('diagnostic', diagnostic, 'diagnostic-summary.json', 'diagnostic'),
    ('dll-search', diagnostic, 'core-without-modules/reports/dll-search-summary.json', 'dll'),
  ]
  emitted = 0
  failed = False
  for label, root, relative, kind in paths:
    try:
      identity, value = readReport(root, relative)
      if label == 'diagnostic':
        if value is not None and value.get('source_request', {}).get('schema_version') == 3:
          paths.extend(comparisonReportPaths(diagnostic))
        else:
          paths.extend([
            ('core-native', diagnostic, 'c/reports/native-debug.json', 'native'),
            ('core-internal', diagnostic, 'c/reports/core-without-modules.json', 'core'),
            ('gui-native', diagnostic, 'g/reports/native-debug.json', 'native'),
          ])
      text = payloadText(label, identity, value, kind)
      require(emitted + len(text) <= MAX_TOTAL_PROJECTION_BYTES, 'Combined diagnostic log budget exceeded')
      emitPayload(label, text)
      emitted += len(text)
    except Exception as error:
      failed = True
      print('VW_DIAGNOSTIC_REPORT_ERROR ' + json.dumps({
        'label': label, 'path': relative, 'status': 'ERROR', 'error': type(error).__name__ + ': ' + str(error),
        'scope': 'No product qualification or field truncation; complete reports stay in artifact'}, ensure_ascii=True))
  return 1 if failed else 0


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--diagnostic', type=Path, required=True)
  parser.add_argument('--fixtures', type=Path, required=True)
  parser.add_argument('--source', type=Path, required=True)
  args = parser.parse_args()
  return collectReports(args.diagnostic.resolve(), args.fixtures.resolve(), args.source.resolve())


if __name__ == '__main__':
  raise SystemExit(main())
