"""Keep Python import caches out of checked build inputs."""

import os
import sys
from contextlib import contextmanager
from collections.abc import Iterator


def pythonChildEnvironment() -> dict[str, str]:
  environment = os.environ.copy()
  environment['PYTHONDONTWRITEBYTECODE'] = '1'
  return environment


@contextmanager
def preventSourceBytecode() -> Iterator[None]:
  previous = os.environ.get('PYTHONDONTWRITEBYTECODE')
  previousFlag = sys.dont_write_bytecode
  os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
  sys.dont_write_bytecode = True
  try:
    yield
  finally:
    sys.dont_write_bytecode = previousFlag
    if previous is None:
      os.environ.pop('PYTHONDONTWRITEBYTECODE', None)
    else:
      os.environ['PYTHONDONTWRITEBYTECODE'] = previous
