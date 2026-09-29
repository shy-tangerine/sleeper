import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "sleeper"


def run_cli(value, profile, no_jq=False, command="click"):
    environment = os.environ.copy()
    environment.update(
        SLEEPER_DRY_RUN="1",
        SLEEPER_PROFILE=profile,
    )
    if no_jq:
        with tempfile.TemporaryDirectory() as directory:
            for binary in ("bash", "dirname", "readlink", "sed"):
                os.symlink(shutil.which(binary), Path(directory) / binary)
            os.symlink(sys.executable, Path(directory) / "python3")
            environment["PATH"] = directory
            return _run_cli(environment, value, command)
    return _run_cli(environment, value, command)


def _run_cli(environment, value, command):
    result = subprocess.run(
        [str(CLI), command, value] if command == "click"
        else [str(CLI), command, value, "--files", value],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("value", "profile"),
    [
        ('quote " and apostrophe', "profile-1"),
        (r"backslash \\ and $HOME", "profile\\name"),
        ("line one\nline two", "profile\nname"),
        ("Unicode: café 日本語 😀", "perfil-á"),
        ("empty-profile", ""),
    ],
)
def test_jq_and_python_json_helpers_are_equivalent(value, profile):
    if shutil.which("jq") is None:
        pytest.skip("jq unavailable; Python fallback remains covered")
    jq_payload = run_cli(value, profile, no_jq=False)
    python_payload = run_cli(value, profile, no_jq=True)
    assert jq_payload == python_payload


def test_empty_json_string_escaping_matches_without_jq():
    if shutil.which("jq") is None:
        pytest.skip("jq unavailable; Python fallback remains covered")
    # upload --files now embeds file contents (name + content_base64), matching
    # the extension contract, so parity is checked against a real file; both
    # runs must produce byte-identical payloads with and without jq.
    with tempfile.NamedTemporaryFile() as handle:
        assert run_cli(handle.name, "qa", command="upload") == run_cli(
            handle.name, "qa", no_jq=True, command="upload"
        )
