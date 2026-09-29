"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class Element {
  constructor(tag, attrs = {}) { this.tagName = tag.toUpperCase(); this.attrs = attrs; this.events = []; this.textContent = attrs.text || ""; this.innerText = this.textContent; this.id = attrs.id || ""; this.name = attrs.name || ""; this.type = attrs.type || ""; this.value = attrs.value || ""; this.disabled = false; }
  getAttribute(name) { return this.attrs[name] || null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  hasAttribute(name) { return Object.hasOwn(this.attrs, name); }
  closest() { return null; }
  focus() { this.focused = true; }
  click() { this.clicked = true; }
  scrollIntoView() {}
  getBoundingClientRect() { return { width: 1, height: 1 }; }
  dispatchEvent(event) { this.events.push(event.type); return true; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
}
class Input extends Element {}
class Textarea extends Element {}
class Select extends Element {}
class Event { constructor(type) { this.type = type; } }
class KeyboardEvent extends Event {}
class MouseEvent extends Event {}
class DragEvent extends Event {}
class DataTransfer { constructor() { this.files = []; this.items = { add: (file) => this.files.push(file) }; } }

const fileInput = new Input("input", { type: "file", id: "file" });
const search = new Input("input", { id: "search", placeholder: "Search" });
const source = new Element("button", { "data-sleeper-ref": "sleeper-1", text: "Source" });
const target = new Element("div", { "data-sleeper-ref": "sleeper-2", text: "Target" });
const form = new Element("form");
form.querySelectorAll = (selector) => selector.includes("input") ? [search] : [];
const all = [search, source, target, form];
const document = {
  activeElement: source,
  body: new Element("body"),
  title: "fixture",
  querySelector(selector) {
    if (selector === "#file") return fileInput;
    if (selector === "#search") return search;
    if (selector === "form") return form;
    const ref = selector.match(/^\[data-sleeper-ref="(.+)"\]$/);
    return ref ? all.find((element) => element.getAttribute("data-sleeper-ref") === ref[1]) || null : null;
  },
  querySelectorAll(selector) {
    if (selector === "body *" || selector === "*") return all;
    const found = this.querySelector(selector);
    return found ? [found] : [];
  },
};
const context = { document, CSS: { escape: (value) => value }, Element, HTMLElement: Element, HTMLInputElement: Input, HTMLTextAreaElement: Textarea, Event, KeyboardEvent, MouseEvent, DragEvent, DataTransfer, File: require("buffer").File, atob, window: { addEventListener() {}, removeEventListener() {}, postMessage() {} }, location: { href: "http://fixture/" }, setInterval, clearInterval, setTimeout, clearTimeout, Promise, Array, Object, String, Number, Error };
vm.createContext(context);
context.globalThis = context;
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "extension", "locators.js"), "utf8"), context);
const handlers = vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "extension", "sleeper.js"), "utf8"), context);

(async () => {
await handlers.type({ selector: "#search", text: "css value" });
assert.strictEqual(search.value, "css value", "CSS type writes its action value");
await handlers.type({ role: "textbox", name: "Search", text: "semantic value" });
assert.strictEqual(search.value, "semantic value", "semantic type does not use its value as locator text");
await handlers.type({ role: "textbox", name: "Search", text: "" });
assert.strictEqual(search.value, "", "empty type value is supported");
handlers.keys({ keys: ["Enter"] });
assert.ok(source.events.includes("keydown"), "keys defaults to active element");
assert.strictEqual(handlers.forms({ role: "form" }).count, 1, "forms resolves semantic scope");
handlers.drag({ source: "@sleeper-1", target: "@sleeper-2" });
assert.ok(source.events.includes("dragstart") && target.events.includes("drop"), "drag resolves snapshot references");
console.log("locator handlers: ok");

  assert.throws(() => handlers.upload({ selector: "#file", files: ["fake.txt"] }), /file contents required/);
  assert.strictEqual(fileInput.files, undefined, "rejected upload leaves input unchanged");
  const bytes = Buffer.from([0, 1, 127, 128, 255]);
  handlers.upload({ selector: "#file", files: [{ name: "bytes.bin", content_base64: bytes.toString("base64"), mime_type: "application/octet-stream" }] });
  assert.deepStrictEqual(Buffer.from(await fileInput.files[0].arrayBuffer()), bytes);
  assert.deepStrictEqual(fileInput.events, ["input", "change"]);
  const previous = fileInput.files;
  assert.throws(() => handlers.upload({ selector: "#file", files: [{ name: "bad", content_base64: "%not-base64%" }] }), /invalid base64/);
  assert.strictEqual(fileInput.files, previous, "invalid upload preserves selected files");

  const visibleWait = await handlers.waitUntil({ selector: "#search", state: "visible", timeout: 50 });
  assert.strictEqual(visibleWait.satisfied, true, "structured visible wait resolves without dynamic code");
  search.setAttribute("data-ready", "yes");
  const attributeWait = await handlers.waitUntil({
    condition: { selector: "#search", attribute: "data-ready", value: "yes" },
    timeout: 50,
  });
  assert.strictEqual(attributeWait.satisfied, true, "structured attribute wait resolves");
  await assert.rejects(
    handlers.waitUntil({ predicate: "document.title === 'fixture'", timeout: 50 }),
    /unavailable in the signed Firefox build/,
  );
  assert.throws(() => handlers.exec({ code: "1 + 1" }), /unavailable in the signed Firefox build/);

  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "extension", "dynamic_code.js"), "utf8"), context);
  assert.strictEqual(handlers.exec({ code: "1 + 1" }), 2, "Chromium adapter retains arbitrary exec");
  const predicateWait = await handlers.waitUntil({ predicate: "document.title === 'fixture'", timeout: 50 });
  assert.strictEqual(predicateWait.satisfied, true, "Chromium adapter retains predicate waits");
  console.log("upload byte integrity: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
