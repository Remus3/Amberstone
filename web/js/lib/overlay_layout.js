// web/js/lib/overlay_layout.js
//
// RC Overlay Doctrine (docs/OVERLAY_DOCTRINE.md section 2-4) - the movable,
// position-PERSISTENT widget field. Replaces the old monolithic 460px right-edge
// dock: each in-game cue is an independently absolute-positioned widget the
// operator drags to where their eye rests, and the (x,y) is saved + reloaded so
// it never moves on its own again (rule 9: fixed/learnable beats smart/moving).
//
// Self-gates on body[data-shell="overlay"] - a no-op on the 1920 dashboard
// (retired as a user surface, but it still renders for headless audits, so this
// must not touch it). The CSS (.ovx-widget in overlay.css) owns position:fixed +
// the Hextech shell; this module owns ONLY the dynamic left/top + the drag +
// the persistence, so the look and the layout logic never drift.
//
// Drag is grabbed by a small handle marked data-rc-zone so the rc-shell
// click-through machine (clickthrough_zones.js) makes JUST the handle
// interactive while the widget body stays click-through during play; in a plain
// browser (no rc-shell bridge) everything is clickable, so drag still works for
// preview / headless audit captures.
//
// Persistence: localStorage["rc-overlay-layout"] = { <id>: {x,y,hidden,scale} }.
// When the rc-shell bridge exposes setWidgetLayout/getWidgetLayout the layout is
// ALSO mirrored to the shell's on-disk state (durable across a localStorage
// wipe + hand-editable); absent the bridge it degrades to localStorage-only,
// which already survives a reload since the overlay shares the dashboard origin.

const LS_KEY = "rc-overlay-layout";

// Widget registry: id -> mount selector + default 1080p (x,y) + tier. Defaults
// push urgent cues toward the eye (minimap / champion HUD / combat center) per
// OVERLAY_DOCTRINE section 4. (x,y) is the widget top-left in 1920x1080 game px;
// the body zoom (--rc-overlay-scale / ovscale) scales them with the window.
const WIDGETS = [
  // Default 1080p positions = the EYE-LINE ANCHORS (OVERLAY_DOCTRINE section 4).
  // Operator chose near-the-eye over the old left-edge column (2026-06-22): each
  // cue defaults to where the eye already rests rather than a tidy out-of-play
  // gutter, so the most time-critical call is not in the corner furthest from the
  // combat center-of-mass (rule 9). Placement map: the CALL sits upper-center
  // above combat; the A/B choices sit lower-center above the ability bar; the
  // objective/spike callouts sit at the minimap; the macro-lead pill sits under
  // the top score bar; the spike cue sits bottom-left by the champion stats; the
  // trinket glyph sits by the avatar. Drag still OVERRIDES + PERSISTS per widget
  // (rule 9), and Alt+Shift+R resets the field to THESE defaults (section 3).
  // (x,y) is design-px in 1920x1080; the fullscreen window's body zoom scales them
  // with the resolution.
  // Operator 2026-06-27 nudge: CALL (760,140 -> 180,130) + the WARD/trinket glyph
  // (920,540 -> 340,600) moved OFF the center combat column - they were rendering
  // over the champion / top play lane in-game. The rest keep the near-eye anchors;
  // drag still overrides per-widget (Ctrl+Shift+A then drag; Alt+Shift+R resets).
  { id: "w-lead", sel: "#rn-lead", x: 786, y: 44, tier: "ambient", label: "Macro Lead" },
  { id: "w-call", sel: "#view-active-match .am-pane-call", x: 180, y: 130, tier: "primary", label: "Coach Call" },
  { id: "w-choices", sel: "#rn-choices", x: 760, y: 815, tier: "urgent", label: "A/B Choices" },
  { id: "w-callouts", sel: "#rn-callouts", x: 1486, y: 780, tier: "ambient", label: "Callouts" },
  { id: "w-threat", sel: "#view-active-match .am-pane-cd", x: 1604, y: 560, tier: "urgent", label: "Threat / CDs" },
  { id: "w-build", sel: "#view-active-match .am-pane-build", x: 70, y: 470, tier: "ambient", label: "Build" },
  { id: "w-ovds", sel: "#am-pane-ovds", x: 20, y: 780, tier: "ambient", label: "DS Controls" },
  // New doctrine cues (OVERLAY_DOCTRINE section 4). Both are data-gated (their
  // renderer un-hides the mount only when actionable) + coach-core (shown in
  // every panel set). Mounted as direct am-grid children (NOT inside a pane) so
  // position:fixed is viewport-relative, not trapped by a transformed pane.
  { id: "w-trinket", sel: "#am-ward-cue", x: 340, y: 600, tier: "urgent", label: "Ward Cue" },
  { id: "w-spike", sel: "#am-spike-cue", x: 360, y: 840, tier: "urgent", label: "Spike Cue" },
];

// The launcher is a CONTROL widget, not a panel: a small always-visible square
// (HUD summoner-spell sized) the operator drags anywhere and taps (in ACTIVE) to
// open the layout control center - per-panel show/hide + reset + panel-set. It is
// the in-game escape hatch back to a panel that was right-click-hidden: the only
// other un-hide path (Alt+Shift+R resetOverlayLayout) is Electron-globalShortcut-
// only and so dead while League holds foreground focus. Deliberately NOT in
// WIDGETS - it is never itself hideable and never appears in its own panel list.
// Its position rides the same _layout mirror under its own id; a reset clears that
// entry, so it returns to the default corner (and stays visible) like every panel.
const LAUNCHER = { id: "w-launcher", sel: "#w-launcher", x: 24, y: 24, tier: "control", label: "Overlay menu" };

// Panel sets the menu can switch to (mirror of rc-shell overlay_state PANEL_SETS;
// the shell's normOverlayAction re-validates, so this list is only the UI source).
const PANEL_SETS = ["coach", "build", "threat"];

let _layout = {};
let _saveTimer = 0;

function _readLayout() {
  try {
    const o = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    return o && typeof o === "object" ? o : {};
  } catch (_e) {
    return {};
  }
}

function _persist() {
  // Debounced write: a drag fires many pointermove ticks; only the settled
  // position needs to hit storage. localStorage is synchronous + origin-shared.
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(_layout));
    } catch (_e) {
      // best-effort; a full / disabled storage must not break dragging.
    }
    try {
      if (window.rcShell && typeof window.rcShell.setWidgetLayout === "function") {
        Promise.resolve(window.rcShell.setWidgetLayout(_layout)).catch(() => {});
      }
    } catch (_e) {
      // no bridge (plain browser) - localStorage already holds the value.
    }
  }, 400);
}

function _posFor(w) {
  const saved = _layout[w.id] || {};
  return {
    x: Number.isFinite(saved.x) ? saved.x : w.x,
    y: Number.isFinite(saved.y) ? saved.y : w.y,
    hidden: saved.hidden === true,
    scale: Number.isFinite(saved.scale) ? saved.scale : 1,
  };
}

function _applyPos(el, p) {
  // CSS owns position:fixed; this sets only the dynamic values.
  el.style.left = p.x + "px";
  el.style.top = p.y + "px";
  if (p.scale && p.scale !== 1) {
    el.style.setProperty("--ovx-scale", String(p.scale));
  } else {
    el.style.removeProperty("--ovx-scale");
  }
  el.classList.toggle("ovx-hidden", p.hidden);
}

function _bodyZoom() {
  const z = parseFloat(getComputedStyle(document.body).zoom);
  return Number.isFinite(z) && z > 0 ? z : 1;
}

// ACTIVE-mode signal (doctrine section 2/3): the rc-shell main process lights
// the overlay ACTIVE (Alt+Shift+A) by adding the "rc-shell-active" class to
// <html> (rc-shell/src/active_indicator.js activeIndicatorSetJS). That class is
// present in the page DOM EXACTLY while the overlay is interactive, so it is the
// authoritative page-side ACTIVE check - the same gate the drag affordance lives
// behind (the drag handle is only grabbable when click-through is off / ACTIVE).
// PASSIVE (click-through) => the class is absent => this returns false and the
// hide menu stays a pure no-op so right-clicks pass through to the game.
function _isActiveMode() {
  try {
    return document.documentElement.classList.contains("rc-shell-active");
  } catch (_e) {
    return false; // headless / locked-down document: treat as PASSIVE (safe).
  }
}

// Per-widget HIDE affordance (doctrine section 2: "A widget the operator never
// wants is hidden via a per-widget toggle"; section 3: "A per-widget reset is
// the right-click affordance in ACTIVE mode"). Sets hidden:true on this widget's
// layout entry, persists via the EXISTING mirror, and applies the hide through
// the SAME read-side path (_applyPos toggles .ovx-hidden). hidden != deleted -
// the mount + its wiring stay; the field just stops painting it. Restored by the
// existing Alt+Shift+R resetOverlayLayout (clears _layout -> hidden:false again).
function _hideWidget(el, w) {
  _layout[w.id] = { ...(_layout[w.id] || {}), hidden: true };
  _applyPos(el, _posFor(w));
  _persist();
}

// Bidirectional show/hide for the launcher menu's per-panel toggles. _hideWidget
// only sets hidden:true (the right-click affordance); the menu must also bring a
// panel BACK - the whole reason the launcher exists. Same read-side path
// (_applyPos -> .ovx-hidden) and same persistence (mirror) as every other layout
// mutation. The mount is looked up fresh (the menu has no el in hand).
function _setHidden(w, hidden) {
  _layout[w.id] = { ...(_layout[w.id] || {}), hidden: !!hidden };
  const el = document.querySelector(w.sel);
  if (el) _applyPos(el, _posFor(w));
  _persist();
}

// Toggle one panel's visibility; returns the new hidden state (for the menu row).
function _toggleHidden(w) {
  const next = !_posFor(w).hidden;
  _setHidden(w, next);
  return next;
}

// Fire an overlay action through the rc-shell bridge (set-panel / set-active).
// Degrades to a no-op in a plain browser (no bridge); returns whether it fired.
// best-effort: a missing/locked bridge must never throw into a click handler.
function _shellAction(msg) {
  try {
    if (window.rcShell && typeof window.rcShell.overlayAction === "function") {
      window.rcShell.overlayAction(msg);
      return true;
    }
  } catch (_e) {
    // swallow: the click is a convenience, never a crash surface.
  }
  return false;
}

// Right-click hide, mirroring _installDrag's structure. STRICTLY gated on ACTIVE:
// in PASSIVE mode the handler does NOTHING - no preventDefault, no capture - so
// the contextmenu event is never consumed and never blocks/leaks to the game
// underneath the click-through overlay (doctrine: never require a mid-fight
// dismissal, never obstruct). Only in ACTIVE does it preventDefault + hide.
function _installHideMenu(el, w) {
  el.addEventListener("contextmenu", (e) => {
    if (!_isActiveMode()) return; // PASSIVE: pure no-op, let it fall through.
    e.preventDefault();
    _hideWidget(el, w);
  });
}

// Drag core. Returns a `begin(e)` starter the caller wires to whichever element
// should grab the drag: the small handle (always - the passive quick-drag via
// data-rc-zone) AND, in ACTIVE mode, the whole widget body (operator 2026-06-27:
// "in ACTIVE I expect to drag the panel, not hunt a 3px grip"). Capture +
// move/up live on `el` so a drag begun from either trigger tracks identically.
function _installDrag(el, w) {
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;

  const begin = (e) => {
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const p = _posFor(w);
    originX = p.x;
    originY = p.y;
    el.classList.add("ovx-dragging");
    try {
      el.setPointerCapture(e.pointerId);
    } catch (_e) {
      // setPointerCapture can throw if the pointer is gone; harmless.
    }
    e.preventDefault();
  };

  el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    // clientX/Y are screen px; the stored (x,y) are design px, so divide the
    // delta by the body zoom to keep 1:1 cursor tracking at any ovscale.
    const z = _bodyZoom();
    const nx = Math.round(originX + (e.clientX - startX) / z);
    const ny = Math.round(originY + (e.clientY - startY) / z);
    _layout[w.id] = { ...(_layout[w.id] || {}), x: nx, y: ny };
    el.style.left = nx + "px";
    el.style.top = ny + "px";
  });

  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("ovx-dragging");
    try {
      el.releasePointerCapture(e.pointerId);
    } catch (_e) {
      // already released; harmless.
    }
    _persist();
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  return begin;
}

// Clickable controls inside a widget that must NOT start a body drag in ACTIVE
// mode - a press on these should still actuate the control (and the handle has
// its own grab). Everything else in the body becomes a drag surface in ACTIVE.
const _NO_BODY_DRAG =
  ".ovx-handle, button, input, select, textarea, a, [contenteditable], " +
  "#ovset, #rn-choices, #am-pane-ovds, [data-rc-zone]";

function _makeHandle(el, w) {
  if (el.querySelector(":scope > .ovx-handle")) return;
  const h = document.createElement("div");
  h.className = "ovx-handle";
  // data-rc-zone: the rc-shell click-through machine makes this grabbable in
  // PASSIVE mode without the global ACTIVE toggle - a deliberate small target so
  // the body stays click-through during play (no accidental drags mid-fight).
  h.setAttribute("data-rc-zone", "");
  h.title = "drag to move (saves automatically); right-click to hide (ACTIVE)";
  h.innerHTML = "<span></span><span></span><span></span>";
  el.appendChild(h);
  const begin = _installDrag(el, w);
  // Handle: always grabbable (the passive quick-drag target).
  h.addEventListener("pointerdown", begin);
  // Body: grabbable ONLY in ACTIVE mode, and never on an interactive control or
  // the handle (operator 2026-06-27: once you have explicitly entered ACTIVE,
  // drag the whole panel instead of hunting the small grip).
  el.addEventListener("pointerdown", (e) => {
    if (!_isActiveMode()) return;
    if (e.target && e.target.closest && e.target.closest(_NO_BODY_DRAG)) return;
    begin(e);
  });
}

// Attach the right-click hide listener once per mount. Idempotent: a dataset
// flag survives re-renders that keep the same node, and _placeAll re-runs the
// whole pass after a renderer rebuilds a mount (a fresh node has no flag, so the
// listener re-attaches). Mirrors _makeHandle's double-attach guard.
function _makeHideMenu(el, w) {
  if (el.dataset.ovxHideMenu === "1") return;
  el.dataset.ovxHideMenu = "1";
  _installHideMenu(el, w);
}

function _placeAll() {
  for (const w of WIDGETS) {
    const el = document.querySelector(w.sel);
    if (!el) continue;
    el.classList.add("ovx-widget");
    el.dataset.ovxId = w.id;
    el.dataset.ovxTier = w.tier;
    _applyPos(el, _posFor(w));
    _makeHandle(el, w);
    _makeHideMenu(el, w);
  }
}

// --- Launcher control widget + layout control center -------------------------
// The launcher is a small square (HUD summoner-spell sized) that is ALWAYS
// present, ACTIVE-only interactive (no data-rc-zone, so PASSIVE clicks fall
// through to the game - no accidental menu mid-fight). Tap it in ACTIVE to open
// the menu; drag it (movement past a small threshold) to reposition. Both gates
// match the panel drag affordance (ACTIVE-only) so the operator's "enter ACTIVE,
// arrange, leave" flow is uniform.
let _menuEl = null;

// Drag-vs-tap on the launcher: a press that does not move past THRESH px is a TAP
// (open/close the menu); a press that does is a DRAG (reposition + persist). We
// cannot reuse _installDrag (it treats every pointerdown as a drag) because the
// launcher must distinguish the two from a single press.
function _installLauncher(el, w, onTap) {
  const THRESH = 4;
  let down = false;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;
  el.addEventListener("pointerdown", (e) => {
    if (!_isActiveMode()) return; // PASSIVE: ignore so the press falls through.
    down = true;
    moved = false;
    startX = e.clientX;
    startY = e.clientY;
    const p = _posFor(w);
    originX = p.x;
    originY = p.y;
    try {
      el.setPointerCapture(e.pointerId);
    } catch (_e) {
      // harmless if the pointer is gone.
    }
    e.preventDefault();
  });
  el.addEventListener("pointermove", (e) => {
    if (!down) return;
    if (!moved && (Math.abs(e.clientX - startX) > THRESH || Math.abs(e.clientY - startY) > THRESH)) {
      moved = true;
      el.classList.add("ovx-dragging");
    }
    if (!moved) return;
    const z = _bodyZoom();
    const nx = Math.round(originX + (e.clientX - startX) / z);
    const ny = Math.round(originY + (e.clientY - startY) / z);
    _layout[w.id] = { ...(_layout[w.id] || {}), x: nx, y: ny };
    el.style.left = nx + "px";
    el.style.top = ny + "px";
  });
  const end = (e) => {
    if (!down) return;
    down = false;
    el.classList.remove("ovx-dragging");
    try {
      el.releasePointerCapture(e.pointerId);
    } catch (_e) {
      // already released; harmless.
    }
    if (moved) _persist(); // a real drag settled - save the new position.
    else onTap(); // a tap - toggle the menu.
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

function _setMenu(open) {
  if (!_menuEl) return;
  _menuEl.classList.toggle("ovx-menu-open", !!open);
  if (open) _renderMenu(_menuEl);
}

// Rebuild the menu rows from CURRENT state each open so the per-panel [x]/[ ]
// markers reflect what is actually shown right now.
function _renderMenu(menu) {
  menu.innerHTML = "";
  const head = document.createElement("div");
  head.className = "ovx-menu-head";
  head.textContent = "PANELS";
  menu.appendChild(head);

  for (const w of WIDGETS) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "ovx-menu-row ovx-menu-toggle";
    const hidden = _posFor(w).hidden;
    row.dataset.ovxTarget = w.id;
    row.dataset.on = hidden ? "0" : "1";
    row.textContent = (hidden ? "[ ] " : "[x] ") + (w.label || w.id);
    row.addEventListener("click", () => {
      _toggleHidden(w);
      _renderMenu(menu);
    });
    menu.appendChild(row);
  }

  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "ovx-menu-row ovx-menu-reset";
  reset.textContent = "Reset all panels";
  reset.addEventListener("click", () => {
    resetOverlayLayout();
    _renderMenu(menu);
  });
  menu.appendChild(reset);

  const psHead = document.createElement("div");
  psHead.className = "ovx-menu-head";
  psHead.textContent = "PANEL SET";
  menu.appendChild(psHead);
  for (const ps of PANEL_SETS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ovx-menu-row ovx-menu-panelset";
    b.textContent = ps;
    b.addEventListener("click", () => {
      _shellAction({ action: "set-panel", panelSet: ps });
    });
    menu.appendChild(b);
  }

  const done = document.createElement("button");
  done.type = "button";
  done.className = "ovx-menu-row ovx-menu-done";
  done.textContent = "Done (back to play)";
  done.addEventListener("click", () => {
    _setMenu(false);
    _shellAction({ action: "set-active" }); // flip back to PASSIVE / click-through
  });
  menu.appendChild(done);
}

// Create the launcher mount once (idempotent: returns the existing node on a
// re-render). Mounted as a direct #am-grid child (NOT inside a pane) so its
// position:fixed is viewport-relative, matching the doctrine cues.
function _ensureLauncher() {
  // best-effort: a locked-down / minimal document (or a host with no appendChild)
  // must never throw into resetOverlayLayout / init - the launcher is additive.
  try {
    let el = document.querySelector(LAUNCHER.sel);
    if (el) {
      _menuEl = (el.querySelector && el.querySelector(".ovx-launcher-menu")) || _menuEl;
      _applyPos(el, _posFor(LAUNCHER));
      return el;
    }
    const host = document.querySelector("#am-grid") || document.body;
    if (!host || typeof host.appendChild !== "function") return null;

    el = document.createElement("div");
    el.id = "w-launcher";
    el.className = "ovx-widget ovx-launcher";
    el.dataset.ovxId = LAUNCHER.id;
    el.dataset.ovxTier = LAUNCHER.tier;
    el.title = "overlay menu - tap to open (ACTIVE), drag to move";
    el.setAttribute("aria-label", "Open overlay layout menu");

    const icon = document.createElement("div");
    icon.className = "ovx-launcher-icon";
    // three CSS bars (a hamburger glyph drawn in CSS - no non-ASCII source char).
    icon.innerHTML = "<span></span><span></span><span></span>";
    el.appendChild(icon);

    const menu = document.createElement("div");
    menu.className = "ovx-launcher-menu";
    menu.id = "ovx-launcher-menu";
    el.appendChild(menu);
    _menuEl = menu;

    host.appendChild(el);
    _applyPos(el, _posFor(LAUNCHER));
    _installLauncher(el, LAUNCHER, () => _setMenu(!menu.classList.contains("ovx-menu-open")));
    return el;
  } catch (_e) {
    return null; // additive widget; never break the field over it.
  }
}

export function initOverlayLayout() {
  if (document.body.dataset.shell !== "overlay") return;
  _layout = _readLayout();

  // Expose the field reset so the rc-shell Alt+Shift+R global hotkey can call it
  // over executeJavaScript (the overlay is click-through during play, so a
  // page-level keydown never fires - the OS-level hotkey is the only path). The
  // doctrine section 3 reset clears both stores + re-places at the defaults.
  try {
    window.__rcOverlayReset = resetOverlayLayout;
  } catch (_e) {
    // window may be locked down in a headless context; the export still works.
  }

  // Seed from the rc-shell on-disk mirror when localStorage is empty + the
  // bridge is present (durable across a localStorage wipe), then place.
  if (
    Object.keys(_layout).length === 0 &&
    window.rcShell &&
    typeof window.rcShell.getWidgetLayout === "function"
  ) {
    Promise.resolve(window.rcShell.getWidgetLayout())
      .then((s) => {
        if (s && typeof s === "object") {
          _layout = s;
          try {
            localStorage.setItem(LS_KEY, JSON.stringify(_layout));
          } catch (_e) {
            // best-effort mirror.
          }
        }
      })
      .catch(() => {})
      .finally(() => {
        _placeAll();
        _ensureLauncher();
      });
  } else {
    _placeAll();
    _ensureLauncher();
  }

  // The body zoom can change with the window (ovscale); re-apply on resize so
  // the design-px positions keep their on-screen anchor.
  window.addEventListener("resize", () => {
    for (const w of WIDGETS) {
      const el = document.querySelector(w.sel);
      if (el) _applyPos(el, _posFor(w));
    }
  });

  // Survive re-renders. The lead / choices / callouts mounts are rebuilt by
  // their panel renderers (replaceWith / innerHTML), which drops the .ovx-widget
  // class AND the drag handle. A debounced observer re-runs the idempotent
  // _placeAll so positioning + handles re-attach after every re-render. The
  // observer disconnects around its own DOM writes so handle-appends do not
  // re-trigger it (no feedback loop).
  let reTimer = 0;
  const mo = new MutationObserver(() => {
    if (reTimer) return;
    reTimer = setTimeout(() => {
      reTimer = 0;
      mo.disconnect();
      _placeAll();
      _ensureLauncher(); // re-create the launcher if a re-render dropped it
      mo.observe(document.body, { childList: true, subtree: true });
    }, 150);
  });
  mo.observe(document.body, { childList: true, subtree: true });
}

// Reset the field to the section-4 defaults (clears both stores). Wired to a
// future Alt+Shift+R rc-shell hotkey; exported now for tests + a settings hook.
export function resetOverlayLayout() {
  _layout = {};
  try {
    localStorage.removeItem(LS_KEY);
  } catch (_e) {
    // best-effort.
  }
  _placeAll();
  _ensureLauncher(); // restore the launcher to its default corner + keep it shown
  _persist();
}

// Exported for unit tests (pure helpers + the registry + the hide-affordance
// seams). _setLayout lets a test drive the module's internal layout state so the
// contextmenu + reset behavior can be exercised without a real rc-shell bridge.
export const _internals = {
  WIDGETS,
  LAUNCHER,
  PANEL_SETS,
  LS_KEY,
  _posFor,
  _readLayout,
  _isActiveMode,
  _hideWidget,
  _setHidden,
  _toggleHidden,
  _shellAction,
  _ensureLauncher,
  _renderMenu,
  _installHideMenu,
  _makeHandle,
  _persist,
  _applyPos,
  _getLayout: () => _layout,
  _setLayout: (o) => {
    _layout = o && typeof o === "object" ? o : {};
  },
};
