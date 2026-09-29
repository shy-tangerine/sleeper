#!/usr/bin/env python3
"""Create a history-free, policy-checked public source candidate.

This exporter intentionally reads the current working tree instead of using
``git archive``.  The staging repository has private historical objects, and
an archive of a commit would also omit reviewed-but-uncommitted changes.  The
candidate is assembled only from tracked files and non-ignored untracked files
that pass the public-tree policy.

The destination must be outside the source checkout and must not already
exist.  A temporary sibling is populated first and atomically renamed, so a
failed export cannot leave a plausible partial candidate behind.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]

# Import the single source of truth for the repository's reviewed public
# boundary.  The checker is deliberately run against the combined tracked and
# non-ignored-untracked set below; ``git ls-files`` alone would miss new files
# in a dirty staging tree.
sys.path.insert(0, str(ROOT))
from scripts.check_public_tree import _is_dev_only, dev_only_entries, violations  # noqa: E402


class ExportError(RuntimeError):
    """A fail-closed export precondition was not met."""


def _open_root(root: Path) -> int:
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ExportError("secure source traversal is unavailable on this platform")
    absolute = Path(os.path.abspath(root))
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ExportError("cannot safely open directory path") from exc


def _open_checked(root_descriptor: int, relative: str) -> int:
    """Open a source file without following any path component."""
    parts = PurePosixPath(relative).parts
    directories = [os.dup(root_descriptor)]
    try:
        for part in parts[:-1]:
            directories.append(
                os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directories[-1])
            )
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directories[-1])
    except OSError as exc:
        raise ExportError(f"cannot safely open source file: {relative}") from exc
    finally:
        for descriptor in reversed(directories):
            os.close(descriptor)


def _open_output(root_descriptor: int, relative: str) -> int:
    parts = PurePosixPath(relative).parts
    directories = [os.dup(root_descriptor)]
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=directories[-1])
            except FileExistsError:
                pass
            directories.append(
                os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directories[-1])
            )
        return os.open(
            parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directories[-1],
        )
    except OSError as exc:
        raise ExportError(f"cannot safely create output file: {relative}") from exc
    finally:
        for descriptor in reversed(directories):
            os.close(descriptor)


def _copy_checked(source_root: int, output_root: int, relative: str) -> None:
    """Copy one regular file while retaining and rechecking its identity."""
    descriptor = _open_checked(source_root, relative)
    output_descriptor = -1
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ExportError(f"source changed or is not a regular file: {relative}")
        output_descriptor = _open_output(output_root, relative)
        with os.fdopen(descriptor, "rb", closefd=False) as input_file, \
             os.fdopen(output_descriptor, "wb", closefd=False) as output_file:
            shutil.copyfileobj(input_file, output_file)
        after = os.fstat(descriptor)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity:
            raise ExportError(f"source changed during export: {relative}")
        os.fchmod(output_descriptor, stat.S_IMODE(before.st_mode))
        os.utime(output_descriptor, ns=(before.st_atime_ns, before.st_mtime_ns))
    finally:
        os.close(descriptor)
        if output_descriptor >= 0:
            os.close(output_descriptor)


def _git_paths(root: Path, *args: str) -> list[str]:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z", *args],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "output", b"").decode("utf-8", "replace").strip()
        raise ExportError(f"cannot read the Git file set: {detail or exc}") from exc
    return [path for path in output.decode("utf-8", "surrogateescape").split("\0") if path]


def candidate_paths(root: Path) -> list[str]:
    """Return existing tracked and non-ignored untracked files."""
    if not (root / ".git").exists() and not (root / ".git").is_file():
        raise ExportError("source must be a Git checkout; refusing an unscoped directory export")
    paths = set(_git_paths(root))
    paths.update(_git_paths(root, "--others", "--exclude-standard"))
    existing: list[str] = []
    for raw in sorted(paths):
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise ExportError(f"unsafe Git path: {raw}")
        source = root.joinpath(*relative.parts)
        # A symlink could point out of the reviewed source tree or change
        # between policy checking and copy.  Refuse it, including symlinked
        # parent directories.
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ExportError(f"symlink is not exportable: {raw}")
        if source.is_file():
            existing.append(relative.as_posix())
    return existing


def _open_destination(root: Path, destination: Path) -> tuple[Path, int]:
    source = Path(os.path.abspath(root))
    target = Path(os.path.abspath(destination.expanduser()))
    if target == source or source in target.parents:
        raise ExportError("destination must be outside the source checkout")
    parent_descriptor = _open_root(target.parent)
    try:
        current = target.parent.stat(follow_symlinks=False)
        opened = os.fstat(parent_descriptor)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ExportError("destination parent changed during export")
        if opened.st_uid != os.getuid():
            raise ExportError("destination parent must be owned by the current user")
        if opened.st_mode & 0o002 and not opened.st_mode & stat.S_ISVTX:
            raise ExportError("world-writable destination parent requires the sticky bit")
        try:
            os.stat(target.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return target, parent_descriptor
        raise ExportError(f"destination already exists: {target}")
    except Exception:
        os.close(parent_descriptor)
        raise


def _require_directory_identity(path: Path, descriptor: int, label: str) -> None:
    try:
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ExportError(f"{label} changed during export") from exc
    opened = os.fstat(descriptor)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise ExportError(f"{label} changed during export")


def export_tree(root: Path, destination: Path, *, dry_run: bool = False) -> list[str]:
    root_descriptor = _open_root(root)
    parent_descriptor = -1
    try:
        target, parent_descriptor = _open_destination(root, destination)
        paths = candidate_paths(root)
        dev_only = dev_only_entries(root)
        if dev_only:
            # Staging-only files registered in dev-only.txt never ship.
            paths = [path for path in paths if not _is_dev_only(path, dev_only)]
        try:
            current_root = root.stat(follow_symlinks=False)
        except OSError as exc:
            raise ExportError("source root changed during export") from exc
        opened_root = os.fstat(root_descriptor)
        if (current_root.st_dev, current_root.st_ino) != (opened_root.st_dev, opened_root.st_ino):
            raise ExportError("source root changed during export")
        blocked = violations(paths)
        if blocked:
            details = "\n".join(f"- {path}" for path in blocked)
            raise ExportError(
                "public-tree policy rejected files; review or remove them before exporting:\n" + details
            )
        if dry_run:
            return paths

        temporary_name = f".{target.name}.{secrets.token_hex(8)}"
        os.mkdir(temporary_name, 0o700, dir_fd=parent_descriptor)
        temporary_descriptor = os.open(
            temporary_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_descriptor,
        )
        reserved_target = False
        try:
            for relative in paths:
                _copy_checked(root_descriptor, temporary_descriptor, relative)
            os.close(temporary_descriptor)
            temporary_descriptor = -1
            _require_directory_identity(target.parent, parent_descriptor, "destination parent")
            try:
                os.mkdir(target.name, 0o700, dir_fd=parent_descriptor)
                reserved_target = True
            except FileExistsError as exc:
                raise ExportError(f"destination appeared during export: {target}") from exc
            os.rename(
                temporary_name, target.name,
                src_dir_fd=parent_descriptor, dst_dir_fd=parent_descriptor,
            )
            reserved_target = False
        except Exception:
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            try:
                shutil.rmtree(temporary_name, dir_fd=parent_descriptor)
            except (FileNotFoundError, TypeError):
                pass
            if reserved_target:
                try:
                    os.rmdir(target.name, dir_fd=parent_descriptor)
                except OSError:
                    pass
            raise
        return paths
    finally:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        os.close(root_descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a policy-checked public source candidate without Git history."
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="new, empty-free destination outside this checkout (must not already exist)",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the complete file set and print paths without copying",
    )
    args = parser.parse_args(argv)
    root = args.source_root.expanduser().resolve()
    try:
        paths = export_tree(root, args.destination, dry_run=args.dry_run)
    except ExportError as exc:
        print(f"PUBLIC EXPORT: FAILED\n{exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"PUBLIC EXPORT: PASS (dry run; {len(paths)} files)")
        for path in paths:
            print(path)
    else:
        print(f"PUBLIC EXPORT: PASS ({len(paths)} files copied; Git history omitted)")
        print(f"destination: {args.destination.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
