"""Source identity of development browser packages (issue #20).

A development XPI must expose a reproducible source identity separate from
the release version, so a stale same-version package can never pass as
current.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_packages.py"


def build(source: Path, output: Path, kind: str = "firefox") -> None:
    subprocess.run([sys.executable, str(BUILDER), kind, str(source), str(output)],
                   check=True, cwd=ROOT, capture_output=True)


def source_id(archive: Path) -> dict[str, str]:
    with zipfile.ZipFile(archive) as z:
        raw = z.read("SOURCE_ID").decode("utf-8")
    identity: dict[str, str] = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            identity[key.strip()] = value.strip()
    return identity


def test_dev_package_exposes_reproducible_source_identity(tmp_path):
    output = tmp_path / "sleeper.xpi"
    build(ROOT / "extension", output)
    first = source_id(output)
    assert first["version"]
    assert len(first["content"]) == 16
    # Two builds from identical sources agree.
    second_output = tmp_path / "again.xpi"
    build(ROOT / "extension", second_output)
    assert source_id(second_output) == first
    assert output.read_bytes() == second_output.read_bytes()


def test_source_identity_changes_when_packaged_source_changes(tmp_path):
    import shutil
    staged = tmp_path / "extension"
    shutil.copytree(ROOT / "extension", staged,
                    ignore=shutil.ignore_patterns("__pycache__"))
    output_a = tmp_path / "a.xpi"
    build(staged, output_a)
    (staged / "sleeper.js").write_text(
        (staged / "sleeper.js").read_text(encoding="utf-8") + "\n// touched\n",
        encoding="utf-8")
    output_b = tmp_path / "b.xpi"
    build(staged, output_b)
    assert source_id(output_a)["content"] != source_id(output_b)["content"]
    # Same manifest version in both packages: only SOURCE_ID tells them apart.
    assert source_id(output_a)["version"] == source_id(output_b)["version"]


def test_daemon_reports_addon_source_id_in_sessions(tmp_path):
    sys.path.insert(0, str(ROOT / "daemon"))
    import daemon
    identity = "16ca9068c7f9/69ec30b76e264fd7"
    record = daemon._client_record(
        ws=object(),
        info={"profile": "p", "browser_id": "b", "addon_version": "2.0.1",
              "source_id": identity, "protocol_version": daemon.PROTOCOL_VERSION,
              "client_type": "extension"},
        existing=None)
    assert record["source_id"] == identity
