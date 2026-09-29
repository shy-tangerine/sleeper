#!/usr/bin/env bash
# Run the unpacked extension in Firefox for Android Nightly and reload it on
# source changes. This is a development install; it is not an update channel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB_BIN="${ADB_BIN:-adb}"
FIREFOX_APK="${FIREFOX_APK:-org.mozilla.fenix}"
WEB_EXT_BIN="${WEB_EXT_BIN:-$ROOT/node_modules/.bin/web-ext}"
DEVICE="${ADB_DEVICE:-}"
DRY_RUN=0
ALLOW_PERSISTENT_REPLACEMENT=0

usage() {
  cat <<'EOF'
Usage: scripts/firefox-android-iterate.sh [options]

Run the unpacked extension in Firefox for Android Nightly. web-ext watches
extension/ and reloads the temporary development install after each change.

Options:
  --adb-device SERIAL  select one device (required when more than one is found)
  --firefox-apk ID     Android package (default: org.mozilla.fenix)
  --allow-persistent-replacement
                        acknowledge that web-ext may replace the same-ID
                        persistent Sleeper install on this device
  --dry-run            print checks and the command without starting web-ext
  -h, --help           show this help

Environment: ADB_BIN, ADB_DEVICE, FIREFOX_APK, WEB_EXT_BIN. The default
web-ext executable is installed from the repository lockfile with
`npm ci --ignore-scripts`.
EOF
}

while (($#)); do
  case "$1" in
    --adb-device) (($# >= 2)) || { echo "--adb-device needs a value" >&2; exit 2; }; DEVICE="$2"; shift 2 ;;
    --firefox-apk) (($# >= 2)) || { echo "--firefox-apk needs a value" >&2; exit 2; }; FIREFOX_APK="$2"; shift 2 ;;
    --allow-persistent-replacement) ALLOW_PERSISTENT_REPLACEMENT=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -x "$(command -v "$ADB_BIN" 2>/dev/null || true)" ] || {
  echo "ADB executable not found: $ADB_BIN" >&2; exit 1;
}
[ -f "$ROOT/extension/manifest.json" ] || { echo "missing extension/manifest.json" >&2; exit 1; }

mapfile -t devices < <("$ADB_BIN" devices | awk 'NR > 1 && $2 == "device" { print $1 }')
if [[ -n "$DEVICE" ]]; then
  printf '%s\n' "${devices[@]}" | grep -Fxq "$DEVICE" || {
    echo "ADB device is not connected and ready: $DEVICE" >&2
    echo "Connected ready devices: ${devices[*]:-(none)}" >&2
    exit 1
  }
elif ((${#devices[@]} == 1)); then
  DEVICE="${devices[0]}"
elif ((${#devices[@]} == 0)); then
  echo "No ready ADB device found; enable USB/Wi-Fi debugging and retry" >&2
  exit 1
else
  echo "Multiple ADB devices found; pass --adb-device SERIAL: ${devices[*]}" >&2
  exit 2
fi

[[ -x "$WEB_EXT_BIN" ]] || { echo "pinned web-ext is not installed; run npm ci --ignore-scripts" >&2; exit 1; }
web_ext_cmd=("$WEB_EXT_BIN")
command=("${web_ext_cmd[@]}" run --source-dir "$ROOT/extension" --target firefox-android --adb-device "$DEVICE" --firefox-apk "$FIREFOX_APK")
echo "Firefox Android development install: device=$DEVICE apk=$FIREFOX_APK"
echo "This uses web-ext's temporary install and file watcher; Ctrl-C cleans up when the debugger remains connected."
if ((DRY_RUN)); then
  printf 'command:'; printf ' %q' "${command[@]}"; printf '\n'
  exit 0
fi
if (( ! ALLOW_PERSISTENT_REPLACEMENT )); then
  cat >&2 <<'EOF'
Refusing to start: Firefox Android temporary installs use the extension's
manifest ID and can replace/remove a persistent Sleeper install when web-ext
exits. Uninstall or back up the persistent install first, then re-run with
--allow-persistent-replacement if replacing it is intentional.
EOF
  exit 3
fi
exec "${command[@]}"
