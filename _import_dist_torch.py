import os
import sys

root = r"c:\Users\jsdfhasuh\my_scripts\python_build_script\dist\ui_main\_internal"
lib = os.path.join(root, 'torch', 'lib')
os.environ['PATH'] = lib + ';' + root + ';' + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(root)
    os.add_dll_directory(lib)

# Force import from packaged tree first.
sys.path.insert(0, root)

import torch
print('torch imported:', torch.__version__)
print('torch file:', torch.__file__)
