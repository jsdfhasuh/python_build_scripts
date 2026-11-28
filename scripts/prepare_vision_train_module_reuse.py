"""Download exact completed-run artifacts for optional byte-preserving ZIP reuse."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision_train_modular_reuse import prepareReuse


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--run-id', type=int, required=True)
  parser.add_argument('--attempt', type=int, default=1)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  if args.run_id <= 0 or args.attempt <= 0:
    parser.error('Source run and attempt must be positive integers')
  receipt = prepareReuse(args.run_id, args.attempt, args.output.resolve())
  print('Verified completed source artifacts:', receipt['source_run']['id'],
        'modules:', len(receipt['modules']), 'prior result:', receipt['source_product_acceptance']['status'])
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
