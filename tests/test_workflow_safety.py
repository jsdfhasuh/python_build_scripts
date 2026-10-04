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
          if path.name == 'release-windows.yml' and jobName == 'build':
            self.assertEqual(job['permissions'], {'contents': 'write'})
          else:
            self.assertEqual(job.get('permissions', data['permissions']), {'contents': 'read'})

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
