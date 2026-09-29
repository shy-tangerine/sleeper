"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "content.js"), "utf8");
const messages = [];
const isolatedListeners = new Map();

function alert(message) { return "native alert: " + message; }
function confirm(message) { return false; }
function prompt(message, defaultText) { return defaultText === undefined ? null : defaultText; }

const pageWindow = {
  alert,
  confirm,
  prompt,
  postMessage() {},
};

const pageContext = vm.createContext({
  window: pageWindow,
  document: {},
  console: { log() {}, info() {}, warn() {}, error() {} },
  Date,
});

const document = {
  createElement() { return { textContent: "" }; },
  head: {
    appendChild(script) {
      vm.runInContext(script.textContent, pageContext);
    },
  },
};

const chrome = {
  runtime: {
    sendMessage(message) { messages.push(message); },
    onMessage: { addListener(listener) { isolatedListeners.set("message", listener); } },
  },
};

vm.runInNewContext(source, {
  chrome,
  document,
  window: {
    addEventListener(type, listener) { isolatedListeners.set(type, listener); },
  },
  SleeperTailscaleSetup: { offerFromPage() {} },
  location: { href: "https://example.test/" },
  setTimeout,
  console,
});

assert.strictEqual(pageWindow.alert, alert, "idle hook must not replace alert");
assert.strictEqual(pageWindow.confirm, confirm, "idle hook must not replace confirm");
assert.strictEqual(pageWindow.prompt, prompt, "idle hook must not replace prompt");
assert.strictEqual(pageWindow.alert("x"), "native alert: x");
assert.strictEqual(pageWindow.confirm("x"), false);
assert.strictEqual(pageWindow.prompt("x", "default"), "default");
assert.ok(!messages.some((message) => message && message.__sleeper === "dialog-ready"));
assert.ok(isolatedListeners.has("message"), "content bridge should still install its relay");

console.log("idle dialog behavior: ok");
