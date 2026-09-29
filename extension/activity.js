/* Sleeper activity cues: small, transient visuals for automation actions. */
(function (root) {
  "use strict";
  const timers = new Set();
  const cues = new Map();
  let host = null;
  let shadow = null;
  let enabled = true;
  let reducedMotion = false;
  let lastAction = 0;
  const STATUS_CUE_MS = 4000;
  const SENSITIVE_ACTIONS = new Set(["type", "fill", "fillform", "upload"]);

  function canShow() {
    return enabled && document.visibilityState === "visible" && document.hasFocus();
  }
  function schedule(callback, delay) {
    let timer;
    timer = setTimeout(() => { timers.delete(timer); callback(); }, delay);
    timers.add(timer);
    return timer;
  }
  function ensureLayer() {
    if (host && host.isConnected) return shadow;
    host = document.createElement("div");
    host.setAttribute("data-sleeper-activity", "true");
    host.setAttribute("aria-hidden", "true");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483646;pointer-events:none";
    shadow = host.attachShadow({ mode: "closed" });
    shadow.innerHTML = `<style>
      :host{all:initial}.cue{position:fixed;pointer-events:none;box-sizing:border-box}
      .pulse{width:28px;height:28px;border:2px solid #d85b28;border-radius:50%;transform:translate(-50%,-50%);animation:pulse .46s ease-out both}
      .typing{border:2px solid #d85b28;border-radius:4px;animation:typing .9s ease-in-out both}
      .scroll{top:50%;width:30px;height:46px;border:2px solid #d85b28;border-radius:16px;transform:translateY(-50%)}
      .scroll.right{right:clamp(24px,4vw,48px)}.scroll.left{left:clamp(24px,4vw,48px)}
      .scroll:after{content:"";position:absolute;left:10px;top:18px;width:6px;height:6px;border-right:2px solid #d85b28;border-bottom:2px solid #d85b28;transform:rotate(45deg);animation:arrow .7s ease-in-out infinite alternate}
      .scroll.up:after{transform:rotate(225deg)}
      .status{right:max(14px,env(safe-area-inset-right));bottom:max(14px,env(safe-area-inset-bottom));max-width:min(360px,calc(100vw - 28px));padding:10px 13px;border:1px solid color-mix(in srgb,#d85b28 55%,transparent);border-radius:10px;background:Canvas;color:CanvasText;box-shadow:0 5px 18px rgb(0 0 0 / 18%);font:600 13px/1.35 system-ui,sans-serif}
      .status.running{border-color:#238636}.status.failed{border-color:#b42318}
      @keyframes pulse{from{opacity:.9;scale:.35}to{opacity:0;scale:1.8}}
      @keyframes typing{0%,100%{opacity:0}20%,80%{opacity:1}}
      @keyframes arrow{to{translate:0 7px}}
      @media(prefers-reduced-motion:reduce){.cue{animation:none!important}.pulse{opacity:.8}.typing{opacity:.8}.scroll:after{animation:none}}
    </style>`;
    document.documentElement.appendChild(host);
    return shadow;
  }
  function addCue(className, styles, duration) {
    if (!canShow()) return;
    const layer = ensureLayer();
    const baseKind = className.split(" ")[0];
    const kind = className.includes("left") ? `${baseKind}-left` : className.includes("right") ? `${baseKind}-right` : baseKind;
    const previous = cues.get(kind);
    if (previous) {
      clearTimeout(previous.timer);
      timers.delete(previous.timer);
      previous.node.remove();
    }
    const cue = document.createElement("span");
    cue.className = "cue " + className;
    Object.assign(cue.style, styles);
    layer.appendChild(cue);
    const timer = schedule(() => {
      cues.delete(kind);
      cue.remove();
    }, duration);
    cues.set(kind, { node: cue, timer });
  }
  function targetRect(target) {
    try { return target && target.getBoundingClientRect ? target.getBoundingClientRect() : null; } catch (_) { return null; }
  }
  function pulse(target) {
    const rect = targetRect(target);
    if (!rect || !rect.width || !rect.height || !canShow()) return;
    const now = Date.now();
    if (now - lastAction < 45) return;
    lastAction = now;
    addCue("pulse", { left: `${rect.left + rect.width / 2}px`, top: `${rect.top + rect.height / 2}px` }, 500);
  }
  function typing(target) {
    const rect = targetRect(target);
    if (!rect || !rect.width || !rect.height) return;
    const gap = 6;
    const left = Math.max(0, rect.left - gap);
    const top = Math.max(0, rect.top - gap);
    const rectRight = rect.right == null ? rect.left + rect.width : rect.right;
    const rectBottom = rect.bottom == null ? rect.top + rect.height : rect.bottom;
    const right = Math.min(root.innerWidth || rectRight + gap, rectRight + gap);
    const bottom = Math.min(root.innerHeight || rectBottom + gap, rectBottom + gap);
    addCue("typing", { left: `${left}px`, top: `${top}px`, width: `${Math.max(0, right - left)}px`, height: `${Math.max(0, bottom - top)}px` }, reducedMotion ? 500 : 950);
  }
  function scroll(direction) {
    const motion = reducedMotion ? 500 : 850;
    const cueDirection = direction === "up" ? "up" : "down";
    addCue(`scroll ${cueDirection} left`, {}, motion);
    addCue(`scroll ${cueDirection} right`, {}, motion);
  }
  function clear() { timers.forEach(clearTimeout); timers.clear(); cues.clear(); if (host) host.remove(); host = null; shadow = null; }
  function actionName(item, active) { return SleeperActionLabels.describe(item, active); }
  function statusText(item, active) {
    const cmd = String((item && (item.cmd || item.action)) || "").toLowerCase();
    const raw = String((item && item.status) || "").toLowerCase();
    const state = active || raw === "running" || raw === "pending" || raw === "started"
      ? "Working" : (raw === "failed" || raw === "error" || item && item.ok === false ? "Failed" : "Done");
    // Deliberately omit target/value details for all value-bearing commands.
    const target = SENSITIVE_ACTIONS.has(cmd) ? "" : (item && item.target ? ` · ${String(item.target).slice(0, 72)}` : "");
    return `${actionName(item, active)}${target}`;
  }
  function clearStatus() {
    const prior = cues.get("status");
    if (!prior) return;
    if (prior.timer !== null) {
      clearTimeout(prior.timer);
      timers.delete(prior.timer);
    }
    prior.node.remove();
    cues.delete("status");
  }
  function statusCue(item, active) {
    if (!item || !canShow()) return;
    const layer = ensureLayer();
    clearStatus();
    const state = active ? "running" : (String(item.status || "").toLowerCase() === "failed" || item.ok === false ? "failed" : "done");
    const cue = document.createElement("span");
    cue.className = `cue status ${state}`;
    cue.textContent = statusText(item, active);
    layer.appendChild(cue);
    // Keep the current action visible until storage reports its completion; completed
    // outcomes stay long enough to be noticed on a phone.
    const timer = active ? null : schedule(() => { cues.delete("status"); cue.remove(); }, STATUS_CUE_MS);
    cues.set("status", { node: cue, timer });
  }
  function renderStored(value) {
    const current = value && (value.current_action || value.action_current);
    const active = Boolean(current || value && value.action_in_progress);
    if (!active) { clearStatus(); return; }
    const log = Array.isArray(value && value.action_log) ? value.action_log : [];
    const item = current || log.slice().sort((a, b) => (Number(b.ts) || 0) - (Number(a.ts) || 0))[0];
    if (!item) { clearStatus(); return; }
    statusCue(item, Boolean(current));
  }
  function configure(value) { enabled = value !== false; if (!enabled) clear(); }
  function load() {
    reducedMotion = !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const browserApi = root.chrome || root.browser;
    if (browserApi && browserApi.storage && browserApi.storage.local) {
      browserApi.storage.local.get(["visible_activity", "current_action", "action_current", "action_in_progress", "action_log"], (value) => {
        configure(value.visible_activity !== false);
        renderStored(value);
      });
      if (browserApi.storage.onChanged && browserApi.storage.onChanged.addListener) {
        browserApi.storage.onChanged.addListener((changes) => {
          if (changes.visible_activity) {
            configure(changes.visible_activity.newValue !== false);
            if (changes.visible_activity.newValue === false) clear();
          }
          if (changes.current_action || changes.action_current || changes.action_in_progress || changes.action_log) {
            browserApi.storage.local.get(["current_action", "action_current", "action_in_progress", "action_log"], renderStored);
          }
        });
      }
    }
  }
  document.addEventListener("visibilitychange", clear);
  root.addEventListener("blur", clear);
  load();
  root.SleeperActivity = { pulse, typing, scroll, clear, configure };
})(typeof globalThis !== "undefined" ? globalThis : window);
