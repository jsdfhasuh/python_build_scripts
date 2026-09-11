"""Explicit portable-target wizard; default/master legacy workflows remain separate."""

import argparse
import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_config import BuildConfigError
from build_config import ResolvedBuild
from build_config import readJsonObject
from build_config import resolveBuildConfig
from build_records import gitCommit
from build_records import gitState
from build_records import rejectLinks
import release_content as content
from portable_release import RELEASE_TAG
from portable_release import main as releaseMain
from console_utils import configureConsole
from scripts.release_wizard_common import bumpPatchVersion
from scripts.release_wizard_common import loadLocalState


def prompt(label: str, default: str = '') -> str:
  try:
    value = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip()
  except (EOFError, KeyboardInterrupt) as exc:
    raise BuildConfigError('Input ended; cancelled without starting a build') from exc
  return value or default


def choose(label: str, options: dict[str, str], default: str) -> str:
  print(label)
  for key, text in options.items():
    print(f'  {key}. {text}')
  while True:
    value = prompt('请选择', default)
    if value in options:
      return value
    print('请输入列表中的编号。')


def normalizeReleaseTag(value: str) -> str:
  tag = value.strip()
  if tag and tag[0].isdigit():
    tag = 'v' + tag
  if not RELEASE_TAG.fullmatch(tag):
    raise BuildConfigError('版本号必须类似 v1.2.3 或 1.2.3，不能为空。')
  return tag


def readSourceReleaseTag(config: dict, sourcePath: Path) -> str:
  versionFile = config.get('source_version_file') or 'app_version.py'
  if not isinstance(versionFile, str):
    raise BuildConfigError('source_version_file 必须是文件路径')
  versionPath = Path(versionFile.replace('${SOURCE_ROOT}', str(sourcePath)))
  if not versionPath.is_absolute():
    versionPath = sourcePath / versionPath
  if not versionPath.is_file():
    return ''
  # Parse literal assignments without importing or executing application code.
  tree = ast.parse(versionPath.read_text(encoding='utf-8-sig'), filename=str(versionPath))
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
  version = versions.get('__version__') if config.get('source_version_file') else (
    versions.get('APP_VERSION', versions.get('__version__'))
  )
  if not isinstance(version, str):
    raise BuildConfigError(f'无法读取版本文件中的字符串版本号：{versionPath}')
  return normalizeReleaseTag(version)


def suggestReleaseTag(sourcePath: Path) -> str:
  configPath = ROOT / 'configs/emo-vision-train.json'
  try:
    config = json.loads(configPath.read_text(encoding='utf-8-sig'))
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise BuildConfigError(f'无法读取打包配置：{configPath}：{exc}') from exc
  if not isinstance(config, dict):
    raise BuildConfigError(f'打包配置必须是 JSON object：{configPath}')
  try:
    sourceTag = readSourceReleaseTag(config, sourcePath)
  except (OSError, UnicodeError, SyntaxError, BuildConfigError) as exc:
    print(f'无法使用源码版本作为默认值：{exc}')
    sourceTag = ''
  if sourceTag:
    print(f'源码应用版本：{sourceTag}')
    return sourceTag
  releaseRepo = config.get('release_repo')
  gh = shutil.which('gh')
  if not isinstance(releaseRepo, str) or not releaseRepo or not gh:
    print('未找到可用的默认版本，请手动输入。')
    return ''
  try:
    result = subprocess.run([
      gh, 'release', 'list', '--repo', releaseRepo, '--limit', '100',
      '--json', 'tagName,isDraft',
    ], capture_output=True, text=True, encoding='utf-8', errors='replace',
       check=False, timeout=10)
    releases = json.loads(result.stdout) if result.returncode == 0 else []
    if isinstance(releases, list):
      for release in releases:
        if not isinstance(release, dict) or release.get('isDraft') is True:
          continue
        latestTag = release.get('tagName')
        if isinstance(latestTag, str) and latestTag:
          suggestedTag = bumpPatchVersion(latestTag)
          if suggestedTag:
            print(f'发布仓最近 Release：{latestTag}，建议下一版本：{suggestedTag}')
            return suggestedTag
          break
  except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
    print(f'无法查询发布版本：{exc}')
  print('未找到可用的默认版本，请手动输入。')
  return ''


def promptReleaseTag(default: str) -> str:
  while True:
    value = prompt('版本号，例如 v1.2.3（可省略 v）', default)
    try:
      return normalizeReleaseTag(value)
    except BuildConfigError as exc:
      print(exc)


def getDefaultSourceRoot() -> str:
  if os.environ.get('SOURCE_ROOT'):
    return os.environ['SOURCE_ROOT']
  try:
    state = loadLocalState(ROOT)
  except (OSError, UnicodeError) as exc:
    print(f'无法读取上次的源码目录：{exc}')
    return ''
  if state.get('target') in (None, 'emo-vision-train'):
    return state.get('sourceRoot', '')
  return ''


def promptBoolean(label: str, default: bool = False) -> bool:
  while True:
    value = prompt(label + '（y/n）', 'y' if default else 'n').lower()
    if value in ('y', 'yes', 'n', 'no'):
      return value in ('y', 'yes')
    print('请输入 y 或 n。')


def promptBodyPath() -> str:
  while True:
    path = Path(prompt('正文 Markdown 文件路径').strip('"')).expanduser().absolute()
    try:
      return content.readBody(path)
    except BuildConfigError as exc:
      print(exc)


def saveDraft(body: str) -> Path:
  directory = ROOT / 'artifacts/release-drafts'
  rejectLinks(directory)
  directory.mkdir(parents=True, exist_ok=True)
  path = directory / f'release-{uuid.uuid4().hex}.md'
  with path.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(content.validateBody(body))
  print(f'正文草稿：{path}')
  return path


def editBody(body: str) -> str:
  method = choose('编辑正文', {'1': '打开草稿编辑', '2': '导入 Markdown 文件'}, '1')
  if method == '2':
    return promptBodyPath()
  path = saveDraft(body)
  if os.name == 'nt':
    try:
      subprocess.Popen(['notepad.exe', str(path)])
    except OSError as exc:
      print(f'无法打开记事本，请用其他编辑器修改上述文件：{exc}')
  while True:
    prompt('编辑并保存上述文件后按回车，重新读取正文')
    try:
      return content.readBody(path)
    except BuildConfigError as exc:
      print(exc)


def chooseRange(
  sourcePath: Path, head: str, repo: str, tag: str, sourceRepo: str, defaultBase: str = '',
) -> tuple[str, bool]:
  default = '2' if defaultBase or not repo else '1'
  while True:
    selected = choose('更新日志起点', {
      '1': '读取上次 Release 的 manifest', '2': '手动指定源码 commit/tag',
      '3': '首次发布，使用截至本版本的完整历史',
    }, default)
    try:
      if selected == '1':
        previousTag, base = content.findPreviousSource(repo, tag, sourceRepo, sourcePath, head)
        if not base:
          raise BuildConfigError('没有找到上次发布记录，请选择手动起点或首次发布。')
        print(f'上次发布：{previousTag}')
      elif selected == '2':
        base = content.resolveBase(sourcePath, prompt('源码 commit/tag', defaultBase), head)
      else:
        base = ''
      changes = content.getChanges(sourcePath, head, base, selected == '3')
      print(f'日志范围：{base or "完整历史"} -> {head}，共 {len(changes)} 个提交')
      if len(changes) > 50 and not promptBoolean('超过 50 个提交，仍使用这个范围吗'):
        continue
      if not changes:
        print('此范围没有新增提交，请核对起点和发布版本。')
      return base, selected == '3'
    except BuildConfigError as exc:
      print(f'无法确定日志范围：{exc}')
      default = '2'


def collectReleaseDocument(
  resolved: ResolvedBuild, sourcePath: Path, tag: str, repo: str, publish: bool,
  previous: dict | None = None,
) -> dict | None:
  if not publish and not promptBoolean('是否准备发布文档（不代表上传）', bool(previous)):
    return None
  head = content.resolveCommit(sourcePath, 'HEAD')
  if previous and previous['head'] != head:
    raise BuildConfigError('源码 HEAD 已改变，请重新启动向导并核对发布内容。')
  previous = previous or {}
  while True:
    try:
      title = content.validateTitle(prompt('Release 标题',
                                            previous.get('title', f'{resolved.programName} {tag}')))
      break
    except BuildConfigError as exc:
      print(exc)
  notes = prompt('更新短说明（写入 manifest，不是完整正文）', previous.get('notes', tag[1:]))
  mandatory = promptBoolean('是否强制更新', previous.get('mandatory', False))
  methods = {'1': '按源码变更生成中文草稿', '2': '使用 Markdown 文件'}
  if previous:
    methods['3'] = '保留已编辑的正文（标题和摘要独立修改）'
  method = choose('Release 正文', methods, '3' if previous else '1')
  base, allHistory = '', False
  if method == '3':
    body, base, allHistory = previous['body'], previous['base'], previous['all_history']
  elif method == '2':
    body = promptBodyPath()
  else:
    base, allHistory = chooseRange(sourcePath, head, repo, tag,
                                  resolved.config.get('source_repo', ''))
    body = content.generateBody(
      title=title, notes=notes, programName=resolved.programName,
      sourceRepo=resolved.config.get('source_repo', ''), sourceRoot=sourcePath,
      head=head, base=base, allHistory=allHistory, assetName=resolved.assetName(tag),
      legacyNames=tuple(resolved.legacyProgramNames),
    )
  return {'title': title, 'notes': notes, 'mandatory': mandatory, 'head': head,
          'base': base, 'all_history': allHistory, 'body': body}


def reviewDocument(
  summary: dict, body: str, *, yes: bool, details: dict | None = None,
  originalBody: str | None = None,
) -> tuple[str, str]:
  print('\n发布确认')
  for label, value in summary.items():
    print(f'{label}：{value}')
  if body:
    print('\n正文摘要：\n' + '\n'.join(body.splitlines()[:16]))
  while True:
    if yes:
      return 'y', body
    action = prompt('确认执行？y 执行 / p 全文 / e 编辑 / s 保存草稿 / b 返回修改 / d 详细 / n 取消',
                    'n').lower()
    if action in ('y', 'yes'):
      return 'y', body
    if action in ('n', 'no'):
      return 'n', body
    if action == 'b':
      return 'b', body
    if action == 'd':
      print(json.dumps(details or summary, ensure_ascii=False, indent=2))
    elif body and action == 'p':
      print(body)
      if originalBody is not None:
        print(''.join(difflib.unified_diff(originalBody.splitlines(True), body.splitlines(True),
                                         fromfile='当前正文', tofile='拟发布正文')))
    elif body and action == 'e':
      body = editBody(body)
      print('\n修改后的正文：\n' + body)
      if originalBody is not None:
        print(''.join(difflib.unified_diff(originalBody.splitlines(True), body.splitlines(True),
                                         fromfile='当前正文', tofile='拟发布正文')))
    elif body and action == 's':
      saveDraft(body)
    else:
      print('请选择有效操作；本次未配置正文时，请按 b 返回准备文档。')


def finishRelease(
  arguments: list[str], resolved: ResolvedBuild, sourcePath: Path, tag: str, mode: str, yes: bool,
) -> list[str] | None:
  publishing = mode in ('3', '5')
  repo = resolved.config.get('release_repo', '')
  if publishing:
    while True:
      repo = prompt('发布仓库 owner/repo', repo)
      try:
        content.validateRepo(repo)
        break
      except BuildConfigError as exc:
        print(exc)
    source = gitState(sourcePath)
    if source.get('dirty') or not source.get('submodules_ready'):
      raise BuildConfigError('发布前请提交源码改动并初始化子模块；可选择仅预览或只构建 ZIP。')
    content.requireNewRelease(repo, tag)
    arguments += [f'--release-repo={repo}']
  draft = None
  while True:
    draft = collectReleaseDocument(resolved, sourcePath, tag, repo, publishing, previous=draft)
    summary = {
      '模式': '构建并发布' if publishing else '仅预览' if mode == '2' else '本地构建/归档',
      '发布仓库': repo or '未配置（本次不上传）', 'Release tag': tag,
      '源码目录': str(sourcePath), '源码提交': draft['head'] if draft else gitCommit(sourcePath),
      '程序': resolved.programName, '更新器': (resolved.config.get('updater') or {}).get('name', '无'),
      'ZIP 文件名': resolved.assetName(tag), '应用根目录': resolved.programName + '/',
      '是否上传': '是' if publishing else '否',
    }
    if draft:
      summary.update({'Release 标题': draft['title'], '更新短说明': draft['notes'],
                      '强制更新': '是' if draft['mandatory'] else '否',
                      '日志起点': draft['base'] or ('完整历史' if draft['all_history'] else '自定义正文')})
    action, body = reviewDocument(summary, draft['body'] if draft else '', yes=yes,
                                  details=resolved.summary())
    if action == 'n':
      return None
    if action == 'b':
      if draft:
        draft['body'] = body
      continue
    if draft:
      path = saveDraft(body)
      arguments += [f'--release-body-path={path}',
                    f'--release-body-sha256={content.bodyHash(body)}',
                    f'--release-title={draft["title"]}', f'--notes={draft["notes"]}',
                    f'--expected-source-commit={draft["head"]}']
      if draft['base']:
        arguments += [f'--previous-source-ref={draft["base"]}']
      if draft['all_history']:
        arguments += ['--changelog-all']
      if draft['mandatory']:
        arguments += ['--mandatory']
    return arguments


def collectNotesArguments(*, yes: bool = False) -> list[str] | None:
  config = readJsonObject(ROOT / 'configs/emo-vision-train.json')
  repo = prompt('要修改正文的发布仓库 owner/repo', config.get('release_repo', ''))
  content.checkRepository(repo)
  releases = content.listReleases(repo)
  options = {str(index): release['tag_name'] for index, release in enumerate(releases[:10], 1)}
  options['m'] = '手动输入已有 Release 版本'
  selected = choose('选择已有 Release（不创建新版本）', options, '1' if releases else 'm')
  tag = promptReleaseTag('') if selected == 'm' else options[selected]
  release = content.getRelease(repo, tag)
  if release is None:
    raise BuildConfigError('选中的 Release 不存在')
  fingerprint = content.releaseFingerprint(release)
  originalBody = release.get('body') or ''
  workingBody = originalBody
  while True:
    method = choose('正文来源', {'1': '编辑该 Release 现有正文', '2': '使用 Markdown 文件',
                                 '3': '按该 Release 已发布源码记录重新生成'}, '1')
    if method == '1':
      body = editBody(workingBody or f'# {tag}\n')
    elif method == '2':
      body = promptBodyPath()
    else:
      sourcePath = Path(prompt('本地源码仓库根目录', getDefaultSourceRoot()).strip('"')).resolve()
      manifest = content.readManifest(repo, release)
      head = content.getPublishedHead(manifest, config.get('source_repo', ''), sourcePath)
      base = manifest.get('source_base_ref') or ''
      if base:
        base, allHistory = content.resolveBase(sourcePath, base, head), False
      else:
        base, allHistory = chooseRange(sourcePath, head, repo, tag, config.get('source_repo', ''))
      body = content.generateBody(
        title=release.get('name') or tag, notes=str(manifest.get('notes') or ''),
        programName='', sourceRepo=config.get('source_repo', ''), sourceRoot=sourcePath,
        head=head, base=base, allHistory=allHistory,
      )
    print(''.join(difflib.unified_diff(originalBody.splitlines(True), body.splitlines(True),
                                     fromfile='当前正文', tofile='拟发布正文')))
    action, body = reviewDocument({'模式': '只更新正文', '发布仓库': repo, 'Release tag': tag,
                                   '不会修改': 'Release 标题、ZIP、manifest、版本号及校验值'},
                                  body, yes=yes, originalBody=originalBody)
    if action == 'n':
      return None
    if action == 'b':
      workingBody = body
      continue
    path = saveDraft(body)
    return ['--notes-only', '--publish', f'--release-repo={repo}', f'--release-tag={tag}',
            f'--release-body-path={path}', f'--release-body-sha256={content.bodyHash(body)}',
            f'--expected-release-fingerprint={fingerprint}']


def collectArguments(*, yes: bool = False) -> list[str] | None:
  print('提示：直接回车会使用方括号里的默认值。')
  mode = choose('执行模式', {
    '1': '只构建 ZIP，不发布', '2': '仅预览',
    '3': '构建并发布（必须通过更新检查）',
    '4': '使用指定构建记录重新归档，不发布',
    '5': '使用指定构建记录归档并发布',
    '6': '只更新已有 Release 的正文（不构建、不改资产）',
  }, '1')
  if mode == '6':
    return collectNotesArguments(yes=yes)
  appearance = choose('本次外观（不会保存为下次默认）', {
    '1': '原始名称和图标', '2': 'VisionWorkshop 配置档', '3': '本次自定义',
  }, '1')
  source = prompt('本地源码仓库根目录', getDefaultSourceRoot())
  if not source:
    raise BuildConfigError('源码目录不能为空')
  sourcePath = Path(source.strip('"')).expanduser().absolute()
  if not sourcePath.is_dir():
    raise BuildConfigError(f'源码目录不存在：{sourcePath}')
  tag = promptReleaseTag(suggestReleaseTag(sourcePath))
  arguments = [f'--source-root={sourcePath}', f'--release-tag={tag}']
  kwargs = {}
  if appearance == '2':
    kwargs['profilePath'] = str(ROOT / 'profiles/visionworkshop.json')
    arguments += [f'--branding-profile={kwargs["profilePath"]}']
    name = prompt('程序文件名，不含 .exe（留空使用 VisionWorkshop 及旧名兼容入口）')
    if name:
      kwargs['programName'] = name
      arguments += [f'--program-name={name}']
    icon = prompt('ICO 路径（留空使用配置档中的路径）')
  elif appearance == '3':
    name = prompt('程序文件名，不含 .exe', 'VisionWorkshop')
    kwargs['programName'] = name
    arguments += [f'--program-name={name}']
    icon = prompt('ICO 路径（留空沿用原图标）')
    asset = prompt('ZIP 名称模板', '${PROGRAM_NAME}-windows-${RELEASE_TAG}.zip')
    kwargs['releaseAssetName'] = asset
    arguments += [f'--release-asset-name={asset}']
  else:
    icon = ''
  if icon:
    kwargs['iconPath'] = icon.strip('"')
    arguments += [f'--icon-path={kwargs["iconPath"]}']
  if mode in ('4', '5'):
    record = prompt('完整的 build-record.json 路径')
    if not record:
      raise BuildConfigError('必须显式选择构建记录，不能自动使用最近的 dist')
    arguments += ['--skip-build', f'--build-record-path={record.strip(chr(34))}']
  if mode in ('3', '5'):
    arguments += ['--publish']
  elif mode == '2':
    arguments += ['--dry-run']
  else:
    arguments += ['--build-only']
  oldSource = os.environ.get('SOURCE_ROOT')
  try:
    os.environ['SOURCE_ROOT'] = str(sourcePath)
    resolved = resolveBuildConfig(ROOT / 'configs/emo-vision-train.json', **kwargs)
    if mode in ('3', '5'):
      resolved.assertPublicationAllowed()
  finally:
    if oldSource is None:
      os.environ.pop('SOURCE_ROOT', None)
    else:
      os.environ['SOURCE_ROOT'] = oldSource
  print('ZIP 解压即用；不会生成安装器。窗口外观由源码读取品牌配置，运行时自动更新未关闭。')
  return finishRelease(arguments, resolved, sourcePath, tag, mode, yes)


def main(argv: list[str] | None = None) -> int:
  configureConsole()
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--yes', action='store_true', help='Skip final confirmation, not validation')
  parser.add_argument('--legacy', action='store_true', help='Open the unchanged legacy wizard')
  args = parser.parse_args(argv)
  if args.legacy:
    from release_wizard_common import LOCAL_STATE_NAME
    from release_wizard_common import main as legacyMain
    oldArguments = sys.argv
    try:
      sys.argv = [oldArguments[0]] + (['--yes'] if args.yes else [])
      return legacyMain(fixedTarget='emo-vision-train', localStateName=LOCAL_STATE_NAME)
    finally:
      sys.argv = oldArguments
  try:
    arguments = collectArguments(yes=args.yes)
    if arguments is None:
      print('已取消，没有构建或发布。')
      return 0
    # In-process invocation keeps exactly the interpreter running the wizard.
    return releaseMain(arguments)
  except (BuildConfigError, OSError) as exc:
    print(f'无法开始打包：{exc}', file=sys.stderr)
    return 1


if __name__ == '__main__':
  raise SystemExit(main())
