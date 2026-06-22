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
const MAX_ALPHA = 0.25; // hard ceiling on ANY fill alpha (minimap readability)
const ALLY_TINT_MAX = 0.1; // the ally-side flood tint - fainter than the bubbles
const EMA_ALPHA = 0.35; // low-pass coefficient (~1s settle at 2Hz)
const EMA_EPS = 0.002; // "settled" threshold; below this we stop redrawing
// Per-bubble core alpha inside the per-team OFFSCREEN buffer. The whole team
// layer is flattened then blitted onto the minimap at MAX_ALPHA, so overlapping
// same-team bubbles can never stack past the cap (a live CDP pixel sample caught
// raw on-canvas overlaps compositing to ~0.47 on a dense ally blob).
const OFFSCREEN_CORE_ALPHA = 0.55;
// Offscreen alpha for the ally-side flood so it lands at ALLY_TINT_MAX after the
// MAX_ALPHA team-layer blit (it is folded INTO the blue layer, capped with it).
const ALLY_TINT_BASE = ALLY_TINT_MAX / MAX_ALPHA;

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
  if (!bubbles.length && !demarcation && !map_control) return null;
  return { bubbles, demarcation, map_control };
}

// A coarse signature of the SHAPE of the smoothed scene (team count + rounded
// control%). When this is unchanged AND the EMA has converged we skip the
// redraw. Granular motion is caught by the EMA-settled check, not this.
function _sig(z) {
  if (!z) return "";
  const n = z.bubbles.length;
  const pct = z.map_control ? z.map_control.ally_control_pct : -1;
  const dm = z.demarcation ? 1 : 0;
  return `${n}|${pct}|${dm}`;
}

// -- module-scope render state -----------------------------------------
// EMA state survives across ticks; keyed by a stable bubble identity (team +
// index) so the same logical bubble low-passes tick to tick.
let _ema_state = null; // { bubbles:[{cx,cy,r,w}], demarc:{x1,y1,x2,y2}, pct }
let _lastSig = "_unset_";

function _resetMinimapZoi() {
  _ema_state = null;
  _lastSig = "_unset_";
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

function _paint(ctx, scene, demarcRaw, w, h) {
  ctx.clearRect(0, 0, w, h);
  ctx.save();

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
        ctx.drawImage(off, 0, 0);
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

  // 2. Demarcation line on the main canvas (single thin stroke at the cap).
  if (dem) {
    ctx.globalAlpha = _clampAlpha(MAX_ALPHA);
    ctx.strokeStyle = "rgba(230, 230, 240, 1)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(dem.x1, dem.y1);
    ctx.lineTo(dem.x2, dem.y2);
    ctx.stroke();
  }

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
  if (!z) {
    _clearCanvas();
    _resetMinimapZoi();
    return;
  }

  const canvas = document.getElementById("am-zoi-canvas");
  if (!canvas || typeof canvas.getContext !== "function") return;
  const parent = canvas.parentElement || document.getElementById("am-mmrect");
  if (!parent) return;

  const { w, h } = _boxSize(parent);
  if (w <= 0 || h <= 0) return; // box not laid out yet (slice-1 hasn't sized it)

  // size the backing store to the box px; CSS keeps it stretched to 100%.
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;

  const { bubbles, demarc, settled } = _advanceEma(z);
  const sig = _sig(z);

  // Idempotent: skip the redraw only when the shape is unchanged AND nothing is
  // still animating. While converging we redraw every tick.
  if (sig === _lastSig && settled) return;
  _lastSig = sig;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  _paint(ctx, bubbles, demarc, w, h);
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
};
