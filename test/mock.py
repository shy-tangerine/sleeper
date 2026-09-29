#!/usr/bin/env python3
"""Throwaway mock HTTP server for the Sleeper CLI regression harness.

Captures every POST body to /command into a line-delimited JSON log
({path, body}) and responds {"ok":true}. run.sh starts it, points
SLEEPER_PORT at it, drives the real `sleeper` CLI, then tears it down.
"""
import json
import hashlib
import hmac
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG = os.environ["MOCK_LOG"]
PORTF = os.environ["MOCK_PORT_FILE"]
READYF = os.environ["MOCK_READY"]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok(self):
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        nonce = parse_qs(urlparse(self.path).query).get("nonce", [""])[0]
        token_file = Path(os.path.expanduser(os.environ.get(
            "SLEEPER_TOKEN_FILE", "~/.config/browser-sleeper-token"
        )))
        token = token_file.read_text(encoding="utf-8").strip()
        instance = "mock-instance"
        proof = hmac.new(token.encode(), f"{nonce}:{instance}".encode(), hashlib.sha256).hexdigest()
        body = json.dumps({"ok": True, "instance_id": instance, "identity_proof": proof}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        with open(LOG, "a") as f:
            f.write(json.dumps({"path": path, "body": body}) + "\n")
        self._ok()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    with open(PORTF, "w") as f:
        f.write(str(srv.server_address[1]))
    with open(READYF, "w") as f:
        f.write("ready")
    srv.serve_forever()


if __name__ == "__main__":
    main()
