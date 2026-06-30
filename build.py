import argparse
import ast
import glob
import importlib.util
import json
import os
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import List, Set


PYINSTALLER_CMD = [sys.executable, '-m', 'PyInstaller']


@dataclass
class BuildJob:
    label: str
    entry: str
    name: str | None = None
    onefile: bool = True
    console: bool = True
    icon: str | None = None
    add_data: List[str] = field(default_factory=list)
    hidden_imports: List[str] = field(default_factory=list)
    excludes: List[str] = field(default_factory=list)
    collect_binaries: List[str] = field(default_factory=list)
    extra_args: List[str] = field(default_factory=list)
    collect_python_binary: bool = True
    enable_torch_runtime: bool = True


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return expand_config_values(json.load(f))


def expand_config_values(value):
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [expand_config_values(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_config_values(item) for key, item in value.items()}
    return value


def extract_imports_from_file(file_path: str) -> Set[str]:
    """Extract imported top-level modules from a Python file."""
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=file_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except Exception as e:
        print(f"Warning: failed to parse {file_path}: {e}")

    return imports


def get_installed_packages() -> dict:
    """Return installed packages and versions."""
    packages = {}
    freeze = subprocess.run(
        [sys.executable, '-m', 'pip', 'list', '--format=json'],
        capture_output=True,
        text=True,
        check=False,
    )
    if freeze.returncode == 0:
        try:
            pkg_list = json.loads(freeze.stdout)
            for pkg in pkg_list:
                packages[pkg['name'].lower()] = pkg['version']
        except Exception as e:
            print(f"Warning: failed to parse package list: {e}")
    return packages


def analyze_dependencies(entry_file: str, hidden_imports: List[str]) -> None:
    """Analyze and print dependency information."""
    print("\n" + "=" * 70)
    print("Dependency analysis")
    print("=" * 70)

    print(f"\nEntry file: {entry_file}")
    imports = extract_imports_from_file(entry_file)

    if hidden_imports:
        print(f"\nAdditional hidden imports: {len(hidden_imports)}")
        for hi in hidden_imports:
            imports.add(hi.split('.')[0])

    installed_packages = get_installed_packages()

    stdlib_modules = set(sys.builtin_module_names)

    third_party = []
    stdlib = []
    unknown = []

    for imp in sorted(imports):
        imp_lower = imp.lower().replace('_', '-')
        if imp in stdlib_modules:
            stdlib.append(imp)
        elif imp_lower in installed_packages or imp in installed_packages:
            version = installed_packages.get(imp_lower) or installed_packages.get(
                imp, '?'
            )
            third_party.append(f"{imp} ({version})")
        else:
            spec = importlib.util.find_spec(imp)
            if spec and spec.origin:
                if 'site-packages' in spec.origin or 'dist-packages' in spec.origin:
                    third_party.append(f"{imp} (已安装)")
                elif spec.origin.endswith('.py'):
                    unknown.append(f"{imp} (本地)")
                else:
                    stdlib.append(imp)
            else:
                unknown.append(imp)

    print(f"\nThird-party dependencies ({len(third_party)}):")
    if third_party:
        for pkg in third_party:
            print(f"  - {pkg}")
    else:
        print("  (无)")

    print(f"\nStandard library modules ({len(stdlib)}):")
    if stdlib:
        for mod in sorted(stdlib):
            print(f"  - {mod}")
    else:
        print("  (无)")

    if unknown:
        print(f"\nOther modules ({len(unknown)}):")
        for mod in unknown:
            print(f"  - {mod}")

    print("=" * 70 + "\n")


def bool_flag(value: bool, enabled_flag: str, disabled_flag: str = None) -> List[str]:
    flags = []
    if value:
        flags.append(enabled_flag)
    elif disabled_flag:
        flags.append(disabled_flag)
    return flags


def split_add_data(item: str) -> tuple[str, str]:
    if ';' in item:
        source, dest = item.rsplit(';', 1)
    elif ':' in item:
        source, dest = item.rsplit(':', 1)
    else:
        raise ValueError(f'Invalid add_data mapping, expected SOURCE:DEST: {item}')

    if not source or not dest:
        raise ValueError(f'Invalid add_data mapping, expected SOURCE:DEST: {item}')

    return os.path.normpath(source), dest


def normalize_add_data(items: List[str]) -> List[str]:
    # PyInstaller uses the platform path separator between source and destination.
    normalized = []
    for item in items:
        source, dest = split_add_data(item)
        normalized.append(f'{source}{os.pathsep}{dest}')
    return normalized


def validate_file(path: str, label: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f'{label} not found: {path}')


def validate_path(path: str, label: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f'{label} not found: {path}')


def validate_build_paths(entry: str, add_data: List[str], icon: str | None) -> None:
    validate_file(entry, 'Entry script')

    for item in add_data:
        source, _ = split_add_data(item)
        validate_path(source, 'add_data source')

    if icon:
        validate_file(icon, 'Icon')


def get_config_list(cfg: dict, key: str) -> List[str]:
    value = cfg.get(key, []) or []
    if not isinstance(value, list):
        raise ValueError(f'Configuration field "{key}" must be a list')
    return list(value)


def create_build_job(
    cfg: dict,
    label: str,
    default_entry: str | None = None,
    default_name: str | None = None,
    collect_python_binary: bool = True,
    enable_torch_runtime: bool = True,
) -> BuildJob:
    entry = cfg.get('entry', default_entry)
    if not entry:
        raise ValueError(f'Missing "entry" in {label} configuration')

    return BuildJob(
        label=label,
        entry=os.path.normpath(entry),
        name=cfg.get('name', default_name),
        onefile=bool(cfg.get('onefile', True)),
        console=bool(cfg.get('console', True)),
        icon=cfg.get('icon'),
        add_data=get_config_list(cfg, 'add_data'),
        hidden_imports=get_config_list(cfg, 'hidden_imports'),
        excludes=[
            x for x in get_config_list(cfg, 'excludes') if x != 'torch.distributed'
        ],
        collect_binaries=get_config_list(cfg, 'collect_binaries'),
        extra_args=get_config_list(cfg, 'extra_args'),
        collect_python_binary=collect_python_binary,
        enable_torch_runtime=enable_torch_runtime,
    )


def create_main_job(cfg: dict) -> BuildJob:
    return create_build_job(cfg, 'main')


def create_updater_job(cfg: dict) -> BuildJob | None:
    updater_cfg = cfg.get('updater', {}) or {}
    if not updater_cfg.get('enabled', False):
        return None

    return create_build_job(
        updater_cfg,
        'updater',
        default_entry='updater.py',
        default_name='updater',
        collect_python_binary=False,
        enable_torch_runtime=False,
    )


def create_build_jobs(cfg: dict) -> List[BuildJob]:
    jobs = [create_main_job(cfg)]
    updater_job = create_updater_job(cfg)
    if updater_job:
        jobs.append(updater_job)
    return jobs


def _collect_conda_runtime_dlls() -> List[str]:
    """Collect key Conda runtime DLLs that torch/scipy frequently depend on."""
    candidates = [sys.prefix, os.environ.get('CONDA_PREFIX'), sys.base_prefix]
    library_bin = None
    for prefix in candidates:
        if not prefix:
            continue
        candidate = os.path.join(prefix, 'Library', 'bin')
        if os.path.isdir(candidate):
            library_bin = candidate
            break

    if not library_bin:
        return []

    patterns = [
        'mkl*.dll',
        'libiomp*.dll',
        'vcomp140.dll',
        'msvcp*.dll',
        'vcruntime*.dll',
        'concrt140.dll',
        'vccorlib140.dll',
        'tbb*.dll',
        'libifcore*.dll',
        'libifport*.dll',
        'libmmd.dll',
        'svml_dispmd.dll',
    ]
    seen = set()
    dlls: List[str] = []

    for pattern in patterns:
        for path in glob.glob(os.path.join(library_bin, pattern)):
            if os.path.isfile(path) and path not in seen:
                seen.add(path)
                dlls.append(path)

    return dlls


def _ensure_torch_runtime_hook() -> str:
    """Return the runtime hook that adds torch DLL directories early on startup."""
    hook_path = os.path.join(os.path.dirname(__file__), 'pyi_rth_torch_dll.py')
    if not os.path.isfile(hook_path):
        raise FileNotFoundError(f'Torch runtime hook not found: {hook_path}')
    return hook_path


def needs_torch_runtime(job: BuildJob) -> bool:
    if not job.enable_torch_runtime:
        return False

    hidden_roots = {x.split('.')[0] for x in job.hidden_imports}
    return any(x in hidden_roots for x in ('ultralytics', 'torch', 'torchvision'))


def needs_conda_runtime_dlls(job: BuildJob) -> bool:
    hidden_roots = {x.split('.')[0] for x in job.hidden_imports}
    return any(
        x in hidden_roots
        for x in ('ultralytics', 'torch', 'torchvision', 'numpy', 'scipy')
    )


def get_conda_runtime_dest(job: BuildJob) -> str:
    if needs_torch_runtime(job):
        return 'torch/lib'
    return '.'


def append_common_args(
    cmd: List[str], job: BuildJob, clean: bool, specpath: str = None
) -> None:
    if clean:
        cmd.append('--clean')

    if specpath:
        cmd.extend(['--specpath', specpath])

    if job.name:
        cmd.extend(['--name', job.name])

    cmd.extend(bool_flag(job.onefile, '--onefile'))
    cmd.extend(bool_flag(not job.console, '--noconsole'))

    if job.icon:
        cmd.extend(['--icon', job.icon])


def append_data_args(cmd: List[str], job: BuildJob) -> None:
    if job.add_data:
        print(f"\nAdded data files for {job.label}:")
        for data in job.add_data:
            print(f"  - {data}")

    for data in normalize_add_data(job.add_data):
        cmd.append(f'--add-data={data}')


def append_import_args(cmd: List[str], job: BuildJob) -> None:
    for hi in job.hidden_imports:
        cmd.append(f'--hidden-import={hi}')

    if job.excludes:
        print(f"\nExcluded modules for {job.label}:")
        for ex in job.excludes:
            print(f"  - {ex}")

    for ex in job.excludes:
        cmd.append(f'--exclude-module={ex}')


def append_torch_args(
    cmd: List[str],
    job: BuildJob,
    collect_binaries: List[str],
    extra_args: List[str],
) -> None:
    if not needs_torch_runtime(job):
        return

    for mod in ('torch', 'torchvision'):
        if mod not in collect_binaries:
            collect_binaries.append(mod)

    cmd.extend(['--runtime-hook', _ensure_torch_runtime_hook()])

    if '--noupx' not in extra_args:
        cmd.append('--noupx')


def append_binary_args(cmd: List[str], job: BuildJob, collect_binaries: List[str]) -> None:
    for mod in collect_binaries:
        cmd.append(f'--collect-binaries={mod}')

    if needs_conda_runtime_dlls(job):
        conda_dlls = _collect_conda_runtime_dlls()
        if conda_dlls:
            dest = get_conda_runtime_dest(job)
            print(f"\nAdding Conda runtime DLLs for {job.label}: {len(conda_dlls)}")
            for dll in conda_dlls:
                cmd.append(f'--add-binary={dll}{os.pathsep}{dest}')

    if not job.collect_python_binary:
        return

    cmd.append('--collect-binaries=python')

    pythonDll = _find_python_dll()
    if pythonDll:
        cmd.append(f'--add-binary={pythonDll}{os.pathsep}.')
    else:
        print("Warning: python DLL not found; the packaged app may fail to run")


def build_pyinstaller_command(
    job: BuildJob, clean: bool, specpath: str = None
) -> List[str]:
    cmd: List[str] = list(PYINSTALLER_CMD)
    cmd.append('--noconfirm')

    validate_build_paths(job.entry, job.add_data, job.icon)

    collect_binaries = list(job.collect_binaries)
    extra_args = list(job.extra_args)

    append_common_args(cmd, job, clean, specpath)
    append_data_args(cmd, job)
    append_import_args(cmd, job)
    append_torch_args(cmd, job, collect_binaries, extra_args)
    append_binary_args(cmd, job, collect_binaries)

    if extra_args:
        cmd.extend(extra_args)

    cmd.append(job.entry)
    return cmd


def build_command(cfg: dict, clean: bool, specpath: str = None) -> List[str]:
    return build_pyinstaller_command(create_main_job(cfg), clean, specpath)


def build_updater_command(cfg: dict, clean: bool, specpath: str = None) -> List[str]:
    updater_job = create_updater_job(cfg)
    if not updater_job:
        return []
    return build_pyinstaller_command(updater_job, clean, specpath)


def build_job_commands(
    cfg: dict, clean: bool, specpath: str = None
) -> List[tuple[BuildJob, List[str]]]:
    jobs = create_build_jobs(cfg)
    return [
        (job, build_pyinstaller_command(job, clean, specpath))
        for job in jobs
    ]


def copy_updater_to_app_dir(cfg: dict) -> None:
    updater_cfg = cfg.get('updater', {}) or {}
    if not updater_cfg.get('enabled', False):
        return

    app_name = cfg.get('name')
    if not app_name:
        raise ValueError('Missing "name" in configuration')

    updater_name = updater_cfg.get('name', 'updater')
    updater_exe = Path('dist') / f'{updater_name}.exe'
    app_dir = Path('dist') / app_name

    if not app_dir.exists():
        raise FileNotFoundError(f'Application dist directory not found: {app_dir}')
    if not updater_exe.exists():
        raise FileNotFoundError(f'Updater executable not found: {updater_exe}')

    target = app_dir / 'updater.exe'
    shutil.copy2(updater_exe, target)
    print(f'Updater copied to: {target}')


def _find_python_dll() -> str | None:
    candidates = []
    dllName = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    for prefix in {sys.base_prefix, sys.prefix}:
        candidates.append(os.path.join(prefix, dllName))
        candidates.append(os.path.join(prefix, "DLLs", dllName))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def run_command(cmd: List[str]) -> int:
    print('Running:', ' '.join(shlex.quote(x) for x in cmd))
    proc = subprocess.run(cmd)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description='JSON-driven PyInstaller builder')
    parser.add_argument(
        '--config',
        default='configs/training_platform.json',
        help='Path to JSON config',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the PyInstaller command without executing',
    )
    parser.add_argument(
        '--clean', action='store_true', help='Add --clean for PyInstaller'
    )
    parser.add_argument(
        '--specpath', default=None, help='Directory to write .spec (optional)'
    )
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        job_commands = build_job_commands(
            cfg, clean=args.clean, specpath=args.specpath
        )

        if args.dry_run:
            for job, cmd in job_commands:
                print(f'Dry run {job.label} command:')
                print(' '.join(shlex.quote(x) for x in cmd))
            if any(job.label == 'updater' for job, _ in job_commands):
                print('After building, updater.exe will be copied into the app dist dir.')
            return 0

        for _, cmd in job_commands:
            result = run_command(cmd)
            if result != 0:
                return result
        if any(job.label == 'updater' for job, _ in job_commands):
            copy_updater_to_app_dir(cfg)

        return 0
    except FileNotFoundError as exc:
        if getattr(exc, 'filename', None) == 'PyInstaller':
            print('PyInstaller not found. Install it with: pip install pyinstaller')
            return 127
        print(f'Build failed: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
