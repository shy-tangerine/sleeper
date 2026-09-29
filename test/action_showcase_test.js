const assert = require("assert");
const fs = require("fs");
const path = require("path");

const extension = path.join(__dirname, "..", "extension");
const popupHtml = fs.readFileSync(path.join(extension, "popup.html"), "utf8");
const popupJs = fs.readFileSync(path.join(extension, "popup.js"), "utf8");
const popupCss = fs.readFileSync(path.join(extension, "popup.css"), "utf8");
const optionsHtml = fs.readFileSync(path.join(extension, "options.html"), "utf8");
const optionsJs = fs.readFileSync(path.join(extension, "options.js"), "utf8");
const activityJs = fs.readFileSync(path.join(extension, "activity.js"), "utf8");

assert.match(popupHtml, /id="current-action"/, "popup exposes the current action");
assert.match(popupHtml, /id="recent-actions"/, "popup exposes recent action outcomes");
assert.match(popupJs, /POPUP_ACTION_LIMIT\s*=\s*3/, "popup is limited to the latest three actions");
assert.match(popupJs, /action_log/, "popup reads the persisted action log");
assert.match(popupJs, /duration_ms/, "popup consumes enriched action durations");
assert.match(popupJs, /status/, "popup consumes enriched action outcomes");
assert.match(popupCss, /env\(safe-area-inset-bottom\)/, "popup respects mobile safe areas");

assert.match(optionsHtml, /<section[^>]+id="log"[^>]+tabindex="-1"/, "the action log is a focusable URL target");
assert.match(optionsJs, /VISIBLE_ACTIONS\s*=\s*10/, "settings show ten actions before View all");
assert.match(optionsJs, /location\.hash\s*===\s*["']#log["']/, "the #log target is focused on load");
assert.match(optionsJs, /duration_ms/, "settings consume enriched action durations");
assert.match(optionsJs, /status/, "settings consume enriched action outcomes");

assert.match(activityJs, /env\(safe-area-inset-bottom\)/, "page feedback respects the mobile safe area");
assert.match(activityJs, /STATUS_CUE_MS\s*=\s*[3-9]\d{3}/, "page action feedback remains visible for at least three seconds");
assert.match(activityJs, /SENSITIVE_ACTIONS/, "page feedback explicitly redacts value-bearing actions");
assert.match(activityJs, /prefers-reduced-motion/, "page feedback respects reduced motion");
assert.match(activityJs, /visible_activity/, "page feedback respects the activity visibility setting");

console.log("mobile action showcase: ok");
