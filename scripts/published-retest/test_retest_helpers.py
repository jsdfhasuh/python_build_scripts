"""Executable portable checks. These do not certify the Windows EXE scenarios."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('published_retest', ROOT / 'retest_published_windows.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
SOURCE = Path(os.environ.get('RETEST_SOURCE_ROOT', str(ROOT.parents[1] / 'source'))).resolve()
sys.path.insert(0, str(SOURCE))
from github_release_provider import GitHubReleaseProvider
from update_contract import Asset
from update_download import asset_path, download_asset


class ReleaseLockTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads((ROOT / 'published-assets.lock.json').read_bytes())
        self.tag = 'v1.0.29'
        self.record = self.lock['releases'][self.tag]
        self.release = {'id': self.record['release_id'], 'tag_name': self.tag,
                        'draft': False, 'prerelease': False}

    def test_expected_published_asset_set(self):
        r.verify_release_lock(self.release, self.record['assets'], self.record, self.tag)
        self.assertEqual(len(self.record['assets']), 5)

    def test_changed_digest_id_size_or_missing_asset_rejected(self):
        for key, value in [('id', 9), ('digest', 'sha256:' + '0' * 64), ('size', 7)]:
            with self.subTest(key=key):
                assets = copy.deepcopy(self.record['assets'])
                assets[0][key] = value
                with self.assertRaises(RuntimeError):
                    r.verify_release_lock(self.release, assets, self.record, self.tag)
        with self.assertRaises(RuntimeError):
            r.verify_release_lock(self.release, self.record['assets'][:-1], self.record, self.tag)

    def test_new_or_replaced_release_and_prerelease_rejected(self):
        for key, value in [('id', 9), ('tag_name', 'v1.0.30'), ('draft', True), ('prerelease', True)]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                r.verify_release_lock({**self.release, key: value}, self.record['assets'], self.record, self.tag)

    def test_helper_is_exact_known_passing_snapshot(self):
        self.assertEqual(r.digest_file(ROOT / 'frozen_release_helpers.py'), r.HELPER_SHA256)
        helper = r.load_helpers(SOURCE)
        self.assertTrue(callable(helper.extract_baseline))
        self.assertTrue(callable(helper.download_asset))

    def test_status_allowlist_omits_session_secrets_and_paths(self):
        status = {'state': 'FAILED', 'error_code': 'USER_FILES_UNCLASSIFIED',
                  'token': 'secret-value', 'quiescence': {'token': 'nested-secret'},
                  'app_dir': 'private-path', 'launch_token': 'another-secret'}
        result = json.dumps(r.safe_status(status))
        self.assertNotIn('secret', result)
        self.assertNotIn('private', result)
        self.assertEqual(r.safe_error(RuntimeError('token=secret https://signed.example/?x=secret')),
                         {'state': 'failed', 'error_type': 'RuntimeError'})

    def test_expected_frozen_rejection_accepts_clean_failure_exit(self):
        status = {'state': 'FAILED', 'error_code': 'USER_FILES_UNCLASSIFIED',
                  'install_status': 'not_modified', 'token': 'must-not-leak'}
        for returncode in (0, 1):
            r.validate_frozen_result(status, returncode, 'USER_FILES_UNCLASSIFIED')
        for returncode in (-9, 3221225477):
            with self.assertRaises(r.FrozenResultError):
                r.validate_frozen_result(status, returncode, 'USER_FILES_UNCLASSIFIED')
        with self.assertRaises(r.FrozenResultError) as caught:
            r.validate_frozen_result(status, 0, 'LOCAL_FILE_MODIFIED')
        self.assertNotIn('must-not-leak', json.dumps(r.safe_error(caught.exception)))
        with self.assertRaises(r.FrozenResultError):
            r.validate_frozen_result(status, 0)
        with self.assertRaises(r.FrozenResultError):
            r.validate_frozen_result({'state': 'SUCCESS'}, 1)
        r.validate_frozen_result({'state': 'SUCCESS'}, 0)

    def test_workflow_is_read_only_and_evidence_is_single_allowlisted_report(self):
        import yaml
        candidate = ROOT.parents[1] / '.github/workflows/published-update-retest.yml'
        mirror = ROOT / 'published-update-retest.yml'
        actual = candidate if candidate.exists() else mirror
        if candidate.exists():
            self.assertEqual(candidate.read_bytes(), mirror.read_bytes(),
                             'The dispatched workflow and reviewed safety-test copy differ')
        workflow = yaml.safe_load(actual.read_text())
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        job = workflow['jobs']['retest-published-assets']
        self.assertLessEqual(job['timeout-minutes'], 60)
        steps = job['steps']
        writes = [s for s in steps if 'run' in s]
        commands = '\n'.join(s['run'] for s in writes)
        for forbidden in ('actions_release.py', 'portable_release.py', 'build.py', 'gh release', 'git push', 'workflow run'):
            self.assertNotIn(forbidden, commands)
        uploads = [s for s in steps if str(s.get('uses', '')).startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]['if'], 'always()')
        self.assertTrue(uploads[0]['with']['path'].endswith('/retest-report.json'))
        self.assertNotIn('**', uploads[0]['with']['path'])
        refs = [s.get('with', {}).get('ref') for s in steps]
        self.assertIn(self.lock['source_commit'], refs)
        self.assertIn(self.lock['packager_commit'], refs)


class DownloadChecks(unittest.TestCase):
    def test_same_length_corrupt_cache_is_replaced_by_exact_bytes(self):
        raw = b'published-asset-fixture-' * 100
        asset = Asset(9001, 'fixture.zip', len(raw), hashlib.sha256(raw).hexdigest())
        calls = []
        class Response:
            status_code = 200
            headers = {'Content-Length': str(len(raw))}
            def iter_content(self, chunk_size):
                yield raw
        class Provider:
            @contextmanager
            def open_asset(self, item, offset=0):
                calls.append((item.asset_id, offset))
                yield Response()
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            target = asset_path(cache, asset)
            target.write_bytes(b'x' * len(raw))
            result = download_asset(Provider(), asset, cache)
            self.assertEqual(result.read_bytes(), raw)
            self.assertEqual(calls, [(asset.asset_id, 0)])
            self.assertFalse(target.with_suffix('.download').exists())
            download_asset(Provider(), asset, cache)
            self.assertEqual(len(calls), 1, 'Verified bytes should be reusable without a new request')

    def test_corrupted_download_retries_from_zero_then_verifies(self):
        raw = b'retry-fixture' * 100
        asset = Asset(9002, 'fixture.zip', len(raw), hashlib.sha256(raw).hexdigest())
        calls = []
        class Response:
            status_code = 200
            headers = {'Content-Length': str(len(raw))}
            def __init__(self, body):
                self.body = body
            def iter_content(self, chunk_size):
                yield self.body
        class Provider:
            @contextmanager
            def open_asset(self, item, offset=0):
                calls.append(offset)
                yield Response(b'x' * len(raw) if len(calls) == 1 else raw)
        with tempfile.TemporaryDirectory() as temporary, patch('update_download.time.sleep'):
            result = download_asset(Provider(), asset, Path(temporary))
            self.assertEqual(result.read_bytes(), raw)
            self.assertEqual(calls, [0, 0])

    def test_permanent_corrupted_download_fails_closed(self):
        raw = b'expected'
        asset = Asset(9003, 'fixture.zip', len(raw), hashlib.sha256(raw).hexdigest())
        class Response:
            status_code = 200
            headers = {'Content-Length': str(len(raw))}
            def iter_content(self, chunk_size):
                yield b'x' * len(raw)
        class Provider:
            @contextmanager
            def open_asset(self, item, offset=0):
                yield Response()
        with tempfile.TemporaryDirectory() as temporary, patch('update_download.time.sleep'):
            cache = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'PACKAGE_TRANSFER_FAILED'):
                download_asset(Provider(), asset, cache, retries=1)
            self.assertFalse(asset_path(cache, asset).exists())
            self.assertFalse(asset_path(cache, asset).with_suffix('.download').exists())


if __name__ == '__main__':
    unittest.main()
