"""Isolated real-release Windows acceptance. Never operates an existing install.

Tests the released baseline launcher/updater, actual target product startup,
file transaction, configuration preservation, and interrupted recovery. The
idle-product exit handshake is harness-driven, not a product UI-click test.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from unittest.mock import patch
import zipfile


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait_until(callback, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = callback()
        if value:
            return value
        time.sleep(.2)
    raise TimeoutError(description)


def read_json(path):
    return json.loads(path.read_bytes())


def wait_json(path, predicate=lambda value: True, timeout=180):
    def read():
        if not path.exists():
            return None
        value = read_json(path)
        return value if predicate(value) else None
    return wait_until(read, 'Waiting for ' + str(path), timeout)


def stop_owned(root):
    import psutil
    owned = os.path.normcase(str(root.resolve())) + os.sep
    processes = []
    for process in psutil.process_iter(['pid', 'exe']):
        try:
            if process.info['exe'] and os.path.normcase(process.info['exe']).startswith(owned):
                processes.append(process)
                process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(processes, timeout=20)
    for process in alive:
        process.kill()
    psutil.wait_procs(alive, timeout=10)


def environment(work):
    env = os.environ.copy()
    for key in list(env):
        if any(word in key.upper() for word in ('TOKEN', 'PASSWORD', 'SECRET')):
            env.pop(key)
        elif key.upper().startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV')):
            env.pop(key)
    for name in ('APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        destination = work / 'userdata' / name
        destination.mkdir(parents=True, exist_ok=True)
        env[name] = str(destination)
    env.update(QT_QPA_PLATFORM='offscreen', PYINSTALLER_RESET_ENVIRONMENT='1',
               PATH=os.environ['SystemRoot'] + '/System32;' + os.environ['SystemRoot'])
    return env


def spawn_frozen(command, cwd, env):
    return subprocess.Popen([str(value) for value in command], executable=str(command[0]),
                            cwd=cwd, env=env, creationflags=subprocess.CREATE_NO_WINDOW)


def asset_for(path, number):
    record = file_record(path)
    return Asset(number, path.name, record.size, record.sha256)


def target_snapshot(assets, expected_commit, tag, base):
    identity_path = assets / (ASSET_PREFIX + '-release_identity.json')
    manifest_path = assets / (ASSET_PREFIX + '-package_files.json')
    identity = Identity.parse(identity_path.read_bytes())
    manifest = Manifest.parse(manifest_path.read_bytes())
    manifest.bind_identity(identity)
    check(identity.release_tag == tag, 'Wrong target release tag')
    check(read_json(identity_path).get('source', {}).get('commit') == expected_commit,
          'Target source commit is not the requested exact checkout')
    full_path = assets / f'{ASSET_PREFIX}-{identity.build_id}-full.zip'
    full = asset_for(full_path, 900000001)
    descriptors = list(assets.glob('*-delta_descriptor.json'))
    check(len(descriptors) == 1, 'Acceptance requires exactly one real delta descriptor')
    descriptor_path = descriptors[0]
    descriptor = DeltaDescriptor.parse(descriptor_path.read_bytes())
    delta_path = assets / descriptor.zip_name
    selected = asset_for(delta_path, 900000002)
    descriptor.bind(manifest, selected)
    check(descriptor.from_build_id == base.manifest.build_id and
          descriptor.base_files_sha256 == base.manifest.digest, 'Delta is not based on public baseline')
    # Validate both complete archive inventories and metadata before starting any EXE.
    for path, asset, desc in ((full_path, full, None), (delta_path, selected, descriptor)):
        with PayloadArchive(path, asset, base.manifest, manifest, identity, descriptor=desc):
            pass
    snapshot = ReleaseSnapshot(900000000, tag, 'Unpublished exact-build CI acceptance',
        asset_for(identity_path, 900000003), asset_for(manifest_path, 900000004), identity,
        manifest, full, selected, asset_for(descriptor_path, 900000005), descriptor)
    return snapshot, {full: full_path, selected: delta_path}


def extract_baseline(archive_path, work, snapshot):
    # PayloadArchive rejects traversal, links, aliases, duplicate members, bad
    # layout, internal manifest mismatch, and incorrect outer SHA-256.
    with PayloadArchive(archive_path, snapshot.full_asset, snapshot.manifest,
                        snapshot.manifest, snapshot.identity):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(work)
    install = work / 'VisionWorkshop'
    verify_directory(install / 'app', snapshot.manifest, snapshot.identity)
    return install


def customize_config(app, manifest):
    names = [name for name in manifest.files if manifest.policy(name).kind == 'preserve_update_config']
    check(names, 'No mutable update configuration found in real baseline')
    raw = canonical_json({**CONFIG_DEFAULTS, 'enabled': False, 'timeout': 37})
    records = {}
    for name in names:
        (app / name).write_bytes(raw)
        records[name] = (raw, file_identity(app / name))
    return records


def verify_config(app, records):
    for name, (raw, identity) in records.items():
        check((app / name).read_bytes() == raw, 'Mutable config bytes changed: ' + name)
        check(file_identity(app / name) == identity, 'Mutable config identity changed: ' + name)


def prime_cache(registry, paths):
    cache = registry.root / 'cache'
    cache.mkdir(exist_ok=True)
    for asset, path in paths.items():
        if asset.name.endswith('-full.zip'):
            continue  # Delta must succeed; avoid duplicating the multi-GB full asset.
        destination = asset_path(cache, asset)
        shutil.copyfile(path, destination)
        actual = file_record(destination)
        check((actual.size, actual.sha256) == (asset.size, asset.digest), 'Cache copy mismatch')


def interrupted_recovery(source, install, base, target, paths, env, config):
    registry = InstallationRegistry(install)
    directory, request = create_request(registry.app, target, process=current_process())
    # Production launch_session copies and verifies the baseline recovery EXE;
    # defer only its launch while setting up the deterministic crash point.
    with patch('update_session.independent_launch'):
        launch_session(directory)
    tx = FileTransaction(registry.app, directory, request['installation_id'], request['session_id'])
    with PayloadArchive(paths[target.selected_asset], target.selected_asset, base.manifest,
                        target.manifest, target.identity, descriptor=target.descriptor) as archive:
        tx.prepare(base.manifest, base.identity, target.manifest, target.identity, archive.write)
    with registry.gate():
        record = registry.load()
        record['active']['plan_sha256'] = tx.plan_digest
        registry.save(record)
    code = '''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from update_installation import InstallationRegistry
registry = InstallationRegistry(Path(sys.argv[2]))
record = registry.load()
def fault(event, detail):
    if event == 'after_move' and detail['source'] == {'area': 'app', 'path': 'VisionWorkshopApp.exe'}:
        os._exit(71)
with registry.lease(record['installation_id'], 'transaction', exclusive=True):
    with registry.lease(record['installation_id'], 'runtime', exclusive=True):
        registry.transaction(record, fault=fault).apply()
'''
    child = subprocess.run([sys.executable, '-B', '-c', code, str(source), str(install)],
                           cwd=source, check=False, timeout=300)
    check(child.returncode == 71 and not (registry.app / 'VisionWorkshopApp.exe').exists(),
          'Injected interruption did not remove the old executable after durable backup')
    spawn_frozen([install / 'VisionWorkshop.exe'], install, env)
    result = wait_json(directory / 'recovery_result.json', timeout=300)
    check(result.get('install_status') == 'rolled_back', 'Frozen launcher recovery failed')
    check(registry.load()['active'] is None, 'Recovery did not clear active transaction')
    stop_owned(install)
    inspect_installation(registry.app, base.manifest, base.identity)
    verify_config(registry.app, config)
    return {'state': 'passed', 'session_id': request['session_id'],
            'fault': 'separate source transaction process exits after main EXE backup',
            'recovery': 'real released fixed launcher and copied frozen baseline updater',
            'power_loss': 'not-run'}


def find_product_process(app):
    import psutil
    expected = os.path.normcase(str(app / 'VisionWorkshopApp.exe'))
    for process in psutil.process_iter(['pid', 'exe']):
        try:
            if process.info['exe'] and os.path.normcase(process.info['exe']) == expected:
                with ProcessHandle(process.pid) as handle:
                    return handle.identity
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return None


def real_transition(install, base, target, env, config):
    import psutil
    registry = InstallationRegistry(install)
    unchanged = {name: file_identity(registry.app / name) for name, record in base.manifest.files.items()
                 if target.manifest.files.get(name) == record
                 and base.manifest.policy(name).kind == 'immutable'}
    check(unchanged, 'No unchanged immutable files available to test in-place preservation')
    spawn_frozen([install / 'VisionWorkshop.exe'], install, env)
    old_process = wait_until(lambda: find_product_process(registry.app), 'Baseline product process', 180)
    def old_started():
        trace = read_startup_trace(registry.app, old_process)
        if not trace:
            return None
        stages = [item['stage'] for item in trace['events']]
        check('FAILED' not in stages, 'Baseline startup failed')
        return trace if 'CREATING_WINDOW' in stages else None
    baseline_trace = wait_until(old_started, 'Real baseline GUI construction', 180)
    time.sleep(5)
    with ProcessHandle(old_process['pid'], old_process) as handle:
        check(not handle.exited(), 'Baseline product exited during startup smoke')
    directory, request = create_request(registry.app, target, process=old_process)
    def launch(command, cwd):
        return spawn_frozen([*command, '--exit-when-finished'], cwd, env)
    with patch('update_session.independent_launch', side_effect=launch):
        updater = launch_session(directory)
    wait_json(directory / 'updater_status.json', lambda value: value.get('state') == 'WAITING_EXIT')
    # This is a brand-new, empty-userdata test installation with no jobs started.
    # Exercise the production process wait/transaction while labeling the idle
    # handoff as harness-driven; this does not validate application task draining.
    atomic_json(directory / 'app_command.json', command_message(request, 1, 'APP_QUIESCED',
        occupants=[old_process], checks={'writers_stopped': True, 'tasks_safe': True,
                                       'models_restored': True, 'paths_checked': True}))
    wait_json(directory / 'updater_status.json', lambda value: value.get('quiescence'))
    atomic_json(directory / 'app_command.json', command_message(request, 2, 'EXIT_APPROVED'))
    wait_json(directory / 'updater_status.json', lambda value: value.get('exit_accepted'))
    with ProcessHandle(old_process['pid'], old_process) as handle:
        check(not handle.exited(), 'Baseline exited before approved handoff')
    process = psutil.Process(old_process['pid'])
    process.terminate()
    process.wait(timeout=30)
    result = wait_json(directory / 'result.json', timeout=600)
    check(result.get('state') == 'SUCCESS' and result.get('launch_status') == 'confirmed',
          'Real updater failed: ' + json.dumps({key: result.get(key) for key in
             ('state', 'error_code', 'install_status', 'launch_status', 'rollback_status')}))
    ready = wait_json(directory / 'app_ready.json')
    check(ready.get('build_id') == target.identity.build_id, 'Target GUI-ready identity mismatch')
    with ProcessHandle(ready['process']['pid'], ready['process']) as handle:
        check(not handle.exited(), 'Target product is not alive after confirmation')
    def permitted():
        trace = read_startup_trace(registry.app, ready['process'])
        return trace if trace and any(event['stage'] == 'RUN_ALLOWED' for event in trace['events']) else None
    target_trace = wait_until(permitted, 'Target product runtime permission', 120)
    updater.wait(timeout=45)
    check(updater.returncode == 0, 'Frozen updater returned nonzero')
    # Stop only this isolated product after collecting genuine production startup evidence.
    stop_owned(install)
    inspect_installation(registry.app, target.manifest, target.identity)
    verify_config(registry.app, config)
    for name, identity in unchanged.items():
        check(file_identity(registry.app / name) == identity, 'Reused file identity changed: ' + name)
    plan = read_json(directory / 'plan.json')
    check(plan.get('unchanged_copy_bytes') == 0, 'Updater copied unchanged payload')
    check(Identity.parse((registry.app / 'release_identity.json').read_bytes()).raw == target.identity.raw,
          'Installed release identity differs from tested target')
    return {'state': 'passed', 'session_id': request['session_id'], 'package_kind': target.package_kind,
            'unchanged_files_preserved': len(unchanged), 'unchanged_copy_bytes': 0,
            'prepared_bytes': plan['prepared_bytes'], 'configuration_files_preserved': list(config),
            'baseline_startup_stages': [item['stage'] for item in baseline_trace['events']],
            'target_startup_stages': [item['stage'] for item in target_trace['events']],
            'target_gui_ready': True, 'target_launch_confirmed': True,
            'handoff': 'harness-mediated approved exit of isolated idle real baseline product',
            'interactive_ui_quiescence': 'not-run', 'GPU_training': 'not-run'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--baseline-lock', type=Path)
    parser.add_argument('--baseline-tag', default='v1.0.28')
    parser.add_argument('--target-tag', default='v1.0.29')
    args = parser.parse_args()
    check(os.name == 'nt', 'This acceptance harness requires Windows; no substitute pass')
    args.source_root = args.source_root.resolve()
    args.assets = args.assets.resolve()
    args.work = args.work.resolve()
    check(not args.work.exists(), '--work must be a new isolated directory')
    commit = subprocess.check_output(['git', '-C', str(args.source_root), 'rev-parse', 'HEAD'],
                                     text=True).strip()
    check(commit == args.expected_source_commit, 'Source checkout changed from expected commit')
    args.work.mkdir(parents=True)
    sys.path.insert(0, str(args.source_root))
    global Asset, ASSET_PREFIX, CONFIG_DEFAULTS, Identity, Manifest, DeltaDescriptor, canonical_json
    global GitHubReleaseProvider, ReleaseSnapshot, PayloadArchive, FileTransaction, InstallationRegistry
    global file_record, file_identity, verify_directory, inspect_installation, asset_path
    global create_request, launch_session, current_process, ProcessHandle, atomic_json
    global command_message, read_startup_trace
    from update_contract import Asset, ASSET_PREFIX, CONFIG_DEFAULTS, Identity, Manifest, DeltaDescriptor, canonical_json
    from github_release_provider import GitHubReleaseProvider, ReleaseSnapshot
    from update_payload import PayloadArchive
    from update_file_transaction import FileTransaction
    from update_installation import InstallationRegistry
    from update_package import file_record, verify_directory, inspect_installation
    from update_filesystem import file_identity
    from update_download import asset_path, download_asset
    from update_session import create_request, launch_session, provenance
    from update_process import current_process, ProcessHandle
    from update_storage import atomic_json
    from update_protocol import command_message
    from update_diagnostics import read_startup_trace
    report = {'state': 'running', 'scope': 'real release transition in isolated Windows installation',
              'source_commit': commit, 'baseline_tag': args.baseline_tag, 'target_tag': args.target_tag,
              'successive_upgrade': 'not-run; only one published baseline-to-target pair',
              'power_loss': 'not-run', 'fixture_acceptance': 'reported separately',
              'target_transport': 'verified local prepublication artifacts with synthetic asset IDs'}
    started = time.monotonic()
    try:
        with GitHubReleaseProvider(token='') as provider:
            base = provider.exact_release(args.baseline_tag)
            if args.baseline_lock:
                lock = read_json(args.baseline_lock)
                check(lock.get('repository') == 'jsdfhasuh/emo-vision-train-release' and
                      lock.get('id') == base.release_id and lock.get('tag') == base.tag,
                      'Baseline lock does not match current public release')
                check(lock.get('full_name') == base.full_asset.name, 'Baseline lock full name changed')
                archive = Path(lock['directory']) / base.full_asset.name
                check(Asset.parse(lock['assets'][base.full_asset.name]) == base.full_asset,
                      'Frozen baseline asset metadata differs from public release')
                actual = file_record(archive)
                check((actual.size, actual.sha256) == (base.full_asset.size, base.full_asset.digest),
                      'Reused baseline download SHA-256/size mismatch')
            else:
                archive = download_asset(provider, base.full_asset, args.work / 'baseline-download')
        target, paths = target_snapshot(args.assets, commit, args.target_tag, base)
        report.update(baseline_build_id=base.identity.build_id, target_build_id=target.identity.build_id,
                      baseline_full_sha256=base.full_asset.digest, target_manifest_sha256=target.manifest.digest,
                      target_full_sha256=target.full_asset.digest, target_delta_sha256=target.selected_asset.digest,
                      automatic_delta_eligible=target.selected_asset.size * 100 < target.full_asset.size * 80,
                      baseline_download=('reused CI-downloaded public ZIP; anonymous metadata recheck and full SHA-256 verified'
                                         if args.baseline_lock else
                                         'anonymous production GitHubReleaseProvider + download_asset SHA-256 verified'))
        install = extract_baseline(archive, args.work, base)
        registry = InstallationRegistry(install)
        with registry.gate():
            registry.enroll(registry.app, launcher=True)
        registry.register_baseline(registry.app, base.identity, base.manifest, provenance(base))
        config = customize_config(registry.app, base.manifest)
        prime_cache(registry, paths)
        env = environment(args.work)
        report['interrupted_recovery'] = interrupted_recovery(args.source_root, install, base, target,
                                                              paths, env, config)
        atomic_json(args.work / 'acceptance.json', report)
        report['transition'] = real_transition(install, base, target, env, config)
        check(report['automatic_delta_eligible'], 'Delta passes forced application but production selection would use full')
        report['state'] = 'passed'
    except BaseException as error:
        report.update(state='failed', error_type=type(error).__name__, error=str(error))
        traceback.print_exc()
        raise
    finally:
        stop_owned(args.work)
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report['status'] = report['state']
        atomic_json(args.work / 'acceptance.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
