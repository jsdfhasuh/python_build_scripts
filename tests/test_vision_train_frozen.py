"""Archive and evidence classification tests, not Windows executable acceptance."""

import tempfile
import unittest
from pathlib import Path
import zipfile

from scripts import verify_vision_train_frozen as probe


class FrozenEvidenceTests(unittest.TestCase):
  def test_zip_is_extracted_once_to_separate_directory_and_sizes_are_reported(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      archive = root / 'product.zip'
      with zipfile.ZipFile(archive, 'w') as writer:
        writer.writestr('VisionWorkshop/VisionWorkshop.exe', b'fixture')
        writer.writestr('VisionWorkshop/app/_internal/static/models/test.onnx', b'1234')
      before = archive.read_bytes()
      install, report = probe.extractPackage(archive, root / 'disposable')
      self.assertEqual(install, root / 'disposable/VisionWorkshop')
      self.assertEqual(report['file_count'], 2)
      self.assertEqual(report['uncompressed_bytes'], 11)
      self.assertEqual(report['model_resources'][0]['bytes'], 4)
      self.assertEqual(archive.read_bytes(), before)

  def test_unsafe_and_case_duplicate_zip_members_are_rejected(self):
    for names in (['VisionWorkshop/../escape'], ['VisionWorkshop\\escape'],
                  ['VisionWorkshop/a', 'VisionWorkshop/A']):
      with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        archive = root / 'product.zip'
        with zipfile.ZipFile(archive, 'w') as writer:
          for name in names:
            writer.writestr(name, b'fixture')
        with self.assertRaises((ValueError, RuntimeError)):
          probe.extractPackage(archive, root / 'disposable')
        self.assertFalse((root / 'escape').exists())

  def test_pending_cpu_result_only_qualifies_schema_smoke(self):
    document = {'ok': True, 'phase': 'verify', 'run_id': 'frozen-cpu-smoke',
                'status': 'PENDING', 'samples': [], 'provider': ['CPUExecutionProvider']}
    report = probe.checkMicroReport(document)
    self.assertEqual(report['status'], 'PASS')
    self.assertEqual(report['product_model_qualification'], 'PENDING')
    self.assertEqual(report['checkpoint_restore'], 'NOT_RUN')
    self.assertEqual(report['numerical_parity'], 'NOT_RUN')
    for change in ({'ok': False}, {'status': 'PASS'}, {'provider': ['CUDAExecutionProvider']}):
      with self.subTest(change=change), self.assertRaises(ValueError):
        probe.checkMicroReport({**document, **change})

  def test_dino_inspection_requires_no_imported_training_modules_and_real_inventory(self):
    document = {'environment': {'training_modules_imported': []},
                'files_sha256': 'a' * 64, 'bytes': 123}
    result = probe.checkDinoReport(document, lambda env, provider: provider == 'CPUExecutionProvider')
    self.assertEqual(result['model_inference'], 'NOT_RUN')
    for change in ({'bytes': 0}, {'environment': {'training_modules_imported': ['torch']}}):
      with self.subTest(change=change), self.assertRaises(ValueError):
        probe.checkDinoReport({**document, **change}, lambda *_args: True)
    with self.assertRaises(ValueError):
      probe.checkDinoReport(document, lambda *_args: False)


if __name__ == '__main__':
  unittest.main()
