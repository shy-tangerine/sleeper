/* Chromium-only dynamic code adapter.
 *
 * Firefox release packages omit this file. Keeping dynamic evaluation in one
 * isolated artifact makes the AMO submission self-contained and statically
 * reviewable while preserving Chromium's advanced local automation escape
 * hatch.
 * IMPORTANT: This is intentionally dangerous. It is only safe for trusted
 * local callers that own all command inputs. If you do not fully trust callers,
 * disable by removing this module from the Chromium build.
 */

var SleeperDynamicCode = (function () {
  "use strict";

  function ensureDynamicCodeEnabled() {
    if (typeof window !== "undefined" && window.__sleeperDisableDynamicCode) {
      throw new Error("dynamic code execution disabled");
    }
  }

  function exec(args) {
    ensureDynamicCodeEnabled();
    const code = String(args && args.code || "").trim();
    if (code.length === 0) return null;
    if (/(^|[;\s}])\s*await\b/.test(code)) {
      // Chromium-only, explicitly requested local automation.
      // eslint-disable-next-line no-new-func
      const fn = new Function("args", "return (async () => { " + code + " })()");
      return fn(args);
    }
    // eslint-disable-next-line no-new-func
    const fn = new Function("code", "return eval(code)");
    try {
      return fn(code);
    } catch (error) {
      // eval() cannot parse a top-level `return` (e.g. the documented
      // `sleeper exec 'return document.title'` usage) - retry the same code
      // as a function body so top-level returns work. Genuinely malformed
      // code re-throws its own SyntaxError from the second compile.
      if (!(error instanceof SyntaxError)) throw error;
      // eslint-disable-next-line no-new-func
      return new Function("args", code)(args);
    }
  }

  function createPredicate(predicate) {
    ensureDynamicCodeEnabled();
    // Chromium-only, explicitly requested local automation.
    // eslint-disable-next-line no-new-func
    const candidate = new Function("return (" + predicate + ")")();
    if (typeof candidate === "function") return candidate;
    // eslint-disable-next-line no-new-func
    return new Function("return (" + predicate + ")");
  }

  return { exec, createPredicate };
})();
