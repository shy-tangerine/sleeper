#!/usr/bin/env python3
"""Deterministic local fixture for the comparable-browser benchmark."""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HTML = """<!doctype html>
<meta charset="utf-8"><title>Sleeper synthetic fixture</title>
<main>
  <h1>Synthetic browser benchmark</h1>
  <p id="dom-canary">DOM canary: {dom}</p>
  <label>Input <input id="input" name="synthetic-input"></label>
  <button id="action" type="button">Run action</button>
  <p id="result" hidden>Action complete</p>
  <p id="delayed">Loading delayed state…</p>
  <img alt="Synthetic media" src="/media.svg">
</main>
<script>
localStorage.setItem("sleeper_local_canary", {local_json});
setTimeout(() => document.querySelector("#delayed").textContent = "Delayed state ready", 250);
document.querySelector("#action").onclick = () => document.querySelector("#result").hidden = false;
fetch("/api/ping", {headers: {"X-Sleeper-Canary": {header_json}}});
</script>
"""


class Handler(BaseHTTPRequestHandler):
    canary: dict[str, str] = {}

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", f"sleeper_cookie_canary={self.canary['cookie']}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = (HTML.replace("{dom}", self.canary["dom"])
                    .replace("{local_json}", json.dumps(self.canary["local"]))
                    .replace("{header_json}", json.dumps(self.canary["header"]))).encode()
            self.send(200, body, "text/html; charset=utf-8")
        elif self.path == "/api/ping":
            self.send(200, json.dumps({"ok": True, "status": "fixture-ready", "canary": self.canary["api"]}).encode(), "application/json")
        elif self.path == "/api/same-host":
            self.send(200, b'{"ok":true,"same_host":true}', "application/json")
        elif self.path == "/media.svg":
            self.send(200, b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="#4263eb"/></svg>', "image/svg+xml")
        else:
            self.send(404, b"not found", "text/plain")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    Handler.canary = {
        "cookie": os.environ["SLEEPER_CANARY_COOKIE"],
        "dom": os.environ["SLEEPER_CANARY_DOM"],
        "local": os.environ["SLEEPER_CANARY_LOCAL"],
        "header": os.environ["SLEEPER_CANARY_HEADER"],
        "api": os.environ["SLEEPER_CANARY_API"],
    }
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"host": "127.0.0.1", "port": server.server_port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
