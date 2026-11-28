"""Observe the prepared Windows Qt font engine before a long candidate build."""

import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
from pathlib import PureWindowsPath
import secrets
import subprocess
import sys
import time
import traceback


SAMPLES = {'ascii': 'VisionWorkshop ABC 0123', 'chinese': '离线模块训练平台'}


def writeDocument(path: Path, document: dict) -> None:
  path.write_text(json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2) + '\n',
                  encoding='utf-8')


def pixelDifference(blank: bytes, rendered: bytes, width: int, height: int,
                    stride: int) -> dict:
  if (width <= 0 or height <= 0 or stride < width * 4
      or len(blank) != stride * height or len(rendered) != len(blank)):
    raise ValueError('Unexpected RGBA image dimensions or byte count')
  count, left, top, right, bottom = 0, width, height, -1, -1
  for y in range(height):
    for x in range(width):
      start = y * stride + x * 4
      if blank[start:start + 4] != rendered[start:start + 4]:
        count += 1
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x), max(bottom, y)
  return {'changed_pixels': count, 'bounds': [left, top, right, bottom] if count else None,
          'width': width, 'height': height, 'stride': stride,
          'blank_rgba_sha256': hashlib.sha256(blank).hexdigest(),
          'rendered_rgba_sha256': hashlib.sha256(rendered).hexdigest()}


def sampleStatus(pixels: dict, glyphs: list[dict]) -> str:
  if pixels['changed_pixels'] == 0 or not glyphs or not any(item['indexes'] for item in glyphs):
    return 'FAIL'
  if any(not item['font_valid'] or 0 in item['indexes'] for item in glyphs):
    return 'UNSUPPORTED'
  return 'PASS'


def windowsPath(value: str) -> str:
  if not isinstance(value, str) or not PureWindowsPath(value).is_absolute():
    raise RuntimeError('A font probe process identity requires an absolute Windows path')
  return ntpath.normcase(ntpath.normpath(value))


def sameCommand(actual: list, expected: list) -> bool:
  if not isinstance(actual, list) or len(actual) != len(expected):
    return False
  return all((windowsPath(left) == windowsPath(right) if index in {0, 1, 4} else left == right)
             for index, (left, right) in enumerate(zip(actual, expected)))


def selectedRuntime(python: Path) -> dict:
  python = python.resolve()
  if not python.is_file() or python.name.casefold() != 'python.exe':
    raise RuntimeError('The font probe requires the selected CPython executable')
  result = {'selected_python': str(python), 'venv': python.parent.name.casefold() == 'scripts'}
  if not result['venv']:
    return dict(result, prefix=str(python.parent), base_prefix=str(python.parent),
                base_executable=str(python))
  prefix = python.parent.parent
  config = prefix / 'pyvenv.cfg'
  if not config.is_file() or not 0 < config.stat().st_size <= 65536:
    raise RuntimeError('The selected runtime has no bounded pyvenv.cfg')
  data = config.read_bytes()
  if not 0 < len(data) <= 65536:
    raise RuntimeError('The selected pyvenv.cfg changed beyond its byte bound')
  values = {}
  for line in data.decode('utf-8').splitlines():
    key, separator, value = line.partition('=')
    if separator:
      key = key.strip()
      if key in values:
        raise RuntimeError('The selected pyvenv.cfg contains duplicate fields')
      values[key] = value.strip()
  home = Path(values.get('home', ''))
  executable = Path(values.get('executable', ''))
  if (values.get('version') != '3.12.10' or values.get('include-system-site-packages') != 'false'
      or not home.is_absolute() or not executable.is_file()
      or windowsPath(str(executable)) != windowsPath(str(home / 'python.exe'))):
    raise RuntimeError('The selected virtual environment does not identify its fixed base Python')
  return dict(result, prefix=str(prefix), base_prefix=str(home), base_executable=str(executable),
              pyvenv_config={'path': str(config), 'bytes': len(data),
                             'sha256': hashlib.sha256(data).hexdigest(),
                             'fields': {key: values[key] for key in
                               ('home', 'executable', 'version', 'include-system-site-packages')}})


def verifyProcessIdentity(report: dict, launch: dict) -> dict:
  runtime = launch['runtime']
  native = report.get('native_process', {})
  parent = report.get('native_parent', {})
  identity = report.get('interpreter', {})
  if (report.get('nonce') != launch['nonce'] or report.get('python_version') != '3.12.10'
      or type(report.get('pid')) is not int or report['pid'] <= 0
      or type(native.get('pid')) is not int or native['pid'] != report['pid']
      or type(native.get('ppid')) is not int or native['ppid'] <= 0
      or type(parent.get('pid')) is not int or parent['pid'] != native['ppid']):
    raise RuntimeError('Font probe nonce/PID/parent/interpreter identity mismatch')
  for field, expected in (('executable', runtime['selected_python']),
                           ('prefix', runtime['prefix']), ('base_prefix', runtime['base_prefix']),
                           ('base_executable', runtime['base_executable'])):
    if windowsPath(identity.get(field)) != windowsPath(expected):
      raise RuntimeError('Font probe interpreter path mismatch: ' + field)
  if windowsPath(report.get('executable')) != windowsPath(runtime['selected_python']):
    raise RuntimeError('Font probe executable report differs from its interpreter identity')
  if report.get('script_argv') != launch['command'][1:]:
    raise RuntimeError('Font probe script/output/nonce arguments differ from the selected invocation')
  if report['pid'] == launch['pid']:
    if (native['ppid'] != launch['driver_pid']
        or windowsPath(native.get('exe')) != windowsPath(runtime['selected_python'])
        or windowsPath(parent.get('exe')) != windowsPath(launch['driver_base_executable'])
        or not sameCommand(native.get('cmdline'), launch['command'])):
      raise RuntimeError('Direct font probe process does not match its selected Python/parent/command')
    mode = 'direct'
  else:
    actualCommand = [runtime['base_executable'], *launch['command'][1:]]
    if (runtime.get('venv') is not True or native['ppid'] != launch['pid']
        or parent.get('ppid') != launch['driver_pid']
        or windowsPath(parent.get('exe')) != windowsPath(runtime['selected_python'])
        or not sameCommand(parent.get('cmdline'), launch['command'])
        or windowsPath(native.get('exe')) != windowsPath(runtime['base_executable'])
        or not sameCommand(native.get('cmdline'), actualCommand)):
      raise RuntimeError('Font probe is not the selected venv launcher and its single base-Python child')
    mode = 'venv-redirector-single-child'
  return {'status': 'PASS', 'mode': mode, 'launcher_pid': launch['pid'],
          'interpreter_pid': report['pid'], 'native_process': native, 'native_parent': parent,
          'interpreter': identity, 'nonce': launch['nonce']}


def runChild(output: Path, nonce: str) -> int:
  report = {'status': 'FAIL', 'pid': os.getpid(), 'python': sys.version,
            'python_version': '.'.join(map(str, sys.version_info[:3])), 'nonce': nonce,
            'executable': sys.executable, 'requested_platform': os.environ.get('QT_QPA_PLATFORM'),
            'scope': 'Prepared interpreter font rendering; frozen product visual acceptance NOT_RUN',
            'samples': {}}
  app = None
  try:
    if os.name != 'nt' or os.environ.get('QT_QPA_PLATFORM') != 'windows':
      raise RuntimeError('The early font probe requires the native Windows Qt platform')
    if not isinstance(nonce, str) or len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
      raise RuntimeError('The fixed font child requires its fresh invocation nonce')
    import psutil

    process = psutil.Process()
    parent = psutil.Process(process.ppid())
    fields = ['pid', 'ppid', 'exe', 'cmdline', 'create_time']
    report.update(native_process=process.as_dict(attrs=fields),
                  native_parent=parent.as_dict(attrs=fields), script_argv=list(sys.argv),
                  interpreter={'executable': sys.executable, 'prefix': sys.prefix,
                    'base_prefix': sys.base_prefix, 'base_executable': sys._base_executable},
                  psutil_version=psutil.__version__)
    from PyQt5 import QtCore
    from PyQt5 import QtGui
    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication([sys.argv[0]])
    report.update(platform_name=app.platformName(), qt_version=QtCore.QT_VERSION_STR,
                  pyqt_version=QtCore.PYQT_VERSION_STR, qt_module=QtCore.__file__)
    if app.platformName() != 'windows':
      raise RuntimeError('Qt did not use its native Windows platform plugin')
    families = sorted(QtGui.QFontDatabase().families())
    if not families:
      raise RuntimeError('The native Windows Qt font database is empty')
    font = QtGui.QFont(app.font())
    report['application_font'] = font.toString()
    font.setPixelSize(24)
    info = QtGui.QFontInfo(font)
    report['font'] = {'family': info.family(), 'style': info.styleName(),
                      'pixel_size': info.pixelSize(), 'exact_match': info.exactMatch()}
    report['font_families'] = families
    blank = QtGui.QImage(640, 96, QtGui.QImage.Format_RGBA8888)
    blank.fill(QtCore.Qt.white)

    def imageBytes(image):
      pointer = image.constBits()
      pointer.setsize(image.byteCount())
      return bytes(pointer)

    blankBytes = imageBytes(blank)
    if not blank.save(str(output / 'blank.png')):
      raise RuntimeError('Cannot save the blank font probe baseline')
    for name, text in SAMPLES.items():
      image = blank.copy()
      painter = QtGui.QPainter(image)
      if not painter.isActive():
        raise RuntimeError('Qt could not create a QImage painter')
      try:
        painter.setPen(QtCore.Qt.black)
        painter.setFont(font)
        painter.drawText(QtCore.QRect(16, 8, 608, 80),
                         QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
      finally:
        painter.end()
      layout = QtGui.QTextLayout(text, font)
      layout.beginLayout()
      line = layout.createLine()
      if line.isValid():
        line.setLineWidth(608)
      layout.endLayout()
      glyphs = [{'family': item.rawFont().familyName(), 'font_valid': item.rawFont().isValid(),
                 'indexes': list(item.glyphIndexes())} for item in layout.glyphRuns()]
      pixels = pixelDifference(blankBytes, imageBytes(image), image.width(), image.height(),
                                image.bytesPerLine())
      path = output / (name + '.png')
      if not image.save(str(path)):
        raise RuntimeError('Cannot save the rendered font probe image: ' + name)
      report['samples'][name] = {'text': text, 'status': sampleStatus(pixels, glyphs),
                                 'pixels': pixels, 'glyph_runs': glyphs, 'image': path.name,
                                 'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if report['samples']['ascii']['status'] != 'PASS':
      raise RuntimeError('The native Windows Qt font engine did not render supported ASCII glyphs')
    chinese = report['samples']['chinese']['status']
    if chinese == 'FAIL':
      raise RuntimeError('The native Windows Qt font engine produced no Chinese text ink/glyphs')
    report['status'] = 'LIMITED' if chinese == 'UNSUPPORTED' else 'PASS'
    report['chinese_visual_acceptance'] = (
      'UNSUPPORTED; missing glyphs are not Chinese rendering success' if chinese == 'UNSUPPORTED'
      else 'Probe glyphs and raster only; inspect the actual product screenshots separately')
    return 0
  except Exception as error:
    report['error'] = str(error)
    report['traceback'] = traceback.format_exc()
    return 1
  finally:
    if app is not None:
      app.quit()
    writeDocument(output / 'qt-font-probe.json', report)


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--runtime-python', type=Path)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
  parser.add_argument('--probe-nonce', help=argparse.SUPPRESS)
  args = parser.parse_args(argv)
  output = args.output.resolve()
  if args.child:
    return runChild(output, args.probe_nonce)
  if args.runtime_python is None or os.name != 'nt' or args.probe_nonce is not None:
    parser.error('The probe requires Windows and --runtime-python')
  output.mkdir(parents=True, exist_ok=False)
  environment = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONDONTWRITEBYTECODE='1',
                     PYTHONNOUSERSITE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
  nonce = secrets.token_hex(16)
  command = [str(args.runtime_python.resolve()), str(Path(__file__).resolve()),
             '--child', '--output', str(output), '--probe-nonce', nonce]
  record = {'status': 'FAIL', 'command': command, 'timeout_seconds': 120,
            'requested_platform': 'windows', 'nonce': nonce, 'driver_pid': os.getpid(),
            'driver_base_executable': sys._base_executable}
  started = time.monotonic()
  try:
    record['runtime'] = selectedRuntime(args.runtime_python)
    with (output / 'stdout.txt').open('w', encoding='utf-8') as stdout, \
         (output / 'stderr.txt').open('w', encoding='utf-8') as stderr:
      process = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr)
      record['pid'] = process.pid
      try:
        record['exit_code'] = process.wait(timeout=120)
      except subprocess.TimeoutExpired:
        record['status'] = 'TIMEOUT'
        killer = Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'
        try:
          subprocess.run([str(killer), '/PID', str(process.pid), '/T', '/F'],
                         stdout=stderr, stderr=stderr, timeout=30, check=False)
        finally:
          if process.poll() is None:
            process.kill()
          process.wait(timeout=15)
        raise
    if record['exit_code'] != 0:
      raise RuntimeError('The Windows Qt font probe exited with ' + str(record['exit_code']))
    path = output / 'qt-font-probe.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    record['process_identity'] = verifyProcessIdentity(report, record)
    if report.get('platform_name') != 'windows' or report.get('status') not in {'PASS', 'LIMITED'}:
      raise RuntimeError('Qt font probe platform/result mismatch')
    record.update(status=report['status'], report=path.name,
                  report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return 0
  except Exception as error:
    record['error'] = str(error)
    record['traceback'] = traceback.format_exc()
    return 1
  finally:
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    writeDocument(output / 'qt-font-probe.process.json', record)


if __name__ == '__main__':
  raise SystemExit(main())
