"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "extension", "action-labels.js"), "utf8"), context);

const aliases = { fillform: "fillform", findtext: "findtext", clickall: "clickall", clicktext: "clicktext", readall: "readall", select: "selectoption", wait: "waitfor", waittext: "waittext", waituntil: "waituntil", waiturl: "waiturl", waitxhr: "waitxhr", waitdialog: "waitdialog", scrolluntil: "scrolluntil" };
const tools = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "docs", "mcp-tools.json"), "utf8"));
for (const tool of tools) {
  const raw = tool.name.replace(/^sleeper_/, "");
  const compact = raw.replace(/_/g, "");
  const cmd = aliases[compact] || compact;
  for (const item of [
    { cmd, status: "running" },
    { cmd, status: "success" },
    { cmd, status: "failure", ok: false },
  ]) {
    const label = context.SleeperActionLabels.describe(item, item.status === "running");
    assert.ok(!label.startsWith("Browser action"), `${tool.name} must have a dedicated label`);
    assert.ok(!/[a-z][A-Z]|_/.test(label), `${tool.name} leaked protocol naming: ${label}`);
  }
}
assert.strictEqual(context.SleeperActionLabels.describe({ cmd: "private_internal_cmd" }, false), "Browser action finished");
console.log("action label contract: ok");
