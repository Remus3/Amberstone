// Dev panel - settings, diagnostics, dev/sim fixture viewer, replay scrubber.
import { el, safe, fmtList, _to12, logLine } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _resolveChampId } from '../lib/items_index.js';
import { applyTheme, saveTheme, readStoredTheme, queryTheme, DEFAULT_THEME } from '../lib/theme.js';
// s220 PGR S5: Match-V5 timeline event ribbon for the Replay view.
// Sidecar architecture per docs/adr/ADR-009-replay-events-cleanroom.md.
import { loadReplayEvents, wireReplayEventsOnce, setReplaySeekHandler } from './replay_events.js';

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
        meta.textContent = `${tsStr} · ${rec.mode || "?"} · ${rec.model || ""} · ${rec.latency_ms || 0}ms · in ${rec.tokens_in || 0} / out ${rec.tokens_out || 0}` +
          ((rec.cache_read || rec.cache_write) ? ` · cache r ${rec.cache_read || 0} w ${rec.cache_write || 0}` : "");
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

      const ta = mk("textarea", "loop-ta");
      ta.id = "loop-directive-input";
      ta.rows = 3;
      ta.placeholder = "one-shot directive override for the next cycle...";
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
        bot.textContent = `${_replayDateStr(m.game_creation_ts)} · ${_replayDurStr(m.duration_s)} · patch ${m.patch || "?"}`;
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
        m.textContent = `${d.match_id} · ${_replayQueueLabel(d.queue_id)} · ${_replayDurStr(d.duration_s)} · patch ${d.patch || "?"}${v}`;
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
