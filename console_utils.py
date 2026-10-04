"""Consistent UTF-8 output for CLI pipelines, including legacy Windows code pages."""

import sys


def configureConsole() -> None:
  # Native Windows consoles already support Unicode; redirected streams may use cp1252.
  # StringIO and embedding-provided streams need no reconfiguration.
  for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, 'reconfigure', None)
    if callable(reconfigure):
      reconfigure(encoding='utf-8', errors='backslashreplace')
