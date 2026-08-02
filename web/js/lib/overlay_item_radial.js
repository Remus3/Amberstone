// WP-D2 (OVERLAY_BUILD_MASTER_PLAN Section D): right-click radial 5-action menu
// for build-module item icons. A singleton ring lives on <html> (dodging the
// dashboard body `zoom`, the champ_select.js:303 trick) with five data-action
// wedges on the Kurtenbach layout: N=Build-Earlier, E=Build-Later, S=Defer-Once,
// W=Keep on the high-accuracy cardinal axes, center=Silence (so a sloppy flick
// cannot mute by accident). Each wedge writes the per-item override store
// (item_overrides.js); the onAction callback re-renders the LIVE row so the
// reorder shows immediately. D3 makes the server replan honor the overrides.
//
// Coexistence: the icon contextmenu preventDefault + stopPropagation so the
// radial neither dismisses the overlay (overlay_layout.js:241 ACTIVE hide-menu)
// nor cycles the META archetype (active_match.js _cycleMeta on the META strip).

import {
  buildEarlier, buildLater, deferItem, keepItem, silenceItem,
} from "./item_overrides.js";

// Kurtenbach cardinal layout (master plan WP-D2): N=Build-Earlier, E=Build-Later,
// S=Defer-Once, W=Keep on the 4 high-accuracy cardinal axes; Silence on the
// center so a sloppy flick cannot mute by accident.
const _WEDGES = [
  { action: "earlier", label: "EARLY", pos: "top:6px;left:50%;transform:translateX(-50%);" },
  { action: "later",   label: "LATE",  pos: "right:6px;top:50%;transform:translateY(-50%);" },
  { action: "defer",   label: "DEFER", pos: "bottom:6px;left:50%;transform:translateX(-50%);" },
  { action: "keep",    label: "KEEP",  pos: "left:6px;top:50%;transform:translateY(-50%);" },
  // center=Silence is a COMPACT dead-center hub (see _wedgeCss `center`): the four
  // cardinal wedges are ~68px wide, so in the old 140px ring the centered MUTE
  // (also ~68px) overlapped KEEP (left) and LATE (right) horizontally. The ring is
  // now 210px wide + MUTE is a 44px circular chip, so the hub clears the side
  // wedges on both flanks while staying dead-center off the high-accuracy axes.
  { action: "silence", label: "MUTE",  pos: "top:50%;left:50%;transform:translate(-50%,-50%);", center: true },
];

const _ACTION_FN = {
  earlier: buildEarlier, later: buildLater, defer: deferItem,
  keep: keepItem, silence: silenceItem,
};

let _radial = null;
let _onAction = null;     // re-render hook bound at open time
let _curId = null;        // the item the open radial acts on

function _bodyZoom() {
  const z = parseFloat(getComputedStyle(document.body).zoom);
  return Number.isFinite(z) && z > 0 ? z : 1;
}

function _wedgeCss(pos, center) {
  const base = [
    "position:absolute", pos,
    "border-radius:6px",
    "background:rgba(20,24,32,0.97)", "border:1px solid #2a2f3a",
    "box-shadow:0 4px 12px rgba(0,0,0,0.55)",
    "color:#e6e8ee", "font-weight:700",
    "letter-spacing:0.04em", "text-align:center", "cursor:pointer",
  ];
  if (center) {
    // Compact dead-center MUTE target: a tight 44px circular chip, smaller than
    // the ~68px cardinal wedges so it never overlaps KEEP (left) / LATE (right).
    // Reads as the ring hub; the >=44px diameter still clears the touch/flick
    // target floor. Round-border + centered glyph, no min-width/padding growth.
    base.push(
      "width:44px", "height:44px", "padding:0", "box-sizing:border-box",
      "display:flex", "align-items:center", "justify-content:center",
      "border-radius:50%", "font-size:var(--fs-ov-chip,13px)",
    );
  } else {
    // Cardinal wedges: flex-center the label in a >=44px-tall pill so each clears
    // the --hit-min 42px tap/flick-target floor (tokens.css) - the old 5px/7px
    // padding left them ~27px tall, below the floor. Matches the 44px MUTE hub.
    base.push(
      "min-width:52px", "min-height:44px", "padding:4px 9px", "box-sizing:border-box",
      "display:flex", "align-items:center", "justify-content:center",
      "font-size:var(--fs-ov-chip,13px)",
    );
  }
  return base.join(";") + ";";
}

function _ensureRadial() {
  if (_radial) return _radial;
  _radial = document.createElement("div");
  _radial.id = "rc-item-radial";
  // data-rc-zone keeps the in-game overlay (rc-shell click-through) interactive
  // while the cursor is over the open ring, so the wedge clicks land instead of
  // passing through to the game (clickthrough_zones.js ZONE_SELECTOR).
  _radial.setAttribute("data-rc-zone", "");
  // 210x160 ring (was 140x140): widened so the four cardinal wedges + the compact
  // central MUTE hub separate on the horizontal axis (the old 140px box overlapped
  // KEEP/MUTE/LATE), and taller so the now-44px-tall EARLY/MUTE/DEFER wedges keep
  // an 8px vertical gap on the N/S axis. _open() render-then-measures
  // box.width/height, so the viewport clamp + _bodyZoom() adapt to the new size
  // with no other change.
  _radial.style.cssText = [
    "position:fixed", "z-index:2147483601", "width:210px", "height:160px",
    "visibility:hidden", "left:0", "top:0",
  ].join(";") + ";";
  _WEDGES.forEach((w) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "rc-radial-wedge";
    b.setAttribute("data-action", w.action);
    b.textContent = w.label;
    b.style.cssText = _wedgeCss(w.pos, w.center);
    _radial.appendChild(b);
  });
  // Delegated wedge click: route to the store setter, re-render, close.
  _radial.addEventListener("click", (e) => {
    const btn = e.target.closest(".rc-radial-wedge");
    if (!btn) return;
    e.stopPropagation();
    const action = btn.getAttribute("data-action");
    const fn = _ACTION_FN[action];
    if (fn && _curId != null) fn(_curId);
    if (typeof _onAction === "function") _onAction(action, _curId);
    _close();
  });
  document.documentElement.appendChild(_radial);
  // Outside-click dismiss (the radial itself stops its own clicks above).
  document.addEventListener("click", () => { if (_isOpen()) _close(); });
  return _radial;
}

function _isOpen() { return !!_radial && _radial.style.visibility === "visible"; }
function _close() { if (_radial) _radial.style.visibility = "hidden"; }

function _open(clientX, clientY, itemId, onAction) {
  const r = _ensureRadial();
  _curId = itemId;
  _onAction = onAction;
  r.style.zoom = String(_bodyZoom());
  r.style.visibility = "hidden";
  // Render-then-measure: center the ring on the cursor, clamp to the viewport.
  const box = r.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = clientX - box.width / 2;
  let top = clientY - box.height / 2;
  left = Math.max(6, Math.min(left, vw - box.width - 6));
  top = Math.max(6, Math.min(top, vh - box.height - 6));
  r.style.left = Math.round(left) + "px";
  r.style.top = Math.round(top) + "px";
  r.style.visibility = "visible";
}

// Wire the radial onto one build-module icon cell. onAction(action, itemId) is
// the re-render hook the caller passes (clears the build sig + repaints).
export function installItemRadial(anchorEl, itemId, onAction) {
  if (!anchorEl) return;
  anchorEl.addEventListener("contextmenu", (e) => {
    // preventDefault + stopPropagation: do not hide the overlay (ACTIVE
    // _installHideMenu) and do not bubble to the META strip's _cycleMeta.
    e.preventDefault();
    e.stopPropagation();
    _open(e.clientX, e.clientY, itemId, onAction);
  });
}
