#!/usr/bin/env python3
"""Portable Sleeper command transport for Windows and Unix installations."""
from __future__ import annotations

import json
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

COMMAND_ALIASES = {"eval": "exec", "fill": "fillForm", "fill_form": "fillForm", "screenshot": "shot", "find_text": "findText", "click_all": "clickAll", "click_text": "clickText", "read_all": "readAll", "select": "selectOption", "scroll_until": "scrollUntil", "wait": "waitFor", "wait_text": "waitText", "wait_until": "waitUntil", "wait_xhr": "waitXhr", "wait_dialog": "waitDialog", "wait_download": "waitDownload"}
TAB_COMMANDS = {"list": "tabs", "new": "newtab", "select": "selecttab", "close": "closetab"}
POSITIONAL_FIELDS = {
    "batch": ("actions",),
    "exec": ("code",),
    "goto": ("url",), "newtab": ("url",), "find_text": ("text",), "findText": ("text",),
    "click_text": ("text",), "clickText": ("text",), "wait_text": ("text",), "wait_url": ("pattern",),
    "waitText": ("text",), "wait_xhr": ("url_substring",), "waitXhr": ("url_substring",), "waitUntil": ("predicate",), "waitFor": ("selector",), "waitDownload": ("pattern",), "press": ("key", "selector"), "selecttab": ("target",), "closetab": ("target",), "api": ("url",),
    "type": ("selector", "text"), "select": ("selector", "value"),
    "selectOption": ("selector", "value"), "drag": ("source", "target"),
    "upload": ("selector", "files"), "fill_form": ("fields",), "fillForm": ("fields",),
    "extract": ("map",), "keys": ("keys",),
}
BOOLEAN_OPTIONS = {"allow_user_tab", "annotate", "clear", "exact", "full_page", "html", "media", "stealth", "value"}
UNSUPPORTED_COMMANDS = {"adapter", "analyze", "recipe", "schema"}
HELP = """usage: sleeper <command> [args...]

Setup and targeting:
  sleeper sessions                        list connected browser profiles
  sleeper bind BROWSER_ID                 save a project binding
  sleeper mobile setup                    connect Firefox Android through Tailscale
  --profile BROWSER_ID                    target a browser (or bind one)
  --tab id:N                              required for explicit mutation targets
  --allow-user-tab                        permit changes to a tab Sleeper did not create
  Read-only commands also accept tab positions and unique URL substrings.

Commands:
  state | tabs | snapshot | frames
  find SELECTOR | find_text TEXT
  click SELECTOR | click_all SELECTOR | click_text TEXT | dblclick SELECTOR
  type SELECTOR TEXT [--clear] [--stealth]
  read SELECTOR [--html|--value|--attr ATTR] | read_all SELECTOR
  press KEY [--selector SEL] | keys KEY [KEY ...]
  submit | forms | fill_form '{"name":"value"}'
  select SELECTOR VALUE | check SELECTOR | uncheck SELECTOR
  extract '{"title":"h1","prices":".price"}'
  scroll N | scroll --selector SEL | scroll_until [--container C] [--text X] [--selector S]
  goto URL | back | newtab URL | selecttab id:N | closetab id:N
  wait SELECTOR | wait_text TEXT | wait_until CONDITION | wait_url PATTERN
  wait_xhr URL_SUBSTRING [--method GET|POST|DELETE] [--timeout MS]
  wait_download PATTERN [--timeout MS]
  exec 'JS' (Chromium only) | network [--media] | media | console [--lines N]
  api PATH [--method GET|POST|DELETE] [--body '{"k":"v"}']
  shot | screenshot                       viewport PNG
  upload SELECTOR --files 'a.txt,b.txt' | drag SOURCE TARGET
"""
VERSION = "2.0.1"
TOKEN_FILE = os.path.expanduser(os.environ.get("SLEEPER_TOKEN_FILE", "~/.config/browser-sleeper-token"))


def _read_daemon_token() -> str:
    try:
        token = Path(TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("Sleeper daemon credentials are unavailable") from exc
    if not token:
        raise ValueError("Sleeper daemon credentials are unavailable")
    return token


def _daemon_not_running_message() -> str:
    if sys.platform == "darwin":
        return ("Sleeper daemon is not running; on macOS run "
                "`launchctl kickstart -k gui/$(id -u)/com.shy-tangerine.sleeper`, or reinstall Sleeper")
    return ("Sleeper daemon is not running; on Linux run "
            "`systemctl --user enable --now sleeper.service`, or reinstall Sleeper")


def _daemon_health_reachable(port: str) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
            return True
    except (HTTPError, URLError, OSError, ValueError):
        return False


def _command_progress(command: str, started: float) -> tuple[threading.Event, threading.Thread]:
    """Report that a remote browser command is still running on stderr."""
    stopped = threading.Event()

    def report() -> None:
        interval = 1
        while not stopped.wait(interval):
            elapsed = int(time.monotonic() - started)
            print(f"sleeper: {command} still running ({elapsed}s)", file=sys.stderr, flush=True)
            interval = 5

    thread = threading.Thread(target=report, name="sleeper-cli-progress", daemon=True)
    thread.start()
    return stopped, thread


def _verify_daemon(port: str, token: str) -> str:
    nonce = secrets.token_hex(16)
    with urlopen(f"http://127.0.0.1:{port}/health?nonce={quote(nonce)}", timeout=3) as response:
        payload = json.load(response)
    instance_id = str(payload.get("instance_id", ""))
    expected = hmac.new(token.encode(), f"{nonce}:{instance_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(payload.get("identity_proof", "")), expected):
        raise ValueError("daemon identity verification failed")
    return instance_id


def _auth_headers(token: str, instance_id: str, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    nonce = secrets.token_hex(16)
    timestamp = int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{instance_id}\n{nonce}\n{timestamp}\n{method}\n{path}\n{body_hash}".encode()
    proof = hmac.new(token.encode(), message, hashlib.sha256).hexdigest()
    preamble = hmac.new(token.encode(),
        f"{instance_id}\n{nonce}\n{timestamp}\n{method}\n{path}\n{len(body)}".encode(), hashlib.sha256).hexdigest()
    return {"X-Sleeper-Instance": instance_id, "X-Sleeper-Nonce": nonce,
            "X-Sleeper-Timestamp": str(timestamp), "X-Sleeper-Proof": proof,
            "X-Sleeper-Preamble": preamble}


def decode(value: str, field: str | None = None):
    if field == "code":
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    # JavaScript predicates remain source strings; only objects select the
    # structured-condition API. JSON scalars must not lose their source text.
    return value if field == "predicate" and not isinstance(parsed, dict) else parsed


def session_profile() -> str | None:
    if os.environ.get("SLEEPER_PROFILE"):
        return os.environ["SLEEPER_PROFILE"]
    session = Path(os.environ.get("SLEEPER_SESSION_FILE", ".sleeper-session"))
    try:
        profile = session.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return profile or None


def _canonical_command(command: str, argv: list[str]) -> str:
    """Resolve raw/tab-prefixed/wait-download command spellings to wire names."""
    if command == "tab":
        if not argv or argv[0] not in TAB_COMMANDS:
            raise ValueError("usage: sleeper tab {list,new,select,close} [args...]")
        command = TAB_COMMANDS[argv.pop(0)]
    if command == "wait" and argv[:1] == ["download"]:
        command = "waitDownload"
        argv.pop(0)
    return COMMAND_ALIASES.get(command, command)


def _split_positional(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv into positional words and (flag, lookahead) pairs.

    A bare "--" sends everything after it to the positional list verbatim, so
    values that look like flags (URLs containing --, negative numbers) still
    parse. The lookahead keeps the original single-pass scanner's exact
    consumption rule: a flag takes its follower only when that follower does
    not start with "--", so "--selector --tab 2" leaves --tab to be parsed as
    its own flag (selector falls back to boolean true, matching history).
    """
    positional: list[str] = []
    flags: list[tuple[str, str | None]] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--":
            positional.extend(argv[index + 1:])
            break
        if not item.startswith("--"):
            positional.append(item)
            index += 1
            continue
        next_item = argv[index + 1] if index + 1 < len(argv) else None
        if _flag_consumes_next(item, next_item):
            flags.append((item, next_item))
            index += 2
        else:
            flags.append((item, None))
            index += 1
    return positional, flags


def _flag_consumes_next(token: str, next_item: str | None) -> bool:
    """True when "--key value" form must swallow the following argv item.

    Mirrors the original scanner's two conditions: the key (normalized to
    wire spelling) is not a boolean, and the follower exists and is not
    itself flag-shaped. A "--"-prefixed follower is left in the stream and
    parsed as its own flag, while the current flag defaults to "true".
    """
    key = _wire_key("", token[2:].partition("=")[0])
    return (key not in BOOLEAN_OPTIONS and "=" not in token
            and next_item is not None and not next_item.startswith("--"))


def _wire_key(command: str, key: str) -> str:
    """Map CLI spellings onto the daemon's wire keys."""
    key = key.replace("-", "_")
    if command == "waitDownload" and key == "timeout":
        return "timeout_ms"
    return key


def _apply_flag(payload: dict, command: str, flag_token: str, next_value: str | None) -> None:
    """Fold one --flag[=value] token into the payload.

    `next_value` is the raw argv item that followed the flag (consumed by the
    scanner when `_flag_consumes_next` said so). "=" forms, bare booleans, and
    end-of-argv flags have no separate value. Profile and tab live at the
    payload top level, everything else in args.
    """
    key, separator, inline_value = flag_token[2:].partition("=")
    key = _wire_key(command, key)
    has_inline = bool(separator)
    if not has_inline and key not in BOOLEAN_OPTIONS:
        value = "true" if next_value is None else next_value
    else:
        value = inline_value if has_inline else "true"
    decoded = True if (not has_inline and key in BOOLEAN_OPTIONS) else decode(value, key)
    if key in {"profile", "tab"}:
        if value == "true":
            raise ValueError(f"--{key.replace('_', '-')} requires a value")
        payload[key] = str(decoded)
    else:
        payload["args"][key] = decoded


def _parse_flags(payload: dict, command: str, flags: list[tuple[str, str | None]]) -> None:
    """Apply scanned (flag, lookahead) pairs in original argv order."""
    for token, lookahead in flags:
        _apply_flag(payload, command, token, lookahead)


def _assign_positional(payload: dict, command: str, positional: list[str]) -> None:
    """Map positional words onto the command's declared field order."""
    fields = POSITIONAL_FIELDS.get(command, ("selector", "text"))
    if command == "type" and len(positional) == 1 and any(
        key in payload["args"] for key in ("role", "name", "label", "text", "testid")
    ):
        fields = ("text",)
    for index, value in enumerate(positional):
        if index >= len(fields):
            # Trailing list fields (keys/files) collect every remaining word,
            # matching the bash CLI: `sleeper keys Enter Tab ArrowDown`.
            if fields and fields[-1] in {"files", "keys"}:
                payload["args"][fields[-1]].append(decode(value))
                continue
            raise ValueError(f"too many positional arguments for {command}")
        decoded = decode(value, fields[index])
        if fields[index] in {"files", "keys"} and isinstance(decoded, str):
            decoded = [decoded]
        payload["args"][fields[index]] = decoded


def _apply_command_defaults(payload: dict, command: str) -> None:
    """Pin the per-command defaults and validate command-specific shapes.

    Mirrors the Bash CLI: find caps at 50 by default, waitDownload budgets
    15s, batch requires a JSON array and only puts stop_on_error on the wire
    when explicitly requested so old transports stay byte compatible.
    """
    if command in {"read", "readAll"}:
        for mode in ("html", "value"):
            if payload["args"].pop(mode, False):
                payload["args"]["what"] = mode
        if "attr" in payload["args"]:
            payload["args"]["what"] = "attr"
    if command == "waitUntil" and isinstance(payload["args"].get("predicate"), dict):
        payload["args"]["condition"] = payload["args"].pop("predicate")
    if command == "find" and "limit" not in payload["args"]:
        payload["args"]["limit"] = 50
    if command == "waitDownload" and "timeout_ms" not in payload["args"]:
        payload["args"]["timeout_ms"] = 15000
    if command == "batch" and not isinstance(payload["args"].get("actions"), list):
        raise ValueError("batch actions must be a JSON array")
    if command == "batch":
        continue_on_error = payload["args"].pop("continue_on_error", None)
        if continue_on_error is not None:
            payload["args"]["stop_on_error"] = not bool(continue_on_error)


def parse_payload(argv: list[str]) -> dict:
    if not argv:
        raise ValueError("usage: sleeper <command> [args...]")
    command = argv.pop(0)
    if command in UNSUPPORTED_COMMANDS:
        raise ValueError(f"{command} is only available in the Bash CLI")
    if command == "raw":
        if len(argv) != 1:
            raise ValueError("usage: sleeper raw JSON")
        return json.loads(argv[0])
    command = _canonical_command(command, argv)
    payload: dict = {"cmd": command, "args": {}}
    positional, flags = _split_positional(argv)
    _parse_flags(payload, command, flags)
    _assign_positional(payload, command, positional)
    _apply_command_defaults(payload, command)
    profile = session_profile()
    if profile and "profile" not in payload:
        payload["profile"] = profile
    return payload


def session_file() -> Path:
    return Path(os.environ.get("SLEEPER_SESSION_FILE", ".sleeper-session"))


def local_command(argv: list[str]) -> int | None:
    if not argv or argv[0] not in {"bind", "unbind", "close", "mobile"}:
        return None
    command, *args = argv
    if command == "mobile":
        if __package__:
            from . import tailscale_mobile
        else:
            import tailscale_mobile
        return tailscale_mobile.main(args)
    path = session_file()
    if command == "bind":
        if len(args) != 1 or not args[0].replace("-", "").replace("_", "").isalnum():
            raise ValueError("usage: sleeper bind BROWSER_ID")
        path.write_text(f"{args[0]}\n", encoding="utf-8")
        print(json.dumps({"ok": True, "bound": args[0]}, separators=(",", ":")))
    else:
        if args:
            raise ValueError(f"usage: sleeper {command}")
        path.unlink(missing_ok=True)
        print(json.dumps({"ok": True, command: True}, separators=(",", ":")))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["--help"], ["-h"], ["help"]):
        print(HELP, end="")
        return 0
    if argv[:1] in (["--version"], ["version"]):
        print(f"Sleeper {VERSION}")
        return 0
    try:
        local_result = local_command(argv)
        if local_result is not None:
            return local_result
        payload = parse_payload(argv)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if os.environ.get("SLEEPER_DRY_RUN") == "1":
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    port = os.environ.get("SLEEPER_PORT", "8790")
    try:
        token = _read_daemon_token()
    except ValueError:
        if _daemon_health_reachable(port):
            detail = ("Sleeper daemon is running but no local token exists yet; "
                      "start the daemon's first pairing or check SLEEPER_TOKEN_FILE")
        else:
            detail = _daemon_not_running_message()
        print(f"error: {detail}", file=sys.stderr)
        return 1
    body = json.dumps(payload).encode()
    started = time.monotonic()
    progress, progress_thread = _command_progress(str(payload.get("cmd", "command")), started)
    try:
        instance_id = _verify_daemon(port, token)
        headers = {"Content-Type": "application/json", **_auth_headers(token, instance_id, "POST", "/command", body)}
        request = Request(f"http://127.0.0.1:{port}/command", body, headers)
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        progress.set()
        progress_thread.join()
        detail = str(exc)
        if isinstance(exc, URLError) and isinstance(exc.reason, ConnectionRefusedError):
            detail = _daemon_not_running_message()
        duration_ms = round((time.monotonic() - started) * 1000)
        print(json.dumps({"ok": False, "error": detail, "duration_ms": duration_ms}), file=sys.stderr)
        return 1
    progress.set()
    progress_thread.join()
    if not result.get("ok", False):
        duration_ms = round((time.monotonic() - started) * 1000)
        print(f"sleeper: {payload.get('cmd', 'command')} failed after {duration_ms}ms", file=sys.stderr)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
