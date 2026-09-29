"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const nodeCrypto = require("crypto");

const context = { URL, Promise, setTimeout, clearTimeout, TextEncoder, Uint8Array, crypto: nodeCrypto.webcrypto };
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "..", "extension", "tailscale_setup.js"), "utf8"),
  context
);
const setup = context.SleeperTailscaleSetup;

assert.deepEqual(
  JSON.parse(JSON.stringify(setup.endpointsFor("https://desktop.example.ts.net:8790/sleeper-setup#token=pairing-secret"))),
  {
    http: "https://desktop.example.ts.net:8790",
    ws: "wss://desktop.example.ts.net:8789/ws",
    token: "pairing-secret",
  }
);
for (const url of [
  "http://desktop.example.ts.net:8790/sleeper-setup",
  "https://desktop.example.com:8790/sleeper-setup",
  "https://desktop.example.ts.net:8790/not-sleeper",
  "https://desktop.example.ts.net/sleeper-setup",
  "https://desktop.example.ts.net:8790/sleeper-setup",
  "not a url",
]) {
  assert.equal(setup.endpointsFor(url), null, `${url} is not a Sleeper pairing URL`);
}

async function acceptHarness(overrides = {}) {
  const writes = [];
  const removals = [];
  const updates = [];
  const requests = [];
  const storageState = { ...(overrides.storage || {}) };
  const chromeApi = {
    runtime: {
      lastError: null,
      getURL(page) { return `moz-extension://sleeper/${page}`; },
    },
    storage: {
      local: {
        get(keys, callback) {
          const selected = {};
          for (const key of keys) if (Object.prototype.hasOwnProperty.call(storageState, key)) selected[key] = storageState[key];
          callback(selected);
        },
        set(value, callback) { Object.assign(storageState, value); writes.push(value); callback(); },
        remove(keys, callback) { for (const key of keys) delete storageState[key]; removals.push(keys); callback(); },
      }
    },
    tabs: {
      update(tabId, value, callback) { updates.push({ tabId, value }); callback({ id: tabId }); },
    },
  };
  const fetchImpl = overrides.fetchImpl || (async (url, options) => {
    requests.push({ url, options });
    if (url.includes("/health?nonce=")) {
      const nonce = new URL(url).searchParams.get("nonce");
      const instance_id = "mock-instance";
      const identity_proof = nodeCrypto.createHmac("sha256", "pairing-secret").update(`${nonce}:${instance_id}`).digest("hex");
      return { ok: true, async json() { return { ok: true, instance_id, identity_proof }; } };
    }
    return { ok: true, async json() { return { ok: true, tabs: [] }; } };
  });
  const result = await setup.acceptOffer(
    chromeApi,
    { type: "tailscale-setup", url: "https://desktop.example.ts.net:8790/sleeper-setup#token=pairing-secret" },
    { tab: { id: 17 }, url: "https://desktop.example.ts.net:8790/sleeper-setup#token=pairing-secret" },
    fetchImpl
  );
    return { result, writes, removals, updates, requests, storageState, chromeApi };
}

(async () => {
  const accepted = await acceptHarness();
  assert.equal(accepted.result.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(accepted.writes)), [{
    daemon_http_url: "https://desktop.example.ts.net:8790",
    daemon_ws_url: "wss://desktop.example.ts.net:8789/ws",
    daemon_auth_token: "pairing-secret",
  }]);
  assert.deepEqual(JSON.parse(JSON.stringify(accepted.updates)), [{
    tabId: 17,
    value: { url: "moz-extension://sleeper/options.html#daemon-connection", active: true },
  }]);
  assert.equal(accepted.requests.length, 2);
  assert.match(accepted.requests[0].url, /\/health\?nonce=[0-9a-f]{32}$/);
  assert.deepEqual(accepted.requests[0].options, { cache: "no-store" });
  assert.equal(accepted.requests[1].url, "https://desktop.example.ts.net:8790/tabs");
  assert.equal(accepted.requests[1].options.cache, "no-store");
  assert.equal(accepted.requests[1].options.headers["X-Sleeper-Instance"], "mock-instance");
  assert.ok(accepted.requests[1].options.headers["X-Sleeper-Nonce"]);
  assert.ok(accepted.requests[1].options.headers["X-Sleeper-Timestamp"]);
  assert.ok(accepted.requests[1].options.headers["X-Sleeper-Proof"]);
  assert.equal(accepted.requests[1].options.headers.Authorization, undefined);

  const rejected = await acceptHarness({
    fetchImpl: async () => ({ ok: true, async json() { return { ok: true, service: "other" }; } }),
  });
  assert.equal(rejected.result.ok, false);
  assert.deepEqual(rejected.writes, []);

  const replacing = await acceptHarness({
      storage: {
        daemon_http_url: "https://old.example.ts.net:8790",
        daemon_ws_url: "wss://old.example.ts.net:8789/ws",
        daemon_auth_token: "old-pairing-secret",
      },
    });
  assert.equal(replacing.result.ok, true);
  assert.equal(replacing.result.pendingApproval, true);
  assert.equal(replacing.writes.length, 1);
  assert.deepEqual(replacing.writes[0], {
      pending_tailscale_http_url: "https://desktop.example.ts.net:8790",
      pending_tailscale_ws_url: "wss://desktop.example.ts.net:8789/ws",
      pending_tailscale_auth_token: "pairing-secret",
      pending_tailscale_instance_id: "mock-instance",
    });
  assert.equal(replacing.storageState.daemon_http_url, "https://old.example.ts.net:8790");

  const approved = await setup.approveOffer(
      replacing.chromeApi,
      { url: "moz-extension://sleeper/options.html#daemon-connection" }
    );
  assert.equal(approved.ok, true);
  assert.equal(replacing.storageState.daemon_http_url, "https://desktop.example.ts.net:8790");
  assert.deepEqual(replacing.removals, [[
      "pending_tailscale_http_url", "pending_tailscale_ws_url",
      "pending_tailscale_auth_token", "pending_tailscale_instance_id",
    ]]);

  const unauthorized = await setup.approveOffer(
      replacing.chromeApi,
      { url: "https://desktop.example.ts.net:8790/sleeper-setup" }
    );
  assert.equal(unauthorized.ok, false);

  const hostile = await setup.acceptOffer(
    { storage: { local: { set() { throw new Error("must not write"); } } }, tabs: {}, runtime: {} },
    { type: "tailscale-setup", url: "https://desktop.example.ts.net:8790/sleeper-setup" },
    { tab: { id: 17 }, url: "https://desktop.example.ts.net:8790/sleeper-setup" },
    async () => { throw new Error("must not fetch"); }
  );
  assert.equal(hostile.ok, false);

  console.log("tailscale setup: ok");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
