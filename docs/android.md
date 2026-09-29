# Android setup

> **Status: beta.** The Firefox-for-Android flow works end to end but is
> younger than the desktop paths and needs a Tailscale tailnet; report Android
> issues as [bug reports](https://github.com/shy-tangerine/Sleeper/issues/new?template=bug_report.md).

Sleeper uses Tailscale Serve as its only mobile-access path. The daemon stays
bound to `127.0.0.1`; Tailscale supplies HTTPS/WSS and private routing. The
mobile setup link carries the daemon bearer only in its URL fragment, which is
not sent in the HTTP request; the extension verifies that bearer against the
daemon before saving it.

## Computer setup

1. Install Tailscale and sign this computer into your tailnet.
2. Enable MagicDNS and HTTPS certificates for the tailnet.
3. Start the Sleeper daemon normally.
4. Run:

   ```bash
   sleeper mobile setup
   ```

Sleeper configures two tailnet-only HTTPS listeners:

- `https://HOSTNAME.ts.net:8790` → daemon HTTP on `127.0.0.1:8790`
- `wss://HOSTNAME.ts.net:8789/ws` → daemon WebSocket on `127.0.0.1:8789/ws`

The command prints a setup URL and, when the optional QR renderer is installed,
a terminal QR code. The command changes only Tailscale Serve ports 8789 and
8790; it does not reset unrelated Serve routes.

## Phone setup

1. Install Tailscale on the phone and join the same tailnet.
2. Install the AMO-signed Sleeper add-on in Firefox for Android.
3. Scan the QR code from `sleeper mobile setup`, or open its setup URL in
   Firefox.
4. Sleeper verifies the daemon, saves the HTTPS/WSS endpoints in the browser
   profile, and opens its connection settings.

The setup link is a secret: share it only with the intended browser. The
extension stores the bearer locally and uses it for authenticated `/tabs` and
WebSocket requests. Tailscale access controls still decide which users and
devices can reach the service.

## Operations

```bash
sleeper mobile status
sleeper mobile disable
```

`status` reports the tailnet hostname and current Serve configuration.
`disable` removes only Sleeper's HTTPS listeners on ports 8789 and 8790.

If setup reports that Tailscale is not connected, run `tailscale up`. If it
reports that HTTPS is unavailable, enable MagicDNS and HTTPS certificates in
the Tailscale admin console.

## Security invariants

- The daemon must remain loopback-only.
- Only Tailscale Serve may expose the daemon to another device.
- Plain LAN HTTP/WS and direct daemon binding are rejected.
- Setup URLs must use HTTPS, port 8790, and a `.ts.net` hostname.
- Pairing succeeds only when the endpoint returns an authenticated `/tabs`
  response; a `.ts.net` page without the setup fragment cannot pair the add-on.

## Firefox Nightly Android development iteration

Safety note: `web-ext run` installs a temporary add-on using the manifest's
same ID. It is not safely coexistent with a persistent Sleeper installation:
the temporary install may replace that add-on and remove itself on exit. The
runner therefore refuses to start unless you explicitly pass
`--allow-persistent-replacement` after backing up or intentionally uninstalling
the persistent add-on. This workflow reloads source changes only; it is not a
production self-update channel, and add-on storage should be treated as
replaceable during the run.

For extension development, use the unpacked source with Mozilla's supported
`web-ext` Android target. First enable Firefox Nightly remote debugging and
Android USB or Wi-Fi debugging, then confirm the device is visible to ADB:

```bash
npm ci --ignore-scripts
adb devices
scripts/firefox-android-iterate.sh --adb-device SERIAL \
  --allow-persistent-replacement
```

The script runs:

```bash
node_modules/.bin/web-ext run --source-dir extension --target firefox-android \
  --adb-device SERIAL --firefox-apk org.mozilla.fenix
```

`web-ext run` installs the unpacked add-on temporarily into Firefox for
Android's main browser profile, watches `extension/`, and reloads the add-on
after source changes. Because it uses the manifest ID, it can replace a
the persistent AMO Sleeper add-on with that same ID; when the run exits, the
temporary add-on may be removed and the persistent add-on may not be restored.
Back up or intentionally uninstall the persistent add-on before using the
explicit replacement acknowledgement above. This workflow does not change
the production version or provide a self-update channel. Browser profile data
outside the add-on is retained, but add-on storage must be treated as
replaceable. Keep the debugger and ADB connection alive until cleanup.

When more than one device is connected, `--adb-device` is mandatory. The
package defaults to Nightly (`org.mozilla.fenix`); set `FIREFOX_APK` or pass
`--firefox-apk` for another Firefox channel. `--dry-run` validates device
selection and prints the exact command without installing anything:

```bash
scripts/firefox-android-iterate.sh --dry-run --adb-device SERIAL
```

### Updates versus development reloads

Firefox does not treat a locally built unsigned XPI as a production update.
Persistent add-on updates require a signed package and an update manifest (or
distribution through AMO); this repository deliberately has no `update_url`.
For local iteration, `web-ext run` and its Gecko remote-debugger install/reload
protocol are the supported mechanism. Build `build/sleeper.xpi` for a manual
package check, or use the AMO-signed artifact described in
[`firefox-signing.md`](firefox-signing.md) for persistent installation.

References: [Firefox for Android extension development](https://extensionworkshop.com/documentation/develop/developing-extensions-for-firefox-for-android/)
and the [`web-ext run` command reference](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/).
