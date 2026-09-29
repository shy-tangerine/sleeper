#!/usr/bin/env python3
"""Capture Sleeper CLI HTTP JSON bodies for the matched six-operation fixture."""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.async_api import async_playwright
from token_measurement import tokens

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli/sleeper"
DAEMON = ROOT / "daemon/daemon.py"
PACKAGE = ROOT / "build/sleeper-chromium.zip"
FIXTURE = ROOT / "benchmarks/fixture/server.py"
OUTPUT = ROOT / "benchmarks/results/sleeper-cli-protocol-capture.json"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CaptureProxy(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], target: tuple[str, int]):
        super().__init__(address, CaptureHandler)
        self.target = target
        self.records: list[dict[str, object]] = []
        self.lock = threading.Lock()


class CaptureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(length)
        target_host, target_port = self.server.target  # type: ignore[attr-defined]
        started = time.perf_counter()
        connection = http.client.HTTPConnection(target_host, target_port, timeout=20)
        try:
            connection.request("POST", self.path, body=request_body,
                               headers={"Content-Type": "application/json", "Accept": "application/json"})
            response = connection.getresponse()
            response_body = response.read()
            status = response.status
            reason = response.reason
        finally:
            connection.close()
        record = {
            "request_text": request_body.decode("utf-8"),
            "response_text": response_body.decode("utf-8"),
            "request_bytes": len(request_body),
            "response_bytes": len(response_body),
            "status": status,
            "proxy_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        with self.server.lock:  # type: ignore[attr-defined]
            self.server.records.append(record)  # type: ignore[attr-defined]
        self.send_response(status, reason)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(response_body)


def json_body(text: str) -> object:
    return json.loads(text)


def sanitized_text(text: str) -> str:
    """Canonicalize disposable fixture ports and browser tab ids for sharing."""
    text = re.sub(r"http://127\.0\.0\.1:\d+/", "http://127.0.0.1:<fixture-port>/", text)
    return re.sub(r'("tabId"\s*:\s*)\d+', r'\1<tab-id>', text)


async def main(iterations: int) -> None:
    missing = [str(path) for path in (CLI, DAEMON, PACKAGE, FIXTURE) if not path.is_file()]
    if missing:
        raise RuntimeError("Missing benchmark prerequisite(s): " + ", ".join(missing))
    work = Path(tempfile.mkdtemp(prefix="sleeper-cli-wire-"))
    profile, extension = work / "profile", work / "extension"
    daemon = fixture = None
    context = None
    result: dict[str, object] = {
        "schema": "sleeper-cli-http-json-bodies/v1",
        "status": "fail",
        "iterations": iterations,
        "operations": ["navigate", "read_h1", "type", "click", "wait_delayed_text", "read_result"],
        "measurement": {
            "protocol": "HTTP JSON request/response bodies for CLI POST /command",
            "excluded": ["HTTP headers", "HTTP framing", "CLI stdout/stderr", "model prompts and reasoning", "screenshots"],
            "fixture": "synthetic local page; no external network",
        },
        "runs": [],
    }
    try:
        shutil.unpack_archive(PACKAGE, extension, "zip")
        http_port, ws_port, proxy_port = free_port(), free_port(), free_port()
        env = {**os.environ, "SLEEPER_PORT": str(proxy_port), "SLEEPER_HTTP_PORT": str(http_port),
               "SLEEPER_WS_PORT": str(ws_port), "SLEEPER_TOKEN_FILE": str(work / "token"),
               "SLEEPER_PROFILE": "default", "HTTP_PROXY": f"http://127.0.0.1:{proxy_port}",
               "http_proxy": f"http://127.0.0.1:{proxy_port}", "NO_PROXY": "", "no_proxy": ""}
        canaries = {name: f"cli-wire-{name.lower()}" for name in ("COOKIE", "DOM", "LOCAL", "HEADER", "API")}
        fixture_env = {**env, **{f"SLEEPER_CANARY_{key}": value for key, value in canaries.items()}}
        fixture = subprocess.Popen([os.environ.get("PYTHON", "python3"), str(FIXTURE), "--port", "0"], cwd=ROOT,
                                   env=fixture_env, stdout=subprocess.PIPE, text=True)
        assert fixture.stdout is not None
        fixture_url = f"http://127.0.0.1:{json.loads(fixture.stdout.readline())['port']}/"
        background = extension / "background.js"
        background.write_text(background.read_text().replace("127.0.0.1:8790", f"127.0.0.1:{http_port}").replace("127.0.0.1:8789", f"127.0.0.1:{ws_port}"))
        daemon = subprocess.Popen([os.environ.get("PYTHON", "python3"), str(DAEMON)], cwd=ROOT, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        proxy = CaptureProxy(("127.0.0.1", proxy_port), ("127.0.0.1", http_port))
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True); proxy_thread.start()
        async with async_playwright() as playwright:
            chromium = os.environ.get("SLEEPER_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
            if not chromium:
                raise RuntimeError("Set SLEEPER_CHROMIUM or put Chromium on PATH")
            context = await playwright.chromium.launch_persistent_context(
                str(profile), executable_path=chromium,
                headless=True, args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}", "--no-first-run"])
            for _ in range(40):
                if context.service_workers: break
                await asyncio.sleep(.25)
            if not context.service_workers:
                raise RuntimeError("extension worker did not start")
            await context.service_workers[0].evaluate("chrome.storage.local.set({profile: 'default'})")
            for run in range(1, iterations + 1):
                before = len(proxy.records)
                # Keep the six CLI calls explicit so each captured body maps to one operation.
                args_list = [("goto", [fixture_url]), ("read", ["h1"]), ("type", ["#input", f"cli-wire-{run}"]),
                             ("click", ["#action"]), ("wait_text", ["Delayed state ready", "--timeout", "5000"]),
                             ("read", ["#result"])]
                for command, args in args_list:
                    process = await asyncio.to_thread(subprocess.run, [str(CLI), command, *args], cwd=ROOT, env=env, text=True,
                                             capture_output=True, timeout=20)
                    if process.returncode != 0:
                        raise RuntimeError(f"CLI {command} failed: {process.stderr[-500:]}")
                    # The command runs in a worker so Playwright can receive tab events.
                    await asyncio.sleep(.1)
                fixture_pages = [page for page in context.pages if fixture_url.rstrip("/") in page.url]
                if not fixture_pages:
                    raise RuntimeError(f"fixture page missing; pages={[page.url for page in context.pages]!r}; captures={len(proxy.records)}")
                page = fixture_pages[-1]
                verified = await page.evaluate("""() => ({h1:document.querySelector('h1').textContent,input:document.querySelector('#input').value,visible:!document.querySelector('#result').hidden,delayed:document.querySelector('#delayed').textContent})""")
                expected = {"h1": "Synthetic browser benchmark", "input": f"cli-wire-{run}", "visible": True, "delayed": "Delayed state ready"}
                if verified != expected:
                    raise RuntimeError(f"fixture verification failed: {verified!r}")
                records = proxy.records[before:]
                if len(records) != 6:
                    raise RuntimeError(f"expected six captured requests, got {len(records)}")
                steps = []
                for operation, record in zip(result["operations"], records):  # type: ignore[index]
                    steps.append({"operation": operation, **record,
                                  "request_text_sanitized": sanitized_text(record["request_text"]),
                                  "response_text_sanitized": sanitized_text(record["response_text"]),
                                  "request_json": json_body(record["request_text"]),
                                  "response_json": json_body(record["response_text"])})
                result["runs"].append({"run": run, "status": "pass", "steps": steps,
                  "request_tokens": sum(tokens(s["request_text"]) for s in steps),
                  "response_tokens": sum(tokens(s["response_text"]) for s in steps),
                  "total_tokens": sum(tokens(s["request_text"]) + tokens(s["response_text"]) for s in steps)})  # type: ignore[union-attr]
        result["status"] = "pass"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if context:
            try: await context.close()
            except Exception: pass
        if daemon:
            daemon.terminate()
            try: daemon.wait(timeout=5)
            except subprocess.TimeoutExpired: daemon.kill()
        if fixture:
            fixture.terminate()
            try: fixture.wait(timeout=5)
            except subprocess.TimeoutExpired: fixture.kill()
        if "proxy" in locals(): proxy.shutdown(); proxy.server_close()
        shutil.rmtree(work, ignore_errors=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "pass": raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    asyncio.run(main(parser.parse_args().iterations))
