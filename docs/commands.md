# Command guide

## User-visible activity feedback

Sleeper's on-page feedback, toolbar popup, and recent-action history describe automation in plain language for the person using the browser. Internal wire names such as `waitXhr`, `selectOption`, and `exec` are not intended as user-facing status text. For example, a network wait appears as **“Waiting for a network request…”** and page JavaScript appears as **“Running a page script…”**. Unknown protocol commands use a generic browser-action description rather than exposing the raw identifier.

Feedback wording changes with the outcome so running, completed, failed, and timed-out actions are distinguishable. Typed values, file contents, and other sensitive value-bearing details are omitted. This UI is a transparency/status surface, not a debug console; agents and integrations should inspect command results for technical diagnostics. Users can disable the transient on-page cue with **Visible activity** in extension settings.

Use the installed `sleeper` command or the agent client's declared MCP tool schemas. Check `ok` and the resulting browser state when verifying an action.

## Use the CLI

The following examples use synthetic pages and selectors. Replace selectors with elements found on your target page. `find` and `snapshot` return element references such as `@sleeper-1`; use references from the current page, and refresh them after navigation.

<!-- cli-contract:start -->
```bash
sleeper sessions
sleeper state
sleeper tabs
sleeper goto 'https://example.com'
sleeper find 'h1' --limit 5
sleeper find --role button --name 'Save'
sleeper click '@sleeper-1'
sleeper type 'input[name=q]' 'example query' --clear
sleeper read 'h1'
sleeper read_all '.result'
sleeper wait '.loaded' --timeout 15000
sleeper extract '{"title":"h1","items":".result"}'
sleeper snapshot
sleeper tab new 'https://example.com'
sleeper tab select 0
sleeper tab close 0
sleeper wait download 'report.csv' --timeout 15000
sleeper network --since=60
sleeper api '/api/example' --method GET
sleeper shot --full-page --annotate --width 1280 --height 800
```
<!-- cli-contract:end -->

`wait_xhr` and `wait download` observe completions after the wait starts; an
older completed request or download does not satisfy them. A download already
in progress can satisfy `wait download` when it finishes. Individual browser
waits accept up to `--timeout 60000` (milliseconds); larger values return an
error instead of ending the wait early.

### Ordered action batches

Group browser actions into one daemon round trip with `batch`. Actions run in
the order supplied and stop at the first failure by default. Add
`--continue-on-error` when later actions should still run:

```bash
sleeper batch '[{"cmd":"goto","args":{"url":"https://example.com"}},{"cmd":"read","args":{"selector":"h1"}}]'
sleeper batch '[{"cmd":"click","args":{"selector":"#optional"}},{"cmd":"read","args":{"selector":"h1"}}]' --continue-on-error
```

The MCP equivalent is `sleeper_batch` with an `actions` array and optional
`stop_on_error` boolean. Batches contain at most 50 actions and cannot nest.
The daemon computes a batch budget by summing each validated action's budget,
including requested long waits and retry delays, then caps the aggregate at the
global HTTP timeout ceiling. Each action receives at most its own budget and the
remaining aggregate time, so later actions apportion only unused time and the
batch cannot extend the request beyond that ceiling.

### Structured waits and browser-specific JavaScript

Signed Firefox builds accept declarative `wait_until` conditions. Pass a JSON
object containing a selector or text plus an optional state, count, attribute,
value, comparison operator, or exact-text flag:

```bash
sleeper wait_until '{"selector":".result","state":"visible"}'
sleeper wait_until '{"selector":".result","count":3,"operator":"gte"}'
sleeper wait_until '{"selector":"button","attribute":"aria-busy","value":"false"}'
```

Supported states are `exists`, `missing`, `visible`, `hidden`, `enabled`,
`disabled`, `checked`, and `unchecked`. Supported operators are `eq`, `gte`,
`lte`, `gt`, `lt`, and `contains`.

`wait_text` and `find_text` search rendered page text only: raw `<script>` or
`<style>` source and elements hidden with `display:none` / `visibility:hidden`
are excluded, so a string that appears only inside JavaScript source cannot
make a wait succeed. Pass `--include-hidden` (MCP: `include_hidden`) to search
hidden content deliberately.

Arbitrary JavaScript through `exec` and JavaScript-string predicates through
`wait_until` are Chromium-only. Firefox returns an explicit unsupported-command
error; all structured browser controls remain available.

Numeric tab selectors (including `tab close`, `tab select`, and `--tab`) use the zero-based `index` shown by `tab list`, ordered by window and then tab position. `windowIndex` is the browser’s position within its window; `tabId` is browser metadata, not a numeric selector. Re-list after tabs move, open, or close before using another positional selector. DOM commands that support `--tab` accept this index or a URL substring. Prefer an exact, unambiguous target when several tabs share a host. Screenshots are returned as PNG data URLs in a JSON response, capped at 3.75 MiB of encoded image data. Larger captures return an error; reduce the viewport or capture the visible area. See the security and browser limitations below.

[OpenCLI compatibility](OPENCLI-PARITY.md) lists aliases and platform differences. `analyze` inspects URL strings; it does not crawl or prove a site's automation compatibility. `adapter init NAME` creates a local adapter scaffold and `adapter verify NAME` checks it.

### Browser profiles

Each extension installation receives a persistent ID automatically. With one connected browser, commands need no routing configuration. With several, use `sleeper sessions` to discover IDs and choose the intended browser:

```bash
SLEEPER_PROFILE=BROWSER_ID sleeper state
```

For a project-local binding, run `sleeper bind BROWSER_ID`. This writes `.sleeper-session` in the current directory. `sleeper unbind` or `sleeper close` removes the binding; it does not close the browser. `SLEEPER_PROFILE` overrides the file. The optional friendly label in settings helps identify a browser and does not change its routing ID.

### Recipes and schemas

`recipe NAME --json` executes `examples/recipes/NAME.json`; `schema NAME --json` extracts using `examples/schemas/NAME.json`. Inspect the file before running it against a logged-in account.

**Destructive recipe:** `chatgpt-delete-conversations` deletes conversations returned by its initial request. It requests only the first page, with a limit of 100, and does not paginate through all conversations. It has no interactive confirmation. Its name and description are not a guarantee that every conversation will be deleted. Do not run it unless that deletion is intended.


## Authenticated API calls

`api` permits exact HTTPS hosts and binds captured bearer tokens to the host where they were observed. A token from one host is not attached to another host. Set the allowlist in the daemon environment:

```ini
[Service]
Environment="SLEEPER_API_HOSTS=api.example.com"
```

On Linux, use `systemctl --user edit sleeper.service` to add that override, then run `systemctl --user daemon-reload` and `systemctl --user restart sleeper.service`. On macOS, set the environment variable for the LaunchAgent (for example, with `launchctl setenv SLEEPER_API_HOSTS api.example.com`) and restart it with `launchctl kickstart -k gui/$(id -u)/com.shy-tangerine.sleeper`. Reload the extension after configuration changes.

When `SLEEPER_API_HOSTS` is unset, the defaults are `chatgpt.com,www.chatgpt.com`. An explicitly empty value denies all hosts. Wildcards, schemes, paths, and explicit ports are rejected. The allowlist authorizes authenticated requests; it does not restrict ordinary DOM navigation to those hosts.

For strict lock-down in non-production setups, configure extension IDs explicitly:

- `SLEEPER_ALLOW_ANY_EXTENSION=false|no|off|0` (deny-by-default for unlisted extension origins),
- `SLEEPER_ALLOWED_EXTENSION_IDS=...` (comma-separated extension IDs; required when the deny default is enabled).

By default (the **pin** mode) the first `moz-extension://` / `chrome-extension://` origin that completes the daemon's HMAC challenge is remembered in `SLEEPER_EXTENSION_PIN_FILE` (default `~/.config/browser-sleeper-extension-pin`), so a fresh install pairs automatically; later connections from a *different* extension ID are rejected until the pin file is deleted (a deliberate local action) or an explicit allowlist is configured. Set `SLEEPER_ALLOW_ANY_EXTENSION=true|yes|on|1` to trust every genuine extension origin without pinning — development only, and never grant a webpage an extension origin.

Restrict accepted extension IDs when profiles are centrally managed or when re-installing dev builds alongside the release extension.

The daemon's HTTP port is `SLEEPER_HTTP_PORT`; CLI and MCP clients use `SLEEPER_PORT` to select the same port. The WebSocket port is `SLEEPER_WS_PORT`; `SLEEPER_BIND_HOST` defaults to `127.0.0.1` and rejects non-loopback addresses. Local CLI, MCP, and extension requests read `SLEEPER_TOKEN_FILE` (default `~/.config/browser-sleeper-token`) and prove possession with per-request HMACs bound to the current daemon process; the token is never sent in an HTTP header, URL, or WebSocket frame. `/health` remains public and returns only a process identity challenge response. Firefox's release XPI obtains the token through a native host allow-listed to Sleeper's add-on ID; the installer registers that host. The extension's advanced connection fields are for manual recovery. Mobile setup puts the secret in the setup URL fragment (which browsers do not send to the server) and verifies the daemon before storing it; see [Android setup](android.md).

`sleeper --version` works without the daemon. `sleeper sessions` includes daemon and protocol versions plus each connected add-on version and a compatibility flag. If the daemon is stopped, CLI and MCP errors include the platform-specific recovery command (Linux: systemd; macOS: launchctl); the installer registers a startup service on both (systemd user unit on Linux, LaunchAgent on macOS) that restarts the daemon after clean or failed exits.

## Browser profile routing

Sleeper uses one local daemon for all installed browsers. MCP clients discover private installation IDs with `sleeper_sessions`, then pass the intended ID as `profile` on each tool call. CLI clients use `SLEEPER_PROFILE` or a project binding.

When multiple browsers are connected, an untargeted command returns a discovery error. After choosing an ID, `sleeper tabs` lists that browser's tabs; the `tab` selector stays inside that browser. A duplicated installation ID (for example, a copied browser profile) is rejected while both copies are connected.

## File uploads

MCP `sleeper_upload` accepts explicit file contents: `files` is an array of objects with `name`, `content_base64`, and an optional `mime_type`. The total JSON request must fit the daemon's 1 MiB request limit. Native file paths and the CLI's filename-only `upload --files` form are unsupported and return an error; Sleeper does not substitute dummy bytes.
