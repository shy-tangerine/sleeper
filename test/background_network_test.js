const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function event() {
  const listeners = [];
  return { listeners, addListener(listener) { listeners.push(listener); } };
}

const beforeRequest = event();
const completed = event();
const failed = event();
const chromeApi = {
  runtime: { getManifest: () => ({ manifest_version: 3 }) },
  storage: { local: { get(_key, callback) { callback({}); } } },
  webRequest: {
    onBeforeRequest: beforeRequest,
    onCompleted: completed,
    onErrorOccurred: failed,
  },
};
const context = { chrome: chromeApi, URL, setTimeout, clearTimeout };
context.globalThis = context;
vm.runInNewContext(
  fs.readFileSync(require("path").join(__dirname, "..", "extension", "background_network.js"), "utf8"),
  context,
);

const network = context.SleeperBackgroundNetwork.createNetworkCapture(chromeApi);
beforeRequest.listeners[0]({ tabId: 7, url: "https://cdn.example/video.mp4?range=1", method: "GET", type: "media" });
completed.listeners[0]({ tabId: 7, url: "https://cdn.example/video.mp4?range=1", method: "GET", statusCode: 206 });
const response = network.response({ media: true }, 7);
assert.strictEqual(response.count, 1);
assert.strictEqual(response.entries[0].status, 206);

const waiting = network.waitForRequest({ urlSub: "video.mp4", method: "GET", tabId: 7, timeout: 50 });
completed.listeners[0]({ tabId: 7, url: "https://cdn.example/video.mp4?range=2", method: "GET", statusCode: 206 });
waiting
  .then((result) => {
    assert.strictEqual(result.matched, true, "requests completed after registration resolve the wait");
    console.log("background network tests passed");
  });
