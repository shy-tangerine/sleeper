#!/usr/bin/env python3
"""Validate the CLI payloads the mock captured.

Reads MOCK_LOG (one {path,body} per line) and MOCK_EXPECTED (one
"label|expected_cmd" per line, in invocation order). For each captured
request it asserts, in order:
  1. it posted to /command,
  2. the body is valid JSON,
  3. the body has no stray `\\` (double-backslash) escaping artifact,
  4. the JSON `cmd` field matches the expected command name.
Exits non-zero if any assertion fails or counts differ.
"""
import json
import os
import sys


def main():
    log = open(os.environ["MOCK_LOG"], encoding="utf-8").read().splitlines()
    expected = [ln.rstrip("\n") for ln in
                open(os.environ["MOCK_EXPECTED"], encoding="utf-8")
                if ln.strip()]

    if len(log) != len(expected):
        print(f"[FAIL] mock received {len(log)} POSTs, expected "
              f"{len(expected)} commands")
        sys.exit(1)

    fails = 0
    for i, (line, exp) in enumerate(zip(log, expected), 1):
        label, expcmd = exp.split("|", 1)
        try:
            rec = json.loads(line)
        except Exception as e:
            print(f"[FAIL] #{i} {label}: mock log line invalid: {e}")
            fails += 1
            continue

        path = rec.get("path")
        body = rec.get("body", "")
        issues = []
        if path != "/command":
            issues.append(f"path={path!r} (want /command)")
        try:
            obj = json.loads(body)
        except Exception as e:
            issues.append(f"invalid JSON: {e}")
        else:
            if obj.get("cmd") != expcmd:
                issues.append(f"cmd={obj.get('cmd')!r} (want {expcmd!r})")
        if "\\\\" in body:
            issues.append("contains stray double-backslash `\\\\` artifact")
        if issues:
            print(f"[FAIL] #{i} {label}: {'; '.join(issues)}")
            print(f"       body={body}")
            fails += 1
        else:
            print(f"  [PASS] #{i} {label} -> cmd={expcmd}")

    print(f"\npayload checks: {len(expected) - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
