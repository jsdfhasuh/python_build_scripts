"""Inspect the effective branding configuration; never compile or publish anything."""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_config import BuildConfigError
from build_config import resolveBuildConfig
from console_utils import configureConsole


def main() -> int:
  configureConsole()
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--config', type=Path, default=ROOT / 'configs/emo-vision-train.json')
  parser.add_argument('--branding-profile')
  parser.add_argument('--program-name')
  parser.add_argument('--icon-path')
  parser.add_argument('--release-asset-name')
  parser.add_argument('--release-tag')
  parser.add_argument('--manifest-name', default='manifest.json')
  parser.add_argument('--check-publication', action='store_true')
  parser.add_argument('--output', type=Path, help='New private JSON file; never overwrite a file')
  args = parser.parse_args()
  try:
    resolved = resolveBuildConfig(
      args.config, profilePath=args.branding_profile, programName=args.program_name,
      iconPath=args.icon_path, releaseAssetName=args.release_asset_name,
    )
    summary = resolved.summary()
    if args.release_tag is not None:
      summary['release_asset_name'] = resolved.assetName(args.release_tag, args.manifest_name)
    if args.check_publication:
      resolved.assertPublicationAllowed()
    payload = {'schema_version': 1, 'config': resolved.config, 'summary': summary}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    if args.output:
      # Do not create directories or replace input configs implicitly.
      with args.output.open('x', encoding='utf-8') as stream:
        stream.write(text)
    print(text, end='')
    return 0
  except (BuildConfigError, OSError) as exc:
    print(f'Configuration error: {exc}', file=sys.stderr)
    return 1


if __name__ == '__main__':
  raise SystemExit(main())
