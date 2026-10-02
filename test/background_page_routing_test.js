const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const background = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background.js"), "utf8");
const handler = background.slice(background.indexOf("async function routePageCommand("), background.indexOf("\n}", background.indexOf("async function routePageCommand(")) + 2);
const calls = [];
const context = {
  chrome: {},
  resolveTabId: () => 7,
  getFocusMode: async () => "never",
  routeToTab: async (_tab, msg) => { calls.push(["content", msg.args]); return { satisfied: true }; },
  sendResult: () => {},
  sendError: (_id, error) => { throw new Error(error); },
  SleeperChromiumDebugger: {
    exec: async (_api, _tab, args) => { calls.push(["exec", args]); return "title"; },
    waitUntil: async (_api, _tab, args) => { calls.push(["predicate", args]); return { satisfied: true }; },
  },
};
vm.runInNewContext(handler, context);
(async () => {
  const condition = { selector: "h1", state: "visible" };
  await context.routePageCommand({ id: 1, cmd: "waitUntil", args: { condition } });
  await context.routePageCommand({ id: 2, cmd: "waitUntil", args: { predicate: "document.readyState === 'complete'" } });
  await context.routePageCommand({ id: 3, cmd: "exec", args: { code: "document.title" } });
  assert.deepStrictEqual(calls.map(call => call[0]), ["content", "predicate", "exec"]);
  assert.strictEqual(calls[0][1].condition, condition);
  delete context.SleeperChromiumDebugger;
  await context.routePageCommand({ id: 4, cmd: "waitUntil", args: { predicate: "true" } });
  assert.strictEqual(calls[3][0], "content", "Firefox keeps the content-script route");
  console.log("page command routing tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
