"""Protect archive subprocess boundaries and Windows long-path fallback."""

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from build_records import scanFiles
from path_boundary import ioPath
from path_boundary import logicalPath
from portable_release import compressArchive
from portable_release import verifyArchive


class ArchivePathTests(unittest.TestCase):
  def test_7zip_shim_receives_logical_working_directory(self):
    with tempfile.TemporaryDirectory() as directory:
      root = logicalPath(directory)
      app = root / 'VisionWorkshop'
      app.mkdir()
      output = root / 'archive.zip'

      def run(command, *, cwd, check):
        # Model the .NET shim's GetCurrentDirectory failure seen on Actions.
        self.assertFalse(str(cwd).startswith('\\\\?\\'))
        self.assertEqual(cwd, root)
        self.assertIn(str(ioPath(output)), command)
        self.assertEqual(command[-1], f'.{os.sep}VisionWorkshop')
        self.assertFalse(check)
        return subprocess.CompletedProcess(command, 0)

      with patch('portable_release.shutil.which', return_value='7z'), \
           patch('portable_release.subprocess.run', side_effect=run) as process:
        self.assertEqual(compressArchive(ioPath(app), output), 'zip/lzma')
      process.assert_called_once()

  @unittest.skipUnless(os.name == 'nt', 'Windows extended paths')
  def test_deep_working_directory_falls_back_without_losing_long_members(self):
    root = logicalPath(tempfile.mkdtemp())
    self.addCleanup(shutil.rmtree, ioPath(root))
    parent = root
    while len(str(parent)) < 280:
      parent /= 'nested-directory-0123456789'
    app = parent / 'VisionWorkshop'
    payload = app / '_internal' / 'hidden-resource.txt'
    ioPath(payload.parent).mkdir(parents=True)
    ioPath(payload).write_bytes(b'long-path-content')
    ioPath(app / '.keep').write_bytes(b'')
    output = parent / 'archive.zip'
    expected = scanFiles(app)
    with patch('portable_release.shutil.which', return_value='7z'), \
         patch('portable_release.subprocess.run') as process:
      self.assertEqual(compressArchive(app, output), 'zip/deflate')
    process.assert_not_called()
    verifyArchive(output, app.name, expected)
    with zipfile.ZipFile(ioPath(output)) as archive:
      self.assertEqual(archive.read('VisionWorkshop/_internal/hidden-resource.txt'),
                       b'long-path-content')
      self.assertEqual(archive.read('VisionWorkshop/.keep'), b'')


if __name__ == '__main__':
  unittest.main()
