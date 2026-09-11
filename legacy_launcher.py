"""Old executable names forward to VisionWorkshop after an in-place update."""

import subprocess
import sys
from pathlib import Path


def launchMain(appDir: Path, arguments: list[str]) -> None:
  target = appDir / 'VisionWorkshop.exe'
  if not target.is_file():
    raise FileNotFoundError(f'VisionWorkshop executable is missing: {target}')
  if getattr(sys, 'frozen', False) and target.samefile(sys.executable):
    raise RuntimeError('The compatibility launcher cannot replace VisionWorkshop.exe')
  subprocess.Popen([str(target), *arguments], cwd=str(appDir), close_fds=True)


def main() -> int:
  entry = sys.executable if getattr(sys, 'frozen', False) else __file__
  launchMain(Path(entry).resolve().parent, sys.argv[1:])
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
