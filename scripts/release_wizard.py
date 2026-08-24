import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


RELEASE_TAG_PATTERN = re.compile(r'^v[0-9]+(\.[0-9]+){1,3}([-.][A-Za-z0-9._-]+)?$')
REPO_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
LOCAL_STATE_NAME = '.release-wizard.local.json'


def getRepoRoot() -> Path:
  return Path(__file__).resolve().parents[1]


def runCommand(
  args: list[str],
  cwd: Path | None = None,
  capture: bool = True,
) -> subprocess.CompletedProcess[str]:
  stdout = subprocess.PIPE if capture else None
  stderr = subprocess.STDOUT if capture else None
  return subprocess.run(
    args,
    cwd=str(cwd) if cwd else None,
    stdout=stdout,
    stderr=stderr,
    text=True,
    encoding='utf-8',
    errors='replace',
    check=False,
  )


def getCommandOutput(args: list[str], cwd: Path | None = None) -> str:
  result = runCommand(args, cwd=cwd)
  if result.returncode != 0:
    return ''
  return (result.stdout or '').strip()


def requireTool(name: str) -> str:
  toolPath = shutil.which(name)
  if not toolPath:
    raise SystemExit(f'缺少命令：{name}。请先安装或加入 PATH。')
  return toolPath


def getPowerShellExecutable() -> str:
  return shutil.which('pwsh') or shutil.which('powershell') or requireTool('powershell')


def loadLocalState(repoRoot: Path) -> dict[str, str]:
  statePath = repoRoot / LOCAL_STATE_NAME
  if not statePath.exists():
    return {}

  try:
    rawState = json.loads(statePath.read_text(encoding='utf-8'))
  except json.JSONDecodeError:
    return {}

  if not isinstance(rawState, dict):
    return {}

  state: dict[str, str] = {}
  for key, value in rawState.items():
    if isinstance(key, str) and isinstance(value, str):
      state[key] = value
  return state


def saveLocalState(repoRoot: Path, state: dict[str, str]) -> None:
  statePath = repoRoot / LOCAL_STATE_NAME
  statePath.write_text(
    json.dumps(state, indent=2, ensure_ascii=False) + '\n',
    encoding='utf-8',
  )


def loadConfig(configPath: Path) -> dict[str, object]:
  rawConfig = json.loads(configPath.read_text(encoding='utf-8'))
  if not isinstance(rawConfig, dict):
    raise SystemExit(f'配置文件不是 JSON object：{configPath}')
  return rawConfig


def getConfigString(config: dict[str, object], fieldName: str) -> str:
  value = config.get(fieldName, '')
  return value if isinstance(value, str) else ''


def getTargets(repoRoot: Path) -> list[str]:
  configDir = repoRoot / 'configs'
  targets = []
  for configPath in sorted(configDir.glob('*.json')):
    targets.append(configPath.stem)
  return targets


def readPrompt(prompt: str) -> str | None:
  try:
    return input(prompt)
  except EOFError:
    print()
    return None


def promptText(label: str, defaultValue: str = '', required: bool = False) -> str:
  while True:
    suffix = f' [{defaultValue}]' if defaultValue else ''
    rawValue = readPrompt(f'{label}{suffix}: ')
    if rawValue is None:
      if defaultValue:
        return defaultValue
      if required:
        raise SystemExit('输入已结束，已取消。')
      return ''

    value = rawValue.strip()
    if not value and defaultValue:
      return defaultValue
    if value or not required:
      return value
    print('这个值不能为空。')


def promptYesNo(label: str, defaultValue: bool = False) -> bool:
  defaultText = 'Y/n' if defaultValue else 'y/N'
  while True:
    rawValue = readPrompt(f'{label} [{defaultText}]: ')
    if rawValue is None:
      return defaultValue

    value = rawValue.strip().lower()
    if not value:
      return defaultValue
    if value in ('y', 'yes'):
      return True
    if value in ('n', 'no'):
      return False
    print('请输入 y 或 n。')


def promptChoice(
  label: str,
  choices: list[tuple[str, str]],
  defaultKey: str,
) -> str:
  print(label)
  validKeys = {key for key, _ in choices}
  for key, description in choices:
    marker = ' 默认' if key == defaultKey else ''
    print(f'  {key}. {description}{marker}')

  while True:
    rawValue = readPrompt(f'请选择 [{defaultKey}]: ')
    if rawValue is None:
      return defaultKey

    value = rawValue.strip()
    if not value:
      return defaultKey
    if value in validKeys:
      return value
    print('请输入列表中的编号。')


def promptReleaseTag(defaultValue: str = '') -> str:
  while True:
    releaseTag = promptText('Release tag，例如 v1.0.10', defaultValue, required=True)
    if RELEASE_TAG_PATTERN.match(releaseTag):
      return releaseTag
    print('Release tag 必须类似 v1.2.3。')


def promptReleaseRepo(defaultValue: str) -> str:
  while True:
    releaseRepo = promptText('发布仓库 owner/repo', defaultValue, required=True)
    if REPO_PATTERN.match(releaseRepo):
      return releaseRepo
    print('发布仓库必须类似 owner/repo。')


def promptSourceRoot(defaultValue: str) -> Path:
  while True:
    sourceRootText = promptText('本地源码目录', defaultValue, required=True)
    sourceRoot = Path(sourceRootText.strip('"')).expanduser()
    if not sourceRoot.exists():
      print(f'源码目录不存在：{sourceRoot}')
      continue
    if not sourceRoot.is_dir():
      print(f'源码路径不是目录：{sourceRoot}')
      continue
    if not testGitRepo(sourceRoot):
      print(f'源码目录不是 git 仓库：{sourceRoot}')
      continue
    return sourceRoot


def testGitRepo(path: Path) -> bool:
  result = runCommand(['git', '-C', str(path), 'rev-parse', '--is-inside-work-tree'])
  return result.returncode == 0 and (result.stdout or '').strip() == 'true'


def testCommitish(sourceRoot: Path, refName: str) -> bool:
  result = runCommand([
    'git',
    '-C',
    str(sourceRoot),
    'rev-parse',
    '--verify',
    f'{refName}^{{commit}}',
  ])
  return result.returncode == 0


def getGitOutput(sourceRoot: Path, args: list[str]) -> str:
  return getCommandOutput(['git', '-C', str(sourceRoot), *args])


def getCurrentBranch(sourceRoot: Path) -> str:
  return getGitOutput(sourceRoot, ['branch', '--show-current'])


def getHeadCommit(sourceRoot: Path) -> str:
  return getGitOutput(sourceRoot, ['rev-parse', 'HEAD'])


def getRecentCommits(sourceRoot: Path, count: int = 8) -> list[str]:
  output = getGitOutput(sourceRoot, ['log', '--oneline', '-n', str(count)])
  return [line for line in output.splitlines() if line.strip()]


def getRecentCommitRefs(sourceRoot: Path, count: int = 10) -> list[tuple[str, str]]:
  output = getGitOutput(
    sourceRoot,
    ['log', f'--pretty=format:%H%x1f%h%x1f%s', '-n', str(count)],
  )
  commits: list[tuple[str, str]] = []
  for line in output.splitlines():
    parts = line.split('\x1f', 2)
    if len(parts) != 3:
      continue

    fullHash, shortHash, subject = parts
    commits.append((fullHash, f'{shortHash} {subject}'))
  return commits


def getLatestSourceTag(sourceRoot: Path) -> str:
  return getGitOutput(sourceRoot, ['describe', '--tags', '--abbrev=0'])


def getCommitDescription(sourceRoot: Path, refName: str) -> str:
  output = getGitOutput(sourceRoot, ['log', '-1', '--pretty=format:%h %s', refName])
  return output or refName


def getLatestReleaseTag(releaseRepo: str) -> str:
  output = getCommandOutput([
    'gh',
    'release',
    'list',
    '--repo',
    releaseRepo,
    '--limit',
    '1',
    '--json',
    'tagName',
  ])
  if not output:
    return ''

  try:
    releases = json.loads(output)
  except json.JSONDecodeError:
    return ''

  if not isinstance(releases, list) or not releases:
    return ''

  release = releases[0]
  if not isinstance(release, dict):
    return ''

  tagName = release.get('tagName', '')
  return tagName if isinstance(tagName, str) else ''


def getManifestSourceCommit(releaseRepo: str, releaseTag: str) -> str:
  if not releaseTag:
    return ''

  with tempfile.TemporaryDirectory() as tempDir:
    result = runCommand([
      'gh',
      'release',
      'download',
      releaseTag,
      '--repo',
      releaseRepo,
      '--pattern',
      'manifest.json',
      '--dir',
      tempDir,
      '--clobber',
    ])
    if result.returncode != 0:
      return ''

    manifestPath = Path(tempDir) / 'manifest.json'
    if not manifestPath.exists():
      return ''

    try:
      manifest = json.loads(manifestPath.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError:
      return ''

  if not isinstance(manifest, dict):
    return ''

  sourceCommit = manifest.get('source_commit', '')
  return sourceCommit if isinstance(sourceCommit, str) else ''


def bumpPatchVersion(releaseTag: str) -> str:
  match = re.match(r'^v(\d+)\.(\d+)\.(\d+)$', releaseTag)
  if not match:
    return ''

  major, minor, patch = match.groups()
  return f'v{major}.{minor}.{int(patch) + 1}'


def getDefaultTarget(targets: list[str], state: dict[str, str]) -> str:
  stateTarget = state.get('target', '')
  if stateTarget in targets:
    return stateTarget
  if 'emo-vision-train' in targets:
    return 'emo-vision-train'
  return targets[0]


def chooseTarget(targets: list[str], defaultTarget: str) -> str:
  if len(targets) == 1:
    print(f'打包目标：{targets[0]}')
    return targets[0]

  choices = [(str(index + 1), target) for index, target in enumerate(targets)]
  defaultKey = str(targets.index(defaultTarget) + 1)
  selectedKey = promptChoice('请选择打包目标', choices, defaultKey)
  return targets[int(selectedKey) - 1]


def chooseMode() -> str:
  return promptChoice(
    '请选择发布模式',
    [
      ('1', '完整发布：build、压缩、上传 zip 和 manifest'),
      ('2', '跳过 build：使用已有 dist，重新压缩并上传'),
      ('3', '只更新 Release 正文：不 build、不上传 assets'),
    ],
    '1',
  )


def getModeName(modeKey: str) -> str:
  if modeKey == '2':
    return 'skip-build'
  if modeKey == '3':
    return 'notes-only'
  return 'full'


def addPreviousRefCandidate(
  candidates: list[tuple[str, str]],
  seenValues: set[str],
  value: str,
  description: str,
) -> None:
  if not value or value in seenValues:
    return

  candidates.append((value, description))
  seenValues.add(value)


def choosePreviousSourceRef(sourceRoot: Path, previousManifestCommit: str) -> str:
  candidates: list[tuple[str, str]] = []
  seenValues: set[str] = set()

  if previousManifestCommit:
    if testCommitish(sourceRoot, previousManifestCommit):
      commitDescription = getCommitDescription(sourceRoot, previousManifestCommit)
      addPreviousRefCandidate(
        candidates,
        seenValues,
        previousManifestCommit,
        f'上一个 Release manifest source_commit：{commitDescription}',
      )
    else:
      print(f'上一个 Release manifest source_commit 不在本地源码 history：{previousManifestCommit}')

  latestSourceTag = getLatestSourceTag(sourceRoot)
  if latestSourceTag:
    addPreviousRefCandidate(
      candidates,
      seenValues,
      latestSourceTag,
      f'源码仓最新 tag：{latestSourceTag}',
    )

  for commitHash, commitDescription in getRecentCommitRefs(sourceRoot):
    addPreviousRefCandidate(
      candidates,
      seenValues,
      commitHash,
      f'最近源码 commit：{commitDescription}',
    )

  choices: list[tuple[str, str]] = []
  valueByKey: dict[str, str] = {}
  for index, (value, description) in enumerate(candidates, 1):
    key = str(index)
    choices.append((key, description))
    valueByKey[key] = value

  autoKey = str(len(choices) + 1)
  manualKey = str(len(choices) + 2)
  choices.append((autoKey, 'auto：交给发布脚本自动判断'))
  choices.append((manualKey, '手动输入源码 commit/tag/branch'))

  defaultKey = '1' if candidates else autoKey
  selectedKey = promptChoice('请选择 PreviousSourceRef（更新日志起点）', choices, defaultKey)
  if selectedKey == autoKey:
    return ''
  if selectedKey == manualKey:
    manualRef = promptText('请输入 PreviousSourceRef', required=True)
    if not testCommitish(sourceRoot, manualRef):
      raise SystemExit(f'PreviousSourceRef 不在源码仓 history 里：{manualRef}')
    return manualRef

  selectedRef = valueByKey[selectedKey]
  if not testCommitish(sourceRoot, selectedRef):
    raise SystemExit(f'PreviousSourceRef 不在源码仓 history 里：{selectedRef}')
  return selectedRef


def buildPublishCommand(
  powerShellExe: str,
  repoRoot: Path,
  target: str,
  releaseTag: str,
  releaseRepo: str,
  sourceRoot: Path,
  sourceRef: str,
  previousSourceRef: str,
  notes: str,
  releaseBodyPath: str,
  mandatory: bool,
  modeName: str,
) -> list[str]:
  scriptPath = repoRoot / 'scripts' / 'publish-local-release.ps1'
  command = [
    powerShellExe,
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    str(scriptPath),
    '-Target',
    target,
    '-ReleaseTag',
    releaseTag,
    '-ReleaseRepo',
    releaseRepo,
    '-SourceRoot',
    str(sourceRoot),
    '-SourceRef',
    sourceRef,
  ]

  if previousSourceRef:
    command.extend(['-PreviousSourceRef', previousSourceRef])
  if notes:
    command.extend(['-Notes', notes])
  if releaseBodyPath:
    command.extend(['-ReleaseBodyPath', releaseBodyPath])
  if mandatory:
    command.append('-Mandatory')
  if modeName == 'skip-build':
    command.append('-SkipBuild')
  if modeName == 'notes-only':
    command.append('-NotesOnly')

  return command


def printHeader(title: str) -> None:
  print()
  print('=' * 72)
  print(title)
  print('=' * 72)


def printRecentCommits(sourceRoot: Path) -> None:
  recentCommits = getRecentCommits(sourceRoot)
  if not recentCommits:
    return

  print('源码仓最近 commits：')
  for commitLine in recentCommits:
    print(f'  {commitLine}')


def printSummary(
  target: str,
  releaseTag: str,
  releaseRepo: str,
  sourceRoot: Path,
  sourceRef: str,
  previousSourceRef: str,
  notes: str,
  releaseBodyPath: str,
  mandatory: bool,
  modeName: str,
  headCommit: str,
  command: list[str],
) -> None:
  printHeader('发布确认')
  print(f'目标：{target}')
  print(f'模式：{modeName}')
  print(f'Release tag：{releaseTag}')
  print(f'发布仓库：{releaseRepo}')
  print(f'源码目录：{sourceRoot}')
  print(f'源码 ref：{sourceRef}')
  print(f'源码 HEAD：{headCommit}')
  print(f'更新日志起点：{previousSourceRef or "自动判断"}')
  print(f'Manifest notes：{notes or "默认使用版本号"}')
  print(f'强制更新：{"是" if mandatory else "否"}')
  print(f'自定义 Release 正文：{releaseBodyPath or "无"}')
  print()
  print('将执行的命令：')
  print(subprocess.list2cmdline(command))


def main() -> int:
  parser = argparse.ArgumentParser(description='交互式本地发布向导')
  parser.add_argument('--yes', action='store_true', help='跳过最终确认，直接执行')
  args = parser.parse_args()

  repoRoot = getRepoRoot()
  state = loadLocalState(repoRoot)
  requireTool('git')
  requireTool('gh')
  powerShellExe = getPowerShellExecutable()

  ghStatus = runCommand(['gh', 'auth', 'status'])
  if ghStatus.returncode != 0:
    print(ghStatus.stdout or '')
    raise SystemExit('GitHub CLI 未登录，请先运行 gh auth login。')

  targets = getTargets(repoRoot)
  if not targets:
    raise SystemExit('configs 目录下没有 target JSON。')

  printHeader('本地发布向导')
  print(f'当前 Python：{sys.executable}')
  print('提示：直接回车会使用方括号里的默认值。')

  target = chooseTarget(targets, getDefaultTarget(targets, state))
  config = loadConfig(repoRoot / 'configs' / f'{target}.json')
  sourceRepo = getConfigString(config, 'source_repo')
  releaseRepoDefault = (
    state.get('releaseRepo')
    or getConfigString(config, 'release_repo')
    or getCommandOutput(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'])
  )

  printHeader('源码和发布仓')
  print(f'配置源码仓：{sourceRepo or "未配置"}')
  releaseRepo = promptReleaseRepo(releaseRepoDefault)

  sourceRootDefault = state.get('sourceRoot') or os.environ.get('SOURCE_ROOT', '')
  sourceRoot = promptSourceRoot(sourceRootDefault)
  currentBranch = getCurrentBranch(sourceRoot)
  headCommit = getHeadCommit(sourceRoot)
  print(f'源码当前分支：{currentBranch or "detached HEAD"}')
  print(f'源码 HEAD：{headCommit}')
  printRecentCommits(sourceRoot)

  latestReleaseTag = getLatestReleaseTag(releaseRepo)
  suggestedReleaseTag = bumpPatchVersion(latestReleaseTag)

  printHeader('Release 信息')
  if latestReleaseTag:
    print(f'发布仓最新 Release：{latestReleaseTag}')
  releaseTag = promptReleaseTag(suggestedReleaseTag)
  notesDefault = releaseTag.lstrip('v')
  notes = promptText('Manifest notes', notesDefault, required=False)
  sourceRefDefault = currentBranch or 'local'
  sourceRef = promptText('SourceRef，写入 manifest', sourceRefDefault, required=True)

  previousManifestCommit = getManifestSourceCommit(releaseRepo, latestReleaseTag)
  if previousManifestCommit:
    print(f'检测到上一个 Release manifest source_commit：{previousManifestCommit}')
  previousSourceRef = choosePreviousSourceRef(sourceRoot, previousManifestCommit)

  modeName = getModeName(chooseMode())
  mandatory = False
  if modeName != 'notes-only':
    mandatory = promptYesNo('是否强制更新 mandatory=true', False)

  releaseBodyPath = promptText('自定义 Release 正文 Markdown 路径，留空则自动生成', '')
  if releaseBodyPath and not Path(releaseBodyPath).exists():
    raise SystemExit(f'ReleaseBodyPath 不存在：{releaseBodyPath}')

  command = buildPublishCommand(
    powerShellExe=powerShellExe,
    repoRoot=repoRoot,
    target=target,
    releaseTag=releaseTag,
    releaseRepo=releaseRepo,
    sourceRoot=sourceRoot,
    sourceRef=sourceRef,
    previousSourceRef=previousSourceRef,
    notes=notes,
    releaseBodyPath=releaseBodyPath,
    mandatory=mandatory,
    modeName=modeName,
  )

  printSummary(
    target=target,
    releaseTag=releaseTag,
    releaseRepo=releaseRepo,
    sourceRoot=sourceRoot,
    sourceRef=sourceRef,
    previousSourceRef=previousSourceRef,
    notes=notes,
    releaseBodyPath=releaseBodyPath,
    mandatory=mandatory,
    modeName=modeName,
    headCommit=headCommit,
    command=command,
  )

  state.update({
    'target': target,
    'sourceRoot': str(sourceRoot),
    'releaseRepo': releaseRepo,
  })
  saveLocalState(repoRoot, state)

  if not args.yes and not promptYesNo('确认开始执行', False):
    print('已取消。')
    return 0

  printHeader('开始执行')
  result = runCommand(command, cwd=repoRoot, capture=False)
  return result.returncode


if __name__ == '__main__':
  raise SystemExit(main())
