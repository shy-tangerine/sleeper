#!/usr/bin/env bash
# Recipe and schema command implementations for sleeper.
# run_recipe <name> [--json]
# Executes a JSON recipe from recipes/<name>.json. Each step's "args" object is
# wrapped into the exact same {"cmd":..,"args":..} payload a direct CLI call
# would POST, so recipe payloads are byte-identical to hand-invoked commands.
run_recipe() {
  local name="${1:-}" json_flag="${2:-false}"
  [ -n "$name" ] || { echo "error: recipe <name> required" >&2; exit 1; }
  local dir file
  dir="${SLEEPER_ROOT:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)}"
  file="$dir/examples/recipes/$name.json"
  [ -f "$file" ] || { echo "error: recipe not found: $name (expected $file)" >&2; exit 1; }
  export SLEEPER_BASE="$BASE"
  export SLEEPER_TOKEN_FILE="$TOKEN_FILE"
  python3 - "$file" "$json_flag" <<'PYEOF'
import hashlib, hmac, json, os, re, secrets, subprocess, sys, time, urllib.parse, urllib.request

BASE = os.environ.get("SLEEPER_BASE", "http://127.0.0.1:8790")
TOKEN_FILE = os.path.expanduser(os.environ.get("SLEEPER_TOKEN_FILE", "~/.config/browser-sleeper-token"))
DRY = os.environ.get("SLEEPER_DRY_RUN", "0") == "1"
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

def make_payload(cmd, args):
    payload = {"cmd": cmd, "args": args}
    profile = os.environ.get("SLEEPER_PROFILE", "").strip()
    if profile:
        payload["profile"] = profile
    return payload

def substitute(args, elem):
    """Replace {NAME} placeholders in string arg values with the loop element.
    Strings are inserted raw (for URLs/text); non-strings as compact JSON."""
    raw = elem if isinstance(elem, str) else json.dumps(elem, ensure_ascii=False)
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and "{" in v:
            out[k] = PLACEHOLDER.sub(lambda m: raw, v)
        else:
            out[k] = v
    return out

def do_post(payload, dry=DRY):
    data = json.dumps(payload, ensure_ascii=False)
    if dry:                      # mock mode: print the exact payload, no POST
        print(data)
        return data, 200, True
    try:
        with open(TOKEN_FILE, encoding="utf-8") as token_file:
            token = token_file.read().strip()
        if not token:
            raise ValueError("Sleeper daemon credentials are unavailable")
        nonce = secrets.token_hex(16)
        with urllib.request.urlopen(BASE + "/health?nonce=" + urllib.parse.quote(nonce), timeout=3) as response:
            health = json.load(response)
        instance = str(health.get("instance_id", ""))
        expected = hmac.new(token.encode(), f"{nonce}:{instance}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(health.get("identity_proof", "")), expected):
            raise ValueError("daemon identity verification failed")
        body_bytes = data.encode()
        request_nonce = secrets.token_hex(16)
        timestamp = int(time.time())
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        message = f"{instance}\n{request_nonce}\n{timestamp}\nPOST\n/command\n{body_hash}".encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "X-Sleeper-Instance": instance, "X-Sleeper-Nonce": request_nonce,
                   "X-Sleeper-Timestamp": str(timestamp),
                   "X-Sleeper-Proof": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
                   "X-Sleeper-Preamble": hmac.new(token.encode(),
                     f"{instance}\n{request_nonce}\n{timestamp}\nPOST\n/command\n{len(body_bytes)}".encode(), hashlib.sha256).hexdigest()}
        with urllib.request.urlopen(urllib.request.Request(BASE + "/command", body_bytes, headers), timeout=120) as response:
            body = response.read().decode()
            code = response.status
        ok = 200 <= code < 300
        if ok:
            try:
                j = json.loads(body)
                if isinstance(j, dict) and j.get("error"):
                    ok = False
            except Exception:
                pass
        return body, code, ok
    except Exception as e:
        return "", 0, False

def extract_value(raw, ex):
    if raw is None or not ex:
        return None
    try:
        r = subprocess.run(["jq", "-c", ex], input=raw,
                           capture_output=True, text=True)
        if r.returncode != 0:
            return {"jq_error": r.stderr.strip()}
        out = r.stdout.strip()
        if not out:
            return None
        try:
            return json.loads(out)          # single JSON value (scalar/array/obj)
        except json.JSONDecodeError:
            vals = []                        # streaming output, e.g. ".items[].id"
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    vals.append(json.loads(line))
                except json.JSONDecodeError:
                    vals.append(line)
            return vals
    except FileNotFoundError:
        return {"jq_missing": True}

def extract_input(cmd, raw):
    # For the `api` command the extract filter runs against the backend body
    # (result.json), not the transport envelope; for all other commands it runs
    # against the command result. Falls back to raw on any parse error.
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return raw
        inner = obj.get("result")
        if cmd == "api" and isinstance(inner, dict):
            inner = inner.get("json", inner)
        return json.dumps(inner) if inner is not None else raw
    except Exception:
        return raw

def eval_condition(cond, prev):
    if isinstance(cond, str) and cond == "@extract":
        return bool(prev)
    if isinstance(cond, dict):
        if "skip_empty" in cond:
            # skip_empty=true -> skip when prior extract empty (run when non-empty)
            empty = prev is None or prev == [] or prev == "" or prev == {}
            return (not empty) if bool(cond.get("skip_empty")) else empty
        if "eq" in cond:
            return prev == cond.get("eq")
    if prev is None or prev == [] or prev == "":
        return False
    return True

def human(v):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 120 else s[:117] + "..."

def main():
    recipe_file, json_flag = sys.argv[1], (sys.argv[2] == "--json")
    with open(recipe_file) as f:
        recipe = json.load(f)
    name = recipe.get("name", os.path.basename(recipe_file))
    desc = recipe.get("description", "")
    prev_extract = None
    steps = recipe.get("steps", [])
    report, failed = [], None

    for i, step in enumerate(steps, start=1):
        # wait directive (seconds)
        if "cmd" not in step and "wait" in step:
            secs = int(step.get("wait", 0))
            if not DRY:
                time.sleep(secs)
            report.append({"index": i, "directive": "wait", "cmd": "wait",
                           "ok": True, "seconds": secs})
            continue

        cmd = step.get("cmd", "")
        # if_result conditional skip
        if "if_result" in step and not eval_condition(step["if_result"], prev_extract):
            report.append({"index": i, "cmd": cmd, "ok": True, "skipped": True,
                           "reason": "if_result falsy"})
            continue

        args = step.get("args", {})
        ex = step.get("extract")

        if step.get("for_each") is not None:
            iters = prev_extract if isinstance(prev_extract, list) else \
                    ([prev_extract] if prev_extract is not None else [])
            per, all_ok = [], True
            for elem in iters:
                payload = make_payload(cmd, substitute(args, elem))
                resp, code, ok = do_post(payload)
                per.append({"elem": elem, "ok": ok,
                            "extract": extract_value(extract_input(cmd, resp), ex) if ex and not DRY else None})
                all_ok = all_ok and ok
            prev_extract = per
            report.append({"index": i, "cmd": cmd, "ok": all_ok,
                           "for_each": True, "iterations": len(iters),
                           "extract": per if ex else None})
            if not all_ok:
                failed = {"index": i, "cmd": cmd}
                break
        else:
            payload = make_payload(cmd, args)
            resp, code, ok = do_post(payload)
            extracted = extract_value(extract_input(cmd, resp), ex) if ex and not DRY else None
            if ex and not DRY:
                prev_extract = extracted
            report.append({"index": i, "cmd": cmd, "ok": ok, "extract": extracted})
            if not ok:
                failed = {"index": i, "cmd": cmd}
                break

    ok = failed is None
    if json_flag:
        print(json.dumps({"name": name, "ok": ok, "steps": report,
                          "failed_step": failed}, ensure_ascii=False))
    else:
        if desc:
            print("Recipe: %s — %s" % (name, desc))
        for s in report:
            if s.get("skipped"):
                print("[%d] %-9s skipped (%s)" % (s["index"], s["cmd"], s["reason"]))
            elif s.get("directive") == "wait":
                print("[%d] wait %ss ok" % (s["index"], s["seconds"]))
            elif s.get("for_each"):
                print("[%d] %-9s for_each=%d ok=%s" % (
                    s["index"], s["cmd"], s["iterations"], "yes" if s["ok"] else "no"))
            else:
                exv = "" if s.get("extract") is None else " extract=" + human(s["extract"])
                print("[%d] %-9s ok=%s%s" % (s["index"], s["cmd"],
                                             "yes" if s["ok"] else "no", exv))
        if failed:
            print("FAILED at step %d (%s)" % (failed["index"], failed["cmd"]))
        else:
            print("Done. %d/%d steps ok." % (len(report), len(steps)))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
PYEOF
}

schema_json_value() {
  local file="$1" key="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -c ".${key}" "$file"
    return 0
  fi
  python3 - "$file" "$key" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
value = data.get(sys.argv[2]) if isinstance(data, dict) else None
print(json.dumps(value, ensure_ascii=False))
PY
}

schema_raw_value() {
  local file="$1" key="$2" default="${3:-}"
  if command -v jq >/dev/null 2>&1; then
    jq -r ".${key} // \"${default}\"" "$file"
    return 0
  fi
  python3 - "$file" "$key" "$default" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
value = data.get(sys.argv[2]) if isinstance(data, dict) else None
if value is None:
    value = sys.argv[3] or ""
if not isinstance(value, str):
    value = str(value)
print(value)
PY
}


# run_schema <name> [--tab IDX|URL-SUBSTR] [--url URL] [--json]
# Runs a reusable extraction schema from schemas/<name>.json. Each field maps a
# name -> selector (plain string) or -> {"sel":S,"get":"text|html|href|attr:NAME|value"}.
# The fields object is inserted VERBATIM into an `extract` command so the enhanced
# handler shapes it, optionally scoped by schema.selector and targeting a tab.
# If --url is given (or the schema file has a "url" field), that URL is gotos'd
# on the target/active tab first and ~2s allowed for the page to settle.
run_schema() {
  local name="" json_flag="false" url_flag="" tab=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --json) json_flag="true"; shift ;;
      --tab) tab="${2:?tab}"; shift 2 ;;
      --url) url_flag="${2:?url}"; shift 2 ;;
      -*) shift ;;
      *) [ -z "$name" ] && name="$1"; shift ;;
    esac
  done
  [ -n "$name" ] || { echo "error: schema <name> required" >&2; exit 1; }

  local dir file
  dir="${SLEEPER_ROOT:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)}"
 file="$dir/examples/schemas/$name.json"
  [ -f "$file" ] || { echo "error: schema not found: $name (expected $file)" >&2; exit 1; }

  local fields_json selector url
  fields_json=$(schema_json_value "$file" fields)
  [ -n "$fields_json" ] && [ "$fields_json" != "null" ] || {
    echo "error: schema '$name' must define a non-empty 'fields' object" >&2; exit 1; }
  selector=$(schema_raw_value "$file" selector "")
  url="${url_flag:-$(schema_raw_value "$file" url "")}"

  local tab_extra="" selector_extra=""
  if [ -n "$tab" ]; then
    tab_extra=", \"tab\":$(j "$tab")"
  fi

  # optional goto: --url flag wins over the schema's url field
  if [ -n "$url" ]; then
    local goto_payload
    goto_payload="{\"cmd\":\"goto\",\"args\":{\"url\":$(j "$url")$tab_extra}}"
    if [ "${SLEEPER_DRY_RUN:-0}" = "1" ]; then
      post_payload "$goto_payload"
    else
      post_payload "$goto_payload" >/dev/null
      sleep 2
    fi
  fi

  if [ -n "$selector" ]; then
    selector_extra=", \"selector\":$(j "$selector")"
  fi

  local payload
  payload="{\"cmd\":\"extract\",\"args\":{\"map\":$(printf '%s' "$fields_json")$selector_extra$tab_extra}}"
  if [ "${SLEEPER_DRY_RUN:-0}" = "1" ]; then
    post_payload "$payload"
    return 0
  fi

  local resp
  resp=$(post_payload "$payload")
  if [ "$json_flag" = "true" ]; then
    printf '%s' "$resp" | python3 -c 'import json,sys; d=sys.stdin.read()
try: print(json.dumps(json.loads(d), ensure_ascii=False, separators=(",",":")))
except Exception: print(d, end="")'
    echo
  else
    printf '%s' "$resp" | python3 -m json.tool 2>/dev/null || echo "$resp"
  fi
}
