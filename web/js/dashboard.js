// Riot Commander — Phase 3 dashboard.
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
(function () {
  const WS_HOST = location.hostname || "legion-pc.local";
  const WS_PORT = 8891;
  const WS_URL = `ws://${WS_HOST}:${WS_PORT}/push`;

  // ── 12-hour clock helpers (user 2026-04-29: all wall-clock time
  // displays use AM/PM format, not 24h). Accepts a Date or a "HH:MM"
  // / "HH:MM:SS" string; returns "10:30 PM" or "10:30:45 PM" with
  // seconds preserved when present in the input. Duration formats
  // (game time, cooldown timers, "20m" played) are NOT clocks and
  // stay in their original numeric form.
  function _to12(input) {
    let h, m, s = null;
    if (input instanceof Date) {
      h = input.getHours(); m = input.getMinutes(); s = input.getSeconds();
    } else if (typeof input === "string") {
      const parts = input.split(":");
      if (parts.length < 2) return input;
      h = parseInt(parts[0], 10);
      m = parseInt(parts[1], 10);
      if (parts.length >= 3) s = parseInt(parts[2], 10);
      if (Number.isNaN(h) || Number.isNaN(m)) return input;
    } else { return ""; }
    const ampm = h >= 12 ? "PM" : "AM";
    let h12 = h % 12; if (h12 === 0) h12 = 12;
    const mm = String(m).padStart(2, "0");
    if (s !== null && !Number.isNaN(s)) {
      return `${h12}:${mm}:${String(s).padStart(2, "0")} ${ampm}`;
    }
    return `${h12}:${mm} ${ampm}`;
  }

  // ── DOM refs ────────────────────────────────────────────────────────
  const el = (id) => document.getElementById(id);
  const statusPill = el("status-pill");
  const modePill = el("mode-pill");
  const gameTime = el("game-time");
  const kdaEl = el("kda");
  const hpEl = el("hp-bar");
  const hbEl = el("heartbeat");
  const frameCountEl = el("frame-count");
  el("ws-url").textContent = WS_URL;

  // Panels
  const RN = {
    root: el("right-now"),
    action: el("rn-action"),
    immediate: el("rn-immediate"),
    risk: el("rn-risk"),
    fight: el("rn-fight-rule"),
    reset: el("rn-reset"),
    staleness: document.querySelector('.staleness[data-for="right-now"]'),
  };
  const NX = {
    root: el("next"),
    next: el("nx-next"),
    objective: el("nx-objective"),
    positioning: el("nx-positioning"),
    wave: el("nx-wave"),
    staleness: document.querySelector('.staleness[data-for="next"]'),
  };
  const IB = {
    root: el("item-build"),
    owned: el("ib-owned"),
    recommended: el("ib-recommended"),
    // Augments element lives in the header now (#augments-pill), not in the
    // Item Build panel, to keep info-panel layout stable across modes.
    augments: el("augments-pill"),
    staleness: document.querySelector('.staleness[data-for="item-build"]'),
  };
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
  const MM = {
    root: el("minimap"),
    status: el("mm-state"),
    staleness: document.querySelector('.staleness[data-for="minimap"]'),
    dragon: el("mm-dragon"),
    baron: el("mm-baron"),
    herald: el("mm-herald"),
    towers: el("mm-towers"),
    score: el("mm-score"),
    gameTime: el("mm-gametime"),
    imgWrap: el("mm-img-wrap"),
    img: el("mm-img"),
    imgCaption: el("mm-img-caption"),
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
            // dashboard runs in an unsandboxed kiosk-mode Edge — any XSS
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
  function _opGlyph(op) {
    const o = String(op || "").toLowerCase();
    if (o.includes("advisory"))        return "⚠";
    if (o.includes("analyze"))         return "⚗";
    if (o.includes("summary"))         return "Σ";
    if (o.includes("prime"))           return "✦";
    if (o.includes("digest"))          return "≡";
    if (o.includes("vision") || o.includes("screen")) return "◉";
    if (o.includes("game"))            return "▶";
    if (o.includes("file") || o.includes("ingest")) return "◧";
    if (o.includes("champ") || o.includes("pick")) return "♛";
    return "•";
  }
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
    TMODAL.op.textContent = "…";
    TMODAL.owner.textContent = TMODAL.status.textContent = "…";
    TMODAL.priority.textContent = TMODAL.ts.textContent = "…";
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
      TMODAL.op.textContent = d.op || "—";
      TMODAL.owner.textContent = d.owner_agent != null ? `agent${d.owner_agent}` : "—";
      TMODAL.status.textContent = d.status || "—";
      TMODAL.priority.textContent = (d.priority != null) ? String(d.priority) : "—";
      TMODAL.ts.textContent = d.created_at || "—";
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
          // context or user gesture — the button click qualifies.
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

  // ── State ───────────────────────────────────────────────────────────
  const state = {
    mode: "client",      // from health.json
    frames: 0,
    logCount: 0,
    lastTouch: {         // epoch seconds per panel
      right_now: 0,
      next: 0,
      item_build: 0,
      minimap: 0,
    },
    // cached latest coaching frames by mode
    latest: {},
    // ms timestamp of the last /api/state-stream event we processed.
    // The LCU poller + HTTP fallback skip while this is fresh (<4s old)
    // so SSE-pushed updates don't get duplicated by polling fetches.
    // Tier 4 #16 (2026-05-01).
    lastSseTs: 0,
  };

  // Refresh cadences from spec §5 (in seconds)
  const CADENCE = {
    right_now:  { stale: 4,   severe: 12 },
    next:       { stale: 16,  severe: 48 },
    item_build: { stale: 90,  severe: 300 },
    minimap:    { stale: 4,   severe: 12 },     // matches right_now tier per spec
  };

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

  function setMode(tag) {
    if (!tag || tag === state.mode) return;
    state.mode = tag;
    modePill.textContent = (tag || "client").toUpperCase();
    modePill.className = `mode-pill ${tag}`;
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
  // Title-bar dropdown (RIOT COMMANDER) toggles between 8 views:
  //   home / lobby / last-match / session / history / loadouts /
  //   settings / diagnostics
  // Default is auto-mode: view is derived from state.mode + lcu.phase.
  // Manual selection from the dropdown sets rc-view-manual in
  // localStorage and a body[data-view] attribute. Auto promotes to
  // ChampSelect/in-game on urgent game events; if a manual view is
  // active during a promote-worthy event, the banner appears instead.
  const VIEW_IDS = ["home","lobby","last-match","session","history","replay","loadouts","settings","diagnostics"];
  const VIEW_LABELS = {
    "home":"Home","lobby":"Lobby","last-match":"Last Match","session":"Session",
    "history":"History","replay":"Replay",
    "loadouts":"Loadouts","settings":"Settings","diagnostics":"Diagnostics",
  };
  const _VIEW = {
    current: null,
    manual: null,    // user-pinned view id, or null for auto
    bannerDismissed: null,  // last dismissed promote-target view id
  };
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
  function _viewAutoDerive(lcu, mode) {
    const phase = lcu && lcu.phase;
    if (phase === "ChampSelect")            return "lobby";   // cs-overlay still wins visually
    if (phase === "InProgress" || phase === "GameStart") return "last-match";  // panels are in-game in game mode
    if (phase === "Lobby" || phase === "Matchmaking" || phase === "ReadyCheck") return "lobby";
    if (mode === "client" || mode === "lobby" || !mode) return "home";
    return "last-match";  // in-game default → main panels
  }
  // Should we auto-promote past a manual selection? Only for urgent
  // game-state events where missing the actual view is harmful.
  function _viewIsUrgent(targetView) {
    return targetView === "lobby"   // ChampSelect-driven (cs-overlay)
        || targetView === "last-match";  // game InProgress
  }
  function applyView(viewId) {
    if (!VIEW_IDS.includes(viewId)) viewId = "home";
    if (viewId === _VIEW.current) {
      _viewUpdateMenuActive(viewId);
      return;
    }
    _VIEW.current = viewId;
    document.body.dataset.view = viewId;
    _viewUpdateTitleLabel(viewId);
    _viewUpdateMenuActive(viewId);
    // Lazy-fetch view content (wire-once + fetch on first activate)
    if (viewId === "lobby")       { _lobbyViewWireOnce(); _lobbyViewRefresh(); }
    if (viewId === "session")     { _sessionFetchAndRender(); }
    if (viewId === "history")     { _historyWireOnce(); _historyFetchAndRender(); }
    if (viewId === "replay")      { _replayViewWireOnce(); _replayViewRefresh(); }
    if (viewId === "loadouts")    { _loadoutsWireOnce(); _loadoutsFetchAndRender(); }
    if (viewId === "diagnostics") { _diagWireOnce(); _diagFetchAndRender(); }
    if (viewId === "settings")    { _settingsRefresh(); }
  }
  function _viewUpdateTitleLabel(viewId) {
    const el = document.getElementById("view-current-label");
    if (el) el.textContent = (_VIEW.manual ? "" : "AUTO · ") + (VIEW_LABELS[viewId] || viewId).toUpperCase();
    // Show the prominent ↻ AUTO pill only when manual is sticky.
    const pill = document.getElementById("view-auto-pill");
    if (pill) pill.classList.toggle("hidden", !_VIEW.manual);
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
          // Dev / Sim Preview — appends ?sim=default + ?dbg=1 to the
          // URL so sim.js boots its fixture-loader banner. Keeps any
          // existing query params + drops the manual hash so the dev
          // session is isolated. (User asked for a dropdown entry to
          // enter the dev "area" for UI testing.)
          const params = new URLSearchParams(location.search);
          if (!params.has("sim")) params.set("sim", "default");
          params.set("dbg", "1");
          location.search = "?" + params.toString();
          return;
        } else {
          _viewSaveManual(v);
          location.hash = "#" + v;
        }
        _viewResolveAndApply();
      });
    });
    // Prominent ↻ AUTO pill — clears the manual override in one click.
    const autoPill = document.getElementById("view-auto-pill");
    if (autoPill) autoPill.addEventListener("click", () => {
      _viewSaveManual(null);
      location.hash = "";
      _viewResolveAndApply();
    });
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
    const manual = hashView || _VIEW.manual;
    if (manual) {
      // Manual sticky — apply it
      applyView(manual);
      // Banner if auto wants to promote to an urgent target we're not on
      if (_viewIsUrgent(auto) && auto !== manual && auto !== _VIEW.bannerDismissed) {
        _viewBannerShow(auto,
          (auto === "lobby" ? "Champ Select active" : "Game in progress")
          + " — switch to " + (VIEW_LABELS[auto] || auto) + "?");
      } else {
        _viewBannerHide();
      }
    } else {
      _VIEW.bannerDismissed = null;
      applyView(auto);
      _viewBannerHide();
    }
  }

  function fmtList(v) {
    if (Array.isArray(v)) return v.filter(Boolean).join(", ");
    return (v == null ? "" : String(v));
  }

  function safe(s) {
    if (s == null) return "";
    return String(s).trim();
  }

  // Auto-fit text into a box by shrinking font-size until content height
  // fits, or min is reached. Used on the big headline texts so long
  // coach output never gets ellipsized — the user-stated requirement is
  // "never truncated or cutoff or snipped words". Cost ≤0.5ms per call.
  function fitText(elm, text, { max = 48, min = 16, step = 2, lines = null } = {}) {
    if (!elm) return;
    // Idempotency guard — every state envelope (~3s) re-calls this with the
    // same coach text. Without this check, we reset fontSize to `max` and
    // walk down again on every tick, which the user perceives as the big
    // text periodically flashing larger. Key includes max/min/lines so a
    // zen toggle (which changes caller's max) still triggers a re-fit.
    const fitKey = text + "|" + max + "|" + min + "|" + (lines ?? "");
    if (elm.dataset.fitKey === fitKey) return;
    elm.dataset.fitKey = fitKey;
    elm.textContent = text;
    if (!text || text === "—") return;
    // Reset to max, then walk down. Browsers batch the layout reads.
    elm.style.fontSize = max + "px";
    let size = max;
    // Height budget. When `lines` is supplied, the budget scales WITH the
    // font — shrinking the font only reduces the budget proportionally, so
    // fitText must keep shrinking until text actually fits in that many
    // lines (rather than sneaking a 3rd line in at a smaller font because
    // the static clientHeight allowed it). 1.15 covers line-height: 1.1
    // plus a small safety margin.
    const budget = () => lines
      ? Math.ceil(lines * size * 1.15)
      : elm.clientHeight + 1;
    while (size > min && elm.scrollHeight > budget()) {
      size -= step;
      elm.style.fontSize = size + "px";
    }
    // Also prevent horizontal spill for single short lines.
    while (size > min && elm.scrollWidth > elm.clientWidth + 1) {
      size -= step;
      elm.style.fontSize = size + "px";
    }
  }

  // logLine became a no-op when the Event Log panel was replaced with
  // the Adaptation panel in round 8. Kept as a stub so existing
  // call-sites don't break — route to console if useful for debugging.
  function logLine(src, body, cls) {
    // console.debug(`[${src}]`, body);
  }

  // Treat payload as arena when mode field says so, or when it carries
  // arena-only keys (teams list with is_partner flag, augment_advice, etc).
  function isArenaPayload(p) {
    if (!p) return false;
    if (p.mode === "arena") return true;
    if (Array.isArray(p.teams) && p.teams.length &&
        p.teams.some(t => t && (t.is_partner || t.is_next_opponent))) return true;
    if (p.augment_advice || p.anvil_advice || p.round_strategy) return true;
    return false;
  }

  // ── Panel renderers ─────────────────────────────────────────────────
  // Classify the action headline for color coding so the glance-read
   // is keyword-driven, not just always-coral.
  //   urgent  → coral pink  (DEAD, DANGER, DISENGAGE, FLEE, RECALL, back)
  //   fight   → gold         (default for "→" arrows, ENGAGE, BURST, FIGHT)
  //   good    → mint         (SAFE, won, push, CLEAR, OBJECTIVE secured)
  function classifyAction(text) {
    const t = (text || "").toUpperCase();
    if (/\b(DEAD|DANGER|DISENGAGE|FLEE|RECALL|RETREAT|BACK|BAIT|SURRENDER|GANK|COLLAPSE|DIVE|BOXED|CAUGHT|TRAPPED|RUN|ABORT|EMERGENCY|LOW HP|LOW MANA)\b/.test(t)
        || /^(BACK|FLEE|RECALL|DEAD|RUN|ABORT|GANK|DISENGAGE)/.test(t)) return "urgent";
    if (/\b(SAFE|WON|PUSH|CLEAR|OBJECTIVE|SECURED|FREE|SOUL|ACED|DOUBLE|TRIPLE|QUADRA|PENTA)\b/.test(t)) return "good";
    return "fight"; // default
  }

  // One-time bind: click the action headline to copy to clipboard.
  if (RN.action && !RN.action.dataset.bound) {
    RN.action.style.cursor = "copy";
    RN.action.title = "click to copy the coach's call";
    RN.action.addEventListener("click", () => {
      const text = RN.action.dataset.raw || RN.action.textContent || "";
      if (!text || text === "—") return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          RN.action.classList.add("copied");
          setTimeout(() => RN.action.classList.remove("copied"), 900);
          // Tiny "COPIED" bubble over the action for explicit feedback.
          const bubble = document.createElement("span");
          bubble.className = "copied-bubble";
          bubble.textContent = "COPIED";
          RN.action.appendChild(bubble);
          requestAnimationFrame(() => bubble.classList.add("show"));
          setTimeout(() => bubble.remove(), 900);
        }).catch(() => {});
      }
    });
    RN.action.dataset.bound = "1";
  }

  // ── WHAT WENT view (aftergame Map State replacement) ──────────────
  function renderWhatWent(p) {
    if (!p) return;
    const goodList = el("ww-good");
    const badList  = el("ww-bad");
    if (!goodList || !badList) return;
    const good = Array.isArray(p.what_went_good)
      ? p.what_went_good.filter(Boolean)
      : (safe(p.what_went_good) ? [safe(p.what_went_good)] : []);
    const bad = Array.isArray(p.what_went_bad)
      ? p.what_went_bad.filter(Boolean)
      : (safe(p.what_went_bad) ? [safe(p.what_went_bad)] : []);
    const fill = (ul, items) => {
      ul.innerHTML = "";
      if (!items.length) {
        const li = document.createElement("li");
        li.className = "ww-empty";
        li.textContent = "—";
        ul.appendChild(li);
        return;
      }
      for (const t of items) {
        const li = document.createElement("li");
        li.textContent = t;
        ul.appendChild(li);
      }
    };
    fill(goodList, good);
    fill(badList, bad);
  }

  // ── Digest icon + popout ──────────────────────────────────────────
  // Queue #5: cross-session digest warning icon in the header. Replaces
  // the in-panel trend surfaces that were removed. Click opens a modal-
  // style popout with cold-streak / slump / trend data.
  function renderDigest(p) {
    if (!p) return;
    const icon = el("digest-icon");
    const label = el("digest-label");
    if (!icon || !label) return;
    // Severity: "alert" > "warn" > neutral.  Coach emits p.digest_state
    // ∈ {none, ok, warn, alert}; icon class reflects it.
    const state = (safe(p.digest_state) || "none").toLowerCase();
    icon.classList.remove("warn", "alert");
    if (state === "alert") icon.classList.add("alert");
    else if (state === "warn") icon.classList.add("warn");
    // Label: short glyph + optional count ("⟳", "⟳ 3L", "⟳ SLUMP")
    const tag = safe(p.digest_label) || (state === "none" ? "—" : state.toUpperCase());
    label.textContent = tag;
    icon.title = safe(p.digest_tooltip) || "cross-session digest";
    // Populate popout fields from the same payload.
    const setd = (id, v) => { const e = el(id); if (e) e.textContent = safe(v) || "—"; };
    setd("dig-state",      p.digest_state_long);
    setd("dig-streak",     p.digest_streak);
    setd("dig-recent",     p.digest_recent);
    setd("dig-kda-trend",  p.digest_kda_trend);
    setd("dig-tod",        p.digest_time_of_day);
    setd("dig-fatigue",    p.digest_fatigue);
    setd("dig-advice",     p.digest_advice);
  }
  (function bindDigestIcon() {
    const icon = el("digest-icon");
    const pop = el("digest-popout");
    const close = el("digest-popout-close");
    if (!icon || !pop) return;
    // 2026-04-25: populate "TOP INSIGHTS" list from /api/digest each open.
    // Cache for 60 s so reopening within a minute doesn't re-fetch.
    const _DIG = { fetchedAt: 0, items: null };
    function renderInsights(arr) {
      const ul = el("dig-insights");
      const cnt = el("dig-insights-count");
      if (!ul) return;
      ul.innerHTML = "";
      if (!arr || !arr.length) {
        ul.innerHTML = '<li class="dim">no insights yet</li>';
        if (cnt) cnt.textContent = "0";
        return;
      }
      // Sort by severity desc, take top 5.
      const top = arr.slice().sort((a, b) =>
        (b.severity || 0) - (a.severity || 0)).slice(0, 5);
      top.forEach(ins => {
        const sev = (ins.severity || 0);
        const tone = sev >= 0.7 ? "alert" : sev >= 0.4 ? "warn" : "ok";
        const li = document.createElement("li");
        li.className = "ins-row tone-" + tone;
        const tag = document.createElement("span");
        tag.className = "ins-tag";
        tag.textContent = (ins.type || "?").replace(/_/g, " ");
        const msg = document.createElement("span");
        msg.className = "ins-msg";
        msg.textContent = ins.message || "(no message)";
        li.appendChild(tag);
        li.appendChild(msg);
        ul.appendChild(li);
      });
      if (cnt) cnt.textContent = arr.length;
    }
    function refreshInsights(force) {
      const now = Date.now();
      if (!force && _DIG.items && (now - _DIG.fetchedAt) < 60000) {
        renderInsights(_DIG.items);
        return;
      }
      fetch("/api/digest", { cache: "no-store" })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          _DIG.fetchedAt = now;
          _DIG.items = (data && data.insights) || [];
          renderInsights(_DIG.items);
        })
        .catch(() => renderInsights([]));
    }
    const open = () => { pop.classList.remove("hidden"); refreshInsights(false); };
    const hide = () => pop.classList.add("hidden");
    icon.addEventListener("click", open);
    icon.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { open(); e.preventDefault(); }
    });
    if (close) close.addEventListener("click", hide);
    pop.addEventListener("click", e => { if (e.target === pop) hide(); });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !pop.classList.contains("hidden")) hide();
    });
  })();

  // ── GAME SENSE panel renderer ─────────────────────────────────────
  // Client/aftergame mode populates the 3-row Game Sense block with the
  // Early/Mid/Late phase descriptors emitted by the coach. Vocabulary is
  // the 12 approved words (see coaches docs). Each word is valence-
  // colored so the trio reads as a quick strengths/weaknesses read.
  const GAME_SENSE_VALENCE = {
    // Negative (coral)
    chaotic: "v-bad", tilted: "v-bad", drowning: "v-bad",
    scattered: "v-bad",
    // Warning (gold)
    hesitant: "v-warn", reactive: "v-warn",
    // Neutral (text)
    steady: "v-ok",
    // Positive (mint/good)
    composed: "v-good", patient: "v-good", opportunistic: "v-good",
    dominant: "v-good", "on point": "v-good",
  };
  function _valenceClass(word) {
    if (!word) return "";
    return GAME_SENSE_VALENCE[word.toLowerCase().trim()] || "v-ok";
  }
  function renderGameSense(p) {
    if (!p) return;
    const gsBlock = el("game-sense-block");
    if (!gsBlock) return;
    // Only show when we actually have game-sense data (post-game state).
    const e = safe(p.game_sense_early);
    const m = safe(p.game_sense_mid);
    const l = safe(p.game_sense_late);
    const hasAny = [e, m, l].some(v => v && v !== "—");
    gsBlock.style.display = hasAny ? "" : "none";
    if (!hasAny) return;
    const triples = [
      ["gs-early", "gs-early-blurb", e, p.game_sense_early_blurb],
      ["gs-mid",   "gs-mid-blurb",   m, p.game_sense_mid_blurb],
      ["gs-late",  "gs-late-blurb",  l, p.game_sense_late_blurb],
    ];
    for (const [wordId, blurbId, word, blurb] of triples) {
      const wEl = el(wordId);
      const bEl = el(blurbId);
      if (wEl) {
        wEl.textContent = (word || "—").toUpperCase();
        wEl.className = "game-sense-word " + _valenceClass(word);
      }
      if (bEl) bEl.textContent = safe(blurb) || "";
    }
    // Trend line — last N matches aggregate. Coach-emitted string.
    const trendEl = el("gs-trend");
    if (trendEl) {
      const trend = safe(p.game_sense_trend);
      trendEl.textContent = trend || "no trend data yet";
      trendEl.style.display = trend ? "" : "none";
    }
  }

  // ── STATS panel renderer ─────────────────────────────────────────
  // Populates the in-game STATS view (replaces Adaptation for in-game
  // modes). Each field reads a specific payload key; when the coach hasn't
  // emitted that field yet, the placeholder "—" stays. Coach-side work
  // to populate these from live-client + Riot API is a separate pass.
  //
  // Level breakdown math (Lane/Jungle and Jungle Camp rows):
  // Both rows compute independently from p.xp_to_next and don't influence
  // each other — they show parallel paths to the next level (take lane
  // minions OR jungle camps, not a mix).
  //
  // Lane minion XP (mid-game approximation, patch-independent enough):
  //   melee 70, caster 40, siege/cannon 110
  //   wave composition: 3 melee + 3 caster (cannon every 3rd wave)
  // Algorithm: greedy melees first (higher XP per kill), then casters.
  // If melee+caster inside one wave can't reach xp_to_next, switch to
  // "Need Full Wave: N" count.
  //
  // Jungle camp XP average: ~130 per camp (blue 135, red 135, gromp 115,
  // raptors 155, wolves 110, krugs 127). ceil(xp_needed / 130) for count.
  function _levelBreakdowns(xpNeeded) {
    if (xpNeeded == null || xpNeeded <= 0) {
      return { lane: "at level", jungle: "at level" };
    }
    const MELEE = 70, CASTER = 40;
    const WAVE_MELEE = 3, WAVE_CASTER = 3;
    const WAVE_XP_NO_CANNON = WAVE_MELEE * MELEE + WAVE_CASTER * CASTER; // 330
    let xp = xpNeeded, melee = 0, caster = 0;
    while (xp > 0 && melee < WAVE_MELEE) { melee++; xp -= MELEE; }
    while (xp > 0 && caster < WAVE_CASTER) { caster++; xp -= CASTER; }
    const lane = xp <= 0
      ? `Melee: ${melee} | Caster: ${caster}`
      : `Need Full Wave: ${Math.ceil(xpNeeded / WAVE_XP_NO_CANNON)}`;
    const CAMP_XP = 130;
    const camps = Math.ceil(xpNeeded / CAMP_XP);
    return { lane, jungle: String(camps) };
  }
  function renderStats(p) {
    if (!p) return;
    const $ = id => el(id);
    const setv = (id, v) => { const e = $(id); if (e) e.textContent = v == null || v === "" ? "—" : v; };
    // LANING PHASE
    // Level row: "Ln — need X xp"
    if (p.level != null && p.xp_to_next != null) {
      setv("st-level", `L${p.level} — need ${p.xp_to_next} xp`);
    } else if (p.level != null) {
      setv("st-level", `L${p.level}`);
    } else {
      setv("st-level", "—");
    }
    // Two independent breakdowns below Level — lane minions vs jungle camps.
    // Neither influences the other; both re-derive from the same xp_to_next.
    const brk = _levelBreakdowns(p.xp_to_next);
    setv("st-level-lane",   brk.lane);
    setv("st-level-jungle", brk.jungle);
    setv("st-cannon",       p.cannon_cs_summary);
    // Spike hit + Next spike collapsed (2026-04-24) — power-spike status
    // now carries the next-item spike hint appended after the level-hit
    // summary so one row covers both views.
    {
      const sh = safe(p.powerspike_status) || "";
      const ns = safe(p.next_spike) || "";
      let v = sh;
      if (ns && ns !== "—") v = sh ? `${sh} · ${ns}` : ns;
      setv("st-spike-status", v || "—");
    }
    setv("st-cs-at-10",     p.cs_at_10);
    setv("st-csd-15",       p.csd_at_15);
    setv("st-gd-15",        p.gd_at_15);
    setv("st-wave-now",     p.wave_state_now);
    setv("st-back-gold",    p.back_gold_summary);
    setv("st-enemy-side",   p.enemy_side_pct);
    setv("st-build-dev",    p.build_deviation);
    setv("st-waves",        p.wave_control);
    setv("st-trades",       p.trade_winrate);
    setv("st-roams",        p.roams_summary);
    setv("st-freezes",      p.wave_freezes);
    setv("st-jungle-path",  p.jungle_pathing);
    setv("st-lane-prio",    p.lane_prio);
    setv("st-enemy-mastery",p.enemy_laner_mastery);
    setv("st-first-recall", p.first_recall_timing);
    // COMBAT
    setv("st-kp",           p.kill_participation_pct);
    setv("st-dmg-share",    p.damage_share_summary);
    setv("st-dmg-taken",    p.damage_taken_summary);
    setv("st-cc",           p.cc_score_summary);
    setv("st-heal",         p.heal_shield_summary);
    setv("st-peel",         p.peel_on_carry);
    // Alive/Dead collapsed — two lines worth of info ("28s dead" +
    // "98% alive") on one row so the reader sees the death cost and
    // life ratio together.
    {
      const td = safe(p.time_dead_summary) || "";
      const ta = safe(p.time_alive_pct) || "";
      let v = td;
      if (ta && ta !== "—") v = td ? `${td} · alive ${ta}` : `alive ${ta}`;
      setv("st-time-dead", v || "—");
    }
    setv("st-skillshot",    p.skillshot_summary);
    setv("st-combo-hit",    p.combo_hit_rate);
    setv("st-engage",       p.engage_count);
    setv("st-ult-eff",      p.ult_efficiency);
    setv("st-tf-outcomes",  p.teamfight_outcomes);
    setv("st-dive",         p.dive_outcomes);
    setv("st-flash-disc",   p.flash_discipline);
    setv("st-solo-death",   p.solo_death_rate);
    setv("st-top-threat",   p.top_enemy_threat);
    setv("st-comp-id",      p.team_comp_id);
    setv("st-carry-idx",    p.carry_index);
    setv("st-aa-mix",       p.auto_attack_mix);
    setv("st-wasted-clicks",p.wasted_clicks);
    setv("st-apm",          p.apm);
    setv("st-reaction",     p.reaction_time);
    setv("st-cancel-windows",p.cancel_windows);
    setv("st-anim-cancels", p.animation_cancels);
    setv("st-fight-window", p.fight_windows);
    setv("st-wall-deaths",  p.wall_collision_deaths);
    setv("st-death-heat",   p.death_locations);
    setv("st-death-pattern",p.death_pattern);
    setv("st-winc",         p.wincon_ability_up);
    setv("st-ally-summs",   p.ally_summs_up);
    setv("st-enemy-summs",  p.enemy_summs_tracked);
    setv("st-flank",        p.flank_success);
    // MAP PRESENCE
    setv("st-vision",       p.vision_summary);
    setv("st-trinket",      p.trinket_uptime);
    setv("st-pink-uptime",  p.pink_ward_uptime);
    setv("st-vision-denied",p.vision_denied);
    setv("st-obj-setup",    p.objective_setup);
    setv("st-obj-dance",    p.objective_dance);
    setv("st-baron-prep",   p.baron_prep);
    setv("st-scuttle",      p.scuttle_control);
    setv("st-jg-track",     p.jungler_tracking);
    setv("st-split-push",   p.split_push_pressure);
    // IDENTITY
    setv("st-mastery",      p.mastery_summary);
    setv("st-runes",        p.runes_chosen);
    setv("st-spike-map",    p.power_spike_map);
    // Matchup row collapsed (2026-04-24 reorganize) — both history and
    // counter warning surface on the same line so the eye sees "this
    // opponent, here's the record + threat" in one glance.
    const mh = safe(p.matchup_history) || "";
    const cw = safe(p.counter_warning) || "";
    let matchup = mh;
    if (cw && cw !== "—") matchup = mh ? `${mh} · ${cw}` : cw;
    setv("st-matchup", matchup || "—");
    setv("st-champ-key",    p.champ_key_metric);
    setv("st-keystone",     p.keystone_procs);
    setv("st-rune-adapt",   p.rune_adapt_hint);
    // RANK / SESSION
    setv("st-rank",         p.current_rank_lp);
    setv("st-lp-forecast",  p.lp_forecast);
    // Session row collapsed — LP delta + session duration on one line.
    {
      const sd = safe(p.lp_session_delta) || "";
      const dur = safe(p.session_duration) || "";
      let v = sd;
      if (dur && dur !== "—") v = sd ? `${sd} · ${dur}` : dur;
      setv("st-session-delta", v || "—");
    }
    setv("st-gold-diff-trend", p.team_gold_diff_trend);
    setv("st-promo",        p.promo_status);
    setv("st-goal",         p.rank_goal_progress);
    setv("st-break",        p.break_recommendation);
    setv("st-lobby-mmr",    p.lobby_mmr);
    setv("st-benchmark",    p.rank_benchmark);
    setv("st-improve",      p.improvement_target);
    setv("st-chat-tone",    p.chat_tone);
    // Perf row collapsed — strength (+) and weakness (−) of the game
    // in one line, sign-prefixed so the eye reads both as a unit.
    {
      const sg = safe(p.strength_of_game) || "";
      const wg = safe(p.weakness_of_game) || "";
      const parts = [];
      if (sg && sg !== "—") parts.push(`+ ${sg}`);
      if (wg && wg !== "—") parts.push(`− ${wg}`);
      setv("st-strength", parts.join("   ") || "—");
    }
    setv("st-adjust",       p.adjustment_rate);
    setv("st-tilt",         p.tilt_meter);
    setv("st-comeback",     p.comeback_odds);
    setv("st-comp-align",   p.comp_alignment);
    setv("st-wincon-phase", p.wincon_phase);
    setv("st-session-compare",p.session_to_session_delta);
    setv("st-game-eta",     p.game_close_eta);
    setv("st-comp-synergy", p.comp_synergy);
    setv("st-self-judge",   p.self_judgement);
    setv("st-coach-use",    p.coach_interventions);
  }

  function renderRightNow(p) {
    const arena = isArenaPayload(p);
    let rawAction = safe(p.action);
    // DEAD state: the coral `DEAD Ns` pill in the header is the authoritative
    // countdown. When the coach echoes "DEAD — 18s" as the action headline,
    // rewrite so the big text carries the 1-line next-action (headline) and
    // the sub-headline carries the 1-line why/threat — matching the live-
    // game pattern (action = what to do, immediate = detail). Both kept to
    // 1 sentence so the panel reads without duplication.
    let overriddenImmediate = null;
    if (p.is_dead && /^\s*[⚠✓►•⚡⛔🚨✳▶◉→⛔]?\s*DEAD\b/i.test(rawAction)) {
      const immStr = safe(p.immediate) || "";
      const sentences = immStr.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
      if (sentences.length >= 2) {
        // Convention: last sentence = actionable next-step; earlier = why.
        rawAction = sentences[sentences.length - 1].replace(/\.$/, "");
        overriddenImmediate = sentences.slice(0, -1).join(" ");
      } else if (sentences.length === 1) {
        rawAction = sentences[0].replace(/\.$/, "");
        overriddenImmediate = safe(p.next) || "";
      } else if (safe(p.next)) {
        rawAction = safe(p.next);
      }
    }
    const hasAction = !!rawAction;
    const klass = hasAction ? classifyAction(rawAction) : "empty";
    // Detect content change for fresh-state flash — only pulse when the
    // headline actually changes, not on every re-emit of the same text.
    const prevAction = RN.action.dataset.raw || "";
    if (hasAction && rawAction !== prevAction) {
      RN.root.classList.remove("rn-fresh");
      void RN.root.offsetWidth;
      RN.root.classList.add("rn-fresh");
      setTimeout(() => RN.root.classList.remove("rn-fresh"), 1200);
    }
    RN.action.dataset.raw = rawAction;
    RN.action.className = "action action-" + klass;
    // Priority glyph prefix — a quick shape-read for peripheral vision.
    // Skip the glyph when we have no action text to avoid a lonely "►".
    // Also skip if the fixture/coach already starts the string with a
    // matching glyph, to avoid double "⚠ ⚠ DEFEAT".
    const glyph = klass === "urgent" ? "⚠ "
                : klass === "good"   ? "✓ "
                :                      "► ";
    const alreadyGlyphed = hasAction && /^[⚠✓►•⚡⛔🚨✳▶◉→]/.test(rawAction);
    // Fixed-height .action slot with CSS line-clamp (see .action in
    // dashboard.css). No fitText shrinking — font stays at the CSS-defined
    // 48-56px, long content ellipsizes at line 2. Short content sits at
    // the top of the fixed 130px box; the box itself never changes size
    // so subsequent rows stay pinned across fixtures.
    RN.action.textContent = hasAction
      ? (alreadyGlyphed ? rawAction : glyph + rawAction)
      : "—";
    // Arena: in pregame (no round yet / no round_strategy), surface the
    // full pregame card as the immediate content. Once the live coach
    // starts writing round_strategy, swap to that.
    if (arena) {
      const liveStrategy = safe(p.round_strategy);
      const hasLiveRound = (typeof p.round === "number" && p.round > 0) || !!liveStrategy;
      const imm = hasLiveRound
        ? (liveStrategy || safe(p.immediate) || "—")
        : (safe(p.pregame) || safe(p.immediate) || "—");
      RN.immediate.classList.toggle("is-pregame", !hasLiveRound && !!safe(p.pregame));
      RN.immediate.textContent = imm;
    } else {
      RN.immediate.classList.remove("is-pregame");
      // DEAD-state rewrite (see top of function) replaces p.immediate with a
      // single-sentence "why" so headline and sub don't duplicate each other.
      const immText = overriddenImmediate !== null
        ? overriddenImmediate
        : (safe(p.immediate) || safe(p.pregame) || "—");
      RN.immediate.textContent = immText;
    }
    RN.risk.textContent   = safe(p.risk) || "—";
    RN.fight.textContent  = safe(p.fight_rule) || "—";
    // Reset item: if the text has a "(Ng)" price tag, color-code by
    // whether the current gold clears it. "Dark Seal + boots (950g)".
    if (RN.reset) {
      const resetTxt = safe(p.reset_item) || "—";
      const mg = /\((\d+)\s*g\)/.exec(resetTxt);
      RN.reset.textContent = resetTxt;
      RN.reset.classList.remove("can-afford", "short-gold");
      if (mg && typeof p.gold === "number") {
        const need = +mg[1];
        RN.reset.classList.add(p.gold >= need ? "can-afford" : "short-gold");
      }
    }
    // Arena has no SR-style reset. Repurpose the slot for target priority
    // (who to focus) since that's the single highest-value per-fight datum.
    if (arena) {
      const tgt = safe(p.target_priority);
      RN.reset.textContent = tgt || safe(p.anvil_advice) || "—";
      RN.reset.parentElement.firstElementChild.textContent = "Target";
    } else {
      RN.reset.textContent = safe(p.reset_item) || "—";
      RN.reset.parentElement.firstElementChild.textContent = "Base";
    }
    state.lastTouch.right_now = Date.now() / 1000;
  }

  // ── Wave state (Next panel) ──────────────────────────────────────
  // SR has 3 lanes; we show all three on separate lines with the
  // player's own lane marked ▶. Each percentage is colored AND
  // suffixed with the action verb so the eye reads value + intent
  // in one glance.
  //
  //   <= 30 %       wave-our   (icy blue)      → FREEZE
  //   30 – 65 %     wave-mid   (potion green)  → TRADE
  //   65 – 80 %     wave-warn  (gold)          → CRASH
  //   >= 80 %       wave-bad   (vibrant red)   → DISENGAGE
  //   null / —      wave-dim   (faint)         (no suffix)
  function _classifyWavePct(pct) {
    if (pct == null || isNaN(pct)) return "wave-dim";
    if (pct >= 80) return "wave-bad";
    if (pct >= 65) return "wave-warn";
    if (pct <= 30) return "wave-our";
    return "wave-mid";
  }
  function _waveSuffix(pct) {
    if (pct == null || isNaN(pct)) return "";
    if (pct >= 80) return " → DISENGAGE";
    if (pct >= 65) return " → CRASH";
    if (pct <= 30) return " → FREEZE";
    return " → TRADE";
  }
  function _waveVerb(pct) {
    if (pct == null || isNaN(pct)) return "";
    if (pct >= 80) return "DISENGAGE";
    if (pct >= 65) return "CRASH";
    if (pct <= 30) return "FREEZE";
    return "TRADE";
  }
  function _waveLineHtml(lane, pct, isMine) {
    // (2026-04-25) Each lane wrapped in a `.wave-line` block so it
    // renders as exactly one row (white-space:nowrap) — earlier the
    // <br>-separated inline form let BOT's "50%" wrap to a 4th line
    // when the inline span sat at a sub-pixel-tight width. Marker is
    // a fixed-width slot so the lane labels TOP/MID/BOT line up by
    // column whether or not the ▶ is present.
    const cls    = _classifyWavePct(pct);
    const pctTxt = (pct == null || isNaN(pct)) ? "—" : `${Math.round(pct)}%`;
    const verb   = _waveVerb(pct);
    // Each segment in its own fixed-width span so the four columns
    // (label / pct / arrow / verb) lock to identical X positions
    // across all rows, regardless of value length. Marker is absolutely
    // positioned in CSS so it doesn't push the lane label.
    const marker = isMine ? `<span class="wave-marker">▶</span>` : "";
    return `<span class="wave-line">${marker}` +
      `<span class="wave-label">${lane}:</span>` +
      `<span class="wave-pct ${cls}">${pctTxt}</span>` +
      `<span class="wave-arrow ${cls}">→</span>` +
      `<span class="wave-verb ${cls}">${verb}</span>` +
      `</span>`;
  }
  function _renderWaveState(p) {
    if (!NX.wave) return;
    const m = state.mode;
    if (m === "sr") {
      const lane = String(p.lane || p.role || "").toUpperCase();
      const isTop = lane === "TOP" || lane === "TOPLANE";
      const isMid = lane === "MID" || lane === "MIDDLE";
      const isBot = lane === "BOT" || lane === "BOTTOM" || lane === "ADC"
                 || lane === "SUPPORT" || lane === "SUP" || lane === "UTILITY";
      NX.wave.innerHTML = [
        _waveLineHtml("TOP", p.wave_top, isTop),
        _waveLineHtml("MID", p.wave_mid, isMid),
        _waveLineHtml("BOT", p.wave_bot, isBot),
      ].join("");
    } else if (m === "aram" || m === "brawl") {
      // Single-lane modes: just the percentage with classification.
      const pct = p.wave_pct;
      if (pct == null) {
        NX.wave.textContent = safe(p.wave) || "—";
      } else {
        const cls = _classifyWavePct(pct);
        NX.wave.innerHTML = `<span class="wave-pct ${cls}">${Math.round(pct)}%</span>`;
      }
    } else {
      NX.wave.textContent = safe(p.wave) || "—";
    }
  }

  function renderNext(p) {
    const arena = isArenaPayload(p);
    const aftergame = state.mode === "client";
    if (aftergame) {
      // ADVICE layout for aftergame / client. Headline reads as the
      // coach's session take; body rows relabel to "Objective" (stays),
      // "Key Points to Review" (3 bullets), "What to Review in Clips".
      NX.next.textContent        = safe(p.advice_headline) || safe(p.next) || safe(p.action) || "—";
      NX.objective.textContent   = safe(p.objective) || safe(p.advice_objective) || "—";
      NX.positioning.textContent = safe(p.key_points_review) || safe(p.positioning) || "—";
      NX.wave.textContent        = safe(p.clips_review) || safe(p.wave) || "—";
      const rows = NX.root.querySelectorAll(".kv span:first-child");
      if (rows[0]) rows[0].textContent = "Objective";
      if (rows[1]) rows[1].textContent = "Key Points";
      if (rows[2]) rows[2].textContent = "Clips";
    } else if (state.mode === "aram" || state.mode === "brawl") {
      // ARAM/Brawl/Mayhem coach (coaches/aram_coach.py) doesn't emit
      // next/objective/positioning/wave — those rows would all show "—".
      // Map to fields the coach DOES emit so the panel actually fires.
      // 2026-04-26 user-reported regression mid-game.
      // Headline: reset_item is the "what's next" call (build, recall,
      // pack timing). If the coach left it blank, fall back to action.
      const _resetTxt = safe(p.reset_item);
      const _action = safe(p.action) || "";
      let _head = _resetTxt;
      if (!_head || _head === _action) _head = safe(p.next) || _action || "";
      NX.next.textContent = _head || "—";
      // Objective row → item rationale (item_extra) — long-form per-item
      // build context. Truncated by CSS line-clamp.
      NX.objective.textContent = safe(p.item_extra) || safe(p.objective) || "—";
      // Positioning row → HP pack status (TOP / BOT availability). Coach
      // emits hp_packs as [top:bool, bot:bool].
      const hpPacks = Array.isArray(p.hp_packs) ? p.hp_packs : null;
      let hpLine = "—";
      if (hpPacks && hpPacks.length >= 2) {
        const tag = (b) => (b ? "✓" : "✗");
        hpLine = `TOP ${tag(hpPacks[0])} · BOT ${tag(hpPacks[1])}`;
      } else if (safe(p.positioning)) {
        hpLine = safe(p.positioning);
      }
      NX.positioning.textContent = hpLine;
      // Wave row → wave_pct (int 0-100) — minion wave progress.
      const wp = p.wave_pct;
      NX.wave.textContent = (typeof wp === "number")
        ? `${wp}% to next wave` : (safe(p.wave) || "—");
      const rows = NX.root.querySelectorAll(".kv span:first-child");
      if (rows[0]) rows[0].textContent = "Build";
      if (rows[1]) rows[1].textContent = "HP Packs";
      if (rows[2]) rows[2].textContent = "Wave";
    } else if (arena) {
      // Headline: round # + rank + alive teams, since those drive every decision.
      const rd = p.round != null ? `Round ${p.round}` : "";
      const rk = p.rank != null && p.rank !== "?" ? `#${p.rank}/${p.alive_teams || 8}` : "";
      const head = [rd, rk].filter(Boolean).join(" · ") || safe(p.action) || "—";
      NX.next.textContent = head;
      // Objective → anvil advice (what to buy/take between rounds)
      NX.objective.textContent   = safe(p.anvil_advice) || "—";
      // Positioning → partner name + synergy one-liner
      NX.positioning.textContent = arenaPartnerLine(p);
      // Wave → camp-phase or next-opponent hint
      NX.wave.textContent        = arenaWaveLine(p);
      // Relabel KV keys for arena context
      const rows = NX.root.querySelectorAll(".kv span:first-child");
      if (rows[0]) rows[0].textContent = "Anvil";
      if (rows[1]) rows[1].textContent = "Partner";
      if (rows[2]) rows[2].textContent = "Camp/Opp";
    } else {
      // Fixed font, no shrink. Readability matters more than fit — the
      // coach is expected to produce concise, glanceable copy. Hard 2-line
      // cap on headline and 3-line cap on body rows is enforced by CSS
      // -webkit-line-clamp; anything longer gets ellipsized rather than
      // resized to an unreadable small font.
      // Dedup (2026-04-25): the headline used to fall back to p.action
      // when p.next was empty, which produced an exact echo of the Right
      // Now panel headline (e.g. both saying "FOUNTAIN NOW" while dead).
      // Now we only fall back to p.action if it's strictly different;
      // otherwise show "—" so the duplication is visible rather than
      // pretending two coaching slots have content.
      const _action = safe(p.action) || "";
      let _nextHead = safe(p.next);
      if (!_nextHead || _nextHead === _action) _nextHead = "";
      NX.next.textContent        = _nextHead || "—";
      NX.objective.textContent   = safe(p.objective)   || "—";
      NX.positioning.textContent = safe(p.positioning) || "—";
      // (2026-04-25) Wave state: SR shows all-three-lanes per row with a
      // ▶ marker on the player's lane and color-coded percentages
      // matching coach-prompt thresholds. Other modes (ARAM single-lane,
      // Brawl, Arena, TFT) keep the simple "wave NN%" or fall through.
      _renderWaveState(p);
      const rows = NX.root.querySelectorAll(".kv span:first-child");
      if (rows[0]) rows[0].textContent = "Objective";
      if (rows[1]) rows[1].textContent = "Position";
      if (rows[2]) rows[2].textContent = "Waves";
    }
    state.lastTouch.next = Date.now() / 1000;
  }

  // Item icon index — lazy-loaded once from /data/items_index.json.
  // Shape: { version: "16.8.1", byName: {"ludenscompanion": "6655", ...}, byId: {...} }
  const ITEMS = { ready: false, version: "16.8.1", byName: {}, byId: {} };
  // Race fix (2026-04-24): renderItemBuild can run before the async
  // items_index fetch completes — especially in sim/dev-preview mode
  // where FakeSocket fires its state envelope on next tick. When that
  // happens every tile gets `.no-icon` because _resolveItemId returns
  // null for an empty byName. Stash the last state so the ITEMS loader
  // can re-drive the render once resolution actually works.
  let _lastItemBuildState = null;
  (async () => {
    try {
      const r = await fetch("/data/items_index.json");
      if (!r.ok) return;
      const j = await r.json();
      ITEMS.version = j.version || ITEMS.version;
      ITEMS.byName = j.byName || {};
      ITEMS.byId = j.byId || {};
      ITEMS.ready = true;
      if (_lastItemBuildState) {
        try { renderItemBuild(_lastItemBuildState); } catch (_) {}
      }
    } catch (_) { /* text-only fallback stays in effect */ }
  })();

  function _normItemName(s) {
    return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  }
  // Resolver tiers: (1) exact match, (2) key prefixes-query or query
  // prefixes-key (shortest wins), (3) first-6-chars prefix match. Handles
  // casual fixture names like "Rabadon's" → Rabadon's Deathcap and
  // "Luden's Companion" → Luden's Echo.
  const _itemResolveCache = new Map();
  function _resolveItemId(name) {
    const n = _normItemName(name);
    if (!n) return null;
    if (_itemResolveCache.has(n)) return _itemResolveCache.get(n);
    let id = ITEMS.byName[n] || null;
    if (!id) {
      let best = null;
      for (const k in ITEMS.byName) {
        if (k === n) { best = k; break; }
        if (k.startsWith(n) || n.startsWith(k)) {
          if (!best || k.length < best.length) best = k;
        }
      }
      if (!best && n.length >= 5) {
        const stem = n.slice(0, Math.min(n.length, 6));
        for (const k in ITEMS.byName) {
          if (k.startsWith(stem)) {
            if (!best || k.length < best.length) best = k;
          }
        }
      }
      if (best) id = ITEMS.byName[best];
    }
    _itemResolveCache.set(n, id);
    return id;
  }
  function _splitItemList(str, splitArrow) {
    // Accept "A, B, C" and "A → B → C" / "A -> B -> C".
    if (!str) return [];
    const sep = splitArrow ? /\s*(?:,|→|->)\s*/ : /\s*,\s*/;
    return String(str).split(sep).map(s => s.trim()).filter(Boolean);
  }

  // Quick item cost lookup from a separate index file. Loaded lazily.
  const ITEM_COSTS = { ready: false, byId: {} };
  (async () => {
    try {
      const r = await fetch("/data/items_costs.json");
      if (!r.ok) return;
      const j = await r.json();
      ITEM_COSTS.byId = j.byId || {};
      ITEM_COSTS.ready = true;
    } catch (_) { /* no-op */ }
  })();

  function renderItemTiles(container, names, opts) {
    opts = opts || {};
    container.innerHTML = "";
    if (!names.length) {
      container.textContent = "—";
      return;
    }
    const CAP = opts.cap || 6;   // glance-read cap — extra tiles summarized as "+N"
    const shown = names.slice(0, CAP);
    const extra = names.length - shown.length;
    const ver = ITEMS.version;
    shown.forEach((name, i) => {
      const tile = document.createElement("div");
      tile.className = "item-tile";
      const iid = _resolveItemId(name);
      // Tooltip: item name + cost + (if provided) coach's reason for the
      // build choice. Reasons are looked up from opts.reasons[name] — the
      // coach populates this via p.item_build_reasons (or equivalent)
      // when available; otherwise the tooltip just shows name + cost.
      const reason = opts.reasons && opts.reasons[name];
      const cost = iid && ITEM_COSTS.byId[iid] ? `${ITEM_COSTS.byId[iid]}g` : "";
      const parts = [name];
      if (cost) parts.push(cost);
      if (reason) parts.push(reason);
      tile.title = parts.join(" — ");
      const iconWrap = document.createElement("div");
      iconWrap.className = "item-icon";
      if (iid) {
        const img = document.createElement("img");
        // Local-first: use cached asset under /data/ddragon/<ver>/img/item;
        // fall back to the CDN if the cache miss. Keeps us match-proof
        // against ISP/CDN hiccups.
        img.src = `/data/ddragon/${ver}/img/item/${iid}.png`;
        img.alt = name;
        img.loading = "lazy";
        img.onerror = () => {
          if (!img.dataset.cdnRetry) {
            img.dataset.cdnRetry = "1";
            img.src = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png`;
          } else {
            iconWrap.classList.add("no-icon");
            img.remove();
          }
        };
        iconWrap.appendChild(img);
      } else {
        iconWrap.classList.add("no-icon");
      }
      const label = document.createElement("div");
      label.className = "item-name";
      // (2026-04-26) Per-item display overrides for names that wrap awkwardly
      // in the 70px tile. Use `\n` to force a clean break at a syllable
      // boundary; CSS `white-space: pre-line` on .item-name honors it while
      // -webkit-line-clamp still caps total lines.
      const _ITEM_DISPLAY = { "Morellonomicon": "Morello\nnomicon" };
      label.textContent = _ITEM_DISPLAY[name] || name;
      // Highlight the first tile in a path as "next to buy", and attach a
      // gold/cost caption if we have both numbers.
      if (opts.withArrows && i === 0) {
        tile.classList.add("next-up");
        if (iid && ITEM_COSTS.byId[iid] && typeof opts.currentGold === "number") {
          const cost = ITEM_COSTS.byId[iid];
          const pct = Math.max(0, Math.min(1, opts.currentGold / cost));
          tile.style.setProperty("--buy-pct", (pct * 100).toFixed(0) + "%");
          if (pct >= 1) tile.classList.add("can-afford");
          // Gold caption: "need N" = remaining gold to complete the buy.
          // TODO: subtract owned sub-item values once items_recipes.json is
          // generated — for now N = cost − currentGold, clamped to 0 for
          // the can-afford case.
          const need = Math.max(0, Math.round(cost - opts.currentGold));
          const cap = document.createElement("div");
          cap.className = "item-cost";
          cap.textContent = need === 0 ? "ready" : ("need " + need);
          tile.appendChild(cap);
        }
      }
      tile.appendChild(iconWrap);
      tile.appendChild(label);
      container.appendChild(tile);
      if (opts.withArrows && i < shown.length - 1) {
        const arrow = document.createElement("div");
        arrow.className = "item-arrow";
        arrow.textContent = "→";
        container.appendChild(arrow);
      }
    });
    if (extra > 0) {
      const more = document.createElement("div");
      more.className = "item-tile item-more";
      more.title = names.slice(CAP).join(", ");
      more.innerHTML = `<div class="item-icon no-icon">+${extra}</div><div class="item-name">more</div>`;
      container.appendChild(more);
    }
  }

  // 2026-04-26: Track the active loadout label per (champion+mode) so the
  // ITEM BUILD header can show "<Champion> · <Variant Label>" instead of
  // the static "Recommended · next to buy". Cache + lazy-fetch from
  // /api/loadout/list so we don't hammer the endpoint on every render.
  const _itemBuildLabelCache = {};
  function _updateItemBuildHeader(champion, mode) {
    const labelEl = document.getElementById("ib-build-label");
    if (!labelEl) return;
    if (!champion) {
      labelEl.textContent = "Recommended · next to buy";
      return;
    }
    const cacheKey = champion + "|" + (mode || "");
    const cached = _itemBuildLabelCache[cacheKey];
    if (cached !== undefined) {
      labelEl.textContent = cached
        ? `${champion} · ${cached}`
        : `${champion} · Build`;
      return;
    }
    // Lazy fetch
    _itemBuildLabelCache[cacheKey] = null;   // mark in-flight
    fetch("/api/loadout/list", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ champion: champion, mode: mode || "aram" }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        let activeLabel = "";
        if (data && data.variants && data.variants.length) {
          // Prefer the chosen variant from cs-loadout state if it's for
          // this champion; otherwise use the default.
          const chosen = (typeof _csLoadout !== "undefined" && _csLoadout.chosen) || "";
          const defaultKey = data.default || "";
          const matchKey = chosen || defaultKey || data.variants[0].key;
          const found = data.variants.find((v) => v.key === matchKey);
          activeLabel = (found && found.label) || "";
        }
        _itemBuildLabelCache[cacheKey] = activeLabel;
        labelEl.textContent = activeLabel
          ? `${champion} · ${activeLabel}`
          : `${champion} · Build`;
      })
      .catch(() => {
        _itemBuildLabelCache[cacheKey] = "";
        labelEl.textContent = `${champion} · Build`;
      });
  }

  function renderItemBuild(p) {
    _lastItemBuildState = p;
    const arena = isArenaPayload(p);
    // Update header label with champion + active variant.
    _updateItemBuildHeader(p.champion, state.mode);
    // In-game multi-build picker (2026-04-26 user request) — mirrors the
    // cs-build-list inside ITEM BUILD, lets the user hot-swap the item
    // set mid-game. Runes + summoners are locked at game start so we
    // only push items; the LCU agent updates the recommended shop order.
    _ibMaybeRenderBuilds(p);
    const owned = _splitItemList(p.items_display || p.items, false);
    const path = _splitItemList(p.item_build, true);
    // Defensive dedup: a coach payload occasionally leaves an already-owned
    // item at the front of the build-path array (e.g. Zhonya's appears in
    // both Owned and Recommended → "next to buy" highlights a completed
    // item). Strip anything already owned from the Recommended path so the
    // UI can never surface that logic error.
    // Matching is substring-both-ways because the coach uses short forms
    // in build-path ("Zhonya's") and long forms in items_display
    // ("Zhonya's Hourglass"). Exact-match would let the dupe through.
    const _norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const ownedNorm = owned.map(_norm).filter(s => s.length >= 3);
    const pathDedup = path.filter(n => {
      const pn = _norm(n);
      if (pn.length < 3) return true;
      return !ownedNorm.some(o => o.includes(pn) || pn.includes(o));
    });
    // Coach can emit per-item reasons via p.item_build_reasons (a map from
    // item name → short one-liner). Passed to the Recommended tiles so
    // hover shows the "why this next" coaching note. Owned tiles just
    // show name + cost (no reason — it's already bought).
    const itemReasons = (p && p.item_build_reasons) || {};
    renderItemTiles(IB.owned, owned, { withArrows: false });
    renderItemTiles(IB.recommended, pathDedup, {
      withArrows: true, currentGold: p.gold, reasons: itemReasons,
    });
    // Augments pill (header row 2) — always-visible per the static-pill
    // rule. Content = comma-separated list of augments the player
    // currently possesses (not advice). Mode-gated:
    //   arena → always has augments (3 picks per game)
    //   aram  → assumes Mayhem (user's default ARAM; internal mode code is
    //           KIWI — see core/game_snapshot.py where KIWI → MODE_ARAM)
    //   tft   → Set 17+ adds gods + augments; gated later when TFT returns
    //   other → static "Mode does not support Augments" placeholder
    if (IB.augments) {
      const mode = state.mode;
      const modeSupportsAugments = arena || mode === "aram";   // TODO: tft set 17+
      let content = "";
      if (modeSupportsAugments) {
        const owned = fmtList(p.augments);
        content = owned || "(none picked yet)";
        content = content.replace(/\s*\n+\s*/g, ", ").trim();
      } else {
        content = "Mode does not have augments";
      }
      IB.augments.textContent = content;
      IB.augments.classList.remove("hidden");
      IB.augments.classList.toggle("no-support", !modeSupportsAugments);
      // No tooltip when the pill carries real augment content — hover
      // produces tiny unreadable text. Tooltip only helps on the muted
      // "not supported" placeholder.
      IB.augments.title = modeSupportsAugments ? "" : content;
    }
    state.lastTouch.item_build = Date.now() / 1000;
  }

  // ── Arena helpers ───────────────────────────────────────────────────
  // Partner synergy one-liners for the Caitlyn Arena build. Keyed on the
  // partner champion detected from the teams payload; falls back to a
  // generic line if we don't have a canned combo for this matchup.
  const CAITLYN_PARTNER_COMBOS = {
    "Lux":      "Wait for Q root → headshot → R through rooted. Stay 550u behind her shield line.",
    "Orianna":  "Ball on you. Ori R pulls enemies → your trap+R. Net AWAY to drag the ball.",
    "Zoe":      "NEVER engage first. Wait for E sleep → headshot doubles damage → R finisher.",
    "Morgana":  "Q binds = free headshots. E shield blocks their CC; all-in inside her shield.",
    "Leona":    "She engages E+Q, you trap-headshot during her CC chain. Kite after the stun drops.",
    "Nami":     "Nami Q bubble = free headshot. Stay in her E AS-buff range during trades.",
    "Lulu":     "Lulu W polymorph = free headshot. Stay in her shield during all-ins.",
    "Janna":    "Janna shield bonus AD on your autos. R disengage lets you kite-reset any fight.",
    "Soraka":   "Sustain pair — poke with R + traps, she globals you at 30% HP. Avoid all-ins.",
    "Seraphine":"Triple-note stun = full burst window. Stack her shield then all-in.",
  };
  function arenaDetectPartner(p) {
    if (!Array.isArray(p.teams)) return "";
    const partner = p.teams.find(t => t && t.is_partner);
    if (!partner) return "";
    return String(partner.name || partner.champion || "").trim();
  }
  function arenaPartnerLine(p) {
    const partner = arenaDetectPartner(p);
    if (!partner) {
      // Pre-game: surface the planned partner from the pregame card header.
      const pre = safe(p.pregame);
      const m = pre.match(/PARTNER:\s*([A-Za-z][A-Za-z']+)/);
      if (m) {
        // Pregame header is all-caps ("PARTNER: LUX"); combo table is title-case.
        const name = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
        return `${name} (planned) — ${CAITLYN_PARTNER_COMBOS[name] || "synergy loads at game start."}`;
      }
      return "—";
    }
    const combo = CAITLYN_PARTNER_COMBOS[partner] || "Stay 550-600u back. Peel for each other.";
    return `${partner} — ${combo}`;
  }
  function arenaWaveLine(p) {
    if (p.camp_phase) return "CAMP — buy/upgrade + heal";
    if (!Array.isArray(p.teams)) return "—";
    const nxt = p.teams.find(t => t && t.is_next_opponent);
    if (nxt) {
      const hp = nxt.hp_pct != null ? ` (${nxt.hp_pct}% HP)` : "";
      return `vs ${nxt.name || nxt.champion || "?"}${hp}`;
    }
    return "—";
  }

  // Live game-time tracker — extrapolates current game-time from the
  // last-received envelope so objective countdowns tick every second
  // without needing a server push each time.
  state.gameClock = { startedAt: 0, anchorS: 0, raw: "" };
  function _updateGameClock(p) {
    const s = (typeof p.game_time_s === "number") ? p.game_time_s : null;
    if (s != null) {
      state.gameClock.startedAt = Date.now();
      state.gameClock.anchorS = s;
      state.gameClock.raw = p.game_time || "";
      _applyGamePhase(s);
    } else if (p.game_time) {
      state.gameClock.raw = p.game_time;
    }
  }
  // Three phases mapped to body[data-phase] so CSS can tint subtly:
  //   early  < 15:00   (calm blue)
  //   mid    15–25:00  (engaged gold)
  //   late   25:00+    (urgent coral)
  let _lastPhase = null;
  function _applyGamePhase(gtS) {
    const phase = gtS < 900 ? "early" : gtS < 1500 ? "mid" : "late";
    const strip = el("phase-strip"), marker = el("phase-marker");
    if (phase !== _lastPhase) {
      _lastPhase = phase;
      document.body.dataset.phase = phase;
      // Mark transition — briefly pulse the marker + announce via status.
      if (marker && _lastPhase) {
        marker.classList.remove("phase-transition");
        void marker.offsetWidth;
        marker.classList.add("phase-transition");
      }
    }
    if (strip && marker) {
      strip.classList.remove("hidden");
      // Match-length denominator by mode. ARAM games are much shorter.
      const typicalS = state.mode === "aram" ? 1200   // ~20min
                     : state.mode === "arena" ? 900   // ~15min per lobby avg
                     : state.mode === "tft"   ? 1800  // ~30min
                     : 2280;                          // SR ~38min
      const ratio = Math.max(0, Math.min(1, gtS / typicalS));
      marker.style.left = (ratio * 100).toFixed(1) + "%";
    }
  }
  function _currentGameTimeS() {
    if (!state.gameClock.startedAt) return null;
    return state.gameClock.anchorS + (Date.now() - state.gameClock.startedAt) / 1000;
  }
  function _fmtMMSS(s) {
    s = Math.max(0, Math.round(s));
    const m = Math.floor(s / 60), ss = s % 60;
    return `${m}:${ss.toString().padStart(2, "0")}`;
  }
  // Extract "spawns MM:SS" or "next MM:SS" or "in N:SS" from objective text
  // so we can surface a live countdown chip alongside the narrative state.
  function _extractSpawnTime(text) {
    if (!text) return null;
    const m = String(text).match(/\b(?:spawns?|next|in)\s+(\d{1,2}):(\d{2})\b/i);
    if (!m) return null;
    return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
  }

  // Track latest adaptation counters so enemy portraits can surface the
  // hard-matchup ring without needing a second fetch.
  state.adaptCounterMap = {};  // normalized-enemy-name → { wr_delta, kda_delta }

  function renderTeamTile(name, opts) {
    opts = opts || {};
    // Wrap portrait + spell stack in a vertical container so spells sit below.
    const wrap = document.createElement("div");
    wrap.className = "team-tile-wrap";
    const tile = document.createElement("div");
    tile.className = "team-tile";
    if (opts.isSelf) tile.classList.add("is-self");
    let title = name;
    if (opts.counter && opts.counter.delta <= -0.10) {
      tile.classList.add("danger");
      title += `  · ${Math.round(opts.counter.delta * 100)}% wr vs you`;
    } else if (opts.counter && opts.counter.delta >= 0.10) {
      tile.classList.add("favorable");
      title += `  · +${Math.round(opts.counter.delta * 100)}% wr vs you`;
    }
    tile.title = title;
    const cid = _resolveChampId(name);
    if (cid) {
      const img = document.createElement("img");
      img.src = `/data/ddragon/${CHAMPS.version}/img/champion/${cid}.png`;
      img.alt = name;
      img.onerror = () => { img.remove(); tile.classList.add("no-icon"); tile.textContent = (name||"?")[0]; };
      tile.appendChild(img);
    } else {
      tile.classList.add("no-icon");
      tile.textContent = (name || "?")[0];
    }
    // Target-priority crosshair — the coach's "focus this one" flag.
    if (opts.isTarget) {
      tile.classList.add("target");
    }
    // Dead overlay — coral ring + respawn timer inside the portrait.
    if (typeof opts.respawnIn === "number" && opts.respawnIn > 0) {
      tile.classList.add("dead");
      const rt = document.createElement("span");
      rt.className = "respawn-timer";
      rt.textContent = opts.respawnIn;
      rt.dataset.respawnAnchor = Date.now();
      rt.dataset.respawnStart  = opts.respawnIn;
      tile.appendChild(rt);
    }
    wrap.appendChild(tile);
    // Spell slots: render d+f (or however many we have) as tiny badges.
    // Each spell may be a plain name or {spell, cd_remaining_s}.
    if (opts.spells && opts.spells.length) {
      const spellsRow = document.createElement("div");
      spellsRow.className = "tile-spells";
      opts.spells.slice(0, 2).forEach(s => {
        const sname = typeof s === "string" ? s : s.spell;
        const spell = _resolveSpell(sname);
        const cell = document.createElement("span");
        cell.className = "tile-spell";
        cell.dataset.cdKey = _spellKey(name, sname);
        if (spell) {
          const img = document.createElement("img");
          img.src = `/data/ddragon/16.8.1/img/spell/${spell.img}`;
          img.alt = spell.name;
          img.onerror = () => { cell.classList.add("no-icon"); img.remove(); cell.textContent = spell.name[0]; };
          cell.appendChild(img);
          const cdLabel = document.createElement("b");
          cdLabel.className = "cd-label";
          cell.appendChild(cdLabel);
          cell.title = spell.name;
        } else {
          cell.classList.add("no-icon");
          cell.textContent = (sname || "?")[0];
        }
        spellsRow.appendChild(cell);
      });
      wrap.appendChild(spellsRow);
    }
    return wrap;
  }

  // Tick every second — pull current cd from state.spellCds and update
  // each cell's display. Avoids full strip re-render for just cd change.
  // Cheap no-op when tab is backgrounded.
  function _tickSpellCooldowns() {
    if (document.hidden) return;
    // Also decrement enemy respawn timers in place.
    document.querySelectorAll(".respawn-timer").forEach(rt => {
      const anchor = +rt.dataset.respawnAnchor;
      const start  = +rt.dataset.respawnStart;
      const rem = Math.max(0, Math.round(start - (Date.now() - anchor) / 1000));
      if (rem > 0) {
        rt.textContent = rem;
      } else {
        // Respawned — remove timer + unflag the dead class on parent tile.
        const tile = rt.closest(".team-tile");
        if (tile) tile.classList.remove("dead");
        rt.remove();
      }
    });
    // Combined selector — covers ally/enemy tile spells (.tile-spell)
    // AND the user's own header spells (.self-spell).
    document.querySelectorAll(".tile-spell[data-cd-key], .self-spell[data-cd-key]").forEach(cell => {
      const key = cell.dataset.cdKey;
      const rem = _currentSpellCd(key);
      const label = cell.querySelector(".cd-label");
      if (rem > 0) {
        cell.classList.add("on-cd");
        if (label) label.textContent = rem >= 60 ? Math.round(rem/60) + "m" : rem;
        cell.title = (cell.title.split(" — ")[0]) + ` — ${rem}s`;
      } else {
        // If the cell was on cooldown last tick, briefly flash "ready".
        if (cell.classList.contains("on-cd")) {
          cell.classList.add("cd-ready-flash");
          setTimeout(() => cell.classList.remove("cd-ready-flash"), 1100);
        }
        cell.classList.remove("on-cd");
        if (label) label.textContent = "";
      }
    });
  }
  setInterval(_tickSpellCooldowns, 1000);

  function renderAllyStrip(allies, selfChampion, spellsMap) {
    const row = el("ally-strip-row");
    const wrap = el("ally-strip");
    if (!row || !wrap) return;
    if (!Array.isArray(allies) || !allies.length) {
      wrap.classList.add("hidden");
      row.innerHTML = "";
      return;
    }
    wrap.classList.remove("hidden");
    row.innerHTML = "";
    const selfKey = String(selfChampion || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    allies.slice(0, 5).forEach(name => {
      const isSelf = selfKey && String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "") === selfKey;
      const spells = spellsMap && spellsMap[name];
      row.appendChild(renderTeamTile(name, { isSelf, spells }));
    });
  }

  function renderEnemyStrip(enemies, spellsMap, respawnMap, targetPriority) {
    const row = el("enemy-strip-row");
    const wrap = el("enemy-strip");
    if (!row || !wrap) return;
    if (!Array.isArray(enemies) || !enemies.length) {
      wrap.classList.add("hidden");
      row.innerHTML = "";
      return;
    }
    wrap.classList.remove("hidden");
    row.innerHTML = "";
    const priKey = String(targetPriority || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    enemies.slice(0, 5).forEach(name => {
      const k = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
      const counter = state.adaptCounterMap[k];
      const spells = spellsMap && spellsMap[name];
      const respawnIn = respawnMap ? respawnMap[name] : null;
      const isTarget = priKey && k === priKey;
      row.appendChild(renderTeamTile(name, { counter, isEnemy: true, spells, respawnIn, isTarget }));
    });
  }

  // Default spawn-cycle durations per objective (seconds) used as the
  // progress-bar denominator. Not scientific — Riot timings shift — but
  // gives a glanceable "how close are we" feel.
  const _OBJ_CYCLE = {
    dragon: 300,  // 5:00 between drakes
    baron:  360,  // 6:00 respawn after take
    herald: 360,
    atakhan: 300,
  };
  function _kindOf(elm) {
    if (!elm || !elm.id) return null;
    if (elm.id === "mm-dragon")  return "dragon";
    if (elm.id === "mm-baron")   return "baron";
    if (elm.id === "mm-herald")  return "herald";
    if (elm.id === "mm-atakhan") return "atakhan";
    return null;
  }
  // Minimap canvas renderer — Zone of Influence (ZOI) + position dots.
  //
  // ZOI: for each pixel, compute net "pressure" = Σ ally_pressure − Σ enemy_pressure.
  // Each champion contributes a compact-support "bubble" of influence — peaks
  // at 1 at the champ, falls smoothly to exactly 0 at radius R. Beyond R the
  // champion contributes nothing, so the DMZ (the low-|net| band) visibly
  // fills gaps between bubbles and bulges where opposing bubbles press into
  // each other. Positive pressure renders in my-team color, negative in
  // enemy color.
  //
  // Pressure math (Wendland-style, quadratic compact support):
  //   d² = (dist / RADIUS)²
  //   contribution = (1 - d²)²   when d < R,   else 0
  //   Multiple same-team champs in proximity stack (sum).
  //   Opposing team subtracts.
  //
  // Performance: render at 80×80 then upscale to canvas intrinsic size.
  // Re-runs on every state envelope (~3s in sim, whenever coach emits live).
  const ZOI = (() => {
    const q = new URLSearchParams(location.search);
    const pf = (k, d) => {
      const v = parseFloat(q.get(k));
      return isNaN(v) ? d : v;
    };
    return {
      loRes: 80,
      // Each champion influences within ~0.35 of map width. Tunable.
      radius: pf("zoi-R", 0.32),
      // Small deadband around net=0 stays transparent (the "DMZ").
      deadband: pf("zoi-DB", 0.10),
      // Baseline diagonal bias — top-left to bottom-right split (SR map).
      // Blue base is bot-left, red base is top-right. Champion pressure
      // warps this default. Keep weak so ganks + split-push still read.
      baselineStrength: pf("zoi-BL", 0.55),
    };
  })();
  // Phase-aware radius — early game champs are lane-contained, late game
  // they rotate freely. Called with game_time_s from the state envelope.
  function _zoiRadius(gtS) {
    if (typeof gtS !== "number") return ZOI.radius;
    if (gtS < 600)  return 0.22;   // <10:00 — tight lanes
    if (gtS < 1200) return 0.28;   // 10-20 — grouping phase
    if (gtS < 1800) return 0.34;   // 20-30 — rotations
    return 0.40;                    // 30+ — pure teamfight / split
  }
  // Compact-support influence bubble. d2 is (dist/R)² — already normalized
  // by the caller. Outside the bubble (d2 >= 1) the champion contributes
  // nothing, so the DMZ forms naturally in gaps and is pushed/pulled by
  // wherever bubbles actually reach.
  function _bubbleKernel(d2) {
    if (d2 >= 1) return 0;
    const t = 1 - d2;
    return t * t;
  }

  function _drawZoi(ctx, W, H, allies, enemies, myTeam, gtS) {
    const lo = ZOI.loRes;
    const off = document.createElement("canvas");
    off.width = lo; off.height = lo;
    const offCtx = off.getContext("2d");
    const img = offCtx.createImageData(lo, lo);
    const myIsRed = myTeam === "red";
    // Team color RGB.
    const myRGB    = myIsRed ? [240, 126, 139] : [138, 140, 240];   // coral vs lavender
    const enemyRGB = myIsRed ? [138, 140, 240] : [240, 126, 139];
    // Keep weights flat but summable. Radius in normalized units —
    // scales with game phase so late-game teamfights read wider.
    const R = _zoiRadius(gtS);
    const DB = ZOI.deadband;

    // Pre-flatten position arrays for tight inner loop.
    const A = Object.values(allies || {}).filter(Boolean);
    const E = Object.values(enemies || {}).filter(Boolean);

    // Baseline diagonal bias: SR blue base = bottom-left, red = top-right.
    // Diagonal from top-left (0,0) to bottom-right (1,1) is the neutral
    // line. For blue team, positive baseline on points BELOW the diagonal
    // (y > x). For red team, invert. Champion contributions add/subtract
    // from this, producing a warped curve.
    const BL = ZOI.baselineStrength;
    const baselineSign = myIsRed ? -1 : 1;
    // First pass: compute net-pressure at each low-res pixel into a temp
    // Float32 buffer so pass 2 can emit color with edge-line highlight.
    const netBuf = new Float32Array(lo * lo);
    for (let py = 0; py < lo; py++) {
      const ny = (py + 0.5) / lo;
      for (let px = 0; px < lo; px++) {
        const nx = (px + 0.5) / lo;
        // Baseline: (ny - nx) ∈ [-1, 1]; times sign+strength.
        let baseline = (ny - nx) * BL * baselineSign;
        let allyP = 0, enemyP = 0;
        for (let i = 0; i < A.length; i++) {
          const dx = nx - A[i].x, dy = ny - A[i].y;
          const d2 = (dx*dx + dy*dy) / (R*R);
          if (d2 < 1) { const t = 1 - d2; allyP += t * t; }
        }
        for (let i = 0; i < E.length; i++) {
          const dx = nx - E[i].x, dy = ny - E[i].y;
          const d2 = (dx*dx + dy*dy) / (R*R);
          if (d2 < 1) { const t = 1 - d2; enemyP += t * t; }
        }
        netBuf[py * lo + px] = baseline + allyP - enemyP;
      }
    }
    // Second pass: color + boundary line (edge where sign flips).
    for (let py = 0; py < lo; py++) {
      for (let px = 0; px < lo; px++) {
        const idx = py * lo + px;
        const net = netBuf[idx];
        const mag = Math.abs(net);
        // Detect sign-change neighbors for the boundary-line hint.
        let edge = false;
        if (mag < DB * 2) {
          const s = Math.sign(net);
          if (px+1 < lo && Math.sign(netBuf[idx+1]) !== s) edge = true;
          else if (py+1 < lo && Math.sign(netBuf[idx+lo]) !== s) edge = true;
        }
        let r, g, b, a;
        // Smooth exponential ramp: light pressure = subtle tint, heavy
        // concentration (3+ champs stacked) = near-cap saturation.
        // Scale chosen so 1 champion at influence radius ≈ half-cap.
        // Opacity caps tuned for SR underlay — 0.42/0.22 lets the map
        // read through the tint while still clearly team-coded.
        if (net > DB) {
          r = myRGB[0]; g = myRGB[1]; b = myRGB[2];
          a = 0.42 * (1 - Math.exp(-(mag - DB) / 0.7));
        } else if (net < -DB) {
          r = enemyRGB[0]; g = enemyRGB[1]; b = enemyRGB[2];
          a = 0.22 * (1 - Math.exp(-(mag - DB) / 0.7));
        } else {
          r = g = b = 0; a = 0;
        }
        if (edge) {
          // Boundary line between ally/enemy pressure — a soft gold stripe
          // that reads against both tinted zones without blend-mode tricks.
          r = 245; g = 184; b = 124; a = 0.75;
        }
        const p = idx * 4;
        img.data[p]   = r;
        img.data[p+1] = g;
        img.data[p+2] = b;
        img.data[p+3] = Math.round(a * 255);
      }
    }
    offCtx.putImageData(img, 0, 0);
    // Upscale with soft interpolation — looks like a gradient, not pixels.
    ctx.clearRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(off, 0, 0, W, H);
  }

  function renderMinimapCanvases(p) {
    const stack = el("mm-canvas-stack");
    const zoiCanvas = el("mm-zoi-canvas");
    const posCanvas = el("mm-pos-canvas");
    if (!stack || !posCanvas || !zoiCanvas) return;
    if (!p.positions || (!p.positions.allies && !p.positions.enemies)) {
      stack.classList.add("hidden");
      return;
    }
    stack.classList.remove("hidden");
    // Skip the 64k-pixel math + paint when the tab is not visible.
    // Latest state is still captured; next visibilitychange will redraw.
    if (document.hidden) {
      state.pendingZoi = p;
      return;
    }
    const myTeam = (p.my_team || "blue").toLowerCase();
    document.body.dataset.myteam = myTeam;
    const myColor = myTeam === "red" ? "#F07E8B" : "#8A8CF0";
    const enemyColor = myTeam === "red" ? "#8A8CF0" : "#F07E8B";

    // Drop positions for dead champions — they're not exerting pressure.
    // *_respawns keys → remaining seconds; >0 = dead, skip contribution.
    const deadE = new Set(Object.entries(p.enemy_respawns || {})
        .filter(([, s]) => typeof s === "number" && s > 0)
        .map(([n]) => n));
    const deadA = new Set(Object.entries(p.ally_respawns || {})
        .filter(([, s]) => typeof s === "number" && s > 0)
        .map(([n]) => n));
    const allies = Object.fromEntries(
      Object.entries(p.positions.allies || {}).filter(([n]) => !deadA.has(n)));
    const enemies = Object.fromEntries(
      Object.entries(p.positions.enemies || {}).filter(([n]) => !deadE.has(n)));

    // Paint ZOI layer first, dots on top.
    const zctx = zoiCanvas.getContext("2d");
    _drawZoi(zctx, zoiCanvas.width, zoiCanvas.height, allies, enemies, myTeam, p.game_time_s);

    const ctx = posCanvas.getContext("2d");
    const W = posCanvas.width, H = posCanvas.height;
    ctx.clearRect(0, 0, W, H);
    // Objective spawn markers — approximate SR positions. Draws a small
    // translucent icon glyph so the user has map landmarks without the
    // live PNG. ARAM doesn't have these; skip if mode differs.
    if (state.mode === "sr") {
      const marks = [
        { x: 0.68, y: 0.70, label: "D", color: "rgba(240,126,139,0.55)" },  // Dragon — bot-right river
        { x: 0.32, y: 0.30, label: "B", color: "rgba(192,139,150,0.55)" },  // Baron — top-left river
        { x: 0.32, y: 0.30, label: "H", color: "rgba(245,184,124,0.45)", offset: true },  // Herald — same pit pre-20
      ];
      ctx.save();
      ctx.font = "bold 11px Lato, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const m of marks) {
        const cx = Math.round(m.x * W), cy = Math.round(m.y * H) + (m.offset ? 16 : 0);
        ctx.fillStyle = "rgba(23,24,33,0.5)";
        ctx.beginPath();
        ctx.arc(cx, cy, 9, 0, Math.PI*2);
        ctx.fill();
        ctx.fillStyle = m.color;
        ctx.fillText(m.label, cx, cy);
      }
      ctx.restore();
    }
    function drawDot(x, y, color, isSelf) {
      const cx = Math.round(x * W), cy = Math.round(y * H);
      if (isSelf) {
        // Champion sight-range halo — ~1200 units on a 15000-unit SR map
        // ≈ 0.08 normalized. Thin gold stroke + soft glow. Gives the user
        // a "what can I actually see" read without flipping to the minimap.
        const vR = 0.085 * W;
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy, vR, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(245,184,124,0.55)";
        ctx.lineWidth = 1.5;
        ctx.shadowColor = "rgba(245,184,124,0.5)";
        ctx.shadowBlur = 8;
        ctx.stroke();
        ctx.restore();
      }
      ctx.beginPath();
      ctx.arc(cx, cy, isSelf ? 8 : 6, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      if (isSelf) {
        ctx.strokeStyle = "#F5B87C";
        ctx.lineWidth = 2.5;
        ctx.stroke();
        // "YOU" label above the dot (or below if too close to top).
        ctx.font = "bold 13px Lato, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const labelY = cy < 30 ? cy + 20 : cy - 18;
        const inDeep = document.body.dataset.zone === "deep";
        const labelBg = inDeep ? "rgba(74,42,49,0.95)" : "rgba(23,24,33,0.9)";
        const labelFg = inDeep ? "#F07E8B" : "#F5B87C";
        // Rounded backing when available (Chromium 99+), else fallback rect.
        if (ctx.roundRect) {
          ctx.fillStyle = labelBg;
          ctx.beginPath();
          ctx.roundRect(cx - 20, labelY - 9, 40, 18, 6);
          ctx.fill();
          ctx.strokeStyle = labelFg;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.roundRect(cx - 20, labelY - 9, 40, 18, 6);
          ctx.stroke();
        } else {
          ctx.fillStyle = labelBg;
          ctx.fillRect(cx - 20, labelY - 9, 40, 18);
        }
        ctx.fillStyle = labelFg;
        ctx.fillText("YOU", cx, labelY);
      } else {
        ctx.strokeStyle = "rgba(0,0,0,0.65)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
    const selfKey = String(p.champion || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    let selfPos = null;
    for (const name of Object.keys(allies)) {
      const pos = allies[name]; if (!pos) continue;
      const isSelf = String(name).toLowerCase().replace(/[^a-z0-9]/g, "") === selfKey;
      if (isSelf) selfPos = pos;
      drawDot(pos.x, pos.y, myColor, isSelf);
    }
    // Compute pressure at user's position to surface a "zone" chip.
    if (selfPos) {
      const myIsRed = myTeam === "red";
      const baselineSign = myIsRed ? -1 : 1;
      let netAtSelf = (selfPos.y - selfPos.x) * ZOI.baselineStrength * baselineSign;
      const _R = _zoiRadius(p.game_time_s);
      for (const key of Object.keys(allies)) {
        const q = allies[key]; if (!q || key.toLowerCase().replace(/[^a-z0-9]/g,"") === selfKey) continue;
        const dx = selfPos.x - q.x, dy = selfPos.y - q.y;
        const d2 = (dx*dx + dy*dy) / (_R * _R);
        netAtSelf += _bubbleKernel(d2);
      }
      for (const key of Object.keys(enemies)) {
        const q = enemies[key]; if (!q) continue;
        const dx = selfPos.x - q.x, dy = selfPos.y - q.y;
        const d2 = (dx*dx + dy*dy) / (_R * _R);
        netAtSelf -= _bubbleKernel(d2);
      }
      // ?debug=1 — show ZOI pressure readouts under the legend.
      if (/[?&]debug=1/.test(location.search)) {
        const dbg = el("zoi-debug");
        if (dbg) {
          dbg.classList.remove("hidden");
          dbg.textContent =
            `R=${_zoiRadius(p.game_time_s).toFixed(2)} · baseline ${ZOI.baselineStrength}` +
            ` · deadband ${ZOI.deadband} · self-pressure ${netAtSelf.toFixed(2)}`;
        }
      }
      const zonePill = el("zone-pill"), zoneLabel = el("zone-label");
      if (zonePill && zoneLabel) {
        zonePill.classList.remove("hidden");
        if (netAtSelf < -ZOI.deadband) {
          // Deep-enemy-territory escalation: < -3*DB is the "you are
          // clearly deeper than just adjacent to enemy influence" bar.
          // Empirically: sr_gank_scenario (3 enemies stacked, 1 isolated ally)
          // clears the bar; teamfight (5v5) does NOT.
          const deep = netAtSelf < -ZOI.deadband * 3;
          zoneLabel.textContent = deep ? "⛔ DEEP ENEMY" : "⚠ ENEMY ZONE";
          zonePill.className = "zone-pill zone-enemy" + (deep ? " zone-deep" : "");
          document.body.dataset.zone = deep ? "deep" : "enemy";
        } else if (netAtSelf > ZOI.deadband) {
          zoneLabel.textContent = "✓ SAFE";
          zonePill.className = "zone-pill zone-safe";
          document.body.dataset.zone = "safe";
        } else {
          zoneLabel.textContent = "— DMZ";
          zonePill.className = "zone-pill zone-dmz";
          document.body.dataset.zone = "dmz";
        }
      }
    } else {
      delete document.body.dataset.zone;
      const zonePill = el("zone-pill");
      if (zonePill) zonePill.classList.add("hidden");
    }
    // Ghost-marker bookkeeping (2026-04-26 user request): when an enemy
    // dot hasn't moved in a few seconds, fade it and ring it with a
    // clock-face age sweep so the user can read at-a-glance "this enemy
    // is roaming / missing, not actually here." Positions are floats
    // 0-1; we treat <0.005 movement (≈3.6px on the 720-canvas) as
    // "stationary." Entries are dropped when the enemy leaves the frame.
    state.lastEnemyPos ||= {};
    for (const k of Object.keys(state.lastEnemyPos)) {
      if (!(k in enemies)) delete state.lastEnemyPos[k];
    }
    const _ghostNow   = Date.now();
    const _ghostStart = 4000;   // ms before fade begins
    const _ghostEnd   = 12000;  // ms after which dot is hidden entirely
    for (const name of Object.keys(enemies)) {
      const pos = enemies[name]; if (!pos) continue;
      const prev = state.lastEnemyPos[name];
      const dx = prev ? Math.abs(pos.x - prev.x) : 1;
      const dy = prev ? Math.abs(pos.y - prev.y) : 1;
      if (!prev || dx > 0.005 || dy > 0.005) {
        state.lastEnemyPos[name] = { x: pos.x, y: pos.y, t: _ghostNow };
      }
      const age = _ghostNow - state.lastEnemyPos[name].t;
      if (age >= _ghostEnd) continue;  // too stale to draw
      if (age > _ghostStart) {
        const fadeT = (age - _ghostStart) / (_ghostEnd - _ghostStart);
        ctx.save();
        ctx.globalAlpha = 1 - fadeT * 0.7;  // 1.0 → 0.3
        drawDot(pos.x, pos.y, enemyColor, false);
        const cx = Math.round(pos.x * W), cy = Math.round(pos.y * H);
        ctx.beginPath();
        ctx.arc(cx, cy, 11, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * fadeT);
        ctx.strokeStyle = enemyColor;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();
      } else {
        drawDot(pos.x, pos.y, enemyColor, false);
      }
    }
  }

  function renderGoldDiff(p) {
    const wrap = el("gold-diff");
    const fill = el("gold-diff-fill");
    const lbl = el("gold-diff-val");
    if (!wrap || !fill || !lbl) return;
    const diff = typeof p.team_gold_diff === "number" ? p.team_gold_diff : null;
    if (diff == null) {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    // Clamp to ±10k for the fill bar scale.
    const clamp = Math.max(-10000, Math.min(10000, diff));
    const pct = Math.abs(clamp) / 10000;
    // Left edge is 50% (center). Fill extends right (ahead) or left (behind).
    if (clamp >= 0) {
      fill.style.left = "50%";
      fill.style.right = `${50 - pct * 50}%`;
      fill.classList.remove("behind");
      fill.classList.add("ahead");
    } else {
      fill.style.right = "50%";
      fill.style.left = `${50 - pct * 50}%`;
      fill.classList.remove("ahead");
      fill.classList.add("behind");
    }
    const signed = clamp >= 0 ? `+${clamp.toLocaleString()}` : clamp.toLocaleString();
    lbl.textContent = signed;
    lbl.className = clamp >= 0 ? "gd-ahead" : "gd-behind";
  }

  function _tickObjectiveCountdowns() {
    const nowS = _currentGameTimeS();
    for (const elm of [MM.dragon, MM.baron, MM.herald]) {
      if (!elm) continue;
      const raw = elm.dataset.raw || "—";
      if (nowS == null) { elm.textContent = raw; continue; }
      const target = _extractSpawnTime(raw);
      // Find (or lazy-create) the tick progress bar on the containing .kv row.
      const row = elm.closest(".kv");
      let bar = row && row.querySelector(".obj-bar");
      if (row && !bar) {
        bar = document.createElement("i");
        bar.className = "obj-bar";
        row.appendChild(bar);
      }
      if (target == null) {
        elm.textContent = raw;
        if (bar) bar.style.setProperty("--pct", "0%");
        continue;
      }
      const remaining = target - nowS;
      const cycle = _OBJ_CYCLE[_kindOf(elm)] || 300;
      // Ratio of progress toward spawn (0 = just went down, 1 = up now).
      const progress = Math.max(0, Math.min(1, 1 - (remaining / cycle)));
      if (bar) bar.style.setProperty("--pct", (progress * 100).toFixed(1) + "%");
      if (remaining <= 0) {
        elm.textContent = raw.replace(/\b(?:spawns?|next|in)\s+\d{1,2}:\d{2}\b/i, "UP NOW");
        elm.classList.add("obj-up");
        if (bar) bar.classList.add("full");
      } else {
        elm.textContent = raw.replace(
          /\b(?:spawns?|next|in)\s+\d{1,2}:\d{2}\b/i,
          `in ${_fmtMMSS(remaining)}`
        );
        elm.classList.toggle("obj-soon", remaining < 45);
        elm.classList.remove("obj-up");
        if (bar) bar.classList.remove("full");
      }
    }
  }
  // Tick every 1s — objective countdowns are the primary live pulse.
  // Skip work entirely when the tab is hidden (iPad battery / CPU).
  setInterval(() => {
    if (document.hidden) return;
    _tickObjectiveCountdowns();
    const s = _currentGameTimeS();
    if (s != null) {
      const str = _fmtMMSS(s);
      gameTime.textContent = str;
      if (MM.gameTime) MM.gameTime.textContent = str;
    }
  }, 1000);

  function renderMinimap(p) {
    _updateGameClock(p);
    // Coaching-JSON fields surface objective state when the coach has
    // computed it. When absent, keep the placeholder. Fields queried:
    //   p.dragon_state / p.dragon_stack / p.soul — if the coach computed them
    //   p.baron_alive / p.baron_timer
    //   p.herald_alive / p.atakhan_state
    //   p.my_tower_hp / p.enemy_tower_hp (ARAM) or towers_us/towers_them (SR)
    //   p.kda_aggregate (team score)
    //   p.game_time / p.game_time_s
    // Store the raw state text in data-raw so the countdown tick can
    // re-render from it without a fresh state envelope.
    // Strip "(Cloud taken 12:04)" / "(Chemtech taken 8:30)" style parentheticals
    // — the kill count + next-spawn line already convey the important bits;
    // the parenthetical just eats horizontal space.
    const _cleanObj = s => String(s || "—")
      .replace(/\s*\([^)]*taken[^)]*\)\s*/gi, " ")
      .replace(/  +/g, " ")
      .trim() || "—";
    for (const [elm, val] of [
      [MM.dragon,  _cleanObj(p.dragon_state  || p.dragon)],
      [MM.baron,   _cleanObj(p.baron_state   || p.baron)],
      [MM.herald,  _cleanObj(p.herald_state  || p.herald)],
    ]) {
      if (elm) elm.dataset.raw = val;
    }
    _tickObjectiveCountdowns();
    // Merge spell cooldown snapshots before we (re-)render the strips so
    // each tile can read the up-to-date state.spellCds values.
    _snapshotSpells(p.ally_spells);
    _snapshotSpells(p.enemy_spells);
    renderAllyStrip(p.ally_comp || p.team_comp, p.champion, p.ally_spells);
    renderEnemyStrip(p.enemy_comp, p.enemy_spells, p.enemy_respawns, p.target_priority);
    _tickSpellCooldowns();
    renderGoldDiff(p);
    renderMinimapCanvases(p);
    // Tower count / team kills / game time chips were removed from the
    // Map State panel 2026-04-23 — those signals live on the header row 2.
    // Guarded writes so the removal doesn't require touching MM init.
    if (MM.towers) {
      const tUs = p.towers_us ?? p.my_tower_hp;
      const tThem = p.towers_them ?? p.enemy_tower_hp;
      MM.towers.textContent = (tUs != null && tThem != null) ? `${tUs} / ${tThem}` : "—";
    }
    if (MM.score) MM.score.textContent = p.score || p.team_score || p.kda_aggregate || "—";
    if (MM.gameTime) {
      MM.gameTime.textContent = (typeof p.game_time_s === "number")
        ? _fmtMMSS(p.game_time_s) : (p.game_time || "—");
    }

    // Live marker when we have ANY real datum; otherwise scaffold.
    const hasAny = !!(p.dragon_state || p.baron_state || p.herald_state
                     || p.atakhan_state || p.my_tower_hp != null
                     || p.towers_us != null || p.game_time);
    MM.status.className = "minimap-state" + (hasAny ? " live" : "");
    // Dynamic status line — more actionable than the old dev-y scaffold text.
    // 2026-04-26: hide the pill entirely when we have liveclient AND the
    // minimap image is showing — the live cropped minimap is the primary
    // signal; "waiting on positions" is just noise that overlaps the map
    // visually. Only show the pill when there's something useful to say
    // (ZOI populated) or no data at all (offline state).
    if (hasAny) {
      const allyCount = p.positions?.allies ? Object.keys(p.positions.allies).length : 0;
      const enemyCount = p.positions?.enemies ? Object.keys(p.positions.enemies).length : 0;
      if (allyCount || enemyCount) {
        _renderMmStateLine(MM.status, allyCount, enemyCount);
        MM.status.classList.remove("hidden");
      } else {
        // Liveclient up but no positions yet — hide the pill so it
        // doesn't sit on top of the minimap image.
        MM.status.textContent = "";
        MM.status.classList.add("hidden");
      }
    } else {
      MM.status.textContent = "awaiting liveclient data…";
      MM.status.classList.remove("hidden");
    }
    state.lastTouch.minimap = Date.now() / 1000;
  }

  // Heartbeat-styled live state line. Builds a ♥-pulse + counts +
  // self-aging "Xs ago" suffix so the user reads "this is live" without
  // having to compare numbers across renders. The pulse re-fires every
  // call by removing then re-adding the .pulse class on the next frame.
  // The age suffix is auto-updated by a 1s setInterval (registered once).
  function _renderMmStateLine(host, allyCount, enemyCount) {
    if (!host) return;
    if (!host._wired) {
      host._wired = true;
      host.innerHTML = '<span class="mm-heart" aria-hidden="true"></span>'
        + '<span class="mm-counts">— · —</span>'
        + '<span class="mm-age">0s ago</span>';
      // Single global timer; re-uses host._lastT as the source of truth.
      setInterval(() => {
        const ageEl = host.querySelector(".mm-age");
        if (!ageEl || !host._lastT) return;
        const dt = Math.max(0, Math.round((Date.now() - host._lastT) / 1000));
        ageEl.textContent = dt + "s ago";
        // Fade the heartbeat as data goes stale (>15s = no live signal).
        const heart = host.querySelector(".mm-heart");
        if (heart) heart.style.opacity = dt > 15 ? "0.18" : (dt > 5 ? "0.4" : "");
      }, 1000);
    }
    host._lastT = Date.now();
    const counts = host.querySelector(".mm-counts");
    if (counts) counts.textContent = `${allyCount} ally · ${enemyCount} enemy`;
    const age = host.querySelector(".mm-age");
    if (age) age.textContent = "0s ago";
    const heart = host.querySelector(".mm-heart");
    if (heart) {
      heart.style.opacity = "";
      heart.classList.remove("pulse");
      // Force reflow so the next addClass restarts the animation.
      void heart.offsetWidth;
      heart.classList.add("pulse");
    }
  }

  // Lightweight ephemeral burst above the KDA pill — kill/assist/death
  // surfaces briefly then fades. One-shot DOM elements so overlaps
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
        // CSS also — CSS/m (creep-score per minute) as tooltip.
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
      // color class (carry/even/struggle) but no longer rendered as text —
      // the color communicates performance band at a glance.
      const m = /^(\d+)\/(\d+)\/(\d+)$/.exec(safe(p.kda));
      if (m) {
        const K = +m[1], D = +m[2], A = +m[3];
        const r = D === 0 ? (K + A) : (K + A) / D;
        kdaRatioClass = r >= 3 ? "kda-carry" : r >= 1.5 ? "kda-even" : "kda-struggle";
      }
      const newText = safe(p.kda);
      if (kdaEl.textContent !== newText && kdaEl.textContent !== "—") {
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
    // Live win probability pill — hidden if state doesn't provide it.
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
    // Mana / resource bar — hidden when champion has none (Tryndamere etc)
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
    // Skip the DOM build entirely when the slot is hidden by CSS — the
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
            img.src = `/data/ddragon/16.8.1/img/spell/${spell.img}`;
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
        // D / F placeholders — matches League's default hotkey convention
        // for summoner spells so the reader's mental model is consistent.
        ["D", "F"].forEach(letter => {
          const cell = document.createElement("span");
          cell.className = "self-spell placeholder";
          cell.textContent = letter;
          cell.title = `summoner ${letter} — no data`;
          selfSpellsEl.appendChild(cell);
        });
      }
    }
    // Dynamic page title — mode + champion, falls back to mode-only.
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

  // Champion icon resolver (loaded async from /data/champions_index.json).
  const CHAMPS = { ready: false, version: "16.8.1", byName: {}, byId: {} };
  (async () => {
    try {
      // (2026-04-26) Cache-bust query to defeat aggressive PWA/SW caching on
      // iPad. champions_index.json was rebuilt iter 35 with proper byId
      // numeric→name mapping; without the bust, old broken file stays cached.
      const r = await fetch("/data/champions_index.json?v=2026-04-26");
      if (!r.ok) return;
      const j = await r.json();
      CHAMPS.version = j.version || CHAMPS.version;
      CHAMPS.byName = j.byName || {};
      CHAMPS.byId = j.byId || {};
      CHAMPS.ready = true;
    } catch (_) { /* pill-text fallback still works */ }
  })();
  function _resolveChampId(name) {
    const n = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    if (!n) return null;
    return CHAMPS.byName[n] || null;
  }

  // Summoner spell icon resolver — loaded async from /data/spells_index.json.
  const SPELLS = { ready: false, byName: {} };
  (async () => {
    try {
      const r = await fetch("/data/spells_index.json");
      if (!r.ok) return;
      const j = await r.json();
      SPELLS.byName = j.byName || {};
      SPELLS.ready = true;
    } catch (_) { /* silent */ }
  })();
  function _resolveSpell(name) {
    const k = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    return SPELLS.byName[k] || null;
  }

  // Live spell-cooldown state. Each key is champion|spell, value is
  // {remaining: seconds, anchor: Date.now()}. On state re-emit we
  // snapshot, on tick we recompute visible remaining time.
  state.spellCds = {};
  function _spellKey(champ, spell) {
    return (champ || "") + "|" + (spell || "");
  }
  function _snapshotSpells(spellsMap) {
    // Merge fresh spell cooldowns from the state payload.
    // Only overwrite when the incoming timer is meaningfully different
    // to avoid resetting a smooth tick on every 3s re-emit.
    const now = Date.now();
    for (const champ of Object.keys(spellsMap || {})) {
      const slots = spellsMap[champ] || [];
      slots.forEach(s => {
        if (typeof s !== "object" || !s.spell) return;
        const key = _spellKey(champ, s.spell);
        const incoming = typeof s.cd_remaining_s === "number" ? s.cd_remaining_s : 0;
        const prev = state.spellCds[key];
        if (!prev || Math.abs(prev.remaining - _currentSpellCd(key)) > 2) {
          state.spellCds[key] = { remaining: incoming, anchor: now };
        }
      });
    }
  }
  function _currentSpellCd(key) {
    const rec = state.spellCds[key];
    if (!rec) return 0;
    const elapsed = (Date.now() - rec.anchor) / 1000;
    return Math.max(0, Math.round(rec.remaining - elapsed));
  }

  function setChampionPill(name, source) {
    if (!champPill) return;
    if (!name) {
      champPill.textContent = "—";
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
      .replace(/[’'`]/g, "")
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
    } catch { /* silent — we'll retry */ }
  }
  setInterval(refreshChampionFallback, 15000);
  refreshChampionFallback();     // kick one immediately

  // ── State dispatcher ────────────────────────────────────────────────
  function onState(env) {
    const p = env.payload || {};
    state.latest[env.mode] = p;

    // 2026-04-26: faster mode-switch — onState envelopes carry the source
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
    renderNext(p);
    renderItemBuild(p);
    renderMinimap(p);
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
        elm.textContent = "—";
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
      /* network err — leave prior render in place */
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
      AD.champ.textContent = data && data.champion ? data.champion : "—";
      AD.baseline.textContent = "—";
      AD.recent.textContent = "—";
      if (AD.kda) AD.kda.textContent = "—";
      AD.counters.textContent = "—";
      if (trendEl) trendEl.classList.add("hidden");
      if (adaptPanel) adaptPanel.classList.add("adapt-empty");
      return;
    }
    if (adaptPanel) adaptPanel.classList.remove("adapt-empty");
    AD.status.textContent = `${data.games_played} games`;
    AD.champ.textContent = `${data.champion}  (${data.mode})`;
    AD.baseline.textContent = `${(data.win_rate * 100).toFixed(1)}%  ${data.wins}W-${data.losses}L`;
    // Trend arrow: recent vs baseline WR — glance read for hot/cold streak.
    let arrow = "", cls = "";
    if (data.recent_win_rate != null && data.win_rate != null) {
      const delta = data.recent_win_rate - data.win_rate;
      if (delta >=  0.08) { arrow = " ↑"; cls = "trend-up"; }
      else if (delta <= -0.08) { arrow = " ↓"; cls = "trend-down"; }
      else { arrow = " ~"; cls = "trend-flat"; }
    }
    const recentPart = data.recent_win_rate != null
      ? `${(data.recent_win_rate * 100).toFixed(0)}% over last ${data.recent_sample_size}`
      : "—";
    AD.recent.textContent = recentPart + arrow;
    AD.recent.className = cls;

    // Typical KDA — shown once we have ≥5 samples; otherwise placeholder.
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
        AD.kda.textContent = "—";
      }
    }

    // Trend pill in the header — prefers 30d window, falls back to rolling.
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
    // Refresh the enemy-portrait danger map so the Minimap panel can
    // ring hard matchups coral next re-render.
    state.adaptCounterMap = {};
    for (const c of (data.counters || [])) {
      const k = String(c.opponent || "").toLowerCase().replace(/[^a-z0-9]/g, "");
      if (k) state.adaptCounterMap[k] = { delta: c.delta, kda: c.kda_delta };
    }
    // Re-render enemy strip if we have the latest enemies cached.
    const latestState = state.latest[state.mode];
    if (latestState && latestState.enemy_comp) renderEnemyStrip(latestState.enemy_comp);
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
    // Trending is mode-dependent only — fire regardless of champion.
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

    // Skip if same key within the last 8s — no need to hammer the endpoint.
    if (key === ADAPT.lastKey && (Date.now() - ADAPT.fetchedAt) < 8000) return;
    if (ADAPT.inflight) return;
    ADAPT.inflight = true;
    AD.status.textContent = "fetching…";
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

  // ── Champ-select panel (Phase 1, 2026-04-25) ────────────────────────
  // Interactive overlay shown only during phase=ChampSelect. Renders
  // my pick + 5 ally + 5 enemy cells + ARAM bench. Click bench → fires
  // bench_swap (LCU bypasses the 5s client cooldown so it's instant).
  // Click reroll/lock → fires the corresponding LCU command.
  function lcuCmd(cmdObj) {
    // Endpoint expects FLAT shape: {cmd: "name", ...args} — not wrapped.
    return fetch("/api/lcu-cmd", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cmdObj),
    }).then((r) => (r && r.ok ? r.json() : null)).catch(() => null);
  }

  function _csChampImg(cid) {
    if (!cid) return "";
    const nm = CHAMPS.byId[String(cid)];
    if (!nm) return "";
    return `/data/ddragon/${CHAMPS.version}/img/champion/${nm}.png`;
  }
  function _csChampName(cid) {
    return (cid && CHAMPS.byId[String(cid)]) || "";
  }

  // Loadout state — tracks what we've applied to avoid spam-pushing on
  // every 2s poll. Re-pushes when champion or variant key changes, or
  // when the user explicitly picks a different variant from the selector.
  const _csLoadout = {
    lastChamp: 0,        // championId we last pushed for
    lastMode:  "",       // mode we last pushed for
    variants:  [],       // [{key,label,is_default}] for current champion+mode
    chosen:    "",       // user-chosen variant key (sticky until champ change)
    inflight:  false,    // POST in flight — block re-entry
    lastAppliedKey: "",  // `${champ}|${mode}|${variant}` of last successful push
  };

  function _csNormalizeMode(cs) {
    if (!cs) return "sr";
    const q = cs.queue_id | 0;
    if (q === 450 || q === 920 || cs.is_aram) return "aram";
    if (q === 1700 || q === 1710) return "arena";
    if (q === 400) return "sr";  // SR draft
    if (q === 420 || q === 430 || q === 440) return "sr";  // SR ranked / blind
    return "sr";
  }

  function _csSetStatus(text, cls) {
    const el = document.getElementById("cs-loadout-status");
    if (!el) return;
    el.className = "cs-loadout-status" + (cls ? " " + cls : "");
    el.textContent = text || "";
  }

  // Build the set of item_ids that appear in some variants but NOT all
  // — these are the "differing" items that distinguish one build from
  // another. Used by both renderers to mark items with .cs-build-item--diff
  // so the user's eye lands on exactly what trades off between variants.
  // Returns an empty set when there's only one variant (nothing to diff).
  function _csDiffItemIds(variants) {
    const out = new Set();
    if (!variants || variants.length < 2) return out;
    const sets = variants.map((v) =>
      new Set((v.item_ids || []).slice(0, 6).map(String)));
    // Union of all item ids across variants
    const union = new Set();
    sets.forEach((s) => s.forEach((id) => union.add(id)));
    // An id is "diff" if it isn't present in EVERY variant's set.
    union.forEach((id) => {
      if (!sets.every((s) => s.has(id))) out.add(id);
    });
    return out;
  }

  // Render the variant list as selectable rows. Each row carries inline
  // keystone + first-N item icons so the user can compare builds at a
  // glance. Clicking a row selects it (radio-style) and triggers an
  // /api/loadout/apply push. Rebuilt 2026-04-26 — the old <select>
  // dropdown hid alternate builds behind a click and gave the user the
  // impression there was only one choice. 2026-05-01: items that differ
  // across variants get .cs-build-item--diff so the eye lands on the
  // tradeoffs (Tier 4 #17 side-by-side comparison).
  function _csRenderBuildList(variants, chosen) {
    const wrap = document.getElementById("cs-build-list");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!variants || !variants.length) {
      wrap.innerHTML =
        '<div class="cs-loadout-empty">No builds defined for this champion ' +
        'in this mode — add one to data/champion_loadouts.json</div>';
      return;
    }
    const ver = CHAMPS.version || "latest";
    const diffIds = _csDiffItemIds(variants);
    variants.forEach((v) => {
      const row = document.createElement("div");
      const isExp = v.key === "experimental";
      row.className = "cs-build-row" + (v.key === chosen ? " selected" : "")
        + (isExp ? " experimental" : "");
      row.dataset.variant = v.key;

      const cb = document.createElement("div");
      cb.className = "cs-build-checkbox";
      row.appendChild(cb);

      const meta = document.createElement("div");
      meta.className = "cs-build-meta";
      const label = document.createElement("div");
      label.className = "cs-build-label";
      label.textContent = v.label || v.key;
      if (v.is_default) {
        const tag = document.createElement("span");
        tag.className = "default-tag";
        tag.textContent = "default";
        label.appendChild(tag);
      }
      meta.appendChild(label);
      const runes = document.createElement("div");
      runes.className = "cs-build-runes";
      const ks = v.keystone || (isExp ? "auto-generated on pick" : "—");
      const tree = v.primary ? ` · ${v.primary}${v.secondary ? "/" + v.secondary : ""}` : "";
      runes.textContent = ks + tree;
      meta.appendChild(runes);
      row.appendChild(meta);

      const items = document.createElement("div");
      items.className = "cs-build-items";
      const ids = (v.item_ids || []).slice(0, 6);
      if (!ids.length) {
        for (let i = 0; i < 6; i++) {
          const ph = document.createElement("div");
          ph.className = "cs-build-item placeholder";
          items.appendChild(ph);
        }
      } else {
        ids.forEach((iid, idx) => {
          const cell = document.createElement("div");
          const isDiff = diffIds.has(String(iid));
          cell.className = "cs-build-item" + (isDiff ? " cs-build-item--diff" : "");
          const nm = (v.item_names || [])[idx] || ("item " + iid);
          cell.title = isDiff ? `${nm} (differs across variants)` : nm;
          cell.innerHTML = `<img src="/data/ddragon/${ver}/img/item/${iid}.png" onerror="this.style.display='none'" alt="">`;
          items.appendChild(cell);
        });
      }
      row.appendChild(items);

      row.addEventListener("click", () => _csOnBuildRowClick(v.key));
      wrap.appendChild(row);
    });
  }

  function _csMarkSelectedRow(variantKey) {
    const wrap = document.getElementById("cs-build-list");
    if (!wrap) return;
    wrap.querySelectorAll(".cs-build-row").forEach((r) => {
      if (r.dataset.variant === variantKey) r.classList.add("selected");
      else r.classList.remove("selected");
    });
  }

  // ── In-game build chooser (2026-04-26) ───────────────────────────
  // Lives inside #item-build, NOT the champ-select overlay. Pre-game
  // selection is persisted in localStorage so this chooser highlights
  // the same row by default. Mid-game pushes items only (runes +
  // summoners are locked at game start).
  const _ibBuilds = {
    lastChamp:  "",
    lastMode:   "",
    variants:   [],
    chosen:     "",
    inflight:   false,
    lastAppliedKey: "",
  };
  function _ibSetStatus(text, cls) {
    const el = document.getElementById("ib-builds-status");
    if (!el) return;
    el.className = "ib-builds-status" + (cls ? " " + cls : "");
    el.textContent = text || "";
  }
  function _ibStorageKey(champion) { return "rc-ingame-build-" + (champion || ""); }
  function _ibSavedChoice(champion) {
    try { return localStorage.getItem(_ibStorageKey(champion)) || ""; }
    catch (_) { return ""; }
  }
  function _ibSaveChoice(champion, variant) {
    try { localStorage.setItem(_ibStorageKey(champion), variant); }
    catch (_) {}
  }
  function _ibRenderRows(variants, chosen) {
    const wrap = document.getElementById("ib-build-list");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!variants || !variants.length) return;
    const ver = CHAMPS.version || "latest";
    const diffIds = _csDiffItemIds(variants);
    variants.forEach((v) => {
      const row = document.createElement("div");
      const isExp = v.key === "experimental";
      row.className = "cs-build-row" + (v.key === chosen ? " selected" : "")
        + (isExp ? " experimental" : "");
      row.dataset.variant = v.key;
      const cb = document.createElement("div");
      cb.className = "cs-build-checkbox"; row.appendChild(cb);
      const meta = document.createElement("div");
      meta.className = "cs-build-meta";
      const label = document.createElement("div");
      label.className = "cs-build-label";
      label.textContent = v.label || v.key;
      meta.appendChild(label);
      const runes = document.createElement("div");
      runes.className = "cs-build-runes";
      runes.textContent = (v.keystone || "—");
      meta.appendChild(runes);
      row.appendChild(meta);
      const items = document.createElement("div");
      items.className = "cs-build-items";
      (v.item_ids || []).slice(0, 4).forEach((iid, idx) => {
        const cell = document.createElement("div");
        const isDiff = diffIds.has(String(iid));
        cell.className = "cs-build-item" + (isDiff ? " cs-build-item--diff" : "");
        const nm = (v.item_names || [])[idx] || ("item " + iid);
        cell.title = isDiff ? `${nm} (differs across variants)` : nm;
        cell.innerHTML = `<img src="/data/ddragon/${ver}/img/item/${iid}.png" onerror="this.style.display='none'" alt="">`;
        items.appendChild(cell);
      });
      row.appendChild(items);
      row.addEventListener("click", () => _ibOnRowClick(v.key));
      wrap.appendChild(row);
    });
  }
  function _ibMarkSelectedRow(variantKey) {
    const wrap = document.getElementById("ib-build-list");
    if (!wrap) return;
    wrap.querySelectorAll(".cs-build-row").forEach((r) => {
      if (r.dataset.variant === variantKey) r.classList.add("selected");
      else r.classList.remove("selected");
    });
  }
  function _ibPushItems(champion, variant, mode) {
    if (!champion || !variant) return;
    const key = champion + "|" + mode + "|" + variant;
    if (key === _ibBuilds.lastAppliedKey) return;
    if (_ibBuilds.inflight) return;
    _ibBuilds.inflight = true;
    _ibSetStatus("pushing…", "busy");
    fetch("/api/loadout/apply", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        champion: champion, variant: variant, mode: mode,
        push_runes: false, push_summoners: false, push_items: true,
      }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _ibBuilds.inflight = false;
        if (!data || !data.ok) { _ibSetStatus("push failed", "err"); return; }
        _ibBuilds.lastAppliedKey = key;
        _ibSetStatus("✓ " + (data.label || variant), "ok");
        _ibMarkSelectedRow(variant);
        _ibSaveChoice(champion, variant);
      })
      .catch(() => { _ibBuilds.inflight = false; _ibSetStatus("push failed", "err"); });
  }
  function _ibOnRowClick(variant) {
    if (!variant) return;
    _ibBuilds.chosen = variant;
    _ibBuilds.lastAppliedKey = "";
    _ibMarkSelectedRow(variant);
    if (_ibBuilds.lastChamp && _ibBuilds.lastMode) {
      _ibPushItems(_ibBuilds.lastChamp, variant, _ibBuilds.lastMode);
    }
  }
  function _ibFetchAndRender(champion, mode) {
    fetch("/api/loadout/list", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ champion: champion, mode: mode }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        const block = document.getElementById("ib-builds-block");
        if (!data || !data.variants || data.variants.length < 2) {
          // <2 variants is uninteresting (just "default + experimental")
          // — hide rather than clutter the small panel.
          if (block) block.hidden = true;
          return;
        }
        if (block) block.hidden = false;
        _ibBuilds.variants = data.variants;
        // Default highlight: persisted pre-game choice if it's still a valid
        // variant for this champion+mode; otherwise the resolver's default.
        const saved = _ibSavedChoice(champion);
        const valid = data.variants.some((v) => v.key === saved);
        _ibBuilds.chosen = (saved && valid) ? saved : (data.default || data.variants[0].key);
        _ibRenderRows(data.variants, _ibBuilds.chosen);
        _ibSetStatus("ready · " + data.variants.length + " builds", "");
      })
      .catch(() => {});
  }
  function _ibMaybeRenderBuilds(p) {
    // Only show in modes where loadout variants make sense + the live
    // champion is known. Skip Arena/TFT (no fixed builds) and client mode.
    const mode = state.mode;
    const champion = p && p.champion;
    if (!champion || !["sr","aram","brawl"].includes(mode)) {
      const block = document.getElementById("ib-builds-block");
      if (block) block.hidden = true;
      return;
    }
    if (champion === _ibBuilds.lastChamp && mode === _ibBuilds.lastMode
        && _ibBuilds.variants.length) {
      // Already rendered for this champion+mode; nothing to do.
      return;
    }
    _ibBuilds.lastChamp = champion;
    _ibBuilds.lastMode  = mode;
    _ibBuilds.lastAppliedKey = "";
    _ibFetchAndRender(champion, mode);
  }

  // Single click handler shared by every row (no per-row delegation
  // needed since we re-render the whole list on champion/variant change).
  function _csOnBuildRowClick(variant) {
    if (!variant) return;
    _csLoadout.chosen = variant;
    _csLoadout.lastAppliedKey = "";  // force push
    _csMarkSelectedRow(variant);
    const champName = _csChampName(_csLoadout.lastChamp);
    if (!champName) return;
    if (variant === "experimental") {
      _csSetStatus("generating experimental…", "busy");
      fetch("/api/experimental/get", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ champion: champName, mode: _csLoadout.lastMode }),
      })
        .then((r) => (r && r.ok ? r.json() : null))
        .then((data) => {
          if (!data || !data.ok || !data.current) {
            _csSetStatus("experimental gen failed", "err");
            return;
          }
          _csApplyLoadout(champName, "experimental", _csLoadout.lastMode);
          fetch("/api/experimental/mark", {
            method: "POST", cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ champion: champName, mode: _csLoadout.lastMode }),
          }).catch(() => {});
        })
        .catch(() => _csSetStatus("experimental fetch failed", "err"));
    } else {
      _csApplyLoadout(champName, variant, _csLoadout.lastMode);
    }
  }

  // Force-summoners override (2026-04-26 user request). When the
  // checkbox is on, _csApplyLoadout suppresses the variant's summoner
  // push (push_summoners:false) and instead sends a separate
  // set_summoners {d:4, f:32} via /api/lcu-cmd. State persists in
  // localStorage rc-force-flash-snowball.
  function _csForceSummsOn() {
    try { return localStorage.getItem("rc-force-flash-snowball") === "1"; }
    catch (_) { return false; }
  }
  function _csWireForceSummsOnce() {
    const cb = document.getElementById("cs-force-flash-snowball");
    if (!cb || cb._wired) return;
    cb._wired = true;
    cb.checked = _csForceSummsOn();
    cb.addEventListener("change", () => {
      try { localStorage.setItem("rc-force-flash-snowball", cb.checked ? "1" : "0"); }
      catch (_) {}
      // Force re-push so the override takes effect immediately on the
      // currently-selected build (no need to re-click the row).
      _csLoadout.lastAppliedKey = "";
      const champ = _csChampName(_csLoadout.lastChamp);
      if (champ && _csLoadout.chosen) {
        _csApplyLoadout(champ, _csLoadout.chosen, _csLoadout.lastMode);
      }
    });
  }

  function _csApplyLoadout(champion, variant, mode) {
    if (!champion || !variant) return;
    const force = _csForceSummsOn();
    const key = champion + "|" + mode + "|" + variant + (force ? "|F" : "");
    if (key === _csLoadout.lastAppliedKey) return;  // already pushed
    if (_csLoadout.inflight) return;
    _csLoadout.inflight = true;
    _csSetStatus("pushing…", "busy");
    fetch("/api/loadout/apply", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        champion: champion, variant: variant, mode: mode,
        push_summoners: !force,  // skip variant summoners when override is on
      }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _csLoadout.inflight = false;
        if (!data || !data.ok) {
          _csSetStatus("push failed", "err");
          return;
        }
        _csLoadout.lastAppliedKey = key;
        if (force) {
          // Send the override AFTER the build apply — set_summoners is
          // its own LCU command path, doesn't conflict with item/rune push.
          lcuCmd({ cmd: "set_summoners", d: 4, f: 32 });
        }
        // Persist this pre-game choice so the in-game build chooser
        // (renderItemBuild → _ibMaybeRenderBuilds) can pre-select it.
        try { localStorage.setItem("rc-ingame-build-" + champion, variant); }
        catch (_) {}
        const queued = (data.queued || []).join(", ") || "nothing";
        const tag = force ? " · F+S forced" : "";
        _csSetStatus("✓ pushed: " + queued + tag, "ok");
        _csMarkSelectedRow(variant);
        // Clear the OK flash after a few seconds
        setTimeout(() => {
          if (_csLoadout.lastAppliedKey === key) _csSetStatus("✓ active: " + (data.label || variant) + tag, "ok");
        }, 2400);
      })
      .catch(() => {
        _csLoadout.inflight = false;
        _csSetStatus("push failed", "err");
      });
  }

  function _csOnChampionOrModeChange(championName, championId, mode) {
    // Reset chosen variant — sticky only within same champion.
    _csLoadout.lastChamp = championId;
    _csLoadout.lastMode  = mode;
    _csLoadout.chosen    = "";
    _csLoadout.lastAppliedKey = "";
    fetch("/api/loadout/list", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ champion: championName, mode: mode }),
    })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        const block = document.getElementById("cs-loadout-block");
        if (!data || !data.variants || !data.variants.length) {
          if (block) block.hidden = true;
          _csSetStatus("");
          return;
        }
        if (block) block.hidden = false;
        _csLoadout.variants = data.variants;
        _csLoadout.chosen   = data.default || data.variants[0].key;
        _csRenderBuildList(data.variants, _csLoadout.chosen);
        _csApplyLoadout(championName, _csLoadout.chosen, mode);
      })
      .catch(() => {
        const block = document.getElementById("cs-loadout-block");
        if (block) block.hidden = true;
      });
  }

  // ── Team-comp analyzer (Phase 3, 2026-04-26) ────────────────────────
  // Debounced AI call that recommends swap / variant / stay based on
  // current team comp. Only runs in ARAM and only when bench has options
  // OR the user has multiple variants available. Result drives:
  //   - verdict badge + reason text in cs-analyzer-block
  //   - star highlight on the recommended bench cell
  //   - glow on the variant dropdown when variant change is recommended
  const _csAnalyzer = {
    lastKey: "",            // dedupe key for comp+bench+champ+variant
    inflight: false,
    lastResult: null,       // last response payload
    debounceTimer: null,
  };

  function _csAnalyzerFireDebounced(payload, key) {
    if (key === _csAnalyzer.lastKey) return;
    if (_csAnalyzer.inflight) return;
    if (_csAnalyzer.debounceTimer) clearTimeout(_csAnalyzer.debounceTimer);
    // 4s debounce — bench/team churn during active draft shouldn't burn calls
    _csAnalyzer.debounceTimer = setTimeout(() => {
      _csAnalyzer.lastKey = key;
      _csAnalyzer.inflight = true;
      const block = document.getElementById("cs-analyzer-block");
      const verdictEl = document.getElementById("cs-analyzer-verdict");
      const reasonEl = document.getElementById("cs-analyzer-reason");
      if (block) block.hidden = false;
      if (verdictEl) {
        verdictEl.className = "cs-analyzer-verdict busy";
        verdictEl.textContent = "analyzing…";
      }
      if (reasonEl) reasonEl.textContent = "asking the coach…";
      fetch("/api/aram-analyze", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((r) => (r && r.ok ? r.json() : null))
        .then((data) => {
          _csAnalyzer.inflight = false;
          _csAnalyzer.lastResult = data;
          _csRenderAnalyzerResult(data);
        })
        .catch(() => {
          _csAnalyzer.inflight = false;
          if (verdictEl) {
            verdictEl.className = "cs-analyzer-verdict";
            verdictEl.textContent = "error";
          }
          if (reasonEl) reasonEl.textContent = "analyzer call failed";
        });
    }, 4000);
  }

  function _csRenderAnalyzerResult(data) {
    const block = document.getElementById("cs-analyzer-block");
    const verdictEl = document.getElementById("cs-analyzer-verdict");
    const confEl = document.getElementById("cs-analyzer-conf");
    const reasonEl = document.getElementById("cs-analyzer-reason");
    if (!data || !data.ok) {
      if (verdictEl) { verdictEl.className = "cs-analyzer-verdict"; verdictEl.textContent = "—"; }
      if (reasonEl) reasonEl.textContent = (data && data.reason) || "analyzer unavailable";
      return;
    }
    const rec = data.recommendation || "stay";
    const verdictText = rec === "swap"    ? `SWAP → ${data.swap_to || "?"}`
                      : rec === "variant" ? `VARIANT → ${data.variant_to || "?"}`
                      :                     "STAY (comp ok)";
    if (verdictEl) {
      verdictEl.className = "cs-analyzer-verdict " + rec;
      verdictEl.textContent = verdictText;
    }
    if (confEl) confEl.textContent = (data.confidence || "") + " conf";
    if (reasonEl) reasonEl.textContent = data.reason || "";

    // Apply highlights — bench cell for swap, build row for variant.
    document.querySelectorAll(".cs-bench-cell.recommended").forEach(
      (el) => el.classList.remove("recommended")
    );
    document.querySelectorAll(".cs-build-row.has-recommendation").forEach(
      (el) => {
        el.classList.remove("has-recommendation");
        const t = el.querySelector(".cs-build-label .reco-tag");
        if (t) t.remove();
      }
    );

    if (rec === "swap" && data.swap_to) {
      document.querySelectorAll(".cs-bench-cell").forEach((cell) => {
        const title = cell.title || "";
        if (title.startsWith("Swap to " + data.swap_to + " ")) {
          cell.classList.add("recommended");
        }
      });
    } else if (rec === "variant" && data.variant_to) {
      const row = document.querySelector(
        '.cs-build-row[data-variant="' + CSS.escape(data.variant_to) + '"]'
      );
      if (row) {
        row.classList.add("has-recommendation");
        const lbl = row.querySelector(".cs-build-label");
        if (lbl && !lbl.querySelector(".reco-tag")) {
          const tag = document.createElement("span");
          tag.className = "reco-tag";
          tag.textContent = "★ recommended";
          lbl.appendChild(tag);
        }
      }
    }
  }

  function _csMaybeRunAnalyzer(cs, myCid, myName, mode) {
    // Only in ARAM (or ARAM Mayhem). Other modes don't have bench/swap
    // and the analyzer prompt is ARAM-tuned. Mayhem queue_ids don't
    // always set cs.is_aram (LCU agent only flags 450/920) — fall back
    // to "bench present" or mode === aram as additional ARAM signals
    // so Mayhem games surface the analyzer too. (2026-04-26 user-
    // reported regression: analyzer never rendered during Mayhem.)
    const _aramish = !!(cs && (cs.is_aram
                               || (Array.isArray(cs.bench) && cs.bench.length > 0)
                               || mode === "aram"));
    if (!_aramish) {
      const block = document.getElementById("cs-analyzer-block");
      if (block) block.hidden = true;
      return;
    }
    if (!myCid || !myName || myName === "—") return;
    if (!CHAMPS.ready) return;
    const myTeam = (cs.my_team || [])
      .map((p) => CHAMPS.byId[String(p && p.championId)])
      .filter(Boolean);
    const theirTeam = (cs.their_team || [])
      .map((p) => CHAMPS.byId[String(p && p.championId)])
      .filter(Boolean);
    const bench = (cs.bench || [])
      .map((id) => CHAMPS.byId[String(id)])
      .filter(Boolean);
    // Skip when there's no swap target AND no variant alternatives —
    // analyzer won't have anything to recommend.
    if (!bench.length && (!_csLoadout.variants || _csLoadout.variants.length <= 1)) {
      const block = document.getElementById("cs-analyzer-block");
      if (block) block.hidden = true;
      return;
    }
    const key = [myName, myTeam.join("|"), theirTeam.join("|"),
                 bench.join("|"), _csLoadout.chosen || ""].join("/");
    _csAnalyzerFireDebounced({
      my_champion: myName,
      my_team:     myTeam,
      their_team:  theirTeam,
      bench:       bench,
      current_variant: _csLoadout.chosen || "",
      mode:        mode,
    }, key);
  }

  function _csWireButtonsOnce() {
    const r = document.getElementById("cs-reroll-btn");
    if (r && !r._wired) {
      r._wired = true;
      r.addEventListener("click", () => {
        if (r.disabled) return;
        r.disabled = true;
        lcuCmd({ cmd: "reroll" });
        setTimeout(() => { r.disabled = false; }, 1500);
      });
    }
    const l = document.getElementById("cs-lock-btn");
    if (l && !l._wired) {
      l._wired = true;
      l.addEventListener("click", () => {
        if (l.disabled) return;
        l.disabled = true;
        // Pull current pick from cached state (cs.my_champion).
        const cid = (l._currentCid | 0);
        if (cid > 0) lcuCmd({ cmd: "lock_pick", championId: cid });
        setTimeout(() => { l.disabled = false; }, 1500);
      });
    }
  }

  // ── Session view fetchers (2026-04-26) ───────────────────────────
  function _sessionFetchAndRender() {
    fetch("/api/session/summary", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set("session-window", d.window_label || "—");
        set("session-games", d.games || "0");
        const sec = (d.time_played_s | 0);
        const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60);
        set("session-time", hh > 0 ? `${hh}h ${mm}m` : `${mm}m`);
        set("session-start", d.started_at || "—");
        set("session-last", d.last_at || "—");
        set("session-kda", d.total_kda || "—");
        set("session-avg", d.avg_kda != null ? d.avg_kda.toFixed(2) : "—");
        set("session-grades",
          d.grades ? Object.entries(d.grades).map(([g,n]) => `${g}×${n}`).join(" ") : "—");
        set("session-modes",
          d.modes ? Object.entries(d.modes).map(([m,n]) => `${m} ${n}`).join(" · ") : "—");
        const champUl = document.getElementById("session-champs");
        if (champUl) {
          champUl.innerHTML = "";
          (d.champions || []).forEach((c) => {
            const li = document.createElement("li");
            li.className = "history-match-row";
            li.innerHTML = `<span style="flex:1">${c.champion}</span>` +
              `<span class="dim">${c.games}g</span>` +
              `<span style="margin-left:10px">${c.kda || "—"}</span>`;
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
            const grade = String(m.grade || "—")[0];
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
  const _HISTORY = { scope: "14d", selectedSession: null };
  function _historyFetchAndRender() {
    fetch("/api/history?scope=" + encodeURIComponent(_HISTORY.scope), { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
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
        set("history-season-total", ss.total != null ? ss.total : "—");
        set("history-season-kda",   ss.avg_kda != null ? ss.avg_kda.toFixed(2) : "—");
        set("history-season-fav",   ss.favorite || "—");
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
      const grade = String(m.grade || "—")[0];
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

  // ── Settings view (2026-04-26) ───────────────────────────────────
  function _settingsRefresh() {
    if (window.__settingsWired) return;
    window.__settingsWired = true;
    const get = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; }};
    const setLS = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
    const cb = (id, key, onSet) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.checked = get(key) === "1";
      el.addEventListener("change", () => {
        setLS(key, el.checked ? "1" : "0");
        if (onSet) onSet(el.checked);
      });
    };
    cb("set-voice-on", "rc-voice-on");
    cb("set-force-flash-snowball", "rc-force-flash-snowball");
    cb("set-zen", "rc-zen", (v) => { document.body.dataset.zen = v ? "1" : ""; });
    const zoom = document.getElementById("set-zoom");
    const zoomVal = document.getElementById("set-zoom-val");
    if (zoom) {
      zoom.value = parseFloat(get("rc-zoom") || "1.0");
      if (zoomVal) zoomVal.textContent = parseFloat(zoom.value).toFixed(2) + "×";
      zoom.addEventListener("input", () => {
        setLS("rc-zoom", zoom.value);
        if (zoomVal) zoomVal.textContent = parseFloat(zoom.value).toFixed(2) + "×";
        document.body.style.zoom = zoom.value;
      });
    }
    // Live metrics status (read-only — env var)
    fetch("/api/diagnostics", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((d) => {
        const el = document.getElementById("set-live-metrics-status");
        if (el && d) el.textContent = d.live_metrics_enabled ? "ON" : "OFF";
      }).catch(() => {});
  }

  // ── Diagnostics view (2026-04-26) ────────────────────────────────
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
            det.style.fontSize = "10px";
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

  // ── Replay scrubber (audit suggestion 2.3, 2026-04-28) ────────────
  // Loads recent matches from /api/replay/matches; clicking one fetches
  // /api/replay/match/<id> and lets the user scrub through per-minute
  // snapshots. Items, level, gold, CS reflect the slider position.
  const _REPLAY = { match: null, snapshotIdx: 0, itemsIndex: null };
  function _replayQueueLabel(q) {
    return ({
      400:"Normal Draft",420:"Ranked Solo",430:"Normal Blind",
      440:"Ranked Flex",450:"ARAM",700:"Clash",900:"ARURF",
      920:"ARAM Mayhem",1700:"Arena",1900:"URF",
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
    return "/icons/champions/" + encodeURIComponent(String(name).replace(/[^A-Za-z]/g, "")) + ".png";
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
    fetch("/api/replay/matches?limit=30")
      .then(r => r.ok ? r.json() : null)
      .then(j => {
        const ul = document.getElementById("replay-match-list");
        if (!ul) return;
        ul.innerHTML = "";
        const items = (j && j.matches) || [];
        if (!items.length) {
          ul.innerHTML = '<li class="home-empty">no matches in rewind_history.db</li>';
          return;
        }
        for (const m of items) {
          const li = document.createElement("li");
          li.className = "replay-match-row";
          if (m.tracked && m.tracked.win === true)  li.classList.add("won");
          if (m.tracked && m.tracked.win === false) li.classList.add("lost");
          li.dataset.matchId = m.match_id;
          const champ = (m.tracked && m.tracked.champion_name) || "?";
          const verdict = m.tracked && m.tracked.win === true ? "W" :
                          m.tracked && m.tracked.win === false ? "L" : "—";
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
        }
      })
      .catch(e => console.warn("replay matches:", e));
    _replayLoadItemsIndex();
  }
  function _replayLoadMatch(matchId, rowEl) {
    document.querySelectorAll(".replay-match-row.active").forEach(r => r.classList.remove("active"));
    if (rowEl) rowEl.classList.add("active");
    const meta = document.getElementById("replay-meta");
    if (meta) meta.textContent = "loading " + matchId + "…";
    fetch("/api/replay/match/" + encodeURIComponent(matchId))
      .then(r => r.ok ? r.json() : null)
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
          const v = verdict ? (verdict.team_won ? " (W)" : " (L)") : "";
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
        ["replay-col-num",    e.level != null ? String(e.level) : "—"],
        ["replay-col-num",    e.total_gold != null ? e.total_gold.toLocaleString() : "—"],
        ["replay-col-num",    e.cs != null ? String(e.cs) : "—"],
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
      const gradeRaw = String(m.grade || "—").toUpperCase()[0] || "—";
      const tier = (gradeRaw === "S" || gradeRaw === "A") ? "tier-good"
                 : (gradeRaw === "D" || gradeRaw === "F") ? "tier-bad"
                 : "tier-mid";
      const dur = m.duration_s
        ? `${Math.floor(m.duration_s / 60)}m`
        : "";
      const tsShort = _to12((m.timestamp || "").split(" ")[1]?.slice(0,5) || "");
      const metaParts = [m.mode, tsShort, dur].filter(Boolean).join(" · ");

      const stripe = document.createElement("div");
      stripe.className = `home-recent-stripe ${tier}`;
      // Champion portrait (DDragon icon, locally mirrored). Falls back
      // to a "?" placeholder if the file is missing.
      const ver = (typeof CHAMPS !== "undefined" && CHAMPS && CHAMPS.version) ? CHAMPS.version : "16.8.1";
      const img = document.createElement("img");
      img.className = "home-recent-img";
      img.alt = "";
      img.loading = "lazy";
      img.src = `/data/ddragon/${ver}/img/champion/${encodeURIComponent(m.champion || "")}.png`;
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
      const kda = document.createElement("span");
      kda.className = "home-recent-kda";
      kda.textContent = m.kda || "—";
      const grade = document.createElement("span");
      grade.className = `home-recent-grade-badge ${gradeRaw}`;
      grade.textContent = gradeRaw;
      card.append(stripe, img, main, kda, grade);

      // Click → open replay view if a match_id is present. Use the
      // existing applyView helper so the URL hash + menu state stay in sync.
      if (m.match_id && typeof applyView === "function") {
        card.addEventListener("click", () => applyView("replay"));
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
      const gradeRaw = String(r.best_grade || "—").toUpperCase()[0] || "—";
      const pct = Math.round(((r.games || 0) / maxGames) * 100);

      const name = document.createElement("span");
      name.className = "home-week-bar-name";
      name.style.setProperty("--bar-pct", pct + "%");
      name.textContent = r.champion || "?";

      const games = document.createElement("span");
      games.className = "home-week-bar-games";
      const gn = r.games || 0;
      games.textContent = `${gn} game${gn === 1 ? "" : "s"}`;

      const kda = document.createElement("span");
      kda.className = "home-week-bar-kda";
      kda.textContent = (r.avg_kda != null) ? r.avg_kda.toFixed(1) : "—";

      const grade = document.createElement("span");
      grade.className = `home-recent-grade-badge ${gradeRaw}`;
      grade.textContent = gradeRaw;
      // No inline sizing — the .home-week-bar-row .home-recent-grade-badge
      // selector in CSS handles the inline-row variant (28x28 / 13px).
      row.append(name, games, kda, grade);
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
        const avgStr = avg != null ? avg.toFixed(2) : "—";
        headline.textContent = `${games} game${games===1?"":"s"} · ${avgStr} avg KDA`;
        if (avg != null) {
          if (avg >= 2.5) headline.classList.add("up");
          else if (avg < 1.5) headline.classList.add("down");
          else headline.classList.add("flat");
        }
      }
    }

    // Chips
    set("home-hero-kda", t && t.total_kda ? t.total_kda : "—");
    set("home-hero-avg", avg != null ? avg.toFixed(2) : "—");
    const gradeStr = t && t.grades
      ? Object.entries(t.grades).map(([g,n]) => `${g}×${n}`).join(" ")
      : "—";
    set("home-hero-grades", gradeStr || "—");
    const modeStr = t && t.modes
      ? Object.entries(t.modes).map(([m,n]) => `${m} ${n}`).join(" · ")
      : "—";
    set("home-hero-modes", modeStr || "—");

    // Legacy IDs (set if present so any external reader still works).
    set("home-today-count", games > 0 ? `${games} game${games===1?"":"s"}` : "");
    set("home-today-kda",   t && t.total_kda ? t.total_kda : "—");
    set("home-today-avg",   avg != null ? avg.toFixed(2) : "—");
    set("home-today-grades", gradeStr || "—");
    set("home-today-modes",  modeStr || "—");
  }
  function _homeRenderServices(rows) {
    // V1 redesign 2026-04-29: render as a thin strip of compact pills
    // (dot + name) instead of a card-sized bulleted list. Detail string
    // moves to the title attribute (hover tooltip) — services are a
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
  function _homeFetchAndRender() {
    if (_HOME.fetching) return;
    _HOME.fetching = true;
    fetch("/api/home/summary", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _HOME.fetching = false;
        if (!data) return;
        _HOME.lastFetchAt = Date.now();
        _homeRenderToday(data.today || {}, data.streaks || {});
        _homeRenderRecent(data.recent || []);
        _homeRenderWeek(data.this_week || []);
        _homeRenderServices(data.services || []);
        _homeUpdateHeroMotif(data);
        // Render trends FIRST so its hidden flag is current when
        // _homeRenderCoach decides whether the combo wrapper shows.
        _homeRenderTrends(data.trends || {});
        _homeRenderCoach(data.tonight_pick, data.last_build);
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
      // (CS / GOLD only — KDA chip val stays driven by _homeRenderToday
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
    const ver = (typeof CHAMPS !== "undefined" && CHAMPS && CHAMPS.version) ? CHAMPS.version : "16.8.1";
    // Tonight's pick
    if (pick && pick.champion) {
      pickCard.hidden = false;
      const img = document.getElementById("home-coach-pick-img");
      const champ = document.getElementById("home-coach-pick-champ");
      const reason = document.getElementById("home-coach-pick-reason");
      if (img) {
        img.src = `/data/ddragon/${ver}/img/champion/${encodeURIComponent(pick.champion)}.png`;
        img.alt = pick.champion;
        img.onerror = () => { img.style.visibility = "hidden"; };
      }
      if (champ) champ.textContent = pick.champion;
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
  // local DDragon icon as the hero background. Local-only — no CDN
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
    const ver = (typeof CHAMPS !== "undefined" && CHAMPS && CHAMPS.version) ? CHAMPS.version : "16.8.1";
    bg.style.backgroundImage =
      `url("/data/ddragon/${ver}/img/champion/${encodeURIComponent(champ)}.png")`;
  }
  // Mirror advisory + digest into the icon-button badges on Tonight's
  // Pick (V3 redesign 2026-04-30). Sets the badge text + toggles
  // .has-data so CSS recolors the button when the count/label is
  // non-default. Badge tooltip carries the verbose text.
  function _homeMirrorAlerts() {
    const advCount = document.getElementById("advisory-count");
    const advBtn = document.getElementById("home-alerts-advisory");
    const advBadge = document.getElementById("home-alerts-advisory-val");
    if (advCount && advBtn && advBadge) {
      const n = parseInt(advCount.textContent || "0", 10) || 0;
      advBadge.textContent = n;
      advBtn.classList.toggle("has-data", n > 0);
      advBtn.title = n === 0 ? "No open advisories"
                             : `${n} open advisor${n === 1 ? "y" : "ies"}`;
    }
    const digLabel = document.getElementById("digest-label");
    const digBtn = document.getElementById("home-alerts-digest");
    const digBadge = document.getElementById("home-alerts-digest-val");
    if (digLabel && digBtn && digBadge) {
      const t = (digLabel.textContent || "").trim();
      const hasData = !!t && t !== "—";
      digBadge.textContent = hasData ? t : "—";
      digBtn.classList.toggle("has-data", hasData);
      digBtn.title = hasData ? `Cross-session digest: ${t}` : "No streak data yet";
    }
  }
  function renderHomePanel(lcu) {
    const overlay = document.getElementById("home-overlay");
    if (!overlay) return;
    // V2 visibility: also un-hide whenever the user is explicitly on
    // the Home view (manual nav). Was previously gated only on
    // state.mode === "client" via _homeShouldShow.
    const onHomeView = document.body.dataset.view === "home";
    if (!onHomeView && !_homeShouldShow(lcu)) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    if (!_HOME.lastFetchAt) _homeFetchAndRender();
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
      tile.addEventListener("click", () => {
        const t = tile.dataset.target;
        if (!t) return;
        if (typeof _viewSaveManual === "function") _viewSaveManual(t);
        try { location.hash = "#" + t; } catch (_) {}
        if (typeof _viewResolveAndApply === "function") _viewResolveAndApply();
        else if (typeof applyView === "function") applyView(t);
      });
    });
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
    wireAlertRow("home-alerts-advisory", "advisory-badge");
    wireAlertRow("home-alerts-digest",   "digest-icon");
    // Initial fetch + recurring tick + alerts mirror.
    _homeFetchAndRender();
    setInterval(_homeFetchAndRender, _HOME.intervalMs);
    setInterval(_homeMirrorAlerts, 2000);
    _homeMirrorAlerts();
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
  const _LV = { wired: false };
  // Static queue-tip table — per queue_id, a list of short tips.
  // Hardcoded since they don't change per-game; feel free to extend.
  const LV_QUEUE_TIPS = {
    450:  ["Bench-swap is instant via the LCU API (5s client cooldown bypassed).",
           "Snowball + Flash is the standard summoner combo.",
           "ARAM Mayhem? Coach treats KIWI mode as ARAM — same loadouts apply."],
    920:  ["ARAM Mayhem rolls 2-3 champions per slot — pick from the cs-overlay.",
           "Augments roll mid-game; the panel surfaces them in the header pill.",
           "Score 1-100 for a win, not 0 deaths — fight more often."],
    400:  ["Normal Draft — 6 bans per side, hover before lock.",
           "Counterpick last-pick role if possible."],
    420:  ["Ranked Solo — match decides LP. Don't dodge unless griefed.",
           "Ban on what enemy team comp / role threats."],
    440:  ["Ranked Flex — premade up to 5; matchmaking pools differ from solo."],
    1700: ["Arena 2v2v2v2 — pick a synergy duo.",
           "Anvil decisions matter more than build path. Read the augment."],
  };
  function _lvSetStatus(text, cls) {
    const el = document.getElementById("lv-status");
    if (!el) return;
    el.className = "lobby-status" + (cls ? " " + cls : "");
    el.textContent = text || "";
  }
  function _lobbyViewWireOnce() {
    if (_LV.wired) return;
    _LV.wired = true;
    const find = document.getElementById("lv-find-match");
    if (find) find.addEventListener("click", () => {
      if (find.disabled) return;
      find.disabled = true;
      lcuCmd({ cmd: "start_matchmaking" });
      _lvSetStatus("starting…", "searching");
      setTimeout(() => { find.disabled = false; }, 1500);
    });
    const cancel = document.getElementById("lv-cancel-match");
    if (cancel) cancel.addEventListener("click", () => {
      lcuCmd({ cmd: "cancel_matchmaking" });
      _lvSetStatus("cancelling…", "");
    });
    const qsel = document.getElementById("lv-queue-select");
    if (qsel) qsel.addEventListener("change", () => {
      const qid = parseInt(qsel.value, 10);
      if (!qid) return;
      lcuCmd({ cmd: "change_queue_type", queue_id: qid });
      _lvSetStatus("changing queue…", "searching");
      qsel.value = "";
    });
  }
  function _lobbyViewRefresh() {
    const lcu = (state.latest && state.latest.lcu) || {};
    const lobby = lcu.lobby || null;
    const wn = document.getElementById("lv-window");
    if (wn) wn.textContent = lobby ? "live" : "awaiting LCU lobby data feed";

    const qName = document.getElementById("lv-queue-name");
    if (qName) qName.textContent = lobby
      ? (lobby.queue_name || ("queue " + (lobby.queue_id || "?"))).toUpperCase()
      : "—";

    const party = document.getElementById("lv-party-pill");
    if (party) {
      if (lobby) {
        const size = lobby.party_size | 0;
        const max  = lobby.max_party_size | 0;
        party.textContent = max > 0 ? `Party ${size || 1}/${max}` : "Party —";
      } else party.textContent = "Party —";
    }
    const leaderTag = document.getElementById("lv-leader-tag");
    if (leaderTag) leaderTag.hidden = !(lobby && lobby.is_leader);
    const qsel = document.getElementById("lv-queue-select");
    if (qsel) qsel.hidden = !(lobby && lobby.is_leader);

    const find = document.getElementById("lv-find-match");
    const findLabel = document.getElementById("lv-find-match-label");
    const cancel = document.getElementById("lv-cancel-match");
    const searching = lobby && lobby.search_state === "Searching";
    const found = lobby && (lobby.search_state === "MatchFound" || lcu.phase === "ReadyCheck");
    if (cancel) cancel.hidden = !searching;
    if (find) {
      // Enable the button as long as we're not currently searching/
      // matched. LCU enforces leader check + lobby readiness on the
      // server side, so even without forwarded lobby data the click
      // is safe (it'll just no-op for non-leaders). User asked
      // 2026-04-26: "include the find match button into the UI".
      const enabled = !searching && !found;
      find.disabled = !enabled;
      if (findLabel) {
        findLabel.textContent = searching ? "Searching…"
          : found ? "Match Found"
          : (lobby && lobby.is_leader === false ? "Leader-only (LCU enforces)" : "Find Match");
      }
    }
    if (searching)               _lvSetStatus("Searching…", "searching");
    else if (found)              _lvSetStatus("Match Found · accept in client", "found");
    else if (!lobby)             _lvSetStatus("Click Find Match — LCU enforces leader check (no lobby feed yet)", "");
    else if (!lobby.is_leader)   _lvSetStatus("Awaiting party leader", "");
    else if (!lobby.can_search)  _lvSetStatus("Lobby not ready", "err");
    else                         _lvSetStatus("Ready to queue", "");

    // Members
    const ul = document.getElementById("lv-members-list");
    const cnt = document.getElementById("lv-members-count");
    const members = (lobby && lobby.members) || [];
    if (cnt) cnt.textContent = members.length + (members.length === 1 ? " member" : " members");
    if (ul) {
      if (!members.length) {
        ul.innerHTML = '<li class="home-empty">no members visible — Game-PC LCU agent needs to forward lcu.lobby.members[]</li>';
      } else {
        ul.innerHTML = "";
        members.forEach((m) => {
          const li = document.createElement("li");
          li.className = "lobby-member-row" +
            (m.is_self ? " is-self" : "") +
            (m.is_leader ? " is-leader" : "");
          const tags = [];
          if (m.is_self)   tags.push('<span class="lobby-member-tag you">YOU</span>');
          if (m.is_leader) tags.push('<span class="lobby-member-tag leader">★ LEADER</span>');
          const stats = [];
          if (m.played_with_me_count > 0) {
            stats.push(`<span class="lobby-member-stat">${m.played_with_me_count}g together</span>`);
            if (m.played_with_me_record) stats.push(`<span class="lobby-member-stat">${m.played_with_me_record}</span>`);
          } else if (!m.is_self) {
            stats.push(`<span class="lobby-member-stat" style="color:var(--text-faint)">no shared games</span>`);
          }
          const lookup = (m.summoner_name && !m.is_self)
            ? `<a class="lobby-member-link" href="https://aggregator-b.invalid/lol/profile/na1/${encodeURIComponent(m.summoner_name)}" target="_blank" rel="noopener">aggregator-b ↗</a>`
            : "";
          li.innerHTML = `<div class="lobby-member-name">${m.summoner_name || "Unknown"}${tags.join("")}</div>` +
                         `<div class="lobby-member-meta">${stats.join("")}${lookup}</div>`;
          ul.appendChild(li);
        });
      }
    }

    // Tips per queue
    const tipsEl = document.getElementById("lv-tips");
    if (tipsEl) {
      const tips = lobby && LV_QUEUE_TIPS[lobby.queue_id];
      if (tips && tips.length) {
        tipsEl.innerHTML = tips.map((t) => `<div class="tip-row">${t}</div>`).join("");
      } else if (lobby) {
        tipsEl.innerHTML = `<div class="home-empty">no tips defined for queue ${lobby.queue_id} — extend LV_QUEUE_TIPS in dashboard.js</div>`;
      } else {
        tipsEl.innerHTML = '<div class="home-empty">queue-specific tips populate when lobby data is available</div>';
      }
    }

    // Recent in this queue (filter match_history client-side via /api/home/summary)
    fetch("/api/home/summary", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((d) => {
        const ul2 = document.getElementById("lv-recent-list");
        const cnt2 = document.getElementById("lv-recent-count");
        if (!ul2) return;
        const all = (d && d.recent) || [];
        // Map queue_id → mode-string for filtering. Best-effort.
        const qid = (lobby && lobby.queue_id) | 0;
        const wantMode = (qid === 450 || qid === 920) ? "ARAM"
                       : (qid === 1700) ? "ARENA"
                       : (qid === 400 || qid === 420 || qid === 430 || qid === 440) ? "SR"
                       : "";
        const filtered = wantMode ? all.filter((m) => (m.mode || "").toUpperCase() === wantMode) : all;
        if (cnt2) cnt2.textContent = filtered.length + (wantMode ? " in " + wantMode : " recent");
        ul2.innerHTML = "";
        filtered.slice(0, 5).forEach((m) => {
          const li = document.createElement("li");
          li.className = "lv-recent-row";
          const grade = String(m.grade || "—")[0];
          const dur = m.duration_s
            ? `${Math.floor(m.duration_s / 60)}:${String(m.duration_s % 60).padStart(2, "0")}` : "";
          li.innerHTML =
            `<span class="lv-recent-grade home-recent-grade ${grade}">${grade}</span>` +
            `<span><strong>${m.champion}</strong> <span class="dim">${_to12((m.timestamp||"").split(" ")[1]?.slice(0,5) || "")}</span></span>` +
            `<span class="dim">${m.kda || "—"}</span>` +
            `<span class="dim">${dur}</span>`;
          ul2.appendChild(li);
        });
        if (!ul2.children.length) ul2.innerHTML = '<li class="home-empty">no recent matches in this queue</li>';
      })
      .catch(() => {});
  }
  // Trigger a refresh of view-lobby on every state envelope when it's
  // the active view (so members/queue update without a manual nav).
  function _maybeRefreshLobbyView() {
    if (_VIEW.current === "lobby") _lobbyViewRefresh();
  }

  // ── Lobby overlay (2026-04-26) ──────────────────────────────────────
  // Pre-queue: shows what queue the user is sitting in + a Find Match
  // button. Hidden during ChampSelect / InProgress (cs-overlay takes
  // over). Find Match is only enabled when localMember.isLeader is true
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
      lcuCmd({ cmd: "start_matchmaking" });
      _setLobbyStatus("starting…", "searching");
      setTimeout(() => { find.disabled = false; }, 1500);
    });
    const cancel = document.getElementById("lobby-cancel-match");
    if (cancel) cancel.addEventListener("click", () => {
      lcuCmd({ cmd: "cancel_matchmaking" });
      _setLobbyStatus("cancelling…", "");
    });
    const qsel = document.getElementById("lobby-queue-select");
    if (qsel) qsel.addEventListener("change", () => {
      const qid = parseInt(qsel.value, 10);
      if (!qid) return;
      lcuCmd({ cmd: "change_queue_type", queue_id: qid });
      _setLobbyStatus("changing queue…", "searching");
      qsel.value = "";  // reset to placeholder
    });
  }
  // Render the party member list from lcu.lobby.members[]. Each member
  // shape (forwarded by Game-PC LCU agent — pending):
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
      // Public-stats fallback link (no Riot key — user opens manually).
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
      party.textContent = max > 0 ? `Party ${size || 1}/${max}` : "Party —";
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
        findLabel.textContent = searching ? "Searching…"
          : found ? "Match Found"
          : (lobby.is_leader ? "Find Match" : "Leader-only");
      }
    }
    // Status line — reads as a single peripheral signal.
    if (searching) _setLobbyStatus("Searching…", "searching");
    else if (found) _setLobbyStatus("Match Found · accept in client", "found");
    else if (!lobby.is_leader) _setLobbyStatus("Awaiting party leader", "");
    else if (!lobby.can_search) _setLobbyStatus("Lobby not ready", "err");
    else _setLobbyStatus("Ready to queue", "");
  }

  function renderChampSelectPanel(lcu) {
    const overlay = document.getElementById("cs-overlay");
    if (!overlay) return;
    // Diagnostic dump (?dbg=1 in URL): one-line console.log of cs.*
    // fields per state poll so we can see what the LCU agent forwards
    // during Mayhem pre-pick (benchChampions vs championPickIntent vs
    // something else). Throttled by a "last-keys" comparison so the
    // console doesn't get spammed on every 2s tick. (2026-04-26 Issue B.)
    if (/[?&]dbg=1/.test(location.search) && lcu && lcu.champ_select) {
      const cs = lcu.champ_select;
      const sig = JSON.stringify({
        phase: lcu.phase,
        keys:  Object.keys(cs).sort(),
        my_champion: cs.my_champion,
        bench_n: (cs.bench || []).length,
        my_team_n: (cs.my_team || []).length,
        their_team_n: (cs.their_team || []).length,
      });
      if (window.__rcLastCsSig !== sig) {
        window.__rcLastCsSig = sig;
        console.log("[rc-dbg] champ_select sig:", sig, "full:", cs);
      }
    }
    if (!lcu || lcu.phase !== "ChampSelect") {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    _csWireButtonsOnce();
    _csWireForceSummsOnce();
    if (!CHAMPS.ready) return;  // names not loaded yet — wait next tick

    const cs = lcu.champ_select || {};
    // ARAM-style mode? Used to hide the enemy team block + collapse the
    // ally row to full width since ARAM doesn't reveal enemies pre-game.
    // Mayhem queue_ids don't always set cs.is_aram, so accept "bench
    // present" as an additional ARAM signal — same fallback used by the
    // bench renderer + analyzer.
    {
      const _aramish = !!(cs.is_aram
                          || (Array.isArray(cs.bench) && cs.bench.length > 0));
      overlay.classList.toggle("aram-mode", _aramish);
    }
    const myCid = cs.my_champion | 0;
    const myName = _csChampName(myCid) || "—";
    const locked = !!cs.my_completed;
    const csMode = _csNormalizeMode(cs);

    // Champion/mode change detection — re-fetches variant list and fires
    // a fresh apply with the default variant. Skipped when champion is
    // unset (null/0) so we don't push during the brief pre-pick window.
    if (myCid > 0 && myName && myName !== "—" &&
        (myCid !== _csLoadout.lastChamp || csMode !== _csLoadout.lastMode)) {
      _csOnChampionOrModeChange(myName, myCid, csMode);
    }
    // (2026-04-26) Always surface the loadout block while in champ-select
    // so the user knows the build chooser exists. Show a placeholder
    // row until they pick a champion. Without this, the block is hidden
    // when myCid===0 and the user reports "no area to select runes/items".
    {
      const _lb = document.getElementById("cs-loadout-block");
      if (_lb && (!myCid || myCid <= 0)) {
        _lb.hidden = false;
        const _list = document.getElementById("cs-build-list");
        if (_list && !_list.children.length) {
          _list.innerHTML =
            '<div class="cs-loadout-empty">Pick a champion above ' +
            '(or click one of the rolled options below) to see build choices</div>';
        }
        _csSetStatus && _csSetStatus("waiting for pick", "");
      }
    }

    // Run the team-comp analyzer (ARAM only) — debounced internally so
    // bench churn during teammate rerolls doesn't burn API calls.
    _csMaybeRunAnalyzer(cs, myCid, myName, csMode);

    const subBits = [];
    if (cs.is_aram) subBits.push("ARAM");
    if (cs.phase) subBits.push(String(cs.phase).toUpperCase());
    if (cs.queue_id) subBits.push("queue " + cs.queue_id);
    const sub = document.getElementById("cs-phase-sub");
    if (sub) sub.textContent = subBits.join(" · ") || "—";

    const iconEl = document.getElementById("cs-my-icon");
    if (iconEl) {
      const cls = myCid ? (locked ? "locked" : "hovering") : "empty";
      iconEl.className = "cs-my-icon " + cls;
      const url = _csChampImg(myCid);
      iconEl.innerHTML = (myCid && url)
        ? `<img src="${url}" alt="${myName}" onerror="this.style.display='none'">`
        : "?";
    }
    const nameEl = document.getElementById("cs-my-name");
    if (nameEl) nameEl.textContent = myName;
    const stateEl = document.getElementById("cs-my-state");
    if (stateEl) {
      stateEl.textContent = locked ? "✓ LOCKED"
        : (myCid ? "⌛ HOVERING — lock to confirm" : "no pick yet");
    }

    const rerollBtn = document.getElementById("cs-reroll-btn");
    // Same is_aram-fallback as the bench: if bench exists, treat as ARAM.
    const _aramish = cs.is_aram || (Array.isArray(cs.bench) && cs.bench.length > 0);
    if (rerollBtn) rerollBtn.hidden = !_aramish;
    const lockBtn = document.getElementById("cs-lock-btn");
    if (lockBtn) {
      lockBtn._currentCid = myCid;
      lockBtn.hidden = locked || !myCid;
    }

    // Build a quick lookup from cellId -> trade record so we can render
    // trade-state badges + decide which allies are click-tradable.
    const tradesByCell = {};
    (cs.trades || []).forEach((t) => {
      if (t && typeof t.cellId === "number") tradesByCell[t.cellId] = t;
    });

    const renderTeam = (containerId, team, includeMe, isAllies) => {
      const el = document.getElementById(containerId);
      if (!el) return;
      // Allies render vertically (top-to-bottom matches in-game ARAM
      // screen orientation). Enemies stay horizontal — no interaction.
      el.className = "cs-team-row" + (isAllies ? " cs-team-vert" : "");
      el.innerHTML = "";
      const arr = (team || []).slice(0, 5);
      while (arr.length < 5) arr.push(null);
      arr.forEach((p) => {
        const cell = document.createElement("div");
        const cid = (p && p.championId) | 0;
        const isMe = !!(includeMe && cid && cid === myCid);
        const baseStateCls = !cid ? "empty" : (p.completed ? "locked" : "hovering");
        const champNm = _csChampName(cid) || (cid ? "cid:" + cid : "—");
        const summ = (p && p.summonerName) || "";
        const url = _csChampImg(cid);

        // Trade interaction — only for ARAM, only for allies, never for me,
        // and only when the cell has a champion.
        let tradeCls = "";
        const trade = (p && typeof p.cellId === "number") ? tradesByCell[p.cellId] : null;
        if (cs.is_aram && isAllies && !isMe && cid) {
          const tstate = (trade && String(trade.state || "").toUpperCase()) || "AVAILABLE";
          if (tstate === "BUSY")            tradeCls = " trade-busy";
          else if (tstate === "SENT")        tradeCls = " trade-sent";
          else if (tstate === "RECEIVED")    tradeCls = " trade-received";
          else                                tradeCls = " trade-able";
        }

        cell.className = "cs-team-cell " + baseStateCls + (isMe ? " me" : "") + tradeCls;
        cell.title = summ ? `${summ} → ${champNm}` : champNm;

        // Vertical (allies) layout uses a side text column for name+summ;
        // horizontal (enemies) keeps the name+summ stacked under the icon.
        if (isAllies) {
          cell.innerHTML =
            (url
              ? `<img src="${url}" alt="" onerror="this.style.display='none'">`
              : '<div style="width:48px;height:48px"></div>') +
            `<div class="cs-cell-text">` +
              `<div class="nm">${champNm}</div>` +
              (summ ? `<div class="summ">${summ.slice(0, 18)}</div>` : "") +
            `</div>`;
        } else {
          cell.innerHTML =
            (url
              ? `<img src="${url}" alt="" onerror="this.style.display='none'">`
              : '<div style="width:48px;height:48px"></div>') +
            `<div class="nm">${champNm.slice(0, 11)}</div>` +
            (summ ? `<div class="summ">${summ.slice(0, 12)}</div>` : "");
        }

        if (tradeCls === " trade-able" && p && typeof p.cellId === "number") {
          const cellId = p.cellId;
          cell.addEventListener("click", () => {
            cell.classList.add("trade-sent");
            cell.classList.remove("trade-able");
            lcuCmd({ cmd: "trade_request", cell_id: cellId });
          });
        } else if (tradeCls === " trade-received" && p && typeof p.cellId === "number") {
          // Incoming offer — append accept-pill + decline-× into the cell.
          // Click anywhere on the cell (except the × button) accepts the
          // trade; the cell's ::after badge is replaced by inline actions.
          const cellId = p.cellId;
          const actions = document.createElement("div");
          actions.className = "cs-trade-actions";
          actions.innerHTML = `<span class="accept-pill">ACCEPT</span>` +
            `<button type="button" class="decline-x" title="Decline trade">×</button>`;
          cell.appendChild(actions);
          // Suppress the ::after badge once we've put real buttons in.
          cell.style.setProperty("--no-after", "1");
          cell.addEventListener("click", (ev) => {
            // Skip if user hit the decline button.
            if (ev.target && ev.target.closest && ev.target.closest(".decline-x")) return;
            lcuCmd({ cmd: "accept_trade", cell_id: cellId });
            cell.classList.remove("trade-received");
            cell.classList.add("trade-sent");  // visual feedback while LCU swaps
          });
          actions.querySelector(".decline-x").addEventListener("click", (ev) => {
            ev.stopPropagation();
            lcuCmd({ cmd: "decline_trade", cell_id: cellId });
            cell.classList.remove("trade-received");
            cell.style.opacity = "0.55";
          });
        }
        el.appendChild(cell);
      });
    };
    renderTeam("cs-allies",  cs.my_team,    true,  true);
    renderTeam("cs-enemies", cs.their_team, false, false);

    const benchBlock = document.getElementById("cs-bench-block");
    if (!benchBlock) return;
    // (2026-04-26) The LCU agent sets cs.is_aram only when queue_id is
    // 450/920. Mayhem variants get other queue ids and slip through, hiding
    // the bench even though it's clearly populated. Treat "has bench" as
    // an authoritative ARAM-style signal — bench champ selection only
    // exists in ARAM modes regardless of queue id.
    // (2026-04-26 v2) Mayhem rolled options surface in cs.rolled_options
    // (extracted from action.championOptions / myTeam[].championOptions /
    // top-level championOptions etc by the agent). When my_champion is
    // 0 AND bench is empty, fall back to rolled_options as the
    // pickable cards. Click fires lock_pick instead of bench_swap since
    // there's no current pick to swap from.
    const _benchPresent = Array.isArray(cs.bench) && cs.bench.length > 0;
    const _rolls = Array.isArray(cs.rolled_options) ? cs.rolled_options : [];
    const _showAsRolls = !_benchPresent && _rolls.length > 0 && (cs.my_champion | 0) === 0;
    const _anyClickable = _benchPresent || _showAsRolls;
    if (!cs.is_aram && !_anyClickable) {
      benchBlock.hidden = true;
      return;
    }
    benchBlock.hidden = false;
    const grid = document.getElementById("cs-bench-grid");
    if (!grid) return;
    // Update the section label to telegraph what these are.
    const benchLabel = benchBlock.querySelector(".cs-bench-label");
    if (benchLabel) {
      benchLabel.textContent = _showAsRolls
        ? "Rolled options — click to pick"
        : "Bench — click for instant swap (no cooldown)";
    }
    const list = _showAsRolls ? _rolls : (cs.bench || []);
    if (!list.length) {
      grid.innerHTML = '<div class="cs-bench-empty">No bench champs yet — wait for a teammate to reroll</div>';
      return;
    }
    grid.innerHTML = "";
    list.forEach((cid) => {
      const champNm = _csChampName(cid) || "cid:" + cid;
      const cell = document.createElement("div");
      cell.className = "cs-bench-cell";
      cell.title = _showAsRolls
        ? "Pick " + champNm
        : "Swap to " + champNm + " (instant)";
      const url = _csChampImg(cid);
      cell.innerHTML =
        (url ? `<img src="${url}" alt="" onerror="this.style.display='none'">` : "") +
        `<div class="nm">${champNm.slice(0, 11)}</div>`;
      cell.addEventListener("click", () => {
        cell.classList.add("swapping");
        // For Mayhem rolled options (no current pick), use lock_pick to
        // commit. For bench rerolls (active pick), bench_swap is instant.
        const cmd = _showAsRolls
          ? { cmd: "lock_pick", championId: cid }
          : { cmd: "bench_swap", championId: cid };
        lcuCmd(cmd);
        setTimeout(() => cell.classList.remove("swapping"), 1200);
      });
      grid.appendChild(cell);
    });
  }

  // 2026-04-25: Cold-start champ-select coaching. When LCU phase is
  // ChampSelect and we have a locked-in champion + enemy team, surface
  // the user's historical adaptation data BEFORE the game starts.
  // Resolves championId integers to names via the CHAMPS byId index.
  const _CS_LIVE = { lastKey: "", inflight: false, lastFetch: 0, lastResult: null };
  function handleChampSelect(lcu) {
    // Render the interactive overlay first (drives visibility on every poll).
    renderChampSelectPanel(lcu);
    renderLobbyPanel(lcu);
    renderHomePanel(lcu);
    // View router: re-resolve view based on current lcu.phase + state.mode.
    // Fires the auto-promote banner if manual blocks an urgent target.
    _viewResolveAndApply(lcu);
    // If view-lobby is active, refresh its content from the new envelope
    // so members / queue / Find Match state update without a manual nav.
    _maybeRefreshLobbyView();
    if (!lcu || lcu.phase !== "ChampSelect") return;
    const cs = lcu.champ_select || {};
    if (!cs.my_champion || cs.my_champion <= 0) return;
    if (!CHAMPS.ready) return;  // wait for champion-name resolver
    const myName = CHAMPS.byId[String(cs.my_champion)];
    if (!myName) return;
    const allies = (cs.my_team || [])
      .map((p) => CHAMPS.byId[String(p && p.championId)])
      .filter(Boolean);
    const enemies = (cs.their_team || [])
      .map((p) => CHAMPS.byId[String(p && p.championId)])
      .filter(Boolean);
    const bench = (cs.bench || [])
      .map((id) => CHAMPS.byId[String(id)])
      .filter(Boolean);
    // Map queue_id to adaptation mode. ARAM = 450/920, Arena = 1700, etc.
    const modeMap = {
      450: "aram", 920: "aram",        // ARAM + ARAM Mayhem
      1700: "arena", 1710: "arena",    // Arena + variants
      400: "sr_draft", 420: "sr_ranked", 430: "sr_ranked", 440: "sr_ranked",
      830: "sr_ranked", 840: "sr_ranked", 850: "sr_ranked",   // co-op vs AI
    };
    const adaptMode = modeMap[cs.queue_id] || "aram";
    fetchAdaptation(myName, adaptMode === "sr_draft" ? "sr" : adaptMode, enemies);

    // Live Haiku coaching — debounced + key-deduped so we only fire when
    // the actual pick state changes (champion or team comp), not on every
    // 2 s state poll. ~1 Haiku call per ~10 s of active drafting.
    const liveKey = [
      myName, cs.queue_id, allies.join("|"), enemies.join("|"), bench.join("|"),
    ].join("/");
    const now = Date.now();
    if (liveKey === _CS_LIVE.lastKey) return;
    if (now - _CS_LIVE.lastFetch < 6000) return;   // 6 s minimum spacing
    if (_CS_LIVE.inflight) return;
    _CS_LIVE.lastKey = liveKey;
    _CS_LIVE.lastFetch = now;
    _CS_LIVE.inflight = true;
    fetch("/api/champ-select-coach", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        is_aram: !!cs.is_aram,
        queue_id: cs.queue_id,
        my_champion: myName,
        my_team: allies,
        their_team: enemies,
        bench: bench,
      }),
    })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        _CS_LIVE.inflight = false;
        if (!data || !data.ok) return;
        _CS_LIVE.lastResult = data;
        renderChampSelectCoach(data);
      })
      .catch(() => { _CS_LIVE.inflight = false; });
  }

  // Light renderer — drops the Haiku output into the Right Now action +
  // immediate slots while in champ-select. Keeps the existing in-game
  // UI surface; switches content when phase=ChampSelect.
  function renderChampSelectCoach(data) {
    if (!RN.action || !RN.immediate) return;
    const head = data.advice || "(no advice)";
    RN.action.innerHTML = "▶ " + head;
    const lines = [];
    if (data.summoners) lines.push("Summoners: " + data.summoners);
    if (data.swap)      lines.push("Swap: " + data.swap);
    if (data.watchout)  lines.push("Watch: " + data.watchout);
    RN.immediate.textContent = lines.join("  •  ");
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
            ? `warm — ${turns} turn(s), idle ${idle}s`
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
            LAT.footer.textContent = "latency —";
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
            adaptNotice.textContent = "refreshing historic data — new match being incorporated";
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
  // bounded by the 2s full-frame upload cadence — pointless to poll
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

  async function refreshVisionOverlay() {
    if (!VT_OVERLAY) return;
    if (document.hidden) return;
    if (!MM.imgWrap || MM.imgWrap.classList.contains("hidden")) {
      VT_OVERLAY.style.display = "none";
      return;
    }
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
    // Size the canvas to the rendered <img> bounds (it's centered in the
    // wrap with margin auto and padded — getBoundingClientRect gives the
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

  // ── Coach decisions banner ─────────────────────────────────────────
  // Polls /api/decisions, renders pending coachable moments as a
  // banner between header and main. Clicking Contest/Give/Skip POSTs
  // to /api/decisions/<id> and animates removal. Records survive in
  // data/decisions_log.jsonl on the backend for postmortem (V2).
  const COACH_DECISIONS = {
    section: el("coach-decisions"),
    list: el("coach-decisions-list"),
    intervalMs: 1500,
    resolving: new Set(),   // ids currently animating-out (suppress redraw)
  };

  function renderCoachDecisions(pending) {
    const C = COACH_DECISIONS;
    if (!C.section || !C.list) return;
    if (!Array.isArray(pending) || pending.length === 0) {
      // Don't hide while animating — would yank the row mid-animation.
      if (C.resolving.size === 0) C.section.hidden = true;
      C.list.innerHTML = "";
      return;
    }
    C.section.hidden = false;
    // Diff by id so we don't re-create rows that already exist (animations
    // re-run on every render = visual chaos when poll fires every 1.5s).
    const wantIds = new Set(pending.map(p => p.id));
    for (const li of Array.from(C.list.children)) {
      if (!wantIds.has(li.dataset.id)) li.remove();
    }
    const haveIds = new Set(Array.from(C.list.children).map(li => li.dataset.id));
    for (const p of pending) {
      if (haveIds.has(p.id) || C.resolving.has(p.id)) continue;
      const li = document.createElement("li");
      li.className = "coach-decision";
      li.dataset.id = p.id;
      li.dataset.type = p.type || "";

      const text = document.createElement("div");
      text.className = "coach-decision-text";
      const title = document.createElement("p");
      title.className = "coach-decision-title";
      title.textContent = p.title || p.id;
      const sub = document.createElement("p");
      sub.className = "coach-decision-sub";
      sub.textContent = p.subtitle || "";
      text.appendChild(title);
      if (p.subtitle) text.appendChild(sub);

      const actions = document.createElement("div");
      actions.className = "coach-decision-actions";
      const opts = (Array.isArray(p.options) && p.options.length)
        ? p.options : ["contest", "give"];
      // Always offer skip as a final option so the user can dismiss.
      const allOpts = opts.includes("skip") ? opts : [...opts, "skip"];
      for (const opt of allOpts) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "coach-decision-btn";
        btn.dataset.choice = opt;
        btn.textContent = opt.toUpperCase();
        btn.addEventListener("click", () => recordChoice(p.id, opt, li, actions));
        actions.appendChild(btn);
      }

      li.appendChild(text);
      li.appendChild(actions);
      C.list.appendChild(li);
    }
  }

  async function recordChoice(id, choice, li, actions) {
    // Disable the row's buttons immediately so a fast double-click can't
    // double-post. Mark id as resolving so the next poll doesn't repaint.
    COACH_DECISIONS.resolving.add(id);
    for (const b of actions.querySelectorAll("button")) b.disabled = true;
    li.classList.add("resolving");
    try {
      const r = await fetch(`/api/decisions/${encodeURIComponent(id)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({choice}),
      });
      if (!r.ok) {
        // Roll back: re-enable, drop resolving so next poll resurrects it.
        for (const b of actions.querySelectorAll("button")) b.disabled = false;
        li.classList.remove("resolving");
        COACH_DECISIONS.resolving.delete(id);
        return;
      }
    } catch (_) {
      for (const b of actions.querySelectorAll("button")) b.disabled = false;
      li.classList.remove("resolving");
      COACH_DECISIONS.resolving.delete(id);
      return;
    }
    // Success — let CSS finish the fade, then remove + clear resolving.
    setTimeout(() => {
      try { li.remove(); } catch (_) {}
      COACH_DECISIONS.resolving.delete(id);
      // If list is now empty, hide the banner.
      if (COACH_DECISIONS.list && COACH_DECISIONS.list.children.length === 0) {
        if (COACH_DECISIONS.section) COACH_DECISIONS.section.hidden = true;
      }
    }, 240);
  }

  async function pollCoachDecisions() {
    if (document.hidden) return;
    try {
      const r = await fetch("/api/decisions");
      if (!r.ok) return;
      const d = await r.json();
      renderCoachDecisions(d.pending || []);
    } catch (_) {}
  }
  setInterval(pollCoachDecisions, COACH_DECISIONS.intervalMs);
  pollCoachDecisions();

  // ── Input bar → /api/input (with chat history) ─────────────────────
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
    parts.push(`intent: ${env.intent || "—"}`);
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
  // Resets on fixture switch (page navigation wipes it naturally).
  const SIM_THREAD = [];       // [{user, reply, intent}, ...]
  const SIM_THREAD_CAP = 5;

  // Detect sim mode from URL — matches the ?sim=<name> gate used by
  // sim.js. Stays false when no sim param is present.
  const SIM_ACTIVE = new URLSearchParams(window.location.search).has("sim");
  const SIM_FIXTURE = new URLSearchParams(window.location.search).get("sim") || null;

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
    if (SIM_ACTIVE) {
      body.sim_context = true;
      body.sim_fixture = SIM_FIXTURE;
      body.history = SIM_THREAD.slice(-SIM_THREAD_CAP);
    }
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

      if (SIM_ACTIVE) {
        SIM_THREAD.push({
          user: text,
          reply: env.reply,
          intent: env.intent,
        });
        while (SIM_THREAD.length > SIM_THREAD_CAP) SIM_THREAD.shift();
      }

      refreshEnv();       // warm indicator
      refreshActivity();  // show the filed tasks in ticker

      // Round 42: auto-reload when a ui-proposal completes.
      // Without bypass the task is still deterministic auto-dispatched;
      // with bypass it's user_override=true so the frozen-file guard
      // doesn't gate it. Poll briefly and reload on success.
      const filedTasks = env.filed || [];
      const looksLikeUIProposal =
        SIM_ACTIVE && !env.refused && filedTasks.length &&
        (env.proposed_changes && env.proposed_changes.length);
      if (looksLikeUIProposal) {
        const tid = filedTasks[0];
        const status = document.createElement("div");
        status.className = "ui-proposal-status";
        status.textContent = `applying task ${tid}…`;
        INPUT.turns.lastChild.appendChild(status);
        const out = await _pollTaskUntilDone(tid);
        if (out.ok) {
          status.textContent = "applied — reloading…";
          setTimeout(() => window.location.reload(), 400);
        } else if (out.timeout) {
          status.textContent =
            `still dispatching (task ${tid}) — refresh manually when ready`;
        } else {
          status.textContent =
            `apply failed (task ${tid}) — open it for error detail`;
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
      // Unknown envelope — log raw.
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
    // Lightweight advisory toast — coral card that slides in from the
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

  // Restore persisted preferences (zoom / zen) from prior session. Also
  // builds a footer chip listing the active flags. The Shift+L header-lock
  // mechanism was removed 2026-04-23 — it broke the UI composition when
  // hidden pills were temporarily un-hidden during measurement, which
  // displaced the visible pills' captured positions. The natural flex
  // layout is stable enough once the advisory badge height is normalised.
  (function restorePrefs() {
    try {
      const savedZoom = localStorage.getItem("rc-body-zoom");
      if (savedZoom) document.body.style.zoom = savedZoom;
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

  // Footer prefs chip — shows "zen:off" and/or "zoom:1×" when the user is
  // running with non-default prefs. Recomputed from live state on each call
  // so a Z-toggle (or zoom hotkey) updates the chip immediately rather
  // than reflecting the value at page-load time only.
  function _refreshPrefsChip() {
    const zenOn = document.body.dataset.zen === "1";
    const z = localStorage.getItem("rc-body-zoom");
    const flags = [];
    if (!zenOn) flags.push("zen:off");
    if (z && parseFloat(z) < 1.1) flags.push("zoom:1×");
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
        localStorage.removeItem("rc-body-zoom");
        localStorage.removeItem("rc-header-lock");
        window.location.reload();
      });
      anchor.parentNode.insertBefore(chip, anchor);
    }
    chip.textContent = flags.join(" · ");
  }

  // Post-auto-reload banner — lets user know the rebuild landed.
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
    // Shift+R resets saved preferences (zen/zoom) + reloads.
    if (e.shiftKey && (e.key === "R" || e.key === "r")) {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      try {
        localStorage.removeItem("rc-zen");
        localStorage.removeItem("rc-body-zoom");
        localStorage.removeItem("rc-header-lock");
      } catch (_) {}
      window.location.reload();
      return;
    }
    // A triggers the ANALYZE NOW footer button — quick kickoff.
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
    // Z toggles "zen" mode — hides Next + Adaptation panels so the grid
    // re-composes around Minimap + Right Now + Item Build. Uses body data
    // attribute so CSS does the rest. Zen is the default view, so we
    // persist "0" on opt-out (not "" — restorePrefs treats null as on).
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
        <div><kbd>1</kbd>–<kbd>9</kbd> switch sim fixture (dev mode only)</div>
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

  // Input clear button — shows only when the field has content.
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
  // onState({mode: st.mode || "client"}) — but /api/state returns the
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
      // the last 4s — SSE has already delivered the same payload.
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
          // /api/health returns raw health.json — contains aram_mode,
          // arena_mode, tft_mode, has_game, mode flags onHealth needs.
          onHealth({ type: "health", source: "health-http", payload: hp });
        }
        if (stResp.ok) {
          const st = await stResp.json();
          const fileMode = st.mode_key || "client";
          // The "coach" sub-object is the state envelope's payload —
          // contains action, immediate, kda, augments, item_build, etc.
          const coachPayload = st.coach || st;
          onState({ type: "state", source: "state-http",
                    mode: fileMode, payload: coachPayload });
          // 2026-04-25: cold-start champ-select prep — surface adaptation
          // history during champ-select via the LCU snapshot.
          handleChampSelect(st.lcu);
        }
      } catch (_) { /* ignore — WS may come back */ }
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
          onState({ type: "state", source: "state-sse",
                    mode: fileMode, payload: coachPayload });
          if (st.lcu) handleChampSelect(st.lcu);
        } catch (_) { /* malformed event — skip */ }
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
          if (st && st.lcu) handleChampSelect(st.lcu);
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
  // device viewing the dashboard — iPad, Game-PC, Legion, whatever —
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
      btn.title = on ? "Voice on — speaks Right Now headline changes" : "Voice off";
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
      if (!txt || txt === "—") return;
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
  // shows it) — we just tee a copy server-side.
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
      } catch (_) { /* localStorage full / disabled — ignore */ }
    }
    function flushQueueAfterSuccess() {
      const queued = readQueue();
      if (!queued.length) return;
      try { localStorage.removeItem(QUEUE_KEY); } catch (_) {}
      // Best-effort drain — fire-and-forget so we don't block the tab.
      queued.forEach((entry, i) => {
        setTimeout(() => {
          try {
            fetch("/api/console-error", {
              method: "POST", cache: "no-store",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...entry, _replay: true }),
            }).catch(() => {});
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
          // Network failure / endpoint down — queue for next success.
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
    // Tee console.error → pipe. We don't tee console.warn/log — too
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
  // Event delegation on document.body — catches dynamically-rendered
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
      const words = String(text).split(/\s+/).filter(Boolean);
      const lines = [];
      for (let i = 0; i < words.length; i += 6) {
        lines.push(words.slice(i, i + 6).join(" "));
      }
      return lines.join("\n");
    }
    // Placement (2026-04-24 rewrite): tooltip always sits immediately
    // below-right of the cursor, with viewport-edge clamping that pulls
    // it back inside if the natural position would clip. Previous build
    // used quadrant-based flipping (left of cursor in right half of
    // screen, above cursor in bottom half) which felt like the tip
    // "jumped" between anchor positions; user wants a single consistent
    // direction relative to cursor.
    //
    // Body-zoom compensation: the dashboard sets `body { zoom: 1.33 }`,
    // so all UI content scales up uniformly. `event.clientX/Y` reports
    // viewport device pixels, but the tip is a descendant of the zoomed
    // body — its `style.left` is interpreted in body-zoom CSS pixels and
    // rendered at that × zoom visually. Without dividing cursor coords
    // by the zoom factor the tip drifted roughly `cursorX × (zoom − 1)`
    // to the right, producing the "~1 inch down, 2 inches over" offset
    // the user flagged. We sample the live computed zoom each call so a
    // JS zoom-override still works.
    function place() {
      const z = parseFloat(getComputedStyle(document.body).zoom) || 1;
      tip.style.left = "-9999px"; tip.style.top = "-9999px";
      const tr = tip.getBoundingClientRect();
      // tr is in viewport device pixels, but the final position needs to
      // be expressed in body-zoom CSS pixels — convert everything once.
      const trW = tr.width  / z;
      const trH = tr.height / z;
      const vw  = window.innerWidth  / z;
      const vh  = window.innerHeight / z;
      const cx  = cursorX / z;
      const cy  = cursorY / z;
      // Default: just below-right of the cursor.
      let left = cx + OFFSET;
      let top  = cy + OFFSET;
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
      const text = capture(el);
      if (!text) return;
      activeEl = el;
      tip.textContent = wrapSixWords(text);
      tip.classList.add("show");
      requestAnimationFrame(place);
    }
    function hide() {
      activeEl = null;
      tip.classList.remove("show");
    }
    // Track cursor continuously — mousemove fires during hover so the tip
    // follows the pointer if the user drags the cursor inside the anchor.
    document.body.addEventListener("mousemove", e => {
      cursorX = e.clientX; cursorY = e.clientY;
      if (activeEl) place();
    });
    document.body.addEventListener("mouseover", e => {
      cursorX = e.clientX; cursorY = e.clientY;
      const el = e.target.closest && e.target.closest("[title], [data-tt]");
      if (!el || el === activeEl) return;
      clearTimeout(hideTimer);
      show(el);
    });
    document.body.addEventListener("mouseout", e => {
      const el = e.target.closest && e.target.closest("[title], [data-tt]");
      if (!el) return;
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, 80);
    });
    // Kill any stuck tip when the anchor scrolls / resizes / user clicks.
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    document.body.addEventListener("click", hide, true);
  })();

  // ───── AUDIT 2026-04-28 — proposals 3.3, 3.6 + 4.4, 2.1 ─────
  // Sticky-header compression on scroll + skeleton loaders + health
  // rollup dot + cost-tile poll. All passive — no-ops if the target
  // elements are absent.
  (function rcAuditUiEnhancements() {
    const header = document.querySelector("header");
    const COMPRESS_AT = 200;
    if (header) {
      // 3.3 — compress on scroll-Y > 200, restore below.
      window.addEventListener("scroll", () => {
        const y = window.scrollY || document.documentElement.scrollTop || 0;
        if (y > COMPRESS_AT) header.dataset.compressed = "1";
        else delete header.dataset.compressed;
      }, { passive: true });

      // 4.4 — health rollup dot ("claude cost pill" — tooltip carries
      // Claude $/day + supervisor + vision health). 2026-04-29: moved
      // from header.header-row-2 to the footer (right of mode-pill) per
      // user — it was visually distracting in the header. Lookup goes
      // both header AND footer for back-compat with any cached layout.
      try {
        let dot = document.querySelector(".health-dot");
        if (!dot) {
          dot = document.createElement("span");
          dot.className = "health-dot yellow";
          dot.title = "Loading…";
          dot.setAttribute("data-tt", "Loading…");
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
              if (bridge.status === "unknown" || bridge.age_s == null) {
                bridgeLine = "bridge no-data";
              } else {
                const a = bridge.age_s;
                const ago = a < 60 ? `${Math.round(a)}s`
                          : a < 3600 ? `${Math.round(a/60)}m`
                          : `${(a/3600).toFixed(1)}h`;
                const label = bridge.status === "green" ? "ok"
                            : bridge.status === "yellow" ? "silent"
                            : "dead";
                bridgeLine = `bridge ${label} · last ${ago} ago`;
              }
              const lines = [
                `RC ${rcVer} (pid ${j.rc?.pid ?? "?"})`,
                `supervisor pid ${sup.pid ?? "?"} · run_id ${runId} · ${oslock}`,
                `vision ${j.vision?.alive ? "up" : "down"}` +
                  (j.vision?.uptime_s ? ` · uptime ${Math.round(j.vision.uptime_s/60)}m` : ""),
                `cost $${(cost.today_usd || 0).toFixed(2)} · ${banner}`,
                bridgeLine,
              ];
              dot.title = lines.join("\n");
              dot.setAttribute("data-tt", dot.title);
            })
            .catch(()=>{});
        };
        refreshHealth();
        setInterval(refreshHealth, 15000);
      } catch (e) { /* never let the dot break the dashboard */ }
    }

    // 3.7 — Hot-reload poller (2026-04-30). Polls /api/asset-stamp
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

    // 3.6 — flag elements with data-rc-skel for the first 500 ms after
    // game-start. Anything bearing the attribute that still reads "—"
    // gets the .rc-skel class until the first data tick lands.
    document.querySelectorAll("[data-rc-skel]").forEach(el => {
      el.classList.add("rc-skel");
    });
    // Strip skeletons once any non-placeholder text appears in the
    // tracked element. Polled cheaply from the regular state tick.
    window.addEventListener("rc:state-tick", () => {
      document.querySelectorAll(".rc-skel").forEach(el => {
        const t = (el.textContent || "").trim();
        if (t && t !== "—" && t.length > 0) el.classList.remove("rc-skel");
      });
    });
  })();
})();
