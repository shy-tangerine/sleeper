// Screenshot capture coordinator shared by Firefox MV2 and Chromium MV3.
// It owns page cleanup and browser-specific capture differences; callers only
// receive a PNG data URL or an Error.
(function (root) {
  "use strict";

  const MAX_SCREENSHOT_DATA_URL_CHARS = 3_932_160;
  const ANNOTATION_LAYER_ID = "__sleeper_annotation_layer";
  const PAGE_METRICS = "({width:Math.max(document.documentElement.scrollWidth,document.body?document.body.scrollWidth:0),height:Math.max(document.documentElement.scrollHeight,document.body?document.body.scrollHeight:0),viewport:window.innerHeight,y:window.scrollY})";

  function installAnnotations() {
    if (document.getElementById("__sleeper_annotation_layer")) return;
    const layer = document.createElement("div");
    layer.id = "__sleeper_annotation_layer";
    layer.style.cssText = "position:absolute;inset:0;z-index:2147483647;pointer-events:none";
    document.querySelectorAll("[data-sleeper-ref]").forEach((element) => {
      const rect = element.getBoundingClientRect();
      const tag = document.createElement("span");
      tag.textContent = `@${element.getAttribute("data-sleeper-ref")}`;
      tag.style.cssText = `position:fixed;left:${Math.max(0, rect.left)}px;top:${Math.max(0, rect.top)}px;background:#ffeb3b;color:#111;font:11px monospace;padding:1px 2px;border:1px solid #111`;
      layer.appendChild(tag);
    });
    document.documentElement.appendChild(layer);
  }

  function removeAnnotations() {
    document.getElementById("__sleeper_annotation_layer")?.remove();
  }

  function invokePageFunction(browserApi, tabId, pageFunction) {
    if (browserApi.scripting && browserApi.scripting.executeScript) {
      return browserApi.scripting.executeScript({ target: { tabId }, func: pageFunction });
    }
    if (browserApi.tabs && browserApi.tabs.executeScript) {
      return Promise.resolve(browserApi.tabs.executeScript(tabId, { code: `(${pageFunction.toString()})()` }));
    }
    return Promise.resolve();
  }

  function dataUrlFromDebugger(browserApi, tabId, args) {
    return new Promise((resolve, reject) => {
      const target = { tabId };
      let finished = false;
      const finish = (error, value) => {
        if (finished) return;
        finished = true;
        clearTimeout(timeout);
        try { browserApi.debugger.detach(target, () => {}); } catch (_) {}
        error ? reject(error) : resolve(value);
      };
      const timeout = setTimeout(() => finish(new Error("screenshot timed out")), 10000);
      browserApi.debugger.attach(target, "1.3", () => {
        if (finished) return;
        if (browserApi.runtime.lastError) return finish(new Error(browserApi.runtime.lastError.message));
        const metrics = {};
        if (Number(args.width) > 0) metrics.width = Number(args.width);
        if (Number(args.height) > 0 && !args.full_page) metrics.height = Number(args.height);
        const capture = () => {
          if (finished) return;
          browserApi.debugger.sendCommand(target, "Page.captureScreenshot", {
          format: "png", fromSurface: true, captureBeyondViewport: !!args.full_page,
          }, (result) => {
          if (finished) return;
          const error = browserApi.runtime.lastError;
          if (metrics.width || metrics.height) browserApi.debugger.sendCommand(target, "Emulation.clearDeviceMetricsOverride", {}, () => {});
          if (error) finish(new Error(error.message));
          else if (!result || !result.data) finish(new Error("Page.captureScreenshot returned no image"));
          else finish(null, `data:image/png;base64,${result.data}`);
          });
        };
        if (metrics.width || metrics.height) {
          browserApi.debugger.sendCommand(target, "Emulation.setDeviceMetricsOverride", {
            width: metrics.width || 800, height: metrics.height || 600, deviceScaleFactor: 1, mobile: false,
          }, capture);
        } else capture();
      });
    });
  }

  function promiseCaptureTab(browserApi, tabId) {
    if (typeof browserApi.tabs.captureTab === "function") return () => Promise.resolve(browserApi.tabs.captureTab(tabId, { format: "png" }));
    return null;
  }

async function snapshotWindowState(browserApi, tab) {
  const activeTabs = await Promise.resolve(browserApi.tabs.query({ active: true, windowId: tab.windowId }));
  let focusedWindowId = null;
  if (browserApi.windows && typeof browserApi.windows.getAll === "function") {
    try {
      const windows = await Promise.resolve(browserApi.windows.getAll());
      const focused = windows.find((window) => window.focused);
      focusedWindowId = focused ? focused.id : null;
    } catch (_) {}
  } else if (browserApi.windows && typeof browserApi.windows.get === "function") {
    try {
      const window = await Promise.resolve(browserApi.windows.get(tab.windowId));
      focusedWindowId = window.focused ? tab.windowId : null;
    } catch (_) {}
  }
  return { activeTabId: activeTabs && activeTabs[0] && activeTabs[0].id, focusedWindowId };
}

  async function restoreWindowState(browserApi, tab, state) {
    if (state && state.activeTabId != null) {
      try { await withTimeout(() => browserApi.tabs.update(state.activeTabId, { active: true }), 4000, "tab restore timed out"); } catch (_) {}
    }
    if (browserApi.windows && typeof browserApi.windows.update === "function" && state) {
      try {
        // Leave an originally unfocused browser alone. Calling focused:false
        // blurs the user's current application and is itself a focus side
        // effect; only restore a window that was already focused.
        if (state.focusedWindowId != null) await withTimeout(() => browserApi.windows.update(state.focusedWindowId, { focused: true }), 4000, "window restore timed out");
      } catch (_) {}
  }
}

  function captureVisibleTab(browserApi, windowId) {
    if (typeof browserApi.tabs.captureVisibleTab !== "function") return Promise.reject(new Error("Firefox does not expose a screenshot capture API"));
    return Promise.resolve(browserApi.tabs.captureVisibleTab(windowId, { format: "png" }));
  }

  async function captureVisibleForTab(browserApi, tabId) {
    const tab = await withTimeout(() => browserApi.tabs.get(tabId), 8000, "tab lookup timed out");
    const state = await withTimeout(() => snapshotWindowState(browserApi, tab), 8000, "window state lookup timed out");
    try {
      await withTimeout(() => browserApi.tabs.update(tabId, { active: true }), 8000, "tab activation timed out");
      if (browserApi.windows && typeof browserApi.windows.update === "function") {
        await withTimeout(() => browserApi.windows.update(tab.windowId, { focused: true }), 8000, "window focus timed out");
      }
      return await withTimeout(() => captureVisibleTab(browserApi, tab.windowId), 8000, "capture timed out");
    } finally {
      await restoreWindowState(browserApi, tab, state);
    }
  }

  function withTimeout(operation, timeoutMs, message) {
    let timer;
    let task;
    try { task = Promise.resolve(typeof operation === "function" ? operation() : operation); }
    catch (error) { task = Promise.reject(error); }
    return Promise.race([
      task,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), timeoutMs); }),
    ]).finally(() => clearTimeout(timer));
  }

  async function captureFirefoxFullPage(browserApi, tabId, args) {
    const deadlineAt = Date.now() + 30000;
    const bounded = (operation, message) => withTimeout(
      operation,
      Math.max(1, Math.min(4000, deadlineAt - Date.now())),
      message
    );
    const tab = await bounded(() => browserApi.tabs.get(tabId), "tab lookup timed out");
    const captureTab = promiseCaptureTab(browserApi, tabId);
    const requiresVisibleTab = !captureTab;
    const state = requiresVisibleTab ? await bounded(() => snapshotWindowState(browserApi, tab), "window state lookup timed out") : null;
    const execute = (code) => bounded(
      () => Promise.resolve(browserApi.tabs.executeScript(tabId, { code })).then((result) => Array.isArray(result) ? result[0] : result),
      "page execution timed out"
    );
    let annotationsInstalled = false;
    let originalY = 0;
    const restorePage = async (y) => {
      try { await execute(`window.scrollTo(0, ${Number(y) || 0})`); } catch (_) {}
      if (annotationsInstalled) {
        try { await bounded(() => invokePageFunction(browserApi, tabId, removeAnnotations), "annotation cleanup timed out"); } catch (_) {}
      }
      if (requiresVisibleTab) await restoreWindowState(browserApi, tab, state);
    };
    try {
      if (requiresVisibleTab) {
        await bounded(() => browserApi.tabs.update(tabId, { active: true }), "tab activation timed out");
        if (browserApi.windows && typeof browserApi.windows.update === "function") await bounded(() => browserApi.windows.update(tab.windowId, { focused: true }), "window focus timed out");
      }
      if (args.annotate) { await bounded(() => invokePageFunction(browserApi, tabId, installAnnotations), "annotation install timed out"); annotationsInstalled = true; }
      const metrics = await execute(PAGE_METRICS);
      originalY = Number(metrics && metrics.y) || 0;
      const width = Math.max(1, Math.min(32767, Number(metrics && metrics.width) || 1));
      const height = Math.max(1, Math.min(32767, Number(metrics && metrics.height) || 1));
      const viewport = Math.max(1, Number(metrics && metrics.viewport) || 600);
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext("2d");
      for (let y = 0; y < height; y += viewport) {
        await execute(`window.scrollTo(0, ${y}); "ok"`);
        await bounded(() => new Promise((resolve) => setTimeout(resolve, 100)), "capture delay timed out");
        const dataUrl = await bounded(() => captureTab ? captureTab() : captureVisibleTab(browserApi, tab.windowId), "capture timeout");
        await bounded(() => new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => { context.drawImage(image, 0, y); resolve(); };
          image.onerror = () => reject(new Error("captured image could not be decoded"));
          image.src = dataUrl;
        }), "captured image decode timed out");
      }
      return canvas.toDataURL("image/png");
    } finally {
      await restorePage(originalY);
    }
  }

  async function capture(browserApi, tabId, args) {
    const options = args || {};
    // Activity cues are transient UI and must never become screenshot pixels.
    if (browserApi.tabs && typeof browserApi.tabs.sendMessage === "function") {
      try { await Promise.resolve(browserApi.tabs.sendMessage(tabId, { type: "sleeper-activity-clear" })); } catch (_) {}
    }
    if (browserApi.debugger && (options.full_page || options.annotate || options.focus_mode === "needed")) {
      if (options.annotate) await invokePageFunction(browserApi, tabId, installAnnotations);
      try { return await dataUrlFromDebugger(browserApi, tabId, options); }
      finally { if (options.annotate) await invokePageFunction(browserApi, tabId, removeAnnotations).catch(() => {}); }
    }
    if (options.full_page && browserApi.tabs && (browserApi.tabs.captureTab || browserApi.tabs.captureVisibleTab)) {
      return captureFirefoxFullPage(browserApi, tabId, options);
    }
    if (typeof browserApi.tabs.captureTab === "function") {
      return withTimeout(() => browserApi.tabs.captureTab(tabId, { format: "png" }), 8000, "capture timed out");
    }
    return captureVisibleForTab(browserApi, tabId);
  }

  function sendResult(sendSuccess, sendFailure, id, dataUrl) {
    if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/png;base64,")) sendFailure(id, "screenshot capture returned an invalid PNG artifact");
    else if (dataUrl.length > MAX_SCREENSHOT_DATA_URL_CHARS) sendFailure(id, `screenshot exceeds ${MAX_SCREENSHOT_DATA_URL_CHARS} byte transport limit`);
    else sendSuccess(id, { dataUrl });
  }

  const api = { MAX_SCREENSHOT_DATA_URL_CHARS, capture, sendResult, installAnnotations, removeAnnotations };
  if (typeof module !== "undefined") module.exports = api;
  root.SleeperScreenshot = api;
})(globalThis);
