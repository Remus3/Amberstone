// web/js/panels/minimap_zoi.js
//
// RC Overlay Doctrine w-mmrect ZOI FILL (item 567 slice 3). The Zone-of-Influence
// shading that lives INSIDE the slice-1 minimap outline box (#am-mmrect). This is
// the layer the outline was built to host: low-opacity team "presence" bubbles
// (ally blue / enemy red), a soft demarcation line between the two zones, and a
// very faint tint on the ally side - all painted onto a <canvas> pinned exactly
// over the live League minimap.
//
// Data source: /api/state.zoi (dashboard/_state_builder.py via core/zoi_*), a
// block in BOX-FRACTION space [0,1] (origin top-left, x right, y down) so it is
// resolution-independent: x_px = cx * canvas.width, r_px = r_frac * canvas.width.
// null whenever the mode has no ZOI (out of game / arena / tft / unreadable).
//
// Three doctrine-critical properties, each enforced + tested:
//
//   CLICK-THROUGH. The canvas is a child of the pointer-events:none #am-mmrect
//   box and is itself pointer-events:none (CSS + belt-and-suspenders). It MUST
//   NEVER intercept a move / ping / minimap-cast click - every click passes
//   straight through to League. There is deliberately no interactive element.
//
//   ALPHA CAP. ctx.globalAlpha is hard-clamped so the fill NEVER exceeds 0.25
//   (_clampAlpha + MAX_ALPHA); the ally-side tint is fainter still (ALLY_TINT_MAX
//   <= 0.12). The minimap underneath stays fully readable - the ZOI is an ambient
//   hint, not an opaque heatmap.
//
//   EMA SMOOTHING. The raw per-tick centroids / weights / control% / demarcation
//   endpoints jitter at the 2Hz state cadence. A module-scope exponential moving
//   average (_ema, alpha ~0.35) low-pass-filters every animated quantity so the
//   shading glides (~1s settle) instead of popping. Steady input converges with
//   no drift; while converging we keep redrawing, and once the smoothed signature
//   is stable AND the EMA has settled (|delta| < epsilon) we skip the redraw
//   entirely (GPU-light, mirrors the slice-1 sig-dedup).
//
// Self-gates on body[data-shell="overlay"] - a no-op on the retired 1920
// dashboard. Pure ESM, ASCII only.

// -- tunables ----------------------------------------------------------
// DEBUG (resolved 2026-06-30): the ZOI shading never appeared in the live overlay
// because the canvas was rendering at computed opacity 0 - the fill drew correctly
// but was fully transparent. NOT a data / sizing / paint bug. Root-caused with an
// on-canvas probe + an on-screen numeric readout; fixed by forcing
// canvas.style.opacity = "1" in renderMinimapZoi. Flip this to true to stroke a
// bright magenta border + fill over the ZOI canvas after the normal paint (a
// ground-truth probe: magenta on the minimap => canvas opaque + sized + painting).
// Ships OFF.
const DEBUG_ZOI = false;
const MAX_ALPHA = 0.55; // hard ceiling on ANY fill alpha (operator 2026-06-30: 0.25 was invisible and 0.42 still "very very faint" on the live minimap once the opacity bug was fixed; raised to 0.55 - tunable, fine-tune live next session if too strong/faint)
const ALLY_TINT_MAX = 0.1; // the ally-side flood tint - fainter than the bubbles
// Gaussian blur (px) applied to each flattened per-team layer as it is blitted so
// the per-champion bubbles merge into a SOFT presence zone rather than reading as
// scattered hard dots (operator 2026-06-30). 0 disables. Tunable - fine-tune live.
const ZOI_BLUR_PX = 12;
const EMA_ALPHA = 0.35; // low-pass coefficient (~1s settle at 2Hz)
const EMA_EPS = 0.002; // "settled" threshold; below this we stop redrawing
// Per-bubble core alpha inside the per-team OFFSCREEN buffer. The whole team
// layer is flattened then blitted onto the minimap at MAX_ALPHA, so overlapping
// same-team bubbles can never stack past the cap (a live CDP pixel sample caught
// raw on-canvas overlaps compositing to ~0.47 on a dense ally blob).
const OFFSCREEN_CORE_ALPHA = 0.85;
// Offscreen alpha for the ally-side flood so it lands at ALLY_TINT_MAX after the
// MAX_ALPHA team-layer blit (it is folded INTO the blue layer, capped with it).
const ALLY_TINT_BASE = ALLY_TINT_MAX / MAX_ALPHA;

// -- ADDITIVE ZOI keys (ZOI Wave 3b, spec G) ---------------------------
// Three NEW additive keys ride the same /api/state.zoi block, each rendered
// independently + tolerant of any subset. A legacy 3-key {bubbles,demarcation,
// map_control} payload is byte-identical to before (these keys simply absent):
//   * mia.rings      -> dashed MIA reachability circles (SR-only by construction)
//   * dmz.path       -> a soft fluid ribbon that REPLACES the straight demarcation
//   * districts[_fused] -> a very faint per-district presence cue (see tint note)
// HIERARCHY (alpha ordering): tints (faintest) < live bubbles < MIA rings < dmz.
const MIA_RING_ALPHA_MAX = 0.5; // dashed outline stroke ceiling; decays w/ confidence
const MIA_RING_ALPHA_MIN = 0.12; // floor so a low-confidence ring is still faintly visible
const MIA_LABEL_PX = 11; // champion-initial label size (>= ~10px legible at 1x per audit)
const MIA_DASH = [4, 3]; // dashed ring pattern (px)
const DMZ_STROKE_ALPHA = 0.45; // the fluid DMZ ribbon centerline stroke
const DMZ_BAND_ALPHA = 0.14; // the soft ribbon fill flanking the centerline (subordinate)
// District presence cue. The presence rows carry NO coordinates (the contract
// shape is {district, ally, enemy, ...}), and the district polygon geometry lives
// in config/minimap_grids/<mode>.json which the browser does NOT fetch (no /config
// route exists - grep dashboard/server.py). SIMPLEST CORRECT FALLBACK (documented
// in notes): render each populated district as a small count dot at a STABLE
// data-derived slot along the canvas top-left edge - a subtle presence tally, NOT
// a positional overlay (we never invent map coords we do not have). Faintest layer.
const TINT_DOT_R_PX = 3; // count-dot radius
const TINT_DOT_ALPHA = 0.28; // dot core alpha inside the offscreen buffer (capped by blit)
const TINT_ROW_STEP_PX = 9; // vertical spacing of the stable tally column
const TINT_INSET_PX = 6; // top-left inset of the tally column

// -- pure helpers (unit-tested via __test) -----------------------------

// Exponential moving average. A null/undefined prev seeds straight to next so a
// fresh attach does not crawl up from 0 (no warm-up lag). prev===next is a hard
// fixed point (no drift on a steady signal).
function _ema(prev, next, alpha) {
  const n = Number(next);
  if (!Number.isFinite(n)) return Number.isFinite(prev) ? prev : 0;
  if (prev === null || prev === undefined || !Number.isFinite(prev)) return n;
  if (prev === n) return prev;
  return prev + alpha * (n - prev);
}

// Clamp any requested alpha into [0, MAX_ALPHA]. Garbage / negative -> 0.
function _clampAlpha(a) {
  const n = Number(a);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return n > MAX_ALPHA ? MAX_ALPHA : n;
}

// Box-fraction [0,1] -> pixels on a `dim`-px canvas axis. Out-of-range fractions
// are clamped to the box; non-finite -> 0.
function fracToPx(frac, dim) {
  let f = Number(frac);
  if (!Number.isFinite(f)) return 0;
  if (f < 0) f = 0;
  else if (f > 1) f = 1;
  return f * dim;
}

// Raw rgba builder (NO alpha clamp). Used only inside the per-team offscreen
// buffer, whose flattened result is later blitted at MAX_ALPHA, so the ON-SCREEN
// alpha is still capped. The public teamColor() keeps the hard clamp.
function _rawTeamRgba(team, a) {
  if (team === "blue") return `rgba(64, 160, 255, ${a})`;
  if (team === "red") return `rgba(255, 72, 72, ${a})`;
  return `rgba(180, 180, 180, ${a})`; // neutral fallback, never throws
}

// Team -> an rgba() string consistent with the minimap palette, alpha hard-capped
// at MAX_ALPHA. ally("blue") = blue-dominant, enemy("red") = red-dominant.
function teamColor(team, alpha) {
  return _rawTeamRgba(team, _clampAlpha(alpha));
}

// Coerce one raw bubble into a clean {team,cx,cy,r_frac,weight} or null.
function _normBubble(b) {
  if (!b || typeof b !== "object") return null;
  const team = b.team === "red" ? "red" : b.team === "blue" ? "blue" : null;
  if (!team) return null;
  const cx = Number(b.cx);
  const cy = Number(b.cy);
  const r = Number(b.r_frac);
  const w = Number(b.weight);
  if (![cx, cy, r].every(Number.isFinite)) return null;
  if (cx < 0 || cx > 1 || cy < 0 || cy > 1 || r <= 0 || r > 1) return null;
  return { team, cx, cy, r_frac: r, weight: Number.isFinite(w) ? w : 0 };
}

// Coerce one raw demarcation into a clean endpoints block or null.
function _normDemarc(d) {
  if (!d || typeof d !== "object") return null;
  const x1 = Number(d.x1);
  const y1 = Number(d.y1);
  const x2 = Number(d.x2);
  const y2 = Number(d.y2);
  if (![x1, y1, x2, y2].every(Number.isFinite)) return null;
  return {
    x1, y1, x2, y2,
    ally_side: typeof d.ally_side === "string" ? d.ally_side : null,
  };
}

// -- ADDITIVE key normalizers (spec G, unit-tested via __test) ----------

// Box-fraction coord in [0,1] or null. Clamps finite in-range, rejects garbage.
function _fracOrNull(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0 || n > 1) return null;
  return n;
}

// Coerce one raw MIA ring into {champion,cx,cy,r_frac,missing_for_s,confidence}
// or null. cx/cy/r_frac are box-fraction [0,1] per CONTRACT; a ring off the box
// or with a non-positive radius is dropped. champion is an optional string.
function _normMiaRing(r) {
  if (!r || typeof r !== "object") return null;
  const cx = _fracOrNull(r.cx);
  const cy = _fracOrNull(r.cy);
  const rf = _fracOrNull(r.r_frac);
  if (cx === null || cy === null || rf === null || rf <= 0) return null;
  const conf = Number(r.confidence);
  const miss = Number(r.missing_for_s);
  return {
    champion: typeof r.champion === "string" && r.champion ? r.champion : null,
    cx, cy, r_frac: rf,
    missing_for_s: Number.isFinite(miss) && miss >= 0 ? miss : 0,
    confidence: Number.isFinite(conf) ? Math.min(1, Math.max(0, conf)) : 0,
  };
}

// Coerce zoi.mia -> {rings:[...],count:int} or null. Drops malformed rings;
// null whenever no valid ring survives (render nothing extra, no reflow).
function normMia(mia) {
  if (!mia || typeof mia !== "object" || Array.isArray(mia)) return null;
  const raw = Array.isArray(mia.rings) ? mia.rings : [];
  const rings = raw.map(_normMiaRing).filter(Boolean);
  if (!rings.length) return null;
  return { rings, count: rings.length };
}

// Coerce zoi.dmz -> {path:[[x,y],...],band_w_frac} or null. Needs >= 2 valid
// box-fraction points; a degenerate/short/malformed path returns null so the
// caller falls back to the legacy straight demarcation (byte-identical).
function normDmz(dmz) {
  if (!dmz || typeof dmz !== "object" || Array.isArray(dmz)) return null;
  const raw = Array.isArray(dmz.path) ? dmz.path : [];
  const path = [];
  for (const p of raw) {
    if (!Array.isArray(p) || p.length < 2) continue;
    const x = _fracOrNull(p[0]);
    const y = _fracOrNull(p[1]);
    if (x === null || y === null) continue;
    path.push([x, y]);
  }
  if (path.length < 2) return null;
  let bw = Number(dmz.band_w_frac);
  if (!Number.isFinite(bw) || bw < 0) bw = 0;
  if (bw > 1) bw = 1;
  return { path, band_w_frac: bw };
}

// Coerce one raw district presence row into {district,ally,enemy} or null.
// Reads fused_present (district_fusion.py) when present, else the raw ally/enemy
// counts (minimap_presence.py). A row with no positive presence is dropped so
// only occupied districts draw a tally dot. NO coordinates exist in the row.
function _normDistrictRow(d) {
  if (!d || typeof d !== "object") return null;
  let ally = 0;
  let enemy = 0;
  const fp = d.fused_present;
  if (fp && typeof fp === "object") {
    ally = Number(fp.ally);
    enemy = Number(fp.enemy);
  } else {
    ally = Number(d.ally);
    enemy = Number(d.enemy);
  }
  ally = Number.isFinite(ally) && ally > 0 ? Math.floor(ally) : 0;
  enemy = Number.isFinite(enemy) && enemy > 0 ? Math.floor(enemy) : 0;
  if (ally <= 0 && enemy <= 0) return null;
  const id = typeof d.district === "string" && d.district
    ? d.district
    : (typeof d.id === "string" ? d.id : "");
  return { district: id, ally, enemy };
}

// Coerce zoi.districts_fused (preferred) or zoi.districts -> a stable-ordered
// list of {district,ally,enemy} occupied rows, or null when none are occupied.
function normDistricts(zoi) {
  if (!zoi || typeof zoi !== "object") return null;
  const src = Array.isArray(zoi.districts_fused)
    ? zoi.districts_fused
    : (Array.isArray(zoi.districts) ? zoi.districts : []);
  const rows = src.map(_normDistrictRow).filter(Boolean);
  if (!rows.length) return null;
  return rows;
}

// Spec H (2026-07-08): champion-identity dots from minimap template matching.
// Each dot has {team,champion,x_frac,y_frac,confidence}  -  discrete identity
// markers (NOT the soft team-presence blobs). Rendered as champion-initial
// labels on top of the ZOI fill.
function _normChampionDot(d) {
  if (!d || typeof d !== "object") return null;
  const team = d.team === "red" ? "red" : d.team === "blue" ? "blue" : null;
  if (!team) return null;
  const champ = typeof d.champion === "string" && d.champion ? d.champion : null;
  if (!champ) return null;
  const cx = _fracOrNull(d.x_frac);
  const cy = _fracOrNull(d.y_frac);
  if (cx === null || cy === null) return null;
  const conf = Number(d.confidence);
  return {
    team,
    champion: champ,
    cx, cy,
    confidence: Number.isFinite(conf) ? Math.min(1, Math.max(0, conf)) : 0,
  };
}

function normChampionDots(zoi) {
  if (!zoi || typeof zoi !== "object") return null;
  const raw = Array.isArray(zoi.champion_dots) ? zoi.champion_dots : [];
  const dots = raw.map(_normChampionDot).filter(Boolean);
  if (!dots.length) return null;
  return dots;
}

// Coerce the raw /api/state.zoi into a clean {bubbles,demarcation,map_control}
// or null. Drops malformed bubbles; preserves a null demarcation as null.
function normZoi(zoi) {
  if (!zoi || typeof zoi !== "object" || Array.isArray(zoi)) return null;
  const rawB = Array.isArray(zoi.bubbles) ? zoi.bubbles : [];
  const bubbles = rawB.map(_normBubble).filter(Boolean);
  const demarcation = _normDemarc(zoi.demarcation);
  let map_control = null;
  if (zoi.map_control && typeof zoi.map_control === "object") {
    const mc = zoi.map_control;
    map_control = {
      ally_control_pct: Number.isFinite(Number(mc.ally_control_pct))
        ? Math.round(Number(mc.ally_control_pct)) : 0,
      action_quadrant: typeof mc.action_quadrant === "string" ? mc.action_quadrant : "",
      line: typeof mc.line === "string" ? mc.line : "",
    };
  }
  // ADDITIVE keys (spec G): each independently optional + validated. A legacy
  // 3-key payload yields mia=null / dmz=null / districts=null so the render is
  // byte-identical to before.
  const mia = normMia(zoi.mia);
  const dmz = normDmz(zoi.dmz);
  const districts = normDistricts(zoi);
  // Spec H (2026-07-08): champion-identity dots - discrete per-champion initial
  // labels (NOT the soft team-presence shading). Additive only.
  const championDots = normChampionDots(zoi);
  if (!bubbles.length && !demarcation && !map_control
      && !mia && !dmz && !districts
      && !championDots) return null;
  return { bubbles, demarcation, map_control, mia, dmz, districts, championDots };
}

// A coarse signature of the SHAPE of the smoothed scene (team count + rounded
// control%). When this is unchanged AND the EMA has converged we skip the
// redraw. Granular motion is caught by the EMA-settled check, not this.
function _sig(z) {
  if (!z) return "";
  const n = z.bubbles.length;
  const pct = z.map_control ? z.map_control.ally_control_pct : -1;
  const dm = z.demarcation ? 1 : 0;
  // Additive keys (spec G) do NOT ride the EMA (they are discrete overlays, not
  // jittering centroids), so fold them into the shape signature - any change in
  // their presence/cardinality must force a redraw even once the EMA has settled.
  const mia = z.mia ? z.mia.count : 0;
  const dz = z.dmz ? z.dmz.path.length : 0;
  const dd = z.districts ? z.districts.length : 0;
  // Spec H: champion-identity dots are discrete identity markers  -  NOT EMA
  // smoothed  -  so their count forces a redraw on arrival/departure.
  const cd = z.championDots ? z.championDots.length : 0;
  return `${n}|${pct}|${dm}|${mia}|${dz}|${dd}|${cd}`;
}

// -- module-scope render state -----------------------------------------
// EMA state survives across ticks; keyed by a stable bubble identity (team +
// index) so the same logical bubble low-passes tick to tick.
let _ema_state = null; // { bubbles:[{cx,cy,r,w}], demarc:{x1,y1,x2,y2}, pct }
let _lastSig = "_unset_";
let _nullStreak = 0; // consecutive renderMinimapZoi(null/invalid) ticks
// Debounce a TRANSIENT absent-zoi frame: the server minimap-dots grab can
// momentarily miss, emptying /api/state.zoi for a poll or two. Hold the last
// painted scene until this many consecutive nulls (~6s at the 2s poll) so the
// overlay does not strobe on/off; feedback_no_reflow_on_data_absence.
const _NULL_CLEAR_STREAK = 3;

function _resetMinimapZoi() {
  _ema_state = null;
  _lastSig = "_unset_";
  _nullStreak = 0;
}

// Pure null-debounce transition: given the current consecutive-null streak and
// whether this tick has a valid scene, return the next streak + whether to
// clear now. A valid scene resets the streak; a null increments it and signals
// a clear only at _NULL_CLEAR_STREAK (so 1-2 transient nulls hold the last
// render). Fail-soft: a non-finite streak restarts at the first null.
function _nullDebounceStep(streak, hasScene) {
  if (hasScene) return { streak: 0, clear: false };
  const next = (Number.isFinite(streak) ? streak : 0) + 1;
  return { streak: next, clear: next >= _NULL_CLEAR_STREAK };
}

// Advance the EMA state toward the freshly-normalized scene. Returns the smoothed
// scene + a `settled` flag (true when every animated quantity is within EMA_EPS
// of its target, i.e. nothing is still visibly moving).
function _advanceEma(z) {
  let settled = true;
  const note = (prev, next) => {
    const v = _ema(prev, next, EMA_ALPHA);
    if (Math.abs(v - Number(next)) > EMA_EPS) settled = false;
    return v;
  };

  const prevB = (_ema_state && _ema_state.bubbles) || [];
  const bubbles = z.bubbles.map((b, i) => {
    const p = prevB[i] || {};
    return {
      team: b.team,
      cx: note(p.cx, b.cx),
      cy: note(p.cy, b.cy),
      r: note(p.r, b.r_frac),
      w: note(p.w, b.weight),
    };
  });

  let demarc = null;
  if (z.demarcation) {
    const p = (_ema_state && _ema_state.demarc) || {};
    demarc = {
      x1: note(p.x1, z.demarcation.x1),
      y1: note(p.y1, z.demarcation.y1),
      x2: note(p.x2, z.demarcation.x2),
      y2: note(p.y2, z.demarcation.y2),
      ally_side: z.demarcation.ally_side,
    };
  }

  const targetPct = z.map_control ? z.map_control.ally_control_pct : 0;
  const pct = note(_ema_state ? _ema_state.pct : null, targetPct);

  // A bubble-count change is a hard discontinuity - force at least one redraw.
  if (!_ema_state || _ema_state.bubbles.length !== bubbles.length) settled = false;

  _ema_state = { bubbles, demarc, pct };
  return { bubbles, demarc, pct, settled };
}

// -- canvas draw -------------------------------------------------------

// Read the live box pixel size from the parent (#am-mmrect): prefer the inline
// width/height that slice-1 sets, fall back to getBoundingClientRect.
function _boxSize(parent) {
  let w = parseFloat(parent.style.width);
  let h = parseFloat(parent.style.height);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
    const r = parent.getBoundingClientRect();
    w = r.width;
    h = r.height;
  }
  return { w: Math.round(w) || 0, h: Math.round(h) || 0 };
}

// A reused offscreen canvas for per-team layer compositing, sized to the box.
// Returns null in a no-DOM context (the unit tests exercise the pure helpers,
// not _paint) so the headless fallback path runs instead.
let _offCanvas = null;
function _offscreen(w, h) {
  try {
    if (typeof document === "undefined" || !document.createElement) return null;
    if (!_offCanvas) _offCanvas = document.createElement("canvas");
    if (_offCanvas.width !== w) _offCanvas.width = w;
    if (_offCanvas.height !== h) _offCanvas.height = h;
    return _offCanvas;
  } catch (_) {
    return null;
  }
}

// Draw one team's radial presence bubbles into a 2d context at full strength
// (the ON-SCREEN cap is applied by the caller's blit). Shared by the offscreen
// and the headless-fallback paths. `rgba(team, a)` builds the fill color.
function _drawTeamBubbles(c, scene, team, w, h, coreAlpha, rgba) {
  let drew = false;
  for (const b of scene) {
    if (b.team !== team) continue;
    drew = true;
    const x = fracToPx(b.cx, w);
    const y = fracToPx(b.cy, h);
    const r = Math.max(1, fracToPx(b.r, w)); // r is a fraction of WIDTH per contract
    const core = rgba(team, coreAlpha);
    const edge = rgba(team, 0); // fade to transparent
    let grad;
    try {
      grad = c.createRadialGradient(x, y, 0, x, y, r);
      grad.addColorStop(0, core);
      grad.addColorStop(1, edge);
      c.fillStyle = grad;
    } catch (_) {
      c.fillStyle = core; // no-gradient fallback
    }
    c.beginPath();
    c.arc(x, y, r, 0, Math.PI * 2);
    c.fill();
  }
  return drew;
}

// Trace the ally-side polygon (line + the box corners on the ally side).
function _allySidePath(c, dem, w, h) {
  c.beginPath();
  c.moveTo(dem.x1, dem.y1);
  c.lineTo(dem.x2, dem.y2);
  if (dem.side === "bottom") { c.lineTo(w, h); c.lineTo(0, h); }
  else if (dem.side === "top") { c.lineTo(w, 0); c.lineTo(0, 0); }
  else if (dem.side === "left") { c.lineTo(0, h); c.lineTo(0, 0); }
  else { c.lineTo(w, h); c.lineTo(w, 0); } // right (default)
  c.closePath();
}

// Ring stroke alpha from confidence: high confidence -> stronger outline. Clamped
// into [MIA_RING_ALPHA_MIN, MIA_RING_ALPHA_MAX] then hard-capped at MAX_ALPHA.
function _miaRingAlpha(conf) {
  const c = Number.isFinite(conf) ? Math.min(1, Math.max(0, conf)) : 0;
  const a = MIA_RING_ALPHA_MIN + c * (MIA_RING_ALPHA_MAX - MIA_RING_ALPHA_MIN);
  return _clampAlpha(a);
}

// District count-tally cue. The rows carry NO map coords + the browser has no
// district geometry (documented fallback), so paint each occupied district as a
// small dot in a STABLE data-derived column at the canvas top-left inset - a
// subtle presence tally that never invents a map position. Faintest layer; drawn
// at TINT_DOT_ALPHA per dot (well under MAX_ALPHA). ally=blue, enemy=red, mixed
// blends toward the majority side.
function _drawDistrictTints(c, districts, w, h) {
  if (!districts || !districts.length) return;
  let i = 0;
  for (const d of districts) {
    const y = TINT_INSET_PX + i * TINT_ROW_STEP_PX;
    if (y > h - TINT_INSET_PX) break; // never spill outside the box
    i += 1;
    const team = d.enemy > d.ally ? "red" : "blue";
    const total = Math.min(5, Math.max(1, d.ally + d.enemy));
    const r = TINT_DOT_R_PX + (total - 1) * 0.6; // more present -> slightly larger
    c.beginPath();
    c.arc(TINT_INSET_PX, y, r, 0, Math.PI * 2);
    c.fillStyle = teamColor(team, TINT_DOT_ALPHA);
    c.fill();
  }
}

// Fluid DMZ ribbon: a soft band (band_w_frac wide) flanking the smoothed path
// polyline, plus a crisp centerline. Replaces the straight demarcation when a
// valid dmz.path is present. All box-fraction -> px; band width is a fraction of
// the box WIDTH (mirrors the bubble radius convention). Subordinate to nothing
// (top of the hierarchy) but still under MAX_ALPHA.
function _drawDmz(c, dmz, w, h) {
  if (!dmz || dmz.path.length < 2) return;
  const pts = dmz.path.map((p) => [fracToPx(p[0], w), fracToPx(p[1], h)]);
  const bandPx = Math.max(0, fracToPx(dmz.band_w_frac, w));
  // 1. soft flanking band (a thick, low-alpha stroke of the same polyline).
  if (bandPx > 0) {
    c.save();
    c.globalAlpha = _clampAlpha(DMZ_BAND_ALPHA);
    c.strokeStyle = "rgba(230, 230, 240, 1)";
    c.lineWidth = bandPx;
    c.lineJoin = "round";
    c.lineCap = "round";
    c.beginPath();
    c.moveTo(pts[0][0], pts[0][1]);
    for (let k = 1; k < pts.length; k += 1) c.lineTo(pts[k][0], pts[k][1]);
    c.stroke();
    c.restore();
  }
  // 2. crisp centerline.
  c.save();
  c.globalAlpha = _clampAlpha(DMZ_STROKE_ALPHA);
  c.strokeStyle = "rgba(230, 230, 240, 1)";
  c.lineWidth = 1.5;
  c.lineJoin = "round";
  c.beginPath();
  c.moveTo(pts[0][0], pts[0][1]);
  for (let k = 1; k < pts.length; k += 1) c.lineTo(pts[k][0], pts[k][1]);
  c.stroke();
  c.restore();
}

// MIA reachability rings: dashed circle outlines at (cx,cy) radius r_frac (of the
// box WIDTH), stroke alpha decaying with confidence, an optional champion-initial
// label. SR-only by construction (the payload is absent in other modes). Drawn
// ABOVE the live bubbles + tints, BELOW the dmz seam.
function _drawMiaRings(c, mia, w, h) {
  if (!mia || !mia.rings || !mia.rings.length) return;
  for (const ring of mia.rings) {
    const x = fracToPx(ring.cx, w);
    const y = fracToPx(ring.cy, h);
    const r = Math.max(2, fracToPx(ring.r_frac, w));
    const a = _miaRingAlpha(ring.confidence);
    c.save();
    c.globalAlpha = a;
    c.strokeStyle = "rgba(255, 214, 120, 1)"; // warm amber - reads as a fog/uncertainty cue
    c.lineWidth = 1.5;
    if (typeof c.setLineDash === "function") c.setLineDash(MIA_DASH);
    c.beginPath();
    c.arc(x, y, r, 0, Math.PI * 2);
    c.stroke();
    if (typeof c.setLineDash === "function") c.setLineDash([]);
    // champion-initial label at the ring center (legible >= ~10px at 1x).
    if (ring.champion) {
      c.globalAlpha = _clampAlpha(Math.max(a, MIA_RING_ALPHA_MIN + 0.1));
      c.fillStyle = "rgba(255, 232, 176, 1)";
      c.font = `${MIA_LABEL_PX}px sans-serif`;
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText(ring.champion.charAt(0).toUpperCase(), x, y);
    }
    c.restore();
  }
}

// Spec H (2026-07-08): champion-identity dots - discrete per-champion initial
// labels rendered ON TOP of the soft team-presence shading. Each dot is a small
// filled circle (team-colored) with the champion's first letter inside. Drawn at
// the exact centroid position (no EMA smoothing  -  these are discrete identity
// markers, not jittering presence blobs). Topmost layer; renders above bubbles,
// MIA rings, and the demarcation seam.
function _drawChampionDots(c, dots, w, h) {
  if (!dots || !dots.length) return;
  const R = 9; // dot radius in px
  c.save();
  for (const d of dots) {
    const cx = fracToPx(d.cx, w);
    const cy = fracToPx(d.cy, h);
    const alpha = _clampAlpha(0.45 + d.confidence * 0.40); // 0.45-0.85 based on match confidence
    // Team-colored filled circle with a dark stroke for contrast on any minimap bg.
    c.beginPath();
    c.arc(cx, cy, R, 0, Math.PI * 2);
    c.fillStyle = d.team === "red"
      ? `rgba(244, 84, 84, ${alpha})`
      : `rgba(72, 144, 240, ${alpha})`;
    c.fill();
    c.strokeStyle = "rgba(10, 14, 20, 0.90)";
    c.lineWidth = 1.2;
    c.stroke();
    // Champion first initial, centered in the dot.
    const initial = d.champion.charAt(0).toUpperCase();
    if (!initial) continue;
    c.fillStyle = "rgba(255, 255, 255, 0.95)";
    c.font = "bold 8px sans-serif";
    c.textAlign = "center";
    c.textBaseline = "middle";
    c.fillText(initial, cx, cy);
  }
  c.restore();
}

function _paint(ctx, scene, demarcRaw, w, h, extras) {
  ctx.clearRect(0, 0, w, h);
  ctx.save();

  const mia = extras && extras.mia ? extras.mia : null;
  const dmz = extras && extras.dmz ? extras.dmz : null;
  const districts = extras && extras.districts ? extras.districts : null;
  const championDots = extras && extras.championDots ? extras.championDots : null;

  // Pre-resolve the demarcation pixel endpoints once. The ally-side tint is
  // folded INTO the blue team layer (below) so tint + ally bubbles are capped
  // together; the line itself is stroked last on the main canvas.
  let dem = null;
  if (demarcRaw) {
    dem = {
      x1: fracToPx(demarcRaw.x1, w), y1: fracToPx(demarcRaw.y1, h),
      x2: fracToPx(demarcRaw.x2, w), y2: fracToPx(demarcRaw.y2, h),
      side: demarcRaw.ally_side,
    };
  }

  // 0. District presence tints - the FAINTEST layer (bottom of the hierarchy),
  //    drawn first so live bubbles + rings + dmz composite ABOVE it.
  if (districts) {
    ctx.globalAlpha = 1;
    _drawDistrictTints(ctx, districts, w, h);
  }

  // 1. Team presence bubbles, composited PER TEAM through an offscreen buffer.
  //    Each team's bubbles (plus, for blue, the ally-side flood) are drawn into
  //    the buffer at full strength, then the FLATTENED buffer is blitted onto
  //    the minimap at MAX_ALPHA - so a single team's ZOI can NEVER exceed the
  //    alpha cap no matter how many bubbles overlap. Only the thin blue/red seam
  //    (the contested boundary) can read denser, which is apt.
  const off = _offscreen(w, h);
  if (off && typeof off.getContext === "function") {
    const octx = off.getContext("2d");
    for (const team of ["blue", "red"]) {
      octx.clearRect(0, 0, w, h);
      octx.globalAlpha = 1;
      let drew = false;
      if (team === "blue" && dem && dem.side) {
        _allySidePath(octx, dem, w, h);
        octx.fillStyle = _rawTeamRgba("blue", ALLY_TINT_BASE);
        octx.fill();
        drew = true;
      }
      drew = _drawTeamBubbles(octx, scene, team, w, h, OFFSCREEN_CORE_ALPHA, _rawTeamRgba) || drew;
      if (drew) {
        ctx.globalAlpha = _clampAlpha(MAX_ALPHA);
        // Blur the flattened team layer as it lands so the per-champion bubbles
        // MERGE into a soft presence ZONE instead of reading as scattered hard
        // dots (operator 2026-06-30: "random red blue dots, no bubbles/coloring").
        // The demarcation LINE is stroked later on the main ctx, so it stays crisp.
        if (ZOI_BLUR_PX > 0 && "filter" in ctx) ctx.filter = `blur(${ZOI_BLUR_PX}px)`;
        ctx.drawImage(off, 0, 0);
        ctx.filter = "none";
      }
    }
    ctx.globalAlpha = 1;
  } else {
    // Headless / no-offscreen fallback: direct draw, per-bubble capped at the
    // clamped teamColor alpha (overlaps may compound, but this path is only the
    // no-DOM safety net; the real overlay always has an offscreen canvas).
    if (dem && dem.side) {
      _allySidePath(ctx, dem, w, h);
      ctx.fillStyle = teamColor("blue", ALLY_TINT_MAX);
      ctx.fill();
    }
    _drawTeamBubbles(ctx, scene, "blue", w, h, MAX_ALPHA, teamColor);
    _drawTeamBubbles(ctx, scene, "red", w, h, MAX_ALPHA, teamColor);
  }

  // 2. MIA reachability rings (ABOVE bubbles, BELOW the seam). SR-only by
  //    construction (payload absent elsewhere).
  if (mia) _drawMiaRings(ctx, mia, w, h);

  // 3. The zone seam. A valid fluid DMZ path REPLACES the straight demarcation
  //    (top of the hierarchy). When dmz is null/degenerate the legacy straight
  //    stroke paints EXACTLY as before (byte-identical fallback).
  if (dmz) {
    _drawDmz(ctx, dmz, w, h);
  } else if (dem) {
    ctx.globalAlpha = _clampAlpha(MAX_ALPHA);
    ctx.strokeStyle = "rgba(230, 230, 240, 1)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(dem.x1, dem.y1);
    ctx.lineTo(dem.x2, dem.y2);
    ctx.stroke();
  }

  // 4. Spec H (2026-07-08): champion-identity dots - the TOPMOST minimap layer.
  //    Discrete per-champion initial labels above the soft presence shading, MIA
  //    rings, and demarcation. These are the most precise signal  -  a confident
  //    "this champion IS here"  -  so they render on top of everything.
  if (championDots) _drawChampionDots(ctx, championDots, w, h);

  ctx.restore();
}

// -- dispatch entry ----------------------------------------------------

// Render the ZOI fill from the raw /api/state.zoi block. No-op everywhere except
// the overlay shell; clears + resets whenever zoi is null (out of game / arena /
// tft). Keeps redrawing while the EMA converges; skips the redraw once the scene
// signature is stable AND the smoothing has settled.
export function renderMinimapZoi(zoi) {
  if (typeof document === "undefined" || !document) return; // node / no DOM
  if (!document.body || document.body.dataset.shell !== "overlay") {
    _clearCanvas();
    _resetMinimapZoi();
    return;
  }

  const z = normZoi(zoi);
  const _dbounce = _nullDebounceStep(_nullStreak, !!z);
  _nullStreak = _dbounce.streak;
  if (!z) {
    // Debounce transient nulls: hold the last scene until _NULL_CLEAR_STREAK
    // consecutive nulls (a real out-of-game), so a momentary empty
    // /api/state.zoi does not blank the overlay ~1 Hz.
    if (_dbounce.clear) {
      _clearCanvas();
      _resetMinimapZoi();
    }
    return;
  }

  const canvas = document.getElementById("am-zoi-canvas");
  if (!canvas || typeof canvas.getContext !== "function") return;
  const parent = canvas.parentElement || document.getElementById("am-mmrect");
  if (!parent) return;

  const { w, h } = _boxSize(parent);
  if (w <= 0 || h <= 0) return; // box not laid out yet (slice-1 hasn't sized it)

  // Size the backing store to the box px, and pin the CSS display size to match.
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  // THE bug (root-caused 2026-06-30 via an on-canvas probe): the ZOI canvas was
  // rendering at computed opacity 0 in the live Electron overlay, so the shading
  // drew correctly but was fully transparent and NEVER appeared in-game - even
  // though the data + box + paint were all right. No CSS/JS rule set it (most
  // likely a Chromium quirk for an absolutely-positioned child inside the
  // position:fixed + zoomed #am-mmrect). Force the element opaque. The ZOI's
  // intended faintness is the 2D globalAlpha cap (MAX_ALPHA), NOT element opacity,
  // so pinning this to 1 is correct.
  canvas.style.opacity = "1";

  const { bubbles, demarc, settled } = _advanceEma(z);
  const sig = _sig(z);

  // Idempotent: skip the redraw only when the shape is unchanged AND nothing is
  // still animating. While converging we redraw every tick.
  if (sig === _lastSig && settled) return;
  _lastSig = sig;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  // The additive spec-G layers (mia rings / fluid dmz / district tints) are
  // discrete overlays, not EMA-smoothed centroids, so they ride straight off the
  // normalized scene `z` (already validated + subset-tolerant).
  _paint(ctx, bubbles, demarc, w, h, {
    mia: z.mia, dmz: z.dmz, districts: z.districts,
    championDots: z.championDots,
  });
  if (DEBUG_ZOI) {
    // Ground-truth probe (DEBUG_ZOI ships OFF): a bright magenta border + fill
    // confirms the canvas is opaque + sized + painting (see the DEBUG_ZOI note).
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = "rgba(255,0,255,0.95)";
    ctx.lineWidth = 4;
    ctx.strokeRect(2, 2, Math.max(0, w - 4), Math.max(0, h - 4));
    ctx.fillStyle = "rgba(255,0,255,0.35)";
    ctx.fillRect(0, 0, w, h);
    ctx.restore();
  }
}

function _clearCanvas() {
  if (typeof document === "undefined" || !document) return;
  const canvas = document.getElementById("am-zoi-canvas");
  if (!canvas || typeof canvas.getContext !== "function") return;
  const ctx = canvas.getContext("2d");
  if (ctx && canvas.width && canvas.height) ctx.clearRect(0, 0, canvas.width, canvas.height);
}

export { _resetMinimapZoi };

export const __test = {
  _ema,
  _clampAlpha,
  teamColor,
  fracToPx,
  normZoi,
  _normBubble,
  _normDemarc,
  _sig,
  MAX_ALPHA,
  ALLY_TINT_MAX,
  EMA_ALPHA,
  // spec G additive-key helpers
  normMia,
  normDmz,
  normDistricts,
  _normMiaRing,
  _normDistrictRow,
  _fracOrNull,
  _miaRingAlpha,
  MIA_RING_ALPHA_MAX,
  MIA_RING_ALPHA_MIN,
  // flicker debounce (transient absent-zoi hold)
  _nullDebounceStep,
  _NULL_CLEAR_STREAK,
  // spec H champion-identity dots (2026-07-08)
  normChampionDots,
  _normChampionDot,
  _drawChampionDots,
};
