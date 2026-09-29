# Security policy

Sleeper controls an existing browser session and can therefore handle highly
sensitive page content. Please do not disclose a vulnerability in a public
issue, discussion, pull request, or chat transcript.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting / Security Advisory form for the
Sleeper repository. Include the affected version or commit, the smallest
reproduction that demonstrates the issue, and the security impact. If private
reporting is unavailable while the repository is being prepared, contact the
maintainer privately through the repository account and do not attach live
cookies, tokens, passwords, screenshots, or customer data.

We will acknowledge a report when it is received, keep the report private
while a fix is prepared, and coordinate disclosure after users have a fix.

## What belongs in scope

Reports involving extension permissions, page-to-extension message
boundaries, daemon authentication, Tailscale setup, cross-origin access,
credential or screenshot exposure, command authorization, and package or
installer integrity are in scope. Denial-of-service reports without a
confidentiality or integrity impact may be handled as ordinary bugs.

## Extension-origin trust

The daemon accepts WebSocket connections only from genuine
`moz-extension://` / `chrome-extension://` origins (webpages can never present
one) that also prove possession of the local daemon token. By default the
first extension to pair is pinned on disk; later connections from a different
extension ID are rejected, which limits a stray or attacker-installed dev
build from silently attaching to an existing daemon. Set
`SLEEPER_ALLOW_ANY_EXTENSION=false` with `SLEEPER_ALLOWED_EXTENSION_IDS` for a
fixed allowlist in managed environments. See
[docs/commands.md](docs/commands.md) for the exact variables.

## Supported versions

The latest release and the current default branch are supported. Development
builds are not a secure update channel and should be used only with test
profiles and test accounts.

Never publish the staging repository, its Git history, local analysis state,
or build output as part of a security report. Public release preparation uses
the history-free export procedure in [docs/publication.md](docs/publication.md).
