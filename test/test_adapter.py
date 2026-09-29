import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "cli" / "adapter.py"


def run(tmp_path, action, name):
    env = os.environ.copy()
    env["SLEEPER_ADAPTER_DIR"] = str(tmp_path / "adapters")
    return subprocess.run(
        [sys.executable, str(ADAPTER), action, name],
        text=True,
        capture_output=True,
        env=env,
    )


def test_nested_adapter_is_created_inside_root(tmp_path):
    result = run(tmp_path, "init", "team/shop")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert (tmp_path / "adapters" / "team" / "shop" / "adapter.json").is_file()


def test_parent_traversal_is_rejected(tmp_path):
    result = run(tmp_path, "init", "../outside")
    assert result.returncode == 2
    assert json.loads(result.stdout)["ok"] is False
    assert not (tmp_path / "outside").exists()


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "linked").symlink_to(outside, target_is_directory=True)
    result = run(tmp_path, "verify", "linked")
    assert result.returncode == 2
    assert json.loads(result.stdout)["ok"] is False


def test_absolute_path_is_structured_error(tmp_path):
    result = run(tmp_path, "init", str(tmp_path / "outside"))
    assert result.returncode == 2
    assert json.loads(result.stdout)["ok"] is False
    assert not result.stderr
    assert not (tmp_path / "outside").exists()


def test_existing_empty_directory_is_preserved(tmp_path):
    directory = tmp_path / "adapters" / "existing"
    directory.mkdir(parents=True)
    result = run(tmp_path, "init", "existing")
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not list(directory.iterdir())
    assert not result.stderr


def test_filesystem_failure_is_structured_error(tmp_path):
    root = tmp_path / "adapters"
    root.mkdir()
    (root / "blocked").write_text("keep")
    result = run(tmp_path, "init", "blocked/child")
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False
    assert (root / "blocked").read_text() == "keep"
    assert not result.stderr


def test_created_adapter_verifies(tmp_path):
    assert run(tmp_path, "init", "team/shop").returncode == 0
    result = run(tmp_path, "verify", "team/shop")
    assert result.returncode == 0
    assert json.loads(result.stdout)["errors"] == []


def test_failed_scaffold_write_leaves_no_partial_adapter(tmp_path, monkeypatch):
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location("adapter_under_test", ADAPTER)
    adapter_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter_module)
    original_write = Path.write_text

    def fail_readme(path, *args, **kwargs):
        if path.name == "README.md":
            raise OSError("simulated write failure")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_readme)
    target = tmp_path / "adapters" / "shop"
    with pytest.raises(OSError, match="simulated write failure"):
        adapter_module.create_adapter(target, "shop")
    assert not target.exists()
    assert not list(target.parent.iterdir())


def test_definition_symlink_cannot_read_outside_adapter(tmp_path):
    directory = tmp_path / "adapters" / "shop"
    directory.mkdir(parents=True)
    outside = tmp_path / "external.json"
    outside.write_text('{"name":"external","commands":[]}')
    (directory / "adapter.json").symlink_to(outside)
    result = run(tmp_path, "verify", "shop")
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not result.stderr
