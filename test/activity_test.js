const assert = require("assert");
const vm = require("vm");
const labelsSource = require("fs").readFileSync(require("path").join(__dirname, "../extension/action-labels.js"), "utf8");
const source = require("fs").readFileSync(require("path").join(__dirname, "../extension/activity.js"), "utf8");
assert.ok(source.includes("storage.onChanged"), "activity settings update live");
assert.ok(source.includes("aria-hidden"), "activity host is hidden from assistive technology");
assert.match(source, /\.scroll\{top:50%;[^}]+transform:translateY\(-50%\)/, "scroll cue stays centered at every frame");
assert.match(source, /\.scroll:after\{[^}]+left:10px;top:18px/, "scroll arrow is optically centered");

function createHarness(stored) {
  const root = { focused: true, matchMedia: () => ({ matches: false }), addEventListener() {} };
  let nextTimer = 0;
  let shadow;
  const listeners = [];
  const state = Object.assign({}, stored || {});
  const chrome = stored ? {
    storage: {
      local: {
        get: (_keys, callback) => callback(state),
      },
      onChanged: {
        addListener: (listener) => listeners.push(listener),
      },
    },
  } : null;
  const document = {
    visibilityState: "visible",
    hasFocus: () => root.focused,
    addEventListener() {},
    documentElement: { appendChild(node) { node.isConnected = true; } },
    createElement() {
      return {
        isConnected: true,
        style: {},
        attrs: {},
        setAttribute(name, value) { this.attrs[name] = value; },
        attachShadow() { shadow = { innerHTML: "", appendChild(node) { this.last = node; this.children.push(node); }, children: [] }; return shadow; },
        remove() { this.isConnected = false; if (this.attrs["data-sleeper-activity"] && shadow) shadow.children.forEach((node) => { node.isConnected = false; }); },
      };
    },
  };
  const context = { chrome, document, setTimeout: () => ++nextTimer, clearTimeout() {}, addEventListener() {}, matchMedia: root.matchMedia, innerWidth: 100, innerHeight: 100, console };
  context.globalThis = context;
  vm.runInNewContext(labelsSource, context);
  vm.runInNewContext(source, context);
  return {
    api: context.SleeperActivity,
    root,
    document,
    getShadow: () => shadow,
    pending: () => nextTimer,
    change(changes) {
      Object.keys(changes).forEach((key) => { state[key] = changes[key].newValue; });
      listeners.forEach((listener) => listener(changes));
    },
  };
}

const { api, root, document, getShadow } = createHarness();
const target = { getBoundingClientRect: () => ({ left: 10, top: 20, width: 80, height: 30 }) };
api.pulse(target);
api.pulse(target);
assert.strictEqual(getShadow().children.filter((node) => node.isConnected).length, 1, "coalesced pulse replaces prior cue");
api.typing(target);
api.typing(target);
assert.strictEqual(getShadow().children.filter((node) => node.isConnected).length, 2, "coalesced typing replaces prior cue");
const typingCue = getShadow().children.find((node) => node.isConnected && node.className === "cue typing");
assert.strictEqual(typingCue.style.left, "4px", "typing cue clears the target border");
assert.strictEqual(typingCue.style.top, "14px", "typing cue expands above the target");
assert.strictEqual(typingCue.style.width, "92px", "typing cue expands horizontally");
api.scroll("down");
api.scroll("down");
assert.strictEqual(getShadow().children.filter((node) => node.isConnected).length, 4, "coalesced scroll replaces both side cues");
assert.ok(getShadow().children.some((node) => node.isConnected && node.className.includes("scroll down left")), "left scroll cue is present");
assert.ok(getShadow().children.some((node) => node.isConnected && node.className.includes("scroll down right")), "right scroll cue is present");
assert.ok(document.documentElement, "activity module initializes without page globals");
root.focused = false;
api.pulse(target); // blur state is a no-op and must not throw
api.configure(false);
root.focused = true;
api.typing(target); // disabled state is a no-op
assert.ok(getShadow().children.every((node) => !node.isConnected), "disabling clears activity cues");
api.clear();
console.log("activity cues: ok");

const historical = createHarness({
  current_action: null,
  action_current: null,
  action_in_progress: false,
  action_log: [{ cmd: "snapshot", status: "success", ts: 1000 }],
});
assert.strictEqual(historical.getShadow(), undefined, "historical actions do not show while idle");

const live = createHarness({
  current_action: { cmd: "snapshot", status: "running", ts: 2000 },
  action_current: null,
  action_in_progress: true,
  action_log: [],
});
assert.strictEqual(live.getShadow().children.filter((node) => node.isConnected).length, 1, "live action shows feedback");
live.change({
  current_action: { oldValue: live, newValue: null },
  action_in_progress: { oldValue: true, newValue: false },
});
assert.ok(live.getShadow().children.every((node) => !node.isConnected), "idle transition clears live feedback");
