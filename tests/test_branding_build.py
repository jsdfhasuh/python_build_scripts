import contextlib
import functools
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import branding_build
import build
from branding_fixtures import makeIco
from branding_fixtures import writeProject
from build_config import createBuildContext
from build_config import resolveBuildConfig


ROOT = Path(__file__).resolve().parents[1]


class CommandIntegrationTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.config, self.icon, self.profile = writeProject(self.root)
    self.stack = contextlib.ExitStack()
    self.addCleanup(self.stack.close)
    self.output = io.StringIO()
    self.stack.enter_context(contextlib.redirect_stdout(self.output))
    self.stack.enter_context(contextlib.redirect_stderr(self.output))
    self.stack.enter_context(patch('build._find_python_dll', return_value=None))
    self.stack.enter_context(patch('build._collect_python_runtime_dlls', return_value=[]))
    self.stack.enter_context(patch('branding_build.resolveBuildConfig', side_effect=
      functools.partial(resolveBuildConfig, packagerRoot=self.root)))

  def runBuild(self, **kwargs) -> int:
    return branding_build.runBrandedBuild(self.config, profilePath=str(self.profile), **kwargs)

  def fakeCompiler(self, command: list[str]) -> int:
    dist = Path(command[command.index('--distpath') + 1])
    name = command[command.index('--name') + 1]
    output = dist / f'{name}.exe' if '--onefile' in command else dist / name / f'{name}.exe'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b'FAKE-EXE-FOR-UNIT-TESTS')
    return 0

  def test_context_routes_jobs_to_isolated_directories(self) -> None:
    resolved = resolveBuildConfig(self.config, programName='VisionWorkshop', packagerRoot=self.root)
    context = createBuildContext(resolved)
    commands = build.build_job_commands(resolved.config, True, context=context)
    for job, command in commands:
      self.assertEqual(command[command.index('--distpath') + 1], str(context.distRoot))
      self.assertEqual(command[command.index('--specpath') + 1], str(context.specPath(job.label)))
      self.assertEqual(command[command.index('--workpath') + 1], str(context.workPath(job.label)))
      self.assertEqual(command[-1], job.entry)
    self.assertEqual(commands[0][0].name, 'VisionWorkshop')
    self.assertEqual(commands[1][0].name, 'updater')

  def test_dry_run_does_not_create_outputs_or_run_commands(self) -> None:
    before = set(self.root.iterdir())
    with patch('build.run_command') as execute, patch('build.copy_updater_to_app_dir') as copy:
      self.assertEqual(self.runBuild(dryRun=True), 0)
      execute.assert_not_called()
      copy.assert_not_called()
    self.assertEqual(set(self.root.iterdir()), before)
    self.assertIn('VisionWorkshop', self.output.getvalue())

  def test_invalid_name_fails_before_build(self) -> None:
    with patch('build.run_command') as execute:
      self.assertEqual(self.runBuild(programName='updater', dryRun=True), 1)
      execute.assert_not_called()
    self.assertFalse((self.root / 'build').exists())

  def test_specpath_override_is_rejected(self) -> None:
    self.assertEqual(self.runBuild(specpath='elsewhere', dryRun=True), 1)
    self.assertIn('isolated', self.output.getvalue())
    self.assertFalse((self.root / 'build').exists())

  def test_non_windows_actual_build_is_explicitly_rejected(self) -> None:
    with patch('branding_build.sys.platform', 'linux'), patch('build.run_command') as execute:
      self.assertEqual(self.runBuild(), 1)
      execute.assert_not_called()
    self.assertFalse((self.root / 'build').exists())
    self.assertIn('require Windows', self.output.getvalue())

  def test_fake_success_routes_updater_and_writes_non_reusable_receipt(self) -> None:
    with patch('branding_build.sys.platform', 'win32'), \
         patch('build.run_command', side_effect=self.fakeCompiler):
      self.assertEqual(self.runBuild(), 0)
    receipts = list(self.root.rglob('build-result.json'))
    self.assertEqual(len(receipts), 1)
    receipt = json.loads(receipts[0].read_text(encoding='utf-8'))
    app = Path(receipt['dist_directory'])
    self.assertEqual((app / 'updater.exe').read_bytes(), b'FAKE-EXE-FOR-UNIT-TESTS')
    self.assertTrue((app / 'VisionWorkshop.exe').exists())
    self.assertFalse(receipt['archive_created'])
    self.assertFalse(receipt['release_uploaded'])
    self.assertFalse(receipt['reusable_build_record'])
    self.assertEqual(receipt['windows_launch_test'], 'not-run')

  def test_failed_compiler_writes_no_success_receipt(self) -> None:
    with patch('branding_build.sys.platform', 'win32'), \
         patch('build.run_command', return_value=7) as execute:
      self.assertEqual(self.runBuild(), 7)
      self.assertEqual(execute.call_count, 1)
    self.assertFalse(list(self.root.rglob('build-result.json')))

  def test_missing_outputs_do_not_fall_back_to_default_dist(self) -> None:
    old = self.root / 'dist' / 'emo-vision-train'
    old.mkdir(parents=True)
    (old / 'emo-vision-train.exe').write_bytes(b'old')
    with patch('branding_build.sys.platform', 'win32'), patch('build.run_command', return_value=0):
      self.assertEqual(self.runBuild(), 1)
    self.assertEqual((old / 'emo-vision-train.exe').read_bytes(), b'old')
    self.assertFalse(list(self.root.rglob('build-result.json')))

  def test_icon_changed_during_build_invalidates_success(self) -> None:
    def changeIcon(command: list[str]) -> int:
      self.icon.write_bytes(makeIco(png=True))
      return self.fakeCompiler(command)
    with patch('branding_build.sys.platform', 'win32'), \
         patch('build.run_command', side_effect=changeIcon):
      self.assertEqual(self.runBuild(), 1)
    self.assertIn('Icon changed', self.output.getvalue())
    self.assertFalse(list(self.root.rglob('build-result.json')))

  def test_existing_config_is_not_written_by_build(self) -> None:
    data = self.config.read_bytes()
    with patch('branding_build.sys.platform', 'win32'), \
         patch('build.run_command', side_effect=self.fakeCompiler):
      self.assertEqual(self.runBuild(), 0)
    self.assertEqual(self.config.read_bytes(), data)


class CliTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.config, self.icon, self.profile = writeProject(self.root)

  def invoke(self, script: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
      [sys.executable, '-X', 'utf8', str(ROOT / script), '--config', str(self.config),
       *arguments], cwd=self.root, text=True, encoding='utf-8', capture_output=True,
      timeout=20, check=False,
    )

  def test_build_cli_prints_profile_commands_from_another_cwd(self) -> None:
    result = self.invoke('build.py', '--branding-profile', str(self.profile), '--dry-run')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('VisionWorkshop', result.stdout)
    self.assertIn('--icon', result.stdout)
    self.assertIn('--workpath', result.stdout)
    self.assertNotIn('Traceback', result.stderr)

  def test_build_cli_reports_bad_icon_without_traceback(self) -> None:
    result = self.invoke('build.py', '--icon-path', str(self.root / 'missing.ico'), '--dry-run')
    self.assertEqual(result.returncode, 1)
    self.assertIn('existing .ico', result.stderr)
    self.assertNotIn('Traceback', result.stderr)

  def test_resolver_outputs_valid_json_and_exact_archive_name(self) -> None:
    result = self.invoke('scripts/resolve_build_config.py', '--branding-profile', str(self.profile),
                         '--release-tag', 'v1.2.3')
    self.assertEqual(result.returncode, 0, result.stderr)
    data = json.loads(result.stdout)
    self.assertEqual(data['config']['name'], 'VisionWorkshop')
    self.assertEqual(data['summary']['release_asset_name'], 'VisionWorkshop-windows-v1.2.3.zip')

  def test_resolver_publication_gate_reports_unverified_rename(self) -> None:
    result = self.invoke('scripts/resolve_build_config.py', '--program-name', 'VisionWorkshop',
                         '--check-publication')
    self.assertEqual(result.returncode, 1)
    self.assertIn('unverified', result.stderr)

  def test_resolver_never_overwrites_input_configuration(self) -> None:
    data = self.config.read_bytes()
    result = self.invoke('scripts/resolve_build_config.py', '--program-name', 'VisionWorkshop',
                         '--output', str(self.config))
    self.assertEqual(result.returncode, 1)
    self.assertEqual(self.config.read_bytes(), data)

  def test_resolver_writes_new_private_file_only_when_requested(self) -> None:
    output = self.root / 'resolved.json'
    result = self.invoke('scripts/resolve_build_config.py', '--program-name', 'VisionWorkshop',
                         '--output', str(output))
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['config']['name'],
                     'VisionWorkshop')


if __name__ == '__main__':
  unittest.main()
