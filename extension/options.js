(() => {
  const ui = {
    entries: document.getElementById("entries"),
    empty: document.getElementById("empty"),
    saved: document.getElementById("saved"),
    connection: document.getElementById("connection"),
    connectionMode: document.getElementById("connection-mode"),
    connectionStatus: document.getElementById("connection-status"),
    connectionAction: document.getElementById("connection-action"),
    connectionApproval: document.getElementById("connection-approval"),
    connectionProposal: document.getElementById("connection-proposal"),
    approveConnection: document.getElementById("approve-connection"),
    dismissConnection: document.getElementById("dismiss-connection"),
    activity: document.getElementById("activity-status"),
    browserId: document.getElementById("browser-id"),
    daemonHelp: document.getElementById("daemon-help"),
    visibleActivity: document.getElementById("visible-activity"),
    more: document.getElementById("more"),
    previewLabel: document.getElementById("preview-label"),
    scopeButtons: [...document.querySelectorAll('[data-setting="scope"]')],
    focusButtons: [...document.querySelectorAll('[data-setting="focus"]')]
  };
  const VISIBLE_ACTIONS = 10;
  const SENSITIVE_ACTIONS = new Set(["type", "fill", "fillform", "upload"]);
  const runtime = { daemonConnected: false, actionInProgress: false };
  const hasExtensionStorage = typeof chrome !== "undefined" && Boolean(chrome.storage?.local);
  let currentLog = [];
  let showAll = false;

  function readStorage(keys) {
    return new Promise((resolve, reject) => {
      chrome.storage.local.get(keys, (value) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(value);
      });
    });
  }

  function writeStorage(value) {
    if (!hasExtensionStorage) return Promise.resolve(value);
    return new Promise((resolve, reject) => {
      chrome.storage.local.set(value, () => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve();
      });
    });
  }

  function announce(message) {
    ui.saved.textContent = message;
    window.setTimeout(() => {
      if (ui.saved.textContent === message) ui.saved.textContent = "";
    }, 1800);
  }

  async function save(value, message) {
    try {
      await writeStorage(value);
      announce(message);
    } catch (error) {
      announce(`Could not save: ${error.message}`);
    }
  }

  function selectSetting(buttons, value) {
    buttons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.value === value));
    });
  }

  function timestamp(value) {
    if (typeof value === "number") return value;
    return Date.parse(value) || 0;
  }

  function actionName(item, active) { return SleeperActionLabels.describe(item, active); }

  function outcome(item) {
    const raw = String((item && item.status) || "").toLowerCase();
    if (raw === "running" || raw === "pending" || raw === "started") return "Running";
    if (raw === "failed" || raw === "error" || (item && item.ok === false)) return "Failed";
    if (["success", "succeeded", "complete", "completed"].includes(raw) || (item && item.ok === true)) return "Done";
    return "Recorded";
  }

  function duration(item) {
    const milliseconds = Number(item && item.duration_ms);
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return "";
    return milliseconds < 1000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
  }

  function safeUrl(value) {
    try {
      const parsed = new URL(String(value));
      return `${parsed.hostname}${parsed.pathname === "/" ? "" : parsed.pathname}`;
    } catch (_) {
      return "";
    }
  }

  function safeTarget(item) {
    const cmd = String((item && (item.cmd || item.action)) || "").toLowerCase();
    if (SENSITIVE_ACTIONS.has(cmd)) return "Content hidden";
    if (item && item.target) return String(item.target).slice(0, 96);
    const url = item && (item.url || item.result_url);
    if (url) return safeUrl(url);
    return item && item.tab != null && item.tab !== "" ? `Tab ${item.tab}` : "Browser";
  }

  function renderLog(log) {
    currentLog = log.slice().sort((left, right) => timestamp(right.ts) - timestamp(left.ts));
    const visible = showAll ? currentLog : currentLog.slice(0, VISIBLE_ACTIONS);
    ui.entries.textContent = "";
    ui.empty.hidden = currentLog.length > 0;

    for (const item of visible) {
      const row = document.createElement("li");
      const command = document.createElement("strong");
      const details = document.createElement("span");
      const time = document.createElement("span");
      const status = outcome(item);
      const elapsed = duration(item);
      command.className = "command-name";
      command.textContent = actionName(item, status === "Running");
      details.className = "target";
      details.textContent = [status, elapsed, safeTarget(item)].filter(Boolean).join(" · ");
      time.className = "time";
      time.textContent = new Date(item.ts).toLocaleString();
      row.className = `action-row action-${status.toLowerCase()}`;
      row.append(command, details, time);
      ui.entries.append(row);
    }

    ui.more.hidden = currentLog.length <= VISIBLE_ACTIONS;
    ui.more.textContent = showAll
      ? "Show latest 10"
      : `View all ${currentLog.length} actions`;
  }

  function connectionName(endpoint) {
    if (!endpoint || !endpoint.ok || !endpoint.http) return "This computer";
    try {
      const hostname = new URL(endpoint.http).hostname.replace(/^\[|\]$/g, "");
      if (SleeperDaemonEndpoint.loopback(hostname)) return "This computer";
      const name = hostname.toLowerCase().endsWith(".ts.net")
        ? hostname.slice(0, -".ts.net".length)
        : hostname;
      const first = name.split(".")[0].trim();
      return first && /^[a-z0-9][a-z0-9-]*$/i.test(first) ? first : "Remote computer";
    } catch (_) {
      return "Remote computer";
    }
  }

  function renderConnection(endpoint) {
    const valid = endpoint && endpoint.ok;
    const mode = valid && endpoint.remote ? "Tailscale" : "Local";
    ui.connectionMode.textContent = `${mode} · ${connectionName(endpoint)}`;
    let statusLabel = ui.connectionStatus.querySelector("span");
    if (!statusLabel) {
      statusLabel = document.createElement("span");
      ui.connectionStatus.appendChild(statusLabel);
    }
    statusLabel.textContent = runtime.daemonConnected ? "Connected" : "Offline";
    ui.connectionStatus.classList.toggle("connected", runtime.daemonConnected);
    ui.connectionAction.textContent = runtime.daemonConnected ? "Reconnect" : (valid ? "Reconnect" : "Set up connection");
  }

  function renderPendingOffer(httpUrl) {
    if (!ui.connectionApproval) return;
    let label = "";
    try {
      const url = new URL(String(httpUrl || ""));
      if (url.protocol === "https:" && url.hostname.toLowerCase().endsWith(".ts.net") && url.port === "8790") {
        label = `${url.hostname}:8790`;
      }
    } catch (_) {}
    ui.connectionApproval.hidden = !label;
    if (label) ui.connectionProposal.textContent = `Proposed host: ${label}`;
  }

  function renderRuntime(endpoint) {
    ui.connection.lastChild.textContent = runtime.daemonConnected ? "Bridge connected" : "Bridge offline";
    ui.connection.classList.toggle("connected", runtime.daemonConnected);
    ui.activity.textContent = runtime.actionInProgress ? "An action is running now." : "No action is running.";
    renderConnection(endpoint || runtime.endpoint);
  }

  // Single seam for every place that resolves an endpoint and reflects it in
  // the connection row (load, manual save, storage change events).
  function adoptEndpoint(endpoint) {
    runtime.endpoint = endpoint;
    renderConnection(endpoint);
  }

  function endpointHelp(endpoint, localText) {
    return endpoint.ok && endpoint.remote
      ? "Connected through your private Tailscale network."
      : localText;
  }

  function previewExamples(now) {
    return [
      ["click", "18", 1],
      ["type", "18", 2],
      ["snapshot", "18", 4],
      ["read", "18", 7],
      ["tabs", "", 11],
      ["goto", "21", 16],
      ["find", "21", 22],
      ["scroll", "21", 31],
      ["shot", "21", 46],
      ["wait", "21", 64],
      ["network", "", 91],
      ["state", "", 126]
    ].map(([cmd, tab, seconds]) => ({ cmd, tab, ts: now - seconds * 1000 }));
  }

  // Rendering shown when the settings page runs outside the extension
  // (no chrome.storage): static preview values, no persistence.
  function renderPreviewMode() {
    selectSetting(ui.scopeButtons, "all_tabs");
    selectSetting(ui.focusButtons, "needed");
    ui.visibleActivity.checked = true;
    ui.browserId.textContent = "preview-installation";
    ui.previewLabel.hidden = false;
    renderLog(previewExamples(Date.now()));
    adoptEndpoint(SleeperDaemonEndpoint.defaults());
    renderRuntime(runtime.endpoint);
    focusLogTarget();
  }

  function applyLoadedSettings(value) {
    applyAccessScope(value.access_scope || "all_tabs");
    applyFocusMode(value.focus_mode || "needed");
    ui.visibleActivity.checked = value.visible_activity !== false;
    ui.browserId.textContent = value.browser_instance_id || "Unavailable";
    const endpoint = SleeperDaemonEndpoint.validate(value.daemon_http_url, value.daemon_ws_url, value.daemon_auth_token);
    ui.daemonHelp.textContent = endpointHelp(endpoint, "Localhost is the default. Run `sleeper mobile setup` for a phone.");
    renderLog(Array.isArray(value.action_log) ? value.action_log : []);
    runtime.daemonConnected = Boolean(value.daemon_connected);
    runtime.actionInProgress = Boolean(value.action_in_progress);
    adoptEndpoint(endpoint);
    renderRuntime(endpoint);
    focusLogTarget();
  }

  async function load() {
    if (!hasExtensionStorage) {
      renderPreviewMode();
      return;
    }
    try {
      const value = await readStorage([
        "access_scope",
        "focus_mode",
        "visible_activity",
        "browser_instance_id",
        "daemon_http_url",
        "daemon_ws_url",
        "daemon_auth_token",
        "pending_tailscale_http_url",
        "daemon_connected",
        "action_in_progress",
        "action_log"
      ]);
      applyLoadedSettings(value);
      renderPendingOffer(value.pending_tailscale_http_url);
    } catch (error) {
      announce(`Could not load settings: ${error.message}`);
    }
  }

  function focusLogTarget() {
    if (location.hash === "#log") {
      const target = document.getElementById("log");
      if (!target) return;
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: "start" });
    }
  }

  // Shared appliers: click handlers and remote storage changes must paint the
  // same state, so both route through one function per setting.
  function applyAccessScope(value) {
    selectSetting(ui.scopeButtons, value);
  }

  function applyFocusMode(value) {
    selectSetting(ui.focusButtons, value);
  }

  function handleScopeClick(button) {
    applyAccessScope(button.dataset.value);
    save(
      { access_scope: button.dataset.value },
      button.dataset.value === "disabled" ? "Commands paused." : "Access setting saved."
    );
  }

  function handleFocusClick(button) {
    applyFocusMode(button.dataset.value);
    save({ focus_mode: button.dataset.value }, "Focus setting saved.");
  }

  function reconnectOrSetup() {
    if (!hasExtensionStorage) return;
    chrome.runtime.sendMessage({ type: "sleeper-reconnect" }, (response) => {
      const error = chrome.runtime.lastError;
      announce(error || !response || response.ok !== true ? "Could not reconnect." : "Reconnecting…");
    });
  }

  function respondToPendingOffer(type, successMessage) {
    chrome.runtime.sendMessage({ type }, (response) => {
      const error = chrome.runtime.lastError;
      if (error || !response || response.ok !== true) {
        announce(error ? "Could not update the pending connection." : response.error);
        return;
      }
      renderPendingOffer("");
      announce(successMessage);
    });
  }

  function clearActionLog() {
    if (!hasExtensionStorage) renderLog([]);
    save({ action_log: [] }, "Recent actions cleared.");
  }

  function toggleShowAll() {
    showAll = !showAll;
    renderLog(currentLog);
  }

  // The background script may change any setting while this page is open;
  // mirror every relevant key into the UI without persisting anything.
  function handleStorageChanges(changes) {
    if (changes.access_scope) applyAccessScope(changes.access_scope.newValue);
    if (changes.focus_mode) applyFocusMode(changes.focus_mode.newValue);
    if (changes.browser_instance_id) ui.browserId.textContent = changes.browser_instance_id.newValue;
    if (changes.action_log) renderLog(changes.action_log.newValue || []);
    if (changes.daemon_connected) runtime.daemonConnected = Boolean(changes.daemon_connected.newValue);
    if (changes.action_in_progress) runtime.actionInProgress = Boolean(changes.action_in_progress.newValue);
    if (changes.pending_tailscale_http_url) renderPendingOffer(changes.pending_tailscale_http_url.newValue);
    if (changes.daemon_http_url || changes.daemon_ws_url || changes.daemon_auth_token) {
      readStorage(["daemon_http_url", "daemon_ws_url", "daemon_auth_token"])
        .then((value) => adoptEndpoint(SleeperDaemonEndpoint.validate(
          value.daemon_http_url, value.daemon_ws_url, value.daemon_auth_token
        )), () => {});
    }
    if (changes.daemon_connected || changes.action_in_progress) renderRuntime(runtime.endpoint);
    if (changes.visible_activity) ui.visibleActivity.checked = changes.visible_activity.newValue !== false;
  }

  window.addEventListener("hashchange", focusLogTarget);

  ui.scopeButtons.forEach((button) => {
    button.addEventListener("click", () => handleScopeClick(button));
  });

  ui.focusButtons.forEach((button) => {
    button.addEventListener("click", () => handleFocusClick(button));
  });

  ui.visibleActivity.addEventListener("change", () => {
    save({ visible_activity: ui.visibleActivity.checked }, "Activity cue setting saved.");
  });
  ui.connectionAction.addEventListener("click", () => reconnectOrSetup());
  ui.approveConnection.addEventListener("click", () => {
    respondToPendingOffer("approve-tailscale-setup", "Daemon connection approved.");
  });
  ui.dismissConnection.addEventListener("click", () => {
    respondToPendingOffer("dismiss-tailscale-setup", "Daemon connection request dismissed.");
  });
  document.getElementById("clear").addEventListener("click", clearActionLog);
  ui.more.addEventListener("click", toggleShowAll);

  if (hasExtensionStorage) chrome.storage.onChanged.addListener(handleStorageChanges);

  load();
})();
