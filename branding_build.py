"""Build a branded application directory and retain verifiable local provenance."""

import json
import copy
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import build
from build_config import BuildConfigError
from build_config import BuildContext
from build_config import ResolvedBuild
from build_config import createBuildContext
from build_config import resolveBuildConfig
from build_environment import preventSourceBytecode
from build_records import completeRecord
from build_records import fileHash
from build_records import inputSnapshot
from build_records import rejectLinks
from build_records import writeJsonNew
from console_utils import configureConsole
from path_boundary import ioPath, logicalPath
from update_protocol_build import protocolEnabled, prepareProtocol, runProducer


class CompilerError(BuildConfigError):
  def __init__(self, returncode: int) -> None:
    self.returncode = returncode
    super().__init__(f'Compiler failed with exit code {returncode}; no success record written')


def prepareSourceAssets(resolved: ResolvedBuild, sourceRoot: Path) -> None:
  script = resolved.config.get('prepare_source_assets')
  if not script:
    return
  if not isinstance(script, str) or Path(script).is_absolute():
    raise BuildConfigError('prepare_source_assets must be a source-relative Python script')
  path = sourceRoot / script
  rejectLinks(path)
  if not path.resolve().is_relative_to(sourceRoot.resolve()) or not path.is_file():
    raise BuildConfigError(f'Asset preparation script is missing or outside SourceRoot: {path}')
  if path.suffix != '.py':
    raise BuildConfigError('Asset preparation script must be a Python file')
  print(f'Preparing bundled source assets: {path}', flush=True)
  result = subprocess.run([sys.executable, '-B', str(path)], cwd=sourceRoot, check=False)
  if result.returncode:
    raise BuildConfigError(f'Asset preparation failed with exit code {result.returncode}')


def buildCommands(
  resolved: ResolvedBuild, context: BuildContext, *, clean: bool = True,
) -> list[tuple[build.BuildJob, list[str]]]:
  configuration = copy.deepcopy(resolved.config)
  if protocolEnabled(resolved):
    configuration['name'] = 'VisionWorkshopApp'
  commands = build.build_job_commands(configuration, clean=clean, context=context)
  if protocolEnabled(resolved):
    sourceRoot = Path(os.environ.get('SOURCE_ROOT') or Path(resolved.config['entry']).parent)
    for _, command in commands:
      command[-1:-1] = ['--runtime-hook', str(context.workRoot / 'update_identity_hook.py'),
                         '--paths', str(sourceRoot)]
    job = build.BuildJob(label='launcher', entry=str(sourceRoot / 'launcher.py'),
      name='VisionWorkshop', onefile=True, console=False, icon=resolved.config.get('icon'),
      collect_conda_runtime_dlls=False, enable_torch_runtime=False)
    command = build.build_pyinstaller_command(job, clean, str(context.specPath(job.label)),
      str(context.distRoot), str(context.workPath(job.label)))
    command[-1:-1] = ['--paths', str(sourceRoot)]
    commands.insert(0, (job, command))
    # PyInstaller joins these roots to bundled paths with stdlib file APIs.
    # Preserve the extended prefix through COLLECT when Windows policy is off.
    for _, command in commands:
      for option in ('--distpath', '--workpath', '--specpath'):
        index = command.index(option) + 1
        command[index] = str(ioPath(command[index]))
  return commands


def copyNamedUpdater(resolved: ResolvedBuild, context: BuildContext) -> None:
  appDir = context.distRoot / resolved.programName
  updater = resolved.config.get('updater') or {}
  copies = []
  if updater.get('enabled') and updater.get('name', 'updater') != 'updater':
    name = f'{updater["name"]}.exe'
    copies.append((context.distRoot / name, appDir / name))
  for source, target in copies:
    rejectLinks(source)
    rejectLinks(target)
    if target.exists():
      raise BuildConfigError(f'Refusing to replace an existing packaged entrypoint: {target}')
    shutil.copy2(source, target)


def removeProtocolBytecode(resolved: ResolvedBuild, context: BuildContext) -> None:
  distRoot = context.distRoot.absolute()
  appDir = distRoot / resolved.programName / 'app'
  rejectLinks(appDir)
  root = appDir.resolve()
  if root == distRoot.resolve() or not root.is_relative_to(distRoot.resolve()) or not root.is_dir():
    raise BuildConfigError(f'Invalid isolated application output: {appDir}')
  files, directories = [], []

  def scanError(error):
    raise error

  # Directory data mappings can carry development caches into the frozen output.
  # Validate the entire tree before deleting only bytecode inside cache directories.
  for parent, folders, names in os.walk(ioPath(root), followlinks=False, onerror=scanError):
    for name in folders + names:
      path = logicalPath(parent) / name
      rejectLinks(path)
      if not path.resolve().is_relative_to(root):
        raise BuildConfigError(f'Packaged path escapes application output: {path}')
      if '__pycache__' not in [part.casefold() for part in path.relative_to(root).parts]:
        continue
      mode = ioPath(path).lstat().st_mode
      if stat.S_ISDIR(mode):
        directories.append(path)
      elif stat.S_ISREG(mode) and path.suffix.lower() in ('.pyc', '.pyo'):
        files.append(path)
      else:
        raise BuildConfigError(f'Unexpected file in packaged bytecode cache: {path}')
  for path in files:
    rejectLinks(path)
    ioPath(path).unlink()
  for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
    rejectLinks(path)
    ioPath(path).rmdir()
  if files or directories:
    print(f'Removed {len(files)} development bytecode files from isolated release output')


@preventSourceBytecode()
def executeBuild(
  resolved: ResolvedBuild, context: BuildContext, sourceRoot: Path, *, clean: bool = True,
) -> dict:
  if sys.platform != 'win32':
    raise BuildConfigError('Actual VisionWorkshop EXE builds require Windows; use --dry-run here')
  prepareSourceAssets(resolved, sourceRoot)
  commands = buildCommands(resolved, context, clean=clean)
  beforeDetails = {}
  before = inputSnapshot(resolved, sourceRoot, details=beforeDetails)
  rejectLinks(context.workRoot)
  rejectLinks(context.distRoot)
  context.prepare(resolved)
  writeJsonNew(context.workRoot / 'input-snapshot-before.json',
               {'snapshot': before, 'details': beforeDetails})
  if protocolEnabled(resolved):
    launcherJob, launcherCommand = commands.pop(0)
    code = build.run_command(launcherCommand)
    if code:
      raise CompilerError(code)
    prepareProtocol(resolved, context, sourceRoot, before['source']['commit'])
  for _, command in commands:
    code = build.run_command(command)
    if code:
      raise CompilerError(code)
  if protocolEnabled(resolved):
    packageRoot = context.distRoot / 'VisionWorkshop'
    ioPath(packageRoot).mkdir()
    ioPath(context.distRoot / 'VisionWorkshopApp').rename(ioPath(packageRoot / 'app'))
    shutil.copy2(ioPath(context.distRoot / 'VisionWorkshopUpdater.exe'), ioPath(packageRoot / 'app' / 'VisionWorkshopUpdater.exe'))
    shutil.copy2(ioPath(context.distRoot / 'VisionWorkshop.exe'), ioPath(packageRoot / 'VisionWorkshop.exe'))
  else:
    build.copy_updater_to_app_dir(resolved.config, context.distRoot)
    copyNamedUpdater(resolved, context)
  icon = resolved.config.get('icon')
  if icon and fileHash(Path(icon)) != resolved.iconSha256:
    raise BuildConfigError('Icon changed during compilation; rebuild before using this output')
  if protocolEnabled(resolved):
    removeProtocolBytecode(resolved, context)
    runProducer(resolved, context, sourceRoot, 'finalize')
  record = completeRecord(resolved, context, sourceRoot, before, beforeDetails)
  receipt = {
    'schema_version': 1, **resolved.summary(), 'status': 'built-directory',
    'dist_directory': str(context.distRoot / resolved.programName),
    'build_record': str(context.workRoot / 'build-record.json'),
    'archive_created': False, 'release_uploaded': False,
    'reusable_build_record': record['reusable'], 'windows_launch_test': 'not-run',
  }
  writeJsonNew(context.workRoot / 'build-result.json', receipt)
  return record


def runBrandedBuild(
  configPath: Path, *, profilePath: str | None = None, programName: str | None = None,
  iconPath: str | None = None, clean: bool = False, dryRun: bool = False,
  specpath: str | None = None,
) -> int:
  configureConsole()
  try:
    if specpath:
      raise BuildConfigError('--specpath cannot override isolated branding outputs')
    resolved = resolveBuildConfig(
      configPath, profilePath=profilePath, programName=programName, iconPath=iconPath,
    )
    context = createBuildContext(resolved)
    commands = buildCommands(resolved, context, clean=clean)
    summary = resolved.summary()
    summary['dist_directory'] = str(context.distRoot / resolved.programName)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('Window appearance and updater compatibility are NOT verified by this build.')
    print('Local build only. Runtime automatic updates are NOT disabled.')
    if dryRun:
      for job, command in commands:
        print(f'Dry run {job.label} command:')
        print(' '.join(shlex.quote(item) for item in command))
      print('No output was created. The next build uses a new isolated build ID.')
      return 0
    sourceRoot = Path(os.environ.get('SOURCE_ROOT') or Path(resolved.config['entry']).parent)
    executeBuild(resolved, context, sourceRoot.resolve(), clean=clean)
    print(f'Application directory: {context.distRoot / resolved.programName}')
    print(f'Local build record: {context.workRoot / "build-record.json"}')
    print('No ZIP or Release was produced. Use the portable release entry to archive this build.')
    return 0
  except CompilerError as exc:
    print(str(exc), file=sys.stderr)
    return exc.returncode
  except (ValueError, OSError) as exc:
    print(f'Branding build failed: {exc}', file=sys.stderr)
    return 1
