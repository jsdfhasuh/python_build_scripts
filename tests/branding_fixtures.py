"""Deterministic test-only icons and minimal projects; not production branding assets."""

import json
import struct
import zlib
from pathlib import Path


def makePng(size: int = 16) -> bytes:
  def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + kind + data + struct.pack(
      '>I', zlib.crc32(kind + data) & 0xffffffff,
    )
  pixels = (b'\0' + b'\x20\x90\xd0\xff' * size) * size
  return (
    b'\x89PNG\r\n\x1a\n'
    + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
    + chunk(b'IDAT', zlib.compress(pixels))
    + chunk(b'IEND', b'')
  )


def makeIco(size: int = 16, png: bool = False) -> bytes:
  if png:
    frame = makePng(size)
  else:
    pixels = b'\xd0\x90\x20\xff' * (size * size)
    mask = b'\0' * (((size + 31) // 32) * 4 * size)
    frame = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                        len(pixels), 0, 0, 0, 0) + pixels + mask
  return struct.pack('<HHHBBBBHHII', 0, 1, 1, size % 256, size % 256, 0, 0,
                     1, 32, len(frame), 22) + frame


def writeProject(root: Path) -> tuple[Path, Path, Path]:
  root.mkdir(parents=True, exist_ok=True)
  (root / 'main.py').write_text('print("test fixture")\n', encoding='utf-8')
  (root / 'updater.py').write_text('print("fixture updater")\n', encoding='utf-8')
  config = {
    'entry': str(root / 'main.py'), 'name': 'emo-vision-train',
    'onefile': False, 'console': True, 'icon': None,
    'release_asset_name': 'emo-vision-train-windows-${RELEASE_TAG}.zip',
    'hidden_imports': [], 'extra_args': [],
    'updater': {
      'enabled': True, 'entry': str(root / 'updater.py'), 'name': 'updater',
      'onefile': True, 'console': True,
    },
  }
  configPath = root / 'emo-vision-train.json'
  configPath.write_text(json.dumps(config), encoding='utf-8')
  icon = root / 'test-icon.ico'
  icon.write_bytes(makeIco())
  profile = root / 'profile.json'
  profile.write_text(json.dumps({
    'schema_version': 1, 'target': 'emo-vision-train',
    'program_name': 'VisionWorkshop', 'icon_path': str(icon),
    'release_asset_name': 'VisionWorkshop-windows-${RELEASE_TAG}.zip',
  }), encoding='utf-8')
  return configPath, icon, profile
