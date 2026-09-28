"""Build the identical domain-bound companion for downloads and store uploads."""

import io
import json
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile


def build_package(origin: str) -> bytes:
    url = urlparse(origin)
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
        raise ValueError("Use an HTTPS app origin or an HTTP loopback origin.")
    origin = origin.rstrip("/")
    root = Path(__file__).resolve().parents[1] / "companion"
    manifest = json.loads((root / "manifest.json").read_text())
    pattern = f"{url.scheme}://{url.hostname}/*"
    manifest["host_permissions"] = ["https://www.aadvantagehotels.com/*", pattern]
    manifest["content_scripts"][0]["matches"] = [pattern]
    if url.hostname == "aahoteloptimizer.streamlit.app":
        # This edition receives work from the open planner; it needs no alarm.
        manifest["permissions"].remove("alarms")
    if url.scheme == "https":
        manifest["name"] = "LP Optimizer Companion"
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in sorted(root.iterdir()):
            if file.suffix not in (".json", ".js", ".html", ".css", ".png"):
                continue
            content = (
                json.dumps(manifest, indent=2).encode()
                if file.name == "manifest.json"
                else f"globalThis.LP_APP_ORIGIN = {json.dumps(origin)};\n".encode()
                if file.name == "config.js"
                else file.read_bytes()
            )
            archive.writestr(file.name, content)
    return output.getvalue()
