#!/usr/bin/env bash
# Regression harness for the Sleeper extension.
#
#   bash test/run.sh      (works from repo root or anywhere)
#
# In a few seconds, without touching the daemon/browser, it asserts:
#   [1] syntax  — bash -n on the CLI, node --check on every *.js,
#                 python ast.parse on daemon.py (no .pyc written).
#   [2] presence — every content handler in sleeper.js and every
#                  background-side command in background.js is wired.
#   [3] CLI payloads — drives the real `sleeper` CLI at every subcommand
#       against a throwaway mock HTTP server, and verifies each emitted
#       body posts to /command, is valid JSON, has no stray `\"` escaping
#       artifacts, and carries the expected `cmd`.
#
# Runtime prerequisites are bash, Python 3.11+, and node. When `uv sync` has
# created `.venv`, the harness uses that interpreter so Python test dependencies
# do not depend on the caller activating the environment first. The mock is
# started with its own disposable daemon token and always torn down via a trap.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="$ROOT/test"
PYTHON_BIN="${SLEEPER_TEST_PYTHON:-python3}"
[ -x "$ROOT/.venv/bin/python" ] && PYTHON_BIN="$ROOT/.venv/bin/python"
cd "$ROOT"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  [FAIL] $1"; }

have() { command -v "$1" >/dev/null 2>&1; }
for d in bash node; do
    have "$d" || { fail "missing dependency: $d"; }
done
have "$PYTHON_BIN" || { fail "missing dependency: Python 3.11+"; }
if [ "$FAIL" -gt 0 ]; then
    echo "ABORT: missing required dependencies (bash, Python 3.11+, node)"
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo "ABORT: Python 3.11 or newer is required"
    exit 1
fi

if "$PYTHON_BIN" "$ROOT/test/test_redaction.py" >/tmp/sleeper_redaction_test 2>&1; then
  pass "redaction boundary tests"
else
  fail "redaction boundary tests"
fi

if "$PYTHON_BIN" "$ROOT/test/test_daemon_health.py" >/tmp/sleeper_daemon_health_test 2>&1; then
  pass "daemon health secret boundary test"
else
  fail "daemon health secret boundary test"
fi

if "$PYTHON_BIN" "$ROOT/test/test_mcp_server.py" >/tmp/sleeper_mcp_server_test 2>&1; then
  pass "MCP request/schema contract tests"
else
  fail "MCP request/schema contract tests"
fi

if "$PYTHON_BIN" "$ROOT/test/test_docs.py" >/tmp/sleeper_docs_test 2>&1; then
  pass "README/docs contract tests"
else
  fail "README/docs contract tests"
fi

if "$PYTHON_BIN" -m pytest -q "$ROOT/test/test_cli_parity.py" >/tmp/sleeper_cli_parity_test 2>&1; then
  pass "CLI semantic parity tests"
else
  fail "CLI semantic parity tests (run uv sync)"
fi

if "$PYTHON_BIN" "$ROOT/test/test_public_tree.py" >/tmp/sleeper_public_tree_test 2>&1 \
  && "$PYTHON_BIN" "$ROOT/scripts/check_public_tree.py" >>/tmp/sleeper_public_tree_test 2>&1; then
  pass "publishable Git tree excludes maintainer-only state"
else
  fail "public tree boundary: $(tail -20 /tmp/sleeper_public_tree_test)"
fi
if "$PYTHON_BIN" "$ROOT/scripts/build_native_plugins.py" validate >/tmp/sleeper_native_plugin_test 2>&1; then
  pass "native plugin adapters match canonical skill"
else
  fail "native plugin adapters: $(tail -20 /tmp/sleeper_native_plugin_test)"
fi

echo "== Sleeper regression harness =="
echo "repo: $ROOT"
node "$ROOT/test/api_host_policy_test.js" || fail "api host policy behavioral test"
node "$ROOT/test/daemon_endpoint_test.js" || fail "daemon endpoint validation test"
node "$ROOT/test/mobile_onboarding_test.js" || fail "mobile onboarding behavioral test"
node "$ROOT/test/android_background_test.js" || fail "Firefox Android background compatibility test"
node "$ROOT/test/tailscale_setup_test.js" || fail "Tailscale setup behavioral test"
node "$ROOT/test/screenshot_transport_test.js"
node "$ROOT/test/screenshot_behavior_test.js"
node "$ROOT/test/focus_policy_test.js"
node "$ROOT/test/action_icon_timing_test.js"
node "$ROOT/test/action_correctness_test.js"
node "$ROOT/test/action_log_test.js"
node "$ROOT/test/action_showcase_test.js"
node "$ROOT/test/action_labels_test.js" || fail "action label contract test"
node "$ROOT/test/background_tabs_test.js"
node "$ROOT/test/background_network_test.js"
node "$ROOT/test/background_network_download_test.js" || fail "background download wait test"
node "$ROOT/test/background_waitxhr_test.js" || fail "background waitXhr dispatch test"
node "$ROOT/test/background_page_hooks_test.js" || fail "Chromium page-hook injection test"
node "$ROOT/test/content_dialog_idle_test.js" || fail "idle dialog behavior test"
node "$ROOT/test/locators_test.js"
node "$ROOT/test/locator_handlers_test.js" || fail "screenshot transport bound wiring"
node "$ROOT/test/activity_test.js" || fail "activity cue behavior harness"
if node "$ROOT/test/icon_state_test.js"; then
  pass "icon state wiring harness"
else
  fail "icon state wiring harness"
fi
if node "$ROOT/test/browser_identity_test.js"; then
  pass "browser identity harness"
else
  fail "browser identity harness"
fi

# ---------------------------------------------------------------- [1] syntax
echo
echo "-- [1/3] syntax checks --"

if bash -n "$ROOT/cli/sleeper" 2>/tmp/sleeper_syn_err; then
    pass "bash -n sleeper (CLI)"
else
    fail "bash -n sleeper: $(cat /tmp/sleeper_syn_err)"
fi

if bash -n "$ROOT/install.sh" 2>/tmp/sleeper_install_syn_err; then
    pass "bash -n install.sh"
else
    fail "bash -n install.sh: $(cat /tmp/sleeper_install_syn_err)"
fi

for f in action-labels.js screenshot.js background_tabs.js action-state.js background_network.js background_page_hooks.js daemon_endpoint.js mobile_onboarding.js tailscale_setup.js debugger_eval.js locators.js activity.js sleeper.js background.js content.js popup.js options.js; do
    f=extension/$f
    if node --check "$ROOT/$f" 2>/tmp/sleeper_js_err; then
        pass "node --check $f"
    else
        fail "node --check $f: $(cat /tmp/sleeper_js_err)"
    fi
done

# ast.parse instead of py_compile so no .pyc is written into the repo.
if "$PYTHON_BIN" -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" \
        "$ROOT/daemon/daemon.py" 2>/tmp/sleeper_py_err; then
    pass "python3 ast.parse daemon.py"
else
    fail "python3 ast.parse daemon.py: $(cat /tmp/sleeper_py_err)"
fi

# ------------------------------------------------------------ [2] presence
echo
echo "-- [2/3] handler / command presence --"

# Content handlers must be defined as methods in sleeper.js.
# NOTE: the task's "goto/newtab/tabs/network" are background-side commands
# (asserted below), and "select" maps to the sleeper.js `selectOption`
# handler — those live where they are actually handled.
cont_pat() { printf '(^|[^A-Za-z0-9_])%s\\(' "$1"; }
for h in upload drag dblclick check uncheck clickText scrollUntil \
        waitDialog waitFor waitText findText exec read fillForm extract \
        selectOption; do
    if grep -qE "$(cont_pat "$h")" "$ROOT/extension/sleeper.js"; then
        pass "sleeper.js handler: $h"
    else
        fail "sleeper.js handler missing: $h"
    fi
done

# Background-side commands must be dispatched in background.js.
# The dispatcher is a handler table (BACKGROUND_COMMAND_HANDLERS) keyed by
# wire command name, with routePageCommand as the fallback for page commands,
# so presence is asserted against the table keys instead of the old inline
# "msg.cmd === ..." chain.
for c in api console waitXhr dialog newtab goto tabs network shot tabinfo; do
    if grep -qE "^\\s*$c:\\s" "$ROOT/extension/background.js" && \
       grep -q "BACKGROUND_COMMAND_HANDLERS" "$ROOT/extension/background.js"; then
        pass "background.js command: $c"
    else
        fail "background.js command missing: $c"
    fi
done

 # Toolbar controls are intentionally small and agent-safe: they expose status,
 # access scope, and the local action log without adding page automation UI.
if grep -q "default_popup" "$ROOT/extension/manifest.json"; then
    pass "manifest.json exposes toolbar controls"
else
    fail "manifest.json is missing toolbar controls"
fi
if [ -e "$ROOT/extension/popup.html" ] && [ -e "$ROOT/extension/options.html" ]; then
    pass "settings and status pages present"
else
    fail "settings/status pages missing"
fi

# ------------------------------------------------- [3] CLI payload mock test
echo
echo "-- [3/3] CLI payload mock verification --"

MOCK_LOG="$(mktemp)"
MOCK_PORT_FILE="$(mktemp)"
MOCK_READY="$(mktemp)"
MOCK_EXPECTED="$(mktemp)"
MOCK_TOKEN="$(mktemp)"
printf '%s\n' 'sleeper-test-token' >"$MOCK_TOKEN"
export SLEEPER_TOKEN_FILE="$MOCK_TOKEN"

MOCK_LOG="$MOCK_LOG" MOCK_PORT_FILE="$MOCK_PORT_FILE" \
    MOCK_READY="$MOCK_READY" "$PYTHON_BIN" "$TEST_DIR/mock.py" 0 >/dev/null 2>&1 &
MOCK_PID=$!

cleanup() {
    kill "$MOCK_PID" 2>/dev/null
    wait "$MOCK_PID" 2>/dev/null
    rm -f "$MOCK_LOG" "$MOCK_PORT_FILE" "$MOCK_READY" "$MOCK_EXPECTED" "$MOCK_TOKEN" \
        /tmp/sleeper_syn_err /tmp/sleeper_js_err /tmp/sleeper_py_err
}
trap cleanup EXIT

for _ in $(seq 1 50); do
    [ -s "$MOCK_READY" ] && break
    sleep 0.1
done
if [ ! -s "$MOCK_READY" ]; then
    fail "mock server failed to start"
    exit 1
fi
PORT="$(cat "$MOCK_PORT_FILE")"
export SLEEPER_PORT="$PORT"
echo "  mock listening on 127.0.0.1:$PORT"

# run_cli <label> <expected_cmd> <sleeper-args...>   (first sleeper-arg is the subcommand)
run_cli() {
    local label="$1" expcmd="$2"
    shift 2
    if "$ROOT/cli/sleeper" "$@" >/dev/null 2>&1; then
        echo "$label|$expcmd" >>"$MOCK_EXPECTED"
    else
        fail "cli '$label' exited non-zero"
    fi
}

run_cli state            state            state
run_cli tabs             tabs             tabs
run_cli snapshot         snapshot         snapshot
run_cli forms            forms            forms
run_cli newtab           newtab           newtab 'https://x.com/?a=1&b=2'
run_cli goto             goto             goto 'https://example.com/search?q=macbook&lang=en'
run_cli wait_url         wait_url         wait_url 'sso/register' --timeout 5000 --tab 1
run_cli find             find             find 'input[placeholder*="Buscar"]'
run_cli click            click            click 'button[type=submit]'
run_cli click_all        clickAll         click_all 'a.buy'
run_cli hover            hover            hover '#nav'
run_cli focus            focus            focus 'input[name=q]'
run_cli find_text        findText         find_text 'Add to cart'
run_cli click_text       clickText        click_text 'Buy now' --verify 'input.qty'
run_cli wait_text        waitText         wait_text 'Loading' --timeout 2000
run_cli type             type             type 'input[name=q]' 'macbook pro' --clear
run_cli keys             keys             keys Enter Tab ArrowDown
run_cli press            press            press Enter --selector 'input'
run_cli read             read             read 'h1' --attr href
run_cli read_all         readAll          read_all '.item' --html
run_cli submit           submit           submit
run_cli wait             waitFor          wait 'div.result' --timeout 5000
run_cli wait_until       waitUntil        wait_until 'document.querySelectorAll(".x").length > 0'
run_cli exec             exec             exec 'return document.title'
run_cli fill_form        fillForm         fill_form '{"q":"macbook"}'
run_cli select           selectOption     select 'select#sort' 'relevance'
run_cli extract          extract          extract '{"title":"h1","prices":".price"}'
run_cli scroll_px        scroll           scroll 400
run_cli scroll_sel       scroll           scroll --selector 'footer'
run_cli scroll_until     scrollUntil      scroll_until --text 'Load more' --max 10
run_cli wait_dialog      waitDialog       wait_dialog --text 'Are you sure' --timeout 5000
run_cli network          network          network --media --since=60
run_cli api_delete       api              api '/backend-api/x' --method DELETE --body '{"a":1}'
run_cli console          console          console --lines 5
run_cli upload           upload           upload 'input[type=file]' --files "$ROOT/examples/recipes/chatgpt-export-titles.json"
# NOTE: upload --files now embeds file contents (name + content_base64) per the
# extension contract (sleeper.js upload handler), so the harness passes a real
# repo file instead of the old filename-only form (which the extension rejects).
run_cli drag             drag             drag '#src' '#tgt'
run_cli dblclick         dblclick         dblclick '#btn'
run_cli check            check            check '#cb'
run_cli uncheck          uncheck          uncheck '#cb'
run_cli wait_xhr         waitXhr          wait_xhr '/api/load' --method POST --timeout 5000
run_cli dialog           dialog           dialog
run_cli back             back             back
run_cli frames           frames           frames
run_cli get              get              get
run_cli get_sel          get              get --selector 'h1'
run_cli shot             shot             shot
run_cli screenshot_alias shot             screenshot

if MOCK_LOG="$MOCK_LOG" MOCK_EXPECTED="$MOCK_EXPECTED" \
        "$PYTHON_BIN" "$TEST_DIR/validate_payloads.py"; then
    :
else
    FAIL=$((FAIL + 1))
fi

# -------------------------------------------------- [3b] recipe regression
echo
echo "-- [3b] recipe regression --"

RECIPE_FAIL=0
for rf in "$ROOT"/recipes/*.json; do
    [ -e "$rf" ] || continue
    if jq -e . "$rf" >/dev/null 2>&1; then
        pass "recipe parses: $(basename "$rf")"
    else
        fail "recipe INVALID JSON: $(basename "$rf")"
        RECIPE_FAIL=1
    fi
done

# The recipe subcommand must resolve recipes under the repo recipes/ dir
# (regression for the symlink dirname-$0 bug) and execute a step in dry-run
# (no POST, no extract) reporting ok:true.
if SLEEPER_DRY_RUN=1 "$ROOT/cli/sleeper" recipe chatgpt-export-titles --json \
        >/tmp/sleeper_recipe_out 2>&1 && grep -q '"ok": true' /tmp/sleeper_recipe_out; then
    pass "recipe executor resolves + dry-run ok"
else
    fail "recipe executor: $(tail -2 /tmp/sleeper_recipe_out)"
    RECIPE_FAIL=1
fi
[ "$RECIPE_FAIL" -eq 0 ] || FAIL=$((FAIL + 1))

# -------------------------------------------------- [4] manual XPI packaging
echo
echo "-- [4/4] manual XPI packaging --"
# Packaging is deliberately a manual operation. Verify the manifest has no
# automatic update URL, the daemon has no package/update server, and the build
# script still produces a usable XPI without creating an updates artifact.

if "$PYTHON_BIN" - <<'PY'
import json, os, re, subprocess, sys, zipfile
root = os.environ.get("SLEEPER_ROOT", os.getcwd())
manifest = json.load(open(os.path.join(root, "extension/manifest.json")))
if "update_url" in manifest.get("browser_specific_settings", {}).get("gecko", {}):
    print("FAIL manifest still declares update_url"); sys.exit(1)
daemon = open(os.path.join(root, "daemon/daemon.py"), encoding="utf-8").read()
if re.search(r"TLS|ssl|run_https|UpdateHandler|updates\\.json|8791", daemon, re.I):
    print("FAIL daemon still contains TLS/update-server code"); sys.exit(1)
if os.path.exists(os.path.join(root, "build/updates.json")):
    print("FAIL obsolete build/updates.json artifact exists"); sys.exit(1)
subprocess.run([os.path.join(root, "scripts/build-xpi.sh")], check=True,
               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
expected_members = {
    "action-labels.js",
    "api_host_policy.js",
    "background_tabs.js",
    "action-state.js",
    "background_network.js",
    "background_page_hooks.js",
    "daemon_endpoint.js",
    "mobile_onboarding.js",
    "tailscale_setup.js",
    "background.js",
    "screenshot.js",
    "content.js",
    "icon-active.png",
    "icon-active128.png",
    "icon-active16.png",
    "icon-active32.png",
    "icon.png",
    "icon128.png",
    "icon16.png",
    "icon32.png",
    "icon48.png",
    "manifest.json",
    "options.css",
    "options.html",
    "options.js",
    "popup.css",
    "popup.html",
"popup.js",
"LICENSE",
"THIRD_PARTY_NOTICES.md",
    "locators.js",
    "activity.js",
    "icon.svg",
    "icon-active.svg",
    "sleeper.js",
    "SOURCE_ID",
}
try:
    with zipfile.ZipFile(os.path.join(root, "build/sleeper.xpi")) as z:
        actual_members = set(z.namelist())
        if actual_members != expected_members:
            print("FAIL unexpected XPI members: %s" % sorted(actual_members ^ expected_members))
            sys.exit(1)
        xpi_manifest = json.loads(z.read("manifest.json"))
        version = xpi_manifest.get("version", "")
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){0,3}", version):
            print("FAIL invalid Firefox version: %s" % version); sys.exit(1)
        if "update_url" in xpi_manifest.get("browser_specific_settings", {}).get("gecko", {}):
            print("FAIL XPI manifest still declares update_url"); sys.exit(1)
except Exception as e:
    print("FAIL XPI manifest unreadable: %s" % e); sys.exit(1)
print("OK manual XPI has no automatic update URL")
print("OK XPI contains exactly the approved public runtime files")
for name in ("action-labels.js", "background.js", "background_tabs.js", "action-state.js", "background_network.js", "background_page_hooks.js", "daemon_endpoint.js", "mobile_onboarding.js", "tailscale_setup.js", "screenshot.js", "content.js", "locators.js", "activity.js", "sleeper.js"):
    with zipfile.ZipFile(os.path.join(root, "build/sleeper.xpi")) as z:
        if z.read(name) != open(os.path.join(root, "extension", name), "rb").read():
            print("FAIL XPI payload differs from current %s" % name); sys.exit(1)
print("OK XPI payloads match current sources")
for name in ("icon-active.png", "icon-active16.png", "icon-active32.png", "icon-active128.png"):
    with zipfile.ZipFile(os.path.join(root, "build/sleeper.xpi")) as z:
        if name not in z.namelist():
            print("FAIL XPI missing active icon %s" % name); sys.exit(1)
print("OK XPI contains all active icons")
PY
then
    pass "manual XPI packaging (no TLS/update server)"
else
    fail "manual XPI packaging"
fi

# ----------------------------------------------------------------- summary
echo
echo "== SUMMARY: $PASS passed, $FAIL failed =="
if [ "$FAIL" -eq 0 ]; then
    exit 0
else
    exit 1
fi
