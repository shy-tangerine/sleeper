"""Portable installer and native CLI contracts that do not require those OSes."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import zipfile
import types
import pytest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


native = load_module("sleeper_native_cli_test", ROOT / "cli/sleeper.py")
installer = load_module("sleeper_installer_test", ROOT / "scripts/install.py")


def test_managed_manifest_cannot_escape_install_root(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir(); target.mkdir()
    (source / "current.txt").write_text("current")
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (target / ".sleeper-managed-files").write_text('["../victim.txt", "/absolute"]')
    installer._sync_managed_tree(source, target)
    assert victim.read_text() == "keep"
    assert (target / "current.txt").read_text() == "current"


def test_managed_tree_refuses_symlink_destination(tmp_path):
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir(); outside.mkdir()
    (source / "file").write_text("new")
    target = tmp_path / "target"
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink destination"):
        installer._sync_managed_tree(source, target)
    assert not (outside / "file").exists()


def test_native_cli_uses_top_level_tab_and_profile(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLEEPER_DRY_RUN", "1")
    monkeypatch.delenv("SLEEPER_PROFILE", raising=False)
    (tmp_path / ".sleeper-session").write_text("work\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "cli/sleeper.py"), "goto", "https://example.test", "--tab", "7"],
        text=True, capture_output=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["cmd"] == "goto"
    assert payload["args"] == {"url": "https://example.test"}
    assert payload["tab"] == "7"


def test_native_cli_maps_core_positional_commands():
    assert native.parse_payload(["type", "#email", "person@example.test"])["args"] == {
        "selector": "#email", "text": "person@example.test"
    }
    assert native.parse_payload(["click_text", "Continue"])["args"] == {"text": "Continue"}
    assert native.parse_payload(["tab", "new", "https://example.test"])["cmd"] == "newtab"
    assert native.parse_payload([
        "batch", '[{"cmd":"goto","args":{"url":"https://example.test"}}]',
    ]) == {
        "cmd": "batch",
        "args": {"actions": [{"cmd": "goto", "args": {"url": "https://example.test"}}]},
    }


def test_native_cli_matches_documented_core_commands():
    cases = [
        (["sessions"], "sessions", {}),
        (["state"], "state", {}),
        (["tabs"], "tabs", {}),
        (["goto", "https://example.com"], "goto", {"url": "https://example.com"}),
        (["find", "h1", "--limit", "5"], "find", {"selector": "h1", "limit": 5}),
        (["find", "--role", "button", "--name", "Save"], "find", {"role": "button", "name": "Save", "limit": 50}),
        (["click", "@sleeper-1"], "click", {"selector": "@sleeper-1"}),
        (["type", "input[name=q]", "example query", "--clear"], "type", {"selector": "input[name=q]", "text": "example query", "clear": True}),
        (["press", "Enter"], "press", {"key": "Enter"}),
        (["read", "h1"], "read", {"selector": "h1"}),
        (["read_all", ".result"], "readAll", {"selector": ".result"}),
        (["wait", ".loaded", "--timeout", "15000"], "waitFor", {"selector": ".loaded", "timeout": 15000}),
        (["extract", '{"title":"h1","items":".result"}'], "extract", {"map": {"title": "h1", "items": ".result"}}),
        (["snapshot"], "snapshot", {}),
        (["tab", "new", "https://example.com"], "newtab", {"url": "https://example.com"}),
        (["tab", "select", "0"], "selecttab", {"target": 0}),
        (["tab", "close", "0"], "closetab", {"target": 0}),
        (["wait", "download", "report.csv", "--timeout", "15000"], "waitDownload", {"pattern": "report.csv", "timeout_ms": 15000}),
        (["network", "--since=60"], "network", {"since": 60}),
        (["api", "/api/example", "--method", "GET"], "api", {"url": "/api/example", "method": "GET"}),
        (["shot", "--full-page", "--annotate", "--width", "1280", "--height", "800"], "shot", {"full_page": True, "annotate": True, "width": 1280, "height": 800}),
    ]
    for argv, command, args in cases:
        payload = native.parse_payload(argv)
        assert payload["cmd"] == command
        assert payload["args"] == args


def test_native_cli_semantic_type_and_top_level_targeting():
    payload = native.parse_payload(["type", "--role", "textbox", "--name", "Search", "your query", "--clear", "--tab", "7", "--profile", "browser-a"])
    assert payload == {"cmd": "type", "args": {"role": "textbox", "name": "Search", "text": "your query", "clear": True}, "tab": "7", "profile": "browser-a"}


def test_native_cli_uses_extension_wire_names_for_snake_case_helpers():
    assert native.parse_payload(["find_text", "Continue"])["cmd"] == "findText"
    assert native.parse_payload(["click_text", "Continue"])["cmd"] == "clickText"
    assert native.parse_payload(["click_all", ".item"])["cmd"] == "clickAll"
    assert native.parse_payload(["wait_text", "Ready"])["cmd"] == "waitText"
    assert native.parse_payload(["wait_until", "window.ready"])["cmd"] == "waitUntil"
    assert native.parse_payload(["wait_xhr", "/api"])["cmd"] == "waitXhr"
    assert native.parse_payload(["wait_dialog"])["cmd"] == "waitDialog"
    assert native.parse_payload(["fill", '{"q":"search"}'])["cmd"] == "fillForm"


def test_native_cli_help_bind_and_errors_do_not_require_daemon(monkeypatch, tmp_path, capsys):
    binding = tmp_path / ".sleeper-session"
    monkeypatch.setenv("SLEEPER_SESSION_FILE", str(binding))
    assert native.main(["--help"]) == 0
    assert "usage: sleeper" in capsys.readouterr().out
    assert native.main(["bind", "browser-a"]) == 0
    assert binding.read_text() == "browser-a\n"
    assert native.main(["unbind"]) == 0
    assert not binding.exists()
    assert native.main(["recipe", "daily"]) == 2
    assert "Bash CLI" in capsys.readouterr().err


def test_portable_builder_emits_platform_manifests(tmp_path):
    for kind, manifest_version in (("firefox", 2), ("chromium", 3)):
        output = tmp_path / f"{kind}.zip"
        result = subprocess.run([sys.executable, str(ROOT / "scripts/build_packages.py"), kind,
                                 str(ROOT / "extension"), str(output)], check=True,
                                text=True, capture_output=True)
        assert result.stdout.strip() == f"{output}: sha256 {hashlib.sha256(output.read_bytes()).hexdigest()}"
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["manifest_version"] == manifest_version
            assert "background.js" in archive.namelist()
            assert "manifest.chromium.json" not in archive.namelist()
            assert ("dynamic_code.js" in archive.namelist()) is (kind == "chromium")
            if kind == "firefox":
                gecko = manifest["browser_specific_settings"]["gecko"]
                assert gecko["id"] == "sleeper@shy-tangerine"
                assert gecko["strict_min_version"] == "140.0"
                assert gecko["data_collection_permissions"]["required"] == [
                    "browsingActivity", "websiteContent", "websiteActivity",
                ]


def test_windows_install_uses_portable_python_builder(tmp_path):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        artifact = Path(args[-1])
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"mock archive")
        return subprocess.CompletedProcess(args, 0)
    with patch.object(installer.sys, "platform", "win32"), patch.object(installer.subprocess, "run", side_effect=run):
        installer.build_packages(tmp_path)
    assert [Path(call[1]).name for call in calls] == ["build_packages.py", "build_packages.py"]
    assert [call[2] for call in calls] == ["firefox", "chromium"]


def test_windows_uninstall_removes_only_managed_launcher(monkeypatch, tmp_path):
    home = tmp_path / "home with spaces"
    data = home / "data"
    bindir = home / "bin"
    launcher = bindir / "sleeper.cmd"
    destination = data / "sleeper"
    destination.mkdir(parents=True)
    bindir.mkdir(parents=True)
    python = destination / "venv/Scripts/python.exe"
    target = destination / "cli/sleeper.py"
    launcher.write_text(f'@echo off\n"{python}" "{target}" %*\n')
    monkeypatch.setenv("SLEEPER_DATA_DIR", str(data))
    monkeypatch.setenv("SLEEPER_BIN_DIR", str(bindir))
    monkeypatch.setenv("SLEEPER_CODEX_CONFIG", str(home / "codex.toml"))
    registry = types.SimpleNamespace(HKEY_CURRENT_USER=object(), KEY_SET_VALUE=1, KEY_READ=1, KEY_WRITE=2,
                                     OpenKey=lambda *args: (_ for _ in ()).throw(FileNotFoundError()))
    with patch.object(installer.sys, "platform", "win32"), patch.object(installer.shutil, "which", return_value=None), \
         patch.dict(sys.modules, {"winreg": registry}):
        installer.uninstall()
    assert not launcher.exists()


def test_windows_firefox_native_host_is_registered_per_user(monkeypatch, tmp_path):
    destination = tmp_path / "data/sleeper"
    (destination / "daemon").mkdir(parents=True)
    values = {}

    class Key:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def query_value(key, _name):
        if key.name not in values:
            raise FileNotFoundError
        return values[key.name], registry.REG_SZ

    registry = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(), REG_SZ=1, KEY_READ=1, KEY_WRITE=2,
        CreateKey=lambda _root, name: Key(name),
        OpenKey=lambda _root, name, *_args: Key(name) if name in values else (_ for _ in ()).throw(FileNotFoundError()),
        QueryValueEx=query_value,
        SetValueEx=lambda key, _name, _reserved, _kind, value: values.__setitem__(key.name, value),
        DeleteValue=lambda key, _name: values.pop(key.name),
    )
    monkeypatch.setenv("SLEEPER_DATA_DIR", str(tmp_path / "data"))
    with patch.object(installer.sys, "platform", "win32"), \
         patch.object(installer, "_runtime_python", return_value=destination / "venv/Scripts/python.exe"), \
         patch.dict(sys.modules, {"winreg": registry}):
        manifest_path = installer._install_native_host(destination)
        payload = json.loads(manifest_path.read_text())
        assert payload["path"].endswith("native_messaging_host.cmd")
        assert payload["allowed_extensions"] == ["sleeper@shy-tangerine"]
        assert values[rf"Software\Mozilla\NativeMessagingHosts\{installer.FIREFOX_NATIVE_HOST}"] == str(manifest_path)
        installer._remove_native_host(destination)
        assert not manifest_path.exists()


def test_windows_install_replaces_only_its_existing_launcher(tmp_path):
    destination = tmp_path / "runtime/sleeper"
    bindir = tmp_path / "bin"
    destination.mkdir(parents=True)
    bindir.mkdir()
    launcher = bindir / "sleeper.cmd"
    with patch.object(installer.sys, "platform", "win32"), \
         patch.object(installer, "venv_dir", return_value=destination / "venv"), \
         patch.object(installer, "bin_dir", return_value=bindir):
        launcher.write_text(f'@echo off\n"{destination / "venv/Scripts/python.exe"}" "{destination / "cli/sleeper.py"}" %*\n')
        assert installer.managed_windows_launcher(launcher, destination)
        launcher.write_text(launcher.read_text() + "echo foreign\n")
        assert not installer.managed_windows_launcher(launcher, destination)


def test_windows_uninstall_preserves_foreign_run_entry(tmp_path):
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Registry:
        HKEY_CURRENT_USER = object(); KEY_READ = 1; KEY_SET_VALUE = 2
        def __init__(self): self.values = {"Sleeper": '"foreign.exe"'}
        def OpenKey(self, *args): return Key()
        def QueryValueEx(self, key, name): return self.values[name], 1
        def DeleteValue(self, key, name): self.values.pop(name)
    registry = Registry()
    with patch.dict(sys.modules, {"winreg": registry}), \
         patch.object(installer, "venv_dir", return_value=tmp_path / "venv"):
        installer._remove_windows_startup(tmp_path / "runtime")
    assert registry.values["Sleeper"] == '"foreign.exe"'


def test_windows_install_refuses_foreign_run_entry(tmp_path):
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Registry:
        HKEY_CURRENT_USER = object(); REG_SZ = 1
        def CreateKey(self, *args): return Key()
        def QueryValueEx(self, key, name): return '"foreign.exe"', self.REG_SZ
        def SetValueEx(self, *args): raise AssertionError("foreign value must not be overwritten")
    destination = tmp_path / "runtime"
    with patch.dict(sys.modules, {"winreg": Registry()}), \
         patch.object(installer, "venv_dir", return_value=tmp_path / "venv"):
        with pytest.raises(RuntimeError, match="foreign Windows startup"):
            installer._install_windows_startup(destination)


def test_windows_install_is_idempotent_with_managed_cmd_launcher(monkeypatch, tmp_path):
    import argparse
    monkeypatch.setenv("SLEEPER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SLEEPER_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("SLEEPER_SKILL_DIR", str(tmp_path / "skills/sleeper"))
    args = argparse.Namespace(no_deps=True, no_mcp=True, no_build=True, no_service=True, no_open=True, no_skill=False, no_plugins=True, plugins=None, yes=False, non_interactive=True)
    registry = types.SimpleNamespace(HKEY_CURRENT_USER=object(), REG_EXPAND_SZ=1, REG_SZ=1,
                                     CreateKey=lambda *args: types.SimpleNamespace(__enter__=lambda self: self, __exit__=lambda self, *a: False))
    # Context-manager magic methods are looked up on the class, not the instance.
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    registry.CreateKey = lambda *args: Key()
    registry.QueryValueEx = lambda *args: (_ for _ in ()).throw(FileNotFoundError())
    registry.SetValueEx = lambda *args: None
    with patch.object(installer.sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": registry}):
        first = installer.install(ROOT, args)
        second = installer.install(ROOT, args)
    launcher = Path(second["cli"])
    assert first["cli"] == second["cli"]
    assert launcher.is_file()
    assert "sleeper.py" in launcher.read_text()


def test_firefox_release_package_requires_matching_manifest_version(tmp_path):
    root = tmp_path / "project"
    (root / "extension").mkdir(parents=True)
    (root / "build").mkdir()
    (root / "extension/manifest.json").write_text('{"version":"2.0.0"}')
    candidate = root / "build/sleeper-firefox.xpi"
    with zipfile.ZipFile(candidate, "w") as archive:
        archive.writestr("manifest.json", '{"version":"2.0.0"}')
        archive.writestr("META-INF/manifest.mf", "Manifest-Version: 1.0\n")
        archive.writestr("META-INF/mozilla.sf", "Signature-Version: 1.0\n")
        archive.writestr("META-INF/mozilla.rsa", b"signature")
    assert installer.firefox_release_package(root) == candidate
    with zipfile.ZipFile(candidate, "w") as archive:
        archive.writestr("manifest.json", '{"version":"1.0.0"}')
        archive.writestr("META-INF/manifest.mf", "Manifest-Version: 1.0\n")
        archive.writestr("META-INF/mozilla.sf", "Signature-Version: 1.0\n")
        archive.writestr("META-INF/mozilla.rsa", b"signature")
    assert installer.firefox_release_package(root) is None


def test_posix_path_registration_is_owned_and_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("USERPROFILE", raising=False)
    with patch.object(installer.sys, "platform", "linux"):
        installer.ensure_cli_path(PurePosixPath("/opt/sleeper bin"))
        installer.ensure_cli_path(PurePosixPath("/opt/sleeper bin"))
        profile = tmp_path / "home/.profile"
        assert profile.read_text().count("# >>> Sleeper CLI >>>") == 1
        assert "'/opt/sleeper bin'" in profile.read_text()
        installer.remove_cli_path()
        assert "Sleeper CLI" not in profile.read_text()


def test_windows_run_key_starts_hidden_daemon_when_dormant(monkeypatch, tmp_path):
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Registry:
        HKEY_CURRENT_USER = object(); REG_SZ = 1
        def __init__(self): self.values = {}
        def CreateKey(self, root, name): self.created = name; return Key()
        def QueryValueEx(self, key, name): raise FileNotFoundError()
        def SetValueEx(self, key, name, reserved, kind, value): self.values[name] = value
    registry = Registry()
    destination = tmp_path / "runtime"
    pythonw = destination / "venv/Scripts/pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.write_bytes(b"")
    (destination / "daemon").mkdir()
    (destination / "daemon/daemon.py").write_text("")
    monkeypatch.setenv("SLEEPER_VENV_DIR", str(destination / "venv"))
    with patch.object(installer.sys, "platform", "win32"), \
         patch.dict(sys.modules, {"winreg": registry}), \
         patch.object(installer, "_daemon_listening", return_value=False), \
         patch.object(installer.subprocess, "Popen") as popen:
        assert installer._install_windows_startup(destination) == "HKCU Run: Sleeper"
    assert registry.created.endswith("CurrentVersion\\Run")
    assert "pythonw.exe" in registry.values["Sleeper"]
    popen.assert_called_once()


def test_signed_firefox_download_requires_signature_metadata(monkeypatch, tmp_path):
    root = tmp_path / "project"
    (root / "extension").mkdir(parents=True)
    (root / "extension/manifest.json").write_text('{"version":"2.0.0"}')
    signed = tmp_path / "signed.xpi"
    with zipfile.ZipFile(signed, "w") as archive:
        archive.writestr("manifest.json", '{"version":"2.0.0"}')
        archive.writestr("META-INF/manifest.mf", "Manifest-Version: 1.0\n")
        archive.writestr("META-INF/mozilla.sf", "Signature-Version: 1.0\n")
        archive.writestr("META-INF/mozilla.rsa", b"signature")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return signed.read_bytes()
    with patch.object(installer, "urlopen", return_value=Response()):
        package, status = installer.acquire_firefox_release_package(root)
    assert package == root / "build/sleeper-firefox.xpi"
    assert status == "downloaded Firefox release package; Firefox verifies its signature during installation"


def test_windows_never_kills_process_from_mutable_pid_file(tmp_path):
    destination = tmp_path / "runtime"
    (destination / "daemon").mkdir(parents=True)
    daemon = destination / "daemon/daemon.py"
    daemon.write_text("")
    (destination / "daemon.pid").write_text("4321")
    with pytest.raises(RuntimeError, match="stop Sleeper manually"):
        installer._stop_windows_daemon(destination)
    assert (destination / "daemon.pid").exists()


def test_windows_refuses_pid_for_another_process(monkeypatch, tmp_path):
    destination = tmp_path / "runtime"
    (destination / "daemon").mkdir(parents=True)
    (destination / "daemon/daemon.py").write_text("")
    (destination / "daemon.pid").write_text("4321")
    with pytest.raises(RuntimeError, match="stop Sleeper manually"):
        installer._stop_windows_daemon(destination)


def test_windows_path_removal_preserves_preexisting_entry(monkeypatch, tmp_path):
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Registry:
        HKEY_CURRENT_USER = object(); REG_EXPAND_SZ = 1; REG_SZ = 1; KEY_READ = 1; KEY_WRITE = 2
        def __init__(self): self.values = {"Path": f"C:\\Tools;{tmp_path / 'shared bin'}"}
        def CreateKey(self, *args): return Key()
        def OpenKey(self, *args): return Key()
        def QueryValueEx(self, key, name):
            if name not in self.values: raise FileNotFoundError()
            return self.values[name], self.REG_SZ
        def SetValueEx(self, key, name, reserved, kind, value): self.values[name] = value
        def DeleteValue(self, key, name): self.values.pop(name, None)
    registry = Registry()
    with patch.object(installer.sys, "platform", "win32"), \
         patch.object(installer, "bin_dir", return_value=tmp_path / "shared bin"), \
         patch.dict(sys.modules, {"winreg": registry}):
        installer.ensure_cli_path(tmp_path / "shared bin")
        installer.remove_cli_path()
    assert registry.values["Path"].endswith("shared bin")
