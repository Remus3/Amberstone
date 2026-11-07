/* s220 PGR S5: Match-V5 timeline event ribbon for the Replay view.
 *
 * Renders a chronological list of discrete timeline events
 * (CHAMPION_KILL / BUILDING_KILL / ELITE_MONSTER_KILL /
 * TURRET_PLATE_DESTROYED by default; ITEM_PURCHASED / SKILL_LEVEL_UP /
 * LEVEL_UP / WARD_PLACED / WARD_KILL when the operator toggles the
 * include filters).
 *
 * Architecture / cleanroom boundary: see
 * docs/adr/ADR-009-replay-events-cleanroom.md - short version:
 * league_record (GPLv3) is the methodology reference for pairing
 * this event sidecar with a future OBS video overlay; the GPL
 * license forbids vendoring its source. The sidecar shape is also
 * Match-V5 timeline's natural shape - no implementation borrowed.
 * do NOT vendor league_record.
 *
 * Source: GET /api/replay/events?match_id=<id>[&include=items,skills,wards]
 *   (dashboard/routes_replay_events.py)
 *
 * Mounted under #replay-events-section in the Replay view; hidden
 * until _replayLoadMatch resolves to a valid match id.
 */

import { CHAMPS, DDRAGON_FALLBACK_VERSION } from '../lib/items_index.js';

const _LS_INCLUDE_KEY = "rc-replay-events-include";

// Resolve DDragon champion portrait URL. Mirrors the
// alphanumeric-strip normalisation of web/js/lib/items_index.js
// (a deleted panel carried the original) - load-bearing for punctuation in display
// names (Kai'Sa -> KaiSa, Cho'Gath -> Chogath). CHAMPS.version is
// async-hydrated from /data/champions_index.json; default 16.10.1.
function _portraitUrl(champName) {
  const ver = (CHAMPS && CHAMPS.version) || DDRAGON_FALLBACK_VERSION;
  const clean = String(champName || "").replace(/[^a-zA-Z0-9]/g, "");
  if (!clean) return "";
  return `/data/ddragon/${ver}/img/champion/${clean}.png`;
}

// Mutable per-mount state. Mirrors the per-view pattern of the
// existing Replay scrubber so a route change tears it down cleanly.
const _RE = {
  matchId: null,
  // S144-U-183: bumped by every loadReplayEvents call; a reply applies only
  // while it is still the newest request (a late reply for an earlier pick
  // or filter used to replace the ribbon of the later one).
  seq: 0,
  include: new Set(),  // subset of {items, skills, wards}
  events:  [],
  // RM-638: the player's in-game "mark this moment" presses for this match
  // (route field you_flagged; core/moment_marks.py). Rendered as rows in
  // the same ribbon, interleaved by clock, so a click seeks like any event.
  flags:   [],
  // S144-U-186: the ribbon note while a pick that did not load is showing
  // (null = the markup's own "No timeline events for this match.").
  // S144-U-187: NOTE_LOADING while a new pick's events are pending.
  note:    null,
};

const FLAG_LABEL = "you flagged";
const NOTE_PLAIN  = "No timeline events for this match.";
const NOTE_FAILED = "No timeline events - the match did not load.";
const NOTE_LOADING = "Loading timeline events...";

// UI scale v2.1 page #3 audit ritual step 5 state-coverage mock fixture
// (2026-05-23). When body.dataset.uiMock === "1" the events fetch
// short-circuits to /data/ui_mock/replay.json. Cache is independent
// from dev.js (small redundant fetch on activation) so this module
// remains decoupled. Filter checkboxes (items/skills/wards) are not
// applied to mock - the fixture events stand as authored.
let _replayEventsMockPromise = null;
function _replayEventsMockLoad() {
  if (_replayEventsMockPromise) return _replayEventsMockPromise;
  _replayEventsMockPromise = fetch("/data/ui_mock/replay.json", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);
  return _replayEventsMockPromise;
}
function _replayEventsIsMock() {
  return document.body && document.body.dataset.uiMock === "1";
}

function _escHtml(s) {
  const div = document.createElement("div");
  div.textContent = String(s == null ? "" : s);
  return div.innerHTML;
}

function _fmtMmSs(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(n / 60);
  const s = n % 60;
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

function _typeLabel(t, subtype) {
  switch (t) {
    case "CHAMPION_KILL":     return "Kill";
    case "BUILDING_KILL": {
      if (!subtype) return "Building";
      const s = String(subtype).toUpperCase();
      if (s.includes("NEXUS"))  return "Nexus";
      if (s.includes("INHIB"))  return "Inhibitor";
      if (s.includes("BASE"))   return "Base";
      if (s.includes("INNER"))  return "Inner";
      if (s.includes("OUTER"))  return "Outer";
      if (s.includes("TURRET")) return "Tower";
      return s;
    }
    case "TURRET_PLATE_DESTROYED": return "Plate";
    case "ELITE_MONSTER_KILL": {
      if (!subtype) return "Objective";
      const s = String(subtype).toUpperCase();
      if (s.includes("BARON"))  return "Baron";
      if (s.includes("HERALD")) return "Herald";
      if (s.includes("HORDE"))  return "Grubs";
      if (s.includes("ATAKHAN")) return "Atakhan";
      if (s.includes("DRAGON")) return "Dragon";
      return s;
    }
    case "ITEM_PURCHASED":     return "Bought";
    case "ITEM_SOLD":          return "Sold";
    case "ITEM_DESTROYED":     return "Consumed";
    case "ITEM_UNDO":          return "Undo";
    case "SKILL_LEVEL_UP":     return "Skill";
    case "LEVEL_UP":           return "Level";
    case "WARD_PLACED":        return "Ward";
    case "WARD_KILL":          return "Sweep";
    default: return String(t || "Event");
  }
}

function _kindFor(type) {
  // Drives CSS color theme - 4 buckets keeps the ribbon visually quiet
  // when the [+items] / [+skills] / [+wards] filters expand the set.
  switch (type) {
    case "CHAMPION_KILL":           return "kill";
    case "BUILDING_KILL":
    case "TURRET_PLATE_DESTROYED":  return "structure";
    case "ELITE_MONSTER_KILL":      return "objective";
    case "WARD_PLACED":
    case "WARD_KILL":               return "ward";
    case "ITEM_PURCHASED":
    case "ITEM_SOLD":
    case "ITEM_DESTROYED":
    case "ITEM_UNDO":               return "item";
    case "SKILL_LEVEL_UP":
    case "LEVEL_UP":                return "skill";
    default:                        return "other";
  }
}

// Build a chip's portrait + text HTML. Three-tier fallback chain:
// champion_name (portrait + champ-text) -> summoner_name only ->
// P<id> only -> empty. Portrait <img> uses onerror hide so a 404 on
// an unmapped champion (event-mode esoterica) collapses cleanly.
function _chipHtml(pid, champ, name, prefix) {
  if (!pid) return { html: "", title: "" };
  const safePrefix = prefix ? `${prefix} ` : "";
  if (champ) {
    const src = _portraitUrl(champ);
    const img = src
      ? `<img class="replay-events-portrait" src="${_escHtml(src)}" alt="" onerror="this.style.display='none'">`
      : "";
    const html = `${img}<span class="replay-events-chip-text">${_escHtml(safePrefix + champ)}</span>`;
    const title = name ? `${name} (P${pid})` : `P${pid}`;
    return { html, title };
  }
  if (name) {
    return {
      html:  `<span class="replay-events-chip-text">${_escHtml(safePrefix + name)}</span>`,
      title: `P${pid}`,
    };
  }
  return {
    html:  `<span class="replay-events-chip-text">${_escHtml(safePrefix + "P" + pid)}</span>`,
    title: "",
  };
}

function _actorChip(e) {
  if (!e) return { html: "", title: "" };
  return _chipHtml(e.actor, e.actor_champion, e.actor_name, "");
}

function _victimChip(e) {
  if (!e) return { html: "", title: "" };
  return _chipHtml(e.victim, e.victim_champion, e.victim_name, "vs");
}

function _loadInclude() {
  try {
    const raw = localStorage.getItem(_LS_INCLUDE_KEY) || "";
    const set = new Set();
    raw.split(",").forEach((p) => {
      const t = p.trim().toLowerCase();
      if (t === "items" || t === "skills" || t === "wards") set.add(t);
    });
    return set;
  } catch (_) {
    return new Set();
  }
}

function _saveInclude(set) {
  try {
    localStorage.setItem(_LS_INCLUDE_KEY, [...set].sort().join(","));
  } catch (_) {}
}

// RM-638: one "you flagged" pin row. Same row contract as an event row
// (li > button.replay-events-row, data-clock seek) so the delegated click /
// keydown seek in wireReplayEventsOnce works on it unchanged.
function _flagRowHtml(pin) {
  const clockS = Math.max(0, Math.floor(Number(pin && pin.game_time_s) || 0));
  const clock  = _fmtMmSs(clockS);
  return `<li class="replay-events-item"><button type="button"
      class="replay-events-row" data-kind="flag" data-team="0"
      data-clock="${clockS}"
      title="You flagged this moment in game - jump the scrubber to ${_escHtml(clock)}">
      <span class="replay-events-clock">${_escHtml(clock)}</span>
      <span class="replay-events-label">${_escHtml(FLAG_LABEL)}</span>
      <span class="replay-events-actor"></span>
      <span class="replay-events-victim"></span>
    </button></li>`;
}

// Merge event rows and flag rows by clock. A flag sorts AFTER an event at
// the same second (stable), so the ribbon reads "what happened, then your
// flag". Pure string build - no DOM reads.
function _rowsHtml(events, flags) {
  const items = [];
  (events || []).forEach((e, i) => {
    items.push({ c: Number(e && e.clock_s) || 0, o: 0, i, html: _eventRowHtml(e) });
  });
  (flags || []).forEach((p, i) => {
    if (!p || !isFinite(Number(p.game_time_s))) return;
    items.push({ c: Math.floor(Number(p.game_time_s)), o: 1, i, html: _flagRowHtml(p) });
  });
  items.sort((a, b) => (a.c - b.c) || (a.o - b.o) || (a.i - b.i));
  return items.map((x) => x.html).join("");
}

function _renderEvents() {
  const list  = document.getElementById("replay-events-list");
  const empty = document.getElementById("replay-events-empty");
  const count = document.getElementById("replay-events-count");
  if (!list || !empty || !count) return;
  const events = _RE.events || [];
  const flags  = _RE.flags || [];
  const loading = _RE.note === NOTE_LOADING;
  // S144-U-187: "-" (no data yet) while loading, never a count of 0.
  count.textContent = loading ? "-" : String(events.length);
  empty.textContent = _RE.note || NOTE_PLAIN;
  if (loading) list.setAttribute("aria-busy", "true");
  else {
    list.removeAttribute("aria-busy");
    // Release the height held by loadReplayEvents for the pending pick.
    const section = document.getElementById("replay-events-section");
    if (section) section.style.minHeight = "";
  }
  if (!events.length && !flags.length) {
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  // Rebuilt only on a fetch resolve (never on a timer), matching the
  // pre-RM-638 render; the delegated seek listeners survive the rebuild.
  list.innerHTML = _rowsHtml(events, flags);
}

// One timeline-event row (the pre-RM-638 map body; li > button since RM-1066).
function _eventRowHtml(e) {
    const clockS  = Number(e.clock_s) || 0;
    const clock   = _fmtMmSs(e.clock_s);
    const label   = _typeLabel(e.type, e.subtype);
    const kind    = _kindFor(e.type);
    const team    = (e.team === 100 || e.team === 200) ? e.team : 0;
    const actor   = _actorChip(e);
    const victim  = _victimChip(e);
    const sub     = e.subtype ? ` ${_escHtml(e.subtype)}` : "";
    const lane    = e.lane ? ` ${_escHtml(e.lane)}` : "";
    const aTitle  = actor.title  ? ` title="${_escHtml(actor.title)}"`  : "";
    const vTitle  = victim.title ? ` title="${_escHtml(victim.title)}"` : "";
    // Each row is a seek control: clicking it (or Enter/Space when focused)
    // drives the scrubber to this event's timestamp via the delegated
    // listener in wireReplayEventsOnce. data-clock carries the raw seconds.
    // RM-1066: the li stays a listitem and the control is a real button.
    return `<li class="replay-events-item"><button type="button"
      class="replay-events-row" data-kind="${kind}" data-team="${team}"
      data-clock="${clockS}"
      title="Jump the scrubber to ${_escHtml(clock)}">
      <span class="replay-events-clock">${_escHtml(clock)}</span>
      <span class="replay-events-label">${_escHtml(label)}${sub}${lane}</span>
      <span class="replay-events-actor"${aTitle}>${actor.html}</span>
      <span class="replay-events-victim"${vTitle}>${victim.html}</span>
    </button></li>`;
}

/**
 * Fetch + render the events ribbon for ``matchId``. Idempotent:
 * re-calling with the same id pulls from the route's TTL cache.
 * Passing a falsy id hides the section.
 */
export function loadReplayEvents(matchId) {
  const section = document.getElementById("replay-events-section");
  if (!section) return;
  const seq = ++_RE.seq;
  const fresh = () => seq === _RE.seq;
  if (!matchId) {
    _RE.note = null;
    section.hidden = true;
    _RE.matchId = null;
    _RE.events = [];
    _RE.flags = [];
    _renderEvents();
    return;
  }
  // S144-U-187: a pick of a DIFFERENT match drops the previous match's rows
  // at once (they were listed under "loading <id>..." until this reply
  // landed, each a seek into the previous match) and says the events are
  // loading. The section keeps its current height until the reply renders,
  // so nothing under it moves twice. A filter toggle on the same match
  // keeps its rows (they still belong to the match in the scrubber).
  // Guard: tests/snapshot_panels/test_replay_pending_pick_ribbon.py.
  if (matchId !== _RE.matchId) {
    const h = section.hidden ? 0 : section.getBoundingClientRect().height;
    _RE.events = [];
    _RE.flags = [];
    _RE.note = NOTE_LOADING;
    _renderEvents();
    if (h > 0) section.style.minHeight = `${h}px`;
  }
  _RE.matchId = matchId;
  section.hidden = false;
  if (_replayEventsIsMock()) {
    _replayEventsMockLoad()
      .then((m) => {
        if (!fresh()) return;
        _RE.note = null;
        if (!m || !Array.isArray(m.matches)) { _RE.events = []; _RE.flags = []; _renderEvents(); return; }
        const hit = m.matches.find((x) => x.match_id === matchId);
        _RE.events = (hit && Array.isArray(hit.events)) ? hit.events : [];
        _RE.flags = (hit && Array.isArray(hit.you_flagged)) ? hit.you_flagged : [];
        _renderEvents();
      })
      .catch(() => { if (!fresh()) return; _RE.note = null; _RE.events = []; _RE.flags = []; _renderEvents(); });
    return;
  }
  const includeParam = [..._RE.include].sort().join(",");
  const url = `/api/replay/events?match_id=${encodeURIComponent(matchId)}` +
              (includeParam ? `&include=${encodeURIComponent(includeParam)}` : "");
  fetch(url, { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((d) => {
      if (!fresh()) return;
      _RE.note = null;
      if (!d || !d.ok) {
        _RE.events = [];
        _RE.flags = [];
      } else {
        _RE.events = d.events || [];
        _RE.flags = Array.isArray(d.you_flagged) ? d.you_flagged : [];
      }
      _renderEvents();
    })
    .catch((err) => {
      if (!fresh()) return;
      try { console.warn("[replay-events] fetch failed:", err); } catch (_) {}
      _RE.note = null;
      _RE.events = [];
      _RE.flags = [];
      _renderEvents();
    });
}

/**
 * S144-U-186: the pick whose match reply failed (dev.js _replayLoadMatch).
 * The events route can still answer for it, so the ribbon used to list its
 * events - each a "jump the scrubber" button with no match to seek - under
 * the "could not load" meta line. Drops the rows, says why, ignores a late
 * events reply for that pick (seq bump) and leaves a filter toggle nothing
 * to re-fetch. The section stays where it is. The next pick's
 * loadReplayEvents restores the plain note.
 * Guard: tests/snapshot_panels/test_replay_failed_load_ribbon.py.
 */
export function clearReplayEventsFailed() {
  ++_RE.seq;
  _RE.matchId = null;
  _RE.events = [];
  _RE.flags = [];
  _RE.note = NOTE_FAILED;
  _renderEvents();
}

let _wired = false;

// Seek bridge: dev.js (which owns the _REPLAY scrubber state) registers a
// handler here so a timeline-row click can drive the per-frame scrubber
// without a circular import. Decoupled - the ribbon stays renderable even
// if no scrubber is mounted (the click is then a no-op).
let _seekHandler = null;
export function setReplaySeekHandler(fn) {
  _seekHandler = (typeof fn === "function") ? fn : null;
}

function _seekFromRow(target) {
  const row = target && target.closest ? target.closest(".replay-events-row") : null;
  if (!row || !_seekHandler) return;
  const c = Number(row.getAttribute("data-clock"));
  // S144-U-187: the row's match rides along, so the scrubber can refuse a
  // row of a match it does not hold yet.
  if (!isNaN(c)) _seekHandler(c, _RE.matchId);
}

/**
 * One-time DOM wiring for the filter checkboxes + the timeline-row seek
 * (delegated, so it survives every _renderEvents innerHTML rebuild).
 * Idempotent - safe to call from _replayViewWireOnce on every activation.
 */
export function wireReplayEventsOnce() {
  if (_wired) return;
  _wired = true;
  _RE.include = _loadInclude();
  const list = document.getElementById("replay-events-list");
  if (list) {
    list.addEventListener("click", (e) => _seekFromRow(e.target));
    list.addEventListener("keydown", (e) => {
      // RM-1062: modifier+key belongs to the recording player.
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        _seekFromRow(e.target);
      }
    });
  }
  const map = {
    "replay-evt-items":  "items",
    "replay-evt-skills": "skills",
    "replay-evt-wards":  "wards",
  };
  Object.keys(map).forEach((id) => {
    const cb = document.getElementById(id);
    if (!cb) return;
    cb.checked = _RE.include.has(map[id]);
    cb.addEventListener("change", () => {
      if (cb.checked) _RE.include.add(map[id]);
      else _RE.include.delete(map[id]);
      _saveInclude(_RE.include);
      // Re-fetch with the new include set (route caches on the tuple).
      if (_RE.matchId) loadReplayEvents(_RE.matchId);
    });
  });
}

// --- test hooks (RM-638 moment_flags.test.mjs) -------------------------
export const __test = { _rowsHtml, _flagRowHtml, _eventRowHtml, FLAG_LABEL };
