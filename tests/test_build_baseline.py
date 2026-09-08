"""Protect the unchanged default target contracts without external application code."""

import contextlib
import hashlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import build


ROOT = Path(__file__).resolve().parents[1]


class DefaultBuildTests(unittest.TestCase):
  def setUp(self) -> None:
    self.stack = contextlib.ExitStack()
    self.addCleanup(self.stack.close)
    self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    self.stack.enter_context(patch.dict(os.environ, {'SOURCE_ROOT': 'SOURCE_ROOT'}))
    self.stack.enter_context(patch('build.validate_build_paths'))
    self.stack.enter_context(patch('build._ensure_torch_runtime_hook', return_value='torch-hook.py'))
    self.stack.enter_context(patch('build._find_python_dll', return_value=None))
    self.stack.enter_context(patch('build._collect_python_runtime_dlls', return_value=[]))
    self.stack.enter_context(patch('build._collect_conda_runtime_dlls', return_value=[]))

  def config(self, target: str) -> dict:
    return build.load_config(str(ROOT / 'configs' / f'{target}.json'))

  def test_target_configuration_semantics_are_pinned(self) -> None:
    expected = {
      'emo-vision-train': '4a7189ac214a997bea9ac2c23830591c2068be4a8b68f79562c0f5f49f2c2de9',
      'emo-master': 'd36a9dd53f6a6e344ba21c9c2d8307c65fe59c10972c2ee5278d62933c1065c9',
    }
    for target, digest in expected.items():
      with self.subTest(target=target):
        data = json.loads((ROOT / 'configs' / f'{target}.json').read_text(encoding='utf-8'))
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8')
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), digest)

  def test_vision_default_commands_match_baseline(self) -> None:
    config = self.config('emo-vision-train')
    commands = build.build_job_commands(config, clean=True)
    self.assertEqual([job.label for job, _ in commands], ['main', 'updater'])
    main, updater = (command for _, command in commands)
    expected = [*build.PYINSTALLER_CMD, '--noconfirm', '--clean', '--name', 'emo-vision-train']
    expected += [f'--add-data={item}' for item in build.normalize_add_data(config['add_data'])]
    expected += [f'--hidden-import={item}' for item in config['hidden_imports']]
    expected += ['--runtime-hook', 'torch-hook.py', '--noupx',
                 '--collect-binaries=torch', '--collect-binaries=torchvision',
                 '--collect-binaries=python']
    expected += config['extra_args'] + [os.path.normpath('SOURCE_ROOT/main.py')]
    self.assertEqual(main, expected)
    self.assertEqual(updater, [*build.PYINSTALLER_CMD, '--noconfirm', '--clean',
                              '--name', 'updater', '--onefile',
                              os.path.normpath('SOURCE_ROOT/updater.py')])
    self.assertNotIn('--distpath', main)
    self.assertNotIn('--workpath', main)
    self.assertNotIn('--onefile', main)

  def test_master_default_command_matches_baseline(self) -> None:
    config = self.config('emo-master')
    commands = build.build_job_commands(config, clean=False)
    self.assertEqual(len(commands), 1)
    command = commands[0][1]
    expected = [*build.PYINSTALLER_CMD, '--noconfirm', '--name', 'EmoMaster', '--noconsole']
    expected += [f'--add-data={item}' for item in build.normalize_add_data(config['add_data'])]
    expected += [f'--hidden-import={item}' for item in config['hidden_imports']]
    expected += [f'--exclude-module={item}' for item in config['excludes']]
    expected += ['--collect-binaries=onnxruntime', '--collect-binaries=python']
    expected += config['extra_args'] + [os.path.normpath(config['entry'])]
    self.assertEqual(command, expected)
    self.assertFalse(build.needs_torch_runtime(commands[0][0]))
    self.assertFalse(build.needs_conda_runtime_dlls(commands[0][0]))

  def test_default_specpath_remains_available(self) -> None:
    commands = build.build_job_commands(self.config('emo-vision-train'), False, 'legacy-spec')
    for _, command in commands:
      self.assertEqual(command[command.index('--specpath') + 1], 'legacy-spec')

  def test_default_loader_does_not_read_profile(self) -> None:
    config = self.config('emo-vision-train')
    self.assertEqual(config['name'], 'emo-vision-train')
    self.assertIsNone(config['icon'])
    self.assertNotIn('installer', config)

  def test_commands_do_not_mutate_target_config(self) -> None:
    config = self.config('emo-vision-train')
    original = json.dumps(config, sort_keys=True)
    build.build_job_commands(config, clean=True)
    self.assertEqual(json.dumps(config, sort_keys=True), original)

  def test_runtime_collectors_keep_original_selection(self) -> None:
    job = build.create_main_job(self.config('emo-vision-train'))
    self.assertTrue(build.needs_torch_runtime(job))
    self.assertTrue(build.needs_conda_runtime_dlls(job))
    self.assertEqual(build.get_conda_runtime_dest(job), 'torch/lib')
    updater = build.create_updater_job(self.config('emo-vision-train'))
    self.assertFalse(updater.collect_python_binary)
    self.assertFalse(build.needs_torch_runtime(updater))

  def test_legacy_onefile_without_updater_is_unchanged(self) -> None:
    config = {'name': 'single', 'entry': 'main.py', 'onefile': True}
    command = build.build_command(config, clean=False)
    self.assertIn('--onefile', command)


if __name__ == '__main__':
  unittest.main()
