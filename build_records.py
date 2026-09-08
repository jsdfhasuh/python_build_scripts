"""Local build provenance and streaming validation; not a signed trust boundary."""

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

from build_config import BuildConfigError
from build_config import BuildContext
from build_config import ResolvedBuild
from build_config import readJsonObject
from build_config import validateFileName


BUILD_ID = re.compile(r'^\d{8}T\d{6}Z-[a-f0-9]{12}$')
CHUNK = 1024 * 1024


def fileHash(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open('rb') as stream:
    for chunk in iter(lambda: stream.read(CHUNK), b''):
      digest.update(chunk)
  return digest.hexdigest()


def objectHash(value: object) -> str:
  return hashlib.sha256(json.dumps(
    value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
  ).encode('utf-8')).hexdigest()


def rejectLinks(path: Path) -> None:
  for component in (path, *path.parents):
    try:
      attributes = getattr(component.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
      attributes = 0
    if (attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024) or component.is_symlink()
        or getattr(component, 'is_junction', lambda: False)()):
      raise BuildConfigError(f'Symlinks/junctions are not permitted in build inputs/outputs: {path}')


def scanFiles(root: Path) -> dict[str, dict]:
  rejectLinks(root)
  if not root.is_dir():
    raise BuildConfigError(f'Application/resource directory is missing: {root}')
  files = {}
  folded = set()
  for directory, directories, names in os.walk(root, followlinks=False):
    base = Path(directory)
    for name in directories + names:
      path = base / name
      rejectLinks(path)
      validateFileName(name, 'Packaged/resource filename')
      key = path.relative_to(root).as_posix()
      if key.casefold() in folded:
        raise BuildConfigError(f'Case-insensitive path collision: {key}')
      folded.add(key.casefold())
    for name in sorted(names):
      path = base / name
      if not path.is_file():
        raise BuildConfigError(f'Not a regular file: {path}')
      before = path.stat()
      digest = fileHash(path)
      after = path.stat()
      if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BuildConfigError(f'File changed while hashing: {path}')
      files[path.relative_to(root).as_posix()] = {'sha256': digest, 'size': after.st_size}
  return dict(sorted(files.items()))


def gitState(root: Path) -> dict:
  def call(*args: str) -> str:
    result = subprocess.run(
      ['git', '-C', str(root), *args], capture_output=True, text=True,
      encoding='utf-8', errors='replace', check=False, timeout=120,
    )
    if result.returncode:
      raise BuildConfigError(f'Git inspection failed: {result.stderr.strip()}')
    return result.stdout.rstrip('\r\n')
  try:
    # A nested directory of some other checkout is not this source repository.
    top = Path(call('rev-parse', '--show-toplevel')).resolve()
    if top != root.resolve():
      raise BuildConfigError('SourceRoot must be the repository root')
    commit = call('rev-parse', 'HEAD')
    status = call('status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none')
    submodules = call('submodule', 'status', '--recursive')
    tracked = {}
    names = call('ls-files', '-z', '--cached', '--others', '--exclude-standard')
    for name in sorted(set(names.split('\0')) - {''}):
      path = root / name
      rejectLinks(path)
      if path.is_dir():
        tracked[name] = gitState(path)
      elif path.is_file():
        tracked[name] = fileHash(path)
      else:
        tracked[name] = 'missing'
    return {
      'commit': commit, 'dirty': bool(status), 'status_sha256': objectHash(status),
      'submodules': submodules, 'working_files_sha256': objectHash(tracked),
      'submodules_ready': all(line[:1] == ' ' for line in submodules.splitlines()),
    }
  except (BuildConfigError, OSError, subprocess.TimeoutExpired):
    return {'commit': None, 'dirty': True, 'submodules_ready': False}


def gitCommit(root: Path) -> str | None:
  try:
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=False, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None
  except (OSError, subprocess.TimeoutExpired):
    return None


def toolVersions() -> dict:
  packages = sorted(
    (item.metadata.get('Name', '').lower(), item.version)
    for item in importlib.metadata.distributions()
  )
  return {
    'python': platform.python_version(), 'platform': sys.platform,
    'machine': platform.machine(), 'packages_sha256': objectHash(packages),
  }


def inputSnapshot(resolved: ResolvedBuild, sourceRoot: Path) -> dict:
  import build
  paths = {Path(job.entry) for job in build.create_build_jobs(resolved.config)}
  versionFile = resolved.config.get('source_version_file')
  if versionFile:
    versionPath = Path(versionFile)
    paths.add(versionPath if versionPath.is_absolute() else sourceRoot / versionPath)
  for job in build.create_build_jobs(resolved.config):
    if job.icon:
      paths.add(Path(job.icon))
    for item in job.add_data:
      paths.add(Path(build.split_add_data(item)[0]))
    arguments = job.extra_args
    for index, argument in enumerate(arguments):
      key, separator, attached = argument.partition('=')
      if key in ('--runtime-hook', '--additional-hooks-dir', '--paths', '--add-data',
                 '--add-binary', '--version-file'):
        value = attached if separator else arguments[index + 1] if index + 1 < len(arguments) else ''
        if not value:
          raise BuildConfigError(f'Missing resource argument: {key}')
        if key in ('--add-data', '--add-binary'):
          value = build.split_add_data(value)[0]
        # One path per --paths occurrence is required for verifiable branded builds.
        if key == '--paths' and os.pathsep in value and not Path(value).exists():
          raise BuildConfigError('Use separate --paths options for separate directories')
        paths.add(Path(value))
    if build.needs_torch_runtime(job):
      paths.add(Path(build._ensure_torch_runtime_hook()))
  inputs = {}
  for path in sorted(paths, key=str):
    if not path.is_absolute():
      path = resolved.packagerRoot / path
    rejectLinks(path)
    if path.is_dir():
      inputs[str(path.resolve())] = objectHash(scanFiles(path))
    elif path.is_file():
      inputs[str(path.resolve())] = fileHash(path)
    else:
      raise BuildConfigError(f'Build input does not exist: {path}')
  # Include executable packager code, not its changing dist/work files.
  packagerFiles = sorted(resolved.packagerRoot.glob('*.py'))
  packagerFiles += sorted((resolved.packagerRoot / 'scripts').glob('*.py'))
  packagerFiles += sorted((resolved.packagerRoot / 'scripts').glob('*.ps1'))
  packagerDigest = {}
  for path in packagerFiles:
    rejectLinks(path)
    packagerDigest[path.relative_to(resolved.packagerRoot).as_posix()] = fileHash(path)
  return {
    'source_root': str(sourceRoot.resolve()), 'source': gitState(sourceRoot),
    'packager': {'commit': gitCommit(resolved.packagerRoot)},
    'packager_code_sha256': objectHash(packagerDigest),
    'environment_sha256': objectHash({key: os.environ.get(key, '') for key in (
      'PYTHONPATH', 'CONDA_PREFIX', 'PYINSTALLER_CONFIG_DIR', 'PATH',
    )}),
    'declared_inputs': inputs, 'tools': toolVersions(),
  }


def writeJsonNew(path: Path, data: dict) -> None:
  rejectLinks(path)
  if path.exists():
    raise BuildConfigError(f'Refusing to overwrite an existing output: {path}')
  temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
  try:
    with temporary.open('x', encoding='utf-8') as stream:
      json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
      stream.write('\n')
      stream.flush()
      os.fsync(stream.fileno())
    # Link fails atomically if another process has created the destination.
    if os.name == 'nt':
      os.rename(temporary, path)
    else:
      os.link(temporary, path)
  finally:
    temporary.unlink(missing_ok=True)


def validateApplication(resolved: ResolvedBuild, appDir: Path) -> dict:
  files = scanFiles(appDir)
  required = [f'{resolved.programName}.exe']
  if (resolved.config.get('updater') or {}).get('enabled'):
    required.append('updater.exe')
  for name in required:
    if name not in files or files[name]['size'] == 0:
      raise BuildConfigError(f'Expected executable missing or empty: {appDir / name}')
  for name in files:
    if (Path(name).name in ('effective-config.json', 'build-record.json', 'build-result.json')
        or '.git' in Path(name).parts):
      raise BuildConfigError(f'Private build record/source metadata must not be bundled: {name}')
  return files


def completeRecord(
  resolved: ResolvedBuild, context: BuildContext, sourceRoot: Path, before: dict,
) -> dict:
  after = inputSnapshot(resolved, sourceRoot)
  if after != before:
    raise BuildConfigError('Source, resources, tools or packager changed during build; rebuild')
  files = validateApplication(resolved, context.distRoot / resolved.programName)
  source = before['source']
  reusable = bool(source.get('commit') and not source['dirty'] and source['submodules_ready'])
  record = {
    'schema_version': 1, 'status': 'complete', 'build_id': context.buildId,
    'target': resolved.target, 'program_name': resolved.programName,
    'config_sha256': resolved.fingerprint, 'icon_sha256': resolved.iconSha256,
    'inputs': before, 'files': files, 'files_sha256': objectHash(files),
    'reusable': reusable, 'windows_launch_test': 'not-run',
  }
  writeJsonNew(context.workRoot / 'build-record.json', record)
  return record


def verifyRecord(
  path: Path, resolved: ResolvedBuild, sourceRoot: Path, *, requireReusable: bool = True,
) -> tuple[BuildContext, dict]:
  rejectLinks(path)
  path = path.absolute()
  record = readJsonObject(path)
  if type(record.get('schema_version')) is not int:
    raise BuildConfigError('Invalid build record schema version')
  buildId = record.get('build_id')
  if not isinstance(buildId, str) or not BUILD_ID.fullmatch(buildId):
    raise BuildConfigError('Invalid build record ID')
  context = BuildContext(resolved.packagerRoot, resolved.target, buildId)
  expected = context.workRoot / 'build-record.json'
  if path.resolve() != expected.resolve():
    raise BuildConfigError('Build record must be in its original isolated work directory')
  for field, expectedValue in {
    'schema_version': 1, 'status': 'complete', 'target': resolved.target,
    'program_name': resolved.programName, 'config_sha256': resolved.fingerprint,
    'icon_sha256': resolved.iconSha256,
  }.items():
    if record.get(field) != expectedValue:
      raise BuildConfigError(f'Build record does not match {field}; rebuild')
  if not isinstance(record.get('inputs'), dict) or not isinstance(record.get('files'), dict):
    raise BuildConfigError('Malformed build record')
  source = record['inputs'].get('source')
  if not isinstance(source, dict):
    raise BuildConfigError('Malformed source provenance in build record')
  if requireReusable and (record.get('reusable') is not True or source.get('dirty') is not False
                         or not source.get('commit') or not source.get('submodules_ready')):
    raise BuildConfigError('Dirty/unversioned source cannot reuse a build record; rebuild')
  if inputSnapshot(resolved, sourceRoot) != record.get('inputs'):
    raise BuildConfigError('Build inputs or tool environment changed; rebuild')
  files = validateApplication(resolved, context.distRoot / resolved.programName)
  if files != record.get('files') or objectHash(files) != record.get('files_sha256'):
    raise BuildConfigError('Build artifacts changed; rebuild')
  return context, record
