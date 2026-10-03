import json
import asyncio
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))
import daemon


class RoutingContract(unittest.TestCase):
    def setUp(self):
        self.old = daemon._reg
        self.old_diagnostic = daemon._connection_diagnostic
        daemon._reg = {"profiles": {}}
        daemon._connection_diagnostic = {"status": "no_attempt"}

    def tearDown(self):
        daemon._reg = self.old
        daemon._connection_diagnostic = self.old_diagnostic

    def test_duplicate_profile_is_observable_and_has_no_active_route(self):
        daemon.upsert(object(), {"profile": "work", "browser_id": "a"})
        daemon.upsert(object(), {"profile": "work", "browser_id": "b"})
        status = daemon.profiles_status()["work"]
        self.assertTrue(status["ambiguous"])
        self.assertEqual(status["browser_clients"], 2)
        self.assertIsNone(daemon.active("work"))
        result, routed = asyncio.run(daemon._dispatch_once("state", {}, profile="work"))
        self.assertFalse(routed)
        self.assertIn("ambiguous", result["error"])

    def test_reconnect_rename_removes_old_profile_route(self):
        ws = object()
        daemon.upsert(ws, {"profile": "old", "browser_id": "same"})
        daemon.upsert(ws, {"profile": "new", "browser_id": "same"})
        self.assertFalse(daemon._clients("old"))
        self.assertEqual(daemon.profiles_status()["new"]["browsers"][0]["id"], "same")

    def test_single_profile_remains_routable(self):
        ws = object()
        daemon.upsert(ws, {"profile": "default", "browser_id": "one"})
        self.assertIs(daemon.active("default")["ws"], ws)
        self.assertFalse(daemon.profiles_status()["default"]["ambiguous"])

    def test_sessions_reports_daemon_addon_and_protocol_versions(self):
        daemon.upsert(object(), {"profile": "work", "browser_id": "one",
                                 "addon_version": "2.0.1", "protocol_version": daemon.PROTOCOL_VERSION})
        result = asyncio.run(daemon.dispatch_command("sessions", {}))
        browser = result["profiles"]["work"]["browsers"][0]
        self.assertEqual(result["daemon_version"], daemon.VERSION)
        self.assertEqual(result["protocol_version"], daemon.PROTOCOL_VERSION)
        self.assertEqual(browser["addon_version"], "2.0.1")
        self.assertTrue(browser["compatible"])
        self.assertEqual(result["browser_connection"], {"status": "connected"})

    def test_sessions_distinguishes_no_connection_attempt(self):
        result = asyncio.run(daemon.dispatch_command("sessions", {}))
        self.assertEqual(result["browser_connection"], {"status": "no_attempt"})

    def test_partial_hello_preserves_browser_identity_and_profile(self):
        ws = object()
        daemon.upsert(ws, {"profile": "work", "browser_id": "one", "url": "https://before"})
        daemon.upsert(ws, {"active": True, "title": "Updated"})
        client = daemon.active("work")
        self.assertEqual(client["browser_id"], "one")
        self.assertEqual(client["url"], "https://before")
        self.assertEqual(client["title"], "Updated")

    def test_sessions_is_daemon_local_inventory(self):
        class Ws:
            def __init__(self): self.sent = False
            async def send(self, raw): self.sent = True

        ws = Ws()
        daemon.upsert(ws, {"profile": "duplicate", "browser_id": "one"})
        daemon.upsert(object(), {"profile": "duplicate", "browser_id": "two"})
        result = asyncio.run(daemon.dispatch_command("sessions", {}, profile="missing"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["profiles"]["duplicate"]["ambiguous"])
        self.assertFalse(result["profiles"].get("missing", {}).get("connected", False))
        self.assertFalse(ws.sent)

    def test_extension_forwards_tab_selector_to_browser(self):
        class Ws:
            async def send(self, raw):
                message = json.loads(raw)
                self.message = message
                daemon.pending[daemon._msg_key(self, message["id"])].set_result({"ok": True})

        ws = Ws()
        daemon.upsert(ws, {"profile": "firefox", "browser_id": "one",
                           "client_type": "extension"})
        result, routed = asyncio.run(
            daemon._dispatch_once("click", {"selector": "#go", "allow_user_tab": True}, tab="id:23", profile="firefox"))
        self.assertTrue(routed)
        self.assertTrue(result["ok"])
        self.assertEqual(ws.message["args"], {"selector": "#go", "allow_user_tab": True, "tab": "id:23"})

    def test_distinct_stable_ids_route_independently(self):
        first, second = object(), object()
        daemon.upsert(first, {"profile": "install-a", "browser_id": "install-a"})
        daemon.upsert(second, {"profile": "install-b", "browser_id": "install-b"})
        self.assertIs(daemon.active("install-a")["ws"], first)
        self.assertIs(daemon.active("install-b")["ws"], second)
        self.assertFalse(daemon.profiles_status()["install-a"]["ambiguous"])

    def test_default_route_uses_the_only_connected_browser_id(self):
        browser = object()
        daemon.upsert(browser, {"profile": "install-a", "browser_id": "install-a"})
        self.assertIs(daemon.active()["ws"], browser)

    def test_default_route_with_multiple_browser_ids_requires_discovery(self):
        daemon.upsert(object(), {"profile": "install-a", "browser_id": "install-a"})
        daemon.upsert(object(), {"profile": "install-b", "browser_id": "install-b"})
        result, routed = asyncio.run(daemon._dispatch_once("state", {}))
        self.assertFalse(routed)
        self.assertIn("sessions", result["error"])

    def test_batch_runs_in_order_and_stops_at_first_failure(self):
        class Ws:
            def __init__(self):
                self.commands = []

            async def send(self, raw):
                message = json.loads(raw)
                self.commands.append(message["cmd"])
                response = ({"ok": False, "error": "missing"}
                            if message["cmd"] == "click" else {"ok": True, "result": message["cmd"]})
                daemon.pending[daemon._msg_key(self, message["id"])].set_result(response)

        ws = Ws()
        daemon.upsert(ws, {"profile": "mobile", "browser_id": "phone",
                           "client_type": "extension"})
        result = asyncio.run(daemon.dispatch_command("batch", {
            "actions": [
                {"cmd": "goto", "args": {"url": "https://example.test"}},
                {"cmd": "click", "args": {"selector": "#missing"}},
                {"cmd": "read", "args": {"selector": "h1"}},
            ],
        }, profile="mobile"))

        self.assertFalse(result["ok"])
        self.assertEqual(ws.commands, ["goto", "click"])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["failed_at"], 1)
        self.assertEqual([item["cmd"] for item in result["results"]], ["goto", "click"])
        self.assertTrue(all(isinstance(item["duration_ms"], int) for item in result["results"]))

    def test_batch_rejects_nested_batches_without_routing(self):
        result = asyncio.run(daemon.dispatch_command("batch", {
            "actions": [{"cmd": "batch", "args": {"actions": []}}],
        }))
        self.assertFalse(result["ok"])
        self.assertIn("nested", result["error"])
