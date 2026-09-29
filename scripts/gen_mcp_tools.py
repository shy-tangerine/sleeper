#!/usr/bin/env python3
"""Regenerate docs/mcp-tools.json from the canonical mcp_server.TOOLS list.

docs/mcp-tools.json is a generated artifact, not a hand-edited file. The
single source of truth for the MCP tool inventory is
daemon/mcp_server.py::TOOLS; run this script whenever TOOLS changes and
commit the result. test_docs.py enforces byte-equality against TOOLS, so a
stale regeneration fails CI exactly like any other contract drift.

Usage: python3 scripts/gen_mcp_tools.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))

import mcp_server  # noqa: E402  (path set above)


def main() -> int:
    target = ROOT / "docs" / "mcp-tools.json"
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    after = mcp_server.dump_tools_json()
    if before == after:
        print(f"docs/mcp-tools.json already up to date ({len(mcp_server.TOOLS)} tools)")
        return 0
    target.write_text(after, encoding="utf-8")
    print(f"docs/mcp-tools.json regenerated ({len(mcp_server.TOOLS)} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
