"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const source = fs.readFileSync(
  path.join(__dirname, "..", "extension", "background.js"),
  "utf8"
);

assert.match(
  source,
  /if \(chrome\.windows && chrome\.windows\.onFocusChanged\) \{\s*chrome\.windows\.onFocusChanged\.addListener/,
  "Firefox Android must not require the unsupported chrome.windows API during background startup"
);

console.log("android background: ok");
