# Setup and connection recovery

Use the repository's one-command installer to install the daemon, CLI, MCP configuration and this skill. It also places the Firefox XPI and Chromium ZIP in the user's Downloads directory. Follow the installer output for the supported MCP client and reload the client so it discovers the tools.

The browser step is separate: load the supplied package, then reload the target page. Chromium uses the permanent folder printed by the installer through **Extensions → Developer mode → Load unpacked**. Firefox requires the AMO-signed `sleeper-firefox.xpi` release asset for persistent installation; an unsigned development build cannot substitute for it. The installer registers a native messaging host allow-listed to Sleeper's fixed Firefox add-on ID, so the XPI pairs locally without manual token entry. Browser permission approval remains a browser step.

To diagnose a connection:

1. Run `sleeper tabs`. If the daemon cannot be reached, inspect `systemctl --user status sleeper.service` on systemd installations and its recent journal. Use the installer's foreground instructions on systems without systemd.
2. If the daemon answers with no connected tabs, confirm the extension is enabled and reload a normal HTTP(S) page. Browser-internal pages cannot run its content script.
3. Use `sleeper_sessions` or `sleeper sessions`. Pass the intended installation ID as MCP `profile` or CLI `SLEEPER_PROFILE`. IDs persist across browser restarts. A single connected browser needs no explicit target.
4. Retry a read-only snapshot. Recovery is complete only when it returns the intended page.

The default HTTP port is 8790; the extension's WebSocket port is 8789. Custom daemon HTTP and client ports must agree (`SLEEPER_HTTP_PORT` and `SLEEPER_PORT`). Changing the WebSocket port also requires matching extension configuration. Advanced endpoint/token fields are manual recovery only. Keep credentials and the local token file out of diagnostic output.
