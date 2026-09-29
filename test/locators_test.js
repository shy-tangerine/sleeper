"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const input = {
  tagName: "INPUT", type: "text", id: "search", innerText: "", textContent: "",
  getAttribute: (name) => ({ placeholder: "Search", "data-testid": "search-box" })[name] || null,
  closest: () => null,
};
const context = {
  globalThis: {},
  CSS: { escape: (value) => value },
  document: { querySelectorAll: () => [input], querySelector: () => null },
};
vm.runInNewContext(fs.readFileSync(require("path").join(__dirname, "..", "extension", "locators.js"), "utf8"), context);
const locators = context.globalThis.SleeperLocators;

assert.strictEqual(locators.find(locators.normalize({ role: "textbox", name: "Search", text: "abc" }, "type")).length, 1, "typed value does not constrain a semantic locator");
assert.strictEqual(locators.find(locators.normalize({ role: "textbox", locator_text: "abc" }, "type")).length, 0, "explicit locator_text still constrains a semantic locator");
assert.strictEqual(locators.normalize({ selector: "#search", text: "" }, "type").text, undefined, "empty typing value is not a locator");
assert.strictEqual(locators.normalize({ text: "Search" }, "find").text, "Search", "legacy find text remains a locator");
console.log("locator boundary: ok");
