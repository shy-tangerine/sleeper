#!/usr/bin/env python3
"""Capture OpenCLI's actual HTTP JSON command bodies on the matched fixture."""
from __future__ import annotations
import argparse, asyncio, json, os, re, shutil, subprocess, tempfile, time
from pathlib import Path
from contextlib import suppress
from playwright.async_api import async_playwright
from token_measurement import tokens

ROOT = Path(__file__).resolve().parents[1]
OPENCLI_ROOT = Path(os.environ.get("OPENCLI_ROOT", "")).expanduser()
CLI = OPENCLI_ROOT / "dist/src/main.js"
EXTENSION = OPENCLI_ROOT / "extension"
FIXTURE = ROOT / "benchmarks/fixture/server.py"
PRELOAD = ROOT / "benchmarks/opencli_fetch_capture.mjs"
OUTPUT = ROOT / "benchmarks/results/opencli-cli-protocol-capture.json"

def chromium() -> str:
    return os.environ.get("SLEEPER_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser") or ""

def parse_json(text: str) -> object:
    return json.loads(text)

def canon(text: str) -> str:
    text = re.sub(r"http://127\.0\.0\.1:\d+/", "http://127.0.0.1:<fixture-port>/", text)
    return re.sub(r'("tabId"\s*:\s*)\d+', r'\1<tab-id>', text)

def run_cli(args: list[str], env: dict[str, str]) -> None:
    proc = subprocess.run(["node", str(CLI), "browser", *args], cwd=ROOT, env=env, text=True,
                          capture_output=True, timeout=30)
    if proc.returncode:
        raise RuntimeError(f"OpenCLI failed ({args[0]}): {proc.stderr[-500:]}")

async def main(iterations: int) -> None:
    global EXTENSION
    if not EXTENSION.is_dir() and os.environ.get("OPENCLI_EXTENSION"):
        EXTENSION = Path(os.environ["OPENCLI_EXTENSION"]).expanduser()
    if not OPENCLI_ROOT or not CLI.is_file() or not EXTENSION.is_dir():
        raise RuntimeError("Set OPENCLI_ROOT to a built OpenCLI checkout")
    if not chromium() or not FIXTURE.is_file() or not PRELOAD.is_file():
        raise RuntimeError("Missing Chromium, fixture, or preload helper")
    work = Path(tempfile.mkdtemp(prefix="opencli-wire-")); profile = work / "profile"; capture = work / "capture.ndjson"
    fixture = context = None
    result: dict[str, object] = {"schema":"opencli-cli-http-json-bodies/v1", "status":"fail", "iterations":iterations,
      "operations":["navigate","read_h1","type","click","wait_delayed_text","read_result"],
      "measurement":{"protocol":"OpenCLI CLI HTTP JSON request/response bodies for POST /command",
        "excluded":["HTTP headers","HTTP framing","CLI stdout/stderr","model prompts and reasoning","screenshots"],
        "fixture":"synthetic local page; no external network"}, "runs":[]}
    try:
        canaries = {n:f"opencli-wire-{n.lower()}" for n in ("COOKIE","DOM","LOCAL","HEADER","API")}
        fenv = {**os.environ, **{f"SLEEPER_CANARY_{k}":v for k,v in canaries.items()}}
        fixture = subprocess.Popen(["python3", str(FIXTURE), "--port", "0"], cwd=ROOT, env=fenv, stdout=subprocess.PIPE, text=True)
        assert fixture.stdout is not None
        fixture_url = f"http://127.0.0.1:{json.loads(fixture.stdout.readline())['port']}/"
        # NODE_OPTIONS parses shell-like quoting; quote the absolute preload path
        # so this remains valid when the checkout contains spaces.
        env = {**os.environ, "OPENCLI_CAPTURE_FILE":str(capture), "NODE_OPTIONS":f'--import="{PRELOAD}"',
               "OPENCLI_BROWSER_COMMAND_TIMEOUT":"30"}
        baseline_proc = subprocess.run(["node", str(CLI), "profile", "list"], cwd=ROOT, env=env,
                                       text=True, capture_output=True, timeout=10)
        baseline_profiles = set(re.findall(r"^\s*([a-z0-9]+)\s+—\s+connected", baseline_proc.stdout + baseline_proc.stderr, re.M))
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(str(profile), executable_path=chromium(), headless=True,
              args=[f"--disable-extensions-except={EXTENSION}",f"--load-extension={EXTENSION}","--no-first-run","--no-default-browser-check"])
            for _ in range(80):
                if context.service_workers: break
                await asyncio.sleep(.25)
            if not context.service_workers: raise RuntimeError("OpenCLI extension worker did not start")
            # Discover the isolated profile through the real OpenCLI client.
            profiles = ""
            for _ in range(80):
                p = subprocess.run(["node",str(CLI),"profile","list"],cwd=ROOT,env=env,text=True,capture_output=True)
                profiles = p.stdout + p.stderr
                match = set(re.findall(r"^\s*([a-z0-9]+)\s+—\s+connected", profiles, re.M)) - baseline_profiles
                if len(match) == 1:
                    env["OPENCLI_PROFILE"] = next(iter(match))
                    break
                if len(match) > 1: raise RuntimeError(f"Expected one new isolated profile, got {sorted(match)}")
                await asyncio.sleep(.25)
            else: raise RuntimeError(f"OpenCLI bridge did not connect: {profiles[-500:]}")
            session = f"opencli-wire-{int(time.time()*1000)}"
            for run in range(1, iterations+1):
                before = len(capture.read_text().splitlines()) if capture.exists() else 0
                commands = [("open",["open",fixture_url,"--window","background"]),("get",["get","text","h1"]),
                  ("type",["type","#input",f"opencli-wire-{run}"]),("click",["click","#action"]),
                  ("wait",["wait","text","Delayed state ready"]),("read",["get","text","#result"])]
                operation_records = []
                cursor = before
                for operation, args in commands:
                    run_cli([session,*args], env)
                    lines = capture.read_text().splitlines() if capture.exists() else []
                    operation_records.append((operation, [json.loads(line) for line in lines[cursor:]]))
                    cursor = len(lines)
                await asyncio.sleep(.1)
                pages=[p for p in context.pages if fixture_url.rstrip("/") in p.url]
                if not pages: raise RuntimeError(f"fixture page missing; pages={[p.url for p in context.pages]!r}")
                verified=await pages[-1].evaluate("""() => ({h1:document.querySelector('h1').textContent,input:document.querySelector('#input').value,visible:!document.querySelector('#result').hidden,delayed:document.querySelector('#delayed').textContent})""")
                expected={"h1":"Synthetic browser benchmark","input":f"opencli-wire-{run}","visible":True,"delayed":"Delayed state ready"}
                if verified != expected: raise RuntimeError(f"fixture verification failed: {verified!r}")
                steps=[]
                for operation, records in operation_records:
                    if not records: raise RuntimeError(f"no protocol captures for {operation}")
                    captures=[]
                    for record in records:
                        req, resp=record["requestText"],record["responseText"]
                        captures.append({"status":record["status"],"request_text":req,"response_text":resp,
                          "request_text_sanitized":canon(req),"response_text_sanitized":canon(resp),"request_bytes":len(req.encode()),"response_bytes":len(resp.encode()),
                          "request_tokens":tokens(req),"response_tokens":tokens(resp),"total_tokens":tokens(req)+tokens(resp),
                          "request_json":parse_json(req),"response_json":parse_json(resp)})
                    steps.append({"operation":operation,"protocol_request_count":len(captures),"captures":captures,
                      "request_bytes":sum(c["request_bytes"] for c in captures),"response_bytes":sum(c["response_bytes"] for c in captures),
                      "request_tokens":sum(c["request_tokens"] for c in captures),"response_tokens":sum(c["response_tokens"] for c in captures),
                      "total_tokens":sum(c["total_tokens"] for c in captures)})
                result["runs"].append({"run":run,"status":"pass","steps":steps,
                  "protocol_request_count":sum(s["protocol_request_count"] for s in steps),
                  "request_tokens":sum(s["request_tokens"] for s in steps),"response_tokens":sum(s["response_tokens"] for s in steps),
                  "total_tokens":sum(s["total_tokens"] for s in steps)})
            result["status"]="pass"
    except Exception as exc: result["error"]=f"{type(exc).__name__}: {exc}"
    finally:
        if context:
            with suppress(Exception): await context.close()
        if fixture:
            fixture.terminate()
            with suppress(Exception): fixture.wait(timeout=5)
        shutil.rmtree(work,ignore_errors=True)
    OUTPUT.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,indent=2,sort_keys=True))
    if result["status"] != "pass": raise SystemExit(1)

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--iterations",type=int,default=5); asyncio.run(main(p.parse_args().iterations))
