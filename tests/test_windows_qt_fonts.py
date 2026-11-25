"""Reject empty/tofu font proof and preserve product-only native Qt selection."""

import os
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_vision_train_modular_product import productEnvironment
from scripts.verify_vision_train_modules import cleanEnvironment
from scripts.verify_windows_qt_fonts import pixelDifference
from scripts.verify_windows_qt_fonts import sampleStatus
from scripts.verify_windows_qt_fonts import verifyProcessIdentity


class WindowsQtFontTests(unittest.TestCase):
  def processFixture(self, *, redirected):
    selected = r'C:\runtime\Scripts\python.exe'
    base = r'C:\Python312\python.exe'
    command = [selected, r'C:\repo\verify_windows_qt_fonts.py', '--child', '--output',
               r'C:\reports\fresh-fonts', '--probe-nonce', 'f' * 32]
    launch = {'pid': 202, 'driver_pid': 101, 'driver_base_executable': base,
               'command': command, 'nonce': 'f' * 32,
               'runtime': {'venv': True, 'selected_python': selected, 'prefix': r'C:\runtime',
                           'base_prefix': r'C:\Python312', 'base_executable': base}}
    pid = 303 if redirected else 202
    native = {'pid': pid, 'ppid': 202 if redirected else 101,
               'exe': base if redirected else selected,
               'cmdline': [base if redirected else selected, *command[1:]]}
    parent = {'pid': native['ppid'], 'ppid': 101 if redirected else 99,
               'exe': selected if redirected else base,
               'cmdline': command if redirected else [base, 'parent.py']}
    report = {'pid': pid, 'nonce': launch['nonce'], 'python_version': '3.12.10',
               'executable': selected, 'script_argv': command[1:],
               'native_process': native, 'native_parent': parent,
               'interpreter': {'executable': selected, 'prefix': r'C:\runtime',
                               'base_prefix': r'C:\Python312', 'base_executable': base}}
    return launch, report

  def test_direct_process_identity_requires_actual_image_parent_and_arguments(self):
    launch, report = self.processFixture(redirected=False)
    result = verifyProcessIdentity(report, launch)
    self.assertEqual(result['mode'], 'direct')
    self.assertEqual(result['launcher_pid'], result['interpreter_pid'])
    for change in (lambda value: value['native_process'].update(exe=r'C:\other\python.exe'),
                    lambda value: value['native_process'].update(ppid=999),
                    lambda value: value['native_parent'].update(exe=r'C:\other\python.exe'),
                    lambda value: value['native_process']['cmdline'].append('--extra')):
      invalid = deepcopy(report)
      change(invalid)
      with self.assertRaises(RuntimeError):
        verifyProcessIdentity(invalid, launch)

  def test_single_venv_redirector_retains_both_observed_process_identities(self):
    launch, report = self.processFixture(redirected=True)
    result = verifyProcessIdentity(report, launch)
    self.assertEqual(result['mode'], 'venv-redirector-single-child')
    self.assertNotEqual(result['launcher_pid'], result['interpreter_pid'])
    self.assertEqual(result['native_process']['exe'], launch['runtime']['base_executable'])
    self.assertEqual(result['native_parent']['exe'], launch['runtime']['selected_python'])

  def test_redirector_cannot_hide_an_unrelated_parent_image_or_invocation(self):
    launch, original = self.processFixture(redirected=True)
    changes = {
      'parent_id': lambda value: value['native_parent'].update(pid=998),
      'extra_hop': lambda value: value['native_process'].update(ppid=999),
      'launcher_parent': lambda value: value['native_parent'].update(ppid=999),
      'launcher_image': lambda value: value['native_parent'].update(exe=r'C:\other\python.exe'),
      'launcher_arguments': lambda value: value['native_parent']['cmdline'].append('--extra'),
      'child_image': lambda value: value['native_process'].update(exe=r'C:\other\python.exe'),
      'child_argv0': lambda value: value['native_process']['cmdline'].__setitem__(
        0, launch['runtime']['selected_python']),
      'child_script': lambda value: value['native_process']['cmdline'].__setitem__(1, r'C:\other.py'),
      'child_output': lambda value: value['native_process']['cmdline'].__setitem__(4, r'C:\old-output'),
      'nonce': lambda value: value.update(nonce='0' * 32),
      'script_argv': lambda value: value['script_argv'].__setitem__(0, r'C:\other.py'),
      'python_version': lambda value: value.update(python_version='3.13.0'),
      'bool_pid': lambda value: value.update(pid=True),
      'native_pid': lambda value: value['native_process'].update(pid=999),
    }
    for name, change in changes.items():
      with self.subTest(field=name):
        report = deepcopy(original)
        change(report)
        with self.assertRaises(RuntimeError):
          verifyProcessIdentity(report, launch)
    launch['runtime']['venv'] = False
    with self.assertRaises(RuntimeError):
      verifyProcessIdentity(original, launch)

  def test_interpreter_fields_cannot_claim_a_different_venv_or_base(self):
    launch, original = self.processFixture(redirected=True)
    for field in ('executable', 'prefix', 'base_prefix', 'base_executable'):
      with self.subTest(field=field):
        report = deepcopy(original)
        report['interpreter'][field] = r'C:\different\python.exe'
        with self.assertRaises(RuntimeError):
          verifyProcessIdentity(report, launch)

  def test_text_pixels_exclude_padding_and_report_actual_bounds(self):
    blank = bytes([255] * 32)
    rendered = bytearray(blank)
    rendered[20:24] = bytes([0, 0, 0, 255])
    rendered[28:32] = bytes([0, 0, 0, 0])
    observed = pixelDifference(blank, bytes(rendered), 3, 2, 16)
    self.assertEqual(observed['changed_pixels'], 1)
    self.assertEqual(observed['bounds'], [1, 1, 1, 1])
    self.assertNotEqual(observed['blank_rgba_sha256'], observed['rendered_rgba_sha256'])

  def test_empty_drawing_cannot_pass_with_font_metadata(self):
    pixels = pixelDifference(bytes([255] * 8), bytes([255] * 8), 2, 1, 8)
    self.assertIsNone(pixels['bounds'])
    self.assertEqual(sampleStatus(pixels, [{'font_valid': True, 'indexes': [1, 2]}]), 'FAIL')

  def test_tofu_ink_is_explicitly_unsupported(self):
    pixels = {'changed_pixels': 25}
    self.assertEqual(sampleStatus(pixels, [{'font_valid': True, 'indexes': [1, 0]}]),
                     'UNSUPPORTED')
    self.assertEqual(sampleStatus(pixels, [{'font_valid': False, 'indexes': [1]}]),
                     'UNSUPPORTED')

  def test_real_fallback_glyph_runs_are_accepted_but_empty_runs_are_not(self):
    pixels = {'changed_pixels': 25}
    self.assertEqual(sampleStatus(pixels, [
      {'font_valid': True, 'indexes': [4, 5]}, {'font_valid': True, 'indexes': [36, 42]},
    ]), 'PASS')
    self.assertEqual(sampleStatus(pixels, []), 'FAIL')
    self.assertEqual(sampleStatus(pixels, [{'font_valid': True, 'indexes': []}]), 'FAIL')

  def test_bad_pixel_geometry_is_rejected(self):
    for width, height, stride, payload in [(0, 1, 4, b'abcd'), (2, 1, 4, b'abcd'),
                                           (1, 2, 4, b'abcd')]:
      with self.subTest(width=width, height=height, stride=stride), self.assertRaises(ValueError):
        pixelDifference(payload, payload, width, height, stride)

  def test_native_platform_override_preserves_the_shared_b2_environment(self):
    with tempfile.TemporaryDirectory() as directory:
      output = Path(directory)
      with patch.dict(os.environ, {'SystemRoot': str(output / 'Windows'),
                                   'QT_QPA_PLATFORM': 'offscreen'}):
        shared = cleanEnvironment(output / 'shared')
        product = productEnvironment(output / 'product')
      self.assertEqual(shared['QT_QPA_PLATFORM'], 'offscreen')
      self.assertEqual(product['QT_QPA_PLATFORM'], 'windows')
      for key in ('PYTHONNOUSERSITE', 'PYTHONDONTWRITEBYTECODE', 'HF_HUB_OFFLINE',
                   'HF_DATASETS_OFFLINE', 'YOLO_AUTOINSTALL', 'PATH'):
        self.assertEqual(product[key], shared[key])
      self.assertTrue(Path(product['LOCALAPPDATA']).is_relative_to(output / 'product'))


if __name__ == '__main__':
  unittest.main()
