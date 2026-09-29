#!/usr/bin/env python3
"""Install Sleeper's native plugin adapters through their client CLIs.

The adapter is copied into a managed user directory, then the client is asked
to register and install it. A copied directory alone is never reported as an
installation.
"""
from __future__ import annotations

import json
import ntpath
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


CLIENTS = ("codex", "claude")


def _reject_symlink_ancestors(path: Path) -> None:
    current = path.absolute()
    while current != current.parent:
        if current.is_symlink():
            raise RuntimeError(f"refusing symlink plugin destination: {current}")
        current = current.parent


def _open_directory_beneath(root: Path, path: Path) -> int:
    root = root.absolute(); path = path.absolute()
    try: relative = path.relative_to(root)
    except ValueError as exc: raise RuntimeError(f"plugin destination escapes managed root: {path}") from exc
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in relative.parts:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor); raise


def _atomic_write_text(path: Path, content: str, managed_root: Path | None = None) -> None:
    managed_root = managed_root or path.parent
    _reject_symlink_ancestors(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink plugin destination: {path}")
    if os.name == "nt":
        try:
            from scripts.install import _windows_pinned_directories
        except ImportError:
            from install import _windows_pinned_directories
        with _windows_pinned_directories(managed_root, path.parent):
            fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(content); output.flush(); os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return
    parent_fd = _open_directory_beneath(managed_root, path.parent)
    temporary_name = f".{path.name}.{secrets.token_hex(16)}"
    fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content); output.flush(); os.fsync(output.fileno())
        os.replace(temporary_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        try: os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError: pass
        os.close(parent_fd)


def _rmtree_at(parent_fd: int, name: str) -> None:
    directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        for child in os.listdir(directory_fd):
            mode = os.stat(child, dir_fd=directory_fd, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode): _rmtree_at(directory_fd, child)
            else: os.unlink(child, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _command(client: str) -> str | None:
    return shutil.which(client)


def _marketplace(root: Path, client: str) -> Path:
    market_root = root / "marketplaces" / client
    package = market_root / "plugins" / "sleeper"
    _reject_symlink_ancestors(package.parent)
    package.parent.mkdir(parents=True, exist_ok=True)
    return market_root


def _marketplace_marker(market_root: Path) -> Path:
    return market_root / ".sleeper-marketplace-managed"


def _copy_adapter(source_root: Path, destination: Path, client: str) -> Path:
    source = source_root / "plugins" / client / "sleeper"
    if not source.is_dir():
        raise FileNotFoundError(f"missing {client} plugin package: {source}")
    target = _marketplace(destination, client) / "plugins" / "sleeper"
    if target.is_symlink() or target.parent.is_symlink():
        raise RuntimeError(f"refusing symlink plugin destination: {target}")
    if target.exists():
        if not (target / ".sleeper-managed").is_file():
            raise RuntimeError(f"refusing to replace unmarked plugin directory: {target}")
    staging = Path(tempfile.mkdtemp(prefix=".sleeper-plugin.", dir=target.parent))
    backup = None
    try:
        shutil.rmtree(staging)
        shutil.copytree(source, staging, symlinks=False)
        (staging / ".sleeper-managed").write_text("Sleeper native plugin\n", encoding="utf-8")
        if os.name == "nt":
            try:
                from scripts.install import _windows_pinned_directories
            except ImportError:
                from install import _windows_pinned_directories
            with _windows_pinned_directories(destination, target.parent):
                if target.exists():
                    backup = target.with_name(f".{target.name}.previous-{secrets.token_hex(8)}")
                    os.replace(target, backup)
                os.replace(staging, target)
                if backup: shutil.rmtree(backup); backup = None
        else:
            parent_fd = _open_directory_beneath(destination, target.parent)
            backup_name = None
            try:
                try:
                    target_fd = os.open(target.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                        dir_fd=parent_fd)
                except FileNotFoundError:
                    target_fd = None
                if target_fd is not None:
                    try:
                        marker = os.stat(".sleeper-managed", dir_fd=target_fd, follow_symlinks=False)
                        if not stat.S_ISREG(marker.st_mode):
                            raise RuntimeError(f"refusing to replace unmarked plugin directory: {target}")
                    finally:
                        os.close(target_fd)
                    backup_name = f".{target.name}.previous-{secrets.token_hex(8)}"
                    os.replace(target.name, backup_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.replace(staging.name, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                if backup_name:
                    _rmtree_at(parent_fd, backup_name)
                    backup_name = None
            finally:
                if backup_name:
                    try: os.replace(backup_name, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    except OSError: pass
                os.close(parent_fd)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if backup and backup.exists() and not target.exists():
            os.replace(backup, target)
    return target


def _write_catalog(market_root: Path, client: str, launcher: str | None) -> None:
    if client == "codex":
        catalog = {"name": "sleeper-local", "interface": {"displayName": "Sleeper"}, "plugins": [{"name": "sleeper", "source": {"source": "local", "path": "./plugins/sleeper"}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]}
    else:
        catalog = {"name": "sleeper-local", "owner": {"name": "Shy Tangerine"}, "plugins": [{"name": "sleeper", "source": "./plugins/sleeper"}]}
    path = market_root / (".agents/plugins/marketplace.json" if client == "codex" else ".claude-plugin/marketplace.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(catalog, indent=2) + "\n", market_root)
    mcp = market_root / "plugins" / "sleeper" / ".mcp.json"
    payload = json.loads(mcp.read_text(encoding="utf-8"))
    payload["mcpServers"]["sleeper"]["command"] = launcher or "sleeper-mcp"
    _atomic_write_text(mcp, json.dumps(payload, indent=2) + "\n", market_root)


_last_command_error = ""


def _run(command: Sequence[str]) -> bool:
    global _last_command_error
    result = subprocess.run(list(command), text=True, capture_output=True, check=False)
    _last_command_error = (result.stderr or result.stdout or "").strip()[-500:]
    return result.returncode == 0


def _normalize_marketplace_path(value: str) -> str:
    """Normalize POSIX and Windows paths without resolving unrelated paths."""
    normalized = value.replace("\\", "/")
    if ":" in normalized[:3] or "\\" in value:
        return ntpath.normcase(ntpath.normpath(normalized)).replace("\\", "/")
    return os.path.normpath(normalized)


def _marketplace_paths_equal(left: str, right: str) -> bool:
    windows_style = ":" in left[:3] or "\\" in left or ":" in right[:3] or "\\" in right
    if windows_style:
        return ntpath.normcase(ntpath.normpath(left.replace("/", "\\"))) == ntpath.normcase(ntpath.normpath(right.replace("/", "\\")))
    return _normalize_marketplace_path(left) == _normalize_marketplace_path(right)


def _marketplace_record_matches(record: object, market_root: Path) -> bool:
    if isinstance(record, list):
        return any(_marketplace_record_matches(value, market_root) for value in record)
    if not isinstance(record, dict):
        return False
    names = [record.get(key) for key in ("name", "marketplace", "id")]
    paths = [record.get(key) for key in ("path", "root", "source")]

    def contains_path(value: object) -> bool:
        if isinstance(value, str):
            return _marketplace_paths_equal(value, str(market_root))
        if isinstance(value, dict):
            return any(contains_path(value.get(key)) for key in ("path", "root", "source"))
        return False

    if "sleeper-local" in names and any(
        contains_path(path)
        for path in paths
    ):
        return True
    return any(_marketplace_record_matches(value, market_root) for value in record.values())


def _registered_marketplace_matches(executable: str, market_root: Path) -> bool | None:
    """Check client state, returning None when the client cannot report it."""
    try:
        result = subprocess.run([executable, "plugin", "marketplace", "list", "--json"],
                                text=True, capture_output=True, check=False)
    except OSError:
        return None
    if result.returncode:
        return None
    try:
        state = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        return False
    return _marketplace_record_matches(state, market_root)


def install_plugins(root: str | Path, destination: str | Path, clients: Sequence[str], launcher: str | None = None) -> set[str]:
    source_root, managed_root = Path(root), Path(destination)
    managed_root.mkdir(parents=True, exist_ok=True)
    installed: set[str] = set()
    pending: set[str] = set()
    errors: dict[str, str] = {}
    status_path = managed_root / ".sleeper-native-plugins.json"
    previous = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    selected = set(clients)
    for client in dict.fromkeys(clients):
        if client not in CLIENTS:
            raise ValueError(f"unsupported native plugin client: {client}")
        executable = _command(client)
        if not executable:
            pending.add(client)
            errors[client] = f"{client} client executable is unavailable"
            continue
        market_root = _marketplace(managed_root, client)
        _copy_adapter(source_root, managed_root, client)
        _write_catalog(market_root, client, launcher)
        add_market = [executable, "plugin", "marketplace", "add", str(market_root)]
        install = ([executable, "plugin", "install", "sleeper@sleeper-local", "--scope", "user"]
                   if client == "claude" else [executable, "plugin", "add", "sleeper", "--marketplace", "sleeper-local"])
        registered = _run(add_market)
        if not registered:
            registered = _registered_marketplace_matches(executable, market_root) is True
        if registered:
            _atomic_write_text(_marketplace_marker(market_root), "Sleeper managed marketplace\n", destination)
        if registered and _run(install):
            installed.add(client)
        else:
            pending.add(client)
            errors[client] = _last_command_error or "marketplace registration or plugin installation failed"
    installed_status = (set(previous.get("installed", [])) - selected) | installed
    pending_status = ((set(previous.get("pending", [])) - selected) | pending) - installed_status
    _atomic_write_text(status_path, json.dumps({"installed": sorted(installed_status), "pending": sorted(pending_status), "errors": errors}, indent=2) + "\n", destination)
    return installed


def uninstall_plugins(destination: str | Path, clients: Sequence[str], launcher: str | None = None) -> set[str]:
    managed_root = Path(destination)
    removed: set[str] = set()
    for client in dict.fromkeys(clients):
        executable = _command(client)
        market_root = managed_root / "marketplaces" / client
        marker = market_root / "plugins" / "sleeper" / ".sleeper-managed"
        if not marker.is_file():
            continue
        registration = _registered_marketplace_matches(executable, market_root) if executable else False
        if registration is not True:
            continue
        remove = ([executable, "plugin", "remove", "sleeper@sleeper-local", "--scope", "user"]
                  if client == "claude" else [executable, "plugin", "remove", "sleeper", "--marketplace", "sleeper-local"])
        if executable and _run(remove):
            marketplace_remove = [executable, "plugin", "marketplace", "remove", "sleeper-local"]
            if _run(marketplace_remove):
                removed.add(client)
                shutil.rmtree(market_root)
    status_path = managed_root / ".sleeper-native-plugins.json"
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["installed"] = sorted(set(status.get("installed", [])) - removed)
        status["pending"] = sorted(set(status.get("pending", [])) - removed)
        _atomic_write_text(status_path, json.dumps(status, indent=2) + "\n", destination)
    return removed
