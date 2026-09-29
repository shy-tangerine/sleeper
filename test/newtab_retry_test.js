// Regression: commands sent to a brand-new tab (newtab → immediate command)
// must succeed once the content script injects, without re-executing a
// mutating command after it actually delivered. Pins the routeToTab retry
// contract: replay-on-"not injected" is safe for all commands, bounded by
// RETRY_WINDOW_MS so a truly dead tab still fails fast.
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background.js"), "utf8");
const start = source.indexOf("function getFocusMode()");
const end = source.indexOf("// ---------------------------------------------------------------------------\n// Startup / tab tracking", start);

// Harness whose content script "injects" after `deliverAfter` sends: earlier
// sends fail with the injection error, later ones succeed.
function harness({ deliverAfter = 2, mutating = false } = {}) {
  let sends = 0;
  const chrome = {
    storage: { local: { get(_key, cb) { cb({ focus_mode: "needed" }); } } }, runtime: { lastError: null },
    tabs: { get(_id, cb) { cb({ id: 4, windowId: 9, active: false, status: "loading" }); },
      update() {}, sendMessage(_id, _msg, cb) {
        sends++;
        if (sends < deliverAfter) {
          chrome.runtime.lastError = { message: "Could not establish connection. Receiving end does not exist." };
          cb();
          return;
        }
        chrome.runtime.lastError = null;
        cb({ ok: true, result: "delivered" });
      } },
    windows: { update() {} },
  };
  const context = { chrome, setTimeout, clearTimeout, console, Promise, Set, Error, Date };
  context.markTabDisconnected = () => {}; context.markTabConnected = () => {};
  vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.f = { routeToTab };`, context);
  const cmd = mutating ? "click" : "read";
  return { route: () => context.f.routeToTab(4, { cmd, args: {} }), sends: () => sends };
}

(async () => {
  // 1. Brand-new tab: the first N sends fail "not injected", the command must
  //    still succeed once the script appears — including mutating commands,
  //    since a failed delivery was never seen by the page.
  const fresh = harness({ deliverAfter: 3, mutating: true });
  const result = await fresh.route();
  assert.strictEqual(result, "delivered");
  assert.strictEqual(fresh.sends(), 3, "mutating command retried until injection, executed once on success");

  // 2. Dead tab (never injects): retries stay inside the window, then fail
  //    with the actionable "not reachable" error.
  const dead = harness({ deliverAfter: Infinity });
  const started = Date.now();
  await assert.rejects(() => dead.route(), /not reachable/);
  const elapsed = Date.now() - started;
  assert.ok(elapsed < 12000, `dead tab fails within the retry window (took ${elapsed}ms)`);

  console.log("newtab retry behavior: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
