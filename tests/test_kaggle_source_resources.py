import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build_config import resolveBuildConfig
from vision_train_runtime import KAGGLE_SOURCE_FILES


ROOT = Path(__file__).resolve().parents[1]


class KaggleSourceResourcesTests(unittest.TestCase):
  def test_effective_config_preserves_source_data_with_profile_and_overrides(self):
    with tempfile.TemporaryDirectory() as directory:
      source = Path(directory).resolve()
      with patch.dict(os.environ, {'SOURCE_ROOT': str(source)}):
        for options in ({}, {'profilePath': 'profiles/visionworkshop.json'},
                        {'profilePath': 'profiles/visionworkshop.json',
                         'programName': 'VisionWorkshop',
                         'iconPath': str(ROOT / 'assets/icons/visionworkshop.ico')}):
          with self.subTest(options=options):
            config = resolveBuildConfig(ROOT / 'configs/emo-vision-train.json',
                                        **options).config
            mappings = [item.rsplit(':', 1) for item in config['add_data']]
            for name in KAGGLE_SOURCE_FILES:
              expected = source / name
              matches = []
              for origin, destination in mappings:
                origin = Path(origin)
                destination = destination.replace('\\', '/')
                if expected == origin:
                  matches.append(destination.rstrip('/') + '/' + origin.name)
                elif expected.is_relative_to(origin):
                  matches.append(destination.rstrip('/') + '/' +
                                 expected.relative_to(origin).as_posix())
              self.assertEqual(matches, [name], name)


if __name__ == '__main__':
  unittest.main()
