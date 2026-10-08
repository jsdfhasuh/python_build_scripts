"""Target-scoped size policy, without importing Torch or compiling the product."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build
from build_config import BuildConfigError
from build_config import getZipLzmaDictionary
from build_config import resolveBuildConfig
import portable_release


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/vision-train/hook-torch.py'


class SlimmingPolicyTests(unittest.TestCase):
  def test_target_keeps_gpu_weights_and_notebook_conversion(self) -> None:
    config = json.loads((ROOT / 'configs/emo-vision-train.json').read_bytes())
    self.assertEqual(config['collect_binaries'], ['torch', 'torchvision'])
    self.assertEqual(config['prepare_source_assets'], 'scripts/prepare_desktop_weights.py')
    self.assertIn('${SOURCE_ROOT}/static:static', config['add_data'])
    self.assertIn('safetensors.torch', config['hidden_imports'])
    self.assertIn('lightning_fabric', config['extra_args'])
    self.assertIn('rfc3987_syntax', config['extra_args'])
    self.assertTrue({'notebook', 'jupyterlab', 'jupyter_server', 'pytest'} <= set(config['excludes']))
    for name in ('torch', 'torch.distributed', 'torchvision', 'onnxruntime', 'timm',
                 'safetensors', 'IPython', 'nbformat', 'jupytext'):
      self.assertNotIn(name, config['excludes'])
    self.assertEqual(portable_release.MAX_ASSET_BYTES, 2147483647)

  def test_hook_directory_is_absolute_in_both_build_paths(self) -> None:
    with patch.dict(os.environ, {'SOURCE_ROOT': str(ROOT / 'fixture-source'),
                               'PACKAGER_ROOT': 'must-not-select-another-hook'}):
      config = build.load_config(str(ROOT / 'configs/emo-vision-train.json'))
      resolved = resolveBuildConfig(ROOT / 'configs/emo-vision-train.json')
    for value in (config, resolved.config):
      arguments = value['extra_args']
      self.assertEqual(Path(arguments[arguments.index('--additional-hooks-dir') + 1]), HOOK.parent)
      self.assertNotIn('--additional-hooks-dir', value['updater']['extra_args'])

  def test_upstream_hook_is_preserved_and_source_collected_once(self) -> None:
    for mode in ('pyz+py', {'torch': 'pyz+py', 'torch.special': 'pyz'}):
      with self.subTest(mode=mode):
        original = {'module_collection_mode': mode, 'binaries': [('cuda.dll', 'torch/lib')],
                    'datas': [('source.py', 'torch')],
                    'hiddenimports': ['torch', 'torch.distributed', 'torch.cuda'],
                    'bindepend_symlink_suppression': ['**/torch/lib/*.so*']}
        with patch('importlib.util.find_spec',
                   return_value=SimpleNamespace(origin=str(ROOT / 'upstream/__init__.py'))), \
             patch('runpy.run_path', return_value=original) as upstream:
          # Execute the local hook without mocking its own top-level runner.
          namespace = {'__file__': str(HOOK), '__name__': 'tested_torch_hook'}
          exec(compile(HOOK.read_bytes(), namespace['__file__'], 'exec'), namespace)
        upstream.assert_called_once_with(str(ROOT / 'upstream/stdhooks/hook-torch.py'))
        self.assertEqual(namespace['module_collection_mode']['torch'], 'pyz+py')
        self.assertEqual(namespace['module_collection_mode']['torch.distributed'], 'py')
        self.assertEqual(namespace['module_collection_mode']['torch.cuda'], 'py')
        for name in ('binaries', 'datas', 'hiddenimports', 'bindepend_symlink_suppression'):
          self.assertEqual(namespace[name], original[name])
        if isinstance(mode, dict):
          self.assertEqual(namespace['module_collection_mode']['torch.special'], 'pyz')
          self.assertEqual(mode['torch'], 'pyz+py')

  def test_missing_upstream_hook_fails_closed(self) -> None:
    with patch('importlib.util.find_spec', return_value=None):
      with self.assertRaisesRegex(RuntimeError, 'upstream'):
        exec(compile(HOOK.read_bytes(), 'hook-torch.py', 'exec'), {})

  def test_dictionary_is_bounded_and_other_targets_keep_default(self) -> None:
    self.assertEqual(getZipLzmaDictionary({}), 64)
    master = json.loads((ROOT / 'configs/emo-master.json').read_bytes())
    self.assertEqual(getZipLzmaDictionary(master), 64)
    for value in (64, 128, 256):
      self.assertEqual(getZipLzmaDictionary({'zip_lzma_dictionary_mib': value}), value)
    for value in (True, None, '256', 0, 512, -1, 64.0):
      with self.subTest(value=value), self.assertRaises(BuildConfigError):
        getZipLzmaDictionary({'zip_lzma_dictionary_mib': value})

  def test_large_dictionary_keeps_unicode_zip_and_memory_retry(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      app = root / 'VisionWorkshop'
      app.mkdir()
      output = root / 'output.zip'
      calls = []
      def run(arguments, **kwargs):
        self.assertFalse(output.exists())
        calls.append(arguments)
        output.write_bytes(b'partial' if len(calls) == 1 else b'complete')
        return subprocess.CompletedProcess(arguments, 8 if len(calls) == 1 else 0)
      with patch('portable_release.shutil.which', return_value='7z'), \
           patch('portable_release.subprocess.run', side_effect=run):
        self.assertEqual(portable_release.compressArchive(app, output, dictionaryMiB=256),
                         'zip/lzma')
      self.assertEqual(len(calls), 2)
      for arguments in calls:
        for option in ('-tzip', '-mm=LZMA', '-mx=9', '-md=256m', '-mcu=on'):
          self.assertIn(option, arguments)
      self.assertIn('-mmt=2', calls[0])
      self.assertIn('-mmt=1', calls[1])


if __name__ == '__main__':
  unittest.main()
