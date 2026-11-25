"""Observe the prepared Windows Qt font engine before a long candidate build."""

import argparse
import hashlib
import json
import os
from pathlib import Path
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


def runChild(output: Path) -> int:
  report = {'status': 'FAIL', 'pid': os.getpid(), 'python': sys.version,
            'executable': sys.executable, 'requested_platform': os.environ.get('QT_QPA_PLATFORM'),
            'scope': 'Prepared interpreter font rendering; frozen product visual acceptance NOT_RUN',
            'samples': {}}
  app = None
  try:
    if os.name != 'nt' or os.environ.get('QT_QPA_PLATFORM') != 'windows':
      raise RuntimeError('The early font probe requires the native Windows Qt platform')
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
  args = parser.parse_args(argv)
  output = args.output.resolve()
  if args.child:
    return runChild(output)
  if args.runtime_python is None or os.name != 'nt':
    parser.error('The probe requires Windows and --runtime-python')
  output.mkdir(parents=True, exist_ok=False)
  environment = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONDONTWRITEBYTECODE='1',
                     PYTHONNOUSERSITE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
  command = [str(args.runtime_python.resolve()), str(Path(__file__).resolve()),
             '--child', '--output', str(output)]
  record = {'status': 'FAIL', 'command': command, 'timeout_seconds': 120,
            'requested_platform': 'windows'}
  started = time.monotonic()
  try:
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
    if (report.get('pid') != record['pid'] or report.get('platform_name') != 'windows'
        or report.get('status') not in {'PASS', 'LIMITED'}):
      raise RuntimeError('Qt font probe process identity/platform/result mismatch')
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
