// Shared tab inventory for Firefox MV2 background pages and Chromium MV3 workers.
// Loaded before background.js and intentionally exposes one narrow global module.
(function (root) {
  "use strict";

  function createTabRegistry(chromeApi) {
    const entries = new Map();
    const pruneAfterMisses = 5;

    function upsert(tab) {
      const previous = entries.get(tab.id);
      const entry = {
        tabId: tab.id,
        windowId: tab.windowId,
        index: tab.index,
        url: tab.url || "",
        title: tab.title || "",
        active: !!tab.active,
        connected: previous ? previous.connected : false,
        misses: 0,
      };
      entries.set(tab.id, entry);
      return entry;
    }

    function refresh() {
      return new Promise((resolve) => {
        chromeApi.tabs.query({}, (tabs) => {
          if (chromeApi.runtime.lastError) {
            resolve();
            return;
          }
          const seen = new Set();
          (tabs || []).forEach((tab) => {
            if (tab.id === chromeApi.tabs.TAB_ID_NONE) return;
            seen.add(tab.id);
            upsert(tab);
          });
          for (const [tabId, entry] of entries) {
            if (!seen.has(tabId)) {
              entry.misses++;
              if (entry.misses > pruneAfterMisses) entries.delete(tabId);
            } else if (entry.misses > 0) {
              entry.misses = 0;
            }
          }
          resolve();
        });
      });
    }

    function markConnected(tabId) {
      const entry = entries.get(tabId);
      if (entry) {
        entry.connected = true;
        entry.misses = 0;
      }
    }

    function markDisconnected(tabId) {
      const entry = entries.get(tabId);
      if (entry) entry.connected = false;
    }

    function snapshot() {
      return Array.from(entries.values())
        .map(({ misses, ...rest }) => rest)
        .sort((left, right) => (left.windowId - right.windowId) || (left.index - right.index));
    }

    function resolve(tab) {
      const all = Array.from(entries.values());
      const pick = (predicate) => {
        const match = all.find(predicate);
        return match ? match.tabId : null;
      };
      const fail = (message, value) => {
        const error = new Error(message);
        error.tab = value;
        throw error;
      };

      if (tab === undefined || tab === null || tab === "") {
        const active = pick((entry) => entry.active);
        if (active != null) return active;
        if (all[0]) return all[0].tabId;
        fail("no active tab", tab);
      }
      if (typeof tab === "string" && /^\d+$/.test(tab)) tab = Number(tab);
      if (typeof tab === "number") {
        const ordered = all.slice().sort(
          (left, right) => (left.windowId - right.windowId) || (left.index - right.index),
        );
        if (tab >= 0 && tab < ordered.length) return ordered[tab].tabId;
        fail("tab not found at position " + tab + " (" + ordered.length + " tabs)", tab);
      }
      if (typeof tab === "string" && tab.length > 0) {
        const substring = tab.toLowerCase();
        const byUrl = pick((entry) => (entry.url || "").toLowerCase().includes(substring));
        if (byUrl != null) return byUrl;
        fail("tab not found by url: " + tab, tab);
      }
      fail("invalid tab: " + tab, tab);
    }

    return { entries, refresh, markConnected, markDisconnected, snapshot, resolve };
  }

  root.SleeperBackgroundTabs = { createTabRegistry };
})(typeof globalThis !== "undefined" ? globalThis : this);
