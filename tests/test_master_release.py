import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from build_config import BuildConfigError
import master_release as master


class MasterReleaseTests(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.request = dict(release_tag='v0.6.2', source_commit='a' * 40,
                        packager_commit='b' * 40, publish=False, title='Emo Master v0.6.2')

  def writeObject(self, path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')

  def writeArtifacts(self):
    for target in master.TARGETS:
      config = master.loadConfig(target)
      folder = self.root / target
      folder.mkdir(exist_ok=True)
      manifest = dict(source_repo=master.REPOSITORY, source_commit='a' * 40, version='0.6.2',
                      assets={})
      for kind, template in (('portable', config['release_asset_name']),
                              ('setup', config['installer']['release_asset_name'])):
        name = template.replace('${RELEASE_TAG}', 'v0.6.2')
        path = folder / name
        path.write_bytes(name.encode('utf-8'))
        record = dict(name=name, sha256=master.fileHash(path),
                      url=f'https://github.com/{master.REPOSITORY}/releases/download/v0.6.2/{name}')
        manifest['assets'][kind] = record
        if kind == 'portable':
          manifest.update(sha256=record['sha256'], url=record['url'])
      self.writeObject(folder / 'manifest.json', manifest)
      (folder / 'private-build.log').write_text('not public')
    runtime = self.root / 'emo-master-runtime'
    identity = dict(source_commit='a' * 40, packager_commit='b' * 40, publish_requested=False)
    self.writeObject(runtime / 'runtime-build.json', identity)
    self.writeObject(runtime / 'archive-check/validation.json', dict(
      identity, status='PASS', archiveAcceptance='PASS', nativeAcceptance='PASS',
      archiveSha256=master.fileHash(runtime / 'emo-master-runtime-windows-v0.6.2.zip'),
    ))

  def testOnlySixPublicFilesAreStagedWithSeparateManifests(self):
    self.writeArtifacts()
    records = master.stageAssets(master.collectAssets(self.root, self.request), self.root / 'public')
    self.assertEqual(len(records), 6)
    self.assertIn('manifest.json', records)
    self.assertIn('runtime-manifest.json', records)
    self.assertEqual(set(records), {path.name for path in (self.root / 'public').iterdir()})
    self.assertNotIn('private-build.log', records)

  def testMissingInstallerChangedZipAndWrongSourceAreRejected(self):
    for mutation in ('missing', 'changed', 'source'):
      with self.subTest(mutation=mutation):
        self.writeArtifacts()
        folder = self.root / 'emo-master'
        if mutation == 'missing':
          (folder / 'emo-master-setup-v0.6.2.exe').unlink()
        elif mutation == 'changed':
          (folder / 'emo-master-windows-v0.6.2.zip').write_bytes(b'changed')
        else:
          manifest = master.readObject(folder / 'manifest.json')
          manifest['source_commit'] = 'c' * 40
          self.writeObject(folder / 'manifest.json', manifest)
        with self.assertRaises(BuildConfigError):
          master.collectAssets(self.root, self.request)

  def testFailedOrMismatchedRuntimeEvidenceCannotPublish(self):
    for key, value in (('status', 'FAIL'), ('nativeAcceptance', 'NOT_RUN'),
                       ('packager_commit', 'c' * 40), ('archiveSha256', '0' * 64)):
      with self.subTest(key=key):
        self.writeArtifacts()
        path = self.root / 'emo-master-runtime/archive-check/validation.json'
        evidence = master.readObject(path)
        evidence[key] = value
        self.writeObject(path, evidence)
        with self.assertRaises(BuildConfigError):
          master.collectAssets(self.root, self.request)

  def testTagMismatchAndAnnotatedTags(self):
    tag = dict(ref='refs/tags/v0.6.2', object=dict(type='tag', sha='c' * 40))
    peeled = dict(object=dict(type='commit', sha='a' * 40))
    with patch.object(master.content, 'runTool', side_effect=[json.dumps([tag]), json.dumps(peeled)]):
      master.checkTag('v0.6.2', 'a' * 40)
    with patch.object(master.content, 'runTool', side_effect=[json.dumps([tag]), json.dumps(peeled)]):
      with self.assertRaisesRegex(BuildConfigError, 'choose a new version'):
        master.checkTag('v0.6.2', 'b' * 40)
    with patch.object(master.content, 'runTool', return_value='[]'):
      master.checkTag('v0.6.2', 'a' * 40)
      with self.assertRaises(BuildConfigError):
        master.checkTag('v0.6.2', 'a' * 40, required=True)

  def testPreparationReusesTrainingReleaseNotesAndDefaultsToBuildOnly(self):
    package = self.root / 'src/emo_master'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('from .app_version import APP_VERSION as __version__\n')
    (package / 'app_version.py').write_text('APP_VERSION = "0.6.2"\n')
    with patch.object(master.content, 'resolveCommit', side_effect=['a' * 40, 'b' * 40]), \
         patch.object(master.content, 'findPreviousSource', return_value=('v0.6.1', 'c' * 40)), \
         patch.object(master.content, 'getChanges', return_value=['abcdef0 fix: example']), \
         patch.object(master, 'checkPublication') as publish, \
         patch.dict(master.os.environ, {'GITHUB_OUTPUT': ''}):
      request = master.prepareRequest({}, self.root, self.root / 'state')
    publish.assert_not_called()
    self.assertFalse(request['publish'])
    self.assertEqual(request['release_tag'], 'v0.6.2')
    body = (self.root / 'state/release-notes.md').read_text(encoding='utf-8')
    for section in ('本次更新', '修复与改进', '下载与升级', '完整变更', '全部提交'):
      self.assertIn(section, body)
    self.assertIn('emo-master-runtime-setup-v0.6.2.exe', body)
    self.assertIn('现场模型和长期运行验收未执行', body)
    self.assertEqual(request['body_sha256'], master.content.bodyHash(body))
    with self.assertRaisesRegex(BuildConfigError, 'does not match application version'):
      master.prepareRequest({'release_tag': 'v0.6.3'}, self.root, self.root / 'other')

  def testPublicationVerifiesDraftDigestsBeforeMakingPublic(self):
    records = {'setup.exe': dict(size=4, digest='sha256:' + 'a' * 64)}
    draft = dict(id=42, draft=True, tag_name='v0.6.2')
    uploaded = dict(draft, assets=[dict(name='setup.exe', state='uploaded', **records['setup.exe'])])
    published = dict(id=42, draft=False, html_url='https://example.test/release')
    payloads = []
    def apiCall(arguments):
      if '--input' in arguments:
        payloads.append(master.readObject(Path(arguments[-1])))
        return json.dumps(draft)
      return json.dumps(published)
    with patch.object(master, 'checkPublication'), patch.object(master, 'checkTag'), \
         patch.object(master.content, 'getRelease', return_value=uploaded), \
         patch.object(master.content, 'runTool', side_effect=apiCall) as run, \
         patch.object(master.subprocess, 'run') as upload:
      url = master.publishAssets(self.request, 'Notes', self.root, records)
    self.assertEqual(url, published['html_url'])
    self.assertIs(payloads[0]['draft'], True)
    self.assertEqual(payloads[0]['target_commitish'], self.request['source_commit'])
    self.assertIn('draft=false', run.call_args_list[1].args[0])
    self.assertNotIn('--clobber', upload.call_args.args[0])
    changed = copy.deepcopy(uploaded)
    changed['assets'][0]['digest'] = 'wrong'
    with patch.object(master, 'checkPublication'), patch.object(master, 'checkTag'), \
         patch.object(master.content, 'getRelease', return_value=changed), \
         patch.object(master.content, 'runTool', return_value=json.dumps(draft)) as run, \
         patch.object(master.subprocess, 'run'):
      with self.assertRaisesRegex(BuildConfigError, 'digest mismatch'):
        master.publishAssets(self.request, 'Notes', self.root, records)
    self.assertEqual(run.call_count, 1)

  def testBundleBuildsPinnedTargetsWithoutIndependentPublication(self):
    workflow = yaml.safe_load((master.ROOT / '.github/workflows/release-emo-master.yml').read_text())
    events = workflow.get('on', workflow.get(True))
    for event in ('workflow_dispatch', 'workflow_call'):
      self.assertIs(events[event]['inputs']['publish_release']['default'], False)
    package = workflow['jobs']['package']
    self.assertEqual(package['strategy']['matrix']['target'], list(master.TARGETS))
    self.assertIs(package['with']['publish_release'], False)
    self.assertEqual(package['with']['source_ref'], '${{ needs.prepare.outputs.source_sha }}')
    self.assertEqual(package['with']['packager_ref'], '${{ needs.prepare.outputs.packager_sha }}')
    self.assertEqual(workflow['jobs']['release']['needs'], ['prepare', 'package'])
    steps = workflow['jobs']['release']['steps']
    iconGate = next(step for step in steps if 'custom icons' in step.get('name', ''))
    publisher = next(step for step in steps if 'Verify six public files' in step.get('name', ''))
    self.assertIn('verify_windows_package.ps1', iconGate['run'])
    self.assertLess(steps.index(iconGate), steps.index(publisher))

  @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell'), 'PowerShell unavailable')
  def testRuntimePublishSwitchReachesLegacyPublisher(self):
    wrapper = self.root / 'publish-local-release.ps1'
    shutil.copyfile(master.ROOT / 'scripts/publish-local-release.ps1', wrapper)
    (self.root / 'publish-local-release-legacy.ps1').write_text(
      "param([string]$Target, [string]$ReleaseTag, [switch]$Publish)\n"
      "if ($Target -ne 'emo-master-runtime' -or -not $Publish) { throw 'Wrong arguments' }\n"
      "Write-Output 'legacy runtime publish selected'\n", encoding='utf-8')
    result = subprocess.run([
      shutil.which('pwsh') or shutil.which('powershell'), '-NoProfile', '-NonInteractive',
      '-File', str(wrapper), '-Target', 'emo-master-runtime', '-ReleaseTag', 'v0.6.2', '-Publish',
    ], capture_output=True, text=True, check=False, timeout=30)
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertIn('legacy runtime publish selected', result.stdout)


if __name__ == '__main__':
  unittest.main()
