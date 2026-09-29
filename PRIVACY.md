# Privacy

Sleeper is a local browser-control bridge. It has no developer-operated
analytics, advertising, tracking, account system, or cloud relay. It does not
sell or send browsing data to the developer.

## What Sleeper processes

When an agent asks for an action, the extension may send the requested command
to the Sleeper daemon and return the requested result. Depending on the
command, this can include:

- tab titles, URLs, tab state, and page DOM or visible text;
- user-requested clicks, typing, form interactions, scrolling, and waits;
- network-request metadata and response data requested through the network or
  API commands; and
- screenshots explicitly requested by the agent.

This processing is necessary to carry out the user's requested automation. A
result or screenshot can contain sensitive information from the page. The
daemon and the MCP/CLI client are controlled by the user; only connect agents
and tailnet devices that the user trusts.

Firefox requires the `<all_urls>` host permission for unattended screenshot
capture. Sleeper's Firefox content scripts remain limited to HTTP and HTTPS
pages; Chromium keeps separate HTTP and HTTPS host permissions.

## What is stored locally

Sleeper can also display transient on-page activity feedback while an action is running. These messages are human-readable summaries of the action and outcome, not protocol/debug output; sensitive typed values and file contents are omitted. The transient message itself is not persisted as page content and can be disabled with the **Visible activity** setting. The recent-action history described below is a separate, bounded local record.

The extension uses Firefox or Chromium local extension storage for connection
settings, the private browser installation ID and access preferences, mobile onboarding state,
connection status, and a bounded recent-action history. Action history records
the command, status, timing, target metadata, and a sanitized URL path. It
deliberately excludes typed values, file contents, and request bodies, but it
is not a record of page privacy: command results and screenshots can still
contain sensitive data and may be saved separately by the client.

On desktop, the daemon's loopback authentication token is managed internally,
stored in the user's configuration directory with owner-only permissions, and
cached by the extension for reconnects. It is not displayed or editable in
Sleeper's interface. Tailscale mobile connections use the user's tailnet identity
and do not copy that local token to the phone. The daemon is configured to
remain loopback-only; Tailscale Serve is the remote transport for mobile use.

Sleeper does not intentionally persist page content, command results, network
captures, screenshots, cookies, or passwords. The local daemon token is the
exception described above and is never sent through Tailscale. Page data and
other command values may exist temporarily in browser, daemon, agent, or
operating-system memory and may be written by a user's chosen client or
command. Structured results apply best-effort masking to common secrets;
masking is not a guarantee and does not alter screenshot pixels.

## Network and third parties

The default desktop connection uses loopback HTTP/WebSocket endpoints. Mobile
uses HTTPS/WSS through the user's private Tailscale network. Sleeper does not
operate a remote service for these connections. The optional API command is
restricted to explicitly allowlisted HTTPS hosts and binds captured bearer
credentials to the host where they were observed.

The extension package contains no remote JavaScript or analytics SDK. Tailscale
is a separate service with its own policies; it is required only for the
mobile-to-computer connection path.

## Removing local data

Clear recent actions from the extension's settings page, remove the extension
through the browser's add-on manager, and stop/uninstall the daemon to remove
its local runtime state and managed credentials. Review and remove any
screenshots, exports, agent transcripts, or logs created by external clients
separately.

This policy describes the source tree and the Firefox/Chromium packages built
from it. It should be reviewed again whenever permissions, storage keys,
daemon listeners, or third-party network behavior changes.
