"""Serve the daemon token only to Firefox's allow-listed Sleeper add-on."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daemon.daemon import _read_existing_token


def main() -> int:
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) != 4:
        return 1
    (length,) = struct.unpack("<I", raw_length)
    if length > 1024:
        return 1
    raw_request = sys.stdin.buffer.read(length)
    if len(raw_request) != length:
        return 1
    try:
        request = json.loads(raw_request)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 1
    if request != {"type": "get_daemon_token"}:
        return 1

    response = json.dumps({"token": _read_existing_token() or ""}, separators=(",", ":")).encode()
    sys.stdout.buffer.write(struct.pack("<I", len(response)) + response)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
