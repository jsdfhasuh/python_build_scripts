"""Bounded console progress for long, synchronous release operations."""

from threading import Event
from threading import Lock
from threading import Thread
from time import monotonic


class ReleaseProgress:
  def __init__(
    self, label: str, *, totalBytes: int | None = None, totalFiles: int | None = None,
    interval: float = 10,
  ) -> None:
    self.label = label
    self.totalBytes = totalBytes
    self.totalFiles = totalFiles
    self.interval = interval
    self.bytesDone = 0
    self.filesDone = 0
    self.started = 0.0
    self.stop = Event()
    self.lock = Lock()
    self.thread = Thread(target=self.reportWhileRunning, daemon=True)

  def __enter__(self) -> 'ReleaseProgress':
    self.started = monotonic()
    self.report('started')
    self.thread.start()
    return self

  def __exit__(self, errorType, error, traceback) -> None:
    self.stop.set()
    self.thread.join()
    self.report('completed' if errorType is None else 'failed')

  def advance(self, byteCount: int = 0, fileCount: int = 0) -> None:
    with self.lock:
      self.bytesDone += byteCount
      self.filesDone += fileCount

  def reportWhileRunning(self) -> None:
    while not self.stop.wait(self.interval):
      self.report('working')

  def report(self, state: str) -> None:
    with self.lock:
      details = [state]
      if self.totalBytes:
        details.append(f'{100 * self.bytesDone / self.totalBytes:.1f}%')
      if self.totalBytes is not None:
        details.append(f'{self.bytesDone / 1024**2:.1f}/{self.totalBytes / 1024**2:.1f} MiB')
      if self.totalFiles is not None:
        details.append(f'{self.filesDone}/{self.totalFiles} files')
      details.append(f'elapsed {monotonic() - self.started:.1f}s')
      print(f'[{self.label}] ' + ' | '.join(details), flush=True)
