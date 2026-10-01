const assert = require("assert");
require("../extension/background_page_hooks.js");

const calls = [];
const api = {
  runtime: {},
  debugger: {},
  scripting: {
    executeScript(details) {
      calls.push(details);
      return Promise.resolve(details.world === "MAIN" ? [{ result: true }] : []);
    },
  },
  tabs: { executeScript() { throw new Error("MV2 fallback used"); } },
};
const hooks = globalThis.SleeperBackgroundPageHooks.createPageHooks(api);
const replies = [];

hooks.handleConsole({ id: 1, args: { tab: 7 } }, (tab) => tab, (id, result) => replies.push({ id, result }), (id, error) => { throw new Error(`${id}: ${error}`); })
  .then(async () => {
    assert.strictEqual(calls.length, 2);
    assert.strictEqual(calls[0].target.tabId, 7);
    assert.strictEqual(typeof calls[0].func, "function");
    assert.strictEqual(calls[1].world, "MAIN");
    assert.strictEqual(typeof calls[1].func, "function");
    assert.deepStrictEqual(replies[0].result.entries, []);
    assert.strictEqual(replies[0].result.note, undefined);
    api.scripting.executeScript = () => Promise.reject(new Error("hook blocked"));
    await hooks.handleConsole({ id: 2, args: { tab: 7 } }, (tab) => tab,
      (id, result) => replies.push({ id, result }),
      (id, error) => { throw new Error(`${id}: ${error}`); });
    assert.deepStrictEqual(replies[1].result.entries, [], "failed injection never returns cached entries");
    assert.match(replies[1].result.note, /hook blocked/);
    console.log("Chromium page-hook injection contract: ok");
  })
  .catch((error) => { console.error(error); process.exitCode = 1; });
