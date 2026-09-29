# Reproduce the browser benchmarks

The runners use the same local fixture and six task outcomes. Read the [protocol and measurement limits](../docs/benchmarks/matched-browser-interface.md) before comparing results. The token estimates use `tiktoken==0.13.0` with `o200k_base`; they are not billed model usage.

## Prerequisites

Use Python 3.11+ through uv:

```bash
uv sync --frozen --group benchmark
./scripts/build-chromium.sh
```

Provide a Chromium-family browser on `PATH`, or set `SLEEPER_CHROMIUM` to its executable. Competitor runners also require Node.js 20.18.1 or newer. Run commands below from the Sleeper repository root.

## Sleeper CLI and MCP

```bash
python benchmarks/run_matched_sleeper_chromium.py
```

This runs both interfaces against an isolated daemon and browser profile. Independent page-state checks occur outside the measured sequence.

## OpenCLI

Prepare the tested revision in a separate tools directory:

```bash
BENCHMARK_TOOLS="$(mktemp -d)"
git clone https://github.com/jackwener/opencli.git "$BENCHMARK_TOOLS/opencli"
git -C "$BENCHMARK_TOOLS/opencli" checkout 8271afc67e8504bda94c147f446ee29775d08274
npm --prefix "$BENCHMARK_TOOLS/opencli" ci
npm --prefix "$BENCHMARK_TOOLS/opencli" run build
export OPENCLI_ROOT="$BENCHMARK_TOOLS/opencli"
node "$OPENCLI_ROOT/dist/src/daemon.js" &
OPENCLI_BENCHMARK_DAEMON_PID=$!
python benchmarks/run_matched_opencli.py --iterations 5
kill "$OPENCLI_BENCHMARK_DAEMON_PID"
```

OpenCLI uses a fixed local bridge port. Run this when that port is free; the harness selects the disposable extension profile it creates.

## Playwright MCP

Install the tested package version into a separate tools directory:

```bash
PLAYWRIGHT_BENCHMARK_TOOLS="$(mktemp -d)"
npm install --prefix "$PLAYWRIGHT_BENCHMARK_TOOLS" @playwright/mcp@0.0.80
export PLAYWRIGHT_MCP_ROOT="$PLAYWRIGHT_BENCHMARK_TOOLS/node_modules/@playwright/mcp"
python benchmarks/run_matched_playwright_mcp.py
```

Selector-scoped reads use `browser_evaluate`. Returned artifact links count toward response text; the contents of snapshot files are excluded because this fixed-selector task does not read them.

## Direct CDP

```bash
python benchmarks/run_matched_cdp.py
```

This opens a disposable Chromium profile and sends CDP messages through the `websockets` dependency declared in `pyproject.toml`. It measures a lower-level protocol baseline without an agent-facing tool interface. Setup calls and events are recorded separately from task request/response messages.

All runners use [the local fixture](fixture/server.py) and write captures under `benchmarks/results/`. Locally generated captures are ignored by Git; reviewed published datasets are explicitly allowlisted.

After running the three agent-facing benchmarks, regenerate and validate their token summary:

```bash
python benchmarks/summarize_tokens.py
```

The CDP capture remains a separate dataset because it measures protocol traffic rather than agent-facing task text.

## CLI-to-daemon protocol text

With the same prerequisites and built OpenCLI checkout, run:

```bash
python benchmarks/run_cli_protocol_capture.py --iterations 5
python benchmarks/run_opencli_protocol_capture.py --iterations 5
```

Use an otherwise idle OpenCLI daemon from that checkout, as in the OpenCLI setup above. The capture runner identifies its newly created browser profile explicitly.

Sleeper captures `/command` JSON through a local HTTP proxy. OpenCLI captures the real Node client's `fetch` bodies through the included preload hook. Both exclude HTTP headers/framing and retain exact bodies plus canonicalized variants and encoded counts. Their outputs are `sleeper-cli-protocol-capture.json` and `opencli-cli-protocol-capture.json` under `benchmarks/results/`.

These internal protocol totals are separate from the agent-facing task-text estimates. They do not represent model-token usage.
