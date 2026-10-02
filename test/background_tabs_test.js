const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background_tabs.js"), "utf8");
let queriedTabs = [];
const chromeApi = {
  runtime: { lastError: null },
  tabs: {
    TAB_ID_NONE: -1,
    query(_options, callback) { callback(queriedTabs); },
  },
};
const context = { chrome: chromeApi };
context.globalThis = context;
vm.runInNewContext(source, context);
const registry = context.SleeperBackgroundTabs.createTabRegistry(chromeApi);

queriedTabs = [
  { id: 91, windowId: 2, index: 0, url: "https://second.example", title: "Second", active: false },
  { id: 47, windowId: 1, index: 1, url: "https://first.example/path", title: "First", active: true },
];
registry.refresh();
assert.strictEqual(registry.resolve(), 47, "defaults to the active tab");
assert.strictEqual(registry.resolve(0), 47, "numeric targets use visible sorted position");
assert.strictEqual(registry.resolve("1"), 91, "numeric strings use visible sorted position");
assert.strictEqual(registry.resolve("second.example"), 91, "text targets match URL substrings");

registry.markConnected(47);
queriedTabs[1].title = "Updated";
registry.refresh();
assert.strictEqual(registry.snapshot()[0].connected, true, "refresh preserves connectivity");
assert.strictEqual(registry.snapshot()[0].title, "Updated", "refresh updates browser metadata");

queriedTabs = [queriedTabs[0]];
for (let miss = 0; miss < 5; miss++) registry.refresh();
assert.strictEqual(registry.entries.has(47), true, "short query gaps tolerate session restore churn");
registry.refresh();
assert.strictEqual(registry.entries.has(47), false, "stale tabs are eventually pruned");

assert.throws(() => registry.resolve(2), /tab not found at position 2/);
// Issue #17: browser indices restart in each window, but numeric selectors
// address the whole inventory. Include the reported position and tab IDs.
queriedTabs = [
  ...Array.from({ length: 2 }, (_, index) => ({ id: 200 + index, windowId: 1, index })),
  ...Array.from({ length: 31 }, (_, index) => ({
    id: index === 29 ? 135 : index === 30 ? 136 : 300 + index,
    windowId: 2, index, url: `https://example.test/${index}`,
  })),
];
for (let miss = 0; miss < 6; miss++) registry.refresh();
function assertListedSelectors() {
  registry.snapshot().forEach((entry, position) => {
    assert.strictEqual(entry.index, position, "listed indices are global positions");
    assert.strictEqual(registry.resolve(entry.index), entry.tabId);
    assert.strictEqual(registry.resolve(String(entry.index)), entry.tabId);
  });
  registry.snapshot().forEach(entry => {
    assert.strictEqual(entry.windowIndex, queriedTabs.find(tab => tab.id === entry.tabId).index);
  });
}
assertListedSelectors();
assert.strictEqual(registry.snapshot().find(tab => tab.tabId === 135).index, 31);
assert.throws(() => registry.resolve(0.5), /tab not found at position/);
assert.throws(() => registry.resolve(-1), /tab not found at position/);
assert.throws(() => registry.resolve(33), /tab not found at position/);

// Exercise the actual lifecycle handler with mocked browser APIs only.
const background = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background.js"), "utf8");
const handler = background.slice(background.indexOf("function handleTabLifecycleCommand("), background.indexOf("// G1: open a fresh tab"));
const removed = [], selected = [], results = [], errors = [];
context.resolveTabId = registry.resolve;
context.TAB_REGISTRY = registry.entries;
context.refreshRegistry = registry.refresh;
context.sendResult = (_id, result) => results.push(result);
context.sendError = (_id, error) => errors.push(error);
chromeApi.tabs.update = (id, _options, callback) => { selected.push(id); callback({ url: "https://example.test" }); };
chromeApi.tabs.remove = (id, callback) => {
  removed.push(id);
  const closed = queriedTabs.find(tab => tab.id === id);
  queriedTabs = queriedTabs.filter(tab => tab.id !== id).map(tab => ({
    ...tab, index: tab.windowId === closed.windowId && tab.index > closed.index ? tab.index - 1 : tab.index,
  }));
  callback();
};
vm.runInNewContext(handler, context);
let target = registry.snapshot().find(tab => tab.tabId === 135);
context.handleTabLifecycleCommand({ id: 1, cmd: "selecttab", args: { target: String(target.index) } });
assert.deepStrictEqual(selected, [135]);
context.handleTabLifecycleCommand({ id: 2, cmd: "closetab", args: { target: target.index } });
assert.deepStrictEqual(removed, [135], "closes exactly the tab shown at the supplied index");
assert.strictEqual(results[1].closed, 135);
assertListedSelectors();
target = registry.snapshot().find(tab => tab.tabId === 136);
context.handleTabLifecycleCommand({ id: 3, cmd: "closetab", args: { tab: String(target.index) } });
assert.deepStrictEqual(removed, [135, 136], "fresh listing remains correct after a close");
assertListedSelectors();
context.handleTabLifecycleCommand({ id: 4, cmd: "closetab", args: { target: 1000 } });
assert.strictEqual(errors.length, 1);
assert.deepStrictEqual(removed, [135, 136], "invalid selectors never remove tabs");
queriedTabs.reverse();
queriedTabs.filter(tab => tab.windowId === 2).forEach((tab, index) => { tab.index = index; });
registry.refresh();
assertListedSelectors();
assert.strictEqual(registry.resolve("example.test/28"), 328, "URL selectors remain unchanged");

// Issue #23: a saved selector must survive moves, insertions, and closes.
const stableTarget = registry.snapshot().find(tab => tab.tabId === 328).selector;
assert.strictEqual(stableTarget, "id:328");
queriedTabs.unshift({ id: 900, windowId: 0, index: 0, url: "https://example.test/28" });
queriedTabs.find(tab => tab.id === 328).index = 100;
registry.refresh();
assert.strictEqual(registry.resolve(stableTarget), 328);
assert.throws(() => registry.resolve("example.test/28"), /ambiguous tab URL/);
for (const invalid of ["id:missing", "id:-1", "id:1.5", "id:9007199254740992", "id:135"]) {
  assert.throws(() => registry.resolve(invalid), /tab not found by id/);
}

const navigated = [];
chromeApi.tabs.update = (id, options, callback) => {
  navigated.push({ id, url: options.url });
  callback({ url: options.url });
};
chromeApi.tabs.onUpdated = { addListener() {}, removeListener() {} };
context.setTimeout = callback => callback();
context.GOTO_SETTLE_TIMEOUT_MS = 0;
const gotoHandler = background.slice(background.indexOf("function handleGotoCommand("), background.indexOf("// Diagnostic: resolve"));
vm.runInNewContext(gotoHandler, context);
context.handleGotoCommand({ id: 5, args: { tab: stableTarget, url: "https://destination.test" } });
assert.deepStrictEqual(navigated, [{ id: 328, url: "https://destination.test" }], "goto uses the saved ID after a reorder");
context.handleTabLifecycleCommand({ id: 6, cmd: "closetab", args: { target: stableTarget } });
assert.strictEqual(removed.at(-1), 328, "close uses the same saved ID after a reorder");

// A restored page with a new ID must never substitute for the closed tab.
queriedTabs.push({ id: 901, windowId: 2, index: 100, url: "https://example.test/28" });
registry.refresh();
const previousErrors = errors.length;
context.handleGotoCommand({ id: 7, args: { tab: stableTarget, url: "https://wrong.test" } });
context.handleTabLifecycleCommand({ id: 8, cmd: "closetab", args: { target: stableTarget } });
assert.strictEqual(errors.length, previousErrors + 2);
assert.strictEqual(navigated.length, 1, "missing IDs never navigate a replacement tab");
assert.strictEqual(removed.at(-1), 328, "missing IDs never close a replacement tab");
console.log("background tab registry tests passed");
