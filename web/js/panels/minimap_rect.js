// web/js/panels/minimap_rect.js
//
// RC Overlay Doctrine w-mmrect: the Zone-of-Influence FOUNDATION. A transparent,
// click-through, gold-hairline OUTLINE box pinned exactly over the live League
// minimap. This slice draws only the aligned outline (proving the geometry); a
// later slice fills it with the ZOI shading.
//
// Data source: /api/state.minimap_rect (dashboard/_state_builder.py), a rect in
// 1920x1080 design px computed from League's game.cfg [HUD] MinimapScale +
// FlipMiniMap (core/league_settings + core/minimap_geometry). LOCAL + free, no
// API. Mode-gated server-side to surfaces that have a minimap; null otherwise.
//
// SETTINGS-pinned, not drag-pinned (doctrine rule-9 exception): the position +
// size are deterministic from game.cfg, so there is NO drag handle - a grabbable
// zone over the click-critical minimap would eat move / ping / minimap-cast
// clicks. The body is pointer-events:none (CSS) so every click passes straight
// through to League. Size is game.cfg-authoritative (the minimap's real size);
// it is re-applied every tick (idempotent, sig-deduped so the poll does not
// thrash the DOM). Self-gates on body[data-shell="overlay"] - a no-op on the
// retired 1920 dashboard. Pure ESM, ASCII only, GPU-light (one static outline,
// no animation).

// Coerce the raw /api/state.minimap_rect into a clean {x,y,w,h,flip} or null.
function normRect(rect) {
  if (!rect || typeof rect !== "object" || Array.isArray(rect)) return null;
  const x = Number(rect.x);
  const y = Number(rect.y);
  const w = Number(rect.w);
  const h = Number(rect.h);
  if (![x, y, w, h].every(Number.isFinite)) return null;
  if (w <= 0 || h <= 0 || x < 0 || y < 0) return null;
  return {
    x: Math.round(x),
    y: Math.round(y),
    w: Math.round(w),
    h: Math.round(h),
    flip: rect.flip === true,
  };
}

// The overlay design canvas (every widget is authored in 1920x1080; the body
// zoom = ovscale reconciles it to the live window). minimap_rect arrives in this
// space.
const DESIGN_W = 1920;
const DESIGN_H = 1080;

// Operator calibration nudge in true screen px (the docstring's "operator-nudge"
// the proportional scale model leaves for residual off-mark error). Applied
// AFTER the body-zoom is cancelled, so these are literal on-screen px at any
// ovscale. +x = right, +y = down. 2026-06-29: operator live-tuned to +7px
// right, +1px down (path: +15 overshot -> 8 -> left 1 / down 1).
const NUDGE_X_PX = 7;
const NUDGE_Y_PX = 1;

// Live body zoom (ovscale). Mirrors overlay_layout._bodyZoom (module-private
// there); a non-finite / non-positive zoom degrades to 1.
function _bodyZoom() {
  if (typeof document === "undefined" || !document.body) return 1;
  const z = parseFloat(getComputedStyle(document.body).zoom);
  return Number.isFinite(z) && z > 0 ? z : 1;
}

// Pure placement math: map the 1920x1080 design rect onto the live window so the
// box lands PIXEL-EXACT over the native in-game minimap, immune to ovscale.
//
// The minimap is anchored bottom-right at a fixed FRACTION of the render, so the
// box's window-fraction (x/1920, y/1080, ...) is resolution- AND ovscale-
// independent. Positioning the box in raw design px instead scales it by the
// inherited body zoom (ovscale - a DPI/readability knob, NOT the design->native
// ratio), landing it up-and-left of + smaller than the real minimap. So: place
// by window-fraction px and set the box's own zoom to 1/ovscale to cancel the
// inherited body zoom, leaving the box on true window px at any ovscale.
function _placement(r, iw, ih, z) {
  const zz = Number.isFinite(z) && z > 0 ? z : 1;
  return {
    left: (r.x / DESIGN_W) * iw,
    top: (r.y / DESIGN_H) * ih,
    width: (r.w / DESIGN_W) * iw,
    height: (r.h / DESIGN_H) * ih,
    zoom: 1 / zz,
  };
}

// Stable signature so an unchanged scene (the common case - the rect only moves
// when the operator edits game.cfg, but the window size / ovscale can also
// change) does not touch the DOM each poll tick. Includes the viewport + zoom so
// a resize / ovscale flip repositions the box.
function _sig(r, iw, ih, z) {
  return r ? `${r.x},${r.y},${r.w},${r.h},${r.flip ? 1 : 0}|${iw}x${ih}@${z}` : "";
}

let _lastSig = "_unset_";

// Render the minimap outline from the raw /api/state.minimap_rect block. Hides
// the box everywhere except the overlay shell, and whenever the rect is null
// (no game / arena / tft / unreadable game.cfg).
export function renderMinimapRect(rect) {
  const mount = document.getElementById("am-mmrect");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    _lastSig = "_unset_";
    return;
  }

  const r = normRect(rect);
  const z = _bodyZoom();
  const iw = (typeof window !== "undefined" && window.innerWidth) || DESIGN_W;
  const ih = (typeof window !== "undefined" && window.innerHeight) || DESIGN_H;
  const sig = _sig(r, iw, ih, z);
  if (sig === _lastSig) return; // idempotent: nothing changed this tick
  _lastSig = sig;

  if (!r) {
    mount.hidden = true;
    return;
  }

  // Lift to a position-fixed overlay widget. overlay.css [data-ovx-id="w-mmrect"]
  // strips the backing/shadow/bracket to a single gold hairline +
  // pointer-events:none (click-through). Unlike every other ovx-widget (which is
  // edge-anchored and WANTS the ovscale body zoom for readability), this box must
  // align pixel-exact to a NATIVE in-game element, so it is placed by window
  // fraction with its own zoom set to cancel the inherited ovscale - see
  // _placement.
  mount.classList.add("ovx-widget");
  mount.dataset.ovxId = "w-mmrect";
  mount.dataset.ovxTier = "ambient";
  const p = _placement(r, iw, ih, z);
  mount.style.left = (p.left + NUDGE_X_PX) + "px";
  mount.style.top = (p.top + NUDGE_Y_PX) + "px";
  mount.style.width = p.width + "px";
  mount.style.height = p.height + "px";
  mount.style.zoom = String(p.zoom);
  mount.hidden = false;
}

// Test reset (module-scope sig-dedup state).
export function _resetMinimapRect() {
  _lastSig = "_unset_";
}

export const __test = { normRect, _sig, _placement, DESIGN_W, DESIGN_H };
