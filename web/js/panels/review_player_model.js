// web/js/panels/review_player_model.js
//
// RM-641 (directive X-41, ADR-016): pure interaction model for the S5 Replay
// video lane. Behaviour observed in external reference E and re-implemented
// clean-room; no code or constants were copied. Every number below is our own
// and says where it came from. No DOM, no fetch, no clock: the thin render in
// review_player.js owns all of that. Tests: review_player_model.test.mjs.
//
// Sidecar keys consumed (written by core/obs_recorder.py _write_sidecar,
// RM-637): game_time_offset_s, bookmarks[] {name, game_time, video_time,
// own_death}. Convention from core/vod_alignment.py:
// video_time = game_time + offset, clamped to >= 0.

// Our own: equal to the 24 px marker button width (WCAG 2.5.8 minimum
// target, web/css/panels/review_player.css). Cluster origins are then more
// than one button apart, so two rendered markers never overlap; markers
// closer than that share one cluster.
export const CLUSTER_RADIUS_PX = 24;

// Directive X-41 behaviour: open at the aligned game start minus 2 s. The
// file is never trimmed (trimming is a recorded non-goal, ADR-016 / X-41).
export const OPEN_LEAD_S = 2;

// Our own: a seek lands a fraction past its target, so "previous" must skip a
// marker the playhead is sitting on. A quarter second is well below the
// spacing of two distinct Live Client events on the same lane pixel.
const NAV_EPS_S = 0.25;

// Our own defaults for the PGR cost lane: the five biggest drops of at least
// 2 percentage points of win probability (smaller swings are model noise on
// a 13-feature estimator, core/post_game_score.py).
const COST_LIMIT = 5;
const COST_MIN_DROP = 0.02;

// Icon priority, first match wins. Ordered by what a reviewer jumps to first:
// their own death, then an epic objective, then a takedown, then structures.
export const ICON_PRIORITY = Object.freeze([
  { icon: "death", test: (m) => m.own_death === true },
  { icon: "objective", test: (m) => /^(BaronKill|DragonKill|HeraldKill|HordeKill|AtakhanKill)$/.test(m.name || "") },
  { icon: "kill", test: (m) => /^(ChampionKill|Multikill|Ace|FirstBlood)$/.test(m.name || "") },
  { icon: "structure", test: (m) => /^(TurretKilled|InhibKilled|FirstBrick)$/.test(m.name || "") },
  { icon: "event", test: () => true },
]);

function _num(v) {
  if (v === null || v === undefined || typeof v === "boolean" || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function markerX(t, durationS, widthPx) {
  const d = _num(durationS);
  const w = _num(widthPx);
  const tt = _num(t);
  if (!d || d <= 0 || !w || w <= 0 || tt === null) return 0;
  return Math.min(w, Math.max(0, (tt / d) * w));
}

export function pickIcon(members) {
  const list = Array.isArray(members) ? members : [];
  for (const row of ICON_PRIORITY) {
    if (list.some((m) => m && row.test(m))) return row.icon;
  }
  return "event";
}

// Origin-anchored clustering: a cluster's ORIGIN is its first (earliest)
// marker, and a later marker joins only while it is within radiusPx of that
// origin. Measuring from the last member instead would let a dense run of
// evenly spaced markers chain into one cluster of unbounded width.
export function clusterMarkers(markers, durationS, widthPx, radiusPx = CLUSTER_RADIUS_PX) {
  const pts = (Array.isArray(markers) ? markers : [])
    .filter((m) => m && _num(m.t) !== null)
    .map((m) => ({ m, x: markerX(m.t, durationS, widthPx) }))
    .sort((a, b) => a.m.t - b.m.t);
  const out = [];
  let cur = null;
  for (const p of pts) {
    if (cur && p.x - cur.x <= radiusPx) {
      cur.members.push(p.m);
      continue;
    }
    cur = { x: p.x, t: p.m.t, members: [p.m] };
    out.push(cur);
  }
  for (const c of out) c.icon = pickIcon(c.members);
  return out;
}

export function videoTimeFor(gameTime, offset) {
  const g = _num(gameTime);
  if (g === null) return null;
  return Math.max(0, g + (_num(offset) ?? 0));
}

export function markersFromSidecar(sidecar) {
  const bms = sidecar && Array.isArray(sidecar.bookmarks) ? sidecar.bookmarks : [];
  const off = sidecar ? _num(sidecar.game_time_offset_s) : null;
  const out = [];
  for (const b of bms) {
    if (!b || typeof b !== "object") continue;
    let t = _num(b.video_time);
    if (t === null) t = videoTimeFor(b.game_time, off);
    if (t === null) continue;
    out.push({ t: Math.max(0, t), name: String(b.name || ""),
               game_time: _num(b.game_time), own_death: b.own_death === true });
  }
  return out.sort((a, b) => a.t - b.t);
}

export function openTimeS(sidecar) {
  const off = sidecar ? _num(sidecar.game_time_offset_s) : null;
  if (off === null) return 0;
  return Math.max(0, off - OPEN_LEAD_S);
}

// Input types that do not take text: a plain key on them is ours.
const _NON_TEXT_INPUTS = new Set(["checkbox", "radio", "range", "button",
  "submit", "reset", "color", "file", "image"]);

// target: {tag, type, editable, marker} - a plain description of
// document.activeElement built by the render layer.
export function isTypingTarget(target) {
  if (!target) return false;
  if (target.editable === true) return true;
  const tag = String(target.tag || "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") return !_NON_TEXT_INPUTS.has(String(target.type || "text").toLowerCase());
  return false;
}

// ev: {key, ctrlKey, altKey, metaKey, shiftKey, target}. Returns an action
// or null (null = not ours, let the browser have it).
export function hotkeyAction(ev) {
  if (!ev) return null;
  const key = ev.key;
  const mod = !!(ev.ctrlKey || ev.altKey || ev.metaKey);
  if (key === "Escape") return { type: "release-focus" };
  const isSpace = key === " " || key === "Spacebar";
  if (isSpace && mod) return { type: "toggle-play" };
  if (mod) return null;
  if (isTypingTarget(ev.target)) return null;
  // Space toggles play and never seeks, even when a marker button has focus
  // (the render layer preventDefaults so the button does not activate).
  if (isSpace) return { type: "toggle-play" };
  if (key === "]") return { type: "next-marker" };
  if (key === "[") return { type: "prev-marker" };
  if (key === "d") return { type: "next-death" };
  if (key === "D") return { type: "prev-death" };
  return null;
}

function _next(times, cur) {
  let best = null;
  for (const t of times) if (t > cur + NAV_EPS_S && (best === null || t < best)) best = t;
  return best;
}

function _prev(times, cur) {
  let best = null;
  for (const t of times) if (t < cur - NAV_EPS_S && (best === null || t > best)) best = t;
  return best;
}

// state: {markers: [t], deaths: [t], current: t}. Returns a seek time or null.
export function seekTarget(action, state) {
  if (!action || !state) return null;
  const cur = _num(state.current) ?? 0;
  const markers = (state.markers || []).map(_num).filter((t) => t !== null);
  const deaths = (state.deaths || []).map(_num).filter((t) => t !== null);
  switch (action.type) {
    case "next-marker": return _next(markers, cur);
    case "prev-marker": return _prev(markers, cur);
    case "next-death": return _next(deaths, cur);
    case "prev-death": return _prev(deaths, cur);
    default: return null;
  }
}

// PGR cost moments from GET /api/post-game-wpa events (wpa is signed for
// team 100, core/post_game_score.py:6). A cost is a drop for trackedTeam.
export function costMoments(events, trackedTeam, opts = {}) {
  const team = _num(trackedTeam);
  if (team !== 100 && team !== 200) return [];
  const limit = _num(opts.limit) ?? COST_LIMIT;
  const minDrop = _num(opts.minDrop) ?? COST_MIN_DROP;
  const sign = team === 100 ? 1 : -1;
  const rows = [];
  for (const e of Array.isArray(events) ? events : []) {
    if (!e) continue;
    const w = _num(e.wpa);
    const gt = _num(e.game_time);
    if (w === null || gt === null) continue;
    const signed = sign * w;
    if (signed <= -minDrop) rows.push({ game_time: gt, cost: -signed, type: String(e.type || "") });
  }
  rows.sort((a, b) => b.cost - a.cost);
  return rows.slice(0, Math.max(0, limit)).sort((a, b) => a.game_time - b.game_time);
}
