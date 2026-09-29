const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const context = { setTimeout, clearTimeout, globalThis: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../extension/debugger_eval.js"), "utf8"), context);
const api = context.globalThis.SleeperChromiumDebugger;

assert(api.expressionFor("document.title", { x: 1 }).includes("eval(code)"));
assert(api.expressionFor("await Promise.resolve(true)", {}).startsWith("(async function"));
assert(api.predicateExpression("() => true").includes("typeof value === \"function\""));

const calls = [];
const browser = {
  runtime: {},
  debugger: {
    attach(target, version, done) { calls.push(["attach", target.tabId, version]); done(); },
    sendCommand(target, method, params, done) { calls.push(["command", method, params.awaitPromise]); done({ result: { value: true } }); },
    detach(target, done) { calls.push(["detach", target.tabId]); done(); },
  },
};

api.evaluate(browser, 7, "true", 1000).then((value) => {
  assert.strictEqual(value, true);
  assert.deepStrictEqual(calls.map((call) => call[0]), ["attach", "command", "detach"]);
  console.log("Chromium debugger evaluation contract: ok");
}).catch((error) => { console.error(error); process.exitCode = 1; });
