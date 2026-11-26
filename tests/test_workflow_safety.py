"""Keep merged diagnostics separate from production publication entrypoints."""

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'
PRODUCTION = ('release-windows.yml', 'visionworkshop-portable.yml')
DIAGNOSTICS = (
  'diagnose-baseline-startup.yml',
  'diagnose-updater-fixtures.yml',
  'published-update-retest.yml',
)


def loadWorkflow(name: str):
  data = yaml.safe_load((WORKFLOWS / name).read_text(encoding='utf-8'))
  return data, data.get('on', data.get(True))


def getSteps(data: dict) -> list[dict]:
  return [step for job in data['jobs'].values() for step in job.get('steps', [])]


class WorkflowSafetyTests(unittest.TestCase):
  def test_all_workflows_parse_with_named_jobs(self) -> None:
    for path in WORKFLOWS.glob('*.yml'):
      with self.subTest(workflow=path.name):
        data, events = loadWorkflow(path.name)
        self.assertTrue(data['name'])
        self.assertTrue(events)
        self.assertTrue(data['jobs'])

  def test_production_release_is_manual_or_explicitly_called(self) -> None:
    for name in PRODUCTION:
      with self.subTest(workflow=name):
        _, events = loadWorkflow(name)
        self.assertEqual(set(events), {'workflow_dispatch', 'workflow_call'})

  def test_production_has_no_historical_or_source_fixture_gate(self) -> None:
    for name in PRODUCTION:
      with self.subTest(workflow=name):
        text = (WORKFLOWS / name).read_text(encoding='utf-8')
        for forbidden in ('VISIONWORKSHOP_REQUIRE_WINDOWS_ACCEPTANCE', 'v1.0.28',
                          'verify_release_transition_windows.py', 'verify_update_windows.py',
                          'test_update_v3_runtime.py', 'pytest'):
          self.assertNotIn(forbidden, text)

  def test_production_preserves_first_full_only_and_incremental_inputs(self) -> None:
    for name in PRODUCTION:
      with self.subTest(workflow=name):
        _, events = loadWorkflow(name)
        for event in ('workflow_dispatch', 'workflow_call'):
          inputs = events[event]['inputs']
          self.assertEqual(inputs['delta_base_tag']['default'], 'auto')
          self.assertEqual(inputs['release_tag'].get('default', ''), '')
          self.assertFalse(inputs['release_tag'].get('required', False))
          self.assertIs(inputs['changelog_all']['default'], False)
    data, _ = loadWorkflow('release-windows.yml')
    self.assertEqual(data['jobs']['vision_train']['with']['delta_base_tag'],
                     '${{ inputs.delta_base_tag }}')

  def test_all_default_tokens_are_read_only(self) -> None:
    for path in WORKFLOWS.glob('*.yml'):
      with self.subTest(workflow=path.name):
        data, _ = loadWorkflow(path.name)
        self.assertEqual(data['permissions'], {'contents': 'read'})
        for jobName, job in data['jobs'].items():
          if ((path.name == 'release-windows.yml' and jobName == 'build') or
              (path.name == 'release-emo-master.yml' and jobName in ('package', 'release'))):
            self.assertEqual(job['permissions'], {'contents': 'write'})
          elif ((path.name == 'visionworkshop-modular-candidate.yml'
                 and jobName == 'windows-modular-candidate') or
                (path.name == 'visionworkshop-core-diagnostic.yml'
                 and jobName == 'windows-core-exit-diagnostic') or
                (path.name == 'visionworkshop-offline-network.yml'
                 and jobName == 'windows-outbound-block') or
                (path.name == 'visionworkshop-disconnected-guest.yml'
                 and jobName == 'windows-disconnected-guest')):
            self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'read'})
          else:
            self.assertEqual(job.get('permissions', data['permissions']), {'contents': 'read'})

  def test_candidate_reuse_read_token_is_scoped_to_explicit_artifact_download(self) -> None:
    data, events = loadWorkflow('visionworkshop-modular-candidate.yml')
    job = data['jobs']['windows-modular-candidate']
    self.assertNotIn('GH_TOKEN', data.get('env', {}))
    self.assertNotIn('GH_TOKEN', job.get('env', {}))
    downloads = [step for step in getSteps(data) if 'GH_TOKEN' in step.get('env', {})]
    self.assertEqual(len(downloads), 1)
    self.assertEqual(downloads[0]['env']['GH_TOKEN'], '${{ github.token }}')
    self.assertEqual(downloads[0]['if'], "${{ env.REUSE_RUN_ID != '' }}")
    self.assertIn('packager/scripts/prepare_vision_train_module_reuse.py', downloads[0]['run'])
    self.assertEqual(events['workflow_dispatch']['inputs']['reuse_run_id']['default'], '')
    self.assertEqual(events['push']['paths'], [
      'ci/visionworkshop-modular-candidate.json',
      '.github/workflows/visionworkshop-modular-candidate.yml',
    ])

  def test_outbound_diagnostic_only_exposes_read_token_during_preparation(self) -> None:
    data, events = loadWorkflow('visionworkshop-offline-network.yml')
    job = data['jobs']['windows-outbound-block']
    self.assertEqual(job['runs-on'], 'windows-latest')
    self.assertEqual(set(events), {'push'})
    self.assertEqual(events['push']['branches'], ['test/visionworkshop-modular-loader'])
    self.assertNotIn('GH_TOKEN', data.get('env', {}))
    self.assertNotIn('GH_TOKEN', job.get('env', {}))
    downloads = [step for step in getSteps(data) if 'GH_TOKEN' in step.get('env', {})]
    self.assertEqual(len(downloads), 1)
    self.assertEqual(downloads[0]['env']['GH_TOKEN'], '${{ github.token }}')
    self.assertIn('-m scripts.verify_vision_train_offline_network prepare ', downloads[0]['run'])

  def test_disconnected_guest_uses_a_hosted_job_and_stages_before_the_network_cut(self) -> None:
    data, events = loadWorkflow('visionworkshop-disconnected-guest.yml')
    job = data['jobs']['windows-disconnected-guest']
    self.assertEqual(job['runs-on'], 'windows-latest')
    self.assertEqual(set(events), {'push'})
    self.assertEqual(events['push']['branches'], ['test/visionworkshop-modular-loader'])
    self.assertNotIn('GH_TOKEN', data.get('env', {}))
    self.assertNotIn('GH_TOKEN', job.get('env', {}))
    steps = getSteps(data)
    downloads = [i for i, step in enumerate(steps) if 'GH_TOKEN' in step.get('env', {})]
    cut = [i for i, step in enumerate(steps) if './scripts/verify_vision_train_disconnected.ps1' in step.get('run', '')]
    self.assertEqual((len(downloads), len(cut)), (1, 1))
    self.assertLess(downloads[0], cut[0])
    self.assertEqual(steps[downloads[0]]['env']['GH_TOKEN'], '${{ github.token }}')
    self.assertIn('-m scripts.verify_vision_train_disconnected stage ', steps[downloads[0]]['run'])

  def test_candidate_projections_are_read_only_always_and_do_not_skip_the_product_gate(self) -> None:
    data, _ = loadWorkflow('visionworkshop-modular-candidate.yml')
    steps = getSteps(data)
    actual = [i for i, step in enumerate(steps)
              if 'packager/scripts/verify_vision_train_modular_product.py' in step.get('run', '')]
    logging = [i for i, step in enumerate(steps)
               if 'packager/scripts/report_vision_train_modular_candidate.py' in step.get('run', '')]
    uploads = [i for i, step in enumerate(steps)
               if step.get('name') == 'Upload candidate evidence independently']
    self.assertEqual((len(actual), len(logging), len(uploads)), (1, 1, 1))
    self.assertLess(actual[0], logging[0])
    self.assertLess(logging[0], uploads[0])
    self.assertEqual(steps[logging[0]]['if'], 'always()')
    self.assertNotIn('GH_TOKEN', steps[logging[0]].get('env', {}))
    self.assertIn('python -I -S -B', steps[logging[0]]['run'])
    self.assertNotIn('continue-on-error', steps[actual[0]])
    self.assertNotIn('continue-on-error', steps[logging[0]])
    guards = next(step for step in steps
                  if step.get('name') == 'Verify builder and native Windows transaction contracts')
    self.assertIn('test_vision_train_candidate_reports.py', guards['run'])

  def test_core_exit_diagnostic_only_downloads_reviewed_core_without_rebuilding(self) -> None:
    data, events = loadWorkflow('visionworkshop-core-diagnostic.yml')
    job = data['jobs']['windows-core-exit-diagnostic']
    self.assertEqual(events['push']['paths'], ['ci/visionworkshop-core-diagnostic.json'])
    self.assertEqual(events['push']['branches'], ['test/visionworkshop-modular-loader'])
    self.assertNotIn('GH_TOKEN', data.get('env', {}))
    self.assertNotIn('GH_TOKEN', job.get('env', {}))
    tokens = [step for step in getSteps(data) if 'GH_TOKEN' in step.get('env', {})]
    self.assertEqual(len(tokens), 1)
    self.assertEqual(tokens[0]['env']['GH_TOKEN'], '${{ github.token }}')
    self.assertIn('diagnose_vision_train_core.py prepare', tokens[0]['run'])
    text = (WORKFLOWS / 'visionworkshop-core-diagnostic.yml').read_text(encoding='utf-8')
    for forbidden in ('build_vision_train_modular.py', 'pip install', 'submodules:', 'source_ref'):
      self.assertNotIn(forbidden, text)
    self.assertIn('diagnose_vision_train_core.py run', text)
    steps = getSteps(data)
    fixtures = [index for index, step in enumerate(steps)
                if '--fixture-output native-debug-fixtures' in step.get('run', '')]
    downloads = [index for index, step in enumerate(steps)
                 if 'diagnose_vision_train_core.py prepare' in step.get('run', '')]
    actual = [index for index, step in enumerate(steps)
              if 'diagnose_vision_train_core.py run' in step.get('run', '')]
    self.assertEqual(len(fixtures), 1)
    self.assertLess(fixtures[0], downloads[0])
    self.assertLess(downloads[0], actual[0])
    self.assertIn('test_vision_train_native_debug.py', text)
    self.assertIn('native-debug-fixtures/*/reports/**', text)
    logging = [step for step in steps if 'report_vision_train_core_diagnostic.py --diagnostic' in step.get('run', '')]
    self.assertEqual(len(logging), 1)
    self.assertEqual(logging[0]['if'], 'always()')
    self.assertNotIn('GH_TOKEN', logging[0].get('env', {}))
    self.assertIn('test_vision_train_diagnostic_reports.py', text)

  def test_release_checkouts_use_explicit_refs_without_persisting_tokens(self) -> None:
    for name in PRODUCTION:
      with self.subTest(workflow=name):
        data, _ = loadWorkflow(name)
        steps = getSteps(data)
        revision = next(step for step in steps if step.get('id') == 'revision')
        self.assertEqual(revision['env']['REQUESTED_REF'], '${{ inputs.packager_ref }}')
        self.assertEqual(revision['env']['CALLER_SHA'], '${{ github.sha }}')
        self.assertIn('Cross-repository callers must supply packager_ref explicitly',
                      revision['run'])
        checkouts = [step['with'] for step in steps
                     if step.get('uses', '').startswith('actions/checkout@')]
        self.assertEqual(checkouts[0]['ref'], '${{ steps.revision.outputs.ref }}')
        self.assertEqual(checkouts[1]['ref'], '${{ inputs.source_ref }}')
        self.assertTrue(all(step['persist-credentials'] is False for step in checkouts))

  def test_reusable_workflow_does_not_require_permission_escalation(self) -> None:
    entry, _ = loadWorkflow('release-windows.yml')
    portable, _ = loadWorkflow('visionworkshop-portable.yml')
    caller = entry['jobs']['vision_train']
    self.assertEqual(caller['uses'], './.github/workflows/visionworkshop-portable.yml')
    self.assertEqual(caller['permissions'], portable['permissions'])
    self.assertEqual(caller['with']['packager_ref'], '${{ inputs.packager_ref }}')
    self.assertEqual(caller['with']['source_ref'], '${{ inputs.source_ref }}')

  def test_user_inputs_never_enter_inline_shell_expressions(self) -> None:
    for path in WORKFLOWS.glob('*.yml'):
      with self.subTest(workflow=path.name):
        data, _ = loadWorkflow(path.name)
        for step in getSteps(data):
          self.assertNotIn('${{ inputs.', step.get('run', ''))
          self.assertNotIn('Invoke-Expression', step.get('run', ''))

  def test_diagnostics_are_manual_read_only_and_never_publish(self) -> None:
    for name in DIAGNOSTICS:
      with self.subTest(workflow=name):
        data, events = loadWorkflow(name)
        self.assertEqual(set(events), {'workflow_dispatch'})
        text = (WORKFLOWS / name).read_text(encoding='utf-8')
        for forbidden in ('RELEASE_REPO_TOKEN', 'gh release', 'git push',
                          'actions_release.py', 'publish-local-release', 'portable_release.py'):
          self.assertNotIn(forbidden, text)
        for step in getSteps(data):
          if step.get('uses', '').startswith('actions/checkout@'):
            self.assertTrue(step['with']['ref'])
            self.assertIs(step['with']['persist-credentials'], False)
          if step.get('uses', '').startswith('actions/upload-artifact@'):
            self.assertNotIn('.zip', step['with']['path'])
            self.assertNotIn('build-record', step['with']['path'])

  def test_source_fixture_checks_are_preserved_as_optional_diagnostics(self) -> None:
    data, events = loadWorkflow('diagnose-updater-fixtures.yml')
    self.assertIs(events['workflow_dispatch']['inputs']['source_ref']['required'], True)
    steps = getSteps(data)
    commands = '\n'.join(step.get('run', '') for step in steps)
    self.assertIn('python -m unittest discover -s tests -v', commands)
    self.assertIn('test_update_v3_runtime.py', commands)
    self.assertIn('scripts/verify_update_windows.py', commands)
    self.assertIn('git -C source diff --exit-code HEAD --', commands)
    self.assertNotIn('vision_train_runtime.py install', commands)

  def test_ci_covers_all_merged_workflows_and_safety_tests(self) -> None:
    data, events = loadWorkflow('visionworkshop-tests.yml')
    self.assertEqual(events['push']['branches'], ['master'])
    self.assertIn('.github/workflows/*.yml', events['pull_request']['paths'])
    self.assertIn('tests/**', events['pull_request']['paths'])
    commands = '\n'.join(step.get('run', '') for step in getSteps(data))
    self.assertIn('python -m unittest discover -s tests -v', commands)


if __name__ == '__main__':
  unittest.main()
