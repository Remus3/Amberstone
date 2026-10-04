// web/js/panels/replay_minimap.js
//
// RM-612 (directive X-12, external reference I): the pure core of the
// past-match minimap layer drawn on the replay scrubber (dev.js). Re-implemented
// from behaviour text only; no third-party code. Every numeric constant below
// is our own and says where it came from.
//
// HONEST UNCERTAINTY, NOT INTERPOLATION. Match-V5 frames are 60 s samples, and
// core/replay_analysis.py (module docstring) records that a 60 s position is a
// sample, not a track. Linear interpolation between two frames was MEASURED
// here (RM-612, see HALO_BY_AGE below for method) at mean 2636 / max 14785
// units of error, so this module never blends positions. A
// champion is drawn at its LAST-KNOWN position with a halo that grows with the
// age of that sample, snaps to the exact kill position at its own kill events,
// and is hidden for the whole of a death window.
//
// Death window = [kill_t, kill_t + deathTimerS(level, kill_t)), a port of
// core.post_game_score.calculate_death_timer (cross-checked against the Python
// function by tests/fixtures/replay_minimap_death_timer.json).
//
// No DOM access in this file: it is imported by dev.js for drawing and by
// replay_minimap.test.mjs under `node --test`.

// --- death timer (port of core/post_game_score.py:76-112) ---------------------
// Base respawn wait by level, index 0 = level 1. Same table as
// core.post_game_score.DEATH_BRW_SECONDS; the cross-check test pins equality.
const DEATH_BRW_SECONDS = Object.freeze([
  10.0, 10.0, 12.0, 12.0, 14.0, 16.0, 20.0, 25.0, 28.0,
  32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5, 50.0, 52.5,
]);

function tifPct(minutes) {
  if (minutes < 15) return 0.0;
  if (minutes < 30) return Math.ceil(2 * (minutes - 15)) * 0.425;
  if (minutes < 45) return 12.75 + Math.ceil(2 * (minutes - 30)) * 0.3;
  if (minutes < 55) return 21.75 + Math.ceil(2 * (minutes - 45)) * 1.45;
  return 50.0;
}

function deathTimerS(level, timeMs) {
  const lvl = Math.max(1, Math.min(Math.trunc(Number(level) || 0), 18));
  const brw = DEATH_BRW_SECONDS[lvl - 1];
  const tif = tifPct(Number(timeMs) / 60000.0) / 100.0;
  return brw + brw * tif;
}

// --- constants (ours) -----------------------------------------------------------
// Halo = the MEAN last-known-position error at that sample age, MEASURED
// 2026-10-04 (RM-612) read-only on data/rewind_history.db, the 300 most recent
// ranked-solo (queue 420) matches. Method: at every CHAMPION_KILL the victim's
// true position is the event's kill position (sub-second); its last frame at or
// before the kill (alive at that frame, no death in between) is the last-known
// sample. Error = distance(frame pos, kill pos), binned by sample age, n = 15583:
//   age  0-10 s mean  788   10-20 s 1811   20-30 s 2748
//       30-40 s     3559   40-50 s 4063   50-60 s 4394   (units; p90 at 50-60 s
//   is 9026, max 17672 - a halo is a typical displacement, not a bound).
// Knots sit at the bin midpoints; linear between; flat after the last bin.
// Why no interpolation either: the same corpus measured LINEAR interpolation
// between the killer's bracketing frames against the kill position at mean 2636
// / median 2094 / max 14785 units (n = 11884; includes the killer's attack-range
// offset) - a confident point with a multi-thousand-unit error.
const HALO_BY_AGE = Object.freeze([
  [0, 0], [5, 788], [15, 1811], [25, 2748], [35, 3559], [45, 4063], [55, 4394],
].map((k) => Object.freeze(k)));
const HALO_MAX_UNITS = HALO_BY_AGE[HALO_BY_AGE.length - 1][1];

// Revive / echo tolerance. MEASURED 2026-10-04 on data/rewind_history.db, the
// 80 most recent ranked-solo matches: of 2885 victim frames that fall inside a
// death window, 2881 sit within 1500 units of the kill position (median 0 -
// Riot keeps a dead champion's frame at its death spot), 31 within 1500 of the
// team fountain (an early respawn: the ported timer is approximate), and 2 are
// near neither (a revive). 1500 separates those classes on that data.
const ECHO_TOL_UNITS = 1500;

// Fountain fallback when a match has no frame 0. MEASURED 2026-10-04: median of
// the frame-0 (spawn) positions per team in data/rewind_history.db, 73 SR
// (queue 420) and 227 ARAM (queue 450) matches.
const FOUNTAIN_FALLBACK = Object.freeze({
  sr:   Object.freeze({ 100: [362, 401],   200: [14321, 14454] }),
  aram: Object.freeze({ 100: [1096, 944],  200: [12020, 11474] }),
});

// World size per map. Same values as the existing projection tables
// (web/js/main.js VT_MAP_SIZE, web/js/panels/active_match.js _AM_MAP_WORLD:
// CLASSIC 14800, ARAM 13800) so the replay map projects like the live one.
const MAP_WORLD = Object.freeze({ sr: 14800, aram: 13800 });

// Map art RC already uses: the local DDragon mirror image (active_match.js
// _AM_MAP_FILE) with the tracked SVG approximations as the fallback.
const MAP_ART = Object.freeze({
  sr:   { ddragon: "map11.png", svg: "/data/icons/sr-minimap.svg" },
  aram: { ddragon: "map12.png", svg: "/data/icons/aram-minimap.svg" },
});

const ARAM_QUEUES = new Set([100, 450, 920]);
// 2400 = ARAM Mayhem event mode: no timeline frames are stored for it
// (measured 2026-10-04: zero timeline_frames rows for queue 2400). Arena
// queues use a different map with no art mapping here.
const NO_MAP_QUEUES = new Set([2400, 1700, 1750]);

function mapKindForQueue(queueId) {
  const q = Number(queueId);
  if (NO_MAP_QUEUES.has(q)) return null;
  return ARAM_QUEUES.has(q) ? "aram" : "sr";
}

function mapArtUrls(kind, ddragonVersion) {
  const a = MAP_ART[kind];
  if (!a) return [];
  const out = [];
  if (ddragonVersion) out.push("/data/ddragon/" + ddragonVersion + "/img/map/" + a.ddragon);
  out.push(a.svg);
  return out;
}

function haloUnits(ageS) {
  const a = Number(ageS);
  if (!(a > 0)) return 0;
  for (let i = 1; i < HALO_BY_AGE.length; i++) {
    const [a1, u1] = HALO_BY_AGE[i];
    if (a <= a1) {
      const [a0, u0] = HALO_BY_AGE[i - 1];
      return u0 + (u1 - u0) * (a - a0) / (a1 - a0);
    }
  }
  return HALO_MAX_UNITS;
}

function monogram(name) {
  const s = String(name == null ? "" : name).replace(/[^A-Za-z0-9 ]/g, "").trim();
  if (!s) return "??";
  const words = s.split(/\s+/).filter(Boolean);
  const mg = words.length > 1 ? words[0][0] + words[1][0] : s.slice(0, 2);
  return mg.toUpperCase().padEnd(2, "?");
}

function worldToCanvas(pos, kind, w, h) {
  const size = MAP_WORLD[kind] || MAP_WORLD.sr;
  // Game origin is bottom-left with y growing up; canvas y grows down.
  return [(pos[0] / size) * w, h - (pos[1] / size) * h];
}

function _dist(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

// A position is two finite NUMBERS. Coercion is deliberately refused
// (Number.isFinite, unlike the global isFinite, is false for any non-number):
// Number(null) and Number("") are 0, so a coercing check would draw a missing
// position at the map's bottom-left corner.
function _validPos(p) {
  return Array.isArray(p) && p.length >= 2
    && Number.isFinite(p[0]) && Number.isFinite(p[1]);
}

function _median(xs) {
  const s = xs.slice().sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

// --- model ------------------------------------------------------------------------
// buildModel(match) -> {
//   hidden, kind, teamOf: Map pid->team, fountains: {100: [x,y], 200: [x,y]},
//   windows: Map pid -> [{start, end, killPos, revived, earlyRespawn}],
//   samples: Map pid -> [{t, pos, src}] sorted by t   (src: frame|kill|respawn|revive)
//   flags:   [{pid, kind: "revive", t}]
// }
function buildModel(match) {
  const d = match || {};
  const kind = mapKindForQueue(d.queue_id);
  const empty = { hidden: true, kind, teamOf: new Map(), fountains: {},
                  windows: new Map(), samples: new Map(), flags: [] };
  if (!kind) return empty;

  const teamOf = new Map();
  for (const p of d.participants || []) teamOf.set(p.participant_id, p.team_id);

  // Per-pid frames, sorted by time: {t, level, pos|null}.
  const frames = new Map();
  let anyPos = false;
  const snaps = (d.snapshots || []).slice()
    .sort((a, b) => Number(a.timestamp_ms) - Number(b.timestamp_ms));
  for (const s of snaps) {
    const t = Number(s.timestamp_ms);
    for (const e of s.entries || []) {
      const pos = _validPos(e.pos) ? [Number(e.pos[0]), Number(e.pos[1])] : null;
      if (pos) anyPos = true;
      if (!frames.has(e.participant_id)) frames.set(e.participant_id, []);
      frames.get(e.participant_id).push({ t, level: e.level, pos });
    }
  }
  if (!anyPos) return empty;

  // Fountains: the match's own frame 0 (spawn), else the measured fallback.
  const fountains = {};
  for (const team of [100, 200]) {
    const xs = [], ys = [];
    for (const [pid, fr] of frames) {
      if (teamOf.get(pid) !== team) continue;
      for (const f of fr) if (f.t < 1000 && f.pos) { xs.push(f.pos[0]); ys.push(f.pos[1]); }
    }
    fountains[team] = xs.length ? [_median(xs), _median(ys)] : FOUNTAIN_FALLBACK[kind][team].slice();
  }

  // Death windows from kill events.
  const kills = (d.kills || []).slice()
    .sort((a, b) => Number(a.timestamp_ms) - Number(b.timestamp_ms));
  const windows = new Map();
  for (const k of kills) {
    const v = k.victim_id;
    if (!teamOf.has(v)) continue;
    const t = Number(k.timestamp_ms);
    let level = null;
    for (const f of frames.get(v) || []) {
      if (f.t > t) break;
      if (f.level != null) level = f.level;
    }
    if (level == null) level = 1;
    const w = {
      start: t, end: t + deathTimerS(level, t) * 1000,
      killPos: _validPos(k.pos) ? [Number(k.pos[0]), Number(k.pos[1])] : null,
      revived: false, earlyRespawn: false,
    };
    if (!windows.has(v)) windows.set(v, []);
    windows.get(v).push(w);
  }

  // Contradictions. A second death inside a window proves the first was
  // revived. A frame inside a window either echoes the death spot (normal),
  // sits at the fountain (early respawn: clip the window), or is neither
  // (revive). Flags are surfaced, never silently resolved.
  const flags = [];
  for (const [pid, ws] of windows) {
    const fountain = fountains[teamOf.get(pid)];
    for (let i = 0; i < ws.length; i++) {
      const w = ws[i];
      const next = ws[i + 1];
      if (next && next.start > w.start && next.start < w.end) {
        w.revived = true;
        flags.push({ pid, kind: "revive", t: w.start });
        continue;
      }
      for (const f of frames.get(pid) || []) {
        if (!(f.t > w.start && f.t < w.end) || !f.pos) continue;
        if (w.killPos && _dist(f.pos, w.killPos) <= ECHO_TOL_UNITS) continue;
        if (fountain && _dist(f.pos, fountain) <= ECHO_TOL_UNITS) {
          w.end = f.t;
          w.earlyRespawn = true;
          break;
        }
        w.revived = true;
        flags.push({ pid, kind: "revive", t: w.start });
        break;
      }
    }
  }

  const deadAt = (pid, t) => (windows.get(pid) || [])
    .some((w) => !w.revived && t >= w.start && t < w.end);

  // Samples.
  const samples = new Map();
  const push = (pid, s) => {
    if (!samples.has(pid)) samples.set(pid, []);
    samples.get(pid).push(s);
  };
  for (const [pid, fr] of frames) {
    for (const f of fr) {
      if (!f.pos || deadAt(pid, f.t)) continue;   // a dead champion's frame is its death spot
      push(pid, { t: f.t, pos: f.pos, src: "frame" });
    }
  }
  for (const k of kills) {
    const t = Number(k.timestamp_ms);
    if (!_validPos(k.pos)) continue;
    const pos = [Number(k.pos[0]), Number(k.pos[1])];
    // Killer id 0 = an execute (tower / minion / monster). A posthumous kill
    // (killer already dead) says nothing about where the killer stands.
    if (teamOf.has(k.killer_id) && !deadAt(k.killer_id, t)) {
      push(k.killer_id, { t, pos, src: "kill" });
    }
  }
  for (const [pid, ws] of windows) {
    for (const w of ws) {
      if (w.revived) {
        if (w.killPos) push(pid, { t: w.start, pos: w.killPos, src: "revive" });
      } else {
        push(pid, { t: w.end, pos: fountains[teamOf.get(pid)].slice(), src: "respawn" });
      }
    }
  }
  // Stable order: by time; at equal time a kill/respawn snap beats a frame.
  const rank = { frame: 0, revive: 1, respawn: 2, kill: 3 };
  for (const list of samples.values()) {
    list.sort((a, b) => (a.t - b.t) || (rank[a.src] - rank[b.src]));
  }

  return { hidden: false, kind, teamOf, fountains, windows, samples, flags };
}

// stateAt(model, pid, tMs) -> what to draw for one champion at one moment.
//   dead:    {visible: false, dead: true, deathPos, respawnInS}
//   unknown: {visible: false, dead: false}
//   alive:   {visible: true, pos, src, sampleT, ageS, haloUnits, revive}
function stateAt(model, pid, tMs) {
  const t = Number(tMs);
  const ws = (model && model.windows && model.windows.get(pid)) || [];
  let floor = -Infinity;
  for (const w of ws) {
    if (w.revived) continue;
    if (t >= w.start && t < w.end) {
      return { visible: false, dead: true, deathPos: w.killPos,
               respawnInS: (w.end - t) / 1000 };
    }
    if (w.end <= t && w.end > floor) floor = w.end;
  }
  const list = (model && model.samples && model.samples.get(pid)) || [];
  let best = null;
  for (const s of list) {
    if (s.t > t) break;
    if (s.t >= floor) best = s;   // never reach back across a death
  }
  if (!best) return { visible: false, dead: false };
  const ageS = (t - best.t) / 1000;
  const revive = best.src === "revive"
    || ws.some((w) => w.revived && t >= w.start && t < w.start + 60000);
  return { visible: true, dead: false, pos: best.pos, src: best.src,
           sampleT: best.t, ageS, haloUnits: haloUnits(ageS), revive };
}

export {
  deathTimerS, tifPct, haloUnits, monogram, mapKindForQueue, mapArtUrls,
  buildModel, stateAt, worldToCanvas,
  HALO_BY_AGE, HALO_MAX_UNITS, ECHO_TOL_UNITS, FOUNTAIN_FALLBACK, MAP_WORLD,
  DEATH_BRW_SECONDS, _validPos,
};
