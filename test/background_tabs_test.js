const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "background_tabs.js"), "utf8");
const background = fs.readFileSync(path.join(__dirname, "..", "extension", "background.js"), "utf8");
let queriedTabs = [
  { id: 91, windowId: 2, index: 0, url: "https://second.example", active: false },
  { id: 47, windowId: 1, index: 1, url: "https://first.example/path", active: true },
];
let queryCallback;
const updates = [], removed = [], results = [], errors = [];
const chrome = {
  runtime: { lastError: null },
  tabs: {
    TAB_ID_NONE: -1,
    query(_options, callback) { queryCallback ? queryCallback(callback) : callback(queriedTabs); },
    create(options, callback) {
      const tab = { id: 100, windowId: 1, index: 2, url: options.url, active: true };
      queriedTabs.forEach(tab => { tab.active = false; });
      queriedTabs.push(tab);
      callback(tab);
    },
    update(id, options, callback) { updates.push({ id, ...options }); callback({ url: options.url }); },
    remove(id, callback) { removed.push(id); queriedTabs = queriedTabs.filter(tab => tab.id !== id); callback(); },
    get(id, callback) { callback(queriedTabs.find(tab => tab.id === id)); },
    onUpdated: { addListener() {}, removeListener() {} },
  },
};
const context = { chrome, setTimeout: callback => callback(), GOTO_SETTLE_TIMEOUT_MS: 0 };
vm.runInNewContext(source, context);
const registry = context.SleeperBackgroundTabs.createTabRegistry(chrome);
Object.assign(context, {
  tabRegistry: registry, TAB_REGISTRY: registry.entries, refreshRegistry: registry.refresh,
  sendResult: (_id, result) => results.push(result), sendError: (_id, error) => errors.push(error),
});
const resolver = background.slice(background.indexOf("const resolveTabId ="), background.indexOf("const pageHooks ="));
const mutating = background.slice(background.indexOf("function isMutatingCommand("), background.indexOf("async function autoActivateTab("));
const lifecycle = background.slice(background.indexOf("async function handleTabLifecycleCommand("), background.indexOf("// G1: navigate"));
const goto = background.slice(background.indexOf("async function handleGotoCommand("), background.indexOf("// Diagnostic: resolve"));
vm.runInNewContext(resolver + mutating + lifecycle + goto + "\nglobalThis.resolveTabId = resolveTabId;", context);
const routingStart = background.indexOf("async function routePageCommand(");
const routing = background.slice(routingStart, background.indexOf("\n}", routingStart) + 2);
let pageSends = 0, focusChecks = 0;
context.getFocusMode = async () => { focusChecks++; return "never"; };
context.routeToTab = async () => { pageSends++; return {}; };
vm.runInNewContext(routing, context);

(async () => {
  assert.strictEqual(await registry.resolve(), 47);
  assert.strictEqual(await registry.resolve(0), 47);
  assert.strictEqual(await registry.resolve("1"), 91);
  assert.strictEqual(await registry.resolve("second.example"), 91);
  registry.markConnected(47);
  queriedTabs[1].title = "Updated";
  await registry.refresh();
  assert.strictEqual(registry.snapshot()[0].connected, true);
  assert.strictEqual(registry.snapshot()[0].title, "Updated");

  // The cache lags a positional shift. Resolving must query and await it.
  queriedTabs.unshift({ id: 900, windowId: 0, index: 0, url: "https://first.example/path" });
  let completeQuery;
  queryCallback = callback => { completeQuery = callback; };
  let resolved = false;
  const pending = registry.resolve(0).then(id => { resolved = true; return id; });
  assert.strictEqual(resolved, false);
  completeQuery(queriedTabs);
  assert.strictEqual(await pending, 900);
  queryCallback = null;
  assert.strictEqual(await registry.resolve("id:47"), 47);
  await assert.rejects(registry.resolve("first.example"), /ambiguous tab URL/);
  for (const selector of ["id:missing", "id:-1", "id:1.5", "id:9007199254740992", "id:404"]) {
    await assert.rejects(registry.resolve(selector), /tab not found by id/);
  }
  for (const selector of [-1, 0.5, 3]) await assert.rejects(registry.resolve(selector), /tab not found at position/);

  for (const cmd of ["goto", "click", "type", "closetab", "selecttab", "dialog", "fillForm", "clickAll", "exec", "back", "navigate", "scrollTo", "hover", "waitUntil"]) {
    for (const tab of [0, "0", "first.example"]) {
      await assert.rejects(context.resolveTabId(tab, { cmd, args: { allow_user_tab: true } }), /explicit id:N/);
    }
    await assert.rejects(context.resolveTabId("id:47", { cmd, args: {} }), /not created by Sleeper/);
    await assert.rejects(context.resolveTabId(undefined, { cmd, args: { allow_user_tab: true } }), /explicit id:N/);
    assert.strictEqual(await context.resolveTabId("id:47", { cmd, args: { allow_user_tab: true } }), 47);
  }
  await context.handleGotoCommand({ id: 1, cmd: "goto", args: { tab: "0", url: "https://wrong.test" } });
  await context.handleTabLifecycleCommand({ id: 2, cmd: "closetab", args: { target: "id:47" } });
  assert.strictEqual(updates.length, 0);
  assert.strictEqual(removed.length, 0);
  assert.strictEqual(errors.length, 2, "rejections happen before browser mutations");
  for (const cmd of ["click", "type"]) {
    await context.routePageCommand({ id: 2, cmd, args: { tab: "id:47" } });
  }
  assert.strictEqual(pageSends, 0, "user-tab mutations never reach the content script");
  assert.strictEqual(focusChecks, 0, "ownership is checked before activation policy");
  await context.routePageCommand({ id: 2, cmd: "read", args: { tab: 0 } });
  await context.routePageCommand({ id: 2, cmd: "click", args: { tab: "id:47", allow_user_tab: true } });
  assert.strictEqual(pageSends, 2, "read-only positions and opted-in mutations still route");
  assert.strictEqual(await context.resolveTabId(0, { cmd: "waitUntil", args: { condition: { selector: "h1" } } }), 900);

  context.handleNewTabCommand({ id: 3, cmd: "newtab", args: { url: "https://owned.test" } });
  assert.strictEqual(registry.owned.has(100), true);
  assert.strictEqual(await context.resolveTabId(undefined, { cmd: "click" }), 100);
  await context.handleGotoCommand({ id: 4, cmd: "goto", args: { tab: "id:100", url: "https://destination.test" } });
  assert.strictEqual(updates[0].id, 100);
  assert.strictEqual(results.at(-1).previousUrl, "https://owned.test");
  await context.handleTabLifecycleCommand({ id: 5, cmd: "selecttab", args: { target: "id:47", allow_user_tab: true } });
  assert.strictEqual(updates.at(-1).id, 47);
  await context.handleTabLifecycleCommand({ id: 6, cmd: "closetab", args: { target: "id:100" } });
  assert.deepStrictEqual(removed, [100]);
  assert.strictEqual(registry.owned.has(100), false);

  // A missing tab retained for restore churn must never be a valid target.
  queriedTabs = queriedTabs.filter(tab => tab.id !== 47);
  await assert.rejects(registry.resolve("id:47"), /tab not found by id/);
  assert.strictEqual(registry.entries.has(47), true);
  for (let i = 0; i < 5; i++) await registry.refresh();
  assert.strictEqual(registry.entries.has(47), false);
  chrome.runtime.lastError = { message: "query failed" };
  await assert.rejects(registry.resolve("id:91"), /cannot refresh tab registry/);
  console.log("background tab registry tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
