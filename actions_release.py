"""Prepare immutable Vision Train CI requests and stage public protocol assets."""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from pathlib import PureWindowsPath
from urllib.parse import quote

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from build_records import writeJsonNew
import release_content as content
from update_protocol_build import ASSET_PREFIX
from update_protocol_build import RELEASE_REPO
from update_protocol_publish import artifactRecords


ROOT = Path(__file__).resolve().parent
IDENTITY_NAME = ASSET_PREFIX + '-release_identity.json'
FILES_NAME = ASSET_PREFIX + '-package_files.json'


def parseVersion(tag: str) -> tuple[int, int, int]:
  match = re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', tag)
  if not match:
    raise BuildConfigError(f'Protocol 2 requires a stable version such as v1.2.3: {tag}')
  return tuple(int(part) for part in match.groups())


def sourceVersion(config: dict, source: Path, requested: str) -> str:
  path = Path(config.get('source_version_file') or 'app_version.py')
  if not path.is_absolute():
    path = source / path
  values = {}
  for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
    targets = node.targets if isinstance(node, ast.Assign) else []
    if isinstance(node, ast.AnnAssign):
      targets = [node.target]
    for target in targets:
      if isinstance(target, ast.Name) and target.id in ('APP_VERSION', '__version__'):
        values[target.id] = node.value.value if isinstance(node.value, ast.Constant) else None
  version = values.get('__version__') if config.get('source_version_file') else (
    values.get('APP_VERSION', values.get('__version__'))
  )
  if not isinstance(version, str) or not version:
    raise BuildConfigError('Source version file must define a literal application version')
  parseVersion(version)
  tag = 'v' + version
  if requested and requested != tag:
    raise BuildConfigError(f'Release tag differs from source version: expected {tag}')
  return tag


def listOfficialReleases(repo: str) -> list[dict]:
  content.validateRepo(repo)
  pages = json.loads(content.runTool([
    'gh', 'api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100',
  ]))
  if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
    raise BuildConfigError('Invalid paginated release list')
  releases = []
  for page in pages:
    for release in page:
      if (not isinstance(release, dict) or type(release.get('id')) is not int
          or not isinstance(release.get('tag_name'), str)
          or type(release.get('draft')) is not bool
          or type(release.get('prerelease')) is not bool):
        raise BuildConfigError('Invalid release in history; cannot determine first release')
      if not release['draft'] and not release['prerelease']:
        releases.append(release)
  return releases


def selectPrevious(releases: list[dict], tag: str) -> dict | None:
  version = parseVersion(tag)
  candidates = []
  for release in releases:
    previous = parseVersion(release['tag_name'])
    if previous < version:
      candidates.append((previous, release))
  if not candidates:
    return None
  candidates.sort(key=lambda item: item[0], reverse=True)
  if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
    raise BuildConfigError('Multiple official releases have the same baseline version')
  return candidates[0][1]


def selectBaseline(releases: list[dict], tag: str, selection: str) -> dict | None:
  if selection == 'none':
    return None
  if selection == 'auto':
    selected = selectPrevious(releases, tag)
    if releases and selected is None:
      raise BuildConfigError('Official history exists but no older baseline is eligible')
    return selected
  matches = [release for release in releases if release['tag_name'] == selection]
  if len(matches) != 1 or parseVersion(selection) >= parseVersion(tag):
    raise BuildConfigError('Explicit baseline must be an existing older official release')
  return matches[0]


def releaseSnapshot(repo: str, tag: str) -> dict:
  release = content.parseObject(content.runTool([
    'gh', 'api', f'repos/{repo}/releases/tags/{quote(tag, safe="")}',
  ]), 'Baseline release')
  if (release.get('tag_name') != tag or type(release.get('id')) is not int
      or release.get('draft') is not False or release.get('prerelease') is not False):
    raise BuildConfigError('Baseline is no longer the selected official release')
  pages = json.loads(content.runTool([
    'gh', 'api', '--paginate', '--slurp',
    f'repos/{repo}/releases/{release["id"]}/assets?per_page=100',
  ]))
  if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
    raise BuildConfigError('Invalid baseline asset pages')
  assets = {}
  for page in pages:
    for asset in page:
      if not isinstance(asset, dict):
        raise BuildConfigError('Invalid baseline asset metadata')
      name = asset.get('name', '')
      validateAssetName(name)
      if (name in assets or asset.get('state') != 'uploaded'
          or type(asset.get('id')) is not int or asset['id'] <= 0
          or type(asset.get('size')) is not int or not 0 < asset['size'] < 2 * 1024**3
          or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or '')):
        raise BuildConfigError('Baseline asset is incomplete, ambiguous or has no SHA-256')
      assets[name] = {key: asset[key] for key in ('id', 'name', 'size', 'digest', 'state')}
  return {'repository': repo, 'id': release['id'], 'tag': tag, 'assets': assets}


def validateAssetName(name: str) -> None:
  if (not isinstance(name, str) or not name or name in ('.', '..')
      or any(char in name for char in '/\\:') or any(ord(char) < 32 for char in name)
      or name.endswith((' ', '.')) or PureWindowsPath(name).is_reserved()):
    raise BuildConfigError(f'Unsafe public asset name: {name!r}')


def downloadAsset(repo: str, asset: dict, directory: Path) -> Path:
  path = directory / asset['name']
  with path.open('xb') as stream:
    result = subprocess.run([
      'gh', 'api', f'repos/{repo}/releases/assets/{asset["id"]}',
      '-H', 'Accept: application/octet-stream',
    ], stdout=stream, stderr=subprocess.PIPE, check=False, timeout=1800)
  if result.returncode:
    raise BuildConfigError('Baseline asset download failed: '
                           + result.stderr.decode('utf-8', errors='replace'))
  verifyAsset(path, asset)
  return path


def verifyAsset(path: Path, expected: dict) -> None:
  rejectLinks(path)
  if (not path.is_file() or path.stat().st_size != expected['size']
      or 'sha256:' + fileHash(path) != expected['digest']):
    raise BuildConfigError(f'Asset bytes differ from frozen metadata: {path.name}')


def prepareBaseline(repo: str, release: dict, source: Path, state: Path,
                    sourceRepo: str) -> Path:
  snapshot = releaseSnapshot(repo, release['tag_name'])
  if snapshot['id'] != release['id']:
    raise BuildConfigError('Baseline release changed during selection')
  directory = state / 'baseline'
  directory.mkdir()
  assets = snapshot['assets']
  for name in (IDENTITY_NAME, FILES_NAME):
    if name not in assets:
      raise BuildConfigError(f'Baseline missing protocol metadata: {name}')
    limit = 65536 if name == IDENTITY_NAME else 32 * 1024**2
    if assets[name]['size'] > limit:
      raise BuildConfigError('Baseline metadata exceeds protocol size limit')
    downloadAsset(repo, assets[name], directory)
  identity = json.loads((directory / IDENTITY_NAME).read_text(encoding='utf-8'))
  buildId = identity.get('build_id', '')
  if not isinstance(buildId, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', buildId):
    raise BuildConfigError('Invalid baseline build identity')
  fullName = f'{ASSET_PREFIX}-{buildId}-full.zip'
  fullNames = {name for name in assets if name.endswith('-full.zip')}
  if fullNames != {fullName}:
    raise BuildConfigError('Baseline full package is missing or ambiguous')
  snapshot['files_name'] = FILES_NAME
  snapshot['full_name'] = fullName
  snapshot['directory'] = str(directory)
  snapshot['source_repository'] = sourceRepo
  lockPath = state / 'baseline-lock.json'
  writeJsonNew(lockPath, snapshot)
  downloadAsset(repo, assets[fullName], directory)
  result = subprocess.run([
    sys.executable, '-X', 'utf8', str(ROOT / 'scripts/validate_actions_baseline.py'),
    '--source-root', str(source), '--lock', str(lockPath),
  ], check=False)
  if result.returncode:
    raise BuildConfigError('Source producer cannot validate/freeze this baseline; '
                           'update the source producer or explicitly select none')
  verifyBaselineLock(lockPath)
  return lockPath


def verifyBaselineLock(path: Path) -> Path:
  rejectLinks(path)
  lock = json.loads(path.read_text(encoding='utf-8'))
  actual = releaseSnapshot(lock['repository'], lock['tag'])
  if any(actual[key] != lock[key] for key in ('repository', 'id', 'tag', 'assets')):
    raise BuildConfigError('Baseline release/assets changed after preparation')
  directory = Path(lock['directory'])
  for name in (IDENTITY_NAME, FILES_NAME, lock['full_name']):
    validateAssetName(name)
    verifyAsset(directory / name, lock['assets'][name])
  return directory / FILES_NAME


def resolveBody(root: Path, value: str) -> Path | None:
  if not value:
    return None
  relative = Path(value)
  if relative.is_absolute() or PureWindowsPath(value).drive or value.startswith(('\\', '/')):
    raise BuildConfigError('Release body must be relative to the packager checkout')
  path = root / relative
  rejectLinks(path)
  if not path.resolve().is_relative_to(root.resolve()) or path.suffix.lower() != '.md':
    raise BuildConfigError('Release body must be a Markdown file inside the packager checkout')
  if not path.is_file():
    raise BuildConfigError('Release body file does not exist')
  return path.resolve()


def booleanInput(inputs: dict, name: str) -> bool:
  value = inputs.get(name, False)
  if value in (False, '', 'false', 'auto', None):
    return False
  if value in (True, 'true'):
    return True
  raise BuildConfigError(f'Invalid boolean input: {name}')


def prepareRequest(inputs: dict, source: Path, state: Path, output: Path) -> dict:
  config = json.loads((ROOT / 'configs/emo-vision-train.json').read_text(encoding='utf-8'))
  source = source.resolve()
  state = state.resolve()
  if state.is_relative_to(ROOT) or state.is_relative_to(source):
    raise BuildConfigError('CI state must live outside both checkouts')
  state.mkdir(parents=True, exist_ok=False)
  ref = inputs.get('source_ref', '').strip()
  head = content.resolveCommit(source, ref)
  if content.resolveCommit(source, 'HEAD') != head:
    raise BuildConfigError('Source ref does not match the checked-out HEAD')
  packager = content.resolveCommit(ROOT, 'HEAD')
  tag = sourceVersion(config, source, inputs.get('release_tag', '').strip())
  repo = inputs.get('release_repo', '').strip() or config['release_repo']
  if repo != RELEASE_REPO:
    raise BuildConfigError('Protocol-2 publication repository is fixed')
  publishing = booleanInput(inputs, 'publish_release')
  if publishing and not os.environ.get('GH_TOKEN'):
    raise BuildConfigError('Publication requires an explicit RELEASE_REPO_TOKEN')
  body = resolveBody(ROOT, inputs.get('release_body_path', '').strip())
  arguments = [f'--source-root={source}', f'--source-ref={head}',
               f'--expected-source-commit={head}', f'--release-tag={tag}',
               f'--release-repo={repo}', f'--output-directory={output.resolve()}']
  for field in ('branding_profile', 'icon_path', 'program_name', 'release_title', 'notes'):
    value = inputs.get(field, '')
    if value:
      arguments.append(f'--{field.replace("_", "-")}={value}')
  from portable_release import makeParser
  from portable_release import resolveRequest
  resolved, _, _, _ = resolveRequest(makeParser().parse_args(
    arguments + ['--publish' if publishing else '--build-only']))
  title = content.validateTitle(inputs.get('release_title') or f'{resolved.programName} {tag}')
  if body:
    arguments += [f'--release-body-path={body}',
                  f'--release-body-sha256={content.bodyHash(content.readBody(body))}']
  releases = listOfficialReleases(repo)
  baseline = selectBaseline(releases, tag, inputs.get('delta_base_tag', 'auto').strip() or 'auto')
  lockPath = prepareBaseline(repo, baseline, source, state, config['source_repo']) if baseline else None
  previousRef = inputs.get('previous_source_ref', '').strip()
  allHistory = booleanInput(inputs, 'changelog_all')
  if previousRef and allHistory:
    raise BuildConfigError('Choose previous_source_ref or changelog_all, not both')
  previousTag = ''
  if previousRef:
    previousRef = content.resolveBase(source, previousRef, head)
  elif not allHistory and not body:
    previous = selectPrevious(releases, tag)
    if previous:
      previousTag = previous['tag_name']
      manifest = content.readManifest(repo, previous)
      previousRef = content.resolveBase(source, content.getPublishedHead(
        manifest, config['source_repo'], source), head)
    elif not releases:
      allHistory = True
    else:
      raise BuildConfigError('No older release for notes; select a source base or body file')
  if previousRef:
    arguments.append(f'--previous-source-ref={previousRef}')
  if allHistory:
    arguments.append('--changelog-all')
  if booleanInput(inputs, 'mandatory'):
    arguments.append('--mandatory')
  if lockPath:
    arguments += [f'--delta-base-tag={baseline["tag_name"]}', f'--delta-base-lock={lockPath}',
                  f'--delta-base-lock-sha256={fileHash(lockPath)}']
  arguments.append('--publish' if publishing else '--build-only')
  request = {'arguments': arguments, 'source_root': str(source), 'source_commit': head,
             'packager_commit': packager, 'release_tag': tag, 'release_repo': repo,
             'baseline_tag': baseline['tag_name'] if baseline else 'none',
             'baseline_lock': str(lockPath) if lockPath else '',
             'baseline_lock_sha256': fileHash(lockPath) if lockPath else '',
             'notes_release': previousTag, 'previous_source_ref': previousRef,
             'release_title': title,
             'program_name': resolved.programName,
             'release_body_path': inputs.get('release_body_path', ''),
             'notes': inputs.get('notes') or tag[1:],
             'mandatory': booleanInput(inputs, 'mandatory'),
             'changelog_all': allHistory, 'publish': publishing,
             'expected_asset_count': 5 if baseline else 3, 'output': str(output.resolve())}
  writeJsonNew(state / 'request.json', request)
  executeRequest(state / 'request.json', dryRun=True)
  summary = {key: value for key, value in request.items()
             if key not in ('arguments', 'baseline_lock', 'source_root', 'output')}
  print(json.dumps(summary, indent=2))
  if os.environ.get('GITHUB_STEP_SUMMARY'):
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
      stream.write('## Vision Train release preparation\n\n```json\n'
                   + json.dumps(summary, indent=2) + '\n```\n')
  return request


def executeRequest(path: Path, *, dryRun: bool = False) -> None:
  request = json.loads(path.read_text(encoding='utf-8'))
  if (content.resolveCommit(Path(request['source_root']), 'HEAD') != request['source_commit']
      or content.resolveCommit(ROOT, 'HEAD') != request['packager_commit']):
    raise BuildConfigError('Checkout changed after CI preparation')
  if request['baseline_lock']:
    lockPath = Path(request['baseline_lock'])
    if fileHash(lockPath) != request['baseline_lock_sha256']:
      raise BuildConfigError('Frozen baseline lock changed')
    verifyBaselineLock(lockPath)
  command = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/publish_visionworkshop.py'),
             *request['arguments']]
  if dryRun:
    command.append('--dry-run')
  if subprocess.run(command, cwd=ROOT, check=False).returncode:
    raise BuildConfigError('Shared portable release entry failed')


def stageAssets(output: Path, destination: Path, *, expectedCount: int | None = None) -> None:
  rejectLinks(output)
  summaryPath = output / 'build-summary.json'
  rejectLinks(summaryPath)
  summary = json.loads(summaryPath.read_text(encoding='utf-8'))
  names = summary.get('protocol_asset_names')
  if not isinstance(names, list) or len(names) not in (3, 5):
    raise BuildConfigError('Expected three or five public protocol assets')
  if expectedCount is not None and len(names) != expectedCount:
    raise BuildConfigError('Protocol asset count differs from the prepared release mode')
  for name in names:
    validateAssetName(name)
  if len({name.casefold() for name in names}) != len(names):
    raise BuildConfigError('Duplicate public asset names')
  fullName = summary.get('asset_name', '')
  if not re.fullmatch(re.escape(ASSET_PREFIX) + r'-[A-Za-z0-9_-]+-full\.zip', fullName):
    raise BuildConfigError('Invalid protocol full asset name')
  expectedNames = {fullName, IDENTITY_NAME, FILES_NAME}
  if len(names) == 5:
    deltaNames = [name for name in names if re.fullmatch(
      re.escape(fullName[:-9]) + r'-from-[A-Za-z0-9_-]+-delta\.zip', name)]
    if len(deltaNames) != 1:
      raise BuildConfigError('Missing or ambiguous delta ZIP')
    expectedNames.update((deltaNames[0], deltaNames[0][:-4] + '_descriptor.json'))
  if set(names) != expectedNames:
    raise BuildConfigError('Unexpected/private file in public protocol asset list')
  for name in names:
    rejectLinks(output / name)
    if not (output / name).is_file():
      raise BuildConfigError(f'Missing protocol asset: {name}')
  expected = summary.get('protocol_assets')
  if artifactRecords([output / name for name in names]) != expected:
    raise BuildConfigError('Public protocol assets differ from build summary')
  rejectLinks(destination)
  destination.mkdir(parents=True, exist_ok=False)
  for name in names:
    shutil.copyfile(output / name, destination / name)
  if artifactRecords([destination / name for name in names]) != expected:
    raise BuildConfigError('Public protocol assets changed while staging')
  writeJsonNew(destination / 'build-summary.json', summary)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('action', choices=('prepare', 'build', 'stage'))
  parser.add_argument('--state', type=Path, required=True)
  parser.add_argument('--source-root', type=Path)
  parser.add_argument('--output', type=Path)
  parser.add_argument('--destination', type=Path)
  args = parser.parse_args()
  try:
    if args.action == 'prepare':
      if not args.source_root or not args.output:
        parser.error('prepare requires --source-root and --output')
      prepareRequest(json.loads(os.environ['RELEASE_INPUTS_JSON']),
                     args.source_root, args.state, args.output)
    elif args.action == 'build':
      executeRequest(args.state / 'request.json')
    else:
      if not args.destination:
        parser.error('stage requires --destination')
      request = json.loads((args.state / 'request.json').read_text(encoding='utf-8'))
      stageAssets(Path(request['output']), args.destination,
                  expectedCount=request['expected_asset_count'])
    return 0
  except (BuildConfigError, OSError, ValueError, KeyError, SyntaxError,
          subprocess.TimeoutExpired) as exc:
    print(f'Actions release failed: {exc}', file=sys.stderr)
    return 1


if __name__ == '__main__':
  raise SystemExit(main())
