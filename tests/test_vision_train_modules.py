import copy
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock
import zlib


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
  'verifyVisionTrainModules', ROOT / 'scripts/verify_vision_train_modules.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
CORE_SPEC = importlib.util.spec_from_file_location(
  'modularProbeCore', ROOT / 'scripts/modular_probe_core.py')
coreProbe = importlib.util.module_from_spec(CORE_SPEC)
CORE_SPEC.loader.exec_module(coreProbe)


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
    self.archive = self.makeArchive()

  def makeArchive(self):
    modules = {name: {'archive_type': 'm', 'payload_sha256': hashlib.sha256(
      name.encode()).hexdigest(), 'code_filename': name + '.py'}
      for name in probe.BOOTSTRAP_MODULES}
    return {
      'schema_version': 1, 'reader_version': probe.BUILD_VERSIONS['pyinstaller'],
      'executable': {'path': str(self.core), 'bytes': self.core.stat().st_size,
                     'sha256': probe.fileHash(self.core)},
      'archive': {'python_version': 312, 'python_library': 'python312.dll'},
      'bootstrap_modules': modules,
      'members': [dict(name=name, archive_type=value['archive_type'],
                       payload_sha256=value['payload_sha256']) for name, value in modules.items()],
    }

  def makeReport(self):
    return {'schema_version': 1, 'status': 'PASS', 'mode': 'pure', 'run_id': 'run-1',
            'pid': 123, 'frozen': True, 'python': '3.12.10',
            'sys_executable': str(self.core),
            'bootstrap_archive': dict(self.archive['archive'], path=str(self.core),
                                       sha256=self.archive['executable']['sha256']),
            'bootstrap_modules': {name: dict(value, module_file=value['code_filename'])
                                    for name, value in self.archive['bootstrap_modules'].items()},
            'module_origins': {'vw_external_fixture': str(
              self.runtime / 'vw_external_fixture/__init__.py')}}

  def validate(self, report):
    probe.validateProbeReport(report, mode='pure', runId='run-1', pid=123,
                              executable=self.core, runtime=self.runtime, source=self.source,
                              archive=self.archive)

  def testBootstrapInventoryBindsExactExecutableAndEmbeddedModules(self):
    probe.validateArchiveInventory(self.archive, self.core)
    altered = copy.deepcopy(self.archive)
    altered['members'].append({'name': 'unreviewed_module', 'archive_type': 'm',
                              'payload_sha256': '0' * 64})
    with self.assertRaisesRegex(ValueError, 'pinned module set'):
      probe.validateArchiveInventory(altered, self.core)
    altered = copy.deepcopy(self.archive)
    altered['bootstrap_modules']['struct']['payload_sha256'] = '0' * 64
    with self.assertRaisesRegex(ValueError, 'payload evidence mismatch'):
      probe.validateArchiveInventory(altered, self.core)
    self.core.write_bytes(b'changed executable')
    with self.assertRaisesRegex(ValueError, 'selected frozen Core'):
      probe.validateArchiveInventory(self.archive, self.core)

  def testBootstrapExceptionDoesNotAllowCwdOrSubstitutedEvidence(self):
    self.validate(self.makeReport())
    report = self.makeReport()
    report['bootstrap_archive']['sha256'] = '0' * 64
    with self.assertRaisesRegex(ValueError, 'independently inspected Core'):
      self.validate(report)
    report = self.makeReport()
    report['bootstrap_modules']['struct']['module_file'] = str(self.root / 'struct.py')
    with self.assertRaisesRegex(ValueError, 'embedded code payload'):
      self.validate(report)
    report = self.makeReport()
    report['module_origins']['ordinary_relative_module'] = 'ordinary_relative_module.py'
    with self.assertRaisesRegex(ValueError, 'Invalid import origin'):
      self.validate(report)

  def testCoreArchiveReaderUsesEmbeddedPayloadAndRejectsTruncation(self):
    payloads, entries = bytearray(), bytearray()
    expected = {}
    for name in sorted(probe.BOOTSTRAP_MODULES):
      payload = marshal.dumps(compile('MARKER = 1', name + '.py', 'exec'))
      packed = zlib.compress(payload)
      encodedName = name.encode() + b'\0'
      entries.extend(struct.pack('!IIIIBc', 18 + len(encodedName), len(payloads),
                                 len(packed), len(payload), 1, b'm'))
      entries.extend(encodedName)
      payloads.extend(packed)
      expected[name] = hashlib.sha256(payload).hexdigest()
    cookie = struct.pack('!8sIIII64s', b'MEI\x0c\x0b\x0a\x0b\x0e',
                          len(payloads) + len(entries) + 88, len(payloads), len(entries),
                          312, b'python312.dll')
    self.core.write_bytes(b'MZ fixture executable' + payloads + entries + cookie)
    report = coreProbe.readBootstrapArchive(self.core)
    self.assertEqual({name: value['payload_sha256']
                      for name, value in report['bootstrap_modules'].items()}, expected)
    self.assertEqual(report['bootstrap_archive']['sha256'], probe.fileHash(self.core))
    self.core.write_bytes(self.core.read_bytes()[:-1])
    with self.assertRaisesRegex(RuntimeError, 'complete CArchive cookie'):
      coreProbe.readBootstrapArchive(self.core)

  def testBuildEnvironmentAndBinaryInventoryRejectRunnerJava(self):
    base = self.root / 'CPython'
    venv = self.root / 'build-venv'
    windows = self.root / 'Windows'
    java = self.root / 'Java/bin/ucrtbase.dll'
    binary = base / 'python312.dll'
    for file in (java, binary):
      file.parent.mkdir(parents=True, exist_ok=True)
      file.write_bytes(b'native fixture')
    info = {'prefix': str(venv), 'base_prefix': str(base)}
    with mock.patch.dict(os.environ, {'SystemRoot': str(windows), 'Path': str(java.parent),
                                      'PATH': str(java.parent), 'PYTHONPATH': str(java.parent)}):
      environment = probe.cleanBuildEnvironment(info, self.root / 'output')
    self.assertNotIn(str(java.parent), environment['PATH'])
    self.assertNotIn('Path', environment)
    self.assertNotIn('PYTHONPATH', environment)
    self.assertEqual(environment['PATH'].split(os.pathsep),
                     [str(base), str(base / 'DLLs'), str(windows / 'System32'), str(windows)])
    records = probe.validateBinarySources(
      {'binaries': [('python312.dll', str(binary), 'BINARY')]}, info, windows)
    self.assertEqual(records[0]['owner'], 'python_base')
    self.assertEqual(records[0]['sha256'], probe.fileHash(binary))
    with self.assertRaisesRegex(ValueError, 'unapproved build source'):
      probe.validateBinarySources({'binaries': [('ucrtbase.dll', str(java), 'BINARY')]},
                                   info, windows)

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

  def testTorchGeneratedNamespacesRequireExactExternalImplementationIdentity(self):
    torch = types.ModuleType('torch')
    torch.__file__ = str(self.runtime / 'torch/__init__.py')
    for name, className, attribute, filename in (
        ('torch.ops', '_Ops', 'ops', '_ops.py'),
        ('torch.classes', '_Classes', 'classes', '_classes.py')):
      with self.subTest(name=name):
        implementationName = 'torch.' + filename[:-3]
        implementation = types.ModuleType(implementationName)
        implementation.__file__ = str(self.runtime / 'torch' / filename)
        namespaceClass = type(className, (types.ModuleType,), {
          '__module__': implementationName, '__file__': filename})
        namespace = namespaceClass(name)
        setattr(implementation, className, namespaceClass)
        setattr(implementation, attribute, namespace)
        setattr(torch, attribute, namespace)
        with mock.patch.dict(sys.modules, {'torch': torch, implementationName: implementation,
                                          name: namespace}):
          evidence = coreProbe.generatedTorchOrigin(name, namespace, self.runtime)
          self.assertEqual(evidence['implementation_file'], implementation.__file__)
          replacement = namespaceClass(name)
          with self.assertRaisesRegex(RuntimeError, 'identity was replaced'):
            coreProbe.generatedTorchOrigin(name, replacement, self.runtime)
          implementation.__file__ = str(self.root / filename)
          with self.assertRaisesRegex(RuntimeError, 'implementation escaped'):
            coreProbe.generatedTorchOrigin(name, namespace, self.runtime)

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

  def makeVendoredPython(self):
    source = self.root / 'wheel-environment'
    duplicate = source / 'torchvision/python312.dll'
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b'reviewed native fixture')
    metadata = source / 'torchvision-0.25.0+cu128.dist-info'
    metadata.mkdir()
    (metadata / 'METADATA').write_text(
      'Metadata-Version: 2.1\nName: torchvision\nVersion: 0.25.0+cu128\n', encoding='utf-8')
    (metadata / 'RECORD').write_text(
      'torchvision\\python312.dll,sha256=NDbUa7Zah7o9IV3wZfAQ2f2rGMmUyqJ1tUa4h3tSBbI,7470920\n',
      encoding='utf-8')
    report = self.root / 'torch-install.json'
    report.write_text(json.dumps({'install': [{
      'metadata': {'name': 'torchvision', 'version': '0.25.0+cu128'},
      'download_info': {'url': probe.TORCHVISION_WHEEL_URL,
                         'archive_info': {'hashes': {'sha256': probe.TORCHVISION_WHEEL_SHA256}}},
    }]}), encoding='utf-8')
    corePython = self.core.parent / 'python312.dll'
    corePython.write_bytes(b'Core-owned CPython fixture')
    duplicateIdentity = dict(probe.TORCHVISION_PYTHON, path=str(duplicate))
    coreIdentity = dict(path=str(corePython), bytes=corePython.stat().st_size,
                        sha256=probe.fileHash(corePython), machine=0x8664,
                        file_version='3.12.10150.1013', product_version='3.12.10')
    return source, report, corePython, duplicateIdentity, coreIdentity

  def testOnlyReviewedTorchvisionPythonDuplicateIsOmitted(self):
    source, report, corePython, duplicate, owner = self.makeVendoredPython()
    record = source / 'torchvision-0.25.0+cu128.dist-info/RECORD'
    with record.open('a', encoding='utf-8') as stream:
      stream.write('torchvision/python312.dll,,\n')
    def extract(_wheel, destination):
      (destination / 'msvcp140.dll').write_bytes(b'CRT fixture')
      return {'licenses': []}
    with mock.patch.object(probe, 'nativeIdentity', side_effect=[duplicate, owner]), \
         mock.patch.object(probe, 'verifyPythonConsumer', return_value={
           'python_import_count': 97, 'missing_python_exports': []}), \
         mock.patch.object(probe, 'extractCrt', side_effect=extract):
      files, _crt, omitted = probe.copyRuntime(
        source, self.root / 'staged-runtime', self.root / 'fixture.whl',
        corePython=corePython, torchInstallReport=report)
    self.assertFalse((self.root / 'staged-runtime/torchvision/python312.dll').exists())
    self.assertTrue(corePython.is_file())
    self.assertEqual(len(omitted), 1)
    self.assertEqual(omitted[0]['excluded_file']['sha256'], probe.TORCHVISION_PYTHON['sha256'])
    self.assertEqual(omitted[0]['owner']['product_version'], '3.12.10')
    self.assertEqual(omitted[0]['installed_record_aliases'], [['torchvision/python312.dll', '', '']])
    self.assertNotIn('torchvision/python312.dll', {item['path'] for item in files})

  def testReviewedDuplicateRuleRejectsDifferentAbiPayloadOrWheel(self):
    source, report, corePython, duplicate, owner = self.makeVendoredPython()
    with self.assertRaisesRegex(ValueError, 'another Python'):
      probe.qualifyVendoredPython(source, Path('torchvision/python311.dll'), corePython, report)
    for field, value in [('sha256', '0' * 64), ('machine', 0x14c),
                         ('product_version', '3.11.12'), ('bytes', 1)]:
      with self.subTest(field=field):
        altered = dict(duplicate, **{field: value})
        with mock.patch.object(probe, 'nativeIdentity', return_value=altered), \
             self.assertRaisesRegex(ValueError, 'DLL bytes, PE architecture or version changed'):
          probe.qualifyVendoredPython(source, Path('torchvision/python312.dll'), corePython, report)
    with mock.patch.object(probe, 'nativeIdentity', side_effect=[
        duplicate, dict(owner, product_version='3.12.12')]), \
         self.assertRaisesRegex(ValueError, 'Core must own'):
      probe.qualifyVendoredPython(source, Path('torchvision/python312.dll'), corePython, report)
    record = source / 'torchvision-0.25.0+cu128.dist-info/RECORD'
    original = record.read_text(encoding='utf-8')
    record.write_text(original + 'torchvision/python312.dll,sha256=wrong,7470920\n', encoding='utf-8')
    with self.assertRaisesRegex(ValueError, 'conflicting installed RECORD ownership'):
      probe.qualifyVendoredPython(source, Path('torchvision/python312.dll'), corePython, report)
    record.write_text(original, encoding='utf-8')
    changed = json.loads(report.read_text())
    changed['install'][0]['download_info']['archive_info']['hashes']['sha256'] = '0' * 64
    report.write_text(json.dumps(changed), encoding='utf-8')
    with self.assertRaisesRegex(ValueError, 'reviewed wheel'):
      probe.qualifyVendoredPython(source, Path('torchvision/python312.dll'), corePython, report)

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
