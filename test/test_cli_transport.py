import json
import hashlib
import hmac
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "sleeper"


class Recorder(BaseHTTPRequestHandler):
    requests = []
    error_mode = False
    response_delay = 0

    def do_GET(self):
        nonce = parse_qs(urlparse(self.path).query).get("nonce", [""])[0]
        instance = "mock-instance"
        proof = hmac.new(b"test-token", f"{nonce}:{instance}".encode(), hashlib.sha256).hexdigest()
        raw = json.dumps({"ok": True, "instance_id": instance, "identity_proof": proof}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if type(self).response_delay:
            time.sleep(type(self).response_delay)
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        type(self).requests.append(body)
        type(self).auth_headers.append({name: self.headers.get(name) for name in
                                        ("Authorization", "X-Sleeper-Instance", "X-Sleeper-Nonce", "X-Sleeper-Proof")})
        payload = {"ok": not type(self).error_mode, "result": {"items": []}}
        if body.get("cmd") == "shot":
            payload["result"] = {"dataUrl": "data:image/png;base64,UE5H"}
        if type(self).error_mode:
            payload["error"] = "mock daemon failure"
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        pass


class Server:
    def __enter__(self):
        Recorder.requests = []
        Recorder.auth_headers = []
        Recorder.error_mode = False
        Recorder.response_delay = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()

    @property
    def port(self):
        return self.server.server_port


def run(server, *args, executable=None):
    env = os.environ.copy()
    env.update(SLEEPER_PORT=str(server.port), SLEEPER_PROFILE="qa")
    with tempfile.TemporaryDirectory() as directory:
        token_path = Path(directory) / "token"
        token_path.write_text("test-token\n", encoding="utf-8")
        env["SLEEPER_TOKEN_FILE"] = str(token_path)
        return subprocess.run(
            [*(executable or [str(CLI)]), *args], cwd=ROOT, env=env, text=True,
            capture_output=True, timeout=15,
        )


def run_shell(server, *args):
    env = os.environ.copy()
    env.update(SLEEPER_PORT=str(server.port), SLEEPER_PROFILE="qa")
    with tempfile.TemporaryDirectory() as directory:
        token_path = Path(directory) / "token"
        token_path.write_text("test-token\n", encoding="utf-8")
        env["SLEEPER_TOKEN_FILE"] = str(token_path)
        return subprocess.run(
            [str(ROOT / "cli" / "sleeper"), *args], cwd=ROOT, env=env,
            text=True, capture_output=True, timeout=15,
        )


def run_without_token(port, *args):
    env = os.environ.copy()
    env.update(SLEEPER_PORT=str(port), SLEEPER_PROFILE="qa")
    with tempfile.TemporaryDirectory() as directory:
        env["SLEEPER_TOKEN_FILE"] = str(Path(directory) / "missing-token")
        return subprocess.run(
            [str(CLI), *args], cwd=ROOT, env=env, text=True,
            capture_output=True, timeout=15,
        )


def test_ordinary_and_early_paths_share_profiled_transport():
    with Server() as server:
        assert run(server, "state").returncode == 0
        assert run(server, "click", "--role", "button", "--name", "Next").returncode == 0
        assert run(server, "shot", "--full-page").returncode == 0

    assert [request["cmd"] for request in Recorder.requests] == ["state", "click", "shot"]
    assert all(request["profile"] == "qa" for request in Recorder.requests)
    assert all(headers["Authorization"] is None and headers["X-Sleeper-Instance"] == "mock-instance" and
               headers["X-Sleeper-Nonce"] and headers["X-Sleeper-Proof"] for headers in Recorder.auth_headers)


def test_version_is_available_without_daemon():
    result = subprocess.run([str(CLI), "--version"], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "Sleeper 2.0.1"


def test_missing_token_distinguishes_running_daemon():
    with Server() as server:
        result = run_without_token(server.port, "sessions")

    assert result.returncode == 1
    assert "daemon is running but no local token exists yet" in result.stderr
    assert "daemon is not running" not in result.stderr


def test_missing_token_reports_stopped_daemon():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    result = run_without_token(port, "sessions")

    assert result.returncode == 1
    assert "daemon is not running" in result.stderr


def test_shot_writes_png_instead_of_dumping_base64(tmp_path):
    output = tmp_path / "capture.png"
    with Server() as server:
        result = run(server, "shot", str(output), "--full-page", "--annotate", "--tab", "2", "--width", "1200", "--height", "800")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"saved {output}"
    assert output.read_bytes() == b"PNG"
    assert Recorder.requests == [{
        "cmd": "shot",
        "args": {"tab": "2", "full_page": True, "annotate": True, "width": 1200, "height": 800},
        "profile": "qa",
    }]


def test_network_forwards_tab_and_filters(tmp_path):
    with Server() as server:
        result = run(server, "network", "--media", "--since=60", "--clear", "--body", "--tab", "2")

    assert result.returncode == 0, result.stderr
    assert Recorder.requests == [{
        "cmd": "network",
        "args": {"media": True, "since": 60, "clear": True, "body": True, "tab": "2"},
        "profile": "qa",
    }]


def test_schema_and_recipe_paths_use_profiled_command_contract():
    with Server() as server:
        schema = run(server, "schema", "product-listing", "--json")
        recipe = run(server, "recipe", "chatgpt-export-titles", "--json")

    assert schema.returncode == 0
    assert recipe.returncode == 0
    assert [request["cmd"] for request in Recorder.requests] == ["extract", "api"]
    assert all(request["profile"] == "qa" for request in Recorder.requests)
    assert all(headers["Authorization"] is None and headers["X-Sleeper-Proof"] for headers in Recorder.auth_headers)
    assert json.loads(recipe.stdout)["ok"] is True


def test_daemon_error_payload_remains_visible():
    with Server() as server:
        Recorder.error_mode = True
        Recorder.response_delay = 2
        result = run(server, "state")

    assert result.returncode == 0
    assert "mock daemon failure" in result.stdout
    duration = result.stderr.split("failed after ", 1)[1].split("ms", 1)[0]
    assert int(duration) >= 1000


def test_long_command_reports_progress_without_changing_stdout_json():
    with Server() as server:
        Recorder.response_delay = 2
        result = run(server, "wait_text", "ready")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True
    assert "waitText still running (" in result.stderr


def test_python_cli_reports_elapsed_time_for_daemon_failure():
    with Server() as server:
        Recorder.error_mode = True
        Recorder.response_delay = 2
        result = run(
            server, "state",
            executable=[sys.executable, str(ROOT / "cli" / "sleeper.py")],
        )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"] == "mock daemon failure"
    duration = result.stderr.split("failed after ", 1)[1].split("ms", 1)[0]
    assert int(duration) >= 1000


def test_shell_cli_never_sends_daemon_bearer_token():
    with Server() as server:
        result = run_shell(server, "state")

    assert result.returncode == 0, result.stderr
    assert Recorder.auth_headers[0]["Authorization"] is None
    assert Recorder.auth_headers[0]["X-Sleeper-Proof"]


def test_batch_posts_one_ordered_action_list():
    actions = '[{"cmd":"goto","args":{"url":"https://example.test"}},{"cmd":"read","args":{"selector":"h1"}}]'
    with Server() as server:
        result = run(server, "batch", actions)

    assert result.returncode == 0
    assert Recorder.requests == [{
        "cmd": "batch",
        "args": {"actions": json.loads(actions)},
        "profile": "qa",
    }]
