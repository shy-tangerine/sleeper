# Sleeper

[English](README.md) · [简体中文](docs/i18n/README.zh-CN.md) · [日本語](docs/i18n/README.ja.md) · [Português](docs/i18n/README.pt-BR.md) · [Español](docs/i18n/README.es.md) · [Deutsch](docs/i18n/README.de.md)

![Sleeper browser control for agents](assets/repository-hero.png)

<p align="center">
  <a href="docs/agent-skill.md#mcp"><img alt="MCP" src="https://img.shields.io/badge/MCP-supported-8B5CF6?style=flat-square&amp;labelColor=000000&amp;logo=modelcontextprotocol&amp;logoColor=white"></a>
  <a href="https://skills.sh/shy-tangerine/Sleeper"><img alt="skills.sh" src="https://img.shields.io/badge/skills.sh-install-06B6D4?style=flat-square&amp;labelColor=000000"></a>
  <a href="skills/sleeper/SKILL.md"><img alt="Agent skill" src="https://img.shields.io/badge/agent_skill-included-84CC16?style=flat-square&amp;labelColor=000000"></a>
  <br>
  <a href="https://github.com/shy-tangerine/Sleeper/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/shy-tangerine/Sleeper?style=flat-square&amp;labelColor=000000&amp;color=FACC15&amp;logo=github&amp;logoColor=white"></a>
  <a href="https://github.com/shy-tangerine/Sleeper/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/shy-tangerine/Sleeper/total?style=flat-square&amp;labelColor=000000&amp;color=38BDF8"></a>
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-A78BFA?style=flat-square&amp;labelColor=000000"></a>
  <a href="https://github.com/sponsors/shy-tangerine"><img alt="Sponsor" src="https://img.shields.io/badge/Sponsor-%E2%99%A5-F472B6?style=flat-square&amp;labelColor=000000&amp;logo=githubsponsors&amp;logoColor=white"></a>
</p>

Let your agent control the browser you already use, whether it’s on your
desktop or Android phone. Sleeper connects Firefox or Chromium through MCP or
CLI to navigate websites, read pages, fill forms, take screenshots, and extract
structured data without copying session credentials into agent configuration.

[Features](#features) · [Install](#install) · [Commands](docs/commands.md) · [Agent setup](docs/agent-skill.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md) · [Benchmarks](#benchmarks) · [Contribute](#contribute)

## Features

- 📱 **Firefox for Android (beta):** Run Sleeper on Android through a private Tailscale Serve connection to your desktop daemon. No Caddy, router port, or public listener is required.
- 🖥️ **Firefox + Chromium desktop:** Control pages in an existing browser session through the extension. Linux and macOS are supported; Windows is best-effort.
- 🗂️ **Profiles and tabs:** Each browser installation has its own persistent ID. Agents discover connected browsers and target the intended tab.
- 🎯 **Element targeting:** Find controls by CSS selector, accessible role and name, or a reference returned by `snapshot`.
- 📝 **Page interaction:** Fill inputs, press keys, click controls, and wait for selectors or text before the next action.
- 📋 **Structured extraction:** Read one element, collect matching elements, or extract a JSON map. Save repeatable work as recipes and schemas.
- 📸 **Screenshots:** Capture the viewport or full page, with optional annotations. PNG output has a size limit; [capture options](docs/commands.md#use-the-cli) explain it.
- 🌐 **Network and APIs:** Inspect captured requests and call allowed HTTPS APIs with credentials kept in the browser and bound to their source host.
- 🔒 **Secret masking:** Structured results receive best-effort redaction before reaching the CLI or MCP client. Screenshots can still contain private information.
- 🔌 **CLI and MCP:** Run shell commands or call MCP tools through the local daemon.
- 📖 **Included skill:** Give agents instructions for session selection, action verification, and connection recovery.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first,
then run from a checkout on **Linux or macOS** (the supported desktop
platforms):

```bash
./install.sh
```

Windows works on a best-effort basis and is not a launch-supported platform;
run in PowerShell:

```powershell
py scripts/install.py
```

Choose **Everything** or **Customize** to select MCP, native agent plugins, and standalone instructions. The installer starts the daemon, installs the CLI, registers Firefox's extension-scoped native host for automatic XPI pairing, keeps Chromium's extension in a permanent folder, and copies browser packages to Downloads.

Firefox for Android connects through Tailscale Serve (**beta**). Run `sleeper mobile setup`, then open the QR code in Firefox; see the [Android setup guide](docs/android.md). The daemon remains loopback-only.

### Troubleshooting

**Toolbar icon opens a thin full-width strip instead of the popup** — fixed by using a fixed popup width; rebuild and reinstall the extension package (see [docs/commands.md](docs/commands.md) for daemon environment configuration).

**"no browser connected" / popup shows "Daemon disconnected"** — check `curl http://127.0.0.1:8790/health` (daemon must be running), then run `sleeper sessions` (your browser should appear under `profiles`). For Firefox, rerun `./install.sh update` if the native host was not registered; the fields under **Advanced connection** are manual recovery only. Extension origins are pinned to the first browser add-on that pairs with the daemon; restrict them further with `SLEEPER_ALLOW_ANY_EXTENSION=false` and `SLEEPER_ALLOWED_EXTENSION_IDS=<uuid>,...` in the daemon's startup service (systemd user unit on Linux, LaunchAgent on macOS — see [docs/commands.md](docs/commands.md)).

Run `sleeper --version` for the installed CLI version. `sleeper sessions` reports daemon, protocol, and connected add-on versions; an incompatible or older add-on is marked in its browser record.

### Codex and Claude Code

The main installer can register Sleeper's native plugin when you choose
**Everything** or **Customize**. For manual setup, install the Sleeper runtime
first, then run the commands for your agent from the repository root.

**Codex**

```bash
codex plugin marketplace add .
codex plugin add sleeper --marketplace sleeper-local
```

**Claude Code**

```bash
claude plugin marketplace add . --scope user
claude plugin install sleeper@sleeper --scope user
```

<details>
<summary>Install the agent plugin from public GitHub</summary>

```bash
# Codex
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local

# Claude Code
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

</details>

Restart the agent after installation so it loads the bundled skill and MCP
server. See [agent setup](docs/agent-skill.md#native-plugins) for public-GitHub
installation, verification, updates, and removal commands.

| Browser | Finish installation |
|---|---|
| Chromium | Open the extensions page, enable **Developer mode**, choose **Load unpacked**, and select the folder printed by the installer. |
| Firefox | Install the signed `sleeper-firefox.xpi` release asset through **Add-ons → Install Add-on From File**. Signed releases are pending Mozilla signing credentials. |

Browser permission approval is required once. [Installation, updates, and removal](docs/installation.md).

Prefer manual client setup? Use the verified [Codex and Claude Code plugin commands](docs/agent-skill.md#native-plugins).

<details>
<summary>Install from GitHub</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

</details>


Inspect the open tabs and current page:

```bash
sleeper tabs
sleeper snapshot
sleeper type --role textbox --name Search 'your query' --clear
sleeper press Enter
```

While an agent is working, Sleeper can show a small on-page activity message such as **“Opening a page…”**, **“Clicked an element”**, or **“Timed out waiting for the page.”** These messages use plain language rather than CLI/MCP command names. Typed values, uploaded file contents, and other sensitive action values are not shown. Visible activity can be turned off in the extension settings; the toolbar still exposes connection and access state.

The included [agent skill](skills/sleeper/SKILL.md) covers session selection, action verification, and connection recovery. Agents can use MCP tools directly; the [command guide](docs/commands.md) covers tab targets, extraction, recipes, and API calls.

| Waiting | Working |
|:---:|:---:|
| <img src="extension/icon.svg" width="48" alt="Sleeper with a closed eye"> | <img src="extension/icon-active.svg" width="48" alt="Sleeper with an open eye"> |



## Benchmarks

Five verified runs per interface, on one machine. Each sequence navigates, reads a heading, types, clicks, waits for text, and reads the result.

Tested on Linux with **Helium 0.17.0.1 (Chromium 153.0.8010.36)**. Every interface used the same browser build and a fresh profile.

<table>
  <tr>
    <td align="center" valign="top" width="33%"><h3>76.7%</h3>lower sequence time<br><sub>Sleeper CLI vs OpenCLI</sub></td>
    <td align="center" valign="top" width="33%"><h3>82.8%</h3>lower sequence time<br><sub>Sleeper MCP vs Playwright MCP</sub></td>
    <td align="center" valign="top" width="33%"><h3>98.6%</h3>fewer protocol-text tokens<br><sub>Sleeper CLI vs OpenCLI</sub></td>
  </tr>
</table>

Percentages use the rounded medians below.

| Interface | Median sequence | Median browser RSS | Task-text tokens | Protocol-text tokens |
|---|---:|---:|---:|---:|
| Sleeper CLI | 934 ms | 1,139 MiB | 441 | 409 (HTTP JSON) |
| Sleeper MCP | 281 ms | 1,127 MiB | 502 | 695 (JSON-RPC) |
| OpenCLI | 4,011 ms | 1,218 MiB | 364 | 29,152 (HTTP JSON) |
| Playwright MCP | 1,635 ms | 1,027 MiB | 536 | 734 (JSON-RPC) |
| Direct CDP | 291 ms | 1,038 MiB | Not applicable | 956 (CDP) |

Task-text tokens estimate agent-facing input and output with `o200k_base`. Protocol tokens count internal HTTP JSON, JSON-RPC, or CDP traffic; they are not model usage. Direct CDP has no agent-facing task-text interface.

Browser RSS sums browser process memory, can double-count shared pages, and excludes daemons. Timing and protocol captures use separate runs. These results come from one machine, one browser build, and one run date (2026-09-11) measuring deterministic browser primitives, not agent task completion or general speed; see the [canonical methodology caveats](docs/benchmarks/matched-browser-interface.md#canonical-caveat-block), which must accompany these figures wherever they are quoted. [Raw samples, methodology, discovery costs, and feature comparison](docs/benchmarks/matched-browser-interface.md).

<details>
<summary>Browser checks on Linux</summary>

| Browser | Version | Result |
|---|---|---|
| Firefox | 155.0.1 | Passed |
| Chrome | 151.0.7922.47 | Passed |
| Zen | 1.22b | Passed |
| Helium | 0.17.0.1 (Chromium 153.0.8010.36) | Passed |

The Chrome check used Google Chrome for Testing, the automation distribution of Chrome. Its exact version is shown above.

</details>

## Contribute

[Build and test](docs/installation.md#development) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md) · [MIT license](LICENSE) · [Sponsorship](docs/SPONSORS.md)

<details>
<summary>Repository layout</summary>

| Directory | Contents |
|---|---|
| `extension/` | Browser manifests, page handlers, popup, icons |
| `daemon/` | HTTP/WebSocket relay and MCP server |
| `cli/` | CLI, recipes, adapter support |
| `skills/` | Agent instructions |
| `examples/` | Recipes and extraction schemas |
| `test/` | Behavioral, transport, and package checks |

</details>

## Star history

[View the star-history chart](https://www.star-history.com/#shy-tangerine/Sleeper&Date)

## Python package build (PyPI)

The browser extension release workflow is separate from Python packaging. Python package metadata is in `pyproject.toml`; `uv.lock` governs development. Run `uv lock --check`, `uv sync --locked`, and `uv build` to produce an sdist and wheel in `dist/`. After the owner approves a release and PyPI credentials/trusted publishing are configured, `uv publish` can upload those artifacts. Do not treat building as release authorization.
