#!/usr/bin/env python3
"""Five-run local-only six-operation OpenCLI browser benchmark.

This measures OpenCLI's deterministic browser primitives.  It intentionally
does not invoke a model or an OpenCLI agent workflow.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import re
import shlex
from contextlib import suppress

import psutil
from playwright.async_api import async_playwright
from token_measurement import ENCODING, compact, sample


ROOT = Path(__file__).resolve().parents[1]
OPENCLI_ROOT = os.environ.get("OPENCLI_ROOT")
if not OPENCLI_ROOT:
    raise RuntimeError("Set OPENCLI_ROOT to a built OpenCLI checkout (see benchmarks/README.md).")
VENDOR = Path(OPENCLI_ROOT).expanduser().resolve()
EXTENSION = VENDOR / "extension"
CLI = VENDOR / "dist/src/main.js"
FIXTURE = ROOT / "benchmarks/fixture/server.py"
OUTPUT = ROOT / "benchmarks/results/opencli-matched-results.json"
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


def json_output(process: subprocess.CompletedProcess[str]) -> object:
    """Return the last JSON document written by a browser primitive."""
    text = process.stdout.strip()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            return json.loads(text[index:])
        except json.JSONDecodeError:
            pass
    return text


def browser_scope(profile: Path) -> dict[str, object]:
    marker = f"--user-data-dir={profile}"
    processes = []
    rss = 0
    cpu = 0.0
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            command = " ".join(process.info["cmdline"] or [])
            if marker not in command:
                continue
            memory = process.memory_info().rss
            times = process.cpu_times()
            processes.append(process.pid)
            rss += memory
            cpu += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {
        "scope": "all Chromium processes whose command line has this disposable --user-data-dir",
        "pids": processes,
        "rss_bytes": rss,
        "cpu_seconds": round(cpu, 6),
    }


def opencli_daemon() -> psutil.Process:
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            command = " ".join(process.info["cmdline"] or [])
            if str(VENDOR / "dist/src/daemon.js") in command:
                return process
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise RuntimeError("OpenCLI bridge daemon is not running")


def call(session: str, args: list[str], env: dict[str, str]) -> tuple[dict[str, object], object]:
    started = time.perf_counter()
    process = subprocess.run(
        ["node", str(CLI), "browser", session, *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    return (
        {
            "operation": args[0],
            "command": ["browser", session, *args],
            "ms": round((time.perf_counter() - started) * 1000, 3),
            "exit_code": process.returncode,
            "stdout": process.stdout[-2000:],
            "stderr": process.stderr[-2000:],
            "token_sample": sample(shlex.join(["node", "$OPENCLI_ROOT/dist/src/main.js", "browser", session, *args]), process.stdout),
        },
        json_output(process),
    )


def connected_profiles(text: str) -> set[str]:
    return set(re.findall(r"^\s*([a-z0-9]+)\s+—\s+connected", text, flags=re.MULTILINE))


def profile_list(env: dict[str, str]) -> str:
    process = subprocess.run(
        ["node", str(CLI), "profile", "list"], cwd=ROOT, env=env,
        text=True, capture_output=True, timeout=10,
    )
    return (process.stdout + process.stderr).strip()


async def wait_for_bridge(env: dict[str, str], existing: set[str]) -> tuple[str, str]:
    """Wait for the freshly loaded extension to register with the daemon."""
    deadline = time.monotonic() + 20
    last = ""
    while time.monotonic() < deadline:
        last = profile_list(env)
        new_profiles = connected_profiles(last) - existing
        if new_profiles:
            if len(new_profiles) != 1:
                raise RuntimeError(f"Expected one isolated bridge profile, got {sorted(new_profiles)}")
            return last, new_profiles.pop()
        await asyncio.sleep(0.25)
    raise RuntimeError(f"OpenCLI Browser Bridge did not connect: {last}")


async def main(iterations: int) -> None:
    required = (CLI, EXTENSION / "manifest.json", FIXTURE)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Missing benchmark prerequisite(s): " + ", ".join(missing))
    work = Path(tempfile.mkdtemp(prefix="opencli-matched-"))
    profile = work / "profile"
    fixture: subprocess.Popen[str] | None = None
    context = None
    canaries = {key: f"matched-opencli-{key.lower()}" for key in ("COOKIE", "DOM", "LOCAL", "HEADER", "API")}
    env = {**os.environ, **{f"SLEEPER_CANARY_{key}": value for key, value in canaries.items()}, "OPENCLI_BROWSER_COMMAND_TIMEOUT": "20"}
    result: dict[str, object] = {
        "schema": "opencli-matched-browser-primitives/v1",
        "token_method": {"encoding": ENCODING, "scope": "canonical shell rendering of spawned argv ($OPENCLI_ROOT substituted) and raw stdout; deterministic wire-text estimate, not model-billed tokens", "excluded": ["model prompts and reasoning", "screenshots", "daemon HTTP/WebSocket framing", "stderr"]},
        "status": "fail",
        "mode": "deterministic browser primitives; excludes agent/model performance",
        "iterations": iterations,
        "browser": "same Chromium binary, one fresh disposable persistent profile",
        "browser_baseline_excluded": True,
        "operations": ["navigate", "read_h1", "type", "click", "wait_delayed_text", "read_result"],
        "canaries": canaries,
        "runs": [],
    }
    try:
        initially_connected = connected_profiles(profile_list(env))
        fixture = subprocess.Popen(
            [sys.executable, str(FIXTURE), "--port", "0"], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        assert fixture.stdout is not None
        fixture_url = f"http://127.0.0.1:{json.loads(fixture.stdout.readline())['port']}/"
        async with async_playwright() as playwright:
            startup = time.perf_counter()
            context = await playwright.chromium.launch_persistent_context(
                str(profile), executable_path=CHROMIUM, headless=True,
                args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}", "--no-first-run", "--no-default-browser-check"],
            )
            result["startup_ms"] = round((time.perf_counter() - startup) * 1000, 3)
            bridge_profiles, isolated_profile = await wait_for_bridge(env, initially_connected)
            result["bridge_profiles"] = bridge_profiles
            result["isolated_bridge_profile"] = isolated_profile
            env["OPENCLI_PROFILE"] = isolated_profile

            controller = opencli_daemon()
            initial_controller_cpu = sum(controller.cpu_times()[:2])
            for index in range(1, iterations + 1):
                session = f"matched-opencli-{index}-{int(time.time() * 1000)}"
                row: dict[str, object] = {"run": index, "status": "fail", "steps": []}
                before_browser = browser_scope(profile)
                started = time.perf_counter()
                try:
                    steps: list[dict[str, object]] = row["steps"]  # type: ignore[assignment]
                    opened, _ = call(session, ["open", fixture_url, "--window", "background"], env); steps.append(opened)
                    h1, h1_value = call(session, ["get", "text", "h1"], env); steps.append(h1)
                    typed, typed_value = call(session, ["type", "#input", f"matched-{index}"], env); steps.append(typed)
                    clicked, clicked_value = call(session, ["click", "#action"], env); steps.append(clicked)
                    waited, wait_value = call(session, ["wait", "text", "Delayed state ready"], env); steps.append(waited)
                    read, result_value = call(session, ["get", "text", "#result"], env); steps.append(read)
                    outputs = [h1_value, typed_value, clicked_value, wait_value, result_value]
                    assert all(step["exit_code"] == 0 for step in steps), outputs
                    assert isinstance(h1_value, dict) and h1_value.get("value") == "Synthetic browser benchmark", h1_value
                    assert isinstance(typed_value, dict) and typed_value.get("typed") is True, typed_value
                    assert isinstance(clicked_value, dict) and clicked_value.get("clicked") is True, clicked_value
                    assert isinstance(result_value, dict) and result_value.get("value") == "Action complete", result_value
                    # Resource scope is sampled while the result page remains
                    # open. The verifier and session close are intentionally
                    # outside both this snapshot and the six-call timer.
                    row["sequence_ms"] = round((time.perf_counter() - started) * 1000, 3)
                    browser_metrics = browser_scope(profile)
                    browser_metrics["cpu_seconds_delta"] = round(float(browser_metrics.pop("cpu_seconds")) - float(before_browser["cpu_seconds"]), 6)
                    row["browser_process_scope"] = browser_metrics
                    await asyncio.sleep(0.1)
                    page = next(page for page in context.pages if page.url.startswith(fixture_url))
                    verified = await page.evaluate("""() => ({input:document.querySelector('#input').value,visible:!document.querySelector('#result').hidden,delayed:document.querySelector('#delayed').textContent})""")
                    assert verified == {"input":f"matched-{index}","visible":True,"delayed":"Delayed state ready"}, verified
                    row["assertions"] = {"h1": True, "type": True, "click": True, "result": True}
                    row["status"] = "pass"
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    # Session timing contains precisely the six listed browser
                    # operations. Releasing the lease is cleanup, not a step.
                    row.setdefault("sequence_ms", round((time.perf_counter() - started) * 1000, 3))
                    try:
                        call(session, ["close"], env)
                    except Exception:
                        pass
                row["controller_process_scope"] = {
                    "scope": "OpenCLI persistent local bridge daemon; excludes per-command CLI child and browser",
                    "rss_bytes": controller.memory_info().rss,
                    "cpu_seconds_delta": round(sum(controller.cpu_times()[:2]) - initial_controller_cpu, 6),
                }
                if "browser_process_scope" not in row:
                    browser_metrics = browser_scope(profile)
                    browser_metrics["cpu_seconds_delta"] = round(float(browser_metrics.pop("cpu_seconds")) - float(before_browser["cpu_seconds"]), 6)
                    row["browser_process_scope"] = browser_metrics
                result["runs"].append(row)  # type: ignore[union-attr]
                # Persist raw completed rows in case an external benchmark
                # supervisor enforces a wall-clock limit.
                OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            result["status"] = "pass" if all(row["status"] == "pass" for row in result["runs"]) else "fail"  # type: ignore[index]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if context is not None:
            with suppress(Exception):
                await context.close()
        if fixture is not None:
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.iterations))
