#!/usr/bin/env python3
"""Five-run local-only Sleeper CLI benchmark using the shared fixture."""
from __future__ import annotations

import asyncio, json, os, shutil, socket, subprocess, sys, tempfile, time, shlex, statistics
from pathlib import Path

import psutil
from playwright.async_api import async_playwright
from token_measurement import ENCODING, compact, sample

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "build/sleeper-chromium.zip"
CLI = ROOT / "cli/sleeper"
DAEMON = ROOT / "daemon/daemon.py"
def chromium_path() -> str:
    configured = os.environ.get("SLEEPER_CHROMIUM")
    if configured:
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("Set SLEEPER_CHROMIUM to a Chromium-family browser executable; none was found on PATH.")

CHROMIUM = chromium_path()
OUTPUT = ROOT / "benchmarks/results/sleeper-matched-results.json"
MCP_OUTPUT = ROOT / "benchmarks/results/sleeper-mcp-matched-results.json"

def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return sock.getsockname()[1]

def invoke(env: dict[str, str], *args: str) -> dict:
    started = time.perf_counter()
    process = subprocess.run([str(CLI), *args], cwd=ROOT, env=env, text=True, capture_output=True, timeout=15)
    payload = json.loads(process.stdout)
    assert process.returncode == 0 and payload.get("ok"), payload
    canonical_argv = shlex.join(["$REPO/cli/sleeper", *args])
    return {"command": args[0], "ms": round((time.perf_counter() - started) * 1000, 3), "bytes": len(process.stdout.encode()), "result": payload, "token_sample": sample(canonical_argv, process.stdout)}

def mcp_call(process: subprocess.Popen[str], request: dict) -> tuple[dict, dict]:
    """Send one complete stdio JSON-RPC message and retain both wire lines."""
    assert process.stdin and process.stdout
    request_text = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    process.stdin.write(request_text + "\n"); process.stdin.flush()
    response_text = process.stdout.readline().strip()
    if not response_text: raise RuntimeError("MCP server returned no response")
    response = json.loads(response_text)
    params = request.get("params", {})
    return response, {"wire": sample(request_text, response_text), "model_payload": sample(compact({"name": params.get("name", request["method"]), "arguments": params.get("arguments", {})}), compact(response.get("result", {})))}

def browser_scope(profile: Path) -> dict:
    marker = f"--user-data-dir={profile}"
    pids, rss, cpu = [], 0, 0.0
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            if marker not in " ".join(process.info["cmdline"] or []): continue
            pids.append(process.pid); rss += process.memory_info().rss
            times = process.cpu_times(); cpu += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    return {"scope": "all Chromium processes whose command line has this disposable --user-data-dir", "pids": pids, "rss_bytes": rss, "cpu_seconds": round(cpu, 6)}

async def main() -> None:
    assert PACKAGE.is_file() and CLI.is_file() and DAEMON.is_file()
    work = Path(tempfile.mkdtemp(prefix="sleeper-matched-")); extension, profile = work / "extension", work / "profile"
    http_port, ws_port = port(), port()
    env = {**os.environ, "SLEEPER_PORT": str(http_port), "SLEEPER_HTTP_PORT": str(http_port), "SLEEPER_WS_PORT": str(ws_port), "SLEEPER_TOKEN_FILE": str(work / "token")}
    canaries = {name: f"matched-{name.lower()}" for name in ("COOKIE", "DOM", "LOCAL", "HEADER", "API")}
    fixture = subprocess.Popen([sys.executable, str(ROOT / "benchmarks/fixture/server.py"), "--port", "0"], cwd=ROOT, env={**env, **{f"SLEEPER_CANARY_{k}": v for k, v in canaries.items()}}, stdout=subprocess.PIPE, text=True)
    daemon = None; context = None
    mcp = None
    result = {"schema": "sleeper-matched-browser-primitives/v2", "token_method": {"encoding": ENCODING, "scope": "canonical shell rendering of spawned argv ($REPO substituted) and raw stdout; deterministic wire-text estimate, not model-billed tokens", "excluded": ["model prompts and reasoning", "screenshots", "HTTP framing", "stderr"]}, "status": "fail", "iterations": 5, "mode": "deterministic browser primitives; excludes agent/model performance", "browser": "same Chromium binary, one fresh disposable persistent profile", "browser_baseline_excluded": True, "operations": ["navigate", "read_h1", "type", "click", "wait_delayed_text", "read_result"], "canaries": canaries, "runs": [], "mcp": {"token_method": {"encoding": ENCODING, "scope": "complete stdio JSON-RPC request and response lines", "excluded": ["model prompts and reasoning", "screenshots"]}, "runs": []}}
    try:
        fixture_url = f"http://127.0.0.1:{json.loads(fixture.stdout.readline())['port']}/"
        shutil.unpack_archive(PACKAGE, extension, "zip")
        # The loopback endpoints moved to daemon_endpoint.js defaults; rewrite
        # every extension script so the isolated daemon ports take effect
        # regardless of which module owns the constant.
        for script in extension.glob("*.js"):
            text = script.read_text()
            if "127.0.0.1:8790" in text or "127.0.0.1:8789" in text:
                script.write_text(text.replace("127.0.0.1:8790", f"127.0.0.1:{http_port}").replace("127.0.0.1:8789", f"127.0.0.1:{ws_port}"))
        daemon = subprocess.Popen([sys.executable, str(DAEMON)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        async with async_playwright() as playwright:
            startup = time.perf_counter()
            context = await playwright.chromium.launch_persistent_context(str(profile), executable_path=CHROMIUM, headless=True, args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}", "--no-first-run"])
            result["startup_ms"] = round((time.perf_counter() - startup) * 1000, 3)
            for _ in range(40):
                if context.service_workers: break
                await asyncio.sleep(.25)
            assert context.service_workers, "extension worker did not start"
            await context.service_workers[0].evaluate("chrome.storage.local.set({profile: 'default'})")
            mcp = subprocess.Popen([sys.executable, str(ROOT / "daemon/mcp_server.py")], cwd=ROOT, env=env, text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, initialize_tokens = mcp_call(mcp, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"benchmark","version":"1"}}})
            schema, schema_tokens = mcp_call(mcp, {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
            assert "tools" in schema.get("result", {}), schema
            result["mcp"]["cold_discovery"] = {"initialize": initialize_tokens, "tools_list": schema_tokens}
            controller = psutil.Process(daemon.pid)
            initial_cpu = sum(controller.cpu_times()[:2])
            for run in range(1, 6):
                before_browser = browser_scope(profile)
                steps = [invoke(env, "goto", fixture_url), invoke(env, "read", "h1"), invoke(env, "type", "#input", f"matched-{run}"), invoke(env, "click", "#action"), invoke(env, "wait_text", "Delayed state ready", "--timeout", "5000"), invoke(env, "read", "#result")]
                blob = json.dumps(steps)
                assert "Synthetic browser benchmark" in blob and f"matched-{run}" in blob and "Action complete" in blob, "CLI assertion failed"
                # CLI subprocess calls block this coroutine; yield once so
                # Playwright receives the page/tab lifecycle notifications.
                await asyncio.sleep(0.1)
                fixture_pages = [page for page in context.pages if fixture_url.rstrip('/') in page.url]
                assert fixture_pages, [page.url for page in context.pages]
                cli_verified = await fixture_pages[-1].evaluate("""() => ({h1:document.querySelector('h1').textContent,input:document.querySelector('#input').value,visible:!document.querySelector('#result').hidden,delayed:document.querySelector('#delayed').textContent})""")
                assert cli_verified == {"h1":"Synthetic browser benchmark","input":f"matched-{run}","visible":True,"delayed":"Delayed state ready"}, cli_verified
                current_cpu = sum(controller.cpu_times()[:2])
                browser_metrics = browser_scope(profile)
                browser_metrics["cpu_seconds_delta"] = round(browser_metrics.pop("cpu_seconds") - before_browser["cpu_seconds"], 6)
                result["runs"].append({"run": run, "status": "pass", "sequence_ms": round(sum(step["ms"] for step in steps), 3), "steps": [{k: step[k] for k in ("command", "ms", "bytes", "token_sample")} for step in steps], "controller_process_scope": {"scope": "Sleeper local daemon process; excludes per-command CLI child and browser", "rss_bytes": controller.memory_info().rss, "cpu_seconds_delta": round(current_cpu - initial_cpu, 6)}, "browser_process_scope": browser_metrics})
                mcp_steps=[]
                mcp_started = time.perf_counter()
                for number, (name, arguments) in enumerate([("sleeper_goto", {"url":fixture_url}), ("sleeper_read", {"selector":"h1","what":"text"}), ("sleeper_type", {"selector":"#input","text":f"matched-mcp-{run}"}), ("sleeper_click", {"selector":"#action"}), ("sleeper_wait_text", {"text":"Delayed state ready","timeout_ms":5000}), ("sleeper_read", {"selector":"#result","what":"text"})], start=10):
                    response, token_sample = mcp_call(mcp, {"jsonrpc":"2.0","id":number,"method":"tools/call","params":{"name":name,"arguments":arguments}})
                    assert not response.get("result", {}).get("isError"), response
                    mcp_steps.append({"tool":name,"token_sample":token_sample,"response":response})
                mcp_sequence_ms = round((time.perf_counter() - mcp_started) * 1000, 3)
                mcp_blob=json.dumps(mcp_steps)
                assert "Synthetic browser benchmark" in mcp_blob and "Action complete" in mcp_blob, mcp_blob
                await asyncio.sleep(0.1)
                mcp_verified = await fixture_pages[-1].evaluate("""() => ({input:document.querySelector('#input').value,visible:!document.querySelector('#result').hidden,delayed:document.querySelector('#delayed').textContent})""")
                assert mcp_verified == {"input":f"matched-mcp-{run}","visible":True,"delayed":"Delayed state ready"}, mcp_verified
                mcp_browser = browser_scope(profile)
                result["mcp"]["runs"].append({"run":run,"status":"pass","sequence_ms":mcp_sequence_ms,"browser_process_scope":mcp_browser,"steps":[{"tool":s["tool"],"token_sample":s["token_sample"]} for s in mcp_steps]})
            result["status"] = "pass"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if context:
            try: await context.close()
            except Exception: pass
        if daemon: daemon.terminate(); daemon.wait(timeout=5)
        if mcp: mcp.terminate(); mcp.wait(timeout=5)
        fixture.terminate(); fixture.wait(timeout=5)
        shutil.rmtree(work, ignore_errors=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    mcp_runs = result["mcp"]["runs"]
    mcp_result = {"schema":"sleeper-mcp-matched-browser-primitives/v1","status":"pass" if len(mcp_runs)==5 and all(row["status"]=="pass" for row in mcp_runs) else "fail","iterations":5,"operations":["navigate","read_h1","type","click","wait_delayed_text","read_result"],"measurement":{"sequence":"six MCP tools/call requests only; excludes out-of-band Playwright verifier","browser_rss_scope":"sum of RSS for Chromium processes with the fresh disposable profile's --user-data-dir; not physical-memory total"},"median_sequence_ms":round(statistics.median(row["sequence_ms"] for row in mcp_runs),3) if mcp_runs else None,"median_browser_rss_bytes":round(statistics.median(row["browser_process_scope"]["rss_bytes"] for row in mcp_runs)) if mcp_runs else None,"runs":[{"run":row["run"],"status":row["status"],"sequence_ms":row["sequence_ms"],"browser_process_scope":row["browser_process_scope"]} for row in mcp_runs]}
    MCP_OUTPUT.write_text(json.dumps(mcp_result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "pass": raise SystemExit(1)

if __name__ == "__main__": asyncio.run(main())
