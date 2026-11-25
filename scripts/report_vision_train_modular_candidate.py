"""Read-only bounded log projections for a complete modular candidate.

Inventory tables and native module lists stay in the original evidence artifact.
Each printed source and projection keeps its own byte count and SHA256 identity.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__:
  from . import report_vision_train_core_diagnostic as common
else:
  sys.path.insert(0, str(Path(__file__).resolve().parent))
  import report_vision_train_core_diagnostic as common


MAX_PROCESS_REPORTS = 256
MAX_PROCESS_LOG_BYTES = 64 * 1024
CASE_REPORTS = (
  'empty-status-default-output', 'core-without-modules', 'annotation-without-modules',
  'gui-runtime-lease', 'cold-ort-repair', 'ort-after-repair-without-torch',
  'dino-without-torch', 'dino-worker-without-torch', 'edgesam-without-torch',
  'edgesam-single-module-update', 'edgesam-after-version-rollback', 'core-after-remove',
  'torch-full', 'dataloader-spawn-full', 'ort-full', 'dino-full', 'dino-worker-full',
  'sklearn-full', 'image-simplification-full', 'cnn-pretrained-full', 'dino-pretrained-full',
  'yolo-pretrained-full', 'yolo-full', 'pt-full', 'core-after-rollback',
)


def readProcessOutput(root, relative):
  # The caller derives this single basename from a discovered process receipt,
  # never from a path supplied inside that receipt or an arbitrary command.
  common.require(relative and Path(relative).name == relative and '/' not in relative
                 and '\\' not in relative and ':' not in relative
                 and relative.endswith(('.stdout.txt', '.stderr.txt')),
                 'Unsafe process output path')
  path = root / relative
  common.require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(),
                 'Process output is outside its declared report root')
  if not path.exists():
    return {'path': relative, 'status': 'MISSING'}, None
  common.require(path.is_file(), 'Process output is not a regular file')
  size = path.stat().st_size
  common.require(0 <= size <= MAX_PROCESS_LOG_BYTES, 'Process output exceeds its fixed read budget')
  raw = path.read_bytes()
  common.require(len(raw) == size, 'Process output size changed during the read')
  identity = {'path': relative, 'status': 'READ', 'bytes': size,
              'sha256': hashlib.sha256(raw).hexdigest()}
  try:
    value = {'text': raw.decode('utf-8-sig'), 'decoding': 'utf-8-sig'}
  except UnicodeDecodeError as error:
    # Preserve every non-UTF8 byte as an explicit escape, not an invented codepage.
    value = {'text': raw.decode('utf-8', errors='backslashreplace'),
             'decoding': 'utf-8 with invalid byte escapes', 'decoding_error': str(error)}
  return identity, value


def reuseProjection(value):
  result = common.selected(value, ('enabled',))
  result['files'] = [common.selected(item, (
    'status', 'module_id', 'archive_bytes_unchanged', 'manifest_bytes_unchanged',
    'manifest_sha256', 'payload_files_verified', 'source_run', 'source_artifact',
    'source_build', 'target_core_build', 'source_product_acceptance', 'scope'))
    for item in value.get('files', [])]
  return result


def buildProjection(value):
  result = common.selected(value, ('status', 'published', 'product_acceptance', 'gpu_hardware',
    'scope', 'error', 'traceback', 'elapsed_seconds', 'core_archive', 'module_archives',
    'core_sha256', 'core_bytes', 'module_index', 'release_gate', 'compatibility_findings',
    'unique_python_files', 'source', 'packager', 'profile_sha256', 'module_builds'))
  result['core'] = common.selected(value.get('core', {}), (
    'type', 'protocol_version', 'module_api', 'version', 'python', 'build',
    'dependency_lock_sha256', 'catalog'))
  result['module_reuse'] = reuseProjection(value.get('module_reuse', {}))
  result['projection_scope'] = 'Complete archive/index identities and original module build/reuse identities; file and dependency inventory tables remain in the source report'
  return result


def caseProjection(value):
  # Keep every business-result/error/traceback field. The excluded fields are
  # native/file inventories, which are available through the source report hash.
  result = common.selected(value, ('name', 'case', 'status', 'ok', 'code', 'error',
    'traceback', 'pid', 'executable', 'frozen', 'python', 'platform', 'elapsed_seconds',
    'runtime_identity', 'network_attempts', 'scope', 'result', 'inert_pth',
    'module_id', 'manifest_sha256', 'runtime_identity_before', 'runtime_identity_after',
    'damaged_file', 'ordinary_install', 'full_payload_restored', 'payload_inventory_sha256',
    'payload_file_count', 'runtime_identity_updated', 'runtime_identity_restored',
    'original_versions_unchanged_after_update', 'original_versions_unchanged_after_rollback',
    'fixture_payload_verified', 'installed_fixture_path', 'updated_model_computation',
    'gui_pid', 'pending_install_while_running', 'activation_denied', 'termination'))
  if 'fixture' in value:
    result['fixture'] = common.selected(value['fixture'], (
      'scope', 'distributed_archive', 'diagnostic_archive', 'marker'))
  if 'original_version_inventories' in value:
    result['original_inventory_file_counts'] = {
      name: len(files) for name, files in value['original_version_inventories'].items()}
  result['projection_scope'] = 'Complete result/error/traceback and lifecycle identity fields; full native and per-file inventories remain in the source report'
  return result


def productProjection(value):
  result = common.selected(value, ('status', 'published', 'gpu_hardware', 'cpu_product_fixtures',
    'scope', 'error', 'traceback', 'elapsed_seconds', 'build', 'module_builds',
    'module_index', 'core_sha256', 'executable', 'executable_sha256',
    'qt_platform_requested', 'core_inventory_before', 'core_integrity_checks',
    'release_gate', 'compatibility_findings', 'limitations'))
  result['cases'] = [common.selected(item, (
    'name', 'status', 'pid', 'gui_pid', 'report', 'sha256', 'report_sha256',
    'runtime_identity', 'scope', 'error', 'traceback', 'exit_code', 'termination'))
    for item in value.get('cases', [])]
  result['module_reuse'] = reuseProjection(value.get('module_reuse', {}))
  result['projection_scope'] = 'All completed case names and identities; separate case/process projections retain actual exits, failures and results'
  return result


def project(value, kind):
  if kind == 'build':
    return buildProjection(value)
  if kind == 'product':
    return productProjection(value)
  if kind == 'case':
    return caseProjection(value)
  common.require(kind in ('complete', 'process'), 'Unknown candidate report projection')
  return value


def collectReports(build, product, writer=print):
  paths = [
    ('candidate-build', build, 'modular-build-summary.json', 'build'),
    ('candidate-index', build, 'module-index.json', 'complete'),
    ('candidate-product', product, 'modular-product-summary.json', 'product'),
    ('candidate-index-verification', product, 'module-index-verification.json', 'complete'),
  ]
  paths.extend(('candidate-case:' + name, product, name + '.json', 'case')
               for name in CASE_REPORTS)
  # Read these even when the outer check raises before returning result: the
  # spawn helper writes its real PID/identity/cleanup evidence in a finally block.
  paths.extend((
    ('candidate-spawn-detail', product,
     'dataloader-spawn-full-files/dataloader-spawn-check.json', 'complete'),
    ('candidate-spawn-worker', product,
     'dataloader-spawn-full-files/worker-0.json', 'complete'),
  ))
  failures, emitted = False, 0
  try:
    process_paths = sorted(product.glob('*.process.json'))
    common.require(len(process_paths) <= MAX_PROCESS_REPORTS,
                   'Process report count exceeds the fixed log budget')
    paths.extend(('candidate-process:' + path.name[:-13], product, path.name, 'process')
                 for path in process_paths)
  except Exception as error:
    failures = True
    writer('VW_CANDIDATE_REPORT_ERROR ' + json.dumps({
      'label': 'candidate-process-discovery', 'status': 'ERROR',
      'error': type(error).__name__ + ': ' + str(error)}, ensure_ascii=True))
  for label, root, relative, kind in paths:
    try:
      identity, value = (readProcessOutput(root, relative) if kind == 'text'
                         else common.readReport(root, relative))
      if kind == 'process' and value is not None and (
          value.get('status') != 'PASS' or value.get('exit_code') != 0 or value.get('error')):
        name = relative[:-len('.process.json')]
        paths.extend(('candidate-process-output:' + name + ':' + stream, root,
                      name + '.' + stream + '.txt', 'text') for stream in ('stdout', 'stderr'))
      projected = (value if kind == 'text' else project(value, kind)) if value is not None else None
      text = common.payloadText(label, identity, projected, 'complete')
      common.require(emitted + len(text) <= common.MAX_TOTAL_PROJECTION_BYTES,
                     'Combined candidate log budget exceeded')
      common.emitPayload(label, text, writer)
      emitted += len(text)
    except Exception as error:
      failures = True
      writer('VW_CANDIDATE_REPORT_ERROR ' + json.dumps({
        'label': label, 'path': relative, 'status': 'ERROR',
        'error': type(error).__name__ + ': ' + str(error),
        'scope': 'No product qualification or field truncation; complete reports stay in artifact'},
        ensure_ascii=True))
  return 1 if failures else 0


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--build', type=Path, required=True)
  parser.add_argument('--product', type=Path, required=True)
  args = parser.parse_args()
  return collectReports(args.build.resolve(), args.product.resolve())


if __name__ == '__main__':
  raise SystemExit(main())
