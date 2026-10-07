import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / 'scripts' / 'publish-local-release-legacy.ps1'


class MasterReleaseProvenanceTests(unittest.TestCase):
  def testGuardsAreScopedAndBuildOnlyIsExempt(self):
    text = PUBLISHER.read_text(encoding='utf-8')
    self.assertIn("$guardMasterPublication = $Target -in @('emo-master', 'emo-master-runtime') -and -not $BuildOnly", text)
    self.assertLess(text.index('if ($BuildOnly) {'), text.index('  $releaseExists = Test-MasterReleaseExists'))

  def testMasterUploadCannotClobberAndChecksAllAssetsFirst(self):
    text = PUBLISHER.read_text(encoding='utf-8')
    upload = text[text.index('  if ($releaseExists) {'):]
    self.assertIn('$uploadOptions = @()', upload)
    self.assertIn('Assert-MasterReleaseAssetsAvailable', upload)
    self.assertLess(upload.index('Assert-MasterReleaseAssetsAvailable'), upload.index('gh release upload'))
    self.assertIn('--repo $resolvedReleaseRepo @uploadOptions', upload)

  def testCreateTargetsBuiltCommit(self):
    text = PUBLISHER.read_text(encoding='utf-8')
    self.assertIn("$createOptions = @('--target', $sourceCommit)", text)
    self.assertIn("if ($masterTagExists) { $createOptions += '--verify-tag' }", text)
    self.assertIn('gh release create $ReleaseTag @releaseAssetPaths @createOptions', text)

  def testProvenanceRecheckedAfterBuild(self):
    text = PUBLISHER.read_text(encoding='utf-8')
    final = text[text.index('  if ($BuildOnly) {'):]
    self.assertIn('Assert-MasterPublicationSource', final)
    self.assertIn('Assert-MasterReleaseTag', final)

  @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell'),
                       'PowerShell unavailable; run focused harness on Windows')
  def testMockedPowerShellGuards(self):
    shell = shutil.which('pwsh') or shutil.which('powershell')
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File',
                             str(ROOT / 'tests/powershell/test_master_release_provenance.ps1')],
                            text=True, capture_output=True, check=False)
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
  unittest.main()
