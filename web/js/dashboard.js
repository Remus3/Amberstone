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
            const ts = (e.ts || "").slice(11, 19);   // HH:MM:SS
            const op = (e.op || "").slice(0, 34);
            // Op-type glyph prefix for fast pattern-match of recent events.
            const glyph = _opGlyph(e.op);
            span.innerHTML =
              `<span class="ev-glyph">${glyph}</span>` +
              `<span class="ev-ts">${ts}</span>` +
              `<span class="ev-op"></span>` +
              `<span class="ev-kind"></span>`;
            span.children[2].textContent = op;
            span.children[3].textContent = e.event || "";
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
  const VIEW_IDS = ["home","lobby","last-match","session","history","loadouts","settings","diagnostics"];
  const VIEW_LABELS = {
    "home":"Home","lobby":"Lobby","last-match":"Last Match","session":"Session",
    "history":"History","loadouts":"Loadouts","settings":"Settings","diagnostics":"Diagnostics",
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
    if (viewId === "session")     { _sessionFetchAndRender(); }
    if (viewId === "history")     { _historyWireOnce(); _historyFetchAndRender(); }
    if (viewId === "loadouts")    { _loadoutsWireOnce(); _loadoutsFetchAndRender(); }
    if (viewId === "diagnostics") { _diagWireOnce(); _diagFetchAndRender(); }
    if (viewId === "settings")    { _settingsRefresh(); }
  }
  function _viewUpdateTitleLabel(viewId) {
    const el = document.getElementById("view-current-label");
    if (!el) return;
    el.textContent = (_VIEW.manual ? "" : "AUTO · ") + (VIEW_LABELS[viewId] || viewId).toUpperCase();
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
    } else {
      _viewMenuClose();
    }
  }
  function _viewWireOnce() {
    if (_VIEW._wired) return;
    _VIEW._wired = true;
    const trig = document.getElementById("view-trigger");
    const menu = document.getElementById("view-menu");
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
        } else {
          _viewSaveManual(v);
          location.hash = "#" + v;
        }
        _viewResolveAndApply();
      });
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
        winPill.className = "win-pill win-" + (
          v >= 65 ? "strong" :
          v >= 50 ? "even"   :
          v >= 35 ? "behind" : "losing"
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

  // Render the variant list as selectable rows. Each row carries inline
  // keystone + first-N item icons so the user can compare builds at a
  // glance. Clicking a row selects it (radio-style) and triggers an
  // /api/loadout/apply push. Rebuilt 2026-04-26 — the old <select>
  // dropdown hid alternate builds behind a click and gave the user the
  // impression there was only one choice.
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
          cell.className = "cs-build-item";
          const nm = (v.item_names || [])[idx] || ("item " + iid);
          cell.title = nm;
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
        cell.className = "cs-build-item";
        cell.title = (v.item_names || [])[idx] || ("item " + iid);
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
            li.innerHTML = `<span class="diag-conn-dot ${c.ok ? "ok" : "err"}"></span>` +
              `<span style="flex:1; color:var(--text); font-weight:700">${c.name}</span>` +
              `<span class="dim" style="font-size:10px">${c.detail || ""}</span>`;
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
  }
  function _diagWireOnce() {
    if (window.__diagWired) return;
    window.__diagWired = true;
    const r = document.getElementById("diag-refresh");
    if (r) r.addEventListener("click", _diagFetchAndRender);
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
      ul.innerHTML = '<li class="home-empty">no matches yet</li>';
      return;
    }
    for (const m of rows) {
      const li = document.createElement("li");
      li.className = "home-recent-row";
      const grade = String(m.grade || "—").toUpperCase()[0] || "—";
      const dur = m.duration_s
        ? `${Math.floor(m.duration_s / 60)}:${String(m.duration_s % 60).padStart(2,"0")}`
        : "";
      const tsShort = (m.timestamp || "").split(" ")[1]?.slice(0,5) || "";
      li.innerHTML =
        `<span class="home-recent-grade ${grade}">${grade}</span>` +
        `<span><span class="home-recent-champ">${m.champion || "?"}</span> ` +
          `<span class="home-recent-meta">${tsShort} · ${dur}</span></span>` +
        `<span class="home-recent-kda">${m.kda || "—"}</span>` +
        `<span class="home-recent-mode">${m.mode || ""}</span>`;
      ul.appendChild(li);
    }
  }
  function _homeRenderWeek(rows) {
    const ul = document.getElementById("home-week-list");
    if (!ul) return;
    ul.innerHTML = "";
    if (!rows || !rows.length) {
      ul.innerHTML = '<li class="home-empty">no games this week</li>';
      return;
    }
    for (const r of rows) {
      const li = document.createElement("li");
      li.className = "home-week-row";
      const grade = String(r.best_grade || "—").toUpperCase()[0] || "—";
      li.innerHTML =
        `<span class="home-week-champ">${r.champion}</span>` +
        `<span class="home-week-games">${r.games}g</span>` +
        `<span class="home-week-kda">${r.avg_kda.toFixed(1)}</span>` +
        `<span class="home-week-grade home-recent-grade ${grade}">${grade}</span>`;
      ul.appendChild(li);
    }
  }
  function _homeRenderToday(t) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const games = (t && t.games) || 0;
    set("home-today-count", games > 0 ? `${games} game${games===1?"":"s"}` : "");
    set("home-today-kda", t && t.total_kda ? t.total_kda : "—");
    set("home-today-avg", t && t.avg_kda ? t.avg_kda.toFixed(2) : "—");
    const gradeStr = t && t.grades
      ? Object.entries(t.grades).map(([g,n]) => `${g}×${n}`).join(" ")
      : "—";
    set("home-today-grades", gradeStr || "—");
    const modeStr = t && t.modes
      ? Object.entries(t.modes).map(([m,n]) => `${m} ${n}`).join(" · ")
      : "—";
    set("home-today-modes", modeStr || "—");
  }
  function _homeRenderServices(rows) {
    const ul = document.getElementById("home-services-list");
    if (!ul) return;
    ul.innerHTML = "";
    if (!rows || !rows.length) {
      ul.innerHTML = '<li class="home-empty">no services reporting</li>';
      return;
    }
    for (const s of rows) {
      const li = document.createElement("li");
      li.className = "home-services-row";
      li.innerHTML =
        `<span class="home-services-dot ${s.ok ? "ok" : "err"}"></span>` +
        `<span class="home-services-name">${s.name}</span>` +
        `<span class="home-services-detail">${s.detail || ""}</span>`;
      ul.appendChild(li);
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
        _homeRenderToday(data.today || {});
        _homeRenderRecent(data.recent || []);
        _homeRenderWeek(data.this_week || []);
        _homeRenderServices(data.services || []);
      })
      .catch(() => { _HOME.fetching = false; });
  }
  function renderHomePanel(lcu) {
    const overlay = document.getElementById("home-overlay");
    if (!overlay) return;
    if (!_homeShouldShow(lcu)) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    // Initial fetch + 20s refresh tick (registered once).
    if (!_HOME.lastFetchAt) _homeFetchAndRender();
    if (!overlay._tickWired) {
      overlay._tickWired = true;
      setInterval(() => {
        if (!_homeShouldShow(state.latest && state.latest.lcu ? { phase: state.latest.lcu.phase } : null)) return;
        _homeFetchAndRender();
      }, _HOME.intervalMs);
    }
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
    const _benchPresent = Array.isArray(cs.bench) && cs.bench.length > 0;
    if (!cs.is_aram && !_benchPresent) {
      benchBlock.hidden = true;
      return;
    }
    benchBlock.hidden = false;
    const grid = document.getElementById("cs-bench-grid");
    if (!grid) return;
    const bench = cs.bench || [];
    if (!bench.length) {
      grid.innerHTML = '<div class="cs-bench-empty">No bench champs yet — wait for a teammate to reroll</div>';
      return;
    }
    grid.innerHTML = "";
    bench.forEach((cid) => {
      const champNm = _csChampName(cid) || "cid:" + cid;
      const cell = document.createElement("div");
      cell.className = "cs-bench-cell";
      cell.title = "Swap to " + champNm + " (instant)";
      const url = _csChampImg(cid);
      cell.innerHTML =
        (url ? `<img src="${url}" alt="" onerror="this.style.display='none'">` : "") +
        `<div class="nm">${champNm.slice(0, 11)}</div>`;
      cell.addEventListener("click", () => {
        cell.classList.add("swapping");
        lcuCmd({ cmd: "bench_swap", championId: cid });
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
  // Polls /api/minimap-crop every 2s when mode ∈ {sr, aram, brawl} and
  // the page is visible. Falls back silently — the backend returns 502
  // if the vision server isn't up, in which case we hide the img and
  // keep showing the KV scaffold.
  const MINIMAP_MODES = new Set(["sr", "aram", "brawl"]);
  let minimapTimer = null;
  let lastMinimapMode = null;

  async function refreshMinimap() {
    if (document.hidden) return;
    if (!MINIMAP_MODES.has(state.mode)) {
      MM.imgWrap.classList.add("hidden");
      lastMinimapMode = null;
      return;
    }
    const tNow = Date.now();
    const bust = tNow - (tNow % 2000);   // cache-bust per 2s window
    try {
      const resp = await fetch(`/api/minimap-crop?mode=${state.mode}&_=${bust}`);
      if (!resp.ok) {
        MM.imgWrap.classList.add("hidden");
        return;
      }
      const blob = await resp.blob();
      if (blob.type !== "image/png") {
        MM.imgWrap.classList.add("hidden");
        return;
      }
      // Revoke previous blob URL to avoid leaks.
      const prev = MM.img.dataset.blobUrl;
      if (prev) { try { URL.revokeObjectURL(prev); } catch (_) {} }
      const url = URL.createObjectURL(blob);
      MM.img.dataset.blobUrl = url;
      MM.img.src = url;
      const size = (blob.size / 1024).toFixed(1);
      MM.imgCaption.textContent = `${state.mode.toUpperCase()} · ${size} KB · ${new Date().toLocaleTimeString()}`;
      MM.imgWrap.classList.remove("hidden", "stale");
      lastMinimapMode = state.mode;
    } catch (e) {
      MM.imgWrap.classList.add("stale");
    }
  }
  minimapTimer = setInterval(refreshMinimap, 2000);
  refreshMinimap();   // fire once on load

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
        // Compact 24h HH:MM:SS — saves header width vs locale "6:51:12 AM".
        const hbT = new Date((env.t || Date.now()/1000) * 1000);
        const pad = (n) => n.toString().padStart(2, "0");
        hbEl.textContent = `♥ ${pad(hbT.getHours())}:${pad(hbT.getMinutes())}:${pad(hbT.getSeconds())}`;
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
      const spacer = document.querySelector("footer .spacer");
      if (!spacer) return;
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
      spacer.parentNode.insertBefore(chip, spacer);
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

  // ── Independent LCU / champ-select poller (2026-04-26) ────────────
  // The WS state envelope only contains coach data — LCU phase /
  // champ_select / trades come exclusively via /api/state's `lcu` key.
  // Without this poller, the cs-overlay only updates when the WS-stale
  // fallback fires (~5s+ after WS dies). When WS is alive, the overlay
  // would NEVER appear during champ-select. Polls every 2s so the
  // overlay shows up fast when phase=ChampSelect, and disappears just
  // as fast when phase flips back.
  (function setupLcuPoller() {
    let inflight = false;
    async function pollLcu() {
      if (document.hidden) return;
      if (inflight) return;
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
    async function check() {
      try {
        const r = await fetch("/api/ui-version", { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (known === null) {
          known = j.v;
          // Stamp version in footer so current build is visible at a glance.
          const host = document.querySelector("footer .ui-version");
          if (!host) {
            const span = document.createElement("span");
            span.className = "ui-version";
            span.textContent = `ui ${j.v}`;
            const spacer = document.querySelector("footer .spacer");
            if (spacer) spacer.parentNode.insertBefore(span, spacer);
          }
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
})();
