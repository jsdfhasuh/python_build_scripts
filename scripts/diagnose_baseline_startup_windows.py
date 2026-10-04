"""No-build, path-only diagnostic of a clean public Windows baseline startup.

Does not modify source, publish, delete unclassified data, or weaken updater checks.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def inventory(root):
    from update_filesystem import io_path, logical_path
    files, directories = {}, set()
    for parent, dirs, names in os.walk(io_path(root), followlinks=False):
        parent = logical_path(parent)
        for name in dirs:
            directories.add((Path(parent) / name).relative_to(root).as_posix())
        for name in names:
            path = Path(parent) / name
            stat = io_path(path).stat()
            files[path.relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return files, directories


def difference(before, after):
    old, old_dirs = before
    new, new_dirs = after
    parents = {p for name in new for p in
               ['/'.join(name.split('/')[:i]) for i in range(1, len(name.split('/')))]}
    return {'added_files': sorted(set(new) - set(old)),
            'removed_files': sorted(set(old) - set(new)),
            'metadata_changed_files': sorted(name for name in set(old) & set(new) if old[name] != new[name]),
            'added_directories': sorted(new_dirs - old_dirs),
            'removed_directories': sorted(old_dirs - new_dirs),
            'empty_directories': sorted(new_dirs - parents)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--baseline-lock', type=Path)
    parser.add_argument('--baseline-tag', default='v1.0.28')
    parser.add_argument('--expected-source-commit', required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Actual Windows required')
    source = args.source_root.resolve()
    work = args.work.resolve()
    if work.exists():
        raise RuntimeError('Refusing an existing work directory')
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != args.expected_source_commit:
        raise RuntimeError('Diagnostic source SHA mismatch')
    sys.path.insert(0, str(source))
    from github_release_provider import GitHubReleaseProvider
    from update_contract import Asset, CONFIG_DEFAULTS, canonical_json
    from update_download import download_asset
    from update_filesystem import io_path
    from update_installation import InstallationRegistry
    from update_package import file_record, inspect_installation, verify_directory
    from update_payload import PayloadArchive
    from update_session import provenance
    from update_storage import atomic_json
    from update_process import ProcessHandle
    from update_diagnostics import read_startup_trace
    import psutil
    import zipfile
    # Reuse only process/environment helpers, never its acceptance main function.
    spec = importlib.util.spec_from_file_location('release_acceptance',
        Path(__file__).with_name('verify_release_transition_windows.py'))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    work.mkdir(parents=True)
    report = {'status': 'running', 'scope': 'actual public baseline startup path-only diagnostic',
              'source_commit': commit, 'baseline_tag': args.baseline_tag, 'snapshots': []}
    try:
        with GitHubReleaseProvider(token='') as provider:
            base = provider.exact_release(args.baseline_tag)
            if args.baseline_lock:
                lock = json.loads(args.baseline_lock.read_bytes())
                helpers.check(lock['id'] == base.release_id and lock['tag'] == base.tag and
                              lock['repository'] == 'jsdfhasuh/emo-vision-train-release', 'Lock mismatch')
                helpers.check(Asset.parse(lock['assets'][base.full_asset.name]) == base.full_asset,
                              'Lock asset changed')
                archive = Path(lock['directory']) / base.full_asset.name
                actual = file_record(archive)
                helpers.check((actual.size, actual.sha256) == (base.full_asset.size, base.full_asset.digest),
                              'Baseline ZIP bytes changed')
            else:
                archive = download_asset(provider, base.full_asset, work / 'download')
        report.update(baseline_build_id=base.identity.build_id, baseline_sha256=base.full_asset.digest)
        with PayloadArchive(archive, base.full_asset, base.manifest, base.manifest, base.identity):
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(io_path(work))
        install, app = work / 'VisionWorkshop', work / 'VisionWorkshop/app'
        verify_directory(app, base.manifest, base.identity)
        registry = InstallationRegistry(install)
        with registry.gate():
            registry.enroll(app, launcher=True)
        registry.register_baseline(app, base.identity, base.manifest, provenance(base))
        for name in base.manifest.files:
            if base.manifest.policy(name).kind == 'preserve_update_config':
                (app / name).write_bytes(canonical_json({**CONFIG_DEFAULTS, 'enabled': False, 'timeout': 37}))
        inspect_installation(app, base.manifest, base.identity)
        before = inventory(app)
        env = helpers.environment(work)
        helpers.spawn_frozen([install / 'VisionWorkshop.exe'], install, env)
        expected_image = os.path.normcase(str(app / 'VisionWorkshopApp.exe'))
        started = time.monotonic()
        identity = None
        for threshold in (5, 15, 30, 60):
            while time.monotonic() - started < threshold:
                time.sleep(.2)
            if identity is None:
                for process in psutil.process_iter(['pid', 'exe']):
                    try:
                        if process.info['exe'] and os.path.normcase(process.info['exe']) == expected_image:
                            with ProcessHandle(process.pid) as handle:
                                identity = handle.identity
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                        pass
            observation = {'seconds_after_launcher': threshold, **difference(before, inventory(app))}
            if identity:
                trace = read_startup_trace(app, identity)
                observation['startup_stages'] = [v['stage'] for v in (trace or {}).get('events', [])]
                try:
                    with ProcessHandle(identity['pid'], identity) as handle:
                        observation['process_alive'] = not handle.exited()
                except OSError:
                    observation['process_alive'] = False
            else:
                observation['process_seen'] = False
            report['snapshots'].append(observation)
            atomic_json(work / 'startup-diagnostic.json', report)
        helpers.stop_owned(work)
        after = inventory(app)
        report['after_stop'] = difference(before, after)
        changed = report['after_stop']['metadata_changed_files']
        report['managed_changed_hashes'] = {
            name: {'official_sha256': base.manifest.files[name].sha256,
                   'actual_sha256': file_record(app / name).sha256}
            for name in changed if name in base.manifest.files}
        try:
            inspect_installation(app, base.manifest, base.identity)
            report['production_inspection'] = {'status': 'passed'}
        except Exception as error:
            report['production_inspection'] = {'status': 'rejected',
                'error_code': getattr(error, 'code', None),
                'message': str(error).replace(str(work), '<isolated-work>')}
        report['status'] = 'diagnosed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__,
                      error=str(error).replace(str(work), '<isolated-work>'))
        raise
    finally:
        helpers.stop_owned(work)
        atomic_json(work / 'startup-diagnostic.json', report)
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
