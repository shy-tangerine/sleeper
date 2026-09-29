#!/usr/bin/env python3
"""Configure Sleeper's tailnet-only HTTPS/WSS entry points."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote


HTTP_PORT = "8790"
WS_PORT = "8789"
TOKEN_FILE = "~/.config/browser-sleeper-token"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def run_command(args: list[str]) -> CommandResult:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _executable(value: str | None) -> str | None:
    return value or shutil.which("tailscale")


def _tailscale_identity(runner: Runner, executable: str) -> tuple[str | None, str | None]:
    result = runner([executable, "status", "--json"])
    if result.returncode != 0:
      return None, result.stderr.strip() or "Tailscale is not running."
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "Tailscale returned an unreadable status."
    if status.get("BackendState") != "Running":
        return None, "Tailscale is not connected. Run `tailscale up` first."
    dns_name = str(status.get("Self", {}).get("DNSName", "")).rstrip(".")
    if not dns_name.endswith(".ts.net"):
        return None, "Tailscale HTTPS requires MagicDNS and HTTPS certificates for this tailnet."
    return dns_name, None


def _run_or_error(runner: Runner, args: list[str]) -> str | None:
    result = runner(args)
    if result.returncode == 0:
        return None
    return result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}"


def _read_daemon_token(token_file: str | None = None) -> str | None:
    path = Path(os.path.expanduser(token_file or os.environ.get("SLEEPER_TOKEN_FILE", TOKEN_FILE)))
    try:
        if not path.is_file():
            return None
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def setup(*, runner: Runner = run_command, executable: str | None = None, token_file: str | None = None) -> dict:
    binary = _executable(executable)
    if not binary:
        return {"ok": False, "error": "Tailscale is not installed. Install it from https://tailscale.com/download/linux."}
    dns_name, error = _tailscale_identity(runner, binary)
    if error:
        return {"ok": False, "error": error}
    token = _read_daemon_token(token_file)
    if not token:
        return {"ok": False, "error": "Sleeper daemon credentials are unavailable; start the daemon first."}

    commands = [
        [binary, "serve", "--bg", f"--https={HTTP_PORT}", f"http://127.0.0.1:{HTTP_PORT}"],
        [binary, "serve", "--bg", f"--https={WS_PORT}", f"http://127.0.0.1:{WS_PORT}"],
    ]
    first_error = _run_or_error(runner, commands[0])
    if first_error:
        return {"ok": False, "error": first_error}
    second_error = _run_or_error(runner, commands[1])
    if second_error:
        _run_or_error(runner, [binary, "serve", f"--https={HTTP_PORT}", "off"])
        return {"ok": False, "error": second_error}

    return {
        "ok": True,
        "hostname": dns_name,
        # The fragment is never sent in the HTTP request for the setup page.
        "setup_url": f"https://{dns_name}:{HTTP_PORT}/sleeper-setup#token={quote(token, safe='')}",
        "http_url": f"https://{dns_name}:{HTTP_PORT}",
        "websocket_url": f"wss://{dns_name}:{WS_PORT}/ws",
    }


def status(*, runner: Runner = run_command, executable: str | None = None) -> dict:
    binary = _executable(executable)
    if not binary:
        return {"ok": False, "error": "Tailscale is not installed."}
    dns_name, error = _tailscale_identity(runner, binary)
    if error:
        return {"ok": False, "error": error}
    serve = runner([binary, "serve", "status", "--json"])
    serve_config = None
    serve_error = None
    if serve.returncode == 0:
        try:
            serve_config = json.loads(serve.stdout or "{}")
        except json.JSONDecodeError:
            serve_error = "Tailscale returned an unreadable Serve status."
    else:
        serve_error = serve.stderr.strip() or "Could not read Serve status."
    return {
        "ok": serve_error is None,
        "hostname": dns_name,
        "setup_url": f"https://{dns_name}:{HTTP_PORT}/sleeper-setup",
        "serve": serve_config,
        "error": serve_error,
    }


def disable(*, runner: Runner = run_command, executable: str | None = None) -> dict:
    binary = _executable(executable)
    if not binary:
        return {"ok": False, "error": "Tailscale is not installed."}
    errors = [
        error for error in (
            _run_or_error(runner, [binary, "serve", f"--https={HTTP_PORT}", "off"]),
            _run_or_error(runner, [binary, "serve", f"--https={WS_PORT}", "off"]),
        ) if error
    ]
    return {"ok": not errors, "disabled": not errors, "error": "; ".join(errors) if errors else None}


def _print_qr(url: str) -> None:
    try:
        import qrcode  # type: ignore[import-not-found]
    except ImportError:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args else "status"
    if args or command not in {"setup", "status", "disable"}:
        print("usage: sleeper mobile {setup|status|disable}", file=sys.stderr)
        return 2
    result = {"setup": setup, "status": status, "disable": disable}[command]()
    if command == "setup" and result.get("ok"):
        _print_qr(result["setup_url"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
