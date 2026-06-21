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

// Stable signature so an unchanged rect (the common case - it only moves when
// the operator edits game.cfg) does not touch the DOM each poll tick.
function _sig(r) {
  return r ? `${r.x},${r.y},${r.w},${r.h},${r.flip ? 1 : 0}` : "";
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
  const sig = _sig(r);
  if (sig === _lastSig) return; // idempotent: nothing changed this tick
  _lastSig = sig;

  if (!r) {
    mount.hidden = true;
    return;
  }

  // Lift to a position-fixed overlay widget. The .ovx-widget base owns
  // position:fixed + the body-zoom transform that maps design px to the live
  // window; overlay.css [data-ovx-id="w-mmrect"] strips the backing/shadow/
  // bracket to a single gold hairline + pointer-events:none (click-through).
  mount.classList.add("ovx-widget");
  mount.dataset.ovxId = "w-mmrect";
  mount.dataset.ovxTier = "ambient";
  mount.style.left = r.x + "px";
  mount.style.top = r.y + "px";
  mount.style.width = r.w + "px";
  mount.style.height = r.h + "px";
  mount.hidden = false;
}

// Test reset (module-scope sig-dedup state).
export function _resetMinimapRect() {
  _lastSig = "_unset_";
}

export const __test = { normRect, _sig };
