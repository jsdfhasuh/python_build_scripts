"""Invoke the source-owned protocol producer with explicit isolated build paths."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from build_config import BuildConfigError
from build_environment import pythonChildEnvironment


ASSET_PREFIX = 'VisionWorkshop-windows-x86_64'
RELEASE_REPO = 'jsdfhasuh/emo-vision-train-release'


def protocolEnabled(resolved) -> bool:
  return resolved.config.get('update_protocol') == 2


def runProducer(resolved, context, sourceRoot, action, *arguments) -> dict:
  helper = sourceRoot / 'update_release.py'
  if not helper.is_file():
    raise BuildConfigError('Protocol-2 source producer missing; update the source checkout')
  command = [sys.executable, str(helper), action, '--work', str(context.workRoot),
             '--app', str(context.distRoot / resolved.programName), *map(str, arguments)]
  result = subprocess.run(command, cwd=sourceRoot, text=True, encoding='utf-8',
                          capture_output=True, check=False, env=pythonChildEnvironment())
  if result.returncode:
    raise BuildConfigError(f'Protocol producer {action} failed: {result.stderr.strip()}')
  return json.loads(result.stdout) if result.stdout.strip() else {}


def prepareProtocol(resolved, context, sourceRoot, sourceCommit):
  versionFile = Path(resolved.config.get('source_version_file') or sourceRoot / 'app_version.py')
  if not versionFile.is_absolute():
    versionFile = sourceRoot / versionFile
  try:
    tree = ast.parse(versionFile.read_text(encoding='utf-8-sig'), filename=str(versionFile))
  except (OSError, UnicodeError, SyntaxError) as exc:
    raise BuildConfigError(f'Cannot read protocol source version file: {versionFile}: {exc}') from exc
  versions = {}
  for statement in tree.body:
    if isinstance(statement, ast.Assign):
      targets = statement.targets
    elif isinstance(statement, ast.AnnAssign):
      targets = [statement.target]
    else:
      continue
    for target in targets:
      if isinstance(target, ast.Name) and target.id in ('APP_VERSION', '__version__'):
        value = statement.value
        versions[target.id] = value.value if isinstance(value, ast.Constant) else None
  version = versions.get('__version__') if resolved.config.get('source_version_file') else (
    versions.get('APP_VERSION', versions.get('__version__'))
  )
  if not isinstance(version, str) or not version:
    raise BuildConfigError(f'Cannot determine protocol version from source version file: {versionFile}')
  if os.environ.get('RELEASE_TAG') not in (None, '', 'v' + version):
    raise BuildConfigError('Protocol release tag differs from source version')
  return runProducer(resolved, context, sourceRoot, 'prepare', '--build-id', context.buildId,
    '--version', version, '--entrypoint', resolved.programName + '.exe',
    '--updater-entrypoint', resolved.config['updater'].get('name', 'updater') + '.exe',
    '--source-repo', resolved.config.get('source_repo', ''), '--source-commit', sourceCommit)


def verifyProtocol(resolved, context, sourceRoot):
  return runProducer(resolved, context, sourceRoot, 'verify')


def fullAssetName(context):
  return f'{ASSET_PREFIX}-{context.buildId}-full.zip'
