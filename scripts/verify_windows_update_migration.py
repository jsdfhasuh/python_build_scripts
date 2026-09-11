"""Compile tiny Windows apps with real updater code; never contact a release channel."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build
from build_records import fileHash
from build_records import gitCommit
from build_records import readJsonObject
from build_records import rejectLinks
from console_utils import configureConsole
from verify_windows_portable import run
from verify_windows_portable import verifyIcon


def waitForLaunch(appDir: Path, expectedName: str) -> dict:
  marker = appDir / 'launched.json'
  deadline = time.monotonic() + 30
  while time.monotonic() < deadline:
    if marker.exists():
      try:
        data = readJsonObject(marker)
      except ValueError:
        time.sleep(0.1)
        continue
      if data['name'] != expectedName or data['display_name'] != 'VisionWorkshop':
        raise RuntimeError(f'Unexpected restarted application: {data}')
      return data
    time.sleep(0.1)
  raise RuntimeError(f'Updater did not restart the application: {appDir}')


def runUpdate(
  executable: Path, caseRoot: Path, package: Path, oldName: str, newName: str,
  *, expectFailure: bool = False,
) -> dict:
  app = caseRoot / 'installed app'
  app.mkdir(parents=True)
  (app / oldName).write_bytes(b'old application sentinel')
  appData = caseRoot / 'userdata'
  preferences = appData / 'training_platform/preferences.json'
  preferences.parent.mkdir(parents=True)
  preferences.write_text('{"keep": true}', encoding='utf-8')
  environment = {**os.environ, 'APPDATA': str(appData), 'PYTHONIOENCODING': 'utf-8'}
  result = subprocess.run([
    str(executable), '--pid', '0', '--app-dir', str(app), '--zip', str(package),
    '--exe', oldName,
  ], cwd=caseRoot, env=environment, capture_output=True, text=True, encoding='utf-8',
     errors='replace', timeout=90, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
  if expectFailure:
    if result.returncode == 0 or (app / oldName).read_bytes() != b'old application sentinel':
      raise RuntimeError('Invalid update changed the existing installation')
    if list(caseRoot.glob('installed app.backup_*')):
      raise RuntimeError('Invalid update unexpectedly replaced the application directory')
    return {'case': caseRoot.name, 'invalid_payload_keeps_old_install': 'passed'}
  if result.returncode:
    raise RuntimeError(f'Updater failed: {result.stdout}\n{result.stderr}')
  launch = waitForLaunch(app, newName)
  backups = list(caseRoot.glob('installed app.backup_*'))
  if len(backups) != 1 or (backups[0] / oldName).read_bytes() != b'old application sentinel':
    raise RuntimeError('Update did not preserve the previous installation backup')
  if preferences.read_text(encoding='utf-8') != '{"keep": true}':
    raise RuntimeError('Update modified persistent user data')
  return {'case': caseRoot.name, 'from': oldName, 'restarted': launch['name'],
          'backup': 'passed', 'user_data_preserved': 'passed'}


def main() -> int:
  configureConsole()
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source-root', type=Path, required=True)
  parser.add_argument('--legacy-source-ref', required=True,
                      help='An explicit source commit/ref containing the old updater')
  args = parser.parse_args()
  if os.name != 'nt':
    parser.error('This acceptance test requires Windows')
  sourceRoot = args.source_root.resolve()
  rejectLinks(sourceRoot)
  if args.legacy_source_ref.startswith('-'):
    parser.error('Invalid legacy source ref')
  legacyCommit = run(['git', '-C', str(sourceRoot), 'rev-parse', '--verify',
                      f'{args.legacy_source_ref}^{{commit}}']).strip()
  legacyCode = subprocess.check_output(
    ['git', '-C', str(sourceRoot), 'show', f'{legacyCommit}:updater.py'],
  )
  evidence = {
    'schema_version': 1, 'date_utc': datetime.now(timezone.utc).isoformat(),
    'legacy_source_commit': legacyCommit,
    'legacy_updater_sha256': hashlib.sha256(legacyCode).hexdigest(),
    'new_updater_sha256': fileHash(sourceRoot / 'updater.py'),
    'packager_commit': gitCommit(ROOT), 'product_gui_test': False,
    'production_update_contacted': False, 'cases': [],
  }
  with tempfile.TemporaryDirectory(prefix='visionworkshop-migration-') as directory:
    root = Path(directory).resolve()
    source = root / 'source'
    source.mkdir()
    (source / '.gitignore').write_text('__pycache__/\n', encoding='utf-8')
    (source / 'main.py').write_text(
      'import json, sys\nfrom pathlib import Path\n'
      'branding = json.loads((Path(sys._MEIPASS) / "branding.json").read_text())\n'
      'data = {"name": Path(sys.executable).name, "display_name": branding["display_name"]}\n'
      'Path(sys.executable).with_name("launched.json").write_text(json.dumps(data))\n',
      encoding='utf-8',
    )
    shutil.copy2(sourceRoot / 'updater.py', source / 'updater.py')
    for arguments in (['init'], ['config', 'user.name', 'Migration Acceptance'],
                      ['config', 'user.email', 'tests@example.invalid'],
                      ['add', '.'], ['commit', '-m', 'fixture']):
      run(['git', '-C', str(source), *arguments])
    config = root / 'emo-vision-train.json'
    config.write_text(json.dumps({
      'name': 'emo-vision-train', 'entry': str(source / 'main.py'), 'onefile': False,
      'console': False, 'collect_conda_runtime_dlls': False,
      'release_asset_name': 'fixture.zip',
      'updater': {'enabled': True, 'entry': str(source / 'updater.py'),
                  'name': 'updater', 'onefile': True, 'console': True},
    }), encoding='utf-8')
    output = root / 'output'
    print('Building tiny application, branded updater and legacy launchers...', flush=True)
    run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/publish_visionworkshop.py'),
         '--config', str(config), '--source-root', str(source), '--release-tag', 'v0.0.0-migration',
         '--branding-profile', str(ROOT / 'profiles/visionworkshop.json'),
         '--build-only', '--output-directory', str(output)], cwd=ROOT)
    summary = readJsonObject(output / 'build-summary.json')
    package = output / summary['asset_name']
    unpacked = root / 'unpacked'
    with zipfile.ZipFile(package) as archive:
      archive.extractall(unpacked)
    app = unpacked / 'VisionWorkshop'
    icon = ROOT / 'assets/icons/visionworkshop.ico'
    for name in ('VisionWorkshop.exe', 'VisionWorkshopUpdater.exe', 'emo-vision-train.exe'):
      verifyIcon(app / name, icon)
    if fileHash(app / 'updater.exe') != fileHash(app / 'VisionWorkshopUpdater.exe'):
      raise RuntimeError('Legacy updater alias differs from branded updater')
    if fileHash(app / 'emo-vision-train.exe') != fileHash(app / 'training_platform.exe'):
      raise RuntimeError('Legacy launchers differ')
    namedUpdater = app / 'VisionWorkshopUpdater.exe'
    if 'VisionWorkshop updater' not in run([str(namedUpdater), '--help']):
      raise RuntimeError('Branded updater did not load its embedded display name')
    evidence['exe_icon_resources'] = 'passed'
    evidence['updater_embedded_branding'] = 'passed'
    evidence['zip_sha256'] = fileHash(package)

    legacyPath = root / 'legacy_updater.py'
    legacyPath.write_bytes(legacyCode)
    job = build.BuildJob(label='legacy-updater-test', entry=str(legacyPath),
                         name='legacy-updater-test', onefile=True, console=True,
                         collect_conda_runtime_dlls=False, enable_torch_runtime=False)
    print('Compiling the explicitly selected old updater code...', flush=True)
    run(build.build_pyinstaller_command(
      job, True, str(root / 'legacy-spec'), str(root / 'legacy-dist'), str(root / 'legacy-work'),
    ), cwd=ROOT)
    oldUpdater = root / 'legacy-dist/legacy-updater-test.exe'
    for oldName in ('emo-vision-train.exe', 'training_platform.exe'):
      print(f'Testing old updater: {oldName} -> VisionWorkshop.exe', flush=True)
      evidence['cases'].append(runUpdate(oldUpdater, root / f'old-{oldName}', package,
                                          oldName, 'VisionWorkshop.exe'))
    print('Testing branded updater: VisionWorkshop.exe -> VisionWorkshop.exe', flush=True)
    evidence['cases'].append(runUpdate(namedUpdater, root / 'new-to-new', package,
                                      'VisionWorkshop.exe', 'VisionWorkshop.exe'))

    originalPackage = root / 'original-name.zip'
    with zipfile.ZipFile(originalPackage, 'w', zipfile.ZIP_DEFLATED) as archive:
      for path in (app / '_internal').rglob('*'):
        if path.is_file():
          archive.write(path, f'emo-vision-train/{path.relative_to(app).as_posix()}')
      archive.write(app / 'VisionWorkshop.exe', 'emo-vision-train/emo-vision-train.exe')
      archive.write(namedUpdater, 'emo-vision-train/updater.exe')
    print('Testing branded updater with an original-name package...', flush=True)
    evidence['cases'].append(runUpdate(namedUpdater, root / 'new-to-original', originalPackage,
                                      'VisionWorkshop.exe', 'emo-vision-train.exe'))
    badPackage = root / 'invalid.zip'
    with zipfile.ZipFile(badPackage, 'w') as archive:
      archive.writestr('VisionWorkshop/readme.txt', 'no executable')
    evidence['cases'].append(runUpdate(namedUpdater, root / 'invalid-payload', badPackage,
                                      'VisionWorkshop.exe', '', expectFailure=True))
  artifact = ROOT / 'artifacts/windows-update-migration.json'
  artifact.parent.mkdir(exist_ok=True)
  artifact.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
  print(f'Windows update migration acceptance passed: {artifact}')
  print('No product GUI, production download, or release upload was performed.')
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
