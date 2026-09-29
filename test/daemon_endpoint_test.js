"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const context = { URL };
context.globalThis = context;
vm.runInNewContext(
  fs.readFileSync(path.join(__dirname, "..", "extension", "daemon_endpoint.js"), "utf8"),
  context
);
const endpoint = context.SleeperDaemonEndpoint;

let checked = endpoint.validate(
  "http://127.0.0.1:8790",
  "ws://127.0.0.1:8789/ws",
  ""
);
assert.strictEqual(checked.ok, true);
assert.strictEqual(checked.remote, false);

checked = endpoint.validate(
  "https://desktop.example.ts.net:8790",
  "wss://desktop.example.ts.net:8789/ws",
  "manual-secret"
);
assert.strictEqual(checked.ok, true);
assert.strictEqual(checked.remote, true);
assert.strictEqual(checked.tailscale, true);
assert.strictEqual(checked.token, "manual-secret");

for (const values of [
  ["http://192.168.1.2:8790", "ws://192.168.1.2:8789/ws"],
  ["https://sleeper.example.net", "wss://sleeper.example.net/ws"],
  ["https://desktop.example.ts.net:8790", "wss://other.example.ts.net:8789/ws"],
  ["https://desktop.example.ts.net:8790/path", "wss://desktop.example.ts.net:8789/ws"],
]) {
  assert.strictEqual(endpoint.validate(values[0], values[1], "").ok, false);
}

assert.strictEqual(endpoint.socketUrl(checked), "wss://desktop.example.ts.net:8789/ws");
assert.strictEqual(endpoint.socketUrl(endpoint.defaults()), "ws://127.0.0.1:8789/ws");

console.log("daemon endpoint tests passed");
