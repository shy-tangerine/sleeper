#!/usr/bin/env python3
"""Measure five verified six-call browser sequences through Playwright MCP."""
from __future__ import annotations

import json, os, re, shutil, statistics, subprocess, sys, tempfile, time
from pathlib import Path
from typing import Any

import psutil
from token_measurement import ENCODING, compact, sample

ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = Path(os.environ["PLAYWRIGHT_MCP_ROOT"]).expanduser().resolve()
CHROMIUM = os.environ.get("SLEEPER_CHROMIUM") or shutil.which("chromium")
OUT = ROOT / "benchmarks/results/playwright-mcp-token-results.json"
ITERATIONS = 5


def browser_scope(profile: Path) -> dict[str, object]:
    marker, count, rss, cpu = f"--user-data-dir={profile}", 0, 0, 0.0
    for process in psutil.process_iter(["cmdline"]):
        try:
            if marker not in " ".join(process.info["cmdline"] or []):
                continue
            count += 1; rss += process.memory_info().rss
            times = process.cpu_times(); cpu += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"scope": "all Chromium processes whose command line has this disposable --user-data-dir", "process_count": count, "rss_bytes": rss, "cpu_seconds": round(cpu, 6)}


def rpc(process: subprocess.Popen[str], request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    assert process.stdin and process.stdout
    raw = compact(request); process.stdin.write(raw + "\n"); process.stdin.flush()
    response = process.stdout.readline().strip()
    if not response:
        detail = process.stderr.read() if process.stderr else ""
        raise RuntimeError(f"Playwright MCP produced no stdio response: {detail[-1000:]}")
    value = json.loads(response)
    if "error" in value:
        raise RuntimeError(f"Playwright MCP JSON-RPC error: {value['error']}")
    wire = sample(token_text(raw), token_text(response))
    params = request.get("params", {})
    model_request = compact({"name": params.get("name", request["method"]), "arguments": params.get("arguments", {})})
    return value, {"wire": wire, "model_payload": sample(token_text(model_request), token_text(compact(value.get("result", {}))))}


def tool(process: subprocess.Popen[str], request_id: int, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value, tokens = rpc(process, {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    result = value.get("result", {})
    if result.get("isError"):
        raise RuntimeError(f"Playwright MCP tool {name} failed: {result}")
    return value, tokens


def token_totals(steps: list[dict[str, Any]], key: str) -> dict[str, int]:
    return {field: sum(int(step["tokens"][key][field]) for step in steps) for field in ("request_tokens", "response_tokens", "total_tokens")}


def token_text(value: str) -> str:
    """Canonicalize volatile returned artifact links before counting and storing."""
    return re.sub(r"(?:\.\./)*tmp/pw-mcp-matched-[^/\s)\"]+/artifacts/[^/\s)\"]+", "$TEMP/artifacts/<GENERATED_FILE>", value)


def sanitize_public(value: Any) -> Any:
    """Remove disposable artifact paths after token measurement, before publishing."""
    if isinstance(value, list): return [sanitize_public(item) for item in value]
    if isinstance(value, dict):
        return {key: (item if key in {"request_text", "response_text"} else sanitize_public(item)) for key, item in value.items()}
    if not isinstance(value, str): return value
    value = re.sub(r"127\.0\.0\.1:\d{1,5}", "127.0.0.1:<PORT>", value)
    value = re.sub(r"(?:\.\./)*tmp/pw-mcp-matched-[^/\s)\"]+/artifacts/[^/\s)\"]+", "$TEMP/artifacts/<GENERATED_FILE>", value)
    value = re.sub(r"matched-\d+", "matched-N", value)
    return value


def main() -> None:
    if not CHROMIUM:
        raise RuntimeError("Set SLEEPER_CHROMIUM or install chromium on PATH.")
    cli, package, fixture = MCP_ROOT / "cli.js", MCP_ROOT / "package.json", ROOT / "benchmarks/fixture/server.py"
    if not all(path.is_file() for path in (cli, package, fixture)):
        raise RuntimeError("PLAYWRIGHT_MCP_ROOT must name a built Playwright MCP checkout.")
    work, profile = Path(tempfile.mkdtemp(prefix="pw-mcp-matched-")), None
    profile = work / "profile"
    env = {**os.environ, **{f"SLEEPER_CANARY_{name}": f"pw-mcp-{name.lower()}" for name in ("COOKIE", "DOM", "LOCAL", "HEADER", "API")}}
    server: subprocess.Popen[str] | None = None; process: subprocess.Popen[str] | None = None
    result: dict[str, Any] = {
        "schema": "playwright-mcp-matched-browser-primitives/v2", "status": "fail", "version": json.loads(package.read_text())["version"], "encoding": ENCODING, "iterations": ITERATIONS,
        "mode": "deterministic browser primitives; excludes agent/model performance", "browser": "same Chromium binary, one fresh disposable persistent profile", "browser_baseline_excluded": True,
        "operations": ["navigate", "read_h1", "type", "click", "wait_delayed_text", "read_result"],
        "primitive_mapping": {"navigate": "browser_navigate", "read_h1": "browser_evaluate h1.textContent", "type": "browser_type", "click": "browser_click", "wait_delayed_text": "browser_wait_for", "read_result": "browser_evaluate #result.textContent"},
        "artifact_policy": "MCP-generated output files are not read; only tool result JSON is counted.",
        "capture_normalization": "After measurement, published output replaces local ports, run strings, and disposable generated-artifact paths with stable placeholders. Token totals remain the measured run values.",
        "measurement_scope": "six task tools/call requests only; initialize, tools/list, startup warmup, and verifier are excluded from sequence_ms", "runs": [],
    }
    try:
        server = subprocess.Popen([sys.executable, str(fixture), "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        assert server.stdout
        fixture_url = f"http://127.0.0.1:{json.loads(server.stdout.readline())['port']}/"
        launch = ["node", str(cli), "--headless", "--browser", "chrome", "--executable-path", CHROMIUM, "--user-data-dir", str(profile), "--output-dir", str(work / "artifacts")]
        result["launch_argv"] = ["node", "$PLAYWRIGHT_MCP_ROOT/cli.js", "--headless", "--browser", "chrome", "--executable-path", "$SLEEPER_CHROMIUM", "--user-data-dir", "$TEMP/profile", "--output-dir", "$TEMP/artifacts"]
        process = subprocess.Popen(launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        _, init = rpc(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "benchmark", "version": "1"}}})
        tools, discovery = rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        result["cold_discovery"] = {"initialize": init, "tools_list": discovery, "tool_count": len(tools.get("result", {}).get("tools", []))}
        _, warmup = tool(process, 3, "browser_navigate", {"url": fixture_url})
        result["startup_warmup"] = {"tool": "browser_navigate", "tokens": warmup, "excluded_from_sequence_ms": True}
        initial = browser_scope(profile)
        if not initial["process_count"]:
            raise RuntimeError("No Chromium process used the requested disposable --user-data-dir")
        for run in range(1, ITERATIONS + 1):
            before, started = browser_scope(profile), time.perf_counter()
            calls = [("browser_navigate", {"url": fixture_url}), ("browser_evaluate", {"function": "() => document.querySelector('h1').textContent"}), ("browser_type", {"target": "#input", "text": f"matched-{run}"}), ("browser_click", {"target": "#action"}), ("browser_wait_for", {"text": "Delayed state ready"}), ("browser_evaluate", {"function": "() => document.querySelector('#result').textContent"})]
            steps = []
            for offset, (name, arguments) in enumerate(calls):
                value, tokens = tool(process, 100 + run * 10 + offset, name, arguments)
                steps.append({"tool": name, "tokens": tokens, "result": value["result"]})
            sequence_ms = round((time.perf_counter() - started) * 1000, 3)
            verify, _ = tool(process, 1000 + run, "browser_evaluate", {"function": "() => JSON.stringify({h1:document.querySelector('h1').textContent,input:document.querySelector('#input').value,visible:!document.querySelector('#result').hidden,delayed:document.querySelector('#delayed').textContent})"})
            verifier_text = verify["result"]["content"][0]["text"]
            try:
                verifier = json.loads(json.loads(verifier_text.splitlines()[1]))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"verifier did not return JSON: {verifier_text!r}") from exc
            expected = {"h1": "Synthetic browser benchmark", "input": f"matched-{run}", "visible": True, "delayed": "Delayed state ready"}
            if verifier != expected:
                raise AssertionError(f"run {run} verifier mismatch: {verifier!r}")
            steps[1]["assertion"] = "Synthetic browser benchmark" in compact(steps[1]["result"]); steps[5]["assertion"] = "Action complete" in compact(steps[5]["result"])
            if not steps[1]["assertion"] or not steps[5]["assertion"]:
                raise AssertionError(f"run {run} read result did not contain expected text")
            after = browser_scope(profile)
            result["runs"].append({"run": run, "status": "pass", "sequence_ms": sequence_ms, "steps": steps, "tokens": {"wire": token_totals(steps, "wire"), "model_payload": token_totals(steps, "model_payload")}, "browser_process_scope": {**after, "cpu_seconds_delta": round(float(after["cpu_seconds"]) - float(before["cpu_seconds"]), 6)}})
        final = browser_scope(profile)
        result["browser_process_scope"] = {**final, "cpu_seconds_delta": round(float(final["cpu_seconds"]) - float(initial["cpu_seconds"]), 6)}
        result["summary"] = {"sequence_ms_median": round(statistics.median(row["sequence_ms"] for row in result["runs"]), 3), "browser_rss_bytes_median": int(statistics.median(row["browser_process_scope"]["rss_bytes"] for row in result["runs"])), "browser_cpu_seconds_delta_median": round(statistics.median(row["browser_process_scope"]["cpu_seconds_delta"] for row in result["runs"]), 6)}
        result["status"] = "pass"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()
        if server:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired: server.kill()
        shutil.rmtree(work, ignore_errors=True)
    public_result = sanitize_public(result)
    OUT.write_text(json.dumps(public_result, indent=2, sort_keys=True) + "\n"); print(json.dumps(public_result, indent=2, sort_keys=True))
    if result["status"] != "pass": raise SystemExit(1)


if __name__ == "__main__": main()
