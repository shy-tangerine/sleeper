import json
import shutil
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.install_plugins import install_plugins, uninstall_plugins, _registered_marketplace_matches


def test_install_plugins_copies_then_registers_only_successful_clients(tmp_path, monkeypatch):
    source = tmp_path / "source"
    package = source / "plugins/codex/sleeper"
    (package / ".codex-plugin").mkdir(parents=True)
    (package / "skills/sleeper/references").mkdir(parents=True)
    (package / ".codex-plugin/plugin.json").write_text("{}")
    (package / ".mcp.json").write_text('{"mcpServers":{"sleeper":{"command":"sleeper-mcp"}}}')
    (package / "skills/sleeper/SKILL.md").write_text("canonical")
    (package / "skills/sleeper/references/setup.md").write_text("setup")
    calls = []
    monkeypatch.setattr("scripts.install_plugins.shutil.which", lambda client: "/fake/" + client if client == "codex" else None)
    monkeypatch.setattr("scripts.install_plugins._run", lambda command: calls.append(command) or True)
    installed = install_plugins(source, tmp_path / "managed", ["codex", "claude"], "/custom/sleeper-mcp")
    assert installed == {"codex"}
    assert len(calls) == 2
    assert (tmp_path / "managed/marketplaces/codex/plugins/sleeper/.sleeper-managed").is_file()
    status = json.loads((tmp_path / "managed/.sleeper-native-plugins.json").read_text())
    assert status["installed"] == ["codex"]
    assert status["pending"] == ["claude"]
    assert "claude" in status["errors"]


def test_uninstall_only_removes_marked_managed_adapter(tmp_path, monkeypatch):
    managed = tmp_path / "managed/marketplaces/codex/plugins/sleeper"
    managed.mkdir(parents=True)
    (managed / ".sleeper-managed").write_text("Sleeper native plugin")
    calls = []
    monkeypatch.setattr("scripts.install_plugins.shutil.which", lambda client: "/fake/" + client)
    monkeypatch.setattr("scripts.install_plugins._run", lambda command: calls.append(command) or True)
    monkeypatch.setattr("scripts.install_plugins._registered_marketplace_matches", lambda executable, root: True)
    assert uninstall_plugins(tmp_path / "managed", ["codex"]) == {"codex"}
    assert not (tmp_path / "managed/marketplaces/codex").exists()
    assert calls[0][-3:] == ["sleeper", "--marketplace", "sleeper-local"]
    assert calls[1][-2:] == ["remove", "sleeper-local"]


def test_unmarked_package_is_never_overwritten_or_removed(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source = source_root / "plugins/codex/sleeper"
    source.mkdir(parents=True)
    target = tmp_path / "managed/marketplaces/codex/plugins/sleeper"
    target.mkdir(parents=True)
    (target / "user-file").write_text("keep")
    monkeypatch.setattr("scripts.install_plugins.shutil.which", lambda client: "/fake/" + client)
    monkeypatch.setattr("scripts.install_plugins._run", lambda command: (_ for _ in ()).throw(AssertionError("CLI must not run")))
    import pytest
    with pytest.raises(RuntimeError, match="unmarked"):
        install_plugins(tmp_path / "source", tmp_path / "managed", ["codex"])
    assert uninstall_plugins(tmp_path / "managed", ["codex"]) == set()
    assert (target / "user-file").read_text() == "keep"


def test_plugin_install_refuses_symlink_destination(tmp_path, monkeypatch):
    source = tmp_path / "source/plugins/codex/sleeper"
    source.mkdir(parents=True)
    (source / ".mcp.json").write_text('{"mcpServers":{"sleeper":{"command":"sleeper-mcp"}}}')
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "managed/marketplaces/codex/plugins/sleeper"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr("scripts.install_plugins.shutil.which", lambda client: "/fake/" + client)
    with pytest.raises(RuntimeError, match="symlink plugin destination"):
        install_plugins(tmp_path / "source", tmp_path / "managed", ["codex"])


def test_marketplace_marker_does_not_claim_external_registration(tmp_path, monkeypatch):
    import scripts.install_plugins as installer
    executable = "/fake/codex"
    market_root = tmp_path / "marketplaces/codex"
    result = type("Result", (), {"returncode": 0, "stdout": json.dumps({
        "marketplaces": [{"name": "sleeper-local", "path": str(tmp_path / "other")}]
    })})()
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: result)
    assert _registered_marketplace_matches(executable, market_root) is False


def test_marketplace_source_name_must_match_same_record(tmp_path, monkeypatch):
    import scripts.install_plugins as installer
    market_root = tmp_path / "marketplaces/codex"
    state = {"marketplaces": [
        {"name": "sleeper-local", "path": str(tmp_path / "other")},
        {"name": "unrelated", "path": str(market_root)},
    ]}
    result = type("Result", (), {"returncode": 0, "stdout": json.dumps(state)})()
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: result)
    assert _registered_marketplace_matches("/fake/codex", market_root) is False


def test_marketplace_source_path_normalizes_windows_form(tmp_path, monkeypatch):
    import scripts.install_plugins as installer
    market_root = tmp_path / "marketplaces/codex"
    windows_path = str(market_root).replace("/", "\\").upper()
    result = type("Result", (), {"returncode": 0, "stdout": json.dumps(
        {"marketplaces": [{"name": "sleeper-local", "source": {"path": windows_path}}]}
    )})()
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: result)
    assert _registered_marketplace_matches("/fake/codex", market_root) is True


def test_install_recovers_registration_when_marker_is_stale(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source = source_root / "plugins/codex/sleeper"
    source.mkdir(parents=True)
    (source / ".mcp.json").write_text('{"mcpServers":{"sleeper":{"command":"sleeper-mcp"}}}')
    managed = tmp_path / "managed/marketplaces/codex"
    (managed / "plugins/sleeper").mkdir(parents=True)
    (managed / "plugins/sleeper/.sleeper-managed").write_text("Sleeper native plugin\n")
    calls = []
    monkeypatch.setattr("scripts.install_plugins.shutil.which", lambda client: "/fake/" + client)
    monkeypatch.setattr("scripts.install_plugins._run", lambda command: calls.append(command) or len(calls) > 1)
    monkeypatch.setattr("scripts.install_plugins._registered_marketplace_matches", lambda executable, root: True)
    assert install_plugins(source_root, tmp_path / "managed", ["codex"]) == {"codex"}
    assert calls[0][3:5] == ["add", str(tmp_path / "managed/marketplaces/codex")]


def test_codex_local_install_round_trip_in_isolated_home(tmp_path, monkeypatch):
    codex = shutil.which("codex")
    if not codex:
        import pytest
        pytest.skip("codex CLI unavailable")
    isolated_home = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    isolated_home.mkdir()
    codex_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    from scripts.install_plugins import install_plugins, uninstall_plugins
    destination = tmp_path / "managed"
    assert install_plugins(Path(__file__).resolve().parents[1], destination, ["codex"]) == {"codex"}
    assert install_plugins(Path(__file__).resolve().parents[1], destination, ["codex"]) == {"codex"}
    assert uninstall_plugins(destination, ["codex"]) == {"codex"}
    assert not (destination / "marketplaces/codex").exists()
