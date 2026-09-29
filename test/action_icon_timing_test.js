const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "..", "extension", "action-state.js"), "utf8");
const timers = [];
const clearedTimers = [];
let fakeNow = 0;
const iconCalls = [];
const storageCalls = [];
const chromeApi = {
  storage: { local: { set: (value) => storageCalls.push(value) } },
  browserAction: {
    setIcon: (value) => iconCalls.push({ type: "icon", value }),
    setTitle: (value) => iconCalls.push({ type: "title", value }),
  },
};
const context = {
  chrome: chromeApi,
  setTimeout: (fn, ms) => { const timer = { fn, ms, cleared: false }; timers.push(timer); return timer; },
  clearTimeout: (timer) => { timer.cleared = true; clearedTimers.push(timer); },
};
vm.runInNewContext(source, context);

function tracker() {
  return context.SleeperBackgroundActivity.createActivityTracker({
    chromeApi,
    setTimeoutFn: context.setTimeout,
    clearTimeoutFn: context.clearTimeout,
    now: () => fakeNow,
  });
}

const activity = tracker();
activity.setDaemonConnected(true);
activity.start("A");
activity.start("B");
activity.finish("A");
assert.strictEqual(activity.isActive(), true, "A completion does not hide while B is active");
assert.strictEqual(timers.length, 0, "overlapping requests do not schedule an early idle timer");
activity.finish("B");
assert.strictEqual(timers.length, 1, "final completion starts the idle window");
assert.strictEqual(timers[0].ms, 3000, "idle activity window is three seconds");
fakeNow = 3000;
timers[0].fn();
assert.strictEqual(activity.isActive(), false, "activity closes after the idle window");

activity.start("A");
activity.finish("A");
const firstIdleTimer = timers[1];
activity.finish("A");
assert.strictEqual(timers.length, 2, "duplicate completion does not schedule another timer");
activity.start("B");
assert.strictEqual(firstIdleTimer.cleared, true, "new activity cancels the pending idle close");
activity.finish("B");
assert.strictEqual(timers.length, 3, "a later final completion gets a fresh idle window");

activity.setDaemonConnected(false);
assert.strictEqual(activity.isActive(), false, "disconnect clears outstanding activity");
assert.strictEqual(timers[2].cleared, true, "disconnect cancels the idle close");
activity.setDaemonConnected(true);
activity.start("reconnected");
assert.strictEqual(activity.isActive(), true, "activity works after reconnect");
activity.finish("reconnected");

assert.ok(storageCalls.some((value) => value.daemon_connected === false), "disconnect persists daemon state");
assert.ok(storageCalls.some((value) => value.action_in_progress === true), "start persists active state");
assert.ok(iconCalls.length > 0, "toolbar state is updated");
console.log("action icon timing: ok");
