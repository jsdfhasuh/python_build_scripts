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
from path_boundary import ioPath, logicalPath
from update_protocol_build import protocolEnabled, verifyProtocol


BUILD_ID = re.compile(r'^\d{8}T\d{6}Z-[a-f0-9]{12}$')
CHUNK = 1024 * 1024


def fileHash(path: Path) -> str:
  digest = hashlib.sha256()
  with ioPath(path).open('rb') as stream:
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
      attributes = getattr(ioPath(component).lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
      attributes = 0
    if (attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024) or ioPath(component).is_symlink()
        or getattr(ioPath(component), 'is_junction', lambda: False)()):
      raise BuildConfigError(f'Symlinks/junctions are not permitted in build inputs/outputs: {path}')


def scanFiles(root: Path) -> dict[str, dict]:
  rejectLinks(root)
  if not ioPath(root).is_dir():
    raise BuildConfigError(f'Application/resource directory is missing: {root}')
  files = {}
  folded = set()
  def scanError(error):
    raise error
  for directory, directories, names in os.walk(ioPath(root), followlinks=False, onerror=scanError):
    base = logicalPath(directory)
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
      if not ioPath(path).is_file():
        raise BuildConfigError(f'Not a regular file: {path}')
      before = ioPath(path).stat()
      digest = fileHash(path)
      after = ioPath(path).stat()
      if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BuildConfigError(f'File changed while hashing: {path}')
      files[path.relative_to(root).as_posix()] = {'sha256': digest, 'size': after.st_size}
  return dict(sorted(files.items()))


def gitState(root: Path, *, details: dict | None = None) -> dict:
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
        tracked[name] = gitState(path, details=details)
      elif path.is_file():
        tracked[name] = fileHash(path)
      else:
        tracked[name] = 'missing'
      if details is not None and not path.is_dir() and tracked[name] != 'missing':
        details[str(path.resolve())] = tracked[name]
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


def inputSnapshot(
  resolved: ResolvedBuild, sourceRoot: Path, *, details: dict | None = None,
) -> dict:
  import build
  paths = {Path(job.entry) for job in build.create_build_jobs(resolved.config)}
  if protocolEnabled(resolved):
    paths.add(sourceRoot / 'launcher.py')
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
  resourceFiles = {}
  for path in sorted(paths, key=str):
    if not path.is_absolute():
      path = resolved.packagerRoot / path
    rejectLinks(path)
    if path.is_dir():
      files = scanFiles(path)
      inputs[str(path.resolve())] = objectHash(files)
      resourceFiles.update({str((path / name).resolve()): value for name, value in files.items()})
    elif path.is_file():
      inputs[str(path.resolve())] = fileHash(path)
      resourceFiles[str(path.resolve())] = inputs[str(path.resolve())]
    else:
      raise BuildConfigError(f'Build input does not exist: {path}')
  # Include executable packager code, not its changing dist/work files.
  packagerFiles = sorted(resolved.packagerRoot.glob('*.py'))
  packagerFiles += sorted((resolved.packagerRoot / 'scripts').glob('*.py'))
  packagerFiles += sorted((resolved.packagerRoot / 'scripts').glob('*.ps1'))
  packagerFiles += sorted((resolved.packagerRoot / 'ci').glob('*.json'))
  packagerDigest = {}
  for path in packagerFiles:
    rejectLinks(path)
    packagerDigest[path.relative_to(resolved.packagerRoot).as_posix()] = fileHash(path)
  sourceFiles = {} if details is not None else None
  source = gitState(sourceRoot, details=sourceFiles)
  if details is not None:
    details.update(source_files=sourceFiles, resource_files=resourceFiles,
                   packager_files=packagerDigest)
  return {
    'source_root': str(sourceRoot.resolve()), 'source': source,
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
    with ioPath(temporary).open('x', encoding='utf-8') as stream:
      json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
      stream.write('\n')
      stream.flush()
      os.fsync(stream.fileno())
    # Link fails atomically if another process has created the destination.
    if os.name == 'nt':
      os.rename(temporary, path)
    else:
      os.link(ioPath(temporary), ioPath(path))
  finally:
    ioPath(temporary).unlink(missing_ok=True)


def validateApplication(resolved: ResolvedBuild, appDir: Path) -> dict:
  files = scanFiles(appDir)
  if protocolEnabled(resolved):
    required = ['VisionWorkshop.exe', 'app/VisionWorkshopApp.exe', 'app/VisionWorkshopUpdater.exe',
                'app/release_identity.json', 'app/package_files.json']
    for name in required:
      if name not in files or files[name]['size'] == 0:
        raise BuildConfigError(f'Protocol-3 required artifact missing: {name}')
    for name in files:
      if name != 'VisionWorkshop.exe' and not name.startswith('app/'):
        raise BuildConfigError(f'File outside protocol-3 application layout: {name}')
      if Path(name).name.casefold() in ('updater.exe', 'training_platform.exe', 'emo-vision-train.exe'):
        raise BuildConfigError(f'Obsolete executable alias in protocol-3 build: {name}')
  else:
    required = [f'{resolved.programName}.exe']
    if (resolved.config.get('updater') or {}).get('enabled'):
      required.append('updater.exe')
      required.append(f'{resolved.config["updater"].get("name", "updater")}.exe')
    for name in required:
      if name not in files or files[name]['size'] == 0:
        raise BuildConfigError(f'Expected executable missing or empty: {appDir / name}')
    if (resolved.config.get('updater') or {}).get('enabled'):
      namedUpdater = f'{resolved.config["updater"].get("name", "updater")}.exe'
      if files[namedUpdater] != files['updater.exe']:
        raise BuildConfigError('Named updater and legacy updater.exe must contain identical bytes')
  for name in files:
    if (Path(name).name in ('effective-config.json', 'build-record.json', 'build-result.json',
                           'input-snapshot-before.json', 'input-changes.json')
        or '.git' in Path(name).parts):
      raise BuildConfigError(f'Private build record/source metadata must not be bundled: {name}')
  return files


def completeRecord(
  resolved: ResolvedBuild, context: BuildContext, sourceRoot: Path, before: dict,
  beforeDetails: dict | None = None,
) -> dict:
  afterDetails = {}
  after = inputSnapshot(resolved, sourceRoot, details=afterDetails)
  if after != before:
    categories = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    changes = {}
    detailCategories = set(beforeDetails) | set(afterDetails) if beforeDetails is not None else set()
    for category in sorted(detailCategories):
      old = (beforeDetails or {}).get(category, {})
      new = afterDetails.get(category, {})
      changes[category] = {
        'added': sorted(set(new) - set(old)),
        'removed': sorted(set(old) - set(new)),
        'modified': sorted(key for key in set(old) & set(new) if old[key] != new[key]),
      }
    diagnostic = context.workRoot / 'input-changes.json'
    writeJsonNew(diagnostic, {'categories': categories, 'changes': changes,
                             'before': before, 'after': after,
                             'before_details': beforeDetails, 'after_details': afterDetails})
    counts = ', '.join(f'{category}: ' + '/'.join(
      str(len(items[kind])) for kind in ('added', 'removed', 'modified'))
      for category, items in changes.items() if any(items.values()))
    examples = []
    for category, items in changes.items():
      for kind, names in items.items():
        for name in names:
          path = Path(name)
          if path.is_absolute():
            path = next((path.relative_to(root.resolve()) for root in
                         (sourceRoot, resolved.packagerRoot)
                         if path.is_relative_to(root.resolve())), Path(path.name))
          if len(examples) < 10:
            examples.append(f'{category}/{kind}: {path.as_posix()}')
    raise BuildConfigError(
      'Source, resources, tools or packager changed during build; rebuild. '
      f'Changed categories: {", ".join(categories)}. '
      f'File counts (added/removed/modified): {counts or "none"}. '
      f'File examples (up to 10): {json.dumps(examples, ensure_ascii=True)}. '
      f'Private diagnostics: {diagnostic}'
    )
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
  if protocolEnabled(resolved):
    record['update_protocol'] = verifyProtocol(resolved, context, sourceRoot)
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
  if protocolEnabled(resolved):
    expectedProtocol = record.get('update_protocol')
    if not isinstance(expectedProtocol, dict) or expectedProtocol.get('protocol_version') != 3:
      raise BuildConfigError('Old build record has no protocol identity; clean rebuild required')
    if verifyProtocol(resolved, context, sourceRoot) != expectedProtocol:
      raise BuildConfigError('Protocol artifacts differ from the original build record')
  return context, record
