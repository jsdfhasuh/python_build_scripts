"""Collect inspectable Torch submodules once while retaining the PYZ entrypoint."""

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
module_collection_mode = {name: 'py' for name in hiddenimports if name.startswith('torch.')}
if isinstance(upstreamMode, dict):
  module_collection_mode.update(upstreamMode)
# Keep the small initializer in PYZ for the existing frozen-runtime admission gate.
module_collection_mode['torch'] = 'pyz+py'
