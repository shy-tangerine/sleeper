// Sleeper - background.js
// Thin relay: connects to the daemon over WS, routes incoming commands to the
// active tab's content script, replies with the result.
//
// Command flow:
//   daemon --WS--> background --tabs.sendMessage--> content.js -> sleeper.js
//   handlers run against the real DOM --sendResponse--> background --WS--> daemon
//
// The daemon treats this background WS as one "tab" connection. We register
// with a hello on connect and keep url/title/active fresh on tab events so
// the daemon's active-tab routing picks us up.
//
// Dormancy: the extension is always-on by design (unlike the userscript,
// which only connects while its tab is visible+focused). It does no polling —
// it only reacts to daemon commands and tab events.

// Firefox provides the callback-capable `chrome` namespace used by this
// legacy relay.  Fall back to `browser` only where `chrome` is absent.
if (typeof chrome === "undefined" && typeof browser !== "undefined") {
  globalThis.chrome = browser;
}

// MV3 service workers do not support the Firefox manifest's background
// script array, so load the shared policy module explicitly when needed.
// Firefox already loads it from manifest.json; the guard keeps that path
// harmless and makes both builds use the same implementation.
if ((typeof SleeperApiHostPolicy === "undefined" || typeof SleeperScreenshot === "undefined" || typeof SleeperBackgroundTabs === "undefined" || typeof SleeperBackgroundActivity === "undefined" || typeof SleeperBackgroundNetwork === "undefined" || typeof SleeperBackgroundPageHooks === "undefined" || typeof SleeperDaemonEndpoint === "undefined" || typeof SleeperMobileOnboarding === "undefined" || typeof SleeperTailscaleSetup === "undefined" || typeof SleeperChromiumDebugger === "undefined") && typeof importScripts === "function") {
  importScripts("api_host_policy.js", "screenshot.js", "background_tabs.js", "action-state.js", "background_network.js", "background_page_hooks.js", "daemon_endpoint.js", "mobile_onboarding.js", "tailscale_setup.js", "debugger_eval.js");
}

// Source identity of the installed package (issue #20): SOURCE_ID is written
// by the build scripts and lets `sleeper sessions` distinguish same-version
// dev builds. Empty when absent (e.g. a signed release XPI).
let SleeperSourceIdentity = "";
try {
  fetch(chrome.runtime.getURL("SOURCE_ID")).then((r) => (r.ok ? r.text() : "")).then((text) => {
    if (!text) return;
    const content = String(text).split("\n").find((line) => line.startsWith("content="));
    const commit = String(text).split("\n").find((line) => line.startsWith("commit="));
    if (content) SleeperSourceIdentity = `${(commit || "commit=?").slice(7, 19)}/${content.slice(8)}`;
  }).catch(() => {});
} catch (_) { /* SOURCE_ID is optional */ }

const TOKEN_STORAGE_KEY = "daemon_token";
const NATIVE_HOST_NAME = "com.shy_tangerine.sleeper";
const DAEMON_HTTP_STORAGE_KEY = "daemon_http_url";
const DAEMON_WS_STORAGE_KEY = "daemon_ws_url";
const DAEMON_AUTH_STORAGE_KEY = "daemon_auth_token";
const BROWSER_INSTANCE_ID_KEY = "browser_instance_id";

let daemonToken = ""; // configured during pairing and cached in storage.local — never hardcoded
let ws = null;
let browserInstanceId = null;
let browserInstanceIdLoading = false;
let browserInstanceIdCallbacks = [];
let wsClosedByUs = false;
let wsKeepaliveTimer = null;
const WS_KEEPALIVE_MS = 20000;

// A3 — reconnect backoff. Start fast (~500ms), grow exponentially with jitter,
// cap at 30s, reset to fast on a successful open. A single pending reconnect
// timer is kept at a time so close storms can't stack connects.
let wsReconnectBase = 500;
const WS_RECONNECT_MAX = 30000;
let wsReconnectAttempt = 0;
let reconnectTimer = null;

// Endpoint settings are stored per browser profile. A remote browser never
// falls back to localhost or to a less secure URL after a bad edit.
function readDaemonConfig() {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get([DAEMON_HTTP_STORAGE_KEY, DAEMON_WS_STORAGE_KEY, DAEMON_AUTH_STORAGE_KEY], (value) => {
        const checked = SleeperDaemonEndpoint.validate(
          value && value[DAEMON_HTTP_STORAGE_KEY], value && value[DAEMON_WS_STORAGE_KEY],
          value && value[DAEMON_AUTH_STORAGE_KEY]
        );
        resolve(checked.ok ? checked : Object.assign(SleeperDaemonEndpoint.defaults(), { invalid: true }));
      });
    } catch (_) { resolve(SleeperDaemonEndpoint.defaults()); }
  });
}

async function hmacHex(token, message) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(token), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(signature), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function verifyDaemonIdentity(config, token) {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const nonce = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  const response = await fetch(`${config.http}/health?nonce=${nonce}`, { cache: "no-store" });
  if (!response.ok) return false;
  const payload = await response.json();
  const instanceId = String(payload.instance_id || "");
  const expected = await hmacHex(token, `${nonce}:${instanceId}`);
  return typeof payload.identity_proof === "string" && payload.identity_proof === expected ? instanceId : null;
}

async function daemonAuthHeaders(token, instanceId, method, path, body = "") {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const nonce = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  const bodyBytes = new TextEncoder().encode(body);
  const timestamp = Math.floor(Date.now() / 1000);
  const digest = await crypto.subtle.digest("SHA-256", bodyBytes);
  const bodyHash = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  const proof = await hmacHex(token, `${instanceId}\n${nonce}\n${timestamp}\n${method}\n${path}\n${bodyHash}`);
  const preamble = await hmacHex(token, `${instanceId}\n${nonce}\n${timestamp}\n${method}\n${path}\n${bodyBytes.length}`);
  return { "X-Sleeper-Instance": instanceId, "X-Sleeper-Nonce": nonce,
    "X-Sleeper-Timestamp": String(timestamp), "X-Sleeper-Proof": proof, "X-Sleeper-Preamble": preamble };
}

const activityTracker = SleeperBackgroundActivity.createActivityTracker({
  chromeApi: chrome,
  browserApi: typeof browser !== "undefined" ? browser : null,
});
activityTracker.setDaemonConnected(false);

const actionRecorder = SleeperBackgroundActivity.createActionRecorder({ chromeApi: chrome });

function readAccessScope() {
  return new Promise((resolve) => {
    try { chrome.storage.local.get("access_scope", (v) => resolve(v.access_scope || "all_tabs")); }
    catch (_) { resolve("all_tabs"); }
  });
}

async function accessAllowed(msg) {
  const scope = await readAccessScope();
  if (scope === "disabled") return msg.cmd === "tabs" || msg.cmd === "state";
  if (scope === "active_tab" && msg.args && msg.args.tab != null) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Auth capture (C)
// ChatGPT (and other SPA backends) inject `Authorization: Bearer <token>` via
// a fetch interceptor. We capture the most recent bearer token on requests to
// TARGET_AUTH_HOSTS so the background can answer `api` commands in O(1) with a
// same-origin fetch. SECURITY: the raw token is held ONLY in this background
// variable and is NEVER sent to the daemon or included in any response.
// ---------------------------------------------------------------------------

// Origins the background `api` fetch is allowed to target (resolved relative
// paths use the daemon's first allowed host). Keeps the privileged bearer token scoped to
// the captured host instead of letting the daemon point the fetch anywhere.
// Deny capture and authenticated calls until the daemon supplies its explicit
// allowlist. A temporary daemon outage must never widen this boundary.
const apiPolicy = SleeperApiHostPolicy.createPolicy([]);
let apiPolicyLoaded = false;
async function loadApiHostAllowlist(config, token, instanceId) {
 if (config.invalid) { apiPolicy.setHosts([]); apiPolicyLoaded = true; return; }
 try { const headers = await daemonAuthHeaders(token, instanceId, "GET", "/api-hosts");
   const r = await fetch(`${config.http}/api-hosts`, {cache: "no-store", headers});
    if (r.ok) apiPolicy.setHosts(await r.json()); else apiPolicy.setHosts([]);
  } catch (_) { /* retain last known-good policy; never widen on failure */ }
  finally { apiPolicyLoaded = true; }
}

chrome.webRequest.onSendHeaders.addListener((d) => {
  if (!apiPolicyLoaded) return;
  if (!d.requestHeaders) return;
  const auth = d.requestHeaders.find((h) => h.name.toLowerCase() === "authorization");
  if (auth && auth.value) {
    const v = auth.value.trim();
    apiPolicy.capture(d.url, v);
  }
}, { urls: ["https://*/*"] }, ["requestHeaders"]);

const networkCapture = SleeperBackgroundNetwork.createNetworkCapture(chrome);
const NET_LOG = networkCapture.log;
const netResponse = networkCapture.response;
const waitDownloadOnce = networkCapture.waitForDownload;
const waitXhrOnce = networkCapture.waitForRequest;

// ---------------------------------------------------------------------------
// Tab registry (G2)
// Live inventory of every tab across all windows, refreshed on connect and on
// tab events. 'connected' reflects whether the tab's content script is
// reachable (confirmed by a successful command response, or a hello message
// carrying sender.tab). Session-restore churn is tolerated: onRemoved is the
// authoritative eviction; query misses only soft-mark a tab so bursts don't
// wipe the registry.
// ---------------------------------------------------------------------------

const tabRegistry = SleeperBackgroundTabs.createTabRegistry(chrome);
const TAB_REGISTRY = tabRegistry.entries;
const refreshRegistry = tabRegistry.refresh;
const markTabConnected = tabRegistry.markConnected;
const markTabDisconnected = tabRegistry.markDisconnected;
const registrySnapshot = tabRegistry.snapshot;

// Resolve a `tab` param against the registry (G1/G2). Defaults to the active
// tab; otherwise a NUMBER is the 0-based position in the `sleeper tabs`
// listing (same ordering tabs renders), and a non-numeric STRING is a
// url-substring match. Resolution is FOCUS-FREE: it is based purely on the
// registry, never on which window/tab happens to have OS focus, so a target
// tab selected by url-substring or position is addressed correctly even when
// it is not the focused/active tab. Numbers are NEVER treated as raw browser
// tabIds — those are arbitrary and unrelated to the listing order, so doing
// so previously sent a numeric target to the wrong tab.
const resolveTabId = tabRegistry.resolve;

const pageHooks = SleeperBackgroundPageHooks.createPageHooks(chrome);
const handleConsole = (msg) => pageHooks.handleConsole(msg, resolveTabId, sendResult, sendError);
const handleDialog = (msg) => pageHooks.handleDialog(msg, resolveTabId, sendResult, sendError);

// ---------------------------------------------------------------------------
// Reply helpers for background-side commands (no page round-trip).
// A3 — all outbound frames go through sendToDaemon so a closed socket can
// never throw; replies to a dropped socket are logged and dropped (the daemon
// is master-driven and id-matched, so it simply won't match this id).
// ---------------------------------------------------------------------------

function sendToDaemon(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify(obj));
      return true;
    } catch (e) {
      console.warn("Sleeper: WS send threw", e, "for id", obj && obj.id);
      return false;
    }
  }
  console.warn("Sleeper: dropping WS frame id=", obj && obj.id, "(socket not OPEN)");
  return false;
}

function sendResult(id, result) {
  activityTracker.finish(id);
  actionRecorder.finish(id, true, result);
  sendToDaemon({ id, ok: true, result });
}

function sendScreenshotResult(id, dataUrl) {
  SleeperScreenshot.sendResult(sendResult, sendError, id, dataUrl);
}

function handleScreenshotCommand(msg) {
  let tabId;
  try {
    tabId = resolveTabId((msg.args && msg.args.tab));
  } catch (error) {
    sendError(msg.id, String(error.message || error));
    return;
  }
  const browserApi = typeof browser !== "undefined" ? browser : chrome;
  getFocusMode().then((focusMode) => {
    if (focusMode === "always") return autoActivateTab(tabId, msg, true);
    msg.args = Object.assign({}, msg.args || {}, { focus_mode: focusMode });
  }).then(() => SleeperScreenshot.capture(browserApi, tabId, msg.args || {}))
    .then((dataUrl) => sendScreenshotResult(msg.id, dataUrl))
    .catch((error) => sendError(msg.id, String((error && error.message) || error)));
}

function sendError(id, error) {
  activityTracker.finish(id);
  actionRecorder.finish(id, false, error);
  sendToDaemon({ id, ok: false, error });
}

// ---------------------------------------------------------------------------
// Background-side command handlers
// Each answers a daemon command without a page round-trip. Handlers receive
// (msg) and reply via sendResult/sendError themselves; the dispatcher below
// only picks the handler. Alias names map here too (wait_xhr -> waitXhr).
// ---------------------------------------------------------------------------

// `network` (and its `media` alias): report captured requests, optionally
// re-fetch one of them from the background. `clear` empties the log first.
function handleNetworkCommand(msg) {
  const args = msg.args || {};
  if (args.clear) {
    NET_LOG.clear();
    sendResult(msg.id, { cleared: true });
    return;
  }
  let tabId;
  try {
    tabId = resolveTabId(args.tab);
  } catch (e) {
    sendError(msg.id, String(e.message || e));
    return;
  }
  const res = netResponse(args, tabId);
  if (args.fetch || args.body) {
    const selected = args.url || (res.entries[0] && res.entries[0].url);
    if (!selected || !/^https?:\/\//i.test(selected)) {
      sendError(msg.id, "network fetch requires a selected http(s) URL"); return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    fetch(selected, {cache: "no-store", signal: ctrl.signal}).then(async (resp) => {
      const readBody = async () => {
        if (!resp.body || !resp.body.getReader) throw new Error("streaming response body unavailable");
        const reader = resp.body.getReader();
        const chunks = [];
        let total = 0;
        for (;;) {
          const part = await reader.read();
          if (part.done) break;
          total += part.value.byteLength;
          if (total > 2 * 1024 * 1024) {
            await reader.cancel();
            throw new Error("response body exceeds 2 MiB limit");
          }
          chunks.push(part.value);
        }
        const bytes = new Uint8Array(total); let at = 0;
        chunks.forEach((chunk) => { bytes.set(chunk, at); at += chunk.byteLength; });
        return new TextDecoder().decode(bytes);
      };
      const ct = resp.headers.get("content-type") || "";
      const isJson = /json/i.test(ct);
      const payload = isJson ? JSON.parse(await readBody().catch(() => null) || "{}") : await readBody().catch(() => "");
      sendResult(msg.id, Object.assign(res, {fetch: {url: selected, status: resp.status,
        ok: resp.ok, json: isJson ? payload : undefined, body: isJson ? undefined : payload}}));
    }).catch((e) => sendError(msg.id, "network fetch failed: " + String(e.message || e)))
      .finally(() => clearTimeout(timer));
  } else {
    sendResult(msg.id, res);
  }
}

// `media` normalizes to a media-scoped network query (no fetch branch).
function handleMediaCommand(msg) {
  msg.args = Object.assign({}, msg.args || {}, {media: true});
  const args = msg.args;
  let tabId;
  try { tabId = resolveTabId(args.tab); } catch (e) {
    sendError(msg.id, String(e.message || e)); return;
  }
  sendResult(msg.id, netResponse(args, tabId));
}

// G2: full tab inventory, answered background-side.
function handleTabsCommand(msg) {
  refreshRegistry().then(() => sendResult(msg.id, { tabs: registrySnapshot() }));
}

// OpenCLI-compatible tab lifecycle commands run in the background context,
// before page-target routing.
function handleTabLifecycleCommand(msg) {
  let targetId;
  try { targetId = resolveTabId(msg.args && (msg.args.tab ?? msg.args.target)); }
  catch (e) { sendError(msg.id, String(e.message || e)); return; }
  if (msg.cmd === "selecttab") {
    chrome.tabs.update(targetId, { active: true }, (t) => {
      if (chrome.runtime.lastError) { sendError(msg.id, String(chrome.runtime.lastError.message)); return; }
      refreshRegistry();
      sendResult(msg.id, { selected: targetId, url: t && t.url });
    });
  } else {
    chrome.tabs.remove(targetId, () => {
      if (chrome.runtime.lastError) { sendError(msg.id, String(chrome.runtime.lastError.message)); return; }
      TAB_REGISTRY.delete(targetId);
      refreshRegistry();
      sendResult(msg.id, { closed: targetId });
    });
  }
}

// G1: open a fresh tab (extension API bypasses popup blockers).
// The tabs.create callback often still reports about:blank because the
// navigation is pending; the requested URL is echoed alongside so callers
// never mistake the placeholder for the target.
function handleNewTabCommand(msg) {
  const url = (msg.args && msg.args.url) || "about:blank";
  chrome.tabs.create({ url }, (t) => {
    if (chrome.runtime.lastError) {
      sendError(msg.id, String(chrome.runtime.lastError.message));
      return;
    }
    refreshRegistry();
    sendResult(msg.id, { tabId: t.id, url: (t && t.url) || url, requested: url, navigating: (t && t.url) !== url && url !== "about:blank" });
  });
}

// G1: navigate an existing tab to a url (active by default; also resolves
// tabId, window-relative index, or url-substring). The reply waits for the
// navigation to settle (status complete or an error page) so follow-up
// commands act on the NEW page, not the old one racing teardown. A hard cap
// keeps an unresponsive server from hanging the caller.
const GOTO_SETTLE_TIMEOUT_MS = 15000;

function handleGotoCommand(msg) {
  const args = msg.args || {};
  let tabId;
  try {
    tabId = resolveTabId(args.tab);
  } catch (e) {
    sendError(msg.id, String(e.message || e));
    return;
  }
  const url = args.url || "";
  chrome.tabs.update(tabId, { url }, (t) => {
    if (chrome.runtime.lastError) {
      // Firefox reports browser-native wording ("Illegal URL: …") for schemes
      // the extension cannot open; translate it into something actionable.
      const raw = String(chrome.runtime.lastError.message || "");
      const friendly = /Illegal URL|not allowed|restricted/i.test(raw)
        ? `cannot navigate to "${url}": this URL scheme (file:, javascript:, browser pages) is blocked by the browser. Use http(s) URLs`
        : raw;
      sendError(msg.id, friendly);
      return;
    }
    refreshRegistry();
    const settle = (completedUrl) => {
      const currentUrl = completedUrl || (t && t.url) || url;
      sendResult(msg.id, { tabId, url: currentUrl, requested: url, navigating: url !== "" && currentUrl !== url });
    };
    // Same-URL navigations (or about:blank) may not emit onUpdated; the
    // update callback's URL plus a short grace check covers those.
    let settled = false;
    const listener = (updatedTabId, changeInfo) => {
      if (updatedTabId !== tabId) return;
      if (changeInfo.status === "complete" || changeInfo.status === "unloaded") {
        settled = true;
        chrome.tabs.onUpdated.removeListener(listener);
        chrome.tabs.get(tabId, (tab) => {
          settle(chrome.runtime.lastError ? undefined : tab && tab.url);
        });
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(listener);
      settle(undefined);
    }, GOTO_SETTLE_TIMEOUT_MS);
  });
}

// Diagnostic: resolve + tabs.get only (splits tab lookup from capture).
function handleTabInfoCommand(msg) {
  let tabId;
  try {
    tabId = resolveTabId((msg.args && msg.args.tab));
  } catch (e) {
    sendError(msg.id, String(e.message || e));
    return;
  }
  chrome.tabs.get(tabId, (t) => {
    if (chrome.runtime.lastError) {
      sendError(msg.id, String(chrome.runtime.lastError.message));
      return;
    }
    sendResult(msg.id, { tabId, windowId: t.windowId, url: t.url,
                         captureTabFn: typeof chrome.tabs.captureTab });
  });
}

// Read a bounded (2 MiB) response body off a fetch Response.
async function readBoundedResponseBody(resp) {
  if (!resp.body || !resp.body.getReader) return await resp.text();
  const reader = resp.body.getReader();
  let total = 0; const chunks = [];
  for (;;) {
    const part = await reader.read();
    if (part.done) break;
    total += part.value.byteLength;
    if (total > 2 * 1024 * 1024) {
      await reader.cancel();
      throw new Error("response body exceeds 2 MiB limit");
    }
    chunks.push(part.value);
  }
  const bytes = new Uint8Array(total); let at = 0;
  chunks.forEach((chunk) => { bytes.set(chunk, at); at += chunk.byteLength; });
  return new TextDecoder().decode(bytes);
}

function isJsonContentType(resp) {
  return /json/i.test(resp.headers.get("content-type") || "");
}

// C: background-side `api` — same-origin fetch against the page's backend
// using the captured Authorization header. Only status + json (or text) are
// returned; the bearer token NEVER leaves the background.
function handleApiCommand(msg) {
  const args = msg.args || {};
  const url = String(args.url || "");
  if (!url) { sendError(msg.id, "api: url is required"); return; }
  let target;
  try {
    target = apiPolicy.resolve(url);
  } catch (e) {
    sendError(msg.id, String(e.message || e));
    return;
  }
  const method = String(args.method || "GET").toUpperCase();
  const headers = Object.assign({}, args.headers || {});
  const targetToken = apiPolicy.token(target);
  if (!targetToken) { sendError(msg.id, "api: no captured token for target host"); return; }
  headers["Authorization"] = "Bearer " + targetToken;
  const hasBody = args.body != null;
  const hasContentType = Object.keys(headers).some((k) => k.toLowerCase() === "content-type");
  if (hasBody && !hasContentType) headers["Content-Type"] = "application/json";
  const body = hasBody
    ? (typeof args.body === "string" ? args.body : JSON.stringify(args.body))
    : undefined;

  const timeoutMs = Math.max(2000, Number(args.timeout_ms) > 0 ? Number(args.timeout_ms) : (Number(args.timeout) > 0 ? Number(args.timeout) : 15000));
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  fetch(target, {method, headers, body, signal: ctrl.signal})
    .then(async (resp) => {
      const isJson = isJsonContentType(resp);
      const payload = isJson
        ? await readBoundedResponseBody(resp).then((text) => {
          try { return JSON.parse(text); } catch (e) { return null; }
        })
        : await readBoundedResponseBody(resp).catch(() => "");
      sendResult(msg.id, {
        status: resp.status,
        ok: resp.ok,
        json: isJson ? payload : undefined,
        text: isJson ? undefined : payload,
      });
    })
    .catch((e) => {
      sendError(msg.id, String((e && e.message) || e));
    })
    .finally(() => clearTimeout(timer));
}

// Wait for a matching http(s) request to complete. NOTE: the pre-refactor
// code called an undefined `handleWaitXhr` here — every waitXhr command threw
// a ReferenceError inside the async onmessage handler and was silently
// dropped. This is the one deliberate behavior fix in the table refactor:
// waitXhr now actually waits for a future completion, matching the waitXhrOnce contract in
// background_network.js ({url_sub, method, tabId, timeout}).
function handleWaitXhrCommand(msg) {
  const args = msg.args || {};
  const timeout = Number(args.timeout_ms) > 0 ? Number(args.timeout_ms) : 15000;
  waitXhrOnce({
    // Both the Python CLI and the MCP bridge send url_substring (the bash CLI
    // sends url_sub) - accept all spellings so the filter is never dropped.
    urlSub: String(args.url_sub || args.url_substring || args.url || ""),
    method: args.method,
    tabId: args.tab !== undefined && args.tab !== null && args.tab !== "" ? resolveTabId(args.tab) : null,
    timeout,
  }).then((result) => sendResult(msg.id, result));
}

// Wait for a matching download to finish (page-independent).
function handleWaitDownloadCommand(msg) {
  const args = msg.args || {};
  const timeout = Number(args.timeout_ms) > 0 ? Number(args.timeout_ms) : 15000;
  const pattern = String(args.pattern || args.filename || args.url || "");
  waitDownloadOnce(pattern, timeout).then((result) => sendResult(msg.id, result));
}

// Page-world console capture (best-effort; see HONESTY notes above).
function handleConsoleCommand(msg) { handleConsole(msg); }

// Install the page-world auto-accept/dismiss hook for JS dialogs.
function handleDialogCommand(msg) { handleDialog(msg); }

// ---------------------------------------------------------------------------
// Page commands (route to a tab's content script) — the default dispatch
// target for every command without a background-side handler.
// ---------------------------------------------------------------------------
async function routePageCommand(msg) {
  // G2/A2: route page commands to the requested tab when `--tab` is
  // given (active tab otherwise). Resolve here so EVERY page command
  // (read/exec/wait_url/find/click/...) honors args.tab. Resolution is
  // focus-free (registry-based) so a url-substring or index target is
  // addressed even when not focused/active.
  let tabId;
  try {
    tabId = resolveTabId((msg.args || {}).tab);
  } catch (e) {
    sendError(msg.id, String(e.message || e));
    return;
  }
  // Needed mode tries a background route first and focuses only when
  // the target is unavailable. Always mode focuses before routing.
  const focusMode = await getFocusMode();
  let result;
  if (focusMode === "always") await autoActivateTab(tabId, msg, true);
  else if (focusMode === "needed" && !((msg.args || {}).no_activate === true) && isMutatingCommand(msg.cmd) && await tabNeedsActivation(tabId)) {
    await autoActivateTab(tabId, msg, true);
  }
  if (typeof SleeperChromiumDebugger !== "undefined" && (msg.cmd === "exec" || msg.cmd === "waitUntil")) {
    try {
      result = msg.cmd === "exec"
        ? await SleeperChromiumDebugger.exec(chrome, tabId, msg.args || {})
        : await SleeperChromiumDebugger.waitUntil(chrome, tabId, msg.args || {});
    } catch (error) {
      sendError(msg.id, String((error && error.message) || error));
      return;
    }
    sendResult(msg.id, result);
    return;
  }
  try {
    result = await routeToTab(tabId, msg);
  } catch (error) {
    const safeMutationFallback = isMutatingCommand(msg.cmd) && isDefinitelyNoDelivery(error);
    if (focusMode !== "needed" || !isUnreachableError(error) || (isMutatingCommand(msg.cmd) && !safeMutationFallback)) throw error;
    await autoActivateTab(tabId, msg, true);
    result = await routeToTab(tabId, msg, 0, true);
  }
  sendResult(msg.id, result);
}

// ---------------------------------------------------------------------------
// WebSocket to the daemon
// ---------------------------------------------------------------------------

// Read the paired WS token from settings or storage.local. The daemon never
// exposes its bearer over HTTP, and there is no hardcoded fallback.
async function getToken() {
  // 1) down-cache: last known good token survives a daemon outage
  try {
    const cached = await new Promise((res) =>
      chrome.storage.local.get(TOKEN_STORAGE_KEY, (v) => res(v && v[TOKEN_STORAGE_KEY]))
    );
    if (cached) daemonToken = cached;
  } catch (e) { /* storage may be unavailable on first install */ }

  const config = await readDaemonConfig();
  if (config.invalid) return "";
  if (config.token) {
    daemonToken = config.token;
    return config.token;
  }
  if (daemonToken) return daemonToken;

  try {
    const response = await new Promise((resolve) =>
      chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, { type: "get_daemon_token" }, resolve)
    );
    if (response && typeof response.token === "string" && response.token) {
      daemonToken = response.token;
      await new Promise((resolve) => chrome.storage.local.set({ [TOKEN_STORAGE_KEY]: daemonToken }, resolve));
      return daemonToken;
    }
  } catch (_) { /* native host is optional for recovery and remote-only installs */ }

  return "";
}

function sendHello() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const t = tabs && tabs[0];
    getBrowserInstanceId((browserId) => {
      sendToDaemon({
        type: "hello",
        client_type: "extension",
        addon_version: chrome.runtime.getManifest().version || "unknown",
        protocol_version: 2,
        source_id: SleeperSourceIdentity || "",
        profile: browserId,
        browser_id: browserId,
        url: (t && t.url) || "about:blank",
        title: (t && t.title) || "",
        active: true,
      });
    });
  });
}

function stopWebSocketKeepalive() {
  if (wsKeepaliveTimer) clearInterval(wsKeepaliveTimer);
  wsKeepaliveTimer = null;
}

function startWebSocketKeepalive(sock) {
  stopWebSocketKeepalive();
  wsKeepaliveTimer = setInterval(() => {
    if (ws !== sock || sock.readyState !== WebSocket.OPEN) {
      stopWebSocketKeepalive();
      return;
    }
    // WebSocket traffic resets Chromium's MV3 worker idle budget. Reusing the
    // existing hello also refreshes the daemon's active-tab metadata.
    sendHello();
  }, WS_KEEPALIVE_MS);
}

function getBrowserInstanceId(callback) {
  if (browserInstanceId) {
    callback(browserInstanceId);
    return;
  }

  browserInstanceIdCallbacks.push(callback);
  if (browserInstanceIdLoading) return;
  browserInstanceIdLoading = true;

  chrome.storage.local.get(BROWSER_INSTANCE_ID_KEY, (value) => {
    const storedId = value && value[BROWSER_INSTANCE_ID_KEY];
    const browserId = typeof storedId === "string" && storedId
      ? storedId
      : (typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const finish = () => {
      browserInstanceId = browserId;
      browserInstanceIdLoading = false;
      const callbacks = browserInstanceIdCallbacks;
      browserInstanceIdCallbacks = [];
      callbacks.forEach((queuedCallback) => queuedCallback(browserId));
    };

    if (storedId === browserId) finish();
    else chrome.storage.local.set({ [BROWSER_INSTANCE_ID_KEY]: browserId }, finish);
  });
}
if (chrome.storage && chrome.storage.onChanged) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes[DAEMON_HTTP_STORAGE_KEY] || changes[DAEMON_WS_STORAGE_KEY] || changes[DAEMON_AUTH_STORAGE_KEY]) {
      // Android may restart the background page while settings change. Tear
      // down the old socket so the single reconnect timer establishes only the
      // newly validated endpoint.
      if (ws) { try { ws.close(); } catch (_) {} }
      ws = null;
      wsReconnectAttempt = 0;
      scheduleReconnect(true);
    }
  });
}

// A3 — exponential backoff with jitter: base 500ms, cap 30s, reset to fast on
// a successful open. One pending timer at a time (no reconnect storms).
function jitter(ms) {
  return Math.round(ms * (0.7 + Math.random() * 0.6)); // ±30% around base
}

function scheduleReconnect(immediate) {
  if (wsClosedByUs) return;
  if (reconnectTimer) return; // already scheduled — don't stack
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  let delay;
  if (immediate && wsReconnectAttempt <= 3) {
    // daemon health is reachable — get back on the socket fast
    delay = 250;
  } else {
    const exp = Math.min(
      wsReconnectBase * Math.pow(1.6, Math.max(0, wsReconnectAttempt - 1)),
      WS_RECONNECT_MAX
    );
    delay = jitter(exp);
  }
  reconnectTimer = setTimeout(() => { reconnectTimer = null; connectWebSocket(); }, delay);
}

// A3 — on a dropped socket, probe the daemon over HTTP. Reachable => reconnect
// shortly; unreachable => back off. Failures here also advance the backoff so
// a long daemon outage doesn't hammer the loop.
function checkDaemonHealth() {
  wsReconnectAttempt++;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 1500);
 readDaemonConfig().then((config) => {
   if (config.invalid) { clearTimeout(t); scheduleReconnect(false); return null; }
   return fetch(`${config.http}/health`, { signal: ctrl.signal, cache: "no-store" });
 }).then((r) => { if (r) { clearTimeout(t); scheduleReconnect(!!r.ok); } })
    .catch(() => { clearTimeout(t); scheduleReconnect(false); });
}
function connectWebSocket() {
  activityTracker.setDaemonConnected(false);
  if (wsClosedByUs) return;
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  Promise.all([getToken(), readDaemonConfig()]).then(async ([tok, config]) => {
    if (wsClosedByUs || config.invalid) { wsReconnectAttempt++; scheduleReconnect(false); return; }
    if (!tok) {
      // No paired token yet; back off until setup supplies one.
      wsReconnectAttempt++;
      scheduleReconnect(false);
      return;
    }
    let instanceId;
    try {
      instanceId = await verifyDaemonIdentity(config, tok);
      if (!instanceId) throw new Error("daemon identity mismatch");
    } catch (_) {
      wsReconnectAttempt++;
      scheduleReconnect(false);
      return;
    }
    let sock;
    try { sock = new WebSocket(SleeperDaemonEndpoint.socketUrl(config)); }
    catch (e) { wsReconnectAttempt++; scheduleReconnect(false); return; }
    ws = sock;

    let wsAuthenticated = false;
    let wsChallenge = null;
    ws.onopen = () => {};

    ws.onmessage = async (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }      // Commands FROM the daemon: {id, cmd, args} — route to the target tab,
      if (msg && msg.type === "auth_challenge" && typeof msg.challenge === "string") {
        wsChallenge = msg.challenge;
        sock.send(JSON.stringify({ type: "auth", proof: await hmacHex(tok, `ws:${msg.challenge}`) }));
        return;
      }
      if (msg && msg.type === "auth_ok") {
        const expected = wsChallenge && await hmacHex(tok, `ws-ok:${instanceId}:${wsChallenge}`);
        if (!expected || msg.instance_id !== instanceId || msg.proof !== expected) {
          try { sock.close(); } catch (_) { /* noop */ }
          return;
        }
        wsAuthenticated = true;
        activityTracker.setDaemonConnected(true);
        console.log("Sleeper: Connected to daemon WS");
        wsReconnectAttempt = 0;
        loadApiHostAllowlist(config, tok, instanceId);
        refreshRegistry();
        sendHello();
        startWebSocketKeepalive(sock);
        return;
      }
      if (!wsAuthenticated) return;
      // await the page-world result, reply {id, ok, result|error} over WS.
      if (msg && typeof msg.id === "number" && msg.cmd) {
        activityTracker.start(msg.id);
        actionRecorder.start(msg);
        // Every handler path must reply exactly once. routePageCommand and
        // the content-script bridge surface page errors via rejection; an
        // uncaught rejection here used to reach nobody — the daemon waited
        // out its full budget and reported a misleading "timeout waiting for
        // page" instead of the real error (unknown command, missing
        // selector, exec unavailable, ...).
        try {
          if (!(await accessAllowed(msg))) {
            sendError(msg.id, "command blocked by Sleeper access settings");
            return;
          }
          const handler = BACKGROUND_COMMAND_HANDLERS[msg.cmd] || routePageCommand;
          await handler(msg);
        } catch (error) {
          sendError(msg.id, String((error && error.message) || error));
        }
        return;
      }

      // hello/bye from daemon — informational, ignore
      if (msg && (msg.type === "hello" || msg.type === "bye")) return;
    };

    ws.onclose = () => {
      stopWebSocketKeepalive();
      activityTracker.setDaemonConnected(false);
      console.log("Sleeper: WS disconnected");
      if (!wsClosedByUs) checkDaemonHealth();
    };

    ws.onerror = () => {
      activityTracker.setDaemonConnected(false);
      try { ws.close(); } catch (e) { /* noop */ }
    };
  }); // end getToken().then
}

// ---------------------------------------------------------------------------
// Command dispatch table
// One entry per command answered without a page round-trip. `shot` is listed
// for documentation; its handler is defined above. Commands not present here
// (find/click/type/exec/...) are page commands and fall through to
// routePageCommand, which resolves args.tab, applies focus policy, and
// forwards to the content script. Aliases share the same handler object.
// ---------------------------------------------------------------------------
const BACKGROUND_COMMAND_HANDLERS = {
  shot: handleScreenshotCommand,
  network: handleNetworkCommand,
  media: handleMediaCommand,
  tabs: handleTabsCommand,
  selecttab: handleTabLifecycleCommand,
  closetab: handleTabLifecycleCommand,
  newtab: handleNewTabCommand,
  goto: handleGotoCommand,
  tabinfo: handleTabInfoCommand,
  api: handleApiCommand,
  console: handleConsoleCommand,
  waitXhr: handleWaitXhrCommand,
  wait_xhr: handleWaitXhrCommand,
  waitDownload: handleWaitDownloadCommand,
  wait_download: handleWaitDownloadCommand,
  dialog: handleDialogCommand,
};

// ---------------------------------------------------------------------------
// Routing to a content script
// ---------------------------------------------------------------------------

// Activate the target tab for an explicitly focused operation, or after a
// needed-mode background attempt proves that Firefox has suspended it.
//
// SCOPE NOTE — DOM commands need the browser window to be VISIBLE (not
// minimized). Firefox MV2 has no chrome.debugger (that is Chrome-only), so a
// fully-hidden/minimized DOM op is impossible in Firefox: only background-side
// commands (api, console, waitXhr, dialog, newtab, goto, tabs, network) work
// with the browser minimized. We never force-focus or restore a minimized
// window here — that would steal OS focus (out of scope).
//
// Opt-out: set msg.args.no_activate = true to skip activation entirely. Never
// throws — routing still surfaces the actual reachability error.
function getFocusMode() {
  return new Promise((resolve) => {
    const storage = chrome.storage && chrome.storage.local;
    if (!storage || typeof storage.get !== "function") return resolve("needed");
    try {
      storage.get("focus_mode", (value) => {
        resolve(value && value.focus_mode === "always" ? "always" : "needed");
      });
    } catch (_) { resolve("needed"); }
  });
}

function isUnreachableError(error) {
  return !!(error && error.tabId != null && /not reachable|timed out awaiting content script/i.test(String(error.message || error)));
}

function isDefinitelyNoDelivery(error) {
  return !!(error && /receiving end does not exist|could not establish connection|no receiving end/i.test(String(error.message || error)));
}

function tabNeedsActivation(tabId) {
  return new Promise((resolve) => {
    try {
      chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError || !tab) return resolve(true);
        resolve(tab.discarded === true || tab.frozen === true || tab.status === "unloaded");
      });
    } catch (_) { resolve(true); }
  });
}

// Commands that can change page state must never be replayed after an
// uncertain message delivery. A lost callback cannot tell us whether the
// browser executed the command before the connection failed.
function isMutatingCommand(command) {
  return new Set([
    "click", "clickall", "clicktext", "dblclick", "drag", "type", "fill", "fillform",
    "press", "keys", "select", "selectoption", "check", "uncheck", "focus", "scroll",
    "scrolluntil", "upload", "eval", "exec", "submit", "back", "goto",
  ]).has(String(command || "").toLowerCase());
}

async function autoActivateTab(tabId, msg, focusWindow) {
  const args = (msg && msg.args) || {};
  if (args.no_activate === true) return; // explicit opt-out
  if (tabId == null || tabId < 0) return;
  try {
    // Resolve the tab's current state + window fresh (registry `active` can be
    // stale). Falls back to null when the tab is gone.
    const t = await new Promise((resolve) =>
      chrome.tabs.get(tabId, (t) => resolve(chrome.runtime.lastError ? null : t))
    );
    if (!t) return;  // tab closed/vanished — routeToTab will surface it
    const winId = t.windowId;
    if (t.active) {
      if (focusWindow && winId != null && chrome.windows && typeof chrome.windows.update === "function") {
        await new Promise((resolve) => chrome.windows.update(winId, { focused: true }, () => resolve()));
      }
      return;
    }
    // Activate the target tab. Always mode deliberately focuses the window;
    // needed mode uses this only after a background attempt was unreachable.
    await new Promise((resolve) =>
      chrome.tabs.update(tabId, { active: true }, () => resolve())
    );
    if (focusWindow && winId != null && chrome.windows && typeof chrome.windows.update === "function") {
      await new Promise((resolve) =>
        chrome.windows.update(winId, { focused: true }, () => resolve())
      );
    }
  } catch (e) {
    // Never throw on activation failure — proceed to routeToTab as before.
  }
}

// Send a command to a specific tab's content script and get the page-world
// result. G5/A2: if the sendMessage fails with a "receiving end does not
// exist"-style error (content script not injected yet — e.g. during nav or
// restore), retry with backoff until the content script answers. Brand-new
// tabs (newtab → immediately command) are the main driver: their content
// script does not exist until the document starts loading, so early attempts
// legitimately fail. Bounded by RETRY_WINDOW_MS so a truly dead tab fails
// within the daemon's dispatch budget instead of hanging; each attempt is
// also bounded so a hidden/suspended tab can't hang the promise. Once the
// content script answers, the tab is marked connected so later routing skips
// the injection race entirely.
const RETRY_WINDOW_MS = 8000;   // total budget for "not injected yet" retries
const RETRY_BASE_DELAY_MS = 250;

function routeToTab(tabId, msg, attempt, allowReplay, startedAt) {
  return new Promise((resolve, reject) => {
    const attempts = attempt || 0;
    const windowStart = startedAt || Date.now();
    let settled = false;
    const finish = (fn, v) => {
      if (settled) return;
      settled = true;
      clearTimeout(guardTimer);
      fn(v);
    };

    // A suspended/unresponsive tab may never invoke the sendMessage callback;
    // bound every attempt so we can retry or give up cleanly. But the bound must
    // be LONGER than the handler's own timeout (wait_url/waitDialog/waitFor poll
    // up to timeout_ms) or it races the handler and falsely aborts a live command.
    // Tie it to the command's timeout_ms when present, else a generous default.
    const argsTimeout = Number(msg && msg.args && msg.args.timeout_ms);
    const legacyTimeout = Number(msg && msg.args && msg.args.timeout);
    const cmdTimeout = Number.isFinite(argsTimeout) && argsTimeout > 0 ? argsTimeout
      : Number.isFinite(legacyTimeout) && legacyTimeout > 0 ? legacyTimeout : 15000;
    const guardMs = (Number.isFinite(cmdTimeout) ? cmdTimeout : 4000) + 3000;
    const guardTimer = setTimeout(() => {
      finish(reject, makeUnreachableError(tabId, "timed out awaiting content script"));
    }, guardMs);

    chrome.tabs.sendMessage(tabId, {
      type: "daemon-command",
      cmd: msg.cmd,
      args: msg.args || {},
    }, (resp) => {
      const err = chrome.runtime.lastError;
      if (err) {
        const m = String(err.message || err);
        const flaky = /receiving end does not exist|could not establish connection|no receiving end|message port closed/i.test(m);
        const withinWindow = Date.now() - windowStart < RETRY_WINDOW_MS;
        // Retry while the injection window is open. The only-replay-when-safe
        // rule applies once a command may have DELIVERED (mutating commands
        // answered with a port error after the page saw them); the
        // "receiving end does not exist" family here means the message was
        // NOT delivered — no listener existed — so replay is safe even for
        // mutating commands on a tab that is still loading.
        if (flaky && withinWindow && (allowReplay !== false)) {
          markTabDisconnected(tabId);
          const delay = Math.min(RETRY_BASE_DELAY_MS * Math.pow(1.5, attempts), 1000);
          setTimeout(() => {
            routeToTab(tabId, msg, attempts + 1, allowReplay, windowStart).then(
              (v) => finish(resolve, v),
              (e) => finish(reject, e)
            );
          }, delay);
          return;
        }
        // Retries exhausted (or a non-flaky error): give a clear, actionable
        // message naming the tab instead of a raw "receiving end" string.
        return finish(reject, makeUnreachableError(tabId, m));
      }
      if (resp && resp.ok) {
        markTabConnected(tabId);
        finish(resolve, resp.result);
      } else {
        finish(reject, new Error((resp && resp.error) || "no response from page"));
      }
    });
  });
}

function makeUnreachableError(tabId, detail) {
  const e = new Error(`tab ${tabId} is not reachable (content script not injected): ${detail}`);
  e.tabId = tabId;
  return e;
}

// C — resolve the `api` fetch target. Relative paths default to the primary
// capture host (chatgpt.com); absolute URLs must be on an allowed host so the
// captured bearer token is never exfiltrated to an arbitrary origin.

// ---------------------------------------------------------------------------
// Startup / tab tracking
// ---------------------------------------------------------------------------

// Keep the daemon's view of the "active tab" fresh so routing works, and keep
// the tab registry in sync. onRemoved is the authoritative eviction point so
// session-restore bursts don't wipe the registry (refreshRegistry only
// soft-marks misses).
chrome.tabs.onActivated.addListener(() => { refreshRegistry(); sendHello(); });
chrome.tabs.onCreated.addListener(() => refreshRegistry());
chrome.tabs.onRemoved.addListener((tabId) => {
  TAB_REGISTRY.delete(tabId);
  pageHooks.clear(tabId);
  refreshRegistry();
});
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    // Page tearing down for a new navigation — content script not reachable
    // yet, and any page-world hooks (console/dialog) are gone. Drop the stale
    // captured state so a fresh load starts clean.
    markTabDisconnected(tabId);
    pageHooks.clear(tabId);
    refreshRegistry();
  } else if (changeInfo.url || changeInfo.title) {
    refreshRegistry();
  }
  // G5: once a registered tab finishes loading, re-send the hello so the
  // daemon marks it connected again (survives page reloads).
  if (changeInfo.status === "complete" && TAB_REGISTRY.has(tabId)) {
    refreshRegistry();
    sendHello();
  }
});
if (chrome.windows && chrome.windows.onFocusChanged) {
  chrome.windows.onFocusChanged.addListener(() => { refreshRegistry(); sendHello(); });
}

// G2: mark a tab connected whenever its content script reports in (a hello,
// or any message carrying sender.tab). Lets the registry flag a reachable tab
// without waiting for a command round-trip.
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request && request.type === "sleeper-reconnect") {
    if (ws) { try { ws.close(); } catch (_) {} }
    ws = null;
    wsReconnectAttempt = 0;
    scheduleReconnect(true);
    sendResponse({ ok: true });
    return false;
  }
  if (request && request.type === "tailscale-setup") {
    SleeperTailscaleSetup.acceptOffer(chrome, request, sender, fetch)
      .then(sendResponse, () => sendResponse({ ok: false, error: "Tailscale setup failed." }));
    return true;
  }
  if (request && request.type === "approve-tailscale-setup") {
    SleeperTailscaleSetup.approveOffer(chrome, sender)
      .then(sendResponse, () => sendResponse({ ok: false, error: "Could not approve the daemon connection." }));
    return true;
  }
  if (request && request.type === "dismiss-tailscale-setup") {
    SleeperTailscaleSetup.dismissOffer(chrome, sender)
      .then(sendResponse, () => sendResponse({ ok: false, error: "Could not dismiss the daemon connection." }));
    return true;
  }
  if (sender && sender.tab && sender.tab.id != null) {
    const tabId = sender.tab.id;
    markTabConnected(tabId);
    pageHooks.acceptRuntimeMessage(tabId, request);
  }
  return false;
});

chrome.runtime.onInstalled.addListener((details) => {
  SleeperMobileOnboarding.openOnFirstAndroidInstall(chrome, details);
  chrome.storage.local.remove(["adblockEnabled", "profile"]);
  refreshRegistry();
  connectWebSocket();
});
chrome.runtime.onStartup.addListener(() => {
  refreshRegistry();
  connectWebSocket();
});

// Reloading an add-on does not reliably emit onInstalled or onStartup.
// Connect immediately whenever the background page itself is evaluated so a
// manual reload is sufficient to recover the daemon session.
refreshRegistry();
connectWebSocket();
