import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
  'verifyVisionTrainModules', ROOT / 'scripts/verify_vision_train_modules.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ModularProbeTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name).resolve()
    self.runtime = self.root / 'runtime/site-packages'
    self.runtime.mkdir(parents=True)
    self.core = self.root / 'Core/VisionWorkshopProbeCore.exe'
    self.core.parent.mkdir()
    self.core.write_bytes(b'fixture')
    self.source = self.root / 'application'
    self.source.mkdir()

  def makeReport(self):
    return {'schema_version': 1, 'status': 'PASS', 'mode': 'pure', 'run_id': 'run-1',
            'pid': 123, 'frozen': True, 'python': '3.12.10',
            'sys_executable': str(self.core),
            'module_origins': {'vw_external_fixture': str(
              self.runtime / 'vw_external_fixture/__init__.py')}}

  def validate(self, report):
    probe.validateProbeReport(report, mode='pure', runId='run-1', pid=123,
                              executable=self.core, runtime=self.runtime, source=self.source)

  def testProbeRejectsStaleWrongProcessOrNonFrozenEvidence(self):
    self.validate(self.makeReport())
    for field, value in [('run_id', 'old-run'), ('mode', 'native'), ('pid', 456),
                         ('frozen', False), ('status', 'READY'), ('python', '3.12.11')]:
      with self.subTest(field=field):
        report = self.makeReport()
        report[field] = value
        with self.assertRaisesRegex(ValueError, 'identity/status'):
          self.validate(report)

  def testProbeRejectsHostEnvironmentImportAndWrongExecutable(self):
    report = self.makeReport()
    report['module_origins']['numpy'] = str(self.root / 'host/Lib/site-packages/numpy/__init__.py')
    with self.assertRaisesRegex(ValueError, 'escaped'):
      self.validate(report)
    report = self.makeReport()
    report['sys_executable'] = str(self.root / 'host/python.exe')
    with self.assertRaisesRegex(ValueError, 'selected Core'):
      self.validate(report)

  def testProbeRequiresAnActualExternalModuleOrigin(self):
    report = self.makeReport()
    report['module_origins'].clear()
    with self.assertRaisesRegex(ValueError, 'Required dependency'):
      self.validate(report)
    report['module_origins']['vw_external_fixture'] = str(self.core.parent / 'fixture.py')
    with self.assertRaisesRegex(ValueError, 'Required dependency'):
      self.validate(report)

  def testMatchingPathPrefixDoesNotGrantImportPermission(self):
    other = self.root / 'runtime/site-packages-other/numpy/__init__.py'
    self.assertFalse(probe.isInside(other, self.runtime))
    self.assertFalse(probe.isInside(self.runtime / '../../outside.py', self.runtime))

  def testExternalRuntimeRejectsBundledPythonInterpreter(self):
    source = self.root / 'staging'
    source.mkdir()
    (source / 'python312.dll').write_bytes(b'not-an-extension')
    with self.assertRaisesRegex(ValueError, 'another Python'):
      probe.copyRuntime(source, self.root / 'new-runtime', self.root / 'unused.whl')
    self.assertTrue(probe.isInterpreterFile(Path('python.exe')))
    self.assertTrue(probe.isInterpreterFile(Path('python3.dll')))
    self.assertFalse(probe.isInterpreterFile(Path('_psutil_windows.pyd')))
    self.assertFalse(probe.isInterpreterFile(Path('torch_python.dll')))

  def testVersionValidationRejectsDuplicateOwnersAndMixedOrt(self):
    expected = {'numpy': '2.0.2', 'onnxruntime-gpu': '1.23.2'}
    distributions = [{'name': name, 'version': version} for name, version in expected.items()]
    probe.validateVersions({'distributions': distributions}, expected)
    with self.assertRaisesRegex(ValueError, 'Duplicate installed'):
      probe.validateVersions({'distributions': distributions + [
        {'name': 'NumPy', 'version': '2.0.2'}]}, expected)
    with self.assertRaisesRegex(ValueError, 'cannot coexist'):
      probe.validateVersions({'distributions': distributions + [
        {'name': 'onnxruntime', 'version': '1.23.2'}]}, expected)

  def testPureFixtureReloadReplacesMetadataWithoutChangingOtherPayload(self):
    existing = self.runtime / 'other_module.py'
    existing.write_bytes(b'preserved')
    probe.writePureFixture(self.runtime, 'v1', '1.0.0')
    probe.writePureFixture(self.runtime, 'v2', '2.0.0')
    self.assertEqual(existing.read_bytes(), b'preserved')
    self.assertFalse((self.runtime / 'vw_external_fixture-1.0.0.dist-info').exists())
    self.assertEqual((self.runtime / 'vw_external_fixture/__init__.py').read_text(), "MARKER = 'v2'\n")
    self.assertIn('Version: 2.0.0', (self.runtime / 'vw_external_fixture-2.0.0.dist-info/METADATA').read_text())

  def testStdlibEnumerationCannotCollectSitePackagesOrTestTooling(self):
    stdlib = self.root / 'Lib'
    for relative in ['asyncio/__init__.py', 'asyncio/tasks.py', 'email/parser.py',
                     'site-packages/numpy/__init__.py', 'test/test_os.py',
                     'tkinter/__init__.py', 'ensurepip/__init__.py']:
      file = stdlib / relative
      file.parent.mkdir(parents=True, exist_ok=True)
      file.write_text('', encoding='utf-8')
    names = probe.collectStdlibModules({'stdlib': str(stdlib),
                                       'stdlib_names': ['sys', '_sqlite3', '_tkinter', '_testcapi']})
    self.assertEqual(names, ['_sqlite3', 'asyncio', 'asyncio.tasks', 'email.parser', 'sys'])

  def testManifestSortingAndHashAreStableForMixedCasePaths(self):
    for name in ['numpy.py', 'PyQt5.py', 'PIL.py', 'torch.py']:
      (self.runtime / name).write_text(name, encoding='utf-8')
    records = probe.inventory(self.runtime)
    self.assertEqual([item['path'] for item in records], ['PIL.py', 'PyQt5.py', 'numpy.py', 'torch.py'])
    self.assertEqual(probe.summarizeFiles(records)['files_sha256'], probe.objectHash(records))
    original = probe.objectHash(records)
    (self.runtime / 'numpy.py').write_text('changed', encoding='utf-8')
    self.assertNotEqual(original, probe.objectHash(probe.inventory(self.runtime)))

  def testRuntimeExcludesBuildToolsWithoutRemovingRuntimeMetadata(self):
    for name in ['pip/__init__.py', 'pip-24.3.dist-info/METADATA',
                 'PyInstaller/__main__.py', 'pyinstaller_hooks_contrib-2026.0.dist-info/METADATA',
                 'numpy/__pycache__/__init__.pyc']:
      self.assertTrue(probe.isExcluded(Path(name)), name)
    for name in ['PyQt5-5.15.9.dist-info/METADATA', 'torch/lib/torch_cpu.dll',
                 'numpy/__init__.py', 'setuptools/__init__.py']:
      self.assertFalse(probe.isExcluded(Path(name)), name)


if __name__ == '__main__':
  unittest.main()
