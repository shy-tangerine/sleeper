#!/usr/bin/env python3
"""Sleeper MCP bridge — stdio JSON-RPC exposing the sleeper command set as MCP tools.

Transports each MCP tools/call to the local sleeper daemon (HTTP 127.0.0.1:8790/command).
The transport and JSON-RPC protocol use stdlib http.client + json; no MCP SDK
is required. Result sanitization uses the project's redaction module, which
depends on detect-secrets.

Protocol: JSON-RPC 2.0 over stdio, MCP initialize + tools/list + tools/call + ping.
"""
import json
import hashlib
import hmac
import os
import secrets
import sys
import time
import http.client
from pathlib import Path
if __package__:
    from .redaction import sanitize
else:
    from redaction import sanitize

DAEMON_HOST = os.environ.get("SLEEPER_HOST", "127.0.0.1")
DAEMON_PORT = int(os.environ.get("SLEEPER_PORT", "8790"))
DAEMON_PROFILE = os.environ.get("SLEEPER_PROFILE", "").strip()
TOKEN_FILE = os.path.expanduser(os.environ.get("SLEEPER_TOKEN_FILE", "~/.config/browser-sleeper-token"))
MAX_REQUEST_BYTES = 1024 * 1024
MAX_BATCH_REQUESTS = 50


def _read_daemon_token():
    try:
        token = Path(TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("Sleeper daemon credentials are unavailable") from exc
    if not token:
        raise RuntimeError("Sleeper daemon credentials are unavailable")
    return token


def _verify_daemon_identity(token):
    nonce = secrets.token_hex(16)
    conn = http.client.HTTPConnection(DAEMON_HOST, DAEMON_PORT, timeout=3)
    try:
        try:
            conn.request("GET", f"/health?nonce={nonce}")
            payload = json.loads(conn.getresponse().read().decode())
        except Exception as exc:
            raise RuntimeError("daemon identity verification failed") from exc
    finally:
        conn.close()
    instance_id = str(payload.get("instance_id", ""))
    expected = hmac.new(token.encode(), f"{nonce}:{instance_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(payload.get("identity_proof", "")), expected):
        raise RuntimeError("daemon identity verification failed")
    return instance_id


def _auth_headers(token, instance_id, method, path, body=b""):
    nonce = secrets.token_hex(16)
    timestamp = int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{instance_id}\n{nonce}\n{timestamp}\n{method}\n{path}\n{body_hash}".encode()
    return {
        "X-Sleeper-Instance": instance_id,
        "X-Sleeper-Nonce": nonce,
        "X-Sleeper-Timestamp": str(timestamp),
        "X-Sleeper-Proof": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
        "X-Sleeper-Preamble": hmac.new(token.encode(),
            f"{instance_id}\n{nonce}\n{timestamp}\n{method}\n{path}\n{len(body)}".encode(), hashlib.sha256).hexdigest(),
    }

# Map MCP tool name -> daemon cmd
TOOL_CMD = {
    "sleeper_batch": "batch",
    "sleeper_state": "state",
    "sleeper_sessions": "sessions",
    "sleeper_tabs": "tabs",
    "sleeper_snapshot": "snapshot",
    "sleeper_goto": "goto",
    "sleeper_back": "back",
    "sleeper_frames": "frames",
    "sleeper_get": "get",
    "sleeper_find": "find",
    "sleeper_find_text": "findText",
    "sleeper_click": "click",
    "sleeper_click_all": "clickAll",
    "sleeper_click_text": "clickText",
    "sleeper_hover": "hover",
    "sleeper_focus": "focus",
    "sleeper_type": "type",
    "sleeper_keys": "keys",
    "sleeper_press": "press",
    "sleeper_submit": "submit",
    "sleeper_read": "read",
    "sleeper_read_all": "readAll",
    "sleeper_wait": "waitFor",
    "sleeper_wait_text": "waitText",
    "sleeper_wait_until": "waitUntil",
    "sleeper_wait_url": "wait_url",
    "sleeper_exec": "exec",
    "sleeper_forms": "forms",
    "sleeper_fill_form": "fillForm",
    "sleeper_select": "selectOption",
    "sleeper_extract": "extract",
    "sleeper_scroll": "scroll",
    "sleeper_scroll_until": "scrollUntil",
    "sleeper_wait_dialog": "waitDialog",
    "sleeper_network": "network",
    "sleeper_media": "media",
    "sleeper_wait_xhr": "waitXhr",
    "sleeper_wait_download": "waitDownload",
    "sleeper_console": "console",
    "sleeper_shot": "shot",
    "sleeper_screenshot": "shot",
    "sleeper_upload": "upload",
    "sleeper_drag": "drag",
    "sleeper_dblclick": "dblclick",
    "sleeper_check": "check",
    "sleeper_uncheck": "uncheck",
    "sleeper_newtab": "newtab",
    "sleeper_api": "api",
    "sleeper_dialog": "dialog",
}

def _tool(name, desc, props, required=None, additional_properties=False):
    props = dict(props)
    props.setdefault("profile", {
        "type": "string",
        "description": "Browser ID from sleeper_sessions; optional with one connected browser.",
    })
    return {
        "name": name,
        "description": desc,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required or [],
            "additionalProperties": bool(additional_properties),
        },
    }

TOOLS = [
    _tool("sleeper_batch", "Run ordered browser actions in one request; stops at the first failure by default", {
        "actions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "args": {"type": "object"},
                    "tab": {"type": "string"},
                },
                "required": ["cmd"],
                "additionalProperties": False,
            },
        },
        "stop_on_error": {"type": "boolean", "default": True},
    }, ["actions"]),
    _tool("sleeper_state", "Get page state for the selected Sleeper profile (url, title, focus, visibility)", {}),
    _tool("sleeper_sessions", "List connected stable browser installation IDs for routing", {}),
    _tool("sleeper_tabs", "List tabs in the selected Sleeper browser profile", {}),
    _tool("sleeper_snapshot", "Headings/inputs/buttons/links summary", {"tab": {"type": "string", "description": "tab index or URL substring"}}),
    _tool("sleeper_goto", "Navigate to URL", {"url": {"type": "string"}, "tab": {"type": "string"}}, ["url"]),
    _tool("sleeper_back", "History back", {"tab": {"type": "string"}}),
    _tool("sleeper_frames", "List cross-origin iframes", {}),
    _tool("sleeper_get", "Get page/element properties", {"selector": {"type": "string"}, "tab": {"type": "string"}}),
    _tool("sleeper_find", "Inspect elements by CSS selector", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_find_text", "Find element by innerText", {"text": {"type": "string"}, "exact": {"type": "boolean"}, "tab": {"type": "string"}}, ["text"]),
    _tool("sleeper_click", "Click element by CSS selector (supports :has-text)", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_click_all", "Click every matching element", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_click_text", "Click element by text", {"text": {"type": "string"}, "index": {"type": "integer"}, "exact": {"type": "boolean"}, "verify": {"type": "string"}, "tab": {"type": "string"}}, ["text"]),
    _tool("sleeper_hover", "Mouseover element", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_focus", "Focus element", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_type", "Type into input (React-compatible events)", {"selector": {"type": "string"}, "text": {"type": "string"}, "clear": {"type": "boolean"}, "stealth": {"type": "boolean"}, "tab": {"type": "string"}}, ["selector", "text"]),
    _tool("sleeper_keys", "Dispatch key events on active element", {"keys": {"type": "array", "items": {"type": "string"}}, "tab": {"type": "string"}}, ["keys"]),
    _tool("sleeper_press", "Keyboard events on element/active", {"key": {"type": "string"}, "selector": {"type": "string"}, "tab": {"type": "string"}}, ["key"]),
    _tool("sleeper_submit", "Submit form", {"selector": {"type": "string"}, "tab": {"type": "string"}}),
    _tool("sleeper_read", "Read single element (text/html/value/attr)", {"selector": {"type": "string"}, "what": {"type": "string", "enum": ["text", "html", "value", "attr"]}, "attr": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_read_all", "Read all matching elements", {"selector": {"type": "string"}, "what": {"type": "string"}, "attr": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_wait", "Wait for selector", {"selector": {"type": "string"}, "timeout": {"type": "integer"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_wait_text", "Wait for text", {"text": {"type": "string"}, "exact": {"type": "boolean"}, "timeout_ms": {"type": "integer"}, "tab": {"type": "string"}}, ["text"]),
    _tool("sleeper_wait_until", "Wait for a structured page condition; JavaScript predicates are Chromium-only", {"condition": {"type": "object", "description": "Structured condition with selector or text, plus optional state, count, attribute, value, operator, and exact fields"}, "predicate": {"type": "string", "description": "Chromium-only JavaScript predicate"}, "timeout": {"type": "integer"}, "interval": {"type": "integer"}, "tab": {"type": "string"}}),
    _tool("sleeper_wait_url", "Wait until URL contains pattern", {"pattern": {"type": "string"}, "timeout_ms": {"type": "integer"}, "tab": {"type": "string"}}, ["pattern"]),
    _tool("sleeper_exec", "Execute arbitrary JS in Chromium; unavailable in signed Firefox builds", {"code": {"type": "string"}, "tab": {"type": "string"}}, ["code"]),
    _tool("sleeper_forms", "Enumerate form inputs", {"selector": {"type": "string"}, "tab": {"type": "string"}}),
    _tool("sleeper_fill_form", "Fill form by name/id/placeholder (JSON map)", {"fields": {"type": "object"}, "tab": {"type": "string"}}, ["fields"]),
    _tool("sleeper_select", "Set select value + change event", {"selector": {"type": "string"}, "value": {"type": "string"}, "tab": {"type": "string"}}, ["selector", "value"]),
    _tool("sleeper_extract", "Extract selector->text map", {"map": {"type": "object"}, "tab": {"type": "string"}}, ["map"]),
    _tool("sleeper_scroll", "Scroll by pixels or to selector", {"y": {"type": "integer"}, "selector": {"type": "string"}, "tab": {"type": "string"}}),
    _tool("sleeper_scroll_until", "Scroll until text/selector appears", {"container": {"type": "string"}, "text": {"type": "string"}, "selector": {"type": "string"}, "max_iters": {"type": "integer"}, "tab": {"type": "string"}}),
    _tool("sleeper_wait_dialog", "Wait for dialog", {"text": {"type": "string"}, "timeout_ms": {"type": "integer"}, "tab": {"type": "string"}}),
    _tool("sleeper_network", "Per-tab request log or fetch", {"media": {"type": "boolean"}, "since": {"type": "integer"}, "clear": {"type": "boolean"}, "fetch": {"type": "boolean"}, "url": {"type": "string"}, "body": {"type": "boolean"}, "segment": {"type": "string"}, "tab": {"type": "string"}}),
    _tool("sleeper_media", "Per-tab media request log", {"since": {"type": "integer"}, "clear": {"type": "boolean"}, "tab": {"type": "string"}}),
    _tool("sleeper_wait_xhr", "Wait for XHR matching URL substring", {"url_substring": {"type": "string"}, "method": {"type": "string"}, "timeout_ms": {"type": "integer"}, "tab": {"type": "string"}}, ["url_substring"]),
    _tool("sleeper_wait_download", "Wait for a download matching a URL/filename pattern to finish", {"pattern": {"type": "string"}, "timeout_ms": {"type": "integer"}, "tab": {"type": "string"}}, ["pattern"]),
    _tool("sleeper_console", "Page console capture", {"limit": {"type": "integer"}, "tab": {"type": "string"}}),
    _tool("sleeper_shot", "Viewport PNG screenshot (data URL)", {"tab": {"type": "string"}}),
    _tool("sleeper_screenshot", "Alias for shot — viewport PNG screenshot", {"tab": {"type": "string"}}),
    _tool("sleeper_upload", "Upload explicit base64 file contents to an input; native paths are unsupported. Total JSON request limit: 1 MiB.", {
        "selector": {"type": "string"},
        "files": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["name", "content_base64"],
            "properties": {"name": {"type": "string"}, "content_base64": {"type": "string"}, "mime_type": {"type": "string"}},
        }},
        "tab": {"type": "string"},
    }, ["selector", "files"]),
    _tool("sleeper_drag", "Drag source to target", {"source": {"type": "string"}, "target": {"type": "string"}, "tab": {"type": "string"}}, ["source", "target"]),
    _tool("sleeper_dblclick", "Double-click element", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_check", "Check checkbox", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_uncheck", "Uncheck checkbox", {"selector": {"type": "string"}, "tab": {"type": "string"}}, ["selector"]),
    _tool("sleeper_newtab", "Open new tab via extension API", {"url": {"type": "string"}}, ["url"]),
    _tool("sleeper_api", "Call page backend API with captured auth token (background fetch)", {"url": {"type": "string"}, "method": {"type": "string"}, "body": {"type": "string"}}, ["url"]),
    _tool("sleeper_dialog", "Install auto accept/dismiss dialog hook", {}),
]


def daemon_call(cmd, args, tab=None, profile=None):
    request = {"cmd": cmd, "args": args or {}}
    if tab is not None:
        request["tab"] = tab
    selected_profile = DAEMON_PROFILE if profile is None else profile
    if selected_profile:
        request["profile"] = selected_profile
    body = json.dumps(request, separators=(",", ":")).encode()
    try:
        token = _read_daemon_token()
        instance_id = _verify_daemon_identity(token)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    # A requested browser wait may run for 60 seconds plus daemon overhead.
    conn = http.client.HTTPConnection(DAEMON_HOST, DAEMON_PORT, timeout=65)
    try:
        conn.request("POST", "/command", body=body, headers={
            "Content-Type": "application/json",
            **_auth_headers(token, instance_id, "POST", "/command", body),
        })
        resp = conn.getresponse()
        data = resp.read().decode()
        try:
            return json.loads(data) if data else {"ok": False, "error": "empty response"}
        except json.JSONDecodeError:
            return {"ok": False, "error": data[:500]}
    except ConnectionRefusedError:
        if sys.platform == "darwin":
            return {"ok": False, "error": ("Sleeper daemon is not running; on macOS run "
                                            "`launchctl kickstart -k gui/$(id -u)/com.shy-tangerine.sleeper`, or reinstall Sleeper")}
        return {"ok": False, "error": ("Sleeper daemon is not running; on Linux run "
                                        "`systemctl --user enable --now sleeper.service`, or reinstall Sleeper")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def _method_error(code, msg, req):
    mid = req.get("id") if isinstance(req, dict) else None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def handle_request(req):
    if not isinstance(req, dict):
        return _method_error(-32600, "Invalid Request", {})
    mid = req.get("id")
    method = req.get("method", "")

    def reply(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    def err(code, msg):
        return _method_error(code, msg, req)

    if not isinstance(method, str):
        return err(-32600, "Invalid Request")
    if "jsonrpc" in req and req["jsonrpc"] != "2.0":
        return err(-32600, "Invalid Request")
    params = req.get("params", {})
    if not isinstance(params, dict):
        return err(-32602, "Invalid params")
    handler = _METHOD_HANDLERS.get(method)
    if handler is None:
        return err(-32601, f"unknown method: {method}")
    return handler(params, reply, err)


def _respond_initialize(params, reply, err):
    return reply({
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "sleeper", "version": "2.0.1"},
    })


def _respond_ping(params, reply, err):
    return reply({})


def _respond_tools_list(params, reply, err):
    return reply({"tools": TOOLS})


def _respond_tools_call(params, reply, err):
    name = params.get("name", "")
    if not isinstance(name, str) or not name:
        return err(-32602, "Invalid params")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return err(-32602, "Invalid arguments")
    if name not in TOOL_CMD:
        return err(-32602, f"unknown tool: {name}")
    cmd = TOOL_CMD[name]
    arguments = dict(arguments)
    profile = arguments.pop("profile", None)
    tab = arguments.pop("tab", None)
    result = daemon_call(cmd, arguments, tab=tab, profile=profile)
    text = json.dumps(
        sanitize(result, allow_image_artifacts=(cmd == "shot")),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    is_error = isinstance(result, dict) and result.get("ok") is False
    return reply({"content": [{"type": "text", "text": text}], "isError": is_error})


_METHOD_HANDLERS = {
    "initialize": _respond_initialize,
    "notifications/initialized": lambda params, reply, err: None,
    "ping": _respond_ping,
    "tools/list": _respond_tools_list,
    "tools/call": _respond_tools_call,
}

def serialize_response(response):
    # `handle_request` already sanitizes daemon results before embedding them
    # as MCP text. Sanitizing this outer JSON string again would see a large
    # PNG data URL as ordinary text and corrupt the artifact by truncation.
    return json.dumps(response, ensure_ascii=False, separators=(",", ":"))


def main():
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    while True:
        line = stream.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return 0
        if len(line) > MAX_REQUEST_BYTES:
            sys.stdout.write(serialize_response(_method_error(-32600, "Request too large", {})) + "\n")
            sys.stdout.flush()
            return 1
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                line = ""
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(serialize_response(_method_error(-32700, "Parse error", {})) + "\n")
            sys.stdout.flush()
            continue
        # Handle batch array (not expected but spec allows)
        if isinstance(req, list):
            if not req or len(req) > MAX_BATCH_REQUESTS:
                sys.stdout.write(serialize_response(_method_error(-32600, "Invalid Request", {})) + "\n")
                sys.stdout.flush()
                continue
            responses = [handle_request(r) for r in req]
            for resp in responses:
                if resp is not None:
                    sys.stdout.write(serialize_response(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(serialize_response(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

def dump_tools_json():
    """Serialize TOOLS the way docs/mcp-tools.json is published.

    Used by scripts/gen_mcp_tools.py (and its regression test) so the doc
    file is a generated artifact of the canonical TOOLS list rather than a
    hand-maintained copy that drifts.
    """
    return json.dumps(TOOLS, indent=2, ensure_ascii=False) + "\n"
