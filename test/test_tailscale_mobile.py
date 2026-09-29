"""Tailscale-only mobile setup behavior."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "tailscale_mobile", ROOT / "cli" / "tailscale_mobile.py"
)
tailscale_mobile = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = tailscale_mobile
SPEC.loader.exec_module(tailscale_mobile)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[1:] == ["status", "--json"]:
            return tailscale_mobile.CommandResult(
                0,
                json.dumps(
                    {
                        "BackendState": "Running",
                        "Self": {"DNSName": "desktop.example.ts.net."},
                    }
                ),
                "",
            )
        if args[1:] == ["serve", "status", "--json"]:
            return tailscale_mobile.CommandResult(0, "{}", "")
        return tailscale_mobile.CommandResult(0, "", "")


class TailscaleMobileTest(unittest.TestCase):
    def test_setup_uses_two_tailnet_only_https_proxies(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("pairing-secret\n", encoding="utf-8")
            result = tailscale_mobile.setup(
                runner=runner, executable="tailscale", token_file=str(token_file)
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["setup_url"],
            "https://desktop.example.ts.net:8790/sleeper-setup#token=pairing-secret",
        )
        self.assertNotIn("pairing-secret", result["http_url"])
        self.assertNotIn("pairing-secret", result["websocket_url"])
        self.assertEqual(
            runner.calls[-2:],
            [
                [
                    "tailscale",
                    "serve",
                    "--bg",
                    "--https=8790",
                    "http://127.0.0.1:8790",
                ],
                [
                    "tailscale",
                    "serve",
                    "--bg",
                    "--https=8789",
                    "http://127.0.0.1:8789",
                ],
            ],
        )

    def test_setup_requires_daemon_token(self):
        result = tailscale_mobile.setup(
            runner=FakeRunner(), executable="tailscale", token_file="/missing/token"
        )
        self.assertFalse(result["ok"])
        self.assertNotIn("pairing-secret", result["error"])

    def test_disable_removes_only_sleeper_ports(self):
        runner = FakeRunner()
        result = tailscale_mobile.disable(runner=runner, executable="tailscale")

        self.assertTrue(result["ok"])
        self.assertEqual(
            runner.calls,
            [
                ["tailscale", "serve", "--https=8790", "off"],
                ["tailscale", "serve", "--https=8789", "off"],
            ],
        )

    def test_setup_refuses_logged_out_tailscale(self):
        def runner(args):
            return tailscale_mobile.CommandResult(
                0, json.dumps({"BackendState": "NeedsLogin", "Self": {}}), ""
            )

        result = tailscale_mobile.setup(runner=runner, executable="tailscale")

        self.assertFalse(result["ok"])
        self.assertIn("tailscale up", result["error"])

    def test_status_reports_unreadable_serve_json(self):
        class InvalidServeStatusRunner(FakeRunner):
            def __call__(self, args):
                if args[1:] == ["serve", "status", "--json"]:
                    self.calls.append(args)
                    return tailscale_mobile.CommandResult(0, "not-json", "")
                return super().__call__(args)

        result = tailscale_mobile.status(
            runner=InvalidServeStatusRunner(), executable="tailscale"
        )

        self.assertFalse(result["ok"])
        self.assertIsNone(result["serve"])
        self.assertEqual(
            result["error"], "Tailscale returned an unreadable Serve status."
        )


if __name__ == "__main__":
    unittest.main()
