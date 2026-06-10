// rc-shell/src/active_indicator.js
//
// PURE Phase 4 ACTIVE-indicator string builders (no electron import;
// node:testable). While the overlay is click-through there is zero visual
// difference from ACTIVE mode, so the operator cannot tell whether a click
// will hit the game or the HUD - this glow frame is that missing cue. The
// main process injects these strings (insertCSS + executeJavaScript) into the
// OVERLAY page only; the companion never gets the frame.
//
// Same injected-strings pattern as ./drag_region: the preload is sandboxed
// and cannot require local modules, so strings built here are the only way
// page-side visuals ship from the main process.

"use strict";

const INDICATOR_ID = "rc-shell-active-indicator";
const ACTIVE_CLASS = "rc-shell-active";

// CSS for the glow frame. pointer-events:none is load-bearing - the frame
// covers the whole viewport and must NEVER eat a click meant for an overlay
// control (or, forwarded, the game). Visibility is driven purely by the
// ACTIVE_CLASS on <html> so flips are one classList call, and the effect is
// a static border + inset shadow with an opacity transition - no keyframes,
// per the overlay GPU-light perf rule. z-index matches the drag strip's max
// int32; the indicator mounts after the strip, so equal z paints above it.
function activeIndicatorCSS() {
  return [
    "#" + INDICATOR_ID + " {",
    "  position: fixed;",
    "  inset: 0;",
    "  pointer-events: none;",
    "  z-index: 2147483647;",
    "  border: 2px solid rgba(127, 208, 255, 0.55);",
    "  box-shadow: inset 0 0 14px rgba(127, 208, 255, 0.35);",
    "  opacity: 0;",
    "  transition: opacity 150ms ease;",
    "}",
    "html." + ACTIVE_CLASS + " #" + INDICATOR_ID + " {",
    "  opacity: 1;",
    "}",
  ].join("\n");
}

// JS that mounts the frame div. IDEMPOTENT (getElementById guard) because it
// runs on every did-finish-load and a reload re-fires the hook on a document
// that may already carry the frame. Appends to documentElement, not body, so
// a dashboard framework re-rendering <body> cannot wipe it.
function activeIndicatorMountJS() {
  const idLit = JSON.stringify(INDICATOR_ID);
  return [
    "(function () {",
    "  if (document.getElementById(" + idLit + ")) { return; }",
    '  var el = document.createElement("div");',
    "  el.id = " + idLit + ";",
    "  document.documentElement.appendChild(el);",
    "})();",
  ].join("\n");
}

// JS that shows/hides the frame by toggling ACTIVE_CLASS on <html>. The
// boolean is serialized INTO the string (the overlay page shares no state
// with the main process), so re-running the latest string after a reload
// re-applies the current ACTIVE/PASSIVE truth.
function activeIndicatorSetJS(active) {
  const flag = JSON.stringify(!!active);
  const clsLit = JSON.stringify(ACTIVE_CLASS);
  return [
    "(function () {",
    "  if (" + flag + ") {",
    "    document.documentElement.classList.add(" + clsLit + ");",
    "  } else {",
    "    document.documentElement.classList.remove(" + clsLit + ");",
    "  }",
    "})();",
  ].join("\n");
}

module.exports = {
  INDICATOR_ID,
  ACTIVE_CLASS,
  activeIndicatorCSS,
  activeIndicatorMountJS,
  activeIndicatorSetJS,
};
