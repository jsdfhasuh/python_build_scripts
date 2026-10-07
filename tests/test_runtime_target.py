import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class RuntimeTargetTests(unittest.TestCase):
  def testIndependentRuntimeKeepsDesignerTargetUnchanged(self):
    runtime = json.loads((ROOT / 'configs/emo-master-runtime.json').read_text())
    designer = json.loads((ROOT / 'configs/emo-master.json').read_text())
    self.assertEqual(runtime['entry'], '${SOURCE_ROOT}/scripts/run_operator.py')
    self.assertEqual(runtime['name'], 'EmoMasterRuntime')
    self.assertFalse(runtime['onefile'])
    self.assertFalse(runtime['console'])
    self.assertFalse(runtime['installer']['enabled'])
    self.assertIn('emo_master.apps.designer', runtime['excludes'])
    self.assertTrue(all('/designer/' not in value for value in runtime['add_data']))
    self.assertEqual(runtime['ci_extra_packages'], designer['ci_extra_packages'])
    self.assertEqual(runtime['collect_binaries'], designer['collect_binaries'])
    self.assertEqual(designer['name'], 'EmoMaster')
    self.assertTrue(designer['installer']['enabled'])
    self.assertEqual(runtime['verification_script'], '${SOURCE_ROOT}/scripts/verify_runtime_package.ps1')
    self.assertEqual(runtime['archive_compression'], 'deflate')

  def testWorkflowRuntimeAutoBuildsOnly(self):
    text = (ROOT / '.github/workflows/release-windows.yml').read_text()
    workflow = yaml.safe_load(text)
    build = next(step for step in workflow['jobs']['build']['steps']
                 if step['name'] == 'Build Windows artifacts')['run']
    self.assertIn("$env:TARGET_INPUT -eq 'emo-master-runtime'", build)
    self.assertIn("$env:PUBLISH_RELEASE_INPUT -ne 'true'", build)
    self.assertIn("$publishArgs['BuildOnly'] = $true", build)

  def testFrozenGatePrecedesArchiveAndPublicationAndReusesProvenance(self):
    text = (ROOT / 'scripts/publish-local-release-legacy.ps1').read_text()
    self.assertIn("$Target -in @('emo-master', 'emo-master-runtime') -and -not $BuildOnly", text)
    gate = text.index('Frozen Runtime verification failed')
    archive = text.index('$archiveCompression = Compress-ReleaseArchive')
    self.assertLess(gate, archive)
    self.assertIn("$LASTEXITCODE = 0\n    & $verificationScript", text)
    self.assertIn("-ReportPath (Join-Path $artifactDirectory 'runtime-self-test.json')", text)
    self.assertIn('-PreferDeflate:$preferDeflate', text)

  def testCloudRuntimeRecordsBothCheckoutsAndUploadsFailures(self):
    workflow = yaml.safe_load((ROOT / '.github/workflows/release-windows.yml').read_text())
    steps = workflow['jobs']['build']['steps']
    identity = next(step for step in steps if step.get('id') == 'identity')
    self.assertEqual(identity['if'], "inputs.target == 'emo-master-runtime'")
    self.assertIn('git -C source rev-parse HEAD', identity['run'])
    self.assertIn('git -C packager rev-parse HEAD', identity['run'])
    self.assertIn('runtime-build.json', identity['run'])
    for name in ('Runtime source regression', 'Verify Runtime archive and native cycles'):
      step = next(step for step in steps if step.get('name') == name)
      self.assertTrue(step['if'].startswith("inputs.target == 'emo-master-runtime'"))
    verify = next(step for step in steps if step.get('name') == 'Verify Runtime archive and native cycles')
    self.assertEqual(verify['env']['SOURCE_SHA'], '${{ steps.identity.outputs.source_sha }}')
    self.assertEqual(verify['env']['PACKAGER_SHA'], '${{ steps.identity.outputs.packager_sha }}')
    upload = next(step for step in steps if step.get('name') == 'Upload Windows artifacts')
    self.assertEqual(upload['if'], '${{ always() }}')
    self.assertLess(steps.index(identity), steps.index(verify))
    self.assertLess(next(i for i, step in enumerate(steps) if step.get('id') == 'artifact'),
                    next(i for i, step in enumerate(steps) if step.get('name') == 'Build Windows artifacts'))

  def testLocalRuntimeRequiresExplicitPublicationWithoutChangingOtherTargets(self):
    publisher = (ROOT / 'scripts/publish-local-release-legacy.ps1').read_text()
    self.assertIn("if ($Target -eq 'emo-master-runtime' -and -not $Publish) { $BuildOnly = $true }", publisher)
    self.assertIn("if ($Publish -and $BuildOnly) { throw 'Publish and BuildOnly cannot be combined' }", publisher)
    wrapper = (ROOT / 'scripts/publish-local-release.ps1').read_text()
    self.assertIn("if ($Target -eq 'emo-master-runtime' -and $Publish) { $legacyArguments['Publish'] = $true }", wrapper)
    workflow = yaml.safe_load((ROOT / '.github/workflows/release-windows.yml').read_text())
    build = next(step for step in workflow['jobs']['build']['steps']
                 if step.get('name') == 'Build Windows artifacts')['run']
    self.assertIn("$env:TARGET_INPUT -eq 'emo-master-runtime' -and $env:PUBLISH_RELEASE_INPUT -eq 'true'", build)
    self.assertIn("$publishArgs['Publish'] = $true", build)


if __name__ == '__main__':
  unittest.main()
