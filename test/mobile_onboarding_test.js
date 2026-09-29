"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "extension", "mobile_onboarding.js"),
  "utf8"
);
const backgroundSource = fs.readFileSync(
  path.join(__dirname, "..", "extension", "background.js"),
  "utf8"
);
const optionsSource = fs.readFileSync(
  path.join(__dirname, "..", "extension", "options.html"),
  "utf8"
);

function load() {
  const context = {};
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.SleeperMobileOnboarding;
}

function browserMock(os) {
  const calls = { platform: 0, tabs: [], storage: [], events: [] };
  const values = {};
  let failNextTab = false;
  return {
    calls,
    failNextTab() {
      failNextTab = true;
    },
    api: {
      runtime: {
        lastError: null,
        getPlatformInfo(callback) {
          calls.platform += 1;
          callback({ os });
        },
        getURL(page) {
          return `moz-extension://sleeper/${page}`;
        },
      },
      tabs: {
        create(options) {
          calls.events.push("tabs:create");
          calls.tabs.push(options);
          if (failNextTab) {
            failNextTab = false;
            return { then(_resolve, reject) { reject(new Error("tab blocked")); } };
          }
          if (arguments[1]) arguments[1]({ id: calls.tabs.length });
        },
      },
      storage: {
        local: {
        get(key, callback) {
          calls.events.push("storage:get");
          calls.storage.push(`get:${key}`);
          callback({ [key]: values[key] });
        },
        set(update, callback) {
          calls.events.push("storage:set");
          Object.assign(values, update);
            calls.storage.push(`set:${Object.keys(update)[0]}`);
            if (callback) callback();
          },
        },
      },
    },
  };
}

const onboarding = load();

assert.match(
  backgroundSource,
  /onInstalled\.addListener\(\(details\)\s*=>\s*\{\s*SleeperMobileOnboarding\.openOnFirstAndroidInstall\(chrome, details\);/,
  "background install lifecycle invokes mobile onboarding"
);
assert.match(
  optionsSource,
  /id="daemon-connection"/,
  "setup URL targets the daemon connection controls"
);

{
  const browser = browserMock("android");
  onboarding.openOnFirstAndroidInstall(browser.api, { reason: "install" });
  assert.equal(browser.calls.platform, 1, "initial install checks the platform");
  assert.deepEqual(browser.calls.tabs, [
    { url: "moz-extension://sleeper/options.html#daemon-connection", active: true },
  ]);
  assert.deepEqual(browser.calls.storage, [
    `get:${onboarding.COMPLETED_KEY}`,
    `set:${onboarding.COMPLETED_KEY}`,
  ]);
  assert.deepEqual(
    browser.calls.events,
    ["storage:get", "tabs:create", "storage:set"],
    "completion is persisted only after the setup tab is opened"
  );
  onboarding.openOnFirstAndroidInstall(browser.api, { reason: "install" });
  assert.equal(browser.calls.tabs.length, 1, "same-profile reload cannot reopen onboarding");

  const failedBrowser = browserMock("android");
  failedBrowser.failNextTab();
  onboarding.openOnFirstAndroidInstall(failedBrowser.api, { reason: "install" });
  assert.deepEqual(
    failedBrowser.calls.storage,
    [`get:${onboarding.COMPLETED_KEY}`],
    "a failed setup tab does not mark onboarding complete"
  );
  onboarding.openOnFirstAndroidInstall(failedBrowser.api, { reason: "install" });
  assert.deepEqual(
    failedBrowser.calls.storage,
    [`get:${onboarding.COMPLETED_KEY}`, `get:${onboarding.COMPLETED_KEY}`, `set:${onboarding.COMPLETED_KEY}`],
    "a later successful install can retry onboarding"
  );
}

for (const reason of ["update", "browser_update", "chrome_update", undefined]) {
  const browser = browserMock("android");
  onboarding.openOnFirstAndroidInstall(browser.api, { reason });
  assert.equal(browser.calls.platform, 0, `${reason || "missing reason"} does not check the platform`);
  assert.deepEqual(browser.calls.tabs, [], `${reason || "missing reason"} does not open setup`);
}

for (const os of ["linux", "mac", "win", "cros", "openbsd"]) {
  const browser = browserMock(os);
  onboarding.openOnFirstAndroidInstall(browser.api, { reason: "install" });
  assert.deepEqual(browser.calls.tabs, [], `${os} install preserves desktop behavior`);
}

console.log("mobile onboarding: ok");
