"""Installer contract for uv-managed runtime dependencies."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sleeper_install_uv", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(installer)


def test_uv_metadata_is_canonical_and_version_aligned():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    firefox = json.loads((ROOT / "extension/manifest.json").read_text())
    chromium = json.loads((ROOT / "extension/manifest.chromium.json").read_text())

    daemon_source = (ROOT / "daemon/daemon.py").read_text(encoding="utf-8")
    cli_source = (ROOT / "cli/sleeper.py").read_text(encoding="utf-8")
    mcp_source = (ROOT / "daemon/mcp_server.py").read_text(encoding="utf-8")
    shell_source = (ROOT / "cli/sleeper").read_text(encoding="utf-8")
    version = project["project"]["version"]
    assert version == firefox["version"] == chromium["version"]
    assert f'VERSION = "{version}"' in daemon_source
    assert f'VERSION = "{version}"' in cli_source
    assert f'"version": "{version}"' in mcp_source
    assert f'Sleeper {version}' in shell_source
    assert project["project"]["license"] == "MIT"
    assert (ROOT / "uv.lock").is_file()
    assert not (ROOT / "daemon/requirements.txt").exists()
    assert not (ROOT / "daemon/requirements-dev.txt").exists()


def test_installer_uses_frozen_uv_runtime_environment(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    bin_root = tmp_path / "bin"
    venv = data_root / "sleeper" / "venv"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("SLEEPER_DATA_DIR", str(data_root))
    monkeypatch.setenv("SLEEPER_BIN_DIR", str(bin_root))
    monkeypatch.setenv("SLEEPER_VENV_DIR", str(venv))
    monkeypatch.setattr(installer, "uv_executable", lambda: "uv-test")
    monkeypatch.setattr(installer, "ensure_cli_path", lambda _directory: None)

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    args = argparse.Namespace(
        no_deps=False,
        no_mcp=True,
        no_build=True,
        no_service=True,
        no_open=True,
        no_skill=True,
        no_plugins=True,
        plugins=None,
        yes=False,
        non_interactive=True,
    )

    installer.install(ROOT, args)

    destination = data_root / "sleeper"
    assert (destination / "pyproject.toml").read_bytes() == (ROOT / "pyproject.toml").read_bytes()
    assert (destination / "uv.lock").read_bytes() == (ROOT / "uv.lock").read_bytes()
    assert calls == [
        (
            [
                "uv-test",
                "sync",
                "--project",
                str(destination),
                "--frozen",
                "--no-dev",
                "--no-install-project",
            ],
            {
                "check": True,
                "env": {
                    **os.environ,
                    "UV_PROJECT_ENVIRONMENT": str(venv),
                },
            },
        )
    ]
