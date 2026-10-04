"""Extended Windows paths at the build/archive I/O boundary."""

import os
from pathlib import Path


def logicalPath(path):
  value = os.fspath(path)
  if os.name == 'nt':
    if value.startswith('\\\\?\\UNC\\'):
      value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\'):
      value = value[4:]
  return Path(os.path.abspath(value))


def ioPath(path):
  value = str(logicalPath(path))
  if os.name != 'nt':
    return Path(value)
  return Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
