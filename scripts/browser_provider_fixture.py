"""Route AA to a local TLS fixture before Chrome opens any extension-created tab.

Playwright page routes can attach after a new tab's first navigation. Browser DNS
mapping makes even that first request local. Only this ephemeral certificate is
trusted, in the isolated test browser; no OS trust or personal profile is changed.
"""

import base64
import hashlib
import ssl
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@contextmanager
def provider_fixture(respond):
    with tempfile.TemporaryDirectory(prefix="lp-provider-fixture-") as temp:
        cert, key = Path(temp) / "cert.pem", Path(temp) / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=www.aadvantagehotels.com",
                "-addext",
                "subjectAltName=DNS:www.aadvantagehotels.com",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            capture_output=True,
        )
        public = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"],
            check=True,
            capture_output=True,
        ).stdout
        der = subprocess.run(
            ["openssl", "pkey", "-pubin", "-outform", "DER"],
            input=public,
            check=True,
            capture_output=True,
        ).stdout
        spki = base64.b64encode(hashlib.sha256(der).digest()).decode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content_type, body = respond(self.path)
                payload = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield [
                f"--host-resolver-rules=MAP www.aadvantagehotels.com 127.0.0.1:{server.server_port}",
                f"--ignore-certificate-errors-spki-list={spki}",
                "--no-proxy-server",
            ]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
