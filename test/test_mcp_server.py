import json
import hashlib
import hmac
import os
import sys
import base64
import struct
import subprocess
import threading
import tempfile
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
import zlib
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "daemon"))
import mcp_server


class McpContract(unittest.TestCase):
    def setUp(self):
        self.token_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.token_dir.name, "token")
        with open(self.token_path, "w", encoding="utf-8") as handle:
            handle.write("test-token\n")
        self.token_file = patch.object(mcp_server, "TOKEN_FILE", self.token_path)
        self.token_file.start()
        self.identity = patch.object(mcp_server, "_verify_daemon_identity")
        self.identity.start().return_value = "mock-instance"
        self.addCleanup(self.token_file.stop)
        self.addCleanup(self.identity.stop)
        self.addCleanup(self.token_dir.cleanup)

    def _call(self, name, arguments):
        return mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })

    def test_tab_is_top_level_in_daemon_request(self):
        captured = {}

        class Response:
            def read(self):
                return b'{"ok":true}'

        class Connection:
            def __init__(self, *args, **kwargs):
                captured["timeout"] = kwargs["timeout"]
            def request(self, method, path, body, headers):
                captured["raw_body"] = body
                captured["body"] = json.loads(body)
                captured["headers"] = headers
            def getresponse(self):
                return Response()
            def close(self):
                pass

        with patch.object(mcp_server.http.client, "HTTPConnection", Connection):
            self._call("sleeper_click", {"selector": "#go", "tab": "id:42"})

        self.assertEqual(captured["timeout"], 65)
        self.assertNotIn(b" ", captured["raw_body"])
        self.assertEqual(captured["body"], {"cmd": "click", "args": {"selector": "#go"}, "tab": "id:42"})
        self.assertNotIn("Authorization", captured["headers"])
        self.assertEqual(captured["headers"]["X-Sleeper-Instance"], "mock-instance")
        self.assertTrue(captured["headers"]["X-Sleeper-Proof"])

    def test_runtime_argument_names_and_shapes_are_exposed(self):
        schemas = {tool["name"]: tool["inputSchema"] for tool in mcp_server.TOOLS}
        self.assertIn("timeout_ms", schemas["sleeper_wait_text"]["properties"])
        self.assertIn("timeout_ms", schemas["sleeper_wait_url"]["properties"])
        xhr = schemas["sleeper_wait_xhr"]["properties"]
        self.assertTrue(set(("url_substring", "timeout_ms", "tab")) <= set(xhr))
        self.assertIn("limit", schemas["sleeper_console"]["properties"])
        self.assertEqual(schemas["sleeper_upload"]["properties"]["files"]["type"], "array")
        self.assertIn("sleeper_media", schemas)
        network = schemas["sleeper_network"]["properties"]
        for key in ("fetch", "url", "body", "segment", "tab"):
            self.assertIn(key, network)

        batch = schemas["sleeper_batch"]
        self.assertEqual(batch["properties"]["actions"]["type"], "array")
        self.assertEqual(batch["required"], ["actions"])

    def test_batch_is_forwarded_as_one_daemon_command(self):
        captured = {}
        actions = [
            {"cmd": "goto", "args": {"url": "https://example.test"}},
            {"cmd": "read", "args": {"selector": "h1"}, "tab": "0"},
        ]

        with patch.object(mcp_server, "daemon_call", side_effect=lambda cmd, args, tab=None, profile=None: captured.update(
            cmd=cmd, args=args, tab=tab, profile=profile) or {"ok": True}):
            self._call("sleeper_batch", {"actions": actions, "profile": "phone"})

        self.assertEqual(captured, {
            "cmd": "batch", "args": {"actions": actions}, "tab": None, "profile": "phone",
        })

    def test_stdio_rejects_oversized_records_before_json_parsing(self):
        stdin = io.BytesIO(b"{" + b"x" * mcp_server.MAX_REQUEST_BYTES + b"}\n")
        stdout = io.StringIO()
        with patch.object(mcp_server.sys, "stdin", stdin), patch.object(mcp_server.sys, "stdout", stdout):
            self.assertEqual(mcp_server.main(), 1)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["message"], "Request too large")

    def test_stdio_rejects_oversized_json_rpc_batches(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        stdin = io.StringIO(json.dumps([request] * (mcp_server.MAX_BATCH_REQUESTS + 1)) + "\n")
        stdout = io.StringIO()
        with patch.object(mcp_server.sys, "stdin", stdin), patch.object(mcp_server.sys, "stdout", stdout):
            self.assertEqual(mcp_server.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], -32600)

    def test_profile_is_forwarded_from_environment(self):
        captured = {}
        class Response:
            def read(self): return b'{"ok":true}'
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, method, path, body, headers): captured["body"] = json.loads(body)
            def getresponse(self): return Response()
            def close(self): pass
        with patch.object(mcp_server, "DAEMON_PROFILE", "qa"), patch.object(mcp_server.http.client, "HTTPConnection", Connection):
            self._call("sleeper_click", {"selector": "#go"})
        self.assertEqual(captured["body"]["profile"], "qa")

    def test_tool_response_uses_compact_json_without_skipping_redaction(self):
        secret = "sk_live_1234567890abcdefghij"
        result = {"ok": True, "result": {"token": secret, "items": [1, 2]}}

        with patch.object(mcp_server, "daemon_call", return_value=result):
            response = self._call("sleeper_click", {"selector": "#go"})

        text = response["result"]["content"][0]["text"]
        self.assertEqual(text, json.dumps(json.loads(text), separators=(",", ":")))
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED]", text)

    def test_large_image_artifact_survives_mcp_output(self):
        chunk = lambda kind, value: struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
        raw = b"".join(b"\0" + b"\x11" * 768 for _ in range(256))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 0)) + chunk(b"IEND", b"")
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        self.assertGreater(len(data_url), 65536)
        with patch.object(mcp_server, "daemon_call", return_value={"ok": True, "result": {"dataUrl": data_url}}):
            response = self._call("sleeper_shot", {})
        text = response["result"]["content"][0]["text"]
        self.assertEqual(json.loads(text)["result"]["dataUrl"], data_url)

    def test_large_image_artifact_survives_mcp_stdio(self):
        chunk = lambda kind, value: struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
        raw = b"".join(b"\0" + b"\x11" * 768 for _ in range(256))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 0)) + chunk(b"IEND", b"")
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonce = parse_qs(urlparse(self.path).query).get("nonce", [""])[0]
                instance = "mock-instance"
                proof = hmac.new(b"test-token", f"{nonce}:{instance}".encode(), hashlib.sha256).hexdigest()
                body = json.dumps({"ok": True, "instance_id": instance, "identity_proof": proof}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                body = json.dumps({"ok": True, "result": {"dataUrl": data_url}}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args): pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = os.environ.copy(); env["SLEEPER_PORT"] = str(server.server_port); env["SLEEPER_TOKEN_FILE"] = self.token_path
        try:
            proc = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), "daemon", "mcp_server.py")], input=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sleeper_shot","arguments":{}}}) + "\n", text=True, capture_output=True, env=env, timeout=10)
        finally:
            server.shutdown(); server.server_close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["result"]["dataUrl"], data_url)


    def test_per_call_profile_overrides_environment(self):
        captured = {}

        class Response:
            def read(self): return b'{"ok":true}'
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, method, path, body, headers):
                captured["body"] = json.loads(body)
            def getresponse(self): return Response()
            def close(self): pass

        with patch.object(mcp_server, "DAEMON_PROFILE", "default"), \
             patch.object(mcp_server.http.client, "HTTPConnection", Connection):
            self._call("sleeper_click", {"selector": "#go", "profile": "firefox"})
        self.assertEqual(captured["body"]["profile"], "firefox")
        self.assertNotIn("profile", captured["body"]["args"])

    def test_sessions_uses_daemon_local_command(self):
        captured = {}

        class Response:
            def read(self): return b'{"ok":true,"profiles":{"firefox":{"ambiguous":false}}}'
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, method, path, body, headers):
                captured["method"] = method
                captured["path"] = path
                captured["body"] = json.loads(body)
            def getresponse(self): return Response()
            def close(self): pass

        with patch.object(mcp_server.http.client, "HTTPConnection", Connection):
            response = self._call("sleeper_sessions", {})
        self.assertEqual((captured["method"], captured["path"]), ("POST", "/command"))
        self.assertEqual(captured["body"]["cmd"], "sessions")
        self.assertIn("firefox", json.loads(response["result"]["content"][0]["text"])["profiles"])

    def test_connection_refused_reports_daemon_remedy(self):
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): raise ConnectionRefusedError()
            def close(self): pass

        with patch.object(mcp_server.http.client, "HTTPConnection", Connection), \
                patch.object(mcp_server.sys, "platform", "linux"):
            result = mcp_server.daemon_call("sessions", {})
        self.assertFalse(result["ok"])
        self.assertIn("on Linux run", result["error"])
        self.assertIn("systemctl --user enable --now sleeper.service", result["error"])

        with patch.object(mcp_server.http.client, "HTTPConnection", Connection), \
                patch.object(mcp_server.sys, "platform", "darwin"):
            result = mcp_server.daemon_call("sessions", {})
        self.assertFalse(result["ok"])
        self.assertIn("on macOS run", result["error"])
        self.assertIn("launchctl kickstart", result["error"])

    def test_all_tools_accept_profile_override(self):
        for tool in mcp_server.TOOLS:
            self.assertIn("profile", tool["inputSchema"]["properties"], tool["name"])


if __name__ == "__main__":
    unittest.main()
