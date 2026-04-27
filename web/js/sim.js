/* Round 40 — Dev Preview mode.
 *
 * Loaded BEFORE dashboard.js (so our patches land before the dashboard
 * wires its WebSocket + fetch polling). Activation is gated on
 * ?sim=<name> in the URL — no sim param means this file is a no-op.
 *
 * When active:
 *   • Banner at the top of the page shows DEV PREVIEW + fixture name
 *     + mode-switcher dropdown + "exit preview" link.
 *   • window.fetch is intercepted: /api/* calls return synthesised
 *     responses from the fixture (with per-endpoint safe defaults when
 *     the fixture omits a section).
 *   • window.WebSocket is replaced with a fake that fires one health
 *     envelope then one state envelope on "open", producing the same
 *     render result as a live connection.
 *   • Each panel that fails to get fixture data has a "(fixture: no
 *     data)" overlay via the `.sim-missing` CSS class.
 */
(() => {
  const params = new URLSearchParams(window.location.search);
  const simName = params.get("sim");
  if (!simName) return;       // Live mode — do nothing.

  // Prevent the real dashboard from racing ahead while we set up.
  // We block the original fetch/WebSocket as soon as this script runs;
  // dashboard.js will inherit our overrides.

  const _origFetch = window.fetch.bind(window);
  const _origWebSocket = window.WebSocket;

  // Mutable state — the currently loaded fixture.
  let FIXTURE = null;
  // FakeSockets that were created before the fixture finished loading.
  // Once _bootstrap resolves FIXTURE we walk this list and replay.
  const _pendingSockets = [];

  // ---- Placeholder fallbacks for routes the fixture didn't fill ------
  const ROUTE_DEFAULTS = {
    "/api/adaptation":  { present: false, champion: "", mode: "", counters: [], top_items: [], first_legendary: [] },
    "/api/trending":    { mode: "aram", hot: [], cold: [] },
    "/api/activity":    { events: [], snapshot: { ready: 0, in_progress: 0, completed: 0, failed: 0 } },
    "/api/env":         { warm_agent7: false, flags: {}, auto_analyze: { state: "unknown" } },
    "/api/advisories":  { advisories: [] },
    "/api/task/":       { error: "sim: no detail" },
    "/api/insight-card": { card: "(sim: no insight card)" },
    "/api/analyze":     { status: "sim-ack", ran: false },
    "/api/digest":      { mode: "all", count: 0, insights: [] },
    "/api/session":     { since: "sim", games: 0, wins: 0, losses: 0, avg_kda: null, per_mode: {}, champions: [] },
    "/api/session-games": { since: "sim", games: [] },
    "/api/time-of-day": { mode: "all", buckets: [], total_games: 0, best: null, worst: null },
    "/api/day-of-week": { mode: "all", buckets: [], total_games: 0, best: null, worst: null },
    "/api/duration":    { mode: "all", buckets: [], total_games: 0, best: null, worst: null },
  };

  // Which fixture key feeds which endpoint prefix.
  const ROUTE_MAP = [
    ["/api/adaptation",  "adaptation"],
    ["/api/trending",    "trending"],
    ["/api/activity",    "activity"],
    ["/api/env",         "env"],
    ["/api/advisories",  "advisories"],
    ["/api/digest",      "digest"],
    ["/api/session-games", "session_games"],
    ["/api/session",     "session"],
    ["/api/time-of-day", "time_of_day"],
    ["/api/day-of-week", "day_of_week"],
    ["/api/duration",    "duration"],
    ["/api/insight-card", "insight_card"],
    ["/api/task/",       "task_detail"],
    ["/api/analyze",     "analyze_ack"],
  ];

  function _matchRoute(path) {
    for (const [prefix, key] of ROUTE_MAP) {
      if (path.startsWith(prefix)) return [prefix, key];
    }
    return [null, null];
  }

  function _synthResponse(path) {
    // Sim POSTs are best-effort: we just ack with the default payload.
    const [prefix, key] = _matchRoute(path);
    let body;
    if (key && FIXTURE && Object.prototype.hasOwnProperty.call(FIXTURE, key)) {
      body = FIXTURE[key];
    } else if (prefix && ROUTE_DEFAULTS[prefix] !== undefined) {
      body = ROUTE_DEFAULTS[prefix];
    } else {
      body = { _sim: true, _path: path };
    }
    const json = JSON.stringify(body);
    return new Response(json, {
      status: 200,
      statusText: "OK (sim)",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "X-Sim-Fixture": (FIXTURE && FIXTURE.meta && FIXTURE.meta.name) || simName,
      },
    });
  }

  // ---- fetch patch ---------------------------------------------------
  // Endpoints we explicitly want to hit the real server even when a sim
  // fixture is loaded — e.g. /api/ui-version must return the actual
  // hash so auto-reload triggers on CSS/JS edits during dev preview.
  // Without this bypass the synth responder returns `{_sim, _path}` and
  // `j.v` is undefined, which is what the "ui undefined" footer stamp
  // was reflecting (2026-04-24).
  const _SYNTH_BYPASS = [
    "/api/sim",          // fixture loader — keep hitting real server
    "/api/ui-version",   // auto-reload hash
  ];
  window.fetch = (input, init) => {
    const url = (typeof input === "string") ? input : (input && input.url) || "";
    for (const prefix of _SYNTH_BYPASS) {
      if (url.startsWith(prefix)) return _origFetch(input, init);
    }
    // Pass static assets (CSS/JS/images) through unchanged.
    if (!url.startsWith("/api/")) return _origFetch(input, init);
    // Anything under /api/ goes to the synth responder.
    return Promise.resolve(_synthResponse(url));
  };

  // ---- WebSocket patch ----------------------------------------------
  //
  // The dashboard connects to ws://<host>:8890 and expects health/state
  // envelopes. Replace the constructor with a fake that fires those
  // envelopes synchronously after open.
  class FakeSocket {
    constructor(_url) {
      this.readyState = 0;
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      this.onerror = null;
      this._firedInitial = false;
      // Hold open until FIXTURE is loaded — otherwise _replay() no-ops
      // and the dashboard sees no health/state envelopes (mode stays
      // at default "client", panels stay empty).
      if (FIXTURE) {
        setTimeout(() => this._open(), 0);
      } else {
        _pendingSockets.push(this);
      }
    }
    _open() {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      if (this.onopen) this.onopen({});
      this._replay();
      // Keep panels "fresh" — the real WS sends state updates as the
      // coach emits them; in sim we re-emit the fixture so the staleness
      // sweep doesn't fade the cards after 4-12s.
      this._tickTimer = setInterval(() => this._tick(), 3000);
    }
    _replay() {
      if (!FIXTURE) return;
      const queue = [];
      if (FIXTURE.health) queue.push(FIXTURE.health);
      if (FIXTURE.state)  queue.push(FIXTURE.state);
      queue.push({ type: "heartbeat", t: Date.now() / 1000 });
      for (const env of queue) {
        if (this.onmessage) {
          this.onmessage({ data: JSON.stringify(env) });
        }
      }
      this._firedInitial = true;
    }
    _tick() {
      if (this.readyState !== 1 || !FIXTURE) return;
      if (FIXTURE.state && this.onmessage) {
        this.onmessage({ data: JSON.stringify(FIXTURE.state) });
      }
      if (this.onmessage) {
        this.onmessage({ data: JSON.stringify({ type: "heartbeat", t: Date.now() / 1000 }) });
      }
    }
    send() { /* sink */ }
    close() {
      this.readyState = 3;
      if (this._tickTimer) { clearInterval(this._tickTimer); this._tickTimer = null; }
      if (this.onclose) this.onclose({});
    }
  }
  // Preserve constants the dashboard might read.
  FakeSocket.CONNECTING = 0; FakeSocket.OPEN = 1;
  FakeSocket.CLOSING    = 2; FakeSocket.CLOSED = 3;
  window.WebSocket = FakeSocket;

  // ---- Banner + dropdown wiring -------------------------------------
  async function _loadManifestAndBanner() {
    const banner = document.getElementById("sim-banner");
    const label = document.getElementById("sim-label");
    const select = document.getElementById("sim-select");
    if (!banner || !select) return;
    // ?banner=0 keeps the banner hidden for clean screenshot captures.
    if (/[?&]banner=0/.test(location.search)) return;
    banner.classList.remove("hidden");
    // Footer toggle (2026-04-25) — only shown in sim mode. Persists the
    // user's banner-collapse choice in localStorage so refreshes don't
    // re-pop the banner if they wanted it hidden for a clean snapshot.
    const toggle = document.getElementById("dev-banner-toggle");
    if (toggle) {
      toggle.classList.remove("hidden");
      const saved = localStorage.getItem("rc-dev-banner");
      const initial = saved === "off" ? "off" : "on";
      document.body.dataset.devBanner = initial;
      toggle.addEventListener("click", () => {
        const cur = document.body.dataset.devBanner === "off" ? "off" : "on";
        const next = cur === "off" ? "on" : "off";
        document.body.dataset.devBanner = next;
        try { localStorage.setItem("rc-dev-banner", next); } catch (_) {}
      });
    }
    // Fetch manifest → populate dropdown.
    let manifest = null;
    try {
      const resp = await _origFetch("/api/sim/_manifest");
      if (resp.ok) manifest = await resp.json();
    } catch { /* ignore */ }
    const fixtures = (manifest && manifest.fixtures) || [];
    select.innerHTML = "";
    for (const f of fixtures) {
      const opt = document.createElement("option");
      opt.value = f.name;
      opt.textContent = `${f.label || f.name}  (${f.mode || "?"})`;
      if (f.name === simName) opt.selected = true;
      select.appendChild(opt);
    }
    // If current fixture isn't in manifest, still offer it.
    if (![...select.options].some(o => o.value === simName)) {
      const opt = document.createElement("option");
      opt.value = simName;
      opt.textContent = `${simName}  (custom)`;
      opt.selected = true;
      select.appendChild(opt);
    }
    select.addEventListener("change", () => {
      const next = select.value;
      const url = new URL(window.location.href);
      url.searchParams.set("sim", next);
      window.location.href = url.toString();
    });
    // 1-9 keyboard shortcut — jumps to the Nth fixture in the manifest.
    // Useful during dev iteration. Skipped when focus is in an input.
    window.addEventListener("keydown", (e) => {
      const tgt = e.target;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (/^[1-9]$/.test(e.key)) {
        const idx = parseInt(e.key, 10) - 1;
        const opt = select.options[idx];
        if (opt) {
          const url = new URL(window.location.href);
          url.searchParams.set("sim", opt.value);
          window.location.href = url.toString();
        }
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        // Cycle through fixtures with Left/Right arrows.
        let idx = -1;
        for (let i = 0; i < select.options.length; i++) {
          if (select.options[i].value === simName) { idx = i; break; }
        }
        if (idx < 0) return;
        const delta = e.key === "ArrowLeft" ? -1 : 1;
        const next = select.options[(idx + delta + select.options.length) % select.options.length];
        if (next) {
          const url = new URL(window.location.href);
          url.searchParams.set("sim", next.value);
          window.location.href = url.toString();
        }
      }
    });
    // Label populated once the fixture itself loads.
    const meta = FIXTURE && FIXTURE.meta;
    if (meta && label) {
      label.textContent = `${meta.label || meta.name}`;
    } else if (label) {
      label.textContent = simName;
    }
    // Tint the DEV PREVIEW banner by mode — quick glance cue.
    if (meta && meta.mode) {
      banner.dataset.mode = meta.mode;
    }
  }

  function _markMissingPanels() {
    // A panel is "missing" if the fixture lacks the section that drives
    // it AND our default would have rendered nothing useful.
    if (!FIXTURE) return;
    const state = FIXTURE.state && FIXTURE.state.payload || {};
    const mappings = [
      // [panelId, predicateOnStatePayload]
      ["right-now",   p => p.action || p.immediate || p.risk],
      ["next",        p => p.next || p.objective || p.positioning],
      ["item-build",  p => p.items_display || p.item_build || p.augments],
      ["minimap",     p => p.dragon_state || p.baron_state || p.herald_state || p.my_tower_hp != null],
      ["adaptation",  _ => !!(FIXTURE.adaptation && FIXTURE.adaptation.present)],
    ];
    for (const [panelId, pred] of mappings) {
      const el = document.getElementById(panelId);
      if (!el) continue;
      if (!pred(state)) el.classList.add("sim-missing");
    }
  }

  async function _bootstrap() {
    try {
      const r = await _origFetch(`/api/sim/${encodeURIComponent(simName)}`);
      if (r.ok) {
        FIXTURE = await r.json();
      } else {
        FIXTURE = { meta: { name: simName, label: `${simName} (not found)`, mode: "client" } };
      }
    } catch (e) {
      FIXTURE = { meta: { name: simName, label: `${simName} (load error)`, mode: "client" } };
    }
    // Flush any FakeSockets that were constructed before the fixture
    // finished loading. Each one opens on its next tick and replays
    // the health/state envelopes to the dashboard.
    while (_pendingSockets.length) {
      const sock = _pendingSockets.shift();
      setTimeout(() => sock._open(), 0);
    }
    await _loadManifestAndBanner();
    _markMissingPanels();
  }

  // Run synchronously so patches are in place before dashboard.js.
  // Banner + fixture load are async but dashboard.js doesn't hard-depend
  // on them being ready at import time.
  _bootstrap();
})();
