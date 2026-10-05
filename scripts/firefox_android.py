#!/usr/bin/env python3
"""Run web-ext against a temporary Android package and mirror source changes."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from build_packages import extension_members


def sync_source(source: Path, stage: Path) -> None:
    members = extension_members("firefox-android", source)
    for path in stage.iterdir():
        if path.name not in members:
            path.unlink()
    for name, content in members.items():
        path = stage / name
        if not path.exists() or path.read_bytes() != content:
            pending = stage / (name + ".tmp")
            pending.write_bytes(content)
            pending.replace(path)


def main() -> int:
    command = sys.argv[1:]
    source_index = command.index("--source-dir") + 1
    source = Path(command[source_index])
    with tempfile.TemporaryDirectory(prefix="sleeper-android-") as directory:
        stage = Path(directory)
        sync_source(source, stage)
        command[source_index] = str(stage)
        process = subprocess.Popen(command)
        try:
            while True:
                try:
                    return process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    sync_source(source, stage)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
