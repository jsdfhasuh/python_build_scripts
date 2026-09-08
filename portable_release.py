"""VisionWorkshop ZIP orchestration. Publication is always explicit and gated."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import quote

import build
from branding_build import CompilerError
from branding_build import executeBuild
from build_config import BuildConfigError
from build_config import BuildContext
from build_config import ResolvedBuild
from build_config import createBuildContext
from build_config import resolveBuildConfig
from build_config import validateFileName
from build_records import CHUNK
from build_records import fileHash
from build_records import gitState
from build_records import gitCommit
from build_records import rejectLinks
from build_records import validateApplication
from build_records import verifyRecord
from build_records import writeJsonNew
from console_utils import configureConsole


ROOT = Path(__file__).resolve().parent
RELEASE_TAG = re.compile(r'^v[0-9]+(\.[0-9]+){1,3}([-.][A-Za-z0-9._-]+)?$')
REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
MAX_ASSET_BYTES = 2147483647


def runChecked(arguments: list[str], *, cwd: Path | None = None) -> str:
  result = subprocess.run(
    arguments, cwd=cwd, text=True, encoding='utf-8', errors='replace',
    capture_output=True, check=False,
  )
  if result.returncode:
    raise BuildConfigError(f'{arguments[0]} failed ({result.returncode}): {result.stderr.strip()}')
  return result.stdout.strip()


def compressArchive(appDir: Path, destination: Path) -> str:
  sevenZip = shutil.which('7z')
  if sevenZip:
    for threads in (2, 1):
      result = subprocess.run([
        sevenZip, 'a', '-tzip', '-mm=LZMA', '-mx=9', '-md=64m', f'-mmt={threads}',
        str(destination), f'.{os.sep}{appDir.name}',
      ], cwd=appDir.parent, check=False)
      if result.returncode == 0:
        return 'zip/lzma'
      destination.unlink(missing_ok=True)
      if result.returncode == 8 and threads == 2:
        print('7-Zip memory allocation failed; retrying with one thread.')
        continue
      raise BuildConfigError(f'7-Zip failed with exit code {result.returncode}')
  shell = shutil.which('pwsh') or shutil.which('powershell')
  if not shell:
    raise BuildConfigError('Archive creation requires 7z or PowerShell Compress-Archive')
  runChecked([
    shell, '-NoProfile', '-NonInteractive', '-File',
    str(ROOT / 'scripts/compress-portable-archive.ps1'),
    '-DistDir', str(appDir), '-AssetPath', str(destination),
  ])
  return 'zip/deflate'


def verifyArchive(path: Path, programName: str, expectedFiles: dict) -> None:
  seen = set()
  files = {}
  with zipfile.ZipFile(path) as archive:
    for member in archive.infolist():
      text = member.filename
      parts = PurePosixPath(text).parts
      if ('\\' in text or '\x00' in text or not parts or parts[0] != programName
          or text.startswith('/') or any(part in ('.', '..') for part in text.split('/') if part)
          or text.rstrip('/') != '/'.join(parts)):
        raise BuildConfigError(f'Archive contains unsafe or unexpected path: {text!r}')
      for part in parts:
        validateFileName(part, 'ZIP member')
      folded = text.rstrip('/').casefold()
      if folded in seen:
        raise BuildConfigError(f'Duplicate ZIP member: {text}')
      seen.add(folded)
      mode = (member.external_attr >> 16) & 0o170000
      if mode not in (0, 0o040000, 0o100000):
        raise BuildConfigError(f'Archive contains a link/special file: {text}')
      if member.is_dir():
        continue
      relative = '/'.join(parts[1:])
      if relative not in expectedFiles or member.file_size != expectedFiles[relative]['size']:
        raise BuildConfigError(f'Unexpected file or size in ZIP: {text}')
      digest = hashlib.sha256()
      size = 0
      with archive.open(member) as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
          size += len(chunk)
          if size > expectedFiles[relative]['size']:
            raise BuildConfigError(f'ZIP data exceeds expected size: {text}')
          digest.update(chunk)
      files[relative] = {'size': size, 'sha256': digest.hexdigest()}
  if files != expectedFiles:
    raise BuildConfigError('ZIP contents differ from the verified application directory')


def validateModes(args: argparse.Namespace) -> None:
  if args.build_only and args.publish:
    raise BuildConfigError('--build-only and --publish cannot be combined')
  if args.notes_only:
    raise BuildConfigError('Notes-only does not accept branding; use the unchanged legacy entry')
  if args.manifest_name.lower().endswith('.zip'):
    raise BuildConfigError('Manifest name must not use the ZIP asset extension')
  if args.skip_build != bool(args.build_record_path):
    raise BuildConfigError('--skip-build requires an explicit --build-record-path and vice versa')
  if not RELEASE_TAG.fullmatch(args.release_tag):
    raise BuildConfigError('Release tag must look like v1.2.3')
  if args.target != 'emo-vision-train':
    raise BuildConfigError('Portable branding is supported only for emo-vision-train')


def resolveRequest(args: argparse.Namespace) -> tuple[ResolvedBuild, Path, str, dict]:
  validateModes(args)
  if not args.source_root or not args.source_root.strip():
    raise BuildConfigError('SourceRoot is required')
  sourceRoot = Path(args.source_root).expanduser().absolute()
  rejectLinks(sourceRoot)
  sourceRoot = sourceRoot.resolve()
  if not sourceRoot.is_dir():
    raise BuildConfigError(f'Source directory not found: {sourceRoot}')
  os.environ['SOURCE_ROOT'] = str(sourceRoot)
  os.environ['RELEASE_TAG'] = args.release_tag
  resolved = resolveBuildConfig(
    args.config or ROOT / 'configs/emo-vision-train.json',
    profilePath=args.branding_profile, programName=args.program_name,
    iconPath=args.icon_path, releaseAssetName=args.release_asset_name,
  )
  versionFile = resolved.config.get('source_version_file')
  if versionFile:
    versionPath = Path(versionFile)
    if not versionPath.is_absolute():
      versionPath = sourceRoot / versionPath
    rejectLinks(versionPath)
    match = re.search(r'''__version__\s*=\s*["']([^"']+)["']''',
                      versionPath.read_text(encoding='utf-8'))
    if not match or match.group(1) != args.release_tag[1:]:
      raise BuildConfigError('Release tag does not match the configured source version')
  name = resolved.assetName(args.release_tag, args.manifest_name)
  if name.casefold() == 'build-summary.json' or args.manifest_name.casefold() == 'build-summary.json':
    raise BuildConfigError('ZIP/manifest must not collide with build-summary.json')
  source = gitState(sourceRoot)
  if not source.get('commit'):
    raise BuildConfigError('SourceRoot must be an accessible git repository root without links')
  if args.source_ref != 'local':
    if not args.source_ref or args.source_ref.startswith('-'):
      raise BuildConfigError('Invalid source ref')
    commit = runChecked([
      'git', '-C', str(sourceRoot), 'rev-parse', '--verify', f'{args.source_ref}^{{commit}}',
    ])
    if commit != source.get('commit'):
      raise BuildConfigError('SourceRef does not match the checked-out HEAD; checkout it first')
  if args.publish:
    # This precedes authentication, compilation and every output/write operation.
    resolved.assertPublicationAllowed()
    repo = args.release_repo or resolved.config.get('release_repo', '')
    if not REPOSITORY.fullmatch(repo):
      raise BuildConfigError('An explicit/configured owner/repo is required for publication')
  return resolved, sourceRoot, name, source


def chooseOutput(
  args: argparse.Namespace, resolved: ResolvedBuild, context: BuildContext, sourceRoot: Path,
) -> Path:
  if args.output_directory:
    output = Path(args.output_directory)
    if not output.is_absolute():
      output = resolved.packagerRoot / output
  else:
    output = (resolved.packagerRoot / 'release-output/branding' / resolved.target
              / context.buildId / uuid.uuid4().hex[:12])
  output = output.absolute()
  rejectLinks(output)
  output = output.resolve()
  for forbidden in (sourceRoot, resolved.packagerRoot / 'dist', resolved.packagerRoot / 'build'):
    if output.is_relative_to(forbidden.absolute()):
      raise BuildConfigError('Release output must be outside source, dist and private build data')
  if output.exists() and (not output.is_dir() or any(output.iterdir())):
    raise BuildConfigError('OutputDirectory must be new or empty; never overwrite previous assets')
  return output


def releaseNotes(args: argparse.Namespace, sourceRoot: Path) -> str:
  if args.release_body_path:
    return Path(args.release_body_path).read_text(encoding='utf-8-sig')
  arguments = ['git', '-C', str(sourceRoot), 'log', '--pretty=format:- %h %s']
  if args.previous_source_ref:
    if args.previous_source_ref.startswith('-'):
      raise BuildConfigError('Invalid previous source ref')
    runChecked(['git', '-C', str(sourceRoot), 'rev-parse', '--verify',
                f'{args.previous_source_ref}^{{commit}}'])
    arguments += [f'{args.previous_source_ref}..HEAD']
  else:
    arguments += ['-n', '30', 'HEAD']
  commits = runChecked(arguments) if gitState(sourceRoot).get('commit') else '(Unversioned local source)'
  return f'# {args.release_tag}\n\n{args.notes or "Portable Windows build"}\n\n{commits}\n'


def publishAssets(
  args: argparse.Namespace, resolved: ResolvedBuild, sourceRoot: Path, context: BuildContext,
  summary: dict, output: Path,
) -> None:
  resolved.assertPublicationAllowed()
  # Recheck the directory and source immediately before publishing, not just before zipping.
  _, record = verifyRecord(context.workRoot / 'build-record.json', resolved, sourceRoot)
  archivePath = output / summary['asset_name']
  verifyArchive(archivePath, resolved.programName, record['files'])
  if fileHash(archivePath) != summary['asset_sha256']:
    raise BuildConfigError('ZIP changed before publication')
  repo = args.release_repo or resolved.config['release_repo']
  url = f'https://github.com/{repo}/releases/download/{quote(args.release_tag, safe="")}/'
  url += quote(summary['asset_name'], safe='')
  manifest = {
    'mandatory': args.mandatory, 'notes': args.notes or args.release_tag[1:],
    'sha256': summary['asset_sha256'], 'url': url, 'version': args.release_tag[1:],
    'source_repo': resolved.config.get('source_repo', ''),
    'source_ref': (args.source_ref if args.source_ref != 'local'
                   else record['inputs']['source']['commit']),
    'source_commit': record['inputs']['source']['commit'],
    'source_base_ref': args.previous_source_ref or '', 'source_compare_url': '',
    'archive_compression': summary['archive_compression'],
  }
  if args.previous_source_ref:
    manifest['source_compare_url'] = (
      f'https://github.com/{manifest["source_repo"]}/compare/'
      f'{quote(args.previous_source_ref, safe="")}...{manifest["source_commit"]}'
    )
  manifestPath = output / args.manifest_name
  writeJsonNew(manifestPath, manifest)
  notesPath = context.workRoot / f'release-notes-{uuid.uuid4().hex}.md'
  notesPath.write_text(releaseNotes(args, sourceRoot), encoding='utf-8')
  # Existing release assets are not silently overwritten; an explicit new tag is required.
  existing = subprocess.run(['gh', 'release', 'view', args.release_tag, '--repo', repo],
                            capture_output=True, check=False)
  if existing.returncode == 0:
    raise BuildConfigError('Release already exists; use a new tag (no implicit --clobber)')
  runChecked(['gh', 'release', 'create', args.release_tag, str(archivePath), str(manifestPath),
              '--repo', repo, '--title', args.release_tag, '--notes-file', str(notesPath)])


def runRelease(args: argparse.Namespace) -> dict:
  resolved, sourceRoot, assetName, source = resolveRequest(args)
  if args.skip_build:
    context, record = verifyRecord(Path(args.build_record_path), resolved, sourceRoot)
  else:
    context, record = createBuildContext(resolved), None
  output = chooseOutput(args, resolved, context, sourceRoot)
  preview = {
    **resolved.summary(), 'asset_name': assetName, 'release_tag': args.release_tag,
    'output_directory': str(output), 'source_commit': source.get('commit'),
    'packager_commit': gitCommit(resolved.packagerRoot),
    'build_record': str(context.workRoot / 'build-record.json'),
    'will_publish': bool(args.publish and not args.dry_run),
  }
  print(json.dumps(preview, ensure_ascii=False, indent=2))
  print('Portable ZIP only. Runtime updates are NOT disabled; window branding is not changed.')
  if args.dry_run:
    if not args.skip_build:
      for job, command in build.build_job_commands(resolved.config, True, context=context):
        print(f'{job.label}: {subprocess.list2cmdline(command)}')
    return preview
  if args.publish:
    if source.get('dirty') or not source.get('commit') or not source.get('submodules_ready'):
      raise BuildConfigError('Publication requires clean, versioned source and initialized submodules')
    runChecked(['gh', 'auth', 'status'])
  # Resolve notes before compiling, so a missing supplied file cannot waste a full build.
  if args.release_body_path and not Path(args.release_body_path).is_file():
    raise BuildConfigError('ReleaseBodyPath does not exist')
  if record is None:
    record = executeBuild(resolved, context, sourceRoot)
  if record['inputs']['source'] != source:
    raise BuildConfigError('Source changed after preflight; rebuild with the requested checkout')
  appDir = context.distRoot / resolved.programName
  output.mkdir(parents=True, exist_ok=True)
  temporary = output / f'.{uuid.uuid4().hex}.zip'
  assetPath = output / assetName
  try:
    compression = compressArchive(appDir, temporary)
    if not temporary.is_file() or not 0 < temporary.stat().st_size <= MAX_ASSET_BYTES:
      raise BuildConfigError('ZIP is missing, empty or exceeds the existing release size limit')
    verifyArchive(temporary, resolved.programName, record['files'])
    # Dirty source is allowed for a fresh local build, never for SkipBuild/publication.
    verifyRecord(context.workRoot / 'build-record.json', resolved, sourceRoot,
                 requireReusable=bool(args.skip_build or args.publish))
    temporary.rename(assetPath)
  finally:
    temporary.unlink(missing_ok=True)
  summary = {
    'schema_version': 1, 'target': resolved.target, 'program_name': resolved.programName,
    'release_tag': args.release_tag, 'asset_name': assetName,
    'asset_sha256': fileHash(assetPath), 'asset_size': assetPath.stat().st_size,
    'archive_compression': compression, 'files_sha256': record['files_sha256'],
    'icon_sha256': resolved.iconSha256, 'source_commit': source.get('commit'),
    'packager_commit': record['inputs']['packager'].get('commit'),
    'source_dirty': source.get('dirty', True), 'published': False,
    'update_compatibility': 'unverified' if resolved.renamed else 'unchanged-name-not-retested',
    'runtime_updates_disabled': False, 'window_branding': 'not-adapted-by-packager',
    'windows_launch_test': 'not-run',
  }
  # A failure leaves a valid local ZIP, but never a summary falsely marked as published.
  summaryPath = output / 'build-summary.json'
  writeJsonNew(summaryPath, summary)
  if args.publish:
    publishAssets(args, resolved, sourceRoot, context, summary, output)
    # Replace only the summary created by this run, after successful upload.
    if summaryPath.read_text(encoding='utf-8') != json.dumps(
      summary, ensure_ascii=False, sort_keys=True, indent=2,
    ) + '\n':
      raise BuildConfigError('Publication succeeded, but the local summary was concurrently changed')
    summary['published'] = True
    finalSummary = output / f'.{uuid.uuid4().hex}.json'
    writeJsonNew(finalSummary, summary)
    rejectLinks(summaryPath)
    os.replace(finalSummary, summaryPath)
  print(f'ZIP: {assetPath}')
  print(f'Build record (private, do not distribute): {context.workRoot / "build-record.json"}')
  print(f'Published: {summary["published"]}; Windows application launch not verified here.')
  return summary


def makeParser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--target', default='emo-vision-train')
  parser.add_argument('--config', type=Path)
  parser.add_argument('--source-root', required=True)
  parser.add_argument('--source-ref', default='local')
  parser.add_argument('--release-tag', required=True)
  parser.add_argument('--branding-profile')
  parser.add_argument('--program-name')
  parser.add_argument('--icon-path')
  parser.add_argument('--release-asset-name')
  parser.add_argument('--output-directory')
  parser.add_argument('--build-record-path')
  parser.add_argument('--skip-build', action='store_true')
  parser.add_argument('--dry-run', action='store_true')
  parser.add_argument('--build-only', action='store_true')
  parser.add_argument('--publish', action='store_true')
  parser.add_argument('--notes-only', action='store_true')
  parser.add_argument('--release-repo', default='')
  parser.add_argument('--manifest-name', default='manifest.json')
  parser.add_argument('--mandatory', action='store_true')
  parser.add_argument('--notes', default='')
  parser.add_argument('--previous-source-ref', default='')
  parser.add_argument('--release-body-path')
  return parser


def main(argv: list[str] | None = None) -> int:
  configureConsole()
  originalDirectory = Path.cwd()
  originalEnvironment = {name: os.environ.get(name) for name in ('SOURCE_ROOT', 'RELEASE_TAG')}
  try:
    args = makeParser().parse_args(argv)
    # Resolve user CLI paths before adopting the legacy packager working directory.
    for name in ('source_root', 'config', 'build_record_path', 'release_body_path'):
      value = getattr(args, name)
      if value:
        setattr(args, name, str(Path(value).expanduser().absolute()))
    if args.config:
      args.config = Path(args.config)
    os.chdir(ROOT)
    runRelease(args)
    return 0
  except CompilerError as exc:
    print(str(exc), file=sys.stderr)
    return exc.returncode
  except (BuildConfigError, OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
    print(f'Portable release failed: {exc}', file=sys.stderr)
    return 1
  finally:
    os.chdir(originalDirectory)
    for name, value in originalEnvironment.items():
      if value is None:
        os.environ.pop(name, None)
      else:
        os.environ[name] = value


if __name__ == '__main__':
  raise SystemExit(main())
