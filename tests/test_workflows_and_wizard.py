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
collectDocument = wizard.collectReleaseDocument


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
    self.output = io.StringIO()
    self.stack.enter_context(contextlib.redirect_stdout(self.output))
    self.stack.enter_context(patch.object(wizard, 'ROOT', self.root))
    self.stack.enter_context(patch.object(wizard, 'resolveBuildConfig', side_effect=
      functools.partial(resolveBuildConfig, packagerRoot=self.root)))
    self.documents = self.stack.enter_context(patch.object(wizard, 'collectReleaseDocument',
                                                          return_value=None))
    self.stack.enter_context(patch.object(wizard, 'gitCommit', return_value='a' * 40))

  def collect(self, replies: list[str], *, yes: bool = False):
    with patch('builtins.input', side_effect=replies):
      return wizard.collectArguments(yes=yes)

  def test_default_is_local_build_without_profile(self) -> None:
    args = self.collect(['', '', str(self.source), 'v1.2.3', 'y'])
    self.assertIn('--build-only', args)
    self.assertNotIn('--publish', args)
    self.assertFalse(any(arg.startswith('--branding-profile') for arg in args))

  def test_unprefixed_version_is_normalized_before_summary(self) -> None:
    args = self.collect(['1', '1', str(self.source), '1.0.20', 'y'])
    self.assertIn('--release-tag=v1.0.20', args)
    self.assertIn('emo-vision-train-windows-v1.0.20.zip', self.output.getvalue())
    self.assertIn('Release tag：v1.0.20', self.output.getvalue())

  def test_invalid_and_empty_versions_reprompt_before_confirmation(self) -> None:
    replies = ['1', '1', str(self.source), '', 'not-a-version', '1.0.20', 'y']
    with patch('builtins.input', side_effect=replies) as read:
      args = wizard.collectArguments()
    self.assertIn('--release-tag=v1.0.20', args)
    prompts = [call.args[0] for call in read.call_args_list]
    self.assertTrue(all('v1.2.3' in text for text in prompts[3:6]))
    self.assertIn('确认执行', prompts[6])

  def test_source_version_is_default_without_executing_source(self) -> None:
    (self.source / 'app_version.py').write_text(
      'APP_VERSION = "1.0.20"\nraise RuntimeError("must not execute")\n', encoding='utf-8',
    )
    with patch('builtins.input', side_effect=['1', '1', str(self.source), '', 'y']) as read, \
         patch.object(wizard.subprocess, 'run') as run:
      args = wizard.collectArguments()
    self.assertIn('--release-tag=v1.0.20', args)
    self.assertIn('[v1.0.20]', read.call_args_list[3].args[0])
    run.assert_not_called()

  def test_configured_source_version_takes_precedence(self) -> None:
    configPath = self.root / 'configs/emo-vision-train.json'
    config = json.loads(configPath.read_text(encoding='utf-8'))
    config['source_version_file'] = '${SOURCE_ROOT}/version.py'
    configPath.write_text(json.dumps(config), encoding='utf-8')
    (self.source / 'app_version.py').write_text('APP_VERSION = "1.0.19"\n', encoding='utf-8')
    (self.source / 'version.py').write_text('__version__ = "1.0.20"\n', encoding='utf-8')
    self.assertEqual(wizard.suggestReleaseTag(self.source), 'v1.0.20')

  def test_source_version_formats(self) -> None:
    for content in (
      'APP_VERSION: str = "1.0.20"\n',
      '__version__ = "1.0.20"\n',
      'APP_VERSION = "v1.0.20"\n',
      'APP_VERSION = "1.0.19"\nAPP_VERSION = "1.0.20"\n',
    ):
      with self.subTest(content=content):
        (self.source / 'app_version.py').write_text(content, encoding='utf-8-sig')
        self.assertEqual(wizard.suggestReleaseTag(self.source), 'v1.0.20')

  def test_unreadable_source_version_leaves_manual_input_available(self) -> None:
    for content in ('APP_VERSION =', 'APP_VERSION = "invalid"', 'APP_VERSION = getVersion()'):
      with self.subTest(content=content):
        (self.source / 'app_version.py').write_text(content, encoding='utf-8')
        self.assertEqual(wizard.suggestReleaseTag(self.source), '')
    args = self.collect(['1', '1', str(self.source), '1.0.20', 'y'])
    self.assertIn('--release-tag=v1.0.20', args)

  def configureReleaseRepo(self) -> None:
    configPath = self.root / 'configs/emo-vision-train.json'
    config = json.loads(configPath.read_text(encoding='utf-8'))
    config['release_repo'] = 'fixture/releases'
    configPath.write_text(json.dumps(config), encoding='utf-8')

  def test_release_default_bumps_patch_and_excludes_drafts(self) -> None:
    self.configureReleaseRepo()
    releases = [{'tagName': 'v1.0.99', 'isDraft': True}, {'tagName': 'v1.0.19'}]
    result = subprocess.CompletedProcess([], 0, json.dumps(releases))
    with patch.object(wizard.shutil, 'which', return_value='gh'), \
         patch.object(wizard.subprocess, 'run', return_value=result) as run:
      self.assertEqual(wizard.suggestReleaseTag(self.source), 'v1.0.20')
    self.assertIn('fixture/releases', run.call_args.args[0])
    self.assertEqual(run.call_args.kwargs['timeout'], 10)

  def test_source_version_does_not_require_github_lookup(self) -> None:
    self.configureReleaseRepo()
    (self.source / 'app_version.py').write_text('APP_VERSION = "1.0.20"\n', encoding='utf-8')
    with patch.object(wizard.subprocess, 'run') as run:
      self.assertEqual(wizard.suggestReleaseTag(self.source), 'v1.0.20')
    run.assert_not_called()

  def test_release_lookup_failure_does_not_prevent_manual_version(self) -> None:
    self.configureReleaseRepo()
    for error in (FileNotFoundError('gh unavailable'), subprocess.TimeoutExpired('gh', 10)):
      with self.subTest(error=error), \
           patch.object(wizard.shutil, 'which', return_value='gh'), \
           patch.object(wizard.subprocess, 'run', side_effect=error):
        args = self.collect(['1', '1', str(self.source), '1.0.20', 'y'])
        self.assertIn('--release-tag=v1.0.20', args)

  def test_no_release_default_when_gh_is_missing(self) -> None:
    self.configureReleaseRepo()
    with patch.object(wizard.shutil, 'which', return_value=None), \
         patch.object(wizard.subprocess, 'run') as run:
      self.assertEqual(wizard.suggestReleaseTag(self.source), '')
    run.assert_not_called()

  def test_invalid_release_responses_leave_no_default(self) -> None:
    self.configureReleaseRepo()
    for code, output in (
      (1, 'not logged in'), (0, 'invalid JSON'), (0, '{}'), (0, '[]'),
      (0, '[null, {"tagName": 123}]'),
      (0, '[{"tagName": "v1.0.20-rc.1"}, {"tagName": "v1.0.19"}]'),
    ):
      with self.subTest(output=output), \
           patch.object(wizard.shutil, 'which', return_value='gh'), \
           patch.object(wizard.subprocess, 'run',
                        return_value=subprocess.CompletedProcess([], code, output)):
        self.assertEqual(wizard.suggestReleaseTag(self.source), '')

  def test_saved_source_root_is_reused_without_changing_state(self) -> None:
    statePath = self.root / '.release-wizard.local.json'
    statePath.write_text(json.dumps({
      'target': 'emo-vision-train', 'sourceRoot': str(self.source),
    }), encoding='utf-8')
    before = statePath.read_bytes()
    with patch.dict(os.environ, {'SOURCE_ROOT': ''}):
      args = self.collect(['1', '1', '', '1.0.20', 'y'])
    self.assertIn(f'--source-root={self.source}', args)
    self.assertEqual(statePath.read_bytes(), before)

  def test_source_environment_overrides_saved_state(self) -> None:
    with patch.dict(os.environ, {'SOURCE_ROOT': str(self.source)}), \
         patch.object(wizard, 'loadLocalState') as load:
      self.assertEqual(wizard.getDefaultSourceRoot(), str(self.source))
    load.assert_not_called()

  def test_other_target_source_root_is_not_reused(self) -> None:
    with patch.dict(os.environ, {'SOURCE_ROOT': ''}), \
         patch.object(wizard, 'loadLocalState', return_value={
           'target': 'emo-master', 'sourceRoot': str(self.source),
         }):
      self.assertEqual(wizard.getDefaultSourceRoot(), '')

  def test_missing_source_fails_before_version_lookup(self) -> None:
    with patch.object(wizard, 'suggestReleaseTag') as suggest, \
         self.assertRaisesRegex(BuildConfigError, '源码目录不存在'):
      self.collect(['1', '1', str(self.root / 'missing')])
    suggest.assert_not_called()

  def test_eof_at_version_cancels_even_when_default_and_yes_are_available(self) -> None:
    (self.source / 'app_version.py').write_text('APP_VERSION = "1.0.20"\n', encoding='utf-8')
    with patch.object(wizard, 'releaseMain') as execute, \
         patch('builtins.input', side_effect=['1', '1', str(self.source), EOFError]), \
         contextlib.redirect_stderr(io.StringIO()):
      self.assertEqual(wizard.main(['--yes']), 1)
    execute.assert_not_called()

  def test_yes_cannot_bypass_invalid_version(self) -> None:
    with patch.object(wizard, 'releaseMain') as execute, \
         patch('builtins.input', side_effect=['1', '1', str(self.source), 'bad', EOFError]), \
         contextlib.redirect_stderr(io.StringIO()):
      self.assertEqual(wizard.main(['--yes']), 1)
    execute.assert_not_called()

  def test_normalization_keeps_shared_release_tag_contract(self) -> None:
    for value in ('1.0.20', ' v1.0.20 ', '1.0.20-rc.1', 'v1.0.20-rc.1'):
      with self.subTest(value=value):
        tag = wizard.normalizeReleaseTag(value)
        self.assertTrue(wizard.RELEASE_TAG.fullmatch(tag))
        self.assertFalse(tag.startswith('vv'))
    for value in ('', 'v', 'main', '1', 'v1.2.3/unsafe'):
      with self.subTest(value=value), self.assertRaises(BuildConfigError):
        wizard.normalizeReleaseTag(value)

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

  def test_publication_fields_and_frozen_markdown_reach_shared_entry(self) -> None:
    self.configureReleaseRepo()
    self.documents.side_effect = collectDocument
    path = self.root / 'notes.md'
    path.write_text('# Release details\n', encoding='utf-8')
    with patch.object(wizard, 'gitState', return_value={'dirty': False, 'submodules_ready': True}), \
         patch.object(wizard.content, 'requireNewRelease') as check, \
         patch.object(wizard.content, 'resolveCommit', return_value='a' * 40):
      args = self.collect(['3', '1', str(self.source), '1.0.20', '', '',
                           'Short update summary', 'y', '2', str(path), 'y'])
    self.assertIn('--publish', args)
    self.assertIn('--release-repo=fixture/releases', args)
    self.assertIn('--release-title=emo-vision-train v1.0.20', args)
    self.assertIn('--notes=Short update summary', args)
    self.assertIn('--mandatory', args)
    self.assertIn('--expected-source-commit=' + 'a' * 40, args)
    saved = Path(next(arg.split('=', 1)[1] for arg in args if arg.startswith('--release-body-path=')))
    self.assertEqual(saved.read_text(encoding='utf-8'), '# Release details\n')
    self.assertNotEqual(saved, path)
    check.assert_called_once_with('fixture/releases', 'v1.0.20')

  def test_cancel_document_review_does_not_save_automatic_draft(self) -> None:
    self.documents.side_effect = collectDocument
    path = self.root / 'notes.md'
    path.write_text('# Release details\n', encoding='utf-8')
    before = sorted(self.root.rglob('*'))
    with patch.object(wizard.content, 'resolveCommit', return_value='a' * 40):
      result = self.collect(['1', '1', str(self.source), 'v1.0.20',
                             'y', '', '', '', '2', str(path), 'n'])
    self.assertIsNone(result)
    self.assertEqual(sorted(self.root.rglob('*')), before)

  def test_explicit_range_is_used_for_generated_preview(self) -> None:
    self.documents.side_effect = collectDocument
    with patch.object(wizard.content, 'resolveCommit', return_value='b' * 40), \
         patch.object(wizard.content, 'resolveBase', return_value='a' * 40), \
         patch.object(wizard.content, 'getChanges', return_value=['1234567 fix: example']):
      args = self.collect(['2', '1', str(self.source), 'v1.0.20', 'y', '', '', '',
                           '1', '2', 'old-tag', 'p', 'y'])
    self.assertIn('--dry-run', args)
    self.assertIn('--previous-source-ref=' + 'a' * 40, args)
    self.assertIn('fix: example', self.output.getvalue())
    self.assertNotIn('--publish', args)

  def test_return_to_settings_preserves_edited_body(self) -> None:
    self.documents.side_effect = collectDocument
    path = self.root / 'notes.md'
    path.write_text('# original\n', encoding='utf-8')
    with patch.object(wizard.content, 'resolveCommit', return_value='a' * 40), \
         patch.object(wizard, 'editBody', return_value='# edited\n'):
      args = self.collect(['1', '1', str(self.source), 'v1.0.20',
                           'y', '', '', '', '2', str(path), 'e', 'b',
                           '', '', 'Changed short summary', '', '', 'y'])
    self.assertIn('--notes=Changed short summary', args)
    saved = Path(next(arg.split('=', 1)[1] for arg in args if arg.startswith('--release-body-path=')))
    self.assertEqual(saved.read_text(encoding='utf-8'), '# edited\n')

  def test_notes_only_skips_branding_and_uses_existing_tag(self) -> None:
    self.configureReleaseRepo()
    path = self.root / 'notes.md'
    path.write_text('# corrected\n', encoding='utf-8')
    release = {'id': 10, 'tag_name': 'v1.0.19', 'name': 'Old title', 'body': '# old\n', 'assets': []}
    with patch.object(wizard.content, 'checkRepository'), \
         patch.object(wizard.content, 'listReleases', return_value=[release]), \
         patch.object(wizard.content, 'getRelease', return_value=release), \
         patch.object(wizard, 'resolveBuildConfig') as resolve:
      args = self.collect(['6', '', '', '2', str(path), 'p', 'y'])
    self.assertIn('--notes-only', args)
    self.assertIn('--publish', args)
    self.assertIn('--release-tag=v1.0.19', args)
    self.assertTrue(any(arg.startswith('--expected-release-fingerprint=') for arg in args))
    self.assertFalse(any(arg.startswith('--branding-profile') for arg in args))
    self.assertIn('-# old', self.output.getvalue())
    self.assertIn('+# corrected', self.output.getvalue())
    resolve.assert_not_called()

  def test_notes_only_regeneration_pins_published_source_not_current_head(self) -> None:
    self.configureReleaseRepo()
    release = {'id': 10, 'tag_name': 'v1.0.19', 'body': '# old\n'}
    manifest = {'source_commit': 'a' * 40, 'source_base_ref': 'b' * 40, 'notes': 'old summary'}
    with patch.object(wizard.content, 'checkRepository'), \
         patch.object(wizard.content, 'listReleases', return_value=[release]), \
         patch.object(wizard.content, 'getRelease', return_value=release), \
         patch.object(wizard.content, 'readManifest', return_value=manifest), \
         patch.object(wizard.content, 'getPublishedHead', return_value='a' * 40), \
         patch.object(wizard.content, 'resolveBase', return_value='b' * 40), \
         patch.object(wizard.content, 'generateBody', return_value='# historical\n') as generate, \
         patch.object(wizard.content, 'resolveCommit') as head:
      args = self.collect(['6', '', '', '3', str(self.source), 'y'])
    self.assertIn('--release-tag=v1.0.19', args)
    self.assertEqual(generate.call_args.kwargs['head'], 'a' * 40)
    self.assertEqual(generate.call_args.kwargs['base'], 'b' * 40)
    head.assert_not_called()

  def test_notes_only_cancel_and_eof_do_not_publish(self) -> None:
    self.configureReleaseRepo()
    release = {'id': 10, 'tag_name': 'v1.0.19', 'body': '# old\n'}
    with patch.object(wizard.content, 'checkRepository'), \
         patch.object(wizard.content, 'listReleases', return_value=[release]), \
         patch.object(wizard.content, 'getRelease', return_value=release), \
         patch.object(wizard, 'editBody', return_value='# edited\n'), \
         patch.object(wizard, 'releaseMain') as run, \
         patch('builtins.input', side_effect=['6', '', '', '1', 'n']):
      self.assertEqual(wizard.main([]), 0)
    run.assert_not_called()
    self.assertFalse((self.root / 'artifacts').exists())


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
