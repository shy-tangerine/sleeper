// Chromium-only page evaluation for MV3 commands that cannot use eval in a
// content script. Firefox does not load this module.
(function (root) {
  "use strict";

  function expressionFor(code, args) {
    const source = String(code || "").trim();
    const encodedArgs = JSON.stringify(args || {});
    const encodedCode = JSON.stringify(source);
    if (/(^|[;\s}])\s*await\b/.test(source)) return `(async function(args){ ${source}\n })(${encodedArgs})`;
    return `(function(args, code){ try { return eval(code); } catch (error) { if (!(error instanceof SyntaxError)) throw error; return (function(){ ${source}\n }).call(this); } })(${encodedArgs}, ${encodedCode})`;
  }

  function predicateExpression(predicate) {
    return `(function(){ var value = (${String(predicate || "")}); return typeof value === "function" ? value() : value; })()`;
  }

  function evaluate(browserApi, tabId, expression, timeoutMs) {
    return new Promise((resolve, reject) => {
      if (!browserApi.debugger || typeof browserApi.debugger.attach !== "function") {
        reject(new Error("Chromium debugger evaluation unavailable"));
        return;
      }
      const target = { tabId };
      let settled = false;
      let timer;
      const finish = (error, value) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        const done = () => error ? reject(error) : resolve(value);
        try { browserApi.debugger.detach(target, done); } catch (_) { done(); }
      };
      if (timeoutMs > 0) timer = setTimeout(() => finish(new Error("Chromium debugger evaluation timed out")), timeoutMs);
      try {
        browserApi.debugger.attach(target, "1.3", () => {
          if (browserApi.runtime && browserApi.runtime.lastError) { finish(new Error(String(browserApi.runtime.lastError.message))); return; }
          browserApi.debugger.sendCommand(target, "Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, (result) => {
            if (browserApi.runtime && browserApi.runtime.lastError) { finish(new Error(String(browserApi.runtime.lastError.message))); return; }
            const exception = result && result.exceptionDetails;
            if (exception) { finish(new Error(String(exception.text || (result.result && result.result.description) || "JavaScript evaluation failed"))); return; }
            finish(null, result && result.result ? result.result.value : undefined);
          });
        });
      } catch (error) { finish(error); }
    });
  }

  async function exec(browserApi, tabId, args) {
    return evaluate(browserApi, tabId, expressionFor(args && args.code, args), 10000);
  }

  async function waitUntil(browserApi, tabId, args) {
    const timeout = Number(args && (args.timeout_ms || args.timeout)) > 0 ? Number(args.timeout_ms || args.timeout) : 10000;
    const interval = Number(args && (args.interval_ms || args.interval)) > 0 ? Number(args.interval_ms || args.interval) : 100;
    const deadline = Date.now() + timeout;
    const expression = predicateExpression(args && args.predicate);
    while (true) {
      if (await evaluate(browserApi, tabId, expression, Math.min(10000, Math.max(1, deadline - Date.now())))) return { satisfied: true };
      if (Date.now() >= deadline) throw new Error("timeout waiting for predicate");
      await new Promise((resolve) => setTimeout(resolve, Math.min(interval, deadline - Date.now())));
    }
  }

  root.SleeperChromiumDebugger = { evaluate, exec, waitUntil, expressionFor, predicateExpression };
})(typeof globalThis !== "undefined" ? globalThis : this);
