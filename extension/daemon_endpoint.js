// Daemon endpoint parsing is deliberately isolated from background.js so the
// options page and connection lifecycle make exactly the same security choice.
(function (root) {
  "use strict";

  const DEFAULT_HTTP = "http://127.0.0.1:8790";
  const DEFAULT_WS = "ws://127.0.0.1:8789/ws";

  function loopback(hostname) {
    const host = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
    return host === "localhost" || host === "::1" || /^127(?:\.\d{1,3}){3}$/.test(host);
  }

  function endpointError(message) { return { ok: false, error: message }; }

  function tailscale(hostname) {
    return String(hostname || "").toLowerCase().endsWith(".ts.net");
  }

  function validate(httpValue, wsValue, token) {
    const httpText = String(httpValue || DEFAULT_HTTP).trim().replace(/\/$/, "");
    const wsText = String(wsValue || DEFAULT_WS).trim();
    let http, ws;
    try { http = new URL(httpText); ws = new URL(wsText); }
    catch (_) { return endpointError("Enter complete daemon URLs."); }
    if (!/^https?:$/.test(http.protocol) || !/^wss?:$/.test(ws.protocol)) {
      return endpointError("Daemon URLs must use HTTP(S) and WS(S).");
    }
    if (http.username || http.password || ws.username || ws.password || http.search || ws.search || http.hash || ws.hash) {
      return endpointError("Daemon URLs cannot include credentials, queries, or fragments.");
    }
    if (ws.pathname !== "/ws" || http.pathname !== "/") {
      return endpointError("Use an HTTP base URL and a WebSocket URL ending in /ws.");
    }
    if (http.hostname !== ws.hostname) return endpointError("HTTP and WebSocket endpoints must use the same host.");
    const local = loopback(http.hostname) && loopback(ws.hostname);
    const tailnet = tailscale(http.hostname) && tailscale(ws.hostname);
    if (!local && !tailnet) return endpointError("Mobile connections require a Tailscale .ts.net address.");
    if (tailnet && (http.protocol !== "https:" || ws.protocol !== "wss:")) {
      return endpointError("Tailscale connections require HTTPS and WSS.");
    }
    return {
      ok: true,
      http: http.href.replace(/\/$/, ""),
      ws: ws.href,
      remote: !local,
      tailscale: tailnet,
      token: typeof token === "string" ? token.trim() : "",
    };
  }

  function defaults() { return { http: DEFAULT_HTTP, ws: DEFAULT_WS, remote: false, token: "" }; }
  function socketUrl(config) { return config.ws; }

  root.SleeperDaemonEndpoint = { DEFAULT_HTTP, DEFAULT_WS, loopback, tailscale, validate, defaults, socketUrl };
})(typeof globalThis !== "undefined" ? globalThis : this);
