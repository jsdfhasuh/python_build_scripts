import contextlib
import io
import unittest
from threading import Event
from unittest.mock import patch

from release_progress import ReleaseProgress


class ReleaseProgressTests(unittest.TestCase):
  def test_byte_file_counts_and_completion_are_flushed(self) -> None:
    with patch('release_progress.print') as emit:
      with ReleaseProgress('verify', totalBytes=4, totalFiles=1) as progress:
        progress.advance(byteCount=2)
        progress.report('working')
        progress.advance(byteCount=2, fileCount=1)
    text = '\n'.join(call.args[0] for call in emit.call_args_list)
    self.assertIn('50.0%', text)
    self.assertIn('100.0%', text)
    self.assertIn('1/1 files', text)
    self.assertIn('completed', text)
    self.assertIn('elapsed', text)
    self.assertTrue(all(call.kwargs == {'flush': True} for call in emit.call_args_list))
    self.assertFalse(progress.thread.is_alive())

  def test_unknown_totals_report_heartbeat_without_fake_percent(self) -> None:
    heartbeat = Event()
    def emit(text, **kwargs):
      if 'working' in text:
        heartbeat.set()
    with patch('release_progress.print', side_effect=emit) as output:
      with ReleaseProgress('upload', interval=0.01) as progress:
        self.assertTrue(heartbeat.wait(2), 'Long operations must emit a heartbeat')
    text = '\n'.join(call.args[0] for call in output.call_args_list)
    self.assertNotIn('%', text)
    self.assertIn('completed', text)
    self.assertFalse(progress.thread.is_alive())

  def test_error_and_cancellation_do_not_report_completion(self) -> None:
    for error in (ValueError('bad ZIP'), KeyboardInterrupt()):
      with self.subTest(error=type(error)), contextlib.redirect_stdout(io.StringIO()) as output:
        with self.assertRaises(type(error)):
          with ReleaseProgress('verify') as progress:
            raise error
        self.assertIn('failed', output.getvalue())
        self.assertNotIn('completed', output.getvalue())
        self.assertFalse(progress.thread.is_alive())

  def test_empty_totals_do_not_divide_by_zero(self) -> None:
    with contextlib.redirect_stdout(io.StringIO()) as output:
      with ReleaseProgress('empty', totalBytes=0, totalFiles=0):
        pass
    self.assertIn('completed', output.getvalue())
    self.assertIn('0/0 files', output.getvalue())


if __name__ == '__main__':
  unittest.main()
