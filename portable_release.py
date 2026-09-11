"""VisionWorkshop ZIP orchestration. Publication is always explicit and gated."""

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import quote

import build
from branding_build import CompilerError
from branding_build import buildCommands
from branding_build import executeBuild
from build_config import BuildConfigError
from build_config import BuildContext
from build_config import ResolvedBuild
from build_config import createBuildContext
from build_config import resolveBuildConfig
from build_config import validateFileName
from build_records import CHUNK
from build_records import gitState
from build_records import gitCommit
from build_records import objectHash
from build_records import rejectLinks
from build_records import validateApplication
from build_records import verifyRecord
from build_records import writeJsonNew
from console_utils import configureConsole
from release_content import ReleaseContent
from release_content import bodyHash
from release_content import checkRepository
from release_content import findPreviousSource
from release_content import generateBody
from release_content import getRelease
from release_content import readBody
from release_content import releaseFingerprint
from release_content import requireNewRelease
from release_content import resolveBase
from release_content import updateBody
from release_content import validateTitle
from release_progress import ReleaseProgress


ROOT = Path(__file__).resolve().parent
RELEASE_TAG = re.compile(r'^v[0-9]+(\.[0-9]+){1,3}([-.][A-Za-z0-9._-]+)?$')
REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
MAX_ASSET_BYTES = 2147483647


@dataclass(frozen=True)
class VerifiedArchive:
  programName: str
  filesSha256: str
  sha256: str
  size: int


def hashArchive(path: Path, label: str) -> tuple[str, int]:
  rejectLinks(path)
  before = path.stat()
  digest = hashlib.sha256()
  with ReleaseProgress(label, totalBytes=before.st_size) as progress:
    with path.open('rb') as stream:
      for chunk in iter(lambda: stream.read(CHUNK), b''):
        digest.update(chunk)
        progress.advance(byteCount=len(chunk))
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
      raise BuildConfigError('ZIP changed while hashing')
  return digest.hexdigest(), before.st_size


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
      # ZIP member names must round-trip independently of the Windows code page.
      result = subprocess.run([
        sevenZip, 'a', '-tzip', '-mm=LZMA', '-mx=9', '-md=64m', f'-mmt={threads}', '-mcu=on',
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


def verifyArchive(path: Path, programName: str, expectedFiles: dict) -> VerifiedArchive:
  before = hashArchive(path, 'ZIP 校验前指纹')
  with ReleaseProgress('ZIP 完整内容校验',
                       totalBytes=sum(item['size'] for item in expectedFiles.values()),
                       totalFiles=len(expectedFiles)) as progress:
    verifyArchiveContents(path, programName, expectedFiles, progress)
  after = hashArchive(path, 'ZIP 校验后指纹')
  if before != after:
    raise BuildConfigError('ZIP changed during content verification')
  return VerifiedArchive(programName, objectHash(expectedFiles), after[0], after[1])


def verifyArchiveContents(
  path: Path, programName: str, expectedFiles: dict, progress: ReleaseProgress,
) -> None:
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
          progress.advance(byteCount=len(chunk))
      files[relative] = {'size': size, 'sha256': digest.hexdigest()}
      progress.advance(fileCount=1)
  if files != expectedFiles:
    raise BuildConfigError('ZIP contents differ from the verified application directory')


def validateModes(args: argparse.Namespace) -> None:
  if args.build_only and args.publish:
    raise BuildConfigError('--build-only and --publish cannot be combined')
  if args.notes_only:
    fields = ('branding_profile', 'program_name', 'icon_path', 'release_asset_name',
              'build_record_path', 'skip_build', 'build_only', 'mandatory', 'notes',
              'previous_source_ref', 'changelog_all', 'release_title', 'output_directory', 'config')
    if any(getattr(args, field) for field in fields) or args.source_ref != 'local':
      raise BuildConfigError('Notes-only cannot change branding, build options or manifest fields')
    if not args.release_body_path or not REPOSITORY.fullmatch(args.release_repo):
      raise BuildConfigError('Notes-only requires --release-repo and --release-body-path')
  if args.changelog_all and args.previous_source_ref:
    raise BuildConfigError('--changelog-all and --previous-source-ref cannot be combined')
  if args.release_body_sha256 and not args.release_body_path:
    raise BuildConfigError('--release-body-sha256 requires --release-body-path')
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
  if args.expected_source_commit and args.expected_source_commit != source['commit']:
    raise BuildConfigError('Source HEAD changed after preview; review the release again')
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


def prepareContent(
  args: argparse.Namespace, resolved: ResolvedBuild, sourceRoot: Path, head: str,
) -> ReleaseContent:
  title = validateTitle(args.release_title or f'{resolved.programName} {args.release_tag}')
  base = resolveBase(sourceRoot, args.previous_source_ref, head) if args.previous_source_ref else ''
  if args.publish and not (base or args.changelog_all or args.release_body_path):
    repo = args.release_repo or resolved.config.get('release_repo', '')
    _, base = findPreviousSource(repo, args.release_tag,
                                resolved.config.get('source_repo', ''), sourceRoot, head)
    if not base:
      raise BuildConfigError('没有可用的上次发布记录，请指定日志起点、正文文件或 --changelog-all')
  if args.release_body_path:
    body = readBody(Path(args.release_body_path), args.release_body_sha256)
  else:
    body = generateBody(
      title=title, notes=args.notes or args.release_tag[1:], programName=resolved.programName,
      sourceRepo=resolved.config.get('source_repo', ''), sourceRoot=sourceRoot,
      head=head, base=base, allHistory=args.changelog_all,
      assetName=resolved.assetName(args.release_tag),
      legacyNames=tuple(resolved.legacyProgramNames),
    )
  return ReleaseContent(title, body, head, base)


def runNotesOnly(args: argparse.Namespace) -> dict:
  checkRepository(args.release_repo)
  release = getRelease(args.release_repo, args.release_tag)
  if release is None:
    raise BuildConfigError('要修改正文的 Release 不存在')
  fingerprint = releaseFingerprint(release)
  if args.expected_release_fingerprint and args.expected_release_fingerprint != fingerprint:
    raise BuildConfigError('Release 在确认后变化，请重新预览')
  body = readBody(Path(args.release_body_path), args.release_body_sha256)
  before = release.get('body') or ''
  print(''.join(difflib.unified_diff(before.splitlines(True), body.splitlines(True),
                                   fromfile='当前正文', tofile='拟发布正文')))
  result = {'release_tag': args.release_tag, 'release_repo': args.release_repo,
            'notes_only': True, 'published': False, 'url': release.get('html_url', '')}
  if args.publish and not args.dry_run and body != before:
    updated = updateBody(args.release_repo, args.release_tag, body, fingerprint)
    result.update(published=True, url=updated.get('html_url', result['url']))
    print('仅更新了 Release 正文；标题、ZIP、manifest 均未修改。')
    print(f'Release: {result["url"]}')
  else:
    print('正文未改变。' if body == before else '仅预览，未修改远端正文。')
  return result


def publishAssets(
  args: argparse.Namespace, resolved: ResolvedBuild, sourceRoot: Path, context: BuildContext,
  summary: dict, output: Path, content: ReleaseContent, *, verifiedArchive: VerifiedArchive,
) -> None:
  resolved.assertPublicationAllowed()
  with ReleaseProgress('发布前复查源码、工具和构建目录'):
    _, record = verifyRecord(context.workRoot / 'build-record.json', resolved, sourceRoot)
  if (verifiedArchive.programName != resolved.programName
      or verifiedArchive.filesSha256 != record['files_sha256']
      or verifiedArchive.filesSha256 != summary['files_sha256']
      or verifiedArchive.sha256 != summary['asset_sha256']
      or verifiedArchive.size != summary['asset_size']):
    raise BuildConfigError('ZIP verification does not match the publication inputs')
  archivePath = output / summary['asset_name']
  repo = args.release_repo or resolved.config['release_repo']
  # Only the current run's verified bytes may be reused, never a persisted summary alone.
  with ReleaseProgress('确认发布仓库和版本'):
    requireNewRelease(repo, args.release_tag)
  if hashArchive(archivePath, '上传前复查 ZIP 指纹') != (
    verifiedArchive.sha256, verifiedArchive.size,
  ):
    raise BuildConfigError('ZIP changed before publication')
  url = f'https://github.com/{repo}/releases/download/{quote(args.release_tag, safe="")}/'
  url += quote(summary['asset_name'], safe='')
  manifest = {
    'mandatory': args.mandatory, 'notes': args.notes or args.release_tag[1:],
    'sha256': summary['asset_sha256'], 'url': url, 'version': args.release_tag[1:],
    'source_repo': resolved.config.get('source_repo', ''),
    'source_ref': (args.source_ref if args.source_ref != 'local'
                   else record['inputs']['source']['commit']),
    'source_commit': record['inputs']['source']['commit'],
    'source_base_ref': content.baseCommit, 'source_compare_url': '',
    'archive_compression': summary['archive_compression'],
  }
  if content.baseCommit:
    manifest['source_compare_url'] = (
      f'https://github.com/{manifest["source_repo"]}/compare/'
      f'{content.baseCommit}...{manifest["source_commit"]}'
    )
  manifestPath = output / args.manifest_name
  writeJsonNew(manifestPath, manifest)
  notesPath = context.workRoot / f'release-notes-{uuid.uuid4().hex}.md'
  notesPath.write_text(content.body, encoding='utf-8')
  with ReleaseProgress('上传 ZIP 和 manifest 到 GitHub（取决于上行速度）'):
    runChecked(['gh', 'release', 'create', args.release_tag, str(archivePath), str(manifestPath),
                '--repo', repo, '--title', content.title, '--notes-file', str(notesPath)])


def runRelease(args: argparse.Namespace) -> dict:
  validateModes(args)
  if args.notes_only:
    return runNotesOnly(args)
  with ReleaseProgress('检查配置和源码'):
    resolved, sourceRoot, assetName, source = resolveRequest(args)
  if args.skip_build:
    with ReleaseProgress('检查选定的构建记录、输入和产物'):
      context, record = verifyRecord(Path(args.build_record_path), resolved, sourceRoot)
  else:
    context, record = createBuildContext(resolved), None
  output = chooseOutput(args, resolved, context, sourceRoot)
  if args.publish:
    if source.get('dirty') or not source.get('submodules_ready'):
      raise BuildConfigError('Publication requires clean, versioned source and initialized submodules')
    requireNewRelease(args.release_repo or resolved.config['release_repo'], args.release_tag)
  content = prepareContent(args, resolved, sourceRoot, source['commit'])
  preview = {
    **resolved.summary(), 'asset_name': assetName, 'release_tag': args.release_tag,
    'output_directory': str(output), 'source_commit': source.get('commit'),
    'packager_commit': gitCommit(resolved.packagerRoot),
    'build_record': str(context.workRoot / 'build-record.json'),
    'will_publish': bool(args.publish and not args.dry_run),
    'release_title': content.title, 'source_base_ref': content.baseCommit,
    'release_body_sha256': bodyHash(content.body), 'notes': args.notes or args.release_tag[1:],
    'mandatory': args.mandatory,
  }
  print(json.dumps(preview, ensure_ascii=False, indent=2))
  print('Portable ZIP only. Runtime updates are NOT disabled; window appearance needs app support.')
  if args.dry_run:
    print('\nRelease 正文预览：\n' + content.body)
    if not args.skip_build:
      for job, command in buildCommands(resolved, context):
        print(f'{job.label}: {subprocess.list2cmdline(command)}')
    return preview
  if record is None:
    with ReleaseProgress('编译应用、更新器并记录构建输入和产物'):
      record = executeBuild(resolved, context, sourceRoot)
  if record['inputs']['source'] != source:
    raise BuildConfigError('Source changed after preflight; rebuild with the requested checkout')
  appDir = context.distRoot / resolved.programName
  output.mkdir(parents=True, exist_ok=True)
  temporary = output / f'.{uuid.uuid4().hex}.zip'
  assetPath = output / assetName
  try:
    with ReleaseProgress('压缩 ZIP'):
      compression = compressArchive(appDir, temporary)
    if not temporary.is_file() or not 0 < temporary.stat().st_size <= MAX_ASSET_BYTES:
      raise BuildConfigError('ZIP is missing, empty or exceeds the existing release size limit')
    verifiedArchive = verifyArchive(temporary, resolved.programName, record['files'])
    # Publishing performs this full input/artifact recheck once, immediately before upload.
    if not args.publish:
      with ReleaseProgress('复查源码、工具和构建目录'):
        verifyRecord(context.workRoot / 'build-record.json', resolved, sourceRoot,
                     requireReusable=bool(args.skip_build))
      if hashArchive(temporary, '保存前复查 ZIP 指纹') != (
        verifiedArchive.sha256, verifiedArchive.size,
      ):
        raise BuildConfigError('ZIP changed before finalization')
    temporary.rename(assetPath)
  finally:
    temporary.unlink(missing_ok=True)
  summary = {
    'schema_version': 1, 'target': resolved.target, 'program_name': resolved.programName,
    'release_tag': args.release_tag, 'asset_name': assetName,
    'asset_sha256': verifiedArchive.sha256, 'asset_size': verifiedArchive.size,
    'archive_compression': compression, 'files_sha256': record['files_sha256'],
    'icon_sha256': resolved.iconSha256, 'source_commit': source.get('commit'),
    'packager_commit': record['inputs']['packager'].get('commit'),
    'source_dirty': source.get('dirty', True), 'published': False,
    'update_compatibility': resolved.updateCompatibility,
    'updater_program_name': (resolved.config.get('updater') or {}).get('name'),
    'legacy_program_names': resolved.legacyProgramNames,
    'runtime_updates_disabled': False, 'window_branding': resolved.summary()['window_branding'],
    'runtime_branding': resolved.config.get('runtime_branding'),
    'windows_launch_test': 'not-run',
    'release_title': content.title, 'release_body_sha256': bodyHash(content.body),
    'source_base_ref': content.baseCommit,
  }
  # A failure leaves a valid local ZIP, but never a summary falsely marked as published.
  summaryPath = output / 'build-summary.json'
  writeJsonNew(summaryPath, summary)
  if args.publish:
    publishAssets(args, resolved, sourceRoot, context, summary, output, content,
                  verifiedArchive=verifiedArchive)
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
  parser.add_argument('--source-root', default='')
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
  parser.add_argument('--release-title', default='')
  parser.add_argument('--release-body-sha256', default='')
  parser.add_argument('--expected-source-commit', default='')
  parser.add_argument('--expected-release-fingerprint', default='')
  parser.add_argument('--changelog-all', action='store_true')
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
