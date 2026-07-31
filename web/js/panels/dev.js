// Dev panel - settings, diagnostics, dev/sim fixture viewer, replay scrubber.
import { el, safe, fmtList, _to12, logLine } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _resolveChampId } from '../lib/items_index.js';
import { applyTheme, saveTheme, readStoredTheme, queryTheme, DEFAULT_THEME } from '../lib/theme.js';
// s220 PGR S5: Match-V5 timeline event ribbon for the Replay view.
// Sidecar architecture per docs/adr/ADR-009-replay-events-cleanroom.md.
import { loadReplayEvents, wireReplayEventsOnce, setReplaySeekHandler } from './replay_events.js';
// Mission Control S4: arm-then-confirm for the two queued shortcuts.
import { createArmController } from '../lib/arm_confirm.js';

// -- Settings view (2026-04-26) -----------------------------------
function _settingsRefresh() {
  if (window.__settingsWired) return;
  window.__settingsWired = true;
  const get = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; }};
  const setLS = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
  const cb = (id, key, onSet, invert) => {
    const el = document.getElementById(id);
    if (!el) return;
    // invert=true: checked UNLESS the stored value is "0" (opt-OUT, default
    // ON) - used by the item-1 Phase 5 push toggles. Default (invert falsy):
    // checked only when the stored value is "1" (the item-240 opt-in).
    el.checked = invert ? (get(key) !== "0") : (get(key) === "1");
    el.addEventListener("change", () => {
      setLS(key, el.checked ? "1" : "0");
      if (onSet) onSet(el.checked);
    });
  };
  cb("set-voice-on", "rc-voice-on");
  cb("set-force-flash-snowball", "rc-force-flash-snowball");
  cb("set-zen", "rc-zen", (v) => { document.body.dataset.zen = v ? "1" : ""; });
  // UI scale v2 (2026-05-23, docs/UI_SCALE_SPEC_V2.md): the page-zoom
  // slider was removed in favor of a per-element 25% scale across the
  // token layer. Mock-data toggle replaces it - dev affordance for
  // panel layout work, default OFF.
  cb("set-ui-mock", "rc-ui-mock", (v) => { document.body.dataset.uiMock = v ? "1" : ""; });
  // item 1 Phase 5 (2026-07-11): champ-select auto-push toggles, relocated
  // from the in-panel build-chooser control. INVERTED (checked unless "0") so
  // they default ON - champ_select._csvGetPushFlags reads the SAME 3 flat keys.
  // Opt-OUT: uncheck a category to stop auto-pushing it on build select.
  cb("set-push-runes",  "rc-cs-push-runes",  null, true);
  cb("set-push-spells", "rc-cs-push-spells", null, true);
  cb("set-push-build",  "rc-cs-push-build",  null, true);
  // s220: Post Game Review knobs. Rank-tier writes the SAME
  // localStorage key the PGR page's inline dropdown uses
  // (rc-pgr-rank-tier) - Settings is the canonical home, the two stay
  // in sync via the shared key. Baseline window (rc-pgr-baseline) is
  // read by last_match.js and passed to /api/last-match?baseline=.
  const pgrTier = document.getElementById("set-pgr-rank-tier");
  if (pgrTier) {
    pgrTier.value = get("rc-pgr-rank-tier") || "";
    pgrTier.addEventListener("change", () => {
      setLS("rc-pgr-rank-tier", pgrTier.value);
    });
  }
  const pgrBase = document.getElementById("set-pgr-baseline");
  const pgrBaseVal = document.getElementById("set-pgr-baseline-val");
  if (pgrBase) {
    let saved = parseInt(get("rc-pgr-baseline") || "20", 10);
    if (isNaN(saved)) saved = 20;
    saved = Math.max(5, Math.min(50, saved));
    pgrBase.value = saved;
    if (pgrBaseVal) pgrBaseVal.textContent = String(saved);
    pgrBase.addEventListener("input", () => {
      setLS("rc-pgr-baseline", pgrBase.value);
      if (pgrBaseVal) pgrBaseVal.textContent = pgrBase.value;
    });
  }

  // PRE-GAME LOBBY: party-type default. Remembered preference only
  // (rc-lobby-party-default), shared with the lobby Party toggle via the
  // same key - last-write-wins, survives reload. Per the operator's
  // choice this is NOT auto-pushed to LCU on lobby entry; it's just the
  // persisted preference. (The lobby Auto Accept checkbox in this same
  // card is agent-CONFIG-backed and wired in main.js, not here.)
  const lpd = document.getElementById("set-lobby-party-default");
  if (lpd) {
    lpd.value = get("rc-lobby-party-default") || "open";
    lpd.addEventListener("change", () => { setLS("rc-lobby-party-default", lpd.value); });
  }

  // DISPLAY: theme picker. web/js/lib/theme.js is the single source of truth
  // (whitelist + precedence + the sole writer of <html data-theme>). The
  // select reflects the SESSION theme, so a ?theme= override shows up here
  // without overwriting the stored preference; a change persists + applies
  // live (pure CSS-variable rebinding, no reload).
  const themeSel = document.getElementById("set-theme");
  if (themeSel) {
    themeSel.value = queryTheme() || readStoredTheme() || DEFAULT_THEME;
    themeSel.addEventListener("change", () => {
      const v = themeSel.value;
      saveTheme(v);
      applyTheme(v);
    });
  }

  // Live metrics status (read-only - env var)
  fetch("/api/diagnostics", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => {
      const el = document.getElementById("set-live-metrics-status");
      if (el && d) el.textContent = d.live_metrics_enabled ? "ON" : "OFF";
    }).catch(() => {});

  // API SPEND GATES (dev): a master dev-mode toggle reveals the per-gate
  // Anthropic kill-switches. The gate rows themselves are server-driven
  // (GATE_META) so they stay in sync; each shows a per-match cost averaged
  // over the last N full matches. Persistent via rc-dev-mode + the gate
  // disabled-set lives server-side in coach_settings.json.
  const devCb = document.getElementById("set-dev-mode");
  const gatesList = document.getElementById("spend-gates-list");
  if (devCb) {
    devCb.checked = get("rc-dev-mode") === "1";
    document.body.dataset.devMode = devCb.checked ? "1" : "";
    if (gatesList) gatesList.hidden = !devCb.checked;
    devCb.addEventListener("change", () => {
      setLS("rc-dev-mode", devCb.checked ? "1" : "0");
      document.body.dataset.devMode = devCb.checked ? "1" : "";
      if (gatesList) gatesList.hidden = !devCb.checked;
      if (devCb.checked) renderSpendGates();
    });
    if (devCb.checked) renderSpendGates();
  }

  // COACHING ACTIONS (RC2 P3.5): the no-hotkey Force vision scan button.
  // POSTs the SAME force_vision command the legacy dashboard's btn-scan
  // used (-> dashboard/_writers.py force_vision_scan -> data/force_scan.json),
  // which is the keyboard-free equivalent of the Ctrl+Tab hotkey
  // (core/hotkeys.py). Token-header aware (mirrors screen_read /
  // loop-control). A client-side 3s cooldown matches CTRL_TAB_COOLDOWN so a
  // double-tap can't spam the marker; the button disables for the window.
  const fsBtn = document.getElementById("set-force-scan-btn");
  const fsStatus = document.getElementById("set-force-scan-status");
  if (fsBtn) {
    let fsLast = 0;
    fsBtn.addEventListener("click", () => {
      const now = Date.now();
      if (fsBtn.disabled || now - fsLast < 3000) return;   // CTRL_TAB_COOLDOWN
      fsLast = now;
      fsBtn.disabled = true;
      if (fsStatus) fsStatus.textContent = "scan requested...";
      fetch("/api/command", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
        body: JSON.stringify({ command: "force_vision" }),
      })
        .then((r) => { if (fsStatus) fsStatus.textContent = (r && r.ok) ? "scan requested" : "request failed"; })
        .catch(() => { if (fsStatus) fsStatus.textContent = "request failed"; })
        .finally(() => { setTimeout(() => { fsBtn.disabled = false; }, 3000); });
    });
  }
}

// Re-entrant: fetch the gate registry + per-match cost and (re)build the
// rows. Called on each Settings view show + after every toggle so the cost
// stays synced. A checked box = gate ENABLED (Anthropic spend allowed);
// unchecking it persists the kill-switch server-side and applies live.
function renderSpendGates() {
  const host = document.getElementById("spend-gates-list");
  if (!host) return;
  fetch("/api/spend/gates", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((j) => {
      if (!j || !j.gates) return;
      const pm = j.per_match || {};
      host.innerHTML = "";
      const mk = (tag, cls) => {
        const n = document.createElement(tag);
        if (cls) n.className = cls;
        return n;
      };
      for (const gate of Object.keys(j.gates)) {
        const g = j.gates[gate];
        const cost = pm[gate] || { usd: 0, tokens: 0, n: 0 };
        const row = mk("label", "settings-row spend-gate-row");
        const cbx = document.createElement("input");
        cbx.type = "checkbox";
        cbx.checked = !g.disabled;
        cbx.addEventListener("change", () => {
          fetch("/api/coach/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "rc-dashboard" },
            body: JSON.stringify({ mode: gate, disabled: !cbx.checked }),
          }).then(() => renderSpendGates()).catch(() => {});
        });
        const txt = mk("span", "spend-gate-txt");
        const lab = mk("b"); lab.textContent = g.label || gate;
        const exp = mk("span", "dim"); exp.textContent = g.explain || "";
        txt.append(lab, document.createElement("br"), exp);
        const costEl = mk("span", "spend-gate-cost");
        if (cost.n) {
          const usd = mk("b"); usd.textContent = "$" + (cost.usd || 0).toFixed(4);
          const tok = mk("span", "dim");
          tok.textContent = (cost.tokens || 0).toLocaleString() + " tok/match";
          costEl.append(usd, document.createElement("br"), tok);
        } else {
          const nd = mk("span", "dim"); nd.textContent = "no data";
          costEl.append(nd);
        }
        row.append(cbx, txt, costEl);
        host.appendChild(row);
      }
    })
    .catch(() => {});
}

// -- Diagnostics view (2026-04-26) --------------------------------
function _diagFetchAndRender() {
  fetch("/api/diagnostics", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => {
      if (!d) return;
      const ul = document.getElementById("diag-conn-list");
      if (ul) {
        ul.innerHTML = "";
        (d.connections || []).forEach((c) => {
          const li = document.createElement("li");
          li.className = "diag-conn-row";
          const dot = document.createElement("span");
          dot.className = "diag-conn-dot " + (c.ok ? "ok" : "err");
          const nm = document.createElement("span");
          nm.style.cssText = "flex:1; color:var(--text); font-weight:700";
          nm.textContent = c.name;
          const det = document.createElement("span");
          det.className = "dim";
          // DIAG1 audit: dropped the inline 10px sub-floor; the detail span
          // inherits the .diag-conn-row 12px dense-surface size.
          det.textContent = c.detail || "";
          li.append(dot, nm, det);
          ul.appendChild(li);
        });
        if (!ul.children.length) ul.innerHTML = '<li class="home-empty">no connections reporting</li>';
      }
      const log = document.getElementById("diag-log");
      if (log) log.textContent = (d.log_tail || []).join("\n") || "(no log lines)";
      const health = document.getElementById("diag-health");
      if (health) health.textContent = JSON.stringify(d.health || {}, null, 2);
    })
    .catch(() => {});
  // 2026-04-28: also refresh the cost tile, coach toggles, and trace
  // list. Each is independent; one failure doesn't block the others.
  _diagFetchCost();
  _diagFetchCoachState();
  _diagFetchTrace();
}
function _diagFetchCost() {
  fetch("/api/cost", { cache: "no-store" })
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      if (!j) return;
      const sp = j.spend || {};
      const v = document.getElementById("cost-val");
      if (v) v.textContent = "$" + (sp.total_usd || 0).toFixed(4);
      const c = document.getElementById("cost-calls");
      if (c) c.textContent = String(sp.calls || 0);
      const t = document.getElementById("cost-tokens");
      if (t) t.textContent = `${(sp.tokens_in||0).toLocaleString()} / ${(sp.tokens_out||0).toLocaleString()}`;
      const cc = document.getElementById("cost-cache");
      if (cc) cc.textContent = `${(sp.cache_in||0).toLocaleString()} / ${(sp.cache_write||0).toLocaleString()}`;
      const b = document.getElementById("cost-banner");
      if (b) {
        b.classList.remove("ok","warn","over");
        b.classList.add(j.banner || "ok");
        b.textContent = (j.banner || "ok").toUpperCase();
      }
    })
    .catch(()=>{});
}
function _diagFetchCoachState() {
  fetch("/api/coach/state", { cache: "no-store" })
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      if (!j || !j.enabled) return;
      for (const mode of Object.keys(j.enabled)) {
        const pill = document.querySelector(`.coach-toggle-pill[data-mode="${mode}"]`);
        if (!pill) continue;
        if (pill.dataset.disabled === "1") continue;   // tft on hold
        const on = j.enabled[mode];
        pill.classList.remove("on","off");
        pill.classList.add(on ? "on" : "off");
        pill.textContent = on ? "ON" : "OFF";
      }
    })
    .catch(()=>{});
}
function _diagFetchTrace() {
  fetch("/api/coach/trace?limit=20", { cache: "no-store" })
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      const host = document.getElementById("trace-list");
      if (!host) return;
      host.innerHTML = "";
      const rows = (j && j.records) || [];
      if (!rows.length) {
        host.innerHTML = '<div class="home-empty">no coach calls yet today</div>';
        return;
      }
      for (const rec of rows.slice().reverse()) {  // newest first
        const item = document.createElement("div");
        item.className = "trace-item";
        const meta = document.createElement("div");
        meta.className = "trace-meta";
        const tsStr = _to12(new Date((rec.ts || 0) * 1000));
        meta.textContent = `${tsStr} - ${rec.mode || "?"} - ${rec.model || ""} - ${rec.latency_ms || 0}ms - in ${rec.tokens_in || 0} / out ${rec.tokens_out || 0}` +
          ((rec.cache_read || rec.cache_write) ? ` - cache r ${rec.cache_read || 0} w ${rec.cache_write || 0}` : "");
        const resp = document.createElement("pre");
        resp.textContent = (rec.response || "").slice(0, 600);
        item.append(meta, resp);
        host.appendChild(item);
      }
    })
    .catch(()=>{});
}
function _diagToggleCoach(mode, currentlyOn) {
  fetch("/api/coach/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "rc-dashboard" },
    body: JSON.stringify({ mode: mode, disabled: currentlyOn })
  })
    .then(r => r.ok ? r.json() : null)
    .then(_ => _diagFetchCoachState())
    .catch(()=>{});
}
function _diagWireOnce() {
  if (window.__diagWired) return;
  window.__diagWired = true;
  const r = document.getElementById("diag-refresh");
  if (r) r.addEventListener("click", _diagFetchAndRender);
  // Coach-toggle clicks
  document.querySelectorAll(".coach-toggle-pill").forEach(p => {
    if (p.dataset.disabled === "1") return;
    p.addEventListener("click", () => {
      const mode = p.dataset.mode;
      const currentlyOn = p.classList.contains("on");
      _diagToggleCoach(mode, currentlyOn);
    });
  });
}

// -- Headless loop status (2026-06-07) ----------------------------
// Read-only, mobile-friendly surface over /api/loop-status (which reads the
// ops/loop/control/* files + last commit). Rendered on each Settings show so
// a Gemini-directed loop is watchable from the phone over Tailscale.
//
// CONTROL half (2026-06-07): POST /api/loop-control writes ops/loop/control/*
// so the loop can be halted / resumed / re-directed from the phone. The helper
// re-renders the card and echoes the action result into #loop-ctl-msg.
function _loopControl(action, extra) {
  fetch("/api/loop-control", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
    body: JSON.stringify(Object.assign({ action: action }, extra || {})),
  })
    .then((r) => (r ? r.json() : null))
    .then((d) => {
      const txt = d && d.ok
        ? action + ": " + (d.detail || "ok")
        : "error: " + (d && d.error ? d.error : "failed");
      renderLoopStatus(txt);
    })
    .catch(() => renderLoopStatus("request failed"));
}

// -- Mission Control S4: lock rows + shortcuts 1 and 2 ------------
// Three lock states, never two. A lock file whose pid is DEAD reads exactly
// like a live one from the file alone, so RECLAIMABLE gets its own colour and
// its own note and is NEVER collapsed into RUNNING - collapsing them is what
// made a dead loop report as live (docs/MISSION_CONTROL_PLAN.md).
const _LOCK_STATES = ["FREE", "RUNNING", "RECLAIMABLE"];

function _loopAge(secs) {
  if (typeof secs !== "number" || !isFinite(secs) || secs < 0) return null;
  if (secs < 90) return Math.round(secs) + "s";
  if (secs < 5400) return Math.round(secs / 60) + "m";
  if (secs < 172800) return Math.round(secs / 3600) + "h";
  return Math.round(secs / 86400) + "d";
}

function _loopLockRow(mk, label, block) {
  // An absent block means S1 is not installed. It still renders a row: a
  // vanishing row reflows everything under it (feedback_no_reflow_on_data_absence).
  const known = block && _LOCK_STATES.indexOf(block.state) >= 0;
  const st = known ? block.state : "UNAVAILABLE";
  const cls = st.toLowerCase();
  const row = mk("div", "loop-lock-row");
  row.append(mk("span", "loop-lock-label", label));
  row.append(mk("span", "loop-lock-dot " + cls));
  row.append(mk("b", "loop-lock-state " + cls, st));

  const bits = [];
  if (known) {
    if (block.lane) bits.push("lane " + block.lane);
    if (block.pid != null) bits.push("pid " + block.pid);
    if (block.run_id) bits.push("run " + block.run_id);
    const age = _loopAge(block.age_s);
    if (age) bits.push("held " + age);
  }
  // No `dim` class here: web/css has no bare `.dim` rule, only descendant-scoped
  // ones, so it is inert. .loop-lock-meta owns its own colour.
  row.append(mk("span", "loop-lock-meta", bits.join("  -  ")));
  if (st === "RECLAIMABLE") {
    row.append(mk("span", "loop-lock-note", "holder is gone - free to claim"));
  }
  return row;
}

// The two shortcuts that cannot spawn a lane. Both only WRITE an intent file
// the running session consumes at its next safe boundary - nothing is killed
// and nothing is signalled.
const _MC_SHORTCUTS = [
  { id: "halt_save", label: "Halt and Save",
    hint: "finish the step, run the done ritual, write the next-session prompt to the Desktop" },
  { id: "done_continue", label: "/done Continue",
    hint: "done ritual, then auto-clear and re-run the prompt it just emitted" },
];

// The key is minted at ARM and discarded on disarm - see web/js/lib/arm_confirm.js.
// A key reused across arms replays the first refusal forever, so the button
// looks alive and is permanently inert. MEASURED against the real S2 route.
const _mcArm = createArmController({ onChange: () => _mcPaint() });
let _mcHost = null;
let _mcTimer = null;

function _mcSetTimer(on) {
  if (on && _mcTimer == null) {
    _mcTimer = setInterval(() => { _mcArm.tick(); _mcPaint(); }, 250);
  } else if (!on && _mcTimer != null) {
    clearInterval(_mcTimer);
    _mcTimer = null;
  }
}

function _mcMsg(text) {
  const node = document.getElementById("loop-ctl-msg");
  if (node) node.textContent = text;
}

function _mcFire(shortcut, key) {
  _mcMsg(shortcut.label + ": sending...");
  fetch("/api/loop-control", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
    body: JSON.stringify({
      action: "queue_intent", intent: shortcut.id, idempotency_key: key,
    }),
  })
    .then((r) => (r ? r.json() : null))
    .then((d) => {
      if (d && d.ok) {
        _mcMsg(shortcut.label + ": " + (d.detail || "queued")
          + (d.replayed ? " (replayed)" : ""));
      } else {
        const why = d && (d.refused || d.error) ? (d.refused || d.error) : "failed";
        _mcMsg(shortcut.label + " refused: " + why);
      }
    })
    .catch(() => _mcMsg(shortcut.label + ": request failed"));
}

// S5: the headless lanes. Mutually exclusive - one lock - and a fire against a
// held lane is REFUSED, never queued. The wired list comes from the SERVER
// (lanes_available.wired, derived from the launcher's own map) so the panel
// cannot drift as S6 and S8 wire the rest.
const _LANE_LABELS = {
  "upgrade": "Headless-Upgrade",
  "uiux": "Headless-UIUX",
  "research": "Headless-Research",
  "ds": "Headless-DS",
  "repo": "Headless-Repo",
  "true-audit": "Headless-True-Audit",
};

let _mcLanes = { all: [], wired: [] };
let _mcLaneHost = null;

function _mcSteerKey() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  let out = "";
  for (let i = 0; i < 8; i += 1) {
    out += Math.floor(Math.random() * 0x10000).toString(16).padStart(4, "0");
    if (i === 1 || i === 3 || i === 5) out += "-";
  }
  return out;
}

function _mcRunId() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID().slice(0, 8);
  return Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
}

function _mcFireLane(lane, key) {
  const label = _LANE_LABELS[lane] || lane;
  _mcMsg(label + ": starting...");
  fetch("/api/loop-control", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
    body: JSON.stringify({
      action: "fire_lane", lane: lane,
      run_id: _mcRunId(), idempotency_key: key,
    }),
  })
    .then((r) => (r ? r.json() : null))
    .then((d) => {
      if (d && d.ok) {
        _mcMsg(label + ": " + (d.detail || "running")
          + (d.replayed ? " (replayed)" : ""));
      } else if (d && d.refused) {
        _mcMsg(label + " REFUSED - " + (d.detail || d.refused));
      } else {
        _mcMsg(label + " failed: " + ((d && d.error) || "request failed"));
      }
      renderLoopStatus();
    })
    .catch(() => _mcMsg(label + ": request failed"));
}

function _mcPaintLanes() {
  const host = _mcLaneHost;
  if (!host || !host.isConnected) return false;
  const focusedId = (document.activeElement && host.contains(document.activeElement))
    ? document.activeElement.dataset.mcId : null;
  let refocus = null;
  host.innerHTML = "";
  const wired = _mcLanes.wired || [];
  const all = (_mcLanes.all && _mcLanes.all.length) ? _mcLanes.all
    : Object.keys(_LANE_LABELS);
  let anyArmed = false;
  all.forEach((lane) => {
    const id = "lane:" + lane;
    const isWired = wired.indexOf(lane) >= 0;
    const armed = _mcArm.isArmed(id);
    if (armed) anyArmed = true;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "loop-btn loop-lane-btn" + (armed ? " loop-btn-armed" : "")
      + (isWired ? "" : " loop-lane-unwired");
    b.dataset.mcId = id;
    if (focusedId === id) refocus = b;
    b.setAttribute("aria-pressed", armed ? "true" : "false");
    const label = _LANE_LABELS[lane] || lane;
    if (!isWired) {
      b.disabled = true;
      b.textContent = label;
      b.title = "no command doc wired yet - a later stage lands this lane";
      b.setAttribute("aria-disabled", "true");
    } else if (armed) {
      b.textContent = "Confirm " + label + " ("
        + Math.ceil(_mcArm.remainingMs() / 1000) + "s)";
      b.title = "fires a real headless run in its own git worktree";
    } else {
      b.textContent = label;
      b.title = "fires a real headless run in its own git worktree";
    }
    b.addEventListener("click", () => {
      if (b.disabled) return;
      if (_mcArm.isArmed(id)) {
        const res = _mcArm.confirm(id);
        if (res.fired) _mcFireLane(lane, res.key);
        return;
      }
      _mcArm.arm(id);
      _mcMsg("armed: click again within 3s to start " + label);
    });
    host.append(b);
  });
  if (refocus) refocus.focus();
  return anyArmed;
}

// S9 - INTERRUPT. The only Mission Control action that kills a process, so it
// is the only one whose ARM does a round trip first: the plan requires the
// button to NAME the agents it will kill BEFORE the confirm, and the names can
// only come from the server.
//
// The fingerprint lives here beside the victims and is dropped by the same
// paint that observes the arm has lapsed - deliberately the same lifecycle as
// the idempotency key in arm_confirm.js. A fingerprint that outlived its arm
// would let a later confirm fire against a list the operator is no longer
// looking at, which is precisely what the fingerprint exists to prevent.
const _MC_IRQ_ID = "interrupt";
let _mcIrq = { fp: null, victims: [], host: null };

function _mcIrqForget() {
  _mcIrq.fp = null;
  _mcIrq.victims = [];
}

function _mcVictimLine(v) {
  const bits = [String(v.pid), v.name || "?"];
  if (v.lane) bits.push("lane " + v.lane);
  else if (v.kind === "controller") bits.push("loop controller");
  else if (v.kind === "child") bits.push("child of " + v.ppid);
  return bits.join("  -  ");
}

function _mcIrqPreview() {
  _mcMsg("INTERRUPT: probing what is running...");
  fetch("/api/loop-control", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
    body: JSON.stringify({ action: "interrupt_preview" }),
  })
    .then((r) => (r ? r.json() : null))
    .then((d) => {
      if (!d || !d.ok) {
        _mcMsg("INTERRUPT preview failed: " + ((d && d.error) || "request failed"));
        return;
      }
      if (!d.count) {
        // Nothing to kill, so nothing to name - arming here would offer a
        // confirm whose victim list is empty, and the server refuses it anyway.
        _mcIrqForget();
        _mcMsg("INTERRUPT: nothing is running - nothing to interrupt");
        _mcPaint();
        return;
      }
      _mcIrq.fp = d.fingerprint;
      _mcIrq.victims = d.victims || [];
      _mcArm.arm(_MC_IRQ_ID);
      _mcMsg("INTERRUPT armed: " + d.count
        + " process(es) named below - click again within 3s to KILL them");
    })
    .catch(() => _mcMsg("INTERRUPT preview: request failed"));
}

function _mcIrqFire(key, fp) {
  // `fp` is passed IN, never read from _mcIrq here. MEASURED live 2026-07-31:
  // _mcArm.confirm() disarms and notifies SYNCHRONOUSLY, that notify repaints,
  // and the repaint sees armed === false and calls _mcIrqForget() - so by the
  // time this function ran, the fingerprint it needed was already null and the
  // server answered 400 "requires 'fingerprint'". The tier failed safe (nothing
  // died) but could never kill anything. The caller reads the fingerprint
  // BEFORE confirm() and hands it over.
  _mcIrqForget();
  _mcMsg("INTERRUPT: killing...");
  fetch("/api/loop-control", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
    body: JSON.stringify({ action: "interrupt", fingerprint: fp,
                           idempotency_key: key }),
  })
    .then((r) => (r ? r.json() : null))
    .then((d) => {
      if (d && d.ok) {
        _mcMsg("INTERRUPT: " + (d.detail || "done")
          + (d.replayed ? " (replayed)" : ""));
      } else if (d && d.refused === "victims_changed") {
        // The honest failure: what the operator approved is no longer what is
        // running, so nothing was killed. Say that plainly and make them look
        // again rather than silently re-targeting.
        _mcMsg("INTERRUPT REFUSED - the running processes changed since the "
          + "preview. Nothing was killed. Preview again to see the current "
          + (d.count || 0) + ".");
      } else if (d && d.refused) {
        _mcMsg("INTERRUPT REFUSED - " + d.refused);
      } else {
        _mcMsg("INTERRUPT failed: " + ((d && d.error) || "request failed"));
      }
      renderLoopStatus();
    })
    .catch(() => _mcMsg("INTERRUPT: request failed"));
}

function _mcPaintInterrupt() {
  const host = _mcIrq.host;
  if (!host || !host.isConnected) return false;
  const armed = _mcArm.isArmed(_MC_IRQ_ID);
  // The arm lapsing is what expires the fingerprint. Handled on the paint that
  // notices, so a countdown running out is indistinguishable from a Cancel.
  if (!armed && _mcIrq.fp) _mcIrqForget();
  const focused = (document.activeElement && host.contains(document.activeElement))
    ? document.activeElement.dataset.mcId : null;
  let refocus = null;
  host.innerHTML = "";

  const b = document.createElement("button");
  b.type = "button";
  b.className = "loop-btn loop-irq-btn" + (armed ? " loop-btn-armed" : "");
  b.dataset.mcId = _MC_IRQ_ID;
  b.setAttribute("aria-pressed", armed ? "true" : "false");
  if (focused === _MC_IRQ_ID) refocus = b;
  if (armed) {
    b.textContent = "Confirm INTERRUPT - kill " + _mcIrq.victims.length
      + " (" + Math.ceil(_mcArm.remainingMs() / 1000) + "s)";
    b.title = "kills exactly the processes listed below, and nothing else";
  } else {
    b.textContent = "INTERRUPT - show what dies";
    b.title = "probes what is running and names it before anything is killed";
  }
  b.addEventListener("click", () => {
    if (_mcArm.isArmed(_MC_IRQ_ID)) {
      // Read the fingerprint FIRST: confirm() notifies synchronously, the
      // notify repaints, and the repaint clears it. See _mcIrqFire.
      const fp = _mcIrq.fp;
      const res = _mcArm.confirm(_MC_IRQ_ID);
      if (res.fired) _mcIrqFire(res.key, fp);
      return;
    }
    _mcIrqPreview();
  });
  host.append(b);

  if (armed && _mcIrq.victims.length) {
    // The named victims. This list IS the safety property - it must be on
    // screen before the confirm is reachable, not behind a disclosure.
    //
    // document.createElement, NOT the `mk` helper. `mk` is a function-LOCAL
    // const inside renderLoopStatus, so at module scope it is a ReferenceError
    // - and one thrown here is swallowed by the preview's .catch, which
    // reported it as "request failed". The armed button still rendered
    // "Confirm INTERRUPT - kill 3" with NO list beneath it, which is precisely
    // the blind kill this tier exists to prevent. Every other module-scope
    // paint function here already uses createElement for the same reason.
    const list = document.createElement("ul");
    list.className = "loop-irq-victims";
    list.setAttribute("aria-label", "processes this interrupt will kill");
    _mcIrq.victims.forEach((v) => {
      const li = document.createElement("li");
      li.className = "loop-irq-victim";
      li.textContent = _mcVictimLine(v);
      list.append(li);
    });
    host.append(list);
  }
  if (refocus) refocus.focus();
  return armed;
}

function _mcPaint() {
  // Lanes first, and its armed flag is folded into the timer decision below -
  // otherwise a lane armed on its own would have its countdown cancelled by
  // the shortcut row reporting nothing armed.
  const laneArmed = _mcPaintLanes();
  const irqArmed = _mcPaintInterrupt();
  const host = _mcHost;
  if (!host || !host.isConnected) { _mcSetTimer(!!laneArmed || !!irqArmed); return; }
  // The countdown repaints 4x/second while armed, and innerHTML="" destroys the
  // node the operator is standing on. Without this, tabbing to a shortcut and
  // pressing Enter armed it and threw focus to <body> - so the confirm click
  // could never be reached from the keyboard and the whole flow was mouse-only.
  const focusedId = (document.activeElement && host.contains(document.activeElement))
    ? document.activeElement.dataset.mcId : null;
  host.innerHTML = "";
  let anyArmed = false;
  let refocus = null;
  _MC_SHORTCUTS.forEach((sc) => {
    const armed = _mcArm.isArmed(sc.id);
    if (armed) anyArmed = true;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "loop-btn loop-shortcut" + (armed ? " loop-btn-armed" : "");
    b.setAttribute("aria-pressed", armed ? "true" : "false");
    b.dataset.mcId = sc.id;
    if (focusedId === sc.id) refocus = b;
    b.title = sc.hint;
    if (armed) {
      const left = Math.ceil(_mcArm.remainingMs() / 1000);
      b.textContent = "Confirm " + sc.label + " (" + left + "s)";
    } else {
      b.textContent = sc.label;
    }
    b.addEventListener("click", () => {
      if (_mcArm.isArmed(sc.id)) {
        const res = _mcArm.confirm(sc.id);
        if (res.fired) _mcFire(sc, res.key);
        return;
      }
      _mcArm.arm(sc.id);
      _mcMsg("armed: click again within 3s to " + sc.label.toLowerCase());
    });
    host.append(b);
  });
  // laneArmed and irqArmed too: the arm controller is global, so an armed LANE
  // or INTERRUPT - the heavier actions - would otherwise be the ones with no
  // visible abort.
  if (anyArmed || laneArmed || irqArmed) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "loop-btn loop-btn-cancel";
    cancel.dataset.mcId = "cancel";
    if (focusedId === "cancel") refocus = cancel;
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => {
      _mcArm.disarm();
      _mcMsg("disarmed");
    });
    host.append(cancel);
  }
  if (refocus) refocus.focus();
  _mcSetTimer(anyArmed || !!laneArmed || !!irqArmed);
}

function renderLoopStatus(ctlMsg) {
  const host = document.getElementById("loop-status-body");
  if (!host) return;
  const mk = (tag, cls, txt) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  };
  fetch("/api/loop-status", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => {
      if (!d || !d.ok) {
        host.innerHTML = '<div class="home-empty">loop status unavailable</div>';
        return;
      }
      host.innerHTML = "";
      const st = d.state || "idle";

      const stateRow = mk("div", "loop-state-row");
      stateRow.append(mk("span", "loop-dot " + st));
      stateRow.append(mk("b", null, st.toUpperCase()));
      if (d.cycle != null) {
        stateRow.append(mk("span", "dim",
          "cycle " + d.cycle + (d.max_cycles ? " / " + d.max_cycles : "")));
      }
      if (d.mode) stateRow.append(mk("span", "loop-mode", d.mode));
      host.append(stateRow);

      if (d.stop_reason) host.append(mk("div", "loop-line dim", "stop: " + d.stop_reason));

      // Lock states. Two separate locks with two separate lifetimes: the lane
      // mutex (control/lanes/0.lock) and the loop controller's own single-flight
      // lock (control/RUNNING.lock). Reported side by side, never merged.
      const locks = mk("div", "loop-locks");
      locks.append(_loopLockRow(mk, "LANE", d.lanes));
      locks.append(_loopLockRow(mk, "LOOP", d.controller_lock));
      host.append(locks);

      if (d.last_done) {
        const ld = d.last_done;
        const row = mk("div", "loop-line");
        row.append(mk("span", "dim",
          "last cycle " + (ld.cycle != null ? ld.cycle : "?") + ":"));
        row.append(mk("code", null, ld.sha || "?"));
        row.append(mk("span", null,
          "tests " + (ld.tests_pass != null ? ld.tests_pass : "?")));
        row.append(mk("span", ld.regressions ? "loop-bad" : "loop-ok",
          ld.regressions ? "REGRESS" : "clean"));
        host.append(row);
      }

      if (d.budget) {
        const b = d.budget;
        const num = (v) => (typeof v === "number" ? v : null);
        const g = num(b.gemini_usd), gc = num(b.gemini_ceiling), c = num(b.claude_usd_info);
        host.append(mk("div", "loop-line dim",
          "spend: gemini $" + (g != null ? g.toFixed(2) : "?") +
          " / $" + (gc != null ? gc.toFixed(0) : "?") +
          "  -  claude(info) $" + (c != null ? c.toFixed(2) : "?")));
      }

      if (d.last_commit) {
        const lc = d.last_commit;
        const row = mk("div", "loop-line");
        row.append(mk("code", null, lc.sha || "?"));
        row.append(mk("span", "dim", lc.subject || ""));
        host.append(row);
      }

      if (Array.isArray(d.log_tail) && d.log_tail.length) {
        host.append(mk("pre", "loop-log", d.log_tail.join("\n")));
      }

      // -- Control row (CONTROL half): stop / resume + one-shot directive
      // override. Each writes ops/loop/control/* via POST /api/loop-control.
      const btn = (label, cls, fn) => {
        const b = mk("button", "loop-btn " + (cls || ""), label);
        b.type = "button";
        b.addEventListener("click", fn);
        return b;
      };
      const ctl = mk("div", "loop-controls");
      if (st === "stopped") {
        ctl.append(btn("Resume", "loop-btn-resume", () => _loopControl("resume")));
      } else {
        ctl.append(btn("Stop loop", "loop-btn-stop",
          () => _loopControl("stop", { reason: "stopped from dashboard" })));
      }
      host.append(ctl);

      // Shortcuts 1 and 2 - queued intents, safe alongside a running lane.
      // Arm-then-confirm: a stray single click decays after 3s and fires nothing.
      host.append(mk("div", "loop-sub-head", "SHORTCUTS - ARM, THEN CONFIRM"));
      _mcHost = mk("div", "loop-shortcuts");
      host.append(_mcHost);

      // Lanes (S5). Mutually exclusive; a fire against a held lane is refused.
      _mcLanes = d.lanes_available || { all: [], wired: [] };
      // The count is in VISIBLE text on purpose. Five permanently-dim buttons
      // under a heading that only says "refused if held" read as "currently
      // held" - a transient explanation for a permanent state - and the real
      // reason lived only in a hover title, which a disabled button does not
      // reliably announce.
      const nWired = (_mcLanes.wired || []).length;
      const nAll = (_mcLanes.all || []).length || Object.keys(_LANE_LABELS).length;
      host.append(mk("div", "loop-sub-head",
        "LANES - ARM, THEN CONFIRM - ONE AT A TIME, REFUSED IF HELD - "
        + nWired + " of " + nAll + " wired"));
      _mcLaneHost = mk("div", "loop-shortcuts loop-lanes-row");
      host.append(_mcLaneHost);
      _mcPaint();

      // Steer channel (S7). NOTE and STEER only - INTERRUPT is S9 and is a
      // different act entirely. Single click on purpose: a steer is GUIDANCE,
      // it executes nothing and kills nothing, and the text has to be typed
      // first, which is itself the deliberate act. The arm-then-confirm window
      // is for things that cannot be taken back.
      const steerInfo = d.steer || null;
      host.append(mk("div", "loop-sub-head",
        "STEER - GUIDANCE, NEVER AN INTERRUPT"
        + (steerInfo && steerInfo.pending
           ? " - " + steerInfo.pending + " PENDING" : "")));
      const sta = mk("textarea", "loop-ta");
      sta.id = "loop-steer-input";
      sta.rows = 2;
      sta.placeholder = "note for the running session...";
      // A placeholder is NOT an accessible name - it disappears on the first
      // keystroke, so a screen reader loses the label exactly when the field
      // has content. The visible sub-head above is not programmatically
      // associated with the field, so name it explicitly.
      sta.setAttribute("aria-label", "steer text for the running session");
      host.append(sta);
      const steerRow = mk("div", "loop-dir-row loop-steer-row");
      const _sendSteer = (tier) => {
        const node = document.getElementById("loop-steer-input");
        const text = node && node.value ? node.value.trim() : "";
        if (!text) { _mcMsg("steer: type something first"); return; }
        fetch("/api/loop-control", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
          body: JSON.stringify({
            action: "steer", tier: tier, text: text,
            // One key per SEND, minted here - the same rule as the arm path.
            idempotency_key: _mcSteerKey(),
          }),
        })
          .then((r) => (r ? r.json() : null))
          .then((dd) => {
            if (dd && dd.ok) {
              _mcMsg(tier.toUpperCase() + ": " + (dd.detail || "queued"));
              if (node) node.value = "";
              renderLoopStatus();
            } else {
              _mcMsg(tier.toUpperCase() + " failed: "
                + ((dd && dd.error) || "request failed"));
            }
          })
          .catch(() => _mcMsg(tier.toUpperCase() + ": request failed"));
      };
      // No accent on either: see the .loop-steer-row comment in header.css.
      steerRow.append(btn("Send NOTE", "", () => _sendSteer("note")));
      steerRow.append(btn("Send STEER", "", () => _sendSteer("steer")));
      host.append(steerRow);
      if (steerInfo && steerInfo.newest) {
        // No `dim` class - web/css has no bare `.dim` rule, and .loop-line
        // already carries --text-dim. Same inert-class trap as S4.
        host.append(mk("div", "loop-line",
          "newest pending: " + steerInfo.newest));
      }

      // INTERRUPT (S9). Its own sub-head, below STEER, because it is a
      // different ACT and not a louder tier of the same one - the two share a
      // heading only in the plan's prose, never on screen.
      host.append(mk("div", "loop-sub-head",
        "INTERRUPT - STOPS THE TURN AND KILLS AGENTS"));
      host.append(mk("div", "loop-line",
        "names every process first - the confirm can only kill what the "
        + "preview listed"));
      _mcIrq.host = mk("div", "loop-shortcuts loop-irq-row");
      host.append(_mcIrq.host);
      // Paint again now that the interrupt host exists. The earlier call sits
      // above this block and painted into a host that was still null, so
      // without this the button is missing until the next 5s poll - the same
      // class of bug as the S4 card that rendered into markup that did not
      // exist.
      _mcPaint();

      // Its own sub-head. Before S7 this was the trailing block and read as a
      // group; once the steer row landed above it, it became the only unheaded
      // group in the card and both textareas read as one STEER control.
      host.append(mk("div", "loop-sub-head",
        "DIRECTIVE OVERRIDE - ONE SHOT, NEXT CYCLE"));
      const ta = mk("textarea", "loop-ta");
      ta.id = "loop-directive-input";
      ta.rows = 3;
      ta.placeholder = "one-shot directive override for the next cycle...";
      ta.setAttribute("aria-label",
        "one-shot directive override for the next loop cycle");
      host.append(ta);

      const dirRow = mk("div", "loop-dir-row");
      dirRow.append(btn("Queue directive", "loop-btn-dir", () => {
        const node = document.getElementById("loop-directive-input");
        const t = node && node.value ? node.value : "";
        if (t.trim()) _loopControl("set_directive", { text: t });
      }));
      dirRow.append(btn("Clear", "loop-btn-clear", () => _loopControl("clear_directive")));
      host.append(dirRow);

      const msg = mk("div", "loop-ctl-msg");
      msg.id = "loop-ctl-msg";
      // The arm transition is announced here; without a live region a screen
      // reader never hears that a 3s confirm window just opened.
      msg.setAttribute("role", "status");
      msg.setAttribute("aria-live", "polite");
      if (ctlMsg) msg.textContent = ctlMsg;
      host.append(msg);
    })
    .catch(() => {
      host.innerHTML = '<div class="home-empty">loop status error</div>';
    });
}

// -- Replay scrubber (audit suggestion 2.3, 2026-04-28) ------------
// Loads recent matches from /api/replay/matches; clicking one fetches
// /api/replay/match/<id> and lets the user scrub through per-minute
// snapshots. Items, level, gold, CS reflect the slider position.
const _REPLAY = { match: null, snapshotIdx: 0, itemsIndex: null };

// UI scale v2.1 page #3 audit ritual step 5 state-coverage mock fixture
// (2026-05-23). When body.dataset.uiMock === "1" the three fetch
// sites below short-circuit to /data/ui_mock/replay.json instead of
// the live /api/replay/* endpoints. Cached at module scope so the
// list + match-detail + events ribbon share one fetch per page load.
let _replayMockPromise = null;
function _replayMockLoad() {
  if (_replayMockPromise) return _replayMockPromise;
  _replayMockPromise = fetch("/data/ui_mock/replay.json", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);
  return _replayMockPromise;
}
function _replayIsMock() {
  return document.body && document.body.dataset.uiMock === "1";
}
function _replayQueueLabel(q) {
  return ({
    400:"Normal Draft",420:"Ranked Solo",430:"Normal Blind",
    440:"Ranked Flex",450:"ARAM",700:"Clash",900:"ARURF",
    920:"Poro King",1700:"Arena",1750:"Arena",1900:"URF",2400:"ARAM Mayhem",
  })[q] || ("queue " + q);
}
function _replayDurStr(s) {
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${String(ss).padStart(2,"0")}`;
}
function _replayDateStr(ts) {
  if (!ts) return "?";
  const d = new Date(ts);
  return d.toLocaleString("en-US", { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" });
}
function _replayChampIconUrl(name) {
  if (!name) return "";
  // Use _resolveChampId so display names like "Kai'Sa" / "Wukong" / "Renata
  // Glasc" map to their on-disk DDragon ids ("Kaisa" / "MonkeyKing" /
  // "Renata"). The bare /[^A-Za-z]/ strip preserved capital letters
  // (Kai'Sa -> KaiSa) which never matched the lower-cased file (Kaisa.png).
  const cid = _resolveChampId(name) || String(name).replace(/[^A-Za-z]/g, "");
  return "/icons/champions/" + encodeURIComponent(cid) + ".png";
}
function _replayItemIconUrl(id) {
  return "/icons/items/" + id + ".png";
}
function _replayLoadItemsIndex() {
  if (_REPLAY.itemsIndex) return Promise.resolve(_REPLAY.itemsIndex);
  return fetch("/data/items_index.json")
    .then(r => r.ok ? r.json() : null)
    .then(j => { _REPLAY.itemsIndex = j; return j; })
    .catch(() => null);
}
function _replayViewRefresh() {
  // s220 PGR S5: auto-select the focused match when arriving from
  // PGR's "Review ->" button. The button stashes the match id to
  // sessionStorage.rc-replay-focus-match; we consume + clear it so
  // a later manual selection isn't overridden on the next view nav.
  let focusMatchId = null;
  try {
    focusMatchId = sessionStorage.getItem("rc-replay-focus-match") || null;
    if (focusMatchId) sessionStorage.removeItem("rc-replay-focus-match");
  } catch (_) {}
  const matchesPromise = _replayIsMock()
    ? _replayMockLoad().then((m) => (m && m.matches) ? { matches: m.matches } : null)
    : fetch("/api/replay/matches?limit=30").then(r => r.ok ? r.json() : null);
  matchesPromise
    .then(j => {
      const ul = document.getElementById("replay-match-list");
      if (!ul) return;
      ul.innerHTML = "";
      const items = (j && j.matches) || [];
      if (!items.length) {
        ul.innerHTML = '<li class="home-empty">no matches in rewind_history.db</li>';
        return;
      }
      let focusRow = null;
      for (const m of items) {
        const li = document.createElement("li");
        li.className = "replay-match-row";
        if (m.tracked && m.tracked.win === true)  li.classList.add("won");
        if (m.tracked && m.tracked.win === false) li.classList.add("lost");
        li.dataset.matchId = m.match_id;
        const champ = (m.tracked && m.tracked.champion_name) || "?";
        const verdict = m.tracked && m.tracked.win === true ? "W" :
                        m.tracked && m.tracked.win === false ? "L" : "-";
        const top = document.createElement("div");
        top.className = "replay-match-top";
        const span1 = document.createElement("span");
        span1.className = "replay-match-verdict " + (verdict === "W" ? "won" : verdict === "L" ? "lost" : "");
        span1.textContent = verdict;
        const span2 = document.createElement("span");
        span2.className = "replay-match-champ";
        span2.textContent = champ;
        const span3 = document.createElement("span");
        span3.className = "replay-match-queue";
        span3.textContent = _replayQueueLabel(m.queue_id);
        top.append(span1, span2, span3);
        const bot = document.createElement("div");
        bot.className = "replay-match-bot";
        bot.textContent = `${_replayDateStr(m.game_creation_ts)} - ${_replayDurStr(m.duration_s)} - patch ${m.patch || "?"}`;
        li.append(top, bot);
        li.addEventListener("click", () => _replayLoadMatch(m.match_id, li));
        ul.appendChild(li);
        if (focusMatchId && m.match_id === focusMatchId) focusRow = li;
      }
      // s220 PGR S5: auto-load the focused match (from PGR Review ->).
      // Fires AFTER all rows are mounted so .active highlighting works.
      if (focusRow) {
        _replayLoadMatch(focusMatchId, focusRow);
        try { focusRow.scrollIntoView({ block: "nearest" }); } catch (_) {}
      }
    })
    .catch(e => console.warn("replay matches:", e));
  _replayLoadItemsIndex();
}
function _replayLoadMatch(matchId, rowEl) {
  document.querySelectorAll(".replay-match-row.active").forEach(r => r.classList.remove("active"));
  if (rowEl) rowEl.classList.add("active");
  const meta = document.getElementById("replay-meta");
  if (meta) meta.textContent = "loading " + matchId + "...";
  // s220 PGR S5: fire the Match-V5 timeline event ribbon fetch in
  // parallel with the per-frame snapshot fetch below. Both target
  // the same matchId so the ribbon + scrubber are coherent.
  try { loadReplayEvents(matchId); } catch (_) {}
  const matchPromise = _replayIsMock()
    ? _replayMockLoad().then((m) => {
        if (!m || !Array.isArray(m.matches)) return null;
        return m.matches.find((x) => x.match_id === matchId) || null;
      })
    : fetch("/api/replay/match/" + encodeURIComponent(matchId)).then(r => r.ok ? r.json() : null);
  matchPromise
    .then(d => {
      if (!d) return;
      _REPLAY.match = d;
      _REPLAY.snapshotIdx = 0;
      const slider = document.getElementById("replay-slider");
      if (slider) {
        slider.max = String(Math.max(0, (d.snapshots || []).length - 1));
        slider.value = "0";
        slider.disabled = !((d.snapshots || []).length);
      }
      const m = document.getElementById("replay-meta");
      if (m) {
        const verdict = (d.participants || []).find(p =>
          p.champion_id === (d.tracked && d.tracked.champion_id));
        const v = verdict
          ? (verdict.team_won === true
              ? " (W)"
              : verdict.team_won === false
                ? " (L)"
                : "")
          : "";
        m.textContent = `${d.match_id} - ${_replayQueueLabel(d.queue_id)} - ${_replayDurStr(d.duration_s)} - patch ${d.patch || "?"}${v}`;
      }
      _replayRenderSnapshot(0);
    })
    .catch(e => console.warn("replay match:", e));
}
function _replayRenderSnapshot(idx) {
  const d = _REPLAY.match;
  if (!d || !d.snapshots || !d.snapshots.length) return;
  const snap = d.snapshots[Math.max(0, Math.min(idx, d.snapshots.length - 1))];
  const clock = document.getElementById("replay-clock");
  if (clock) clock.textContent = `t = ${snap.minute.toFixed(1)}min`;
  const tbody = document.getElementById("replay-grid-body");
  if (!tbody) return;
  tbody.innerHTML = "";
  const partsByPid = new Map();
  for (const p of d.participants || []) partsByPid.set(p.participant_id, p);
  // Sort: team 100 first, then team 200; preserve participant_id order.
  const entries = (snap.entries || []).slice().sort((a, b) => {
    const pa = partsByPid.get(a.participant_id);
    const pb = partsByPid.get(b.participant_id);
    const ta = (pa && pa.team_id) || 0, tb = (pb && pb.team_id) || 0;
    if (ta !== tb) return ta - tb;
    return a.participant_id - b.participant_id;
  });
  for (const e of entries) {
    const p = partsByPid.get(e.participant_id) || {};
    const tr = document.createElement("tr");
    if (p.team_won === true) tr.classList.add("won");
    if (p.team_won === false) tr.classList.add("lost");
    const cells = [
      ["replay-col-team",   p.team_id === 200 ? "R" : "B"],
      ["replay-col-champ",  null, _replayChampIconUrl(p.champion_name), p.champion_name],
      ["replay-col-name",   p.summoner_name || ""],
      ["replay-col-num",    e.level != null ? String(e.level) : "-"],
      ["replay-col-num",    e.total_gold != null ? e.total_gold.toLocaleString() : "-"],
      ["replay-col-num",    e.cs != null ? String(e.cs) : "-"],
    ];
    for (const c of cells) {
      const td = document.createElement("td");
      td.className = c[0];
      if (c[2]) {
        const img = document.createElement("img");
        img.className = "replay-champ-icon";
        img.src = c[2]; img.alt = c[3] || "";
        img.title = c[3] || "";
        const sp = document.createElement("span");
        sp.textContent = c[3] || "";
        td.append(img, sp);
      } else {
        td.textContent = c[1];
      }
      tr.appendChild(td);
    }
    const itemsCell = document.createElement("td");
    itemsCell.className = "replay-col-items";
    for (const itemId of (e.items || []).slice(0, 7)) {
      const img = document.createElement("img");
      img.className = "replay-item-icon";
      img.src = _replayItemIconUrl(itemId);
      img.alt = String(itemId);
      const lookup = _REPLAY.itemsIndex && _REPLAY.itemsIndex.byId;
      img.title = (lookup && lookup[String(itemId)]) || ("item " + itemId);
      img.onerror = () => { img.style.display = "none"; };
      itemsCell.appendChild(img);
    }
    tr.appendChild(itemsCell);
    tbody.appendChild(tr);
  }
}
// R30 page-6: seek the scrubber to a timeline event's timestamp. Maps the
// event clock (seconds) to the nearest per-frame snapshot by minute, moves
// the slider, and re-renders the grid at that frame - so a timeline click
// is real navigation (the "actionable event timeline", not a passive log).
function _replaySeekToClock(clockS) {
  const d = _REPLAY.match;
  if (!d || !Array.isArray(d.snapshots) || !d.snapshots.length) return;
  const targetMin = (Number(clockS) || 0) / 60;
  let bestIdx = 0, bestDelta = Infinity;
  for (let i = 0; i < d.snapshots.length; i++) {
    const mn = Number(d.snapshots[i].minute) || 0;
    const delta = Math.abs(mn - targetMin);
    if (delta < bestDelta) { bestDelta = delta; bestIdx = i; }
  }
  _REPLAY.snapshotIdx = bestIdx;
  const slider = document.getElementById("replay-slider");
  if (slider && !slider.disabled) slider.value = String(bestIdx);
  _replayRenderSnapshot(bestIdx);
}
function _replayViewWireOnce() {
  if (window.__replayWired) return;
  window.__replayWired = true;
  const slider = document.getElementById("replay-slider");
  if (slider) {
    slider.addEventListener("input", () => {
      _REPLAY.snapshotIdx = parseInt(slider.value, 10) || 0;
      _replayRenderSnapshot(_REPLAY.snapshotIdx);
    });
  }
  // s220 PGR S5: wire the event-ribbon filter checkboxes once.
  try { wireReplayEventsOnce(); } catch (_) {}
  // R30 page-6: let a timeline-row click drive the scrubber above.
  try { setReplaySeekHandler(_replaySeekToClock); } catch (_) {}
}

export {
  _settingsRefresh, renderSpendGates, renderLoopStatus,
  _diagFetchAndRender, _diagWireOnce,
  _replayViewWireOnce, _replayViewRefresh, _replayLoadMatch,
};
