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
  h.title = "drag to move (saves automatically)";
  h.innerHTML = "<span></span><span></span><span></span>";
  el.appendChild(h);
  _installDrag(h, el, w);
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
  }
}

export function initOverlayLayout() {
  if (document.body.dataset.shell !== "overlay") return;
  _layout = _readLayout();

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

// Exported for unit tests (pure helpers + the registry).
export const _internals = { WIDGETS, LS_KEY, _posFor, _readLayout };
