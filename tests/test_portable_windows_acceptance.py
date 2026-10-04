"""Publisher reporting tests with fabricated reports, never real Windows acceptance."""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import portable_release
from build_config import BuildConfigError
from build_records import fileHash
from build_records import objectHash
from build_records import scanFiles
from release_content import ReleaseContent
from update_protocol_build import ASSET_PREFIX


class WindowsAcceptanceSummaryTests(unittest.TestCase):
  def setUp(self) -> None:
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.context = SimpleNamespace(workRoot=self.root / 'work', distRoot=self.root / 'dist',
                                   buildId='fixture')
    app = self.context.distRoot / 'VisionWorkshop'
    app.mkdir(parents=True)
    (app / 'VisionWorkshop.exe').write_bytes(b'fixture only; not a Windows executable')
    self.source = {'commit': 'a' * 40, 'dirty': False, 'submodules_ready': True}
    self.protocol = {'protocol_version': 3, 'build_id': 'fixture', 'files_sha256': 'b' * 64}
    files = scanFiles(app)
    self.record = {'inputs': {'source': self.source, 'packager': {'commit': 'c' * 40}},
                   'files': files, 'files_sha256': objectHash(files),
                   'update_protocol': self.protocol}
    self.resolved = SimpleNamespace(
      target='emo-vision-train', programName='VisionWorkshop', packagerRoot=self.root,
      config={'update_protocol': 3, 'release_repo': 'tests/releases'}, iconSha256='d' * 64,
      updateCompatibility='protocol-3', legacyProgramNames=[],
      summary=lambda: {'window_branding': 'requires app support'},
    )
    self.advisory = {'status': 'not-run', 'checks': {'power_loss_recovery': 'not-run'}}
    self.stack = contextlib.ExitStack()
    self.addCleanup(self.stack.close)
    self.log = io.StringIO()
    self.stack.enter_context(contextlib.redirect_stdout(self.log))
    self.stack.enter_context(patch.dict(os.environ, {
      'RUNNER_TEMP': str(self.root), 'VISIONWORKSHOP_REQUIRE_WINDOWS_ACCEPTANCE': '1',
    }))
    replacements = {
      'resolveRequest': (self.resolved, self.root / 'source', 'fixture.zip', self.source),
      'createBuildContext': self.context,
      'executeBuild': self.record,
      'verifyRecord': (self.context, self.record),
      'prepareContent': ReleaseContent('Fixture release', 'Fixture notes', self.source['commit']),
      'gitCommit': 'c' * 40,
      'requireNewRelease': None,
      'verifyAcceptance': self.advisory,
      'runDeltaProducer': {'verified_target_sha256': self.protocol['files_sha256']},
      'validateDeltaAssets': [],
    }
    for name, value in replacements.items():
      self.stack.enter_context(patch('portable_release.' + name, return_value=value))
    self.stack.enter_context(patch('portable_release.shutil.which', return_value=None))
    self.stack.enter_context(patch('portable_release.runProducer', side_effect=self.export))
    self.publish = self.stack.enter_context(patch('portable_release.publishAssets'))
    self.harness = self.stack.enter_context(patch('portable_release.subprocess.run',
                                                 side_effect=self.writeReport))
    self.reportOverrides = {}
    self.runCount = 0

  def export(self, *args) -> None:
    for suffix in ('release_identity.json', 'package_files.json'):
      (self.output / f'{ASSET_PREFIX}-{suffix}').write_text('{}', encoding='utf-8')

  def writeReport(self, command, **kwargs) -> subprocess.CompletedProcess:
    report = {
      'status': 'passed', 'source_commit': self.source['commit'],
      'baseline_tag': 'v1.2.2', 'target_tag': 'v1.2.3',
      'target_full_sha256': fileHash(next(self.output.glob('*.zip'))),
      'target_manifest_sha256': self.protocol['files_sha256'],
      'transition': {'state': 'passed', 'target_gui_ready': True,
                     'target_launch_confirmed': True, 'GPU_training': 'not-run',
                     'interactive_ui_quiescence': 'not-run', 'unchanged_files_preserved': 7,
                     'unchanged_copy_bytes': 0, 'prepared_bytes': 42},
      'interrupted_recovery': {'state': 'passed'},
      'power_loss': 'not-run', 'successive_upgrade': 'not-run',
      **self.reportOverrides,
    }
    self.reportPath = Path(command[command.index('--work') + 1]) / 'acceptance.json'
    self.reportPath.parent.mkdir(exist_ok=True)
    self.reportPath.write_text(json.dumps(report), encoding='utf-8')
    return subprocess.CompletedProcess(command, 0)

  def release(self, *, publish=True, frozen=True) -> dict:
    self.runCount += 1
    self.output = self.root / f'output-{self.runCount}'
    arguments = ['--release-tag', 'v1.2.3']
    if publish:
      arguments.append('--publish')
    if frozen:
      arguments.extend(['--delta-base-tag', 'v1.2.2', '--delta-base-lock', 'fixture-lock.json',
                        '--delta-base-lock-sha256', 'e' * 64])
    with patch('portable_release.chooseOutput', return_value=self.output):
      return portable_release.runRelease(portable_release.makeParser().parse_args(arguments))

  def savedSummary(self) -> dict:
    return json.loads((self.output / 'build-summary.json').read_text(encoding='utf-8'))

  def test_passed_transition_is_persisted_separately_with_exact_report_hash(self) -> None:
    summary = self.release()
    self.assertTrue(summary['published'])
    self.assertEqual(self.savedSummary(), summary)
    self.assertEqual(summary['windows_launch_test'], 'passed')
    acceptance = summary['windows_transition_acceptance']
    self.assertEqual(acceptance['status'], 'passed')
    self.assertEqual(acceptance['report_sha256'], fileHash(self.reportPath))
    self.assertEqual(acceptance['target_full_sha256'], summary['asset_sha256'])
    self.assertEqual(acceptance['target_manifest_sha256'], self.protocol['files_sha256'])
    self.assertEqual(acceptance['transition']['GPU_training'], 'not-run')
    self.assertEqual(acceptance['transition']['unchanged_files_preserved'], 7)
    self.assertEqual(acceptance['transition']['unchanged_copy_bytes'], 0)
    self.assertEqual(acceptance['transition']['prepared_bytes'], 42)
    self.assertEqual(acceptance['power_loss'], 'not-run')
    self.assertEqual(summary['update_acceptance'], self.advisory)
    self.assertIn('Windows application launch, release transition and interrupted recovery passed',
                  self.log.getvalue())
    self.assertNotIn('Windows application launch not verified here', self.log.getvalue())
    self.harness.assert_called_once()
    self.publish.assert_called_once()

  def test_public_summary_excludes_unknown_and_nested_private_report_fields(self) -> None:
    private = 'private-token-or-path-must-not-be-published'
    self.reportOverrides = {
      'token': private, 'error': private, 'private_path': private,
      'transition': {'state': 'passed', 'target_gui_ready': True,
                     'target_launch_confirmed': True, 'session_id': private,
                     'configuration_files_preserved': [private], 'prepared_bytes': private,
                     'target_startup_stages': [private], 'unknown': {'token': private}},
      'interrupted_recovery': {'state': 'passed', 'session_id': private, 'fault': private},
    }
    summary = self.release()
    self.assertNotIn(private, json.dumps(summary))
    self.assertNotIn(private, json.dumps(self.savedSummary()))
    self.assertNotIn('prepared_bytes', summary['windows_transition_acceptance']['transition'])
    self.assertIn(private, self.reportPath.read_text(encoding='utf-8'))
    self.assertEqual(summary['windows_transition_acceptance']['report_sha256'],
                     fileHash(self.reportPath))

  def test_failed_or_mismatched_reports_never_publish(self) -> None:
    cases = {
      'status': 'failed', 'source_commit': 'f' * 40, 'target_tag': 'v1.2.4',
      'target_full_sha256': 'f' * 64, 'target_manifest_sha256': 'f' * 64,
      'transition': {'state': 'failed'}, 'interrupted_recovery': {'state': 'not-run'},
    }
    for key, value in cases.items():
      with self.subTest(field=key):
        self.reportOverrides = {key: value}
        with self.assertRaisesRegex(BuildConfigError, 'failed or build binding changed'):
          self.release()
        self.assertFalse((self.output / 'build-summary.json').exists())
    self.publish.assert_not_called()

  def test_launch_pass_requires_explicit_gui_and_launch_confirmation(self) -> None:
    for key in ('target_gui_ready', 'target_launch_confirmed'):
      with self.subTest(field=key):
        self.reportOverrides = {'transition': {
          'state': 'passed', 'target_gui_ready': True, 'target_launch_confirmed': True, key: False,
        }}
        with self.assertRaisesRegex(BuildConfigError, 'failed or build binding changed'):
          self.release()
    self.publish.assert_not_called()

  def test_upload_failure_keeps_passed_acceptance_but_unpublished_summary(self) -> None:
    self.publish.side_effect = BuildConfigError('upload failed')
    with self.assertRaisesRegex(BuildConfigError, 'upload failed'):
      self.release()
    summary = self.savedSummary()
    self.assertFalse(summary['published'])
    self.assertEqual(summary['windows_transition_acceptance']['status'], 'passed')

  def test_concurrent_summary_change_is_still_detected_after_acceptance(self) -> None:
    def change(*args, **kwargs):
      path = self.output / 'build-summary.json'
      path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    self.publish.side_effect = change
    with self.assertRaisesRegex(BuildConfigError, 'summary was concurrently changed'):
      self.release()
    self.assertFalse(self.savedSummary()['published'])
    self.assertEqual(self.savedSummary()['windows_transition_acceptance']['status'], 'passed')

  def test_full_only_publication_without_opt_in_does_not_run_windows_gate(self) -> None:
    for setting in ('', '0', 'true'):
      with self.subTest(setting=setting), patch.dict(os.environ, {
        'VISIONWORKSHOP_REQUIRE_WINDOWS_ACCEPTANCE': setting,
      }):
        summary = self.release(frozen=False)
        self.assertTrue(summary['published'])
        self.assertEqual(summary['windows_transition_acceptance']['status'], 'not-run')
        self.assertEqual(summary['windows_launch_test'], 'not-run')
        self.assertEqual(summary['update_acceptance'], self.advisory)
    self.harness.assert_not_called()

  def test_local_build_does_not_run_opted_in_publication_gate(self) -> None:
    summary = self.release(publish=False, frozen=False)
    self.assertFalse(summary['published'])
    self.assertEqual(summary['windows_transition_acceptance']['status'], 'not-run')
    self.harness.assert_not_called()
    self.publish.assert_not_called()

  def test_opted_in_full_only_publication_requires_frozen_baseline(self) -> None:
    with self.assertRaisesRegex(BuildConfigError, 'requires a frozen protocol-3 baseline'):
      self.release(frozen=False)
    self.harness.assert_not_called()
    self.publish.assert_not_called()


if __name__ == '__main__':
  unittest.main()
