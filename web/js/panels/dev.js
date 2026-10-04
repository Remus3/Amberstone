// Dev panel - settings, dev/sim fixture viewer, replay scrubber.
import { el, safe, fmtList, _to12, logLine } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _resolveChampId } from '../lib/items_index.js';
import { applyTheme, saveTheme, readStoredTheme, queryTheme, DEFAULT_THEME } from '../lib/theme.js';
// s220 PGR S5: Match-V5 timeline event ribbon for the Replay view.
// Sidecar architecture per docs/adr/ADR-009-replay-events-cleanroom.md.
import { loadReplayEvents, wireReplayEventsOnce, setReplaySeekHandler } from './replay_events.js';
// RM-612 (X-12): pure minimap logic (death windows, last-known + age halo).
import { buildModel, stateAt, worldToCanvas, mapArtUrls, monogram, MAP_WORLD } from './replay_minimap.js';

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
      _replayMapAttach(d);
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
function _replayRenderSnapshot(idx, mapTms) {
  const d = _REPLAY.match;
  if (!d || !d.snapshots || !d.snapshots.length) return;
  const snap = d.snapshots[Math.max(0, Math.min(idx, d.snapshots.length - 1))];
  const clock = document.getElementById("replay-clock");
  if (clock) clock.textContent = `t = ${snap.minute.toFixed(1)}min`;
  // RM-612: the slider puts the map on the frame time; a timeline-event seek
  // passes the event's exact clock so the map shows that moment (with halos
  // for sample age) while the grid shows the nearest frame.
  _replayMapSetTime(mapTms != null ? mapTms : snap.timestamp_ms);
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
  _replayRenderSnapshot(bestIdx, (Number(clockS) || 0) * 1000);
}

// -- RM-612 (X-12, external reference I): past-match minimap -------------
// Canvas-only layer on the scrubber. All position / death-window / halo logic
// is in replay_minimap.js (node-tested); this section only draws. Redraws are
// coalesced to one animation frame and never touch DOM structure, so a
// focused slider or checkbox is never repainted.
const _REPLAY_MAP = {
  model: null, t: 0, allyTeam: 100,
  art: null, artKind: null, icons: new Map(), raf: 0,
};
// Resolve a CSS custom property for canvas use. Every name passed here is
// pinned to an existing definition by tests/test_replay_minimap_crosscheck.py
// (an undefined var would resolve to "" and fail silently).
function _replayMapToken(name) {
  try {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  } catch (_) {
    return "";
  }
}
function _replayMapAttach(d) {
  const fig = document.getElementById("replay-map-figure");
  const model = buildModel(d);
  _REPLAY_MAP.model = model;
  if (!fig) return;
  // Event modes (queue 2400) and matches with no stored positions: no map.
  if (model.hidden) { fig.hidden = true; return; }
  fig.hidden = false;
  const tracked = (d.participants || []).find(p =>
    p.champion_id === (d.tracked && d.tracked.champion_id));
  _REPLAY_MAP.allyTeam = tracked ? tracked.team_id : 100;
  _replayMapLoadArt(model.kind);
}
function _replayMapLoadArt(kind) {
  if (_REPLAY_MAP.artKind === kind) return;
  _REPLAY_MAP.artKind = kind;
  _REPLAY_MAP.art = null;
  // Map art RC already uses: the local DDragon map image, then the tracked SVG.
  const urls = mapArtUrls(kind, ITEMS && ITEMS.version);
  const tryAt = (i) => {
    if (i >= urls.length) return;
    const img = new Image();
    img.onload = () => {
      if (_REPLAY_MAP.artKind !== kind) return;
      _REPLAY_MAP.art = img;
      _replayMapSchedule();
    };
    img.onerror = () => tryAt(i + 1);
    img.src = urls[i];
  };
  tryAt(0);
}
// Cached DDragon champion icon (same /icons/champions/ URL the grid uses).
// Returns null until loaded or on a miss, so the caller draws the monogram.
function _replayMapIcon(name) {
  let rec = _REPLAY_MAP.icons.get(name);
  if (!rec) {
    rec = { img: new Image(), ok: false };
    rec.img.onload = () => { rec.ok = true; _replayMapSchedule(); };
    rec.img.onerror = () => { rec.ok = false; };
    rec.img.src = _replayChampIconUrl(name);
    _REPLAY_MAP.icons.set(name, rec);
  }
  return rec.ok ? rec.img : null;
}
function _replayMapSetTime(tMs) {
  _REPLAY_MAP.t = Math.max(0, Number(tMs) || 0);
  _replayMapSchedule();
}
function _replayMapSchedule() {
  if (_REPLAY_MAP.raf) return;
  const run = () => { _REPLAY_MAP.raf = 0; _replayMapDraw(); };
  _REPLAY_MAP.raf = (typeof requestAnimationFrame === "function")
    ? requestAnimationFrame(run) : setTimeout(run, 16);
}
function _replayMapDraw() {
  const m = _REPLAY_MAP.model, d = _REPLAY.match;
  const canvas = document.getElementById("replay-map-canvas");
  if (!m || m.hidden || !d || !canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const W = canvas.width, H = canvas.height, t = _REPLAY_MAP.t;
  const fg = _replayMapToken("--text");
  const allyColor = _replayMapToken("--signal-info") || fg;
  const enemyColor = _replayMapToken("--signal-bad") || fg;
  const badgeBg = _replayMapToken("--surface");
  ctx.clearRect(0, 0, W, H);
  if (_REPLAY_MAP.art) {
    ctx.save();
    ctx.filter = "saturate(0.55) brightness(0.7)";   // same treatment as grid.css map backdrop
    ctx.drawImage(_REPLAY_MAP.art, 0, 0, W, H);
    ctx.restore();
  }
  const unitsToPx = W / (MAP_WORLD[m.kind] || MAP_WORLD.sr);
  const R = Math.round(W / 30);
  const alive = [], dead = [], revived = [];
  for (const p of d.participants || []) {
    const s = stateAt(m, p.participant_id, t);
    const color = p.team_id === _REPLAY_MAP.allyTeam ? allyColor : enemyColor;
    if (s.dead) {
      if (s.deathPos) dead.push({ s, color });
    } else if (s.visible) {
      alive.push({ p, s, color });
      if (s.revive) revived.push(p.champion_name || "?");
    }
  }
  // Death spots: a small cross where the victim fell; the badge itself is
  // hidden for the whole death window.
  for (const { s, color } of dead) {
    const [x, y] = worldToCanvas(s.deathPos, m.kind, W, H);
    const k = R * 0.5;
    ctx.save();
    ctx.globalAlpha = 0.7;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x - k, y - k); ctx.lineTo(x + k, y + k);
    ctx.moveTo(x + k, y - k); ctx.lineTo(x - k, y + k);
    ctx.stroke();
    ctx.restore();
  }
  // Age halos under every badge: radius = how far the champion could be from
  // its last sample. Never interpolated, never carried across a death.
  for (const { s, color } of alive) {
    if (!(s.haloUnits > 0)) continue;
    const [x, y] = worldToCanvas(s.pos, m.kind, W, H);
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, Math.max(R, s.haloUnits * unitsToPx), 0, Math.PI * 2);
    ctx.globalAlpha = 0.10;
    ctx.fillStyle = color;
    ctx.fill();
    ctx.globalAlpha = 0.45;
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = color;
    ctx.stroke();
    ctx.restore();
  }
  for (const { p, s, color } of alive) {
    const [x, y] = worldToCanvas(s.pos, m.kind, W, H);
    const icon = _replayMapIcon(p.champion_name);
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, R, 0, Math.PI * 2);
    ctx.closePath();
    if (badgeBg) { ctx.fillStyle = badgeBg; ctx.fill(); }
    if (icon) {
      ctx.save();
      ctx.clip();
      ctx.drawImage(icon, x - R, y - R, 2 * R, 2 * R);
      ctx.restore();
    } else {
      // operator-exception: canvas monogram (NOT DOM text, no --fs-* token
      // possible). 17px on the 480px backing store renders ~10.6px at the
      // 300px CSS size - the same scale as map_state.js's 11px canvas glyphs -
      // and two letters fit inside the 32px-backing badge circle.
      ctx.fillStyle = fg;
      ctx.font = "bold 17px Lato, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(monogram(p.champion_name), x, y + 1);
    }
    ctx.lineWidth = 3;
    ctx.strokeStyle = color;
    if (s.revive) ctx.setLineDash([4, 3]);   // revive suspected: dashed ring
    ctx.stroke();
    ctx.restore();
  }
  const clockEl = document.getElementById("replay-map-clock");
  const clockTxt = "Map at " + _replayDurStr(Math.floor(t / 1000));
  if (clockEl && clockEl.textContent !== clockTxt) clockEl.textContent = clockTxt;
  const flagsEl = document.getElementById("replay-map-flags");
  const flagsTxt = revived.length
    ? "Revive suspected (a sample contradicts the death timer): " + revived.join(", ")
    : "";
  if (flagsEl && flagsEl.textContent !== flagsTxt) flagsEl.textContent = flagsTxt;
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
  _settingsRefresh, renderSpendGates,
  _replayViewWireOnce, _replayViewRefresh, _replayLoadMatch,
};
