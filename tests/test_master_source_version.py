import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.release_wizard_common import getSourceVersion


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('pwsh') or shutil.which('powershell')


class MasterSourceVersionTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.source = Path(temporary.name)
    self.package = self.source / 'src/emo_master'
    self.package.mkdir(parents=True)

  def writeVersion(self, *, legacy=False, value='0.6.2'):
    if legacy:
      init = f'__version__ = "{value}"\n'
    else:
      init = 'from .app_version import APP_VERSION as __version__\n'
      (self.package / 'app_version.py').write_text(
        f'APP_VERSION = "{value}"\nraise RuntimeError("must not execute")\n',
        encoding='utf-8',
      )
    (self.package / '__init__.py').write_text(
      init + 'raise RuntimeError("must not execute")\n', encoding='utf-8',
    )

  def testBothTargetsReadSingleVersionWithoutExecutingApplication(self):
    for value in ('0.6.2', '0.6.3'):
      self.writeVersion(value=value)
      for target in ('emo-master', 'emo-master-runtime'):
        with self.subTest(value=value, target=target):
          config = json.loads((ROOT / f'configs/{target}.json').read_text(encoding='utf-8'))
          self.assertEqual(getSourceVersion(config, self.source), value)

  def testHistoricalLiteralVersionStillWorks(self):
    self.writeVersion(legacy=True)
    config = {'source_version_file': '${SOURCE_ROOT}/src/emo_master/__init__.py'}
    self.assertEqual(getSourceVersion(config, self.source), '0.6.2')

  def testMissingOrComputedVersionIsNotAccepted(self):
    self.writeVersion()
    config = {'source_version_file': 'src/emo_master/__init__.py'}
    for source in ('# APP_VERSION = "0.6.2"\n', 'APP_VERSION = str(123)\n'):
      with self.subTest(source=source):
        (self.package / 'app_version.py').write_text(source, encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, 'APP_VERSION'):
          getSourceVersion(config, self.source)

  @unittest.skipUnless(SHELL, 'PowerShell is required for the publisher version check')
  def testPublisherAcceptsMatchingVersionAndRejectsMismatch(self):
    command = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:VERSION_TEST_PUBLISHER, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$function = $ast.Find({ param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
  $node.Name -eq 'Assert-SourceVersionMatchesTag'
}, $true)
$checkVersion = $function.Body.GetScriptBlock()
$config = [pscustomobject]@{source_version_file = 'src/emo_master/__init__.py'}
& $checkVersion $config $env:VERSION_TEST_SOURCE '0.6.2'
try {
  & $checkVersion $config $env:VERSION_TEST_SOURCE '0.6.3'
  throw 'Mismatched version was accepted'
} catch {
  if ($_.Exception.Message -notlike '*does not match application version 0.6.2') { throw }
}
Write-Output 'Version checks passed'
'''
    environment = dict(os.environ)
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment['PATH']
    environment['VERSION_TEST_SOURCE'] = str(self.source)
    environment['VERSION_TEST_PUBLISHER'] = str(ROOT / 'scripts/publish-local-release-legacy.ps1')
    for legacy in (False, True):
      with self.subTest(legacy=legacy):
        self.writeVersion(legacy=legacy)
        result = subprocess.run(
          [SHELL, '-NoProfile', '-NonInteractive', '-Command', command],
          env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
  unittest.main()
