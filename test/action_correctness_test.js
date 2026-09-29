"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class EventTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, fn) {
    const entries = this.listeners.get(type) || [];
    entries.push(fn);
    this.listeners.set(type, entries);
  }
  removeEventListener(type, fn) {
    const entries = this.listeners.get(type) || [];
    this.listeners.set(type, entries.filter((entry) => entry !== fn));
  }
  dispatchEvent(event) {
    event.target = this;
    for (const fn of this.listeners.get(event.type) || []) fn(event);
    return !event.defaultPrevented;
  }
}

class TestEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = !!options.bubbles;
    this.cancelable = !!options.cancelable;
    this.defaultPrevented = false;
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
}
class KeyboardEvent extends TestEvent {
  constructor(type, options = {}) { super(type, options); this.key = options.key; }
}
class MouseEvent extends TestEvent {}
class DragEvent extends TestEvent {}
class DataTransfer { constructor() { this.files = []; this.items = { add: (file) => this.files.push(file) }; } }

class Element extends EventTarget {
  constructor(tag, attrs = {}) {
    super();
    this.tagName = tag.toUpperCase();
    this.attrs = attrs;
    this.id = attrs.id || "";
    this.type = attrs.type || "";
    this.value = attrs.value || "";
    this.textContent = attrs.text || "";
    this.innerText = this.textContent;
    this.disabled = false;
    this.checked = !!attrs.checked;
    this.form = null;
  }
  getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  hasAttribute(name) { return Object.hasOwn(this.attrs, name); }
  closest(selector) { return selector === "form" ? this.form : null; }
  focus() { document.activeElement = this; }
  click() { this.clicked = (this.clicked || 0) + 1; }
  scrollIntoView() {}
  getBoundingClientRect() { return { width: 1, height: 1 }; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
class Input extends Element {}
class Textarea extends Element {}

const input = new Input("input", { id: "search", type: "search" });
const form = new Element("form");
input.form = form;
form.requestSubmit = () => { form.submissions = (form.submissions || 0) + 1; };
let dynamic = [];

const document = new EventTarget();
document.activeElement = input;
document.body = new Element("body");
document.documentElement = new Element("html");
document.title = "fixture";
document.readyState = "complete";
document.visibilityState = "visible";
document.hasFocus = () => true;
document.cookie = "";
document.querySelector = (selector) => selector === "#search" ? input : dynamic.find((el) => el.id === selector.slice(1)) || null;
document.querySelectorAll = (selector) => {
  if (selector === "#search") return [input];
  if (selector === "body *" || selector === "*") return [input, form, ...dynamic];
  const found = document.querySelector(selector);
  return found ? [found] : [];
};

let observers = [];
class MutationObserver {
  constructor(callback) { this.callback = callback; }
  observe() { observers.push(this); }
  disconnect() { observers = observers.filter((observer) => observer !== this); }
}

const windowTarget = new EventTarget();
windowTarget.postMessage = () => {};
windowTarget.innerHeight = 800;
windowTarget.scrollBy = () => {};
windowTarget.scrollTo = () => {};

const location = { href: "https://example.test/search" };
const context = {
  document,
  location,
  history: { back() {} },
  CSS: { escape: (value) => value },
  Element,
  HTMLElement: Element,
  HTMLInputElement: Input,
  HTMLTextAreaElement: Textarea,
  Event: TestEvent,
  KeyboardEvent,
  MouseEvent,
  DragEvent,
  DataTransfer,
  File: require("buffer").File,
  atob,
  window: windowTarget,
  MutationObserver,
  setInterval,
  clearInterval,
  setTimeout,
  clearTimeout,
  Promise,
  Array,
  Object,
  String,
  Number,
  Error,
};
vm.createContext(context);
context.globalThis = context;
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "extension", "locators.js"), "utf8"), context);
const handlers = vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "extension", "sleeper.js"), "utf8"), context);

(async () => {
  const result = handlers.press({ key: "Enter", selector: "#search" });
  assert.strictEqual(form.submissions, 1, "Enter on a single-line form control performs its semantic default action");
  assert.strictEqual(result.submitted, true, "press reports the semantic submission it performed");

  form.submissions = 0;
  const prevent = (event) => event.preventDefault();
  input.addEventListener("keydown", prevent);
  const prevented = handlers.press({ key: "Enter", selector: "#search" });
  input.removeEventListener("keydown", prevent);
  assert.strictEqual(form.submissions, 0, "preventDefault suppresses the semantic fallback");
  assert.strictEqual(prevented.defaultPrevented, true, "press reports that the page canceled the action");

  const originalRequestSubmit = form.requestSubmit;
  form.requestSubmit = () => { throw new Error("invalid form"); };
  const failedSubmit = handlers.press({ key: "Enter", selector: "#search" });
  form.requestSubmit = originalRequestSubmit;
  assert.strictEqual(failedSubmit.submitted, false, "press does not report success when semantic submission fails");
  assert.strictEqual(failedSubmit.submission, null, "failed semantic submission has no submission method");

  form.submissions = 0;
  const handled = () => form.dispatchEvent(new TestEvent("submit", { cancelable: true }));
  input.addEventListener("keydown", handled);
  const alreadyHandled = handlers.press({ key: "Enter", selector: "#search" });
  input.removeEventListener("keydown", handled);
  assert.strictEqual(form.submissions, 0, "a page-handled submit is not repeated by the fallback");
  assert.strictEqual(alreadyHandled.submission, "event", "press reports the page-handled submission");

  const waitStarted = Date.now();
  const pending = handlers.waitFor({ selector: "#ready", timeout: 500, interval: 1000 });
  setTimeout(() => {
    dynamic.push(new Element("div", { id: "ready" }));
    observers.slice().forEach((observer) => observer.callback([{ type: "childList" }]));
  }, 10);
  const waited = await pending;
  assert.strictEqual(waited.found, true);
  assert.ok(Date.now() - waitStarted < 150, "DOM mutation wakes the wait before its polling interval");

  const aliasPending = handlers.waitFor({ selector: "#alias-ready", timeout_ms: 500, interval_ms: 1000 });
  setTimeout(() => {
    dynamic.push(new Element("div", { id: "alias-ready" }));
    observers.slice().forEach((observer) => observer.callback([{ type: "childList" }]));
  }, 10);
  const aliasResult = await aliasPending;
  assert.strictEqual(aliasResult.found, true, "waitFor accepts timeout_ms and interval_ms aliases");

  location.href = "https://example.test/start";
  const urlPending = handlers.wait_url({ pattern: "/done", timeout_ms: 500, interval: 1000 });
  setTimeout(() => {
    location.href = "https://example.test/done";
    windowTarget.dispatchEvent(new TestEvent("hashchange"));
  }, 10);
  const urlResult = await urlPending;
  assert.strictEqual(urlResult.url, "https://example.test/done");

  await assert.rejects(
    handlers.wait_url({ pattern: "/missing", timeout_ms: 10, interval: 1000 }),
    /current=https:\/\/example\.test\/done readyState=complete/,
    "timeout errors report the last URL and document state",
  );

  const navigated = handlers.navigate({ url: "https://example.test/next" });
  assert.strictEqual(navigated.accepted, true);
  assert.strictEqual(navigated.url, "https://example.test/next");

  function nativeControl(id, type, checked) {
    const control = new Input("input", { id, type, checked });
    control.click = function () {
      this.clicked = (this.clicked || 0) + 1;
      if (this.type === "checkbox") this.checked = !this.checked;
      if (this.type === "radio") this.checked = true;
      this.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      this.dispatchEvent(new TestEvent("change", { bubbles: true }));
    };
    dynamic.push(control);
    return control;
  }

  const checkbox = nativeControl("agree", "checkbox", false);
  let checkResult = handlers.check({ selector: "#agree" });
  assert.strictEqual(checkResult.checked, true);
  assert.strictEqual(checkResult.changed, true);
  assert.strictEqual(checkbox.clicked, 1, "checking uses one native activation");
  checkResult = handlers.check({ selector: "#agree" });
  assert.strictEqual(checkResult.checked, true);
  assert.strictEqual(checkResult.changed, false);
  assert.strictEqual(checkbox.clicked, 1, "checking an already checked box is a no-op");
  checkResult = handlers.uncheck({ selector: "#agree" });
  assert.strictEqual(checkResult.checked, false);
  assert.strictEqual(checkResult.changed, true);
  assert.strictEqual(checkbox.clicked, 2, "unchecking uses one native activation");

  const radio = nativeControl("choice", "radio", true);
  let radioChanges = 0;
  radio.addEventListener("change", () => { radioChanges += 1; });
  checkResult = handlers.uncheck({ selector: "#choice" });
  assert.strictEqual(checkResult.checked, false);
  assert.strictEqual(checkResult.changed, true);
  assert.strictEqual(radio.clicked || 0, 0, "radio uncheck does not use an ineffective click");
  assert.strictEqual(radioChanges, 1, "radio uncheck emits change");

  const doubleTarget = new Element("button", { id: "double" });
  dynamic.push(doubleTarget);
  let clickEvents = 0;
  let doubleEvents = 0;
  doubleTarget.addEventListener("click", () => { clickEvents += 1; });
  doubleTarget.addEventListener("dblclick", () => { doubleEvents += 1; });
  handlers.dblclick({ selector: "#double" });
  assert.strictEqual(doubleEvents, 1, "dblclick emits one double-click event");
  assert.strictEqual(clickEvents, 0, "dblclick does not append a single-click activation");

  console.log("action correctness: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
