"""Build a domain-bound Chrome companion zip. Does not publish or install it."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile

parser = argparse.ArgumentParser()
parser.add_argument("--origin", required=True)
parser.add_argument("--output", default=".local/lp-companion.zip")
args = parser.parse_args()
url = urlparse(args.origin)
if (
    url.path not in ("", "/")
    or url.query
    or url.fragment
    or url.username
    or not url.hostname
    or (
        url.scheme != "https"
        and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost"))
    )
):
    parser.error("Use an HTTPS app origin or an HTTP loopback origin.")
origin = args.origin.rstrip("/")
root = Path(__file__).resolve().parents[1] / "companion"
manifest = json.loads((root / "manifest.json").read_text())
# Chrome match patterns omit ports; content.js additionally checks the exact origin.
pattern = f"{url.scheme}://{url.hostname}/*"
manifest["host_permissions"] = ["https://www.aadvantagehotels.com/*", pattern]
manifest["content_scripts"][0]["matches"] = [pattern]
if url.scheme == "https":
    manifest["name"] = "LP Optimizer Companion"
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for file in root.iterdir():
        if file.suffix not in (".json", ".js", ".html", ".css"):
            continue
        content = (
            json.dumps(manifest, indent=2)
            if file.name == "manifest.json"
            else (
                f"globalThis.LP_APP_ORIGIN = {json.dumps(origin)};\n"
                if file.name == "config.js"
                else file.read_text()
            )
        )
        archive.writestr(file.name, content)
print(f"Built {output} for {origin}")
