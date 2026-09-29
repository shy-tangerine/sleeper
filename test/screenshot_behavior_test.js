const assert = require("assert");
const screenshot = require("../extension/screenshot.js");

async function withImageStubs(fn) {
  const documentBefore = global.document;
  const imageBefore = global.Image;
  global.document = { createElement: () => ({ getContext: () => ({ drawImage() {} }), toDataURL: () => "data:image/png;base64,AA==" }) };
  global.Image = class { set src(_) { queueMicrotask(() => this.onload()); } };
  try { await fn(); } finally { global.document = documentBefore; global.Image = imageBefore; }
}

async function run() {
  const calls = [];
  const browser = {
    tabs: {
      get: async () => ({ id: 2, windowId: 7 }), query: async () => [{ id: 1 }],
      update: async (id, change) => calls.push(["tab.update", id, change]),
      executeScript: async (_id, request) => request.code.includes("scrollWidth") ? [{ width: 1, height: 1, viewport: 1, y: 44 }] : (calls.push(["execute", request.code]), ["ok"]),
      captureVisibleTab: async () => "data:image/png;base64,AA==",
    },
    windows: { getAll: async () => [{ id: 7, focused: false }, { id: 9, focused: true }], update: async (id, change) => calls.push(["window.update", id, change]) },
  };
  await withImageStubs(() => screenshot.capture(browser, 2, { full_page: true }));
  assert.deepStrictEqual(calls[0], ["tab.update", 2, { active: true }]);
  assert.deepStrictEqual(calls[1], ["window.update", 7, { focused: true }]);
  assert.ok(calls.some((call) => call[0] === "execute" && call[1].includes("scrollTo(0, 44)")), "restores page scroll");
  assert.ok(calls.some((call) => call[0] === "tab.update" && call[1] === 1), "restores prior active tab");
  assert.deepStrictEqual(calls.at(-1), ["window.update", 9, { focused: true }]);
  assert.ok(!calls.some((call) => call[0] === "window.update" && call[1] === 7 && call[2].focused === false), "does not artificially blur the browser");

  const timeoutCalls = [];
  const timeoutBrowser = {
    tabs: {
      get: async () => ({ id: 2, windowId: 7 }), query: async () => [{ id: 1 }],
      update: async (id, change) => timeoutCalls.push(["tab.update", id, change]),
      executeScript: async (_id, request) => request.code.includes("scrollWidth") ? [{ width: 1, height: 1, viewport: 1, y: 12 }] : (timeoutCalls.push(["execute", request.code]), ["ok"]),
      captureVisibleTab: () => new Promise(() => {}),
    },
    windows: { getAll: async () => [{ id: 7, focused: false }, { id: 9, focused: true }], update: async (id, change) => timeoutCalls.push(["window.update", id, change]) },
  };
  const timerBefore = global.setTimeout;
  let boundedCaptureTimers = 0;
  global.setTimeout = (fn, ms) => {
    if (ms === 4000 && ++boundedCaptureTimers >= 8) { queueMicrotask(fn); return 1; }
    return timerBefore(fn, ms);
  };
  try {
    await assert.rejects(() => withImageStubs(() => screenshot.capture(timeoutBrowser, 2, { full_page: true })), /capture timeout/);
  } finally { global.setTimeout = timerBefore; }
  assert.ok(timeoutCalls.some((call) => call[0] === "execute" && call[1].includes("scrollTo(0, 12)")), "timeout restores page scroll");
  assert.ok(timeoutCalls.some((call) => call[0] === "tab.update" && call[1] === 1), "timeout restores prior active tab");
  assert.deepStrictEqual(timeoutCalls.at(-1), ["window.update", 9, { focused: true }]);

  const visibleCalls = [];
  const visibleBrowser = {
    tabs: {
      get: async () => ({ id: 2, windowId: 7 }), query: async () => [{ id: 1 }],
      update: async (id, change) => visibleCalls.push(["tab.update", id, change]),
      captureVisibleTab: async () => "data:image/png;base64,AA==",
    },
    windows: { getAll: async () => [{ id: 7, focused: false }, { id: 9, focused: true }], update: async (id, change) => visibleCalls.push(["window.update", id, change]) },
  };
  await screenshot.capture(visibleBrowser, 2, {});
  assert.deepStrictEqual(visibleCalls.slice(0, 2), [["tab.update", 2, { active: true }], ["window.update", 7, { focused: true }]]);
  assert.ok(visibleCalls.some((call) => call[0] === "tab.update" && call[1] === 1), "visible capture restores prior tab");
  assert.deepStrictEqual(visibleCalls.at(-1), ["window.update", 9, { focused: true }]);
  assert.ok(!visibleCalls.some((call) => call[0] === "window.update" && call[1] === 7 && call[2].focused === false), "visible fallback does not blur the browser");

  const tabScopedCalls = [];
  const tabScoped = {
    tabs: {
      get: async () => ({ id: 2, windowId: 7 }),
      executeScript: async (_id, request) => request.code.includes("scrollWidth") ? [{ width: 1, height: 1, viewport: 1, y: 0 }] : ["ok"],
      captureTab: async () => "data:image/png;base64,AA==",
      update: async (...args) => tabScopedCalls.push(args),
    },
  };
  await withImageStubs(() => screenshot.capture(tabScoped, 2, { full_page: true }));
  assert.deepStrictEqual(tabScopedCalls, [], "tab-scoped capture does not activate or focus the browser");
}

run().then(() => console.log("screenshot restoration behavior: ok"));
