"""Real Windows fixture acceptance. Never builds the product or accesses update channels."""

import hashlib
import importlib.metadata
import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from datetime import timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from branding_fixtures import makeIco
from build_records import readJsonObject
from build_records import gitCommit
from portable_release import verifyArchive


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 600) -> str:
  result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', check=False, timeout=timeout)
  if result.returncode:
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    raise RuntimeError(f'Command failed with exit code {result.returncode}: {command[0]}')
  return result.stdout


def verifyIcon(executable: Path, icon: Path) -> None:
  import pefile
  data = icon.read_bytes()
  count = struct.unpack_from('<H', data, 4)[0]
  expected = set()
  for index in range(count):
    length, offset = struct.unpack_from('<II', data, 6 + 16 * index + 8)
    expected.add(hashlib.sha256(data[offset:offset + length]).hexdigest())
  found = set()
  with pefile.PE(str(executable)) as image:
    for kind in image.DIRECTORY_ENTRY_RESOURCE.entries:
      if kind.id != 3:
        continue
      for entry in kind.directory.entries:
        for language in entry.directory.entries:
          resource = language.data.struct
          payload = image.get_data(resource.OffsetToData, resource.Size)
          found.add(hashlib.sha256(payload).hexdigest())
  if not expected.issubset(found):
    raise RuntimeError('EXE icon resources do not match the supplied ICO image data')


def main() -> int:
  if os.name != 'nt':
    print('This acceptance runner requires Windows; no Windows result was produced.')
    return 2
  evidence = {'schema_version': 1, 'platform': sys.platform, 'python': sys.version,
              'date_utc': datetime.now(timezone.utc).isoformat(),
              'packager_commit': gitCommit(ROOT),
              'pyinstaller': importlib.metadata.version('pyinstaller'),
              'pillow': importlib.metadata.version('pillow'),
              'product_test': False, 'production_update_contacted': False, 'cases': []}
  with tempfile.TemporaryDirectory(prefix='visionworkshop-acceptance-') as directory:
    root = Path(directory)
    source = root / 'source'
    source.mkdir()
    (source / '.gitignore').write_text('__pycache__/\n', encoding='utf-8')
    (source / 'main.py').write_text(
      'import json, sys\nfrom pathlib import Path\n'
      'print(json.dumps({"name": Path(sys.executable).name, '
      '"frozen": bool(getattr(sys, "frozen", False)), '
      '"data": Path(__file__).with_name("asset.txt").read_text()}))\n', encoding='utf-8',
    )
    (source / 'updater.py').write_text('print("fixture-updater-only")\n', encoding='utf-8')
    (source / 'asset.txt').write_text('resource-ok', encoding='utf-8')
    icon = source / 'fixture.ico'
    config = root / 'emo-vision-train.json'
    config.write_text(json.dumps({
      'name': 'emo-vision-train', 'entry': str(source / 'main.py'), 'onefile': False,
      'console': True, 'icon': None, 'collect_conda_runtime_dlls': False,
      'release_asset_name': '${PROGRAM_NAME}-windows-${RELEASE_TAG}.zip',
      'add_data': [f'{source / "asset.txt"}:.'],
      'updater': {'enabled': True, 'name': 'updater', 'entry': str(source / 'updater.py'),
                  'onefile': True, 'console': True},
    }), encoding='utf-8')
    for args in (['init'], ['config', 'user.name', 'Windows Acceptance'],
                 ['config', 'user.email', 'tests@example.invalid']):
      run(['git', '-C', str(source), *args])
    cases = [('VisionWorkshop', False, 16), ('视觉 工坊', True, 32),
             ('VisionWorkshop', True, 16), ('emo-vision-train', None, 16)]
    for index, (name, png, size) in enumerate(cases):
      icon.write_bytes(makeIco(size=size, png=bool(png)))
      run(['git', '-C', str(source), 'add', '.'])
      run(['git', '-C', str(source), 'commit', '--allow-empty', '-m', f'fixture {index}'])
      before = set((ROOT / 'build/branding').rglob('build-record.json'))
      output = root / f'output-{index}'
      arguments = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/publish_visionworkshop.py'),
                   '--config', str(config), '--source-root', str(source),
                   '--release-tag', f'v0.0.{index}', '--build-only',
                   '--output-directory', str(output)]
      if png is not None:
        arguments += ['--program-name', name, '--icon-path', str(icon)]
      print(f'Building fixture {index}: {name}', flush=True)
      run(arguments, cwd=ROOT)
      created = set((ROOT / 'build/branding').rglob('build-record.json')) - before
      if len(created) != 1:
        raise RuntimeError('Expected exactly one new build record')
      recordPath = created.pop()
      record = readJsonObject(recordPath)
      summary = readJsonObject(output / 'build-summary.json')
      archive = output / summary['asset_name']
      verifyArchive(archive, name, record['files'])
      extraction = root / f'unpacked-{index}'
      with zipfile.ZipFile(archive) as content:
        content.extractall(extraction)
      executable = extraction / name / f'{name}.exe'
      result = json.loads(run([str(executable)], timeout=30))
      if result != {'name': f'{name}.exe', 'frozen': True, 'data': 'resource-ok'}:
        raise RuntimeError(f'Unexpected frozen fixture result: {result}')
      if run([str(extraction / name / 'updater.exe')], timeout=30).strip() != 'fixture-updater-only':
        raise RuntimeError('The updater fixture did not launch')
      if png is not None:
        verifyIcon(executable, icon)
      reuseArguments = arguments.copy()
      reuseArguments[reuseArguments.index('--output-directory') + 1] = str(root / f'reused-{index}')
      reuseArguments += ['--skip-build', '--build-record-path', str(recordPath)]
      run(reuseArguments, cwd=ROOT)
      if (set((ROOT / 'build/branding').rglob('build-record.json')) - before) != {recordPath}:
        raise RuntimeError('SkipBuild unexpectedly created another build record')
      evidence['cases'].append({
        'name': name, 'source_commit': record['inputs']['source']['commit'],
        'zip_hash': summary['asset_sha256'], 'unpack_and_launch': 'passed',
        'updater_fixture_launch': 'passed', 'record_reuse': 'passed',
        'pe_icon_match': 'passed' if png is not None else 'default-not-customized',
      })
  artifact = ROOT / 'artifacts/windows-portable-acceptance.json'
  artifact.parent.mkdir(exist_ok=True)
  artifact.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
  print(f'Fixture acceptance passed. Evidence: {artifact}')
  print('This does not certify VisionWorkshop GUI startup, drivers, or cross-name updates.')
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
