# Comparison

Sleeper is designed for agents working in an existing Firefox or Chromium session, with a CLI, MCP tools, and an agent skill. The comparison below separates a measured local browser task from broader interface capabilities.

## Matched benchmark results

On 2026-09-11, Sleeper and OpenCLI each completed five verified runs of the same local fixture: navigate, read a heading, type, click, wait for delayed text, and read the result. Both used the same Chromium binary and disposable profiles. Model inference and external network requests were excluded.

| Interface | Median sequence | Median browser RSS | Task-text tokens | Protocol-text tokens |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 227 ms | 1,152 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | Not applicable | 956 (CDP) |

The browser memory columns sum process RSS and can double-count shared pages. Browser RSS excludes daemon and short-lived CLI child processes. The original CLI timing samples retain daemon measurements separately in their raw data. These are endpoint samples, not peak memory. Browser CPU deltas and cumulative daemon CPU samples are recorded for diagnostics in the raw results; process replacement makes a CPU ranking unreliable.

This small sample characterizes one fixture on one machine. It does not measure model task success, internet latency, all browser features, or total machine resource consumption. Launch-only browser startup is separate from the six-operation timer and excludes bridge readiness.

See the [full protocol and capability matrix](benchmarks/matched-browser-interface.md), [individual samples](../benchmarks/results/matched-browser-interface-samples.json), and [reproduction instructions](../benchmarks/README.md).

## Other tools to evaluate

[OpenCLI](https://github.com/jackwener/opencli) offers a broad CLI interface and site-specific integrations through its Browser Bridge. It is the direct CLI comparison measured here.

[Playwright MCP](https://github.com/microsoft/playwright-mcp) exposes browser automation through MCP and is useful when Playwright's browser control and testing ecosystem fit the task. Its separate smoke tests used a different operation sequence and are not included in the timing table.

[Browser Use](https://github.com/browser-use/browser-use) combines browser automation with an agent framework and local or cloud browser options. A deterministic action-API test is not a measurement of its model-driven Agent. Fresh-session failures in the local experiment prevented a complete matched dataset, so no Browser Use speed ranking is published.

For authenticated APIs, Sleeper's specific contract is an exact HTTPS host allowlist with credentials bound to the host where they were captured. The benchmark does not compare competitors' authentication policies or make claims about which policy is better.

## Token estimates and protocol captures

The table uses measured medians. Sleeper CLI uses about **12% fewer task-text tokens than Sleeper MCP** in this fixture. The token counts are deterministic text-encoding estimates with `o200k_base`, excluding model reasoning, shared shell/skill instructions, and client-specific context formatting.

CLI protocol figures come from captured `/command` HTTP JSON bodies. OpenCLI's six high-level operations produced a median of **47 underlying daemon requests**, including JavaScript execution payloads. Its 29,152 protocol-text tokens are internal traffic, not model context. Direct CDP likewise has no agent-facing task-text interface; that cell is not applicable.

See [measurement definitions, discovery overhead, raw samples, and reproduction steps](benchmarks/matched-browser-interface.md).
