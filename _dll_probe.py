import os
import ctypes

p = r"c:\Users\jsdfhasuh\my_scripts\python_build_script\dist\ui_main\_internal\torch\lib\c10.dll"

try:
    ctypes.CDLL(p)
    print('CDLL direct: OK')
except OSError as e:
    print('CDLL direct:', e)

root = r"c:\Users\jsdfhasuh\my_scripts\python_build_script\dist\ui_main\_internal"
tl = os.path.join(root, 'torch', 'lib')
os.environ['PATH'] = tl + ';' + root + ';' + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(root)
    os.add_dll_directory(tl)

try:
    ctypes.CDLL(p)
    print('CDLL with path: OK')
except OSError as e:
    print('CDLL with path:', e)
