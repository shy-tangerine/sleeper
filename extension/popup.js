(() => {
  "use strict";

  const POPUP_ACTION_LIMIT = 3;
  const SENSITIVE_ACTIONS = new Set(["type", "fill", "fillform", "upload"]);
  const ui = {
    status: document.getElementById("status"),
    statusLabel: document.querySelector("#status span"),
    scope: document.getElementById("scope"),
    current: document.getElementById("current-action"),
    recent: document.getElementById("recent-actions"),
    empty: document.getElementById("no-actions")
  };

  function timestamp(value) {
    if (typeof value === "number") return value;
    return Date.parse(value) || 0;
  }

  function actionName(item, active) { return SleeperActionLabels.describe(item, active); }

  function safeUrl(value) {
    try {
      const parsed = new URL(String(value));
      return `${parsed.hostname}${parsed.pathname === "/" ? "" : parsed.pathname}`;
    } catch (_) {
      return "";
    }
  }

  // Short, human site name: "example.com" — no paths, no query strings.
  function friendlySite(value) {
    const site = safeUrl(value);
    return site ? site.split("/")[0] : "";
  }

  function safeTarget(item) {
    const cmd = String((item && (item.cmd || item.action)) || "").toLowerCase();
    if (SENSITIVE_ACTIONS.has(cmd)) return "Content hidden";
    // Prefer the site visited over raw selectors — "example.com" reads
    // naturally; "#ctl00$main$btn" does not.
    const url = item && (item.url || item.result_url);
    if (url) {
      const site = friendlySite(url);
      if (site) return site;
    }
    if (item && item.target) return String(item.target).slice(0, 80);
    return item && item.tab != null && item.tab !== "" ? `Tab ${item.tab}` : "Browser";
  }

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

  function sorted(log) {
    return (Array.isArray(log) ? log : []).slice().sort((left, right) => timestamp(right.ts) - timestamp(left.ts));
  }

  function renderRecent(log) {
    const recent = sorted(log).slice(0, POPUP_ACTION_LIMIT);
    ui.recent.textContent = "";
    ui.empty.hidden = recent.length > 0;
    for (const item of recent) {
      const row = document.createElement("li");
      const label = document.createElement("strong");
      const meta = document.createElement("span");
      const state = outcome(item);
      const elapsed = duration(item);
      label.textContent = actionName(item, state === "Running");
      meta.textContent = [state, elapsed, safeTarget(item)].filter(Boolean).join(" · ");
      row.className = `action-row action-${state.toLowerCase()}`;
      row.append(label, meta);
      ui.recent.append(row);
    }
  }

  function renderCurrent(value, log) {
    const active = Boolean(value.action_in_progress || value.current_action || value.action_current);
    const item = value.current_action || value.action_current || sorted(log)[0];
    ui.current.textContent = active ? actionName(item, true) : "Idle";
    ui.current.classList.toggle("is-running", active);
  }

  function render(value) {
    ui.statusLabel.textContent = value.daemon_connected ? "Bridge connected" : "Bridge offline";
    ui.status.classList.toggle("connected", Boolean(value.daemon_connected));
    const labels = { active_tab: "Active tab only", all_tabs: "All tabs", disabled: "Paused" };
    ui.scope.textContent = labels[value.access_scope || "all_tabs"];
    renderCurrent(value, value.action_log);
    renderRecent(value.action_log);
  }

  const keys = ["daemon_connected", "access_scope", "action_in_progress", "current_action", "action_current", "action_log"];
  chrome.storage.local.get(keys, render);
  chrome.storage.onChanged.addListener((changes) => {
    if (!changes.action_in_progress && !changes.current_action && !changes.action_current && !changes.action_log && !changes.daemon_connected && !changes.access_scope) return;
    chrome.storage.local.get(keys, render);
  });

  document.getElementById("options").addEventListener("click", () => chrome.runtime.openOptionsPage());
  document.getElementById("log").addEventListener("click", () => {
    chrome.tabs.create({ url: chrome.runtime.getURL("options.html#log") });
  });
})();
