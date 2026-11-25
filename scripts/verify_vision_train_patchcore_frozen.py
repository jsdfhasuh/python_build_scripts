"""Numerically exercise a real frozen Windows PatchCore with an explicit synthetic fixture."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from scripts import verify_vision_train_frozen as smoke


WORKER_FLAG = '--cnn-patchcore-onnx-worker'
WEIGHTS_PATH = 'static/models/patchcore_wide_resnet50_2.racm_in1k.safetensors'
FIXTURE_SCOPE = ('Synthetic fitted-state fixture: pinned offline WideResNet weights, '
                 'seven artificial memory-bank rows and two generated RGB images; '
                 'no training, calibration, user data or business-model quality measurement')


def readDocument(path: Path) -> dict:
  return json.loads(path.read_bytes())


def rejectNetwork(*_args, **_kwargs):
  raise RuntimeError('Fixture generation must remain offline')


def prepareFixture(sourceRoot: Path, weights: Path, destination: Path) -> dict:
  """Use real Anomalib state and preprocessing objects, matching the native integration fixture."""
  if sys.version_info[:2] != (3, 12):
    raise RuntimeError('The fixture interpreter must be Python 3.12')
  socket.socket.connect = socket.create_connection = rejectNetwork
  sys.path.insert(0, str(sourceRoot))
  import numpy as np
  from PIL import Image
  import torch
  from anomalib.models import Patchcore
  from anomaly_func.cnn_onnx_artifacts import PARAMETERS
  from anomaly_func.pretrained_weights import load_bundled_pretrained_weights
  from anomaly_func.pretrained_weights import verify_pretrained_weights

  versions = {name: importlib.metadata.version(name) for name in
              ('torch', 'torchvision', 'numpy', 'anomalib', 'timm', 'safetensors')}
  if (versions['torch'].split('+')[0] != '2.10.0' or versions['anomalib'] != '2.5.1'
      or versions['numpy'] != '2.0.2' or versions['timm'] != '1.0.27'):
    raise ValueError('Fixture dependencies differ from the CP312 runtime profile: ' + str(versions))
  verify_pretrained_weights(weights)
  destination.mkdir()
  torch.set_num_threads(2)
  torch.manual_seed(17)
  params = {'backbone': 'wide_resnet50_2', 'layers': ['layer2', 'layer3'],
            'pre_trained': False, 'coreset_sampling_ratio': .1, 'num_neighbors': 3}
  native = Patchcore(**params, post_processor=False, evaluator=False, visualizer=False,
                     pre_processor=Patchcore.configure_pre_processor(image_size=(64, 64)))
  native = native.cpu().eval()
  load_bundled_pretrained_weights(native, weights)
  # The bundled loader records pre_trained=True in hparams after disabling downloads.
  params = {key: native.hparams[key] for key in PARAMETERS if key != 'image_size'}
  params['image_size'] = 64
  torch.manual_seed(17)
  native.model.memory_bank = torch.randn(7, sum(native.model.feature_extractor.out_dims))
  native._is_fitted.fill_(True)
  bank = native.model.memory_bank.detach().cpu().numpy()
  bankEvidence = {'shape': list(bank.shape),
                  'sha256': hashlib.sha256(bank.tobytes()).hexdigest()}
  checkpoint = destination / 'synthetic.ckpt'
  torch.save({'hyper_parameters': dict(native.hparams), 'state_dict': native.state_dict()},
             checkpoint)
  samples = []
  for index, shape in enumerate(((81, 97, 3), (97, 81, 3))):
    path = destination / f'image-{index}.png'
    pixels = np.random.default_rng(17 + index).integers(0, 255, shape, dtype=np.uint8)
    Image.fromarray(pixels).save(path)
    samples.append({'path': str(path), 'sha256': smoke.fileHash(path)})
  source = {'paths': {'model': str(checkpoint)},
            'hashes': {'model': smoke.fileHash(checkpoint)}, 'params': params,
            'identity': {}, 'model_threshold': 1000.0}
  return {'scope': FIXTURE_SCOPE, 'source': source, 'samples': samples,
          'memory_bank': bankEvidence, 'versions': versions, 'python': sys.version,
          'weights': {'name': weights.name, 'bytes': weights.stat().st_size,
                      'sha256': smoke.fileHash(weights)},
          'threshold_origin': 'Fixed synthetic 1000.0; not calibrated',
          'fitted_state_origin': 'Synthetic _is_fitted=True; no training was performed'}


def runFixture(python: Path, source: Path, weights: Path, work: Path, output: Path,
               env: dict, timeout: int) -> dict:
  resultPath = output / 'fixture.json'
  command = [str(python), '-I', '-B', '-X', 'utf8', str(Path(__file__).resolve()),
             '--prepare-fixture', '--source-root', str(source), '--weights', str(weights),
             '--destination', str(work / 'fixture'), '--report', str(resultPath)]
  started = time.monotonic()
  record = {'command': command, 'status': 'FAIL'}
  try:
    with (output / 'fixture.stdout.txt').open('w', encoding='utf-8') as stdout, \
         (output / 'fixture.stderr.txt').open('w', encoding='utf-8') as stderr:
      # This source-only child creates no workers; subprocess.run kills it on timeout.
      result = subprocess.run(command, cwd=work, env=env, stdout=stdout, stderr=stderr,
                              timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    record['exit_code'] = result.returncode
    if result.returncode:
      raise RuntimeError('Fixture preparation failed; see fixture.stderr.txt')
    record['status'] = 'PASS'
    return readDocument(resultPath)
  finally:
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    smoke.writeReport(output / 'fixture.process.json', record)


def runWorker(app: Path, job: dict, name: str, work: Path, output: Path,
              env: dict, helper, timeout: int) -> dict:
  requestPath, resultPath = output / (name + '.job.json'), output / (name + '.worker.json')
  smoke.writeReport(requestPath, job)
  command = [str(app / 'VisionWorkshopApp.exe'), WORKER_FLAG,
             '--job', str(requestPath), '--report', str(resultPath)]
  started = time.monotonic()
  record = {'command': command, 'status': 'FAIL'}
  try:
    with (output / (name + '.stdout.txt')).open('w', encoding='utf-8') as stdout, \
         (output / (name + '.stderr.txt')).open('w', encoding='utf-8') as stderr:
      child = subprocess.Popen(command, cwd=app, env=env, stdout=stdout, stderr=stderr,
                               creationflags=subprocess.CREATE_NO_WINDOW)
      record['pid'] = child.pid
      try:
        code = child.wait(timeout=timeout)
      except subprocess.TimeoutExpired:
        record['status'] = 'TIMEOUT'
        helper.stop_owned(work)
        child.wait(timeout=10)
        raise
    record['exit_code'] = code
    if code:
      raise RuntimeError(f'{name} exited with {code}; see its worker report and stderr')
    record['status'] = 'EXITED_ZERO'
    result = readDocument(resultPath)
    if (result.get('ok') is not True or result.get('run_id') != job['run_id']
        or result.get('phase') != job['phase']):
      raise ValueError(f'{name} returned failed or mismatched worker evidence')
    return result
  finally:
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    smoke.writeReport(output / (name + '.process.json'), record)


def checkExport(document: dict, fixture: dict) -> dict:
  if document.get('memory_bank') != fixture['memory_bank']:
    raise ValueError('Frozen checkpoint restoration/export changed the synthetic memory bank')
  versions = document.get('versions', {})
  if (versions.get('torch', '').split('+')[0] != fixture['versions']['torch'].split('+')[0]
      or versions.get('anomalib') != fixture['versions']['anomalib']
      or versions.get('onnx') != '1.16.0'):
    raise ValueError('Frozen export and fixture dependency versions do not match the profile')
  return {'status': 'PASS', 'memory_bank': document['memory_bank'], 'versions': versions,
          'scope': 'Frozen native CKPT strict restoration and complete ONNX graph export'}


def checkArrayComparison(document: dict) -> None:
  if document.get('status') != 'PASS':
    raise ValueError('Numerical array comparison did not pass')
  for name in ('max_abs_error', 'max_tolerance_ratio'):
    value = document.get(name)
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
      raise ValueError('Numerical comparison has missing or invalid measurements')
  if (document['max_tolerance_ratio'] > 1 or document.get('atol') != 1e-5
      or document.get('rtol') != 1e-4):
    raise ValueError('Numerical measurements do not meet the product tolerance')


def checkNumerical(document: dict, samples: list[dict], runId: str) -> dict:
  if (document.get('ok') is not True or document.get('phase') != 'verify'
      or document.get('run_id') != runId or document.get('status') != 'PASS'
      or document.get('provider') != ['CPUExecutionProvider']
      or document.get('optimization') != 'BASIC' or document.get('onnxruntime') != '1.23.2'
      or document.get('atol') != 1e-5 or document.get('rtol') != 1e-4):
    raise ValueError('Frozen numerical verification requires actual CPU PASS, not exit code alone')
  rows = document.get('samples')
  if (not samples or not isinstance(rows, list) or len(rows) != len(samples)
      or [row.get('sha256') for row in rows] != [sample['sha256'] for sample in samples]):
    raise ValueError('Frozen numerical verification has missing or mismatched samples')
  for row in rows:
    checkArrayComparison(row.get('preprocessing', {}))
    for name in ('ckpt_compatibility', 'onnx_parity'):
      comparison = row.get(name, {})
      if comparison.get('status') != 'PASS' or comparison.get('decision_equal') is not True:
        raise ValueError(name + ' did not pass raw-score/map/decision comparison')
      for field in ('score', 'raw_map'):
        checkArrayComparison(comparison.get(field, {}))
  return {'status': 'PASS', 'sample_count': len(rows), 'provider': document['provider'],
          'onnxruntime': document['onnxruntime'], 'samples': rows,
          'scope': 'Synthetic preprocessing, native CKPT/stable graph and ORT raw score/map parity'}


def finalizePackage(package: Path, fixture: dict, exported: dict, verified: dict) -> dict:
  from anomaly_func.cnn_onnx_artifacts import PROFILE
  from anomaly_func.cnn_onnx_artifacts import inventory
  from anomaly_func.cnn_onnx_artifacts import source_binding
  from anomaly_func.cnn_onnx_artifacts import validate_package
  from anomaly_func.cnn_onnx_templates import PREDICT_SOURCE
  from anomaly_func.cnn_onnx_templates import PREPROCESS_SOURCE

  source = fixture['source']
  (package / 'predict.py').write_text(PREDICT_SOURCE, encoding='utf-8')
  (package / 'preprocess.py').write_text(PREPROCESS_SOURCE, encoding='utf-8')
  smoke.writeReport(package / 'threshold.json',
                    {'threshold': source['model_threshold'], 'decision_rule': 'score_gte_threshold'})
  (package / 'README.txt').write_text(FIXTURE_SCOPE + '\nCPU synthetic validation only.\n',
                                     encoding='utf-8')
  document = {'schema': 'cnn_onnx_v1', 'profile': PROFILE, 'status': verified['status'],
              'source': source_binding(source), 'memory_bank': exported['memory_bank'],
              'runtime': {'export': exported['versions'], 'onnxruntime': verified['onnxruntime'],
                          'provider': 'CPUExecutionProvider', 'optimization': 'BASIC',
                          'location': 'local'}, 'files': inventory(package)}
  smoke.writeReport(package / 'deployment.json', document)
  return validate_package(package, source=source, require_pass=True)


def copyFinalGraph(package: Path, target: Path, manifest: dict) -> list[dict]:
  """Reload the exact final graph bytes in a new scratch directory; preserve the final inventory."""
  entries = {row['path']: row for row in manifest['files']}
  required = ('model.onnx', 'model.onnx.data')
  if any(name not in entries for name in required):
    raise ValueError('Full exported ONNX graph and external tensor data are required')
  target.mkdir()
  evidence = []
  for name in required:
    origin, copy = package / name, target / name
    entry = entries[name]
    if (origin.is_symlink() or not origin.is_file() or origin.stat().st_size != entry['size']
        or smoke.fileHash(origin) != entry['sha256']):
      raise ValueError('Final graph content changed before fresh-process reload')
    shutil.copyfile(origin, copy)
    if copy.stat().st_size != entry['size'] or smoke.fileHash(copy) != entry['sha256']:
      raise ValueError('Reload graph copy differs from the final output')
    evidence.append(dict(entry))
  return evidence


def retainReference(work: Path, fixture: dict, output: Path) -> None:
  target = output / 'reference'
  target.mkdir()
  shutil.copyfile(work / 'reference.json', target / 'reference.json')
  for index, sample in enumerate(fixture['samples']):
    shutil.copyfile(sample['path'], target / f'image-{index}.png')
    for name in ('tensor', 'score', 'map'):
      filename = f'{index}-{name}.npy'
      shutil.copyfile(work / filename, target / filename)


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--zip', type=Path, required=True, dest='archive')
  parser.add_argument('--source-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--fixture-python', type=Path, default=Path(sys.executable))
  parser.add_argument('--timeout-seconds', type=int, default=1800)
  args = parser.parse_args(argv)
  args.archive, args.source_root, args.output, args.fixture_python = (
    path.resolve() for path in (args.archive, args.source_root, args.output, args.fixture_python))
  args.output.mkdir(parents=True, exist_ok=False)
  checkNames = ('launcher_observation', 'fixture_preparation', 'checkpoint_export',
                'onnx_numerical_parity', 'deployment_inventory', 'fresh_process_reload')
  report = {'status': 'FAIL', 'scope': FIXTURE_SCOPE,
            'checks': {name: {'status': 'NOT_RUN'} for name in checkNames},
            'fixture_is_business_model': False, 'training_acceptance': 'NOT_RUN',
            'business_model_numerical_acceptance': 'NOT_RUN', 'GPU_execution': 'NOT_RUN',
            'interactive_GUI': 'NOT_RUN', 'product_UI_model_import': 'NOT_RUN',
            'standalone_predict_py_execution': 'NOT_RUN', 'build_summary_modified': False}
  started = time.monotonic()
  activeCheck = None
  try:
    if os.name != 'nt':
      report.update(status='NOT_RUN', reason='Actual Windows frozen workers are required')
      return 2
    if args.timeout_seconds <= 0:
      raise ValueError('Timeout must be positive')
    report['archive'] = {'name': args.archive.name, 'bytes': args.archive.stat().st_size,
                         'sha256': smoke.fileHash(args.archive)}
    helper = smoke.loadHelpers(args.source_root)
    with tempfile.TemporaryDirectory(prefix='vision-train-patchcore-',
                                     dir=os.environ.get('RUNNER_TEMP')) as directory:
      work = Path(directory)
      try:
        install, inventory = smoke.extractPackage(args.archive, work / 'unpacked')
        report['archive'].update(inventory)
        app = install / 'app'
        identity = readDocument(app / 'release_identity.json')
        sourceCommit = subprocess.check_output(
          ['git', '-C', str(args.source_root), 'rev-parse', 'HEAD'], text=True).strip()
        if identity.get('source', {}).get('commit') != sourceCommit:
          raise ValueError('Source checkout differs from the frozen build identity')
        report.update(build_identity=identity, source_commit=sourceCommit,
                      executable_sha256=smoke.fileHash(app / 'VisionWorkshopApp.exe'))
        env = helper.environment(work)
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', YOLO_AUTOINSTALL='false')
        checks = report['checks']
        activeCheck = 'launcher_observation'
        checks['launcher_observation'] = smoke.observeLauncher(
          install, work, args.output, env, helper, min(args.timeout_seconds, 180))
        if checks['launcher_observation']['status'] != 'PASS':
          raise RuntimeError('Normal isolated launcher initialization did not pass')
        activeCheck = 'fixture_preparation'
        fixture = runFixture(args.fixture_python, args.source_root,
                             app / '_internal' / WEIGHTS_PATH, work, args.output,
                             env, args.timeout_seconds)
        report['fixture'] = fixture
        checks['fixture_preparation'] = {'status': 'PASS', 'scope': FIXTURE_SCOPE}
        package = args.output / 'deployment'
        package.mkdir()
        job = {'source': fixture['source'], 'checkpoint': fixture['source']['paths']['model'],
               'samples': fixture['samples'], 'work': str(work), 'package': str(package),
               'trusted_source': True, 'location': 'local'}
        activeCheck = 'checkpoint_export'
        exportJob = {**job, 'phase': 'export', 'run_id': uuid.uuid4().hex}
        exported = runWorker(app, exportJob, 'ckpt-export', work, args.output,
                             env, helper, args.timeout_seconds)
        checks['checkpoint_export'] = checkExport(exported, fixture)
        retainReference(work, fixture, args.output)
        activeCheck = 'onnx_numerical_parity'
        verifyJob = {**job, 'phase': 'verify', 'run_id': uuid.uuid4().hex}
        verified = runWorker(app, verifyJob, 'onnx-parity', work, args.output,
                             env, helper, args.timeout_seconds)
        checks['onnx_numerical_parity'] = checkNumerical(
          verified, fixture['samples'], verifyJob['run_id'])
        activeCheck = 'deployment_inventory'
        manifest = finalizePackage(package, fixture, exported, verified)
        checks['deployment_inventory'] = {'status': 'PASS', 'manifest': manifest}
        reloadRoot = work / 'reload-package'
        graphEvidence = copyFinalGraph(package, reloadRoot, manifest)
        activeCheck = 'fresh_process_reload'
        reloadJob = {**job, 'package': str(reloadRoot), 'phase': 'verify',
                     'run_id': uuid.uuid4().hex}
        reloaded = runWorker(app, reloadJob, 'onnx-reload', work, args.output,
                             env, helper, args.timeout_seconds)
        checks['fresh_process_reload'] = checkNumerical(
          reloaded, fixture['samples'], reloadJob['run_id'])
        checks['fresh_process_reload'].update(
          graph_files=graphEvidence,
          scope='New frozen process loads exact final ONNX graph/data bytes and predicts against references')
        activeCheck = 'deployment_inventory'
        from anomaly_func.cnn_onnx_artifacts import validate_package
        validate_package(package, source=fixture['source'], require_pass=True)
        if smoke.fileHash(Path(fixture['source']['paths']['model'])) != fixture['source']['hashes']['model']:
          raise ValueError('Source synthetic checkpoint was modified')
        report['status'] = 'PASS'
        activeCheck = None
      finally:
        helper.stop_owned(work)
    return 0
  except Exception as error:
    report.update(status='FAIL', error=str(error), error_type=type(error).__name__)
    if activeCheck:
      report['checks'][activeCheck].update(status='FAIL', error=str(error))
    (args.output / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    return 1
  finally:
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    smoke.writeReport(args.output / 'frozen-patchcore.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def fixtureMain(argv) -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument('--source-root', type=Path, required=True)
  parser.add_argument('--weights', type=Path, required=True)
  parser.add_argument('--destination', type=Path, required=True)
  parser.add_argument('--report', type=Path, required=True)
  args = parser.parse_args(argv)
  smoke.writeReport(args.report, prepareFixture(args.source_root, args.weights, args.destination))
  return 0


if __name__ == '__main__':
  if sys.argv[1:2] == ['--prepare-fixture']:
    raise SystemExit(fixtureMain(sys.argv[2:]))
  raise SystemExit(main())
