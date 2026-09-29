const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background.js"), "utf8");
const start = source.indexOf("function getFocusMode()");
const end = source.indexOf("// ---------------------------------------------------------------------------\n// Startup / tab tracking", start);

function harness({ mode = "needed", tab = {}, send } = {}) {
  const calls = [];
  const chrome = {
    storage: { local: { get(_key, cb) { cb({ focus_mode: mode }); } } }, runtime: { lastError: null },
    tabs: { get(_id, cb) { cb({ id: 4, windowId: 9, active: false, status: "complete", ...tab }); },
      update(id, change, cb) { calls.push(["tab", id, change]); cb && cb({}); },
      sendMessage: send || ((_id, _msg, cb) => cb({ ok: true, result: "ok" })) },
    windows: { update(id, change, cb) { calls.push(["window", id, change]); cb && cb({}); } },
  };
  const context = { chrome, setTimeout, clearTimeout, console, Promise, Set, Error };
  context.markTabDisconnected = () => {}; context.markTabConnected = () => {};
  vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.f = { getFocusMode, tabNeedsActivation, autoActivateTab, routeToTab, isDefinitelyNoDelivery };`, context);
  return { ...context.f, chrome, calls };
}

(async () => {
  const needed = harness(); assert.strictEqual(await needed.tabNeedsActivation(4), false); await needed.routeToTab(4, { cmd: "read", args: {} });
  assert.strictEqual(JSON.stringify(needed.calls), "[]", "needed leaves reachable inactive tab alone");
  const always = harness({ mode: "always" }); await always.autoActivateTab(4, { args: {} }, true);
  assert.strictEqual(JSON.stringify(always.calls), JSON.stringify([["tab", 4, { active: true }], ["window", 9, { focused: true }]]), "always activates and focuses");
  let sends = 0;
  const discarded = harness({ tab: { discarded: true }, send: (_id, _msg, cb) => { sends++; cb({ ok: true, result: "done" }); } });
  if (await discarded.tabNeedsActivation(4)) await discarded.autoActivateTab(4, { args: {} }, true);
  await discarded.routeToTab(4, { cmd: "click", args: {} });
  assert.strictEqual(sends, 1, "discarded mutation executes once after activation");
  assert.strictEqual(harness().isDefinitelyNoDelivery(new Error("Receiving end does not exist")), true);
  const closed = harness({ send: (_id, _msg, cb) => { closed.chrome.runtime.lastError = { message: "The message port closed" }; cb(); } });
  await assert.rejects(() => closed.routeToTab(4, { cmd: "click", args: {} }), /not reachable/);
  assert.strictEqual(closed.isDefinitelyNoDelivery(new Error("The message port closed")), false, "closed ports are uncertain");
  console.log("focus policy behavior: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
