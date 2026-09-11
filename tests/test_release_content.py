import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import portable_release
import release_content as content
import test_portable_release as fixtures
from build_config import BuildConfigError


class ContentTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    (self.root / 'fixture.txt').write_text('one')
    fixtures.initializeGit(self.root)
    self.base = fixtures.git(self.root, 'rev-parse', 'HEAD')
    (self.root / 'fixture.txt').write_text('two')
    fixtures.git(self.root, 'commit', '-am', 'fix: correct training')
    self.head = fixtures.git(self.root, 'rev-parse', 'HEAD')
    (self.root / 'fixture.txt').write_text('three')
    fixtures.git(self.root, 'commit', '-am', 'feat: later work not released')

  def generate(self, **kwargs) -> str:
    return content.generateBody(title='VisionWorkshop v1.0.20', notes='Release summary',
                                programName='VisionWorkshop', sourceRepo='tests/source',
                                sourceRoot=self.root, head=self.head, **kwargs)

  def test_generated_body_uses_pinned_head_and_explicit_range(self) -> None:
    body = self.generate(base=self.base, assetName='VisionWorkshop-v1.0.20.zip',
                         legacyNames=('emo-vision-train',))
    self.assertIn('fix: correct training', body)
    self.assertNotIn('later work not released', body)
    self.assertNotIn('fixture\n', body)
    self.assertIn('## 修复与改进', body)
    self.assertIn('emo-vision-train.exe', body)
    self.assertIn(f'{self.base}...{self.head}', body)

  def test_no_implicit_recent_commit_fallback(self) -> None:
    with patch.object(content, 'runTool') as run:
      body = self.generate()
    run.assert_not_called()
    self.assertIn('尚未指定更新范围', body)

  def test_all_history_is_explicit_and_still_pins_head(self) -> None:
    body = self.generate(allHistory=True)
    self.assertIn('fixture', body)
    self.assertNotIn('later work not released', body)

  def test_base_must_be_ancestor_of_published_head(self) -> None:
    with self.assertRaises(BuildConfigError):
      content.resolveBase(self.root, 'HEAD', self.head)
    self.assertEqual(content.resolveBase(self.root, self.base, self.head), self.base)

  def test_published_source_must_match_repository_and_full_commit(self) -> None:
    manifest = {'source_repo': 'tests/source', 'source_commit': self.head}
    self.assertEqual(content.getPublishedHead(manifest, 'tests/source', self.root), self.head)
    for invalid in ({**manifest, 'source_repo': 'other/source'},
                    {**manifest, 'source_commit': 'HEAD'}):
      with self.subTest(invalid=invalid), self.assertRaises(BuildConfigError):
        content.getPublishedHead(invalid, 'tests/source', self.root)

  def test_previous_release_uses_selected_versions_predecessor(self) -> None:
    releases = [{'tag_name': 'v1.0.21'}, {'tag_name': 'v1.0.20'}, {'tag_name': 'v1.0.19'}]
    manifest = {'source_repo': 'tests/source', 'source_commit': self.base}
    with patch.object(content, 'listReleases', return_value=releases), \
         patch.object(content, 'readManifest', return_value=manifest) as read:
      tag, base = content.findPreviousSource('tests/releases', 'v1.0.20',
                                             'tests/source', self.root, self.head)
    self.assertEqual((tag, base), ('v1.0.19', self.base))
    self.assertEqual(read.call_args.args[1]['tag_name'], 'v1.0.19')


class BodyTests(unittest.TestCase):
  def test_utf8_bom_and_line_endings_are_normalized_and_hashed(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'body.md'
      path.write_bytes(b'\xef\xbb\xbf# Notes\r\n')
      body = content.readBody(path)
      self.assertEqual(body, '# Notes\n')
      self.assertEqual(content.readBody(path, content.bodyHash(body)), body)
      path.write_text('# changed', encoding='utf-8')
      with self.assertRaisesRegex(BuildConfigError, '确认后变化'):
        content.readBody(path, content.bodyHash(body))

  def test_empty_non_utf8_missing_directory_and_large_bodies_fail(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      for data in (b'', b'  ', b'\xff\xfe', b'hello\0world', b'x' * 120001):
        path = root / 'body.md'
        path.write_bytes(data)
        with self.subTest(data=data[:10]), self.assertRaises(BuildConfigError):
          content.readBody(path)
      for path in (root, root / 'missing.md'):
        with self.assertRaises(BuildConfigError):
          content.readBody(path)

  def test_title_validation(self) -> None:
    self.assertEqual(content.validateTitle(' VisionWorkshop v1.0.20 '), 'VisionWorkshop v1.0.20')
    for title in ('', 'x' * 201, 'bad\ntitle'):
      with self.assertRaises(BuildConfigError):
        content.validateTitle(title)


class ReleaseApiTests(unittest.TestCase):
  def setUp(self) -> None:
    self.release = {'id': 10, 'tag_name': 'v1.0.20', 'name': 'Existing title', 'body': '# old\n',
                    'updated_at': '2026-01-01T00:00:00Z', 'assets': [
                      {'id': 20, 'name': 'manifest.json', 'size': 300, 'download_count': 2},
                      {'id': 21, 'name': 'app.zip', 'size': 5000},
                    ]}

  def test_existing_release_is_rejected_before_build(self) -> None:
    with patch.object(content, 'checkRepository'), \
         patch.object(content, 'getRelease', return_value=self.release):
      with self.assertRaisesRegex(BuildConfigError, '已存在'):
        content.requireNewRelease('tests/releases', 'v1.0.20')

  def test_inaccessible_repository_is_not_a_free_tag(self) -> None:
    with patch.object(content, 'checkRepository', side_effect=BuildConfigError('HTTP 404')), \
         patch.object(content, 'getRelease') as get:
      with self.assertRaises(BuildConfigError):
        content.requireNewRelease('tests/releases', 'v1.0.20')
    get.assert_not_called()

  def test_network_and_auth_errors_are_not_treated_as_missing_release(self) -> None:
    for message in ('HTTP 401', 'timeout', 'HTTP 403'):
      result = subprocess.CompletedProcess([], 1, '', message)
      with patch.object(content.subprocess, 'run', return_value=result), \
           self.assertRaises(BuildConfigError):
        content.getRelease('tests/releases', 'v1.0.20')
    with patch.object(content.subprocess, 'run',
                      return_value=subprocess.CompletedProcess([], 1, '', 'gh: Not Found (HTTP 404)')):
      self.assertIsNone(content.getRelease('tests/releases', 'v1.0.20'))

  def test_download_counts_do_not_invalidate_body_preview(self) -> None:
    changed = copy.deepcopy(self.release)
    changed['assets'][0]['download_count'] += 1
    self.assertEqual(content.releaseFingerprint(changed), content.releaseFingerprint(self.release))
    changed['assets'][0]['size'] += 1
    self.assertNotEqual(content.releaseFingerprint(changed), content.releaseFingerprint(self.release))

  def test_patch_payload_only_contains_body(self) -> None:
    def run(arguments):
      self.assertEqual(arguments[:4], ['gh', 'api', '--method', 'PATCH'])
      self.assertIn('repos/tests/releases/releases/10', arguments)
      payload = json.loads(Path(arguments[-1]).read_text(encoding='utf-8'))
      self.assertEqual(payload, {'body': '# new\n'})
      return json.dumps({**self.release, 'body': '# new\n'})
    with patch.object(content, 'getRelease', return_value=self.release), \
         patch.object(content, 'runTool', side_effect=run) as runMock:
      content.updateBody('tests/releases', 'v1.0.20', '# new\n',
                         content.releaseFingerprint(self.release))
    runMock.assert_called_once()

  def test_concurrent_release_edit_is_not_overwritten(self) -> None:
    changed = {**self.release, 'body': '# changed remotely'}
    with patch.object(content, 'getRelease', return_value=changed), \
         patch.object(content, 'runTool') as run:
      with self.assertRaisesRegex(BuildConfigError, '预览后发生变化'):
        content.updateBody('tests/releases', 'v1.0.20', '# new',
                           content.releaseFingerprint(self.release))
    run.assert_not_called()


class NotesOnlyTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.path = Path(temp.name) / 'body.md'
    self.path.write_text('# new\n', encoding='utf-8')
    self.release = {'id': 10, 'tag_name': 'v1.0.20', 'body': '# old\n', 'assets': []}
    self.stack = contextlib.ExitStack()
    self.addCleanup(self.stack.close)
    self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    self.stack.enter_context(patch.object(portable_release, 'checkRepository'))
    self.stack.enter_context(patch.object(portable_release, 'getRelease', return_value=self.release))
    self.build = self.stack.enter_context(patch.object(portable_release, 'executeBuild'))
    self.resolve = self.stack.enter_context(patch.object(portable_release, 'resolveBuildConfig'))
    self.update = self.stack.enter_context(patch.object(portable_release, 'updateBody',
                                                     return_value={**self.release, 'body': '# new\n'}))

  def args(self, *extra):
    return portable_release.makeParser().parse_args([
      '--notes-only', '--release-repo', 'tests/releases', '--release-tag', 'v1.0.20',
      '--release-body-path', str(self.path), *extra,
    ])

  def test_notes_only_requires_explicit_publish(self) -> None:
    result = portable_release.runRelease(self.args())
    self.assertFalse(result['published'])
    self.update.assert_not_called()
    self.resolve.assert_not_called()
    self.build.assert_not_called()

  def test_notes_only_publish_never_resolves_or_builds_application(self) -> None:
    result = portable_release.runRelease(self.args('--publish'))
    self.assertTrue(result['published'])
    self.update.assert_called_once()
    self.resolve.assert_not_called()
    self.build.assert_not_called()

  def test_notes_only_dry_run_blocks_remote_mutation(self) -> None:
    portable_release.runRelease(self.args('--publish', '--dry-run'))
    self.update.assert_not_called()

  def test_notes_only_rejects_asset_and_manifest_overrides(self) -> None:
    for extra in (['--program-name', 'VisionWorkshop'], ['--mandatory'], ['--build-only'],
                  ['--notes', 'changed'], ['--config', 'config.json'], ['--skip-build'],
                  ['--previous-source-ref', 'HEAD'], ['--release-title', 'changed']):
      with self.subTest(extra=extra), self.assertRaises(BuildConfigError):
        portable_release.runRelease(self.args('--publish', *extra))
    self.update.assert_not_called()

  def test_preview_fingerprint_and_body_hash_are_checked(self) -> None:
    for flag in ('--expected-release-fingerprint', '--release-body-sha256'):
      with self.assertRaises(BuildConfigError):
        portable_release.runRelease(self.args('--publish', flag, 'invalid'))
    self.update.assert_not_called()


class ContentPipelineTests(fixtures.PortableTests):
  def test_unreadable_body_fails_before_compilation(self) -> None:
    with self.assertRaises(BuildConfigError):
      self.runLocal('--release-body-path', str(self.root / 'missing.md'))
    self.compiler.assert_not_called()
    self.compressor.assert_not_called()

  def test_invalid_base_fails_before_compilation(self) -> None:
    with self.assertRaises(BuildConfigError):
      self.runLocal('--previous-source-ref', 'unknown-commit')
    self.compiler.assert_not_called()

  def test_existing_tag_fails_before_compilation(self) -> None:
    with patch.object(portable_release, 'requireNewRelease', side_effect=BuildConfigError('exists')):
      with self.assertRaisesRegex(BuildConfigError, 'exists'):
        self.runLocal('--program-name', 'emo-vision-train', '--publish')
    self.compiler.assert_not_called()
    self.assertFalse((self.packager / 'build').exists())

  def test_changed_source_head_fails_before_compilation(self) -> None:
    with self.assertRaisesRegex(BuildConfigError, 'HEAD changed'):
      self.runLocal('--expected-source-commit', 'a' * 40)
    self.compiler.assert_not_called()

  def test_dry_run_previews_body_without_writing_outputs(self) -> None:
    path = self.root / 'notes.md'
    path.write_text('# Release body preview', encoding='utf-8')
    before = sorted(self.packager.rglob('*'))
    result = self.runLocal('--dry-run', '--release-body-path', str(path))
    self.assertIn('# Release body preview', self.log.getvalue())
    self.assertIn('release_body_sha256', result)
    self.assertEqual(sorted(self.packager.rglob('*')), before)
    self.compiler.assert_not_called()

  def test_confirmed_body_is_frozen_before_compilation(self) -> None:
    path = self.root / 'notes.md'
    path.write_text('# approved\n', encoding='utf-8')
    def compiler(command):
      path.write_text('# edited during build\n', encoding='utf-8')
      return self.compile(command)
    self.compiler.side_effect = compiler
    with patch.object(portable_release, 'requireNewRelease'), \
         patch.object(portable_release, 'publishAssets') as publish:
      self.runLocal('--program-name', 'emo-vision-train', '--publish',
                    '--release-body-path', str(path))
    self.assertEqual(publish.call_args.args[-1].body, '# approved\n')


def load_tests(loader, tests, pattern):
  suite = unittest.TestSuite()
  for case in (ContentTests, BodyTests, ReleaseApiTests, NotesOnlyTests):
    suite.addTests(loader.loadTestsFromTestCase(case))
  for name in ContentPipelineTests.__dict__:
    if name.startswith('test_'):
      suite.addTest(ContentPipelineTests(name))
  return suite


if __name__ == '__main__':
  unittest.main()
