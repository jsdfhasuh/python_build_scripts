"""Build the guarded Windows bootloader from the pinned PyInstaller source archive."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks


VERSION = '6.18.0'
SOURCE_SHA256 = 'cdc507542783511cad4856fce582fdc37e9f29665ca596889c663c83ec8c6ec9'
MAIN_SHA256 = '261f79aeb9dc82d8c4a7386727628e00181570fc029b407e7fc3849ae32d053f'


def buildLauncher(output: Path) -> dict:
  source = Path(__file__).resolve().parent / 'native/core-upgrade-launcher.c'
  vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
  setup = subprocess.check_output([
    str(vswhere), '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
    '-find', r'VC\Auxiliary\Build\vcvars64.bat', '-utf8',
  ], encoding='utf-8').strip()
  if not setup or not Path(setup).is_file():
    raise BuildConfigError('The x64 MSVC developer environment is unavailable')
  script = output / 'build-upgrade-launcher.cmd'
  script.write_text(
    '@echo off\n'
    f'call "{setup}"\n'
    'if errorlevel 1 exit /b %errorlevel%\n'
    f'cl.exe /nologo /std:c17 /O2 /W4 /WX /MT /DUNICODE /D_UNICODE "{source}" '
    '/Fe:VisionWorkshopLauncher.exe /link /SUBSYSTEM:WINDOWS /Brepro shell32.lib bcrypt.lib\n'
    'exit /b %errorlevel%\n', encoding='utf-8')
  log = output / 'upgrade-launcher-build.log'
  with log.open('xb') as stream:
    subprocess.run(['cmd.exe', '/d', '/c', script.name], cwd=output, stdout=stream,
                   stderr=subprocess.STDOUT, check=True, timeout=180)
  launcher = output / 'VisionWorkshopLauncher.exe'
  return {'upgrade_launcher': str(launcher), 'upgrade_launcher_sha256': fileHash(launcher),
          'upgrade_launcher_source_sha256': fileHash(source), 'upgrade_launcher_log_sha256': fileHash(log)}


def build(sourceArchive: Path, output: Path) -> dict:
  if sys.platform != 'win32' or sys.version_info[:3] != (3, 12, 10):
    raise BuildConfigError('Build the guarded bootloader with Windows CPython 3.12.10')
  rejectLinks(sourceArchive)
  rejectLinks(output)
  if fileHash(sourceArchive) != SOURCE_SHA256:
    raise BuildConfigError('PyInstaller source archive does not match the reviewed SHA-256')
  output.mkdir()
  with tarfile.open(sourceArchive, mode='r:gz') as archive:
    archive.extractall(output, filter='data')
  if fileHash(sourceArchive) != SOURCE_SHA256:
    raise BuildConfigError('PyInstaller source archive changed during extraction')
  source = output / ('pyinstaller-' + VERSION)
  bootloader = source / 'bootloader'
  main = bootloader / 'src/main.c'
  if fileHash(main) != MAIN_SHA256:
    raise BuildConfigError('Pinned PyInstaller Windows entrypoint differs')
  body = main.read_bytes()
  include = b'#if defined(WINDOWED)\n\n/* Entry point'
  entry = b'    return pyi_main(global_pyi_ctx);\n}\n\n#else /* defined(WINDOWED) */'
  if body.count(include) != 1 or body.count(entry) != 1:
    raise BuildConfigError('Cannot identify the exact Windows windowed entrypoint')
  body = body.replace(include, b'#if defined(WINDOWED)\n\n#include "core-admission.h"\n\n/* Entry point')
  body = body.replace(entry, entry.replace(b'pyi_main(', b'core_admitted_main('))
  header = Path(__file__).resolve().parent / 'native/core-admission.h'
  shutil.copyfile(header, bootloader / 'src/core-admission.h')
  main.write_bytes(body)
  command = [sys.executable, 'waf', 'all', '--target-arch=64bit']
  log = output / 'waf-build.log'
  with log.open('xb') as stream:
    subprocess.run(command, cwd=bootloader, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
  compiled = bootloader / 'build/releasew/runw.exe'
  installed = source / 'PyInstaller/bootloader/Windows-64bit-intel/runw.exe'
  if fileHash(compiled) != fileHash(installed):
    raise BuildConfigError('Installed guarded bootloader differs from the compiled Windows PE')
  binary = output / 'runw.exe'
  shutil.copyfile(installed, binary)
  receipt = {'pyinstaller': VERSION, 'upstream_archive_sha256': SOURCE_SHA256,
             'upstream_main_sha256': MAIN_SHA256, 'patched_main_sha256': fileHash(main),
             'guard_source_sha256': fileHash(header), 'waf_build_log_sha256': fileHash(log),
             'bootloader_sha256': fileHash(binary), 'bootloader': str(binary)}
  receipt.update(buildLauncher(output))
  (output / 'bootloader-build.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
  return receipt


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source-archive', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  print(json.dumps(build(args.source_archive.absolute(), args.output.absolute())), flush=True)


if __name__ == '__main__':
  main()
