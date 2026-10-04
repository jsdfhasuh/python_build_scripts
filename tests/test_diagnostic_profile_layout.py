import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
  'baseline_diagnostic', Path(__file__).resolve().parents[1]
  / 'scripts/diagnose_baseline_startup_windows.py',
)
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTIC)


class DiagnosticProfileTests(unittest.TestCase):
  def test_split_and_native_profiles_remain_distinct(self):
    with tempfile.TemporaryDirectory() as folder:
      root = Path(folder)
      base = {'PATH': 'sanitized', 'HOME': 'inherited', 'USERPROFILE': 'inherited'}
      for layout in ('split', 'original-harness'):
        env = DIAGNOSTIC.diagnosticEnvironment(root / layout, layout, base)
        paths = {key: Path(env[key]) for key in
                 ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP')}
        self.assertEqual(len(set(paths.values())), 6)
        self.assertTrue(all(path.parent == root / layout / 'userdata'
                            for path in paths.values()))
        self.assertTrue(all(path.is_dir() for path in paths.values()))
        self.assertEqual(env['PATH'], 'sanitized')
      for layout in ('native', 'windows-profile'):
        env = DIAGNOSTIC.diagnosticEnvironment(root / layout, layout, base)
        profile = Path(env['USERPROFILE'])
        self.assertEqual(env['HOME'], env['USERPROFILE'])
        self.assertEqual(Path(env['APPDATA']), profile / 'AppData/Roaming')
        self.assertEqual(Path(env['LOCALAPPDATA']), profile / 'AppData/Local')
        self.assertEqual(Path(env['TEMP']), profile / 'AppData/Local/Temp')
        self.assertEqual(env['TEMP'], env['TMP'])
      self.assertEqual(base['HOME'], 'inherited')

  def test_unknown_layout_fails_closed(self):
    with tempfile.TemporaryDirectory() as folder:
      with self.assertRaises(ValueError):
        DIAGNOSTIC.diagnosticEnvironment(Path(folder), 'typo', {})
