"""Validate frozen assets using the selected source's protocol implementation."""

import argparse
import json
import subprocess
import sys
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
  from update_package import _transfer
  from update_payload import PayloadArchive
  from update_storage import read_bytes

  lock = json.loads(args.lock.read_text(encoding='utf-8'))
  directory = Path(lock['directory'])
  identityName = 'VisionWorkshop-windows-x86_64-release_identity.json'
  identityBytes = read_bytes(directory / identityName, 65536)
  identity = Identity.parse(identityBytes)
  metadata = json.loads(identityBytes)
  if (identity.release_tag != lock['tag']
      or metadata.get('source', {}).get('repository') != lock['source_repository']):
    raise ValueError('Baseline identity does not match the selected release/source repository')
  manifest = Manifest.parse(read_bytes(directory / lock['files_name'], 32 * 1024**2))
  manifest.bind_identity(identity)
  asset = Asset.parse(lock['assets'][lock['full_name']])
  # Validate the frozen baseline through the same protocol-3 archive consumer,
  # streaming all payload hashes without constructing a complete candidate copy.
  with PayloadArchive(directory / asset.name, asset, manifest, manifest, identity) as package:
    for path, member in package.payload.items():
      with package.archive.open(member) as stream:
        _transfer(stream, expected=manifest.files[path])
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
