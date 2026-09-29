// Sleeper - content script bridge
// Runs in the isolated content-script world. sleeper.js is loaded FIRST in
// the same world (manifest js order), so its top-level `const handlers` is
// visible here as a global — no eval, no fetch, no page-world injection.
// (Page CSP blocks script tags; content-script sandboxes block eval/new
// Function; sharing a bundled scope avoids both.)
//
// Flow: daemon --WS--> background --tabs.sendMessage--> here -> run handler
// against the real DOM -> sendResponse back.
//
// Stealth: handlers live in this isolated world, invisible to page JS.
//
// This file runs at document_start so the page-world console hook installs
// before page scripts run, letting `console` capture output emitted during page
// load. Native alert/confirm/prompt stay untouched until a dialog command
// explicitly requests automation.

if (typeof chrome === "undefined" && typeof browser !== "undefined") {
  globalThis.chrome = browser;
}

SleeperTailscaleSetup.offerFromPage(chrome, location);

(function () {
  // handlers comes from sleeper.js (same isolated world, loaded first).
  // If missing, fall back to window.__sleeper_handlers_v2 for safety.
  function getHandlers() {
    if (typeof handlers !== "undefined" && handlers) return handlers;
    return null;
  }

  // --- Always-on page-world console hook ------------------------------------
  // Runs in the PAGE world (appended <script>, subject to page CSP) and relays
  // captured output / ready signals back via postMessage -> isolated-world
  // relay below -> chrome.runtime.sendMessage -> background ring buffer.
  // The dialog hook is deliberately injected by the background `dialog`
  // command only; idle browsing must retain native dialog behavior.
  const PAGE_HOOK_SOURCE = `(function(){
    // console capture (idempotent)
    if (!window.__sleeperConsoleHooked) {
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
    }
  })();`;

  function installPageWorldHooks() {
    // Append the page-world hook <script>. If the page CSP blocks inline
    // scripts it simply won't execute (no ready signal) — we report honestly.
    try {
      var s = document.createElement("script");
      s.textContent = PAGE_HOOK_SOURCE;
      (document.head || document.documentElement).appendChild(s);
    } catch (e) { /* no DOM/CSP — hook just won't install */ }
    // Isolated-world relay: forward __sleeper page-world postMessages to the
    // background ring buffer / ready state.
    if (!window.__sleeperRelay) {
      window.__sleeperRelay = true;
      window.addEventListener("message", function (e) {
        try {
          var d = e.data;
          if (d && d.__sleeper) {
            chrome.runtime.sendMessage({
              __sleeper: d.__sleeper,
              level: d.level,
              text: d.text,
              ts: d.ts,
            });
          }
        } catch (err) {}
      });
    }
  }

  // document_start => install before page scripts run so `console` captures
  // output from the very start of the load.
  installPageWorldHooks();

  // Report in on load so the background registry marks this tab `connected`
  // immediately (no wait for a command round-trip). Background's
  // runtime.onMessage listener flips the flag on any message carrying sender.tab.
  try {
    chrome.runtime.sendMessage({ type: "sleeper-hello", url: location.href });
  } catch (e) { /* background not ready; connected flips on first command */ }

  // Execute a daemon-command against the handlers map and send the response.
  // Returns true (async) if a handler ran, false if the command was unknown.
  function runHandler(handlersMap, request, sendResponse) {
    // Accept the CLI's snake_case aliases (click_text, wait_text, ...) by
    // matching camelCase handlers case- and separator-insensitively. The
    // daemon passes commands through verbatim, so "click_text" used to fail
    // with "unknown command" even though the CLI documents it.
    let handler = handlersMap[request.cmd];
    if (!handler) {
      const wanted = String(request.cmd || "").toLowerCase().replace(/[_-]/g, "");
      for (const name of Object.keys(handlersMap)) {
        if (name.toLowerCase() === wanted) { handler = handlersMap[name]; break; }
      }
    }
    if (!handler) {
      sendResponse({ ok: false, error: "unknown command: " + request.cmd });
      return false;
    }
    Promise.resolve()
      .then(() => handler(request.args || {}))
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message || error) }));
    return true; // async
  }

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request && request.type === "sleeper-activity-clear") {
      if (typeof SleeperActivity !== "undefined") SleeperActivity.clear();
      sendResponse({ ok: true });
      return false;
    }
    if (request && request.type === "daemon-command") {
      const h = getHandlers();
      if (!h) {
        // Race at injection: sleeper.js may not have defined `handlers` yet.
        // Retry once after ~150ms before giving up.
        setTimeout(() => {
          const h2 = getHandlers();
          if (!h2) {
            return sendResponse({ ok: false, error: "sleeper handlers not loaded" });
          }
          runHandler(h2, request, sendResponse);
        }, 150);
        return true; // keep the channel open for the delayed response
      }
      return runHandler(h, request, sendResponse);
    }
    return false;
  });
})();
