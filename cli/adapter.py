#!/usr/bin/env python3
"""Create and verify adapter definitions inside a configured directory."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def adapter_directory(root: Path, name: str) -> Path:
    """Allow nested relative names, never traversal or symlink escapes."""
    path = Path(name)
    if (not name or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
            or path.is_absolute() or not path.parts
            or any(part in {".", ".."} for part in name.split("/"))):
        raise ValueError("adapter name must be a relative path without traversal")
    directory = (root / path).resolve()
    if not directory.is_relative_to(root.resolve()):
        raise ValueError("adapter name must stay within the adapter directory")
    return directory


def create_adapter(directory: Path, name: str) -> dict:
    if directory.exists():
        raise FileExistsError("adapter directory already exists")
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Publish both scaffold files together; failed writes leave no partial adapter.
    with tempfile.TemporaryDirectory(prefix=".sleeper-adapter-", dir=directory.parent) as temporary:
        staging = Path(temporary)
        definition = {"name": name, "version": 1, "domain": "", "commands": []}
        (staging / "adapter.json").write_text(json.dumps(definition, indent=2) + "\n", encoding="utf-8")
        (staging / "README.md").write_text(
            f"# Sleeper adapter: {name}\n\nDefine commands in adapter.json.\n", encoding="utf-8")
        if directory.exists():
            raise FileExistsError("adapter directory already exists")
        staging.rename(directory)
    return {"ok": True, "created": str(directory)}


def verify_adapter(directory: Path) -> dict:
    adapter = directory / "adapter.json"
    if not adapter.resolve().is_relative_to(directory):
        raise ValueError("adapter definition must stay within its directory")
    if not adapter.is_file():
        return {"ok": False, "error": "adapter not found", "path": str(adapter)}
    data = json.loads(adapter.read_text(encoding="utf-8"))
    errors = []
    if not isinstance(data, dict):
        errors.append("root must be object")
    else:
        if not data.get("name"):
            errors.append("name required")
        if not isinstance(data.get("commands"), list):
            errors.append("commands must be array")
    return {"ok": not errors, "path": str(adapter), "errors": errors}


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"init", "verify"}:
        print(json.dumps({"ok": False, "error": "usage: sleeper adapter init|verify <name>"}))
        return 2
    action, name = sys.argv[1:]
    root = Path(os.environ.get("SLEEPER_ADAPTER_DIR", "adapters")).expanduser()
    try:
        directory = adapter_directory(root, name)
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2
    try:
        result = create_adapter(directory, name) if action == "init" else verify_adapter(directory)
    except (OSError, ValueError) as error:
        result = {"ok": False, "error": f"adapter {action} failed: {error}"}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
