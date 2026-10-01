# Installation

Read the [privacy policy](../PRIVACY.md) before connecting an agent to a
logged-in browser. Security reports belong in the private channel described
in [SECURITY.md](../SECURITY.md).

## One-command setup

The installer runs on Linux, macOS, and Windows. Linux and macOS are the
supported desktop platforms; Windows is best-effort and not launch-supported.
It needs Python 3.10 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/); network access is needed to install locked Python dependencies. The installer uses its portable Python package builder on every platform and does not require `jq` or `zip`. The Unix bootstrap and CLI use Bash; Windows uses the native Python CLI. Git is needed for installation without a checkout.

From a Linux or macOS checkout:

```bash
./install.sh
```

From a Windows PowerShell checkout:

```powershell
py scripts/install.py
```

After the repository becomes public, installation without a checkout will use:

```bash
curl -fsSL https://raw.githubusercontent.com/shy-tangerine/Sleeper/main/install.sh | bash
```

The installer offers **Everything** or **Customize** in an interactive terminal. The core installation sets up the daemon, CLI, Python environment, browser packages in Downloads, and a background service. Optional integrations are the standalone MCP bridge, standalone skill, and native Codex and Claude Code plugins. Browser extension loading requires the browser steps below.

A native plugin includes the skill and MCP configuration for its client. Selecting plugins skips a new shared standalone skill by default; Customize can retain one for other clients. Successful plugin installs remove redundant Sleeper-managed MCP registrations for that client and an unchanged managed shared skill when it was not selected for other clients. Existing custom skills and MCP entries are preserved. Missing agent clients are reported in `plugins_pending`; install the client and rerun the installer to finish.

For direct marketplace registration instead of installer-managed setup, use the verified [Codex and Claude Code native plugin commands](agent-skill.md#native-plugins).

Default locations:

| Component | Location |
|---|---|
| Runtime and Python environment | `~/.local/share/sleeper/` |
| CLI | `~/.local/bin/sleeper` |
| MCP launcher | `~/.local/bin/sleeper-mcp` (`sleeper-mcp.cmd` on Windows) |
| Native plugins | Runtime directory under `marketplaces/codex/` and `marketplaces/claude/` |
| Standalone Codex registration, when selected | `~/.codex/config.toml` |
| Agent skill and references | `~/.agents/skills/sleeper/` |
| Browser packages | XDG Downloads directory, or `~/Downloads/` |
| Background service | Linux: `~/.config/systemd/user/sleeper.service`; macOS: `~/Library/LaunchAgents/com.shy-tangerine.sleeper.plist`; Windows: HKCU Run entry `Sleeper` |

On Linux, the runtime respects `XDG_DATA_HOME` and the systemd service respects `XDG_CONFIG_HOME`. macOS uses Application Support and LaunchAgents; Windows uses Local AppData and a `.cmd` launcher. Codex configuration remains at `~/.codex/config.toml` unless `SLEEPER_CODEX_CONFIG` overrides it. The installer adds its launcher directory to the current user's persistent `PATH`: `.profile` on Linux, `.zprofile` on macOS, and the user `Path` registry value on Windows. Open a new terminal or PowerShell window before running `sleeper`. Restart the agent client after installing its MCP configuration and skill.

For environments where the background service should be managed externally, pass `--no-service` (`py scripts/install.py --no-service` in PowerShell). Linux installs a user systemd service, macOS installs a per-user LaunchAgent, and Windows stores a per-user `Sleeper` entry in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; it starts the daemon immediately without a console when no daemon already owns the local port. Updates replace the Run entry and take effect at the next logon when an existing daemon remains active.

Run the installed daemon with its virtual environment's Python interpreter, or arrange startup through your environment's service manager. The default command is:

```bash
~/.local/share/sleeper/venv/bin/python ~/.local/share/sleeper/daemon/daemon.py
```

## Future PyPI installation

The Python distribution candidate is `sleeper-cli`; the generic
PyPI name `sleeper` is already occupied by an unrelated package. The candidate
was checked on PyPI on 2026-09-13 and was not present then; availability is not
reserved and must be rechecked before release. Once published, the CLI, daemon,
and stdio MCP launcher can be installed with:

```bash
uv tool install sleeper-cli
# or: python -m pip install sleeper-cli
sleeper --help
```

The runtime package does not contain the browser extension,
Firefox/Chromium packages, native Codex or Claude plugins, agent skill files,
installer, or service definitions. Install and load a compatible extension
separately, then run `sleeper-daemon`; configure an MCP client to execute
`sleeper-mcp`. The current checkout installer remains the path for setting up
all of those artifacts together.

## Browser extension

The Downloads files are locally built development packages. They are not signed Firefox releases or store installations.

**Chromium:** extract `sleeper-chromium.zip` into a permanent directory. Open `chrome://extensions` (or your browser's extensions page), enable **Developer mode**, select **Load unpacked**, and choose that directory. Keep it in place while the extension is installed. If Chrome reports an unsupported manifest, rebuild with `./scripts/build-chromium.sh` and load the extracted ZIP. The source `extension/` directory contains the Firefox manifest and cannot be loaded directly in current Chrome.

**Firefox:** install the `sleeper-firefox.xpi` asset from a Sleeper GitHub Release. This is an AMO-signed, unlisted package that Firefox can install persistently: download it, open Firefox's add-ons manager, choose the settings menu, select **Install Add-on From File**, and choose the downloaded XPI. Firefox shows the requested permissions before installation. The installer always copies `sleeper.xpi` as an unsigned development package; it copies `sleeper-firefox.xpi` only when a version-matched signed build is already available locally. It never submits an add-on for signing. `sleeper.xpi` is not a supported persistent installation path. If a release does not contain `sleeper-firefox.xpi`, no signed Firefox package has been published for that version yet.

The installer registers the Firefox native messaging host before you install the XPI; it is allow-listed to Sleeper's fixed add-on ID and pairs the local extension automatically. Open the extension popup and confirm the daemon connection. Reload pages opened before the extension was loaded. Then run:

```bash
sleeper tabs
sleeper snapshot
```

For Firefox for Android on another device (beta), use [Tailscale-only Android setup](android.md). The pairing URL configures HTTPS/WSS automatically while the daemon remains loopback-only.

If no tabs appear, use the [connection recovery guide](../plugins/codex/sleeper/skills/sleeper/references/setup.md). The icon's closed eye indicates idle state; the popup supplies connection status.

## Updates and removal

From an updated checkout, run:

```bash
./install.sh update
```

Reload the browser extension after replacing its files, and restart the agent client to pick up skill or MCP changes.

To remove the managed runtime and integration:

```bash
./install.sh uninstall
```

Remove the extension through your browser's extension manager. Downloaded packages can be deleted separately.

For unattended installation, use `./install.sh --yes` for all integrations, or select components explicitly:

```bash
./install.sh --non-interactive --plugins codex --no-skill
./install.sh --non-interactive --no-plugins --no-mcp --no-skill
```

The second command installs the browser runtime and CLI without agent integrations. On Windows, use the same flags with `py scripts/install.py`.

`--no-plugins`, `--no-mcp`, and `--no-skill` exclude optional components; explicit exclusions also apply with `--yes`. A selected plugin still needs the MCP launcher even when standalone MCP registration is excluded. `--no-build` skips browser packages. These flags skip installation; they do not uninstall existing components. See `./install.sh --help` for all options. `--no-deps` is intended for controlled tests or an already prepared environment and does not create a usable Python environment on its own.

## Development

Runtime code is grouped under `extension/`, `daemon/`, and `cli/`. Examples live under `examples/`; the agent skill lives under `plugins/codex/sleeper/skills/`.

Build development browser packages:

```bash
./scripts/build-xpi.sh
./scripts/build-chromium.sh
```

Each development package embeds a `SOURCE_ID` (the packaging git commit and a
digest of exactly the packaged files) that is independent of the release
version, so two same-version packages built from different sources are
distinguishable. `sleeper sessions` reports the installed add-on's source
identity, and the installer compares a package already present in Downloads
against the fresh build and replaces a stale same-version copy with a printed
warning.

Outputs are written under `build/`. Create a development environment and run the checks:

```bash
uv sync --frozen
uv run pytest -q test
uv run bash test/run.sh
uv run python scripts/check_public_tree.py
```

See the [command guide](commands.md) for CLI examples and the [comparison](comparison.md) for benchmark scope and limitations.
