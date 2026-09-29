const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "action-state.js"), "utf8");
let clock = 1000;
const stored = { action_log: [] };
const writes = [];
const chromeApi = {
  storage: {
    local: {
      get: (key, callback) => callback({ [key]: stored[key] }),
      set: (values) => {
        Object.assign(stored, values);
        writes.push(JSON.parse(JSON.stringify(values)));
      },
    },
  },
};
const context = { chrome: chromeApi, setTimeout, clearTimeout, URL };
vm.runInNewContext(source, context);

const recorder = context.SleeperBackgroundActivity.createActionRecorder({
  chromeApi,
  now: () => clock,
});

recorder.start({
  id: "one",
  cmd: "type",
  args: { selector: "#password", text: "never-store-this", tab: "2" },
});
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(stored.current_action)),
  {
    cmd: "type",
    ts: 1000,
    started_at: "1970-01-01T00:00:01.000Z",
    tab: "2",
    target: "#password",
    status: "running",
  },
);

clock = 1250;
recorder.finish("one", true, { url: "https://example.test/path?token=never-store-this#private" });
assert.strictEqual(stored.current_action, null);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(stored.action_log)),
  [{
    cmd: "type",
    ts: 1000,
    started_at: "1970-01-01T00:00:01.000Z",
    duration_ms: 250,
    ok: true,
    status: "success",
    tab: "2",
    target: "#password",
    url: "https://example.test/path",
  }],
);
assert.ok(!JSON.stringify(writes).includes("never-store-this"));

recorder.start({ id: "two", cmd: "click", args: { selector: "#save" } });
clock = 1275;
recorder.finish("two", false, "selector #save not found");
assert.strictEqual(stored.action_log[1].status, "failure");
assert.strictEqual(stored.action_log[1].ok, false);
assert.strictEqual(stored.action_log[1].duration_ms, 25);

console.log("action log telemetry: ok");
