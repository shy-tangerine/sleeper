#!/usr/bin/env python3
"""Portable deterministic extension packager used when Bash/zip are unavailable."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

RUNTIME_FILES = (
    "action-labels.js", "api_host_policy.js", "screenshot.js", "background_tabs.js", "action-state.js", "background_network.js",
    "background_page_hooks.js", "daemon_endpoint.js", "mobile_onboarding.js", "tailscale_setup.js", "debugger_eval.js", "background.js", "content.js", "locators.js", "activity.js", "sleeper.js",
    "popup.html", "popup.css", "popup.js", "options.html", "options.css", "options.js",
    "icon.png", "icon16.png", "icon32.png", "icon48.png", "icon128.png", "icon-active.png", "icon-active16.png",
    "icon-active32.png", "icon-active128.png",
    "icon.svg", "icon-active.svg",
)


def archive(source: Path, output: Path) -> str:
    """Archive every source file (backward-compatible generic mode)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive_file:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive_file.writestr(info, path.read_bytes())
    return hashlib.sha256(output.read_bytes()).hexdigest()


def source_identity(source: Path, manifest_name: str, kind: str) -> dict[str, str]:
    """Reproducible source identity for a dev package (issue #20).

    `commit` records the packaging git commit when available; `content`
    digests exactly the files the package embeds, so two builds from
    identical sources agree and a stale same-version package differs.
    """
    import subprocess
    manifest = json.loads((source / manifest_name).read_text(encoding="utf-8"))
    names = [("manifest.json", source / "manifest.json")]
    names += [(n, source / n) for n in RUNTIME_FILES if (source / n).is_file()]
    if kind == "chromium":
        names.append(("dynamic_code.js", source / "dynamic_code.js"))
    names += [(n, source.parent / n) for n in ("LICENSE", "THIRD_PARTY_NOTICES.md") if (source.parent / n).is_file()]
    digest = hashlib.sha256()
    for name, path in sorted(names):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    try:
        commit = subprocess.run(["git", "-C", str(source.parent), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        commit = "unknown"
    return {"commit": commit, "content": digest.hexdigest()[:16], "version": str(manifest.get("version"))}


def extension_package(kind: str, source: Path, output: Path) -> str:
    manifest_name = "manifest.json" if kind == "firefox" else "manifest.chromium.json"
    manifest = json.loads((source / manifest_name).read_text(encoding="utf-8"))
    if not manifest.get("version"):
        raise ValueError(f"{manifest_name} has no version")
    identity = source_identity(source, manifest_name, kind)
    members: dict[str, bytes] = {
        "manifest.json": json.dumps(manifest, separators=(",", ":")).encode(),
        "SOURCE_ID": "commit={commit}\ncontent={content}\nversion={version}\n".format(**identity).encode(),
    }
    for name in RUNTIME_FILES:
        path = source / name
        if path.is_file():
            members[name] = path.read_bytes()
    if kind == "chromium":
        members["dynamic_code.js"] = (source / "dynamic_code.js").read_bytes()
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        path = source.parent / name
        if path.is_file():
            members[name] = path.read_bytes()
    required = {"manifest.json", "background.js", "content.js", "sleeper.js"}
    missing = required - members.keys()
    if missing:
        raise ValueError(f"extension package missing: {', '.join(sorted(missing))}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive_file:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive_file.writestr(info, members[name])
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", nargs="?", choices=("firefox", "chromium"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.kind:
        digest = extension_package(args.kind, args.source, args.output)
    else:
        digest = archive(args.source, args.output)
    print(f"{args.output}: sha256 {digest}")
    return 0


def read_source_id(package: Path) -> dict[str, str]:
    """Parse the SOURCE_ID member of a dev package; {} when absent."""
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


if __name__ == "__main__":
    raise SystemExit(main())
