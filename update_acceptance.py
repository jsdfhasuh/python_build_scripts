"""Protocol-3 publication requires separately recorded product and power-loss evidence."""

import json
from pathlib import Path

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from path_boundary import ioPath


REQUIRED_CHECKS = (
  'automated_tests', 'frozen_product_update_and_recovery', 'two_successive_updates',
  'broken_app_recovery_without_python', 'long_paths_policy_disabled',
  'real_manifest_zero_unchanged_copy', 'power_loss_recovery',
)


def verifyAcceptance(workRoot: Path, protocol: dict) -> dict:
  path = workRoot / 'update-acceptance.json'
  rejectLinks(path)
  try:
    if ioPath(path).stat().st_size > 1024 * 1024:
      raise BuildConfigError('Update acceptance report exceeds the size limit')
    report = json.loads(ioPath(path).read_text(encoding='utf-8'))
  except (OSError, ValueError) as error:
    raise BuildConfigError(
      'Protocol-3 publication is blocked until product and power-loss acceptance is '
      f'recorded for this build: {path}. Build-only and explicit-record re-archive remain available.'
    ) from error
  if (report.get('schema_version') != 1 or report.get('protocol') != protocol
      or protocol.get('protocol_version') != 3):
    raise BuildConfigError('Acceptance report does not bind this exact protocol-3 build')
  checks = report.get('checks', {})
  for name in REQUIRED_CHECKS:
    check = checks.get(name, {})
    if check.get('status') != 'passed' or not check.get('evidence'):
      raise BuildConfigError(f'Update acceptance not passed: {name}')
    for item in check['evidence']:
      relative = Path(item.get('path', ''))
      if not relative.parts or relative.is_absolute() or '..' in relative.parts:
        raise BuildConfigError(f'Acceptance evidence path is invalid: {name}')
      evidence = workRoot / relative
      rejectLinks(evidence)
      if fileHash(evidence) != item.get('sha256'):
        raise BuildConfigError(f'Acceptance evidence changed: {name}')
  return {'status': 'passed', 'report_sha256': fileHash(path), 'checks': list(REQUIRED_CHECKS)}
