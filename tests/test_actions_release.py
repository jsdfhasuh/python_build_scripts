import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock
from unittest.mock import patch

import actions_release as ci
from build_config import BuildConfigError
from update_protocol_publish import artifactRecords


def release(tag: str, number: int = 1, **fields) -> dict:
  return {'id': number, 'tag_name': tag, 'draft': False, 'prerelease': False, **fields}


class SelectionTests(unittest.TestCase):
  def test_auto_uses_highest_older_version_not_api_order(self):
    releases = [release('v1.2.0'), release('v1.10.0', 2), release('v2.0.0', 3)]
    self.assertEqual(ci.selectBaseline(releases, 'v2.0.0', 'auto')['id'], 2)

  def test_first_release_and_explicit_none(self):
    self.assertIsNone(ci.selectBaseline([], 'v1.0.0', 'auto'))
    self.assertIsNone(ci.selectBaseline([release('v9.0.0')], 'v1.0.0', 'none'))

  def test_history_without_eligible_baseline_does_not_downgrade(self):
    for releases in ([release('v2.0.0')], [release('v1.0.0')]):
      with self.assertRaises(BuildConfigError):
        ci.selectBaseline(releases, 'v1.0.0', 'auto')

  def test_explicit_tag_never_falls_back(self):
    history = [release('v1.0.0'), release('v1.1.0', 2)]
    self.assertEqual(ci.selectBaseline(history, 'v2.0.0', 'v1.0.0')['id'], 1)
    for tag in ('v0.1.0', 'v2.0.0', 'v3.0.0'):
      with self.assertRaises(BuildConfigError):
        ci.selectBaseline(history, 'v2.0.0', tag)

  def test_invalid_or_ambiguous_versions_fail(self):
    for history in ([release('unknown')], [release('v1.0.0'), release('1.0.0', 2)]):
      with self.assertRaises(BuildConfigError):
        ci.selectBaseline(history, 'v2.0.0', 'auto')

  def test_paginated_history_filters_drafts_and_prereleases(self):
    pages = [[release('v1.0.0'), release('v2.0.0', draft=True)],
             [release('v3.0.0', prerelease=True), release('v1.1.0', 4)]]
    with patch.object(ci.content, 'runTool', return_value=json.dumps(pages)) as run:
      self.assertEqual([r['tag_name'] for r in ci.listOfficialReleases(ci.RELEASE_REPO)],
                       ['v1.0.0', 'v1.1.0'])
    self.assertIn('--paginate', run.call_args.args[0])

  def test_query_errors_are_not_empty_history(self):
    with patch.object(ci.content, 'runTool', side_effect=BuildConfigError('HTTP 403')):
      with self.assertRaisesRegex(BuildConfigError, '403'):
        ci.listOfficialReleases(ci.RELEASE_REPO)
    with patch.object(ci.content, 'runTool', return_value='{}'):
      with self.assertRaises(BuildConfigError):
        ci.listOfficialReleases(ci.RELEASE_REPO)


class RequestTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.source = self.root / 'source'
    self.source.mkdir()
    (self.source / 'app_version.py').write_text("__version__ = '2.0.0'\n", encoding='utf-8')
    self.inputs = {'source_ref': 'main'}
    self.addCleanup(patch.stopall)
    patch.object(ci.content, 'resolveCommit', return_value='a' * 40).start()
    self.history = patch.object(ci, 'listOfficialReleases', return_value=[]).start()
    self.execute = patch.object(ci, 'executeRequest').start()
    patch('portable_release.resolveRequest',
          return_value=(Mock(programName='emo-vision-train'), None, None, None)).start()
    patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': ''}).start()

  def prepare(self):
    return ci.prepareRequest(self.inputs, self.source, self.root / 'state', self.root / 'output')

  def test_first_release_defaults_and_preflight(self):
    result = self.prepare()
    self.assertEqual(result['release_tag'], 'v2.0.0')
    self.assertEqual(result['baseline_tag'], 'none')
    self.assertTrue(result['changelog_all'])
    self.assertFalse(result['publish'])
    self.assertIn('--build-only', result['arguments'])
    self.assertIn('--source-ref=' + 'a' * 40, result['arguments'])
    self.assertEqual(self.execute.call_args.kwargs, {'dryRun': True})

  def test_version_mismatch_fails_before_history_query(self):
    self.inputs['release_tag'] = 'v1.0.0'
    with self.assertRaisesRegex(BuildConfigError, 'source version'):
      self.prepare()
    self.history.assert_not_called()

  def test_computed_version_is_not_executed(self):
    (self.source / 'app_version.py').write_text('__version__ = str(2)\n', encoding='utf-8')
    with self.assertRaises(BuildConfigError):
      ci.sourceVersion({}, self.source, '')

  def test_app_version_and_configured_version_match_protocol_reader(self):
    (self.source / 'app_version.py').write_text(
      "APP_VERSION: str = '2.0.0'\n__version__ = '1.0.0'\n", encoding='utf-8-sig')
    self.assertEqual(ci.sourceVersion({}, self.source, ''), 'v2.0.0')
    self.assertEqual(ci.sourceVersion({'source_version_file': 'app_version.py'},
                                     self.source, ''), 'v1.0.0')

  def test_publish_requires_token(self):
    self.inputs['publish_release'] = True
    with patch.dict(os.environ, {'GH_TOKEN': 'read-only-token', 'RELEASE_REPO_TOKEN': ''}):
      with self.assertRaisesRegex(BuildConfigError, 'RELEASE_REPO_TOKEN'):
        self.prepare()

  def test_publish_passes_document_flags(self):
    self.inputs.update({'publish_release': True, 'release_title': 'Title',
                        'notes': 'Some notes', 'changelog_all': True})
    with patch.dict(os.environ, {'GH_TOKEN': 'fixture-token',
                                 'RELEASE_REPO_TOKEN': 'fixture-token'}):
      result = self.prepare()
    for arg in ('--publish', '--release-title=Title', '--notes=Some notes'):
      self.assertIn(arg, result['arguments'])
    self.assertNotIn('--build-only', result['arguments'])

  def test_build_only_accepts_read_token_without_publish_secret(self):
    with patch.dict(os.environ, {'GH_TOKEN': 'read-only-token', 'RELEASE_REPO_TOKEN': ''}):
      result = self.prepare()
    self.assertFalse(result['publish'])
    self.history.assert_called_once()

  def test_mandatory_fails_before_history_or_compilation(self):
    self.inputs['mandatory'] = True
    with self.assertRaisesRegex(BuildConfigError, 'does not support mandatory'):
      self.prepare()
    self.history.assert_not_called()
    self.execute.assert_not_called()

  def test_query_failure_does_not_build(self):
    self.history.side_effect = BuildConfigError('HTTP 401')
    with self.assertRaises(BuildConfigError):
      self.prepare()
    self.execute.assert_not_called()

  def test_invalid_selected_baseline_never_retries_older_release(self):
    self.history.return_value = [release('v1.0.0'), release('v1.1.0', 2)]
    with patch.object(ci, 'prepareBaseline', side_effect=BuildConfigError('bad baseline')) as base:
      with self.assertRaisesRegex(BuildConfigError, 'bad baseline'):
        self.prepare()
    self.assertEqual(base.call_count, 1)
    self.assertEqual(base.call_args.args[1]['tag_name'], 'v1.1.0')

  def test_notes_base_is_independent_of_explicit_delta_base(self):
    self.history.return_value = [release('v1.0.0'), release('v1.1.0', 2)]
    self.inputs['delta_base_tag'] = 'v1.0.0'
    lock = self.root / 'lock.json'
    lock.write_text('{}', encoding='utf-8')
    with patch.object(ci, 'prepareBaseline', return_value=lock), \
         patch.object(ci.content, 'readManifest', return_value={}) as read, \
         patch.object(ci.content, 'getPublishedHead', return_value='b' * 40), \
         patch.object(ci.content, 'resolveBase', return_value='b' * 40):
      result = self.prepare()
    self.assertEqual(read.call_args.args[1]['tag_name'], 'v1.1.0')
    self.assertEqual(result['baseline_tag'], 'v1.0.0')
    self.assertEqual(result['previous_source_ref'], 'b' * 40)
    self.assertEqual(result['expected_asset_count'], 5)

  def test_body_path_is_confined_and_existing_markdown(self):
    (self.root / 'notes.md').write_text('Notes', encoding='utf-8')
    self.assertEqual(ci.resolveBody(self.root, 'notes.md'), (self.root / 'notes.md').resolve())
    for path in ('../notes.md', str(self.root / 'notes.md'), 'C:notes.md',
                 '\\server\\notes.md', 'missing.md', 'notes.txt'):
      with self.assertRaises(BuildConfigError, msg=path):
        ci.resolveBody(self.root, path)

  def test_conflicting_log_options_fail(self):
    self.inputs.update({'previous_source_ref': 'old', 'changelog_all': True})
    with self.assertRaisesRegex(BuildConfigError, 'not both'):
      self.prepare()


class BaselineLockTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name).resolve()
    self.fullName = ci.ASSET_PREFIX + '-old-full.zip'
    names = [ci.IDENTITY_NAME, ci.FILES_NAME, self.fullName]
    assets = {}
    for index, name in enumerate(names, 1):
      raw = name.encode('utf-8')
      (self.root / name).write_bytes(raw)
      assets[name] = {'id': index, 'name': name, 'size': len(raw), 'state': 'uploaded',
                      'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
    self.lock = {'id': 42, 'repository': ci.RELEASE_REPO, 'tag': 'v1.0.0', 'assets': assets,
                 'full_name': self.fullName, 'files_name': ci.FILES_NAME,
                 'directory': str(self.root)}
    self.path = self.root / 'lock.json'
    self.path.write_text(json.dumps(self.lock), encoding='utf-8')
    self.remote = {key: self.lock[key] for key in ('id', 'repository', 'tag', 'assets')}

  def test_unchanged_snapshot_returns_fixed_local_manifest(self):
    with patch.object(ci, 'releaseSnapshot', return_value=self.remote):
      self.assertEqual(ci.verifyBaselineLock(self.path), self.root / ci.FILES_NAME)

  def test_remote_identity_size_hash_or_asset_set_change_fails(self):
    for mutation in ('id', 'size', 'digest', 'deleted'):
      changed = copy.deepcopy(self.remote)
      if mutation == 'id':
        changed['id'] += 1
      elif mutation == 'deleted':
        del changed['assets'][self.fullName]
      else:
        changed['assets'][self.fullName][mutation] = 'changed'
      with self.subTest(mutation=mutation), \
           patch.object(ci, 'releaseSnapshot', return_value=changed):
        with self.assertRaisesRegex(BuildConfigError, 'changed'):
          ci.verifyBaselineLock(self.path)

  def test_local_baseline_change_fails(self):
    (self.root / ci.FILES_NAME).write_bytes(b'tampered')
    with patch.object(ci, 'releaseSnapshot', return_value=self.remote):
      with self.assertRaisesRegex(BuildConfigError, 'frozen metadata'):
        ci.verifyBaselineLock(self.path)

  def test_delta_uses_frozen_files_and_checks_returned_base_hash(self):
    import portable_release as portable
    args = portable.makeParser().parse_args([
      '--release-tag=v2.0.0', '--delta-base-tag=v1.0.0',
      f'--delta-base-lock={self.path}', f'--delta-base-lock-sha256={ci.fileHash(self.path)}',
    ])
    resolved = Mock(config={'release_repo': ci.RELEASE_REPO})
    digest = self.lock['assets'][ci.FILES_NAME]['digest'][7:]
    with patch.object(ci, 'releaseSnapshot', return_value=self.remote), \
         patch.object(portable, 'runProducer', return_value={'base_files_sha256': digest}) as run:
      portable.runDeltaProducer(args, resolved, None, self.root, self.root)
      self.assertIn('--base-files', run.call_args.args)
      self.assertNotIn('--base-tag', run.call_args.args)
      run.return_value = {'base_files_sha256': '0' * 64}
      with self.assertRaisesRegex(BuildConfigError, 'different baseline'):
        portable.runDeltaProducer(args, resolved, None, self.root, self.root)
      self.path.write_text('{}', encoding='utf-8')
      with self.assertRaisesRegex(BuildConfigError, 'lock changed'):
        portable.runDeltaProducer(args, resolved, None, self.root, self.root)

  def test_baseline_missing_metadata_fails_before_download(self):
    snapshot = copy.deepcopy(self.remote)
    del snapshot['assets'][ci.IDENTITY_NAME]
    state = self.root / 'state'
    state.mkdir()
    with patch.object(ci, 'releaseSnapshot', return_value=snapshot), \
         patch.object(ci, 'downloadAsset') as download:
      with self.assertRaisesRegex(BuildConfigError, 'missing protocol metadata'):
        ci.prepareBaseline(ci.RELEASE_REPO, release('v1.0.0', 42), self.root, state, 'o/r')
    download.assert_not_called()


class StageTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.output = self.root / 'output'
    self.output.mkdir()
    self.destination = self.root / 'public'

  def writeSummary(self, delta=False):
    fullName = ci.ASSET_PREFIX + '-new-full.zip'
    names = [fullName, ci.IDENTITY_NAME, ci.FILES_NAME]
    if delta:
      deltaName = ci.ASSET_PREFIX + '-new-from-old-delta.zip'
      names.extend([deltaName, deltaName[:-4] + '_descriptor.json'])
    for name in names:
      (self.output / name).write_bytes(name.encode('utf-8'))
    summary = {'asset_name': fullName, 'protocol_asset_names': names,
               'protocol_assets': artifactRecords([self.output / name for name in names])}
    (self.output / 'build-summary.json').write_text(json.dumps(summary), encoding='utf-8')
    (self.output / 'build-record.json').write_text('private', encoding='utf-8')
    return summary

  def test_full_assets_and_summary_only(self):
    summary = self.writeSummary()
    ci.stageAssets(self.output, self.destination)
    self.assertEqual({path.name for path in self.destination.iterdir()},
                     set(summary['protocol_asset_names']) | {'build-summary.json'})

  def test_delta_assets_include_descriptor(self):
    summary = self.writeSummary(delta=True)
    ci.stageAssets(self.output, self.destination)
    self.assertEqual(len(list(self.destination.iterdir())), 6)
    self.assertTrue((self.destination / summary['protocol_asset_names'][-1]).exists())

  def test_expected_delta_mode_cannot_stage_full_only(self):
    self.writeSummary()
    with self.assertRaisesRegex(BuildConfigError, 'prepared release mode'):
      ci.stageAssets(self.output, self.destination, expectedCount=5)

  def test_missing_or_modified_asset_fails_before_staging(self):
    self.writeSummary()
    (self.output / ci.FILES_NAME).unlink()
    with self.assertRaises(BuildConfigError):
      ci.stageAssets(self.output, self.destination)
    self.assertFalse(self.destination.exists())
    self.writeSummary()
    (self.output / ci.FILES_NAME).write_bytes(b'tampered')
    with self.assertRaises(BuildConfigError):
      ci.stageAssets(self.output, self.destination)
    self.assertFalse(self.destination.exists())

  def test_unexpected_and_traversal_names_are_not_staged(self):
    summary = self.writeSummary()
    for name in ('build-record.json', '../private.json', 'C:secret', 'NUL', 'dir/file.zip'):
      summary['protocol_asset_names'][1] = name
      (self.output / 'build-summary.json').write_text(json.dumps(summary), encoding='utf-8')
      with self.assertRaises(BuildConfigError, msg=name):
        ci.stageAssets(self.output, self.destination)
      self.assertFalse(self.destination.exists())

  def test_copy_time_mutation_is_detected(self):
    self.writeSummary()
    original = ci.shutil.copyfile
    def changedCopy(source, target):
      original(source, target)
      target.write_bytes(b'changed')
    with patch.object(ci.shutil, 'copyfile', side_effect=changedCopy):
      with self.assertRaisesRegex(BuildConfigError, 'while staging'):
        ci.stageAssets(self.output, self.destination)


class WorkflowTests(unittest.TestCase):
  def load(self, name):
    import yaml
    data = yaml.safe_load((ci.ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))
    return data, data.get('on', data.get(True))

  def test_both_entrypoints_expose_document_and_baseline_inputs(self):
    required = {'release_tag', 'delta_base_tag', 'release_title', 'notes', 'mandatory',
                'previous_source_ref', 'release_body_path', 'changelog_all', 'packager_ref'}
    for name in ('release-windows.yml', 'visionworkshop-portable.yml'):
      _, events = self.load(name)
      dispatch = events['workflow_dispatch']['inputs']
      called = events['workflow_call']['inputs']
      self.assertEqual(set(dispatch), set(called))
      self.assertTrue(required <= set(dispatch))
      self.assertLessEqual(len(dispatch), 25)
      for inputs in (dispatch, called):
        self.assertEqual(inputs['delta_base_tag']['default'], 'auto')
        self.assertFalse(inputs['release_tag'].get('required', False))

  def test_legacy_entry_routes_train_only_to_shared_workflow(self):
    data, events = self.load('release-windows.yml')
    train, master = data['jobs']['vision_train'], data['jobs']['build']
    self.assertEqual(train['if'], "inputs.target == 'emo-vision-train'")
    self.assertEqual(master['if'], "inputs.target != 'emo-vision-train'")
    self.assertEqual(train['uses'], './.github/workflows/visionworkshop-portable.yml')
    self.assertEqual(train['with']['branding_profile'], 'profiles/visionworkshop.json')
    self.assertEqual(events['workflow_dispatch']['inputs']['publish_release']['default'], 'auto')
    self.assertIs(events['workflow_call']['inputs']['publish_release']['default'], False)
    steps = master['steps']
    self.assertEqual(steps[0]['with']['ref'], 'master')
    buildStep = next(step for step in steps if step.get('name') == 'Build Windows artifacts')
    self.assertIn('.\\scripts\\publish-local-release.ps1 @publishArgs', buildStep['run'])
    self.assertIn("$env:PUBLISH_RELEASE_INPUT -eq 'false'", buildStep['run'])
    self.assertEqual(steps[-1]['with']['path'], 'packager/release-output/*')

  def test_ci_uses_runtime_installer_and_profile_cache_key(self):
    data, _ = self.load('visionworkshop-portable.yml')
    steps = data['jobs']['build']['steps']
    installer = next(step for step in steps if step.get('name') ==
                     'Install verified Vision Train GPU dependencies')
    self.assertIn('vision_train_runtime.py install', installer['run'])
    self.assertIn('$LASTEXITCODE', installer['run'])
    self.assertNotIn('pip install @packages', installer['run'])
    pythonStep = next(step for step in steps if 'setup-python' in step.get('uses', ''))
    self.assertIn('ci/vision-train-runtime.json', pythonStep['with']['cache-dependency-path'])

  def test_shared_preparation_and_execution_use_frozen_state(self):
    data, _ = self.load('visionworkshop-portable.yml')
    steps = data['jobs']['build']['steps']
    prepare = next(step for step in steps if step.get('name') == 'Preflight before heavy dependencies')
    execute = next(step for step in steps if step.get('name') == 'Build through the shared portable entry')
    self.assertIn('actions_release.py prepare', prepare['run'])
    self.assertIn('actions_release.py build', execute['run'])
    self.assertIn('RELEASE_INPUTS_JSON', prepare['env'])
    self.assertNotIn('RELEASE_INPUTS_JSON', execute['env'])
    for step in (prepare, execute):
      self.assertEqual(step['env']['GH_TOKEN'], '${{ secrets.RELEASE_REPO_TOKEN || github.token }}')
      self.assertEqual(step['env']['RELEASE_REPO_TOKEN'], '${{ secrets.RELEASE_REPO_TOKEN }}')
    for step in steps:
      self.assertNotIn('${{ inputs.', step.get('run', ''))


class ExecutionTests(unittest.TestCase):
  def test_build_cannot_publish_with_only_a_read_token(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'request.json'
      path.write_text(json.dumps({
        'source_root': directory, 'source_commit': 'a' * 40, 'packager_commit': 'a' * 40,
        'baseline_lock': '', 'arguments': ['--publish'], 'publish': True,
      }))
      with patch.object(ci.content, 'resolveCommit', return_value='a' * 40), \
           patch.dict(os.environ, {'GH_TOKEN': 'read-token', 'RELEASE_REPO_TOKEN': ''}), \
           patch.object(ci.subprocess, 'run') as run:
        with self.assertRaisesRegex(BuildConfigError, 'explicit RELEASE_REPO_TOKEN'):
          ci.executeRequest(path)
      run.assert_not_called()

  def test_dry_run_and_build_share_exact_arguments(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'request.json'
      request = {'source_root': directory, 'source_commit': 'a' * 40,
                 'packager_commit': 'a' * 40, 'baseline_lock': '',
                 'arguments': ['--release-tag=v2.0.0', '--notes=a b', '--build-only']}
      path.write_text(json.dumps(request), encoding='utf-8')
      with patch.object(ci.content, 'resolveCommit', return_value='a' * 40), \
           patch.object(ci.subprocess, 'run', return_value=Mock(returncode=0)) as run:
        ci.executeRequest(path, dryRun=True)
        ci.executeRequest(path)
      preview, build = [call.args[0] for call in run.call_args_list]
      self.assertEqual(preview, build + ['--dry-run'])
      self.assertIn('--notes=a b', build)
      self.assertIn('--verify-vision-train-runtime', build)
      self.assertTrue(any(arg.endswith('publish_visionworkshop.py') for arg in build))
      with patch.object(ci.content, 'resolveCommit', return_value='b' * 40), \
           patch.object(ci.subprocess, 'run') as run:
        with self.assertRaisesRegex(BuildConfigError, 'Checkout changed'):
          ci.executeRequest(path)
      run.assert_not_called()


class ValidatorTests(unittest.TestCase):
  def test_missing_frozen_interface_fails_explicitly(self):
    from scripts import validate_actions_baseline as validator
    with patch.object(validator.sys, 'argv', ['validate', '--source-root=.', '--lock=unused']), \
         patch.object(validator.subprocess, 'run',
                      return_value=Mock(returncode=0, stdout='--base-tag')):
      with self.assertRaisesRegex(ValueError, '--base-files'):
        validator.main()

  def test_source_contract_and_archive_consumer_validate_baseline(self):
    import sys
    from scripts import validate_actions_baseline as validator
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      identityName = ci.IDENTITY_NAME
      (root / identityName).write_text(json.dumps({'source': {'repository': 'o/r'}}),
                                      encoding='utf-8')
      (root / ci.FILES_NAME).write_bytes(b'files')
      fullName = ci.ASSET_PREFIX + '-old-full.zip'
      (root / fullName).write_bytes(b'zip')
      lock = {'tag': 'v1.0.0', 'directory': directory, 'source_repository': 'o/r',
              'files_name': ci.FILES_NAME, 'full_name': fullName, 'assets': {fullName: {}}}
      lockPath = root / 'lock.json'
      lockPath.write_text(json.dumps(lock), encoding='utf-8')
      contract, package, payload, storage = Mock(), Mock(), MagicMock(), Mock()
      storage.read_bytes.side_effect = lambda path, maximum: path.read_bytes()
      payload.PayloadArchive.return_value.__enter__.return_value.payload = {}
      contract.Identity.parse.return_value.release_tag = 'v1.0.0'
      contract.Asset.parse.return_value.name = fullName
      with patch.object(sys, 'path', list(sys.path)), \
           patch.dict(sys.modules, {'update_contract': contract, 'update_package': package, 'update_payload': payload, 'update_storage': storage}), \
           patch.object(sys, 'argv', ['validate', f'--source-root={root}', f'--lock={lockPath}']), \
           patch.object(validator.subprocess, 'run',
                        return_value=Mock(returncode=0, stdout='--base-files')):
        self.assertEqual(validator.main(), 0)
      contract.Manifest.parse.return_value.bind_identity.assert_called_once()
      payload.PayloadArchive.assert_called_once()


if __name__ == '__main__':
  unittest.main()
