"""Explicit portable-target wizard; default/master legacy workflows remain separate."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_config import BuildConfigError
from build_config import resolveBuildConfig
from portable_release import main as releaseMain
from console_utils import configureConsole


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


def collectArguments(*, yes: bool = False) -> list[str] | None:
  mode = choose('执行模式', {
    '1': '只构建 ZIP，不发布', '2': '仅预览',
    '3': '构建并发布（必须通过更新检查）',
    '4': '使用指定构建记录重新归档，不发布',
    '5': '使用指定构建记录归档并发布',
  }, '1')
  appearance = choose('本次外观（不会保存为下次默认）', {
    '1': '原始名称和图标', '2': 'VisionWorkshop 配置档', '3': '本次自定义',
  }, '1')
  source = prompt('本地源码仓库根目录', os.environ.get('SOURCE_ROOT', ''))
  if not source:
    raise BuildConfigError('源码目录不能为空')
  sourcePath = Path(source.strip('"')).expanduser().absolute()
  tag = prompt('版本号，例如 v1.2.3')
  arguments = [f'--source-root={sourcePath}', f'--release-tag={tag}']
  kwargs = {}
  if appearance == '2':
    kwargs['profilePath'] = str(ROOT / 'profiles/visionworkshop.json')
    arguments += [f'--branding-profile={kwargs["profilePath"]}']
    name = prompt('程序文件名，不含 .exe（留空沿用 VisionWorkshop）')
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
    summary = resolved.summary()
    summary['ZIP 文件名'] = resolved.assetName(tag)
    summary['应用根目录'] = resolved.programName + '/'
    summary['是否上传'] = mode in ('3', '5')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
  finally:
    if oldSource is None:
      os.environ.pop('SOURCE_ROOT', None)
    else:
      os.environ['SOURCE_ROOT'] = oldSource
  print('ZIP 解压即用；不会生成安装器。窗口标题未由打包器修改，运行时自动更新未关闭。')
  if not yes and prompt('确认执行？输入 y，其余取消', 'n').lower() not in ('y', 'yes'):
    return None
  return arguments


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
