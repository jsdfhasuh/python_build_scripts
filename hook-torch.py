"""Keep inspectable Torch source without a duplicate PYZ copy for Vision Train."""

import importlib.util
from pathlib import Path
import runpy


spec = importlib.util.find_spec('_pyinstaller_hooks_contrib')
if spec is None or not spec.origin:
  raise RuntimeError('Vision Train requires the upstream PyInstaller Torch hook')
upstreamPath = Path(spec.origin).parent / 'stdhooks/hook-torch.py'
upstream = runpy.run_path(str(upstreamPath))
if 'module_collection_mode' not in upstream:
  raise RuntimeError('Vision Train source collection requires PyInstaller 6 or newer')
# Preserve upstream binary, data, hidden-import and platform-specific collection.
globals().update({name: value for name, value in upstream.items() if not name.startswith('__')})
upstreamMode = module_collection_mode
module_collection_mode = dict(upstreamMode) if isinstance(upstreamMode, dict) else {}
module_collection_mode['torch'] = 'py'
