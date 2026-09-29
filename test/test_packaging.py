"""Offline contract for the future Python distribution boundary."""

from __future__ import annotations

import tomllib
import re
import zipfile
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_python_distribution_metadata_is_explicit():
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]
    assert document["build-system"] == {
        "requires": ["setuptools>=68"],
        "build-backend": "setuptools.build_meta",
    }
    assert project["name"] == "sleeper-cli"
    assert project["readme"] == "README.md"
    assert project["scripts"] == {
        "sleeper": "cli.sleeper:main",
        "sleeper-daemon": "daemon.daemon:run",
        "sleeper-mcp": "daemon.mcp_server:main",
    }
    assert document["tool"]["uv"]["package"] is True
    assert document["tool"]["setuptools"]["packages"]["find"] == {
        "include": ["cli", "daemon"],
        "namespaces": False,
    }
    for package in ("cli", "daemon"):
        assert (ROOT / package / "__init__.py").is_file()


def test_portable_chromium_package_contains_background_imports(tmp_path):
    spec = importlib.util.spec_from_file_location("build_packages", ROOT / "scripts" / "build_packages.py")
    assert spec and spec.loader
    build_packages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_packages)

    extension = ROOT / "extension"
    package = tmp_path / "chromium.zip"
    build_packages.extension_package("chromium", extension, package)
    background = (extension / "background.js").read_text(encoding="utf-8")
    imports = re.search(r"importScripts\(([^;]+)\);", background)
    assert imports is not None
    required = set(re.findall(r'"([^"]+\.js)"', imports.group(1)))
    assert required
    with zipfile.ZipFile(package) as archive_file:
        assert required <= set(archive_file.namelist())
