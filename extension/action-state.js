/* Toolbar activity state for the background relay. */
(function (root) {
  "use strict";

  const DEFAULT_IDLE_MS = 3000;
  const INACTIVE_ICON_PATHS = { 16: "icon16.png", 32: "icon32.png", 128: "icon128.png" };
  const ACTIVE_ICON_PATHS = { 16: "icon-active16.png", 32: "icon-active32.png", 128: "icon-active128.png" };
  const IDLE_ACTION_TITLE = "Sleeper controls";
  const ACTIVE_ACTION_TITLE = "Sleeper — command in progress";

  function createActivityTracker(options) {
    const settings = options || {};
    const chromeApi = settings.chromeApi || (typeof chrome !== "undefined" ? chrome : null);
    const browserApi = settings.browserApi || (typeof browser !== "undefined" ? browser : null);
    const setTimeoutFn = settings.setTimeoutFn || root.setTimeout;
    const clearTimeoutFn = settings.clearTimeoutFn || root.clearTimeout;
    const now = settings.now || Date.now;
    const idleMs = settings.idleMs == null ? DEFAULT_IDLE_MS : settings.idleMs;
    const activeRequests = new Set();
    let connected = false;
    let hideTimer = null;
    let generatedRequestId = 0;
    let idleGeneration = 0;
    let idleDeadline = 0;

    function storageSet(values) {
      try {
        const storage = chromeApi && chromeApi.storage && chromeApi.storage.local;
        if (storage && typeof storage.set === "function") storage.set(values);
      } catch (_) {}
    }

    function actionApi() {
      if (browserApi && browserApi.browserAction) return browserApi.browserAction;
      if (chromeApi) return chromeApi.action || chromeApi.browserAction;
      return null;
    }

    function updateToolbarIcon() {
      const api = actionApi();
      if (!api || typeof api.setIcon !== "function") return;
      const paths = activeRequests.size ? ACTIVE_ICON_PATHS : INACTIVE_ICON_PATHS;
      const title = activeRequests.size ? ACTIVE_ACTION_TITLE : IDLE_ACTION_TITLE;
      try {
        const iconResult = api.setIcon({ path: paths });
        if (iconResult && typeof iconResult.catch === "function") iconResult.catch(() => {});
        const titleResult = api.setTitle({ title });
        if (titleResult && typeof titleResult.catch === "function") titleResult.catch(() => {});
      } catch (_) {}
    }

    function setActive(active) {
      storageSet({ action_in_progress: active });
      updateToolbarIcon();
    }

    function cancelHideTimer() {
      idleGeneration += 1;
      if (hideTimer === null) return;
      clearTimeoutFn(hideTimer);
      hideTimer = null;
    }

    function scheduleIdleClose() {
      cancelHideTimer();
      const generation = idleGeneration;
      idleDeadline = now() + idleMs;
      const closeWhenIdle = () => {
        hideTimer = null;
        if (generation !== idleGeneration || activeRequests.size !== 0) return;
        const remaining = idleDeadline - now();
        if (remaining > 0) {
          hideTimer = setTimeoutFn(closeWhenIdle, remaining);
          return;
        }
        setActive(false);
      };
      hideTimer = setTimeoutFn(closeWhenIdle, idleMs);
    }

    function start(requestId) {
      cancelHideTimer();
      const id = requestId === undefined || requestId === null
        ? `implicit-${++generatedRequestId}`
        : requestId;
      activeRequests.add(id);
      setActive(true);
      return id;
    }

    function finish(requestId) {
      if (requestId === undefined || requestId === null || !activeRequests.has(requestId)) return;
      activeRequests.delete(requestId);
      if (activeRequests.size === 0) scheduleIdleClose();
    }

    function setDaemonConnected(value) {
      connected = !!value;
      storageSet({ daemon_connected: connected });
      if (!connected) {
        activeRequests.clear();
        cancelHideTimer();
        setActive(false);
        return;
      }
      updateToolbarIcon();
    }

    return {
      setDaemonConnected,
      start,
      finish,
      isActive: () => activeRequests.size > 0,
      isConnected: () => connected,
    };
  }

  function createActionRecorder(options) {
    const settings = options || {};
    const chromeApi = settings.chromeApi || (typeof chrome !== "undefined" ? chrome : null);
    const now = settings.now || Date.now;
    const maxEntries = settings.maxEntries == null ? 200 : settings.maxEntries;
    const storageKey = settings.storageKey || "action_log";
    const active = new Map();
    const pendingLogs = [];
    let logWriteBusy = false;

    function storage() {
      return chromeApi && chromeApi.storage && chromeApi.storage.local;
    }

    function cleanText(value, limit) {
      return typeof value === "string" && value ? value.slice(0, limit) : undefined;
    }

    function safeUrl(value) {
      if (typeof value !== "string" || !/^https?:\/\//i.test(value)) return undefined;
      try {
        const parsed = new URL(value);
        return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
      } catch (_) {
        return undefined;
      }
    }

    function summary(msg, status) {
      const args = msg && msg.args && typeof msg.args === "object" ? msg.args : {};
      const started = now();
      const row = {
        cmd: String((msg && msg.cmd) || "unknown"),
        ts: started,
        started_at: new Date(started).toISOString(),
        status,
      };
      const tab = cleanText(args.tab, 160);
      // Keep locator metadata useful for the activity UI, while deliberately
      // excluding value-bearing fields (text/value/files/body) that may hold
      // passwords or other typed secrets.
      const target = cleanText(args.selector, 160) || cleanText(args.target, 160)
        || cleanText(args.role, 80) || cleanText(args.name, 120)
        || cleanText(args.label, 120) || cleanText(args.testid, 120);
      const url = safeUrl(args.url);
      if (tab) row.tab = tab;
      if (target) row.target = target;
      if (url) row.url = url;
      return row;
    }

    function setCurrent() {
      const values = Array.from(active.values());
      const api = storage();
      if (api && typeof api.set === "function") {
        try { api.set({ current_action: values.length ? values[values.length - 1] : null }); } catch (_) {}
      }
    }

    function start(msg) {
      if (!msg || msg.id === undefined || msg.id === null) return;
      active.set(msg.id, summary(msg, "running"));
      setCurrent();
    }

    function finish(id, ok, detail) {
      if (!active.has(id)) return;
      const running = active.get(id);
      active.delete(id);
      const completed = Object.assign({}, running, {
        duration_ms: Math.max(0, Math.round(now() - running.ts)),
        ok: !!ok,
        status: ok ? "success" : "failure",
      });
      const resultUrl = detail && typeof detail === "object" ? safeUrl(detail.url) : undefined;
      if (resultUrl) completed.url = resultUrl;
      setCurrent();

      const api = storage();
      if (!api || typeof api.get !== "function" || typeof api.set !== "function") return;
      // storage.get is asynchronous. Serializing read/modify/write cycles
      // prevents two overlapping browser actions from dropping one another's
      // completion rows when they finish in the same turn.
      pendingLogs.push(completed);
      if (logWriteBusy) return;
      const writeNext = () => {
        if (!pendingLogs.length) { logWriteBusy = false; return; }
        logWriteBusy = true;
        const entry = pendingLogs.shift();
        try {
          api.get(storageKey, (value) => {
            const log = value && Array.isArray(value[storageKey]) ? value[storageKey] : [];
            try { api.set({ [storageKey]: log.concat(entry).slice(-maxEntries) }); } catch (_) {}
            writeNext();
          });
        } catch (_) { writeNext(); }
      };
      writeNext();
    }

    function clear() {
      active.clear();
      setCurrent();
    }

    function fail(id, detail) {
      finish(id, false, detail);
    }

    return { start, finish, fail, clear };
  }

  root.SleeperBackgroundActivity = { createActivityTracker, createActionRecorder };
})(typeof globalThis !== "undefined" ? globalThis : this);
