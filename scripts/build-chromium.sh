#!/usr/bin/env bash
# Build the Chromium MV3 package for manual installation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/extension"
OUT="$ROOT/build"
mkdir -p "$OUT"

version="$(jq -r '.version' "$SRC/manifest.chromium.json")"
[ -n "$version" ] && [ "$version" != "null" ] || { echo "manifest.chromium.json has no version" >&2; exit 1; }

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

cp "$SRC/manifest.chromium.json" "$stage/manifest.json"
cp "$SRC/action-labels.js" "$stage/"
cp "$SRC/api_host_policy.js" "$SRC/screenshot.js" "$SRC/background_tabs.js" "$SRC/action-state.js" "$SRC/background_network.js" "$SRC/background_page_hooks.js" "$SRC/daemon_endpoint.js" "$SRC/mobile_onboarding.js" "$SRC/tailscale_setup.js" "$SRC/debugger_eval.js" "$SRC/background.js" "$SRC/content.js" "$SRC/locators.js" "$SRC/activity.js" "$SRC/sleeper.js" "$SRC/dynamic_code.js" \
  "$SRC/popup.html" "$SRC/popup.css" "$SRC/popup.js" \
  "$SRC/options.html" "$SRC/options.css" "$SRC/options.js" "$SRC/icon.svg" "$SRC/icon-active.svg" "$stage/"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$stage/"
for icon in icon.png icon16.png icon32.png icon48.png icon128.png \
  icon-active.png icon-active16.png icon-active32.png icon-active128.png; do
  [ -f "$SRC/$icon" ] && cp "$SRC/$icon" "$stage/"
done

jq --arg v "$version" '.version = $v' "$stage/manifest.json" > "$stage/manifest.tmp"
mv "$stage/manifest.tmp" "$stage/manifest.json"

# Source identity (issue #20): see scripts/build-xpi.sh.
COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
CONTENT="$(cd "$stage" && find . -type f ! -name SOURCE_ID -print | LC_ALL=C sort | \
  xargs -d '\n' sha256sum 2>/dev/null | sed 's/  .\// /' | \
  python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])')"
printf 'commit=%s\ncontent=%s\nversion=%s\n' "$COMMIT" "$CONTENT" "$version" > "$stage/SOURCE_ID"

(cd "$stage" && find . -type f -exec touch -h -d '2000-01-01 00:00:00 UTC' {} + && \
  find . -type f -print | LC_ALL=C sort | zip -q -X "$OUT/.sleeper-chromium.zip.tmp" -@)
mv "$OUT/.sleeper-chromium.zip.tmp" "$OUT/sleeper-chromium.zip"
echo "built $OUT/sleeper-chromium.zip version $version source $COMMIT/$CONTENT"
