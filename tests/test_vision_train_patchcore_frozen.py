"""Fail-closed evidence checks; these tests do not claim real Windows/GPU execution."""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts import verify_vision_train_patchcore_frozen as probe


def numericalEvidence():
  array = {'status': 'PASS', 'max_abs_error': 0.0, 'max_tolerance_ratio': 0.0,
           'atol': 1e-5, 'rtol': 1e-4}
  prediction = {'status': 'PASS', 'decision_equal': True,
                'score': dict(array), 'raw_map': dict(array)}
  return {'ok': True, 'phase': 'verify', 'run_id': 'test-run', 'status': 'PASS',
          'provider': ['CPUExecutionProvider'], 'optimization': 'BASIC',
          'onnxruntime': '1.23.2', 'atol': 1e-5, 'rtol': 1e-4,
          'samples': [{'sha256': 'a' * 64, 'preprocessing': dict(array),
                       'ckpt_compatibility': copy.deepcopy(prediction),
                       'onnx_parity': copy.deepcopy(prediction)}]}


class FrozenPatchcoreEvidenceTests(unittest.TestCase):
  def test_success_requires_complete_numeric_measurements_for_the_exact_sample(self):
    result = probe.checkNumerical(numericalEvidence(), [{'sha256': 'a' * 64}], 'test-run')
    self.assertEqual(result['status'], 'PASS')
    self.assertEqual(result['sample_count'], 1)

  def test_zero_exit_or_success_label_cannot_hide_failure_pending_or_missing_samples(self):
    changes = ({'status': 'FAIL'}, {'status': 'PENDING'}, {'samples': []}, {'ok': False},
               {'run_id': 'different-run'}, {'phase': 'export'}, {'onnxruntime': 'different'},
               {'provider': ['CUDAExecutionProvider', 'CPUExecutionProvider']})
    for change in changes:
      with self.subTest(change=change), self.assertRaises(ValueError):
        probe.checkNumerical({**numericalEvidence(), **change},
                              [{'sha256': 'a' * 64}], 'test-run')
    with self.assertRaises(ValueError):
      probe.checkNumerical(numericalEvidence(), [{'sha256': 'b' * 64}], 'test-run')

  def test_numeric_labels_are_checked_against_errors_decisions_and_tolerances(self):
    for kind in ('failed_map', 'false_decision', 'excess_error', 'nan_error', 'looser_tolerance'):
      document = numericalEvidence()
      prediction = document['samples'][0]['onnx_parity']
      if kind == 'failed_map':
        prediction['raw_map']['status'] = 'FAIL'
      elif kind == 'false_decision':
        prediction['decision_equal'] = False
      elif kind == 'excess_error':
        prediction['score']['max_tolerance_ratio'] = 1.01
      elif kind == 'nan_error':
        prediction['raw_map']['max_abs_error'] = float('nan')
      else:
        prediction['score']['rtol'] = .1
      with self.subTest(kind=kind), self.assertRaises(ValueError):
        probe.checkNumerical(document, [{'sha256': 'a' * 64}], 'test-run')

  def test_export_preserves_bank_and_allows_cpu_fixture_for_matching_cuda_torch_release(self):
    bank = {'shape': [7, 1536], 'sha256': 'a' * 64}
    fixture = {'memory_bank': bank, 'versions': {'torch': '2.10.0+cpu', 'anomalib': '2.5.1'}}
    exported = {'memory_bank': dict(bank),
                'versions': {'torch': '2.10.0+cu128', 'anomalib': '2.5.1', 'onnx': '1.16.0'}}
    self.assertEqual(probe.checkExport(exported, fixture)['status'], 'PASS')
    for change in ({'memory_bank': {**bank, 'sha256': 'b' * 64}},
                   {'memory_bank': {**bank, 'shape': [6, 1536]}},
                   {'versions': {**exported['versions'], 'torch': '2.9.0+cpu'}}):
      with self.subTest(change=change), self.assertRaises(ValueError):
        probe.checkExport({**exported, **change}, fixture)

  def test_reload_uses_exact_final_graph_bytes_and_keeps_final_package_unchanged(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      package = root / 'final'
      package.mkdir()
      (package / 'model.onnx').write_bytes(b'graph fixture')
      (package / 'model.onnx.data').write_bytes(b'external tensor fixture')
      verification = package / 'verification.json'
      verification.write_text('original report', encoding='utf-8')
      entries = [{'path': path.name, 'size': path.stat().st_size,
                  'sha256': probe.smoke.fileHash(path)} for path in package.iterdir()]
      evidence = probe.copyFinalGraph(package, root / 'reload', {'files': entries})
      self.assertEqual(len(evidence), 2)
      self.assertEqual({path.name for path in (root / 'reload').iterdir()},
                        {'model.onnx', 'model.onnx.data'})
      (root / 'reload/verification.json').write_text('fresh process report', encoding='utf-8')
      self.assertEqual(verification.read_text(encoding='utf-8'), 'original report')
      (package / 'model.onnx.data').write_bytes(b'changed')
      with self.assertRaises(ValueError):
        probe.copyFinalGraph(package, root / 'corrupt-reload', {'files': entries})

  @unittest.skipIf(os.name == 'nt', 'Only checks that Linux cannot become Windows acceptance')
  def test_non_windows_is_not_run_and_never_pass(self):
    with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
      output = Path(directory) / 'result'
      code = probe.main(['--zip', str(Path(directory) / 'not-present.zip'),
                         '--source-root', directory, '--output', str(output)])
      report = json.loads((output / 'frozen-patchcore.json').read_bytes())
      self.assertEqual(code, 2)
      self.assertEqual(report['status'], 'NOT_RUN')
      self.assertTrue(all(item['status'] == 'NOT_RUN' for item in report['checks'].values()))
      self.assertEqual(report['GPU_execution'], 'NOT_RUN')
      self.assertFalse(report['build_summary_modified'])


if __name__ == '__main__':
  unittest.main()
