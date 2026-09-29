#!/usr/bin/env python3
"""Direct-CDP baseline for the local six-operation browser fixture.

This sends Chrome DevTools Protocol messages over a direct WebSocket connection
using the repository's existing ``websockets`` transport dependency. It does
not use Playwright, Selenium, or a CDP client library. Results retain the
actual CDP method/request/response exchange and its protocol-token estimate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.request import urlopen
import re

import psutil
from websockets.sync.client import connect

from token_measurement import ENCODING, compact, sample


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks/fixture/server.py"
OUTPUT = ROOT / "benchmarks/results/cdp-matched-results.json"
ITERATIONS = 5


def chromium_path() -> str:
    configured = os.environ.get("SLEEPER_CHROMIUM")
    if configured:
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("Set SLEEPER_CHROMIUM to a Chromium-family browser executable; none was found on PATH.")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def browser_scope(profile: Path) -> dict[str, object]:
    marker = f"--user-data-dir={profile}"
    process_count = 0
    rss = 0
    cpu = 0.0
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            if marker not in " ".join(process.info["cmdline"] or []):
                continue
            process_count += 1
            rss += process.memory_info().rss
            times = process.cpu_times()
            cpu += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {
        "scope": "all Chromium processes whose command line has this disposable --user-data-dir",
        "process_count": process_count,
        "rss_bytes": rss,
        "cpu_seconds": round(cpu, 6),
    }


class CDP:
    def __init__(self, websocket_url: str):
        self.ws = connect(websocket_url, open_timeout=10, close_timeout=2)
        self.next_id = 1
        self.events: list[dict[str, Any]] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        request = {"id": self.next_id, "method": method}
        self.next_id += 1
        if params:
            request["params"] = params
        self.ws.send(compact(request))
        while True:
            response = json.loads(self.ws.recv())
            if response.get("id") == request["id"]:
                if "error" in response:
                    raise RuntimeError(f"CDP {method} failed: {response['error']}")
                return request, response
            self.events.append(response)

    def wait_event(self, method: str, timeout_seconds: float = 10) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            for index, event in enumerate(self.events):
                if event.get("method") == method:
                    return self.events.pop(index)
            try:
                self.events.append(json.loads(self.ws.recv(timeout=max(0.01, deadline - time.monotonic()))))
            except TimeoutError:
                break
        raise TimeoutError(f"CDP event {method} was not received")

    def close(self) -> None:
        self.ws.close()


def endpoint(port: int) -> dict[str, Any]:
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
        return json.loads(response.read())


def wait_for_endpoint(port: int) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return endpoint(port)
        except Exception as exc:  # Chrome has not opened the debugging socket yet.
            last = exc
            time.sleep(0.1)
    raise RuntimeError(f"Chromium did not expose CDP on port {port}: {last}")


def page_socket(port: int, target_id: str) -> str:
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
        pages = json.loads(response.read())
    for page in pages:
        if page.get("id") == target_id:
            return str(page["webSocketDebuggerUrl"])
    raise RuntimeError(f"CDP target {target_id} was not listed")


def protocol_record(request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    item = sample(compact(request), compact(response))
    item.update({
        "method": request["method"],
        "request": sanitize_capture(request),
        "response": sanitize_capture(response),
    })
    return item


def sanitize_capture(value: Any) -> Any:
    """Canonicalize CDP's volatile local identifiers before publishing a run."""
    if isinstance(value, list):
        return [sanitize_capture(item) for item in value]
    if not isinstance(value, dict):
        if not isinstance(value, str):
            return value
        value = re.sub(r"127\.0\.0\.1:\d{1,5}", "127.0.0.1:<PORT>", value)
        value = re.sub(r"\b[A-F0-9]{32}\b", "<CDP_IDENTIFIER>", value)
        return re.sub(r"matched-\d+", "matched-N", value)
    return {
        key: (0 if key == "id" and isinstance(item, int) else sanitize_capture(item))
        for key, item in value.items()
    }


def totals(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "request_tokens": sum(int(record["request_tokens"]) for record in records),
        "response_tokens": sum(int(record["response_tokens"]) for record in records),
        "total_tokens": sum(int(record["total_tokens"]) for record in records),
    }


def value(response: dict[str, Any]) -> Any:
    return response["result"]["result"].get("value")


def evaluate(cdp: CDP, expression: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})


def operation(cdp: CDP, name: str, calls: list[tuple[str, dict[str, Any] | None]], expected: Any) -> dict[str, Any]:
    """Execute one outcome-level operation, retaining every CDP sub-request."""
    started = time.perf_counter()
    protocol: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    for method, params in calls:
        request, response = cdp.call(method, params)
        protocol.append(protocol_record(request, response))
        final = response
    assert final is not None
    if expected is not None:
        assert value(final) == expected, (name, value(final), expected)
    result = {
        "operation": name,
        "ms": round((time.perf_counter() - started) * 1000, 3),
        "protocol": protocol,
        "protocol_tokens": totals(protocol),
    }
    return result


def wait_text(cdp: CDP, text: str) -> dict[str, Any]:
    started = time.perf_counter()
    protocol: list[dict[str, Any]] = []
    expression = f"document.body.innerText.includes({json.dumps(text)})"
    while time.perf_counter() - started < 5:
        request, response = evaluate(cdp, expression)
        protocol.append(protocol_record(request, response))
        if value(response) is True:
            return {
                "operation": "wait_delayed_text",
                "ms": round((time.perf_counter() - started) * 1000, 3),
                "protocol": protocol,
                "protocol_tokens": totals(protocol),
            }
        time.sleep(0.025)
    raise TimeoutError(f"Timed out waiting for {text!r}")


def main() -> None:
    if not FIXTURE.is_file():
        raise RuntimeError(f"Missing fixture: {FIXTURE}")
    work = Path(tempfile.mkdtemp(prefix="cdp-matched-"))
    profile = work / "profile"
    debug_port = free_port()
    canaries = {name: f"matched-cdp-{name.lower()}" for name in ("COOKIE", "DOM", "LOCAL", "HEADER", "API")}
    env = {**os.environ, **{f"SLEEPER_CANARY_{key}": item for key, item in canaries.items()}}
    result: dict[str, Any] = {
        "schema": "direct-cdp-matched-browser-primitives/v1",
        "status": "fail",
        "iterations": ITERATIONS,
        "mode": "deterministic browser primitives; excludes agent/model performance",
        "browser": "same Chromium binary, one fresh disposable persistent profile",
        "browser_baseline_excluded": True,
        "operations": ["navigate", "read_h1", "type", "click", "wait_delayed_text", "read_result"],
        "canaries": canaries,
        "transport": {"protocol": "Chrome DevTools Protocol over direct RFC 6455 WebSocket", "client": "websockets.sync.client transport; no Playwright/Selenium/CDP client library"},
        "token_method": {
            "encoding": ENCODING,
            "protocol_scope": "actual serialized compact JSON CDP requests and responses recorded below",
            "excluded": ["model prompts and reasoning", "WebSocket handshake/framing", "browser events not used as operation responses"],
            "interpretation": "a low-level CDP transport baseline; it has no default agent-context or model-billing meaning",
        },
        "capture_normalization": {
            "stored_protocol": "CDP request/response JSON preserves methods and message shape; local ports, numeric request IDs, 32-character CDP frame/loader/target identifiers, and matched run values are replaced with stable placeholders.",
            "token_text": "token_measurement.py canonicalizes fixture ports and numeric request IDs before o200k_base counting.",
            "excluded_host_details": "Disposable-profile paths are never recorded; browser process identifiers are reduced to process_count.",
        },
        "runs": [],
    }
    fixture: subprocess.Popen[str] | None = None
    browser: subprocess.Popen[bytes] | None = None
    browser_cdp: CDP | None = None
    page_cdp: CDP | None = None
    try:
        fixture = subprocess.Popen([sys.executable, str(FIXTURE), "--port", "0"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert fixture.stdout is not None
        fixture_url = f"http://127.0.0.1:{json.loads(fixture.stdout.readline())['port']}/"
        browser = subprocess.Popen([
            chromium_path(), "--headless=new", f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        startup = time.perf_counter()
        version = wait_for_endpoint(debug_port)
        result["startup_ms"] = round((time.perf_counter() - startup) * 1000, 3)
        result["browser_version"] = version.get("Browser")

        browser_cdp = CDP(str(version["webSocketDebuggerUrl"]))
        setup_records: list[dict[str, Any]] = []
        request, response = browser_cdp.call("Target.createTarget", {"url": "about:blank"})
        setup_records.append(protocol_record(request, response))
        target_id = response["result"]["targetId"]
        page_cdp = CDP(page_socket(debug_port, target_id))
        request, response = page_cdp.call("Page.enable")
        setup_records.append(protocol_record(request, response))
        result["setup"] = {"protocol": setup_records, "protocol_tokens": totals(setup_records), "event_subscription": "Page.enable; Page.loadEventFired is consumed only to establish navigation completion"}

        initial_cpu = browser_scope(profile)["cpu_seconds"]
        for run in range(1, ITERATIONS + 1):
            assert page_cdp is not None
            before = browser_scope(profile)
            row: dict[str, Any] = {"run": run, "status": "fail", "steps": []}
            started = time.perf_counter()

            nav_request, nav_response = page_cdp.call("Page.navigate", {"url": fixture_url})
            page_cdp.wait_event("Page.loadEventFired")
            nav_protocol = [protocol_record(nav_request, nav_response)]
            row["steps"].append({
                "operation": "navigate", "ms": round((time.perf_counter() - started) * 1000, 3),
                "protocol": nav_protocol, "protocol_tokens": totals(nav_protocol),
            })
            row["steps"].append(operation(page_cdp, "read_h1", [("Runtime.evaluate", {"expression": "document.querySelector('h1').innerText", "returnByValue": True})], "Synthetic browser benchmark"))
            row["steps"].append(operation(page_cdp, "type", [
                ("Runtime.evaluate", {"expression": "document.querySelector('#input').focus()", "returnByValue": True}),
                ("Input.insertText", {"text": f"matched-{run}"}),
                ("Runtime.evaluate", {"expression": "document.querySelector('#input').value", "returnByValue": True}),
            ], f"matched-{run}"))
            row["steps"].append(operation(page_cdp, "click", [("Runtime.evaluate", {"expression": "document.querySelector('#action').click()", "returnByValue": True})], None))
            row["steps"].append(wait_text(page_cdp, "Delayed state ready"))
            row["steps"].append(operation(page_cdp, "read_result", [(
                "Runtime.evaluate",
                {"expression": "({text: document.querySelector('#result').innerText, hidden: document.querySelector('#result').hidden})", "returnByValue": True},
            )], {"text": "Action complete", "hidden": False}))
            row["sequence_ms"] = round((time.perf_counter() - started) * 1000, 3)
            row["protocol_tokens"] = totals([record for step in row["steps"] for record in step["protocol"]])
            after = browser_scope(profile)
            row["browser_process_scope"] = {**after, "cpu_seconds_delta": round(float(after["cpu_seconds"]) - float(before["cpu_seconds"]), 6)}
            row["status"] = "pass"
            result["runs"].append(row)
        final_scope = browser_scope(profile)
        result["browser_process_scope"] = {**final_scope, "cpu_seconds_delta": round(float(final_scope["cpu_seconds"]) - float(initial_cpu), 6)}
        result["status"] = "pass"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if page_cdp:
            page_cdp.close()
        if browser_cdp:
            browser_cdp.close()
        if browser:
            browser.terminate()
            try:
                browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser.kill()
        if fixture:
            fixture.terminate()
            try:
                fixture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fixture.kill()
        shutil.rmtree(work, ignore_errors=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
