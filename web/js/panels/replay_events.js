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

const _LS_INCLUDE_KEY = "rc-replay-events-include";

// Mutable per-mount state. Mirrors the per-view pattern of the
// existing Replay scrubber so a route change tears it down cleanly.
const _RE = {
  matchId: null,
  include: new Set(),  // subset of {items, skills, wards}
  events:  [],
};

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

function _actorText(e) {
  // The events table carries participant_ids (1..10); a richer join
  // against participants.summoner_name + champion lives in
  // /api/replay/match/<id> response so we keep this side lean. The
  // ribbon shows P<id> chips by default; the operator can hover the
  // Replay grid + ribbon at the same time to correlate.
  const a = e && e.actor;
  if (!a) return "";
  return `P${a}`;
}

function _victimText(e) {
  const v = e && e.victim;
  if (!v) return "";
  return `vs P${v}`;
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

function _renderEvents() {
  const list  = document.getElementById("replay-events-list");
  const empty = document.getElementById("replay-events-empty");
  const count = document.getElementById("replay-events-count");
  if (!list || !empty || !count) return;
  const events = _RE.events || [];
  count.textContent = String(events.length);
  if (!events.length) {
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  const rows = events.map((e) => {
    const clock   = _fmtMmSs(e.clock_s);
    const label   = _typeLabel(e.type, e.subtype);
    const kind    = _kindFor(e.type);
    const team    = (e.team === 100 || e.team === 200) ? e.team : 0;
    const actor   = _actorText(e);
    const victim  = _victimText(e);
    const sub     = e.subtype ? ` ${_escHtml(e.subtype)}` : "";
    const lane    = e.lane ? ` ${_escHtml(e.lane)}` : "";
    return `<li class="replay-events-row" data-kind="${kind}" data-team="${team}">
      <span class="replay-events-clock">${_escHtml(clock)}</span>
      <span class="replay-events-label">${_escHtml(label)}${sub}${lane}</span>
      <span class="replay-events-actor">${_escHtml(actor)}</span>
      <span class="replay-events-victim">${_escHtml(victim)}</span>
    </li>`;
  }).join("");
  list.innerHTML = rows;
}

/**
 * Fetch + render the events ribbon for ``matchId``. Idempotent:
 * re-calling with the same id pulls from the route's TTL cache.
 * Passing a falsy id hides the section.
 */
export function loadReplayEvents(matchId) {
  const section = document.getElementById("replay-events-section");
  if (!section) return;
  if (!matchId) {
    section.hidden = true;
    _RE.matchId = null;
    _RE.events = [];
    _renderEvents();
    return;
  }
  _RE.matchId = matchId;
  section.hidden = false;
  const includeParam = [..._RE.include].sort().join(",");
  const url = `/api/replay/events?match_id=${encodeURIComponent(matchId)}` +
              (includeParam ? `&include=${encodeURIComponent(includeParam)}` : "");
  fetch(url, { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((d) => {
      if (!d || !d.ok) {
        _RE.events = [];
      } else {
        _RE.events = d.events || [];
      }
      _renderEvents();
    })
    .catch((err) => {
      try { console.warn("[replay-events] fetch failed:", err); } catch (_) {}
      _RE.events = [];
      _renderEvents();
    });
}

let _wired = false;

/**
 * One-time DOM wiring for the filter checkboxes. Idempotent - safe to
 * call from _replayViewWireOnce on every view activation.
 */
export function wireReplayEventsOnce() {
  if (_wired) return;
  _wired = true;
  _RE.include = _loadInclude();
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
