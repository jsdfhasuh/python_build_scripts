"""CLI shim for the shared portable release implementation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portable_release import main


if __name__ == '__main__':
  raise SystemExit(main())
