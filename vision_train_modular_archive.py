"""Write verified ZIP/LZMA packages containing files only, with bounded dictionaries."""

import hashlib
import lzma
import struct
import zipfile
from pathlib import Path

from build_config import BuildConfigError
from build_records import fileHash
from build_records import scanFiles


class ZipLzmaCompressor:
  def __init__(self, dictionaryBytes: int):
    # ZIP method 14 embeds the standard LZMA1 lc/lp/pb and dictionary properties.
    self.header = struct.pack('<BBHBI', 9, 4, 5, (2 * 5) * 9 + 3, dictionaryBytes)
    self.compressor = lzma.LZMACompressor(format=lzma.FORMAT_RAW, filters=[{
      'id': lzma.FILTER_LZMA1, 'dict_size': dictionaryBytes, 'lc': 3, 'lp': 0, 'pb': 2,
      'mode': lzma.MODE_NORMAL, 'nice_len': 273, 'mf': lzma.MF_BT4,
    }])

  def compress(self, data: bytes) -> bytes:
    header, self.header = self.header, b''
    return header + self.compressor.compress(data)

  def flush(self) -> bytes:
    header, self.header = self.header, b''
    return header + self.compressor.flush()


def compressPackage(source: Path, destination: Path, *, prefix: str = '',
                    dictionaryMiB: int = 256, maximumBytes: int = 2 * 1024**3 - 1) -> dict:
  if dictionaryMiB not in (1, 8, 16, 32, 64, 128, 256):
    raise BuildConfigError('Unsupported ZIP/LZMA dictionary size')
  if prefix and (not prefix.isidentifier() or prefix in ('.', '..')):
    raise BuildConfigError('Invalid Core archive prefix')
  files = scanFiles(source)
  if not files:
    raise BuildConfigError('Cannot compress an empty package')
  destination.parent.mkdir(parents=True, exist_ok=True)
  expected = {(prefix + '/' if prefix else '') + relative: record
              for relative, record in files.items()}
  with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_LZMA, allowZip64=True) as archive:
    for relative, record in files.items():
      path = source / relative
      name = (prefix + '/' if prefix else '') + relative
      information = zipfile.ZipInfo.from_file(path, name, strict_timestamps=False)
      information.compress_type = zipfile.ZIP_LZMA
      information.create_system = 3
      information.external_attr = 0o100644 << 16
      digest = hashlib.sha256()
      total = 0
      with archive.open(information, 'w', force_zip64=True) as writer, path.open('rb') as reader:
        if not hasattr(writer, '_compressor'):
          raise BuildConfigError('The selected Python ZIP writer cannot select a bounded LZMA dictionary')
        dictionary = min(dictionaryMiB * 1024**2, max(1024**2, 1 << max(0, record['size'] - 1).bit_length()))
        writer._compressor = ZipLzmaCompressor(dictionary)
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
          digest.update(chunk)
          total += len(chunk)
          writer.write(chunk)
      if total != record['size'] or digest.hexdigest() != record['sha256']:
        raise BuildConfigError('Package input changed while compressing: ' + relative)
  if destination.stat().st_size > maximumBytes:
    raise BuildConfigError('Compressed package exceeds the per-file download limit: ' + destination.name)
  before = fileHash(destination)
  with zipfile.ZipFile(destination) as archive:
    members = archive.infolist()
    if len(members) != len(expected) or {item.filename for item in members} != set(expected):
      raise BuildConfigError('ZIP contains missing, duplicate or extra members')
    for member in members:
      record = expected[member.filename]
      if member.is_dir() or member.file_size != record['size'] or member.compress_type != zipfile.ZIP_LZMA:
        raise BuildConfigError('ZIP member layout or compression differs from the package')
      with archive.open(member) as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
      if actual != record['sha256']:
        raise BuildConfigError('ZIP member does not match its declared SHA256: ' + member.filename)
    compressedPayload = sum(item.compress_size for item in members)
  if fileHash(destination) != before:
    raise BuildConfigError('ZIP changed during verification')
  return {'path': str(destination), 'bytes': destination.stat().st_size, 'sha256': before,
          'compression': 'zip/lzma', 'dictionary_max_mib': dictionaryMiB,
          'file_count': len(expected), 'expanded_bytes': sum(item['size'] for item in files.values()),
          'compressed_payload_bytes': compressedPayload, 'verified': True}
