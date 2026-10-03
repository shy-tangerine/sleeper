// Shared tab inventory for Firefox MV2 background pages and Chromium MV3 workers.
// Loaded before background.js and intentionally exposes one narrow global module.
(function (root) {
  "use strict";

  function createTabRegistry(chromeApi) {
    const entries = new Map();
    const owned = new Set();
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
      return new Promise((resolve, reject) => {
        chromeApi.tabs.query({}, (tabs) => {
          if (chromeApi.runtime.lastError) {
            reject(new Error("cannot refresh tab registry: " + chromeApi.runtime.lastError.message));
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

    function orderedEntries() {
      return Array.from(entries.values())
        .sort((left, right) => (left.windowId - right.windowId) || (left.index - right.index));
    }

    function snapshot() {
      return orderedEntries().map(({ misses, index: windowIndex, ...rest }, index) => ({
        ...rest, index, windowIndex, selector: `id:${rest.tabId}`,
      }));
    }

    async function resolve(tab, { mutating = false, allowUserTab = false } = {}) {
      await refresh();
      // Soft-retained entries tolerate restore churn in listings, but are
      // never valid command targets unless the latest query saw them.
      const all = Array.from(entries.values()).filter(entry => entry.misses === 0);
      if (mutating && tab != null && tab !== "" && !/^id:\d+$/.test(String(tab))) {
        throw new Error("mutating commands require an explicit id:N tab selector; use sleeper tabs");
      }
      const checked = (id) => {
        if (mutating && !owned.has(id) && (!allowUserTab || tab == null || tab === "")) {
          throw new Error("tab id:" + id + " was not created by Sleeper; use an explicit id:N selector with --allow-user-tab");
        }
        return id;
      };
      const pick = (predicate) => {
        const match = all.find(predicate);
        return match ? checked(match.tabId) : null;
      };
      const fail = (message, value) => {
        const error = new Error(message);
        error.tab = value;
        throw error;
      };

      if (tab === undefined || tab === null || tab === "") {
        const active = pick((entry) => entry.active);
        if (active != null) return active;
        if (all[0]) return checked(all[0].tabId);
        fail("no active tab", tab);
      }
      if (typeof tab === "string" && tab.startsWith("id:")) {
        const id = /^id:\d+$/.test(tab) ? Number(tab.slice(3)) : NaN;
        if (Number.isSafeInteger(id) && all.some(entry => entry.tabId === id)) return checked(id);
        fail("tab not found by id: " + tab + "; re-list tabs if the browser session was restored", tab);
      }
      if (typeof tab === "string" && /^\d+$/.test(tab)) tab = Number(tab);
      if (typeof tab === "number") {
        const ordered = orderedEntries().filter(entry => entry.misses === 0);
        if (Number.isInteger(tab) && tab >= 0 && tab < ordered.length) return ordered[tab].tabId;
        fail("tab not found at position " + tab + " (" + ordered.length + " tabs)", tab);
      }
      if (typeof tab === "string" && tab.length > 0) {
        const substring = tab.toLowerCase();
        const matches = all.filter((entry) => (entry.url || "").toLowerCase().includes(substring));
        if (matches.length === 1) return matches[0].tabId;
        if (matches.length > 1) fail("ambiguous tab URL: " + tab + "; use an id: selector from tab list", tab);
        fail("tab not found by url: " + tab, tab);
      }
      fail("invalid tab: " + tab, tab);
    }

    return { entries, owned, refresh, markConnected, markDisconnected, snapshot, resolve };
  }

  root.SleeperBackgroundTabs = { createTabRegistry };
})(typeof globalThis !== "undefined" ? globalThis : this);
