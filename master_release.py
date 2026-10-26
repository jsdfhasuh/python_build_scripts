"""Build identity, release notes and publication for the two Emo Master packages."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote

from build_config import BuildConfigError
import release_content as content
from scripts.release_wizard_common import getSourceVersion


ROOT = Path(__file__).resolve().parent
TARGETS = ('emo-master', 'emo-master-runtime')
REPOSITORY = 'jsdfhasuh/emo_master'


def readObject(path: Path) -> dict:
  return content.parseObject(path.read_text(encoding='utf-8-sig'), str(path))


def fileHash(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
      digest.update(block)
  return digest.hexdigest()


def loadConfig(target: str) -> dict:
  config = readObject(ROOT / 'configs' / (target + '.json'))
  if config['source_repo'] != REPOSITORY or config['release_repo'] != REPOSITORY:
    raise BuildConfigError('Emo Master releases must use the source repository')
  if not config['installer']['enabled'] or not config['installer']['smoke_test']:
    raise BuildConfigError(f'{target} requires an installer and installation smoke test')
  return config


def checkTag(tag: str, sourceCommit: str, *, required: bool = False) -> None:
  refs = json.loads(content.runTool([
    'gh', 'api', f'repos/{REPOSITORY}/git/matching-refs/tags/{quote(tag, safe="")}',
  ]))
  if not isinstance(refs, list):
    raise BuildConfigError('Invalid GitHub tag lookup response')
  matches = [ref for ref in refs if ref['ref'] == f'refs/tags/{tag}']
  if not matches:
    if required:
      raise BuildConfigError(f'Release tag is missing: {tag}')
    return
  obj = matches[0]['object']
  for _ in range(8):
    if obj['type'] != 'tag':
      break
    obj = content.parseObject(content.runTool([
      'gh', 'api', f'repos/{REPOSITORY}/git/tags/{obj["sha"]}',
    ]), 'Annotated tag')['object']
  if obj['type'] != 'commit' or obj['sha'] != sourceCommit:
    raise BuildConfigError(f'Tag {tag} does not match the built source; choose a new version')


def checkPublication(request: dict) -> None:
  if not os.environ.get('RELEASE_REPO_TOKEN'):
    raise BuildConfigError('Publication requires RELEASE_REPO_TOKEN with source-repository access')
  commit = content.parseObject(content.runTool([
    'gh', 'api', f'repos/{REPOSITORY}/commits/{request["source_commit"]}',
  ]), 'Source commit')
  if commit.get('sha') != request['source_commit']:
    raise BuildConfigError('Source commit is not present in the configured repository')
  checkTag(request['release_tag'], request['source_commit'])
  content.requireNewRelease(REPOSITORY, request['release_tag'])


def prepareRequest(inputs: dict, sourceRoot: Path, state: Path) -> dict:
  versions = [getSourceVersion(loadConfig(target), sourceRoot) for target in TARGETS]
  if versions[0] != versions[1] or not re.fullmatch(r'\d+(\.\d+){1,3}', versions[0]):
    raise BuildConfigError('Both installers require the same numeric application version')
  tag = inputs.get('release_tag', '').strip() or 'v' + versions[0]
  if tag != 'v' + versions[0]:
    raise BuildConfigError(f'Release tag {tag} does not match application version {versions[0]}')
  sourceCommit = content.resolveCommit(sourceRoot, 'HEAD')
  packagerCommit = content.resolveCommit(ROOT, 'HEAD')
  title = content.validateTitle(inputs.get('release_title', '').strip() or f'Emo Master {tag}')
  request = dict(release_tag=tag, source_commit=sourceCommit, packager_commit=packagerCommit,
                 publish=inputs.get('publish_release', False) is True, title=title)
  if request['publish']:
    if content.runTool(['git', '-C', str(sourceRoot), 'status', '--porcelain']):
      raise BuildConfigError('Publication requires a clean source checkout')
    checkPublication(request)
  base = inputs.get('previous_source_ref', '').strip()
  allHistory = inputs.get('changelog_all', False) is True
  if base and allHistory:
    raise BuildConfigError('Choose previous_source_ref or changelog_all, not both')
  if base:
    base = content.resolveBase(sourceRoot, base, sourceCommit)
  elif not allHistory:
    _, base = content.findPreviousSource(REPOSITORY, tag, REPOSITORY, sourceRoot, sourceCommit)
  request['source_base_ref'] = base
  bodyPath = inputs.get('release_body_path', '').strip()
  if bodyPath:
    path = (ROOT / bodyPath).resolve()
    if Path(bodyPath).is_absolute() or not path.is_relative_to(ROOT) or path.suffix != '.md':
      raise BuildConfigError('release_body_path must be a Markdown file inside the packager')
    body = content.readBody(path)
  else:
    body = content.generateBody(
      title=title, notes=inputs.get('notes', '').strip() or versions[0], programName='EmoMaster',
      sourceRepo=REPOSITORY, sourceRoot=sourceRoot, head=sourceCommit, base=base,
      allHistory=allHistory,
      downloadNotes=(
        f'Designer 安装版：`emo-master-setup-{tag}.exe`。',
        f'独立 Runtime 安装版：`emo-master-runtime-setup-{tag}.exe`。',
        '两者安装目录、开始菜单和卸载入口独立，可以同时安装。',
        f'便携版：`emo-master-windows-{tag}.zip` 和 '
        f'`emo-master-runtime-windows-{tag}.zip`，均须完整解压后运行。',
        'Designer 使用 `manifest.json`；Runtime 使用 `runtime-manifest.json`。',
        '保留已有用户数据；相机 SDK 和设备驱动仍需单独安装。',
        '云端检查包含冻结自测、静默安装与卸载及 Runtime 合成运行；'
        '真实相机、PLC、现场模型和长期运行验收未执行。',
      ),
    )
  request['body_sha256'] = content.bodyHash(body)
  state.mkdir(parents=True, exist_ok=True)
  (state / 'release-notes.md').write_text(body, encoding='utf-8')
  (state / 'request.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
  output = os.environ.get('GITHUB_OUTPUT')
  if output:
    with Path(output).open('a', encoding='utf-8') as stream:
      for name, value in (('release_tag', tag), ('source_sha', sourceCommit),
                          ('packager_sha', packagerCommit)):
        stream.write(f'{name}={value}\n')
  return request


def collectAssets(artifacts: Path, request: dict) -> list[tuple[Path, str]]:
  tag = request['release_tag']
  files = []
  for target in TARGETS:
    config = loadConfig(target)
    folder = artifacts / target
    manifestPath = folder / 'manifest.json'
    manifest = readObject(manifestPath)
    if (manifest.get('source_repo') != REPOSITORY
        or manifest.get('source_commit') != request['source_commit']
        or manifest.get('version') != tag[1:]):
      raise BuildConfigError(f'{target} manifest does not match the requested source/version')
    for kind, template in (('portable', config['release_asset_name']),
                            ('setup', config['installer']['release_asset_name'])):
      name = template.replace('${RELEASE_TAG}', tag)
      path = folder / name
      record = manifest.get('assets', {}).get(kind, {})
      expectedUrl = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{quote(name)}'
      if (record.get('name') != name or record.get('url') != expectedUrl
          or not path.is_file() or record.get('sha256') != fileHash(path)):
        raise BuildConfigError(f'{target} {kind} file, URL or SHA256 mismatch')
      if kind == 'portable' and (manifest.get('url') != expectedUrl
                                 or manifest.get('sha256') != record['sha256']):
        raise BuildConfigError(f'{target} top-level portable metadata mismatch')
      files.append((path, name))
    publicName = 'runtime-manifest.json' if target == 'emo-master-runtime' else 'manifest.json'
    files.append((manifestPath, publicName))
  runtime = artifacts / 'emo-master-runtime'
  identity = readObject(runtime / 'runtime-build.json')
  evidence = readObject(runtime / 'archive-check/validation.json')
  for record in (identity, evidence):
    if (record.get('source_commit') != request['source_commit']
        or record.get('packager_commit') != request['packager_commit']):
      raise BuildConfigError('Runtime evidence does not match the requested checkouts')
  if identity.get('publish_requested') is not False:
    raise BuildConfigError('The Runtime build must not publish independently')
  if any(evidence.get(key) != 'PASS' for key in ('status', 'archiveAcceptance', 'nativeAcceptance')):
    raise BuildConfigError('Runtime archive/native acceptance did not pass')
  runtimeZip = next(path for path, name in files if name.startswith('emo-master-runtime-windows-'))
  if evidence.get('archiveSha256') != fileHash(runtimeZip):
    raise BuildConfigError('Runtime acceptance belongs to a different archive')
  return files


def stageAssets(files: list[tuple[Path, str]], output: Path) -> dict[str, dict]:
  if output.exists() and any(output.iterdir()):
    raise BuildConfigError('Public staging directory must be empty')
  output.mkdir(parents=True, exist_ok=True)
  records = {}
  for source, name in files:
    digest = fileHash(source)
    destination = output / name
    shutil.copyfile(source, destination)
    if fileHash(destination) != digest:
      raise BuildConfigError(f'Asset changed while staging: {name}')
    records[name] = dict(size=destination.stat().st_size, digest='sha256:' + digest)
  return records


def publishAssets(request: dict, body: str, output: Path, records: dict[str, dict]) -> str:
  checkPublication(request)
  tag = request['release_tag']
  with tempfile.TemporaryDirectory(prefix='master-release-') as directory:
    payload = Path(directory) / 'release.json'
    payload.write_text(json.dumps(dict(
      tag_name=tag, target_commitish=request['source_commit'], name=request['title'],
      body=body, draft=True,
    ), ensure_ascii=False), encoding='utf-8')
    draft = content.parseObject(content.runTool([
      'gh', 'api', '--method', 'POST', f'repos/{REPOSITORY}/releases', '--input', str(payload),
    ]), 'Created draft')
  if draft.get('draft') is not True or draft.get('tag_name') != tag:
    raise BuildConfigError('GitHub did not create the expected draft release')
  subprocess.run([
    'gh', 'release', 'upload', tag, '--repo', REPOSITORY,
    *[str(output / name) for name in records],
  ], check=True, timeout=1800)
  uploaded = content.getRelease(REPOSITORY, tag)
  if not uploaded or uploaded['id'] != draft['id'] or uploaded.get('draft') is not True:
    raise BuildConfigError('Draft release identity changed during upload')
  assets = uploaded.get('assets', [])
  if len(assets) != len(records) or {asset['name'] for asset in assets} != set(records):
    raise BuildConfigError('Draft assets differ from the six verified public files')
  for asset in assets:
    if asset.get('state') != 'uploaded' or any(
      asset.get(key) != value for key, value in records[asset['name']].items()
    ):
      raise BuildConfigError(f'Uploaded size/digest mismatch: {asset["name"]}')
  checkTag(tag, request['source_commit'])
  published = content.parseObject(content.runTool([
    'gh', 'api', '--method', 'PATCH', f'repos/{REPOSITORY}/releases/{draft["id"]}',
    '-F', 'draft=false', '-f', 'make_latest=true',
  ]), 'Published release')
  if published.get('draft') is not False:
    raise BuildConfigError('GitHub did not confirm publication')
  checkTag(tag, request['source_commit'], required=True)
  return published['html_url']


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('command', choices=('prepare', 'release'))
  parser.add_argument('--source-root', type=Path, required=True)
  parser.add_argument('--state', type=Path, required=True)
  parser.add_argument('--artifacts', type=Path)
  parser.add_argument('--output', type=Path)
  args = parser.parse_args()
  if args.command == 'prepare':
    request = prepareRequest(json.loads(os.environ['MASTER_RELEASE_INPUTS']),
                             args.source_root, args.state)
    print(json.dumps(request, indent=2))
    return 0
  if args.artifacts is None or args.output is None:
    parser.error('release requires --artifacts and --output')
  request = readObject(args.state / 'request.json')
  if (content.resolveCommit(ROOT, 'HEAD') != request['packager_commit']
      or content.resolveCommit(args.source_root, 'HEAD') != request['source_commit']):
    raise BuildConfigError('Checkouts changed after release preparation')
  if any(getSourceVersion(loadConfig(target), args.source_root) != request['release_tag'][1:]
         for target in TARGETS):
    raise BuildConfigError('Application version changed after preparation')
  body = content.readBody(args.state / 'release-notes.md', request['body_sha256'])
  records = stageAssets(collectAssets(args.artifacts, request), args.output)
  if request['publish']:
    print(publishAssets(request, body, args.output, records))
  else:
    print('Both Windows packages verified; build-only, no Release was created.')
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
