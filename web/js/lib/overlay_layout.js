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
  // Default 1080p positions = a tidy LEFT-EDGE column, out of the play area
  // (center / champion HUD / minimap), per operator feedback "so intrusive":
  // non-intrusive beats near-the-eye for the DEFAULT - the operator drags each
  // where they want and it saves. (x,y) is design-px in 1920x1080; the fullscreen
  // window's body zoom scales them with the resolution.
  { id: "w-lead", sel: "#rn-lead", x: 20, y: 92, tier: "ambient" },
  { id: "w-call", sel: "#view-active-match .am-pane-call", x: 20, y: 132, tier: "primary" },
  { id: "w-choices", sel: "#rn-choices", x: 20, y: 300, tier: "urgent" },
  { id: "w-callouts", sel: "#rn-callouts", x: 20, y: 470, tier: "ambient" },
  { id: "w-threat", sel: "#view-active-match .am-pane-cd", x: 20, y: 620, tier: "urgent" },
  { id: "w-build", sel: "#view-active-match .am-pane-build", x: 20, y: 620, tier: "ambient" },
  { id: "w-ovds", sel: "#am-pane-ovds", x: 20, y: 780, tier: "ambient" },
  // New doctrine cues (OVERLAY_DOCTRINE section 4). Both are data-gated (their
  // renderer un-hides the mount only when actionable) + coach-core (shown in
  // every panel set). Mounted as direct am-grid children (NOT inside a pane) so
  // position:fixed is viewport-relative, not trapped by a transformed pane.
  { id: "w-trinket", sel: "#am-ward-cue", x: 20, y: 520, tier: "urgent" },
  { id: "w-spike", sel: "#am-spike-cue", x: 20, y: 580, tier: "urgent" },
];

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

function _installDrag(handle, el, w) {
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;

  handle.addEventListener("pointerdown", (e) => {
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const p = _posFor(w);
    originX = p.x;
    originY = p.y;
    el.classList.add("ovx-dragging");
    try {
      handle.setPointerCapture(e.pointerId);
    } catch (_e) {
      // setPointerCapture can throw if the pointer is gone; harmless.
    }
    e.preventDefault();
  });

  handle.addEventListener("pointermove", (e) => {
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
      handle.releasePointerCapture(e.pointerId);
    } catch (_e) {
      // already released; harmless.
    }
    _persist();
  };
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
}

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
  _installDrag(h, el, w);
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
      .finally(_placeAll);
  } else {
    _placeAll();
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
  _persist();
}

// Exported for unit tests (pure helpers + the registry + the hide-affordance
// seams). _setLayout lets a test drive the module's internal layout state so the
// contextmenu + reset behavior can be exercised without a real rc-shell bridge.
export const _internals = {
  WIDGETS,
  LS_KEY,
  _posFor,
  _readLayout,
  _isActiveMode,
  _hideWidget,
  _installHideMenu,
  _persist,
  _applyPos,
  _getLayout: () => _layout,
  _setLayout: (o) => {
    _layout = o && typeof o === "object" ? o : {};
  },
};
