// rc-shell/src/window_controls.js
//
// PURE window-control string builders (no electron import; node:testable). The
// companion window is FRAMELESS (frame:false in main.js), so the remote RC
// dashboard it loads has no native minimize / close / pin chrome. The main
// process injects this strip (insertCSS + executeJavaScript) after every load -
// a small top-right cluster of three controls, sibling to the drag region:
//
//   [ on-top toggle ] [ minimize ] [ close ]
//
// The controls call back over the allow-listed preload bridge (window.rcShell):
//   winToggleAlwaysOnTop() -> Promise<boolean>   (also reflects the initial state
//                                                 via winGetAlwaysOnTop())
//   winMinimize()          -> void
//   winClose()             -> void
//
// COMPANION ONLY. The in-game overlay never mounts these (it is a passive HUD;
// min/close/pin would be noise and a focus hazard mid-game) - main.js injects
// this strictly on the companion window's did-finish-load.
//
// Glyphs are CSS-drawn (pseudo-elements / borders), so the page textContent
// stays 7-bit ASCII (repo hard rule) and the controls still read like real
// window chrome. Each button carries an aria-label for assistive tech.

"use strict";

const WINDOW_CONTROLS_DEFAULTS = Object.freeze({
  id: "rc-shell-winctl", // the control cluster container
  height: 24, // px; matches the drag-region strip height so they align
  zIndex: 2147483647, // max int32 - sit above any page stacking context
  pinnedClass: "rc-winctl-pinned", // on the cluster when always-on-top is ON
});

// Merge a partial override over the defaults without mutating either.
function resolveOpts(opts) {
  return Object.assign(
    {},
    WINDOW_CONTROLS_DEFAULTS,
    opts && typeof opts === "object" ? opts : {}
  );
}

// CSS for the cluster. position:fixed top-right so it pins to the viewport
// corner regardless of page scroll. The whole cluster + every button is
// -webkit-app-region: no-drag so a frameless drag strip underneath cannot
// swallow the clicks. Glyphs are drawn with ::before/::after (no text nodes).
function windowControlsCSS(opts) {
  const o = resolveOpts(opts);
  const id = "#" + o.id;
  return [
    id + " {",
    "  position: fixed;",
    "  top: 0;",
    "  right: 0;",
    "  height: " + o.height + "px;",
    "  display: flex;",
    "  align-items: stretch;",
    "  z-index: " + o.zIndex + ";",
    "  -webkit-app-region: no-drag;",
    "  pointer-events: auto;",
    "}",
    id + " .rc-winctl-btn {",
    "  -webkit-app-region: no-drag;",
    "  position: relative;",
    "  width: 40px;",
    "  height: 100%;",
    "  margin: 0;",
    "  padding: 0;",
    "  border: 0;",
    "  outline: 0;",
    "  background: rgba(20, 24, 33, 0.55);",
    "  cursor: pointer;",
    "  color: #c8d0e0;",
    "  transition: background 0.12s ease;",
    "}",
    id + " .rc-winctl-btn:hover { background: rgba(70, 80, 100, 0.85); }",
    // Minimize: a single centered bottom bar.
    id + " .rc-winctl-min::before {",
    "  content: '';",
    "  position: absolute;",
    "  left: 50%; top: 58%;",
    "  width: 11px; height: 2px;",
    "  margin-left: -5.5px;",
    "  background: currentColor;",
    "}",
    // Close: two crossed bars (an X) via ::before + ::after.
    id + " .rc-winctl-close::before, " + id + " .rc-winctl-close::after {",
    "  content: '';",
    "  position: absolute;",
    "  left: 50%; top: 50%;",
    "  width: 13px; height: 2px;",
    "  margin-left: -6.5px; margin-top: -1px;",
    "  background: currentColor;",
    "}",
    id + " .rc-winctl-close::before { transform: rotate(45deg); }",
    id + " .rc-winctl-close::after { transform: rotate(-45deg); }",
    id + " .rc-winctl-close:hover { background: #c4283b; color: #fff; }",
    // Always-on-top: an upward chevron (drawn with a rotated open corner).
    id + " .rc-winctl-top::before {",
    "  content: '';",
    "  position: absolute;",
    "  left: 50%; top: 52%;",
    "  width: 9px; height: 9px;",
    "  margin-left: -5px; margin-top: -2px;",
    "  border-left: 2px solid currentColor;",
    "  border-top: 2px solid currentColor;",
    "  transform: rotate(45deg);",
    "}",
    // Pinned (always-on-top ON): light the chevron gold + a faint glow so the
    // toggle state is visible at a glance (color is not the only signal - the
    // aria-pressed attribute also flips).
    id + "." + o.pinnedClass + " .rc-winctl-top { color: #f0b232; }",
    id + "." + o.pinnedClass + " .rc-winctl-top::before { border-color: #f0b232; }",
  ].join("\n");
}

// JS that mounts the cluster. IDEMPOTENT (getElementById guard) because it runs
// on every did-finish-load and a Cmd+R reload re-fires the hook on a document
// that may already carry the cluster. Appended to documentElement (not body) so
// a dashboard framework re-rendering <body> cannot wipe it. Degrades to a safe
// no-op if the preload bridge (window.rcShell) is absent - the buttons mount but
// their handlers simply do nothing rather than throw. Self-contained IIFE.
function windowControlsMountJS(opts) {
  const o = resolveOpts(opts);
  const idLit = JSON.stringify(String(o.id));
  const pinnedLit = JSON.stringify(String(o.pinnedClass));
  return [
    "(function () {",
    "  if (document.getElementById(" + idLit + ")) { return; }",
    "  var bridge = (typeof window !== 'undefined' && window.rcShell) || null;",
    '  var box = document.createElement("div");',
    "  box.id = " + idLit + ";",
    "  function mkBtn(cls, label, onClick) {",
    '    var b = document.createElement("button");',
    '    b.className = "rc-winctl-btn " + cls + " rc-shell-no-drag";',
    '    b.setAttribute("type", "button");',
    '    b.setAttribute("aria-label", label);',
    '    b.setAttribute("title", label);',
    '    b.addEventListener("click", onClick);',
    "    box.appendChild(b);",
    "    return b;",
    "  }",
    "  function reflectPinned(on) {",
    "    if (on) { box.classList.add(" + pinnedLit + "); }",
    "    else { box.classList.remove(" + pinnedLit + "); }",
    '    topBtn.setAttribute("aria-pressed", on ? "true" : "false");',
    "  }",
    // Always-on-top toggle (far left of the cluster).
    '  var topBtn = mkBtn("rc-winctl-top", "Toggle always on top", function () {',
    "    if (!bridge || !bridge.winToggleAlwaysOnTop) { return; }",
    "    bridge.winToggleAlwaysOnTop().then(reflectPinned).catch(function () {});",
    "  });",
    // Minimize.
    '  mkBtn("rc-winctl-min", "Minimize", function () {',
    "    if (bridge && bridge.winMinimize) { bridge.winMinimize(); }",
    "  });",
    // Close (far right).
    '  mkBtn("rc-winctl-close", "Close", function () {',
    "    if (bridge && bridge.winClose) { bridge.winClose(); }",
    "  });",
    "  document.documentElement.appendChild(box);",
    // Reflect the live always-on-top state once the cluster is in the DOM.
    "  if (bridge && bridge.winGetAlwaysOnTop) {",
    "    bridge.winGetAlwaysOnTop().then(reflectPinned).catch(function () {});",
    "  }",
    "})();",
  ].join("\n");
}

module.exports = {
  WINDOW_CONTROLS_DEFAULTS,
  windowControlsCSS,
  windowControlsMountJS,
};
