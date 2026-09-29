#!/usr/bin/env bash
set -euo pipefail
SOURCE="${0}"
ROOT="$(cd "$(dirname "${SOURCE:-.}")" && pwd)"
if [ ! -f "$ROOT/scripts/install.py" ]; then
  BOOTSTRAP_DIR="${SLEEPER_SOURCE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/sleeper-source}"
  REPO="${SLEEPER_BOOTSTRAP_REPO:-https://github.com/shy-tangerine/Sleeper.git}"
  if [ ! -d "$BOOTSTRAP_DIR/.git" ]; then
    mkdir -p "$(dirname "$BOOTSTRAP_DIR")"
    git clone "$REPO" "$BOOTSTRAP_DIR"
  else
    git -C "$BOOTSTRAP_DIR" pull --ff-only
  fi
  ROOT="$BOOTSTRAP_DIR"
fi
exec "${PYTHON:-python3}" "$ROOT/scripts/install.py" "$@"
