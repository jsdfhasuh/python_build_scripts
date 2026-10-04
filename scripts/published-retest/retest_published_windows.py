"""Nonpublishing Windows retest of the exact public v1.0.28 -> v1.0.29 bytes.

No compiler, build, release, credentials, live user data, or latest-release lookup.
Reports are allowlisted summaries; raw session records must never be uploaded.
"""
import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from unittest.mock import patch

HELPER_SHA256 = '3565e8d2c70ab76a688fcfc679619e5ca3bb8432a494d0b0bc13d0d6e9e1180b'
STATUS_KEYS = ('state', 'error_code', 'install_status', 'launch_status', 'rollback_status',
               'package_kind', 'fallback_used')


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def asset_key(value):
    return {key: value.get(key) for key in ('id', 'name', 'size', 'digest', 'state')}


def verify_release_lock(release, assets, locked, tag):
    check(release.get('id') == locked['release_id'] and release.get('tag_name') == tag,
          'Public release ID/tag changed')
    check(release.get('draft') is False and release.get('prerelease') is False,
          'Expected a stable published release')
    actual = sorted((asset_key(value) for value in assets), key=lambda value: value['name'])
    check(actual == locked['assets'], 'Published asset IDs/names/lengths/digests changed')


def safe_status(status):
    return {key: status.get(key) for key in STATUS_KEYS if key in status}


def safe_error(error):
    # Deliberately omit exception strings/tracebacks, signed URLs and session tokens.
    result = {'state': 'failed', 'error_type': type(error).__name__}
    code = getattr(error, 'code', None)
    if isinstance(code, str) and code.isupper() and code.replace('_', '').isalnum():
        result['error_code'] = code
    if isinstance(error, FrozenResultError):
        result['frozen_result'] = error.result
        result['process_exit_code'] = error.process_exit_code
    return result


class FrozenResultError(RuntimeError):
    def __init__(self, result, process_exit_code):
        super().__init__('Unexpected frozen updater outcome')
        self.result = safe_status(result)
        self.process_exit_code = process_exit_code


def validate_frozen_result(result, process_exit_code, expected_error=None):
    if expected_error is not None:
        accepted = (result.get('state') == 'FAILED' and result.get('error_code') == expected_error
                    and result.get('install_status') == 'not_modified'
                    and process_exit_code in (0, 1))
    else:
        accepted = result.get('state') == 'SUCCESS' and process_exit_code == 0
    if not accepted:
        raise FrozenResultError(result, process_exit_code)


def verify_checkouts(source, packager, lock):
    for path, key in ((source, 'source_commit'), (packager, 'packager_commit')):
        commit = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'],
                                         text=True).strip()
        check(commit == lock[key], 'Checkout does not match immutable ' + key)
        check(not subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain',
                                          '--untracked-files=no'], text=True).strip(),
              'Tracked checkout files were modified')


def load_helpers(source):
    path = Path(__file__).with_name('frozen_release_helpers.py')
    check(digest_file(path) == HELPER_SHA256, 'Known-passing helper snapshot changed')
    spec = importlib.util.spec_from_file_location('published_frozen_helpers', path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    sys.path.insert(0, str(source))
    bindings = {
        'update_contract': ('Asset', 'ASSET_PREFIX', 'CONFIG_DEFAULTS', 'Identity', 'Manifest',
                            'DeltaDescriptor', 'canonical_json'),
        'github_release_provider': ('GitHubReleaseProvider', 'ReleaseSnapshot'),
        'update_payload': ('PayloadArchive',),
        'update_file_transaction': ('FileTransaction',),
        'update_installation': ('InstallationRegistry',),
        'update_package': ('file_record', 'verify_directory', 'inspect_installation'),
        'update_filesystem': ('file_identity', 'io_path'),
        'update_download': ('asset_path', 'download_asset'),
        'update_session': ('create_request', 'launch_session', 'provenance'),
        'update_process': ('current_process', 'ProcessHandle'),
        'update_storage': ('atomic_json',),
        'update_protocol': ('command_message',),
        'update_diagnostics': ('read_startup_trace',),
    }
    for module, names in bindings.items():
        imported = importlib.import_module(module)
        for name in names:
            setattr(helper, name, getattr(imported, name))
    return helper


def exact_snapshots(helper, lock):
    from update_contract import stable_version
    with helper.GitHubReleaseProvider(token='') as provider:
        releases = {}
        for tag, frozen in lock['releases'].items():
            release = provider._api('/releases/tags/' + tag)
            # Use production pagination and full asset parsing, not just the first API page.
            assets = list(provider._assets(release['id']).values())
            verify_release_lock(release, assets, frozen, tag)
            releases[tag] = release
        base = provider._snapshot(releases['v1.0.28'])
        target = provider._snapshot(releases['v1.0.29'],
                                    current=stable_version(base.identity.version), base=base.manifest)
        full = provider._snapshot(releases['v1.0.29'])
        check(target is not None and target.package_kind == 'delta',
              'Published target is not automatically delta-eligible from the pinned baseline')
        check(full.package_kind == 'full', 'No-baseline published selection is not full')
        for snapshot in (base, target):
            frozen = lock['releases'][snapshot.tag]
            check(snapshot.identity.build_id == frozen['build_id'], 'Build identity changed')
            check(json.loads(snapshot.identity.raw)['source']['commit'] == frozen['source_commit'],
                  'Published source identity changed')
        check(provider._snapshot(releases['v1.0.29'],
                                 current=stable_version(target.identity.version), base=target.manifest) is None,
              'Already-current version incorrectly offers the pinned release again')
    return base, target, full


def new_install(helper, archive, work, base):
    install = helper.extract_baseline(archive, work, base)
    registry = helper.InstallationRegistry(install)
    with registry.gate():
        registry.enroll(registry.app, launcher=True)
    registry.register_baseline(registry.app, base.identity, base.manifest, helper.provenance(base))
    config = helper.customize_config(registry.app, base.manifest)
    for name in config:
        (registry.app / name).chmod(stat.S_IREAD)
        check((registry.app / name).stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY,
              'Read-only configuration fixture was not set')
    return install, registry, config, helper.environment(work)


def check_config(helper, app, config):
    helper.verify_config(app, config)
    for name in config:
        check((app / name).stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY,
              'Configuration read-only attribute changed')


def wait_status(helper, directory, predicate, timeout=180):
    def ready(value):
        check(value.get('state') not in {'FAILED', 'CANCELLED', 'UNCONFIRMED', 'RECOVERY_REQUIRED'},
              'Unexpected frozen updater terminal status: ' + str(value.get('state')))
        return predicate(value)
    return helper.wait_json(directory / 'updater_status.json', ready, timeout)


def frozen_session(helper, install, snapshot, env, *, before_handoff=None, expected_error=None):
    """Real released baseline EXE, real updater, genuine process identities; idle handoff by harness."""
    import psutil
    registry = helper.InstallationRegistry(install)
    helper.spawn_frozen([install / 'VisionWorkshop.exe'], install, env)
    old = helper.wait_until(lambda: helper.find_product_process(registry.app), 'Baseline process', 180)
    def started():
        trace = helper.read_startup_trace(registry.app, old)
        if not trace:
            return None
        stages = [event['stage'] for event in trace['events']]
        check('FAILED' not in stages, 'Baseline startup failed')
        return trace if 'CREATING_WINDOW' in stages else None
    baseline_trace = helper.wait_until(started, 'Baseline GUI construction', 180)
    time.sleep(5)
    with helper.ProcessHandle(old['pid'], old) as handle:
        check(not handle.exited(), 'Baseline exited during initial smoke test')
    if before_handoff:
        before_handoff(registry)
    directory, request = helper.create_request(registry.app, snapshot, process=old)
    def launch(command, cwd):
        return helper.spawn_frozen([*command, '--exit-when-finished'], cwd, env)
    with patch('update_session.independent_launch', side_effect=launch):
        updater = helper.launch_session(directory)
    wait_status(helper, directory, lambda value: value.get('state') == 'WAITING_EXIT')
    helper.atomic_json(directory / 'app_command.json', helper.command_message(request, 1, 'APP_QUIESCED',
        occupants=[old], checks={name: True for name in
            ('writers_stopped', 'tasks_safe', 'models_restored', 'paths_checked')}))
    wait_status(helper, directory, lambda value: value.get('quiescence'))
    helper.atomic_json(directory / 'app_command.json', helper.command_message(request, 2, 'EXIT_APPROVED'))
    wait_status(helper, directory, lambda value: value.get('exit_accepted'))
    with helper.ProcessHandle(old['pid'], old) as handle:
        check(not handle.exited(), 'Baseline exited before approved handoff')
    process = psutil.Process(old['pid'])
    process.terminate()
    process.wait(timeout=30)
    result = helper.wait_json(directory / 'result.json', timeout=1200)
    updater.wait(timeout=45)
    validate_frozen_result(result, updater.returncode, expected_error)
    return directory, result, [event['stage'] for event in baseline_trace['events']]


def unknown_file_rejection(helper, install, registry, base, target, config, env):
    sentinel = registry.app / 'retest-user-data-do-not-delete.txt'
    content = b'Isolated user-file sentinel; preserve this byte sequence.\n'
    before = {name: helper.file_identity(registry.app / name) for name in base.manifest.files}
    def inject(_registry):
        sentinel.write_bytes(content)
    directory, result, _ = frozen_session(helper, install, target, env, before_handoff=inject,
                                          expected_error='USER_FILES_UNCLASSIFIED')
    helper.stop_owned(install)
    check(result.get('state') == 'FAILED' and result.get('error_code') == 'USER_FILES_UNCLASSIFIED',
          'Unknown user file did not safely reject the frozen update')
    check(result.get('install_status') == 'not_modified' and result.get('fallback_used') is False,
          'Unknown user file must not trigger modification or full fallback')
    check(not (directory / 'plan.json').exists(), 'Unknown-file failure wrote a durable modification plan')
    check(sentinel.read_bytes() == content, 'Unknown user data was changed')
    check(registry.load()['active'] is None, 'Unknown-file rejection left an active transaction')
    for name, identity in before.items():
        check(helper.file_identity(registry.app / name) == identity,
              'Rejected update replaced a baseline file')
    sentinel.unlink()  # Only the test-created sentinel; this authorizes the next test.
    helper.inspect_installation(registry.app, base.manifest, base.identity)
    check_config(helper, registry.app, config)
    return {'state': 'passed', 'frozen_result': safe_status(result), 'user_bytes_preserved': True,
            'baseline_file_identities_preserved': len(before), 'no_durable_plan': True,
            'scope': 'real frozen updater; harness-inserted unknown user file after idle startup'}


def poison_cache(helper, registry, asset):
    cache = registry.root / 'cache'
    cache.mkdir(exist_ok=True)
    destination = helper.asset_path(cache, asset)
    # The earlier rejected session downloaded a valid public delta. Corrupt one byte
    # in place so the cache has the right name AND length, but the wrong digest.
    check(destination.is_file() and destination.stat().st_size == asset.size,
          'No complete delta from the negative test is available to corrupt')
    check(digest_file(destination) == asset.digest, 'Negative-test delta cache was not verified')
    with destination.open('r+b') as stream:
        byte = stream.read(1)
        stream.seek(0)
        stream.write(bytes([byte[0] ^ 1]))
        stream.flush()
        os.fsync(stream.fileno())
    check(digest_file(destination) != asset.digest, 'Cache corruption fixture did not change digest')
    check(not destination.with_suffix('.download').exists(), 'Unexpected partial cache fixture')
    return destination


def verify_success(helper, registry, snapshot, config, directory, result, unchanged):
    check(result.get('state') == 'SUCCESS' and result.get('launch_status') == 'confirmed',
          'Frozen updater did not confirm target launch')
    ready = helper.wait_json(directory / 'app_ready.json')
    check(ready.get('build_id') == snapshot.identity.build_id, 'Target GUI identity mismatch')
    with helper.ProcessHandle(ready['process']['pid'], ready['process']) as handle:
        check(not handle.exited(), 'Confirmed target exited')
    def permitted():
        trace = helper.read_startup_trace(registry.app, ready['process'])
        return trace if trace and any(event['stage'] == 'RUN_ALLOWED' for event in trace['events']) else None
    trace = helper.wait_until(permitted, 'Target runtime permission', 180)
    helper.stop_owned(registry.parent)
    helper.inspect_installation(registry.app, snapshot.manifest, snapshot.identity)
    check_config(helper, registry.app, config)
    for name, identity in unchanged.items():
        check(helper.file_identity(registry.app / name) == identity, 'Unchanged file identity changed')
    record = registry.load()
    check(record['active'] is None, 'Successful update left an active transaction')
    manifest, identity = registry.baseline(record)
    check(manifest.raw == snapshot.manifest.raw and identity.raw == snapshot.identity.raw,
          'Next-session baseline receipt was not advanced to exact published target')
    plan = helper.read_json(directory / 'plan.json')
    check(plan['unchanged_copy_bytes'] == 0, 'Unchanged payload was copied')
    cached = helper.asset_path(registry.root / 'cache', snapshot.selected_asset)
    check(cached.stat().st_size == snapshot.selected_asset.size and
          digest_file(cached) == snapshot.selected_asset.digest, 'Installed transport asset was not exact public bytes')
    return {'state': 'passed', 'frozen_result': safe_status(result),
            'verified_transport_asset_sha256': snapshot.selected_asset.digest,
            'unchanged_file_identities_preserved': len(unchanged), 'unchanged_copy_bytes': 0,
            'prepared_bytes': plan['prepared_bytes'], 'next_session_baseline_verified': True,
            'read_only_config_preserved': list(config),
            'target_startup_stages': [event['stage'] for event in trace['events']]}


def transition(helper, install, registry, base, target, config, env):
    unchanged = {name: helper.file_identity(registry.app / name) for name, record in base.manifest.files.items()
                 if target.manifest.files.get(name) == record and base.manifest.policy(name).kind == 'immutable'}
    check(unchanged, 'No unchanged immutable payload to verify')
    directory, result, baseline_stages = frozen_session(helper, install, target, env)
    report = verify_success(helper, registry, target, config, directory, result, unchanged)
    report['baseline_startup_stages'] = baseline_stages
    return report


def cold_restarts(helper, install, registry, target, config, env):
    results = []
    for ordinal in (1, 2):
        helper.spawn_frozen([install / 'VisionWorkshop.exe'], install, env)
        process = helper.wait_until(lambda: helper.find_product_process(registry.app), 'Cold restart process', 180)
        def permitted():
            trace = helper.read_startup_trace(registry.app, process)
            if not trace:
                return None
            stages = [event['stage'] for event in trace['events']]
            check('FAILED' not in stages, 'Cold restart failed')
            # GUI_READY/RUN_ALLOWED exist only for protected post-update startup.
            # An ordinary cold launch is unprotected and reports CREATING_WINDOW.
            return stages if 'GUARD_ACCEPTED' in stages and 'CREATING_WINDOW' in stages else None
        stages = helper.wait_until(permitted, 'Cold restart guard and GUI construction', 240)
        time.sleep(15)
        with helper.ProcessHandle(process['pid'], process) as handle:
            check(not handle.exited(), 'Cold restart product exited early')
        helper.stop_owned(install)
        check(registry.load()['active'] is None, 'Cold restart created an unresolved transaction')
        check_config(helper, registry.app, config)
        results.append({'restart': ordinal, 'state': 'passed', 'startup_stages': stages,
                        'alive_after_construction_seconds': 15,
                        'ordinary_launch_gui_completion_signal': 'not available in this product'})
    helper.inspect_installation(registry.app, target.manifest, target.identity)
    return {'state': 'passed', 'attempts': results,
            'scope': 'two cold-start guard/GUI-construction/alive checks after one real upgrade; not a second version upgrade'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--packager-root', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=Path(__file__).with_name('published-assets.lock.json'))
    args = parser.parse_args()
    check(os.name == 'nt', 'Real Windows execution is required; Linux is helper-test only')
    work = args.work.resolve()
    check(not work.exists(), '--work must be a new isolated directory')
    work.mkdir(parents=True)
    report = {'state': 'running', 'scope': 'isolated exact published Windows update retest',
              'source_commit': None, 'packager_commit': None, 'publication': 'not-run; no write API',
              'rebuild': 'not-run; exact published EXEs only', 'checks': {},
              'interactive_ui_quiescence': 'not-run; harness-approved idle-product handoff',
              'dynamic_full_fallback': 'not-run; full test uses actual no-baseline selection',
              'second_version_upgrade': 'not-run; no published v1.0.30 is assumed',
              'GPU_training': 'not-run', 'physical_power_loss': 'not-run'}
    started = time.monotonic()
    helper = None
    def save():
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        (work / 'retest-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    def step(name, callback):
        report['checkpoint'] = name
        save()
        try:
            report['checks'][name] = callback()
        except BaseException as error:
            report['checks'][name] = safe_error(error)
            raise
        finally:
            save()
    try:
        lock = json.loads(args.lock.read_bytes())
        verify_checkouts(args.source_root, args.packager_root, lock)
        report.update(source_commit=lock['source_commit'], packager_commit=lock['packager_commit'])
        helper = load_helpers(args.source_root.resolve())
        base, target, full = exact_snapshots(helper, lock)
        report['checks']['pinned_public_metadata'] = {'state': 'passed',
            'baseline_release_id': base.release_id, 'target_release_id': target.release_id,
            'baseline_build_id': base.identity.build_id, 'target_build_id': target.identity.build_id,
            'already_current_selection': 'no_update', 'matching_baseline_selection': 'delta',
            'no_baseline_selection': 'full'}
        # Two sequential independent installs, one baseline ZIP, two target caches plus safety margin.
        needed = 2 * sum(value.size for value in base.manifest.files.values()) + base.full_asset.size + full.full_asset.size + 3 * target.selected_asset.size + 2 * 1024**3
        import shutil
        check(shutil.disk_usage(work).free > needed, 'Insufficient free space for both isolated installations')
        report['required_free_bytes_estimate'] = needed
        with helper.GitHubReleaseProvider(token='') as provider:
            archive = helper.download_asset(provider, base.full_asset, work / 'baseline-download')
        report['checks']['baseline_download'] = {'state': 'passed', 'sha256': digest_file(archive),
                                                 'transport': 'anonymous production GitHubReleaseProvider'}
        delta_ok = False
        try:
            install, registry, config, env = new_install(helper, archive, work / 'delta-case', base)
            step('unknown_user_file_rejection', lambda: unknown_file_rejection(
                helper, install, registry, base, target, config, env))
            poison_cache(helper, registry, target.selected_asset)
            report['checks']['corrupted_cache_fixture'] = {'state': 'prepared', 'same_asset_length': True,
                'wrong_sha256': True, 'partial_download_absent': True}
            step('live_delta_replaces_corrupt_cache', lambda: transition(
                helper, install, registry, base, target, config, env))
            report['checks']['corrupted_cache_fixture']['state'] = 'passed'
            step('post_delta_cold_restarts', lambda: cold_restarts(helper, install, registry, target, config, env))
            delta_ok = True
        except BaseException as error:
            report['checks'].setdefault('delta_case', safe_error(error))
        finally:
            helper.stop_owned(work / 'delta-case')
            save()
        full_ok = False
        try:
            install, registry, config, env = new_install(helper, archive, work / 'full-case', base)
            check(not (registry.root / 'cache').exists(), 'Full case must start with an empty cache')
            step('live_full_package_transition', lambda: transition(
                helper, install, registry, base, full, config, env))
            full_ok = True
        except BaseException as error:
            report['checks'].setdefault('full_case', safe_error(error))
        finally:
            helper.stop_owned(work / 'full-case')
        report['state'] = 'passed' if delta_ok and full_ok else 'failed'
    except BaseException as error:
        report.update(safe_error(error))
    finally:
        if helper is not None:
            helper.stop_owned(work)
        report['status'] = report['state']
        save()
        print(json.dumps(report, indent=2))
    return 0 if report['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
