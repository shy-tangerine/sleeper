#!/usr/bin/env python3
"""Local HTTP-to-WebSocket relay for Sleeper browser extensions.

One daemon serves multiple named browser profiles. Each extension registers
its profile and browser identity. Commands select a profile and an optional
browser tab; duplicate connected profile names are rejected. The daemon-local
`sessions` command returns routing inventory without sending browser actions.

The HTTP command endpoint binds to loopback on port 8790 and rejects browser
Origin headers. Extensions authenticate their WebSocket connection on port
8789 with a shared local token. These are trusted local automation interfaces.
"""
import asyncio
import concurrent.futures
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import stat
import sys
import threading
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets
if __package__:
    from .redaction import sanitize
else:
    from redaction import sanitize
from websockets.exceptions import ConnectionClosed
from websockets.server import ServerProtocol

logger = logging.getLogger("sleeper.daemon")

VERSION = "2.0.1"
PROTOCOL_VERSION = 2

WS_PORT = int(os.environ.get("SLEEPER_WS_PORT", "8789"))
HTTP_PORT = int(os.environ.get("SLEEPER_HTTP_PORT", "8790"))
BIND_HOST = os.environ.get("SLEEPER_BIND_HOST", "127.0.0.1").strip()
# Tests and multi-instance users can isolate credentials without changing HOME.
# The default preserves the established per-user token location.
TOKEN_FILE = os.path.expanduser(os.environ.get("SLEEPER_TOKEN_FILE", "~/.config/browser-sleeper-token"))
ALLOWED_PROCESSES = frozenset(p for p in os.environ.get("SLEEPER_ALLOWED_PROCESSES", "").split(":") if p)
_API_HOSTS_RAW = os.environ.get("SLEEPER_API_HOSTS")

COMMAND_TIMEOUT = 2.0
COMMAND_MAX_ATTEMPTS = 2
COMMAND_RETRY_DELAY = 0.3
# Total budget for a /command request. Page-wait commands may legitimately run
# to their requested timeout_ms (10-15s default in the content-script wait
# handlers), so long-wait commands get a per-command larger budget (see
# _command_budget). HTTP_TIMEOUT stays a hard ceiling for the HTTP thread.
LONG_WAIT_COMMANDS = frozenset({
    "waitFor", "waitUntil", "waitText", "waitDialog", "waitUrl",
    "waitDownload", "waitXhr", "scrollUntil", "goto",
    # Snake_case wire names used by the bash CLI, the Python CLI (which has no
    # wait_url alias) and the MCP bridge (sleeper_wait_url -> "wait_url").
    "wait_for", "wait_until", "wait_text", "wait_dialog", "wait_url",
    "wait_download", "wait_xhr", "scroll_until",
})
COMMAND_TIMEOUT_LONG = 16.0
MAX_WAIT_MS = 60000
HTTP_TIMEOUT = MAX_WAIT_MS / 1000 + COMMAND_RETRY_DELAY * COMMAND_MAX_ATTEMPTS + 0.4
ALLOWED_EXTENSION_IDS = tuple(s.strip() for s in os.environ.get("SLEEPER_ALLOWED_EXTENSION_IDS", "").split(",") if s.strip())
# Extension-origin policy (issue #46 hardening):
#   strict   — only UUIDs in SLEEPER_ALLOWED_EXTENSION_IDS connect
#              (SLEEPER_ALLOW_ANY_EXTENSION=false|no|off|0).
#   pin      — the FIRST extension origin that proves possession of the daemon
#              token is remembered (SLEEPER_EXTENSION_PIN_FILE) and later
#              connections from a different extension ID are rejected. This is
#              the release default: a fresh install pairs automatically (the
#              Zen/Firefox-fork fix), but a second dev-build extension cannot
#              attach silently afterwards.
#   any      — every genuine moz-extension:// / chrome-extension:// origin is
#              trusted (development only; webpages can never present such an
#              origin) (SLEEPER_ALLOW_ANY_EXTENSION=true|yes|on|1).
pin_path = os.environ.get("SLEEPER_EXTENSION_PIN_FILE", "~/.config/browser-sleeper-extension-pin")
EXTENSION_PIN_FILE = os.path.expanduser(pin_path)
_ALLOW_ANY_RAW = os.environ.get("SLEEPER_ALLOW_ANY_EXTENSION", "").strip().lower()
if _ALLOW_ANY_RAW in {"0", "false", "no", "off"}:
    EXTENSION_ORIGIN_MODE = "strict"
elif _ALLOW_ANY_RAW in {"1", "true", "yes", "on"}:
    EXTENSION_ORIGIN_MODE = "any"
else:
    EXTENSION_ORIGIN_MODE = "pin"
# Backwards-compatible flag for tests and callers that used the boolean.
ALLOW_ANY_EXTENSION = EXTENSION_ORIGIN_MODE == "any"
_extension_pin_lock = threading.Lock()
_pinned_extension_ids = None


def _read_pinned_extension_ids():
    global _pinned_extension_ids
    if _pinned_extension_ids is not None:
        return _pinned_extension_ids
    try:
        with open(EXTENSION_PIN_FILE, encoding="utf-8") as f:
            ids = frozenset(line.strip().lower() for line in f if line.strip())
    except OSError:
        ids = frozenset()
    _pinned_extension_ids = ids
    return ids


def _remember_extension_id(extension_id):
    """Pin the first extension ID that completed token authentication.

    Later IDs are ignored: replacing the pin requires deleting the pin file
    (a deliberate local action) or running with an explicit allowlist.
    """
    global _pinned_extension_ids
    with _extension_pin_lock:
        pinned = _read_pinned_extension_ids()
        if extension_id in pinned:
            return
        if pinned:
            logger.warning("refusing to pin extension id %s: extension id(s) %s already pinned", extension_id, ",".join(sorted(pinned)))
            return
        directory = os.path.dirname(EXTENSION_PIN_FILE) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".sleeper-ext-pin-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for known in sorted(pinned | {extension_id}):
                    f.write(known + "\n")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, EXTENSION_PIN_FILE)
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
        _pinned_extension_ids = frozenset(pinned | {extension_id})
def configured_api_hosts():
    raw = _API_HOSTS_RAW if _API_HOSTS_RAW is not None else "chatgpt.com,www.chatgpt.com"
    hosts = [h.strip().lower() for h in raw.split(",") if h.strip()]
    if any("*" in h or "/" in h or ":" in h or not re.match(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", h) for h in hosts):
        raise ValueError("invalid API host allowlist")
    return hosts


def is_loopback_host(host):
    """Return true only for loopback addresses/names, never private LAN IPs."""
    candidate = str(host or "").strip().strip("[]").lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _extension_id(origin):
    if not origin:
        return None
    value = origin.strip().lower()
    if value.startswith("moz-extension://"):
        rest = value[len("moz-extension://"):]
    elif value.startswith("chrome-extension://"):
        rest = value[len("chrome-extension://"):]
    else:
        return None
    return (rest.split("/", 1)[0] or "").strip()


def _is_trusted_extension_origin(origin, authenticated=False):
    """Accept extension-scheme origins per the configured origin mode.

    Origin is only an additional WebSocket check; every peer must also
    prove possession of the daemon token. Set SLEEPER_ALLOW_ANY_EXTENSION=false
    plus SLEEPER_ALLOWED_EXTENSION_IDS for a fixed allowlist, or true to trust
    every genuine extension origin (development only).
    """
    extension_id = _extension_id(origin)
    if not extension_id:
        return False
    if ALLOWED_EXTENSION_IDS:
        return extension_id in ALLOWED_EXTENSION_IDS
    if EXTENSION_ORIGIN_MODE == "strict":
        return False
    if EXTENSION_ORIGIN_MODE == "any":
        return True
    # "pin" mode: the first token-authenticated extension is remembered;
    # later connections from a different extension ID are rejected.
    if authenticated:
        pinned = _read_pinned_extension_ids()
        return not pinned or extension_id in pinned
    return bool(_read_pinned_extension_ids())


def validate_network_config(host=BIND_HOST):
    """Keep the daemon private; Tailscale Serve is the only mobile listener."""
    if not host:
        raise ValueError("SLEEPER_BIND_HOST must not be empty")
    if not is_loopback_host(host):
        raise ValueError("Sleeper daemon must remain loopback-only; use Tailscale Serve for mobile access")
    return True


def _read_existing_token():
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(TOKEN_FILE, flags)
    except OSError:
        return None
    try:
        st = os.fstat(descriptor)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            return None
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, encoding="utf-8", closefd=False) as f:
            tok = f.read().strip()
        return tok
    finally:
        os.close(descriptor)


def _write_token(token):
    directory = os.path.dirname(TOKEN_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".sleeper-token-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token + "\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, TOKEN_FILE)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def get_token():
    # Loopback extensions use this local token. It never crosses Tailscale.
    existing = _read_existing_token()
    if existing:
        return existing
    tok = secrets.token_urlsafe(16)
    _write_token(tok)
    return tok


# Resolve the auth token lazily so importing this module never touches the
# filesystem (previously `TOKEN = get_token()` ran at import time and created
# ~/.config/browser-sleeper-token as a side effect).
_TOKEN_CACHE = None


def _token():
    global _TOKEN_CACHE
    if _TOKEN_CACHE is None:
        _TOKEN_CACHE = get_token()
    return _TOKEN_CACHE


LOOPBACK_BIND = validate_network_config()
INSTANCE_ID = secrets.token_hex(16)
_auth_nonces = {}
_auth_nonce_lock = threading.Lock()
AUTH_WINDOW_SECONDS = 300
# ponytail: 65,536-entry cap; reject at capacity rather than evict live
# nonces. Raise only if measured legitimate bursts require it.
MAX_AUTH_NONCES = 65536


def token_matches(candidate):
    """Constant-time comparison that safely rejects malformed text input."""
    return isinstance(candidate, str) and secrets.compare_digest(candidate.encode("utf-8"), _token().encode("utf-8"))


def daemon_identity_proof(nonce):
    if not re.fullmatch(r"[0-9a-f]{32,128}", str(nonce or "")):
        return None
    message = f"{nonce}:{INSTANCE_ID}".encode()
    return hmac.new(_token().encode(), message, hashlib.sha256).hexdigest()


def request_proof(nonce, timestamp, method, path, body=b""):
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{INSTANCE_ID}\n{nonce}\n{timestamp}\n{method}\n{path}\n{body_hash}".encode()
    return hmac.new(_token().encode(), message, hashlib.sha256).hexdigest()


def request_preamble(nonce, timestamp, method, path, content_length):
    message = f"{INSTANCE_ID}\n{nonce}\n{timestamp}\n{method}\n{path}\n{content_length}".encode()
    return hmac.new(_token().encode(), message, hashlib.sha256).hexdigest()


def consume_request_proof(instance_id, nonce, timestamp, proof, method, path, body=b""):
    if instance_id != INSTANCE_ID or not re.fullmatch(r"[0-9a-f]{32,128}", str(nonce or "")):
        return False
    try:
        signed_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if abs(now - signed_at) > AUTH_WINDOW_SECONDS:
        return False
    expected = request_proof(nonce, signed_at, method, path, body)
    if not isinstance(proof, str) or not secrets.compare_digest(proof, expected):
        return False
    with _auth_nonce_lock:
        stale = [key for key, seen_at in _auth_nonces.items() if now - seen_at > AUTH_WINDOW_SECONDS]
        for key in stale:
            del _auth_nonces[key]
        if nonce in _auth_nonces:
            return False
        if len(_auth_nonces) >= MAX_AUTH_NONCES:
            return False
        _auth_nonces[nonce] = signed_at
    return True


# ---- connection registry -------------------------------------------------
# Each profile may have several connections, but actions require exactly one.
_reg = {"profiles": {}}  # {profile: [{ws, url, title, active_seq, conn_seq, profile}]}
_connection_diagnostic = {"status": "no_attempt"}
_seq_counter = [0]
_state_lock = threading.Lock()
_pending_lock = threading.Lock()
_seq_lock = threading.Lock()


def _seq():
    with _seq_lock:
        _seq_counter[0] += 1
        return _seq_counter[0]


def _clients(profile):
    """Return (possibly empty) browser clients for one Sleeper profile."""
    with _state_lock:
        return list(_reg["profiles"].setdefault(profile, []))


def _all_clients():
    with _state_lock:
        return [client for clients in _reg["profiles"].values() for client in clients]


def _client_identity(info):
    return str(info.get("browser_id") or "").strip()[:80]


def _detach_locked(ws):
    """Drop one WebSocket connection from the registry; callers hold _state_lock."""
    for profile, clients in list(_reg["profiles"].items()):
        remaining = [c for c in clients if c["ws"] is not ws]
        if remaining:
            _reg["profiles"][profile] = remaining
        else:
            _reg["profiles"].pop(profile, None)


def _detach(ws):
    with _state_lock:
        _detach_locked(ws)


def _client_record(ws, info, existing):
    """Build one registry entry; reconnects carry forward unknown fields."""
    return {
        "ws": ws, "profile": str(info.get("profile") or (existing or {}).get("profile") or "default"),
        "browser_id": _client_identity(info) or (existing or {}).get("browser_id", ""),
        "client_type": str(info.get("client_type") or (existing or {}).get("client_type", "")).strip()[:40],
        "addon_version": str(info.get("addon_version") or (existing or {}).get("addon_version", "unknown")).strip()[:40],
        "source_id": str(info.get("source_id") or (existing or {}).get("source_id", "")).strip()[:80],
        "protocol_version": info.get("protocol_version", (existing or {}).get("protocol_version")),
        "url": info.get("url", (existing or {}).get("url", "")),
        "title": info.get("title", (existing or {}).get("title", "")),
        "active_seq": _seq() if info.get("active") else (existing or {}).get("active_seq", 0),
        "conn_seq": _seq(),
    }


def upsert(ws, info):
    with _state_lock:
        existing = next((c for clients in _reg["profiles"].values() for c in clients if c["ws"] is ws), None)
        record = _client_record(ws, info, existing)
        # Remove before appending only when a reconnect explicitly renames, while
        # preserving partial focus/url updates from the same browser client.
        _detach_locked(ws)
        _reg["profiles"].setdefault(record["profile"], []).append(record)
        _connection_diagnostic.clear()
        _connection_diagnostic["status"] = "connected"


def remove(ws):
    with _state_lock:
        _detach_locked(ws)
        if not any(_reg["profiles"].values()) and _connection_diagnostic.get("status") in {"authenticated", "connected"}:
            _connection_diagnostic.clear()
            _connection_diagnostic["status"] = "disconnected"


def _record_connection(status, reason=None):
    with _state_lock:
        _connection_diagnostic.clear()
        _connection_diagnostic["status"] = status
        if reason:
            _connection_diagnostic["reason"] = reason


def connection_diagnostic():
    with _state_lock:
        if any(_reg["profiles"].values()):
            return {"status": "connected"}
        return dict(_connection_diagnostic)


def active(profile="default"):
    # Backward-compatible default: legacy CLI/MCP calls without a target route
    # to the sole connected installation. More than one installation remains
    # fail-closed so callers must select an ID from `sessions`.
    if profile == "default" and not _clients(profile):
        connected = _all_clients()
        return connected[0] if len(connected) == 1 else None
    clients = _clients(profile)
    # A profile name is a routing boundary, not a load-balancing group.
    return clients[0] if len(clients) == 1 else None


def tabs(profile="default"):
    selected = active(profile)
    return [{"url": c["url"], "title": c["title"], "active": c is selected,
             "browser_id": c.get("browser_id") or "unidentified"}
            for c in _clients(profile)]


def profiles_status():
    """Observable profile routing state; ambiguous profiles are fail-closed."""
    with _state_lock:
        snapshot = {profile: list(clients) for profile, clients in _reg["profiles"].items()}
    return {profile: {"connected": bool(clients), "browser_clients": len(clients),
                      "ambiguous": len(clients) > 1,
                      "browsers": [{"id": c.get("browser_id") or "unidentified",
                                    "addon_version": c.get("addon_version") or "unknown",
                                    "source_id": c.get("source_id") or "",
                                    "protocol_version": c.get("protocol_version"),
                                    "compatible": c.get("protocol_version") == PROTOCOL_VERSION} for c in clients],
                      "tabs": len(clients)}
            for profile, clients in snapshot.items()}


# ---- routing -----------------------------------------------------
pending = {}  # (id(ws), msg_id) -> future

# Error substrings that mean the target page / content script was not
# reachable yet (session-restore in progress, tab just navigated, content
# script not injected, active tab not focused). These are transient and worth
# retrying with backoff against a known tab (G5).
_RETRYABLE_ERRORS = ("could not establish connection",
                     "receiving end does not exist",
                     "no active tab")


def _retryable(err):
    if not isinstance(err, str):
        return False
    e = err.lower()
    return any(sub in e for sub in _RETRYABLE_ERRORS)


def _msg_key(ws, mid):
    return id(ws), mid


def _resolve_dispatch_client(clients, tab, profile):
    """Pick the WS client a command should go to; (client, error_payload).

    Exactly one of the two is returned. An extension websocket represents its
    whole browser profile, so its tab selector is forwarded to the extension
    instead of being treated as a websocket index.
    """
    if clients[0].get("client_type") == "extension":
        return clients[0], None
    if tab is not None:
        for i, c in enumerate(clients):
            if str(i) == str(tab) or (tab and tab in c["url"]):
                return c, None
        return None, {"ok": False, "error": "tab %s is not reachable" % tab}
    target = active(profile)
    if target is None:
        return None, {"ok": False, "error": "no active tab"}
    return target, None


async def _send_and_wait(ws, msg_id, cmd, outbound_args, timeout):
    """Send one framed command and await its reply; cleanup is guaranteed.

    A timeout still counts as "had target" (True) because the client was
    reached and may yet answer — that distinction drives retry policy.
    """
    fut = asyncio.get_event_loop().create_future()
    key = _msg_key(ws, msg_id)
    with _pending_lock:
        pending[key] = fut
    try:
        await ws.send(json.dumps({"id": msg_id, "cmd": cmd, "args": outbound_args}))
        return await asyncio.wait_for(fut, timeout), True
    except asyncio.TimeoutError:
        if not fut.done():
            fut.cancel()
        return {"ok": False, "error": "timeout waiting for page"}, True
    finally:
        with _pending_lock:
            pending.pop(key, None)


async def _dispatch_once(cmd, args, tab=None, timeout=COMMAND_TIMEOUT, profile="default"):
    """One dispatch attempt to a resolved WS client for `profile`.

    Returns (result, had_target). had_target is True when a specific client
    was resolved (via the `tab` param or the active tab) and False when there
    was no client to route to (dormant, or `tab` not found). Retrying only
    makes sense when had_target is True.
    """
    clients = _clients(profile)
    if profile == "default" and not clients:
        clients = _all_clients()
    if not clients:
        return {"ok": False,
                "error": "no browser connected; call sessions to discover browser IDs"}, False
    if len(clients) > 1:
        return {"ok": False, "error": "ambiguous browser target; call sessions and select a browser ID"}, False
    target, error = _resolve_dispatch_client(clients, tab, profile)
    if error is not None:
        return error, False
    msg_id = _seq()
    if timeout <= 0:
        return {"ok": False, "error": "timeout waiting for page"}, False
    outbound_args = dict(args or {})
    if tab is not None:
        outbound_args["tab"] = tab
    return await _send_and_wait(target["ws"], msg_id, cmd, outbound_args, timeout)


def _validate_batch_actions(args):
    """Return an error payload for an invalid batch request, else None.

    Batch is a relay of user-supplied commands, so every action is checked
    before the first one runs: shape, count, no nesting, object args.
    """
    actions = args.get("actions") if isinstance(args, dict) else None
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "error": "batch actions must be a non-empty array"}
    if len(actions) > 50:
        return {"ok": False, "error": "batch is limited to 50 actions"}
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("cmd"), str):
            return {"ok": False, "error": "each batch action requires a command"}
        if action["cmd"] == "batch":
            return {"ok": False, "error": "nested batches are not supported"}
        if "args" in action and not isinstance(action["args"], dict):
            return {"ok": False, "error": "each batch action args value must be an object"}
    return None


async def _run_batch(args, tab, timeout, max_attempts, retry_delay, profile):
    """Execute validated batch actions in order, honoring stop_on_error.

    Stop-on-failure is the default; a caller may relax it with
    stop_on_error:false to collect every result in one round trip.
    """
    actions = args["actions"]
    results = []
    failed_at = None
    stop_on_error = args.get("stop_on_error", True) is not False
    deadline = time.monotonic() + timeout
    for index, action in enumerate(actions):
        started = time.monotonic()
        remaining = max(0, deadline - started)
        action_budget = min(
            remaining,
            _command_budget(action["cmd"], action.get("args") or {}),
        )
        response = await dispatch_command(
            action["cmd"], action.get("args") or {},
            tab=action.get("tab", tab), timeout=action_budget,
            max_attempts=max_attempts, retry_delay=retry_delay, profile=profile,
        )
        if not isinstance(response, dict):
            response = {"ok": False, "error": "invalid browser response"}
        item = {"index": index, "cmd": action["cmd"],
                "duration_ms": max(0, round((time.monotonic() - started) * 1000))}
        item.update(response)
        results.append(item)
        if response.get("ok") is False and failed_at is None:
            failed_at = index
            if stop_on_error:
                break
    output = {"ok": failed_at is None, "completed": len(results), "results": results}
    if failed_at is not None:
        output["failed_at"] = failed_at
    return output


def _requested_wait_ms(args):
    """Read the caller's requested wait budget (timeout_ms / legacy timeout)."""
    if not isinstance(args, dict):
        return None
    for key in ("timeout_ms", "timeout"):
        value = args.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return value
        if isinstance(value, str) and value.replace(".", "", 1).isdigit() and float(value) > 0:
            return float(value)
    return None


def _default_budget(cmd):
    """Total budget when the caller did not request a timeout.

    Ordinary commands keep the short envelope (2 attempts x 2s + one 0.3s
    backoff = 4.3s total across all attempts); long-wait commands
    default to 16s because their content-script handlers poll for 10-15s by
    default. dispatch_command allots each attempt what remains of the total,
    so a hung first attempt consumes the envelope rather than being clamped
    to a smaller per-attempt cap.
    """
    return COMMAND_TIMEOUT_LONG if cmd in LONG_WAIT_COMMANDS else (
        COMMAND_TIMEOUT * COMMAND_MAX_ATTEMPTS + COMMAND_RETRY_DELAY * (COMMAND_MAX_ATTEMPTS - 1)
    )


def _command_budget(cmd, args):
    """Total dispatch budget (seconds) for one command.

    CRITICAL-2: the per-attempt cap must never truncate a page wait. Commands
    whose handler legitimately polls the page (waitFor/waitUrl/waitDialog/...)
    get a budget driven by their requested timeout_ms (default 16s, capped at
    HTTP_TIMEOUT); batches sum those per-action envelopes before applying the
    same global ceiling. Everything else keeps the short 4.3s total envelope.
    """
    if cmd == "batch" and isinstance(args, dict) and isinstance(args.get("actions"), list):
        # Batch actions are validated before dispatch. Sum each action's full
        # retry envelope, then keep the daemon-wide HTTP ceiling authoritative.
        return min(HTTP_TIMEOUT, sum(
            _command_budget(action["cmd"], action.get("args") or {})
            for action in args["actions"]
            if isinstance(action, dict) and isinstance(action.get("cmd"), str)
        ))
    if cmd in LONG_WAIT_COMMANDS:
        requested = _requested_wait_ms(args)
        if requested is not None:
            # Convert the handler's own poll budget to seconds and leave the
            # retry envelope room on top so the first attempt always covers it.
            return min(HTTP_TIMEOUT, requested / 1000.0 + COMMAND_RETRY_DELAY * COMMAND_MAX_ATTEMPTS)
        return COMMAND_TIMEOUT_LONG
    return _default_budget(cmd)


def _wait_timeout_error(cmd, args):
    if cmd == "batch" and isinstance(args, dict) and isinstance(args.get("actions"), list):
        for action in args["actions"]:
            if isinstance(action, dict):
                error = _wait_timeout_error(action.get("cmd"), action.get("args") or {})
                if error:
                    return error
    requested = _requested_wait_ms(args) if cmd in LONG_WAIT_COMMANDS else None
    if requested is not None and requested > MAX_WAIT_MS:
        return {"ok": False, "error": f"timeout_ms must be at most {MAX_WAIT_MS}"}
    return None


async def dispatch_command(cmd, args, tab=None, timeout=HTTP_TIMEOUT,
                           max_attempts=COMMAND_MAX_ATTEMPTS, retry_delay=COMMAND_RETRY_DELAY,
                           profile="default"):
    """Route a command to a WS client, retrying transient connection errors
    (G5) when the command targeted a known tab.

    On {ok:false, error:"Could not establish connection..."} or "no active
    tab", re-dispatch up to `max_attempts` total tries (1 initial + up to 3
    retries) with `retry_delay` backoff so a tab that is mid-restore or whose
    content script hasn't injected yet gets a chance to come up.

    `profile` selects which browser session's client(s) to route to; defaults
    to "default" for backward compatibility with single-profile callers.
    """
    if cmd == "batch":
        error = _validate_batch_actions(args)
        if error:
            return error
        error = _wait_timeout_error(cmd, args)
        if error:
            return error
        return await _run_batch(
            args, tab, min(timeout, _command_budget(cmd, args)),
            max_attempts, retry_delay, profile,
        )

    if cmd == "sessions":
        # Daemon-local inventory must remain available even when every browser
        # profile is disconnected or a requested profile is ambiguous.
        return {"ok": True, "daemon_version": VERSION, "protocol_version": PROTOCOL_VERSION,
                "browser_connection": connection_diagnostic(), "profiles": profiles_status()}

    error = _wait_timeout_error(cmd, args)
    if error:
        return error

    total_budget = min(timeout, _command_budget(cmd, args))
    per_attempt = min(COMMAND_TIMEOUT_LONG, total_budget)
    if total_budget <= 0:
        return {"ok": False, "error": "timeout waiting for page"}
    started = time.monotonic()
    result = None
    for attempt in range(max_attempts):
        elapsed = time.monotonic() - started
        remaining = total_budget - elapsed
        if remaining <= 0:
            return {"ok": False, "error": "timeout waiting for page"}
        remaining_for_retry = remaining - (max_attempts - attempt - 1) * retry_delay
        if remaining_for_retry <= 0:
            return {"ok": False, "error": "timeout waiting for page"}
        attempt_timeout = min(per_attempt, remaining_for_retry)
        result, had_target = await _dispatch_once(cmd, args, tab, attempt_timeout, profile)
        if not had_target:
            return result
        if not (isinstance(result, dict) and result.get("ok") is False
                and _retryable(result.get("error"))):
            return result
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay)
    return result


async def _tabs_from_background(profile="default"):
    """G2: pull the full tab registry from the extension background.

    The background answers a background-side `tabs` command with the live
    registry [{tabId,windowId,index,url,title,active,connected}]. If no
    client is connected for `profile` we return an empty list (per spec). If
    the registry is momentarily unavailable we fall back to the connected-
    pages list so the endpoint never regresses while the background-side
    handler is warming up. The response also carries per-profile client status
    for the multi-profile /tabs view.
    """
    if not _clients(profile) and not (profile == "default" and active(profile)):
        return {"ok": True, "tabs": [], "profiles": profiles_status()}
    resp = await dispatch_command("tabs", {}, profile=profile)
    if isinstance(resp, dict) and resp.get("ok") and "result" in resp:
        return {"ok": True, "tabs": resp["result"], "profiles": profiles_status()}
    return {"ok": True, "tabs": tabs(profile), "profiles": profiles_status()}


# ---- websocket handler ---------------------------------------------------
async def _authenticate_ws(ws):
    """Validate one websocket's origin + credentials; close(4001/4003) on failure.

    Returns True when the caller proves possession of the token without ever
    transmitting it. The server-generated challenge also binds authentication
    to this daemon process, so a process temporarily occupying the WS port
    cannot harvest a reusable credential.
    """
    origin = ws.request.headers.get("Origin", "")
    if not _is_trusted_extension_origin(origin, authenticated=True):
        _record_connection("failed", "extension origin rejected")
        await ws.close(code=4003, reason="extension origin required")
        return False
    challenge = secrets.token_hex(32)
    await ws.send(json.dumps({"type": "auth_challenge", "challenge": challenge}))
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        message = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
        message = {}
    expected = hmac.new(_token().encode(), f"ws:{challenge}".encode(), hashlib.sha256).hexdigest()
    if (message.get("type") != "auth" or
            not isinstance(message.get("proof"), str) or
            not secrets.compare_digest(message["proof"], expected)):
        _record_connection("failed", "authentication failed")
        await ws.close(code=4001, reason="bad token")
        return False
    confirmation = hmac.new(_token().encode(), f"ws-ok:{INSTANCE_ID}:{challenge}".encode(), hashlib.sha256).hexdigest()
    await ws.send(json.dumps({"type": "auth_ok", "instance_id": INSTANCE_ID, "proof": confirmation}))
    if EXTENSION_ORIGIN_MODE == "pin" and not ALLOWED_EXTENSION_IDS:
        pinned_id = _extension_id(origin)
        if pinned_id:
            _remember_extension_id(pinned_id)
    _record_connection("authenticated")
    return True


def _resolve_pending(ws, msg):
    """Complete the future waiting on this (ws, id) response, if any."""
    mid = msg.get("id")
    if mid is None:
        return
    key = _msg_key(ws, mid)
    with _pending_lock:
        fut = pending.pop(key, None)
    if fut is not None and not fut.done():
        fut.set_result(msg)


async def _read_ws_messages(ws):
    """Consume one connection's message stream until teardown; register routing.

    hello registers/updates the browser client, bye deregisters, everything
    else is a command response paired to a pending future by message id.
    """
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "hello":
                upsert(ws, msg)
                continue
            if msg.get("type") == "bye":
                remove(ws)
                break
            _resolve_pending(ws, msg)
    except (ConnectionClosed, ConnectionResetError, BrokenPipeError) as exc:
        # Expected client teardown — the background simply closed the socket
        # (tab navigated, browser closed, idle timeout, extension reload). Log
        # quietly at DEBUG with no traceback so a routine drop doesn't spam.
        logger.debug("ws client disconnected: %s", exc)
    except Exception:
        # Unexpected failure mid-handler. Clean up the registry below, but
        # still surface the real error for diagnosis.
        logger.exception("ws_handler unexpected error")
    finally:
        remove(ws)


async def ws_handler(ws: ServerProtocol):
    if not await _authenticate_ws(ws):
        return
    await _read_ws_messages(ws)


# ---- HTTP command API ----------------------------------------------------
class ApiHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *a):
        pass

    def _send(self, code, obj, allow_image_artifacts=False):
        body = json.dumps(sanitize(obj, allow_image_artifacts=allow_image_artifacts), ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def _send_raw(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _send_html(self, code, body):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        # No CORS contract: loopback APIs are for local CLI/MCP and this
        # extension only. Never grant a webpage a spoofable marker header.
        self._send(403, {"ok": False, "error": "cross-origin blocked"})

    def _is_extension_origin(self):
        origin = self.headers.get("Origin", "")
        return _is_trusted_extension_origin(origin)

    def _is_remote_request(self):
        # Serve strips spoofed identity headers and injects the authenticated
        # tailnet user before proxying to this loopback listener.
        return bool(getattr(self, "headers", {}).get("Tailscale-User-Login"))

    def _is_authorized_request(self, body=b""):
        path = urllib.parse.urlparse(self.path).path
        return consume_request_proof(
            self.headers.get("X-Sleeper-Instance", ""),
            self.headers.get("X-Sleeper-Nonce", ""),
            self.headers.get("X-Sleeper-Timestamp", ""),
            self.headers.get("X-Sleeper-Proof", ""),
            getattr(self, "command", "GET"), path, body)

    def _has_auth_headers(self):
        return all(self.headers.get(name) for name in
                   ("X-Sleeper-Instance", "X-Sleeper-Nonce", "X-Sleeper-Timestamp",
                    "X-Sleeper-Proof"))

    def _has_valid_preamble(self):
        path = urllib.parse.urlparse(self.path).path
        content_length = self.headers.get("Content-Length", "0")
        try:
            if abs(int(time.time()) - int(self.headers.get("X-Sleeper-Timestamp", ""))) > AUTH_WINDOW_SECONDS:
                return False
        except (TypeError, ValueError):
            return False
        expected = request_preamble(
            self.headers.get("X-Sleeper-Nonce", ""),
            self.headers.get("X-Sleeper-Timestamp", ""),
            getattr(self, "command", "POST"), path, content_length)
        return secrets.compare_digest(self.headers.get("X-Sleeper-Preamble", ""), expected)

    def _reject_page_origin(self):
        origin = self.headers.get("Origin", "")
        return bool(origin) and not self._is_extension_origin()

    def _can_read_tabs(self):
        # `/tabs` is a privileged local control read; loopback callers need
        # the file token even when they omit browser fetch metadata.
        return self._is_authorized_request()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        if path == "/health":
            payload = {"ok": True, "service": "sleeper", "daemon_version": VERSION,
                       "protocol_version": PROTOCOL_VERSION, "instance_id": INSTANCE_ID}
            nonce = urllib.parse.parse_qs(parsed_url.query).get("nonce", [""])[0]
            proof = daemon_identity_proof(nonce)
            if proof:
                payload["identity_proof"] = proof
            # Fixed-schema handshake metadata must reach the verifier intact;
            # generic page-result redaction would replace both proof fields.
            self._send_raw(200, payload)
        elif path == "/sleeper-setup":
            if not self._is_remote_request():
                self._send(404, {"ok": False, "error": "not found"})
                return
            self._send_html(200, """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect Sleeper</title><style>body{font:16px system-ui;max-width:34rem;margin:15vh auto;padding:1.5rem;color:CanvasText;background:Canvas}h1{font-size:1.6rem}p{line-height:1.5;color:GrayText}</style><h1>Connecting Sleeper…</h1><p>Keep this tab open. The Sleeper add-on will verify the daemon and finish setup.</p></html>""")
        elif path == "/tabs":
            # G2: pull the full tab registry from the extension background;
            # if no client is connected the endpoint returns {ok:true, tabs:[]}.
            # Also reports per-profile client status ({profiles:{...}}) so the
            # CLI/agent can see which browser sessions are live.
            if not self._can_read_tabs():
                self._send(401, {"ok": False, "error": "local client authorization required"})
                return
            fut = asyncio.run_coroutine_threadsafe(_tabs_from_background(), _loop)
            try:
                result = fut.result(timeout=25)
            except Exception:
                result = {"ok": True, "tabs": [], "profiles": profiles_status()}
            self._send(200, result)
        elif path == "/api-hosts":
            if not self._is_authorized_request():
                self._send(403, {"ok": False, "error": "extension authorization required"}); return
            try: self._send(200, configured_api_hosts())
            except ValueError as exc: self._send(400, {"ok": False, "error": str(exc)})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def _read_command_body(self):
        """Read and validate the JSON command body; send the error response and
        return None on any violation (size, shape, missing cmd/args). Returns
        the full parsed body on success - cmd/args are validated here, while
        profile/tab stay on the body for the dispatcher to route on."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n < 0 or n > 1024 * 1024:
                self._send(413, {"ok": False, "error": "request body too large"})
                return None
            raw = self.rfile.read(n)
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                self._send(400, {"ok": False, "error": "request body must be an object"})
                return None
        except Exception:
            self._send(400, {"ok": False, "error": "bad json"})
            return None
        cmd = data.get("cmd")
        if not isinstance(cmd, str) or not cmd:
            self._send(400, {"ok": False, "error": "request body missing cmd"})
            return None
        args = data.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            self._send(400, {"ok": False, "error": "request body args must be an object"})
            return None
        return data, raw

    def _dispatch_to_browser(self, data):
        """Run one validated command body through the daemon loop and reply.

        The optional `profile` field picks which browser session to route to;
        it defaults to "default". The total HTTP wait is bounded by the same
        per-command budget dispatch_command uses (CRITICAL-2: long-wait
        commands get their requested timeout instead of the 4.5s cap). The
        HTTP future and coroutine use the same bounded budget.
        """
        cmd = data["cmd"]
        args = data.get("args", {})
        profile = data.get("profile") or "default"
        budget = min(HTTP_TIMEOUT, _command_budget(cmd, args))
        if cmd == "batch" and _validate_batch_actions(args):
            budget = HTTP_TIMEOUT
        fut = asyncio.run_coroutine_threadsafe(
            dispatch_command(cmd, args, tab=data.get("tab"),
                             profile=profile),
            _loop)
        try:
            result = fut.result(timeout=budget)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            result = {"ok": False, "error": "timeout waiting for page"}
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        self._send(200, result, allow_image_artifacts=(cmd == "shot"))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/command":
            self._send(404, {"ok": False, "error": "not found"})
            return
        if self.headers.get("Origin"):
            self._send(403, {"ok": False, "error": "cross-origin blocked"})
            return
        if not self._has_auth_headers():
            self._send(401, {"ok": False, "error": "local client authorization required"})
            return
        if not self._has_valid_preamble():
            self._send(401, {"ok": False, "error": "local client authorization required"})
            return
        self.connection.settimeout(10)
        parsed_body = self._read_command_body()
        if parsed_body is None:
            return
        parsed, raw = parsed_body
        if not self._is_authorized_request(raw):
            self._send(401, {"ok": False, "error": "local client authorization required"})
            return
        self._dispatch_to_browser(parsed)


_loop = None


def run_http(host, port):
    srv = BoundedThreadingHTTPServer((host, port), ApiHandler)
    srv.serve_forever()


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    max_connections = 32

    def __init__(self, *args, **kwargs):
        self._request_slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


async def main():
    global _loop
    _loop = asyncio.get_event_loop()
    t = threading.Thread(target=run_http, args=(BIND_HOST, HTTP_PORT), daemon=True)
    t.start()
    print("browser-sleeper daemon")
    scheme = "http"
    print("  ws   : %s://%s:%d/ws" % ("ws", BIND_HOST, WS_PORT))
    print("  api  : %s://%s:%d  (POST /command, GET /tabs, GET /health)" % (scheme, BIND_HOST, HTTP_PORT))
    async with websockets.serve(ws_handler, BIND_HOST, WS_PORT, max_size=2 ** 22):
        await asyncio.Future()


def run() -> int:
    """Run the async daemon from a console-script entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
