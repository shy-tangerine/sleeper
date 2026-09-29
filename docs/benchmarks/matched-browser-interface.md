# Matched local browser-interface benchmark

This benchmark compares deterministic browser primitives, rather than model or
agent task completion. It was run on 2026-09-11 on Linux 7.0.0-31-generic,
AMD Ryzen 5 5500 (12 logical CPUs), with Helium 0.17.0.1 / Chromium
153.0.8010.36. Each tool used that same Chromium executable, a fresh
disposable profile, and a local fixture. No credentials, personal profiles,
model keys, or external traffic were used.

## Canonical caveat block

Whenever these figures are quoted anywhere (READMEs, landing pages, listings,
sponsor material), copy this block alongside them:

> **Methodology caveats.** These numbers come from a single machine
> (AMD Ryzen 5 5500, Linux), a single browser build (Helium 0.17.0.1 /
> Chromium 153.0.8010.36), and a single run date (2026-09-11), using five warm
> sequences per tool against a local fixture. They measure deterministic
> browser primitives (navigate, read, type, click, wait, read), **not agent
> task completion or general speed.** Memory figures sum per-process RSS and
> can double-count shared memory, so they are not physical-memory totals.
> Full protocol: [docs/benchmarks/matched-browser-interface.md](matched-browser-interface.md).

## Protocol

For five warm sequences per tool, after separately recording launch-only browser startup (bridge readiness excluded),
the harness performed exactly these operations:

1. Navigate to the fixture.
2. Read `h1` and assert `Synthetic browser benchmark`.
3. Type a run-specific string into `#input`.
4. Click `#action`.
5. Wait for the delayed text `Delayed state ready`.
6. Read `#result` and assert `Action complete`.

Sleeper commands are `goto`, `read h1`, `type #input`, `click #action`,
`wait_text`, and `read #result`. OpenCLI commands are `browser <session>
open`, `get text h1`, `type #input`, `click #action`, `wait text`, and `get
text #result`. The OpenCLI session close happens after the timer stops.

Re-run locally from the repository root:

```bash
python3 benchmarks/run_matched_sleeper_chromium.py
python3 benchmarks/run_matched_opencli.py --iterations 5
```

The fixture, runners, and [sanitized sample results](../../benchmarks/results/matched-browser-interface-samples.json) are public.

## Results

| Interface | Startup (ms) | Five six-operation sequences (ms) |
| --- | ---: | --- |
| Sleeper CLI + extension | 818.157 | 2443.322, 1284.091, 917.811, 933.826, 909.221 |
| OpenCLI browser CLI + extension | 1771.521 | 6586.640, 4025.798, 3898.712, 3935.764, 4010.886 |

These values are interface timings on this fixture, not a general speed
ranking. OpenCLI performs a browser-bridge command through its local daemon;
Sleeper performs a command through its local daemon. Both were measured with
the same external process boundary: browser startup is separate; the timed
sequence excludes cleanup; browser resources cover all Chromium processes with
the disposable profile; controller resources cover each tool's persistent
local daemon and exclude browser and per-command CLI child processes.

The browser process samples use the same profile-scoped aggregation. RSS is a sum of process RSS values and can double-count shared memory; it is not a physical-memory total. CPU is a
per-sequence delta and can vary when Chromium replaces renderer processes, so
it is recorded for diagnostics and not used to rank tools. Controller CPU
values are cumulative deltas across the five runs from each daemon's initial sample; RSS is an
instantaneous process RSS. Neither is total-machine resource usage.

## Interface capabilities

| Interface | Existing browser session | CLI | MCP | Browser engines | Authenticated API capability |
| --- | --- | --- | --- | --- | --- |
| Sleeper | Yes; named extension profile | Yes | Yes | Chromium and Firefox | Explicit allowlisted HTTPS host through browser session |
| OpenCLI | Yes; Browser Bridge profile | Yes | No MCP interface documented | Chrome/Chromium | Browser/network primitives documented; policy capability not evaluated |
| Playwright MCP | Yes, via Chrome/Edge extension; persistent and isolated profiles also supported | MCP server launcher | Yes | Chromium, Firefox, WebKit | Not evaluated in this benchmark |
| Browser Use | Can reuse system Chrome profile | Yes, plus Python API | Not assessed | Chrome profile and cloud browser; other engines not assessed | Not evaluated in this benchmark |

Sources: Sleeper's [README](../../README.md), [commands](../commands.md), and
[installation guide](../installation.md); [OpenCLI README](https://github.com/jackwener/opencli#readme);
[Playwright MCP documentation](https://github.com/microsoft/playwright-mcp#readme);
and [Browser Use README](https://github.com/browser-use/browser-use#readme).

## Token estimates for agent-facing interfaces

The token-instrumented runs each complete the same six outcomes five times. An independent page-state check verifies the heading, exact typed value, visible result, and delayed text after each sequence. Verification calls are excluded from the measured task text.

The following medians use `tiktoken==0.13.0`, encoding `o200k_base`:

| Interface | Request text | Response text | Total task text |
|---|---:|---:|---:|
| Sleeper CLI | 97 | 344 | 441 |
| OpenCLI CLI | 169 | 195 | 364 |
| Sleeper MCP | 128 | 374 | 502 |
| Playwright MCP | 122 | 414 | 536 |

In this fixture, choosing Sleeper CLI over Sleeper MCP reduces the task-text estimate by **61 tokens (12.2%)**. OpenCLI uses 77 fewer tokens than Sleeper CLI; Sleeper MCP uses 34 fewer than Playwright MCP. These results do not establish a general token-efficiency ranking.

For CLI, request text is the `shlex.join` rendering of the spawned argv, with installation roots replaced by documented placeholders; response text is unfiltered stdout. For MCP, request text is compact JSON containing the tool name and arguments, and response text is the complete compact tool result, preserving returned content strings. This is an explicit comparison convention, not a measurement of how a particular agent client formats its model context.

MCP JSON-RPC envelopes are also captured, but reported separately: median task exchange counts are **695** for Sleeper MCP and **734** for Playwright MCP. CLI shell-tool wrappers and HTTP headers/framing are outside the measured boundary; CLI JSON-body captures are reported below. Direct CDP traffic is outside this agent-facing comparison.

### Discovery and result scope

The current compact `tools/list` result encodes **3,568 tokens for Sleeper MCP** (47 tools, including session discovery and per-call profile selection). The captured Playwright MCP catalog encodes **4,058 tokens**. The [current Sleeper catalog](../../benchmarks/results/mcp-discovery-sample.json) is recorded separately from the older discovery exchanges in the warm-task dataset. Initialization and discovery exchanges are stored separately from the warm task sequences. Client-side tool selection, lazy loading, prompt caching, repeated context, and skill/help instructions determine the actual model overhead; this benchmark does not infer billing savings from the registry size.

Playwright MCP uses `browser_evaluate` for selector-scoped reads and `browser_wait_for` with the delayed text. Its disposable profile and output directory are recorded in the dataset. Returned snapshot links count as text; their file contents are excluded because the fixed-selector task never opens them. A task that needs those snapshots would have a different token budget.

Fixture ports, run/session identifiers, JSON-RPC IDs, and generated artifact timestamps/paths are canonicalized before counting. Other returned text is retained. No model inference, reasoning, screenshots, or external page discovery is measured.

The [published token captures](../../benchmarks/results/matched-token-samples.json) contain all five per-operation samples, counts, verification status, and discovery exchanges. [Reproduction instructions](../../benchmarks/README.md) include the aggregator that validates and rebuilds the summary. Latency and memory in the earlier table come from the separate [timing dataset](../../benchmarks/results/matched-browser-interface-samples.json), not from these instrumented token runs.

## Direct CDP baseline

The [CDP runner](../../benchmarks/run_matched_cdp.py) launches a disposable Chromium profile and sends protocol messages directly through `websockets`, without Playwright, Selenium, or a CDP client framework. Five runs verify the same task outcomes.

| Metric | Median |
|---|---:|
| Six-outcome sequence | 291 ms |
| Summed browser RSS | 1,038 MiB |
| Captured task CDP request/response text | 956 encoded tokens |

CDP is a lower-level baseline. Its protocol messages normally remain inside a browser tool and are not sent to a model, so the protocol token count has **no default agent-context or billing meaning**. It must not be subtracted from the CLI/MCP task-text table as “tokens saved.” The baseline also supplies its own DOM expressions and polling logic; it does not measure an agent discovering how to use CDP.

The [CDP capture](../../benchmarks/results/cdp-matched-results.json) records actual methods and messages. Setup calls and page events are separate; HTTP target discovery, WebSocket handshakes/framing, and unused events are excluded from task counts. Ports, request IDs, and transient CDP identifiers are normalized. Summed RSS has the same shared-page double-counting limitation as the other browser measurements.

## MCP latency and memory

Both MCP interfaces have five independently verified latency and memory samples. Timers cover the six task-call harness iterations, including local bookkeeping; discovery, browser warmup, and out-of-band verification are excluded. Browser RSS sums processes belonging to the disposable profile and excludes the MCP process.

| Interface | Median sequence | Median browser RSS |
|---|---:|---:|
| Sleeper MCP | 227 ms | 1,152 MiB |
| Playwright MCP | 1,635 ms | 1,027 MiB |

Raw samples: [Sleeper MCP](../../benchmarks/results/sleeper-mcp-matched-results.json) and [Playwright MCP](../../benchmarks/results/playwright-mcp-token-results.json). The original [CLI timing dataset](../../benchmarks/results/matched-browser-interface-samples.json) includes its matching browser and daemon resource samples as well.

## CLI protocol-text captures

These measurements capture actual client-to-daemon `/command` request and response JSON bodies. HTTP headers, framing, stdout, and stderr are excluded. Five runs independently verify the same six high-level outcomes.

| Interface | Median request tokens | Median response tokens | Median protocol-text total |
|---|---:|---:|---:|
| Sleeper CLI / daemon | 143 | 266 | 409 |
| OpenCLI / daemon | 25,598 | 3,554 | 29,152 |

Sleeper uses a transparent local HTTP proxy. OpenCLI uses a Node `fetch` capture hook and groups its underlying daemon requests by high-level operation; the median is 47 requests per six-operation sequence. Its request bodies include JavaScript implementation payloads. This is internal protocol traffic, not text automatically sent to a model, and the totals must not be advertised as model-token savings.

Captures retain exact JSON bodies alongside declared canonicalized variants for counting. Sources: [Sleeper CLI capture](../../benchmarks/results/sleeper-cli-protocol-capture.json), [OpenCLI capture](../../benchmarks/results/opencli-cli-protocol-capture.json), and [reproduction instructions](../../benchmarks/README.md). OpenCLI request-code attribution is recorded in [third-party notices](../../THIRD_PARTY_NOTICES.md).
