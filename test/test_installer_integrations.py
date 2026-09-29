import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run_installer(env, *flags):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/install.py"), "--no-build", "--no-service", "--no-open", "--no-deps", *flags],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )

def test_codex_plugin_install_is_idempotent_and_deduplicates(tmp_path):
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o755)
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[mcp_servers.sleeper]\ncommand = ' + json.dumps(str(home / "local-bin/sleeper-mcp")) + '\n\n[mcp_servers.custom]\ncommand = "keep"\n')
    env = os.environ.copy()
    env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(home / ".codex"), PATH=f"{fake_bin}:{env['PATH']}",
               SLEEPER_DATA_DIR=str(home / "data"), SLEEPER_BIN_DIR=str(home / "local-bin"), SLEEPER_CODEX_CONFIG=str(config),
               SLEEPER_SKILL_DIR=str(home / ".agents" / "skills" / "sleeper"))
    first = run_installer(env, "--plugins", "codex", "--non-interactive")
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result["plugins"] == ["codex"]
    assert not (home / ".agents" / "skills" / "sleeper").exists()
    assert "mcp_servers.sleeper" in config.read_text()
    assert "mcp_servers.custom" in config.read_text()
    second = run_installer(env, "--plugins", "codex", "--non-interactive")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["plugins"] == ["codex"]

def test_selection_modes_and_yes_exclusions(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sleeper_install", ROOT / "scripts" / "install.py")
    install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(install)
    from argparse import Namespace
    yes = Namespace(yes=True, no_mcp=False, no_skill=False, no_plugins=False, plugins=None, non_interactive=False)
    assert install.choose_integrations(yes) == {"mcp": True, "skill": False, "plugins": ["codex", "claude"]}
    excluded = Namespace(yes=True, no_mcp=True, no_skill=True, no_plugins=True, plugins=None, non_interactive=False)
    assert install.choose_integrations(excluded) == {"mcp": False, "skill": False, "plugins": []}
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["2", "n", "y", "y", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    custom = Namespace(yes=False, no_mcp=False, no_skill=False, no_plugins=False, plugins=None, non_interactive=False)
    assert install.choose_integrations(custom) == {"mcp": False, "skill": True, "plugins": ["codex"]}

def _plugin_env(tmp_path, skill_dir):
    home, fake_bin = tmp_path / "home", tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n"); codex.chmod(0o755)
    config = home / ".codex" / "config.toml"; config.parent.mkdir(parents=True)
    config.write_text("")
    env = os.environ.copy()
    env.update(HOME=str(home), USERPROFILE=str(home), PATH=f"{fake_bin}:{env['PATH']}",
               SLEEPER_DATA_DIR=str(home / "data"), SLEEPER_BIN_DIR=str(home / "bin"),
               SLEEPER_CODEX_CONFIG=str(config), SLEEPER_SKILL_DIR=str(skill_dir))
    return env, skill_dir

def test_plugin_migration_removes_matching_managed_skill(tmp_path):
    skill_dir = tmp_path / "home" / ".agents" / "skills" / "sleeper"
    import shutil
    shutil.copytree(ROOT / "skills" / "sleeper", skill_dir)
    (skill_dir / ".sleeper-managed").write_text("Sleeper managed skill\n")
    env, _ = _plugin_env(tmp_path, skill_dir)
    result = run_installer(env, "--plugins", "codex", "--non-interactive")
    assert result.returncode == 0, result.stderr
    assert not skill_dir.exists()

def test_plugin_migration_preserves_modified_managed_skill(tmp_path):
    skill_dir = tmp_path / "home" / ".agents" / "skills" / "sleeper"
    import shutil
    shutil.copytree(ROOT / "skills" / "sleeper", skill_dir)
    (skill_dir / "SKILL.md").write_text((skill_dir / "SKILL.md").read_text() + "\nCustom note\n")
    (skill_dir / ".sleeper-managed").write_text("Sleeper managed skill\n")
    env, _ = _plugin_env(tmp_path, skill_dir)
    result = run_installer(env, "--plugins", "codex", "--non-interactive")
    assert result.returncode == 0, result.stderr
    assert skill_dir.exists()
    assert "Custom note" in (skill_dir / "SKILL.md").read_text()

def test_missing_plugin_client_is_reported_pending(tmp_path):
    env, _ = _plugin_env(tmp_path, tmp_path / "home" / ".agents" / "skills" / "sleeper")
    env["PATH"] = str(tmp_path / "bin")
    result = run_installer(env, "--plugins", "claude", "--non-interactive")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["plugins"] == []
    assert "claude" in payload["plugins_pending"]
