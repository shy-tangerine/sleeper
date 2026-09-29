#!/usr/bin/env python3
"""Install, update, and remove Sleeper without clobbering user state."""
from __future__ import annotations
import argparse, json, os, secrets, shutil, shlex, stat, subprocess, sys, tempfile, zipfile
from contextlib import contextmanager
from urllib.error import URLError
from urllib.request import urlopen
from xml.sax.saxutils import escape as _escape_xml
from pathlib import Path, PurePosixPath

PRODUCT = "sleeper"
FIREFOX_NATIVE_HOST = "com.shy_tangerine.sleeper"
FIREFOX_EXTENSION_ID = "sleeper@shy-tangerine"


def _safe_manifest_entry(value):
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def _reject_symlink_path(path, stop=None):
    path = Path(path).absolute()
    stop = Path(stop).absolute() if stop is not None else Path(path.anchor)
    current = path
    checked = []
    while current != stop and current != current.parent:
        checked.append(current)
        current = current.parent
    if current != stop:
        raise RuntimeError(f"destination escapes managed root: {path}")
    if stop.is_symlink():
        raise RuntimeError(f"refusing symlink destination: {stop}")
    for component in reversed(checked):
        if component.is_symlink():
            raise RuntimeError(f"refusing symlink destination: {component}")


def _open_pinned_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    current = os.stat(path, follow_symlinks=False)
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        os.close(descriptor)
        raise RuntimeError(f"destination directory changed while opening: {path}")
    return descriptor


def _open_directory_beneath(root, path):
    root = Path(root).absolute()
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"destination escapes managed root: {path}") from exc
    descriptor = _open_pinned_directory(root)
    try:
        for component in relative.parts:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _windows_pinned_directories(root, path):
    if os.name != "nt":
        yield
        return
    import ctypes
    from ctypes import wintypes
    root = Path(root).absolute(); path = Path(path).absolute()
    try: relative = path.relative_to(root)
    except ValueError as exc: raise RuntimeError(f"destination escapes managed root: {path}") from exc
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetFileAttributesW.restype = wintypes.DWORD
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = wintypes.HANDLE(-1).value
    handles = []
    current = root
    try:
        for component in (None, *relative.parts):
            if component is not None: current /= component
            attributes = kernel32.GetFileAttributesW(str(current))
            if attributes == 0xFFFFFFFF or attributes & 0x400:
                raise RuntimeError(f"refusing reparse-point destination: {current}")
            handle = kernel32.CreateFileW(str(current), 0, 0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None)
            if handle == invalid:
                raise OSError(ctypes.get_last_error(), f"cannot pin destination directory: {current}")
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles): kernel32.CloseHandle(handle)


def _atomic_copy_file(source, target, managed_root=None):
    target = Path(target)
    root = managed_root or target.parent
    _reject_symlink_path(target.parent, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(target, root)
    if os.name == "nt":
        with _windows_pinned_directories(root, target.parent):
            fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as output, open(source, "rb") as input_file:
                    shutil.copyfileobj(input_file, output); output.flush(); os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return
    parent_fd = _open_directory_beneath(root, target.parent)
    temporary_name = f".{target.name}.{secrets.token_hex(16)}"
    temporary = target.parent / temporary_name
    fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "wb") as output, open(source, "rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), os.stat(source, follow_symlinks=False).st_mode & 0o777)
        os.replace(temporary_name, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def _atomic_write_text(path, content, managed_root=None):
    path = Path(path)
    root = managed_root or path.parent
    _reject_symlink_path(path.parent, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(path, root)
    if os.name == "nt":
        with _windows_pinned_directories(root, path.parent):
            fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(content); output.flush(); os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return
    parent_fd = _open_directory_beneath(root, path.parent)
    temporary_name = f".{path.name}.{secrets.token_hex(16)}"
    fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def _rmtree_at(parent_fd, name):
    directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        for child in os.listdir(directory_fd):
            mode = os.stat(child, dir_fd=directory_fd, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                _rmtree_at(directory_fd, child)
            else:
                os.unlink(child, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _replace_staged_tree(staging, target, managed_root):
    target = Path(target)
    _reject_symlink_path(target, managed_root)
    if os.name == "nt":
        backup = None
        with _windows_pinned_directories(managed_root, target.parent):
            try:
                if target.exists():
                    backup = target.with_name(f".{target.name}.previous-{secrets.token_hex(8)}")
                    os.replace(target, backup)
                os.replace(staging, target)
                if backup:
                    shutil.rmtree(backup)
            except Exception:
                if backup and backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
        return
    parent_fd = _open_directory_beneath(managed_root, target.parent)
    backup_name = None
    try:
        try:
            current = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if current and not stat.S_ISDIR(current.st_mode):
            raise RuntimeError(f"refusing non-directory destination: {target}")
        if current:
            backup_name = f".{target.name}.previous-{secrets.token_hex(8)}"
            os.replace(target.name, backup_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.replace(staging.name, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        if backup_name:
            _rmtree_at(parent_fd, backup_name)
            backup_name = None
    except Exception:
        if backup_name:
            try:
                os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.replace(backup_name, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        raise
    finally:
        try:
            _rmtree_at(parent_fd, staging.name)
        except (FileNotFoundError, NotADirectoryError):
            pass
        os.close(parent_fd)


def _replace_tree_from_zip(archive_path, target, managed_root):
    target = Path(target)
    _reject_symlink_path(target.parent, managed_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_path(target, managed_root)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                member = PurePosixPath(info.filename)
                if member.is_absolute() or any(part in ("", ".", "..") for part in member.parts):
                    raise RuntimeError(f"unsafe archive member: {info.filename}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError(f"refusing archive symlink: {info.filename}")
            archive.extractall(staging)
        _replace_staged_tree(staging, target, managed_root)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _remove_relative(root, relative):
    parts = tuple(relative.parts)
    if os.name == "nt":
        path = root.joinpath(*parts)
        _reject_symlink_path(path.parent, root)
        with _windows_pinned_directories(root, path.parent):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        return
    descriptors = [_open_pinned_directory(root)]
    try:
        for component in parts[:-1]:
            descriptors.append(os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=descriptors[-1]))
        parent_fd = descriptors[-1]
        try:
            mode = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return
        if stat.S_ISDIR(mode):
            try:
                os.rmdir(parts[-1], dir_fd=parent_fd)
            except OSError:
                pass
        else:
            os.unlink(parts[-1], dir_fd=parent_fd)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)

def choose_integrations(args):
    def selection(plugins, mcp=True, skill=None):
        plugins = [] if args.no_plugins else plugins
        return {"mcp": mcp and not args.no_mcp,
                "skill": (not plugins if skill is None else skill) and not args.no_skill,
                "plugins": plugins}

    if args.yes:
        return selection(args.plugins or ["codex", "claude"])
    if args.non_interactive or not sys.stdin.isatty():
        return selection(args.plugins or [])
    print("Sleeper integrations: [1] Everything  [2] Customize", file=sys.stderr)
    choice = input("Choose 1 or 2 [1]: ").strip()
    while choice not in ("", "1", "2"):
        choice = input("Enter 1 or 2 [1]: ").strip()
    if choice in ("", "1"):
        return selection(args.plugins or ["codex", "claude"])
    mcp = input("Install standalone MCP? [Y/n]: ").strip().lower() not in ("n", "no")
    skill = input("Install a standalone skill for other clients? [y/N]: ").strip().lower() in ("y", "yes")
    plugins = [client for client in ("codex", "claude")
               if input(f"Install {client} plugin? [y/N]: ").strip().lower() in ("y", "yes")]
    return selection(plugins, mcp, skill)


def venv_dir():
    return Path(os.environ.get("SLEEPER_VENV_DIR", data_dir() / "venv"))

def uv_executable():
    override = os.environ.get("SLEEPER_UV")
    executable = override or shutil.which("uv")
    if not executable:
        raise RuntimeError(
            "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
        )
    return executable

# copy_tree is the historical name callers rely on; it forwards to the
# managed sync so installs remove stale files without touching user state.
def copy_tree(source, target):
    _sync_managed_tree(source, target)

def _shell_path_file():
    return home() / (".zprofile" if sys.platform == "darwin" else ".profile")


def ensure_cli_path(directory):
    """Register Sleeper's launcher directory without editing unrelated settings."""
    if sys.platform == "win32":
        import winreg
        key_path = r"Environment"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current = ""
            parts = [part for part in current.split(";") if part]
            if str(directory).casefold() not in {part.casefold() for part in parts}:
                parts.append(str(directory))
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(parts))
                winreg.SetValueEx(key, "SleeperPathAdded", 0, winreg.REG_SZ, str(directory))
        return
    path_file = _shell_path_file()
    begin, end = "# >>> Sleeper CLI >>>", "# <<< Sleeper CLI <<<"
    text = path_file.read_text(encoding="utf-8") if path_file.exists() else ""
    if begin not in text:
        import shlex
        path_file.parent.mkdir(parents=True, exist_ok=True)
        block = f"{begin}\nexport PATH={shlex.quote(str(directory))}:$PATH\n{end}\n"
        path_file.write_text(text.rstrip() + "\n\n" + block, encoding="utf-8")


def remove_cli_path():
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                added, _ = winreg.QueryValueEx(key, "SleeperPathAdded")
                current, value_type = winreg.QueryValueEx(key, "Path")
                target = str(added).casefold()
                parts = [part for part in current.split(";") if part.casefold() != target]
                winreg.SetValueEx(key, "Path", 0, value_type, ";".join(parts))
                winreg.DeleteValue(key, "SleeperPathAdded")
        except FileNotFoundError:
            pass
        return
    path_file = _shell_path_file()
    if not path_file.exists():
        return
    begin, end = "# >>> Sleeper CLI >>>", "# <<< Sleeper CLI <<<"
    text = path_file.read_text(encoding="utf-8")
    start = text.find(begin)
    finish = text.find(end, start)
    if start >= 0 and finish >= 0:
        finish += len(end)
        path_file.write_text((text[:start] + text[finish:]).strip() + "\n", encoding="utf-8")


def _daemon_listening():
    import socket
    try:
        with socket.create_connection(("127.0.0.1", int(os.environ.get("SLEEPER_PORT", "8790"))), timeout=0.2):
            return True
    except OSError:
        return False


def xml_escape(value):
    """Escape characters that break the plist token stream in launchctl templates."""
    return _escape_xml(str(value), {"\"": "&quot;", "'": "&apos;"})


def _managed_files_manifest(path):
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {str(entry) for value in payload if (entry := _safe_manifest_entry(value)) is not None}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return set()


def _write_managed_manifest(path, entries):
    data = sorted(str(item) for item in entries)
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", path.parent)


def _native_host_launcher(destination):
    python = _runtime_python()
    script = destination / "daemon/native_messaging_host.py"
    launcher = destination / "daemon/native_messaging_host.cmd" if sys.platform == "win32" else destination / "daemon/native_messaging_host"
    if sys.platform == "win32":
        content = f'@echo off\n"{python}" -u "{script}"\n'
    else:
        content = f"#!/bin/sh\nexec {shlex.quote(str(python))} {shlex.quote(str(script))}\n"
    if launcher.is_symlink():
        raise RuntimeError(f"refusing symlink native messaging launcher: {launcher}")
    if launcher.exists() and launcher.read_text(encoding="utf-8", errors="replace") != content:
        raise RuntimeError(f"refusing to replace unmanaged native messaging launcher: {launcher}")
    if not launcher.exists():
        _atomic_write_text(launcher, content, destination)
    if os.name != "nt":
        os.chmod(launcher, 0o755)
    return launcher


def _native_host_manifest_path(destination):
    if sys.platform == "win32":
        return destination / "daemon" / f"{FIREFOX_NATIVE_HOST}.json"
    if sys.platform == "darwin":
        directory = home() / "Library/Application Support/Mozilla/NativeMessagingHosts"
    else:
        directory = home() / ".mozilla/native-messaging-hosts"
    return directory / f"{FIREFOX_NATIVE_HOST}.json"


def _native_host_manifest(destination, ensure_launcher=True):
    if ensure_launcher:
        launcher = _native_host_launcher(destination)
    else:
        launcher = destination / "daemon/native_messaging_host.cmd" if sys.platform == "win32" else destination / "daemon/native_messaging_host"
    return {
        "name": FIREFOX_NATIVE_HOST,
        "description": "Sleeper managed native messaging host",
        "path": str(launcher),
        "type": "stdio",
        "allowed_extensions": [FIREFOX_EXTENSION_ID],
    }


def _install_native_host(destination):
    path = _native_host_manifest_path(destination)
    payload = _native_host_manifest(destination)
    created = False
    managed_root = home() if path.is_relative_to(home()) else path.parent
    _reject_symlink_path(path.parent, managed_root)
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink native messaging manifest: {path}")
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if existing != payload:
            raise RuntimeError(f"refusing to replace unmanaged native messaging manifest: {path}")
    else:
        _atomic_write_text(path, json.dumps(payload, indent=2) + "\n", path.parent)
        created = True
    if sys.platform == "win32":
        import winreg
        registry_path = rf"Software\Mozilla\NativeMessagingHosts\{FIREFOX_NATIVE_HOST}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "")
            except FileNotFoundError:
                current = None
            if current not in (None, str(path)):
                if created:
                    path.unlink(missing_ok=True)
                raise RuntimeError("refusing to replace foreign Firefox native messaging registration")
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(path))
    return path


def _remove_native_host(destination):
    path = _native_host_manifest_path(destination)
    if sys.platform == "win32":
        import winreg
        registry_path = rf"Software\Mozilla\NativeMessagingHosts\{FIREFOX_NATIVE_HOST}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                current, _ = winreg.QueryValueEx(key, "")
                if current == str(path):
                    winreg.DeleteValue(key, "")
        except FileNotFoundError:
            pass
    managed_root = home() if path.is_relative_to(home()) else path.parent
    try:
        _reject_symlink_path(path.parent, managed_root)
    except RuntimeError:
        return
    if path.is_symlink() or not path.is_file():
        return
    try:
        managed = json.loads(path.read_text(encoding="utf-8")) == _native_host_manifest(destination, ensure_launcher=False)
    except (OSError, json.JSONDecodeError, RuntimeError):
        managed = False
    if managed:
        path.unlink()


def _sync_managed_tree(source, target):
    """Copy a runtime directory while removing only stale files previously managed.

    Files created by users after a successful previous install remain even if not
    present in the packaged source tree. This keeps manual state under the same
    data directory while still removing outdated managed assets.
    """
    if not source.is_dir():
        raise RuntimeError(f"missing runtime directory: {source}")
    _reject_symlink_path(target, target.parent)
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / ".sleeper-managed-files"
    previous = _managed_files_manifest(manifest)
    current = set()
    for item in source.rglob("*"):
        if item == source:
            continue
        rel = item.relative_to(source).as_posix()
        if rel == ".sleeper-managed-files":
            continue
        if item.is_file():
            current.add(rel)
    stale = previous - current
    for rel in sorted(stale, reverse=True):
        safe_rel = _safe_manifest_entry(rel)
        if safe_rel is None:
            continue
        _remove_relative(target, safe_rel)
    for item in source.rglob("*"):
        if item.is_symlink():
            raise RuntimeError(f"refusing symlink in packaged runtime: {item}")
        destination = target / item.relative_to(source)
        if item.is_dir():
            _reject_symlink_path(destination, target)
            destination.mkdir(exist_ok=True)
        elif item.is_file():
            _atomic_copy_file(item, destination, target)
    _write_managed_manifest(manifest, current)


def _stop_windows_daemon(destination):
    """Never kill a process from mutable per-user PID metadata."""
    pid_file = destination / "daemon.pid"
    if not pid_file.exists():
        return False
    raise RuntimeError("refusing to kill a process from a PID file; stop Sleeper manually before updating or uninstalling")


def _windows_startup_command(destination):
    python = venv_dir() / "Scripts/python.exe"
    pythonw = python.with_name("pythonw.exe")
    executable = pythonw if pythonw.is_file() else python
    return f'"{executable}" "{destination / "daemon/daemon.py"}"'


def _install_windows_startup(destination):
    """Register the daemon in the caller's Run key and start it when dormant."""
    import winreg
    python = venv_dir() / "Scripts/python.exe"
    pythonw = python.with_name("pythonw.exe")
    executable = pythonw if pythonw.is_file() else python
    command = _windows_startup_command(destination)
    daemon = destination / "daemon/daemon.py"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        try:
            current, _ = winreg.QueryValueEx(key, "Sleeper")
        except FileNotFoundError:
            current = None
        if current not in (None, command):
            raise RuntimeError("refusing to replace foreign Windows startup entry named Sleeper")
        winreg.SetValueEx(key, "Sleeper", 0, winreg.REG_SZ, command)
    # Do not kill a process we did not start. A running daemon owns the ports;
    # the Run entry makes the updated daemon start on the next logon.
    if not _daemon_listening():
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen([str(executable), str(daemon)], cwd=str(destination), creationflags=flags,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (destination / "daemon.pid").write_text(str(process.pid), encoding="ascii")
    return "HKCU Run: Sleeper"


def _remove_windows_startup(destination):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            getattr(winreg, "KEY_QUERY_VALUE", winreg.KEY_READ) | winreg.KEY_SET_VALUE) as key:
            current, _ = winreg.QueryValueEx(key, "Sleeper")
            if current == _windows_startup_command(destination):
                winreg.DeleteValue(key, "Sleeper")
    except FileNotFoundError:
        pass


def merge_config(path, value):
    current = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            raise RuntimeError(f"MCP config must be a JSON object: {path}")
    servers = current.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"mcpServers must be an object: {path}")
    servers["sleeper"] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")

def remove_config(path):
    if not path.exists():
        return
    current = json.loads(path.read_text(encoding="utf-8"))
    servers = current.get("mcpServers") if isinstance(current, dict) else None
    if isinstance(servers, dict) and _is_managed_json_entry(servers.get("sleeper")):
        del servers["sleeper"]
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")

def remove_codex_config(path):
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    output, skipping = [], False
    for line in lines:
        if line.strip() == "[mcp_servers.sleeper]":
            block = []
            skipping = True
            continue
        if skipping and line.lstrip().startswith("["):
            if not _is_managed_codex_block(block):
                output.extend(["[mcp_servers.sleeper]"] + block)
            skipping = False
        if not skipping:
            output.append(line)
        else:
            block.append(line)
    if skipping and not _is_managed_codex_block(block):
        output.extend(["[mcp_servers.sleeper]"] + block)
    path.write_text(chr(10).join(output).rstrip() + chr(10), encoding="utf-8")


def _is_managed_codex_block(lines):
    assignments = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    expected = {
        f'command = {json.dumps(str(venv_dir() / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")))}',
        f'args = [{json.dumps(str(data_dir() / "daemon/mcp_server.py"))}]',
    }
    return set(assignments) == expected and len(assignments) == len(expected)


def _is_managed_json_entry(entry):
    if not isinstance(entry, dict):
        return False
    command = str(bin_dir() / ("sleeper-mcp.cmd" if sys.platform == "win32" else "sleeper-mcp"))
    return entry == {"command": command}

def remove_managed_codex_config(path):
    remove_codex_config(path)

def remove_managed_json_config(path):
    if not path.exists(): return
    current = json.loads(path.read_text(encoding="utf-8"))
    servers = current.get("mcpServers") if isinstance(current, dict) else None
    entry = servers.get("sleeper") if isinstance(servers, dict) else None
    if _is_managed_json_entry(entry):
        del servers["sleeper"]
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")

def codex_config():
    return Path(os.environ.get("SLEEPER_CODEX_CONFIG", home() / ".codex/config.toml")).expanduser()

def merge_codex_config(path, command):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "[mcp_servers.sleeper]"
    lines = text.splitlines()
    kept, skipping = [], False
    for line in lines:
        if line.strip() == marker:
            skipping = True
            continue
        if skipping and line.lstrip().startswith("["):
            skipping = False
        if not skipping:
            kept.append(line)
    text = chr(10).join(kept)
    quoted = json.dumps(command, ensure_ascii=False)
    daemon_script = json.dumps(str(data_dir() / "daemon/mcp_server.py"), ensure_ascii=False)
    block = f'{marker}\ncommand = {quoted}\nargs = [{daemon_script}]\n'
    path.write_text(text.rstrip() + chr(10) + chr(10) + block, encoding="utf-8")

def config_paths():
    paths = []
    if os.environ.get("SLEEPER_CONFIGURE_CLAUDE") == "1":
        paths.append(Path(os.environ.get("SLEEPER_CLAUDE_CONFIG", home() / ".claude.json")).expanduser())
    return paths

def _valid_firefox_package_structure(path, version):
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            members = {name.replace("\\", "/") for name in archive.namelist()}
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
    if manifest.get("version") != version:
        return False
    member_list = {name.lower() for name in members}
    has_signed_manifest = any(
        name.startswith("meta-inf/") and name.endswith((".rsa", ".dsa", ".ec"))
        for name in member_list
    )
    has_signature_file = any(name.startswith("meta-inf/") and name.endswith(".sf") for name in member_list)
    has_jar_manifest = "meta-inf/manifest.mf" in member_list
    # Cryptographic trust is enforced by Firefox when the user installs the XPI.
    # This preflight only rejects malformed or clearly unsigned-shaped assets.
    return has_signed_manifest and has_signature_file and has_jar_manifest


def firefox_release_package(root):
    """Return a structurally valid version-matched XPI for Firefox to verify."""
    candidate = root / "build/sleeper-firefox.xpi"
    try:
        version = json.loads((root / "extension/manifest.json").read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None
    return candidate if candidate.is_file() and _valid_firefox_package_structure(candidate, version) else None


def acquire_firefox_release_package(root):
    local = firefox_release_package(root)
    if local:
        return local, "local Firefox release package; Firefox verifies its signature during installation"
    version = json.loads((root / "extension/manifest.json").read_text(encoding="utf-8"))["version"]
    url = f"https://github.com/shy-tangerine/Sleeper/releases/download/v{version}/sleeper-firefox.xpi"
    candidate = root / "build/sleeper-firefox.xpi"
    try:
        with urlopen(url, timeout=20) as response:
            payload = response.read(64 * 1024 * 1024 + 1)
        if len(payload) > 64 * 1024 * 1024:
            return None, "Firefox release asset is too large"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=candidate.parent, delete=False) as temp:
            temp.write(payload)
            temporary = Path(temp.name)
        try:
            if not _valid_firefox_package_structure(temporary, version):
                return None, "release Firefox asset is malformed, lacks signature metadata, or has the wrong version"
            temporary.replace(candidate)
        finally:
            temporary.unlink(missing_ok=True)
        return candidate, "downloaded Firefox release package; Firefox verifies its signature during installation"
    except (OSError, URLError) as exc:
        return None, f"Firefox release package pending or unavailable: {exc}"


def build_packages(root):
    builder = root / "scripts/build_packages.py"
    subprocess.run([sys.executable, str(builder), "firefox", str(root / "extension"), str(root / "build/sleeper.xpi")], check=True, cwd=root)
    subprocess.run([sys.executable, str(builder), "chromium", str(root / "extension"), str(root / "build/sleeper-chromium.zip")], check=True, cwd=root)
    packages = [root / "build/sleeper.xpi", root / "build/sleeper-chromium.zip"]
    if any(not package.is_file() for package in packages):
        raise RuntimeError("browser package build did not produce both packages")
    return packages

def install_service(root, destination):
    if sys.platform == "darwin":
        service = home() / "Library/LaunchAgents/com.shy-tangerine.sleeper.plist"
        service.parent.mkdir(parents=True, exist_ok=True)
        content = (root / "packaging/com.shy-tangerine.sleeper.plist").read_text(encoding="utf-8")
        content = content.replace("__SLEEPER_PYTHON__", xml_escape(str(venv_dir() / "bin/python")))
        content = content.replace("__SLEEPER_DAEMON__", xml_escape(str(destination / "daemon/daemon.py")))
        if service.exists():
            current = service.read_text(encoding="utf-8", errors="replace") if not service.is_symlink() else ""
            legacy = content.replace("<!-- Sleeper managed service -->\n", "")
            if service.is_symlink() or current not in (content, legacy):
                raise RuntimeError(f"refusing to replace unmanaged service file: {service}")
        _atomic_write_text(service, content, service.parent)
        launchctl = shutil.which("launchctl")
        if launchctl:
            domain = f"gui/{os.getuid()}"
            # `bootstrap` replaces the deprecated `load`; bootout first makes
            # update idempotent while retaining the same per-user service.
            subprocess.run([launchctl, "bootout", domain, str(service)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([launchctl, "bootstrap", domain, str(service)], check=True)
        return service
    if sys.platform == "win32":
        return _install_windows_startup(destination)
    service_dir = Path(os.environ.get("XDG_CONFIG_HOME", home() / ".config")) / "systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    template = root / "packaging/sleeper.service"
    content = template.read_text(encoding="utf-8")
    def quote(path):
        return '"' + str(path).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'
    content = content.replace("__SLEEPER_ROOT_PATH__", str(destination).replace("%", "%%"))
    content = content.replace("__SLEEPER_PYTHON__", quote(venv_dir() / "bin/python"))
    content = content.replace("__SLEEPER_DAEMON__", quote(destination / "daemon/daemon.py"))
    service = service_dir / "sleeper.service"
    if service.exists():
        current = service.read_text(encoding="utf-8", errors="replace") if not service.is_symlink() else ""
        legacy = content.replace("# .sleeper-managed-service\n", "")
        if service.is_symlink() or current not in (content, legacy):
            raise RuntimeError(f"refusing to replace unmanaged service file: {service}")
    _atomic_write_text(service, content, service.parent)
    systemctl = shutil.which("systemctl")
    if systemctl:
        subprocess.run([systemctl, "--user", "daemon-reload"], check=True)
        subprocess.run([systemctl, "--user", "enable", "--now", "sleeper.service"], check=True)
    return service

def managed_windows_launcher(path, destination):
    if not path.is_file():
        return False
    expected = f'"{venv_dir() / "Scripts/python.exe"}" "{destination / "cli/sleeper.py"}" %*'
    return path.read_text(encoding="utf-8", errors="replace") == f"@echo off\n{expected}\n"


def _managed_mcp_launcher(path, destination):
    if not path.is_file() or ".sleeper-managed-mcp" not in path.read_text(encoding="utf-8", errors="replace"):
        return False
    python = venv_dir() / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    daemon = destination / "daemon/mcp_server.py"
    if sys.platform == "win32":
        expected = f'@echo off\nrem .sleeper-managed-mcp\n"{python}" "{daemon}" %*\n'
    else:
        expected = f"#!/bin/sh\n# .sleeper-managed-mcp\nexec {shlex.quote(str(python))} {shlex.quote(str(daemon))} \"$@\"\n"
    return path.read_text(encoding="utf-8", errors="replace") == expected


def _restart_linux_service():
    if sys.platform != "linux":
        return
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return
    subprocess.run(
        [systemctl, "--user", "restart", "sleeper.service"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _skill_is_unmodified(shared_skill):
    canonical = Path(__file__).resolve().parents[1] / "skills/sleeper"
    if not (shared_skill / ".sleeper-managed").is_file() or not canonical.is_dir():
        return False
    source_files = {p.relative_to(canonical): p.read_bytes() for p in canonical.rglob("*") if p.is_file()}
    installed_files = {p.relative_to(shared_skill): p.read_bytes() for p in shared_skill.rglob("*")
                       if p.is_file() and p.name != ".sleeper-managed"}
    return source_files == installed_files


def _path_referenced(path, values):
    if isinstance(values, dict):
        return any(_path_referenced(path, value) for value in values.values())
    if isinstance(values, list):
        return any(_path_referenced(path, value) for value in values)
    return isinstance(values, str) and str(path) in values


def _custom_config_references(paths, target):
    for path in paths:
        if not path.is_file():
            continue
        contents = path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(contents)
        except json.JSONDecodeError:
            lines = contents.splitlines()
            block = []
            in_sleeper = False
            for line in lines:
                if line.strip() == "[mcp_servers.sleeper]":
                    in_sleeper = True
                    block = []
                elif in_sleeper and line.lstrip().startswith("["):
                    break
                elif in_sleeper:
                    block.append(line)
            if str(target) in contents and not _is_managed_codex_block(block):
                return True
            continue
        entry = parsed.get("mcpServers", {}).get("sleeper") if isinstance(parsed, dict) else None
        if not _is_managed_json_entry(entry) and _path_referenced(target, entry):
            return True
    return False


def _runtime_python() -> Path:
    """The installed venv's interpreter for the current platform."""
    return venv_dir() / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _sync_runtime_files(root, destination):
    """Copy daemon, CLI, recipes, schemas, and project metadata into place."""
    if sys.platform == "win32":
        _stop_windows_daemon(destination)
    copy_tree(root / "daemon", destination / "daemon")
    copy_tree(root / "cli", destination / "cli")
    copy_tree(root / "examples/recipes", destination / "cli/recipes")
    copy_tree(root / "examples/schemas", destination / "cli/schemas")
    for metadata_name in ("pyproject.toml", "uv.lock"):
        metadata = root / metadata_name
        if not metadata.is_file():
            raise RuntimeError(f"missing {metadata}")
        _atomic_copy_file(metadata, destination / metadata_name, destination)


def _sync_venv(root, destination, skip_deps):
    """Materialize the frozen dependency set into the runtime venv."""
    if skip_deps:
        return
    uv_env = os.environ.copy()
    uv_env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir())
    subprocess.run(
        [
            uv_executable(),
            "sync",
            "--project",
            str(destination),
            "--frozen",
            "--no-dev",
            "--no-install-project",
        ],
        check=True,
        env=uv_env,
    )


def _write_cli_launcher(destination):
    """Create (or replace) the managed `sleeper` launcher; refuse foreign files."""
    launcher = bin_dir() / ("sleeper.cmd" if sys.platform == "win32" else "sleeper")
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if launcher.is_symlink():
        if launcher.resolve() != (destination / "cli/sleeper").resolve():
            raise RuntimeError(f"refusing to replace existing symlink: {launcher}")
    elif launcher.exists() and not (sys.platform == "win32" and managed_windows_launcher(launcher, destination)):
        raise RuntimeError(f"refusing to replace existing file: {launcher}")
    if sys.platform == "win32":
        _atomic_write_text(launcher,
            f'@echo off\n"{venv_dir() / "Scripts/python.exe"}" "{destination / "cli/sleeper.py"}" %*\n',
            launcher.parent)
    else:
        parent_fd = _open_pinned_directory(launcher.parent)
        try:
            try: os.unlink(launcher.name, dir_fd=parent_fd)
            except FileNotFoundError: pass
            os.symlink(destination / "cli/sleeper", launcher.name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    ensure_cli_path(bin_dir())
    return launcher


def _write_mcp_launcher(destination, requested):
    """Create the managed sleeper-mcp launcher when MCP or plugins requested it."""
    mcp_launcher = bin_dir() / ("sleeper-mcp.cmd" if sys.platform == "win32" else "sleeper-mcp")
    if not requested:
        return mcp_launcher
    mcp_python = _runtime_python()
    mcp_launcher = bin_dir() / ("sleeper-mcp.cmd" if sys.platform == "win32" else "sleeper-mcp")
    if mcp_launcher.exists() and ".sleeper-managed-mcp" not in mcp_launcher.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"refusing replace existing file: {mcp_launcher}")
    if sys.platform == "win32":
        _atomic_write_text(mcp_launcher, f'@echo off\nrem .sleeper-managed-mcp\n"{mcp_python}" "{destination / "daemon/mcp_server.py"}" %*\n', mcp_launcher.parent)
    else:
        _atomic_write_text(mcp_launcher, f"#!/bin/sh\n# .sleeper-managed-mcp\nexec {shlex.quote(str(mcp_python))} {shlex.quote(str(destination / 'daemon/mcp_server.py'))} \"$@\"\n", mcp_launcher.parent)
        descriptor = os.open(mcp_launcher, os.O_RDONLY | os.O_NOFOLLOW)
        try: os.fchmod(descriptor, 0o755)
        finally: os.close(descriptor)
    return mcp_launcher


def _install_plugins_if_requested(root, destination, choices):
    """Run the native plugin installer when requested; return (installed, pending)."""
    status_path = destination / ".sleeper-native-plugins.json"
    previous_plugins = json.loads(status_path.read_text()) if status_path.is_file() else {}
    plugin_result = previous_plugins.get("installed", [])
    plugin_pending = previous_plugins.get("pending", [])
    if not choices["plugins"]:
        return plugin_result, plugin_pending
    try:
        try:
            from scripts.install_plugins import install_plugins
        except ImportError:
            from install_plugins import install_plugins
        plugin_result = sorted(install_plugins(root, destination, choices["plugins"], str(bin_dir() / ("sleeper-mcp.cmd" if sys.platform == "win32" else "sleeper-mcp"))))
        status_path = destination / ".sleeper-native-plugins.json"
        if status_path.is_file():
            plugin_pending = json.loads(status_path.read_text(encoding="utf-8")).get("pending", [])
        if "codex" in plugin_result:
            remove_managed_codex_config(codex_config())
        if "claude" in plugin_result:
            for config_path in config_paths():
                remove_managed_json_config(config_path)
    except ImportError:
        raise RuntimeError("native plugin installer is unavailable")
    return plugin_result, plugin_pending


def _remove_managed_skill_copy(skill, shared_skill):
    """Delete a plugin-superseded shared copy only when it is managed and identical."""
    managed = (shared_skill / ".sleeper-managed").is_file()
    source_files = {p.relative_to(skill): p.read_bytes() for p in skill.rglob("*") if p.is_file()}
    installed_files = {p.relative_to(shared_skill): p.read_bytes() for p in shared_skill.rglob("*")
                       if p.is_file() and p.name != ".sleeper-managed"}
    if managed and source_files == installed_files:
        shutil.rmtree(shared_skill)
        return []
    return ["Existing shared skill was preserved because it is custom or unmanaged; it may duplicate plugin instructions."]


def _install_shared_skill_copy(skill, shared_skill):
    """Refresh the managed shared copy; an unmanaged copy is preserved with a warning."""
    if shared_skill.exists() and not (shared_skill / ".sleeper-managed").is_file():
        return ["Existing unmanaged shared skill was preserved."]
    _sync_managed_tree(skill, shared_skill)
    _atomic_write_text(shared_skill / ".sleeper-managed", "Sleeper managed skill\n", shared_skill)
    return []


def _reconcile_skill(args, choices, plugin_result):
    """Decide who owns the shared skill after this install; return warnings.

    A plugin owns its instructions. Keep a shared copy only when requested for
    other clients, or when no native plugin could be installed. A managed copy
    identical to the source is removed; a custom/unmanaged copy is preserved
    with a warning because it may carry user edits.
    """
    skill = root_skills_dir()
    shared_skill = _shared_skill_dir()
    warnings = []
    install_skill = choices["skill"] or (not plugin_result and not args.no_skill and not choices["plugins"])
    if plugin_result and not choices["skill"] and shared_skill.exists():
        warnings.extend(_remove_managed_skill_copy(skill, shared_skill))
    if install_skill and skill.is_dir():
        warnings.extend(_install_shared_skill_copy(skill, shared_skill))
    return warnings


def root_skills_dir():
    return Path(__file__).resolve().parents[1] / "skills/sleeper"


def _read_source_id(package):
    """Parse the SOURCE_ID member of a dev package; {} when absent (issue #20)."""
    try:
        with zipfile.ZipFile(package) as archive_file:
            raw = archive_file.read("SOURCE_ID").decode("utf-8")
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError):
        return {}
    identity = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            identity[key.strip()] = value.strip()
    return identity


def _build_and_stage_packages(root, destination, args):
    """Build browser packages into the user's download dir; return staging info."""
    copied = []
    chromium_extension = None
    firefox_signed = None
    firefox_status = "not requested (--no-build)" if args.no_build else "Firefox release package pending"
    if args.no_build:
        return copied, chromium_extension, firefox_signed, firefox_status
    download = downloads_dir()
    download.mkdir(parents=True, exist_ok=True)
    for package in build_packages(root):
        target = download / package.name
        fresh = _read_source_id(package)
        existing = _read_source_id(target) if target.is_file() else {}
        if existing and fresh and existing != fresh:
            print(f"replacing stale same-version package {target.name}: "
                  f"installed source {existing.get('commit','?')[:12]}/{existing.get('content','?')} "
                  f"differs from current build {fresh.get('commit','?')[:12]}/{fresh.get('content','?')}")
        elif existing and fresh:
            print(f"{target.name} matches the current source build "
                  f"({fresh.get('commit','?')[:12]}/{fresh.get('content','?')})")
        _atomic_copy_file(package, target, download)
        copied.append(str(target))
        if package.name.endswith("chromium.zip"):
            extension_dir = destination / "browser/chromium"
            _replace_tree_from_zip(package, extension_dir, destination)
            chromium_extension = str(extension_dir)
    firefox_package, firefox_status = acquire_firefox_release_package(root)
    if firefox_package:
        target = download / firefox_package.name
        _atomic_copy_file(firefox_package, target, download)
        copied.append(str(target))
        firefox_signed = str(target)
    return copied, chromium_extension, firefox_signed, firefox_status


def install(root, args):
    choices = choose_integrations(args)
    args.no_mcp = not choices["mcp"]
    args.no_skill = not choices["skill"]
    destination = data_dir()
    _sync_runtime_files(root, destination)
    _sync_venv(root, destination, args.no_deps)
    _install_native_host(destination)
    launcher = _write_cli_launcher(destination)
    mcp_launcher = _write_mcp_launcher(destination, not args.no_mcp or choices["plugins"])
    plugin_result, plugin_pending = _install_plugins_if_requested(root, destination, choices)
    warnings = _reconcile_skill(args, choices, plugin_result)
    copied, chromium_extension, firefox_signed, firefox_status = _build_and_stage_packages(root, destination, args)
    if not args.no_mcp and "codex" not in plugin_result:
        merge_codex_config(codex_config(), str(_runtime_python()))
    service = None if args.no_service else install_service(root, destination)
    # HIGH-2 (Round 2 review): opting out of service management must not touch
    # systemd - a restart would target a possibly-never-installed unit.
    if not args.no_service:
        _restart_linux_service()
    return {"ok": True, "data": str(destination), "cli": str(launcher), "packages": copied, "chromium_extension": chromium_extension, "firefox_signed": firefox_signed, "firefox_status": firefox_status, "service": str(service) if service else None, "plugins": plugin_result, "plugins_pending": plugin_pending, "mcp": str(mcp_launcher) if mcp_launcher.exists() else None, "warnings": warnings}

def _shared_skill_dir():
    """The user-visible shared skill directory (install and uninstall agree on it)."""
    return Path(os.environ.get("SLEEPER_SKILL_DIR", home() / ".agents/skills/sleeper")).expanduser()


def _remove_native_plugins(destination):
    """Uninstall native plugins; raise if removal is pending so the runtime stays."""
    try:
        try:
            from scripts.install_plugins import uninstall_plugins
        except ImportError:
            from install_plugins import uninstall_plugins
        uninstall_plugins(destination, ("codex", "claude"))
        status_path = destination / ".sleeper-native-plugins.json"
        if status_path.is_file() and json.loads(status_path.read_text()).get("installed"):
            raise RuntimeError("native plugin removal is pending; runtime retained so installed plugins keep working")
    except ImportError:
        pass


def _remove_managed_launchers(destination):
    """Delete only the launchers Sleeper itself wrote; foreign files survive."""
    mcp_launcher = bin_dir() / ("sleeper-mcp.cmd" if sys.platform == "win32" else "sleeper-mcp")
    if _managed_mcp_launcher(mcp_launcher, destination):
        mcp_launcher.unlink()
    if sys.platform == "win32":
        _stop_windows_daemon(destination)
    launcher = bin_dir() / ("sleeper.cmd" if sys.platform == "win32" else "sleeper")
    if launcher.is_symlink() and launcher.resolve() == (destination / "cli/sleeper").resolve():
        launcher.unlink()
    elif sys.platform == "win32" and managed_windows_launcher(launcher, destination):
        launcher.unlink()


def _managed_service_file(service, destination, marker):
    if not service.is_file() or service.is_symlink():
        return False
    text = service.read_text(encoding="utf-8", errors="replace")
    return marker in text and str(destination / "daemon/daemon.py") in text and str(venv_dir()) in text


def _remove_posix_service(destination):
    """Tear down the per-platform daemon service, if this platform has one."""
    if sys.platform == "darwin":
        service = home() / "Library/LaunchAgents/com.shy-tangerine.sleeper.plist"
        if not _managed_service_file(service, destination, "Sleeper managed service"):
            return
        launchctl = shutil.which("launchctl")
        if launchctl:
            domain = f"gui/{os.getuid()}"
            subprocess.run([launchctl, "bootout", domain, str(service)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        service.unlink(missing_ok=True)
    elif sys.platform == "win32":
        _remove_windows_startup(destination)
    elif sys.platform == "linux":
        service = Path(os.environ.get("XDG_CONFIG_HOME", home() / ".config")) / "systemd/user/sleeper.service"
        if not _managed_service_file(service, destination, ".sleeper-managed-service"):
            return
        systemctl = shutil.which("systemctl")
        if systemctl:
            subprocess.run([systemctl, "--user", "disable", "--now", "sleeper.service"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([systemctl, "--user", "daemon-reload"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        service.unlink(missing_ok=True)


def _configs_reference_path(paths, target):
    """True when any preserved config still points at `target` (JSON or TOML text)."""
    for path in paths:
        if not path.is_file():
            continue
        contents = path.read_text(encoding="utf-8")
        try:
            if _path_referenced(target, json.loads(contents)):
                return True
        except json.JSONDecodeError:
            if str(target) in contents:
                return True
    return False


def uninstall():
    destination = data_dir()
    preserved_configs = [codex_config(), *config_paths()]
    mcp_launcher = bin_dir() / ("sleeper-mcp.cmd" if sys.platform == "win32" else "sleeper-mcp")
    config_references_runtime = (_custom_config_references(preserved_configs, destination)
                                 or _custom_config_references(preserved_configs, mcp_launcher))
    _remove_native_plugins(destination)
    _remove_native_host(destination)
    if not config_references_runtime and _managed_mcp_launcher(mcp_launcher, destination):
        mcp_launcher.unlink()
    _remove_managed_launchers(destination)
    _remove_posix_service(destination)

    remove_cli_path()
    remove_managed_codex_config(codex_config())
    warnings = []
    shared_skill = _shared_skill_dir()
    if _skill_is_unmodified(shared_skill):
        shutil.rmtree(shared_skill)
    elif shared_skill.exists():
        warnings.append("Existing shared skill was preserved because it is custom or unmanaged.")
    for path in config_paths():
        remove_config(path)
    references_runtime = _configs_reference_path(preserved_configs, destination)
    if references_runtime or config_references_runtime:
        warnings.append("Runtime was preserved because a customized configuration still references it.")
        runtime_removed = False
    else:
        shutil.rmtree(destination, ignore_errors=True)
        runtime_removed = True
    return {"ok": True, "removed": str(destination) if runtime_removed else None,
            "runtime_preserved": not runtime_removed, "warnings": warnings}


def home():
    """Return the user's home on POSIX, macOS, and Windows."""
    return Path(os.environ.get("USERPROFILE", os.environ.get("HOME", str(Path.home())))).expanduser()


def data_dir():
    override = os.environ.get("SLEEPER_DATA_DIR")
    if override:
        return Path(override).expanduser() / PRODUCT
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = home() / "Library/Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME", home() / ".local/share")
    return Path(base).expanduser() / PRODUCT


def bin_dir():
    override = os.environ.get("SLEEPER_BIN_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", home() / "AppData/Local")) / PRODUCT / "bin"
    if sys.platform == "darwin":
        return home() / "Library/Application Support" / PRODUCT / "bin"
    return Path(os.environ.get("XDG_BIN_HOME", home() / ".local/bin")).expanduser()


def downloads_dir():
    override = os.environ.get("SLEEPER_DOWNLOADS_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", home())) / "Downloads"
    if sys.platform == "darwin":
        return home() / "Downloads"
    return Path(os.environ.get("XDG_DOWNLOAD_DIR", home() / "Downloads")).expanduser()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=("install", "update", "uninstall"), default="install")
    parser.add_argument("--no-service", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-mcp", action="store_true", help="skip MCP registration")
    parser.add_argument("--no-skill", action="store_true", help="skip shared Sleeper skill installation")
    parser.add_argument("--non-interactive", action="store_true", help="use flags without prompting")
    parser.add_argument("--yes", action="store_true", help="install all supported Sleeper integrations")
    parser.add_argument("--plugins", nargs="+", choices=("codex", "claude"), help="install selected native plugins")
    parser.add_argument("--no-plugins", action="store_true", help="skip native plugins")
    parser.add_argument("--no-deps", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        result = uninstall() if args.action == "uninstall" else install(root, args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
