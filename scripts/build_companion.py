"""Build a domain-bound Chrome companion zip. Does not publish or install it."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aa_hotel_optimizer.companion_package import build_package

parser = argparse.ArgumentParser()
parser.add_argument("--origin", required=True)
parser.add_argument("--output", default=".local/lp-companion.zip")
args = parser.parse_args()
try:
    package = build_package(args.origin)
except ValueError as error:
    parser.error(str(error))
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(package)
print(f"Built {output} for {args.origin.rstrip('/')}")
