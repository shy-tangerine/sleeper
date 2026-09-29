#!/usr/bin/env bash
# Submit Sleeper to AMO's unlisted signing service and keep only its signed XPI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${SLEEPER_FIREFOX_ARTIFACT_DIR:-$ROOT/build}"
ARTIFACTS="$(mktemp -d)"
SOURCE="$(mktemp -d)"
trap 'rm -rf "$ARTIFACTS" "$SOURCE"' EXIT

: "${AMO_JWT_ISSUER:?AMO_JWT_ISSUER is required (AMO Developer Hub API key / JWT issuer)}"
: "${AMO_JWT_SECRET:?AMO_JWT_SECRET is required (AMO Developer Hub API secret)}"
WEB_EXT="${SLEEPER_WEB_EXT:-$ROOT/node_modules/.bin/web-ext}"
[ -x "$WEB_EXT" ] || { echo "pinned web-ext is not installed; run npm ci --ignore-scripts" >&2; exit 1; }

mkdir -p "$OUT"
"$ROOT/scripts/build-xpi.sh"
unzip -q "$ROOT/build/sleeper.xpi" -d "$SOURCE"
"$WEB_EXT" sign \
  --source-dir "$SOURCE" \
  --artifacts-dir "$ARTIFACTS" \
  --channel unlisted \
  --api-key "$AMO_JWT_ISSUER" \
  --api-secret "$AMO_JWT_SECRET"
unset AMO_JWT_ISSUER AMO_JWT_SECRET

signed_xpi="$(find "$ARTIFACTS" -maxdepth 1 -type f -name '*.xpi' -print -quit)"
[ -n "$signed_xpi" ] || { echo "AMO signing completed without a signed XPI" >&2; exit 1; }
cp "$signed_xpi" "$OUT/sleeper-firefox.xpi"
echo "signed Firefox package: $OUT/sleeper-firefox.xpi"
