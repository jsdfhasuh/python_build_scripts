import os
import sys

os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('OMP_WAIT_POLICY', 'PASSIVE')

base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
candidates = [
    base,
    os.path.join(base, 'torch', 'lib'),
    os.path.join(base, '_internal'),
    os.path.join(base, '_internal', 'torch', 'lib'),
]

log_file = os.path.join(os.path.dirname(sys.executable), 'torch_dll_hook.log')
def _log(msg):
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass

_log('base=' + base)
seen = set()
for dll_dir in candidates:
    if dll_dir in seen:
        continue
    seen.add(dll_dir)
    _log('candidate=' + dll_dir + ' exists=' + str(os.path.isdir(dll_dir)))
    if not os.path.isdir(dll_dir):
        continue
    try:
        os.add_dll_directory(dll_dir)
        _log('add_dll_directory ok: ' + dll_dir)
    except Exception:
        _log('add_dll_directory fail: ' + dll_dir)
    os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')

try:
    import ctypes
    torch_lib_dirs = [d for d in seen if d.endswith(os.path.join('torch', 'lib')) and os.path.isdir(d)]
    for d in torch_lib_dirs:
        for name in ('torch_global_deps.dll', 'c10.dll', 'torch_cpu.dll', 'torch_python.dll'):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                try:
                    ctypes.CDLL(p)
                    _log('preload ok: ' + p)
                except OSError as e:
                    _log('preload fail: ' + p + ' err=' + str(e))
except Exception as e:
    _log('preload exception: ' + str(e))
