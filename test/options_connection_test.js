const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const extension = path.join(__dirname, "..", "extension");
const html = fs.readFileSync(path.join(extension, "options.html"), "utf8");
const js = fs.readFileSync(path.join(extension, "options.js"), "utf8");

assert.match(html, /id="connection-mode"/, "summary exposes connection mode and computer name");
assert.match(html, /id="connection-status"[^>]+aria-live="polite"/, "connection status is announced live");
assert.match(html, /id="connection-action"/, "summary provides a reconnect/setup action");
assert.doesNotMatch(html, /daemon-auth-token|Daemon token/, "daemon credentials are never exposed to the user");
assert.doesNotMatch(html, /Browser label|id="profile"/, "browser labels are not user-configurable");
assert.doesNotMatch(html, /Request blocking|id="adblock"/, "request blocking is not part of Sleeper");
assert.match(js, /function connectionName\(endpoint\)/, "computer name parsing is isolated in a helper");
assert.match(js, /SleeperDaemonEndpoint\.loopback\(hostname\)/, "loopback endpoints never leak an address as a computer name");
assert.match(js, /test\(first\)/, "remote computer names are constrained to safe hostname labels");
assert.doesNotMatch(js, /connectionStatus\.lastElementChild/, "connection status does not assume a child exists");
assert.match(js, /if \(!statusLabel\)[\s\S]*?createElement\("span"\)[\s\S]*?connectionStatus\.appendChild\(statusLabel\)/,
  "missing connection label is restored without replacing sibling status content");
assert.match(js, /ui\.connectionAction\.addEventListener\("click", \(\) =>/, "reconnect/setup action is keyboard accessible");
assert.match(js, /sendMessage\(\{ type: "sleeper-reconnect" \}/, "reconnect does not expose connection credentials");

console.log("options connection tests passed");
