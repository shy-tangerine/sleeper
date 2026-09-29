#!/usr/bin/env python3
"""Generate the Claude Code and Codex Sleeper plugin adapters.

The repository skill is the source of truth; generated plugins only package it
with each client's manifest and MCP launcher declaration.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "sleeper" / "SKILL.md"
DESCRIPTION = "Inspect and control an existing local browser session through Sleeper MCP tools."
VERSION = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def build() -> None:
    for client, manifest_dir in (("claude", ".claude-plugin"), ("codex", ".codex-plugin")):
        target = ROOT / "plugins" / client / "sleeper"
        if target.exists():
            shutil.rmtree(target)
        (target / "skills" / "sleeper").mkdir(parents=True)
        shutil.copytree(SKILL.parent, target / "skills" / "sleeper", dirs_exist_ok=True)
        (target / "assets").mkdir(exist_ok=True)
        shutil.copy2(ROOT / "extension/icon-active.svg", target / "assets/icon.svg")
        manifest = {
            "name": "sleeper",
            "description": DESCRIPTION,
            "version": VERSION,
            "author": {"name": "Shy Tangerine"},
            "repository": "https://github.com/shy-tangerine/Sleeper",
            "homepage": "https://github.com/shy-tangerine/Sleeper",
            "license": "MIT",
        }
        if client == "codex":
            manifest["skills"] = "./skills/"
            manifest["mcpServers"] = "./.mcp.json"
            manifest["interface"] = {"displayName": "Sleeper", "shortDescription": "Control a local browser session", "longDescription": DESCRIPTION, "developerName": "Shy Tangerine", "category": "Productivity", "capabilities": ["Interactive"], "defaultPrompt": ["Inspect the current browser session"]}
        if client == "codex":
            manifest["interface"].update({"websiteURL": "https://github.com/shy-tangerine/Sleeper", "composerIcon": "./assets/icon.svg", "logo": "./assets/icon.svg", "logoDark": "./assets/icon.svg"})
        write_json(target / manifest_dir / "plugin.json", manifest)
        write_json(target / ".mcp.json", {"mcpServers": {"sleeper": {"command": "sleeper-mcp"}}})

    write_json(ROOT / "plugins" / "claude" / ".claude-plugin" / "marketplace.json", {
        "name": "sleeper",
        "owner": {"name": "Shy Tangerine"},
        "plugins": [{"name": "sleeper", "source": "./sleeper"}],
    })
    write_json(ROOT / ".claude-plugin" / "marketplace.json", {
        "name": "sleeper",
        "owner": {"name": "Shy Tangerine"},
        "plugins": [{"name": "sleeper", "source": "./plugins/claude/sleeper"}],
    })
    write_json(ROOT / ".agents" / "plugins" / "marketplace.json", {
        "name": "sleeper-local",
        "interface": {"displayName": "Sleeper"},
        "plugins": [{"name": "sleeper", "source": {"source": "local", "path": "./plugins/codex/sleeper"}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}],
    })


def validate() -> None:
    if not SKILL.is_file():
        raise SystemExit(f"missing canonical skill: {SKILL}")
    canonical = SKILL.read_bytes()
    for client, manifest_dir in (("claude", ".claude-plugin"), ("codex", ".codex-plugin")):
        target = ROOT / "plugins" / client / "sleeper"
        packaged_skill = target / "skills" / "sleeper"
        canonical_files = {p.relative_to(SKILL.parent) for p in SKILL.parent.rglob("*") if p.is_file()}
        packaged_files = {p.relative_to(packaged_skill) for p in packaged_skill.rglob("*") if p.is_file()}
        if packaged_files != canonical_files:
            raise SystemExit(f"{client} skill file set drifted from canonical source")
        for relative_path in canonical_files:
            if (packaged_skill / relative_path).read_bytes() != (SKILL.parent / relative_path).read_bytes():
                raise SystemExit(f"{client} skill drifted from canonical source: {relative_path}")
        manifest = json.loads((target / manifest_dir / "plugin.json").read_text())
        if manifest.get("name") != "sleeper" or manifest.get("version") != VERSION or not (target / ".mcp.json").is_file():
            raise SystemExit(f"invalid {client} plugin adapter")
    print("native plugin validation: ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "validate"))
    args = parser.parse_args()
    (build if args.command == "build" else validate)()
