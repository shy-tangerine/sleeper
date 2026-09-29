"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "background.js"), "utf8");
const start = source.indexOf("function getBrowserInstanceId(callback)");
assert.notEqual(start, -1, "browser identity helper exists");
let depth = 0;
let end = start;
for (; end < source.length; end += 1) {
  if (source[end] === "{") depth += 1;
  if (source[end] === "}" && --depth === 0) {
    end += 1;
    break;
  }
}
const helper = source.slice(start, end);

function loadHelper(storage, uuid = "generated-id") {
  const context = {
    BROWSER_INSTANCE_ID_KEY: "browser_instance_id",
    chrome: { storage: { local: storage } },
    crypto: { randomUUID: () => uuid },
  };
  vm.runInNewContext(`let browserInstanceId = null; let browserInstanceIdLoading = false; let browserInstanceIdCallbacks = []; ${helper}; this.getBrowserInstanceId = getBrowserInstanceId;`, context);
  return context.getBrowserInstanceId;
}

{
  const storage = {
    get(_key, callback) { callback({}); },
    setCalls: [],
    set(value, callback) { this.setCalls.push({ value, callback }); },
  };
  const getBrowserInstanceId = loadHelper(storage);
  const ids = [];
  getBrowserInstanceId((id) => ids.push(id));
  getBrowserInstanceId((id) => ids.push(id));
  assert.equal(storage.setCalls.length, 1, "concurrent first hellos share one pending write");
  assert.deepEqual(ids, [], "hello waits until its ID is persisted");
  storage.setCalls[0].callback();
  assert.deepEqual(ids, ["generated-id", "generated-id"]);
}

{
  const storage = {
    setCalls: 0,
    get(_key, callback) { callback({ browser_instance_id: "saved-id" }); },
    set() { this.setCalls += 1; },
  };
  const getBrowserInstanceId = loadHelper(storage);
  let id;
  getBrowserInstanceId((value) => { id = value; });
  assert.equal(id, "saved-id", "restart reuses the persisted installation ID");
  assert.equal(storage.setCalls, 0, "existing IDs are not regenerated");
}

console.log("browser identity: ok");
