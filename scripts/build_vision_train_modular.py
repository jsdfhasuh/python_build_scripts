"""Explicit protocol-4 candidate builder; never publishes a Release."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision_train_modular_build import main


if __name__ == '__main__':
  raise SystemExit(main())
