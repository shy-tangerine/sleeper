// Behavioral test: the background's waitXhr command handler.
//
// History: the pre-refactor dispatch chain called `handleWaitXhr(msg)`, a
// function that was never defined — every waitXhr command threw a swallowed
// ReferenceError inside the async onmessage handler and the daemon got no
// reply. The handler table now wires waitXhr/wait_xhr to waitXhrOnce from
// background_network.js. This test pins that wiring end-to-end at the
// background.js level so the dead-command regression can never silently
// return.
//
// Strategy: load background.js in a vm sandbox with stubbed chrome APIs, a
// stubbed WebSocket, and a stubbed fetch. Drive a fake daemon connection:
// open the socket, capture ws.onmessage, deliver a waitXhr command frame,
// and assert the daemon receives {id, ok:true, result:{matched,url,status}}
// when a matching request completes after the wait begins.

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const nodeCrypto = require("crypto");

function event() {
  const listeners = [];
  return { listeners, addListener(listener) { listeners.push(listener); } };
}

// --- stub chrome -----------------------------------------------------------
// A fresh install has no daemon token. The native host supplies it locally
// without asking the user to copy it from the daemon token file.
const storageData = {};
let nativeMessageCount = 0;
const beforeRequest = event();
const onCompleted = event();
const onErrorOccurred = event();
const onSendHeaders = event();

const chromeApi = {
  runtime: {
    getManifest: () => ({ manifest_version: 2 }),
    sendNativeMessage(host, message, callback) {
      nativeMessageCount++;
      assert.equal(host, "com.shy_tangerine.sleeper");
      assert.deepEqual(message, { type: "get_daemon_token" });
      callback({ token: "test-token" });
    },
    onMessage: event(),
    onInstalled: event(),
    onStartup: event(),
    lastError: null,
  },
  storage: {
    local: {
      get(keys, callback) {
        const out = {};
        (Array.isArray(keys) ? keys : [keys]).forEach((k) => { if (k in storageData) out[k] = storageData[k]; });
        callback(out);
      },
      set(obj, callback) { Object.assign(storageData, obj); if (callback) callback(); },
    },
    onChanged: event(),
  },
  webRequest: { onBeforeRequest: beforeRequest, onCompleted, onErrorOccurred, onSendHeaders },
  tabs: {
    onActivated: event(), onCreated: event(), onRemoved: event(), onUpdated: event(),
    query(_q, cb) { cb([{ id: 7, windowId: 1, index: 0, url: "https://developer.mozilla.org/", active: true }]); },
    get(_id, cb) { cb(null); },
    sendMessage() {},
    create() {},
    update() {},
    remove() {},
    TAB_ID_NONE: -1,
  },
  windows: { onFocusChanged: event(), update() {} },
};

// --- stub WebSocket --------------------------------------------------------
// background.js does `new WebSocket(url)` and checks
// `readyState === WebSocket.OPEN/CONNECTING`, so the stub must carry its own
// statics. It is installed as `sandbox.WebSocket` (a function, so `new` works).
class FakeWebSocket {
  constructor(url) { this.url = url; this.readyState = 0; FakeWebSocket.instances.push(this); }
  send(data) { FakeWebSocket.sent.push(JSON.parse(data)); }
  close() {}
}
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.OPEN = 1;
FakeWebSocket.CLOSING = 2;
FakeWebSocket.CLOSED = 3;
FakeWebSocket.instances = [];
FakeWebSocket.sent = [];

let nextIntervalId = 1;
const intervals = new Map();
function fakeSetInterval(callback, delay) {
  const id = nextIntervalId++;
  intervals.set(id, { callback, delay });
  return id;
}
function fakeClearInterval(id) { intervals.delete(id); }

const sandbox = {
  chrome: chromeApi,
  browser: undefined,
  fetch: fakeFetch,
  WebSocket: FakeWebSocket,
  setTimeout, clearTimeout, setInterval: fakeSetInterval, clearInterval: fakeClearInterval,
  console: { log() {}, warn() {}, error() {} },
  URL, TextDecoder, TextEncoder, AbortController,
  crypto: nodeCrypto.webcrypto,
  importScripts: undefined,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// --- stub fetch ------------------------------------------------------------
// The paired daemon token is already present in extension storage.
async function fakeFetch(url, opts) {
  if (String(url).endsWith("/api-hosts")) {
    return { ok: true, json: async () => ["chatgpt.com"] };
  }
  if (String(url).includes("/health?nonce=")) {
    const nonce = new URL(String(url)).searchParams.get("nonce");
    const instance_id = "mock-instance";
    const identity_proof = nodeCrypto.createHmac("sha256", "test-token").update(`${nonce}:${instance_id}`).digest("hex");
    return { ok: true, json: async () => ({ ok: true, instance_id, identity_proof }) };
  }
  if (String(url).endsWith("/health")) return { ok: true };
  throw new Error("unexpected fetch: " + url);
}

// --- load the shared modules background.js expects, then background.js -----
for (const module of ["api_host_policy.js", "screenshot.js", "background_tabs.js", "action-state.js", "background_network.js", "background_page_hooks.js", "daemon_endpoint.js", "mobile_onboarding.js", "tailscale_setup.js"]) {
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "..", "extension", module), "utf8"),
    sandbox,
    { filename: module },
  );
}
vm.runInNewContext(
  fs.readFileSync(path.join(__dirname, "..", "extension", "background.js"), "utf8"),
  sandbox,
  { filename: "background.js" },
);

// background.js auto-connects on evaluation. Flush the connect promise chain
// by yielding a macrotask, then grab the single socket it opened.
setTimeout(() => {
  run();
}, 50);

function drain() { return new Promise((resolve) => setTimeout(resolve, 0)); }

async function run() {
  assert.equal(nativeMessageCount, 1, "fresh install obtains its token through the native host");
  assert.equal(storageData.daemon_token, "test-token", "paired token is persisted for reconnects");
  const sock = FakeWebSocket.instances[0];
  assert(sock, "background opened a WebSocket");
  sock.readyState = FakeWebSocket.OPEN;
  sock.onopen();
  await sock.onmessage({ data: JSON.stringify({ type: "auth_challenge", challenge: "abc" }) });
  await sock.onmessage({ data: JSON.stringify({ type: "auth_ok", instance_id: "mock-instance", proof: "forged" }) });
  await sock.onmessage({ data: JSON.stringify({ id: 100, cmd: "waitXhr", args: { url_sub: "ignored" } }) });
  assert.equal(FakeWebSocket.sent.some((frame) => frame.id === 100), false);
  const okProof = nodeCrypto.createHmac("sha256", "test-token").update("ws-ok:mock-instance:abc").digest("hex");
  await sock.onmessage({ data: JSON.stringify({ type: "auth_ok", instance_id: "mock-instance", proof: okProof }) });
  const keepalive = Array.from(intervals.values()).find((entry) => entry.delay === 20000);
  assert(keepalive, "authenticated Chromium socket installs a 20-second keepalive");
  const hellosBeforeKeepalive = FakeWebSocket.sent.filter((frame) => frame.type === "hello").length;
  keepalive.callback();
  await drain();
  assert.equal(FakeWebSocket.sent.filter((frame) => frame.type === "hello").length, hellosBeforeKeepalive + 1,
    "keepalive refreshes the daemon hello frame");

  // A request completed before the wait must not satisfy it.
  beforeRequest.listeners.forEach((l) => l({ tabId: 7, url: "https://api.example/x/data", method: "GET", type: "xmlhttprequest" }));
  onCompleted.listeners.forEach((l) => l({ tabId: 7, url: "https://api.example/x/data", method: "GET", statusCode: 200 }));

  const deliver = (frame) => sock.onmessage({ data: JSON.stringify(frame) });

  // 1) A waitXhr command observes the next completion, not the stale one.
  deliver({ id: 101, cmd: "waitXhr", args: { url_sub: "api.example/x/data", timeout_ms: 1000 } });
  await drain();
  assert.equal(FakeWebSocket.sent.some((f) => f.id === 101), false, "stale completion does not satisfy waitXhr");
  beforeRequest.listeners.forEach((l) => l({ tabId: 7, url: "https://api.example/x/data", method: "GET", type: "xmlhttprequest" }));
  onCompleted.listeners.forEach((l) => l({ tabId: 7, url: "https://api.example/x/data", method: "GET", statusCode: 201 }));
  await drain();
  const reply1 = FakeWebSocket.sent.find((f) => f.id === 101);
  assert(reply1, "waitXhr command got a reply (the dead-handler bug would leave none)");
  assert.strictEqual(reply1.ok, true);
  assert.strictEqual(reply1.result.matched, true);
  assert.strictEqual(reply1.result.url, "https://api.example/x/data");
  assert.strictEqual(reply1.result.status, 201);

  // 2) The snake_case alias must behave identically.
  deliver({ id: 102, cmd: "wait_xhr", args: { url_sub: "api.example/x/data", timeout_ms: 1000 } });
  await drain();
  assert.equal(FakeWebSocket.sent.some((f) => f.id === 102), false, "alias also waits for a fresh completion");
  onCompleted.listeners.forEach((l) => l({ tabId: 7, url: "https://api.example/x/data", method: "GET", statusCode: 202 }));
  await drain();
  const reply2 = FakeWebSocket.sent.find((f) => f.id === 102);
  assert(reply2, "wait_xhr alias got a reply");
  assert.strictEqual(reply2.ok, true);
  assert.strictEqual(reply2.result.matched, true);

  // 3) A waitXhr for a request that never completed must resolve
  //    {matched:false} after its (short) timeout, not hang and not throw.
  deliver({ id: 103, cmd: "waitXhr", args: { url_sub: "never-seen", timeout_ms: 30 } });
  await new Promise((resolve) => setTimeout(resolve, 120));
  const reply3 = FakeWebSocket.sent.find((f) => f.id === 103);
  assert(reply3, "unmatched waitXhr still replies after timeout");
  assert.deepStrictEqual(reply3.result, { matched: false });

  // A cleared capture followed by a fresh page request is queried against the
  // active tab's real browser ID, not the webRequest sentinel -1.
  deliver({ id: 104, cmd: "network", args: { clear: true } });
  await drain();
  assert.deepStrictEqual(FakeWebSocket.sent.find((f) => f.id === 104).result, { cleared: true });
  beforeRequest.listeners.forEach((l) => l({ tabId: 7, url: "https://developer.mozilla.org/api/data", method: "GET", type: "xmlhttprequest" }));
  onCompleted.listeners.forEach((l) => l({ tabId: 7, url: "https://developer.mozilla.org/api/data", method: "GET", statusCode: 200 }));
  deliver({ id: 105, cmd: "network", args: { since: 60 } });
  await drain();
  const networkReply = FakeWebSocket.sent.find((f) => f.id === 105);
  assert(networkReply && networkReply.ok, "network query gets a successful reply");
  assert.strictEqual(networkReply.result.tabId, 7, "network query defaults to the active browser tab ID");
  assert.strictEqual(networkReply.result.count, 1, "freshly captured requests remain visible after clear");
  assert.strictEqual(networkReply.result.entries[0].url, "https://developer.mozilla.org/api/data");

  console.log("background waitXhr dispatch tests passed");
}
