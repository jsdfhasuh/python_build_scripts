import os
import ctypes

root = r"c:\Users\jsdfhasuh\my_scripts\python_build_script\dist\ui_main\_internal"
tl = os.path.join(root, 'torch', 'lib')
os.environ['PATH'] = tl + ';' + root + ';' + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(root)
    os.add_dll_directory(tl)

def probe(name):
    p = os.path.join(tl, name)
    try:
        ctypes.CDLL(p)
        print('OK ', name)
    except OSError as e:
        print('FAIL', name, e)

print('=== no cv2 first ===')
probe('c10.dll')
probe('torch_cpu.dll')

print('=== import cv2 then probe ===')
import cv2
probe('c10.dll')
probe('torch_cpu.dll')
