/* Sleeper — page-world logic */

// ------------------------------------------------------------------
// CONFIG — nothing exposed to the page world, nothing on window
// ------------------------------------------------------------------

// Bridge interface provided by content.js
const bridge = {
  sendCommand: function(cmd, args) {
    return new Promise((resolve, reject) => {
      const id = typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : "bs-" + Date.now() + "-" + Math.random().toString(36).substr(2, 9);
      const message = {
        __bs_bridge: true,
        id: id,
        cmd: cmd,
        args: args || {}
      };

      // Listen for response
      const listener = (event) => {
        if (event.source !== window || event.origin !== window.location.origin) return;
        if (event.data && event.data.__bs_bridge && event.data.id === id) {
          window.removeEventListener('message', listener);
          if (event.data.ok) {
            resolve(event.data.result);
          } else {
            reject(new Error(event.data.error || 'Command failed'));
          }
        }
      };

      window.addEventListener('message', listener);
      window.postMessage(message, '*');
    });
  }
};

// ------------------------------------------------------------------
// STATE — nothing exposed to the page world, nothing on window
// ------------------------------------------------------------------

// ------------------------------------------------------------------
// React / controlled-input compatible value setter
// ------------------------------------------------------------------
  function setNativeValue(el, value) {
    const previous = String(el.value || "");
    const proto =
      el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : HTMLElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    // React tracks an input's last value separately from the DOM property.
    // Resetting that tracker to the prior value makes its delegated input
    // handler observe the native setter change instead of discarding it.
    try {
      if (el._valueTracker && typeof el._valueTracker.setValue === "function") {
        el._valueTracker.setValue(previous);
      }
    } catch (_) {}
    const view = el.ownerDocument && el.ownerDocument.defaultView;
    const InputEventCtor = view && view.InputEvent;
    const EventCtor = (view && view.Event) || Event;
    const inputEvent = typeof InputEventCtor === "function"
      ? new InputEventCtor("input", {
        bubbles: true,
        composed: true,
        data: String(value),
        inputType: String(value) ? "insertText" : "deleteContentBackward",
      })
      : new EventCtor("input", { bubbles: true, composed: true });
    el.dispatchEvent(inputEvent);
    el.dispatchEvent(new EventCtor("change", { bubbles: true, composed: true }));
}

function visible(el) {
  const r = el.getBoundingClientRect();
  return !!(r.width && r.height);
}

function qs(selector, root) {
  root = root || document;
  // open shadow roots: selector "a >> b" descends into shadow trees
  if (selector.includes(">>")) {
    const parts = selector.split(">>").map((s) => s.trim());
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const found = node.querySelector(parts[i]);
      if (!found) throw new Error("no element for shadow selector: " + selector);
      if (i === parts.length - 1) return found;
      node = found.shadowRoot || found;
    }
  }
  const els = qsa(selector, root);
  if (els.length === 0) throw new Error("no element for selector: " + selector);
  return els[0];
}

function qsa(selector, root) {
  root = root || document;
  if (typeof selector === "string" && /^@sleeper-\d+$/.test(selector)) {
    const ref = selector.slice(1);
    const el = root.querySelector(`[data-sleeper-ref="${ref}"]`);
    return el ? [el] : [];
  }
  // G3: text-based selectors (:has-text / :has). Plain selectors keep the
  // native querySelectorAll fast path — zero regression.
  if (hasTextToken(selector)) return resolveSelector(selector, root);
  return Array.from(root.querySelectorAll(selector)).filter((el) => !isActivityElement(el));
}

function isActivityElement(el) {
  return !!(el && el.getAttribute && el.getAttribute("data-sleeper-activity") === "true");
}

let nextSleeperRef = 1;
function ensureSleeperRef(el) {
  if (!el || !el.setAttribute) return null;
  let ref = el.getAttribute("data-sleeper-ref");
  if (!ref) {
    ref = `sleeper-${nextSleeperRef++}`;
    el.setAttribute("data-sleeper-ref", ref);
  }
  return `@${ref}`;
}

const semanticTarget = (args, command) => SleeperLocators.target(args, command, qs);
const optionalSemanticTarget = (args, command, fallback) => SleeperLocators.optionalTarget(args, command, qs, fallback);

// ------------------------------------------------------------------
// G3 — TEXT-BASED SELECTORS
// ------------------------------------------------------------------
// Supported subset (cheap, documented):
//   button:has-text("Next")        -> buttons whose innerText contains "Next"
//   :has-text("Sign Up")           -> any element whose innerText contains it
//   div:has("input[type=email]")   -> elements that contain a matching descendant
//   :has(":has-text('foo')")       -> nested :has-text inside :has (recursive)
//   comma-separated lists of the above
// Tokens are split off the base part; the base is queried with querySelectorAll
// and then filtered element-by-element by the predicate walk. `:has-text`/`:has`
// may appear at the end of an element (the common case, e.g. `button:has-text("x")`);
// tokens embedded mid-selector split the base around them (best-effort).

function hasTextToken(selector) {
  if (!selector || typeof selector !== "string") return false;
  if (selector.indexOf(":has-text") !== -1) return true;
  return /:has\s*\(/.test(selector);
}

// Finds the closing parenthesis of the pseudo-token that opens at `open`
// (index of "("), honoring quotes and nested parens. Returns the index just
// past the closing paren, or selector.length when unbalanced.
function endOfPseudoToken(selector, open) {
  let depth = 0;
  let quote = null;
  for (let k = open; k < selector.length; k++) {
    const c = selector[k];
    if (quote) {
      if (c === quote && selector[k - 1] !== "\\") quote = null;
    } else if (c === '"' || c === "'") {
      quote = c;
    } else if (c === "(") {
      depth++;
    } else if (c === ")") {
      depth--;
      if (depth === 0) return k + 1;
    }
  }
  return selector.length;
}

// Strips one level of surrounding quotes, e.g. :has-text("Next") -> Next,
// :has("input[type=email]") -> input[type=email], and nested
// :has(":has-text('foo')") -> :has-text('foo')
function stripSurroundingQuotes(inner) {
  if (inner.length < 2) return inner;
  const a = inner[0];
  const b = inner[inner.length - 1];
  if ((a === '"' && b === '"') || (a === "'" && b === "'")) return inner.slice(1, -1).trim();
  return inner;
}

// Matches a :has-text / :has pseudo-token starting at index i, returning
// { type, arg, end } where `end` is the index just past the closing paren,
// or null when no token starts here.
function matchPseudoToken(selector, i) {
  const m = selector.startsWith(":has-text", i) ? { name: ":has-text", type: "text" }
    : selector.startsWith(":has", i) ? { name: ":has", type: "has" } : null;
  if (!m) return null;
  let j = i + m.name.length;
  while (j < selector.length && /\s/.test(selector[j])) j++;
  if (selector[j] !== "(") return null;
  const end = endOfPseudoToken(selector, j);
  const arg = stripSurroundingQuotes(selector.slice(j + 1, end - 1).trim());
  return { type: m.type, arg, end };
}

// Splits one selector (no commas) into { base, tokens } where tokens are
// {type:"text"|"has", arg}. base is the selector with tokens removed (may be "").
function splitTextSelector(selector) {
  const base = [];
  const tokens = [];
  let last = 0;
  let i = 0;
  while (i < selector.length) {
    const token = matchPseudoToken(selector, i);
    if (!token) { i++; continue; }
    tokens.push({ type: token.type, arg: token.arg });
    base.push(selector.slice(last, i));
    last = token.end;
    i = token.end;
  }
  base.push(selector.slice(last));
  return { base: base.join("").trim(), tokens };
}

// Recursive resolver: returns the array of elements matching a selector that may
// contain :has-text / :has tokens. Handles comma lists and nested tokens.
function resolveSelector(selector, root) {
  root = root || document;
  if (!selector || typeof selector !== "string") return [];
  const out = [];
  const parts = selector.split(",").map((p) => p.trim()).filter(Boolean);
  for (const part of parts) {
    const { base, tokens } = splitTextSelector(part);
    const baseSel = base || "*";
    let nodes;
    try {
      nodes = Array.from(root.querySelectorAll(baseSel));
    } catch (e) {
      throw new Error("not a valid selector: " + part);
    }
    if (tokens.length === 0) {
      out.push.apply(out, nodes);
      continue;
    }
    const preds = tokens.map((tok) => {
      if (tok.type === "text") {
        const arg = tok.arg;
        return function (el) { return (el.innerText || "").indexOf(arg) !== -1; };
      }
      // :has — recursively resolve the argument against this element
      const arg = tok.arg;
      return function (el) {
        if (!el.querySelectorAll) return false;
        try { return resolveSelector(arg, el).length > 0; } catch (e) { return false; }
      };
    });
    for (const node of nodes) {
      if (preds.every(function (p) { return p(node); })) out.push(node);
    }
  }
  return out;
}

// Find elements by innerText (contains or exact). Prefers "minimal" matches:
// an element whose text also lives in a matching descendant is dropped, so we
// keep the deepest element (buttons, links, inputs) rather than its container.
// Non-rendered elements (script/style source, display:none subtrees) are
// excluded by default — matching raw <script> source text made wait_text
// "succeed" while the visible page never changed. Pass {includeHidden:true}
// to search hidden content deliberately.
function isRenderedElement(el) {
  for (let n = el; n; n = n.parentElement) {
    const tag = n.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || tag === "TEMPLATE") return false;
  }
  const cs = getComputedStyle(el);
  return cs.display !== "none" && cs.visibility !== "hidden";
}

function elementsByText(text, opts) {
  opts = opts || {};
  const want = String(text == null ? "" : text);
  const exact = !!opts.exact;
  const includeHidden = !!opts.includeHidden;
  if (!want) return [];
  const matches = [];
  const all = Array.from(document.querySelectorAll("body *")).filter((el) => !isActivityElement(el));
  for (const el of all) {
    const t = (el.innerText || "").trim();
    if (!t) continue;
    if (exact ? t === want : t.indexOf(want) !== -1) matches.push(el);
  }
  return matches.filter(function (el) {
    if (!includeHidden && !isRenderedElement(el)) return false;
    for (let j = 0; j < matches.length; j++) {
      const other = matches[j];
      if (other !== el && el.contains(other)) return false;
    }
    return true;
  });
}


function safeJson(value, depth) {
  depth = depth || 0;
  if (depth > 4) return "[deep]";
  if (value === null || value === undefined) return value;
  const t = typeof value;
  if (t === "string" || t === "number" || t === "boolean") return value;
  if (t === "function") return "[function]";
  if (t === "bigint") return value.toString();
  if (Array.isArray(value)) return value.map((v) => safeJson(v, depth + 1));
  if (value instanceof Element) {
    const r = value.getBoundingClientRect();
    return {
      tag: value.tagName.toLowerCase(),
      id: value.id || null,
      classes: typeof value.className === "string" ? value.className.split(/\s+/).filter(Boolean) : [],
      name: value.getAttribute("name") || null,
      type: value.type || null,
      text: (value.textContent || "").slice(0, 200),
      value: value.value !== undefined ? value.value : null,
      placeholder: value.getAttribute("placeholder") || null,
      href: value.getAttribute("href") || null,
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      visible: visible(value),
    };
  }
  if (t === "object") {
    try {
      const out = {};
      for (const k of Object.keys(value).slice(0, 20)) out[k] = safeJson(value[k], depth + 1);
      return out;
    } catch (e) {
      return "[unserializable]";
    }
  }
  return String(value);
}

// ------------------------------------------------------------------
// G6 — IFRAME / FRAME AWARENESS
// ------------------------------------------------------------------
// Walks window.frames (same-origin at least). Same-origin frames contribute
// a compact text/input outline; cross-origin frames are recorded as present
// but not introspectable (never throws on the SecurityError).
function collectFrames(args) {
  if (!args || !args.frames) return null;
  const frames = [];
  const MAX = 20;
  let count = 0;
  function visit(win) {
    if (count >= MAX) return;
    let list;
    try { list = win.frames; } catch (e) { return; }
    const n = list.length;
    for (let i = 0; i < n && count < MAX; i++) {
      count++;
      let fwin;
      try { fwin = list[i]; } catch (e) { continue; }
      let sameOrigin = false;
      try {
        const d = fwin.document; // throws SecurityError for cross-origin
        sameOrigin = !!d;
        void d;
      } catch (e) {
        sameOrigin = false;
      }
      if (sameOrigin && fwin.document) {
        const fdoc = fwin.document;
        const entry = {
          index: i,
          crossOrigin: false,
          url: (() => { try { return fwin.location.href; } catch (e) { return null; } })(),
          title: fdoc.title || null,
          textLength: (fdoc.body ? fdoc.body.innerText : "").length,
          headings: [],
          inputs: [],
        };
        const pushLimited = (list, limit) => list.slice(0, limit);
        pushLimited(Array.from(fdoc.querySelectorAll("h1,h2,h3")), 10)
          .forEach(function (h) { entry.headings.push((h.textContent || "").trim().slice(0, 120)); });
        pushLimited(Array.from(fdoc.querySelectorAll("input,textarea,select,button")), 20)
          .forEach(function (el) {
            entry.inputs.push({
              tag: el.tagName.toLowerCase(), id: el.id || null, name: el.name || null,
              type: el.type || null, placeholder: el.getAttribute("placeholder") || null,
              text: el.tagName === "BUTTON" ? el.textContent.trim().slice(0, 60) : null,
            });
          });
        frames.push(entry);
        visit(fwin); // nested frames
      } else {
        let url = null;
        try { url = fwin.location.href; } catch (e) { url = null; }
        frames.push({ index: i, url: url || null, crossOrigin: true, note: "cross-origin frame; cannot introspect without frame injection" });
      }
    }
  }
  try { visit(window); } catch (e) { /* ignore */ }
  return frames;
}

// Lightweight login-state heuristics for state()/snapshot().
function authHints() {
  const hints = { cookieLength: (document.cookie || "").length };
  const markers = {
    loginForm: !!document.querySelector("form[action*='login'], form[action*='signin'], input[type='password']"),
    loggedInUser: !!document.querySelector("[class*='user'], [class*='account'], [data-testid*='user']"),
  };
  const known = [
    "email", "password", "passwd", "otp", "code", "verification",
    "signin", "signup", "login", "register", "logout", "token", "session",
  ];
  let present = [];
  try {
    const text = (document.body ? document.body.innerText : "").toLowerCase();
    for (const kw of known) if (text.indexOf(kw) !== -1) present.push(kw);
  } catch (e) { /* ignore */ }
  hints.keywords = present.slice(0, 12);
  hints.loginForm = markers.loginForm;
  hints.userElement = markers.loggedInUser;
  return hints;
}

// Resolve a page condition as soon as a relevant browser signal fires. The
// timeout poll remains as a compatibility fallback for pages whose state lives
// outside the DOM, but DOM and same-document navigation changes do not have to
// wait for the next polling interval.
function waitForPageCondition(check, options) {
  options = options || {};
  const timeoutValue = Number(options.timeout);
  const intervalValue = Number(options.interval);
  const timeout = Number.isFinite(timeoutValue) ? Math.max(0, timeoutValue) : 10000;
  const interval = Number.isFinite(intervalValue) ? Math.max(25, intervalValue) : 150;
  const started = Date.now();

  return new Promise((resolve, reject) => {
    let settled = false;
    let pollTimer = null;
    let timeoutTimer = null;
    let observer = null;
    const eventTargets = [];

    const cleanup = () => {
      if (pollTimer !== null) clearTimeout(pollTimer);
      if (timeoutTimer !== null) clearTimeout(timeoutTimer);
      if (observer) observer.disconnect();
      eventTargets.forEach(([target, type]) => target.removeEventListener(type, inspect));
    };
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn(value);
    };
    const inspect = () => {
      if (settled) return;
      try {
        const result = check();
        if (result) finish(resolve, result);
      } catch (error) {
        finish(reject, error);
      }
    };
    const poll = () => {
      inspect();
      if (!settled) pollTimer = setTimeout(poll, interval);
    };

    if (typeof MutationObserver !== "undefined" && document.documentElement) {
      observer = new MutationObserver(inspect);
      observer.observe(document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
        characterData: true,
      });
    }
    ["hashchange", "popstate", "pageshow", "load", "DOMContentLoaded"].forEach((type) => {
      if (window && window.addEventListener) {
        window.addEventListener(type, inspect);
        eventTargets.push([window, type]);
      }
    });
    if (document && document.addEventListener) {
      document.addEventListener("readystatechange", inspect);
      eventTargets.push([document, "readystatechange"]);
    }

    inspect();
    if (settled) return;
    timeoutTimer = setTimeout(() => {
      // Inspect once at the boundary so a condition that changed alongside the
      // timer wins over a stale timeout.
      inspect();
      if (!settled) {
        const detail = typeof options.timeoutDetail === "function" ? options.timeoutDetail() : "";
        finish(reject, new Error(options.timeoutMessage + (detail ? "; " + detail : "")));
      }
    }, timeout);
    pollTimer = setTimeout(poll, interval);
  }).then((result) => {
    if (result && typeof result === "object" && result.waited_ms == null) {
      result.waited_ms = Date.now() - started;
    }
    return result;
  });
}

function waitOption(args, names, fallback) {
  for (const name of names) {
    const value = Number(args && args[name]);
    if (Number.isFinite(value)) return Math.max(0, value);
  }
  return fallback;
}

function formForEnter(el) {
  if (!el || el.disabled || el.readOnly) return null;
  const tag = String(el.tagName || "").toLowerCase();
  if (tag !== "input") return null;
  const type = String(el.type || "text").toLowerCase();
  if (["button", "submit", "reset", "checkbox", "radio", "file", "range", "color", "hidden"].includes(type)) return null;
  return el.form || (typeof el.closest === "function" ? el.closest("form") : null);
}

function submitFormSemantically(form) {
  let submitter = null;
  try {
    submitter = form.querySelector && form.querySelector('button[type="submit"]:not([disabled]), input[type="submit"]:not([disabled])');
  } catch (e) { /* malformed/custom form implementations have no submitter */ }
  if (typeof form.requestSubmit === "function") {
    try {
      if (submitter) form.requestSubmit(submitter);
      else form.requestSubmit();
      return "requestSubmit";
    } catch (e) {
      return null;
    }
  }
  if (submitter && typeof submitter.click === "function") {
    try {
      submitter.click();
      return "submitterClick";
    } catch (e) {
      return null;
    }
  }
  if (typeof form.submit === "function") {
    try {
      form.submit();
      return "submit";
    } catch (e) {
      return null;
    }
  }
  return null;
}

function structuredWaitUntil(args) {
  const condition = args && typeof args.condition === "object" ? args.condition : (args || {});
  const timeout = waitOption(args, ["timeout", "timeout_ms"], 10000);
  const interval = waitOption(args, ["interval", "interval_ms"], 150);
  const selector = typeof condition.selector === "string" ? condition.selector.trim() : "";
  const state = String(condition.state || "exists");
  const states = ["exists", "missing", "visible", "hidden", "enabled", "disabled", "checked", "unchecked"];
  const operators = ["eq", "gte", "lte", "gt", "lt", "contains"];

  if (!selector && condition.text == null) {
    return Promise.reject(new Error("waitUntil requires selector or text"));
  }
  if (!states.includes(state)) {
    return Promise.reject(new Error("waitUntil unsupported state: " + state));
  }

  function compare(actual, expected, operator) {
    if (!operators.includes(operator)) throw new Error("waitUntil unsupported operator: " + operator);
    if (operator === "eq") return actual === expected;
    if (operator === "gte") return actual >= expected;
    if (operator === "lte") return actual <= expected;
    if (operator === "gt") return actual > expected;
    if (operator === "lt") return actual < expected;
    return String(actual).includes(String(expected));
  }

  function inspect() {
    const elements = selector ? qsa(selector) : [document.documentElement];
    const count = elements.length;

    if (condition.count != null) {
      const expected = Number(condition.count);
      if (!Number.isFinite(expected)) throw new Error("waitUntil count must be a number");
      return { satisfied: compare(count, expected, String(condition.operator || "eq")), count };
    }

    if (condition.text != null) {
      const expected = String(condition.text);
      const matched = elements.some((el) => {
        const actual = String(el.innerText != null ? el.innerText : (el.textContent || "")).trim();
        return condition.exact === true ? actual === expected : actual.includes(expected);
      });
      return { satisfied: matched, count };
    }

    if (condition.attribute) {
      const attribute = String(condition.attribute);
      const operator = String(condition.operator || (condition.value == null ? "exists" : "eq"));
      const matched = elements.some((el) => {
        if (operator === "exists") return el.hasAttribute(attribute);
        const actual = el.getAttribute(attribute);
        return actual != null && compare(String(actual), String(condition.value), operator);
      });
      return { satisfied: matched, count };
    }

    if (condition.value != null) {
      const operator = String(condition.operator || "eq");
      const matched = elements.some((el) => compare(String(el.value == null ? "" : el.value), String(condition.value), operator));
      return { satisfied: matched, count };
    }

    let satisfied = false;
    if (state === "exists") satisfied = count > 0;
    else if (state === "missing") satisfied = count === 0;
    else if (state === "visible") satisfied = elements.some(visible);
    else if (state === "hidden") satisfied = count === 0 || elements.every((el) => !visible(el));
    else if (state === "enabled") satisfied = elements.some((el) => !el.disabled && el.getAttribute("aria-disabled") !== "true");
    else if (state === "disabled") satisfied = elements.some((el) => !!el.disabled || el.getAttribute("aria-disabled") === "true");
    else if (state === "checked") satisfied = elements.some((el) => !!el.checked || el.getAttribute("aria-checked") === "true");
    else if (state === "unchecked") satisfied = elements.some((el) => el.checked === false || el.getAttribute("aria-checked") === "false");
    return { satisfied, count };
  }

  return waitForPageCondition(() => {
    const result = inspect();
    return result.satisfied
      ? { satisfied: true, selector: selector || null, state, count: result.count }
      : null;
  }, {
    timeout,
    interval,
    timeoutMessage: "timeout waiting for structured condition",
    timeoutDetail: () => `url=${location.href} readyState=${document.readyState}`,
  });
}

// ------------------------------------------------------------------
// COMMANDS
// ------------------------------------------------------------------
const handlers = {
  state(args) {
    const out = {
      sleeper: (chrome.runtime.getManifest ? chrome.runtime.getManifest().version : "2.0.1"),
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      visible: document.visibilityState === "visible",
      hasFocus: document.hasFocus(),
      lang: document.documentElement.lang || null,
      textLength: (document.body ? document.body.innerText : "").length,
    };
    // G6: login-state heuristics + optional frames
    const hints = authHints();
    out.cookieLength = hints.cookieLength;
    out.auth = { loginForm: hints.loginForm, userElement: hints.userElement, keywords: hints.keywords };
    const frames = collectFrames(args);
    if (frames) out.frames = frames;
    return out;
  },
  back(args) {
    history.back();
    return { wentBack: true };
  },
  frames(args) {
    return { frames: collectFrames({ frames: true }) || [] };
  },
  get(args) {
    const sel = args && args.selector;
    const el = sel ? document.querySelector(sel) : document.documentElement;
    if (sel && !el) throw new Error("get: no match for selector " + sel);
    return {
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      text: el.innerText != null ? el.innerText : String(el.textContent || ""),
      htmlLength: (el.outerHTML || "").length,
    };
  },

  exec(args) {
    if (typeof SleeperDynamicCode === "undefined") {
      throw new Error("exec is unavailable in the signed Firefox build");
    }
    // G7 fix: reliably return the evaluated result for ANY well-formed JS.
    // Previously, any code containing a newline or `;` (multi-statement
    // scripts, IIFEs) was run as an async-IIFE *statement body*, so its
    // completion value was silently dropped and the command returned null.
    // Fix: evaluate via eval(), which returns the completion value of the last
    // evaluated expression/statement — so IIFEs, multi-statement code, and
    // object/array results are all captured as real values (not null).
    // `new Function` bodies run in the page's global scope, so document/window
    // are reachable. Thrown errors propagate to runHandler's .catch → {ok:false}.
    const code = String(args.code || "").trim();
    if (code.length === 0) return null;
    // Top-level `await` can't be eval'd as a script; fall back to the async-IIFE
    // so code relying on `await` keeps working (best-effort — such code returns
    // a Promise/undefined rather than a completion value, as before).
    if (/(^|[;\s}])\s*await\b/.test(code)) {
      // eslint-disable-next-line no-new-func
      return SleeperDynamicCode.exec(args);
    }
    // eslint-disable-next-line no-new-func
    return SleeperDynamicCode.exec(args);
  },

  find(args) {
    const locator = SleeperLocators.normalize(args, "find");
    const list = SleeperLocators.hasSemantic(locator) ? SleeperLocators.find(locator) : qsa(locator.selector || "*");
    const out = list.slice(0, args.limit || 50).map(safeJson);
    list.slice(0, args.limit || 50).forEach((el, i) => {
      const ref = ensureSleeperRef(el);
      if (out[i] && typeof out[i] === "object") out[i].ref = ref;
    });
    return { count: list.length, returned: out.length, elements: out };
  },

  click(args) {
    const el = semanticTarget(args, "click");
    el.scrollIntoView({ block: "center", behavior: "instant" });
    el.focus();
    if (typeof SleeperActivity !== "undefined") SleeperActivity.pulse(el);
    el.click();
    return { clicked: true, tag: el.tagName.toLowerCase(), text: (el.textContent || "").slice(0, 80) };
  },

  clickAll(args) {
    const locator = SleeperLocators.normalize(args, "clickAll");
    const els = SleeperLocators.hasSemantic(locator) ? SleeperLocators.find(locator) : qsa(locator.selector);
    els.forEach((el) => { el.scrollIntoView({ block: "center" }); el.click(); });
    return { clicked: els.length };
  },

  hover(args) {
    const el = semanticTarget(args, "hover");
    el.scrollIntoView({ block: "center", behavior: "instant" });
    ["mouseover", "mouseenter", "mousemove"].forEach((t) =>
      el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true })));
    return { hovered: args.selector };
  },

  focus(args) {
    const el = semanticTarget(args, "focus");
    el.focus();
    return { focused: args.selector, tag: el.tagName.toLowerCase() };
  },

    async type(args) {
    const el = semanticTarget(args, "type");
    el.focus();
    if (typeof SleeperActivity !== "undefined") SleeperActivity.typing(el);
    if (args.clear) setNativeValue(el, "");
    const text = String(args.text);
    if (args.stealth) {
      // character-by-character with key events — closer to human typing
      if (args.clear) setNativeValue(el, "");
      for (const ch of text) {
        const opts = { key: ch, bubbles: true, cancelable: true };
        el.dispatchEvent(new KeyboardEvent("keydown", opts));
        el.dispatchEvent(new KeyboardEvent("keypress", opts));
        setNativeValue(el, String(el.value || "") + ch);
        el.dispatchEvent(new KeyboardEvent("keyup", opts));
      }
      } else {
        setNativeValue(el, text);
      }
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (String(el.value || "") !== text) {
        throw new Error("type: target rejected the value after input events");
      }
      return { typed: text, tag: el.tagName.toLowerCase(), stealth: !!args.stealth };
  },

  keys(args) {
    const el = optionalSemanticTarget(args, "keys", () => document.activeElement || document.body);
    for (const key of args.keys) {
      const opts = { key, bubbles: true, cancelable: true };
      el.dispatchEvent(new KeyboardEvent("keydown", opts));
      el.dispatchEvent(new KeyboardEvent("keypress", opts));
      el.dispatchEvent(new KeyboardEvent("keyup", opts));
    }
    return { keys: args.keys, target: el.tagName.toLowerCase() };
  },

  press(args) {
    const el = optionalSemanticTarget(args, "press", () => document.activeElement || document.body);
    const key = String(args.key || "");
    const opts = { key, bubbles: true, cancelable: true };
    const form = key === "Enter" ? formForEnter(el) : null;
    let submitObserved = false;
    const observeSubmit = () => { submitObserved = true; };
    if (form && form.addEventListener) form.addEventListener("submit", observeSubmit, true);

    const hrefBefore = location.href;
    const keydownAccepted = el.dispatchEvent(new KeyboardEvent("keydown", opts));
    const keypressAccepted = keydownAccepted !== false
      ? el.dispatchEvent(new KeyboardEvent("keypress", opts))
      : false;
    el.dispatchEvent(new KeyboardEvent("keyup", opts));
    const defaultPrevented = keydownAccepted === false || keypressAccepted === false;
    let submission = submitObserved ? "event" : null;

    // Synthetic keyboard events are untrusted, so browsers do not perform the
    // native Enter default action. Recreate only that semantic default, and
    // only when the page neither canceled nor already handled it.
    if (form && !defaultPrevented && !submitObserved && location.href === hrefBefore) {
      submission = submitFormSemantically(form);
    }
    if (!submission && location.href !== hrefBefore) submission = "navigation";
    if (form && form.removeEventListener) form.removeEventListener("submit", observeSubmit, true);

    return {
      pressed: key,
      dispatched: true,
      defaultPrevented,
      submitted: !!submission,
      submission,
      target: el.tagName.toLowerCase(),
      url: location.href,
    };
  },

  submit(args) {
    const form = args.selector ? qs(args.selector) : document.querySelector("form");
    if (!form) throw new Error("no form found");
    const btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (btn) btn.click();
    else if (form.requestSubmit) form.requestSubmit();
    else form.submit();
    return { submitted: true };
  },

  read(args) {
    const el = qs(args.selector);
    const what = args.what || "text";
    if (what === "value") return { value: el.value ?? null };
    if (what === "html") return { html: el.outerHTML.slice(0, 6000) };
    if (what === "attr") return { attr: el.getAttribute(args.attr || "href") };
    if (what === "fulltext") return { text: (el.innerText || "").trim().slice(0, 6000) };
    return { text: (el.textContent || "").trim().slice(0, 6000) };
  },

  readAll(args) {
    const els = qsa(args.selector);
    const what = args.what || "text";
    return {
      count: els.length,
      items: els.slice(0, args.limit || 100).map((el) => {
        const base = { tag: el.tagName.toLowerCase() };
        if (what === "value") base.value = el.value ?? null;
        else if (what === "html") base.html = el.outerHTML.slice(0, 1500);
        else if (what === "attr") base.attr = el.getAttribute(args.attr || "href");
        else base.text = (el.textContent || "").trim().slice(0, 1500);
        return base;
      }),
    };
  },

  waitFor(args) {
    const sel = args.selector;
    const timeout = waitOption(args, ["timeout", "timeout_ms"], 10000);
    return waitForPageCondition(() => {
      // G3: use the text-aware resolver so :has-text / :has work in waits too
      const el = qsa(sel)[0];
      return el ? { found: true, selector: sel, el: safeJson(el) } : null;
    }, {
      timeout,
      interval: waitOption(args, ["interval", "interval_ms"], 150),
      timeoutMessage: "timeout waiting for " + sel,
      timeoutDetail: () => `url=${location.href} readyState=${document.readyState}`,
    });
  },

  waitUntil(args) {
    return new Promise((resolve, reject) => {
      const predicate = String(args.predicate || "").trim();
      if (!predicate) {
        structuredWaitUntil(args).then(resolve, reject);
        return;
      }
      if (typeof SleeperDynamicCode === "undefined") {
        reject(new Error("JavaScript predicates are unavailable in the signed Firefox build"));
        return;
      }
      let fn;
      try {
        fn = SleeperDynamicCode.createPredicate(predicate);
      } catch (e) { reject(e); return; }
      const timeout = waitOption(args, ["timeout", "timeout_ms"], 10000);
      waitForPageCondition(
        () => fn() ? { satisfied: true } : null,
        {
          timeout,
          interval: waitOption(args, ["interval", "interval_ms"], 150),
          timeoutMessage: "timeout waiting for predicate",
          timeoutDetail: () => `url=${location.href} readyState=${document.readyState}`,
        },
      ).then(resolve, reject);
    });
  },

  wait_url(args) {
    // G4: navigation-completion wait — poll location.href until it matches
    // args.pattern. Plain string = substring match; "/regex/" = RegExp.
    // Resolves {url} once matched, rejects on args.timeout_ms (default 15000).
    const pat = args.pattern;
    const timeout = waitOption(args, ["timeout_ms", "timeout"], 15000);
    let re = null;
    if (typeof pat === "string" && pat.length > 2 &&
        pat[0] === "/" && pat[pat.length - 1] === "/") {
      try { re = new RegExp(pat.slice(1, -1)); } catch (e) { re = null; }
    }
    return waitForPageCondition(() => {
      const href = location.href;
      const ok = re ? re.test(href) : href.includes(String(pat));
      return ok ? { url: href, pattern: pat } : null;
    }, {
      timeout,
      interval: waitOption(args, ["interval", "interval_ms"], 150),
      timeoutMessage: "timeout waiting for url pattern: " + pat,
      timeoutDetail: () => `current=${location.href} readyState=${document.readyState}`,
    });
  },

  scroll(args) {
    if (args.selector) { qs(args.selector).scrollIntoView({ block: "center" }); return { scrolled: args.selector }; }
    if (typeof SleeperActivity !== "undefined") SleeperActivity.scroll((args.y || 0) < 0 ? "up" : "down");
    window.scrollBy(args.x || 0, args.y || 0);
    return { scrolled: "by", x: args.x || 0, y: args.y || 0 };
  },

  scrollTo(args) {
    if (typeof SleeperActivity !== "undefined") SleeperActivity.scroll((args.y || 0) < window.scrollY ? "up" : "down");
    window.scrollTo(args.x || 0, args.y || 0);
    return { scrolledTo: [args.x || 0, args.y || 0] };
  },

  // Batch primitive: scroll a container down (40% of clientHeight per step)
  // until an element matching args.selector exists OR an element whose innerText
  // includes args.text is found, or args.max_iters steps are exhausted.
  // Resolves a plain result; never throws on a missing/bad selector.
  scrollUntil(args) {
    if (!args.selector && !args.text) {
      throw new Error("scrollUntil requires at least one of selector or text");
    }
    const maxIters = args.max_iters || 40;
    const pause = args.pause_ms || 150;
    let container = null;
    if (args.container) {
      container = qs(args.container);
    } else {
      // page scroll; fall back to <nav> / body when the page element isn't
      // the scroll container or isn't measurable (clientHeight 0)
      container = document.scrollingElement || document.documentElement;
      if (!container || container.clientHeight === 0) {
        container = document.querySelector("nav") || document.body;
      }
    }
    const check = () => {
      if (args.selector) {
        try { if (qsa(args.selector).length > 0) return true; } catch (e) { /* bad selector: skip */ }
      }
      if (args.text) {
        if (elementsByText(args.text).length > 0) return true;
      }
      return false;
    };
    const scrollTop = () => (container ? container.scrollTop : 0);
    return new Promise((resolve) => {
      // tick once so the pre-scroll state is observed deterministically
      setTimeout(() => {
        const run = (iter) => {
          if (check()) { resolve({ found: true, iter, scrollTop: scrollTop() }); return; }
          if (iter >= maxIters) { resolve({ found: false, iter: maxIters, scrollTop: scrollTop() }); return; }
          const step = Math.max(1, Math.round((container.clientHeight || window.innerHeight || 1) * 0.4));
          container.scrollTop += step;
          setTimeout(() => run(iter + 1), pause);
        };
        run(0);
      }, 0);
    });
  },

  navigate(args) {
    const requested = String(args.url || "");
    if (!requested) throw new Error("navigate requires url");
    location.href = args.url;
    return { navigating: requested, accepted: location.href !== "", url: location.href };
  },

  forms(args) {
    const scope = optionalSemanticTarget(args, "forms", () => document);
    const out = [];
    scope.querySelectorAll("input, textarea, select").forEach((el, i) => {
      if (el.type === "hidden") return;
      out.push({
        i, name: el.name || null, id: el.id || null,
        type: el.type || el.tagName.toLowerCase(),
        placeholder: el.getAttribute("placeholder") || null,
        visible: visible(el),
      });
    });
    return { count: out.length, fields: out };
  },

  fillForm(args) {
    const scope = optionalSemanticTarget(args, "fillForm", () => document);
    const fields = args.fields || {}; // {nameOrIdOrPlaceholder: value}
    let filled = 0;
    scope.querySelectorAll("input, textarea, select").forEach((el) => {
      if (el.type === "hidden" || el.disabled) return;
      const key = el.name || el.id || el.getAttribute("placeholder") || "";
      if (key && fields[key] !== undefined) {
        if (el.tagName === "SELECT") {
          el.value = String(fields[key]);
          el.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
          setNativeValue(el, String(fields[key]));
        }
        filled++;
      }
    });
    return { filled };
  },

  selectOption(args) {
    const el = semanticTarget(args, "selectOption");
    el.value = String(args.value);
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { selected: el.value, tag: el.tagName.toLowerCase() };
  },

  extract(args) {
    // {"map": {"title": "h1", "prices": ".price"}}            -> {"title": {...el blob...}, "prices": [{...}, ...]}
    // {"map": {"bio": {"sel":"p.bio","get":"text"}}}          -> {"bio": "the bio text"}  (scalar form)
    // get kinds: "text" | "html" | "href" | "value" | "attr:NAME"
    // Single match -> scalar; multiple matches -> array of scalars (capped at 20);
    // no match -> null for that field. Unknown/missing get -> element blob (safeJson).
    const scope = args.selector ? qs(args.selector) : document;
    const out = {};
    const resolveScalar = (el, get) => {
      if (get === "text") return (el.textContent || "").trim();
      if (get === "fulltext") return (el.innerText || "").trim();
      if (get === "html") return el.innerHTML;
      if (get === "href") return el.getAttribute("href");
      if (get === "value") return el.value;
      if (typeof get === "string" && get.indexOf("attr:") === 0) return el.getAttribute(get.slice(5));
      return safeJson(el); // missing/unknown kind -> element blob fallback
    };
    for (const [key, spec] of Object.entries(args.map || {})) {
      let sel = spec;
      let get = null;
      if (spec && typeof spec === "object" && !Array.isArray(spec)) {
        sel = spec.sel;
        get = spec.get;
      }
      const all = qsa(sel, scope);
      if (all.length === 0) { out[key] = null; continue; }
      if (get === null) { // plain-selector form -> existing element-blob behavior
        if (all.length === 1) out[key] = safeJson(all[0]);
        else out[key] = all.slice(0, 20).map(safeJson);
      } else { // object form -> scalar values
        if (all.length === 1) out[key] = resolveScalar(all[0], get);
        else out[key] = all.slice(0, 20).map((el) => resolveScalar(el, get));
      }
    }
    return out;
  },

  snapshot(args) {
    // lightweight text outline for agent context — headings + links + inputs
    const out = { title: document.title, url: location.href, headings: [], inputs: [] };
    document.querySelectorAll("h1,h2,h3").forEach((h, i) => {
      if (i < 30) out.headings.push({ text: h.textContent.trim().slice(0, 120), ref: ensureSleeperRef(h) });
    });
    document.querySelectorAll("input,textarea,select,button").forEach((el, i) => {
      if (i < 40) out.inputs.push({
        tag: el.tagName.toLowerCase(), id: el.id || null, name: el.name || null,
        type: el.type || null, placeholder: el.getAttribute("placeholder") || null,
        text: el.tagName === "BUTTON" ? el.textContent.trim().slice(0, 60) : null,
        ref: ensureSleeperRef(el),
      });
    });
    // G6: optional frames + auth heuristics
    out.auth = authHints();
    const frames = collectFrames(args);
    if (frames) out.frames = frames;
    return out;
  },

  // G3 convenience: find element(s) by innerText, like find().
  findText(args) {
    const matches = elementsByText(args.text, { exact: args.exact });
    const limit = args.limit || 20;
    return {
      count: matches.length,
      returned: Math.min(matches.length, limit),
      elements: matches.slice(0, limit).map(safeJson),
    };
  },

  // G3 convenience: click the element whose innerText matches (default: first).
  // Optional args.verify (CSS selector, or text substring prefixed "text:") polls
  // up to ~3000ms for the result of the click before resolving. Absent verify
  // keeps the original synchronous {clicked:true, tag, text} behavior.
  clickText(args) {
    const matches = elementsByText(args.text, { exact: args.exact });
    const idx = args.index || 0;
    const el = matches[idx];
    if (!el) throw new Error("no element with text: " + args.text);
    el.scrollIntoView({ block: "center", behavior: "instant" });
    el.focus();
    if (typeof SleeperActivity !== "undefined") SleeperActivity.pulse(el);
    el.click();
    const base = { clicked: true, tag: el.tagName.toLowerCase(), text: (el.textContent || "").trim().slice(0, 80) };
    if (!args.verify) return base;
    return new Promise((resolve) => {
      let verifySel = null;
      let verifyText = null;
      if (String(args.verify).indexOf("text:") === 0) verifyText = String(args.verify).slice(5);
      else verifySel = args.verify;
      const start = Date.now();
      const iv = setInterval(() => {
        let ok = false;
        if (verifySel) {
          try { ok = qsa(verifySel).length > 0; } catch (e) { ok = false; }
        } else if (verifyText) {
          ok = elementsByText(verifyText).length > 0;
        }
        if (ok) {
          clearInterval(iv);
          resolve(Object.assign({}, base, { verified: true, verify_reason: verifySel ? "selector" : "text" }));
        } else if (Date.now() - start > 3000) {
          clearInterval(iv);
          resolve(Object.assign({}, base, { verified: false, verify_reason: "timeout" }));
        }
      }, 200);
    });
  },

  // G3 convenience: poll until an element whose innerText contains the text exists.
  waitText(args) {
    const timeout = waitOption(args, ["timeout_ms", "timeout"], 10000);
    return waitForPageCondition(() => {
      const matches = elementsByText(args.text, { exact: args.exact });
      return matches.length > 0
        ? { found: true, text: args.text, el: safeJson(matches[0]) }
        : null;
    }, {
      timeout,
      interval: waitOption(args, ["interval", "interval_ms"], 150),
      timeoutMessage: "timeout waiting for text: " + args.text,
      timeoutDetail: () => `url=${location.href} readyState=${document.readyState}`,
    });
  },

  // Batch primitive: poll for an open modal dialog (role=dialog). Optionally
  // require its textContent to include args.text. Resolves {found,text} or
  // rejects with a descriptive Error on timeout.
  waitDialog(args) {
    const timeout = waitOption(args, ["timeout_ms", "timeout"], 15000);
    const text = args.text;
    return waitForPageCondition(() => {
      const dlg = document.querySelector("[role=dialog]");
      return dlg && (!text || (dlg.textContent || "").indexOf(text) !== -1)
        ? { found: true, text: (dlg.textContent || "").trim().slice(0, 4000) }
        : null;
    }, {
      timeout,
      interval: waitOption(args, ["interval", "interval_ms"], 150),
      timeoutMessage: "timeout waiting for dialog" + (text ? ":" + text : ""),
      timeoutDetail: () => `url=${location.href} readyState=${document.readyState}`,
    });
  },

  cookies() {
    // same-origin only; document.cookie is the browser-visible surface
    return { cookie: document.cookie.slice(0, 4000) };
  },

  // ------------------------------------------------------------------
  // G8 — DOM INTERACTION HANDLERS
  // ------------------------------------------------------------------

  // Files carry explicit bytes; filenames alone cannot represent an upload.
  upload(args) {
    try {
      const sel = args.selector;
      const files = Array.isArray(args.files) ? args.files : [args.files];
      if (!files.length || files.some((file) => typeof file === "string")) {
        throw new Error("file contents required; filenames alone cannot upload");
      }
      const prepared = files.map((file) => {
        if (!file || typeof file !== "object" || typeof file.name !== "string" || typeof file.content_base64 !== "string") throw new Error("each upload file requires name and content_base64");
        let binary;
        try { binary = atob(file.content_base64); } catch (_) { throw new Error(`invalid base64 content for ${file.name}`); }
        if (binary.length > 10 * 1024 * 1024) throw new Error(`file exceeds 10 MiB limit: ${file.name}`);
        return new File([Uint8Array.from(binary, (char) => char.charCodeAt(0))], file.name, { type: typeof file.mime_type === "string" ? file.mime_type : "application/octet-stream" });
      });
      const input = qs(sel);
      if (!input || input.tagName !== "INPUT" || input.type !== "file") {
        throw new Error("no file input for selector: " + sel);
      }
      const dt = new DataTransfer();
      for (const file of prepared) dt.items.add(file);
      input.files = dt.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      const names = prepared.map((file) => file.name);
      return { uploaded: true, files: names, file_names: names, target: sel };
    } catch (error) {
      throw error;
    }
  },

  // drag: dispatch the HTML5 drag/drop event sequence between two elements.
  // Sequence: dragstart/dragenter/dragover on the source, drop on the target,
  // then dragend on the source. A fresh DataTransfer is shared across events.
  // LIMITATION: React DnD (and some libs) bind native drag events at the root
  // and may ignore synthetic ones — this is best-effort; a real pointer path
  // needs native input injection.
  drag(args) {
    try {
      const src = semanticTarget({ selector: args.source, role: args.source_role, name: args.source_name, label: args.source_label, locator_text: args.source_text, testid: args.source_testid }, "drag");
      const tgt = semanticTarget({ selector: args.target, role: args.target_role, name: args.target_name, label: args.target_label, locator_text: args.target_text, testid: args.target_testid }, "drag");
      const dt = new DataTransfer();
      const opt = (type, target) =>
        new DragEvent(type, {
          bubbles: true,
          cancelable: true,
          dataTransfer: dt,
          relatedTarget: target,
        });
      src.dispatchEvent(opt("dragstart", tgt));
      src.dispatchEvent(opt("dragenter", tgt));
      src.dispatchEvent(opt("dragover", tgt));
      tgt.dispatchEvent(opt("drop", src));
      src.dispatchEvent(opt("dragend", tgt));
      return { dragged: true, source: args.source, target: args.target };
    } catch (e) {
      throw new Error("no element for selector: " + (args.source || args.target));
    }
  },

  // dblclick: dispatch only the requested double-click event. A separate
  // el.click() would add an unintended single-click activation after it.
  dblclick(args) {
    try {
      const el = semanticTarget(args, "dblclick");
      el.scrollIntoView({ block: "center", behavior: "instant" });
      if (typeof SleeperActivity !== "undefined") SleeperActivity.pulse(el);
      el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true, detail: 2 }));
      return { dblclicked: true, target: args.selector, tag: el.tagName.toLowerCase() };
    } catch (e) {
      throw new Error("no element for selector: " + args.selector);
    }
  },

  // check/uncheck: set a checkbox/radio (or role=checkbox / [aria-checked]
  // widget) to checked=true/false. Records whether the state actually changed.
  check(args) { return setChecked(args, true); },
  uncheck(args) { return setChecked(args, false); },
};

// Shared implementation for check/uncheck. Lives after the handlers object so
// the object literal above stays tidy; content.js reaches it via the handler.
function setChecked(args, checked) {
  const sel = args.selector;
  try {
    const el = semanticTarget(args, "check");
    const isNative = el instanceof HTMLInputElement &&
      (el.type === "checkbox" || el.type === "radio");
    const isWidget = el.getAttribute("role") === "checkbox" || el.hasAttribute("aria-checked");
    if (!isNative && !isWidget) {
      throw new Error("not a checkable element for selector: " + sel);
    }
    const before = isNative ? el.checked : el.getAttribute("aria-checked") === "true";
    if (isNative) {
      if (el.type === "radio" && !checked) {
        if (el.checked) {
          el.checked = false;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
      } else if (el.checked !== checked) {
        // Native activation applies the browser's own checkbox/radio state
        // transition and event ordering. Do not pre-set checked and then click:
        // the click default action would toggle the requested state back.
        el.click();
      }
    } else if (before !== checked) {
      el.click();
      // Custom widgets are page-defined. If the click handler did not update
      // aria-checked synchronously, reflect the requested state explicitly.
      if ((el.getAttribute("aria-checked") === "true") !== checked) {
        el.setAttribute("aria-checked", String(checked));
      }
    }
    const actual = isNative ? el.checked : el.getAttribute("aria-checked") === "true";
    return { checked: actual, changed: before !== actual, target: sel };
  } catch (e) {
    throw new Error("no element for selector: " + sel);
  }
}

// ------------------------------------------------------------------
// REGISTER HANDLERS
// ------------------------------------------------------------------

// The content script evals this file in its own isolated world and calls it
// as a function that returns the handlers. Nothing is exposed on window —
// page scripts can neither see nor call the sleeper (Xray-safe).
//
// Dormancy: the handlers do no polling, no network, no DOM mutation until
// a command arrives from the daemon — effectively dormant until asked.
handlers;
