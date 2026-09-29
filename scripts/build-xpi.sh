#!/usr/bin/env bash
# build-xpi.sh — package the Sleeper extension as an .xpi for
# manual install/update in Firefox.
#
# The version is read from manifest.json. Release builds are reproducible:
# source mtimes and local build counters never affect the package version.
#
# Output: build/sleeper.xpi under this checkout.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/extension"
OUT="$ROOT/build"
mkdir -p "$OUT"

for tool in jq zip; do
  command -v "$tool" >/dev/null 2>&1 || \
    { echo "build-xpi.sh: missing dependency '$tool' - on Debian/Ubuntu: sudo apt install -y $tool" >&2; exit 127; }
done

VER="$(jq -r '.version' "$SRC/manifest.json")"
[ -n "$VER" ] && [ "$VER" != "null" ] || { echo "manifest.json has no version" >&2; exit 1; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

cp "$SRC/action-labels.js" "$STAGE/"
cp "$SRC/api_host_policy.js" "$SRC/screenshot.js" "$SRC/background_tabs.js" "$SRC/action-state.js" "$SRC/background_network.js" "$SRC/background_page_hooks.js" "$SRC/daemon_endpoint.js" "$SRC/mobile_onboarding.js" "$SRC/tailscale_setup.js" "$SRC/background.js" "$SRC/content.js" "$SRC/locators.js" "$SRC/activity.js" "$SRC/sleeper.js" \
   "$SRC/popup.html" "$SRC/popup.css" "$SRC/popup.js" \
  "$SRC/options.html" "$SRC/options.css" "$SRC/options.js" "$SRC/icon.svg" "$SRC/icon-active.svg" "$STAGE/"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$STAGE/"
for ic in icon.png icon16.png icon32.png icon48.png icon128.png \
          icon-active.png icon-active16.png icon-active32.png icon-active128.png; do
  [ -f "$SRC/$ic" ] && cp "$SRC/$ic" "$STAGE/"
done
jq --arg v "$VER" '.version = $v' "$SRC/manifest.json" > "$STAGE/manifest.json"

# Source identity (issue #20): a same-version dev package must be
# distinguishable from a stale one. COMMIT is the packaging git commit when
# available; CONTENT is a digest over exactly the files that go into the
# package, so two builds from identical sources always agree.
COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
CONTENT="$(cd "$STAGE" && find . -type f ! -name SOURCE_ID -print | LC_ALL=C sort | \
  xargs -d '\n' sha256sum 2>/dev/null | sed 's/  .\// /' | \
  python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])')"
printf 'commit=%s\ncontent=%s\nversion=%s\n' "$COMMIT" "$CONTENT" "$VER" > "$STAGE/SOURCE_ID"

(cd "$STAGE" && find . -type f -exec touch -h -d '2000-01-01 00:00:00 UTC' {} + && \
  find . -type f -print | LC_ALL=C sort | zip -q -X "$OUT/.sleeper.xpi.tmp" -@)
mv "$OUT/.sleeper.xpi.tmp" "$OUT/sleeper.xpi"

SHA256="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$OUT/sleeper.xpi")"
echo "built $OUT/sleeper.xpi version $VER source $COMMIT/$CONTENT sha256 $SHA256"
