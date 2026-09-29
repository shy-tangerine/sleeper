"""CRITICAL-2 regression: dispatch budgets honor page-wait timeouts.

The 625c6d2 dispatch loop capped every attempt at COMMAND_TIMEOUT,
so a `wait` command whose content-script handler polls for 10-15s was
abandoned mid-wait: the daemon replied "timeout waiting for page" and
discarded the extension's eventual success. These tests pin the fix:
long-wait commands get a budget derived from the caller's timeout_ms, while
ordinary commands keep snappy pacing (2s per attempt, 2 attempts).
"""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))
import daemon


class FakeWaitSocket:
    """A connected "extension" whose page handler answers `wait` after delay."""

    def __init__(self, delay_s):
        self.delay_s = delay_s
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))
        frame = self.sent[-1]
        # Emulate the page-world wait handler: reply after the delay.
        asyncio.get_event_loop().call_later(
            self.delay_s,
            lambda: daemon._resolve_pending(self, {"id": frame["id"], "ok": True, "result": {"waited": self.delay_s}}),
        )


class CommandBudgetContract(unittest.TestCase):
    def test_long_wait_command_budget_covers_requested_timeout(self):
        # waitFor with a 10s request: budget must exceed the request instead
        # of clamping to the 4.5s per-attempt cap (the CRITICAL-2 defect).
        budget = daemon._command_budget("waitFor", {"timeout_ms": 10000})
        self.assertGreaterEqual(budget, 10.0)
        self.assertLessEqual(budget, daemon.HTTP_TIMEOUT)

    def test_maximum_wait_is_honored_and_excess_is_rejected(self):
        self.assertGreater(daemon._command_budget("waitXhr", {"timeout_ms": 60000}), 60)
        result = asyncio.run(daemon.dispatch_command("waitXhr", {"timeout_ms": 60001}))
        self.assertEqual(result["error"], "timeout_ms must be at most 60000")
        result = asyncio.run(daemon.dispatch_command("batch", {"actions": [
            {"cmd": "waitDownload", "args": {"timeout_ms": 60001}},
        ]}))
        self.assertEqual(result["error"], "timeout_ms must be at most 60000")

    def test_goto_budget_covers_navigation_settle_window(self):
        self.assertGreaterEqual(daemon._command_budget("goto", {}), 15.0)

    def test_batch_budget_sums_action_waits_and_retry_envelopes(self):
        actions = [
            {"cmd": "click", "args": {}},
            {"cmd": "waitFor", "args": {"timeout_ms": 5000}},
            {"cmd": "goto", "args": {"timeout_ms": 7000}},
        ]
        expected = sum(
            daemon._command_budget(action["cmd"], action["args"])
            for action in actions
        )
        self.assertEqual(daemon._command_budget("batch", {"actions": actions}), expected)

    def test_batch_budget_keeps_global_http_ceiling(self):
        actions = [{"cmd": "waitFor", "args": {"timeout_ms": 10 ** 9}}] * 50
        self.assertEqual(daemon._command_budget("batch", {"actions": actions}), daemon.HTTP_TIMEOUT)

    def test_short_command_keeps_default_budget(self):
        budget = daemon._command_budget("click", {})
        self.assertLessEqual(budget, daemon.HTTP_TIMEOUT)
        # Ordinary commands keep the default envelope exactly:
        # 2 attempts x 2s + 1 x 0.3s backoff = 4.3s.
        historical = daemon.COMMAND_TIMEOUT * daemon.COMMAND_MAX_ATTEMPTS + \
            daemon.COMMAND_RETRY_DELAY * (daemon.COMMAND_MAX_ATTEMPTS - 1)
        self.assertEqual(budget, historical)

    def test_unknown_command_never_exceeds_http_ceiling(self):
        for cmd in ("click", "readAll", "exec", "waitFor"):
            self.assertLessEqual(daemon._command_budget(cmd, {"timeout_ms": 10 ** 9}), daemon.HTTP_TIMEOUT)

    def test_slow_page_wait_is_not_abandoned(self):
        """End-to-end: a page that answers after 8s still gets its reply through.

        This is the exact scenario from the review notes' live repro: request
        `wait timeout_ms=10000`, page answers at 8s. The old code returned
        {"ok": False, "error": "timeout waiting for page"} at ~4.5s.
        """
        old_reg = daemon._reg
        daemon._reg = {"profiles": {}}
        old_pending = dict(daemon.pending)
        try:
            ws = FakeWaitSocket(delay_s=8.0)
            daemon.upsert(ws, {"profile": "default", "browser_id": "one"})
            started = time.monotonic()
            result = asyncio.run(daemon.dispatch_command("waitFor", {"timeout_ms": 10000}))
            elapsed = time.monotonic() - started
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result["result"]["waited"], 8.0)
            # The reply must arrive after the page's delay (8s), not at the
            # old 4.5s cap, and within the requested 10s budget.
            self.assertGreater(elapsed, 7.5)
            self.assertLess(elapsed, 10.0)
        finally:
            daemon._reg = old_reg
            daemon.pending.clear()
            daemon.pending.update(old_pending)

    def test_wait_beyond_requested_timeout_times_out(self):
        """A 2s page delay on a 1s requested wait still times out as requested."""
        old_reg = daemon._reg
        daemon._reg = {"profiles": {}}
        old_pending = dict(daemon.pending)
        try:
            ws = FakeWaitSocket(delay_s=2.0)
            daemon.upsert(ws, {"profile": "default", "browser_id": "one"})
            started = time.monotonic()
            result = asyncio.run(daemon.dispatch_command("waitFor", {"timeout_ms": 1000}))
            elapsed = time.monotonic() - started
            self.assertFalse(result.get("ok"))
            self.assertIn("timeout", result["error"])
            # Honors the caller's 1s budget (plus retry-envelope slack), NOT
            # the 16s long-wait default and not the old 4.5s cap either.
            self.assertGreater(elapsed, 0.9)
            self.assertLess(elapsed, 4.0)
        finally:
            daemon._reg = old_reg
            daemon.pending.clear()
            daemon.pending.update(old_pending)

    def test_non_wait_command_times_out_at_snappy_pace(self):
        """Ordinary commands keep the tight default: no 20s hangs for `click`."""
        old_reg = daemon._reg
        daemon._reg = {"profiles": {}}
        old_pending = dict(daemon.pending)
        try:
            ws = FakeWaitSocket(delay_s=30.0)  # never answers in time
            daemon.upsert(ws, {"profile": "default", "browser_id": "one"})
            started = time.monotonic()
            result = asyncio.run(daemon.dispatch_command("click", {"selector": "#a"}))
            elapsed = time.monotonic() - started
            self.assertFalse(result.get("ok"))
            self.assertIn("timeout", result["error"])
            # Default envelope: 2 attempts x 2s + 1 x 0.3s = 4.3s; the point
            # is it must be far below the long-wait default and bounded.
            self.assertLess(elapsed, 5.0)
        finally:
            daemon._reg = old_reg
            daemon.pending.clear()
            daemon.pending.update(old_pending)


if __name__ == "__main__":
    unittest.main()
