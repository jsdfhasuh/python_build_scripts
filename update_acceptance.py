"""Record optional protocol-3 acceptance without treating untested checks as passed."""

import json
from pathlib import Path

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from path_boundary import ioPath


ACCEPTANCE_CHECKS = (
  'automated_tests', 'frozen_product_update_and_recovery', 'two_successive_updates',
  'broken_app_recovery_without_python', 'long_paths_policy_disabled',
  'real_manifest_zero_unchanged_copy', 'power_loss_recovery',
)


def verifyAcceptance(workRoot: Path, protocol: dict) -> dict:
  if protocol.get('protocol_version') != 3:
    raise BuildConfigError('Acceptance report requires protocol 3')
  path = workRoot / 'update-acceptance.json'
  rejectLinks(path)
  try:
    if ioPath(path).stat().st_size > 1024 * 1024:
      raise BuildConfigError('Update acceptance report exceeds the size limit')
    report = json.loads(ioPath(path).read_text(encoding='utf-8'))
  except FileNotFoundError:
    return {'status': 'not-run', 'checks': {name: 'not-run' for name in ACCEPTANCE_CHECKS}}
  except (OSError, ValueError) as error:
    raise BuildConfigError(f'Cannot read acceptance report: {path}') from error
  if (not isinstance(report, dict) or report.get('schema_version') != 1
      or report.get('protocol') != protocol):
    raise BuildConfigError('Acceptance report does not bind this exact protocol-3 build')
  checks = report.get('checks', {})
  if not isinstance(checks, dict):
    raise BuildConfigError('Acceptance checks must be an object')
  statuses = {}
  for name in ACCEPTANCE_CHECKS:
    check = checks.get(name, {})
    if not isinstance(check, dict):
      raise BuildConfigError(f'Invalid acceptance check: {name}')
    status = check.get('status', 'not-run')
    evidenceItems = check.get('evidence', [])
    if status not in ('passed', 'failed', 'not-run', 'skipped') or not isinstance(evidenceItems, list):
      raise BuildConfigError(f'Invalid acceptance status or evidence: {name}')
    if status == 'passed' and not evidenceItems:
      raise BuildConfigError(f'Passed acceptance requires evidence: {name}')
    statuses[name] = status
    for item in evidenceItems:
      if not isinstance(item, dict) or not isinstance(item.get('path'), str):
        raise BuildConfigError(f'Acceptance evidence path is invalid: {name}')
      relative = Path(item.get('path', ''))
      if not relative.parts or relative.is_absolute() or '..' in relative.parts:
        raise BuildConfigError(f'Acceptance evidence path is invalid: {name}')
      evidence = workRoot / relative
      rejectLinks(evidence)
      if fileHash(evidence) != item.get('sha256'):
        raise BuildConfigError(f'Acceptance evidence changed: {name}')
  status = ('passed' if all(value == 'passed' for value in statuses.values()) else
            'failed' if 'failed' in statuses.values() else 'not-verified')
  return {'status': status, 'report_sha256': fileHash(path), 'checks': statuses}
