// rc-shell/src/drag_region.js
//
// PURE drag-region string builders (no electron import; node:testable). The
// companion window is frameless and loads the REMOTE RC dashboard, which ships
// no -webkit-app-region rule of its own - so without injection the window can
// never be moved. The main process injects these strings (insertCSS +
// executeJavaScript) after every load; the preload stays empty because
// sandbox:true forbids it from requiring local modules.
//
// Same strip on the overlay: while click-through the strip is inert (mouse
// events forward to the game), but in ACTIVE mode it makes the overlay
// user-draggable for free - no extra state plumbing.

"use strict";

const DRAG_REGION_DEFAULTS = Object.freeze({
  id: "rc-shell-drag-region",
  height: 24, // px; thin enough to not cover dashboard content
  zIndex: 2147483647, // max int32 so no page stacking context can sit above it
});

// Merge a partial override over the defaults without mutating either.
function resolveOpts(opts) {
  return Object.assign({}, DRAG_REGION_DEFAULTS, opts && typeof opts === "object" ? opts : {});
}

// CSS for the strip. position:fixed (not absolute) so it pins to the viewport
// regardless of page scroll; background transparent so the dashboard header
// stays visible underneath. The .rc-shell-no-drag rule is the escape hatch for
// any future control rendered inside the strip (buttons must opt out of drag
// or they become unclickable).
function dragRegionCSS(opts) {
  const o = resolveOpts(opts);
  return [
    "#" + o.id + " {",
    "  position: fixed;",
    "  top: 0;",
    "  left: 0;",
    "  width: 100%;",
    "  height: " + o.height + "px;",
    "  z-index: " + o.zIndex + ";",
    "  background: transparent;",
    "  pointer-events: auto;",
    "  -webkit-app-region: drag;",
    "}",
    "#" + o.id + " .rc-shell-no-drag {",
    "  -webkit-app-region: no-drag;",
    "}",
  ].join("\n");
}

// JS that mounts the strip div. IDEMPOTENT (getElementById guard) because it
// runs on every did-finish-load, and a Cmd+R reload re-fires the hook on a
// document that may already carry the strip. Appends to documentElement, not
// body, so a dashboard framework re-rendering <body> cannot wipe the strip.
// Self-contained IIFE returning nothing - safe to executeJavaScript repeatedly.
function dragRegionMountJS(opts) {
  const o = resolveOpts(opts);
  const idLit = JSON.stringify(String(o.id));
  return [
    "(function () {",
    "  if (document.getElementById(" + idLit + ")) { return; }",
    '  var el = document.createElement("div");',
    "  el.id = " + idLit + ";",
    "  document.documentElement.appendChild(el);",
    "})();",
  ].join("\n");
}

module.exports = {
  DRAG_REGION_DEFAULTS,
  dragRegionCSS,
  dragRegionMountJS,
};
