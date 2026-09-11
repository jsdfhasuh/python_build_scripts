"""Build a branded application directory and retain verifiable local provenance."""

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

import build
from build_config import BuildConfigError
from build_config import BuildContext
from build_config import ResolvedBuild
from build_config import createBuildContext
from build_config import resolveBuildConfig
from build_records import completeRecord
from build_records import fileHash
from build_records import inputSnapshot
from build_records import rejectLinks
from build_records import writeJsonNew
from console_utils import configureConsole


class CompilerError(BuildConfigError):
  def __init__(self, returncode: int) -> None:
    self.returncode = returncode
    super().__init__(f'Compiler failed with exit code {returncode}; no success record written')


def buildCommands(
  resolved: ResolvedBuild, context: BuildContext, *, clean: bool = True,
) -> list[tuple[build.BuildJob, list[str]]]:
  commands = build.build_job_commands(resolved.config, clean=clean, context=context)
  if resolved.legacyProgramNames:
    job = build.BuildJob(
      label='legacy-launcher', entry=resolved.config['legacy_launcher_entry'],
      name=resolved.legacyProgramNames[0], onefile=True, console=False,
      icon=resolved.config.get('icon'), collect_conda_runtime_dlls=False,
      enable_torch_runtime=False,
    )
    commands.append((job, build.build_pyinstaller_command(
      job, clean, str(context.specPath(job.label)), str(context.distRoot),
      str(context.workPath(job.label)),
    )))
  return commands


def copyCompatibilityEntrypoints(resolved: ResolvedBuild, context: BuildContext) -> None:
  appDir = context.distRoot / resolved.programName
  updater = resolved.config.get('updater') or {}
  copies = []
  if updater.get('enabled') and updater.get('name', 'updater') != 'updater':
    name = f'{updater["name"]}.exe'
    copies.append((context.distRoot / name, appDir / name))
  if resolved.legacyProgramNames:
    source = context.distRoot / f'{resolved.legacyProgramNames[0]}.exe'
    copies.extend((source, appDir / f'{name}.exe') for name in resolved.legacyProgramNames)
  for source, target in copies:
    rejectLinks(source)
    rejectLinks(target)
    if target.exists():
      raise BuildConfigError(f'Refusing to replace an existing packaged entrypoint: {target}')
    shutil.copy2(source, target)


def executeBuild(
  resolved: ResolvedBuild, context: BuildContext, sourceRoot: Path, *, clean: bool = True,
) -> dict:
  if sys.platform != 'win32':
    raise BuildConfigError('Actual VisionWorkshop EXE builds require Windows; use --dry-run here')
  commands = buildCommands(resolved, context, clean=clean)
  before = inputSnapshot(resolved, sourceRoot)
  rejectLinks(context.workRoot)
  rejectLinks(context.distRoot)
  context.prepare(resolved)
  for _, command in commands:
    code = build.run_command(command)
    if code:
      raise CompilerError(code)
  build.copy_updater_to_app_dir(resolved.config, context.distRoot)
  copyCompatibilityEntrypoints(resolved, context)
  icon = resolved.config.get('icon')
  if icon and fileHash(Path(icon)) != resolved.iconSha256:
    raise BuildConfigError('Icon changed during compilation; rebuild before using this output')
  record = completeRecord(resolved, context, sourceRoot, before)
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
