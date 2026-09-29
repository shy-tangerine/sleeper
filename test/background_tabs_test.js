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
console.log("background tab registry tests passed");
