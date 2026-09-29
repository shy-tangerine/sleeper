/* Canonical DOM locator contract shared by Sleeper action handlers. */
(function (global) {
  function roleOf(element) {
    const explicit = element.getAttribute("role");
    if (explicit) return explicit.toLowerCase();
    const tag = element.tagName.toLowerCase();
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "img") return "img";
    if (tag === "nav") return "navigation";
    if (tag === "main") return "main";
    if (tag === "header") return "banner";
    if (tag === "footer") return "contentinfo";
    if (tag === "form") return "form";
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (tag === "button") return "button";
    if (tag === "a") return "link";
    if (tag !== "input") return "";
    const type = (element.type || "text").toLowerCase();
    return ["button", "submit", "reset"].includes(type) ? "button" : type === "checkbox" || type === "radio" ? type : "textbox";
  }

  function nameOf(element) {
    const direct = element.getAttribute("aria-label") || element.getAttribute("title") || element.getAttribute("placeholder");
    if (direct) return direct.trim();
    const label = element.id && document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
    if (label) return (label.innerText || label.textContent || "").trim();
    const parent = element.closest("label");
    return parent ? (parent.innerText || parent.textContent || "").trim() : (element.innerText || element.textContent || "").trim();
  }

  function normalize(args, command) {
    const source = args || {};
    // text is an action payload for type/fill-like commands; legacy locator
    // text remains supported for find/click and every non-writing command.
    const text = source.locator_text != null ? source.locator_text : command === "type" ? undefined : source.text;
    return { selector: source.selector, role: source.role, name: source.name, label: source.label, text, testid: source.testid };
  }

  function hasSemantic(locator) {
    return !!(locator.role || locator.name || locator.label || locator.text || locator.testid);
  }

  function hasTarget(args, command) {
    const locator = normalize(args, command);
    return !!locator.selector || hasSemantic(locator);
  }

  function contains(value, needle) {
    return !needle || String(value || "").toLowerCase().includes(String(needle).toLowerCase());
  }

  function find(locator) {
    return Array.from(document.querySelectorAll("body *")).filter((element) => {
      if (locator.role && roleOf(element) !== String(locator.role).toLowerCase()) return false;
      if (locator.name && !contains(nameOf(element), locator.name)) return false;
      if (locator.label && !contains(nameOf(element), locator.label)) return false;
      if (locator.text && !contains(element.innerText || element.textContent, locator.text)) return false;
      return !locator.testid || ["data-testid", "data-test", "test-id"].some((key) => contains(element.getAttribute(key), locator.testid));
    });
  }

  function target(args, command, query) {
    const locator = normalize(args, command);
    if (hasSemantic(locator)) {
      const element = find(locator)[0];
      if (!element) throw new Error("no element matches semantic locator");
      return element;
    }
    return query(locator.selector);
  }

  function optionalTarget(args, command, query, fallback) {
    return hasTarget(args, command) ? target(args, command, query) : fallback();
  }

  global.SleeperLocators = { normalize, hasSemantic, hasTarget, find, target, optionalTarget };
}(globalThis));
