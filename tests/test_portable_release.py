import argparse
import contextlib
import functools
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import branding_build
import portable_release
from branding_fixtures import makeIco
from branding_fixtures import writeProject
from build_config import BuildConfigError
from build_config import resolveBuildConfig
from build_records import fileHash
from build_records import gitState
from build_records import objectHash
from build_records import readJsonObject
from build_records import scanFiles
from build_records import verifyRecord
from build_records import writeJsonNew


def git(root: Path, *args: str) -> str:
  result = subprocess.run(['git', '-C', str(root), *args], text=True, encoding='utf-8',
                          capture_output=True, check=False)
  if result.returncode:
    raise AssertionError(result.stderr)
  return result.stdout.strip()


def initializeGit(root: Path) -> None:
  git(root, 'init')
  git(root, 'config', 'user.name', 'Portable Tests')
  git(root, 'config', 'user.email', 'tests@example.invalid')
  git(root, 'add', '.')
  git(root, 'commit', '-m', 'fixture')


class PortableTests(unittest.TestCase):
  def setUp(self) -> None:
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.root = Path(temp.name).resolve()
    self.source = self.root / 'source'
    self.packager = self.root / 'packager'
    self.packager.mkdir()
    config, self.icon, self.profile = writeProject(self.source)
    self.config = self.packager / 'configs/emo-vision-train.json'
    self.config.parent.mkdir()
    data = json.loads(config.read_text())
    data['source_repo'] = 'tests/source'
    data['release_repo'] = 'tests/releases'
    self.config.write_text(json.dumps(data), encoding='utf-8')
    (self.packager / '.gitignore').write_text('build/\ndist/\nrelease-output/\n__pycache__/\n')
    (self.source / '.gitignore').write_text('__pycache__/\n')
    (self.source / 'helper.py').write_text('VALUE = 1\n')
    initializeGit(self.source)
    initializeGit(self.packager)
    self.stack = contextlib.ExitStack()
    self.addCleanup(self.stack.close)
    self.log = io.StringIO()
    self.stack.enter_context(contextlib.redirect_stdout(self.log))
    self.stack.enter_context(contextlib.redirect_stderr(self.log))
    self.stack.enter_context(patch.dict(os.environ, {'SOURCE_ROOT': str(self.source)}))
    self.stack.enter_context(patch('portable_release.ROOT', self.packager))
    self.stack.enter_context(patch('portable_release.resolveBuildConfig', side_effect=
      functools.partial(resolveBuildConfig, packagerRoot=self.packager)))
    self.stack.enter_context(patch('branding_build.sys.platform', 'win32'))
    self.stack.enter_context(patch('build_records.toolVersions', return_value={'test': 1}))
    self.compiler = self.stack.enter_context(patch('build.run_command', side_effect=self.compile))
    self.compressor = self.stack.enter_context(patch('portable_release.compressArchive',
                                                   side_effect=self.compress))
    self.stack.enter_context(patch('build._find_python_dll', return_value=None))
    self.stack.enter_context(patch('build._collect_python_runtime_dlls', return_value=[]))

  def args(self, *extra: str) -> argparse.Namespace:
    return portable_release.makeParser().parse_args([
      '--config', str(self.config), '--source-root', str(self.source),
      '--branding-profile', str(self.profile), '--release-tag', 'v1.2.3', *extra,
    ])

  def compile(self, command: list[str]) -> int:
    directory = Path(command[command.index('--distpath') + 1])
    name = command[command.index('--name') + 1]
    if '--onefile' in command:
      path = directory / f'{name}.exe'
    else:
      path = directory / name / f'{name}.exe'
      resource = directory / name / '_internal/data.txt'
      resource.parent.mkdir(parents=True)
      resource.write_bytes(b'test data')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'FAKE compiler output, never a Windows acceptance test')
    return 0

  def compress(self, app: Path, path: Path) -> str:
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
      for file in sorted(app.rglob('*')):
        if file.is_file():
          archive.write(file, f'{app.name}/{file.relative_to(app).as_posix()}')
    return 'zip/deflate'

  def runLocal(self, *extra: str) -> dict:
    return portable_release.runRelease(self.args(*extra))

  def recordPath(self) -> Path:
    return next((self.packager / 'build').rglob('build-record.json'))

  def test_fresh_build_creates_single_root_zip_and_public_summary_only(self) -> None:
    with patch('portable_release.runChecked', side_effect=AssertionError('No GH in BuildOnly')):
      summary = self.runLocal('--build-only')
    self.assertEqual(summary['asset_name'], 'VisionWorkshop-windows-v1.2.3.zip')
    self.assertFalse(summary['published'])
    archive = next(self.packager.glob('release-output/**/*.zip'))
    with zipfile.ZipFile(archive) as content:
      self.assertEqual({p.split('/')[0] for p in content.namelist()}, {'VisionWorkshop'})
      self.assertIn('VisionWorkshop/updater.exe', content.namelist())
      self.assertFalse(any('build-record' in p or 'effective-config' in p for p in content.namelist()))
    self.assertEqual({p.name for p in archive.parent.iterdir()},
                     {summary['asset_name'], 'build-summary.json'})
    self.assertNotIn(str(self.root), json.dumps(summary))
    self.assertTrue(readJsonObject(self.recordPath())['reusable'])

  def test_preview_is_read_only(self) -> None:
    before = sorted(str(p) for p in self.packager.rglob('*'))
    self.runLocal('--dry-run')
    self.assertEqual(sorted(str(p) for p in self.packager.rglob('*')), before)
    self.compiler.assert_not_called()
    self.compressor.assert_not_called()

  def test_profile_does_not_mutate_default_config(self) -> None:
    before = self.config.read_bytes()
    self.runLocal()
    self.assertEqual(self.config.read_bytes(), before)

  def test_rename_is_blocked_before_auth_build_or_output(self) -> None:
    for extra in (['--publish'], ['--publish', '--release-repo', 'other/repo'],
                  ['--publish', '--manifest-name', 'different.json']):
      with self.subTest(extra=extra), patch('portable_release.runChecked') as auth:
        with self.assertRaisesRegex(BuildConfigError, 'unverified'):
          self.runLocal(*extra)
        auth.assert_not_called()
    self.compiler.assert_not_called()
    self.assertFalse((self.packager / 'build').exists())

  def test_mode_conflicts_and_missing_record_fail_early(self) -> None:
    cases = [('--publish', '--build-only'), ('--skip-build',),
             ('--build-record-path', 'missing.json'), ('--notes-only',)]
    for extra in cases:
      with self.subTest(extra=extra), self.assertRaises(BuildConfigError):
        self.runLocal(*extra)
    self.compiler.assert_not_called()

  def test_record_reuse_does_not_recompile_and_may_change_release_tag(self) -> None:
    self.runLocal()
    self.compiler.reset_mock()
    result = self.runLocal('--skip-build', '--build-record-path', str(self.recordPath()),
                           '--release-tag', 'v1.2.4')
    self.compiler.assert_not_called()
    self.assertTrue(result['asset_name'].endswith('v1.2.4.zip'))

  def test_same_path_different_icon_invalidates_reuse(self) -> None:
    self.runLocal()
    self.icon.write_bytes(makeIco(png=True))
    with self.assertRaisesRegex(BuildConfigError, 'match|changed'):
      self.runLocal('--skip-build', '--build-record-path', str(self.recordPath()))

  def test_changed_artifact_invalidates_reuse(self) -> None:
    self.runLocal()
    app = next((self.packager / 'dist').rglob('VisionWorkshop.exe'))
    app.write_bytes(b'changed exe')
    with self.assertRaisesRegex(BuildConfigError, 'artifacts changed'):
      self.runLocal('--skip-build', '--build-record-path', str(self.recordPath()))

  def test_changed_helper_invalidates_reuse(self) -> None:
    self.runLocal()
    (self.source / 'helper.py').write_text('VALUE = 2\n')
    with self.assertRaisesRegex(BuildConfigError, 'inputs'):
      self.runLocal('--skip-build', '--build-record-path', str(self.recordPath()))

  def test_dirty_source_can_build_but_cannot_reuse(self) -> None:
    (self.source / 'helper.py').write_text('VALUE = 2\n')
    self.runLocal()
    self.assertFalse(readJsonObject(self.recordPath())['reusable'])
    with self.assertRaisesRegex(BuildConfigError, 'Dirty'):
      self.runLocal('--skip-build', '--build-record-path', str(self.recordPath()))

  def test_dirty_helper_changes_during_compile_are_detected(self) -> None:
    helper = self.source / 'helper.py'
    helper.write_text('VALUE = 2\n')
    def compiler(command):
      helper.write_text('VALUE = 3\n')
      return self.compile(command)
    self.compiler.side_effect = compiler
    with self.assertRaisesRegex(BuildConfigError, 'changed during build'):
      self.runLocal()
    self.assertFalse(list(self.packager.rglob('build-record.json')))

  def test_compiler_failure_does_not_reuse_previous_dist(self) -> None:
    old = self.packager / 'dist/emo-vision-train/emo-vision-train.exe'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'old')
    self.compiler.return_value = 4
    self.compiler.side_effect = None
    with self.assertRaises(branding_build.CompilerError):
      self.runLocal()
    self.assertEqual(old.read_bytes(), b'old')
    self.compressor.assert_not_called()

  def test_broken_archive_has_no_success_summary(self) -> None:
    def broken(app, output):
      output.write_bytes(b'not a ZIP')
      return 'zip/deflate'
    self.compressor.side_effect = broken
    with self.assertRaises(zipfile.BadZipFile):
      self.runLocal()
    self.assertFalse(list(self.packager.rglob('build-summary.json')))
    self.assertFalse(list(self.packager.glob('release-output/**/*.zip')))

  def test_output_must_be_new_or_empty(self) -> None:
    output = self.root / 'output'
    output.mkdir()
    keep = output / 'keep.txt'
    keep.write_text('keep')
    with self.assertRaisesRegex(BuildConfigError, 'new or empty'):
      self.runLocal('--output-directory', str(output))
    self.compiler.assert_not_called()
    self.assertEqual(keep.read_text(), 'keep')

  def test_output_cannot_be_in_source_or_private_workdir(self) -> None:
    for output in (self.source / 'out', self.packager / 'dist/out', self.packager / 'build/out'):
      with self.subTest(output=output), self.assertRaisesRegex(BuildConfigError, 'outside source'):
        self.runLocal('--output-directory', str(output))
    self.compiler.assert_not_called()

  def test_bad_source_ref_is_not_ignored(self) -> None:
    with self.assertRaises(BuildConfigError):
      self.runLocal('--source-ref', 'does-not-exist')
    self.compiler.assert_not_called()

  def test_ref_at_other_commit_fails(self) -> None:
    git(self.source, 'tag', 'old')
    (self.source / 'helper.py').write_text('VALUE = 2\n')
    git(self.source, 'commit', '-am', 'change')
    with self.assertRaisesRegex(BuildConfigError, 'does not match'):
      self.runLocal('--source-ref', 'old')

  def test_manifest_summary_collision_fails_before_build(self) -> None:
    with self.assertRaisesRegex(BuildConfigError, 'collide'):
      self.runLocal('--manifest-name', 'build-summary.json')
    self.compiler.assert_not_called()

  def test_relocated_record_cannot_redirect_publisher(self) -> None:
    self.runLocal()
    moved = self.root / 'copied-record.json'
    moved.write_bytes(self.recordPath().read_bytes())
    with self.assertRaisesRegex(BuildConfigError, 'original isolated'):
      self.runLocal('--skip-build', '--build-record-path', str(moved))

  def test_record_path_traversal_is_rejected(self) -> None:
    self.runLocal()
    path = self.recordPath()
    record = readJsonObject(path)
    record['build_id'] = '../../../source'
    path.write_text(json.dumps(record))
    with self.assertRaisesRegex(BuildConfigError, 'record ID'):
      self.runLocal('--skip-build', '--build-record-path', str(path))

  def test_same_identity_new_build_recovers_after_customization(self) -> None:
    self.runLocal()
    self.runLocal('--program-name', 'emo-vision-train')
    names = {path.name for path in (self.packager / 'dist').rglob('*.exe')}
    self.assertIn('VisionWorkshop.exe', names)
    self.assertIn('emo-vision-train.exe', names)

  def test_new_publication_failure_keeps_summary_unpublished(self) -> None:
    with patch('portable_release.runChecked', return_value=''), \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.publishAssets', side_effect=BuildConfigError('upload failed')):
      with self.assertRaisesRegex(BuildConfigError, 'upload failed'):
        self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    summary = readJsonObject(next(self.packager.rglob('build-summary.json')))
    self.assertFalse(summary['published'])

  def test_explicit_publication_success_marks_summary(self) -> None:
    with patch('portable_release.runChecked', return_value=''), \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.publishAssets') as publish:
      result = self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    self.assertTrue(result['published'])
    publish.assert_called_once()
    self.assertTrue(readJsonObject(next(self.packager.rglob('build-summary.json')))['published'])

  def test_publication_verifies_zip_contents_and_post_build_record_only_once(self) -> None:
    with patch('portable_release.runChecked', return_value='') as upload, \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.verifyArchiveContents',
               wraps=portable_release.verifyArchiveContents) as contents, \
         patch('portable_release.verifyRecord', wraps=verifyRecord) as record:
      result = self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    self.assertTrue(result['published'])
    contents.assert_called_once()
    record.assert_called_once()
    self.assertEqual(upload.call_args.args[0][:3], ['gh', 'release', 'create'])
    for label in ('ZIP \u5b8c\u6574\u5185\u5bb9\u6821\u9a8c', '\u53d1\u5e03\u524d\u590d\u67e5\u6e90\u7801', '\u4e0a\u4f20\u524d\u590d\u67e5 ZIP \u6307\u7eb9', '\u4e0a\u4f20 ZIP'):
      self.assertIn(label, self.log.getvalue())

  def test_reused_build_gets_fresh_zip_verification_before_publication(self) -> None:
    self.runLocal('--program-name', 'emo-vision-train')
    self.compiler.reset_mock()
    with patch('portable_release.runChecked', return_value=''), \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.verifyArchiveContents',
               wraps=portable_release.verifyArchiveContents) as contents, \
         patch('portable_release.verifyRecord', wraps=verifyRecord) as record:
      result = self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all',
                             '--skip-build', '--build-record-path', str(self.recordPath()))
    self.assertTrue(result['published'])
    self.compiler.assert_not_called()
    contents.assert_called_once()
    self.assertEqual(record.call_count, 2)  # Reuse preflight and the final publication check.

  def test_changed_zip_is_rejected_even_with_same_size_and_mtime(self) -> None:
    def write(path, data):
      writeJsonNew(path, data)
      if path.name == 'build-summary.json':
        archive = path.parent / data['asset_name']
        before = archive.stat()
        value = archive.read_bytes()
        archive.write_bytes(value[:-1] + bytes([value[-1] ^ 1]))
        os.utime(archive, ns=(before.st_atime_ns, before.st_mtime_ns))
    with patch('portable_release.runChecked') as upload, \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.writeJsonNew', side_effect=write):
      with self.assertRaisesRegex(BuildConfigError, 'ZIP changed before publication'):
        self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    upload.assert_not_called()
    self.assertFalse(readJsonObject(next(self.packager.rglob('build-summary.json')))['published'])

  def test_rewriting_summary_hash_cannot_replace_current_run_verification(self) -> None:
    def write(path, data):
      if path.name == 'build-summary.json':
        archive = path.parent / data['asset_name']
        value = archive.read_bytes()
        archive.write_bytes(value[:-1] + bytes([value[-1] ^ 1]))
        data['asset_sha256'] = fileHash(archive)
      writeJsonNew(path, data)
    with patch('portable_release.runChecked') as upload, \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.writeJsonNew', side_effect=write):
      with self.assertRaisesRegex(BuildConfigError, 'verification does not match'):
        self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    upload.assert_not_called()

  def assertPublicationChangeRejected(self, changeSource: bool) -> None:
    def write(path, data):
      writeJsonNew(path, data)
      if path.name == 'build-summary.json':
        changed = (self.source / 'helper.py' if changeSource else
                   next((self.packager / 'dist').rglob('emo-vision-train.exe')))
        changed.write_bytes(b'changed after ZIP verification')
    with patch('portable_release.runChecked') as upload, \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.writeJsonNew', side_effect=write):
      with self.assertRaisesRegex(BuildConfigError, 'inputs|artifacts changed'):
        self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    upload.assert_not_called()
    self.assertFalse(readJsonObject(next(self.packager.rglob('build-summary.json')))['published'])

  def test_changed_source_is_still_rejected_before_upload(self) -> None:
    self.assertPublicationChangeRejected(True)

  def test_changed_artifact_is_still_rejected_before_upload(self) -> None:
    self.assertPublicationChangeRejected(False)

  def test_local_zip_changed_during_record_recheck_is_not_finalized(self) -> None:
    def verify(*args, **kwargs):
      result = verifyRecord(*args, **kwargs)
      archive = next(self.packager.glob('release-output/**/*.zip'))
      archive.write_bytes(archive.read_bytes() + b'changed')
      return result
    with patch('portable_release.verifyRecord', side_effect=verify):
      with self.assertRaisesRegex(BuildConfigError, 'ZIP changed before finalization'):
        self.runLocal('--build-only')
    self.assertFalse(list(self.packager.rglob('build-summary.json')))
    self.assertFalse(list(self.packager.glob('release-output/**/*.zip')))

  def test_cancelled_content_verification_never_uploads_or_marks_success(self) -> None:
    with patch('portable_release.runChecked') as upload, \
         patch('portable_release.requireNewRelease'), \
         patch('portable_release.verifyArchiveContents', side_effect=KeyboardInterrupt):
      with self.assertRaises(KeyboardInterrupt):
        self.runLocal('--program-name', 'emo-vision-train', '--publish', '--changelog-all')
    upload.assert_not_called()
    self.assertFalse(list(self.packager.rglob('build-summary.json')))
    self.assertFalse(list(self.packager.glob('release-output/**/*.zip')))


class ArchiveTests(unittest.TestCase):
  def setUp(self) -> None:
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.app = self.root / 'VisionWorkshop'
    self.app.mkdir()
    (self.app / 'VisionWorkshop.exe').write_bytes(b'test')
    self.expected = scanFiles(self.app)
    self.path = self.root / 'test.zip'

  def writeZip(self, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(self.path, 'w', zipfile.ZIP_LZMA) as archive:
      for name, data in members:
        archive.writestr(name, data)

  def test_valid_lzma_zip_streams_and_matches(self) -> None:
    self.writeZip([('VisionWorkshop/VisionWorkshop.exe', b'test')])
    verified = portable_release.verifyArchive(self.path, 'VisionWorkshop', self.expected)
    self.assertEqual(verified.programName, 'VisionWorkshop')
    self.assertEqual(verified.sha256, fileHash(self.path))
    self.assertEqual(verified.size, self.path.stat().st_size)
    self.assertEqual(verified.filesSha256, objectHash(self.expected))

  def test_change_during_verification_invalidates_the_result(self) -> None:
    self.writeZip([('VisionWorkshop/VisionWorkshop.exe', b'test')])
    verifyContents = portable_release.verifyArchiveContents
    def change(*args):
      verifyContents(*args)
      before = self.path.stat()
      value = self.path.read_bytes()
      self.path.write_bytes(value[:-1] + bytes([value[-1] ^ 1]))
      os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with patch('portable_release.verifyArchiveContents', side_effect=change):
      with self.assertRaisesRegex(BuildConfigError, 'ZIP changed during content verification'):
        portable_release.verifyArchive(self.path, 'VisionWorkshop', self.expected)

  def test_large_member_advances_byte_progress_before_the_file_finishes(self) -> None:
    self.writeZip([('VisionWorkshop/VisionWorkshop.exe', b'test')])
    with patch('portable_release.CHUNK', 2), \
         patch.object(portable_release.ReleaseProgress, 'advance', autospec=True) as advance:
      portable_release.verifyArchive(self.path, 'VisionWorkshop', self.expected)
    updates = [call.kwargs for call in advance.call_args_list
               if call.args[0].label == 'ZIP \u5b8c\u6574\u5185\u5bb9\u6821\u9a8c']
    self.assertEqual(updates, [{'byteCount': 2}, {'byteCount': 2}, {'fileCount': 1}])

  def test_unsafe_members_fail(self) -> None:
    cases = ['../escape', 'Other/app.exe', '/VisionWorkshop/file',
             'VisionWorkshop/../file', 'VisionWorkshop\\file',
             'VisionWorkshop//file', 'VisionWorkshop/./file', 'VisionWorkshop/CON']
    for name in cases:
      with self.subTest(name=name):
        self.writeZip([(name, b'test')])
        with self.assertRaises(BuildConfigError):
          portable_release.verifyArchive(self.path, 'VisionWorkshop', self.expected)

  def test_modified_missing_extra_and_duplicate_files_fail(self) -> None:
    base = [('VisionWorkshop/VisionWorkshop.exe', b'test')]
    for members in ([], [('VisionWorkshop/VisionWorkshop.exe', b'xxxx')],
                    base + [('VisionWorkshop/secret.json', b'test')],
                    base + [('VisionWorkshop/visionworkshop.EXE', b'test')]):
      with self.subTest(members=members):
        self.writeZip(members)
        with self.assertRaises(BuildConfigError):
          portable_release.verifyArchive(self.path, 'VisionWorkshop', self.expected)

  def test_links_are_rejected(self) -> None:
    with zipfile.ZipFile(self.path, 'w') as archive:
      member = zipfile.ZipInfo('VisionWorkshop/VisionWorkshop.exe')
      member.create_system = 3
      member.external_attr = 0o120777 << 16
      archive.writestr(member, b'test')
    with self.assertRaisesRegex(BuildConfigError, 'link'):
      portable_release.verifyArchive(self.path, 'VisionWorkshop', self.expected)

  def test_json_writer_never_overwrites(self) -> None:
    target = self.root / 'record.json'
    writeJsonNew(target, {'a': 1})
    with self.assertRaises(BuildConfigError):
      writeJsonNew(target, {'a': 2})
    self.assertEqual(readJsonObject(target), {'a': 1})


class CompressionPolicyTests(unittest.TestCase):
  def test_7z_memory_failure_retries_once_with_one_thread(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      app = root / 'VisionWorkshop'
      app.mkdir()
      output = root / 'out.zip'
      calls = []
      def run(args, **kwargs):
        calls.append(args)
        output.write_bytes(b'partial' if len(calls) == 1 else b'ok')
        return subprocess.CompletedProcess(args, 8 if len(calls) == 1 else 0)
      with patch('portable_release.shutil.which', return_value='7z'), \
           patch('portable_release.subprocess.run', side_effect=run):
        self.assertEqual(portable_release.compressArchive(app, output), 'zip/lzma')
      self.assertIn('-mmt=2', calls[0])
      self.assertIn('-mmt=1', calls[1])
      self.assertTrue(all('-mcu=on' in command for command in calls))
      self.assertEqual(output.read_bytes(), b'ok')

  def test_other_7z_errors_are_not_silently_retried(self) -> None:
    with patch('portable_release.shutil.which', return_value='7z'), \
         patch('portable_release.subprocess.run', return_value=subprocess.CompletedProcess([], 2)) as run:
      with self.assertRaises(BuildConfigError):
        portable_release.compressArchive(Path('/app/VisionWorkshop'), Path('/not-created.zip'))
      run.assert_called_once()


if __name__ == '__main__':
  unittest.main()
