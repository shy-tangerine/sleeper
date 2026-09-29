// Network observation, filtering, and event-driven request/download waits.
(function (root) {
  "use strict";

  function createNetworkCapture(chromeApi) {
    // ---------------------------------------------------------------------------
    // Network capture (opencli `browser network` pattern)
    // Logs http(s) requests per tab so media/CDN URLs stay resolvable even when
    // the page hides them behind blob: URLs (e.g. Instagram story videos).
    // ---------------------------------------------------------------------------

    const NET_LOG = new Map(); // tabId -> [{url, method, type, status, ts}]
    const NET_MAX = 1000;
    const NET_FILTER = { urls: ["http://*/*", "https://*/*"] };
    const MEDIA_EXT = /\.(mp4|m4v|mov|webm|mkv|avi|jpg|jpeg|png|webp|gif|avif|heic)(\?|#|$)/i;
    function pushNet(tabId, entry) {
      if (tabId === undefined || tabId < 0) return;
      let arr = NET_LOG.get(tabId);
      if (!arr) { arr = []; NET_LOG.set(tabId, arr); }
      arr.push(entry);
      if (arr.length > NET_MAX) arr.splice(0, arr.length - NET_MAX);
    }

    function stampNet(d, status) {
      return { url: d.url, method: d.method, type: d.type, status, ts: Date.now() };
    }

    chromeApi.webRequest.onBeforeRequest.addListener((d) => {
      pushNet(d.tabId, stampNet(d, 0));
    }, NET_FILTER);

    chromeApi.webRequest.onCompleted.addListener((d) => {
      const arr = NET_LOG.get(d.tabId);
      if (arr) {
        const last = arr[arr.length - 1];
        if (last && last.url === d.url && last.status === 0) last.status = d.statusCode;
      }
      checkWaiters(d, d.statusCode); // one-shot waitXhr matchers
    }, NET_FILTER);

    chromeApi.webRequest.onErrorOccurred.addListener((d) => {
      const arr = NET_LOG.get(d.tabId);
      if (arr) {
        const last = arr[arr.length - 1];
        if (last && last.url === d.url) last.status = d.error || 0;
      }
      // A matching request that errored will never "complete" — fail its waiter
      // so waitXhr doesn't hang until its timeout.
      for (const w of WAITERS) {
        if (w.done) continue;
        if (w.m && (d.method || "").toLowerCase() !== w.m) continue;
        if (w.url && !(d.url || "").toLowerCase().includes(w.url)) continue;
        if (w.tabId != null && d.tabId !== w.tabId) continue;
        w.finish({ matched: false, error: d.error || "request error" });
      }
    }, NET_FILTER);

    function netResponse(args, tabId) {
      const arr = NET_LOG.get(tabId) || [];
      const media = !!(args && args.media);
      const since = Number((args && args.since) || 0);
      const now = Date.now();
      let out = arr.filter((e) => {
        if (since > 0 && now - e.ts > since * 1000) return false;
        if (media && !(e.type === "media" || e.type === "image" || MEDIA_EXT.test(e.url))) return false;
        return true;
      });
      if (media) { // dedupe byte-range variants; keep the richest/latest entry
        const seen = new Map();
        for (const e of out) {
          let key = e.url;
          try {
            const u = new URL(e.url);
            ["bytestart", "byteend", "range", "cb", "cache", "cachebuster"].forEach((p) => u.searchParams.delete(p));
            key = u.href;
          } catch (_) {}
          const prev = seen.get(key);
          // Prefer progressive media and completed responses over range fragments.
          const score = (x) => (x.status >= 200 && x.status < 400 ? 2 : 0) +
            (/\.(mp4|m4v|mov|webm)(\?|#|$)/i.test(x.url) ? 2 : 0);
          if (!prev || score(e) >= score(prev)) seen.set(key, e);
        }
        out = Array.from(seen.values());
      }
      out.sort((a, b) => a.ts - b.ts || String(a.url).localeCompare(String(b.url)));
      let segment = 0, previous = null;
      out = out.map((e) => {
        if (previous != null && e.ts - previous >= 4000) segment++;
        previous = e.ts;
        return Object.assign({}, e, {segment});
      });
      if (args && args.segment != null) out = out.filter((e) => e.segment === Number(args.segment));
      return { tabId, count: out.length, segments: segment + (out.length ? 1 : 0), entries: out };
    }

    // ---------------------------------------------------------------------------
    // waitXhr — wait until a matching http(s) request completes
    // One-shot event-driven matcher layered on the existing webRequest listeners.
    // Does NOT touch the `network` ring buffer; it only reads/complements it.
    // ---------------------------------------------------------------------------

    const WAITERS = []; // { url, m, tabId, finish }

    // Download observation parity. The listener is optional so Firefox/older
    // Chromium builds without the downloads API continue to start cleanly.
    const DOWNLOAD_WAITERS = [];
    const DOWNLOADS = [];
    if (chromeApi.downloads && chromeApi.downloads.onCreated) {
      chromeApi.downloads.onCreated.addListener((item) => {
        DOWNLOADS.push({ id: item.id, url: item.url || "", filename: item.filename || "", state: item.state || "in_progress", ts: Date.now() });
        if (DOWNLOADS.length > 200) DOWNLOADS.splice(0, DOWNLOADS.length - 200);
        for (const waiter of DOWNLOAD_WAITERS) waiter.eligibleIds.add(item.id);
      });
      chromeApi.downloads.onChanged.addListener((delta) => {
        const item = DOWNLOADS.find((x) => x.id === delta.id);
        if (!item) return;
        if (delta.state && delta.state.current) item.state = delta.state.current;
        if (delta.filename && delta.filename.current) item.filename = delta.filename.current;
        for (const waiter of DOWNLOAD_WAITERS.slice()) {
          if (waiter.done || !waiter.eligibleIds.has(item.id) || (waiter.pattern && !(`${item.url} ${item.filename}`).includes(waiter.pattern))) continue;
          if (item.state === "complete" || item.state === "interrupted") waiter.finish({ matched: item.state === "complete", download: Object.assign({}, item) });
        }
      });
    }
    function waitDownloadOnce(pattern, timeout) {
      return new Promise((resolve) => {
        // A wait observes future completion, including an already-running download.
        // Terminal entries from an earlier command are deliberately excluded.
        const eligibleIds = new Set(DOWNLOADS.filter((x) => x.state !== "complete" && x.state !== "interrupted").map((x) => x.id));
        const waiter = { pattern, eligibleIds, done: false, finish: (result) => { if (waiter.done) return; waiter.done = true; clearTimeout(waiter.timer); clearInterval(waiter.pollTimer); const i = DOWNLOAD_WAITERS.indexOf(waiter); if (i >= 0) DOWNLOAD_WAITERS.splice(i, 1); resolve(result); } };
        waiter.timer = setTimeout(() => waiter.finish({ matched: false, pattern }), timeout);
        DOWNLOAD_WAITERS.push(waiter);
        if (chromeApi.downloads && typeof chromeApi.downloads.search === "function") {
          const poll = () => {
            const inspect = (items) => {
              if (waiter.done) return;
              const terminal = (items || []).find((item) =>
                waiter.eligibleIds.has(item.id) &&
                (!pattern || (`${item.url || ""} ${item.filename || ""}`).includes(pattern)) &&
                (item.state === "complete" || item.state === "interrupted")
              );
              if (terminal) waiter.finish({ matched: terminal.state === "complete", download: Object.assign({}, terminal) });
            };
            try {
              const pending = chromeApi.downloads.search({});
              if (pending && typeof pending.then === "function") {
                pending.then(inspect, () => {});
                return;
              }
            } catch (_) { /* try the callback form below */ }
            try { chromeApi.downloads.search({}, inspect); }
            catch (_) { /* event listeners remain the compatibility fallback */ }
          };
          poll();
          if (!waiter.done) waiter.pollTimer = setInterval(poll, 250);
        }
      });
    }

    function checkWaiters(d, status) {
      for (const w of WAITERS) {
        if (w.done) continue;
        if (w.m && (d.method || "").toLowerCase() !== w.m) continue;
        if (w.url && !(d.url || "").toLowerCase().includes(w.url)) continue;
        if (w.tabId != null && d.tabId !== w.tabId) continue;
        w.finish({ matched: true, url: d.url, status });
      }
    }

    function waitXhrOnce({ urlSub, method, tabId, timeout }) {
      return new Promise((resolve) => {
        const url = (urlSub || "").toLowerCase();
        const m = method ? method.toLowerCase() : null;
        // Register synchronously so a completion after this call cannot be missed.
        const waiter = {
          url, m, tabId,
          done: false,
          finish: (result) => {
            if (waiter.done) return;
            waiter.done = true;
            clearTimeout(waiter.timer);
            const i = WAITERS.indexOf(waiter);
            if (i >= 0) WAITERS.splice(i, 1);
            resolve(result);
          },
        };
        waiter.timer = setTimeout(() => waiter.finish({ matched: false }), timeout);
        WAITERS.push(waiter);
      });
    }


    return {
      log: NET_LOG,
      response: netResponse,
      waitForDownload: waitDownloadOnce,
      waitForRequest: waitXhrOnce,
    };
  }

  root.SleeperBackgroundNetwork = { createNetworkCapture };
})(typeof globalThis !== "undefined" ? globalThis : this);
