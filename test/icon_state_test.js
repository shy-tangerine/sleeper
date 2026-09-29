"use strict";

// Focused harness checks for the toolbar contract. The full MV2 background
// needs browser APIs and a live daemon, so these assertions guard the wiring
// and state transitions without starting an extension process.
const assert = require("assert");
const fs = require("fs");

const backgroundSource = fs.readFileSync(require("path").join(__dirname, "..", "extension", "background.js"), "utf8");
const activitySource = fs.readFileSync(require("path").join(__dirname, "..", "extension", "action-state.js"), "utf8");

for (const path of [
  "icon.png", "icon16.png", "icon32.png", "icon128.png",
  "icon-active.png", "icon-active16.png", "icon-active32.png", "icon-active128.png",
]) {
  assert.ok(fs.existsSync(require("path").join(__dirname, "..", "extension", path)), `${path} exists`);
}

assert.match(activitySource, /setIcon\(\{\s*path:/);
assert.match(backgroundSource, /activityTracker\.setDaemonConnected\(false\);\s*\n\s*if \(wsClosedByUs\)/);
assert.match(backgroundSource, /msg && msg\.type === "auth_ok"[\s\S]*?activityTracker\.setDaemonConnected\(true\);/);
assert.match(backgroundSource, /ws\.onclose = \(\) => \{\s*\n\s*stopWebSocketKeepalive\(\);\s*\n\s*activityTracker\.setDaemonConnected\(false\);/);
assert.match(backgroundSource, /ws\.onerror = \(\) => \{\s*\n\s*activityTracker\.setDaemonConnected\(false\);/);
assert.match(activitySource, /16: "icon-active16\.png"/);
assert.match(activitySource, /16: "icon16\.png"/);
assert.match(activitySource, /ACTIVE_ACTION_TITLE/);
assert.match(activitySource, /action_in_progress/);
assert.match(backgroundSource, /browser_id: browserId/);
assert.doesNotMatch(backgroundSource, /browser_label:/);

console.log("icon state wiring: ok");
