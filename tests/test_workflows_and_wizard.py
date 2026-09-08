import contextlib
import functools
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branding_fixtures import writeProject
from build_config import BuildConfigError
from build_config import resolveBuildConfig

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_wizard', ROOT / 'scripts/visionworkshop_wizard.py')
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)


class WizardTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.source = self.root / 'source'
    self.config, self.icon, profile = writeProject(self.source)
    (self.root / 'configs').mkdir()
    (self.root / 'configs/emo-vision-train.json').write_bytes(self.config.read_bytes())
    (self.root / 'profiles').mkdir()
    (self.root / 'profiles/visionworkshop.json').write_bytes(profile.read_bytes())
    self.stack = contextlib.ExitStack()
    self.addCleanup(self.stack.close)
    self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    self.stack.enter_context(patch.object(wizard, 'ROOT', self.root))
    self.stack.enter_context(patch.object(wizard, 'resolveBuildConfig', side_effect=
      functools.partial(resolveBuildConfig, packagerRoot=self.root)))

  def collect(self, replies: list[str], *, yes: bool = False):
    with patch('builtins.input', side_effect=replies):
      return wizard.collectArguments(yes=yes)

  def test_default_is_local_build_without_profile(self) -> None:
    args = self.collect(['', '', str(self.source), 'v1.2.3', 'y'])
    self.assertIn('--build-only', args)
    self.assertNotIn('--publish', args)
    self.assertFalse(any(arg.startswith('--branding-profile') for arg in args))

  def test_profile_selection_is_explicit_and_not_persisted(self) -> None:
    before = sorted(str(p) for p in self.root.rglob('*'))
    args = self.collect(['1', '2', str(self.source), 'v1.2.3', '', '', 'y'])
    self.assertTrue(any(arg.startswith('--branding-profile=') for arg in args))
    self.assertEqual(sorted(str(p) for p in self.root.rglob('*')), before)

  def test_cancel_does_not_execute_or_write(self) -> None:
    with patch.object(wizard, 'releaseMain') as execute, \
         patch('builtins.input', side_effect=['1', '1', str(self.source), 'v1.2.3', 'n']):
      self.assertEqual(wizard.main([]), 0)
      execute.assert_not_called()

  def test_eof_cancels_instead_of_defaulting_to_build(self) -> None:
    with patch('builtins.input', side_effect=EOFError), self.assertRaises(BuildConfigError):
      wizard.collectArguments(yes=True)

  def test_yes_does_not_bypass_update_guard(self) -> None:
    with self.assertRaisesRegex(BuildConfigError, 'unverified'):
      self.collect(['3', '2', str(self.source), 'v1.2.3', '', ''], yes=True)

  def test_yes_only_skips_final_confirmation(self) -> None:
    args = self.collect(['1', '1', str(self.source), 'v1.2.3'], yes=True)
    self.assertIn('--build-only', args)

  def test_reuse_requires_explicit_record(self) -> None:
    with self.assertRaises(BuildConfigError):
      self.collect(['4', '1', str(self.source), 'v1.2.3', ''], yes=True)

  def test_preview_is_forwarded_and_not_publication(self) -> None:
    args = self.collect(['2', '1', str(self.source), 'v1.2.3', 'y'])
    self.assertIn('--dry-run', args)
    self.assertNotIn('--publish', args)

  def test_custom_name_icon_and_asset_template_reach_shared_entry(self) -> None:
    args = self.collect(['1', '3', str(self.source), 'v1.2.3', 'Vision Workshop',
                         str(self.icon), '${PROGRAM_NAME}-${RELEASE_TAG}.zip', 'y'])
    self.assertIn('--program-name=Vision Workshop', args)
    self.assertIn(f'--icon-path={self.icon}', args)
    self.assertIn('--release-asset-name=${PROGRAM_NAME}-${RELEASE_TAG}.zip', args)


class WorkflowTests(unittest.TestCase):
  def load(self, name: str):
    import yaml
    data = yaml.safe_load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))
    return data, data.get('on', data.get(True))

  def test_dispatch_and_reuse_share_input_names(self) -> None:
    _, triggers = self.load('visionworkshop-portable.yml')
    self.assertEqual(set(triggers['workflow_dispatch']['inputs']),
                     set(triggers['workflow_call']['inputs']))

  def test_both_modes_default_to_no_publication(self) -> None:
    _, triggers = self.load('visionworkshop-portable.yml')
    for key in ('workflow_dispatch', 'workflow_call'):
      self.assertIs(triggers[key]['inputs']['publish_release']['default'], False)
      self.assertIs(triggers[key]['inputs']['source_ref']['required'], True)

  def test_reuse_requires_explicit_packager_ref(self) -> None:
    _, triggers = self.load('visionworkshop-portable.yml')
    self.assertTrue(triggers['workflow_call']['inputs']['packager_ref']['required'])

  def test_checkouts_use_resolved_refs_not_fixed_master(self) -> None:
    data, _ = self.load('visionworkshop-portable.yml')
    steps = data['jobs']['build']['steps']
    checkouts = [step['with'] for step in steps if step.get('uses', '').startswith('actions/checkout')]
    self.assertEqual(checkouts[0]['ref'], '${{ steps.revision.outputs.ref }}')
    self.assertEqual(checkouts[1]['ref'], '${{ inputs.source_ref }}')
    self.assertTrue(all(item['persist-credentials'] is False for item in checkouts))

  def test_actions_upload_only_whitelisted_public_outputs(self) -> None:
    data, _ = self.load('visionworkshop-portable.yml')
    upload = next(step['with'] for step in data['jobs']['build']['steps']
                  if step.get('uses', '').startswith('actions/upload-artifact'))
    self.assertEqual(upload['path'].splitlines(), [
      'packager/release-output/ci/*.zip', 'packager/release-output/ci/build-summary.json',
    ])

  def test_both_workflows_use_read_only_default_token(self) -> None:
    for name in ('visionworkshop-portable.yml', 'visionworkshop-tests.yml'):
      data, _ = self.load(name)
      self.assertEqual(data['permissions'], {'contents': 'read'})

  def test_inputs_are_not_interpolated_directly_into_shell_code(self) -> None:
    data, _ = self.load('visionworkshop-portable.yml')
    for step in data['jobs']['build']['steps']:
      self.assertNotIn('${{ inputs.', step.get('run', ''))
      self.assertNotIn('Invoke-Expression', step.get('run', ''))

  def test_preflight_precedes_heavy_dependency_install(self) -> None:
    data, _ = self.load('visionworkshop-portable.yml')
    names = [step.get('name') for step in data['jobs']['build']['steps']]
    self.assertLess(names.index('Preflight before heavy dependencies'),
                    names.index('Install unchanged source and CI dependencies'))

  def test_unit_workflow_has_no_production_source_or_release(self) -> None:
    text = (ROOT / '.github/workflows/visionworkshop-tests.yml').read_text()
    self.assertNotIn('SOURCE_REPO_TOKEN', text)
    self.assertNotIn('RELEASE_REPO_TOKEN', text)
    self.assertNotIn('gh release ', text)
    self.assertIn('verify_windows_portable.py', text)

  def test_ps_wrapper_retains_legacy_fallback_and_bound_switch_safety(self) -> None:
    text = (ROOT / 'scripts/publish-local-release.ps1').read_text()
    self.assertIn('publish-local-release-legacy.ps1', text)
    self.assertIn("@('DryRun', 'Publish', 'BuildRecordPath', 'PythonExecutable')", text)
    self.assertIn('$PSBoundParameters.ContainsKey($field)', text)
    self.assertIn("else { $arguments += '--build-only' }", text)
    self.assertNotIn('Invoke-Expression', text)


@unittest.skipUnless(os.name == 'nt', 'PowerShell execution requires the Windows runner')
class PowerShellTests(unittest.TestCase):
  def test_invalid_branding_and_conflicting_modes_fail(self) -> None:
    with tempfile.TemporaryDirectory() as source:
      for extras in (['-ProgramName', 'updater', '-DryRun'],
                     ['-ProgramName', 'VisionWorkshop', '-NotesOnly'],
                     ['-ProgramName', 'VisionWorkshop', '-Publish', '-BuildOnly']):
        with self.subTest(extras=extras):
          result = subprocess.run([
            shutil.which('pwsh') or 'powershell', '-NoProfile', '-NonInteractive', '-File',
            str(ROOT / 'scripts/publish-local-release.ps1'), '-SourceRoot', source,
            '-ReleaseTag', 'v1.2.3', '-PythonExecutable', sys.executable, *extras,
          ], capture_output=True, text=True, errors='replace', check=False, timeout=30)
          self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
  unittest.main()
