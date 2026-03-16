# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import copy_metadata

datas = []
binaries = [('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\vcomp140.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\msvcp140.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\msvcp140_1.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\msvcp140_2.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\msvcp140_atomic_wait.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\msvcp140_codecvt_ids.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\vcruntime140.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\vcruntime140_1.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\vcruntime140_threads.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\concrt140.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\Library\\bin\\vccorlib140.dll', 'torch/lib'), ('C:\\Users\\jsdfhasuh\\.conda\\envs\\white-block-detect-py312\\python312.dll', '.')]
hiddenimports = ['matplotlib', 'aphyt', 'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.uic', 'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'cv2', 'numpy', 'ultralytics', 'altgraph', 'certifi', 'charset_normalizer', 'colorama', 'contourpy', 'cycler', 'filelock', 'fonttools', 'fsspec', 'idna', 'iniconfig', 'Jinja2', 'kiwisolver', 'lap', 'MarkupSafe', 'mpmath', 'networkx', 'opencv-python', 'packaging', 'pefile', 'pillow', 'pluggy', 'polars', 'polars-runtime-32', 'psutil', 'Pygments', 'pyinstaller', 'pyinstaller-hooks-contrib', 'pyparsing', 'PyQt5-Qt5', 'PyQt5_sip', 'python-dateutil', 'pywin32-ctypes', 'PyYAML', 'requests', 'scipy', 'setuptools', 'six', 'sympy', 'torch', 'torchvision', 'typing_extensions', 'ultralytics-thop', 'urllib3', 'wheel']
datas += collect_data_files('ultralytics')
datas += copy_metadata('torch')
datas += copy_metadata('torchvision')
binaries += collect_dynamic_libs('torch')
binaries += collect_dynamic_libs('torchvision')
binaries += collect_dynamic_libs('python')
hiddenimports += collect_submodules('ultralytics')


a = Analysis(
    ['C:\\Users\\jsdfhasuh\\my_files\\my_work\\.worktrees\\yolo-ultralytics\\ui_main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['c:\\Users\\jsdfhasuh\\my_scripts\\python_build_script\\pyi_rth_torch_dll.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ui_main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ui_main',
)
