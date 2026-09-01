// rc-shell/src/clickthrough_zones.js
//
// PURE RC2 Stage 4.2 click-through-ZONES injected-string builder (no electron
// import; node:testable). Same pattern as ./active_indicator + ./drag_region:
// the sandboxed preload cannot require local modules, so the page-side hover
// detector ships as a string main.js runs (executeJavaScript) on the OVERLAY
// page only.
//
// The overlay is a passive click-through HUD (setIgnoreMouseEvents(true,
// {forward:true}) - clicks pass to the game, but {forward:true} keeps the page
// receiving mouse-move messages). This script watches those moves: while the
// cursor is over an interactive control (a "zone") it reports hover=true over
// the preload bridge (window.rcShell.setZoneHover), and main.js flips the
// window interactive via overlay_state.effectiveIgnoreMouse; off the zone it
// reports false and the HUD goes back to click-through. The net effect is the
// operator can click the settings strip / A+B choices / DS knobs WITHOUT first
// hitting the global ACTIVE hotkey - the "non-intrusive" win for stage 4.2.
//
// Vanguard-safe: no capture, no injection into the game; this is page-side DOM
// only, behind the existing preload bridge.

"use strict";

// The interactive overlay controls that should capture the cursor on hover.
// #ovset = the overlay settings strip (toggles + opacity + revert seconds);
// #rn-choices = the A+B coach choice chips; #am-pane-ovds = the DS fight-model
// knob pane; [data-rc-zone] = a generic opt-in hook so a future control joins a
// zone with no code change here.
//
// Overlay controls ONLY. This selector is compiled into the OVERLAY page and
// nowhere else, so a control that lives in the companion window can never
// match and must not be listed. In particular there is deliberately NO entry
// for the #rc-shell-drag-region move strip: that strip is companion-only (see
// ./drag_region.js), and clickthrough_zones.test.js pins its absence.
const ZONE_SELECTOR = "#ovset, #rn-choices, #am-pane-ovds, [data-rc-zone]";

// JS that wires the hover detector. IDEMPOTENT (a window flag) because it runs
// on every did-finish-load and a reload re-fires the hook. Self-heals when the
// bridge is absent (a plain browser preview): setHover no-ops without throwing.
// The selector literal is embedded so the page-side script is self-contained.
function clickThroughZonesMountJS() {
  const selLit = JSON.stringify(ZONE_SELECTOR);
  return [
    "(function () {",
    '  if (window.__rcZoneHoverWired) { return; }',
    "  window.__rcZoneHoverWired = true;",
    "  var SEL = " + selLit + ";",
    "  var hovering = false;",
    "  function setHover(on) {",
    "    on = !!on;",
    "    if (on === hovering) { return; }",
    "    hovering = on;",
    "    try {",
    "      if (window.rcShell && typeof window.rcShell.setZoneHover === 'function') {",
    "        window.rcShell.setZoneHover(on);",
    "      }",
    "    } catch (e) { /* no bridge - best effort */ }",
    "  }",
    "  function hit(node) {",
    "    return !!(node && typeof node.closest === 'function' && node.closest(SEL));",
    "  }",
    // pointermove (capture) is the robust hit-test: setHover dedups, so the
    // bridge only fires on a true enter/leave transition, not per move.
    "  document.addEventListener('pointermove', function (e) {",
    "    setHover(hit(e.target));",
    "  }, true);",
    // pointerdown covers a click that lands without a preceding move (e.g.
    // tap), so the very first interaction is never swallowed.
    "  document.addEventListener('pointerdown', function (e) {",
    "    setHover(hit(e.target));",
    "  }, true);",
    // Leaving the overlay region entirely drops the hover so the HUD returns
    // to click-through even if no final move landed off a zone.
    "  window.addEventListener('pointerleave', function () { setHover(false); }, true);",
    "  document.addEventListener('mouseleave', function () { setHover(false); }, true);",
    "})();",
  ].join("\n");
}

module.exports = {
  ZONE_SELECTOR,
  clickThroughZonesMountJS,
};
