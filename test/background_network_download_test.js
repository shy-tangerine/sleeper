"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const context = { Map, Promise, setTimeout, clearTimeout, setInterval, clearInterval };
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "..", "extension", "background_network.js"), "utf8"),
  context
);

function event() {
  const listeners = [];
  return {
    addListener(listener) { listeners.push(listener); },
    emit(value) { for (const listener of listeners) listener(value); },
  };
}

function harness(searchMode = "callback") {
  let searchItems = [];
  const downloads = {
    onCreated: event(),
    onMoved: event(), onAttached: event(), onDetached: event(),
    onChanged: event(),
    search(_query, callback) {
      if (searchMode === "promise") return Promise.resolve(searchItems);
      callback(searchItems);
    },
    setSearchItems(items) { searchItems = items; },
  };
  const capture = context.SleeperBackgroundNetwork.createNetworkCapture({
    downloads,
    webRequest: { onBeforeRequest: event(), onCompleted: event(), onErrorOccurred: event() },
  });
  return { capture, downloads };
}

async function main() {
  const h = harness();
  const success = h.capture.waitForDownload("success.txt", 100);
  h.downloads.onCreated.emit({ id: 1, url: "http://127.0.0.1/success.txt", filename: "/tmp/success.txt", state: "in_progress" });
  h.downloads.onChanged.emit({ id: 1, state: { current: "complete" } });
  assert.equal((await success).matched, true);
  const staleSuccess = h.capture.waitForDownload("success.txt", 20);
  assert.equal((await staleSuccess).matched, false);

  const failure = h.capture.waitForDownload("failure.txt", 100);
  h.downloads.onCreated.emit({ id: 2, url: "http://127.0.0.1/failure.txt", filename: "/tmp/failure.txt", state: "in_progress" });
  h.downloads.onChanged.emit({ id: 2, state: { current: "interrupted" } });
  const interrupted = await failure;
  assert.equal(interrupted.matched, false);
  assert.equal(interrupted.download.state, "interrupted");
  const staleFailure = await h.capture.waitForDownload("failure.txt", 20);
  assert.equal(staleFailure.matched, false);
  assert.equal(staleFailure.download, undefined);

  h.downloads.onCreated.emit({ id: 3, url: "http://127.0.0.1/searched.txt", filename: "/tmp/searched.txt", state: "in_progress" });
  const searched = h.capture.waitForDownload("searched.txt", 400);
  h.downloads.setSearchItems([{ id: 3, url: "http://127.0.0.1/searched.txt", filename: "/tmp/searched.txt", state: "complete" }]);
  assert.equal((await searched).matched, true);
  h.downloads.onCreated.emit({ id: 4, url: "http://127.0.0.1/searched-failure.txt", filename: "/tmp/searched-failure.txt", state: "in_progress" });
  h.downloads.setSearchItems([{ id: 4, url: "http://127.0.0.1/searched-failure.txt", filename: "/tmp/searched-failure.txt", state: "interrupted" }]);
  const searchedFailure = await h.capture.waitForDownload("searched-failure.txt", 100);
  assert.equal(searchedFailure.matched, false);
  assert.equal(searchedFailure.download.state, "interrupted");

  const promiseSearch = harness("promise");
  promiseSearch.downloads.onCreated.emit({ id: 5, url: "http://127.0.0.1/promise.txt", filename: "/tmp/promise.txt", state: "in_progress" });
  promiseSearch.downloads.setSearchItems([{ id: 5, url: "http://127.0.0.1/promise.txt", filename: "/tmp/promise.txt", state: "complete" }]);
  assert.equal((await promiseSearch.capture.waitForDownload("promise.txt", 100)).matched, true);

  h.downloads.setSearchItems([]);
  assert.equal((await h.capture.waitForDownload("missing.txt", 10)).matched, false);
  console.log("background download waits: ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
