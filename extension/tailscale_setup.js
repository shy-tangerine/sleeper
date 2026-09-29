// Tailnet-only setup handoff from the daemon pairing page to the extension.
(function (root) {
  "use strict";

  const SETUP_PATH = "/sleeper-setup";
  const HTTP_PORT = "8790";
  const WS_PORT = "8789";

  function endpointsFor(value) {
    let url;
    try {
      url = new URL(String(value || ""));
    } catch (_) {
      return null;
    }
    if (url.protocol !== "https:" || url.pathname !== SETUP_PATH) return null;
    if (url.port !== HTTP_PORT || !url.hostname.toLowerCase().endsWith(".ts.net")) return null;
    if (url.username || url.password || url.search) return null;
    const fragment = url.hash.startsWith("#") ? url.hash.slice(1) : "";
    if (!fragment.startsWith("token=") || fragment.includes("&")) return null;
    let token;
    try { token = decodeURIComponent(fragment.slice("token=".length)); }
    catch (_) { return null; }
    if (!token) return null;
    return {
      http: `https://${url.hostname}:${HTTP_PORT}`,
      ws: `wss://${url.hostname}:${WS_PORT}/ws`,
      token,
    };
  }

  function setStorage(chromeApi, value) {
    return new Promise((resolve, reject) => {
      chromeApi.storage.local.set(value, () => {
        if (chromeApi.runtime.lastError) reject(new Error(chromeApi.runtime.lastError.message));
        else resolve();
      });
    });
  }

  function getStorage(chromeApi, keys) {
    return new Promise((resolve, reject) => {
      chromeApi.storage.local.get(keys, (value) => {
        if (chromeApi.runtime.lastError) reject(new Error(chromeApi.runtime.lastError.message));
        else resolve(value);
      });
    });
  }

  function removeStorage(chromeApi, keys) {
    return new Promise((resolve, reject) => {
      chromeApi.storage.local.remove(keys, () => {
        if (chromeApi.runtime.lastError) reject(new Error(chromeApi.runtime.lastError.message));
        else resolve();
      });
    });
  }

  function updateTab(chromeApi, tabId, value) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        if (chromeApi.runtime.lastError) reject(new Error(chromeApi.runtime.lastError.message));
        else resolve();
      };
      try {
        const result = chromeApi.tabs.update(tabId, value, done);
        if (result && typeof result.then === "function") result.then(done, reject);
      } catch (error) {
        reject(error);
      }
    });
  }

  async function verifyIdentity(base, token, fetchImpl) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    const nonce = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    const response = await fetchImpl(`${base}/health?nonce=${nonce}`, { cache: "no-store" });
    if (!response.ok) return false;
    const payload = await response.json();
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(token), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
    );
    const instanceId = String(payload.instance_id || "");
    const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${nonce}:${instanceId}`));
    const expected = Array.from(new Uint8Array(signature), (value) => value.toString(16).padStart(2, "0")).join("");
    return payload.identity_proof === expected ? instanceId : null;
  }

  async function authHeaders(token, instanceId, method, path) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    const nonce = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    const timestamp = Math.floor(Date.now() / 1000);
    const emptyHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array())),
      (value) => value.toString(16).padStart(2, "0")).join("");
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(token), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
    );
    const signature = await crypto.subtle.sign("HMAC", key,
      new TextEncoder().encode(`${instanceId}\n${nonce}\n${timestamp}\n${method}\n${path}\n${emptyHash}`));
    const proof = Array.from(new Uint8Array(signature), (value) => value.toString(16).padStart(2, "0")).join("");
    return { "X-Sleeper-Instance": instanceId, "X-Sleeper-Nonce": nonce,
      "X-Sleeper-Timestamp": String(timestamp), "X-Sleeper-Proof": proof };
  }

  async function acceptOffer(chromeApi, request, sender, fetchImpl) {
    const senderUrl = sender && sender.url;
    if (!request || request.type !== "tailscale-setup" || request.url !== senderUrl) {
      return { ok: false, error: "Invalid setup request." };
    }
    const endpoints = endpointsFor(senderUrl);
    if (!endpoints || !sender.tab || sender.tab.id == null) {
      return { ok: false, error: "Setup must be opened from a Sleeper tailnet URL." };
    }

    try {
      const instanceId = await verifyIdentity(endpoints.http, endpoints.token, fetchImpl);
      if (!instanceId) {
        return { ok: false, error: "The tailnet endpoint could not verify the Sleeper daemon." };
      }
      const headers = await authHeaders(endpoints.token, instanceId, "GET", "/tabs");
      const response = await fetchImpl(`${endpoints.http}/tabs`, {
        cache: "no-store",
        headers,
      });
      const payload = response.ok ? await response.json() : null;
      if (!payload || payload.ok !== true || !Array.isArray(payload.tabs)) {
        return { ok: false, error: "The tailnet endpoint could not verify the Sleeper daemon." };
      }
      const current = await getStorage(chromeApi, [
        "daemon_http_url", "daemon_ws_url", "daemon_auth_token",
      ]);
      const replacing = Boolean(
        current.daemon_http_url && current.daemon_auth_token &&
        (current.daemon_http_url !== endpoints.http || current.daemon_auth_token !== endpoints.token)
      );
      if (replacing) {
        await setStorage(chromeApi, {
          pending_tailscale_http_url: endpoints.http,
          pending_tailscale_ws_url: endpoints.ws,
          pending_tailscale_auth_token: endpoints.token,
          pending_tailscale_instance_id: instanceId,
        });
        await updateTab(chromeApi, sender.tab.id, {
          url: chromeApi.runtime.getURL("options.html#daemon-connection"),
          active: true,
        });
        return { ok: true, pendingApproval: true };
      }
      await setStorage(chromeApi, {
        daemon_http_url: endpoints.http,
        daemon_ws_url: endpoints.ws,
        daemon_auth_token: endpoints.token,
      });
      await updateTab(chromeApi, sender.tab.id, {
        url: chromeApi.runtime.getURL("options.html#daemon-connection"),
        active: true,
      });
      return { ok: true };
    } catch (_) {
      return { ok: false, error: "Could not reach the Sleeper daemon through Tailscale." };
    }
  }

  function isOptionsSender(chromeApi, sender) {
    const url = String(sender && sender.url || "");
    return url.startsWith(chromeApi.runtime.getURL("options.html"));
  }

  async function approveOffer(chromeApi, sender) {
    if (!isOptionsSender(chromeApi, sender)) return { ok: false, error: "Approval must come from Sleeper settings." };
    const pending = await getStorage(chromeApi, [
      "pending_tailscale_http_url", "pending_tailscale_ws_url",
      "pending_tailscale_auth_token", "pending_tailscale_instance_id",
    ]);
    if (!pending.pending_tailscale_http_url || !pending.pending_tailscale_auth_token) {
      return { ok: false, error: "There is no pending daemon connection." };
    }
    await setStorage(chromeApi, {
      daemon_http_url: pending.pending_tailscale_http_url,
      daemon_ws_url: pending.pending_tailscale_ws_url,
      daemon_auth_token: pending.pending_tailscale_auth_token,
    });
    await removeStorage(chromeApi, [
      "pending_tailscale_http_url", "pending_tailscale_ws_url",
      "pending_tailscale_auth_token", "pending_tailscale_instance_id",
    ]);
    return { ok: true };
  }

  async function dismissOffer(chromeApi, sender) {
    if (!isOptionsSender(chromeApi, sender)) return { ok: false, error: "Dismissal must come from Sleeper settings." };
    await removeStorage(chromeApi, [
      "pending_tailscale_http_url", "pending_tailscale_ws_url",
      "pending_tailscale_auth_token", "pending_tailscale_instance_id",
    ]);
    return { ok: true };
  }

  function offerFromPage(chromeApi, locationLike) {
    const url = String(locationLike && locationLike.href || "");
    if (!endpointsFor(url) || !chromeApi || !chromeApi.runtime) return false;
    try {
      chromeApi.runtime.sendMessage({ type: "tailscale-setup", url }, () => {
        void chromeApi.runtime.lastError;
      });
      return true;
    } catch (_) {
      return false;
    }
  }

  root.SleeperTailscaleSetup = {
    SETUP_PATH, endpointsFor, acceptOffer, approveOffer, dismissOffer, offerFromPage,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
