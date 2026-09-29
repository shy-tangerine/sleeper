const assert = require("assert");
const screenshot = require("../extension/screenshot.js");

const prefix = "data:image/png;base64,";
const cap = screenshot.MAX_SCREENSHOT_DATA_URL_CHARS;
const replies = [];
const success = (id, result) => replies.push({ id, ok: true, result });
const failure = (id, error) => replies.push({ id, ok: false, error });

screenshot.sendResult(success, failure, 1, prefix + "A".repeat(cap - prefix.length));
screenshot.sendResult(success, failure, 2, prefix + "A".repeat(cap - prefix.length + 1));
screenshot.sendResult(success, failure, 3, "data:text/plain;base64,QQ==");

assert.deepStrictEqual(replies[0], { id: 1, ok: true, result: { dataUrl: prefix + "A".repeat(cap - prefix.length) } });
assert.deepStrictEqual(replies[1], { id: 2, ok: false, error: `screenshot exceeds ${cap} byte transport limit` });
assert.deepStrictEqual(replies[2], { id: 3, ok: false, error: "screenshot capture returned an invalid PNG artifact" });
console.log("screenshot transport contract: ok");
