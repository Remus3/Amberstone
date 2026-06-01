// Riot Commander - Phase 3 dashboard. ES module - no outer IIFE.
// Subscribes to the supervisor's /push WebSocket relay (which in turn
// receives file-watcher pushes from agents/agent2_backend/file_ingest.py
// while the Game-PC Forwarder is still deferred).
//
// Envelope shapes handled:
//   {type: "heartbeat", t: <epoch>}
//   {type: "health",    source: "health",              payload: <health.json>}
//   {type: "state",     source: "<name>.json", mode: "<tag>", payload: {...}}
//
// Staleness policy per spec §5:
//   Right Now / Next: refresh 1-2s → stale at ~4s → severe at ~12s.
//   Next             ~8s refresh                  → ~16s / ~48s.
//   Item Build:      event-driven                 → 90s / 5min.

import { _to12, el, fmtList, safe, fitText, logLine, isArenaPayload, classifyAction, _opGlyph, _formatRelativeAge } from './lib/helpers.js';
import { state, CADENCE, VIEW_IDS, VIEW_LABELS, _VIEW } from './lib/state.js';
import { ITEMS, ITEM_COSTS, CHAMPS, SPELLS, _itemResolveCache, _normItemName, _resolveItemId, _splitItemList, _resolveChampId, _resolveSpell } from './lib/items_index.js';
import { idempotentRender, makeSig } from './lib/idempotent_render.js';

// ── Panel modules ─────────────────────────────────────────────────────────
import { RN, renderRightNow, renderWhatWent, renderDigest, renderGameSense, renderStats } from './panels/right_now.js';
import { renderCoachChoices } from './panels/coach_choices.js';
import { startPersonalContextPolling } from './panels/personal_context.js';
import { NX, renderNext, arenaDetectPartner, arenaPartnerLine, arenaWaveLine } from './panels/next.js';
import { IB, renderItemBuild, renderItemTiles, _updateItemBuildHeader, _ibPushItems, _ibMaybeRenderBuilds, _ibFetchAndRender, _ibSetStatus, _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice } from './panels/item_build.js';
import { MM, renderMinimap, _tickSpellCooldowns, _tickObjectiveCountdowns, _updateGameClock, _applyGamePhase, _snapshotSpells, _fmtMMSS, _renderMmStateLine } from './panels/map_state.js';
import { renderAugmentReco } from './panels/augment_reco.js';
import { handleChampSelect, renderChampSelectCoach, renderChampSelectView } from './panels/champ_select.js';
import { renderTeamContext } from './panels/team_context.js';
import { renderArchetypeNudge } from './panels/archetype_nudge_chip.js';
import { renderScreenRead } from './panels/screen_read.js';
import { renderActiveMatch, activeMatchEnabled } from './panels/active_match.js';
import { wireLastMatchOnce, fetchAndRenderLastMatch } from './panels/last_match.js';
import { renderBridgePending, renderCoachDecisions, renderRecentCoachCalls } from './panels/bridge_pending.js';
// ADR-007 (s169) - heartbeat pill self-starts on import (own setInterval).
import './panels/trigger_pill.js';
import { _settingsRefresh, renderSpendGates, _diagFetchAndRender, _diagWireOnce, _replayViewWireOnce, _replayViewRefresh, _replayLoadMatch } from './panels/dev.js';

  const WS_HOST = location.hostname || "legion-pc.local";
  const WS_PORT = 8891;
  const WS_URL = `ws://${WS_HOST}:${WS_PORT}/push`;

  // ── LCU helper (s171 restore) ──────────────────────────────────────
  // ``lcuCmd`` / ``lcuPollResult`` were referenced 22 times in main.js
  // (Find Match / Cancel / Change Lobby Mode / queue switcher / etc.)
  // but never declared in this module - the function existed only in
  // champ_select.js's module scope where main.js's callsites can't
  // reach it. Result: every operator click on a lobby button threw
  // ReferenceError silently. Restored here as plain module-local
  // helpers so the existing call sites work without import churn.
  function lcuCmd(cmdObj) {
    return fetch("/api/lcu-cmd", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cmdObj),
    }).then((r) => (r && r.ok ? r.json() : null)).catch(() => null);
  }
  function lcuPollResult(id, onResult) {
    if (!id) { onResult && onResult({ ok: false, err: "no_queue_id" }); return; }
    let tries = 0;
    const tick = () => {
      tries += 1;
      fetch("/api/lcu-cmd-result?id=" + id, { cache: "no-store" })
        .then((r) => r.json().then((j) => ({ status: r.status, body: j })))
        .then(({ status, body }) => {
          if (status === 200 && body && body.result) {
            onResult && onResult(body.result);
          } else if (tries < 6) {
            setTimeout(tick, 500);
          } else {
            onResult && onResult({ ok: false, err: "timeout" });
          }
        })
        .catch(() => {
          if (tries < 6) setTimeout(tick, 500);
          else onResult && onResult({ ok: false, err: "fetch_failed" });
        });
    };
    setTimeout(tick, 300);
  }
  // ``_lvQueueChangeError`` is the surface used when change_queue_type
  // returns ok:false. Falls back to _setLobbyStatus if it's wired (the
  // legacy lobby panel uses it); otherwise drops a console.warn so the
  // failure is at least diagnosable.
  function _lvQueueChangeError(err) {
    const msg = "Queue change failed: " + (err || "unknown");
    try {
      if (typeof _setLobbyStatus === "function") {
        _setLobbyStatus(msg, "err");
        return;
      }
    } catch (_) {}
    const sub = document.getElementById("lv-queue-sub");
    if (sub) sub.textContent = msg;
    console.warn("[lobby]", msg);
  }

  // ── DOM refs ────────────────────────────────────────────────────────
  // el() imported from lib/helpers.js; _to12 likewise.
  const statusPill = el("status-pill");
  const modePill = el("mode-pill");
  const gameTime = el("game-time");
  const kdaEl = el("kda");
  const hpEl = el("hp-bar");
  const hbEl = el("heartbeat");
  const frameCountEl = el("frame-count");
  el("ws-url").textContent = WS_URL;

  const AD = {
    root: el("adaptation"),
    status: el("adapt-status"),
    champ: el("adapt-champ"),
    baseline: el("adapt-baseline"),
    recent: el("adapt-recent"),
    kda: el("adapt-kda"),
    counters: el("adapt-counters"),
    items: el("adapt-items"),
    streaksHot: el("streaks-hot"),
    streaksCold: el("streaks-cold"),
    flagVal: el("adapt-flag-val"),
  };
  const LAT = { footer: el("input-latency-footer") };
  const ANLZ = { footer: el("analyze-footer"), btn: el("analyze-now") };
  const ACT = {
    line: el("activity-line"),
    count: el("activity-count"),
  };

  // ── Activity ticker (queue events) ──────────────────────────────────
  // Pulls /api/activity every 10s + after each /api/input response, so
  // the autonomous framework's work stays visible to the operator.
  async function refreshActivity() {
    try {
      const resp = await fetch("/api/activity?limit=6");
      if (!resp.ok) return;
      const data = await resp.json();
      const events = data.events || [];
      if (ACT.line) {
        ACT.line.innerHTML = "";
        const top = events.slice(0, 3);
        if (!top.length) {
          ACT.line.textContent = "(no events yet)";
        } else {
          for (const e of top) {
            const span = document.createElement("span");
            span.className = `activity-event event-${e.event || "?"}`;
            const ts = _to12((e.ts || "").slice(11, 19));   // 12hr AM/PM
            const op = (e.op || "").slice(0, 34);
            // Op-type glyph prefix for fast pattern-match of recent events.
            const glyph = _opGlyph(e.op);
            // AUDIT 2026-04-28 (P-audit4-m04): build the row with
            // createElement + textContent so a future event payload that
            // overrides ts/op/event with HTML can't inject markup. The
            // dashboard runs in an unsandboxed kiosk-mode Edge - any XSS
            // here can same-origin call /api/* on the supervisor.
            const g = document.createElement("span"); g.className = "ev-glyph"; g.textContent = glyph;
            const t = document.createElement("span"); t.className = "ev-ts";    t.textContent = ts;
            const o = document.createElement("span"); o.className = "ev-op";    o.textContent = op;
            const k = document.createElement("span"); k.className = "ev-kind";  k.textContent = e.event || "";
            span.append(g, t, o, k);
            span.title = `agent${e.owner_agent || "?"} · ${e.task_id} · click for detail`;
            span.dataset.taskId = e.task_id || "";
            // Round 41: expose op as data attr so CSS can pink-tag advisories.
            span.dataset.op = e.op || "";
            if (e.op && e.op.includes("advisory")) {
              span.classList.add("op-advisory");
            }
            if (e.task_id) {
              span.addEventListener("click", () => openTaskModal(e.task_id));
            }
            ACT.line.appendChild(span);
          }
        }
      }
      if (ACT.count) {
        const snap = data.snapshot || {};
        const total = snap.total || 0;
        const done = (snap.by_status && snap.by_status.completed) || 0;
        ACT.count.textContent = `${done}/${total}`;
      }
    } catch (_e) { /* non-fatal; next tick will retry */ }
  }
  // _opGlyph imported from lib/helpers.js
  refreshActivity();
  setInterval(refreshActivity, 10000);

  // ── Task detail modal ──────────────────────────────────────────────
  const TMODAL = {
    root: el("task-modal"),
    closeBtn: el("task-modal-close"),
    id: el("tm-id"),
    op: el("tm-op"),
    owner: el("tm-owner"),
    status: el("tm-status"),
    priority: el("tm-priority"),
    ts: el("tm-ts"),
    events: el("tm-events"),
  };

  function closeTaskModal() {
    if (TMODAL.root) TMODAL.root.classList.add("hidden");
  }

  async function openTaskModal(taskId) {
    if (!TMODAL.root || !taskId) return;
    TMODAL.id.textContent = taskId;
    TMODAL.op.textContent = "...";
    TMODAL.owner.textContent = TMODAL.status.textContent = "...";
    TMODAL.priority.textContent = TMODAL.ts.textContent = "...";
    TMODAL.events.innerHTML = "";
    TMODAL.root.classList.remove("hidden");
    try {
      const resp = await fetch(`/api/task/${encodeURIComponent(taskId)}`);
      if (!resp.ok) {
        TMODAL.op.textContent = `HTTP ${resp.status}`;
        return;
      }
      const d = await resp.json();
      TMODAL.id.textContent = d.id || taskId;
      TMODAL.op.textContent = d.op || "-";
      TMODAL.owner.textContent = d.owner_agent != null ? `agent${d.owner_agent}` : "-";
      TMODAL.status.textContent = d.status || "-";
      TMODAL.priority.textContent = (d.priority != null) ? String(d.priority) : "-";
      TMODAL.ts.textContent = d.created_at || "-";
      // Events, newest at top
      TMODAL.events.innerHTML = "";
      const events = (d.events || []).slice().reverse();
      if (!events.length) {
        TMODAL.events.textContent = "(no events)";
      } else {
        for (const ev of events) {
          const row = document.createElement("div");
          row.className = "tm-event-row ev-" + (ev.event || "unknown");
          const ts = (ev.ts || "").slice(11, 19);
          row.innerHTML =
            `<span class="tm-ts">${ts}</span>` +
            `<span class="tm-kind"></span>` +
            `<span class="tm-body"></span>`;
          row.children[1].textContent = ev.event || "";
          row.children[2].textContent = `→ ${ev.status || ""}`;
          TMODAL.events.appendChild(row);
        }
      }
    } catch (e) {
      TMODAL.op.textContent = "fetch error";
    }
  }

  if (TMODAL.closeBtn) TMODAL.closeBtn.addEventListener("click", closeTaskModal);
  if (TMODAL.root) {
    TMODAL.root.addEventListener("click", (e) => {
      if (e.target === TMODAL.root) closeTaskModal();   // click backdrop
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeTaskModal();
  });

  // ── Insight-card COPY button ────────────────────────────────────────
  const ADAPT_COPY_BTN = el("adapt-copy");
  if (ADAPT_COPY_BTN) {
    ADAPT_COPY_BTN.addEventListener("click", async () => {
      // Look up current champion/mode/enemies from latest state frame.
      const latest = state.latest || {};
      // Prefer any payload with a champion field (ARAM/SR have it).
      let champ = "";
      let enemies = [];
      for (const p of Object.values(latest)) {
        if (p && typeof p === "object") {
          if (!champ && p.champion) champ = String(p.champion);
          if (Array.isArray(p.enemy_comp) && !enemies.length) {
            enemies = p.enemy_comp.filter(Boolean);
          }
        }
      }
      if (!champ) {
        ADAPT_COPY_BTN.textContent = "NO CHAMP";
        setTimeout(() => { ADAPT_COPY_BTN.textContent = "COPY CARD"; }, 1500);
        return;
      }
      const modeMap = {
        sr: "sr_ranked", aram: "aram", arena: "arena",
        brawl: "brawl", tft: "aram", client: "aram",
      };
      const mode = modeMap[state.mode] || "aram";
      const enemyParam = enemies.length
        ? `&enemies=${encodeURIComponent(enemies.join(","))}` : "";
      const originalText = ADAPT_COPY_BTN.textContent;
      ADAPT_COPY_BTN.disabled = true;
      try {
        const resp = await fetch(
          `/api/insight-card?champion=${encodeURIComponent(champ)}&mode=${mode}${enemyParam}`,
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const payload = await resp.json();
        const card = payload.card || "";
        if (!card) {
          ADAPT_COPY_BTN.textContent = "NO DATA";
        } else {
          // Clipboard API. On iPad Chrome kiosk this requires a secure
          // context or user gesture - the button click qualifies.
          try {
            await navigator.clipboard.writeText(card);
            ADAPT_COPY_BTN.textContent = `COPIED (${payload.chars}c)`;
          } catch (_e) {
            // Fallback: fill a hidden textarea and execCommand.
            const ta = document.createElement("textarea");
            ta.value = card;
            ta.style.position = "fixed"; ta.style.top = "-100px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            ADAPT_COPY_BTN.textContent = `COPIED (${payload.chars}c)`;
          }
        }
      } catch (_e) {
        ADAPT_COPY_BTN.textContent = "ERR";
      } finally {
        setTimeout(() => {
          ADAPT_COPY_BTN.textContent = originalText;
          ADAPT_COPY_BTN.disabled = false;
        }, 2000);
      }
    });
  }

  if (ANLZ.btn) {
    ANLZ.btn.addEventListener("click", async () => {
      ANLZ.btn.disabled = true;
      const modeTag = state.mode;
      const modeMap = {
        sr: "sr_ranked", aram: "aram", arena: "arena",
        brawl: "brawl", tft: null, client: null,
      };
      const mode = modeMap[modeTag] || null;
      try {
        const body = mode ? { mode } : {};
        const resp = await fetch("/api/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (resp.ok) {
          refreshEnv();  // surface last_run_ago
        }
      } catch (_e) {
        // non-fatal; env poll will catch up
      } finally {
        setTimeout(() => { ANLZ.btn.disabled = false; }, 1500);
      }
    });
  }

  // state, CADENCE imported from lib/state.js
  // (spellCds and deadUntil are added to state at runtime below)

  // ── Helpers ─────────────────────────────────────────────────────────
  // The visible connection state now lives in the heartbeat pill's color:
  // green when connected, muted gray when offline/pending. The old
  // "status-pill" element was removed so the row 2 right group reads
  // cleanly as advisory + trend + heartbeat.
  function setStatus(label, cls) {
    if (statusPill) {
      statusPill.title = label;
      statusPill.className = `pill ${cls}`;
    }
    if (hbEl) {
      hbEl.classList.toggle("hb-connected", cls === "connected");
      hbEl.classList.toggle("hb-offline", cls !== "connected");
      hbEl.title = label;
    }
  }
  function _pulseStatus() {
    if (!statusPill) return;
    statusPill.classList.remove("pill-pulse");
    void statusPill.offsetWidth;
    statusPill.classList.add("pill-pulse");
  }

  // ── Transition log (s158) ─────────────────────────────────────────
  // Capture every mode/view change so flicker is debuggable from the
  // dashboard itself without opening DevTools. Three sinks:
  //   1. console.log (always) - visible in F12.
  //   2. window.__rcDebugLog ring buffer (last 50) - inspectable.
  //   3. Floating overlay #rc-dbg (when location.search includes dbg=1
  //      or localStorage.rcDebug==='1') - always-on screen tail of
  //      the last 8 lines, monospace, mode pill bottom right corner.
  // The overlay is wired once on first call.
  if (!window.__rcDebugLog) window.__rcDebugLog = [];
  const _RC_DEBUG_ON = (() => {
    try {
      if (location.search.includes("dbg=1")) return true;
      return localStorage.getItem("rcDebug") === "1";
    } catch (_) { return false; }
  })();
  function _rcDbgEnsureOverlay() {
    if (!_RC_DEBUG_ON) return null;
    let ov = document.getElementById("rc-dbg");
    if (ov) return ov;
    ov = document.createElement("div");
    ov.id = "rc-dbg";
    ov.style.cssText = [
      "position:fixed", "right:8px", "bottom:32px",
      "max-width:520px", "max-height:160px", "overflow:hidden",
      "padding:6px 8px", "z-index:9999",
      "background:rgba(0,0,0,0.78)", "color:#cfd8dc",
      "border:1px solid #455a64", "border-radius:6px",
      "font:11px/1.35 ui-monospace,Consolas,monospace",
      "white-space:pre", "pointer-events:none",
    ].join(";");
    document.body.appendChild(ov);
    return ov;
  }
  function _rcDbgPaint() {
    const ov = _rcDbgEnsureOverlay();
    if (!ov) return;
    const tail = window.__rcDebugLog.slice(-8);
    ov.textContent = tail.map((e) => {
      const t = new Date(e.t).toISOString().slice(11, 23);
      const meta = e.meta
        ? " " + Object.entries(e.meta).map(([k, v]) => `${k}=${v}`).join(" ")
        : "";
      return `${t} ${e.kind}: ${e.from || "-"} → ${e.to}${meta}`;
    }).join("\n");
  }
  function _rcLogTransition(kind, from, to, meta) {
    const entry = { t: Date.now(), kind, from: from || null, to, meta: meta || null };
    window.__rcDebugLog.push(entry);
    if (window.__rcDebugLog.length > 50) window.__rcDebugLog.shift();
    const metaStr = meta
      ? " " + Object.entries(meta).map(([k, v]) => `${k}=${v}`).join(" ")
      : "";
    console.log(`[rc-${kind}] ${from || "-"} → ${to}${metaStr}`);
    _rcDbgPaint();
  }

  function setMode(tag) {
    if (!tag || tag === state.mode) return;
    // s158: transition log so flicker is observable without DevTools tracing.
    // Stamps every actual mode change (early-return-guarded above) into a
    // ring buffer + console.log + (when ?dbg=1) the floating overlay.
    _rcLogTransition("mode", state.mode, tag);
    state.mode = tag;
    modePill.textContent = (tag || "client").toUpperCase();
    modePill.className = `mode-pill ${tag}`;
    // 2026-05-25 item 201 fix: stamp a baseline document.title on every
    // mode flip so the browser tab doesn't carry the prior game's
    // champion + game_time after the operator returns to lobby
    // (renderHeader, which authors the enriched title, bails on
    // !driveNow for client/sr-without-coach-data). Coach ticks for
    // in-game modes overwrite this with "RC · <champ> · <MODE> · <t>".
    try { document.title = "RC · " + (tag || "client").toUpperCase(); } catch (_) {}
    // Mode-aware CSS hook for minimap panel (SR underlay only on SR).
    const mmPanel = document.querySelector(".panel-minimap");
    if (mmPanel) mmPanel.className = "panel panel-minimap mode-" + tag;
    // body[data-mode] drives mode-scoped layout rules (in-game Adaptation
    // shrink, aftergame panel reassignment, TFT map-state swap, etc.).
    document.body.dataset.mode = tag;
    // Panel title swaps per mode (queue #3 aftergame reassignment).
    //   in-game (sr/aram/arena/brawl/tft):
    //     MAP STATE / RIGHT NOW / NEXT / STATS
    //   client (lobby + aftergame):
    //     WHAT WENT / SESSION SUMMARY / ADVICE / GAME SENSE
    const inGame = ["sr","aram","arena","brawl","tft"].includes(tag);
    const titles = inGame
      ? { mm: "MAP STATE", rn: "RIGHT NOW", nx: "NEXT", adapt: "STATS" }
      : { mm: "WHAT WENT", rn: "SESSION SUMMARY", nx: "ADVICE", adapt: "GAME SENSE" };
    const mmT    = el("mm-panel-title");    if (mmT)    mmT.textContent    = titles.mm;
    const rnT    = el("rn-panel-title");    if (rnT)    rnT.textContent    = titles.rn;
    const nxT    = el("nx-panel-title");    if (nxT)    nxT.textContent    = titles.nx;
    const adaptT = el("adapt-panel-title"); if (adaptT) adaptT.textContent = titles.adapt;
  }

  // ── View router (2026-04-26) ──────────────────────────────────────
  // VIEW_IDS, VIEW_LABELS, _VIEW imported from lib/state.js.
  function _viewFromHash() {
    const h = (location.hash || "").replace(/^#/, "").trim();
    return VIEW_IDS.includes(h) ? h : null;
  }
  function _viewFromStorage() {
    try { return localStorage.getItem("rc-view-manual") || null; }
    catch (_) { return null; }
  }
  function _viewSaveManual(id) {
    try {
      if (id) localStorage.setItem("rc-view-manual", id);
      else    localStorage.removeItem("rc-view-manual");
    } catch (_) {}
    _VIEW.manual = id;
  }
  // Auto-derive view from observed state. Returns one of VIEW_IDS.
  // MIRROR: dashboard/view_router_state.py is a pytest-only Python mirror
  // of this transition table (audit #11 / 4.D). If you change the logic
  // here, change it there too - both must agree on the same table.
  function _viewAutoDerive(lcu, mode) {
    const phase = lcu && lcu.phase;
    // s171 post-CS sticky guard: once we've entered ChampSelect, the
    // dashboard should never drop back to home/lobby until the game has
    // cleanly resolved. LCU briefly emits phase=null or stale phase=Lobby
    // during the CS→GameStart→InProgress flip; track the highest
    // game-state we've observed so transient blips don't flush the view.
    //
    // s209: dropped the "game-start" sticky tier - loading view retired,
    // GameStart is treated as in-progress (advances sticky directly).
    // CS→null inference now advances to "in-progress" so the gap renders
    // active-match instead of the now-deleted loading screen.
    if (phase === "ChampSelect")                _VIEW.gameStarted = "champ-select";
    else if (phase === "GameStart")             _VIEW.gameStarted = "in-progress";
    else if (phase === "InProgress")            _VIEW.gameStarted = "in-progress";
    else if (phase === "EndOfGame" || phase === "PreEndOfGame"
            || phase === "WaitingForStats" || phase === "TerminatedInError"
            || phase === "Lobby" || phase === "Matchmaking"
            || phase === "ReadyCheck" || phase === "None") {
      // Only clear the sticky guard on a STABLE post-game phase. Treat
      // Lobby/Matchmaking/ReadyCheck/None as "post-game" when the prior
      // session-state was in-progress.
      if (_VIEW.gameStarted === "in-progress"
          && (phase === "EndOfGame" || phase === "PreEndOfGame"
              || phase === "WaitingForStats" || phase === "TerminatedInError"
              || phase === "Lobby")) {
        _VIEW.gameStarted = null;
      }
      // s171.8: dodge handling - ChampSelect → Lobby/Matchmaking/etc.
      // means user backed out before game start. Clear the sticky guard
      // so the auto-derive doesn't keep them on the now-stale CS view.
      else if (_VIEW.gameStarted === "champ-select"
               && (phase === "Lobby" || phase === "Matchmaking"
                   || phase === "ReadyCheck" || phase === "None")) {
        _VIEW.gameStarted = null;
      }
    }
    // s209: ChampSelect ended but phase isn't a stable state - must be
    // the gap between CS ending and InProgress firing. Advance sticky
    // straight to "in-progress" so the gap renders active-match (the
    // loading view used to live here pre-s209).
    else if (_VIEW.gameStarted === "champ-select" && !phase) {
      _VIEW.gameStarted = "in-progress";
    }
    // s209: GameStart routes directly to active-match. The loading
    // view was retired (games load too fast for it to be useful);
    // active-match panels render their own "waiting for liveclient"
    // empty state until data arrives.
    if (phase === "GameStart" && activeMatchEnabled()) return "active-match";
    // s159: Active Match is mid-game-only. s171.2: tightened gate -
    // require LCU phase=InProgress explicitly. Previously fell back to
    // the legacy `state.mode in {sr,aram,arena,brawl,tft}` heuristic,
    // but that mode_key sticks at "sr" through ChampSelect for the
    // next game, which wrongly promoted active-match (with stale
    // coach data from the previous game) during champ-select.
    // The mode-key fallback now only fires when LCU phase is unknown
    // (empty/null) - i.e. the LCU agent isn't reporting - AND mode
    // says in-game, which is the rare crash-recovery path.
    if (activeMatchEnabled() && phase === "InProgress") {
      return "active-match";
    }
    const inGame = ["sr", "aram", "arena", "brawl", "tft"].includes(mode);
    if (activeMatchEnabled() && !phase && inGame) {
      return "active-match";
    }
    // s164: ChampSelect routes to the dedicated full-page view.
    if (phase === "ChampSelect") return "champ-select";
    if (phase === "InProgress") return "last-match";  // panels are in-game in game mode
    // s209 sticky guard: in-progress sticky carries through transient
    // null/Lobby blips so the view doesn't flush mid-game.
    if (_VIEW.gameStarted === "in-progress") {
      return activeMatchEnabled() ? "active-match" : "last-match";
    }
    if (_VIEW.gameStarted === "champ-select") return "champ-select";
    if (phase === "Lobby" || phase === "Matchmaking" || phase === "ReadyCheck") return "lobby";
    if (mode === "client" || mode === "lobby" || !mode) return "home";
    return "last-match";  // in-game default → main panels
  }
  // Should we auto-promote past a manual selection? Only for urgent
  // game-state events where missing the actual view is harmful.
  function _viewIsUrgent(targetView) {
    return targetView === "lobby"   // pre-queue lobby
        || targetView === "champ-select"  // s164: full-page CS
        || targetView === "active-match"  // s209: in-game (was loading→active)
        || targetView === "last-match";  // game InProgress fallback
  }
  function applyView(viewId) {
    if (!VIEW_IDS.includes(viewId)) viewId = "home";
    if (viewId === _VIEW.current) {
      _viewUpdateMenuActive(viewId);
      return;
    }
    _rcLogTransition("view", _VIEW.current, viewId,
      { manual: !!_VIEW.manual, mode: state.mode });
    _VIEW.current = viewId;
    document.body.dataset.view = viewId;
    _viewUpdateTitleLabel(viewId);
    _viewUpdateMenuActive(viewId);
    // Lazy-fetch view content (wire-once + fetch on first activate)
    if (viewId === "lobby")       { _lobbyViewWireOnce(); _lobbyViewRefresh(); }
    if (viewId === "champ-select") { renderChampSelectView(_csResolveLcu()); }
    // Item 188: kick the Active Match mock dispatcher on view-change so
    // navigating to #active-match with ?ui_mock=1&mode=<X> renders even
    // before the next state envelope tick fires.
    if (viewId === "active-match" && _amIsMock() && _amMockUrl()) {
      if (_amMockData) {
        renderActiveMatch(_amMockData.coach || {}, {
          mode: _amMockData.mode || "sr",
          lcuPhase: _amMockData.phase || "InProgress",
          liveclient: _amMockData.liveclient || null,
          cooldowns: _amMockData.summoner_cooldowns || null,
        });
      } else {
        _amMockLoad();
      }
    }
    if (viewId === "session")     { _sessionFetchAndRender(); }
    if (viewId === "history")     { _historyWireOnce(); _historyFetchAndRender(); }
    if (viewId === "last-match")  { wireLastMatchOnce(); fetchAndRenderLastMatch(); }
    if (viewId === "replay")      { _replayViewWireOnce(); _replayViewRefresh(); }
    if (viewId === "user-builds") {
      _userBuildsWireOnce();
      _userBuildsFetchAndRender();
      // Dev override: ?ub_form=mock auto-opens the form pane with the
      // first mock-fixture build pre-loaded so headless-Chrome audit
      // captures land on the rune-builder + spell-chooser rendered.
      try {
        const p = new URLSearchParams(location.search || "");
        if (p.get("ub_form") === "mock" && document.body.dataset.uiMock === "1") {
          fetch("/data/ui_mock/user_builds.json", { cache: "no-store" })
            .then((r) => (r && r.ok ? r.json() : null))
            .then((d) => {
              const first = d && d.builds && d.builds[0];
              if (!first) return;
              _UB.champion = d.champion || "Tristana";
              setTimeout(() => _userBuildsOpenForm(first), 100);
            }).catch(() => {});
        }
      } catch (_) {}
    }
    if (viewId === "settings")    { _settingsRefresh(); _settingsLobbyWireOnce(); _syncAutoAcceptUI(); renderSpendGates(); }
  }
  function _viewUpdateTitleLabel(viewId) {
    const el = document.getElementById("view-current-label");
    if (el) el.textContent = (_VIEW.manual ? "" : "AUTO · ") + (VIEW_LABELS[viewId] || viewId).toUpperCase();
    // s162: ↻ AUTO header pill removed. Operator clears manual via the
    // "↻ Auto (clear manual)" entry in the title dropdown menu.
  }
  function _viewUpdateMenuActive(viewId) {
    document.querySelectorAll(".view-menu-item").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === viewId);
    });
  }
  function _viewMenuClose() {
    const m = document.getElementById("view-menu");
    const t = document.getElementById("view-trigger");
    if (m) { m.classList.add("hidden"); m.setAttribute("aria-hidden", "true"); }
    if (t) t.setAttribute("aria-expanded", "false");
  }
  function _viewMenuToggle() {
    const m = document.getElementById("view-menu");
    const t = document.getElementById("view-trigger");
    if (!m || !t) return;
    const open = m.classList.contains("hidden");
    if (open) {
      m.classList.remove("hidden");
      m.setAttribute("aria-hidden", "false");
      t.setAttribute("aria-expanded", "true");
      // Positioning is fully CSS-driven now (v5): the menu is a child
      // of .header-row-1 (which is position:relative), and CSS sets
      // top: 100% + margin-top: 6px + left: 0. No zoom math, no
      // getBoundingClientRect. Clear any stale inline coords from
      // earlier v3/v4 fixed-positioning attempts so they don't stick.
      m.style.top = ""; m.style.left = "";
    } else {
      _viewMenuClose();
    }
  }
  function _viewWireOnce() {
    if (_VIEW._wired) return;
    _VIEW._wired = true;
    const trig = document.getElementById("view-trigger");
    const menu = document.getElementById("view-menu");
    // (v7) Reparent the menu to <body> so no header/row positioning
    // quirk can shift it. Combined with CSS position: fixed + hardcoded
    // top, the menu lands at viewport y = 70 * body-zoom regardless
    // of the cascade above it.
    if (menu && menu.parentElement !== document.body) {
      document.body.appendChild(menu);
    }
    if (trig) trig.addEventListener("click", (e) => { e.stopPropagation(); _viewMenuToggle(); });
    document.addEventListener("click", (e) => {
      if (menu && !menu.contains(e.target) && e.target !== trig) _viewMenuClose();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") _viewMenuClose();
    });
    document.querySelectorAll(".view-menu-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const v = btn.dataset.view;
        _viewMenuClose();
        if (v === "auto") {
          _viewSaveManual(null);
          location.hash = "";
        } else if (v === "dev") {
          _viewSaveManual("dev");
          location.hash = "#dev";
        } else {
          _viewSaveManual(v);
          location.hash = "#" + v;
        }
        _viewResolveAndApply();
      });
    });
    // s162: prominent ↻ AUTO pill removed. The dropdown's "↻ Auto
     // (clear manual)" item already triggers the same path through the
    // view-menu-item click handler above (data-view="auto" branch).
    window.addEventListener("hashchange", _viewResolveAndApply);
    // Initial manual state from localStorage
    _VIEW.manual = _viewFromStorage();
    // Banner buttons
    const accept = document.getElementById("view-banner-accept");
    if (accept) accept.addEventListener("click", () => {
      const target = accept.dataset.target;
      if (target) {
        _viewSaveManual(null);
        location.hash = "#" + target;
        _viewResolveAndApply();
      }
      _viewBannerHide();
    });
    const dismiss = document.getElementById("view-banner-dismiss");
    if (dismiss) dismiss.addEventListener("click", () => {
      _VIEW.bannerDismissed = accept && accept.dataset.target;
      _viewBannerHide();
    });
  }
  function _viewBannerShow(target, text) {
    const b = document.getElementById("view-banner");
    const t = document.getElementById("view-banner-text");
    const accept = document.getElementById("view-banner-accept");
    if (!b || !accept) return;
    if (t) t.textContent = text;
    accept.dataset.target = target;
    b.classList.remove("hidden");
  }
  function _viewBannerHide() {
    const b = document.getElementById("view-banner");
    if (b) b.classList.add("hidden");
  }
  // Resolve current view from hash → manual → auto, then apply.
  // Also handle the auto-promote banner when manual blocks an urgent
  // auto target.
  function _viewResolveAndApply(latestLcu) {
    const lcu = latestLcu || (state.latest && state.latest.lcu) || {};
    const auto = _viewAutoDerive(lcu, state.mode);
    const hashView = _viewFromHash();
    let manual = hashView || _VIEW.manual;
    // s209: auto-clear a stale manual game-state selection whenever the
    // auto-derived view is ALSO a game-state surface (lobby / champ-select
    // / active-match / last-match). Pre-s209 only the in-game surfaces
    // triggered the clear, which left operators stuck on a stale "lobby"
    // manual when phase advanced to ChampSelect - they saw the SWITCH
    // banner instead of the actual CS page. hashView (?#lobby etc) wins
    // since it's URL-level.
    //
    // Sticky-allowed during in-game: session / history / replay /
    // user-builds / settings / dev. The operator may intentionally
    // pull these up mid-game to check past stats or tweak settings;
    // those aren't in _staleManual so they stay sticky.
    const _midFlight = (auto === "lobby"
                      || auto === "champ-select"
                      || auto === "active-match"
                      || auto === "last-match");
    const _staleManual = (manual === "home" || manual === "lobby"
                       || manual === "champ-select"
                       || manual === "active-match"
                       || manual === "last-match");
    // A hash pointing at a *game-state* surface (e.g. #lobby set by the
    // Home Find-Match route at the lcuCmd callsite, or a menu-nav to
    // lobby) is itself stale once the live game advances to a DIFFERENT
    // game-state surface. The s209 stale-manual clear used to bail
    // whenever ANY hash was present (`!hashView`), which froze the
    // operator on #lobby through the whole lobby→champ-select→active-
    // match flow - the urgent-promote banner showed but it never auto-
    // switched. Treat a stale game-state hash like a stale manual: clear
    // it AND the URL hash so the flow auto-advances. Non-game-state
    // hashes (#settings/#history/#replay/#session/#user-builds) stay
    // sticky exactly as before - the operator pulled those up on purpose.
    const _hashIsStaleGameState = !!hashView && hashView !== auto
                      && (hashView === "home" || hashView === "lobby"
                          || hashView === "champ-select"
                          || hashView === "active-match"
                          || hashView === "last-match");
    if (_midFlight && _staleManual && (!hashView || _hashIsStaleGameState)) {
      _viewSaveManual(null);
      if (_hashIsStaleGameState) { try { location.hash = ""; } catch (_) {} }
      _VIEW.bannerDismissed = null;
      manual = null;
    }
    if (manual) {
      // Manual sticky - apply it
      applyView(manual);
      // Banner if auto wants to promote to an urgent target we're not on
      if (_viewIsUrgent(auto) && auto !== manual && auto !== _VIEW.bannerDismissed) {
        let urgentLead = "Game in progress";
        if (auto === "lobby" || auto === "champ-select") urgentLead = "Champ Select active";
        _viewBannerShow(auto,
          urgentLead + " - switch to " + (VIEW_LABELS[auto] || auto) + "?");
      } else {
        _viewBannerHide();
      }
    } else {
      _VIEW.bannerDismissed = null;
      applyView(auto);
      _viewBannerHide();
    }
  }

  // fmtList, safe, fitText, logLine, isArenaPayload, classifyAction imported from lib/helpers.js


  // ── WHAT WENT view (aftergame Map State replacement) ──────────────



  // don't collapse. No hits on the main render path.
  function showKdaBurst(kind) {
    const burst = document.createElement("span");
    burst.className = "kda-burst kda-burst-" + kind;
    burst.textContent = kind === "kill" ? "KILL" : kind === "assist" ? "ASSIST" : "DEATH";
    // Anchor inside the KDA element so position:absolute is relative to it.
    kdaEl.appendChild(burst);
    requestAnimationFrame(() => burst.classList.add("show"));
    setTimeout(() => burst.remove(), 1600);
  }

  function renderHeader(p) {
    // In lobby / matchmaking / champ-select / aftergame (state.mode === "client")
    // there's no live game; in-game pills (CS/KDA/level/gold/vision/ult/game-time)
    // would just show stale values from the prior game. Hide the lot and return.
    // Exception: keep KDA visible in aftergame so the operator can review the
    // just-finished match - but blank the in-game-only pills.
    // Hide in-game pills whenever the operator-facing surface isn't an
    // in-game view. The active view is the most reliable signal -
    // state.mode can be "sr" with empty lcu (live LCU not forwarding
    // lobby data), and lcu.phase can be undefined for the same reason,
    // but if the operator is on the lobby/home/session/etc view they
    // never want WIN% / ZOI / CS / vision / game-time pills cluttering
    // the header.
    const _activeView = (_VIEW && _VIEW.current) || null;
    // s219: last-match is now the Post Game Review page (operator
    // doesn't want live in-game pills cluttering the header there).
    // Only active-match is treated as in-game for the pill-visibility
    // gate. View-router still recognises last-match elsewhere.
    const _isInGameView = (_activeView === "active-match");
    if (state.mode === "client" || !_isInGameView) {
      const inGamePills = [
        "lvl-pill", "vis-pill", "ult-pill", "cs-pill", "gold-pill",
        // s162: hide WIN% + ZOI + game-time in pre-game per operator.
        "win-pill", "zone-pill", "game-time",
      ];
      for (const id of inGamePills) {
        const e = el(id);
        if (e) e.classList.add("hidden");
      }
      if (gameTime) gameTime.textContent = "";
      return;
    }
    if (typeof p.game_time_s === "number") {
      gameTime.textContent = _fmtMMSS(p.game_time_s);
    } else if (p.game_time != null) {
      gameTime.textContent = safe(p.game_time);
    }
    const lvlPill = el("lvl-pill"), lvlVal = el("lvl-val");
    const visPill = el("vis-pill"), visVal = el("vis-val");
    if (lvlPill && lvlVal) {
      if (typeof p.level === "number") {
        lvlVal.textContent = p.level;
        lvlPill.classList.remove("hidden");
        // Power-spike highlight at 6, 11, 16 (classic caster/tank spikes).
        lvlPill.classList.toggle("spike", p.level === 6 || p.level === 11 || p.level === 16);
      } else lvlPill.classList.add("hidden");
    }
    if (visPill && visVal) {
      if (typeof p.vision_score === "number") {
        visVal.textContent = p.vision_score;
        visPill.classList.remove("hidden");
      } else visPill.classList.add("hidden");
    }
    const ultPill = el("ult-pill"), ultVal = el("ult-val");
    if (ultPill && ultVal) {
      // Accept either r_cooldown_s (numeric) or r_ready (bool).
      if (typeof p.r_cooldown_s === "number") {
        const cd = Math.max(0, Math.round(p.r_cooldown_s));
        if (cd > 0) {
          ultVal.textContent = cd >= 60 ? Math.floor(cd/60) + "m" + (cd%60).toString().padStart(2,"0") : cd + "s";
          ultPill.className = "ult-pill ult-cd";
        } else {
          ultVal.textContent = "UP";
          ultPill.className = "ult-pill ult-ready";
        }
        ultPill.classList.remove("hidden");
      } else if (p.r_ready === true) {
        ultVal.textContent = "UP";
        ultPill.className = "ult-pill ult-ready";
        ultPill.classList.remove("hidden");
      } else {
        ultPill.classList.add("hidden");
      }
    }
    const csPill = el("cs-pill"), csVal = el("cs-val");
    const goldPill = el("gold-pill"), goldVal = el("gold-val");
    if (csPill && csVal) {
      if (typeof p.cs === "number" || typeof p.minions_killed === "number") {
        const cs = Math.round(p.cs ?? p.minions_killed);
        csVal.textContent = cs;
        csPill.classList.remove("hidden");
        // CS/m suffix when we have a game clock. ~7-8 CS/m is solid mid-game.
        if (typeof p.game_time_s === "number" && p.game_time_s > 60) {
          const cspm = (cs / (p.game_time_s / 60));
          csVal.textContent = cs + " · " + cspm.toFixed(1) + "/m";
          // Color-code by benchmark.
          csPill.className = "cs-pill cs-" + (
            cspm >= 8 ? "excellent" :
            cspm >= 6 ? "good" :
            cspm >= 4 ? "fair" : "low"
          );
        }
      } else csPill.classList.add("hidden");
    }
    if (goldPill && goldVal) {
      if (typeof p.gold === "number") {
        const g = Math.round(p.gold);
        goldVal.textContent = g >= 1000 ? (g/1000).toFixed(1) + "k" : g;
        goldPill.classList.remove("hidden");
        // CSS also - CSS/m (creep-score per minute) as tooltip.
        if (typeof p.game_time_s === "number" && p.game_time_s > 60 && typeof p.cs === "number") {
          const cspm = (p.cs / (p.game_time_s / 60)).toFixed(1);
          goldPill.title = `gold · CS/m ${cspm}`;
        }
      } else goldPill.classList.add("hidden");
    }
    // Mode-sensitive visibility: KDA/CS are hidden in TFT (no individual
    // K/D/A + creep score in that mode).
    const isTft = state.mode === "tft";
    if (isTft) {
      kdaEl.classList.add("hidden");
      if (csPill) csPill.classList.add("hidden");
    } else {
      kdaEl.classList.remove("hidden");
    }
    let kdaRatioClass = "";
    if (p.kda != null) {
      // KDA pill shows only the raw x/y/z. Ratio is still computed for
      // color class (carry/even/struggle) but no longer rendered as text -
      // the color communicates performance band at a glance.
      const m = /^(\d+)\/(\d+)\/(\d+)$/.exec(safe(p.kda));
      if (m) {
        const K = +m[1], D = +m[2], A = +m[3];
        const r = D === 0 ? (K + A) : (K + A) / D;
        kdaRatioClass = r >= 3 ? "kda-carry" : r >= 1.5 ? "kda-even" : "kda-struggle";
      }
      const newText = safe(p.kda);
      if (kdaEl.textContent !== newText && kdaEl.textContent !== "-") {
        // Diff prior vs new K/D/A to decide which event fired.
        const mPrev = /(\d+)\/(\d+)\/(\d+)/.exec(kdaEl.textContent);
        const mNext = /(\d+)\/(\d+)\/(\d+)/.exec(newText);
        let evt = null;
        if (mPrev && mNext) {
          if (+mNext[1] > +mPrev[1]) evt = "kill";
          else if (+mNext[2] > +mPrev[2]) evt = "death";
          else if (+mNext[3] > +mPrev[3]) evt = "assist";
        }
        kdaEl.classList.remove("kda-flash", "kda-evt-kill", "kda-evt-assist", "kda-evt-death");
        void kdaEl.offsetWidth;
        kdaEl.classList.add("kda-flash");
        if (evt) kdaEl.classList.add("kda-evt-" + evt);
        if (evt) showKdaBurst(evt);
      }
      kdaEl.textContent = newText;
      // Apply KDA ratio band class.
      kdaEl.classList.remove("kda-carry", "kda-even", "kda-struggle");
      if (kdaRatioClass) kdaEl.classList.add(kdaRatioClass);
    }
    // Live win probability pill - hidden if state doesn't provide it.
    const winPill = el("win-pill");
    const winVal = el("win-pct-val");
    if (winPill && winVal) {
      if (typeof p.win_pct === "number") {
        const v = Math.round(p.win_pct);
        winVal.textContent = v + "%";
        winPill.classList.remove("hidden");
        // AUDIT 2026-04-28 (proposal 3.5): 5-band gradient instead of 4
        // so a 26% loss reads visibly different from a 12% loss.
        winPill.className = "win-pill win-" + (
          v >= 70 ? "strong" :   // green
          v >= 55 ? "lead"   :   // lime
          v >= 45 ? "even"   :   // amber
          v >= 30 ? "behind" :   // orange
                    "losing"      // red
        );
      } else {
        winPill.classList.add("hidden");
      }
    }

    const hpFill = el("hp-bar-fill");
    // Mana / resource bar - hidden when champion has none (Tryndamere etc)
    const mpGroup = el("mp-group"), mpBar = el("mp-bar"), mpFill = el("mp-bar-fill");
    if (mpGroup && mpBar && mpFill) {
      if (typeof p.mp_pct === "number" && p.mp_pct >= 0) {
        const v = Math.round(p.mp_pct);
        mpBar.textContent = `MP ${v}%`;
        mpFill.style.width = v + "%";
        mpGroup.classList.remove("hidden");
      } else {
        mpGroup.classList.add("hidden");
      }
    }
    if (p.is_dead) {
      // Dead state: HP pill renders just the countdown number in red; the
      // "DEAD" word and "s" suffix are elided (the color + bar-empty state
      // already communicates what's happening). Reads as "18" → "17" ...
      const tLeft = Math.max(0, Math.round(p.respawn_in_s || 0));
      hpEl.textContent = tLeft > 0 ? String(tLeft) : "UP";
      hpEl.className = "hp hp-dead";
      if (hpFill) { hpFill.style.width = "0%"; hpFill.className = "hp-fill hp-dead"; }
      state.deadUntil = Date.now() + tLeft * 1000;
    } else if (p.hp_pct != null) {
      const v = Math.round(p.hp_pct);
      hpEl.textContent = `HP ${v}%`;
      const band = v <= 20 ? "critical" : v <= 40 ? "low" : v <= 75 ? "mid" : "high";
      hpEl.className = "hp hp-" + band;
      if (hpFill) {
        hpFill.style.width = v + "%";
        hpFill.className = "hp-fill hp-" + band;
      }
      state.deadUntil = 0;
    }
    // Round 45: live champion from state payload overrides the fallback.
    if (p.champion) setChampionPill(p.champion, "live");
    // Render user's own summoner spells from ally_spells[my-champion].
    // Always-visible per the static-pill rule: when no spell data is
    // available (client mode, pre-game, unknown champion), render two
    // placeholder cells labelled "D" and "F" so the slot stays occupied
    // and positionally stable.
    const selfSpellsEl = el("self-spells");
    const selfSpellsData = (p.ally_spells || {})[p.champion];
    // Skip the DOM build entirely when the slot is hidden by CSS - the
    // header `display: none !important` rule kills layout/paint anyway,
    // but every coach tick was still creating + destroying spell cells
    // that never rendered. Cheap getComputedStyle check on a stable
    // element is fine here (we don't iterate it).
    if (selfSpellsEl && getComputedStyle(selfSpellsEl).display !== "none") {
      selfSpellsEl.classList.remove("hidden");
      selfSpellsEl.innerHTML = "";
      if (selfSpellsData && selfSpellsData.length) {
        selfSpellsData.slice(0, 2).forEach(s => {
          const sname = typeof s === "string" ? s : s.spell;
          const spell = _resolveSpell(sname);
          const cell = document.createElement("span");
          cell.className = "self-spell";
          cell.dataset.cdKey = _spellKey(p.champion, sname);
          if (spell) {
            const img = document.createElement("img");
            img.src = `/data/ddragon/16.11.1/img/spell/${spell.img}`;
            img.alt = spell.name;
            cell.title = spell.name;
            cell.appendChild(img);
            const cdLabel = document.createElement("b");
            cdLabel.className = "cd-label";
            cell.appendChild(cdLabel);
          } else {
            cell.textContent = (sname || "?")[0];
          }
          selfSpellsEl.appendChild(cell);
        });
      } else {
        // D / F placeholders - matches League's default hotkey convention
        // for summoner spells so the reader's mental model is consistent.
        ["D", "F"].forEach(letter => {
          const cell = document.createElement("span");
          cell.className = "self-spell placeholder";
          cell.textContent = letter;
          cell.title = `summoner ${letter} - no data`;
          selfSpellsEl.appendChild(cell);
        });
      }
    }
    // Dynamic page title - mode + champion, falls back to mode-only.
    const modeTag = (state.mode || "").toUpperCase();
    const gt = p.game_time || "";
    const parts = ["RC"];
    if (p.champion) parts.push(p.champion);
    if (modeTag) parts.push(modeTag);
    if (gt) parts.push(gt);
    document.title = parts.join(" · ");
  }

  // Round 45: champion-pill fallback. When live-client isn't populating
  // p.champion, the Phase 3 supervisor's /api/locked-champion endpoint
  // probes LCU → match_db → recent user-notes. Poll every 15s.
  const champPill = el("champion-pill");
  let championPillState = { name: null, source: null };

  // CHAMPS, SPELLS, _resolveChampId, _resolveSpell imported from lib/items_index.js.

  function setChampionPill(name, source) {
    if (!champPill) return;
    if (!name) {
      champPill.textContent = "-";
      champPill.className = "champion-pill stale";
      championPillState = { name: null, source: null };
      return;
    }
    // Don't downgrade a live read to a fallback.
    if (championPillState.source === "live" && source !== "live"
        && championPillState.name === name) return;
    const cid = _resolveChampId(name);
    champPill.innerHTML = "";
    if (cid) {
      const img = document.createElement("img");
      img.className = "champ-portrait";
      img.src = `/data/ddragon/${CHAMPS.version}/img/champion/${cid}.png`;
      img.alt = name;
      img.onerror = () => { img.remove(); };
      champPill.appendChild(img);
    }
    const label = document.createElement("span");
    label.className = "champ-name";
    // Display-name sanitiser: strip apostrophes (K'Sante → KSante, Kai'Sa
    // → KaiSa) and keep only the first token of " & " compounds
    // (Nunu & Willump → Nunu). Internal `name` is unchanged; only the
    // rendered label shortens so the pill width can be sized for a more
    // reasonable max like "Renata Glasc" / "Twisted Fate" (12 chars).
    label.textContent = String(name)
      .split(/\s*&\s*/)[0]
      .replace(/[''`]/g, "")
      .trim();
    champPill.appendChild(label);
    champPill.className = "champion-pill" + (source === "live" ? "" : " fallback");
    champPill.title = `champion · via ${source}`;
    championPillState = { name, source };
  }
  async function refreshChampionFallback() {
    // Only fetch if we don't already have a live-driven champion name,
    // OR the current pill is empty.
    if (championPillState.source === "live" && championPillState.name) return;
    try {
      const resp = await fetch("/api/locked-champion");
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.champion) {
        setChampionPill(data.champion, data.source || "fallback");
      }
    } catch { /* silent - we'll retry */ }
  }
  setInterval(refreshChampionFallback, 15000);
  refreshChampionFallback();     // kick one immediately

  // ── State dispatcher ────────────────────────────────────────────────
  function onState(env) {
    const p = env.payload || {};
    state.latest[env.mode] = p;

    // Record the /api/state mode_key + when we saw it. mode_key is the
    // canonical preflip/in-game resolver (build_state.resolve_mode_key +
    // cs_retention); onHealth defers to it so a raw-health "client" can't
    // flap body[data-mode] during ARAM/Arena-lobby preflip.
    state.lastStateMode = env.mode || "";
    state.lastStateModeTs = Date.now();

    // 2026-04-26: faster mode-switch - onState envelopes carry the source
    // mode in env.mode (mode_key from /api/state). Previously mode flipped
    // ONLY on the next health envelope (~5s gap from MetricsCache cadence).
    // Treating env.mode as authoritative for in-game tags shaves 3-5s off
    // every game-start and game-end transition. Health envelope still
    // wins for "client" since some early-state envelopes can carry stale
    // file modes during transitions.
    if (env.mode && env.mode !== state.mode &&
        ["aram","arena","brawl","sr","tft"].includes(env.mode)) {
      setMode(env.mode);
    }

    // Decide which mode's coaching data drives the panels.
    // Priority: tft > aram > arena > brawl > sr > client
    const mode = state.mode;
    const fileMode = env.mode;
    const driveNow = (
      (mode === "game" && (fileMode === "aram" || fileMode === "arena" ||
                            fileMode === "brawl" || fileMode === "sr" ||
                            fileMode === "tft")) ||
      fileMode === mode
    );
    if (!driveNow && !(fileMode === "sr" && state.latest.sr)) {
      // Still log it.
      logLine(env.source, safe(p.action) || "(state update)");
      return;
    }

    renderHeader(p);
    renderRightNow(p);
    renderCoachChoices(state.latest || p);
    renderNext(p);
    renderItemBuild(p);
    renderAugmentReco(p);
    renderMinimap(p);
    // s159: feed the Active Match scaffold on every state envelope so
    // the pane stays current when the view is active. Cheap pass - the
    // module's render is null-safe when DOM nodes are missing. lcuPhase
    // is left out of ctx for step 1; the state envelope carries the
    // per-mode coach payload only, not the full /api/state lcu block.
    // Item 188 (2026-05-25): UI scale v2.1 pages #11/12/13 audit ritual
    // mock fixture short-circuit. When body.dataset.uiMock === "1" AND
    // ?mode=<sr|aram|arena> is present, render the local Active Match
    // fixture instead of the live state envelope so the per-mode audit
    // captures stand on authored coach + liveclient + cooldowns data
    // even when the operator is between games.
    if (_amIsMock() && _amMockUrl()) {
      if (_amMockData) {
        renderActiveMatch(_amMockData.coach || {}, {
          mode: _amMockData.mode || "sr",
          lcuPhase: _amMockData.phase || "InProgress",
          liveclient: _amMockData.liveclient || null,
          cooldowns: _amMockData.summoner_cooldowns || null,
        });
      } else {
        _amMockLoad();  // .then re-fires render on landing
        renderActiveMatch({}, { mode: "", lcuPhase: "", liveclient: null, cooldowns: null });
      }
    } else {
      renderActiveMatch(p, {
        mode: state.mode,
        lcuPhase: (state.latest && state.latest.lcu && state.latest.lcu.phase) || "",
        // UX-2 (2026-05-20): thread the raw liveclient block so the
        // active_match build pane can render per-enemy threat donuts
        // sourced from /api/damage-mix. Null-safe; renderActiveMatch
        // skips the THREATS strip when liveclient is missing/empty.
        liveclient: (state.latest && state.latest.liveclient) || null,
        // UX-3 (2026-05-20): thread the summoner_cooldowns array (or null)
        // so the active_match view's right-rail CD ledger picks it up.
        // Computed backend-side in dashboard/_state_cooldowns.py + sorted
        // by next-up ascending in core/summoner_cooldowns.compute_cooldowns.
        cooldowns: (state.latest && state.latest.summoner_cooldowns) || null,
      });
    }
    // s164: re-fire champ-select view on every state envelope when it's
    // active. lcu envelopes are one-shot from FakeSocket, so a render
    // that bailed on !CHAMPS.ready (champion-name index loads async)
    // would never re-run otherwise. State ticks every 2s - fine.
    if (_VIEW.current === "champ-select") renderChampSelectView(_csResolveLcu());
    renderStats(p);
    renderGameSense(p);
    renderWhatWent(p);
    renderDigest(p);
    maybeRefreshAdaptation(p);
  }

  function onHealth(env) {
    const p = env.payload || {};
    // Prefer a specific mode tag (aram_mode, tft_mode etc.) when present.
    let tag = "client";
    if (p.aram_mode)     tag = "aram";
    else if (p.arena_mode) tag = "arena";
    else if (p.brawl_mode) tag = "brawl";
    else if (p.tft_mode)   tag = "tft";
    else if (p.has_game)   tag = "sr";
    else                   tag = (p.mode || "client").toLowerCase();
    // The health envelope's mode flags are NOT a reliable mode authority:
    // the WS /push health mirror (file_ingest) can fail/lag in the :8891
    // supervisor and /api/health is never preflip-mirrored, so during
    // ARAM/Arena-lobby + champ-select preflip onHealth computes "client"
    // while onState correctly carries the preflip mode_key. Both write
    // body[data-mode] on independent cadences → it flaps aram↔client and
    // every mode-gated header pill (ds/augments/trigger/nudge), the mode
    // pill, and the panel titles flicker on/off every cycle, on all
    // views (shared header). /api/state.mode_key is the canonical
    // resolver - defer the "client" downgrade to it whenever onState
    // recently asserted a preflip/in-game mode. The staleness window
    // still lets a genuine return-to-client through once /api/state
    // stops asserting a game (its mode_key resolves to "client" too).
    if (tag === "client"
        && ["aram", "arena", "brawl", "sr", "tft"].includes(state.lastStateMode)
        && (Date.now() - (state.lastStateModeTs || 0)) < 8000) {
      logLine("health",
        `pid=${p.pid} alive=${p.alive} mode=client(deferred→${state.lastStateMode}) reload_ok=${p.last_reload_ok}`);
      return;
    }
    setMode(tag);
    logLine("health", `pid=${p.pid} alive=${p.alive} mode=${tag} reload_ok=${p.last_reload_ok}`);
  }

  // Respawn-timer tick: when state.deadUntil is in the future, update the
  // HP badge once per second so the number actually counts down between
  // state-envelope re-emits.
  setInterval(() => {
    if (!state.deadUntil) return;
    const left = Math.max(0, Math.ceil((state.deadUntil - Date.now()) / 1000));
    hpEl.textContent = left > 0 ? String(left) : "UP";
    if (left === 0) state.deadUntil = 0;
  }, 500);

  // ── Staleness sweep ─────────────────────────────────────────────────
  function applyStaleness() {
    const now = Date.now() / 1000;
    for (const [panelKey, elm, rootElm] of [
      ["right_now",  RN.staleness, RN.root],
      ["next",       NX.staleness, NX.root],
      ["item_build", IB.staleness, IB.root],
      ["minimap",    MM.staleness, MM.root],
    ]) {
      const touched = state.lastTouch[panelKey];
      if (!touched) {
        elm.textContent = "-";
        elm.className = "staleness";
        rootElm.classList.remove("stale", "severe");
        continue;
      }
      const age = Math.round(now - touched);
      const c = CADENCE[panelKey];
      let klass = "fresh";
      rootElm.classList.remove("stale", "severe");
      if (age >= c.severe) { klass = "severe"; rootElm.classList.add("severe"); }
      else if (age >= c.stale) { klass = "stale"; rootElm.classList.add("stale"); }
      elm.textContent = age + "s";
      elm.className = "staleness " + klass;
    }
  }
  setInterval(applyStaleness, 500);

  // ── Adaptation panel (fetches /api/adaptation on state change) ──────
  const ADAPT = {
    lastKey: "",             // dedupe requests when the same (champ, mode) repeats
    inflight: false,
    fetchedAt: 0,
  };
  const TRENDS = {
    lastMode: "",
    inflight: false,
    fetchedAt: 0,
  };

  function renderTrendEntry(e) {
    const sign = e.delta >= 0 ? "+" : "";
    return `${e.champion} ${sign}${e.delta.toFixed(2)}`;
  }

  function renderStreaks(data) {
    if (!AD.streaksHot || !AD.streaksCold) return;
    if (!data || (!data.hot?.length && !data.cold?.length)) {
      AD.streaksHot.innerHTML = '<span class="dim">(no recent-window sample yet)</span>';
      AD.streaksCold.textContent = "";
      return;
    }
    AD.streaksHot.textContent = (data.hot || []).map(renderTrendEntry).join("  ·  ")
      || '(none)';
    AD.streaksCold.textContent = (data.cold || []).map(renderTrendEntry).join("  ·  ")
      || '(none)';
  }

  async function fetchTrending(modeTag) {
    const modeMap = {
      sr: "sr_ranked", aram: "aram", arena: "arena",
      brawl: "brawl", tft: "aram", client: "aram",
    };
    const mode = modeMap[modeTag] || "aram";
    // Only refetch when mode changes or more than 30s old.
    if (mode === TRENDS.lastMode && Date.now() - TRENDS.fetchedAt < 30000) return;
    if (TRENDS.inflight) return;
    TRENDS.inflight = true;
    try {
      const resp = await fetch(`/api/trending?mode=${mode}&n=3`);
      if (!resp.ok) return;
      const data = await resp.json();
      TRENDS.lastMode = mode;
      TRENDS.fetchedAt = Date.now();
      renderStreaks(data);
    } catch (e) {
      /* network err - leave prior render in place */
    } finally {
      TRENDS.inflight = false;
    }
  }

  function formatCounterLine(c) {
    const sign = c.delta >= 0 ? "+" : "";
    const pct = (c.delta * 100).toFixed(0);
    let line = `vs ${c.opponent}  ${sign}${pct}%  (n=${c.sample}, observed ${(c.observed_wr*100).toFixed(0)}%)`;
    if (c.kda_ratio != null && c.kda_delta != null && Math.abs(c.kda_delta) >= 0.3) {
      const ksign = c.kda_delta >= 0 ? "+" : "";
      line += `  ·  KDA ${c.kda_ratio.toFixed(2)} (${ksign}${c.kda_delta.toFixed(2)})`;
    }
    return line;
  }

  function renderAdaptation(data) {
    const trendEl = document.getElementById("trend-pill");
    const adaptPanel = document.querySelector(".panel-adaptation");
    if (!data || !data.present) {
      AD.status.textContent = "no data";
      AD.status.className = "counter";
      AD.champ.textContent = data && data.champion ? data.champion : "-";
      AD.baseline.textContent = "-";
      AD.recent.textContent = "-";
      if (AD.kda) AD.kda.textContent = "-";
      AD.counters.textContent = "-";
      if (trendEl) trendEl.classList.add("hidden");
      if (adaptPanel) adaptPanel.classList.add("adapt-empty");
      return;
    }
    if (adaptPanel) adaptPanel.classList.remove("adapt-empty");
    AD.status.textContent = `${data.games_played} games`;
    AD.champ.textContent = `${data.champion}  (${data.mode})`;
    AD.baseline.textContent = `${(data.win_rate * 100).toFixed(1)}%  ${data.wins}W-${data.losses}L`;
    // Trend arrow: recent vs baseline WR - glance read for hot/cold streak.
    let arrow = "", cls = "";
    if (data.recent_win_rate != null && data.win_rate != null) {
      const delta = data.recent_win_rate - data.win_rate;
      if (delta >=  0.08) { arrow = " ↑"; cls = "trend-up"; }
      else if (delta <= -0.08) { arrow = " ↓"; cls = "trend-down"; }
      else { arrow = " ~"; cls = "trend-flat"; }
    }
    const recentPart = data.recent_win_rate != null
      ? `${(data.recent_win_rate * 100).toFixed(0)}% over last ${data.recent_sample_size}`
      : "-";
    AD.recent.textContent = recentPart + arrow;
    AD.recent.className = cls;

    // Typical KDA - shown once we have ≥5 samples; otherwise placeholder.
    if (AD.kda) {
      const kda = data.avg_kda;
      if (kda && (kda.sample || 0) >= 5) {
        let line =
          `${kda.ratio.toFixed(2)}  (${kda.k.toFixed(1)}/${kda.d.toFixed(1)}/${kda.a.toFixed(1)}, n=${kda.sample})`;
        const rkda = data.recent_kda;
        if (rkda && (rkda.sample || 0) >= 5) {
          const dr = rkda.delta_ratio || 0;
          const arrow = dr > 0.3 ? "↑" : (dr < -0.3 ? "↓" : "·");
          const sign = dr >= 0 ? "+" : "";
          line += `  ·  recent ${rkda.ratio.toFixed(2)} ${arrow} (${sign}${dr.toFixed(2)})`;
        }
        AD.kda.textContent = line;
      } else {
        AD.kda.textContent = "-";
      }
    }

    // Trend pill in the header - prefers 30d window, falls back to rolling.
    if (trendEl) {
      trendEl.classList.remove("hidden", "up", "down", "neutral");
      const r30 = data.recency_30d;
      if (r30 && (r30.games || 0) >= 5) {
        const dv = r30.delta_vs_alltime || 0;
        const arrow = dv > 0.05 ? "↑" : (dv < -0.05 ? "↓" : "·");
        const klass = dv > 0.05 ? "up" : (dv < -0.05 ? "down" : "neutral");
        trendEl.classList.add(klass);
        trendEl.textContent = `30d ${(r30.win_rate * 100).toFixed(0)}% ${arrow}`;
        trendEl.title = `30d wr ${(r30.win_rate*100).toFixed(1)}% vs ` +
                        `all-time ${(data.win_rate*100).toFixed(1)}% (n=${r30.games})`;
      } else if (data.recent_win_rate != null && data.recent_sample_size >= 5) {
        const dv = data.recent_win_rate - data.win_rate;
        const arrow = dv > 0.05 ? "↑" : (dv < -0.05 ? "↓" : "·");
        const klass = dv > 0.05 ? "up" : (dv < -0.05 ? "down" : "neutral");
        trendEl.classList.add(klass);
        trendEl.textContent = `last${data.recent_sample_size} ${(data.recent_win_rate*100).toFixed(0)}% ${arrow}`;
        trendEl.title = `rolling last-${data.recent_sample_size} wr ` +
                        `${(data.recent_win_rate*100).toFixed(1)}% vs ` +
                        `all-time ${(data.win_rate*100).toFixed(1)}%`;
      } else {
        trendEl.classList.add("hidden");
      }
    }

    // --- Counters section ---
    AD.counters.innerHTML = "";
    const counters = (data.counters || []).slice(0, 5);
    if (!counters.length) {
      AD.counters.textContent = "(no activated matchups vs current enemies)";
    } else {
      for (const c of counters) {
        const div = document.createElement("div");
        div.className = "counter-line " + (c.delta >= 0 ? "positive" : "negative");
        div.textContent = formatCounterLine(c);
        AD.counters.appendChild(div);
      }
    }

    // --- Historic items section ---
    if (AD.items) {
      AD.items.innerHTML = "";
      const items = (data.top_items || []).slice(0, 5);
      if (!items.length) {
        AD.items.textContent = "(no significant item-outcome signals)";
      } else {
        for (const it of items) {
          const div = document.createElement("div");
          div.className = "counter-line " + (it.delta >= 0 ? "positive" : "negative");
          const sign = it.delta >= 0 ? "+" : "";
          const pct = (it.delta * 100).toFixed(0);
          const observed = (it.observed_wr * 100).toFixed(0);
          const name = it.name || ("item " + it.item_id);
          div.textContent = `${name}  ${sign}${pct}%  (n=${it.matches}, observed ${observed}%)`;
          AD.items.appendChild(div);
        }
      }
    }
  }

  async function fetchAdaptation(champion, modeTag, enemies) {
    // Trending is mode-dependent only - fire regardless of champion.
    fetchTrending(modeTag);
    if (!champion || champion === "Unknown") {
      renderAdaptation({ present: false });
      return;
    }
    // Map the dashboard's mode tag to the analyzer's mode.
    const modeMap = {
      sr: "sr_ranked", aram: "aram", arena: "arena",
      brawl: "brawl", tft: "aram",       // tft has no adaptation DB; fall back
      client: "aram",
    };
    const mode = modeMap[modeTag] || "aram";
    const enemyParam = enemies && enemies.length
      ? `&enemies=${encodeURIComponent(enemies.join(","))}`
      : "";
    const key = `${champion}|${mode}|${enemies ? enemies.join(",") : ""}`;

    // Skip if same key within the last 8s - no need to hammer the endpoint.
    if (key === ADAPT.lastKey && (Date.now() - ADAPT.fetchedAt) < 8000) return;
    if (ADAPT.inflight) return;
    ADAPT.inflight = true;
    AD.status.textContent = "fetching...";
    try {
      const resp = await fetch(
        `/api/adaptation?champion=${encodeURIComponent(champion)}&mode=${mode}${enemyParam}`
      );
      if (!resp.ok) {
        AD.status.textContent = `http ${resp.status}`;
        return;
      }
      const data = await resp.json();
      ADAPT.lastKey = key;
      ADAPT.fetchedAt = Date.now();
      renderAdaptation(data);
    } catch (e) {
      AD.status.textContent = "fetch err";
    } finally {
      ADAPT.inflight = false;
    }
  }

  function maybeRefreshAdaptation(payload) {
    // Different coaching-JSON shapes use different keys; try a few.
    const champ = payload.champion || payload.champ || payload.my_champion
               || payload.my_champ || "";
    const enemiesRaw = payload.enemy_comp || payload.enemies
                    || payload.enemy_team || payload.enemy_champions || [];
    const enemies = Array.isArray(enemiesRaw) ? enemiesRaw.filter(Boolean) : [];
    fetchAdaptation(champ, state.mode, enemies);
  }


  // ── Session view fetchers (2026-04-26) ───────────────────────────
  // UI scale v2.1 page #5 audit ritual step 5 state-coverage mock fixture
  // (2026-05-23). When body.dataset.uiMock === "1" the fetch short-
  // circuits to /data/ui_mock/session.json instead of /api/session/summary.
  let _sessionMockPromise = null;
  function _sessionMockLoad() {
    if (_sessionMockPromise) return _sessionMockPromise;
    _sessionMockPromise = fetch("/data/ui_mock/session.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .catch(() => null);
    return _sessionMockPromise;
  }
  function _sessionIsMock() {
    return document.body && document.body.dataset.uiMock === "1";
  }
  function _sessionFetchAndRender() {
    const promise = _sessionIsMock()
      ? _sessionMockLoad()
      : fetch("/api/session/summary", { cache: "no-store" })
          .then((r) => (r && r.ok ? r.json() : null));
    promise
      .then((d) => {
        if (!d) return;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set("session-window", d.window_label || "-");
        set("session-games", d.games || "0");
        const sec = (d.time_played_s | 0);
        const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60);
        set("session-time", hh > 0 ? `${hh}h ${mm}m` : `${mm}m`);
        set("session-start", d.started_at || "-");
        set("session-last", d.last_at || "-");
        set("session-kda", d.total_kda || "-");
        set("session-avg", d.avg_kda != null ? d.avg_kda.toFixed(2) : "-");
        set("session-grades",
          d.grades ? Object.entries(d.grades).map(([g,n]) => `${g}×${n}`).join(" ") : "-");
        set("session-modes",
          d.modes ? Object.entries(d.modes).map(([m,n]) => `${m} ${n}`).join(" · ") : "-");
        const champUl = document.getElementById("session-champs");
        if (champUl) {
          champUl.innerHTML = "";
          (d.champions || []).forEach((c) => {
            const li = document.createElement("li");
            li.className = "history-match-row";
            li.innerHTML = `<span style="flex:1">${c.champion}</span>` +
              `<span class="dim">${c.games}g</span>` +
              `<span style="margin-left:10px">${c.kda || "-"}</span>`;
            champUl.appendChild(li);
          });
          if (!champUl.children.length) champUl.innerHTML = '<li class="home-empty">no champs in session</li>';
        }
        const matchUl = document.getElementById("session-matches");
        if (matchUl) {
          matchUl.innerHTML = "";
          (d.matches || []).forEach((m) => {
            const li = document.createElement("li");
            li.className = "history-match-row";
            const grade = String(m.grade || "-")[0];
            li.innerHTML = `<span class="home-recent-grade ${grade}">${grade}</span>` +
              `<span style="flex:1; margin-left:8px">${m.champion} · ${m.mode}</span>` +
              `<span class="dim">${m.kda}</span>` +
              `<span class="dim" style="margin-left:8px">${m.timestamp}</span>`;
            matchUl.appendChild(li);
          });
          if (!matchUl.children.length) matchUl.innerHTML = '<li class="home-empty">no matches in session</li>';
        }
      })
      .catch(() => {});
  }

  // ── History view fetchers (2026-04-26) ───────────────────────────
  // UI scale v2.1 page #4 audit ritual step 5 state-coverage mock fixture
  // (2026-05-23). When body.dataset.uiMock === "1" the fetch short-
  // circuits to /data/ui_mock/history.json instead of /api/history.
  // Scope tabs still drive the fetch but the mock fixture filters
  // sessions[] by scope on the client side so the UX is identical.
  const _HISTORY = { scope: "14d", selectedSession: null };
  let _historyMockPromise = null;
  function _historyMockLoad() {
    if (_historyMockPromise) return _historyMockPromise;
    _historyMockPromise = fetch("/data/ui_mock/history.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .catch(() => null);
    return _historyMockPromise;
  }
  function _historyIsMock() {
    return document.body && document.body.dataset.uiMock === "1";
  }
  function _historyMockSliceForScope(payload, scope) {
    if (!payload || !payload.scopes) return null;
    const slice = payload.scopes[scope] || payload.scopes["14d"] || null;
    return slice;
  }
  function _historyFetchAndRender() {
    const promise = _historyIsMock()
      ? _historyMockLoad().then((p) => _historyMockSliceForScope(p, _HISTORY.scope))
      : fetch("/api/history?scope=" + encodeURIComponent(_HISTORY.scope), { cache: "no-store" })
          .then((r) => (r && r.ok ? r.json() : null));
    promise
      .then((d) => {
        if (!d) return;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set("history-session-count", (d.sessions || []).length + " session" + ((d.sessions||[]).length===1?"":"s"));
        const ul = document.getElementById("history-session-list");
        if (ul) {
          ul.innerHTML = "";
          (d.sessions || []).forEach((s, idx) => {
            const li = document.createElement("li");
            li.className = "history-session-row";
            li.dataset.sessionIdx = idx;
            li.innerHTML = `<span style="flex:1">${s.date}</span>` +
              `<span class="dim">${s.games}g</span>` +
              `<span class="dim" style="margin-left:8px">${s.duration_label || ""}</span>`;
            li.addEventListener("click", () => {
              _HISTORY.selectedSession = idx;
              ul.querySelectorAll(".history-session-row").forEach((r) => r.classList.remove("active"));
              li.classList.add("active");
              _historyRenderMatches(s);
              const head = document.getElementById("history-detail-head");
              if (head) head.textContent = `MATCHES · ${s.date} · ${s.games}g`;
            });
            ul.appendChild(li);
          });
          if (!ul.children.length) ul.innerHTML = '<li class="home-empty">no sessions in scope</li>';
        }
        // Season stats panel
        const ss = d.season_stats || {};
        set("history-season-total", ss.total != null ? ss.total : "-");
        set("history-season-kda",   ss.avg_kda != null ? ss.avg_kda.toFixed(2) : "-");
        set("history-season-fav",   ss.favorite || "-");

        // s218 v7: deep-link focus by champion (clicked from Tonight's
        // Pick on Home). Find the most recent session containing the
        // champion, auto-select it, highlight all matching match rows.
        let focusChamp = null;
        try { focusChamp = sessionStorage.getItem("rc-history-focus-champion"); } catch (_) {}
        if (focusChamp && ul) {
          try { sessionStorage.removeItem("rc-history-focus-champion"); } catch (_) {}
          const sessions = d.sessions || [];
          const champLower = String(focusChamp).toLowerCase();
          let targetIdx = sessions.findIndex(s =>
            (s.matches || []).some(m => String(m.champion || "").toLowerCase() === champLower)
          );
          if (targetIdx < 0 && sessions.length > 0) targetIdx = 0;
          if (targetIdx >= 0) {
            const session = sessions[targetIdx];
            _HISTORY.selectedSession = targetIdx;
            ul.querySelectorAll(".history-session-row").forEach((r) => r.classList.remove("active"));
            const sessionRow = ul.querySelector(`[data-session-idx="${targetIdx}"]`);
            if (sessionRow) sessionRow.classList.add("active");
            _historyRenderMatches(session);
            const head = document.getElementById("history-detail-head");
            if (head) head.textContent = `MATCHES · ${session.date} · ${session.games}g · ${focusChamp}`;
            requestAnimationFrame(() => {
              const matchUl = document.getElementById("history-match-list");
              if (!matchUl) return;
              const rows = matchUl.querySelectorAll(".history-match-row");
              let firstMatch = null;
              rows.forEach(row => {
                const champText = row.querySelector("span:nth-child(2)");
                const t = champText ? champText.textContent : "";
                if (t.toLowerCase().includes(champLower)) {
                  row.classList.add("is-focused");
                  if (!firstMatch) firstMatch = row;
                  setTimeout(() => row.classList.remove("is-focused"), 3500);
                }
              });
              if (firstMatch) firstMatch.scrollIntoView({ behavior: "smooth", block: "center" });
            });
          }
        }
        // s218 v6: deep-link focus from Recent 5 click on Home. The
        // pending timestamp is "YYYY-MM-DD HH:MM:SS". Find the session
        // whose date prefix matches, auto-select it, then scroll +
        // highlight the matching match row briefly.
        let focusTs = null;
        try { focusTs = sessionStorage.getItem("rc-history-focus-ts"); } catch (_) {}
        if (focusTs && ul) {
          try { sessionStorage.removeItem("rc-history-focus-ts"); } catch (_) {}
          const dateStr = String(focusTs).split(" ")[0];
          const sessions = d.sessions || [];
          let targetIdx = sessions.findIndex(s => s.date === dateStr);
          if (targetIdx < 0 && sessions.length > 0) targetIdx = 0; // fallback: latest
          if (targetIdx >= 0) {
            const session = sessions[targetIdx];
            _HISTORY.selectedSession = targetIdx;
            ul.querySelectorAll(".history-session-row").forEach((r) => r.classList.remove("active"));
            const sessionRow = ul.querySelector(`[data-session-idx="${targetIdx}"]`);
            if (sessionRow) sessionRow.classList.add("active");
            _historyRenderMatches(session);
            const head = document.getElementById("history-detail-head");
            if (head) head.textContent = `MATCHES · ${session.date} · ${session.games}g`;
            requestAnimationFrame(() => {
              const matchUl = document.getElementById("history-match-list");
              if (!matchUl) return;
              const matchRow = matchUl.querySelector(`[data-match-ts="${CSS.escape(focusTs)}"]`);
              if (matchRow) {
                matchRow.classList.add("is-focused");
                matchRow.scrollIntoView({ behavior: "smooth", block: "center" });
                setTimeout(() => matchRow.classList.remove("is-focused"), 3500);
              }
            });
          }
        }
      })
      .catch(() => {});
  }
  function _historyRenderMatches(session) {
    const ul = document.getElementById("history-match-list");
    if (!ul) return;
    ul.innerHTML = "";
    (session.matches || []).forEach((m) => {
      const li = document.createElement("li");
      li.className = "history-match-row";
      // s218 v6: stamp timestamp on the row so the Recent-5 deep-link
      // (sessionStorage "rc-history-focus-ts") can scroll + highlight
      // the matching row after the session is selected.
      if (m.timestamp) li.dataset.matchTs = m.timestamp;
      const grade = String(m.grade || "-")[0];
      li.innerHTML = `<span class="home-recent-grade ${grade}">${grade}</span>` +
        `<span style="flex:1; margin-left:8px">${m.champion} · ${m.mode}</span>` +
        `<span class="dim">${m.kda}</span>` +
        `<span class="dim" style="margin-left:8px">${m.timestamp}</span>`;
      ul.appendChild(li);
    });
    if (!ul.children.length) ul.innerHTML = '<li class="home-empty">no matches in session</li>';
  }
  function _historyWireOnce() {
    if (_HISTORY._wired) return;
    _HISTORY._wired = true;
    document.querySelectorAll("#history-scope-tabs .view-tab").forEach((b) => {
      b.addEventListener("click", () => {
        document.querySelectorAll("#history-scope-tabs .view-tab")
          .forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        _HISTORY.scope = b.dataset.scope;
        _historyFetchAndRender();
      });
    });
  }

  // ── Loadouts view (2026-04-26) ───────────────────────────────────
  function _loadoutsFetchAndRender() {
    const mode = (document.getElementById("loadouts-mode-filter") || {}).value || "aram";
    const filter = ((document.getElementById("loadouts-filter") || {}).value || "").toLowerCase();
    fetch("/api/loadouts/all?mode=" + encodeURIComponent(mode), { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        const list = document.getElementById("loadouts-list");
        const cnt = document.getElementById("loadouts-count");
        if (!list) return;
        list.innerHTML = "";
        const champs = (d.champions || []).filter((c) =>
          !filter || c.champion.toLowerCase().includes(filter));
        if (cnt) cnt.textContent = `${champs.length} of ${(d.champions||[]).length} champions`;
        champs.forEach((c) => {
          const card = document.createElement("div");
          card.className = "loadout-champ";
          const variants = (c.variants || [])
            .filter((v) => v.key !== "experimental")
            .map((v) => `<span style="color:var(--text-dim); font-size:11px; margin-right:14px">${v.label} <span style="color:var(--text-faint)">(${v.keystone||"?"})</span></span>`)
            .join("");
          card.innerHTML = `<div class="loadout-champ-name">${c.champion}</div><div>${variants}</div>`;
          list.appendChild(card);
        });
        if (!champs.length) list.innerHTML = '<div class="home-empty">no champions match filter</div>';
      })
      .catch(() => {});
  }
  function _loadoutsWireOnce() {
    if (window.__loadoutsWired) return;
    window.__loadoutsWired = true;
    const f = document.getElementById("loadouts-filter");
    const m = document.getElementById("loadouts-mode-filter");
    if (f) f.addEventListener("input", _loadoutsFetchAndRender);
    if (m) m.addEventListener("change", _loadoutsFetchAndRender);
  }

  // ── User Builds view (Phase 8 step 6 - 2026-05-04) ───────────────
  // CRUD over data/daemon_slayer/user_builds.json via
  // /api/sr-draft/user-builds (action-keyed POST: list/add/update/delete).
  // Builds saved here APPEND to the engine-generated SR-draft profiles
  // in the champ-select chooser; engine never reads or writes them.
  const _UB = {
    champion:  null,    // current picker value
    builds:    [],      // builds for the current champion (raw shape)
    editingId: null,    // build.id when editing, null when adding
    saving:    false,
  };
  // Summoner-spell chooser state (rendered inside the form pane).
  // Canonical 11-spell catalog covers Cleanse / Exhaust / Flash / Ghost
  // / Heal / Smite / Teleport / Clarity / Ignite / Barrier / Snowball.
  // _ubFormatSpells uses the same mapping; keep ids in sync if extended.
  const _UB_SPELLS = [
    { id: 4,  name: "Flash",    img: "SummonerFlash.png"   },
    { id: 14, name: "Ignite",   img: "SummonerDot.png"     },
    { id: 7,  name: "Heal",     img: "SummonerHeal.png"    },
    { id: 6,  name: "Ghost",    img: "SummonerHaste.png"   },
    { id: 21, name: "Barrier",  img: "SummonerBarrier.png" },
    { id: 3,  name: "Exhaust",  img: "SummonerExhaust.png" },
    { id: 1,  name: "Cleanse",  img: "SummonerBoost.png"   },
    { id: 12, name: "Teleport", img: "SummonerTeleport.png"},
    { id: 11, name: "Smite",    img: "SummonerSmite.png"   },
    { id: 13, name: "Clarity",  img: "SummonerMana.png"    },
    { id: 32, name: "Snowball", img: "SummonerSnowball.png"},
  ];
  // Rune-page + spell-chooser shared state. _RP_TREES cached lazily from
  // /api/dictionary/runes on first form-open. Patch path fixed at the
  // DDragon mirror's current dir (routes_dictionary serves runes for
  // 16.11.1; the static folder mirrors the same patch in lockstep).
  const _RP_DDRAGON_BASE = "/data/ddragon/16.11.1/img/";
  let   _RP_TREES = null;
  const _RP = {
    primaryTree:    null,  // tree.key e.g. "Domination"
    secondaryTree:  null,
    keystone:       null,  // rune.name (display, also stored as keystone)
    primaryMinors:  [],    // rune.name list (intended 1 per row, not enforced)
    secondaryMinors: [],   // rune.name list (intended 2 max)
  };
  const _SP = { active: "d" };  // which slot the spell-grid click writes to
  function _ubEl(id) { return document.getElementById(id); }
  function _ubChampionsList() {
    // Cache a flat list of {name} for the datalist; populated lazily
    // from /api/champions on first wire.
    if (window.__ubChampionsCache) return Promise.resolve(window.__ubChampionsCache);
    return fetch("/api/champions", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((d) => {
        const names = d ? Object.values(d).map((c) => c.name).filter(Boolean).sort() : [];
        window.__ubChampionsCache = names;
        return names;
      })
      .catch(() => []);
  }
  function _ubPopulateDatalist() {
    const dl = _ubEl("ub-champion-datalist");
    if (!dl) return;
    _ubChampionsList().then((names) => {
      dl.innerHTML = "";
      for (const n of names) {
        const opt = document.createElement("option");
        opt.value = n;
        dl.appendChild(opt);
      }
    });
  }
  function _ubFormatSpells(pair) {
    if (!Array.isArray(pair) || pair.length !== 2) return "-";
    const NAMES = {
      1: "Cleanse", 3: "Exhaust", 4: "Flash", 6: "Ghost", 7: "Heal",
      11: "Smite", 12: "Teleport", 13: "Clarity", 14: "Ignite",
      21: "Barrier", 32: "Snowball",
    };
    const a = NAMES[pair[0]] || pair[0];
    const b = NAMES[pair[1]] || pair[1];
    return `${a}/${b}`;
  }
  function _ubFormatSubLine(b) {
    const parts = [];
    if (b.role)                  parts.push(b.role);
    if (b.runes && b.runes.keystone) parts.push(b.runes.keystone);
    parts.push(_ubFormatSpells(b.summoner_spells));
    parts.push(`${(b.items || []).length} item${(b.items || []).length === 1 ? "" : "s"}`);
    return parts.join(" · ");
  }
  function _userBuildsFetchAndRender() {
    const champ = _UB.champion;
    const list  = _ubEl("ub-build-list");
    const lbl   = _ubEl("ub-list-label");
    const cnt   = _ubEl("ub-count");
    const hint  = _ubEl("ub-hint");
    if (!list) return;
    const uiMockOn = (document.body && document.body.dataset.uiMock === "1");
    if (!champ && !uiMockOn) {
      list.innerHTML = '<li class="home-empty">pick a champion above ↑</li>';
      if (lbl) lbl.textContent = "No champion selected";
      if (cnt) cnt.textContent = "-";
      if (hint) hint.textContent = "Pick a champion to view their saved builds.";
      _UB.builds = [];
      return;
    }
    const renderChamp = champ || "Tristana";
    if (lbl) lbl.textContent = champ ? champ.toUpperCase() : "TRISTANA (MOCK)";
    if (hint) hint.textContent = champ
      ? `Builds here append to the engine's 3 SR-draft profiles for ${champ}.`
      : "Dev UI mock fixture - toggle off in Settings to see live data.";
    const liveFetch = champ
      ? fetch(`/api/sr-draft/user-builds?champion=${encodeURIComponent(champ)}`,
              { cache: "no-store" }).then((r) => (r && r.ok ? r.json() : null))
      : Promise.resolve(null);
    liveFetch
      .then(async (d) => {
        let builds = (d && Array.isArray(d.builds)) ? d.builds : [];
        let mockUsed = false;
        if (!builds.length && uiMockOn) {
          try {
            const mockResp = await fetch("/data/ui_mock/user_builds.json",
                                         { cache: "no-store" });
            const mockJson = mockResp && mockResp.ok ? await mockResp.json() : null;
            builds = (mockJson && Array.isArray(mockJson.builds)) ? mockJson.builds : [];
            mockUsed = builds.length > 0;
          } catch (_) {}
        }
        _UB.builds = builds;
        if (cnt) cnt.textContent = `${builds.length} build${builds.length === 1 ? "" : "s"}${mockUsed ? " (mock)" : ""}`;
        list.innerHTML = "";
        if (!builds.length) {
          list.innerHTML = '<li class="home-empty">no builds yet - click + Add build above.</li>';
          return;
        }
        for (const b of builds) {
          const li = document.createElement("li");
          li.className = "ub-build-row";
          if (_UB.editingId === b.id) li.classList.add("editing");

          const meta = document.createElement("div");
          meta.className = "ub-build-meta";
          const lab = document.createElement("span");
          lab.className = "ub-build-label";
          lab.textContent = b.label || "(unnamed)";
          const sub = document.createElement("span");
          sub.className = "ub-build-sub";
          sub.textContent = _ubFormatSubLine(b);
          meta.appendChild(lab);
          meta.appendChild(sub);

          const editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "ub-btn ub-btn-ghost ub-btn-tiny";
          editBtn.textContent = "Edit";
          editBtn.addEventListener("click", () => _userBuildsOpenForm(b));

          const delBtn = document.createElement("button");
          delBtn.type = "button";
          delBtn.className = "ub-btn ub-btn-danger ub-btn-tiny";
          delBtn.textContent = "Delete";
          delBtn.addEventListener("click", () => _userBuildsDelete(b));

          li.appendChild(meta);
          li.appendChild(editBtn);
          li.appendChild(delBtn);
          list.appendChild(li);
        }
      })
      .catch(() => {
        list.innerHTML = '<li class="home-empty">failed to load builds.</li>';
      });
  }
  // ── Summoner-spell chooser (icon grid) ─────────────────────────────
  function _spellById(id) {
    const n = parseInt(id, 10);
    return _UB_SPELLS.find((s) => s.id === n) || null;
  }
  function _spellIconUrl(img) {
    return img ? (_RP_DDRAGON_BASE + "spell/" + img) : "";
  }
  function _ubSpellRenderCurrent() {
    const dId = parseInt(_ubEl("ub-f-spell-d").value, 10);
    const fId = parseInt(_ubEl("ub-f-spell-f").value, 10);
    const dSp = _spellById(dId);
    const fSp = _spellById(fId);
    const dIcon = _ubEl("ub-sp-d-icon");
    const fIcon = _ubEl("ub-sp-f-icon");
    if (dIcon) { dIcon.src = _spellIconUrl(dSp && dSp.img); dIcon.alt = (dSp && dSp.name) || ""; }
    if (fIcon) { fIcon.src = _spellIconUrl(fSp && fSp.img); fIcon.alt = (fSp && fSp.name) || ""; }
    const dName = _ubEl("ub-sp-d-name");
    const fName = _ubEl("ub-sp-f-name");
    if (dName) dName.textContent = (dSp && dSp.name) || "-";
    if (fName) fName.textContent = (fSp && fSp.name) || "-";
    _ubEl("ub-sp-slot-d").classList.toggle("active", _SP.active === "d");
    _ubEl("ub-sp-slot-f").classList.toggle("active", _SP.active === "f");
  }
  function _ubSpellRenderGrid() {
    const g = _ubEl("ub-sp-grid");
    if (!g || g.dataset.wired === "1") return;
    g.dataset.wired = "1";
    g.innerHTML = "";
    for (const sp of _UB_SPELLS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ub-sp-cell";
      b.title = `${sp.name} (id ${sp.id})`;
      b.dataset.spellId = String(sp.id);
      const img = document.createElement("img");
      img.src = _spellIconUrl(sp.img);
      img.alt = sp.name;
      const cap = document.createElement("span");
      cap.className = "ub-sp-cell-name";
      cap.textContent = sp.name;
      b.appendChild(img);
      b.appendChild(cap);
      b.addEventListener("click", () => _ubSpellPick(sp.id));
      g.appendChild(b);
    }
  }
  function _ubSpellSlotActivate(slot) {
    _SP.active = (slot === "f") ? "f" : "d";
    _ubSpellRenderCurrent();
  }
  function _ubSpellPick(id) {
    const slot   = _SP.active === "f" ? "f" : "d";
    const otherSlot = slot === "d" ? "f" : "d";
    const slotInput  = _ubEl(`ub-f-spell-${slot}`);
    const otherInput = _ubEl(`ub-f-spell-${otherSlot}`);
    if (!slotInput) return;
    const prev = parseInt(slotInput.value, 10);
    const other = parseInt(otherInput && otherInput.value, 10);
    if (id === other && otherInput) {
      // Swap so the operator can hot-swap by picking the other spell.
      otherInput.value = prev;
    }
    slotInput.value = id;
    // Auto-flip the active slot so two picks in a row populate both.
    _SP.active = otherSlot;
    _ubSpellRenderCurrent();
  }

  // ── Rune Page builder (5-tree tabs + keystone + minor picker) ─────
  function _runeIconUrl(rel) {
    return rel ? (_RP_DDRAGON_BASE + rel) : "";
  }
  function _ubRpFetchTrees() {
    if (_RP_TREES) return Promise.resolve(_RP_TREES);
    return fetch("/api/dictionary/runes", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((d) => {
        _RP_TREES = Array.isArray(d) ? d : [];
        return _RP_TREES;
      })
      .catch(() => { _RP_TREES = []; return _RP_TREES; });
  }
  function _ubRpTreeByName(name) {
    if (!name || !_RP_TREES) return null;
    return _RP_TREES.find((t) => t.key === name || t.name === name) || null;
  }
  function _ubRpRenderTabs() {
    const tabs = _ubEl("ub-rp-tabs");
    if (!tabs) return;
    tabs.innerHTML = "";
    for (const t of (_RP_TREES || [])) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ub-rp-tab";
      b.dataset.tree = t.key;
      b.setAttribute("role", "tab");
      b.classList.toggle("active", _RP.primaryTree === t.key);
      const img = document.createElement("img");
      img.src = _runeIconUrl(t.icon);
      img.alt = t.name;
      const cap = document.createElement("span");
      cap.textContent = t.name;
      b.appendChild(img);
      b.appendChild(cap);
      b.addEventListener("click", () => _ubRpPickPrimary(t.key));
      tabs.appendChild(b);
    }
  }
  function _ubRpRenderSecTrees() {
    const row = _ubEl("ub-rp-sec-trees");
    if (!row) return;
    row.innerHTML = "";
    for (const t of (_RP_TREES || [])) {
      const isPrimary = (t.key === _RP.primaryTree);
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ub-rp-sec-tab";
      b.dataset.tree = t.key;
      b.disabled = isPrimary;
      b.classList.toggle("active", _RP.secondaryTree === t.key);
      b.classList.toggle("disabled", isPrimary);
      const img = document.createElement("img");
      img.src = _runeIconUrl(t.icon);
      img.alt = t.name;
      const cap = document.createElement("span");
      cap.textContent = t.name;
      b.appendChild(img);
      b.appendChild(cap);
      b.addEventListener("click", () => { if (!isPrimary) _ubRpPickSecondary(t.key); });
      row.appendChild(b);
    }
  }
  function _ubRpBuildRow(rune, kind, rowIdx) {
    const c = document.createElement("button");
    c.type = "button";
    c.className = `ub-rp-rune ub-rp-rune-${kind}`;
    c.dataset.rune = rune.name;
    c.dataset.row  = String(rowIdx);
    const isKeystone = (kind === "keystone");
    const sel = (
      isKeystone ? (_RP.keystone === rune.name) :
      kind === "primary" ? _RP.primaryMinors.includes(rune.name) :
      _RP.secondaryMinors.includes(rune.name)
    );
    c.classList.toggle("selected", sel);
    c.title = rune.name;
    const img = document.createElement("img");
    img.src = _runeIconUrl(rune.icon);
    img.alt = rune.name;
    const cap = document.createElement("span");
    cap.textContent = rune.name;
    c.appendChild(img);
    c.appendChild(cap);
    c.addEventListener("click", () => {
      if (isKeystone) _ubRpPickKeystone(rune.name);
      else if (kind === "primary") _ubRpToggleMinor("primary", rowIdx, rune.name);
      else _ubRpToggleMinor("secondary", rowIdx, rune.name);
    });
    return c;
  }
  function _ubRpRenderRows(treeName, containerId, kind) {
    const cont = _ubEl(containerId);
    if (!cont) return;
    cont.innerHTML = "";
    const tree = _ubRpTreeByName(treeName);
    if (!tree) {
      cont.innerHTML = '<div class="ub-rp-empty">pick a tree above</div>';
      return;
    }
    tree.slots.forEach((slot, i) => {
      // For the SECONDARY pane, skip the keystone slot (row 0); the
      // secondary tree only contributes minor runes per the game's rules.
      if (kind === "secondary" && i === 0) return;
      const rowEl = document.createElement("div");
      rowEl.className = "ub-rp-row";
      rowEl.dataset.rowIdx = String(i);
      for (const rune of slot.runes) {
        const cellKind = (kind === "primary" && i === 0) ? "keystone" : kind;
        rowEl.appendChild(_ubRpBuildRow(rune, cellKind, i));
      }
      cont.appendChild(rowEl);
    });
  }
  function _ubRpRenderSummary() {
    const s = _ubEl("ub-rp-summary");
    if (!s) return;
    const bits = [];
    if (_RP.keystone) bits.push(`Keystone: ${_RP.keystone}`);
    if (_RP.primaryTree) {
      const mins = _RP.primaryMinors.filter(Boolean);
      bits.push(`Primary: ${_RP.primaryTree}${mins.length ? " (" + mins.join(" + ") + ")" : ""}`);
    }
    if (_RP.secondaryTree) {
      const mins = _RP.secondaryMinors.filter(Boolean);
      bits.push(`Secondary: ${_RP.secondaryTree}${mins.length ? " (" + mins.join(" + ") + ")" : ""}`);
    }
    s.textContent = bits.length ? bits.join("  -  ") : "Pick a tree tab, then a keystone.";
  }
  function _ubRpSyncTextFields() {
    const k = _ubEl("ub-f-keystone");
    const p = _ubEl("ub-f-primary");
    const sc = _ubEl("ub-f-secondary");
    if (k)  k.value = _RP.keystone     || "";
    if (p)  p.value = _RP.primaryTree  || "";
    if (sc) sc.value = _RP.secondaryTree || "";
  }
  function _ubRpRenderAll() {
    _ubRpRenderTabs();
    _ubRpRenderRows(_RP.primaryTree,   "ub-rp-primary-rows",   "primary");
    _ubRpRenderSecTrees();
    _ubRpRenderRows(_RP.secondaryTree, "ub-rp-secondary-rows", "secondary");
    _ubRpRenderSummary();
    _ubRpSyncTextFields();
  }
  function _ubRpPickPrimary(treeName) {
    if (_RP.primaryTree === treeName) return;
    _RP.primaryTree = treeName;
    // Reset keystone + primary minors when the tree changes.
    _RP.keystone = null;
    _RP.primaryMinors = [];
    // If the new primary == current secondary, clear secondary so they
    // can never be the same tree (game rule).
    if (_RP.secondaryTree === treeName) {
      _RP.secondaryTree = null;
      _RP.secondaryMinors = [];
    }
    _ubRpRenderAll();
  }
  function _ubRpPickSecondary(treeName) {
    if (treeName === _RP.primaryTree) return;
    _RP.secondaryTree = treeName;
    _RP.secondaryMinors = [];
    _ubRpRenderAll();
  }
  function _ubRpPickKeystone(name) {
    _RP.keystone = (_RP.keystone === name) ? null : name;
    _ubRpRenderAll();
  }
  function _ubRpToggleMinor(side, rowIdx, name) {
    // Single-pick per row in the primary pane; up to 2 total in the
    // secondary pane with no per-row enforcement (visual freedom matches
    // the operator's stated "tabs + driven fields" scope).
    if (side === "primary") {
      const tree = _ubRpTreeByName(_RP.primaryTree);
      if (!tree) return;
      const rowNames = (tree.slots[rowIdx] || {}).runes.map((r) => r.name);
      // Remove any prior pick from THIS row, then add the new one.
      _RP.primaryMinors = _RP.primaryMinors.filter((n) => !rowNames.includes(n));
      if (!_RP.primaryMinors.includes(name)) _RP.primaryMinors.push(name);
    } else {
      const arr = _RP.secondaryMinors;
      if (arr.includes(name)) {
        _RP.secondaryMinors = arr.filter((n) => n !== name);
      } else if (arr.length >= 2) {
        // Replace the oldest to keep at 2.
        _RP.secondaryMinors = [arr[1], name];
      } else {
        _RP.secondaryMinors = [...arr, name];
      }
    }
    _ubRpRenderAll();
  }
  function _ubRpResetFromBuild(b) {
    const r = (b && b.runes) || {};
    _RP.primaryTree     = r.primary   || null;
    _RP.secondaryTree   = r.secondary || null;
    _RP.keystone        = r.keystone  || null;
    _RP.primaryMinors   = Array.isArray(r.minor_primary)   ? r.minor_primary.slice()   : [];
    _RP.secondaryMinors = Array.isArray(r.minor_secondary) ? r.minor_secondary.slice() : [];
  }

  function _userBuildsOpenForm(buildOrNull) {
    const pane  = _ubEl("ub-form-pane");
    const title = _ubEl("ub-form-title");
    if (!pane) return;
    if (!_UB.champion) {
      _ubFormStatus("Pick a champion first.", "error");
      return;
    }
    pane.hidden = false;
    _UB.editingId = (buildOrNull && buildOrNull.id) || null;
    if (title) title.textContent = _UB.editingId ? `Edit build (${_UB.editingId.slice(0,6)}...)` : "Add build";

    const b = buildOrNull || {};
    const sp = b.summoner_spells || [4, 14];
    _ubEl("ub-f-label").value     = b.label || "";
    _ubEl("ub-f-role").value      = b.role || "";
    _ubEl("ub-f-spell-d").value   = (sp[0] != null) ? sp[0] : 4;
    _ubEl("ub-f-spell-f").value   = (sp[1] != null) ? sp[1] : 14;
    _ubEl("ub-f-items").value     = (b.items || []).join("\n");
    _ubEl("ub-f-notes").value     = b.notes || "";
    _ubRpResetFromBuild(b);
    _SP.active = "d";
    _ubSpellRenderGrid();
    _ubSpellRenderCurrent();
    _ubFormStatus("", null);
    _ubRpFetchTrees().then(_ubRpRenderAll);
    // Wire the spell-slot click handlers once. _userBuildsWireOnce
    // wires top-level toolbar buttons; the slot buttons live INSIDE the
    // form pane that opens lazily, so wire here gated by a dataset flag.
    for (const slot of ["d", "f"]) {
      const el = _ubEl(`ub-sp-slot-${slot}`);
      if (el && el.dataset.wired !== "1") {
        el.dataset.wired = "1";
        el.addEventListener("click", () => _ubSpellSlotActivate(slot));
      }
    }
    // Re-highlight rows so the editing one gets the active border.
    _userBuildsFetchAndRender();
    // Focus the label field for fast typing.
    setTimeout(() => { const f = _ubEl("ub-f-label"); if (f) f.focus(); }, 50);
  }
  function _userBuildsCloseForm() {
    const pane = _ubEl("ub-form-pane");
    if (pane) pane.hidden = true;
    _UB.editingId = null;
    _userBuildsFetchAndRender();
  }
  function _ubFormStatus(msg, kind) {
    const s = _ubEl("ub-form-status");
    if (!s) return;
    if (!msg) { s.hidden = true; s.textContent = ""; s.className = "ub-form-status"; return; }
    s.hidden = false;
    s.textContent = msg;
    s.className = "ub-form-status" + (kind === "ok" ? " ok" : kind === "error" ? " error" : "");
  }
  function _ubReadForm() {
    const items = (_ubEl("ub-f-items").value || "")
      .split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    const dRaw = parseInt(_ubEl("ub-f-spell-d").value, 10);
    const fRaw = parseInt(_ubEl("ub-f-spell-f").value, 10);
    const d = Number.isFinite(dRaw) ? dRaw : 4;
    const f = Number.isFinite(fRaw) ? fRaw : 14;
    return {
      label:    (_ubEl("ub-f-label").value || "").trim(),
      role:     (_ubEl("ub-f-role").value  || "").trim() || null,
      runes: {
        keystone:        _RP.keystone     || (_ubEl("ub-f-keystone").value  || "").trim(),
        primary:         _RP.primaryTree  || (_ubEl("ub-f-primary").value   || "").trim(),
        secondary:       _RP.secondaryTree || (_ubEl("ub-f-secondary").value || "").trim(),
        minor_primary:   _RP.primaryMinors.slice(),
        minor_secondary: _RP.secondaryMinors.slice(),
      },
      summoner_spells: [d, f],
      items:    items,
      notes:    (_ubEl("ub-f-notes").value || "").trim(),
    };
  }
  function _userBuildsSave() {
    if (_UB.saving) return;
    if (!_UB.champion) { _ubFormStatus("Pick a champion first.", "error"); return; }
    const build = _ubReadForm();
    if (!build.label) { _ubFormStatus("Label is required.", "error"); return; }
    if (!build.items.length) { _ubFormStatus("At least one item required.", "error"); return; }
    const action = _UB.editingId ? "update" : "add";
    const body   = { action, champion: _UB.champion };
    if (_UB.editingId) { body.id = _UB.editingId; body.patch = build; }
    else               { body.build = build; }
    _UB.saving = true;
    _ubFormStatus(action === "add" ? "Saving..." : "Updating...", null);
    fetch("/api/sr-draft/user-builds", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    })
      .then(async (r) => {
        const txt = await r.text();
        let json = null;
        try { json = JSON.parse(txt); } catch (_) {}
        if (!r.ok || !json || json.ok !== true) {
          const msg = (json && json.error) || `HTTP ${r.status}`;
          _ubFormStatus(`Save failed: ${msg}`, "error");
          return;
        }
        _ubFormStatus("Saved ✓", "ok");
        _UB.editingId = null;
        const pane = _ubEl("ub-form-pane");
        if (pane) pane.hidden = true;
        _userBuildsFetchAndRender();
      })
      .catch((e) => _ubFormStatus(`Save failed: ${e}`, "error"))
      .finally(() => { _UB.saving = false; });
  }
  function _userBuildsDelete(build) {
    if (!build || !build.id) return;
    if (!confirm(`Delete build "${build.label}" for ${_UB.champion}?`)) return;
    fetch("/api/sr-draft/user-builds", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        action:   "delete",
        champion: _UB.champion,
        id:       build.id,
      }),
    })
      .then(async (r) => {
        const json = await r.json().catch(() => null);
        if (!r.ok || !json || json.ok !== true) {
          alert(`Delete failed: ${(json && json.error) || ("HTTP " + r.status)}`);
          return;
        }
        if (_UB.editingId === build.id) _userBuildsCloseForm();
        else _userBuildsFetchAndRender();
      })
      .catch((e) => alert(`Delete failed: ${e}`));
  }
  function _ubChampionPicked(name) {
    _UB.champion = (name || "").trim() || null;
    if (_UB.champion) {
      try { localStorage.setItem("rc-ub-last-champ", _UB.champion); } catch (_) {}
    }
    // Close any open form when the champion changes - editingId is
    // scoped to the previous champion's builds.
    const pane = _ubEl("ub-form-pane");
    if (pane) pane.hidden = true;
    _UB.editingId = null;
    _userBuildsFetchAndRender();
  }
  function _userBuildsWireOnce() {
    if (window.__userBuildsWired) return;
    window.__userBuildsWired = true;
    _ubPopulateDatalist();
    const inp = _ubEl("ub-champion-input");
    if (inp) {
      try {
        const last = localStorage.getItem("rc-ub-last-champ");
        if (last) { inp.value = last; _UB.champion = last; }
      } catch (_) {}
      inp.addEventListener("change", () => _ubChampionPicked(inp.value));
      inp.addEventListener("input",  () => {
        // Datalist selections fire 'input' once chosen; debounce a bit
        // so we don't flood the API while typing.
        clearTimeout(window.__ubChampDebounce);
        window.__ubChampDebounce = setTimeout(() => {
          if (inp.value !== _UB.champion) _ubChampionPicked(inp.value);
        }, 300);
      });
    }
    const addBtn = _ubEl("ub-add-btn");
    if (addBtn) addBtn.addEventListener("click", () => _userBuildsOpenForm(null));
    const closeBtn = _ubEl("ub-form-close");
    if (closeBtn) closeBtn.addEventListener("click", _userBuildsCloseForm);
    const cancelBtn = _ubEl("ub-form-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", _userBuildsCloseForm);
    const saveBtn = _ubEl("ub-form-save");
    if (saveBtn) saveBtn.addEventListener("click", _userBuildsSave);
  }


  // ── Home / lobby landing view (2026-04-26) ───────────────────────────
  // Shown when the user is sitting in client mode with no game/champ-
  // select active (i.e. between matches or just after RC boot). Pulls
  // /api/home/summary every 20s. Hides during ChampSelect / InProgress
  // so the main panel grid is unobstructed.
  const _HOME = { lastFetchAt: 0, intervalMs: 20000, fetching: false };
  function _homeShouldShow(lcu) {
    if (state.mode !== "client") return false;
    if (lcu && (lcu.phase === "ChampSelect"
                || lcu.phase === "InProgress"
                || lcu.phase === "GameStart")) return false;
    return true;
  }
  function _homeRenderRecent(rows) {
    const ul = document.getElementById("home-recent-list");
    if (!ul) return;
    ul.innerHTML = "";
    if (!rows || !rows.length) {
      ul.innerHTML = '<div class="home-empty">no matches yet</div>';
      return;
    }
    // V1 redesign 2026-04-29: render each match as a visual card with a
    // colored W/L-proxy stripe on the left (grade tier), champion name +
    // mode/time meta, KDA pill, and grade badge on the right. Click
    // routes to the Replay view (graceful no-op if no replay handler).
    for (const m of rows) {
      const card = document.createElement("div");
      card.className = "home-recent-card";
      card.dataset.matchId = m.match_id || "";
      const gradeRaw = String(m.grade || "-").toUpperCase()[0] || "-";
      const tier = (gradeRaw === "S" || gradeRaw === "A") ? "tier-good"
                 : (gradeRaw === "D" || gradeRaw === "F") ? "tier-bad"
                 : "tier-mid";
      // s218: spell out duration as "X Minutes" (was "Xm").
      const dur = m.duration_s
        ? `${Math.floor(m.duration_s / 60)} Minutes`
        : "";
      const tsShort = _to12((m.timestamp || "").split(" ")[1]?.slice(0,5) || "");
      // s218: mode subtype hook - when backend supplies mode_subtype
      // (e.g. "Classic" / "Mayhem" for ARAM 450/920), join it to the
      // mode label. Pure passthrough for now since match_history.db
      // doesn't capture queue_id yet. TODO(s218-dummy-data): drop the
      // mode_subtype branch once ingest stops returning null.
      const modeLabel = (m.mode_subtype && m.mode_subtype !== "")
        ? `${m.mode} ${m.mode_subtype}` : (m.mode || "");
      // CS row chip - DB already carries cs + cs_per_min per match.
      const csChip = (m.cs != null && m.cs > 0)
        ? `${m.cs} CS · ${(m.cs_per_min || 0).toFixed(1)}/min`
        : "";
      const metaParts = [modeLabel, tsShort, dur, csChip].filter(Boolean).join(" · ");

      const stripe = document.createElement("div");
      stripe.className = `home-recent-stripe ${tier}`;
      // Champion portrait (DDragon icon, locally mirrored). Falls back
      // to a "?" placeholder if the file is missing. Use _resolveChampId
      // so display names like "Kai'Sa" / "Wukong" / "Renata Glasc" map to
      // their DDragon file ids ("Kaisa" / "MonkeyKing" / "Renata") instead
      // of trying to load a 404'ing URL-encoded version of the raw name.
      const ver = (typeof CHAMPS !== "undefined" && CHAMPS && CHAMPS.version) ? CHAMPS.version : "16.11.1";
      const img = document.createElement("img");
      img.className = "home-recent-img";
      img.alt = "";
      img.loading = "lazy";
      const cid = _resolveChampId(m.champion) || encodeURIComponent(m.champion || "");
      img.src = `/data/ddragon/${ver}/img/champion/${cid}.png`;
      img.onerror = () => { img.style.visibility = "hidden"; };
      const main = document.createElement("div");
      main.className = "home-recent-main";
      const champ = document.createElement("span");
      champ.className = "home-recent-champ";
      champ.textContent = m.champion || "?";
      const meta = document.createElement("span");
      meta.className = "home-recent-meta";
      meta.textContent = metaParts;
      main.append(champ, meta);
      // End-of-match build strip. s219 LCU-ingest supplies items[] for
      // ingested matches; matches predating the pipeline send [] and
      // render as empty hatched slots (graceful - never fabricated).
      // Icons resolve from the local DDragon mirror (same source as the
      // champion portrait above), CDN fallback when the mirror lags the
      // live patch - mirrors the active_match / last_match convention.
      const itemStrip = document.createElement("div");
      itemStrip.className = "home-recent-items";
      const slotCount = (m.items && m.items.length) ? m.items.length : 6;
      for (let i = 0; i < Math.min(slotCount, 6); i++) {
        const slot = document.createElement("span");
        slot.className = "home-recent-item-slot";
        if (m.items && m.items[i]) {
          const iid = m.items[i];
          const ii = document.createElement("img");
          ii.className = "home-recent-item-icon";
          ii.src = `/data/ddragon/${ver}/img/item/${iid}.png`;
          ii.alt = "";
          ii.loading = "lazy";
          ii.onerror = () => {
            if (!ii.dataset.cdnRetry) {
              ii.dataset.cdnRetry = "1";
              ii.src = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png`;
            } else {
              ii.style.visibility = "hidden";
            }
          };
          slot.appendChild(ii);
        } else {
          slot.classList.add("empty");
        }
        itemStrip.appendChild(slot);
      }
      const kda = document.createElement("span");
      kda.className = "home-recent-kda";
      kda.textContent = m.kda || "-";
      const grade = document.createElement("span");
      grade.className = `home-recent-grade-badge ${gradeRaw}`;
      grade.textContent = gradeRaw;
      card.append(stripe, img, main, itemStrip, kda, grade);

      // s218 v6: click → History view focused on this match.
      // Saves the timestamp to sessionStorage so _historyFetchAndRender
      // can auto-select the matching session + scroll the match row
      // into view + highlight it briefly. Was previously gated on
      // m.match_id (rewind_history.db ids) which the local match_history
      // capture doesn't populate - the click handler never fired.
      if (m.timestamp) {
        card.style.cursor = "pointer";
        card.addEventListener("click", () => {
          try { sessionStorage.setItem("rc-history-focus-ts", m.timestamp); } catch (_) {}
          if (typeof _viewSaveManual === "function") _viewSaveManual("history");
          try { location.hash = "#history"; } catch (_) {}
          if (typeof _viewResolveAndApply === "function") _viewResolveAndApply();
          else if (typeof applyView === "function") applyView("history");
        });
      }
      ul.appendChild(card);
    }
  }
  function _homeRenderWeek(rows) {
    // V2 redesign 2026-04-29: replace bullet list with horizontal bar
    // chart. Each row's name cell carries a CSS gradient bar whose
    // width = (games / max_games), giving instant "what did I play
    // most" comparison across the top champs.
    const host = document.getElementById("home-week-list");
    if (!host) return;
    host.innerHTML = "";
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="home-empty">no games this week</div>';
      return;
    }
    const maxGames = Math.max(1, ...rows.map(r => r.games || 0));
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "home-week-bar-row";
      const gradeRaw = String(r.best_grade || "-").toUpperCase()[0] || "-";
      // s218: hue tint by best grade - subtle spectrum from green (S/A)
      // through neutral (B/C) to red (D/F). Applied via class so the
      // tint colors live in CSS variables.
      row.classList.add(`grade-tint-${gradeRaw}`);
      const pct = Math.round(((r.games || 0) / maxGames) * 100);

      const name = document.createElement("span");
      name.className = "home-week-bar-name";
      name.style.setProperty("--bar-pct", pct + "%");
      name.textContent = r.champion || "?";

      const games = document.createElement("span");
      games.className = "home-week-bar-games";
      const gn = r.games || 0;
      games.textContent = `${gn} game${gn === 1 ? "" : "s"}`;

      // s218: KDA cell now shows "1.8  22/10/18" - average + raw totals
      // pulled from per-champion aggregation. Falls back to avg only if
      // the backend hasn't supplied breakdown fields (pre-s218).
      const kda = document.createElement("span");
      kda.className = "home-week-bar-kda";
      const avgStr = (r.avg_kda != null) ? r.avg_kda.toFixed(1) : "-";
      if (r.kills != null && r.deaths != null && r.assists != null) {
        kda.innerHTML = `<b>${avgStr}</b> <span class="home-week-bar-kda-raw">${r.kills}/${r.deaths}/${r.assists}</span>`;
      } else {
        kda.textContent = avgStr;
      }

      // s218: CS chip - AVERAGE CS per game + CS/min average over the
      // week's games on this champion. Operator clarified average, not
      // total. Hidden when zero (Arena / Brawl don't track CS the same
      // way and many sessions surface 0).
      const cs = document.createElement("span");
      cs.className = "home-week-bar-cs";
      if (r.cs_total != null && r.cs_total > 0 && r.games > 0) {
        const csAvg = Math.round(r.cs_total / r.games);
        cs.textContent = `${csAvg} CS · ${(r.cs_per_min || 0).toFixed(1)}/min`;
      } else {
        cs.textContent = "";
      }

      const grade = document.createElement("span");
      grade.className = `home-recent-grade-badge ${gradeRaw}`;
      grade.textContent = gradeRaw;
      // No inline sizing - the .home-week-bar-row .home-recent-grade-badge
      // selector in CSS handles the inline-row variant (28x28 / 13px).
      row.append(name, games, kda, cs, grade);
      host.appendChild(row);
    }
  }
  function _homeRenderToday(t, streaks) {
    // V1 redesign 2026-04-29: populate the hero banner instead of the
    // previous TODAY card grid. Greeting derives from local hour;
    // headline is a one-line read of today's volume + perf direction;
    // chips below carry the detailed numbers.
    // V3 (2026-04-30, suggestion #7): when streaks exist, surface them
    // in the sub-text instead of the bland "no games yet today".
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const games = (t && t.games) || 0;
    const avg = t && t.avg_kda;

    // Time-of-day greeting
    const hr = new Date().getHours();
    const greet = hr < 5 ? "Burning the midnight oil"
                : hr < 12 ? "Good morning"
                : hr < 17 ? "Good afternoon"
                : hr < 22 ? "Good evening"
                          : "Late night session";
    set("home-hero-time", greet);
    // Streak-aware sub-text: prefer the most useful active streak when
    // available, otherwise fall back to today's game count line.
    const streakParts = [];
    if (streaks) {
      const pd = streaks.play_days || 0;
      const gg = streaks.good_grades || 0;
      if (pd >= 2) streakParts.push(`${pd}-day play streak`);
      if (gg >= 2) streakParts.push(`${gg} S/A in a row`);
    }
    let sub;
    if (games > 0) {
      sub = `${games} game${games===1?"":"s"} today`;
      if (streakParts.length) sub += " · " + streakParts.join(" · ");
    } else if (streakParts.length) {
      sub = streakParts.join(" · ");
    } else {
      sub = "no games yet today";
    }
    set("home-hero-sub", sub);

    // Headline: empty state vs games today
    const headline = document.getElementById("home-hero-headline");
    if (headline) {
      headline.classList.remove("up", "down", "flat");
      if (games === 0) {
        headline.textContent = "Ready when you are";
        headline.classList.add("flat");
      } else {
        const avgStr = avg != null ? avg.toFixed(2) : "-";
        headline.textContent = `${games} game${games===1?"":"s"} · ${avgStr} avg KDA`;
        // s218 v7: always .flat. The prior absolute-threshold classifier
        // (>=2.5 up / <1.5 down) had no comparison baseline - a single
        // 1.27-KDA day rendered as "down/red" even though there was
        // nothing to compare against. Real up/down should wait until
        // a yesterday/avg-of-last-N baseline is wired.
        headline.classList.add("flat");
      }
    }

    // Chips
    set("home-hero-kda", t && t.total_kda ? t.total_kda : "-");
    set("home-hero-avg", avg != null ? avg.toFixed(2) : "-");
    const gradeStr = t && t.grades
      ? Object.entries(t.grades).map(([g,n]) => `${g}×${n}`).join(" ")
      : "-";
    set("home-hero-grades", gradeStr || "-");
    const modeStr = t && t.modes
      ? Object.entries(t.modes).map(([m,n]) => `${m} ${n}`).join(" · ")
      : "-";
    set("home-hero-modes", modeStr || "-");

    // Legacy IDs (set if present so any external reader still works).
    set("home-today-count", games > 0 ? `${games} game${games===1?"":"s"}` : "");
    set("home-today-kda",   t && t.total_kda ? t.total_kda : "-");
    set("home-today-avg",   avg != null ? avg.toFixed(2) : "-");
    set("home-today-grades", gradeStr || "-");
    set("home-today-modes",  modeStr || "-");
  }
  function _homeRenderServices(rows) {
    // V1 redesign 2026-04-29: render as a thin strip of compact pills
    // (dot + name) instead of a card-sized bulleted list. Detail string
    // moves to the title attribute (hover tooltip) - services are a
    // glance check, not browsable content. Container changed from <ul>
    // to <div class="home-services-strip"> in the new HTML.
    const strip = document.getElementById("home-services-list");
    if (!strip) return;
    strip.innerHTML = "";
    if (!rows || !rows.length) {
      strip.innerHTML = '<span class="home-empty">no services reporting</span>';
      return;
    }
    for (const s of rows) {
      const pill = document.createElement("span");
      pill.className = `home-services-pill ${s.ok ? "ok" : "err"}`;
      if (s.detail) pill.title = s.detail;
      const dot = document.createElement("span");
      dot.className = "home-services-dot";
      const name = document.createElement("span");
      name.className = "home-services-name";
      name.textContent = s.name || "?";
      pill.append(dot, name);
      strip.appendChild(pill);
    }
  }
  // UI scale v2.1 page #6 audit ritual step 5 state-coverage mock fixture
  // (2026-05-23). When body.dataset.uiMock === "1" the fetch short-
  // circuits to /data/ui_mock/home.json instead of /api/home/summary.
  let _homeMockPromise = null;
  function _homeMockLoad() {
    if (_homeMockPromise) return _homeMockPromise;
    _homeMockPromise = fetch("/data/ui_mock/home.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .catch(() => null);
    return _homeMockPromise;
  }
  function _homeIsMock() {
    return document.body && document.body.dataset.uiMock === "1";
  }
  function _homeFetchAndRender() {
    if (_HOME.fetching) return;
    _HOME.fetching = true;
    const promise = _homeIsMock()
      ? _homeMockLoad()
      : fetch("/api/home/summary", { cache: "no-store" })
          .then((r) => (r && r.ok ? r.json() : null));
    promise
      .then((data) => {
        _HOME.fetching = false;
        if (!data) return;
        _HOME.lastFetchAt = Date.now();
        // s218 v7: cache streaks so _homeMirrorAlerts can read them
        // when populating Section 3 of Tonight's Pick.
        _HOME.streaks = data.streaks || {};
        _homeRenderToday(data.today || {}, data.streaks || {});
        _homeRenderRecent(data.recent || []);
        _homeRenderWeek(data.this_week || []);
        _homeRenderServices(data.services || []);
        _homeUpdateHeroMotif(data);
        // Render trends FIRST so its hidden flag is current when
        // _homeRenderCoach decides whether the combo wrapper shows.
        _homeRenderTrends(data.trends || {});
        _homeRenderCoach(data.tonight_pick, data.last_build);
        _homeMirrorAlerts();
      })
      .catch(() => { _HOME.fetching = false; });
  }
  // V3 (suggestion #5, redesign 2026-04-30): paint sparklines INTO the
  // hero chips (inline next to each chip's value), replacing the prior
  // standalone .home-trends row. Each chip carries data-metric on its
  // wrapper so the right SVG gets the right series.
  function _homeRenderTrends(trends) {
    const series = ["cs_per_min", "gold_per_min", "kda"];
    for (const metric of series) {
      const chip = document.querySelector(`.home-hero-chip[data-metric="${metric}"]`);
      if (!chip) continue;
      const points = trends[metric] || [];
      const svg = chip.querySelector(".home-hero-spark");
      if (!svg) continue;
      // Set the chip's headline value to the latest non-null trend point
      // (CS / GOLD only - KDA chip val stays driven by _homeRenderToday
      // which uses today's KDA, more relevant than 14d-latest).
      const latest = [...points].reverse().find(p => p && p.value != null);
      if (latest != null && metric !== "kda") {
        const valId = metric === "cs_per_min" ? "home-hero-cs"
                    : metric === "gold_per_min" ? "home-hero-gold" : null;
        if (valId) {
          const valEl = document.getElementById(valId);
          if (valEl) valEl.textContent = latest.value.toFixed(1);
        }
      }
      // Build SVG path. Skip if all null.
      svg.innerHTML = "";
      const vals = points.map(p => (p && p.value != null) ? p.value : null);
      const realVals = vals.filter(v => v != null);
      if (realVals.length < 2) continue;
      const minV = Math.min(...realVals);
      const maxV = Math.max(...realVals);
      const span = (maxV - minV) || 1;
      const W = 60, H = 18;
      const xs = points.map((_, i) => (i / (points.length - 1)) * W);
      const ys = vals.map(v => v == null ? null : H - ((v - minV) / span) * (H - 4) - 2);
      // Polyline path skipping nulls
      let d = "";
      let started = false;
      for (let i = 0; i < points.length; i++) {
        if (ys[i] == null) { started = false; continue; }
        d += (started ? " L" : " M") + xs[i].toFixed(1) + " " + ys[i].toFixed(1);
        started = true;
      }
      // Area path (fill under curve)
      let area = "";
      started = false;
      let areaStartX = 0;
      for (let i = 0; i < points.length; i++) {
        if (ys[i] == null) {
          if (started) area += " L" + xs[i-1].toFixed(1) + " " + H + " Z";
          started = false; continue;
        }
        if (!started) { areaStartX = xs[i]; area += " M" + xs[i].toFixed(1) + " " + H + " L" + xs[i].toFixed(1) + " " + ys[i].toFixed(1); started = true; }
        else area += " L" + xs[i].toFixed(1) + " " + ys[i].toFixed(1);
      }
      if (started) area += " L" + xs[points.length - 1].toFixed(1) + " " + H + " Z";
      // Append SVG nodes (createElementNS so they render)
      const NS = "http://www.w3.org/2000/svg";
      const a = document.createElementNS(NS, "path");
      a.setAttribute("class", "spark-area"); a.setAttribute("d", area);
      svg.appendChild(a);
      const l = document.createElementNS(NS, "path");
      l.setAttribute("class", "spark-line"); l.setAttribute("d", d);
      svg.appendChild(l);
      // Highlight last data point
      const lastIdx = ys.findLastIndex ? ys.findLastIndex(v => v != null)
                                        : (function(){ for (let j = ys.length-1; j>=0; j--) if (ys[j]!=null) return j; return -1; })();
      if (lastIdx >= 0) {
        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("class", "spark-dot");
        dot.setAttribute("cx", xs[lastIdx].toFixed(1));
        dot.setAttribute("cy", ys[lastIdx].toFixed(1));
        dot.setAttribute("r", "2");
        svg.appendChild(dot);
      }
    }
  }
  // V3 (suggestions #1 + #4): tonight's pick + last build cards.
  // After 2026-04-30 redesign, pickCard lives inside #home-combo
  // (alongside sparklines); buildCard is its own row below.
  function _homeRenderCoach(pick, build) {
    const combo = document.getElementById("home-combo");
    const pickCard = document.getElementById("home-coach-pick");
    const buildCard = document.getElementById("home-coach-build");
    const trends = document.getElementById("home-trends");
    if (!combo || !pickCard || !buildCard) return;
    const ver = (typeof CHAMPS !== "undefined" && CHAMPS && CHAMPS.version) ? CHAMPS.version : "16.11.1";
    // Tonight's pick
    if (pick && pick.champion) {
      pickCard.hidden = false;
      const img = document.getElementById("home-coach-pick-img");
      const champ = document.getElementById("home-coach-pick-champ");
      const reason = document.getElementById("home-coach-pick-reason");
      if (img) {
        const pickCid = _resolveChampId(pick.champion) || encodeURIComponent(pick.champion);
        img.src = `/data/ddragon/${ver}/img/champion/${pickCid}.png`;
        img.alt = pick.champion;
        img.onerror = () => { img.style.visibility = "hidden"; };
      }
      if (champ) {
        champ.textContent = pick.champion;
        // s218 v7: clicking the champion name jumps to History filtered
        // by this champion. Wired idempotently - re-renders replace the
        // listener via cloneNode-and-replace to avoid stacking handlers.
        const fresh = champ.cloneNode(true);
        fresh.addEventListener("click", () => {
          try { sessionStorage.setItem("rc-history-focus-champion", pick.champion); } catch (_) {}
          if (typeof _viewSaveManual === "function") _viewSaveManual("history");
          try { location.hash = "#history"; } catch (_) {}
          if (typeof _viewResolveAndApply === "function") _viewResolveAndApply();
          else if (typeof applyView === "function") applyView("history");
        });
        champ.parentNode.replaceChild(fresh, champ);
      }
      if (reason) {
        const modeStr = (pick.modes || []).join("/");
        reason.textContent = pick.reason
          + (modeStr ? ` · ${modeStr}` : "")
          + (pick.grade ? ` · best ${pick.grade}` : "");
      }
    } else {
      pickCard.hidden = true;
    }
    // Last build (6 item slots, fills with .empty placeholders if <6)
    if (build && Array.isArray(build.items) && build.items.length) {
      buildCard.hidden = false;
      const sub = document.getElementById("home-coach-build-sub");
      const items = document.getElementById("home-coach-build-items");
      if (sub) sub.textContent = (build.champion ? `· ${build.champion}` : "")
                                 + (build.mode ? ` · ${build.mode}` : "");
      if (items) {
        items.innerHTML = "";
        const slots = build.items.slice(0, 6);
        while (slots.length < 6) slots.push(0);
        for (const id of slots) {
          if (id) {
            const im = document.createElement("img");
            im.className = "home-coach-build-item";
            im.alt = "";
            im.loading = "lazy";
            im.src = `/data/ddragon/${ver}/img/item/${id}.png`;
            im.onerror = () => { im.classList.add("empty"); im.removeAttribute("src"); };
            items.appendChild(im);
          } else {
            const sp = document.createElement("span");
            sp.className = "home-coach-build-item empty";
            items.appendChild(sp);
          }
        }
      }
    } else {
      buildCard.hidden = true;
    }
    // Show the combo wrapper if EITHER tonight's-pick or trends has data
    // (trends visibility is set independently by _homeRenderTrends).
    const trendsVisible = !!(trends && !trends.hidden);
    combo.hidden = pickCard.hidden && !trendsVisible;
  }
  // Champion motif on the hero bg. Picks the most-played champion from
  // this_week (or the most-recent match as a fallback) and sets the
  // local DDragon icon as the hero background. Local-only - no CDN
  // round-trip; falls back silently if no champion data is available.
  function _homeUpdateHeroMotif(data) {
    const bg = document.getElementById("home-hero-bg");
    if (!bg) return;
    let champ = null;
    const wk = (data && data.this_week) || [];
    if (wk.length && wk[0].champion) champ = wk[0].champion;
    if (!champ) {
      const r = (data && data.recent) || [];
      if (r.length && r[0].champion) champ = r[0].champion;
    }
    if (!champ) return;
    const ver = (typeof CHAMPS !== "undefined" && CHAMPS && CHAMPS.version) ? CHAMPS.version : "16.11.1";
    const motifCid = _resolveChampId(champ) || encodeURIComponent(champ);
    bg.style.backgroundImage =
      `url("/data/ddragon/${ver}/img/champion/${motifCid}.png")`;
  }
  // Mirror advisory + digest into the icon-button badges on Tonight's
  // Pick (V3 redesign 2026-04-30). Sets the badge text + toggles
  // .has-data so CSS recolors the button when the count/label is
  // non-default. Badge tooltip carries the verbose text.
  function _homeMirrorAlerts() {
    // s218 v7: populates Section 3 of Tonight's Pick - the Streak +
    // Advisories sub-header rows. Was previously mirroring badge text
    // into the (now-removed) advisory + digest pip-buttons. Streak
    // reads from cached _HOME.streaks (from /api/home/summary);
    // advisories read live from the footer #advisory-count span which
    // is the canonical store the existing advisory system updates.
    const advCount = document.getElementById("advisory-count");
    const advValEl = document.getElementById("home-pick-advisories-val");
    if (advValEl) {
      const n = advCount ? (parseInt(advCount.textContent || "0", 10) || 0) : 0;
      advValEl.textContent = n === 0 ? "None"
                                     : `${n} open`;
      advValEl.title = n === 0 ? "No open advisories"
                               : `${n} open advisor${n === 1 ? "y" : "ies"}`;
    }
    const streakValEl = document.getElementById("home-pick-streak-val");
    if (streakValEl) {
      const s = _HOME.streaks || {};
      const gg = s.good_grades || 0;
      const pd = s.play_days || 0;
      if (gg >= 2) {
        streakValEl.textContent = `${gg}× S/A in a row`;
      } else if (pd >= 2) {
        streakValEl.textContent = `${pd}-day play streak`;
      } else {
        streakValEl.textContent = "-";
      }
    }
  }
  function renderHomePanel(lcu) {
    const overlay = document.getElementById("home-overlay");
    if (!overlay) return;
    // s162 (2026-05-10): hard-gate on view. Pre-fix the home-overlay
    // un-hid based on phase regardless of active view, which caused it
    // to leak into Lobby / Dev / etc when handleLcuEnvelope started
    // actually firing renderHomePanel after the champ_select.js
    // ReferenceError fix. Home-overlay is the home-view surface - only
    // show when the home view is active.
    const onHomeView = document.body.dataset.view === "home";
    if (!onHomeView) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    if (!_homeShouldShow(lcu)) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    if (!_HOME.lastFetchAt) _homeFetchAndRender();
  }
  // s218 v5: Home-unique Find Match picker show/hide. Lazily creates
  // a backdrop dimmer on first show; both close on outside-click +
  // Escape. Wired once on first call.
  function _homeFindMatchPickerShow() {
    const picker = document.getElementById("home-find-match-picker");
    if (!picker) return;
    let backdrop = document.getElementById("home-find-match-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "home-find-match-backdrop";
      backdrop.className = "home-find-match-backdrop";
      backdrop.addEventListener("click", _homeFindMatchPickerHide);
      document.body.appendChild(backdrop);
      // Escape closes the picker. Bound once; safe to leave attached.
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !picker.classList.contains("hidden")) {
          _homeFindMatchPickerHide();
        }
      });
    }
    backdrop.classList.remove("hidden");
    picker.classList.remove("hidden");
    picker.setAttribute("aria-hidden", "false");
  }
  function _homeFindMatchPickerHide() {
    const picker = document.getElementById("home-find-match-picker");
    const backdrop = document.getElementById("home-find-match-backdrop");
    if (picker) {
      picker.classList.add("hidden");
      picker.setAttribute("aria-hidden", "true");
    }
    if (backdrop) backdrop.classList.add("hidden");
  }
  // V3 (2026-04-29): unconditional startup wiring + fetch tick. Click
  // handlers and the data poll now run regardless of whether
  // renderHomePanel ever fires (the previous design left them dormant
  // when LCU was offline). Runs once via DOMContentLoaded.
  function _homeWireStartup() {
    const overlay = document.getElementById("home-overlay");
    if (!overlay || overlay._wiredV3) return;
    overlay._wiredV3 = true;
    // Action tiles → save as manual override + navigate (same flow the
     // dropdown menu uses). Without _viewSaveManual the next LCU poll's
     // _viewResolveAndApply auto-derives back to "home" within 2s.
    overlay.querySelectorAll(".home-action-tile[data-target]").forEach((tile) => {
      tile.addEventListener("click", (e) => {
        const t = tile.dataset.target;
        if (!t) return;
        const isFindMatch = tile.dataset.flow === "find-match-launch";
        // s218 v5: Find Match opens its own Home-unique picker instead
        // of routing - operator picks a queue first, then we fire the
        // LCU change_queue_type cmd and only THEN route to lobby. The
        // lobby view's #lv-mode-menu is left alone; the Home picker is
        // a standalone copy mirrored from the same queue list.
        if (isFindMatch) {
          e.stopPropagation();
          _homeFindMatchPickerShow();
          return;
        }
        if (typeof _viewSaveManual === "function") _viewSaveManual(t);
        try { location.hash = "#" + t; } catch (_) {}
        if (typeof _viewResolveAndApply === "function") _viewResolveAndApply();
        else if (typeof applyView === "function") applyView(t);
      });
    });
    // s218 v5: wire the Home-unique Find Match picker (item clicks +
    // backdrop close + Escape close). Backdrop is created lazily on
    // first show so the DOM stays clean when the picker isn't used.
    const pickerEl = document.getElementById("home-find-match-picker");
    if (pickerEl) {
      pickerEl.querySelectorAll(".lq-mode-item[data-hfm-qid]").forEach((item) => {
        item.addEventListener("click", (e) => {
          e.stopPropagation();
          const qid = parseInt(item.dataset.hfmQid, 10) || 0;
          const special = item.dataset.hfmSpecial || "";
          // s234 (#89): poll the LCU result + surface failures via the
          // lobby-view error channel (we route there next). Previously the
          // result was swallowed (`() => {}` / fire-and-forget), so Practice
          // Tool / ARAM Mayhem / Arena failed silently - the operator had no
          // signal to capture. _lvQueueChangeError is module-scope.
          if (special === "practice") {
            try {
              lcuCmd({ cmd: "lobby.create_practice_tool" }).then((res) => {
                if (typeof lcuPollResult === "function") {
                  lcuPollResult(res && res.id, (r) => {
                    if (r && r.ok === false)
                      _lvQueueChangeError("Practice Tool: " + (r.err || "failed"));
                  });
                }
              });
            } catch (_) {}
          } else if (qid > 0) {
            try {
              lcuCmd({ cmd: "change_queue_type", queue_id: qid }).then((res) => {
                if (typeof lcuPollResult === "function") {
                  lcuPollResult(res && res.id, (r) => {
                    if (r && r.ok === false) _lvQueueChangeError(r.err);
                  });
                }
              });
            } catch (_) {}
          }
          _homeFindMatchPickerHide();
          // Route to Pre-Game Lobby after the LCU command is dispatched.
          if (typeof _viewSaveManual === "function") _viewSaveManual("lobby");
          try { location.hash = "#lobby"; } catch (_) {}
          if (typeof _viewResolveAndApply === "function") _viewResolveAndApply();
          else if (typeof applyView === "function") applyView("lobby");
        });
      });
    }
    // Alerts rows → synthesize click on the original hidden footer
    // triggers so the existing popout / cycle handlers fire unchanged.
    const wireAlertRow = (rowId, anchorId) => {
      const row = document.getElementById(rowId);
      const anchor = document.getElementById(anchorId);
      if (!row || !anchor) return;
      row.addEventListener("click", () => anchor.click());
      // Keyboard parity for ENTER/SPACE
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); anchor.click(); }
      });
    };
    // s218 v7: the old advisory + digest pip-buttons that wireAlertRow
    // targeted were removed in the Tonight's Pick Section-3 redesign.
    // Streak + Advisories now live as sub-header rows populated by
    // _homeMirrorAlerts; no per-row click wiring needed.
    // Initial fetch + recurring tick + alerts mirror.
    _homeFetchAndRender();
    setInterval(_homeFetchAndRender, _HOME.intervalMs);
    setInterval(_homeMirrorAlerts, 5000);
    _homeMirrorAlerts();
    // Personal context (item 124): top-3 recurring death patterns from
    // rewind_history.db, mounted inside the Right Now panel body.
    // 60s polling with mtime-keyed backend cache.
    startPersonalContextPolling();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _homeWireStartup);
  } else {
    _homeWireStartup();
  }

  // ── Lobby view (2026-04-26 v2) ──────────────────────────────────
  // Full-grid lobby surface (QUEUE / PARTY / TIPS / RECENT IN QUEUE)
  // that replaces the post-match-duped 5-panel layout. Reuses the
  // same lcu.lobby data feed as the inline #lobby-overlay; this view
  // is the richer presentation when the user explicitly navigates
  // here OR auto-mode resolves to lobby.
  const _LV = {
    wired: false,
    activeSlot: null,    // "primary" | "secondary" | null - which lane-pref slot the popup is anchored to
    prefPrimary:   "UNSELECTED",
    prefSecondary: "UNSELECTED",
    needsPick:     false,    // true when primary just changed FROM fill → role; secondary needs re-pick
    partyOpen:     true,     // operator default per s162 spec
    partyToggleInflight: false,  // s209: gate refresh from clobbering optimistic click
    lastLcuPartyType: null,      // s209: track external LCU changes vs operator clicks
    autoAccept:    false,    // s162 v2: Auto Accept default off
    mainsTab:      null,     // s162 v4: "you" | "party" | null (auto from party_size)
  };
  // s162 v15: action-button glyph constants. Crown swapped to the
  // actual League captain-icon (CommunityDragon mirror, downloaded
  // to /icons/lobby/captain-icon-crown.png) so the Party panel
  // matches the in-client lobby treatment exactly. Copy swapped to
  // Phosphor `copy-simple` SVG - thin stroke matches the action
  // button border-soft treatment, currentColor inherits hover.
  const _LV_ICON_CROWN = '<img class="lv-crown-img" src="/icons/lobby/captain-icon-crown.png" alt="Party leader" />';
  const _LV_ICON_COPY = (
    '<svg class="lv-copy-svg" viewBox="0 0 256 256" aria-hidden="true">' +
      '<path d="M216 32H88a8 8 0 0 0-8 8v40H40a8 8 0 0 0-8 8v128a8 8 0 0 0 8 8h128a8 8 0 0 0 8-8v-40h40a8 8 0 0 0 8-8V40a8 8 0 0 0-8-8ZM160 208H48V96h112Zm48-48h-32V88a8 8 0 0 0-8-8H96V48h112Z"/>' +
    '</svg>'
  );
  // s162 v2: full uppercase per operator spec ("TOP | JUNGLE | MIDDLE
  // | BOTTOM | SUPPORT | FILL"). UTILITY is the LCU's enum value for
  // the support role; "SUPPORT" is the operator-facing label.
  const LANE_LABELS = {
    TOP: "TOP", JUNGLE: "JUNGLE", MIDDLE: "MIDDLE",
    BOTTOM: "BOTTOM", UTILITY: "SUPPORT", FILL: "FILL",
    UNSELECTED: "-",
  };
  const LANE_ICONS = {
    TOP: "/icons/positions/top.png",
    JUNGLE: "/icons/positions/jungle.png",
    MIDDLE: "/icons/positions/middle.png",
    BOTTOM: "/icons/positions/bottom.png",
    UTILITY: "/icons/positions/utility.png",
    FILL: "/icons/positions/fill.png",
  };
  // SR map queue ids - controls strip is SR-only. ARAM (450/920/2400),
  // Arena (1750 live / 1700/1710 legacy) hide the strip entirely.
  // s162 (2026-05-10): SR map queue ids - controls strip is SR-only.
  // Includes Swiftplay (480) - added 2026-05-10 from operator's live
  // mode list. Brawl modes (NEXUSBLITZ/etc) removed since Brawl is no
  // longer a selectable queue per Riot. ARAM (450/920/2400) + Arena
  // (1750) hide the strip entirely. 2026-05-24 (#89): Arena live queue
  // confirmed 1750 (was 1700 pre-16.10).
  const SR_QUEUE_IDS = new Set([
    400, 420, 430, 440, 480, 700,    // Normal Draft, Ranked Solo, Normal Blind, Ranked Flex, Swiftplay, Clash
    830, 840, 850, 870, 880, 890,    // Co-op vs AI variants (Intro/Beginner/Intermediate)
  ]);
  // UI scale v2.1 page #7 audit ritual step 5 state-coverage mock fixture
  // (2026-05-23). When body.dataset.uiMock === "1" the lobby view's
  // _lobbyViewRefresh consumes /data/ui_mock/lobby.json (shape mirrors
  // lcu envelope's `lobby` + `config` blocks) instead of the live
  // state.latest.lcu feed - so the Pre-Game Lobby surface renders
  // without an actively forwarding LCU agent during the audit pass.
  let _lobbyMockPromise = null;
  let _lobbyMockData = null;
  function _lobbyIsMock() {
    return !!(document.body && document.body.dataset.uiMock === "1");
  }
  function _lobbyMockLoad() {
    if (_lobbyMockPromise) return _lobbyMockPromise;
    _lobbyMockPromise = fetch("/data/ui_mock/lobby.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _lobbyMockData = data || null;
        // Once the mock lands, re-fire the lobby refresh so the placeholder
        // render that fired before the fetch resolved gets replaced.
        if (_VIEW && _VIEW.current === "lobby") {
          try { _lobbyViewRefresh(); } catch (_) {}
        }
        return _lobbyMockData;
      })
      .catch(() => { _lobbyMockData = null; return null; });
    return _lobbyMockPromise;
  }
  function _lobbyResolveLcu() {
    if (_lobbyIsMock()) {
      if (_lobbyMockData) {
        return {
          phase: _lobbyMockData.phase || "Lobby",
          lobby: _lobbyMockData.lobby || null,
          config: _lobbyMockData.config || {},
        };
      }
      // Fire the load on first call; the .then re-fires refresh on landing.
      _lobbyMockLoad();
    }
    return (state.latest && state.latest.lcu) || {};
  }
  // UI scale v2.1 page #8 audit ritual step 5 state-coverage mock fixture
  // (2026-05-23). When body.dataset.uiMock === "1" and the view is
  // champ-select, the renderChampSelectView call sites consume
  // /data/ui_mock/champ_select_sr.json (shape mirrors lcu envelope's
  // `phase` + `champ_select` blocks) instead of the live state.latest.lcu
  // feed - so the Champ Select surface renders without an active LCU
  // ChampSelect phase during the audit pass.
  let _csMockPromise = null;
  let _csMockData = null;
  function _csIsMock() {
    return !!(document.body && document.body.dataset.uiMock === "1");
  }
  function _csMockLoad() {
    if (_csMockPromise) return _csMockPromise;
    // 2026-05-23 item 165: mock fixture picker - ?mode=aram URL flag
    // loads the ARAM fixture (Mark / Snowball + bench), else SR.
    // 2026-05-25 page #10: ?mode=arena URL flag loads the Arena 6x2
    // fixture (6 sub-teams, augments scaffold, Flash + Heal spells).
    let mockUrl = "/data/ui_mock/champ_select_sr.json";
    try {
      const params = new URLSearchParams(window.location.search || "");
      const m = (params.get("mode") || "").toLowerCase();
      if (m === "aram") {
        mockUrl = "/data/ui_mock/champ_select_aram.json";
      } else if (m === "arena") {
        mockUrl = "/data/ui_mock/champ_select_arena.json";
      }
    } catch (_) {}
    _csMockPromise = fetch(mockUrl, { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _csMockData = data || null;
        if (_VIEW && _VIEW.current === "champ-select") {
          try { renderChampSelectView(_csResolveLcu()); } catch (_) {}
        }
        return _csMockData;
      })
      .catch(() => { _csMockData = null; return null; });
    return _csMockPromise;
  }
  function _csResolveLcu(realLcu) {
    if (_csIsMock()) {
      if (_csMockData) {
        return {
          phase: _csMockData.phase || "ChampSelect",
          champ_select: _csMockData.champ_select || null,
          config: _csMockData.config || {},
        };
      }
      _csMockLoad();
    }
    return realLcu || (state.latest && state.latest.lcu) || {};
  }

  // UI scale v2.1 pages #11/12/13 audit ritual + Live UI capture mock
  // fixture dispatcher (item 188, 2026-05-25). When body.dataset.uiMock
  // === "1" AND URL ?mode=<sr|aram|arena> is set, the renderActiveMatch
  // call-site short-circuits to /data/ui_mock/active_match_<mode>.json
  // (full coach payload + liveclient block + summoner_cooldowns +
  // forced phase=InProgress so the active_match.js isLive freshness gate
  // passes). Mirrors _csMockLoad (items 165 + 181) + _lmMockLoad
  // (item 183) + _lobbyMockLoad (item 163) patterns.
  let _amMockPromise = null;
  let _amMockData = null;
  function _amIsMock() {
    return !!(document.body && document.body.dataset.uiMock === "1");
  }
  function _amMockUrl() {
    let url = null;
    try {
      const params = new URLSearchParams(window.location.search || "");
      const m = (params.get("mode") || "").toLowerCase();
      if (m === "sr")         url = "/data/ui_mock/active_match_sr.json";
      else if (m === "aram")  url = "/data/ui_mock/active_match_aram.json";
      else if (m === "arena") url = "/data/ui_mock/active_match_arena.json";
    } catch (_) {}
    return url;
  }
  function _amMockLoad() {
    if (_amMockPromise) return _amMockPromise;
    const url = _amMockUrl();
    if (!url) {
      _amMockPromise = Promise.resolve(null);
      return _amMockPromise;
    }
    _amMockPromise = fetch(url, { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _amMockData = data || null;
        // Re-fire active-match render on landing so the placeholder
        // render that fired before fetch resolved gets replaced.
        if (_VIEW && _VIEW.current === "active-match" && _amMockData) {
          try {
            renderActiveMatch(_amMockData.coach || {}, {
              mode: _amMockData.mode || "sr",
              lcuPhase: _amMockData.phase || "InProgress",
              liveclient: _amMockData.liveclient || null,
              cooldowns: _amMockData.summoner_cooldowns || null,
            });
          } catch (_) {}
        }
        return _amMockData;
      })
      .catch(() => { _amMockData = null; return null; });
    return _amMockPromise;
  }

  function _fmtMasteryPoints(pts) {
    const n = pts | 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, "") + " M points";
    if (n >= 1000)    return Math.round(n / 1000) + " K points";
    return n + " points";
  }
  function _fmtK(n) {
    const v = n | 0;
    if (v >= 1000) return (v / 1000).toFixed(v >= 10000 ? 0 : 1).replace(/\.0$/, "") + "K";
    return String(v);
  }
  function _fmtPct(num, den) {
    if (!den) return "-";
    return Math.round((num / den) * 100) + "%";
  }
  function _mainsTabState() {
    // Default tab driven by party composition. Solo → YOUR. Party → PARTY.
    const lcu = (state.latest && state.latest.lcu) || {};
    const lobby = lcu.lobby || null;
    const partySize = (lobby && lobby.party_size) | 0;
    if (_LV.mainsTab) return _LV.mainsTab;          // operator-toggled wins
    return partySize > 1 ? "party" : "you";
  }
  // s171: server-backed Mains cache. The agent doesn't forward
  // main_champs in the LCU envelope - it lives in match_history.db on
  // Legion, joined with live LCU mastery. /api/mains is the resolver.
  // Cache TTL 60s; per-puuid keyed so party-tab queries can be added
  // later without invalidating the operator's own cache.
  const _MAINS = { byPuuid: Object.create(null) };
  const _MAINS_TTL_MS = 60 * 1000;
  function _mainsFetch(puuid, onLand) {
    const key = puuid || "";
    const slot = _MAINS.byPuuid[key];
    const now  = Date.now();
    if (slot && slot.cache && (now - slot.fetchedAt) < _MAINS_TTL_MS) {
      onLand && onLand(slot.cache);
      return;
    }
    if (slot && slot.inflight) { return; }
    _MAINS.byPuuid[key] = { ...(slot || {}), inflight: true };
    const url = "/api/mains" + (puuid ? `?puuid=${encodeURIComponent(puuid)}` : "");
    fetch(url, { cache: "no-store" })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        const champs = (data && Array.isArray(data.main_champs)) ? data.main_champs : [];
        _MAINS.byPuuid[key] = { cache: { champions: champs }, fetchedAt: Date.now(), inflight: false };
        try { onLand && onLand(_MAINS.byPuuid[key].cache); } catch (_) {}
      })
      .catch(() => {
        _MAINS.byPuuid[key] = { cache: null, fetchedAt: now, inflight: false };
      });
  }
  function _renderMains() {
    // s209: bail until the champion-name index has loaded - otherwise
    // `_resolveChampId(c.name)` returns null and the fallback URL
    // `/icons/champions/<name>.png` 404s for any name with spaces
    // ("Lee Sin", "Master Yi", "Miss Fortune"). The CHAMPS-ready event
    // listener (wired below) re-fires this renderer once the index
    // lands; the 2s state envelope also retries by default.
    if (!CHAMPS.ready) return;
    const lcu = (state.latest && state.latest.lcu) || {};
    const tab = _mainsTabState();
    // Tab visual state
    const tabYou   = document.getElementById("lv-mc-tab-you");
    const tabParty = document.getElementById("lv-mc-tab-party");
    if (tabYou && tabParty) {
      tabYou.classList.toggle("is-selected",   tab === "you");
      tabYou.classList.toggle("is-deselected", tab !== "you");
      tabYou.setAttribute("aria-selected",     tab === "you" ? "true" : "false");
      tabParty.classList.toggle("is-selected",   tab === "party");
      tabParty.classList.toggle("is-deselected", tab !== "party");
      tabParty.setAttribute("aria-selected",     tab === "party" ? "true" : "false");
    }
    if (tab === "you") {
      // s171: prefer server-side /api/mains (joined match_history.db +
      // LCU mastery); fall back to lcu.main_champs when sim fixtures
      // injected one.
      if (Array.isArray(lcu.main_champs) || (lcu.main_champs && lcu.main_champs.champions)) {
        const mc = Array.isArray(lcu.main_champs)
          ? { champions: lcu.main_champs } : lcu.main_champs;
        _renderMainChamps(mc);
        return;
      }
      const cached = _MAINS.byPuuid[""] && _MAINS.byPuuid[""].cache;
      if (cached) {
        _renderMainChamps(cached);
      } else {
        _renderMainChamps(null);  // shows placeholder
      }
      // Always fire a hydrate - re-renders on land.
      _mainsFetch("", (data) => { if (_mainsTabState() === "you") _renderMainChamps(data); });
    } else {
      _renderPartyMains(lcu.lobby || null);
    }
  }
  // s162 v9: shared helpers for the YOUR MAINS + PARTY MAINS rows so
  // both panels render the same Overall + Averaged structure.
  function _kdaScore(totalKda) {
    // total_kda string is "K/D/A" - return (K + A) / D as 2-decimal
    // string. D=0 returns "Perfect"; missing/malformed returns "-".
    if (!totalKda || typeof totalKda !== "string") return "-";
    const parts = totalKda.split("/").map((s) => parseFloat(s));
    if (parts.length !== 3 || parts.some((n) => isNaN(n))) return "-";
    const [k, d, a] = parts;
    if (d === 0) return "Perfect";
    return ((k + a) / d).toFixed(2);
  }
  function _splitKdaForRender(totalKda) {
    // Returns { k, d, a, raw } so the deaths can be wrapped in red.
    if (!totalKda || typeof totalKda !== "string") return null;
    const parts = totalKda.split("/");
    if (parts.length !== 3) return null;
    return { k: parts[0], d: parts[1], a: parts[2], raw: totalKda };
  }
  function _mcOverallHtml(ov) {
    const wins = ov.wins | 0;
    const losses = ov.losses | 0;
    const totalKda = ov.total_kda || "-";
    const split = _splitKdaForRender(totalKda);
    const kdaLine = split
      ? `${split.k}/<span class="lv-mc-deaths">${split.d}</span>/${split.a}`
      : (totalKda || "-");
    const kdaScore = _kdaScore(totalKda);
    // s162 v10: 2-col × 2-row grid layout per operator:
    //   [N Games]   [K/D/A - D in red]
    //   [W - L]     [N.NN KDA]
    return (
      '<span class="lv-mc-overall">' +
        _mcGamesCellHtml(ov) +
        '<span class="lv-mc-total-kda">' + kdaLine + '</span>' +
        '<span class="lv-mc-wl">' +
          '<span class="lv-mc-w">' + wins + 'W</span>' +
          ' - ' +
          '<span class="lv-mc-l">' + losses + 'L</span>' +
        '</span>' +
        '<span class="lv-mc-kda-score">' + kdaScore + ' KDA</span>' +
      '</span>'
    );
  }
  function _mcGamesCellHtml(ov) {
    // s162 v9: games count = sum of all PVP modes (rift + aram + arena).
    // Falls back to ov.games when no per-mode breakdown is wired yet.
    // Tooltip shows a 3×3 mode breakdown (titles / counts / WR%).
    const modes = ov.modes || null;
    let total = ov.games | 0;
    if (modes) {
      total = ((modes.rift && modes.rift.games | 0) || 0) +
              ((modes.aram && modes.aram.games | 0) || 0) +
              ((modes.arena && modes.arena.games | 0) || 0);
    }
    if (!total) {
      return '<span class="lv-mc-games">-</span>';
    }
    if (!modes) {
      return '<span class="lv-mc-games">' + total + ' Games</span>';
    }
    const cell = (g, w) => {
      const games = g | 0;
      const wins = w | 0;
      const wr = games > 0 ? Math.round((wins / games) * 100) + "%" : "-";
      return { games, wr };
    };
    const r = cell((modes.rift && modes.rift.games)  || 0, (modes.rift && modes.rift.wins)  || 0);
    const a = cell((modes.aram && modes.aram.games)  || 0, (modes.aram && modes.aram.wins)  || 0);
    const x = cell((modes.arena && modes.arena.games)|| 0, (modes.arena && modes.arena.wins)|| 0);
    const tip =
      '<div class="lv-mc-games-tip">' +
        '<div class="lv-mc-games-tip-row lv-mc-games-tip-head">' +
          '<span>RIFT</span><span>ARAM</span><span>ARENA</span>' +
        '</div>' +
        '<div class="lv-mc-games-tip-row">' +
          '<span>' + r.games + '</span>' +
          '<span>' + a.games + '</span>' +
          '<span>' + x.games + '</span>' +
        '</div>' +
        '<div class="lv-mc-games-tip-row lv-mc-games-tip-wr">' +
          '<span>' + r.wr + '</span>' +
          '<span>' + a.wr + '</span>' +
          '<span>' + x.wr + '</span>' +
        '</div>' +
      '</div>';
    // Encode HTML for the data-tt-html attribute. The tooltip renderer
    // uses innerHTML when this attr is set; keep the markup self-contained.
    const safeTip = tip.replace(/"/g, "&quot;");
    return '<span class="lv-mc-games" data-tt-html="' + safeTip + '">' + total + ' Games</span>';
  }
  // s162 v10: 5-tier KP% color bands. Numbers reflect what aggregator B /
  // aggregator A / aggregator D consensus on what's a "carry-engaged" vs
  // "passive" kill-participation rate at solo-queue ranked play.
  //   ≥70%  S - elite; almost always a carry/jungler stat
  //   60-69 A - strong; reliable on objectives + skirmishes
  //   50-59 B - average for laners
  //   40-49 C - fades; missing skirmishes / over-farm
  //   <40   D - passive; rarely shows up to fights
  function _kpTierClass(kp) {
    if (kp == null || isNaN(kp)) return "";
    if (kp >= 70) return "lv-mc-kp-s";
    if (kp >= 60) return "lv-mc-kp-a";
    if (kp >= 50) return "lv-mc-kp-b";
    if (kp >= 40) return "lv-mc-kp-c";
    return "lv-mc-kp-d";
  }
  // s162 v17: AVG 5 grade tier classes - letter color coding for the
  // 5-match rating average. Same neo-fintech palette as the KP bands
  // but tighter: S = gold (top), A = good (great), B = info (good),
  // C = clock (average), D = bad (poor). Drives a single .lv-mc-avg5-{cls}
  // class on the bold letter so the label "AVG 5" stays neutral.
  function _avg5RankClass(grade) {
    const g = String(grade || "").trim().toUpperCase();
    if (g === "S") return "lv-mc-avg5-s";
    if (g === "A") return "lv-mc-avg5-a";
    if (g === "B") return "lv-mc-avg5-b";
    if (g === "C") return "lv-mc-avg5-c";
    if (g === "D") return "lv-mc-avg5-d";
    return "";
  }
  function _mcAveragedHtml(av) {
    const kp     = (av.kp     != null) ? Math.round(Number(av.kp)) : null;
    const cs     = (av.cs     != null) ? av.cs : "-";
    const vis    = (av.vision != null) ? av.vision : "-";
    const dmg    = (av.dmg    != null) ? _fmtK(av.dmg) : "-";
    const cspm   = (av.cs_per_min != null) ? Number(av.cs_per_min).toFixed(1) : "-";
    const kpVal  = kp != null ? kp + "%" : "-";
    const kpCls  = _kpTierClass(kp);
    const avg5   = av.avg5 || "-";
    const avg5Cls = _avg5RankClass(avg5);
    // s162 v17: 3-col × 2-row grid (Gold dropped, Vision moved up):
    //   [KP%]    [Vision]  [CS]
    //   [AVG 5]  [Dmg]     [CS/m]
    // AVG 5 is the operator's last-5-match performance grade (S→D)
    // for that champion, derived from rewind_history.db. Letter is
    // bold + color-coded; "AVG 5" label sits below in the standard
    // sub-label treatment.
    return (
      '<span class="lv-mc-averaged">' +
        '<span class="lv-mc-avg-cell">' +
          '<span class="lv-mc-avg-val ' + kpCls + '">' + kpVal + '</span>' +
          '<span class="lv-mc-avg-lbl">KP%</span>' +
        '</span>' +
        '<span class="lv-mc-avg-cell">' +
          '<span class="lv-mc-avg-val">' + vis + '</span>' +
          '<span class="lv-mc-avg-lbl">Vision</span>' +
        '</span>' +
        '<span class="lv-mc-avg-cell">' +
          '<span class="lv-mc-avg-val">' + cs + '</span>' +
          '<span class="lv-mc-avg-lbl">CS</span>' +
        '</span>' +
        '<span class="lv-mc-avg-cell">' +
          '<span class="lv-mc-avg-val lv-mc-avg5-letter ' + avg5Cls + '">' + avg5 + '</span>' +
          '<span class="lv-mc-avg-lbl">AVG 5</span>' +
        '</span>' +
        '<span class="lv-mc-avg-cell">' +
          '<span class="lv-mc-avg-val">' + dmg + '</span>' +
          '<span class="lv-mc-avg-lbl">Dmg</span>' +
        '</span>' +
        '<span class="lv-mc-avg-cell">' +
          '<span class="lv-mc-avg-val">' + cspm + '</span>' +
          '<span class="lv-mc-avg-lbl">CS/m</span>' +
        '</span>' +
      '</span>'
    );
  }
  function _renderMainChamps(mc) {
    const list = document.getElementById("lv-mainchamps-list");
    if (!list) return;
    if (!mc || !Array.isArray(mc.champions) || !mc.champions.length) {
      list.innerHTML = '<li class="home-empty">main champions populate when LCU mastery data is wired</li>';
      return;
    }
    const champs = mc.champions.slice(0, 4);
    const selfName = _selfShortName() || "";
    list.innerHTML = "";
    champs.forEach((c, i) => {
      const rank = i + 1;
      const champKey = _resolveChampId(c.name) || c.name || "";
      const iconUrl = c.icon || ("/icons/champions/" + champKey + ".png");
      const lm = c.last_match || {};
      const result = (lm.result || "").trim();
      const resultLow = result.toLowerCase();
      const ov = c.overall || {};
      const wins  = ov.wins  | 0;
      const losses = ov.losses | 0;
      const av = c.averaged || {};
      const overallHtml  = _mcOverallHtml(ov);
      const averagedHtml = _mcAveragedHtml(av);
      const li = document.createElement("li");
      li.className = "lv-mc-row";
      li.dataset.rank = String(rank);
      li.dataset.colorIdx = "0";   // s162 v5: YOUR MAINS always uses self (lavender)
      li.innerHTML = (
        '<span class="lv-mc-champ">' +
          '<span class="lv-mc-icon">' +
            '<img src="' + iconUrl + '" alt="' + (c.name || "") + '" ' +
              'onerror="this.style.display=\'none\'" />' +
          '</span>' +
          '<button type="button" class="lv-mc-copy" data-copy-rank="' + rank + '" ' +
                  'title="Copy summary for League chat" aria-label="Copy">' + _LV_ICON_COPY + '</button>' +
        '</span>' +
        '<span class="lv-mc-mastery">' +
          '<span class="lv-mc-summoner-name">' + (selfName || "-") + '</span>' +
          '<b class="lv-mc-mastery-level">Mastery ' + (c.mastery_level != null ? c.mastery_level : "-") + '</b>' +
          '<span class="lv-mc-mastery-points">' + _fmtMasteryPoints(c.mastery_points) + '</span>' +
        '</span>' +
        '<span class="lv-mc-recent">' +
          '<span class="lv-mc-result lv-mc-result-' + resultLow + '">' + (result || "-") + '</span>' +
          '<span class="lv-mc-kda">' + (lm.kda || "-") + '</span>' +
        '</span>' +
        overallHtml +
        averagedHtml
      );
      list.appendChild(li);
    });
    // Wire copy buttons (lazy - re-attached on every render)
    list.querySelectorAll(".lv-mc-copy").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const rank = parseInt(btn.dataset.copyRank, 10);
        const c = champs[rank - 1];
        if (!c) return;
        const ov = c.overall || {};
        const games = ov.games | 0;
        const wins  = ov.wins  | 0;
        const wr = (games > 0) ? Math.round((wins / games) * 100) : null;
        const points = _fmtMasteryPoints(c.mastery_points);
        // s162 v5 format: "Summoner - Champion - Mastery N : ## K points · ## Games All-Time · ##% WR"
        const txt = `${selfName || "-"} - ${c.name} - Mastery ${c.mastery_level || "?"} : ${points} · ${games} Games All-Time${wr != null ? " · " + wr + "% WR" : ""}`;
        try {
          navigator.clipboard.writeText(txt);
          btn.classList.add("is-copied");
          setTimeout(() => btn.classList.remove("is-copied"), 1200);
        } catch (_) { /* ignore - older browsers without clipboard API */ }
      });
    });
  }
  function _rankClass(tier) {
    return "lv-rank-" + String(tier || "unranked").toLowerCase().replace(/\s+/g, "");
  }
  // s162 v12: role shorthand normalizer. Operator standard:
  //   TOP / MID / BOT / JNG / SUP / FILL
  // Real LCU data uses TOP/MIDDLE/BOTTOM/JUNGLE/UTILITY/FILL; older
  // fixtures used JGL / SUPP. This collapses every variant to the
  // 3-letter operator label.
  function _roleShort(role) {
    if (!role) return "-";
    const r = String(role).toUpperCase();
    if (r === "JUNGLE" || r === "JGL" || r === "JG" || r === "JUNGLER" || r === "JNG") return "JNG";
    if (r === "UTILITY" || r === "SUPPORT" || r === "SUPP" || r === "SUP") return "SUP";
    if (r === "MIDDLE" || r === "MID") return "MID";
    if (r === "BOTTOM" || r === "ADC" || r === "BOT") return "BOT";
    return r;
  }
  function _fullPartyMember(m) {
    return m.riot_id || (m.game_name && m.tag_line ? `${m.game_name}#${m.tag_line}` : (m.summoner_name || "Unknown"));
  }
  function _resolvePartyMember(m) {
    // s162 v4: party panel display drops the #tag - operator wants just
    // the game name. Copy actions still write the full riot_id via
    // _fullPartyMember.
    return _fullPartyMember(m).split("#")[0];
  }
  function _selfShortName() {
    const lcu = (state.latest && state.latest.lcu) || {};
    const members = (lcu.lobby && lcu.lobby.members) || [];
    const self = members.find((m) => m.is_self);
    if (!self) return "";
    return _fullPartyMember(self).split("#")[0];
  }
  function _partyOtherShortName(idx) {
    // idx 0 = first non-self member, etc.
    const lcu = (state.latest && state.latest.lcu) || {};
    const members = (lcu.lobby && lcu.lobby.members) || [];
    const others = members.filter((m) => !m.is_self);
    const m = others[idx];
    if (!m) return "";
    return _fullPartyMember(m).split("#")[0];
  }
  // s162 v4: position the relocated NORMAL DRAFT + PARTY titles in the
  // section-head row so they sit EXACTLY above the centers of their
  // respective panels. CSS calc() math drifts when the section-head's
  // measured width differs from the lobby-view-grid's measured width
  // (browser rounding, scrollbar reservations, etc.) - so anchor to
  // the actual rendered DOMRects.
  // s162 v4: cross-panel selection sync - clicking a Party row OR a
  // PARTY MAINS card highlights both with white border. Document click
  // outside clears.
  function _selectPartyMember(idx) {
    document.querySelectorAll(".lobby-member-row.is-selected, .lv-mc-row.is-selected")
      .forEach((el) => el.classList.remove("is-selected"));
    if (idx == null) return;
    document.querySelectorAll(`.lobby-member-row[data-member-idx="${idx}"]`)
      .forEach((el) => el.classList.add("is-selected"));
    document.querySelectorAll(`.lv-mc-row[data-member-idx="${idx}"]`)
      .forEach((el) => el.classList.add("is-selected"));
  }
  if (typeof document !== "undefined") {
    document.addEventListener("click", () => _selectPartyMember(null));
  }
  function _positionLobbyTitles() {
    const head = document.querySelector(".lv-section-head-lobby");
    const queue = document.querySelector(".lobby-view-card-queue");
    const party = document.querySelector(".lobby-view-card-party");
    const queueT = document.getElementById("lv-queue-name");
    const partyT = document.querySelector(".lv-section-party-title");
    if (!head || !queue || !party || !queueT || !partyT) return;
    const headRect = head.getBoundingClientRect();
    if (headRect.width <= 0) return;  // not rendered yet
    const queueRect = queue.getBoundingClientRect();
    const partyRect = party.getBoundingClientRect();
    queueT.style.left  = (queueRect.left - headRect.left) + "px";
    queueT.style.right = "auto";
    queueT.style.width = queueRect.width + "px";
    partyT.style.left  = (partyRect.left - headRect.left) + "px";
    partyT.style.right = "auto";
    partyT.style.width = partyRect.width + "px";
  }
  if (typeof window !== "undefined") {
    window.addEventListener("resize", _positionLobbyTitles);
  }

  // s162 v13: SR draft party caps at 5 members. The PARTY panel
  // always renders 5 row slots - filled slots show real members,
  // unfilled slots show dashed placeholder rows. When a member
  // joins or leaves the party, the LCU agent re-pushes the lobby
  // envelope; this renderer auto-populates / depopulates accordingly.
  const PARTY_MAX_SLOTS = 5;
  function _renderPartyMembers(lobby) {
    const ul  = document.getElementById("lv-members-list");
    const members = (lobby && lobby.members) || [];
    const iAmLeader = !!(lobby && lobby.is_leader);
    if (!ul) return;
    if (!members.length) {
      ul.innerHTML = '<li class="home-empty">no members visible - Game-PC LCU agent needs to forward lcu.lobby.members[]</li>';
      return;
    }
    const isSolo = members.length === 1;
    // s162 v10: which party members are in the operator's curated
    // Top 8? Those rows get .is-top8-mate so their green hue mirrors
    // the matching Top 8 row.
    const top8List = _top8Load();
    const top8Keys = new Set();
    top8List.forEach((e) => {
      if (e.riot_id) top8Keys.add(e.riot_id);
      if (e.summoner_name) top8Keys.add(e.summoner_name);
    });
    // s162 v15: Primary-lane conflict detection - pre-pass before the
    // render loop. For each pair of members (incl. self) where their
    // resolved Primary == another's Primary AND it's not FILL/UNSELECTED,
    // mark BOTH as conflicting. Self-involvement → 'self' (red); two
    // other members conflicting (no self) → 'other' (orange).
    const conflictMap = new Map();
    let selfHasConflict = false;
    {
      // Build a list of {key, primary, isSelf} for every party member.
      const probe = [];
      members.forEach((m) => {
        const key = m.riot_id || m.summoner_name || ("idx-" + probe.length);
        const primary = m.is_self
          ? _LV.prefPrimary
          : ((m.position_preferences || m.positionPreferences || {}).first ||
             (m.position_preferences || m.positionPreferences || {}).primary || null);
        probe.push({ key, primary, isSelf: !!m.is_self });
      });
      for (let i = 0; i < probe.length; i++) {
        for (let j = i + 1; j < probe.length; j++) {
          const a = probe[i], b = probe[j];
          if (!a.primary || !b.primary) continue;
          if (a.primary === "FILL" || a.primary === "UNSELECTED") continue;
          if (a.primary !== b.primary) continue;
          const involvesSelf = a.isSelf || b.isSelf;
          const kind = involvesSelf ? "self" : "other";
          // Self always wins over other for the same key.
          const upgrade = (cur, next) => (cur === "self" || next === "self") ? "self" : (cur || next);
          conflictMap.set(a.key, upgrade(conflictMap.get(a.key), kind));
          conflictMap.set(b.key, upgrade(conflictMap.get(b.key), kind));
          if (involvesSelf) selfHasConflict = true;
        }
      }
    }
    // Surface the self-conflict state on the QUEUE Primary button so
    // the operator sees both ends of the conflict in one glance.
    const primaryBtn = document.getElementById("lv-lane-primary");
    if (primaryBtn) {
      primaryBtn.classList.toggle("is-conflict", selfHasConflict);
    }
    ul.innerHTML = "";
    let otherIdx = 0;  // index among non-self members; cross-refs PARTY MAINS card idx
    // s162 v13: iterate up to PARTY_MAX_SLOTS, rendering placeholders
    // for slots beyond members.length. Real-member branch unchanged.
    for (let slot = 0; slot < PARTY_MAX_SLOTS; slot++) {
      const m = members[slot];
      if (!m) {
        const phLi = document.createElement("li");
        phLi.className = "lobby-member-row is-placeholder";
        phLi.innerHTML = (
          '<span class="lv-party-section-name"><span class="lv-party-empty">-</span></span>' +
          '<span class="lv-party-section-prefs"></span>' +
          '<span class="lv-party-section-peak"></span>' +
          '<span class="lv-party-section-rank"></span>' +
          '<span class="lv-party-section-topchamps"></span>' +
          '<span class="lobby-member-actions">' +
            '<span class="lv-member-action-spacer" aria-hidden="true"></span>' +
            '<span class="lv-member-action-spacer" aria-hidden="true"></span>' +
            '<span class="lv-member-action-spacer" aria-hidden="true"></span>' +
            '<span class="lv-member-action-spacer" aria-hidden="true"></span>' +
          '</span>'
        );
        ul.appendChild(phLi);
        continue;
      }
      // Real-member branch - same logic that used to live inside the
      // members.forEach((m) => { ... }) callback below.
      ((m) => {
      const li = document.createElement("li");
      const memberKey = m.riot_id || m.summoner_name;
      const isTop8Mate = !!memberKey && top8Keys.has(memberKey);
      let cls = "lobby-member-row";
      if (m.is_self) cls += " is-self";
      if (isTop8Mate)  cls += " is-top8-mate";
      li.className = cls;
      if (!m.is_self) {
        li.dataset.memberIdx = String(otherIdx);
        // s162 v5: color palette per non-self member (good/gold/teal/coral)
        li.dataset.colorIdx = String(otherIdx + 1);
        otherIdx++;
      } else {
        li.dataset.colorIdx = "0";  // self → lavender
      }
      const ign = _resolvePartyMember(m);
      // s162 v4: Section 1 is just the name. YOU pip removed; the
      // is-self row already gets a border accent. LEADER pip moved to
      // the right-side action group as a crown button.
      // s162 v10: col 2 renders the member's LCU-pulled Primary +
      // Secondary lane preferences. Updates on state push.
      // s162 v15: self row now mirrors col 2 from the QUEUE panel's
      // lane picker (_LV.prefPrimary / _LV.prefSecondary) so the self
      // row visually matches the other party rows. Updates whenever
      // _setLanePref re-renders the party panel.
      let pPrimary, pSecondary;
      if (m.is_self) {
        pPrimary   = _LV.prefPrimary;
        pSecondary = _LV.prefSecondary;
      } else {
        const prefs = m.position_preferences || m.positionPreferences || null;
        pPrimary   = prefs ? (prefs.first  || prefs.primary  || null) : null;
        pSecondary = prefs ? (prefs.second || prefs.secondary || null) : null;
      }
      // s162 v15: conflict check populated by the outer-loop pre-pass
      // (computed once per render, not per row). conflictMap keys are
      // member-keys (riot_id || summoner_name); values are 'self' (red)
      // or 'other' (orange) or null.
      const memberKeyForConflict = m.riot_id || m.summoner_name || ("idx-" + slot);
      const conflictKind = (typeof conflictMap !== "undefined") ? conflictMap.get(memberKeyForConflict) : null;
      const prefIcon = (slot, lane, isPrimary) => {
        const conflictCls = (isPrimary && conflictKind)
          ? (conflictKind === "self" ? " is-conflict-self" : " is-conflict-other")
          : "";
        if (!lane || lane === "UNSELECTED") {
          return `<span class="lv-party-pref-empty${conflictCls}" title="${slot} pref - none set" data-tt="${slot} pref - none set">-</span>`;
        }
        const url  = LANE_ICONS[lane] || "";
        const lbl  = LANE_LABELS[lane] || lane;
        return `<img class="lv-party-pref-icon${conflictCls}" src="${url}" alt="${lbl}" title="${slot}: ${lbl}" data-tt="${slot}: ${lbl}" />`;
      };
      const section1 =
        '<span class="lv-party-section-name">' +
          `<span class="lobby-member-name">${ign}</span>` +
        '</span>' +
        '<span class="lv-party-section-prefs">' +
          prefIcon("Primary", pPrimary, true) + prefIcon("Secondary", pSecondary, false) +
        '</span>';
      // Section 2: current rank / div / LP - shown in BOTH solo and
      // party 2+. Falls back to "LVL NNN : Unranked" when the member
      // has no ranked tier (s162 v10: was "Level NNN").
      let section2;
      if (m.rank && m.rank.tier) {
        const rankCls = _rankClass(m.rank.tier);
        const div = m.rank.division ? " " + m.rank.division : "";
        const lp = (m.rank.lp != null) ? ` ${m.rank.lp} LP` : "";
        section2 =
          '<span class="lv-party-section-rank">' +
            `<span class="lobby-member-pip lobby-member-pip-rank ${rankCls}">${m.rank.tier}${div}${lp}</span>` +
          '</span>';
      } else {
        const lvl = (m.summoner_level != null) ? m.summoner_level : (m.level != null ? m.level : "-");
        section2 = `<span class="lv-party-section-rank"><span class="lv-party-empty">LVL ${lvl} : Unranked</span></span>`;
      }
      // s162 v4: Section 3 - preferred role pip (was peak rank). Based
      // on match history; LCU agent + rewind_history.db will populate
      // m.preferred_role in Phase B.
      // s162 v15: self row also renders its DB/history-assessed role
      // pip (m.assessed_role || m.preferred_role for self). When the
      // user is solo we still render the pip - empty becomes "-".
      const roleVal = m.is_self
        ? (m.assessed_role || m.preferred_role || null)
        : (m.preferred_role || null);
      let section3;
      if (roleVal) {
        section3 =
          '<span class="lv-party-section-peak">' +
            `<span class="lobby-member-pip lobby-member-pip-role">${_roleShort(roleVal)}</span>` +
          '</span>';
      } else {
        section3 = '<span class="lv-party-section-peak"><span class="lv-party-empty">-</span></span>';
      }
      // s162 v6: 4 always-present action slots per row so widths line
      // up across all party rows regardless of role permissions.
      // Slots: [spacer] [copy] [promote OR crown OR spacer] [kick OR spacer].
      // Crown shares slot 3 with promote so the leader's crown sits in
      // the same column as the promote icon on every other row.
      const fullIgn = _fullPartyMember(m);
      const actions = [];
      // Slot 1 - spacer (reserved column for future left-side action)
      actions.push('<span class="lv-member-action-spacer" aria-hidden="true"></span>');
      // Slot 2 - copy (always present)
      actions.push(`<button type="button" class="lv-member-action" data-action="copy" data-ign="${fullIgn}" title="Copy username" aria-label="Copy username">${_LV_ICON_COPY}</button>`);
      // Slot 3 - leader crown OR promote OR spacer
      if (m.is_leader) {
        actions.push(`<span class="lv-member-action lv-member-leader-crown" title="Party leader" aria-label="Party leader">${_LV_ICON_CROWN}</span>`);
      } else if (!isSolo && iAmLeader && !m.is_self) {
        actions.push(`<button type="button" class="lv-member-action" data-action="promote" data-ign="${fullIgn}" title="Promote to leader" aria-label="Promote to leader">⬆</button>`);
      } else {
        actions.push('<span class="lv-member-action-spacer" aria-hidden="true"></span>');
      }
      // Slot 4 - kick / spacer
      if (!isSolo && iAmLeader && !m.is_self && !m.is_leader) {
        actions.push(`<button type="button" class="lv-member-action" data-action="kick" data-ign="${fullIgn}" title="Kick from party" aria-label="Kick">✕</button>`);
      } else {
        actions.push('<span class="lv-member-action-spacer" aria-hidden="true"></span>');
      }
      const section4 = `<span class="lobby-member-actions">${actions.join("")}</span>`;
      // s162 v5: 6-col layout - name (1) | icon-spacer (2) | role (3)
      // | rank (4) | top-2-champs-for-role (5) | actions (6).
      // s162 v7: 3 → 2 champs so the topchamps cell narrows and Role
      // + Rank columns line up vertically with the Top 8 panel.
      const champs = Array.isArray(m.top_role_champs) ? m.top_role_champs : [];
      const shortChamps = champs.slice(0, 2)
        .map((n) => String(n || "").split(/[ '&]/)[0].slice(0, 5))
        .filter(Boolean);
      const sectionTopChamps = '<span class="lv-party-section-topchamps">' +
        (shortChamps.length ? shortChamps.join(" | ") : "-") +
        '</span>';
      li.innerHTML = section1 + section3 + section2 + sectionTopChamps + section4;
      ul.appendChild(li);
      })(m);   // close v13 real-member IIFE - invokes with current m
    }
    // s162 v4: click party row → highlight matching PARTY MAINS card
    // (and the row itself). Clicks on action buttons are ignored.
    ul.querySelectorAll(".lobby-member-row[data-member-idx]").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.closest(".lv-member-action")) return;
        e.stopPropagation();
        _selectPartyMember(row.dataset.memberIdx);
      });
    });
    // Wire action clicks
    ul.querySelectorAll(".lv-member-action").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const ign = btn.dataset.ign;
        if (action === "copy") {
          try {
            navigator.clipboard.writeText(ign);
            btn.classList.add("is-copied");
            setTimeout(() => btn.classList.remove("is-copied"), 1200);
          } catch (_) { /* ignore */ }
          return;
        }
        if (action === "promote") {
          if (!window.confirm(`Promote ${ign} to leader?`)) return;
          // s171: actually push the promote (was Phase B placeholder).
          lcuCmd({ cmd: "lobby.promote_leader", riot_id: ign }).then((res) => {
            lcuPollResult(res && res.id, (r) => {
              if (r && r.ok === false) _lvQueueChangeError(`Promote ${ign}: ${r.err || "failed"}`);
            });
          });
          return;
        }
        if (action === "kick") {
          if (!window.confirm(`Kick ${ign} from party?`)) return;
          lcuCmd({ cmd: "lobby.kick_member", riot_id: ign }).then((res) => {
            lcuPollResult(res && res.id, (r) => {
              if (r && r.ok === false) _lvQueueChangeError(`Kick ${ign}: ${r.err || "failed"}`);
            });
          });
          return;
        }
      });
    });
  }
  function _renderPartyMains(lobby) {
    const list = document.getElementById("lv-mainchamps-list");
    if (!list) return;
    list.innerHTML = "";
    // s162 v4: PARTY MAINS shows up to 4 party-member cards (NOT
    // including self). When solo (party_size === 1) all 4 render as
    // 50%-opacity dashed placeholders. Phase B wires real data from
    // each member's top-1 mastery via lcu.party_mains.
    const lcu = (state.latest && state.latest.lcu) || {};
    const partyMains = Array.isArray(lcu.party_mains) ? lcu.party_mains : [];
    const partySize = (lobby && lobby.party_size) | 0;
    const useData = partySize > 1;
    for (let i = 0; i < 4; i++) {
      const c = useData ? partyMains[i] : null;
      const rank = i + 1;
      const li = document.createElement("li");
      if (c) {
        const champKey = _resolveChampId(c.name) || c.name || "";
        const iconUrl = c.icon || ("/icons/champions/" + champKey + ".png");
        const lm = c.last_match || {};
        const result = (lm.result || "").trim();
        const resultLow = result.toLowerCase();
        const ov = c.overall || {};
        const games = ov.games | 0;
        const wins  = ov.wins  | 0;
        const losses = ov.losses | 0;
        const wr = (games > 0) ? Math.round((wins / games) * 100) : null;
        const totalKda = ov.total_kda || "-";
        const av = c.averaged || {};
        li.className = "lv-mc-row";
        li.dataset.rank = String(rank);
        li.dataset.memberIdx = String(i);  // for click-to-select sync with party panel
        li.dataset.colorIdx  = String(i + 1);  // matches the party-panel non-self color
        const playerName = c.player || _partyOtherShortName(i) || "-";
        li.innerHTML = (
          '<span class="lv-mc-champ">' +
            '<span class="lv-mc-icon">' +
              `<img src="${iconUrl}" alt="${c.name || ""}" onerror="this.style.display='none'" />` +
            '</span>' +
            `<button type="button" class="lv-mc-copy" data-copy-rank="${rank}" ` +
                    'title="Copy summary for League chat" aria-label="Copy">' + _LV_ICON_COPY + '</button>' +
          '</span>' +
          '<span class="lv-mc-mastery">' +
            `<span class="lv-mc-summoner-name">${playerName}</span>` +
            `<b class="lv-mc-mastery-level">Mastery ${c.mastery_level != null ? c.mastery_level : "-"}</b>` +
            `<span class="lv-mc-mastery-points">${_fmtMasteryPoints(c.mastery_points)}</span>` +
          '</span>' +
          '<span class="lv-mc-recent">' +
            `<span class="lv-mc-result lv-mc-result-${resultLow}">${result || "-"}</span>` +
            `<span class="lv-mc-kda">${lm.kda || "-"}</span>` +
          '</span>' +
          _mcOverallHtml(ov) +
          _mcAveragedHtml(av)
        );
        // Wire copy for this party member - same format as YOUR MAINS:
        // "Summoner - Champion - Mastery N : ## K points · ## Games All-Time · ##% WR"
        const copyBtn = li.querySelector(".lv-mc-copy");
        if (copyBtn) copyBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const points = _fmtMasteryPoints(c.mastery_points);
          const txt = `${playerName || "-"} - ${c.name} - Mastery ${c.mastery_level || "?"} : ${points} · ${games} Games All-Time${wr != null ? " · " + wr + "% WR" : ""}`;
          try {
            navigator.clipboard.writeText(txt);
            copyBtn.classList.add("is-copied");
            setTimeout(() => copyBtn.classList.remove("is-copied"), 1200);
          } catch (_) { /* ignore */ }
        });
      } else {
        // No data → dashed placeholder
        li.className = "lv-mc-row is-placeholder";
        li.dataset.rank = String(rank);
        li.innerHTML = (
          '<span class="lv-mc-champ">' +
            '<span class="lv-mc-icon"></span>' +
            `<button type="button" class="lv-mc-copy" data-copy-rank="${rank}" ` +
                    'title="Copy summary for League chat" aria-label="Copy" disabled>' + _LV_ICON_COPY + '</button>' +
          '</span>' +
          '<span class="lv-mc-mastery">' +
            '<span class="lv-mc-summoner-name">-</span>' +
            '<b class="lv-mc-mastery-level">-</b>' +
            '<span class="lv-mc-mastery-points">- points</span>' +
          '</span>' +
          '<span class="lv-mc-recent">' +
            '<span class="lv-mc-result">-</span>' +
            '<span class="lv-mc-kda">-</span>' +
          '</span>' +
          '<span class="lv-mc-overall">' +
            '<span class="lv-mc-games">-</span>' +
            '<span class="lv-mc-total-kda">-</span>' +
            '<span class="lv-mc-wl">-</span>' +
            '<span class="lv-mc-kda-score">-</span>' +
          '</span>' +
          '<span class="lv-mc-averaged">' +
            '<span class="lv-mc-avg-cell"><span class="lv-mc-avg-val">-</span><span class="lv-mc-avg-lbl">KP%</span></span>' +
            '<span class="lv-mc-avg-cell"><span class="lv-mc-avg-val">-</span><span class="lv-mc-avg-lbl">Vision</span></span>' +
            '<span class="lv-mc-avg-cell"><span class="lv-mc-avg-val">-</span><span class="lv-mc-avg-lbl">CS</span></span>' +
            '<span class="lv-mc-avg-cell"><span class="lv-mc-avg-val">-</span><span class="lv-mc-avg-lbl">AVG 5</span></span>' +
            '<span class="lv-mc-avg-cell"><span class="lv-mc-avg-val">-</span><span class="lv-mc-avg-lbl">Dmg</span></span>' +
            '<span class="lv-mc-avg-cell"><span class="lv-mc-avg-val">-</span><span class="lv-mc-avg-lbl">CS/m</span></span>' +
          '</span>'
        );
      }
      list.appendChild(li);
    }
    // s162 v4: PARTY MAINS card click → cross-highlight matching party
    // row. Clicks on the copy button (if not disabled) bubble through
    // before this; we ignore action-button targets.
    list.querySelectorAll(".lv-mc-row[data-member-idx]").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest(".lv-mc-copy")) return;
        e.stopPropagation();
        _selectPartyMember(card.dataset.memberIdx);
      });
    });
  }
  function _renderLanePref(slot, pref, noLcuData) {
    const btn = document.getElementById(slot === "primary" ? "lv-lane-primary" : "lv-lane-secondary");
    if (!btn) return;
    // s162 v2: new HTML uses .lq-lane-icon / .lq-lane-empty inside the
    // shared .lq-btn-line2-icon wrapper.
    const img = btn.querySelector(".lq-lane-icon");
    const empty = btn.querySelector(".lq-lane-empty");
    btn.classList.remove("is-disabled", "is-fill-locked", "needs-pick");
    btn.dataset.pref = pref || "UNSELECTED";
    const isFillLocked = (slot === "secondary" && _LV.prefPrimary === "FILL");
    const needsPick = (slot === "secondary" && _LV.needsPick && _LV.prefPrimary !== "FILL"
                       && (!pref || pref === "UNSELECTED"));
    if (noLcuData) {
      btn.classList.add("is-disabled");
      btn.disabled = true;
    } else {
      btn.disabled = false;
    }
    if (isFillLocked) {
      btn.classList.add("is-fill-locked");
      if (img) { img.src = LANE_ICONS.FILL; img.hidden = false; }
      if (empty) empty.hidden = true;
      return;
    }
    if (needsPick) {
      btn.classList.add("needs-pick");
      if (img) img.hidden = true;
      if (empty) { empty.textContent = ""; empty.hidden = false; }
      return;
    }
    if (pref && pref !== "UNSELECTED" && LANE_ICONS[pref]) {
      if (img) { img.src = LANE_ICONS[pref]; img.alt = LANE_LABELS[pref]; img.hidden = false; }
      if (empty) empty.hidden = true;
    } else {
      if (img) img.hidden = true;
      if (empty) { empty.textContent = "-"; empty.hidden = false; }
    }
  }
  function _openLanePopup(slot) {
    const popup = document.getElementById("lv-lane-popup");
    if (!popup) return;
    _LV.activeSlot = slot;
    const cur = (slot === "primary") ? _LV.prefPrimary : _LV.prefSecondary;
    popup.querySelectorAll(".lobby-lane-popup-cell").forEach((c) => {
      c.classList.toggle("is-current", c.dataset.pref === cur);
    });
    const lbl = document.getElementById("lv-lane-popup-label");
    if (lbl) lbl.innerHTML = "&nbsp;";
    popup.classList.remove("hidden");
    popup.setAttribute("aria-hidden", "false");
  }
  function _closeLanePopup() {
    const popup = document.getElementById("lv-lane-popup");
    if (!popup) return;
    popup.classList.add("hidden");
    popup.setAttribute("aria-hidden", "true");
    _LV.activeSlot = null;
  }
  function _setLanePref(slot, pref) {
    // s162 v8: Primary and Secondary cannot share the same role. If
    // the operator picks a role for one slot that already lives in
    // the OTHER slot, swap: the other slot inherits whatever the
    // edited slot used to hold. Only applies to specific roles -
    // FILL has its own auto-mirror semantics below.
    const isSpecific = (pref && pref !== "UNSELECTED" && pref !== "FILL");
    if (slot === "primary") {
      const wasFill = (_LV.prefPrimary === "FILL");
      const oldPrimary = _LV.prefPrimary;
      if (isSpecific && _LV.prefSecondary === pref) {
        // Conflict: secondary holds the same role we're picking for
        // primary. Swap - secondary inherits the old primary value.
        _LV.prefSecondary = oldPrimary;
        _LV.prefPrimary = pref;
        _LV.needsPick = false;
      } else {
        _LV.prefPrimary = pref;
        if (wasFill && pref !== "FILL") {
          // FILL → specific role: secondary becomes "needs-pick"
          _LV.prefSecondary = "UNSELECTED";
          _LV.needsPick = true;
        } else if (pref === "FILL") {
          // Primary FILL → secondary auto-pinned to FILL
          _LV.prefSecondary = "FILL";
          _LV.needsPick = false;
        } else {
          _LV.needsPick = false;
        }
      }
    } else {
      const oldSecondary = _LV.prefSecondary;
      if (isSpecific && _LV.prefPrimary === pref) {
        // Conflict: primary holds the same role we're picking for
        // secondary. Swap - primary inherits the old secondary value.
        _LV.prefPrimary = oldSecondary;
        _LV.prefSecondary = pref;
      } else {
        _LV.prefSecondary = pref;
      }
      _LV.needsPick = false;
    }
    // s171: actually push to LCU. The local view updates optimistically
    // above; lcuPollResult surfaces errors (non-leader, not-in-lobby,
    // etc.) on the queue-error status line.
    lcuCmd({ cmd: "lobby.set_position_prefs",
             primary:   _LV.prefPrimary,
             secondary: _LV.prefSecondary }).then((res) => {
      lcuPollResult(res && res.id, (r) => {
        if (r && r.ok === false) _lvQueueChangeError("Lane prefs: " + (r.err || "failed"));
      });
    });
    _renderLanePref("primary",   _LV.prefPrimary,   false);
    _renderLanePref("secondary", _LV.prefSecondary, false);
    _closeLanePopup();
    // s162 v15: re-render the PARTY panel so the self-row mirror
    // updates AND the conflict-detection pre-pass re-runs against
    // the new self primary.
    const _lcu = (state.latest && state.latest.lcu) || {};
    if (_lcu.lobby) _renderPartyMembers(_lcu.lobby);
  }
  // Static queue-tip table - per queue_id, a list of short tips.
  // Hardcoded since they don't change per-game; feel free to extend.
  const LV_QUEUE_TIPS = {
    450:  ["Bench-swap is instant via the LCU API (5s client cooldown bypassed).",
           "Snowball + Flash is the standard summoner combo.",
           "ARAM Mayhem? Coach treats KIWI mode as ARAM - same loadouts apply."],
    2400: ["ARAM Mayhem rolls 2-3 champions per slot - pick from the champ-select view.",
           "Augments roll mid-game; the panel surfaces them in the header pill.",
           "Score 1-100 for a win, not 0 deaths - fight more often."],
    400:  ["Normal Draft - 6 bans per side, hover before lock.",
           "Counterpick last-pick role if possible."],
    420:  ["Ranked Solo - match decides LP. Don't dodge unless griefed.",
           "Ban on what enemy team comp / role threats."],
    440:  ["Ranked Flex - premade up to 5; matchmaking pools differ from solo."],
    1750: ["Arena - 6 teams of 3. Pick a synergy trio.",
           "Anvil decisions matter more than build path. Read the augment."],
  };
  // s162 v2: status text removed from the lobby card per operator. Stub
  // s209: re-render mains when CHAMPS index loads (first-paint fix for
  // names with spaces - see _renderMains CHAMPS.ready bail). Idempotent
  // when CHAMPS lands before the lobby view is mounted; the listener
  // fires once globally.
  document.addEventListener("rc:champs-ready", () => {
    if (_VIEW.current === "lobby") _renderMains();
  });
  function _lobbyViewWireOnce() {
    if (_LV.wired) return;
    _LV.wired = true;
    // Instant-paint seed: reflect the last-known auto-accept value before
    // the first state envelope arrives. state.lcu.config.auto_accept (the
    // agent CONFIG) overrides this within ~1-2s via _syncAutoAcceptFromConfig.
    try {
      const _aaSeed = localStorage.getItem("rc-lobby-auto-accept");
      if (_aaSeed === "1" || _aaSeed === "0") _LV.autoAccept = (_aaSeed === "1");
    } catch (_) {}
    // ---- Find Match ----
    // s171: surface non-leader 400s and other LCU failures inline so
    // the operator knows why "Find Match" silently no-op'd. Previously
    // the result was swallowed by the empty `(_r) => {}` callback.
    const find = document.getElementById("lv-find-match");
    if (find) find.addEventListener("click", () => {
      if (find.disabled) return;
      find.disabled = true;
      lcuCmd({ cmd: "start_matchmaking" }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          if (r && r.ok === false) _lvQueueChangeError("Find Match: " + (r.err || "failed"));
        });
      });
      setTimeout(() => { find.disabled = false; }, 1500);
    });
    // ---- Cancel Queue ----
    const cancel = document.getElementById("lv-cancel-match");
    if (cancel) cancel.addEventListener("click", () => {
      if (cancel.disabled) return;
      lcuCmd({ cmd: "cancel_matchmaking" }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          if (r && r.ok === false) _lvQueueChangeError("Cancel: " + (r.err || "failed"));
        });
      });
    });
    // ---- Legacy hidden queue switcher (preserved; new dropdown is
    // .lq-mode-trigger / .lq-mode-menu below). ----
    const qsel = document.getElementById("lv-queue-select");
    if (qsel) qsel.addEventListener("change", () => {
      const qid = parseInt(qsel.value, 10);
      if (!qid) return;
      lcuCmd({ cmd: "change_queue_type", queue_id: qid }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          if (r && r.ok === false) _lvQueueChangeError(r.err);
        });
      });
      qsel.value = "";
    });
    // ---- Party Open/Closed toggle (s171 wired; s209 inflight-guarded) ----
    // Pushes lobby.set_party_type to LCU. Optimistically updates the
    // toggle visual + locks `_LV.partyToggleInflight` so the 2s state
    // envelope can't clobber the click with stale LCU truth. Reverts
    // only on explicit LCU failure - sim/transient "no_queue_id" keeps
    // the optimistic state (acceptable: nothing actually pushed).
    const partyToggle = document.getElementById("lv-party-toggle");
    if (partyToggle) partyToggle.addEventListener("click", () => {
      if (partyToggle.disabled) return;
      const nextOpen = !_LV.partyOpen;
      _LV.partyOpen = nextOpen;
      // Persist the preference (shared with the Settings "Party default"
      // select via rc-lobby-party-default - last-write-wins, survives
      // reload). Preference only: not auto-applied on lobby entry.
      try { localStorage.setItem("rc-lobby-party-default", nextOpen ? "open" : "closed"); } catch (_) {}
      _LV.partyToggleInflight = true;
      const stateEl = document.getElementById("lv-party-toggle-state");
      partyToggle.classList.remove("is-open", "is-closed");
      partyToggle.classList.add(nextOpen ? "is-open" : "is-closed");
      if (stateEl) stateEl.textContent = nextOpen ? "Open" : "Closed";
      lcuCmd({ cmd: "lobby.set_party_type",
               party_type: nextOpen ? "open" : "closed" }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          _LV.partyToggleInflight = false;
          // Only revert on a real LCU error. "no_queue_id" means the
          // agent was unreachable (sim mode or LCU offline) - keep the
          // operator's optimistic state since nothing was actually
          // applied either way.
          if (r && r.ok === false && r.err !== "no_queue_id") {
            _LV.partyOpen = !nextOpen;
            partyToggle.classList.remove("is-open", "is-closed");
            partyToggle.classList.add(!nextOpen ? "is-open" : "is-closed");
            if (stateEl) stateEl.textContent = !nextOpen ? "Open" : "Closed";
            _lvQueueChangeError("Party type: " + (r.err || "failed"));
          }
        });
      });
    });
    // ---- Auto Accept toggle (s171: wired) ----
    // Pushes set_config to the LCU agent so the agent's CONFIG flag
    // mirrors the dashboard. Previously the agent defaulted to True
    // and the dashboard toggle was visual-only, so auto-accept was
    // silently always on regardless of the UI state.
    const autoAccept = document.getElementById("lv-auto-accept");
    if (autoAccept) autoAccept.addEventListener("click", () => {
      if (autoAccept.disabled) return;
      _setAutoAccept(!_LV.autoAccept);
    });
    // ---- Lane pref slot clicks → open popup ----
    const primary   = document.getElementById("lv-lane-primary");
    const secondary = document.getElementById("lv-lane-secondary");
    if (primary) primary.addEventListener("click", (e) => {
      e.stopPropagation();
      if (primary.disabled) return;
      _openLanePopup("primary");
    });
    if (secondary) secondary.addEventListener("click", (e) => {
      e.stopPropagation();
      if (secondary.disabled) return;
      if (_LV.prefPrimary === "FILL") return;
      _openLanePopup("secondary");
    });
    const popup = document.getElementById("lv-lane-popup");
    if (popup) {
      const lbl = document.getElementById("lv-lane-popup-label");
      popup.querySelectorAll(".lobby-lane-popup-cell").forEach((cell) => {
        cell.addEventListener("mouseenter", () => {
          if (lbl) lbl.textContent = LANE_LABELS[cell.dataset.pref] || "-";
        });
        cell.addEventListener("mouseleave", () => {
          if (lbl) lbl.innerHTML = "&nbsp;";
        });
        cell.addEventListener("click", (e) => {
          e.stopPropagation();
          if (!_LV.activeSlot) return;
          _setLanePref(_LV.activeSlot, cell.dataset.pref);
        });
      });
      popup.addEventListener("click", (e) => e.stopPropagation());
    }
    // ---- Change Lobby Mode dropdown (Row 4) ----
    const modeTrigger = document.getElementById("lv-mode-trigger");
    const modeMenu    = document.getElementById("lv-mode-menu");
    if (modeTrigger && modeMenu) {
      modeTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = !modeMenu.classList.contains("hidden");
        if (isOpen) {
          modeMenu.classList.add("hidden");
          modeMenu.setAttribute("aria-hidden", "true");
          modeTrigger.setAttribute("aria-expanded", "false");
        } else {
          // Highlight the current queue
          const lcu = (state.latest && state.latest.lcu) || {};
          const lobby = lcu.lobby || null;
          const curQid = (lobby && lobby.queue_id) | 0;
          modeMenu.querySelectorAll(".lq-mode-item").forEach((it) => {
            it.classList.toggle("is-current", parseInt(it.dataset.qid, 10) === curQid);
          });
          modeMenu.classList.remove("hidden");
          modeMenu.setAttribute("aria-hidden", "false");
          modeTrigger.setAttribute("aria-expanded", "true");
        }
      });
      modeMenu.querySelectorAll(".lq-mode-item").forEach((item) => {
        item.addEventListener("click", (e) => {
          e.stopPropagation();
          const qid = parseInt(item.dataset.qid, 10);
          const special = item.dataset.special;
          if (special === "practice") {
            // Practice Tool: needs a different LCU command (customGameLobby
            // PRACTICETOOL). s234 (#89): surface failures via lcuPollResult
            // like the change_queue_type sibling below - the practice
            // create can fail (e.g. must leave a matchmade lobby first) and
            // the operator needs that error visible, not swallowed.
            lcuCmd({ cmd: "lobby.create_practice_tool" }).then((res) => {
              lcuPollResult(res && res.id, (r) => {
                if (r && r.ok === false)
                  _lvQueueChangeError("Practice Tool: " + (r.err || "failed"));
              });
            });
          } else if (qid > 0) {
            // s171: surface failures via lcuPollResult so non-leader
            // 400s and "already in matchmaking" rejections don't vanish.
            lcuCmd({ cmd: "change_queue_type", queue_id: qid }).then((res) => {
              lcuPollResult(res && res.id, (r) => {
                if (r && r.ok === false) _lvQueueChangeError(r.err);
              });
            });
          }
          modeMenu.classList.add("hidden");
          modeMenu.setAttribute("aria-hidden", "true");
          modeTrigger.setAttribute("aria-expanded", "false");
        });
      });
    }
    // ---- Mains tab toggle (YOUR MAINS / PARTY MAINS) ----
    const tabYou   = document.getElementById("lv-mc-tab-you");
    const tabParty = document.getElementById("lv-mc-tab-party");
    if (tabYou) tabYou.addEventListener("click", () => {
      _LV.mainsTab = "you";
      _renderMains();
    });
    if (tabParty) tabParty.addEventListener("click", () => {
      _LV.mainsTab = "party";
      _renderMains();
    });
    // ---- Document click closes any open popup/dropdown ----
    document.addEventListener("click", () => {
      if (_LV.activeSlot) _closeLanePopup();
      if (modeMenu && !modeMenu.classList.contains("hidden")) {
        modeMenu.classList.add("hidden");
        modeMenu.setAttribute("aria-hidden", "true");
        if (modeTrigger) modeTrigger.setAttribute("aria-expanded", "false");
      }
    });
  }
  function _lobbyViewRefresh() {
    const lcu = _lobbyResolveLcu();
    const lobby = lcu.lobby || null;
    const wn = document.getElementById("lv-window");
    // s162 v14: hide the sub-label entirely when the panel is healthy
    // ("live" was redundant noise next to "Pre-Game Lobby"). Show it
    // only on error/empty states so it always means something.
    if (wn) {
      if (lobby) {
        wn.textContent = "";
        wn.hidden = true;
        wn.classList.remove("is-error");
      } else {
        wn.textContent = "awaiting LCU lobby data feed";
        wn.hidden = false;
        wn.classList.add("is-error");
      }
    }

    const qName = document.getElementById("lv-queue-name");
    if (qName) qName.textContent = lobby
      ? (lobby.queue_name || ("queue " + (lobby.queue_id || "?"))).toUpperCase()
      : "-";

    // s162 controls strip - populate from LCU when forwarded; fall back
    // to defaults (party Open, prefs greyed) when no data.
    // s214 (2026-05-15): strip stays visible on every queue so
    // Accept / Party / Cancel / Find Match work in ARAM + Arena.
    // The lane-pair below is the SR-only piece, hidden separately.
    const controls = document.getElementById("lv-queue-controls");
    const qid = (lobby && lobby.queue_id) | 0;
    if (controls) controls.classList.remove("hidden");
    const lanePair = controls && controls.querySelector(".lq-lane-pair");
    if (lanePair) {
      // s214: hide lane-pair when queue id isn't actively confirmed
      // SR. Pre-data (qid===0 / awaiting LCU feed) hides them too so
      // ARAM operators don't see Primary/Secondary placeholders.
      const showLanes = qid !== 0 && SR_QUEUE_IDS.has(qid);
      lanePair.classList.toggle("hidden", !showLanes);
    }
    // Party Open / Closed - LCU exposes lobby.party_type ("open" | "closed").
    // s209: only sync the toggle visual when (a) it's our first observation
    // of the LCU state, (b) the LCU value changed externally since the last
    // tick (lobby leader toggled it elsewhere), or (c) no operator click is
    // in-flight. Without this guard the 2s refresh races the click handler
    // and reverts every toggle within a single envelope cycle.
    const partyType = (lobby && (lobby.party_type || "").toLowerCase()) || "open";
    const partyToggle = document.getElementById("lv-party-toggle");
    const partyStateEl = document.getElementById("lv-party-toggle-state");
    if (partyToggle && partyStateEl) {
      const lcuChanged = (_LV.lastLcuPartyType != null
                          && _LV.lastLcuPartyType !== partyType);
      const firstSync = (_LV.lastLcuPartyType == null);
      if (!_LV.partyToggleInflight && (firstSync || lcuChanged)) {
        _LV.partyOpen = (partyType !== "closed");
        partyToggle.classList.remove("is-open", "is-closed", "is-disabled");
        partyToggle.classList.add(_LV.partyOpen ? "is-open" : "is-closed");
        partyStateEl.textContent = _LV.partyOpen ? "Open" : "Closed";
      }
      partyToggle.disabled = false;
      _LV.lastLcuPartyType = partyType;
    }
    // s162 v2: Auto Accept toggle - LCU exposes auto-accept on
    // lobby.local_member.auto_fill_protected_for_promos / etc., or via
    // /lol-matchmaking/v1/ready-check/auto-accept. Phase A: read from
    // _LV.autoAccept (operator-toggled). Phase B: read live state.
    const autoAccept = document.getElementById("lv-auto-accept");
    const autoAcceptStateEl = document.getElementById("lv-auto-accept-state");
    if (autoAccept && autoAcceptStateEl) {
      autoAccept.classList.remove("is-on", "is-off", "is-disabled");
      autoAccept.classList.add(_LV.autoAccept ? "is-on" : "is-off");
      autoAcceptStateEl.textContent = _LV.autoAccept ? "On" : "Off";
      autoAccept.disabled = false;
    }
    // Lane prefs from LCU (when forwarded). Shape:
    //   lobby.local_member.position_preferences = {
    //     first_preference, second_preference  // "TOP"|...|"FILL"|"UNSELECTED"
    //   }
    const lm = (lobby && (lobby.local_member || lobby.localMember)) || null;
    const prefs = lm && (lm.position_preferences || lm.positionPreferences) || null;
    if (prefs) {
      _LV.prefPrimary   = (prefs.first_preference  || prefs.firstPreference  || "UNSELECTED").toUpperCase();
      _LV.prefSecondary = (prefs.second_preference || prefs.secondPreference || "UNSELECTED").toUpperCase();
      _LV.needsPick = false;
    }
    _renderLanePref("primary",   _LV.prefPrimary,   !lobby);
    _renderLanePref("secondary", _LV.prefSecondary, !lobby);

    const leaderTag = document.getElementById("lv-leader-tag");
    if (leaderTag) leaderTag.hidden = !(lobby && lobby.is_leader);
    const qsel = document.getElementById("lv-queue-select");
    if (qsel) qsel.hidden = !(lobby && lobby.is_leader);

    // s162 v2: Find Match always visible (2-line "Find" / "Match"),
    // gold pulse via .is-searching class when LCU reports searching.
    // Cancel Queue always visible too, disabled until searching. Both
    // buttons keep their static labels - visual state communicates
    // status (no inline status text).
    const find = document.getElementById("lv-find-match");
    const cancel = document.getElementById("lv-cancel-match");
    const searching = lobby && lobby.search_state === "Searching";
    const found = lobby && (lobby.search_state === "MatchFound" || lcu.phase === "ReadyCheck");
    if (find) {
      const enabled = !searching && !found;
      find.disabled = !enabled;
      find.classList.toggle("is-searching", !!searching);
    }
    if (cancel) {
      cancel.disabled = !searching;
    }

    // s162 v4: Party panel render. Solo (1 member) collapses YOU/LEADER
    // pips and shows just the IGN + copy. Party 2+ shows full IGN +
    // YOU/LEADER pips + rank / peak / most-played role + per-row
    // action pips (copy / promote / kick) right-aligned.
    _renderPartyMembers(lobby);

    // s162 v4: Your Mains / Party Mains panel - tab-switched.
    _renderMains();

    // s162 v5: panel repurposed to "My Top 8" (operator-curated short
    // list with localStorage persistence). The Recently-Played render
    // logic (_renderFriendsRecent) is preserved below for reuse on a
    // future panel - just no longer invoked here.
    _renderTop8();
    _top8WireSearchOnce();
    // s162 v4: re-center NORMAL DRAFT + PARTY titles after layout settles.
    requestAnimationFrame(_positionLobbyTitles);
  }
  // ---- s162 v5 / s171 reworked: My Top 8 panel ----
  // s171: persistence moved from localStorage (origin-dependent, wiped
  // on Chrome cache-clear, drifts when hitting Legion under different
  // hostnames/IPs) to server-side at /api/top8 on Legion. The cache
  // hydrates from /api/top8 on first call; subsequent reads are sync
  // off the cache so the existing render path stays untouched. Saves
  // POST async to /api/top8 and update the cache optimistically.
  const TOP8_KEY = "rc-top8-list";
  const TOP8_MAX = 8;
  // s170 wipe: riot_ids that came from sim fixtures.
  const _TOP8_FAKE_RIOT_IDS = new Set([
    "FrenLuvr#NA1",
    "Brawler#NA1",
    "SmurfLord#PRO",
    "WardBot#SUP",
    "CarryHarder#NA1",
    "SkillIssue#TT",
    "NoobieMcGee#NEW",
    "SamplePlayer Sock#NA1",
  ]);
  // In-memory cache hydrated from /api/top8. Starts uninitialized so
  // the first _top8Load() triggers a fetch + re-render once landed.
  const _TOP8 = { cache: null, hydrating: false, hydrateP: null };
  function _top8Hydrate(onReady) {
    if (_TOP8.cache != null) { onReady && onReady(_TOP8.cache); return; }
    if (_TOP8.hydrating) {
      if (onReady) _TOP8.hydrateP.then(onReady);
      return;
    }
    _TOP8.hydrating = true;
    _TOP8.hydrateP = fetch("/api/top8", { cache: "no-store" })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        let entries = (data && Array.isArray(data.entries)) ? data.entries : [];
        // Migration: if server is empty but localStorage has entries
        // from a pre-s171 dashboard session, push them up so the
        // operator doesn't lose their Top 8 across the upgrade.
        if (entries.length === 0) {
          try {
            const raw = localStorage.getItem(TOP8_KEY);
            if (raw) {
              const arr = JSON.parse(raw);
              if (Array.isArray(arr) && arr.length) {
                entries = arr.filter((e) => {
                  const rid = e && (e.riot_id || e.summoner_name);
                  return !(rid && _TOP8_FAKE_RIOT_IDS.has(rid));
                });
                if (entries.length) _top8Persist(entries);  // fire-and-forget
              }
            }
          } catch (_) {}
        }
        _TOP8.cache = entries;
        _TOP8.hydrating = false;
        return entries;
      })
      .catch(() => {
        _TOP8.cache = [];   // server unreachable - render empty rather than loop
        _TOP8.hydrating = false;
        return [];
      });
    if (onReady) _TOP8.hydrateP.then(onReady);
  }
  function _top8Persist(list) {
    return fetch("/api/top8", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries: list }),
    })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data && Array.isArray(data.entries)) _TOP8.cache = data.entries;
        return data;
      })
      .catch(() => null);
  }
  function _top8Load() {
    // s162 v5: sim fixtures can pre-populate via lcu.top8 - fixture
    // wins so dev preview renders without polluting persisted state.
    const lcu = (state.latest && state.latest.lcu) || {};
    if (Array.isArray(lcu.top8)) return lcu.top8;
    // s171: cache-first; hydrate async on cache miss and let the next
    // _renderTop8 tick land the real list (caller fires render again
    // when the promise resolves).
    if (_TOP8.cache == null) {
      _top8Hydrate(() => { try { _renderTop8(); } catch (_) {} });
      return [];
    }
    return _TOP8.cache;
  }
  function _top8Save(list) {
    _TOP8.cache = Array.isArray(list) ? list : [];
    _top8Persist(_TOP8.cache);
    // s171 backup: also write the localStorage copy so a temporarily
    // dead /api/top8 (RC restart, etc.) still has a fallback the next
    // time the server is up + migrate-on-empty re-pushes.
    try { localStorage.setItem(TOP8_KEY, JSON.stringify(_TOP8.cache)); } catch (_) {}
  }
  function _top8FormatRank(rank) {
    if (!rank || !rank.tier) return "Unranked";
    const div = rank.division ? " " + rank.division : "";
    const lp  = rank.lp != null ? ` ${rank.lp} LP` : "";
    return `${rank.tier}${div}${lp}`;
  }
  function _renderTop8() {
    const list = _top8Load();
    const ul = document.getElementById("lv-top8-list");
    if (!ul) return;
    // s162 v5: which Top 8 entries are currently in the party?
    const lcuOuter = (state.latest && state.latest.lcu) || {};
    const partyMembers = (lcuOuter.lobby && Array.isArray(lcuOuter.lobby.members))
      ? lcuOuter.lobby.members : [];
    const partyKeys = new Set();
    partyMembers.forEach((m) => {
      if (m.riot_id) partyKeys.add(m.riot_id);
      if (m.summoner_name) partyKeys.add(m.summoner_name);
    });
    ul.innerHTML = "";
    for (let i = 0; i < TOP8_MAX; i++) {
      const entry = list[i];
      const li = document.createElement("li");
      if (entry) {
        const inParty = partyKeys.has(entry.riot_id) || partyKeys.has(entry.summoner_name);
        const isOnline = !!entry.is_online;
        // s162 v7: offline rows get a soft red tint via .is-offline.
        // is-in-party tint takes precedence - being in your party
        // implies online.
        let cls = "lv-top8-row";
        if (inParty) cls += " is-in-party";
        else if (!isOnline) cls += " is-offline";
        li.className = cls;
        li.dataset.idx = String(i);
        // s162 v10: per-member color-idx removed - single green hue
        // mirrors PARTY panel's .is-top8-mate.
        const fullId = entry.riot_id || entry.summoner_name || "-";
        const name = String(fullId).split("#")[0];
        const games = entry.games_with_me != null ? `${entry.games_with_me} G` : "-";
        const role  = _roleShort(entry.preferred_role);
        const rankTxt = _top8FormatRank(entry.rank);
        // s162 v9: extend Party-panel rank tier color coding (.lv-rank-*)
        // to the Top 8 rank cell. _rankClass() returns "lv-rank-iron"
        // etc., or "lv-rank-unranked" when no tier.
        const rankCls = _rankClass(entry.rank ? entry.rank.tier : null);
        // s162 v16: when an entry is unranked, mirror the PARTY panel's
        // empty fallback ("LVL ### : Unranked") rather than a plain
        // "Unranked" pill - gives a consistent treatment across the
        // two panels and surfaces summoner_level when LCU forwards it.
        const isUnranked = !entry.rank || !entry.rank.tier;
        let rankCellHtml;
        if (isUnranked) {
          const lvl = (entry.summoner_level != null) ? entry.summoner_level
                    : (entry.level != null ? entry.level : "-");
          rankCellHtml = `<span class="lv-top8-rank-empty">LVL ${lvl} : Unranked</span>`;
        } else {
          rankCellHtml = `<span class="lv-top8-rank-pip ${rankCls}">${rankTxt}</span>`;
        }
        const tag   = entry.user_tag || "+ tag";
        const dotCls   = isOnline ? "lv-top8-dot-on" : "lv-top8-dot-off";
        const dotTitle = isOnline ? "Online" : "Offline";
        li.innerHTML = (
          `<span class="lv-top8-cell lv-top8-name" title="${fullId}">${name}</span>` +
          `<span class="lv-top8-cell lv-top8-games">${games}</span>` +
          `<span class="lv-top8-cell lv-top8-role">${role}</span>` +
          `<span class="lv-top8-cell lv-top8-rank">${rankCellHtml}</span>` +
          `<span class="lv-top8-cell lv-top8-tag" data-action="edit-tag" data-idx="${i}" title="Click to edit tag">${tag}</span>` +
          `<span class="lv-top8-dot ${dotCls}" title="${dotTitle}"></span>` +
          `<button type="button" class="lv-member-action" data-action="invite" data-idx="${i}" title="Invite to lobby" aria-label="Invite">➕</button>` +
          '<span class="lv-top8-reorder">' +
            `<button type="button" class="lv-top8-reorder-btn" data-action="up"   data-idx="${i}" ${i === 0 ? "disabled" : ""} title="Move up" aria-label="Move up">▲</button>` +
            `<button type="button" class="lv-top8-reorder-btn" data-action="down" data-idx="${i}" ${i >= list.length - 1 ? "disabled" : ""} title="Move down" aria-label="Move down">▼</button>` +
          '</span>' +
          `<button type="button" class="lv-member-action" data-action="remove" data-idx="${i}" title="Remove from Top 8" aria-label="Remove">✕</button>`
        );
      } else {
        li.className = "lv-top8-row is-placeholder";
        li.innerHTML = (
          '<span class="lv-top8-cell">-</span>' +
          '<span class="lv-top8-cell">-</span>' +
          '<span class="lv-top8-cell">-</span>' +
          '<span class="lv-top8-cell">-</span>' +
          '<span class="lv-top8-cell">-</span>' +
          '<span class="lv-top8-dot lv-top8-dot-off" title="Empty slot"></span>' +
          '<span class="lv-top8-spacer-reorder"></span>' +
          '<span class="lv-top8-spacer-reorder"></span>' +
          '<span class="lv-top8-spacer-remove"></span>'
        );
      }
      ul.appendChild(li);
    }
    _wireTop8Actions();
  }
  function _wireTop8Actions() {
    const ul = document.getElementById("lv-top8-list");
    if (!ul) return;
    ul.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const idx = parseInt(btn.dataset.idx, 10);
        const list = _top8Load();
        if (action === "edit-tag") {
          const cur = (list[idx] && list[idx].user_tag) || "";
          const next = window.prompt(`User tag for ${list[idx]?.riot_id || "this entry"}:`, cur);
          if (next == null) return;
          list[idx].user_tag = next.trim();
          _top8Save(list);
          _renderTop8();
          return;
        }
        if (action === "remove") {
          const target = list[idx];
          if (!target) return;
          if (!window.confirm(`Remove ${target.riot_id || target.summoner_name} from your Top 8?`)) return;
          list.splice(idx, 1);
          _top8Save(list);
          _renderTop8();
          return;
        }
        if (action === "up" && idx > 0) {
          [list[idx - 1], list[idx]] = [list[idx], list[idx - 1]];
          _top8Save(list);
          _renderTop8();
          return;
        }
        if (action === "down" && idx < list.length - 1) {
          [list[idx + 1], list[idx]] = [list[idx], list[idx + 1]];
          _top8Save(list);
          _renderTop8();
          return;
        }
        if (action === "invite") {
          const target = list[idx];
          if (!target) return;
          const label = target.riot_id || target.summoner_name;
          if (!window.confirm(`Invite ${label} to lobby?`)) return;
          // s171: actually push the invite. Falls back to summoner_id
          // when the entry was added with a numeric id rather than
          // a riot_id ("Name#TAG").
          lcuCmd({ cmd: "lobby.invite_player",
                   riot_id: target.riot_id || "",
                   summoner_id: target.summoner_id || target.summonerId || 0 }).then((res) => {
            lcuPollResult(res && res.id, (r) => {
              if (r && r.ok === false) _lvQueueChangeError(`Invite ${label}: ${r.err || "failed"}`);
            });
          });
          return;
        }
      });
    });
  }
  function _top8WireSearchOnce() {
    if (window.__top8SearchWired) return;
    window.__top8SearchWired = true;
    const input = document.getElementById("lv-top8-search-input");
    const addBtn = document.getElementById("lv-top8-search-add");
    if (!input || !addBtn) return;
    function tryAdd() {
      const raw = (input.value || "").trim();
      if (!raw) return;
      const list = _top8Load();
      // Reject duplicates by riot_id / summoner_name
      const exists = list.some((e) => (e.riot_id || e.summoner_name) === raw);
      if (exists) {
        window.alert(`${raw} is already in your Top 8.`);
        return;
      }
      // 9th-add gate
      if (list.length >= TOP8_MAX) {
        const names = list.map((e, i) => `${i + 1}. ${e.riot_id || e.summoner_name}`).join("\n");
        const choice = window.prompt(
          `You need to remove someone from your Top 8, who will it be?\n\n${names}\n\nEnter the number 1-${TOP8_MAX} to remove, or cancel.`,
          ""
        );
        if (choice == null) return;
        const n = parseInt(choice, 10);
        if (!(n >= 1 && n <= TOP8_MAX)) {
          window.alert("Invalid selection. Add cancelled.");
          return;
        }
        list.splice(n - 1, 1);
      }
      // Append (oldest stays at top per add-time sort)
      list.push({
        riot_id: raw,
        summoner_name: raw.split("#")[0],
        added_at: Date.now(),
        user_tag: "",
        is_online: false,        // Phase B: pull from LCU
        games_with_me: null,
        preferred_role: null,
        rank: null,
      });
      _top8Save(list);
      input.value = "";
      _renderTop8();
    }
    addBtn.addEventListener("click", (e) => { e.stopPropagation(); tryAdd(); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") tryAdd(); });
  }
  function _renderFriendsRecent(friends) {
    const ul = document.getElementById("lv-friends-list");
    if (!ul) return;
    // s162 v4: ALWAYS render 8 slots - real entries fill from top,
    // remaining slots are 50%-opacity placeholders. Filters out anyone
    // currently in the party (by riot_id / summoner_name match) - they
    // re-appear here once they leave.
    const TARGET_SLOTS = 8;
    const lcuOuter = (state.latest && state.latest.lcu) || {};
    const partyMembers = (lcuOuter.lobby && Array.isArray(lcuOuter.lobby.members))
      ? lcuOuter.lobby.members : [];
    const partyKeys = new Set();
    partyMembers.forEach((m) => {
      if (m.riot_id) partyKeys.add(m.riot_id);
      if (m.summoner_name) partyKeys.add(m.summoner_name);
    });
    const safeFriends = Array.isArray(friends) ? friends : [];
    const online = safeFriends.filter((f) => f.is_online !== false);
    const notInParty = online.filter((f) =>
      !(f.riot_id && partyKeys.has(f.riot_id)) &&
      !(f.summoner_name && partyKeys.has(f.summoner_name))
    );
    notInParty.sort((a, b) => (b.games_with_me | 0) - (a.games_with_me | 0));
    const list = notInParty.slice(0, TARGET_SLOTS);
    ul.innerHTML = "";
    list.forEach((f) => {
      const ign  = f.riot_id || f.summoner_name || "Unknown";
      const champ = (f.last_match && f.last_match.champion) || "";
      const champKey = champ ? (_resolveChampId(champ) || champ) : "";
      const champIcon = champKey ? `/icons/champions/${champKey}.png` : "";
      const games = f.games_with_me | 0;
      const gamesLbl = games + (games === 1 ? " Game" : " Games");
      const role = (f.preferred_role || "").toUpperCase();
      // Section 5 - rank or "Level NNN : Unranked"
      let rankHtml;
      if (f.rank && f.rank.tier) {
        const rankCls = _rankClass(f.rank.tier);
        const div = f.rank.division ? " " + f.rank.division : "";
        const lp = (f.rank.lp != null) ? ` ${f.rank.lp} LP` : "";
        rankHtml = `<span class="lobby-member-pip lobby-member-pip-rank ${rankCls}">${f.rank.tier}${div}${lp}</span>`;
      } else {
        const lvl = (f.summoner_level != null) ? f.summoner_level : "-";
        rankHtml = `<span class="lv-party-empty">Level ${lvl} : Unranked</span>`;
      }
      // Section 6 - team marker [E]/[A] + KDA, with hover tooltip
      const lm = f.last_match || {};
      const team = (lm.team || "").toUpperCase();    // "ENEMY" | "ALLY"
      const result = (lm.result || "").toUpperCase(); // "WON" | "LOST"
      const teamMark = team === "ENEMY" ? "E" : (team === "ALLY" ? "A" : "-");
      const teamCls = team === "ENEMY" ? "lv-fr-team-enemy"
                    : team === "ALLY"  ? "lv-fr-team-ally" : "";
      // s162 v4: descriptive tooltip per operator spec.
      let tt = "Unknown team / unknown result";
      if (team === "ENEMY" && result === "WON")  tt = "This player was on the Enemy Team, You Won against them";
      else if (team === "ENEMY" && result === "LOST") tt = "This player was on the Enemy Team, You Lost against them";
      else if (team === "ALLY"  && result === "WON")  tt = "This player was on the Ally Team, You Won with them";
      else if (team === "ALLY"  && result === "LOST") tt = "This player was on the Ally Team, You Lost with them";
      const li = document.createElement("li");
      li.className = "lv-fr-row";
      li.innerHTML = (
        `<span class="lv-fr-name">${ign}</span>` +
        `<span class="lv-fr-icon">${champIcon ? `<img src="${champIcon}" alt="${champ}" onerror="this.style.display='none'" />` : ""}</span>` +
        `<span class="lv-fr-games">${gamesLbl}</span>` +
        `<span class="lv-fr-role">${role || "-"}</span>` +
        `<span class="lv-fr-rank">${rankHtml}</span>` +
        `<span class="lv-fr-team ${teamCls}" data-tt="${tt}">` +
          `<span class="lv-fr-team-mark">[${teamMark}]</span>` +
          `<span class="lv-fr-team-kda">${lm.kda || "-"}</span>` +
        `</span>` +
        `<button type="button" class="lv-fr-copy lv-member-action" data-action="copy" data-ign="${ign}" title="Copy summoner name" aria-label="Copy">${_LV_ICON_COPY}</button>` +
        `<button type="button" class="lv-fr-invite lv-member-action" data-action="invite" data-ign="${ign}" title="Invite to lobby" aria-label="Invite">➕</button>`
      );
      ul.appendChild(li);
    });
    // Pad to TARGET_SLOTS with 50%-opacity empty placeholders.
    const placeholders = TARGET_SLOTS - list.length;
    for (let i = 0; i < placeholders; i++) {
      const li = document.createElement("li");
      li.className = "lv-fr-row is-placeholder";
      li.innerHTML = (
        '<span class="lv-fr-name">-</span>' +
        '<span class="lv-fr-icon"></span>' +
        '<span class="lv-fr-games">-</span>' +
        '<span class="lv-fr-role">-</span>' +
        '<span class="lv-fr-rank"><span class="lv-party-empty">-</span></span>' +
        '<span class="lv-fr-team"><span class="lv-fr-team-mark">-</span></span>' +
        '<button type="button" class="lv-fr-copy lv-member-action" disabled aria-label="Copy">' + _LV_ICON_COPY + '</button>'
      );
      ul.appendChild(li);
    }
    // Wire copy buttons (only on real entries - placeholders are disabled)
    ul.querySelectorAll(".lv-fr-row:not(.is-placeholder) .lv-fr-copy").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const ign = btn.dataset.ign;
        try {
          navigator.clipboard.writeText(ign);
          btn.classList.add("is-copied");
          setTimeout(() => btn.classList.remove("is-copied"), 1200);
        } catch (_) { /* ignore */ }
      });
    });
    // Wire invite buttons. Phase A: confirm + log. Phase B will push
    // an LCU command: lcuCmd({ cmd: "lobby.invite_player", riot_id });
    ul.querySelectorAll(".lv-fr-row:not(.is-placeholder) .lv-fr-invite").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const ign = btn.dataset.ign;
        if (!window.confirm(`Invite ${ign} to lobby?`)) return;
        // s171: actually fire the invite (was Phase B placeholder).
        lcuCmd({ cmd: "lobby.invite_player", riot_id: ign }).then((res) => {
          lcuPollResult(res && res.id, (r) => {
            if (r && r.ok === false) _lvQueueChangeError(`Invite ${ign}: ${r.err || "failed"}`);
          });
        });
      });
    });
  }
  // Trigger a refresh of view-lobby on every state envelope when it's
  // the active view (so members/queue update without a manual nav).
  function _maybeRefreshLobbyView() {
    if (_VIEW.current === "lobby") _lobbyViewRefresh();
  }
  // s162 (2026-05-10): orchestration wrapper for LCU envelopes. Every
  // path that receives an lcu snapshot (SSE /api/state-stream, HTTP
  // /api/state fallback, FakeSocket lcu replay in sim mode) calls this
  // instead of handleChampSelect directly. Reason: handleChampSelect
  // lives in panels/champ_select.js where renderLobbyPanel / etc. are
  // out of scope. Calling them from there throws ReferenceError →
  // silently caught by upstream try/catch → lobby view never refreshes.
  // This wrapper runs in main.js's module scope where all the cross-
  // cutting renders ARE defined.
  function handleLcuEnvelope(lcu) {
    handleChampSelect(lcu);     // champ-select overlay + state.latest.lcu cache
    _syncAutoAcceptFromConfig(lcu);  // reflect agent CONFIG → both controls
    renderLobbyPanel(lcu);      // inline lobby overlay (home view)
    renderHomePanel(lcu);       // home-view phase chip
    _viewResolveAndApply(lcu);  // re-derive view based on new phase
    _maybeRefreshLobbyView();   // re-render view-lobby if it's the active surface
    if (_VIEW.current === "champ-select") renderChampSelectView(_csResolveLcu(lcu));  // s164
  }

  // ── Auto Accept (agent-CONFIG-backed, lobby ↔ settings synced) ──────
  // Source of truth is the Game-PC LCU agent CONFIG - it's what actually
  // accepts the ready-check - surfaced live at state.lcu.config.auto_accept
  // and written via the set_config command. The lobby Auto Accept toggle
  // and the Settings "Auto Accept" checkbox are two views of the same
  // flag, so they stay in sync bidirectionally and persist (the agent
  // persists its CONFIG). localStorage rc-lobby-auto-accept is only an
  // instant-paint mirror for the gap before the first state envelope.
  function _syncAutoAcceptUI() {
    const on = !!_LV.autoAccept;
    const lt = document.getElementById("lv-auto-accept");
    const ls = document.getElementById("lv-auto-accept-state");
    if (lt) { lt.classList.remove("is-on", "is-off"); lt.classList.add(on ? "is-on" : "is-off"); }
    if (ls) ls.textContent = on ? "On" : "Off";
    const sc = document.getElementById("set-lobby-auto-accept");
    if (sc) sc.checked = on;
  }
  function _syncAutoAcceptFromConfig(lcu) {
    try {
      const cfg = (lcu && lcu.config)
                || (state.latest && state.latest.lcu && state.latest.lcu.config)
                || {};
      if (!_LV.autoAcceptInflight && typeof cfg.auto_accept === "boolean") {
        _LV.autoAccept = cfg.auto_accept;
        try { localStorage.setItem("rc-lobby-auto-accept", cfg.auto_accept ? "1" : "0"); } catch (_) {}
      }
      _syncAutoAcceptUI();
    } catch (_) {}
  }
  function _setAutoAccept(nextOn) {
    nextOn = !!nextOn;
    _LV.autoAccept = nextOn;
    _LV.autoAcceptInflight = true;   // guard the ~1-2s envelope round-trip
    try { localStorage.setItem("rc-lobby-auto-accept", nextOn ? "1" : "0"); } catch (_) {}
    _syncAutoAcceptUI();
    try {
      Promise.resolve(lcuCmd({ cmd: "set_config", auto_accept: nextOn })).then((res) => {
        if (typeof lcuPollResult === "function") {
          lcuPollResult(res && res.id, () => { _LV.autoAcceptInflight = false; });
        } else {
          _LV.autoAcceptInflight = false;
        }
      }, () => { _LV.autoAcceptInflight = false; });
    } catch (_) { _LV.autoAcceptInflight = false; }
  }
  // Settings-page Auto Accept checkbox listener. Wired from the
  // settings-view show hook (guaranteed to run when the operator opens
  // Settings, even if they never visited the lobby view this session).
  function _settingsLobbyWireOnce() {
    if (_LV.settingsLobbyWired) return;
    _LV.settingsLobbyWired = true;
    const sc = document.getElementById("set-lobby-auto-accept");
    if (sc) sc.addEventListener("change", () => { _setAutoAccept(!!sc.checked); });
  }

  // ── Lobby overlay (2026-04-26) ──────────────────────────────────────
  // Pre-queue: shows what queue the user is sitting in + a Find Match
  // button. Hidden during ChampSelect / InProgress (champ-select view
  // takes over). Find Match is only enabled when localMember.isLeader is true
  // (LCU restriction); otherwise the button degrades to a status pill
  // showing "Awaiting party leader". Cancel Search appears when
  // search_state === "Searching".
  //
  // Expected /api/state shape (Game-PC LCU agent forwards from
  // /lol-lobby/v2/lobby):
  //   lcu.lobby = {
  //     queue_id:        int,    // 920 = ARAM Mayhem, 450 = ARAM, etc.
  //     queue_name:      str,    // "ARAM Mayhem", "Normal Draft", etc.
  //     party_size:      int,
  //     max_party_size:  int,
  //     is_leader:       bool,   // localMember.isLeader
  //     can_search:      bool,   // canStartActivity from LCU
  //     search_state:    "Idle" | "Searching" | "MatchFound"
  //   }
  const _LOBBY = { wired: false };
  function _wireLobbyButtonsOnce() {
    if (_LOBBY.wired) return;
    _LOBBY.wired = true;
    const find = document.getElementById("lobby-find-match");
    if (find) find.addEventListener("click", () => {
      if (find.disabled) return;
      find.disabled = true;
      _setLobbyStatus("starting...", "searching");
      lcuCmd({ cmd: "start_matchmaking" }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          if (r && r.ok === false) _setLobbyStatus("LCU: " + (r.err || "failed"), "err");
        });
      });
      setTimeout(() => { find.disabled = false; }, 1500);
    });
    const cancel = document.getElementById("lobby-cancel-match");
    if (cancel) cancel.addEventListener("click", () => {
      _setLobbyStatus("cancelling...", "");
      lcuCmd({ cmd: "cancel_matchmaking" }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          if (r && r.ok === false) _setLobbyStatus("LCU: " + (r.err || "failed"), "err");
        });
      });
    });
    const qsel = document.getElementById("lobby-queue-select");
    if (qsel) qsel.addEventListener("change", () => {
      const qid = parseInt(qsel.value, 10);
      if (!qid) return;
      _setLobbyStatus("changing queue...", "searching");
      lcuCmd({ cmd: "change_queue_type", queue_id: qid }).then((res) => {
        lcuPollResult(res && res.id, (r) => {
          if (r && r.ok === false) _setLobbyStatus("LCU: " + (r.err || "failed"), "err");
        });
      });
      qsel.value = "";  // reset to placeholder
    });
  }
  // Render the party member list from lcu.lobby.members[]. Each member
  // shape (forwarded by Game-PC LCU agent - pending):
  //   { puuid, summoner_name, is_self, is_leader,
  //     played_with_me_count, played_with_me_record }  // local match_history join
  function _renderLobbyMembers(members, meIsLeader) {
    const wrap = document.getElementById("lobby-members");
    const ul   = document.getElementById("lobby-members-list");
    const cnt  = document.getElementById("lobby-members-count");
    if (!wrap || !ul) return;
    if (!Array.isArray(members) || !members.length) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    if (cnt) cnt.textContent = members.length + (members.length === 1 ? " member" : " members");
    ul.innerHTML = "";
    members.forEach((m) => {
      const li = document.createElement("li");
      const cls = "lobby-member-row" +
        (m.is_self ? " is-self" : "") +
        (m.is_leader ? " is-leader" : "");
      li.className = cls;
      const tags = [];
      if (m.is_self)   tags.push('<span class="lobby-member-tag you">YOU</span>');
      if (m.is_leader) tags.push('<span class="lobby-member-tag leader">★ LEADER</span>');
      const stats = [];
      if (m.played_with_me_count > 0) {
        stats.push(`<span class="lobby-member-stat">${m.played_with_me_count}g together</span>`);
        if (m.played_with_me_record)
          stats.push(`<span class="lobby-member-stat">${m.played_with_me_record}</span>`);
      } else if (!m.is_self) {
        stats.push(`<span class="lobby-member-stat" style="color:var(--text-faint)">no shared games</span>`);
      }
      // Public-stats fallback link (no Riot key - user opens manually).
      const lookup = (m.summoner_name && !m.is_self)
        ? `<a class="lobby-member-link" href="https://aggregator-b.invalid/lol/profile/na1/${encodeURIComponent(m.summoner_name)}" target="_blank" rel="noopener">aggregator-b ↗</a>`
        : "";
      li.innerHTML =
        `<div class="lobby-member-name">${m.summoner_name || "Unknown"}${tags.join("")}</div>` +
        `<div class="lobby-member-meta">${stats.join("")}${lookup}</div>`;
      ul.appendChild(li);
    });
  }
  function _setLobbyStatus(text, cls) {
    const el = document.getElementById("lobby-status");
    if (!el) return;
    el.className = "lobby-status" + (cls ? " " + cls : "");
    el.textContent = text || "";
  }
  function renderLobbyPanel(lcu) {
    const overlay = document.getElementById("lobby-overlay");
    if (!overlay) return;
    _wireLobbyButtonsOnce();
    // s162 (2026-05-10): hard-gate on view. lobby-overlay is the inline
    // "current lobby" card anchored to the home view. After the
    // handleChampSelect fix it started firing on every lcu envelope
    // regardless of active view, leaking the overlay onto Lobby / Dev /
    // etc. (DOM placement is BEFORE view-content, so it appeared above
    // every view-section.) Restrict to home view only.
    const onHomeView = document.body.dataset.view === "home";
    if (!onHomeView) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    const lobby = lcu && lcu.lobby;
    const phase = lcu && lcu.phase;
    // Hide whenever we're past the lobby (ChampSelect / loading / in-game)
    // OR when no lobby data is available. Keep visible during early
    // game-states ("None"/"Lobby"/"Matchmaking") so the user has an
    // anchor while waiting on the queue.
    const phaseAllowsLobby = !phase
      || phase === "Lobby" || phase === "None"
      || phase === "Matchmaking" || phase === "ReadyCheck";
    if (!lobby || !phaseAllowsLobby) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");

    const qLabel = document.getElementById("lobby-queue");
    if (qLabel) qLabel.textContent = (lobby.queue_name
      || ("queue " + (lobby.queue_id || "?"))).toUpperCase();

    const party = document.getElementById("lobby-party");
    if (party) {
      const size = lobby.party_size | 0;
      const max  = lobby.max_party_size | 0;
      party.textContent = max > 0 ? `Party ${size || 1}/${max}` : "Party -";
    }
    const leaderTag = document.getElementById("lobby-leader-tag");
    if (leaderTag) leaderTag.hidden = !lobby.is_leader;
    // Change-queue dropdown: leader-only
    const qsel = document.getElementById("lobby-queue-select");
    if (qsel) qsel.hidden = !lobby.is_leader;
    // Member list (forwarded by Game-PC LCU agent in lcu.lobby.members[])
    _renderLobbyMembers(lobby.members || [], !!lobby.is_leader);

    const find = document.getElementById("lobby-find-match");
    const findLabel = document.getElementById("lobby-find-match-label");
    const cancel = document.getElementById("lobby-cancel-match");
    const searching = lobby.search_state === "Searching";
    const found     = lobby.search_state === "MatchFound" || phase === "ReadyCheck";

    if (cancel) cancel.hidden = !searching;
    if (find) {
      // Leader gating: button only fires when isLeader; otherwise it's
      // disabled and the status line explains why.
      const enabled = !!lobby.is_leader && !!lobby.can_search && !searching && !found;
      find.disabled = !enabled;
      if (findLabel) {
        findLabel.textContent = searching ? "Searching..."
          : found ? "Match Found"
          : (lobby.is_leader ? "Find Match" : "Leader-only");
      }
    }
    // Status line - reads as a single peripheral signal.
    if (searching) _setLobbyStatus("Searching...", "searching");
    else if (found) _setLobbyStatus("Match Found · accept in client", "found");
    else if (!lobby.is_leader) _setLobbyStatus("Awaiting party leader", "");
    else if (!lobby.can_search) _setLobbyStatus("Lobby not ready", "err");
    else _setLobbyStatus("Ready to queue", "");
  }


  // Pull /api/env periodically so the adaptation flag, warm indicator,
  // and latency footer stay in sync. Refresh every 15s in the background.
  function refreshEnv() {
    return fetch("/api/env")
      .then((r) => r.ok ? r.json() : {})
      .then((env) => {
        const v = env.RC_COACH_ADAPTATION || "";
        AD.flagVal.textContent = v === "1" ? "1 (coaches using hints)" : "0 (hints NOT wired)";
        AD.flagVal.className = v === "1" ? "on" : "";
        const warmInfo = env.warm_agent7 || {};
        const warmEl = document.getElementById("warm-indicator");
        if (warmEl) {
          warmEl.classList.remove("warm", "pending");
          if (warmInfo.warm) warmEl.classList.add("warm");
          const turns = warmInfo.turns || 0;
          const idle = warmInfo.idle_sec;
          warmEl.title = warmInfo.warm
            ? `warm - ${turns} turn(s), idle ${idle}s`
            : "cold (first send will warm)";
        }
        // Latency footer
        const lat = env.input_latency || {};
        if (LAT.footer) {
          if (lat.n && lat.avg_ms != null) {
            LAT.footer.textContent = `latency avg ${Math.round(lat.avg_ms)}ms · p95 ${Math.round(lat.p95_ms)}ms · n=${lat.n}`;
            LAT.footer.classList.remove("slow", "severe");
            if (lat.avg_ms >= 2500) LAT.footer.classList.add("severe");
            else if (lat.avg_ms >= 1500) LAT.footer.classList.add("slow");
          } else {
            LAT.footer.textContent = "latency -";
            LAT.footer.classList.remove("slow", "severe");
          }
        }
        // Auto-analyze status footer + adaptation panel notice
        const az = env.auto_analyze || {};
        const adaptNotice = document.getElementById("adapt-notice");
        if (ANLZ.footer) {
          ANLZ.footer.classList.remove("pending", "running");
          if (az.state === "running") {
            ANLZ.footer.classList.add("running");
            const s = Math.round(az.running_sec || 0);
            ANLZ.footer.textContent = `analyze running (${s}s)`;
          } else if (az.state === "pending") {
            ANLZ.footer.classList.add("pending");
            const r = Math.max(0, Math.round(az.fires_in_sec || 0));
            const mm = Math.floor(r / 60);
            const ss = String(r % 60).padStart(2, "0");
            ANLZ.footer.textContent = `analyze in ${mm}:${ss}`;
          } else {
            const ago = az.last_run_ago_sec;
            if (ago != null) {
              const mm = Math.floor(ago / 60);
              const ss = String(Math.round(ago % 60)).padStart(2, "0");
              const summ = az.last_summary || {};
              const champs = summ.champion_buckets;
              ANLZ.footer.textContent = champs != null
                ? `analyze idle · last ${mm}:${ss} ago · ${champs} buckets`
                : `analyze idle · last ${mm}:${ss} ago`;
            } else {
              ANLZ.footer.textContent = "analyze idle";
            }
          }
        }
        if (adaptNotice) {
          adaptNotice.classList.remove("pending", "running", "hidden");
          if (az.state === "running") {
            adaptNotice.classList.add("running");
            adaptNotice.textContent = "refreshing historic data - new match being incorporated";
          } else if (az.state === "pending") {
            const r = Math.max(0, Math.round(az.fires_in_sec || 0));
            const mm = Math.floor(r / 60);
            const ss = String(r % 60).padStart(2, "0");
            adaptNotice.classList.add("pending");
            adaptNotice.textContent = `stats 1 match stale · refreshing in ${mm}:${ss}`;
          } else {
            adaptNotice.classList.add("hidden");
          }
        }
      })
      .catch(() => { AD.flagVal.textContent = "?"; });
  }
  refreshEnv();
  setInterval(refreshEnv, 15000);

  // ── Minimap image polling ──────────────────────────────────────────
  // Polls /api/minimap-crop on a fast cadence when the dedicated Game-PC
  // minimap stream is live (5-10Hz pre-cropped JPEGs on source=minimap),
  // otherwise the supervisor falls back to crop-from-full-frame which is
  // bounded by the 2s full-frame upload cadence - pointless to poll
  // faster than that. We pick the interval based on which path served
  // the last response: JPEG = fast stream, PNG = slow re-crop.
  const MINIMAP_MODES = new Set(["sr", "aram", "brawl"]);
  const MINIMAP_INTERVAL_FAST = 250;    // 4Hz when fast stream is live
  const MINIMAP_INTERVAL_SLOW = 2000;   // 0.5Hz fallback
  let minimapTimer = null;
  let minimapInterval = MINIMAP_INTERVAL_SLOW;
  let lastMinimapMode = null;

  async function refreshMinimap() {
    if (document.hidden) return;
    if (!MINIMAP_MODES.has(state.mode)) {
      MM.imgWrap.classList.add("hidden");
      lastMinimapMode = null;
      return;
    }
    const tNow = Date.now();
    const bust = tNow - (tNow % minimapInterval);
    try {
      const resp = await fetch(`/api/minimap-crop?mode=${state.mode}&_=${bust}`);
      if (!resp.ok) {
        MM.imgWrap.classList.add("hidden");
        return;
      }
      const blob = await resp.blob();
      if (blob.type !== "image/png" && blob.type !== "image/jpeg") {
        MM.imgWrap.classList.add("hidden");
        return;
      }
      // Adapt the polling cadence to which path served us. JPEG comes
      // from the fast Game-PC minimap stream; PNG from the slow re-crop.
      const desired = (blob.type === "image/jpeg")
        ? MINIMAP_INTERVAL_FAST : MINIMAP_INTERVAL_SLOW;
      if (desired !== minimapInterval) {
        minimapInterval = desired;
        if (minimapTimer) clearInterval(minimapTimer);
        minimapTimer = setInterval(refreshMinimap, minimapInterval);
      }
      // Revoke previous blob URL to avoid leaks.
      const prev = MM.img.dataset.blobUrl;
      if (prev) { try { URL.revokeObjectURL(prev); } catch (_) {} }
      const url = URL.createObjectURL(blob);
      MM.img.dataset.blobUrl = url;
      MM.img.src = url;
      const size = (blob.size / 1024).toFixed(1);
      MM.imgCaption.textContent = `${state.mode.toUpperCase()} · ${size} KB · ${_to12(new Date())}`;
      MM.imgWrap.classList.remove("hidden", "stale");
      lastMinimapMode = state.mode;
    } catch (e) {
      MM.imgWrap.classList.add("stale");
    }
  }
  minimapTimer = setInterval(refreshMinimap, minimapInterval);
  refreshMinimap();   // fire once on load

  // ── Vision-tracker overlay on the live minimap ─────────────────────
  // Reads /api/vision-state (written by core/vision_tracker), projects
  // game coords onto the rendered minimap image, draws dots:
  //   - bright dot at current position when visible
  //   - faded ghost dot at last_seen_pos with "Xs" label when missing
  // Skips when no game is running or the minimap image isn't displayed.
  const VT_OVERLAY = el("mm-vt-overlay");
  const VT_INTERVAL_MS = 500;
  // SR / ARAM map sizes in game units (Howling Abyss is smaller than SR).
  const VT_MAP_SIZE = { CLASSIC: 14800, ARAM: 13800, KIWI: 13800,
                        URF: 14800, NEXUSBLITZ: 14800, ULTBOOK: 14800 };
  // Mirror of core/vision_tracker._SHARED_VISION_MODES - modes where the
  // whole map is visible to both teams and Live Client emits no positions.
  const VT_SHARED_VISION = new Set(["ARAM", "KIWI"]);

  async function refreshVisionOverlay() {
    if (!VT_OVERLAY) return;
    if (document.hidden) return;
    // Fetch first so the shared-vision pill can update even when the
    // minimap PNG isn't currently visible (image still loading, etc.).
    let vs;
    try {
      const r = await fetch("/api/vision-state");
      if (!r.ok) { VT_OVERLAY.style.display = "none"; return; }
      vs = await r.json();
    } catch (_) { VT_OVERLAY.style.display = "none"; return; }
    if (!vs || !vs.enemies || Object.keys(vs.enemies).length === 0) {
      VT_OVERLAY.style.display = "none";
      return;
    }
    // Shared-vision modes (ARAM/KIWI) - Live Client has no positions, so
    // the dot-overlay won't draw anything useful, but vision_tracker still
    // produces a meaningful summary (visible/dead counts, on_bridge zone).
    // Drive the MAP STATE pill from that summary.
    const sharedVision = VT_SHARED_VISION.has((vs.game_mode || "").toUpperCase());
    if (sharedVision && MM.status) {
      const sum = vs.summary || {};
      const visibleCount = sum.visible_count | 0;
      const deadCount = sum.dead_count | 0;
      const sig = `${visibleCount}|${deadCount}`;
      if (MM.status._sharedSig !== sig) {
        _renderMmStateLine(MM.status, `${visibleCount} on bridge · ${deadCount} dead`);
        MM.status._sharedSig = sig;
        MM.status.classList.remove("hidden");
        if (!MM.status.classList.contains("live")) {
          MM.status.className = "minimap-state live";
        }
      } else {
        // Same summary - refresh the timestamp so "Xs ago" stays at 0
        // instead of climbing while data is actually fresh.
        MM.status._lastT = Date.now();
      }
    }
    if (!MM.imgWrap || MM.imgWrap.classList.contains("hidden")) {
      VT_OVERLAY.style.display = "none";
      return;
    }
    // Size the canvas to the rendered <img> bounds (it's centered in the
    // wrap with margin auto and padded - getBoundingClientRect gives the
    // post-layout box we need to align to).
    const img = MM.img;
    if (!img.complete || !img.naturalWidth) {
      VT_OVERLAY.style.display = "none"; return;
    }
    const imgRect = img.getBoundingClientRect();
    const wrapRect = MM.imgWrap.getBoundingClientRect();
    const w = Math.round(imgRect.width);
    const h = Math.round(imgRect.height);
    if (w < 4 || h < 4) { VT_OVERLAY.style.display = "none"; return; }
    VT_OVERLAY.style.display = "block";
    VT_OVERLAY.style.left = (imgRect.left - wrapRect.left) + "px";
    VT_OVERLAY.style.top  = (imgRect.top  - wrapRect.top)  + "px";
    VT_OVERLAY.style.width  = w + "px";
    VT_OVERLAY.style.height = h + "px";
    if (VT_OVERLAY.width !== w)  VT_OVERLAY.width  = w;
    if (VT_OVERLAY.height !== h) VT_OVERLAY.height = h;

    const ctx = VT_OVERLAY.getContext("2d");
    ctx.clearRect(0, 0, w, h);

    const mapSize = VT_MAP_SIZE[(vs.game_mode || "").toUpperCase()] || 14800;
    function project(x, z) {
      // Game origin = bottom-left, z grows up. Canvas y grows down → flip.
      const px = (x / mapSize) * w;
      const py = h - (z / mapSize) * h;
      return [px, py];
    }

    for (const [name, e] of Object.entries(vs.enemies)) {
      if (e.is_dead) continue;
      const pos = e.last_seen_pos;
      if (!pos || typeof pos.x !== "number") continue;
      const [px, py] = project(pos.x, pos.z);

      if (e.visible) {
        // Bright current-position dot
        ctx.beginPath();
        ctx.arc(px, py, 5, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(240, 126, 139, 0.95)";
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else {
        // Ghost dot at last-seen, fading with missing time
        const missing = e.missing_for_s || 0;
        const alpha = Math.max(0.25, 1.0 - missing / 30);
        ctx.beginPath();
        ctx.arc(px, py, 5, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(240, 126, 139, ${alpha * 0.5})`;
        ctx.fill();
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = `rgba(240, 126, 139, ${alpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);
        // "Xs" missing label above the ghost dot
        ctx.font = "bold 10px Lato, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const label = `${Math.round(missing)}s`;
        ctx.lineWidth = 3;
        ctx.strokeStyle = "rgba(0, 0, 0, 0.85)";
        ctx.strokeText(label, px, py - 12);
        ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
        ctx.fillText(label, px, py - 12);
      }
    }
  }
  setInterval(refreshVisionOverlay, VT_INTERVAL_MS);
  refreshVisionOverlay();

  // Fleet Health sub-view was removed (no markup in index.html since
  // before s171). The dead poll of /api/health/peer + sig-based
  // renderFleet block lived here through 2026-05-19. Backend endpoint
  // stays - /api/health/all still rolls up peer heartbeats. If a fleet
  // view is ever re-added, restore via git history (this commit's
  // parent).

  // Input bar to /api/input (with chat history)
  const INPUT = {
    form: document.getElementById("input-form"),
    text: document.getElementById("input-text"),
    send: document.getElementById("input-send"),
    history: document.getElementById("input-history"),
    turns: document.getElementById("history-turns"),
    clearBtn: document.getElementById("history-clear"),
    warmDot: document.getElementById("warm-indicator"),
  };
  const HISTORY_CAP = 8;

  function appendTurn(userText, env, elapsedMs, isError) {
    const turn = document.createElement("div");
    turn.className = "history-turn" + (isError ? " turn-error" : "");
    if (env.sim_mode) turn.classList.add("turn-sim");
    if (env.refused)  turn.classList.add("turn-refused");
    const user = document.createElement("div");
    user.className = "turn-user";
    user.textContent = userText;
    const reply = document.createElement("div");
    reply.className = "turn-reply";
    reply.textContent = env.reply || "(empty reply)";

    // Round 42: inline proposed-changes preview for ui_feedback replies.
    let diffBlock = null;
    const changes = env.proposed_changes || [];
    if (changes.length) {
      diffBlock = document.createElement("div");
      diffBlock.className = "ui-proposal-diff";
      for (const c of changes) {
        const head = document.createElement("div");
        head.className = "ui-proposal-head";
        head.textContent =
          `${c.file}${c.summary ? "  ·  " + c.summary : ""}  ` +
          `(${(c.content || "").length} chars)`;
        const pre = document.createElement("pre");
        pre.className = "ui-proposal-snippet";
        // Show first 600 chars + last 200 so the user gets both ends.
        const full = c.content || "";
        if (full.length > 900) {
          pre.textContent = full.slice(0, 600)
            + "\n\n⋯ (" + (full.length - 800) + " chars elided) ⋯\n\n"
            + full.slice(-200);
        } else {
          pre.textContent = full;
        }
        diffBlock.appendChild(head);
        diffBlock.appendChild(pre);
      }
    }

    const meta = document.createElement("div");
    meta.className = "turn-meta";
    const parts = [];
    parts.push(`intent: ${env.intent || "-"}`);
    if (env.spawn_path) parts.push(env.spawn_path);
    if (!isError && elapsedMs != null) parts.push(`${Math.round(elapsedMs)}ms`);
    if (env.filed && env.filed.length) {
      parts.push(`filed ${env.filed.length} task${env.filed.length > 1 ? "s" : ""}`);
    }
    if (env.bypass_dev) parts.push("bypass-dev");
    for (const p of parts) {
      const chip = document.createElement("span");
      chip.className = "turn-chip";
      chip.textContent = p;
      meta.appendChild(chip);
    }
    turn.appendChild(user);
    turn.appendChild(reply);
    if (diffBlock) turn.appendChild(diffBlock);
    turn.appendChild(meta);
    INPUT.turns.appendChild(turn);
    // Cap to last N turns.
    while (INPUT.turns.children.length > HISTORY_CAP) {
      INPUT.turns.removeChild(INPUT.turns.firstChild);
    }
    INPUT.history.classList.remove("hidden");
    // Auto-scroll to bottom.
    INPUT.history.scrollTop = INPUT.history.scrollHeight;
  }

  INPUT.clearBtn.addEventListener("click", () => {
    INPUT.turns.innerHTML = "";
    INPUT.history.classList.add("hidden");
  });

  // Round 42: in-memory conversation thread used for sim-mode context.

  async function _pollTaskUntilDone(taskId, maxMs = 5000, stepMs = 400) {
    const start = performance.now();
    while (performance.now() - start < maxMs) {
      try {
        const resp = await fetch(`/api/task/${encodeURIComponent(taskId)}`);
        if (resp.ok) {
          const data = await resp.json();
          if (data.status === "completed") return { ok: true, data };
          if (data.status === "failed") return { ok: false, data };
        }
      } catch { /* ignore and retry */ }
      await new Promise(r => setTimeout(r, stepMs));
    }
    return { ok: false, timeout: true };
  }

  INPUT.form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const text = INPUT.text.value.trim();
    if (!text) return;
    INPUT.send.disabled = true;
    INPUT.warmDot.classList.add("pending");
    const t0 = performance.now();
    const body = { text };
    try {
      const resp = await fetch("/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const ms = Math.round(performance.now() - t0);
      if (!resp.ok) {
        appendTurn(text, { intent: "error", reply: `HTTP ${resp.status}`, filed: [] }, ms, true);
        return;
      }
      const env = await resp.json();
      appendTurn(text, env, ms, false);
      INPUT.text.value = "";
      INPUT.text.dispatchEvent(new Event("input"));

      refreshEnv();       // warm indicator
      refreshActivity();  // show the filed tasks in ticker

      // Round 42: auto-reload when a ui-proposal completes.
      // Without bypass the task is still deterministic auto-dispatched;
      // with bypass it's user_override=true so the frozen-file guard
      // doesn't gate it. Poll briefly and reload on success.
      const filedTasks = env.filed || [];
      const looksLikeUIProposal =
        !env.refused && filedTasks.length &&
        (env.proposed_changes && env.proposed_changes.length);
      if (looksLikeUIProposal) {
        const tid = filedTasks[0];
        const status = document.createElement("div");
        status.className = "ui-proposal-status";
        status.textContent = `applying task ${tid}...`;
        INPUT.turns.lastChild.appendChild(status);
        const out = await _pollTaskUntilDone(tid);
        if (out.ok) {
          status.textContent = "applied - reloading...";
          setTimeout(() => window.location.reload(), 400);
        } else if (out.timeout) {
          status.textContent =
            `still dispatching (task ${tid}) - refresh manually when ready`;
        } else {
          status.textContent =
            `apply failed (task ${tid}) - open it for error detail`;
          status.classList.add("ui-proposal-failed");
        }
      }
    } catch (e) {
      const ms = Math.round(performance.now() - t0);
      appendTurn(text, { intent: "error", reply: String(e), filed: [] }, ms, true);
    } finally {
      INPUT.send.disabled = false;
      INPUT.warmDot.classList.remove("pending");
    }
  });

  // ── Connection ──────────────────────────────────────────────────────
  // Audit P-audit3-l01: exponential backoff with jitter.
  const BACKOFF_MS = [1500, 3000, 6000, 12000, 30000];
  let backoffIdx = 0;
  function nextBackoff() {
    const base = BACKOFF_MS[Math.min(backoffIdx, BACKOFF_MS.length - 1)];
    backoffIdx = Math.min(backoffIdx + 1, BACKOFF_MS.length - 1);
    const jitter = (Math.random() - 0.5) * 0.5 * base;
    return Math.max(500, Math.round(base + jitter));
  }

  function connect() {
    setStatus("connecting", "pending");
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      setStatus("connected", "connected");
      backoffIdx = 0;
      logLine("ws", "connected");
    };
    ws.onclose = () => {
      setStatus("closed", "stale");
      logLine("ws", "disconnected, reconnecting", "warn");
      setTimeout(connect, nextBackoff());
    };
    ws.onerror = () => setStatus("error", "stale");
    ws.onmessage = (evt) => {
      let env;
      try { env = JSON.parse(evt.data); } catch (e) { return; }
      state.frames += 1;
      frameCountEl.textContent = state.frames + " frames";
      if (env.type === "heartbeat") {
        // 12hr AM/PM clock (user 2026-04-29). Wider than 24h compact
        // but matches the rest of the wall-clock displays in the app.
        const hbT = new Date((env.t || Date.now()/1000) * 1000);
        hbEl.textContent = `♥ ${_to12(hbT)}`;
        hbEl.classList.remove("hb-pulse");
        void hbEl.offsetWidth;
        hbEl.classList.add("hb-pulse");
        return;
      }
      if (env.type === "health") { _pulseStatus(); return onHealth(env); }
      if (env.type === "state")  { _pulseStatus(); return onState(env); }
      // s162: lcu envelope - drives the lobby view + champ-select overlay.
      // Live operation gets lcu via the SSE/HTTP /api/state.lcu path
      // (handleChampSelect is called there). Sim mode delivers it through
      // the WS path so a fixture can preview the lobby/champ-select flow.
      if (env.type === "lcu")    { _pulseStatus(); return handleLcuEnvelope(env.payload); }
      // Unknown envelope - log raw.
      logLine("ws", JSON.stringify(env).slice(0, 200));
    };
  }

  // ── Advisory badge ───────────────────────────────────────────────
  // Polls /api/advisories every 20s. When there are ready (un-completed)
  // advisories the badge lights with a count + pulses. Tap to cycle
  // through messages as a dismissible toast.
  (function setupAdvisoryBadge() {
    const badge = el("advisory-badge");
    const countEl = el("advisory-count");
    if (!badge || !countEl) return;
    let latest = [];
    let seenIds = new Set();
    async function refresh() {
      try {
        const r = await fetch("/api/advisories", { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        const ads = (j && j.advisories) || [];
        const fresh = ads.filter(a => a && a.status === "ready");
        latest = fresh;
        countEl.textContent = fresh.length;
        if (fresh.length > 0) {
          badge.classList.remove("hidden");
          // Pulse whenever there's a new id we haven't acknowledged.
          const hasNew = fresh.some(a => !seenIds.has(a.id));
          badge.classList.toggle("pulse", hasNew);
        } else {
          badge.classList.add("hidden");
          badge.classList.remove("pulse");
        }
      } catch (_) { /* silent */ }
    }
    function openLatest() {
      for (const a of latest) seenIds.add(a.id);
      badge.classList.remove("pulse");
      if (latest.length) {
        const a = latest[latest.length - 1];
        _showAdvisoryToast(a);
      }
    }
    badge.addEventListener("click", openLatest);
    badge.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLatest(); }
    });
    // Lightweight advisory toast - coral card that slides in from the
    // bottom-right, tap to dismiss, auto-fades after 8s.
    function _showAdvisoryToast(a) {
      let t = document.getElementById("advisory-toast");
      if (!t) {
        t = document.createElement("div");
        t.id = "advisory-toast";
        t.className = "advisory-toast";
        t.addEventListener("click", () => t.classList.remove("show"));
        document.body.appendChild(t);
      }
      t.innerHTML = `<b>⚠ ${a.champion || ""} · ${a.mode || ""}</b><p>${a.message || ""}</p><span class="toast-dismiss">tap to dismiss</span>`;
      t.classList.add("show");
      clearTimeout(t._t);
      t._t = setTimeout(() => t.classList.remove("show"), 8000);
    }
    setInterval(refresh, 20000);
    refresh();
  })();

  // Restore persisted preferences (zen / ui-mock) from prior session.
  // Also builds a footer chip listing the active flags. The Shift+L
  // header-lock mechanism was removed 2026-04-23 - it broke the UI
  // composition when hidden pills were temporarily un-hidden during
  // measurement, which displaced the visible pills' captured positions.
  // The natural flex layout is stable enough once the advisory badge
  // height is normalised. The zoom slider was removed in UI scale v2
  // (2026-05-23) - the per-element 25% bump replaced the body { zoom }
  // approach; the legacy rc-zoom key is cleared on Shift+R / chip-click
  // resets as defense-in-depth for stale browser state.
  (function restorePrefs() {
    try {
      // Zen is OFF by default (2026-04-24). Only enabled when the user
      // has explicitly opted in (stored as "1" via the Z hotkey). First
      // visit + null storage → all four panels visible.
      // One-time migration: browsers carrying the previous zen-on-by-
      // default preference get their cached "1" wiped so they see the
      // new default on the next load. After this, Z-toggles persist
      // normally.
      if (!localStorage.getItem("rc-zen-default-v2")) {
        localStorage.removeItem("rc-zen");
        localStorage.setItem("rc-zen-default-v2", "1");
      }
      const savedZen = localStorage.getItem("rc-zen");
      const zenOn = savedZen === "1";
      if (zenOn) document.body.dataset.zen = "1";
      // UI scale v2: restore the dev mock-data flag if the operator
      // enabled it before. body[data-ui-mock="1"] is read by each
      // panel's renderer to choose mock-fixture vs empty-state rendering.
      const savedMock = localStorage.getItem("rc-ui-mock");
      if (savedMock === "1") document.body.dataset.uiMock = "1";
      // Dev override: ?ui_mock=1 on the URL forces mock mode for this
      // session without touching localStorage. Lets headless-Chrome
      // audit captures hit the populated mock state.
      // UI scale v2.1 page #7 follow-up (2026-05-23): when ?ui_mock=1
      // is paired with a #view hash, ALSO clear the rc-view-manual
      // sticky so the operator's prior manual view doesn't override the
      // audit-capture hash route. Chrome PWA app-mode occasionally
      // launches the URL with hash stripped at script-load time; clearing
      // the sticky lets the auto-derive land on the hash target without
      // the manual side winning the next state envelope.
      try {
        const params = new URLSearchParams(location.search || "");
        if (params.get("ui_mock") === "1") {
          document.body.dataset.uiMock = "1";
          // PWA app-mode quirk: window.location.hash is occasionally
          // empty at script-load time even when the URL bar carries #X.
          // Parse the fragment from the full href as a fallback so the
          // audit-capture hash route survives the PWA reload race.
          let h = (location.hash || "").replace(/^#/, "").trim();
          if (!h) {
            const href = location.href || "";
            const hashIdx = href.indexOf("#");
            if (hashIdx >= 0) h = href.slice(hashIdx + 1).trim();
          }
          if (h && VIEW_IDS.includes(h)) {
            // Clear the prior manual sticky so the audit hash wins.
            try { localStorage.removeItem("rc-view-manual"); } catch (_) {}
            // Force-restore location.hash for downstream _viewFromHash
            // reads when the PWA stripped the fragment from the initial
            // location.hash property. _viewWireOnce + _viewResolveAndApply
            // run AFTER this IIFE so the corrected hash is observable.
            try { if (!location.hash) location.hash = "#" + h; } catch (_) {}
          }
        }
      } catch (_) {}
      // Scrub any legacy header-lock pinned styles so a stored lock from
      // before the feature was removed doesn't leak into the flex layout.
      const staleLock = localStorage.getItem("rc-header-lock");
      if (staleLock) {
        localStorage.removeItem("rc-header-lock");
        document.body.dataset.headerLock = "";
        const hdr = document.querySelector("header");
        if (hdr) for (const c of hdr.children) { c.style.left = ""; c.style.top = ""; }
      }
      _refreshPrefsChip();
    } catch (_) {}
  })();

  // Footer prefs chip - shows the dev mock-data flag when the operator
  // is running with it ON. Recomputed from live state on each call so
  // a toggle updates the chip immediately rather than reflecting the
  // value at page-load time only.
  function _refreshPrefsChip() {
    // s161: zen flag dropped from the prefs chip - operator wanted
    // the "ZEN:OFF" pill removed from the footer.
    // UI scale v2 (2026-05-23): zoom flag dropped - the page-zoom
    // slider is gone, replaced by per-element 25% bump. The dev
    // mock-data flag takes its slot as the surviving diagnostic.
    const mock = localStorage.getItem("rc-ui-mock");
    const flags = [];
    if (mock === "1") flags.push("ui-mock:on");
    let chip = document.querySelector("footer .prefs-chip");
    if (!flags.length) {
      if (chip) chip.remove();
      return;
    }
    if (!chip) {
      // Insert immediately before the mode-pill so the footer order is
      // VOICE → ZEN → CLIENT (per user 2026-04-29). Falls back to the
      // legacy spacer position if the mode-pill isn't in the DOM.
      const anchor = document.getElementById("mode-pill")
                  || document.querySelector("footer .spacer");
      if (!anchor) return;
      chip = document.createElement("span");
      chip.className = "prefs-chip";
      chip.title = "click to reset saved prefs";
      chip.style.cursor = "pointer";
      chip.addEventListener("click", () => {
        localStorage.removeItem("rc-zen");
        localStorage.removeItem("rc-header-lock");
        window.location.reload();
      });
      anchor.parentNode.insertBefore(chip, anchor);
    }
    chip.textContent = flags.join(" · ");
  }

  // Post-auto-reload banner - lets user know the rebuild landed.
  try {
    if (sessionStorage.getItem("rc-just-reloaded") === "1") {
      sessionStorage.removeItem("rc-just-reloaded");
      const t = document.createElement("div");
      t.className = "rebuild-toast";
      t.textContent = "UI updated";
      document.body.appendChild(t);
      requestAnimationFrame(() => t.classList.add("show"));
      setTimeout(() => t.remove(), 2500);
    }
  } catch (_) {}

  // Boot zen mode / no-map if URL says so.
  if (/[?&]zen=1/.test(location.search)) {
    document.body.dataset.zen = "1";
  }

  // Boot view router (2026-04-26): wire dropdown, restore manual view
  // from localStorage / URL hash, apply initial view. Auto-derive runs
  // again on every state envelope (see onState dispatcher).
  _viewWireOnce();
  _viewResolveAndApply();
  // Map underlay brightness override: ?map-br=0.55&map-sat=0.6
  (function mapFilterOverride() {
    const q = new URLSearchParams(location.search);
    const br = parseFloat(q.get("map-br"));
    const sat = parseFloat(q.get("map-sat"));
    if (!isNaN(br) || !isNaN(sat)) {
      const style = document.createElement("style");
      style.textContent = `.mm-canvas-stack::before { filter: saturate(${isNaN(sat)?0.55:sat}) brightness(${isNaN(br)?0.7:br}) !important; }`;
      document.head.appendChild(style);
    }
  })();

  // ── Keyboard shortcuts ───────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    // Shift+R resets saved preferences (zen) + reloads. The zoom key
    // was retired in UI scale v2 (2026-05-23); body { zoom } is gone
    // from base.css and no code path writes rc-zoom anymore.
    if (e.shiftKey && (e.key === "R" || e.key === "r")) {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      try {
        localStorage.removeItem("rc-zen");
        localStorage.removeItem("rc-header-lock");
      } catch (_) {}
      window.location.reload();
      return;
    }
    // A triggers the ANALYZE NOW footer button - quick kickoff.
    if ((e.key === "a" || e.key === "A") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      const btn = el("analyze-now");
      if (btn && !btn.disabled) { btn.click(); e.preventDefault(); return; }
    }
    // F toggles browser fullscreen (monitor-2 use case).
    if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen().catch(() => {});
      e.preventDefault();
      return;
    }
    // Z toggles "zen" mode - hides Next + Adaptation panels so the grid
    // re-composes around Minimap + Right Now + Item Build. Uses body data
    // attribute so CSS does the rest. Zen is the default view, so we
    // persist "0" on opt-out (not "" - restorePrefs treats null as on).
    if ((e.key === "z" || e.key === "Z") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      const turningOn = document.body.dataset.zen !== "1";
      document.body.dataset.zen = turningOn ? "1" : "";
      try { localStorage.setItem("rc-zen", turningOn ? "1" : "0"); } catch (_) {}
      _refreshPrefsChip();
      e.preventDefault();
      return;
    }
    // Esc: close modal → dismiss reply toast → exit Zen mode (in order).
    if (e.key === "Escape") {
      const modal = el("task-modal");
      if (modal && !modal.classList.contains("hidden")) {
        modal.classList.add("hidden");
        e.preventDefault();
        return;
      }
      const reply = document.querySelector(".input-reply:not(.hidden)");
      if (reply) {
        reply.classList.add("hidden");
        e.preventDefault();
        return;
      }
      if (document.body.dataset.zen === "1") {
        document.body.dataset.zen = "";
        e.preventDefault();
        return;
      }
    }
    // Ctrl+K / Cmd+K focuses the prompt input.
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      const input = el("input-text");
      if (input) { input.focus(); input.select(); e.preventDefault(); }
    }
    // "?" or "H" shows a brief keybind hint toast.
    if ((e.key === "?" || e.key === "h" || e.key === "H") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      showKeybindsToast();
    }
  });
  function showKeybindsToast() {
    let toast = document.getElementById("keybinds-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "keybinds-toast";
      toast.className = "keybinds-toast";
      toast.innerHTML = `
        <b>Keybinds</b>
        <div><kbd>Esc</kbd> close modal / dismiss toast</div>
        <div><kbd>Ctrl</kbd>+<kbd>K</kbd> focus prompt</div>
        <div><kbd>F</kbd> toggle fullscreen</div>
        <div><kbd>A</kbd> run Analyze Now</div>
        <div><kbd>Shift</kbd>+<kbd>R</kbd> reset saved prefs</div>
        <div><kbd>Z</kbd> toggle Zen (hide side panels)</div>
        <div><kbd>1</kbd>-<kbd>9</kbd> switch sim fixture (dev mode only)</div>
        <div><kbd>←</kbd> <kbd>→</kbd> cycle sim fixture (dev mode)</div>
        <div><kbd>?</kbd> or <kbd>H</kbd> show this</div>
      `;
      document.body.appendChild(toast);
    }
    toast.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toast.classList.remove("show"), 3500);
  }

  // When the tab returns to foreground, flush a pending ZOI redraw.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.pendingZoi) {
      const p = state.pendingZoi;
      state.pendingZoi = null;
      renderMinimapCanvases(p);
    }
  });

  // ── Auto-hide cursor after idle ─────────────────────────────────
  // For monitor-2 fullscreen display the cursor is distracting. Hide it
  // after 2s of no mousemove; show it back on any movement or keypress.
  (function setupCursorHide() {
    let hideT = null;
    function show() {
      document.body.classList.remove("cursor-hidden");
      clearTimeout(hideT);
      hideT = setTimeout(() => document.body.classList.add("cursor-hidden"), 2000);
    }
    document.addEventListener("mousemove", show, { passive: true });
    document.addEventListener("keydown", show, { passive: true });
    document.addEventListener("touchstart", show, { passive: true });
    show();
  })();

  // Input clear button - shows only when the field has content.
  (function setupInputClear() {
    const input = el("input-text"), clear = el("input-clear");
    if (!input || !clear) return;
    const sync = () => clear.classList.toggle("hidden", !input.value);
    input.addEventListener("input", sync);
    clear.addEventListener("click", () => {
      input.value = "";
      input.focus();
      sync();
    });
    sync();
  })();

  connect();

  // ── HTTP fallback polling ─────────────────────────────────────────
  // If the WebSocket stays disconnected for more than a few seconds,
  // poll /api/state and /api/health directly so the panels keep
  // showing live info. This covers WS drops (iPad WiFi hiccup, server
  // restart, transient network drop during a match).
  //
  // Bug history (2026-04-25): the fallback was synthesising
  // onState({mode: st.mode || "client"}) - but /api/state returns the
  // mode under `mode_key`, not `mode`, so st.mode was ALWAYS undefined
  // and the fallback always declared mode="client". Same for the
  // health-envelope wrapping: /api/state's `health` is flat (alive,
  // pid, mode, has_game, ...) but onHealth needs the mode flags
  // (aram_mode, arena_mode, tft_mode) which only live in /api/health
  // (which IS the raw health.json). Now we read /api/state for the
  // mode_key + coach payload, and /api/health for the mode flags;
  // both go through their respective handlers correctly.
  (function setupHttpFallback() {
    let lastFrameTs = Date.now();
    let lastFrames = 0;
    async function pollIfStale() {
      if (state.frames !== lastFrames) {
        lastFrames = state.frames;
        lastFrameTs = Date.now();
        return;
      }
      // Tier 4 #16: skip when /api/state-stream pushed something within
      // the last 4s - SSE has already delivered the same payload.
      if (Date.now() - state.lastSseTs < 4000) return;
      const ageMs = Date.now() - lastFrameTs;
      if (ageMs < 4000) return;
      try {
        const [stResp, hlResp] = await Promise.all([
          fetch("/api/state", { cache: "no-store" }),
          fetch("/api/health", { cache: "no-store" }),
        ]);
        if (hlResp.ok) {
          const hp = await hlResp.json();
          // /api/health returns raw health.json - contains aram_mode,
          // arena_mode, tft_mode, has_game, mode flags onHealth needs.
          onHealth({ type: "health", source: "health-http", payload: hp });
        }
        if (stResp.ok) {
          const st = await stResp.json();
          const fileMode = st.mode_key || "client";
          // The "coach" sub-object is the state envelope's payload -
          // contains action, immediate, kda, augments, item_build, etc.
          const coachPayload = st.coach || st;
          // 2026-05-25 item 201 fix: stamp the top-level /api/state
          // siblings into state.latest BEFORE onState() so renderActiveMatch
          // sees fresh liveclient + summoner_cooldowns. Without this the
          // CDS rail rendered "no live game" mid-game and the threat-donut
          // strip got null liveclient.
          state.latest.liveclient = st.liveclient || null;
          state.latest.summoner_cooldowns = st.summoner_cooldowns || null;
          onState({ type: "state", source: "state-http",
                    mode: fileMode, payload: coachPayload });
          // 2026-04-25: cold-start champ-select prep - surface adaptation
          // history during champ-select via the LCU snapshot.
          handleLcuEnvelope(st.lcu);
          renderTeamContext(st);
          renderArchetypeNudge(st);
          renderScreenRead(st);
        }
      } catch (_) { /* ignore - WS may come back */ }
    }
    setInterval(pollIfStale, 2000);
  })();

  // ── /api/state-stream SSE subscription (Tier 4 #16, 2026-05-01) ──
  // Server-pushes /api/state on every change + a 15s heartbeat, so the
  // dashboard doesn't need to schedule its own /api/state polls. When
  // a fresh SSE event lands we update state.lastSseTs; the LCU poller
  // and HTTP fallback below check that timestamp and skip while SSE
  // is alive (<4s old). EventSource auto-reconnects on disconnect
  // (browser honors the server-sent `retry: 2000` hint), and the
  // server caps each connection at 600s before forcing a reconnect.
  (function setupStateStream() {
    if (typeof EventSource === "undefined") return;
    let es = null;
    function connectSse() {
      try {
        es = new EventSource("/api/state-stream");
      } catch (_) { return; }
      es.onmessage = (ev) => {
        try {
          const st = JSON.parse(ev.data);
          if (!st) return;
          state.lastSseTs = Date.now();
          // Pipe through the same handlers the WS / HTTP-fallback paths use.
          const fileMode = st.mode_key || "client";
          const coachPayload = st.coach || st;
          // 2026-05-25 item 201 fix: see HTTP-fallback site above.
          state.latest.liveclient = st.liveclient || null;
          state.latest.summoner_cooldowns = st.summoner_cooldowns || null;
          onState({ type: "state", source: "state-sse",
                    mode: fileMode, payload: coachPayload });
          if (st.lcu) handleLcuEnvelope(st.lcu);
          renderTeamContext(st);
          renderArchetypeNudge(st);
          renderScreenRead(st);
        } catch (_) { /* malformed event - skip */ }
      };
      es.onerror = () => {
        // EventSource auto-reconnects per the server's `retry: 2000`
        // hint; nothing to do here besides clear our handle so a new
        // ES is created on next page load if this one is permanently
        // closed.
        if (es && es.readyState === 2 /* CLOSED */) { es = null; }
      };
    }
    connectSse();
  })();

  // ── Independent LCU / champ-select poller (2026-04-26) ────────────
  // Fallback path: SSE (above) normally pushes /api/state including
  // `lcu`, so this polling loop short-circuits while SSE is fresh.
  // Still needed when SSE is unavailable (browser without EventSource,
  // server slot pool exhausted, mid-reconnect window).
  (function setupLcuPoller() {
    let inflight = false;
    async function pollLcu() {
      if (document.hidden) return;
      if (inflight) return;
      // Skip when SSE delivered something within the last 4s.
      if (Date.now() - state.lastSseTs < 4000) return;
      inflight = true;
      try {
        const r = await fetch("/api/state", { cache: "no-store" });
        if (r.ok) {
          const st = await r.json();
          if (st && st.lcu) handleLcuEnvelope(st.lcu);
          // 2026-05-25 item 201 fix: stamp siblings here too so the
          // independent LCU poller path also keeps state.latest fresh.
          if (st) {
            state.latest.liveclient = st.liveclient || null;
            state.latest.summoner_cooldowns = st.summoner_cooldowns || null;
          }
          if (st) { renderTeamContext(st); renderArchetypeNudge(st); renderScreenRead(st); }
        }
      } catch (_) { /* silent */ }
      finally { inflight = false; }
    }
    setInterval(pollLcu, 2000);
    pollLcu();   // fire once on load
  })();

  // ── Voice TTS toggle ─────────────────────────────────────────────
  // (2026-04-25, revised same-day) Speech now uses the browser's
  // window.speechSynthesis (Web Speech API) so audio plays on the
  // device viewing the dashboard - iPad, Game-PC, Legion, whatever -
  // not on the server. The server-side /api/speak endpoint is kept
  // for parity / curl testing but the dashboard no longer uses it.
  // State persisted in localStorage; off by default.
  (function setupVoiceToggle() {
    const btn = document.getElementById("voice-toggle");
    const picker = document.getElementById("voice-picker");
    if (!btn) return;
    const synth = window.speechSynthesis || null;
    const supported = !!(synth && typeof synth.speak === "function");
    let on = false;
    let chosenName = "";
    try { on = localStorage.getItem("rc-voice-on") === "1"; } catch (_) {}
    try { chosenName = localStorage.getItem("rc-voice-name") || ""; } catch (_) {}
    if (!supported) on = false;
    let _voices = [];
    function pickVoiceObj() {
      if (!chosenName || !_voices.length) return null;
      return _voices.find(v => v.name === chosenName) || null;
    }
    function makeUtterance(text) {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05; u.volume = 1.0;
      const v = pickVoiceObj();
      if (v) u.voice = v;
      return u;
    }
    function populatePicker() {
      if (!picker || !synth) return;
      _voices = synth.getVoices() || [];
      // Sort: en-* voices first, then alpha by name.
      _voices.sort((a, b) => {
        const ae = (a.lang || "").startsWith("en") ? 0 : 1;
        const be = (b.lang || "").startsWith("en") ? 0 : 1;
        if (ae !== be) return ae - be;
        return (a.name || "").localeCompare(b.name || "");
      });
      picker.innerHTML = "";
      const def = document.createElement("option");
      def.value = ""; def.textContent = "(default)";
      picker.appendChild(def);
      _voices.forEach(v => {
        const opt = document.createElement("option");
        opt.value = v.name;
        opt.textContent = `${v.name} · ${v.lang}${v.default ? " ★" : ""}`;
        if (v.name === chosenName) opt.selected = true;
        picker.appendChild(opt);
      });
      if (!_voices.length) {
        def.textContent = "(no voices loaded yet)";
      }
    }
    if (picker && synth) {
      populatePicker();
      // Voice list often loads asynchronously; refire when it changes.
      synth.onvoiceschanged = populatePicker;
      picker.addEventListener("change", () => {
        chosenName = picker.value || "";
        try { localStorage.setItem("rc-voice-name", chosenName); } catch (_) {}
        if (on) {
          // Speak a sample with the new voice immediately.
          try {
            synth.cancel();
            const sample = chosenName ? `Voice changed to ${chosenName.split(' ').slice(-1)[0]}`
                                      : "Voice reset to default";
            synth.speak(makeUtterance(sample));
          } catch (_) {}
        }
      });
    }
    function paint() {
      if (!supported) {
        btn.textContent = "🔇 VOICE";
        btn.title = "Voice unsupported in this browser";
        btn.disabled = true;
        if (picker) picker.style.display = "none";
        return;
      }
      btn.textContent = on ? "🔊 VOICE" : "🔇 VOICE";
      btn.title = on ? "Voice on - speaks Right Now headline changes" : "Voice off";
      btn.classList.toggle("active", on);
      if (picker) picker.style.display = on ? "" : "none";
    }
    btn.addEventListener("click", () => {
      if (!supported) return;
      on = !on;
      try { localStorage.setItem("rc-voice-on", on ? "1" : "0"); } catch (_) {}
      paint();
      if (on) {
        try {
          synth.cancel();
          synth.speak(makeUtterance("voice on"));
        } catch (_) {}
      } else {
        try { synth.cancel(); } catch (_) {}
      }
    });
    paint();
    if (!supported) return;

    // Watch the Right Now action element for text changes; debounce so
    // partial-render flickers don't trigger speech.
    const actionEl = document.getElementById("rn-action");
    if (!actionEl) return;
    let lastSpoken = "";
    let lastSpokenTs = 0;
    let pending = null;
    const _MIN_INTERVAL_MS = 4000;
    const _DEDUP_MS = 60000;
    function maybeSpeak() {
      if (!on) return;
      const txt = (actionEl.textContent || "").replace(/^[▶►⚠️\s]+/, "").trim();
      if (!txt || txt === "-") return;
      if (/awaiting|loading|no advice/i.test(txt)) return;
      const now = Date.now();
      if (txt === lastSpoken && (now - lastSpokenTs) < _DEDUP_MS) return;
      if ((now - lastSpokenTs) < _MIN_INTERVAL_MS) return;
      lastSpoken = txt;
      lastSpokenTs = now;
      try {
        synth.cancel();   // stop any in-flight utterance
        synth.speak(makeUtterance(txt.slice(0, 200)));
      } catch (_) { /* swallow synth glitches */ }
    }
    new MutationObserver(() => {
      if (pending) clearTimeout(pending);
      pending = setTimeout(maybeSpeak, 800);
    }).observe(actionEl, { childList: true, subtree: true, characterData: true });
  })();

  // ── Console error pipe ───────────────────────────────────────────
  // (2026-04-25) Wires `window.onerror`, `unhandledrejection`, and
  // `console.error` to a server POST so JS exceptions in the live
  // dashboard land in RC's daily log without the user having to open
  // DevTools. Most "the panel went blank / nothing's updating" bugs
  // leave a JS trace; this makes them visible from the Legion side.
  // Throttled to ≤2 posts/sec so a render-loop crash can't flood RC's
  // log file. The original console.error is preserved (DevTools still
  // shows it) - we just tee a copy server-side.
  (function setupConsoleErrorPipe() {
    let lastSend = 0;
    let dropCount = 0;
    // localStorage fallback queue (NOTE-008): when /api/console-error is
    // unreachable the browser used to silently lose the error, exactly
    // when the user most needs visibility. Now we queue failed posts
    // (capped at 50 entries / 100 KB) and flush them on the next
    // successful post. Survives tab reloads.
    const QUEUE_KEY = "rc-console-error-queue";
    const QUEUE_MAX = 50;
    const QUEUE_BYTES = 100 * 1024;
    function readQueue() {
      try {
        const raw = localStorage.getItem(QUEUE_KEY);
        return raw ? JSON.parse(raw) : [];
      } catch (_) { return []; }
    }
    function writeQueue(arr) {
      try {
        let trimmed = arr.slice(-QUEUE_MAX);
        let s = JSON.stringify(trimmed);
        // Drop oldest until under byte cap (handles long stack strings).
        while (s.length > QUEUE_BYTES && trimmed.length > 1) {
          trimmed = trimmed.slice(1);
          s = JSON.stringify(trimmed);
        }
        localStorage.setItem(QUEUE_KEY, s);
      } catch (_) { /* localStorage full / disabled - ignore */ }
    }
    function _dropQueuedEntry(entry) {
      // Heuristic identity: timestamp + message-prefix. Survives JSON
      // round-trip (object identity wouldn't). Collisions are unlikely
      // and benign - at worst we drop a near-duplicate which will replay
      // on the next pipe success.
      const cur = readQueue();
      const target = (entry.message || "").slice(0, 100);
      const idx = cur.findIndex(
        (e) => e.ts === entry.ts && (e.message || "").slice(0, 100) === target,
      );
      if (idx >= 0) {
        cur.splice(idx, 1);
        writeQueue(cur);
      }
    }
    function flushQueueAfterSuccess() {
      const queued = readQueue();
      if (!queued.length) return;
      // BACKLOG fix (2026-05-12): the original implementation called
      // `localStorage.removeItem(QUEUE_KEY)` BEFORE issuing replay fetches.
      // If the endpoint went down mid-flush (or any single fetch failed)
      // the queue was already gone - fire-and-forget meant every queued
      // entry was lost. Now the queue stays intact; each entry is dropped
      // individually on its own confirmed 2xx response. Persistent outages
      // leave entries queued for the next pipe-success flush (capped at
      // QUEUE_MAX=50 so localStorage can't grow unbounded).
      queued.forEach((entry, i) => {
        setTimeout(() => {
          try {
            fetch("/api/console-error", {
              method: "POST", cache: "no-store",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...entry, _replay: true }),
            }).then((r) => {
              if (r && r.ok) _dropQueuedEntry(entry);
              // Non-2xx → leave queued; next flush will retry.
            }).catch(() => {
              // Network failure → leave queued; next flush will retry.
            });
          } catch (_) {}
        }, i * 100);  // 10 Hz max replay so we don't trip the server throttle
      });
    }
    function send(payload) {
      const now = Date.now();
      if (now - lastSend < 500) {     // 2 Hz cap
        dropCount += 1;
        return;
      }
      lastSend = now;
      const body = {
        ...payload,
        url: location.href,
        ts: now / 1000,
        dropped_since_last: dropCount,
      };
      dropCount = 0;
      try {
        fetch("/api/console-error", {
          method: "POST", cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }).then((r) => {
          if (r && r.ok) {
            flushQueueAfterSuccess();
          } else {
            // Non-2xx counts as a failure for queueing purposes.
            const q = readQueue(); q.push(body); writeQueue(q);
          }
        }).catch(() => {
          // Network failure / endpoint down - queue for next success.
          const q = readQueue(); q.push(body); writeQueue(q);
        });
      } catch (_) { /* don't recurse on send errors */ }
    }
    window.addEventListener("error", (e) => {
      const err = e.error || {};
      send({
        kind:    "window.error",
        message: e.message || err.message || "(no message)",
        source:  e.filename || "",
        lineno:  e.lineno || 0,
        colno:   e.colno  || 0,
        stack:   err.stack || "",
      });
    });
    window.addEventListener("unhandledrejection", (e) => {
      const r = e.reason;
      const isErr = r && typeof r === "object" && (r.message || r.stack);
      send({
        kind:    "unhandledrejection",
        message: typeof r === "string" ? r
                 : (isErr ? r.message : "(promise rejection)"),
        source:  "", lineno: 0, colno: 0,
        stack:   (isErr && r.stack) || "",
      });
    });
    // Tee console.error → pipe. We don't tee console.warn/log - too
    // noisy and most real bugs surface as either thrown errors or
    // explicit console.error calls in our own code.
    const origErr = console.error.bind(console);
    console.error = function (...args) {
      origErr(...args);
      try {
        const msg = args.map((a) => {
          if (typeof a === "string") return a;
          if (a instanceof Error)    return a.message + "\n" + a.stack;
          try { return JSON.stringify(a); } catch (_) { return String(a); }
        }).join(" ");
        send({ kind: "console.error", message: msg.slice(0, 600),
               source: "", lineno: 0, colno: 0, stack: "" });
      } catch (_) {}
    };
  })();

  // ── Auto-reload on CSS/JS changes ─────────────────────────────────
  // Polls /api/ui-version; when the hash changes, reload the page.
  // Keeps iPad in sync with Legion edits without needing manual refresh.
  (function autoReload() {
    let known = null;
    let rcVer = null;
    function stampFooter(uiHash) {
      // 2026-04-28: stamp BOTH the RC app version and the ui asset hash
      // in the footer so a quick glance tells you which build is live.
      let host = document.querySelector("footer .ui-version");
      if (!host) {
        host = document.createElement("span");
        host.className = "ui-version";
        const spacer = document.querySelector("footer .spacer");
        if (spacer) spacer.parentNode.insertBefore(host, spacer);
      }
      const v = rcVer ? `RC ${rcVer}` : "";
      const u = uiHash ? `ui ${uiHash}` : "";
      host.textContent = [v, u].filter(Boolean).join(" · ");
    }
    async function fetchRcVersion() {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        if (!r.ok) return;
        const h = await r.json();
        rcVer = h.rc_version || null;
      } catch (_) {}
    }
    async function check() {
      try {
        if (rcVer === null) await fetchRcVersion();
        const r = await fetch("/api/ui-version", { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (known === null) {
          known = j.v;
          stampFooter(j.v);
          return;
        }
        if (j.v && j.v !== known) {
          try { sessionStorage.setItem("rc-just-reloaded", "1"); } catch (_) {}
          window.location.reload();
        }
      } catch (_) { /* ignore */ }
    }
    setInterval(check, 4000);
    check();
  })();

  // ── App-wide tooltip system ───────────────────────────────────────
  // Replaces browser-native `title` tooltips across the whole UI:
  //   - larger readable font matching the muted-augments pill aesthetic
  //   - thin white border for pop-off-panel contrast
  //   - pinned to the cursor (offset ~14px), not the anchor, so it sits
  //     right next to where the eye is already looking
  //   - viewport-edge-aware: flips left/up from the cursor side if the
  //     tip would clip past the right/bottom edge
  //   - native `title` is stashed in `data-tt` on first hover and the DOM
  //     `title` is cleared so Chromium's delayed popup never shadows ours.
  // Event delegation on document.body - catches dynamically-rendered
  // elements too (champion-pill, item tiles, etc.) without re-init.
  (function initTooltips() {
    const tip = document.createElement("div");
    tip.className = "app-tooltip";
    document.body.appendChild(tip);
    let activeEl = null;
    let hideTimer = null;
    const MARGIN = 6;        // viewport-edge breathing room
    const OFFSET = 6;        // gap between cursor and tip (small → "just beneath cursor")
    let cursorX = 0, cursorY = 0;

    function capture(el) {
      if (el.hasAttribute("title")) {
        const t = el.getAttribute("title");
        if (t) el.setAttribute("data-tt", t);
        el.removeAttribute("title");
      }
      return el.getAttribute("data-tt") || "";
    }
    // Word-wrap content at 6 words per line. Keeps the tooltip visually
    // narrow + predictable instead of relying on CSS max-width which
    // produced awkward wrap points near screen edges.
    function wrapSixWords(text) {
      // s218: preserve explicit "\n" boundaries so multi-section
      // tooltips (e.g. the health-dot's RC / supervisor / vision /
      // DS / cost / bridge lines) render each section on its own row
      // instead of running them all together. Each source line wraps
      // independently at 6 words.
      const out = [];
      for (const line of String(text).split("\n")) {
        const words = line.split(/\s+/).filter(Boolean);
        if (!words.length) { out.push(""); continue; }
        for (let i = 0; i < words.length; i += 6) {
          out.push(words.slice(i, i + 6).join(" "));
        }
      }
      return out.join("\n");
    }
    // Placement (2026-04-24 rewrite): tooltip always sits immediately
    // below-right of the cursor, with viewport-edge clamping that pulls
    // it back inside if the natural position would clip. Previous build
    // used quadrant-based flipping (left of cursor in right half of
    // screen, above cursor in bottom half) which felt like the tip
    // "jumped" between anchor positions; user wants a single consistent
    // direction relative to cursor. UI scale v2 (2026-05-23) retired
    // the body { zoom } feature, so the zoom-compensation divisor that
    // sat in this function is gone - all coords are now in plain
    // viewport CSS pixels.
    function place() {
      tip.style.left = "-9999px"; tip.style.top = "-9999px";
      const tr = tip.getBoundingClientRect();
      const trW = tr.width;
      const trH = tr.height;
      const vw  = window.innerWidth;
      const vh  = window.innerHeight;
      // Default: just below-right of the cursor.
      let left = cursorX + OFFSET;
      let top  = cursorY + OFFSET;
      // Edge clamp: if the natural position runs off the right or bottom,
      // pull back inside the viewport. Reading order is preserved (still
      // grows down + right whenever there's room) without flipping above
      // or to the left of the cursor unless absolutely required by space.
      if (left + trW > vw - MARGIN) left = vw - trW - MARGIN;
      if (top  + trH > vh - MARGIN) top  = vh - trH - MARGIN;
      if (left < MARGIN) left = MARGIN;
      if (top  < MARGIN) top  = MARGIN;
      tip.style.left = left + "px";
      tip.style.top  = top  + "px";
    }
    function show(el) {
      // s162 v9: rich tooltips. If `data-tt-html` is set, render the
      // attribute value as innerHTML (the page is the only source of
      // these strings - operator-authored, not user input). Falls
      // back to plain `data-tt`/`title` text-only path otherwise.
      const html = el.getAttribute("data-tt-html");
      const text = capture(el);
      if (!html && !text) return;
      activeEl = el;
      if (html) {
        tip.innerHTML = html;
      } else {
        tip.textContent = wrapSixWords(text);
      }
      tip.classList.add("show");
      requestAnimationFrame(place);
    }
    function hide() {
      activeEl = null;
      tip.classList.remove("show");
    }
    // Track cursor continuously - mousemove fires during hover so the tip
    // follows the pointer if the user drags the cursor inside the anchor.
    document.body.addEventListener("mousemove", e => {
      cursorX = e.clientX; cursorY = e.clientY;
      if (activeEl) place();
    });
    document.body.addEventListener("mouseover", e => {
      cursorX = e.clientX; cursorY = e.clientY;
      const el = e.target.closest && e.target.closest("[title], [data-tt], [data-tt-html]");
      if (!el || el === activeEl) return;
      clearTimeout(hideTimer);
      show(el);
    });
    document.body.addEventListener("mouseout", e => {
      const el = e.target.closest && e.target.closest("[title], [data-tt], [data-tt-html]");
      if (!el) return;
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 80);
    });
    // Kill any stuck tip when the anchor scrolls / resizes / user clicks.
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    document.body.addEventListener("click", hide, true);
  })();

  // ───── AUDIT 2026-04-28 - proposals 3.3, 3.6 + 4.4, 2.1 ─────
  // Sticky-header compression on scroll + skeleton loaders + health
  // rollup dot + cost-tile poll. All passive - no-ops if the target
  // elements are absent.
  (function rcAuditUiEnhancements() {
    const header = document.querySelector("header");
    const COMPRESS_AT = 200;
    if (header) {
      // 3.3 - compress on scroll-Y > 200, restore below.
      window.addEventListener("scroll", () => {
        const y = window.scrollY || document.documentElement.scrollTop || 0;
        if (y > COMPRESS_AT) header.dataset.compressed = "1";
        else delete header.dataset.compressed;
      }, { passive: true });

      // 4.4 - health rollup dot ("claude cost pill" - tooltip carries
      // Claude $/day + supervisor + vision health). 2026-04-29: moved
      // from header.header-row-2 to the footer (right of mode-pill) per
      // user - it was visually distracting in the header. Lookup goes
      // both header AND footer for back-compat with any cached layout.
      try {
        let dot = document.querySelector(".health-dot");
        if (!dot) {
          dot = document.createElement("span");
          dot.className = "health-dot yellow";
          dot.title = "Loading...";
          dot.setAttribute("data-tt", "Loading...");
          const footer = document.querySelector("footer");
          const modePill = document.getElementById("mode-pill");
          if (modePill && modePill.parentNode === footer) {
            // Insert right after mode-pill (so order is mode → dot → next pill).
            modePill.parentNode.insertBefore(dot, modePill.nextSibling);
          } else if (footer) {
            footer.appendChild(dot);
          } else {
            // Last-ditch fallback to header so the JS doesn't no-op.
            const row2 = header.querySelector(".header-row-2");
            (row2 || header).appendChild(dot);
          }
        }
        const refreshHealth = () => {
          fetch("/api/health/all")
            .then(r => r.ok ? r.json() : null)
            .then(j => {
              if (!j) return;
              dot.classList.remove("green","yellow","red");
              dot.classList.add(j.status || "yellow");
              const cost = j.cost || {};
              const sup = j.supervisor || {};
              const bridge = j.bridge || {};
              const banner = cost.banner || "ok";
              const rcVer = j.rc_version || "?";
              const runId = (sup.run_id || "").slice(0, 8) || "?";
              const oslock = sup.oslock_present ? "lock" : "no-lock";
              // Bridge line: "bridge ok · last 12s ago" / "bridge silent
              // 14m ago" / "bridge dead 2h ago" / "bridge no-data".
              let bridgeLine;
              if (bridge.status === "unknown" || bridge.gamepc_result_age_s == null) {
                bridgeLine = "bridge no-data";
              } else {
                const a = bridge.gamepc_result_age_s;
                const ago = a < 60 ? `${Math.round(a)}s`
                          : a < 3600 ? `${Math.round(a/60)}m`
                          : `${(a/3600).toFixed(1)}h`;
                const label = bridge.status === "green" ? "ok"
                            : bridge.status === "yellow" ? "silent"
                            : "dead";
                bridgeLine = `bridge ${label} · last ${ago} ago`;
              }
              const ds = j.daemon_slayer || {};
              const dsLine = ds.alive
                ? `DS engine up · v${ds.engine_version || "?"} · ${ds.items ?? "?"}i/${ds.champions ?? "?"}c`
                : "DS engine DOWN";
              // Audit7 H-01: surface peer bridge health-publisher age so
              // hovering the (now peer-aware, see rollup status) dot tells
              // you WHICH node is silent - the rc_facts probe rendered
              // this but nothing on the dashboard did.
              const peers = j.peers || {};
              const peerBits = [];
              for (const node of Object.keys(peers).sort()) {
                const p = peers[node] || {};
                if (p.status === "no_data") { peerBits.push(`${node} no-data`); continue; }
                const a = p.age_s;
                if (a == null) continue;
                const ago = a < 60 ? `${Math.round(a)}s`
                          : a < 3600 ? `${Math.round(a/60)}m`
                          : `${(a/3600).toFixed(1)}h`;
                const st = p.status === "green" ? "ok"
                         : p.status === "yellow" ? "stale"
                         : "DEAD";
                peerBits.push(`${node} ${st} ${ago}`);
              }
              const lines = [
                `RC ${rcVer} (pid ${j.rc?.pid ?? "?"})`,
                `supervisor pid ${sup.pid ?? "?"} · run_id ${runId} · ${oslock}`,
                `vision ${j.vision?.alive ? "up" : "down"}` +
                  (j.vision?.uptime_s ? ` · uptime ${Math.round(j.vision.uptime_s/60)}m` : ""),
                dsLine,
                `cost $${(cost.today_usd || 0).toFixed(2)} · ${banner}`,
                bridgeLine,
              ];
              if (peerBits.length) lines.push(`publishers: ${peerBits.join(" · ")}`);
              dot.title = lines.join("\n");
              dot.setAttribute("data-tt", dot.title);
            })
            .catch(()=>{});
        };
        refreshHealth();
        setInterval(refreshHealth, 15000);
      } catch (e) { /* never let the dot break the dashboard */ }
    }

    // 3.7 - Hot-reload poller (2026-04-30). Polls /api/asset-stamp
    // every 3s; on mtime increase, hard-reload the page so CSS/JS
    // edits Legion-side land on Game-PC's secondary display without
    // an alt-tab. Disabled if `localStorage.rc_hot_reload === '0'`.
    (function _hotReloadInit() {
      try {
        if (localStorage.getItem("rc_hot_reload") === "0") return;
      } catch (_) {}
      let baseline = null;
      const tick = async () => {
        if (document.hidden) return;
        try {
          const r = await fetch("/api/asset-stamp", { cache: "no-store" });
          if (!r.ok) return;
          const j = await r.json();
          const m = +j.mtime || 0;
          if (!baseline) { baseline = m; return; }
          if (m > baseline + 0.5) {
            // Avoid reload storms while the file is mid-write.
            setTimeout(() => location.reload(), 250);
          }
        } catch (_) { /* network blip; try again next tick */ }
      };
      tick();
      setInterval(tick, 3000);
    })();

    // 3.6 - flag elements with data-rc-skel for the first 500 ms after
    // game-start. Anything bearing the attribute that still reads "-"
    // gets the .rc-skel class until the first data tick lands.
    document.querySelectorAll("[data-rc-skel]").forEach(el => {
      el.classList.add("rc-skel");
    });
    // Strip skeletons once any non-placeholder text appears in the
    // tracked element. Polled cheaply from the regular state tick.
    window.addEventListener("rc:state-tick", () => {
      document.querySelectorAll(".rc-skel").forEach(el => {
        const t = (el.textContent || "").trim();
        if (t && t !== "-" && t.length > 0) el.classList.remove("rc-skel");
      });
    });
  })();
