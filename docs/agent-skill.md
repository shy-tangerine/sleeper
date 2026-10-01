# Agent setup

Sleeper includes two complementary interfaces: MCP exposes callable tools, and the [Sleeper skill](../plugins/codex/sleeper/skills/sleeper/SKILL.md) teaches an agent how to select a session, inspect a page, perform an action, and verify the result. Installing MCP alone exposes tool schemas but does not provide the complete workflow.

## Native plugins

Sleeper's native Codex and Claude Code plugins each bundle the Sleeper skill, its references, and the MCP server registration. Install the native plugin for your client instead of adding a standalone Sleeper skill and MCP entry to that same client. The plugin still needs the local Sleeper runtime: install Python 3.10 or newer, load a supported browser extension, run the daemon, and make sure `sleeper-mcp` is on the client process's `PATH`.

The main installer can set up the runtime and register a native plugin in one pass. If you use this path, do not repeat the manual marketplace commands below:

```bash
./install.sh --non-interactive --plugins codex --no-skill
./install.sh --non-interactive --plugins claude --no-skill
```

On Windows, use the same options with `py scripts/install.py`. A missing client is reported in `plugins_pending`; install that client and rerun the installer.

### Codex

From a local Sleeper checkout, run these commands at the repository root:

```bash
codex plugin marketplace add .
codex plugin add sleeper --marketplace sleeper-local
```

After the public repository launches, register its Git marketplace instead:

```bash
codex plugin marketplace add https://github.com/shy-tangerine/Sleeper.git
codex plugin add sleeper --marketplace sleeper-local
```

Verify the registration and installation with `codex plugin marketplace list` and `codex plugin list --marketplace sleeper-local`, or open `/plugins` in the Codex CLI. For a local checkout, pull the new source and rerun `codex plugin add sleeper --marketplace sleeper-local`; for the Git marketplace, run `codex plugin marketplace upgrade sleeper-local`. Start a new Codex session after installation or update so the bundled skill and MCP tools are loaded.

Uninstall the plugin and then remove its marketplace registration:

```bash
codex plugin remove sleeper --marketplace sleeper-local
codex plugin marketplace remove sleeper-local
```

These commands require a Codex CLI release that provides `codex plugin`. The command syntax was verified with Codex CLI 0.153.4 and matches the [official Codex plugin packaging and marketplace guide](https://developers.openai.com/plugins/build/plugins).

### Claude Code

From a local Sleeper checkout, run these commands at the repository root:

```bash
claude plugin marketplace add . --scope user
claude plugin install sleeper@sleeper --scope user
```

After the public repository launches, register its Git marketplace instead:

```bash
claude plugin marketplace add https://github.com/shy-tangerine/Sleeper.git --scope user
claude plugin install sleeper@sleeper --scope user
```

Verify the installation with `claude plugin marketplace list`, `claude plugin list`, and `claude plugin details sleeper@sleeper`. After updating a checkout or before fetching a newer Git-backed release, run `claude plugin marketplace update sleeper` followed by `claude plugin update sleeper@sleeper --scope user`. Restart Claude Code after installation or update; Claude applies plugin updates on restart.

Uninstall the plugin and then remove its marketplace registration:

```bash
claude plugin uninstall sleeper@sleeper --scope user
claude plugin marketplace remove sleeper --scope user
```

These commands require a Claude Code release that provides `claude plugin`. The command syntax and a complete isolated install, inspect, update, and uninstall round-trip were verified with Claude Code 2.1.269 and agree with the [official Claude Code plugin guide](https://code.claude.com/docs/en/discover-plugins).

The generated packages live under `plugins/codex/sleeper/` and `plugins/claude/sleeper/`. `python3 scripts/build_native_plugins.py build` regenerates both from the canonical skill; `validate` checks that the packaged references and instructions match.

## Install the skill

When the standalone skill is selected, the [installer](installation.md) copies the complete skill directory, including its setup and network references, to `~/.agents/skills/sleeper`. Restart or reload your agent client so it discovers the new skill. In Codex, ask to use `$sleeper` or describe a task involving an existing browser session.

For a skill-only installation from a local checkout, install Node.js with npm (which supplies `npx`), then use the open-source Skills CLI:

```bash
npx skills add . --skill sleeper --global
```

Choose the agent clients you use when prompted. The skill provides instructions; the daemon, browser extension, and CLI still need installation. Agents should confirm that the daemon answers and a browser tab is connected before beginning page work.

## MCP

Sleeper's MCP server uses stdio and works with any client that supports local MCP servers. The installed `sleeper-mcp` launcher starts the bridge; it connects to the shared Sleeper daemon. Each client may start its own lightweight bridge process, while browser sessions remain attached to the same daemon.

For clients that accept JSON MCP configuration:

```json
{
  "mcpServers": {
    "sleeper": {
      "command": "sleeper-mcp"
    }
  }
}
```

Use the launcher's absolute path printed by the installer if a desktop client does not inherit your terminal's `PATH`. Configuration locations and approval steps depend on the client; there is no universal MCP registration file. A native Sleeper plugin supplies this configuration and the skill together, so that client does not also need standalone copies.

Reload your agent client and open browsers with the Sleeper extension loaded. Start with `sleeper_sessions`, select its stable installation ID from page context, and pass that ID as `profile` on each relevant MCP tool call. Then call `sleeper_tabs` with the selected ID and select a `tab` when the browser has more than one target. An empty list means browser setup or connection recovery is still needed. Follow the skill's [setup reference](../plugins/codex/sleeper/skills/sleeper/references/setup.md).

The CLI and MCP expose different subsets of functionality. Agents should use the declared MCP tool schemas and consult `sleeper --help` for CLI operations, rather than translating flags directly into tool arguments.

Sleeper's transient on-page cue, toolbar popup, and recent-action history use plain-language action descriptions rather than protocol command names. Typed values and file contents are deliberately omitted. The transient cue is separate from the bounded local history and can be disabled with **Visible activity** in extension settings; integrations should use command results, not this user-facing feedback, for diagnostics.

## Distribution through skills.sh

The canonical skill lives at `plugins/codex/sleeper/skills/sleeper/SKILL.md`, with its supporting references beside it. Install it from GitHub with:

```bash
npx skills add shy-tangerine/Sleeper --skill sleeper --global
```

The [skills.sh FAQ](https://skills.sh/docs/faq) says skills appear on its leaderboard automatically through aggregate installation telemetry from the Skills CLI. There is no separate package upload or listing pull request in that documented flow. The [directory documentation](https://skills.sh/docs) also provides a repository install-count badge. A successful local installation is not evidence that a public listing already exists.

The directory listing appears separately from GitHub publication. Verify that the complete skill and its references install successfully, then check the listing.

## Choosing a browser destination

One Sleeper daemon can serve Chromium and Firefox at the same time. Before acting, call `sleeper_sessions`, select the stable installation ID, and pass it as `profile` on each relevant MCP tool call. Then use `sleeper_tabs` with that ID and its `tab` selector when needed. A single connected browser remains the default target; with multiple browsers, choose an ID from the inventory.
