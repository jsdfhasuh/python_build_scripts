"""Observe AddDllDirectory registrations in a disposable stdlib controller child."""

import argparse
import hashlib
import json
import os
from pathlib import Path


def require(value, message):
  if not value:
    raise RuntimeError(message)


def planDirectories(root, core, mode):
  require(mode in ('duplicate', 'unique'), 'Unknown fixed DLL registration sequence')
  launcher = [('launcher', root / '_internal')]
  launcher.extend(('launcher', root / item) for item in core['dll_dirs'])
  runtime = [('runtime-mount', root / item) for item in dict.fromkeys(core['dll_dirs'])]
  sequence = launcher + runtime + [('numpy-delvewheel', root / 'site-packages/numpy.libs')]
  result, known = [], set()
  for stage, path in sequence:
    require(path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(root),
            'DLL probe directory is missing or outside the verified Core')
    key = os.path.normcase(str(path.resolve()))
    if mode == 'unique' and key in known:
      continue
    known.add(key)
    result.append({'stage': stage, 'path': str(path),
                   'utf16_bytes_with_nul': len(str(path).encode('utf-16-le')) + 2})
  return result


def observeRegistrations(sequence, add):
  result = {'status': 'OBSERVED', 'entries': [], 'first_failure': None,
            'successful_directory_count': 0, 'successful_utf16_bytes_with_nul': 0,
            'cleanup_errors': []}
  handles = []
  try:
    for index, item in enumerate(sequence):
      record = dict(item, index=index,
                    attempted_cumulative_utf16_bytes_with_nul=(
                      result['successful_utf16_bytes_with_nul'] + item['utf16_bytes_with_nul']))
      result['entries'].append(record)
      try:
        handles.append(add(item['path']))
      except OSError as error:
        record.update(status='FAIL', error_type=type(error).__name__, error=str(error),
                      winerror=getattr(error, 'winerror', None), errno=error.errno)
        result['first_failure'] = record
        break
      record['status'] = 'REGISTERED'
      result['successful_directory_count'] += 1
      result['successful_utf16_bytes_with_nul'] += item['utf16_bytes_with_nul']
  finally:
    for handle in reversed(handles):
      try:
        handle.close()
      except Exception as error:
        result['cleanup_errors'].append(type(error).__name__ + ': ' + str(error))
    if result['cleanup_errors']:
      result['status'] = 'FAIL'
    result['handles_closed'] = len(handles) - len(result['cleanup_errors'])
  return result


def main():
  import sys
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--input', type=Path, required=True)
  parser.add_argument('--mode', choices=('duplicate', 'unique'), required=True)
  parser.add_argument('--output', type=Path, required=True)
  arguments = parser.parse_args()
  require(os.name == 'nt', 'DLL search registration requires Windows')
  require(not arguments.output.exists(), 'DLL probe output must be new')
  source = arguments.input.read_bytes()
  request = json.loads(source)
  require(set(request) == {'core_root', 'core_sha256'}, 'Unexpected DLL probe request')
  root = Path(request['core_root']).resolve()
  coreBytes = (root / 'core.json').read_bytes()
  require(hashlib.sha256(coreBytes).hexdigest() == request['core_sha256'], 'DLL probe Core identity changed')
  sequence = planDirectories(root, json.loads(coreBytes), arguments.mode)
  result = observeRegistrations(sequence, os.add_dll_directory)
  result.update(mode=arguments.mode, pid=os.getpid(), executable=sys.executable,
                input_sha256=hashlib.sha256(source).hexdigest(), core_sha256=request['core_sha256'],
                core_root=str(root), root_unicode_characters=len(str(root)),
                root_utf16_bytes=len(str(root).encode('utf-16-le')), planned_directory_count=len(sequence),
                scope='Standalone stdlib AddDllDirectory calls only; no Core imports or native DLL loads',
                budget_definition='Sum of directory UTF16 bytes including one NUL per registration; not a claimed Windows internal buffer layout')
  arguments.output.write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + '\n', encoding='utf-8')
  return 0 if result['status'] == 'OBSERVED' else 1


if __name__ == '__main__':
  raise SystemExit(main())
