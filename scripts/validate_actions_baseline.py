"""Validate frozen assets using the selected source's protocol implementation."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source-root', type=Path, required=True)
  parser.add_argument('--lock', type=Path, required=True)
  args = parser.parse_args()
  source = args.source_root.resolve()
  helper = source / 'update_release.py'
  result = subprocess.run([sys.executable, str(helper), '--help'], cwd=source,
                          capture_output=True, text=True, check=False, timeout=60)
  if result.returncode or '--base-files' not in result.stdout:
    raise ValueError('Source producer must support --base-files for frozen delta baselines')
  sys.path.insert(0, str(source))
  from update_contract import Asset
  from update_contract import Identity
  from update_contract import Manifest
  from update_package import prepare_candidate

  lock = json.loads(args.lock.read_text(encoding='utf-8'))
  directory = Path(lock['directory'])
  identityName = 'VisionWorkshop-windows-x86_64-release_identity.json'
  identityBytes = (directory / identityName).read_bytes()
  identity = Identity.parse(identityBytes)
  metadata = json.loads(identityBytes)
  if (identity.release_tag != lock['tag']
      or metadata.get('source', {}).get('repository') != lock['source_repository']):
    raise ValueError('Baseline identity does not match the selected release/source repository')
  manifest = Manifest.parse((directory / lock['files_name']).read_bytes())
  manifest.bind_identity(identity)
  asset = Asset.parse(lock['assets'][lock['full_name']])
  # The source consumer validates both archive inventory and every extracted file.
  with tempfile.TemporaryDirectory(prefix='baseline-verification-', dir=directory) as temporary:
    prepare_candidate(directory / asset.name, Path(temporary) / 'candidate',
                      asset, manifest, identity)
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
