(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SleeperApiHostPolicy = factory();
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const HOST = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
  function parseHostAllowlist(entries) {
    if (!Array.isArray(entries)) throw new Error("invalid HTTPS host allowlist");
    return Array.from(new Set(entries.map((x) => String(x || "").trim().toLowerCase()).map((host) => {
      if (!HOST.test(host) || host.includes("*") || host.includes(":") || host.includes("/"))
        throw new Error("invalid HTTPS host allowlist entry");
      return host;
    })));
  }
  function resolveApiUrl(input, allowed) {
    const hosts = parseHostAllowlist(allowed);
    const raw = String(input || "");
    if (/^[a-z][a-z0-9+.-]*:\/\/[^/]+:\d+(?:\/|$)/i.test(raw)) throw new Error("API URL must not specify a port");
    if (!hosts.length) throw new Error("API host allowlist is empty");
    const url = new URL(raw.startsWith("/") ? `https://${hosts[0]}` + raw : raw);
    const host = url.hostname.toLowerCase();
    if (url.protocol !== "https:" || url.port) throw new Error("API URL must use HTTPS without a port");
    if (!hosts.includes(host)) throw new Error("API host is not allowed");
    return url.href;
  }
  function createPolicy(entries) {
    let allowed = parseHostAllowlist(entries);
    const tokens = new Map();
    return {
      hosts: () => allowed.slice(),
      setHosts(next) { allowed = parseHostAllowlist(next); for (const h of tokens.keys()) if (!allowed.includes(h)) tokens.delete(h); },
      capture(url, value) { try { const u = new URL(url); const h = u.hostname.toLowerCase(); if (u.protocol !== "https:" || u.port || !allowed.includes(h)) return false; const m = String(value || "").match(/^Bearer\s+(.+?)\s*$/i); if (!m || !m[1]) return false; tokens.set(h, m[1]); return true; } catch (_) { return false; } },
      token(url) { try { const u = new URL(url); if (u.protocol !== "https:" || u.port || !allowed.includes(u.hostname.toLowerCase())) return null; return tokens.get(u.hostname.toLowerCase()) || null; } catch (_) { return null; } },
      resolve(url) { return resolveApiUrl(url, allowed); },
    };
  }
  return { parseHostAllowlist, resolveApiUrl, createPolicy };
}));
