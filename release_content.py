"""Release text and read-only provenance queries, independent of compilation."""

import hashlib
import html
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from build_config import BuildConfigError
from build_config import validateFileName


REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
COMMIT = re.compile(r'^[a-fA-F0-9]{40}([a-fA-F0-9]{24})?$')
MAX_BODY_BYTES = 120000


@dataclass(frozen=True)
class ReleaseContent:
  title: str
  body: str
  headCommit: str
  baseCommit: str = ''


def runTool(arguments: list[str]) -> str:
  try:
    result = subprocess.run(arguments, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', check=False, timeout=30)
  except (OSError, subprocess.TimeoutExpired) as exc:
    raise BuildConfigError(f'无法执行 {arguments[0]}：{exc}') from exc
  if result.returncode:
    raise BuildConfigError(f'{arguments[0]} 执行失败：{result.stderr.strip()}')
  return result.stdout.strip()


def parseObject(text: str, label: str) -> dict:
  try:
    value = json.loads(text.lstrip('\ufeff'))
  except json.JSONDecodeError as exc:
    raise BuildConfigError(f'{label} 不是有效 JSON：{exc}') from exc
  if not isinstance(value, dict):
    raise BuildConfigError(f'{label} 必须是 JSON object')
  return value


def validateRepo(repo: str) -> None:
  if not REPOSITORY.fullmatch(repo):
    raise BuildConfigError('发布仓库必须类似 owner/repo')


def checkRepository(repo: str) -> None:
  validateRepo(repo)
  runTool(['gh', 'api', f'repos/{repo}'])


def getRelease(repo: str, tag: str) -> dict | None:
  validateRepo(repo)
  try:
    result = subprocess.run([
      'gh', 'api', f'repos/{repo}/releases/tags/{quote(tag, safe="")}',
    ], capture_output=True, text=True, encoding='utf-8', errors='replace',
       check=False, timeout=30)
  except (OSError, subprocess.TimeoutExpired) as exc:
    raise BuildConfigError(f'无法查询 Release：{exc}') from exc
  if result.returncode:
    if '(HTTP 404)' in result.stderr:
      return None
    raise BuildConfigError(f'无法查询 Release：{result.stderr.strip()}')
  release = parseObject(result.stdout, 'Release')
  if release.get('tag_name') != tag or not isinstance(release.get('id'), int):
    raise BuildConfigError('Release 返回的版本或 ID 不匹配')
  return release


def requireNewRelease(repo: str, tag: str) -> None:
  # A repository-level 404 must not be mistaken for a free release tag.
  checkRepository(repo)
  if getRelease(repo, tag) is not None:
    raise BuildConfigError(f'Release {tag} 已存在，请改用新版本或“只更新正文”。')


def listReleases(repo: str) -> list[dict]:
  validateRepo(repo)
  text = runTool(['gh', 'api', f'repos/{repo}/releases?per_page=100'])
  try:
    releases = json.loads(text)
  except json.JSONDecodeError as exc:
    raise BuildConfigError('Release 列表不是有效 JSON') from exc
  if not isinstance(releases, list):
    raise BuildConfigError('Release 列表格式异常')
  return [item for item in releases if isinstance(item, dict) and item.get('tag_name')
          and not item.get('draft')]


def readManifest(repo: str, release: dict, manifestName: str = 'manifest.json') -> dict:
  validateFileName(manifestName, 'Manifest name')
  assets = release.get('assets', [])
  if not any(isinstance(asset, dict) and asset.get('name') == manifestName for asset in assets):
    raise BuildConfigError(f'Release {release["tag_name"]} 没有 {manifestName}')
  with tempfile.TemporaryDirectory(prefix='release-manifest-') as directory:
    runTool(['gh', 'release', 'download', release['tag_name'], '--repo', repo,
             '--pattern', manifestName, '--dir', directory])
    path = Path(directory) / manifestName
    try:
      manifest = parseObject(path.read_text(encoding='utf-8-sig'), 'Release manifest')
      version = manifest.get('version')
      if version and str(version) != release['tag_name'].removeprefix('v'):
        raise BuildConfigError('Release manifest 的版本号与所选 Release 不一致')
      return manifest
    except (OSError, UnicodeError) as exc:
      raise BuildConfigError(f'无法读取 Release manifest：{exc}') from exc


def resolveCommit(sourceRoot: Path, ref: str) -> str:
  if not ref or ref.startswith('-'):
    raise BuildConfigError('源码引用不能为空或以 - 开头')
  commit = runTool(['git', '-C', str(sourceRoot), 'rev-parse', '--verify', f'{ref}^{{commit}}'])
  if not COMMIT.fullmatch(commit):
    raise BuildConfigError(f'源码引用没有解析为完整提交：{ref}')
  return commit


def resolveBase(sourceRoot: Path, base: str, head: str) -> str:
  commit = resolveCommit(sourceRoot, base)
  runTool(['git', '-C', str(sourceRoot), 'merge-base', '--is-ancestor', commit, head])
  return commit


def getPublishedHead(manifest: dict, sourceRepo: str, sourceRoot: Path) -> str:
  if manifest.get('source_repo') != sourceRepo:
    raise BuildConfigError('Release manifest 的源码仓与当前配置不一致')
  head = manifest.get('source_commit', '')
  if not isinstance(head, str) or not COMMIT.fullmatch(head):
    raise BuildConfigError('Release manifest 缺少有效的完整 source_commit')
  return resolveCommit(sourceRoot, head)


def findPreviousSource(
  repo: str, tag: str, sourceRepo: str, sourceRoot: Path, head: str,
) -> tuple[str, str]:
  releases = listReleases(repo)
  tags = [release['tag_name'] for release in releases]
  index = tags.index(tag) + 1 if tag in tags else 0
  if index >= len(releases):
    return '', ''
  previous = releases[index]
  manifest = readManifest(repo, previous)
  base = getPublishedHead(manifest, sourceRepo, sourceRoot)
  return previous['tag_name'], resolveBase(sourceRoot, base, head)


def bodyHash(body: str) -> str:
  return hashlib.sha256(body.encode('utf-8')).hexdigest()


def validateBody(body: str) -> str:
  if not body.strip():
    raise BuildConfigError('Release 正文不能为空')
  if '\x00' in body or len(body.encode('utf-8')) > MAX_BODY_BYTES:
    raise BuildConfigError('Release 正文包含 NUL 或超过 120 KB')
  return body


def readBody(path: Path, expectedHash: str = '') -> str:
  try:
    if path.stat().st_size > MAX_BODY_BYTES:
      raise BuildConfigError('Release 正文文件超过 120 KB')
    body = validateBody(path.read_text(encoding='utf-8-sig'))
  except (OSError, UnicodeError) as exc:
    raise BuildConfigError(f'无法读取 UTF-8 正文文件 {path}：{exc}') from exc
  if expectedHash and bodyHash(body) != expectedHash:
    raise BuildConfigError('正文已在确认后变化，请重新预览并确认')
  return body


def validateTitle(title: str) -> str:
  title = title.strip()
  if not title or len(title) > 200 or any(ord(char) < 32 for char in title):
    raise BuildConfigError('Release 标题必须为 1 到 200 个字符，且不能包含控制字符')
  return title


def escapeMarkdown(text: str) -> str:
  return re.sub(r'([\\`*_\[\]])', r'\\\1', html.escape(text))


def getChanges(sourceRoot: Path, head: str, base: str = '', allHistory: bool = False) -> list[str]:
  if not base and not allHistory:
    return []
  revision = f'{base}..{head}' if base else head
  output = runTool(['git', '-C', str(sourceRoot), 'log', '--format=%h %s', revision, '--'])
  return output.splitlines() if output else []


def generateBody(
  *, title: str, notes: str, programName: str, sourceRepo: str, sourceRoot: Path,
  head: str, base: str = '', allHistory: bool = False, assetName: str = '',
  legacyNames: tuple[str, ...] = (),
) -> str:
  changes = getChanges(sourceRoot, head, base, allHistory)
  fixes, other = [], []
  for change in changes:
    subject = change.partition(' ')[2]
    bucket = fixes if re.search(r'(?i)\b(fix|fixes|bug|harden|guard)\b|修复|纠正', subject) else other
    bucket.append('- ' + escapeMarkdown(change))
  lines = [f'# {escapeMarkdown(title)}', '', notes.strip(), '', '## 本次更新', '']
  lines += other or ['- 本范围内没有其他变更。' if base or allHistory
                    else '- 尚未指定更新范围；请确认日志起点或编辑正文。']
  lines += ['', '## 修复与改进', '']
  lines += fixes or ['- 本范围内未按提交标题识别到修复项，请人工核对。']
  if assetName:
    lines += ['', '## 下载与升级', '', f'- 下载并完整解压 {escapeMarkdown(assetName)}。',
              f'- 启动 {escapeMarkdown(programName)}.exe。']
    if legacyNames:
      lines += ['- 保留旧名兼容入口：' + '、'.join(escapeMarkdown(name) + '.exe'
                                                for name in legacyNames) + '。']
  lines += ['', '## 完整变更', '', f'- 源码提交：{head}',
            f'- 日志范围：{base + ".." + head if base else "完整历史（显式选择）" if allHistory else "未指定"}',
            '- 内容按提交标题整理，发布前请人工核对。']
  if base and REPOSITORY.fullmatch(sourceRepo):
    lines += [f'- 源码对比：https://github.com/{sourceRepo}/compare/{base}...{head}']
  if changes:
    lines += ['', '<details>', '<summary>全部提交</summary>', '']
    lines += ['- ' + escapeMarkdown(change) for change in changes]
    lines += ['', '</details>']
  return validateBody('\n'.join(lines) + '\n')


def releaseFingerprint(release: dict) -> str:
  snapshot = {key: release.get(key) for key in (
    'id', 'tag_name', 'name', 'body', 'updated_at',
  )}
  snapshot['assets'] = sorted([
    {key: asset.get(key) for key in ('id', 'name', 'size', 'digest', 'updated_at', 'state')}
    for asset in release.get('assets', []) if isinstance(asset, dict)
  ], key=lambda asset: str(asset.get('id')))
  return bodyHash(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))


def updateBody(repo: str, tag: str, body: str, expectedFingerprint: str) -> dict:
  current = getRelease(repo, tag)
  if current is None or releaseFingerprint(current) != expectedFingerprint:
    raise BuildConfigError('Release 在预览后发生变化，请重新读取并确认，未覆盖正文')
  # PATCH only body: title, assets, manifest and published source remain untouched.
  with tempfile.TemporaryDirectory(prefix='release-body-') as directory:
    payload = Path(directory) / 'body.json'
    payload.write_text(json.dumps({'body': validateBody(body)}, ensure_ascii=False),
                       encoding='utf-8')
    result = runTool(['gh', 'api', '--method', 'PATCH',
                      f'repos/{repo}/releases/{current["id"]}', '--input', str(payload)])
  updated = parseObject(result, '更新后的 Release')
  if updated.get('body') != body:
    raise BuildConfigError('Release 正文更新结果不匹配，请检查远端状态')
  return updated
