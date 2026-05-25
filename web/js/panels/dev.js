// Dev panel - settings, diagnostics, dev/sim fixture viewer, replay scrubber.
import { el, safe, fmtList, _to12, logLine } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _resolveChampId } from '../lib/items_index.js';
// s220 PGR S5: Match-V5 timeline event ribbon for the Replay view.
// Sidecar architecture per docs/adr/ADR-009-replay-events-cleanroom.md.
import { loadReplayEvents, wireReplayEventsOnce } from './replay_events.js';

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
  // UI scale v2 (2026-05-23, docs/UI_SCALE_SPEC_V2.md): the page-zoom
  // slider was removed in favor of a per-element 25% scale across the
  // token layer. Mock-data toggle replaces it - dev affordance for
  // panel layout work, default OFF.
  cb("set-ui-mock", "rc-ui-mock", (v) => { document.body.dataset.uiMock = v ? "1" : ""; });
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

  // Live metrics status (read-only - env var)
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
  // (Kai'Sa → KaiSa) which never matched the lower-cased file (Kaisa.png).
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
}

export {
  _settingsRefresh,
  _diagFetchAndRender, _diagWireOnce,
  _replayViewWireOnce, _replayViewRefresh, _replayLoadMatch,
};
