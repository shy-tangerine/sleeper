import json
import os
import struct
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "daemon/native_messaging_host.py"


def _message(payload, declared_length=None):
    body = json.dumps(payload).encode()
    return struct.pack("<I", len(body) if declared_length is None else declared_length) + body


def test_native_host_returns_token_to_allowlisted_extension(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("test-token\n", encoding="utf-8")
    os.chmod(token_file, 0o600)
    env = os.environ.copy()
    env["SLEEPER_TOKEN_FILE"] = str(token_file)

    result = subprocess.run(
        [sys.executable, str(HOST)], input=_message({"type": "get_daemon_token"}),
        capture_output=True, env=env, check=True,
    )

    (length,) = struct.unpack("<I", result.stdout[:4])
    assert json.loads(result.stdout[4:4 + length]) == {"token": "test-token"}
    assert result.stdout[4 + length:] == b""
    assert result.stderr == b""


def test_native_host_rejects_unsupported_messages_without_reading_token(tmp_path):
    token_file = tmp_path / "token"
    env = os.environ.copy()
    env["SLEEPER_TOKEN_FILE"] = str(token_file)

    result = subprocess.run(
        [sys.executable, str(HOST)], input=_message({"type": "other"}),
        capture_output=True, env=env, check=False,
    )

    assert result.returncode == 1
    assert result.stdout == b""
    assert not token_file.exists()


def test_native_host_rejects_truncated_frame_even_when_body_is_valid_json(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("test-token\n", encoding="utf-8")
    os.chmod(token_file, 0o600)
    env = os.environ.copy()
    env["SLEEPER_TOKEN_FILE"] = str(token_file)
    request = {"type": "get_daemon_token"}
    body_length = len(json.dumps(request).encode())

    result = subprocess.run(
        [sys.executable, str(HOST)], input=_message(request, body_length + 1),
        capture_output=True, env=env, check=False,
    )

    assert result.returncode == 1
    assert result.stdout == b""


def test_native_host_does_not_create_a_token_before_the_daemon(tmp_path):
    token_file = tmp_path / "token"
    env = os.environ.copy()
    env["SLEEPER_TOKEN_FILE"] = str(token_file)

    result = subprocess.run(
        [sys.executable, str(HOST)], input=_message({"type": "get_daemon_token"}),
        capture_output=True, env=env, check=True,
    )

    (length,) = struct.unpack("<I", result.stdout[:4])
    assert json.loads(result.stdout[4:4 + length]) == {"token": ""}
    assert not token_file.exists()
