// Best-effort page-world console capture and JavaScript-dialog hooks.
(function (root) {
  "use strict";

  function createPageHooks(chromeApi) {
    // ---------------------------------------------------------------------------
    // Page-world hooking (console capture + JS-dialog handling)
    //
    // HONESTY CONSTRAINT — Firefox MV2 has NO API to read a page's console or to
    // programmatically dismiss native alert/confirm/prompt dialogs:
    //   * chromeApi.debugger (the DevTools Protocol) is CHROME-ONLY and cannot be
    //     added to a Firefox extension. There is no Firefox equivalent exposed to
    //     extensions.
    //   * Therefore the only lever we have is to run code IN the page world and
    //     have it relay data back to us. This is best-effort and has real limits:
    //       - A page's strict Content-Security-Policy can block our injected
    //         <script> (inline-script CSP), in which case the hook simply doesn't
    //         install and we report that honestly — we NEVER fabricate entries.
    //       - Console messages emitted BEFORE the hook installs are not captured.
    //       - Native dialogs shown BEFORE the hook installs cannot be dismissed.
    //
    // Injection model:
    //   background --tabs.executeScript--> isolated world (CSP-exempt)
    //     --append <script> element--> page world (subject to page CSP)
    //     --window.postMessage--> isolated-world relay
    //     --chromeApi.runtime.sendMessage--> background ring buffer / ready state
    // The <script> append is how page-world execution happens in MV2 (executing a
    // code string with executeScript alone runs in the isolated world, which does
    // not see the page's own window.console/alert/etc).
    // ---------------------------------------------------------------------------

    const CONSOLE_LOG = new Map(); // tabId -> [{level, text, ts}]
    const CONSOLE_MAX = 500;
    const HOOK_READY = new Map();  // tabId -> { console?: bool, dialog?: bool }

    function pushConsole(tabId, entry) {
      if (tabId === undefined || tabId < 0) return;
      let arr = CONSOLE_LOG.get(tabId);
      if (!arr) { arr = []; CONSOLE_LOG.set(tabId, arr); }
      arr.push(entry);
      if (arr.length > CONSOLE_MAX) arr.splice(0, arr.length - CONSOLE_MAX);
    }

    function setHookReady(tabId, kind, ok) {
      if (tabId === undefined || tabId < 0) return;
      let h = HOOK_READY.get(tabId);
      if (!h) { h = {}; HOOK_READY.set(tabId, h); }
      h[kind] = !!ok;
    }

    function installConsoleHookMain() {
      if (window.__sleeperConsoleHooked) return true;
      window.__sleeperConsoleHooked = true;
      var originals = { log: console.log, info: console.info, warn: console.warn, error: console.error };
      ["log", "info", "warn", "error"].forEach(function (level) {
        var original = originals[level];
        console[level] = function () {
          var text = "";
          try {
            var parts = [];
            for (var i = 0; i < arguments.length; i++) {
              var value = arguments[i];
              if (typeof value === "string") parts.push(value);
              else if (value && value.stack) parts.push(String(value));
              else { try { parts.push(JSON.stringify(value)); } catch (e) { parts.push(String(value)); } }
            }
            text = parts.join(" ");
          } catch (error) { text = String(error); }
          window.postMessage({ __sleeper: "console", level: level, text: text, ts: Date.now() }, "*");
          return original.apply(console, arguments);
        };
      });
      window.postMessage({ __sleeper: "console-ready" }, "*");
      return true;
    }

    function installDialogHookMain(value) {
      window.__sleeperDialogHooked = true;
      window.alert = function () { return undefined; };
      window.confirm = function () { return true; };
      window.prompt = function (_message, defaultText) {
        if (value !== null && value !== undefined) return String(value);
        if (defaultText !== undefined && defaultText !== null) return String(defaultText);
        return "";
      };
      window.postMessage({ __sleeper: "dialog-ready" }, "*");
      return true;
    }

    // Page-world console hook. Wrapped so re-injection is idempotent. Each
    // captured call is posted to window so the isolated-world relay can forward it.
    const CONSOLE_HOOK_PAGE = `(function(){
      if (window.__sleeperConsoleHooked) return;
      window.__sleeperConsoleHooked = true;
      var o = { log: console.log, info: console.info, warn: console.warn, error: console.error };
      var levels = ["log","info","warn","error"];
      for (var i = 0; i < levels.length; i++) {
        (function (lv) {
          var orig = o[lv];
          console[lv] = function () {
            var text = "";
            try {
              var parts = [];
              for (var j = 0; j < arguments.length; j++) {
                var a = arguments[j];
                if (typeof a === "string") parts.push(a);
                else if (a && a.stack) parts.push(String(a));
                else { try { parts.push(JSON.stringify(a)); } catch (e) { parts.push(String(a)); } }
              }
              text = parts.join(" ");
            } catch (e) { text = String(e); }
            window.postMessage({ __sleeper: "console", level: lv, text: text, ts: Date.now() }, "*");
            return orig.apply(console, arguments);
          };
        })(levels[i]);
      }
      window.postMessage({ __sleeper: "console-ready" }, "*");
    })();`;

    // Page-world JS-dialog hook: auto-accept/dismiss alert/confirm/prompt so a
    // page that blocks on a dialog doesn't hang. confirm -> true, prompt -> the
    // caller-provided value (or the page's defaultText, else ""), alert -> void.
    function dialogHookSource(value) {
      const pv = value != null ? JSON.stringify(String(value)) : "null";
      return `(function(){
      if (window.__sleeperDialogHooked) return;
      window.__sleeperDialogHooked = true;
      var pv = ${pv};
      window.alert = function (m) { return undefined; };
      window.confirm = function (m) { return true; };
      window.prompt = function (m, def) {
        if (pv !== null) return pv;
        if (def !== undefined && def !== null) return String(def);
        return "";
      };
      window.postMessage({ __sleeper: "dialog-ready" }, "*");
    })();`;
    }

    // injectPageWorld: run `pageHookSource` in the page world of `tabId`.
    //  1. executes a code string in the isolated world (CSP-exempt);
    //  2. that code appends a <script> element whose body runs in the page world;
    //  3. it also installs a one-time isolated-world relay that forwards any
    //     `__sleeper` postMessage (console captures, ready signals) to the
    //     background via chromeApi.runtime.sendMessage;
    //  4. the page hook posts its ready message through the relay; absence of that
    //     message within the bounded wait is reported as a possible CSP block.
    // Returns { ok, injected } / { ok:false, error }.
    function executeIsolated(tabId, func, args) {
      if (chromeApi.scripting && typeof chromeApi.scripting.executeScript === "function") {
        return Promise.resolve(chromeApi.scripting.executeScript({ target: { tabId }, func, args }));
      }
      return new Promise((resolve, reject) => {
        try {
          const values = (args || []).map((arg) => JSON.stringify(arg)).join(",");
          chromeApi.tabs.executeScript(tabId, { runAt: "document_start", allFrames: false, code: `(${func.toString()})(${values})` }, () => {
            if (chromeApi.runtime.lastError) reject(new Error(String(chromeApi.runtime.lastError.message)));
            else resolve();
          });
        } catch (error) { reject(error); }
      });
    }

    function injectPageWorld(tabId, pageHookSource, kind, mainInstaller, mainArgs) {
      const installRelay = function () {
        if (!window.__sleeperRelay) {
          window.__sleeperRelay = true;
          window.addEventListener("message", function (e) {
            try {
              var d = e.data;
              if (d && d.__sleeper) chrome.runtime.sendMessage({ __sleeper: d.__sleeper, level: d.level, text: d.text, ts: d.ts });
            } catch (err) {}
          });
        }
      };
      if (chromeApi.scripting && typeof chromeApi.scripting.executeScript === "function") {
        return executeIsolated(tabId, installRelay, [])
          .then(() => chromeApi.scripting.executeScript({
            target: { tabId },
            world: "MAIN",
            func: mainInstaller,
            args: mainArgs || [],
          }))
          .then((results) => {
            const installed = !!(results && results[0] && results[0].result);
            setHookReady(tabId, kind, installed);
            return { ok: true, injected: installed };
          })
          .catch((error) => ({ ok: false, error: String((error && error.message) || error) }));
      }
      const installLegacy = function (source) {
        if (!window.__sleeperRelay) {
          window.__sleeperRelay = true;
          window.addEventListener("message", function (e) {
            try {
              var d = e.data;
              if (d && d.__sleeper) chrome.runtime.sendMessage({ __sleeper: d.__sleeper, level: d.level, text: d.text, ts: d.ts });
            } catch (err) {}
          });
        }
        try {
          var s = document.createElement("script");
          s.textContent = source;
          (document.head || document.documentElement).appendChild(s);
        } catch (e) {}
      };
      return executeIsolated(tabId, installLegacy, [pageHookSource])
        .then(() => ({ ok: true, injected: true }))
        .catch((error) => ({ ok: false, error: String((error && error.message) || error) }));
    }

    // Wait (up to `ms`) for the background to learn whether the hook for `kind`
    // installed on `tabId`. True => installed; false => known CSP-blocked; if the
    // report never arrives (tab closed etc.) we fall back to the buffer state.
    function waitForHookReady(tabId, kind, ms) {
      return new Promise((resolve) => {
        const start = Date.now();
        const tick = () => {
          const h = HOOK_READY.get(tabId);
          const val = h && h[kind];
          if (val === true) return resolve(true);
          if (val === false) return resolve(false);
          if (Date.now() - start >= ms) return resolve(!!val);
          setTimeout(tick, 25);
        };
        tick();
      });
    }

    // `console` command — return the last N captured page-console entries.
    async function handleConsole(msg, resolveTabId, sendResult, sendError) {
      const args = msg.args || {};
      let tabId;
      try { tabId = resolveTabId(args.tab); }
      catch (e) { sendError(msg.id, String((e && e.message) || e)); return; }
      const lines = args.lines || args.limit;
      const limit = Number(lines) > 0 ? Number(lines) : 50;
      const inj = await injectPageWorld(tabId, CONSOLE_HOOK_PAGE, "console", installConsoleHookMain, []);
      if (!inj.ok) {
        sendResult(msg.id, { entries: [], note: "page-world console hook could not be installed: " + inj.error });
        return;
      }
      const ready = await waitForHookReady(tabId, "console", 250);
      const out = (CONSOLE_LOG.get(tabId) || []).slice(-limit);
      if (!ready) {
        // Honest CSP/unreadable signal — never invent entries.
        sendResult(msg.id, {
          entries: [],
          note: chromeApi.debugger
            ? "page-world console hook blocked by CSP (or page not loaded)"
            : "page-world console hook blocked by CSP (or page not loaded) — page console is not readable in Firefox MV2 (no chromeApi.debugger)",
        });
      } else {
        sendResult(msg.id, { entries: out });
      }
    }

    // `dialog` command — install the auto-accept/dismiss hook in the page world.
    async function handleDialog(msg, resolveTabId, sendResult, sendError) {
      const args = msg.args || {};
      let tabId;
      try { tabId = resolveTabId(args.tab); }
      catch (e) { sendError(msg.id, String((e && e.message) || e)); return; }
      const value = args.value != null ? String(args.value) : null;
      // A prior explicit dialog command may already have set
      // __sleeperDialogHooked, so reset the guard before applying a new value.
      try {
        if (chromeApi.scripting && typeof chromeApi.scripting.executeScript === "function") {
          await chromeApi.scripting.executeScript({ target: { tabId }, world: "MAIN", func: () => { try { window.__sleeperDialogHooked = false; } catch (_) {} } });
        } else await new Promise((resolve) => chromeApi.tabs.executeScript(tabId, {
          runAt: "document_start",
          code: "try { window.__sleeperDialogHooked = false; } catch (e) {}",
        }, () => resolve()));
      } catch (e) { /* tab gone / not scriptable; injection will surface it */ }
      const inj = await injectPageWorld(tabId, dialogHookSource(value), "dialog", installDialogHookMain, [value]);
      if (!inj.ok) { sendError(msg.id, inj.error); return; }
      const ready = await waitForHookReady(tabId, "dialog", 250);
      sendResult(msg.id, {
        hooked: true,
        ready,
        note: ready
          ? "page-world dialog hook installed (alert→void, confirm→true, prompt→" +
            (value != null ? "provided value" : "page defaultText else ''") +
            "). Native dialogs shown BEFORE the hook installed cannot be dismissed."
          : chromeApi.debugger
            ? "hook injection may be blocked by page CSP — native alert/confirm/prompt cannot be auto-dismissed."
            : "hook injection may be blocked by page CSP — native alert/confirm/prompt cannot be auto-dismissed in Firefox MV2 (no chromeApi.debugger).",
      });
    }

    async function handleWaitXhr(msg) {
      const args = msg.args || {};
      const urlSub = String(args.url_substring || "");
      if (!urlSub) { sendError(msg.id, "waitXhr: url_substring is required"); return; }
      let tabId = null;
      if (args.tab !== undefined && args.tab !== null && args.tab !== "") {
        try { tabId = resolveTabId(args.tab); }
        catch (e) { sendError(msg.id, String((e && e.message) || e)); return; }
      }
      const method = args.method ? String(args.method).toUpperCase() : null;
      const timeout = Number(args.timeout_ms) > 0 ? Number(args.timeout_ms) : 15000;
      const res = await waitXhrOnce({ urlSub, method, tabId, timeout });
      sendResult(msg.id, res);
    }

    function clear(tabId) {
      CONSOLE_LOG.delete(tabId);
      HOOK_READY.delete(tabId);
    }

    function acceptRuntimeMessage(tabId, request) {
      if (request && request.__sleeper === "console") {
        pushConsole(tabId, {
          level: String(request.level || "log"),
          text: String(request.text != null ? request.text : ""),
          ts: Number(request.ts) || Date.now(),
        });
      } else if (request && request.__sleeper === "console-ready") {
        setHookReady(tabId, "console", true);
      } else if (request && request.__sleeper === "dialog-ready") {
        setHookReady(tabId, "dialog", true);
      } else if (request && request.__sleeper === "hook-result") {
        setHookReady(tabId, request.kind || "console", !!request.ok);
      }
    }

    return { handleConsole, handleDialog, clear, acceptRuntimeMessage };
  }

  root.SleeperBackgroundPageHooks = { createPageHooks };
})(typeof globalThis !== "undefined" ? globalThis : this);
