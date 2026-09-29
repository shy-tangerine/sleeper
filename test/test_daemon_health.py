import asyncio
import hashlib
import hmac
import os
import socket
from types import SimpleNamespace
import base64
import io
import json
import struct
import zlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "daemon"))
import daemon


class HealthEndpointContract(unittest.TestCase):
    def test_http_connections_are_bounded_and_timed_before_headers(self):
        left, right = socket.socketpair()
        handler = daemon.ApiHandler.__new__(daemon.ApiHandler)
        handler.request = left
        handler.client_address = ("127.0.0.1", 1)
        handler.server = SimpleNamespace()
        try:
            handler.setup()
            self.assertEqual(left.gettimeout(), 10)
            handler.finish()
        finally:
            left.close()
            right.close()

        server = daemon.BoundedThreadingHTTPServer(("127.0.0.1", 0), daemon.ApiHandler)
        request = MagicMock()
        try:
            for _ in range(server.max_connections):
                self.assertTrue(server._request_slots.acquire(blocking=False))
            server.process_request(request, ("127.0.0.1", 2))
            request.close.assert_called_once()
        finally:
            server.server_close()

    def test_existing_token_reader_rejects_leaf_replacement(self):
        with tempfile.TemporaryDirectory() as work:
            token = Path(work) / "token"
            outside = Path(work) / "outside"
            token.write_text("original\n", encoding="utf-8")
            outside.write_text("attacker\n", encoding="utf-8")
            original_open = os.open

            def replace_then_open(path, flags, *args, **kwargs):
                if path == str(token):
                    token.unlink()
                    token.symlink_to(outside)
                return original_open(path, flags, *args, **kwargs)

            with patch.object(daemon, "TOKEN_FILE", str(token)), \
                 patch.object(daemon.os, "open", side_effect=replace_then_open):
                self.assertIsNone(daemon._read_existing_token())

    def test_existing_token_is_restricted_before_read(self):
        with tempfile.TemporaryDirectory() as work:
            token = Path(work) / "token"
            token.write_text("private\n", encoding="utf-8")
            os.chmod(token, 0o644)
            original_fdopen = os.fdopen

            def check_mode_before_read(descriptor, *args, **kwargs):
                self.assertEqual(os.fstat(descriptor).st_mode & 0o777, 0o600)
                return original_fdopen(descriptor, *args, **kwargs)

            with patch.object(daemon, "TOKEN_FILE", str(token)), \
                 patch.object(daemon.os, "fdopen", side_effect=check_mode_before_read):
                self.assertEqual(daemon._read_existing_token(), "private")

    def test_health_does_not_return_token_material(self):
        handler = daemon.ApiHandler.__new__(daemon.ApiHandler)
        handler.path = "/health"

        with patch.object(handler, "_send_raw") as send, patch.object(
            daemon, "_token", return_value="super-secret-token"
        ):
            handler.do_GET()

        send.assert_called_once_with(200, {"ok": True, "service": "sleeper",
                                           "daemon_version": daemon.VERSION,
                                           "protocol_version": daemon.PROTOCOL_VERSION,
                                           "instance_id": daemon.INSTANCE_ID})
        payload = send.call_args.args[1]
        self.assertNotIn("token", payload)
        self.assertNotIn("super-secret-token", repr(payload))

    def test_health_proves_daemon_identity_without_disclosing_token(self):
        nonce = "ab" * 16
        handler = daemon.ApiHandler.__new__(daemon.ApiHandler)
        handler.path = f"/health?nonce={nonce}"
        with patch.object(handler, "_send_raw") as send, patch.object(daemon, "_token", return_value="test-token"):
            handler.do_GET()
        payload = send.call_args.args[1]
        self.assertEqual(payload["identity_proof"], hmac.new(
            b"test-token", f"{nonce}:{daemon.INSTANCE_ID}".encode(), hashlib.sha256
        ).hexdigest())
        self.assertNotIn("test-token", repr(payload))

    def test_identity_proof_uses_lazy_token_accessor(self):
        nonce = "cd" * 16
        with patch.object(daemon, "_token", return_value="test-token"):
            proof = daemon.daemon_identity_proof(nonce)
        self.assertEqual(proof, hmac.new(
            b"test-token", f"{nonce}:{daemon.INSTANCE_ID}".encode(), hashlib.sha256
        ).hexdigest())

    def _handler(self, path, origin=""):
        handler = daemon.ApiHandler.__new__(daemon.ApiHandler)
        handler.path = path
        handler.headers = {"Origin": origin} if origin else {}
        handler.connection = SimpleNamespace(settimeout=lambda _seconds: None)
        return handler

    def _authorize(self, handler, method="GET", body=b"", token="test-token"):
        handler.command = method
        nonce = os.urandom(16).hex()
        timestamp = int(time.time())
        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{daemon.INSTANCE_ID}\n{nonce}\n{timestamp}\n{method}\n{handler.path}\n{body_hash}".encode()
        handler.headers.update({
            "Content-Length": str(len(body)),
            "X-Sleeper-Instance": daemon.INSTANCE_ID,
            "X-Sleeper-Nonce": nonce,
            "X-Sleeper-Timestamp": str(timestamp),
            "X-Sleeper-Proof": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
            "X-Sleeper-Preamble": hmac.new(token.encode(),
                f"{daemon.INSTANCE_ID}\n{nonce}\n{timestamp}\n{method}\n{handler.path}\n{len(body)}".encode(),
                hashlib.sha256).hexdigest(),
        })

    def test_page_origins_cannot_read_tab_registry(self):
        handler = self._handler("/tabs", "https://untrusted.example")
        with patch.object(handler, "_send") as send:
            handler.do_GET()
        send.assert_called_once_with(401, {"ok": False, "error": "local client authorization required"})

    def test_browser_navigation_metadata_cannot_read_tabs(self):
        handler = self._handler("/tabs")
        handler.headers["Sec-Fetch-Site"] = "same-origin"
        handler.headers["Sec-Fetch-Mode"] = "navigate"
        with patch.object(handler, "_send") as send:
            handler.do_GET()
        send.assert_called_once_with(401, {"ok": False, "error": "local client authorization required"})

    def test_headerless_local_command_is_rejected(self):
        handler = self._handler("/command")
        with patch.object(handler, "_send") as send:
            handler.do_POST()
        send.assert_called_once_with(401, {"ok": False, "error": "local client authorization required"})

    def test_local_command_accepts_signed_request(self):
        handler = self._handler("/command")
        request = {"cmd": "sessions", "args": {}}
        raw = json.dumps(request).encode()
        with patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(handler, "_read_command_body", return_value=(request, raw)), \
             patch.object(handler, "_dispatch_to_browser") as dispatch:
            self._authorize(handler, "POST", raw)
            handler.do_POST()
        dispatch.assert_called_once_with(request)

    def test_signed_request_nonce_cannot_be_replayed(self):
        handler = self._handler("/command")
        request = {"cmd": "sessions", "args": {}}
        raw = json.dumps(request).encode()
        with patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(handler, "_read_command_body", return_value=(request, raw)), \
             patch.object(handler, "_dispatch_to_browser") as dispatch, \
             patch.object(handler, "_send") as send:
            self._authorize(handler, "POST", raw)
            handler.do_POST()
            handler.do_POST()
        dispatch.assert_called_once_with(request)
        send.assert_called_with(401, {"ok": False, "error": "local client authorization required"})

    def test_auth_nonce_store_prunes_expired_entries_and_has_a_hard_limit(self):
        with patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(daemon, "MAX_AUTH_NONCES", 1), \
             patch.object(daemon, "_auth_nonces", {
                 "expired": int(time.time()) - daemon.AUTH_WINDOW_SECONDS - 1
             }) as nonce_store:
            timestamp = int(time.time())
            nonce = "ab" * 16
            proof = daemon.request_proof(nonce, timestamp, "GET", "/health")
            self.assertTrue(daemon.consume_request_proof(
                daemon.INSTANCE_ID, nonce, timestamp, proof, "GET", "/health"))
            self.assertEqual(nonce_store, {nonce: timestamp})

            next_nonce = "cd" * 16
            next_proof = daemon.request_proof(next_nonce, timestamp, "GET", "/health")
            self.assertFalse(daemon.consume_request_proof(
                daemon.INSTANCE_ID, next_nonce, timestamp, next_proof, "GET", "/health"))
            self.assertEqual(len(nonce_store), 1)

    def test_spoofed_tailscale_command_without_bearer_is_rejected(self):
        handler = self._handler("/command")
        handler.headers["Tailscale-User-Login"] = "person@example.test"
        with patch.object(handler, "_send") as send:
            handler.do_POST()
        send.assert_called_once_with(401, {"ok": False, "error": "local client authorization required"})

    def test_local_tabs_accepts_signed_request(self):
        handler = self._handler("/tabs")
        self._authorize(handler)
        future = SimpleNamespace(result=lambda timeout: {"ok": True, "tabs": []})
        def schedule(coro, loop):
            coro.close()
            return future
        with patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(daemon.asyncio, "run_coroutine_threadsafe", side_effect=schedule), \
             patch.object(handler, "_send") as send:
            handler.do_GET()
        self.assertEqual(send.call_args.args[0], 200)

    def test_spoofed_tailscale_tabs_without_bearer_is_rejected(self):
        handler = self._handler("/tabs")
        handler.headers["Tailscale-User-Login"] = "person@example.test"
        with patch.object(handler, "_send") as send:
            handler.do_GET()
        send.assert_called_once_with(401, {"ok": False, "error": "local client authorization required"})

    def test_token_is_never_exposed_over_http(self):
        for origin in ("", "chrome-extension://test-extension", "moz-extension://test-extension"):
            handler = self._handler("/token", origin)
            with patch.object(handler, "_send") as send, patch.object(daemon, "_token", return_value="test-token"):
                handler.do_GET()
            send.assert_called_once_with(404, {"ok": False, "error": "not found"})

    def test_api_hosts_accepts_signed_paired_extension(self):
        handler = self._handler("/api-hosts")
        self._authorize(handler)
        with patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(daemon, "configured_api_hosts", return_value={"ok": True, "hosts": []}), \
             patch.object(handler, "_send") as send:
            handler.do_GET()
        send.assert_called_once_with(200, {"ok": True, "hosts": []})

    def test_daemon_binding_is_always_loopback_only(self):
        with self.assertRaisesRegex(ValueError, "Tailscale Serve"):
            daemon.validate_network_config("192.168.1.5")
        self.assertTrue(daemon.validate_network_config("127.0.0.1"))

    def test_extension_origin_pin_mode_pins_first_authenticated_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            pin_file = os.path.join(tmp, "ext-pin")
            with patch.object(daemon, "EXTENSION_ORIGIN_MODE", "pin"), \
                 patch.object(daemon, "EXTENSION_PIN_FILE", pin_file), \
                 patch.object(daemon, "ALLOWED_EXTENSION_IDS", ()), \
                 patch.object(daemon, "_pinned_extension_ids", None):
                # Unauthenticated check before any pin: only allowed once an
                # extension has pinned itself.
                self.assertFalse(daemon._is_trusted_extension_origin("moz-extension://aaa"))
                # Token-authenticated origins are accepted and pinned.
                self.assertTrue(daemon._is_trusted_extension_origin("moz-extension://aaa", authenticated=True))
                daemon._remember_extension_id("aaa")
                self.assertTrue(os.path.isfile(pin_file))
                self.assertEqual(daemon._read_pinned_extension_ids(), frozenset({"aaa"}))
                # A different extension ID is rejected after the pin exists.
                self.assertFalse(daemon._is_trusted_extension_origin("chrome-extension://bbb", authenticated=True))

    def test_extension_origin_strict_mode_requires_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(daemon, "EXTENSION_ORIGIN_MODE", "strict"), \
                 patch.object(daemon, "ALLOWED_EXTENSION_IDS", ()), \
                 patch.object(daemon, "_pinned_extension_ids", None):
                self.assertFalse(daemon._is_trusted_extension_origin("moz-extension://aaa", authenticated=True))
            with patch.object(daemon, "EXTENSION_ORIGIN_MODE", "strict"), \
                 patch.object(daemon, "ALLOWED_EXTENSION_IDS", ("aaa",)), \
                 patch.object(daemon, "_pinned_extension_ids", None):
                self.assertTrue(daemon._is_trusted_extension_origin("moz-extension://AAA"))
                self.assertFalse(daemon._is_trusted_extension_origin("moz-extension://bbb"))

    def test_extension_origin_any_mode_trusts_all_extension_origins(self):
        with patch.object(daemon, "EXTENSION_ORIGIN_MODE", "any"), \
             patch.object(daemon, "ALLOWED_EXTENSION_IDS", ()):
            self.assertTrue(daemon._is_trusted_extension_origin("moz-extension://anything"))
            self.assertTrue(daemon._is_trusted_extension_origin("chrome-extension://other"))
            self.assertFalse(daemon._is_trusted_extension_origin("https://example.com"))

    def test_tailscale_proxy_uses_identity_and_never_returns_local_token(self):
        handler = self._handler("/health")
        handler.headers["Tailscale-User-Login"] = "person@example.test"
        with patch.object(handler, "_send_raw") as send:
            handler.do_GET()
        send.assert_called_once_with(200, {"ok": True, "service": "sleeper",
                                           "daemon_version": daemon.VERSION,
                                           "protocol_version": daemon.PROTOCOL_VERSION,
                                           "instance_id": daemon.INSTANCE_ID})

    def test_setup_page_is_available_only_through_tailscale(self):
        local = self._handler("/sleeper-setup")
        with patch.object(local, "_send") as send:
            local.do_GET()
        send.assert_called_once_with(404, {"ok": False, "error": "not found"})

        remote = self._handler("/sleeper-setup")
        remote.headers["Tailscale-User-Login"] = "person@example.test"
        with patch.object(remote, "_send_html") as send_html:
            remote.do_GET()
        self.assertEqual(send_html.call_args.args[0], 200)
        self.assertIn("Connecting Sleeper", send_html.call_args.args[1])

    def test_tailscale_websocket_accepts_challenge_response(self):
        class Socket:
            def __init__(self):
                self.request = SimpleNamespace(path="/ws", headers={"Origin": "moz-extension://test", "Tailscale-User-Login": "person@example.test"})
                self.frame = None
                self.closed = []
            async def send(self, raw):
                message = json.loads(raw)
                if message["type"] == "auth_challenge":
                    proof = hmac.new(b"test-token", f"ws:{message['challenge']}".encode(), hashlib.sha256).hexdigest()
                    self.frame = json.dumps({"type": "auth", "proof": proof})
            async def recv(self): return self.frame
            async def close(self, **kwargs): self.closed.append(kwargs)
            def __aiter__(self):
                async def empty():
                    if False: yield None
                return empty()

        socket = Socket()
        with patch.object(daemon, "ALLOW_ANY_EXTENSION", True), patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(daemon, "_connection_diagnostic", {"status": "no_attempt"}):
            asyncio.run(daemon.ws_handler(socket))
            diagnostic = daemon.connection_diagnostic()
        self.assertEqual(socket.closed, [])
        self.assertEqual(diagnostic, {"status": "disconnected"})

    def test_websocket_rejects_missing_origin_before_challenge(self):
        class Socket:
            def __init__(self):
                self.request = SimpleNamespace(headers={})
                self.sent = []
                self.closed = []
            async def send(self, raw): self.sent.append(raw)
            async def close(self, **kwargs): self.closed.append(kwargs)

        socket = Socket()
        with patch.object(daemon, "ALLOW_ANY_EXTENSION", True), \
             patch.object(daemon, "_connection_diagnostic", {"status": "no_attempt"}):
            accepted = asyncio.run(daemon._authenticate_ws(socket))
            diagnostic = daemon.connection_diagnostic()
        self.assertFalse(accepted)
        self.assertEqual(socket.sent, [])
        self.assertEqual(socket.closed, [{"code": 4003, "reason": "extension origin required"}])
        self.assertEqual(diagnostic,
                         {"status": "failed", "reason": "extension origin rejected"})

    def test_tailscale_websocket_rejects_fixed_protocol_token(self):
        class Socket:
            def __init__(self, frame):
                self.request = SimpleNamespace(path="/ws", headers={"Origin": "moz-extension://test", "Tailscale-User-Login": "person@example.test"})
                self.frame = frame
                self.closed = []
            async def send(self, raw): pass
            async def recv(self): return self.frame
            async def close(self, **kwargs): self.closed.append(kwargs)
            def __aiter__(self):
                async def empty():
                    if False: yield None
                return empty()

        socket = Socket('{"type":"auth","token":"tailscale"}')
        with patch.object(daemon, "ALLOW_ANY_EXTENSION", True), patch.object(daemon, "_token", return_value="test-token"), \
             patch.object(daemon, "_connection_diagnostic", {"status": "no_attempt"}):
            asyncio.run(daemon.ws_handler(socket))
            diagnostic = daemon.connection_diagnostic()
        self.assertEqual(socket.closed, [{"code": 4001, "reason": "bad token"}])
        self.assertEqual(diagnostic,
                         {"status": "failed", "reason": "authentication failed"})

    def test_tailscale_header_does_not_bypass_websocket_token(self):
        class Socket:
            def __init__(self):
                self.request = SimpleNamespace(path="/ws", headers={
                    "Origin": "moz-extension://test",
                    "Tailscale-User-Login": "person@example.test",
                })
                self.closed = []
                self.frame = '{}'
            async def send(self, raw): pass
            async def recv(self): return self.frame
            async def close(self, **kwargs): self.closed.append(kwargs)
            def __aiter__(self):
                async def empty():
                    if False: yield None
                return empty()

        socket = Socket()
        with patch.object(daemon, "_token", return_value="test-token"):
            asyncio.run(daemon.ws_handler(socket))
        self.assertEqual(socket.closed, [{"code": 4001, "reason": "bad token"}])

    def test_large_image_artifact_is_not_truncated_by_daemon_response(self):
        chunk = lambda kind, value: struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
        raw = b"".join(b"\0" + b"\x11" * 768 for _ in range(256))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 0)) + chunk(b"IEND", b"")
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        self.assertGreater(len(data_url), 65536)
        handler = daemon.ApiHandler.__new__(daemon.ApiHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: None
        handler.send_header = lambda key, value: None
        handler.end_headers = lambda: None
        handler._send(200, {"ok": True, "result": {"dataUrl": data_url}}, allow_image_artifacts=True)
        payload = json.loads(handler.wfile.getvalue())
        self.assertEqual(payload["result"]["dataUrl"], data_url)


if __name__ == "__main__":
    unittest.main()
