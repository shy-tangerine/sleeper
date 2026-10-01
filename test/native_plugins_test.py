import json
import os
import sys
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_plugin_generation_and_skill_parity():
    subprocess.run([sys.executable, str(ROOT / "scripts/build_native_plugins.py"), "build"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/build_native_plugins.py"), "validate"], cwd=ROOT, check=True)
    validator = os.environ.get("CODEX_PLUGIN_VALIDATOR")
    if validator and Path(validator).is_file():
        subprocess.run(["python3", validator, str(ROOT / "plugins/codex/sleeper")], cwd=ROOT, check=True)
    canonical = (ROOT / "plugins/codex/sleeper/skills/sleeper/SKILL.md").read_bytes()
    for client, manifest_dir in (("claude", ".claude-plugin"), ("codex", ".codex-plugin")):
        target = ROOT / "plugins" / client / "sleeper"
        assert json.loads((target / manifest_dir / "plugin.json").read_text())["name"] == "sleeper"
        assert json.loads((target / ".mcp.json").read_text())["mcpServers"]["sleeper"]["command"] == "sleeper-mcp"
        assert (target / "skills/sleeper/SKILL.md").read_bytes() == canonical
        assert (target / "skills/sleeper/references/setup.md").is_file()
        assert (target / "skills/sleeper/references/network.md").is_file()

    claude_marketplace = json.loads(
        (ROOT / ".claude-plugin/marketplace.json").read_text()
    )
    assert claude_marketplace["name"] == "sleeper"
    assert claude_marketplace["plugins"][0]["source"] == "./plugins/claude/sleeper"

    codex_marketplace = json.loads(
        (ROOT / ".agents/plugins/marketplace.json").read_text()
    )
    assert codex_marketplace["name"] == "sleeper-local"
    assert codex_marketplace["plugins"][0]["source"]["path"] == "./plugins/codex/sleeper"
