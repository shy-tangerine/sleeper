// Regression: text search (wait_text / find_text) must only match RENDERED
// page text. Raw <script> or <style> source and display:none subtrees made
// waits "succeed" while the visible page never changed. Pins isRenderedElement
// and the includeHidden opt-in in elementsByText.
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(require("path").join(__dirname, "..", "extension", "sleeper.js"), "utf8");
const start = source.indexOf("function isActivityElement");
const end = source.indexOf("function safeJson", start);
assert.ok(start > 0 && end > start, "extracted functions found in sleeper.js");

function el(tag, attrs = {}, text = "") {
  return { tagName: tag, innerText: text, contains: () => false, ...attrs };
}

function harness(markup) {
  // Minimal style resolver: parses inline style="display:none"-style declarations.
  const getComputedStyle = (node) => {
    const out = { display: "block", visibility: "visible" };
    for (const decl of String(node.style || "").split(";")) {
      const [prop, value] = decl.split(":").map((s) => (s || "").trim());
      if (prop in out) out[prop] = value;
    }
    return out;
  };
  const context = { document: markup, getComputedStyle, console };
  vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.f = { elementsByText, isRenderedElement };`, context);
  return context.f;
}

const markup = {
  querySelectorAll: () => "body *".length >= 0 ? [
    el("P", {}, "Delayed state ready"),
    el("SCRIPT", {}, 'setTimeout(() => document.querySelector("#delayed").textContent = "Delayed state ready", 250);'),
    el("STYLE", {}, ".delayed::after { content: 'Delayed state ready'; }"),
    el("P", { style: "display:none" }, "Hidden ready"),
  ] : [],
  body: {},
};

(async () => {
  const f = harness(markup);

  // 1. Rendered text matches.
  const visible = f.elementsByText("Delayed state ready");
  assert.strictEqual(visible.length, 1, "only the rendered <p> matches");
  assert.strictEqual(visible[0].tagName, "P");

  // 2. Script/style source and display:none elements never match by default.
  assert.strictEqual(f.elementsByText("querySelector").length, 0, "script source excluded");
  assert.strictEqual(f.elementsByText("::after").length, 0, "style source excluded");
  assert.strictEqual(f.elementsByText("Hidden ready").length, 0, "display:none excluded");

  // 3. includeHidden deliberately searches hidden content.
  const withHidden = f.elementsByText("Hidden ready", { includeHidden: true });
  assert.strictEqual(withHidden.length, 1, "includeHidden reaches hidden element");
  assert.strictEqual(f.isRenderedElement(el("DIV", { style: "visibility:hidden" })), false, "visibility:hidden excluded");

  console.log("waittext rendered-only behavior: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
