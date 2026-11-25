"""Reject empty/tofu font proof and preserve product-only native Qt selection."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_vision_train_modular_product import productEnvironment
from scripts.verify_vision_train_modules import cleanEnvironment
from scripts.verify_windows_qt_fonts import pixelDifference
from scripts.verify_windows_qt_fonts import sampleStatus


class WindowsQtFontTests(unittest.TestCase):
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
