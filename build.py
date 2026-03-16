import argparse
import ast
import glob
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from typing import List, Set


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_imports_from_file(file_path: str) -> Set[str]:
    """从Python文件中提取所有导入的模块"""
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
        print(f"警告: 无法解析 {file_path}: {e}")

    return imports


def get_installed_packages() -> dict:
    """获取已安装的包列表及其版本"""
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
            print(f"警告: 解析包列表失败: {e}")
    return packages


def analyze_dependencies(entry_file: str, hidden_imports: List[str]) -> None:
    """分析并输出项目的依赖信息"""
    print("\n" + "=" * 70)
    print("📦 依赖分析")
    print("=" * 70)

    # 提取导入
    print(f"\n📄 分析入口文件: {entry_file}")
    imports = extract_imports_from_file(entry_file)

    if hidden_imports:
        print(f"\n🔍 额外的隐藏导入: {len(hidden_imports)} 个")
        for hi in hidden_imports:
            imports.add(hi.split('.')[0])

    # 获取已安装包
    installed_packages = get_installed_packages()

    # 标准库模块
    stdlib_modules = set(sys.builtin_module_names)

    # 分类导入
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
            # 检查是否是本地模块
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

    print(f"\n📚 第三方依赖 ({len(third_party)} 个):")
    if third_party:
        for pkg in third_party:
            print(f"  • {pkg}")
    else:
        print("  (无)")

    print(f"\n🐍 标准库模块 ({len(stdlib)} 个):")
    if stdlib:
        for mod in sorted(stdlib):
            print(f"  • {mod}")
    else:
        print("  (无)")

    if unknown:
        print(f"\n❓ 其他模块 ({len(unknown)} 个):")
        for mod in unknown:
            print(f"  • {mod}")

    print("=" * 70 + "\n")


def bool_flag(value: bool, enabled_flag: str, disabled_flag: str = None) -> List[str]:
    flags = []
    if value:
        flags.append(enabled_flag)
    elif disabled_flag:
        flags.append(disabled_flag)
    return flags


def normalize_add_data(items: List[str]) -> List[str]:
    # PyInstaller expects SOURCE:DEST format on all platforms
    normalized = []
    for item in items:
        # Convert semicolons to colons if needed
        if ';' in item:
            item = item.replace(';', ':')
        normalized.append(item)
    return normalized


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
    """Create a runtime hook that adds torch DLL directories early on startup."""
    hook_path = os.path.join(os.path.dirname(__file__), 'pyi_rth_torch_dll.py')
    hook_code = (
        "import os\n"
        "import sys\n\n"
        "os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')\n"
        "os.environ.setdefault('OMP_WAIT_POLICY', 'PASSIVE')\n\n"
        "base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))\n"
        "candidates = [\n"
        "    base,\n"
        "    os.path.join(base, 'torch', 'lib'),\n"
        "    os.path.join(base, '_internal'),\n"
        "    os.path.join(base, '_internal', 'torch', 'lib'),\n"
        "]\n\n"
        "log_file = os.path.join(os.path.dirname(sys.executable), 'torch_dll_hook.log')\n"
        "def _log(msg):\n"
        "    try:\n"
        "        with open(log_file, 'a', encoding='utf-8') as f:\n"
        "            f.write(msg + '\\n')\n"
        "    except Exception:\n"
        "        pass\n\n"
        "_log('base=' + base)\n"
        "seen = set()\n"
        "for dll_dir in candidates:\n"
        "    if dll_dir in seen:\n"
        "        continue\n"
        "    seen.add(dll_dir)\n"
        "    _log('candidate=' + dll_dir + ' exists=' + str(os.path.isdir(dll_dir)))\n"
        "    if not os.path.isdir(dll_dir):\n"
        "        continue\n"
        "    try:\n"
        "        os.add_dll_directory(dll_dir)\n"
        "        _log('add_dll_directory ok: ' + dll_dir)\n"
        "    except Exception:\n"
        "        _log('add_dll_directory fail: ' + dll_dir)\n"
        "    os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')\n"
        "\n"
        "try:\n"
        "    import ctypes\n"
        "    torch_lib_dirs = [d for d in seen if d.endswith(os.path.join('torch', 'lib')) and os.path.isdir(d)]\n"
        "    for d in torch_lib_dirs:\n"
        "        for name in ('torch_global_deps.dll', 'c10.dll', 'torch_cpu.dll', 'torch_python.dll'):\n"
        "            p = os.path.join(d, name)\n"
        "            if os.path.isfile(p):\n"
        "                try:\n"
        "                    ctypes.CDLL(p)\n"
        "                    _log('preload ok: ' + p)\n"
        "                except OSError as e:\n"
        "                    _log('preload fail: ' + p + ' err=' + str(e))\n"
        "except Exception as e:\n"
        "    _log('preload exception: ' + str(e))\n"
    )

    with open(hook_path, 'w', encoding='utf-8') as f:
        f.write(hook_code)

    return hook_path


def build_command(cfg: dict, clean: bool, specpath: str = None) -> List[str]:
    cmd: List[str] = [sys.executable, '-m', 'PyInstaller']

    entry = cfg.get('entry')
    if not entry:
        raise ValueError('Missing "entry" in configuration')

    name = cfg.get('name')
    onefile = bool(cfg.get('onefile', True))
    console = bool(cfg.get('console', True))
    icon = cfg.get('icon')
    add_data = cfg.get('add_data', []) or []
    hidden_imports = cfg.get('hidden_imports', []) or []
    excludes = cfg.get('excludes', []) or []
    excludes = [x for x in excludes if x != 'torch.distributed']
    collect_binaries = cfg.get('collect_binaries', []) or []
    extra_args = cfg.get('extra_args', []) or []

    if clean:
        cmd.append('--clean')

    if specpath:
        cmd.extend(['--specpath', specpath])

    if name:
        cmd.extend(['--name', name])

    cmd.extend(bool_flag(onefile, '--onefile'))
    cmd.extend(bool_flag(not console, '--noconsole'))

    if icon:
        cmd.extend(['--icon', icon])

    # 输出添加的数据文件
    if add_data:
        print("\n📁 添加的数据文件:")
        for data in add_data:
            print(f"  • {data}")

    for data in normalize_add_data(add_data):
        cmd.append(f'--add-data={data}')

    for hi in hidden_imports:
        cmd.append(f'--hidden-import={hi}')

    # 输出排除的模块
    if excludes:
        print("\n🚫 排除的模块:")
        for ex in excludes:
            print(f"  • {ex}")

    for ex in excludes:
        cmd.append(f'--exclude-module={ex}')

    hidden_roots = {x.split('.')[0] for x in hidden_imports}
    if any(x in hidden_roots for x in ('ultralytics', 'torch', 'torchvision')):
        # Torch on Windows often needs explicit binary collection when frozen.
        for mod in ('torch', 'torchvision'):
            if mod not in collect_binaries:
                collect_binaries.append(mod)

        # Ensure torch native DLL lookup paths are available at process startup.
        cmd.extend(['--runtime-hook', _ensure_torch_runtime_hook()])

        # UPX-compressed torch binaries may fail to initialize on Windows.
        if '--noupx' not in extra_args:
            cmd.append('--noupx')

    for mod in collect_binaries:
        cmd.append(f'--collect-binaries={mod}')

    if any(
        x in hidden_roots
        for x in ('ultralytics', 'torch', 'torchvision', 'numpy', 'scipy')
    ):
        conda_dlls = _collect_conda_runtime_dlls()
        if conda_dlls:
            print(f"\nAdding Conda runtime DLLs: {len(conda_dlls)}")
            for dll in conda_dlls:
                # Keep runtime DLLs next to torch binaries so c10.dll can resolve deps.
                cmd.append(f'--add-binary={dll}{os.pathsep}torch/lib')

    if extra_args:
        cmd.extend(extra_args)

    cmd.append('--collect-binaries=python')

    pythonDll = _find_python_dll()
    if pythonDll:
        cmd.append(f'--add-binary={pythonDll}{os.pathsep}.')
    else:
        print("警告: 未找到 python DLL，可能导致运行失败")

    cmd.append(entry)
    return cmd


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
        '--config', default='pyinstaller_config.json', help='Path to JSON config'
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

    cfg = load_config(args.config)
    cmd = build_command(cfg, clean=args.clean, specpath=args.specpath)

    if args.dry_run:
        print('Dry run command:')
        print(' '.join(shlex.quote(x) for x in cmd))
        return 0

    try:
        return run_command(cmd)
    except FileNotFoundError:
        print('PyInstaller not found. Install it with: pip install pyinstaller')
        return 127


if __name__ == '__main__':
    sys.exit(main())
