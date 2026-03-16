import os
import ctypes

base = r"c:\Users\jsdfhasuh\my_scripts\python_build_script\dist\ui_main\_internal"
lib = os.path.join(base, 'torch', 'lib')
os.environ['PATH'] = lib + ';' + base + ';' + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(base)
    os.add_dll_directory(lib)

fails = []
for name in sorted([n for n in os.listdir(lib) if n.lower().endswith('.dll')]):
    p = os.path.join(lib, name)
    try:
        ctypes.CDLL(p)
    except OSError as e:
        fails.append((name, str(e)))

print('FAIL_COUNT', len(fails))
for n, e in fails:
    print(n, '=>', e)
