import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_visionworkshop_modular_release import prepare


class ModularPreviewReleaseTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.root = Path(self.temp.name)
    self.artifacts = self.root / 'artifacts'
    self.artifacts.mkdir()
    self.output = self.root / 'release'
    self.guide = self.root / 'offline-modules.md'
    self.guide.write_text('# Offline install\n', encoding='utf-8')
    self.request = {
      'candidate_run_id': 12345,
      'candidate_run_attempt': 1,
      'candidate_builder_sha': 'b' * 40,
      'app_sha': 'a' * 40,
      'core_version': '1.0.42',
      'max_core_version': '1.1.0',
      'build_id': '1.0.42+preview1',
      'tag_name': 'v1.0.42-preview.1',
      'release_title': 'VisionWorkshop v1.0.42 Preview 1',
      'expected_case_count': 26,
      'release_repo': 'jsdfhasuh/emo-vision-train-release',
    }
    self.request_path = self.root / 'request.json'
    self._create_artifacts()

  def tearDown(self):
    self.temp.cleanup()

  @staticmethod
  def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

  @staticmethod
  def _write_zip(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
      archive.writestr('payload.txt', payload)

  @staticmethod
  def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

  def _create_artifacts(self):
    run, attempt = self.request['candidate_run_id'], self.request['candidate_run_attempt']
    build_dir = self.artifacts / f'visionworkshop-modular-evidence-{run}-{attempt}'
    product_dir = self.artifacts / f'visionworkshop-modular-product-evidence-{run}-{attempt}'
    index_dir = self.artifacts / f'visionworkshop-module-index-{run}-{attempt}'
    core_dir = self.artifacts / f'visionworkshop-core-candidate-{run}-{attempt}'

    identity = {
      'app_sha': self.request['app_sha'],
      'packager_sha': self.request['candidate_builder_sha'],
      'build_id': self.request['build_id'],
    }
    core_manifest_sha = 'c' * 64
    core_path = core_dir / 'VisionWorkshop-Core-1.0.42.zip'
    self._write_zip(core_path, b'core fixture')
    core_archive = {
      'name': core_path.name, 'bytes': core_path.stat().st_size,
      'sha256': self._digest(core_path), 'compression': 'zip/lzma',
    }
    module_ids = [
      'runtime.torch', 'runtime.ort', 'runtime.science', 'runtime.vision',
      'feature.yolo', 'feature.patchcore', 'resource.yolo',
      'resource.patchcore-cnn', 'resource.image-simplification',
      'resource.edgesam', 'resource.patchcore-dino',
    ]
    modules = []
    build_archives = []
    for index, module_id in enumerate(module_ids):
      name = f'{module_id}-1.0.42.zip'
      artifact_dir = self.artifacts / f'visionworkshop-module-{module_id}-{run}-{attempt}'
      archive_path = artifact_dir / name
      self._write_zip(archive_path, module_id.encode())
      digest = self._digest(archive_path)
      manifest_sha = f'{index + 1:064x}'
      descriptor = {
        'name': name, 'bytes': archive_path.stat().st_size,
        'sha256': digest, 'compression': 'zip/lzma',
      }
      modules.append({
        'module_id': module_id, 'version': '1.0.42', 'build': identity,
        'core_versions': {'min': '1.0.42', 'max_exclusive': '1.1.0'},
        'manifest_sha256': manifest_sha, 'archive': descriptor,
      })
      build_archives.append({
        'module_id': module_id, 'bytes': descriptor['bytes'],
        'sha256': digest, 'manifest_sha256': manifest_sha,
      })

    index = {
      'type': 'visionworkshop-module-index',
      'schema_version': 1,
      'protocol_version': 4,
      'module_api': 1,
      'python': {'version': '3.12.10', 'abi': 'cp312', 'platform': 'win_amd64'},
      'asset_count': 12,
      'build': identity,
      'dependency_lock_sha256': 'd' * 64,
      'core': {
        'version': '1.0.42', 'manifest_sha256': core_manifest_sha,
        'archive': core_archive,
      },
      'modules': modules,
      'qualification': {'release': 'NOT_QUALIFIED'},
    }
    index_path = index_dir / 'module-index.json'
    self._write_json(index_path, index)
    index_sha = self._digest(index_path)
    index_bytes = index_path.stat().st_size

    build = {
      'status': 'BUILT',
      'published': False,
      'gpu_hardware': 'NOT_RUN',
      'release_gate': 'NOT_QUALIFIED',
      'source': {'commit': self.request['app_sha']},
      'packager': {'commit': self.request['candidate_builder_sha']},
      'core': {'version': '1.0.42', 'build': identity, 'dependency_lock_sha256': 'd' * 64},
      'core_sha256': core_manifest_sha,
      'core_archive': core_archive,
      'module_archives': build_archives,
      'module_reuse': {'enabled': False},
      'module_index': {
        'bytes': index_bytes, 'sha256': index_sha,
        'verified': True, 'asset_count': 12,
      },
    }
    self._write_json(build_dir / 'modular-candidate/reports/modular-build-summary.json', build)

    product = {
      'status': 'LIMITED',
      'published': False,
      'gpu_hardware': 'NOT_RUN',
      'release_gate': 'NOT_QUALIFIED',
      'cpu_product_fixtures': 'PASS',
      'build': identity,
      'core_sha256': core_manifest_sha,
      'module_reuse': {'enabled': False},
      'module_index': {
        'status': 'PASS', 'sha256': index_sha, 'asset_count': 12,
        'core_sha256': core_manifest_sha,
      },
      'cases': [{'name': f'case-{i}', 'status': 'PASS'} for i in range(26)],
      'core_integrity_checks': [
        {'status': 'PASS', 'missing': [], 'extra': [], 'changed': []}
        for _ in range(12)
      ],
      'limitations': ['Physical GPU execution not qualified'],
    }
    self._write_json(product_dir / 'modular-acceptance/reports/modular-product-summary.json', product)
    self.request_path.write_text(json.dumps(self.request), encoding='utf-8')

  def _prepare(self):
    return prepare(Namespace(
      artifacts_root=self.artifacts,
      request=self.request_path,
      install_guide=self.guide,
      output=self.output,
    ))

  def test_prepares_versioned_preview_assets_only_after_all_identity_checks(self):
    result = self._prepare()
    self.assertEqual(result['status'], 'READY')
    self.assertEqual(result['product_cases'], 26)
    self.assertEqual(result['module_count'], 11)
    self.assertTrue((self.output / 'VisionWorkshop-Core-1.0.42.zip').is_file())
    self.assertTrue((self.output / 'module-index.json').is_file())
    self.assertTrue((self.output / 'INSTALL.md').is_file())
    self.assertTrue((self.output / 'SHA256SUMS.txt').is_file())
    self.assertTrue((self.output / 'product-evidence.zip').is_file())
    self.assertTrue((self.output / 'build-evidence.zip').is_file())

  def test_rejects_any_failed_product_case(self):
    product_dir = self.artifacts / 'visionworkshop-modular-product-evidence-12345-1'
    path = product_dir / 'modular-acceptance/reports/modular-product-summary.json'
    product = json.loads(path.read_text(encoding='utf-8'))
    product['cases'][0]['status'] = 'FAIL'
    self._write_json(path, product)
    with self.assertRaisesRegex(ValueError, 'product case did not pass'):
      self._prepare()

  def test_rejects_module_archive_hash_mismatch(self):
    module_dir = self.artifacts / 'visionworkshop-module-runtime.torch-12345-1'
    archive = next(module_dir.glob('*.zip'))
    archive.write_bytes(b'tampered')
    with self.assertRaisesRegex(ValueError, 'byte count mismatch'):
      self._prepare()

  def test_rejects_candidate_source_identity_mismatch(self):
    build_dir = self.artifacts / 'visionworkshop-modular-evidence-12345-1'
    path = build_dir / 'modular-candidate/reports/modular-build-summary.json'
    build = json.loads(path.read_text(encoding='utf-8'))
    build['source']['commit'] = 'f' * 40
    self._write_json(path, build)
    with self.assertRaisesRegex(ValueError, 'application SHA mismatch'):
      self._prepare()


if __name__ == '__main__':
  unittest.main()
