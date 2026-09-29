// Regression: goto must reply only after the tab finishes loading (or the
// hard cap), so follow-up commands act on the NEW page. Pins the settle
// listener: fires once on status=complete, removes itself, reports the
// final URL, and the timeout fallback settles with the requested URL.
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

// Objects created inside the vm realm have a foreign Object.prototype, so
// deepStrictEqual rejects them; compare structurally instead.
function sameJson(a, b) {
  assert.strictEqual(JSON.stringify(a), JSON.stringify(b));
}

const source = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background.js"), "utf8");
const start = source.indexOf("const GOTO_SETTLE_TIMEOUT_MS");
const end = source.indexOf("// Diagnostic: resolve + tabs.get only", start);
assert.ok(start > 0 && end > start, "handleGotoCommand extracted");

function harness({ completeAfterMs = 20, finalUrl = "https://new.example/" } = {}) {
  const timers = [];
  let listeners = [];
  let resolved = null;
  const chrome = {
    runtime: { lastError: null },
    tabs: {
      update(_id, _chg, cb) { cb({ id: 7, url: "about:blank" }); },
      get(_id, cb) { cb({ id: 7, url: finalUrl }); },
      onUpdated: {
        addListener(fn) { listeners.push(fn); },
        removeListener(fn) { listeners = listeners.filter((l) => l !== fn); },
      },
    },
  };
  const context = {
    chrome,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => {},
    console,
    URL,
  };
  context.resolveTabId = () => 7;
  context.refreshRegistry = () => {};
  context.sendResult = (_id, result) => { resolved = { ok: true, result }; };
  context.sendError = (_id, error) => { resolved = { ok: false, error }; };
  vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.handleGotoCommand = handleGotoCommand;`, context);
  return {
    call: () => { context.handleGotoCommand({ id: 1, args: { url: "https://new.example/" } }); return listeners.length; },
    fireComplete: () => listeners.forEach((fn) => fn(7, { status: "complete" })),
    fireCompleteOtherTab: () => listeners.forEach((fn) => fn(99, { status: "complete" })),
    runTimers: () => timers.splice(0).forEach((t) => t.fn()),
    timerMs: () => timers.map((t) => t.ms),
    listenerCount: () => listeners.length,
    resolved: () => resolved,
    resolve: (v) => { resolved = v; },
  };
}

(async () => {
  // 1. onUpdated complete settles the reply with the FINAL URL and cleans up.
  const h = harness();
  assert.strictEqual(h.call(), 1, "one listener registered");
  h.fireCompleteOtherTab();
  assert.strictEqual(h.resolved(), null, "other tabs' updates ignored");
  h.fireComplete();
  sameJson(h.resolved().result, { tabId: 7, url: "https://new.example/", requested: "https://new.example/", navigating: false });
  assert.strictEqual(h.listenerCount(), 0, "listener removed after settle");

  // 2. Timeout cap settles with the requested URL when load never completes.
  const slow = harness({ completeAfterMs: Infinity });
  slow.call();
  assert.deepStrictEqual(slow.timerMs(), [15000], "hard cap is 15s");
  slow.runTimers();
  sameJson(slow.resolved().result, { tabId: 7, url: "about:blank", requested: "https://new.example/", navigating: true }, "timeout fallback reports current URL with navigating flag");
  assert.strictEqual(slow.listenerCount(), 0, "listener removed on timeout");

  // 3. Late onUpdated after timeout must not double-reply.
  const late = harness();
  late.call();
  late.runTimers();
  late.resolve(null);
  late.fireComplete();
  assert.strictEqual(late.resolved(), null, "no second reply after timeout settled");

  console.log("goto settle behavior: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
