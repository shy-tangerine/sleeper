import json
import os
import shutil
import sys
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_installer(home, data, bindir, config):
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        SLEEPER_SKILL_DIR=str(home / "skills/sleeper"),
        SLEEPER_DATA_DIR=str(data),
        SLEEPER_BIN_DIR=str(bindir),
        SLEEPER_CODEX_CONFIG=str(config),
    )
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/install.py"), "--no-build", "--no-service", "--no-open", "--no-deps"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )


def test_install_is_idempotent_and_preserves_existing_mcp_config(tmp_path):
    home = tmp_path / "home with spaces"
    data = home / "data"
    bindir = home / "bin"
    config = home / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[other]\nvalue = "keep-me"\n')

    first = run_installer(home, data, bindir, config)
    second = run_installer(home, data, bindir, config)
    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    merged = config.read_text()
    assert '[other]\nvalue = "keep-me"' in merged
    assert "[mcp_servers.sleeper]" in merged
    launcher = bindir / ("sleeper.cmd" if os.name == "nt" else "sleeper")
    assert launcher.is_file() if os.name == "nt" else launcher.is_symlink()
    mcp_launcher = bindir / ("sleeper-mcp.cmd" if os.name == "nt" else "sleeper-mcp")
    assert mcp_launcher.is_file()
    assert ".sleeper-managed-mcp" in mcp_launcher.read_text()
    assert (data / "sleeper/daemon/daemon.py").is_file()
    assert (data / "sleeper/pyproject.toml").is_file()
    assert (data / "sleeper/uv.lock").is_file()
    native_host = home / ".mozilla/native-messaging-hosts/com.shy_tangerine.sleeper.json"
    host_manifest = json.loads(native_host.read_text())
    assert host_manifest["name"] == "com.shy_tangerine.sleeper"
    assert host_manifest["allowed_extensions"] == ["sleeper@shy-tangerine"]
    assert host_manifest["path"] == str(data / "sleeper/daemon/native_messaging_host")
    assert os.access(host_manifest["path"], os.X_OK)
    assert json.loads(second.stdout)["ok"] is True


def test_uninstall_removes_only_sleeper_state(tmp_path):
    home = tmp_path / "home"
    data = home / "data"
    bindir = home / "bin"
    config = home / "config.toml"
    result = run_installer(home, data, bindir, config)
    assert result.returncode == 0
    config.write_text(config.read_text() + '[other]\nvalue = "keep-me"\n')

    env = os.environ.copy()
    env.update(HOME=str(home),
        USERPROFILE=str(home),
        SLEEPER_SKILL_DIR=str(home / "skills/sleeper"), SLEEPER_DATA_DIR=str(data), SLEEPER_BIN_DIR=str(bindir), SLEEPER_CODEX_CONFIG=str(config))
    removed = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"), "uninstall"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert removed.returncode == 0
    final = config.read_text()
    assert "[mcp_servers.sleeper]" not in final
    assert '[other]\nvalue = "keep-me"' in final
    assert not (data / "sleeper").exists()
    assert not (bindir / "sleeper").exists()
    assert not (home / ".mozilla/native-messaging-hosts/com.shy_tangerine.sleeper.json").exists()


def test_codex_config_preserves_tables_and_quoted_paths(tmp_path):
    import tomllib

    home = tmp_path / 'home "quoted" \\ path'
    data, bindir, config = home / "data", home / "bin", home / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[before]\nvalue = "first"\n[mcp_servers.sleeper]\ncommand = "old"\n  [after]\nvalue = "last"\n')
    for _ in range(2):
        result = run_installer(home, data, bindir, config)
        assert result.returncode == 0, result.stderr
        parsed = tomllib.loads(config.read_text())
        assert parsed["before"]["value"] == "first"
        assert parsed["after"]["value"] == "last"
        assert parsed["mcp_servers"]["sleeper"]["command"] == str(data / "sleeper" / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python"))
        assert parsed["mcp_servers"]["sleeper"]["args"] == [str(data / "sleeper/daemon/mcp_server.py")]
def test_managed_dedup_preserves_custom_entries(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sleeper_install", ROOT / "scripts/install.py")
    install = importlib.util.module_from_spec(spec); spec.loader.exec_module(install)
    home = tmp_path / "home"
    data = home / "data"
    config = home / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[mcp_servers.sleeper]\ncommand = "python"\nargs = [' + json.dumps(str(data / "sleeper/daemon/mcp_server.py")) + ']\n\n[mcp_servers.custom]\ncommand = "my-mcp"\n')
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home)); monkeypatch.setenv("SLEEPER_DATA_DIR", str(data))
    install.remove_managed_codex_config(config)
    text = config.read_text()
    assert "mcp_servers.sleeper" in text
    assert "mcp_servers.custom" in text


def test_uninstall_preserves_modified_managed_skill(tmp_path):
    home = tmp_path / "home"
    data = home / "data"
    bindir = home / "bin"
    config = home / "config.toml"
    result = run_installer(home, data, bindir, config)
    assert result.returncode == 0, result.stderr
    skill = home / "skills/sleeper"
    (skill / "SKILL.md").write_text((skill / "SKILL.md").read_text() + "\nCustom note\n")
    env = os.environ.copy()
    env.update(HOME=str(home), USERPROFILE=str(home), SLEEPER_SKILL_DIR=str(skill),
               SLEEPER_DATA_DIR=str(data), SLEEPER_BIN_DIR=str(bindir), SLEEPER_CODEX_CONFIG=str(config))
    removed = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"), "uninstall"],
                             cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert removed.returncode == 0, removed.stderr
    assert skill.exists()
    assert not (data / "sleeper").exists()


def test_linux_service_is_accepted_by_systemd(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("sleeper_install_service", ROOT / "scripts/install.py")
    assert spec and spec.loader
    install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(install)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SLEEPER_VENV_DIR", str(tmp_path / "runtime/venv"))
    monkeypatch.setattr(install.shutil, "which", lambda name: None if name == "systemctl" else shutil.which(name))

    runtime = tmp_path / "runtime"
    python = runtime / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    (runtime / "daemon").mkdir()
    (runtime / "daemon/daemon.py").touch()

    service = install.install_service(ROOT, runtime)
    verified = subprocess.run(
        ["systemd-analyze", "--user", "verify", str(service)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode == 0, verified.stderr
    assert "Restart=always" in service.read_text(encoding="utf-8")
