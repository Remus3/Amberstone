// rc-shell/src/overlay_toggle.js
//
// PURE core of the in-game overlay ON/OFF toggle icon (S134 operator request:
// "the ingame overlay [should] have a toggle icon [movable] to enable or
// disable the visual overlay"). NO electron import - node:testable, like
// ./overlay_state.
//
// Shape. The icon is its OWN tiny always-on-top window (overlay_toggle.html),
// not a widget inside the fullscreen overlay window, because it must stay on
// screen while the overlay content is OFF - and OFF hides the overlay window
// outright (cheaper and safer than an invisible fullscreen window over the
// game). The window is exactly the icon, so it is click-through everywhere
// except the icon by construction, and it is focusable:false (Windows
// WS_EX_NOACTIVATE: a click never activates it, so the game keeps focus).
//
// This module owns every decision main.js makes about the icon:
//   - on/off state + persistence (overlay.toggle in rc-shell-state.json,
//     default ON, never clobbering the sibling overlay / companion keys);
//   - where the icon goes: per-display (Electron display id) with the position
//     stored as FRACTIONS of that display's free travel, so a resolution change
//     keeps it in the same relative spot, a vanished monitor falls back to the
//     nearest display, and the result is always clamped fully on-screen;
//   - tap vs drag from one press (the same 4px law as the in-overlay
//     w-launcher in web/js/lib/overlay_layout.js);
//   - which windows show for a surface (the icon follows the in-game surface,
//     the overlay follows the surface AND the toggle);
//   - the IPC allow-list for the toggle page.

"use strict";

const cfg = require("./config");
const ov = require("./overlay_state");

const TOGGLE_DEFAULTS = Object.freeze({
  visible: true, // overlay content ON by default (operator spec)
  baseSize: 32, // icon box in DIP at the 1920x1080 baseline; grows with the HUD scale
  minSize: 24, // hit-target floor (WCAG 2.5.8 minimum target size)
  // Default spot in 1080p design px, scaled like the HUD body zoom: directly
  // under the in-overlay "Overlay menu" launcher (design 24,24, 34px square),
  // so the two controls sit together in the corner the doctrine keeps clear.
  designX: 24,
  designY: 72,
  dragThresholdPx: 4, // a press that moves less than this is a TAP
  label: "Overlay on/off",
  // Keyboard path. Owned by tools/hotkey_listener.py (WH_KEYBOARD_LL - the only
  // hook that sees a chord while League holds focus), which stamps the signal
  // file main.js polls. Electron globalShortcut is dead in-game.
  hotkey: "Ctrl+Shift+O",
});

// Actions the toggle page may send (one validated channel, like
// overlay_state.normOverlayAction). press/move/release/cancel are the pointer
// drag-or-tap protocol; activate is the keyboard (Enter / Space) path.
const TOGGLE_ACTIONS = Object.freeze(["press", "move", "release", "cancel", "activate"]);

const FALLBACK_BOUNDS = Object.freeze({ x: 0, y: 0, width: 1920, height: 1080 });

function _obj(v) {
  return v && typeof v === "object" && !Array.isArray(v) ? v : null;
}

function _num(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function _frac(v) {
  const n = _num(v);
  return n === null ? null : Math.min(1, Math.max(0, n));
}

// A display bounds rect, or null when any field is unusable.
function _bounds(b) {
  const o = _obj(b);
  if (!o) {
    return null;
  }
  const x = _num(o.x);
  const y = _num(o.y);
  const w = _num(o.width);
  const h = _num(o.height);
  if (x === null || y === null || w === null || h === null || w <= 0 || h <= 0) {
    return null;
  }
  return { x, y, width: w, height: h };
}

// Electron screen.getAllDisplays() -> [{ id, bounds }] with garbage dropped.
// bounds (not workArea): a Borderless game covers the taskbar strip too, and
// the overlay window itself is sized to bounds (main.js item 567).
function normDisplays(displays) {
  const list = Array.isArray(displays) ? displays : [];
  const out = [];
  for (const d of list) {
    const o = _obj(d);
    const b = o ? _bounds(o.bounds) : null;
    if (b) {
      out.push({ id: _num(o.id), bounds: b });
    }
  }
  return out;
}

// Icon box size for a display: the baseline box grown by the same resolution
// scale the overlay HUD zooms by, never under the hit-target floor.
function toggleSize(bounds) {
  const b = _bounds(bounds) || FALLBACK_BOUNDS;
  const s = ov.resolveOverlayScale(b);
  return Math.max(TOGGLE_DEFAULTS.minSize, Math.round(TOGGLE_DEFAULTS.baseSize * s));
}

// A saved position, or null. fx/fy are the icon's top-left as a fraction of the
// display's free travel (width - size, height - size), clamped to [0,1]; x/y
// are the absolute DIP coords at save time, used only to find the nearest
// display when the saved one is gone.
function sanitizeTogglePos(pos) {
  const p = _obj(pos);
  if (!p) {
    return null;
  }
  const fx = _frac(p.fx);
  const fy = _frac(p.fy);
  if (fx === null || fy === null) {
    return null;
  }
  return { displayId: _num(p.displayId), fx, fy, x: _num(p.x), y: _num(p.y) };
}

// Read the toggle state out of a full saved-state blob. Never throws.
function toggleStateFrom(saved) {
  const s = _obj(saved) || {};
  const o = _obj(s.overlay) || {};
  const t = _obj(o.toggle) || {};
  return {
    visible: typeof t.visible === "boolean" ? t.visible : TOGGLE_DEFAULTS.visible,
    pos: sanitizeTogglePos(t.pos),
  };
}

// Merge a toggle patch ({ visible?, pos? }) into overlay.toggle WITHOUT touching
// any sibling overlay key (position / panelSet / settings / widgetLayout) or the
// companion's top-level keys. pos: null clears the saved spot (back to the
// default corner). Garbage fields are dropped. Returns a new object; never
// mutates; garbage prev starts fresh.
function mergeToggleStatePatch(prevState, patch) {
  const prev = _obj(prevState) || {};
  const prevOverlay = _obj(prev.overlay) || {};
  const prevToggle = _obj(prevOverlay.toggle) || {};
  const p = _obj(patch) || {};
  const nextToggle = Object.assign({}, prevToggle);
  if (typeof p.visible === "boolean") {
    nextToggle.visible = p.visible;
  }
  if (p.pos === null) {
    delete nextToggle.pos;
  } else if (p.pos !== undefined) {
    const clean = sanitizeTogglePos(p.pos);
    if (clean) {
      nextToggle.pos = clean;
    }
  }
  return Object.assign({}, prev, {
    overlay: Object.assign({}, prevOverlay, { toggle: nextToggle }),
  });
}

function _distToRect(pt, b) {
  const dx = Math.max(b.x - pt.x, 0, pt.x - (b.x + b.width));
  const dy = Math.max(b.y - pt.y, 0, pt.y - (b.y + b.height));
  return dx * dx + dy * dy;
}

// Which display the icon belongs on: the saved display if it is still
// connected, else the display nearest the saved absolute point, else the
// primary (by id), else the first listed. Always returns a usable display.
function pickDisplay(pos, displays, primaryId) {
  const list = normDisplays(displays);
  if (list.length === 0) {
    return { id: null, bounds: Object.assign({}, FALLBACK_BOUNDS) };
  }
  const p = sanitizeTogglePos(pos);
  if (p && p.displayId !== null) {
    const same = list.find((d) => d.id === p.displayId);
    if (same) {
      return same;
    }
  }
  if (p && p.x !== null && p.y !== null) {
    let best = list[0];
    let bestD = Infinity;
    for (const d of list) {
      const dist = _distToRect({ x: p.x, y: p.y }, d.bounds);
      if (dist < bestD) {
        best = d;
        bestD = dist;
      }
    }
    return best;
  }
  const prim = list.find((d) => d.id !== null && d.id === _num(primaryId));
  return prim || list[0];
}

// Clamp an icon top-left fully inside a display's bounds (integer DIP).
function clampToggleToBounds(pt, size, bounds) {
  const b = _bounds(bounds) || FALLBACK_BOUNDS;
  const s = _num(size) !== null && size > 0 ? size : TOGGLE_DEFAULTS.baseSize;
  const p = _obj(pt) || {};
  const c = cfg.clampPosition(
    { x: _num(p.x) === null ? b.x : p.x, y: _num(p.y) === null ? b.y : p.y, width: s, height: s },
    b
  );
  return { x: c.x, y: c.y };
}

// Where the icon window goes: { x, y, width, height, displayId }. Saved
// fractions are applied to the chosen display (so a resolution change keeps the
// relative spot); no saved spot -> the default corner on the primary display,
// scaled like the HUD. Always fully on-screen.
function resolveToggleBounds(pos, displays, primaryId) {
  const d = pickDisplay(pos, displays, primaryId);
  const b = d.bounds;
  const size = toggleSize(b);
  const p = sanitizeTogglePos(pos);
  let x;
  let y;
  if (p) {
    x = b.x + Math.round(p.fx * Math.max(0, b.width - size));
    y = b.y + Math.round(p.fy * Math.max(0, b.height - size));
  } else {
    const s = ov.resolveOverlayScale(b);
    x = b.x + Math.round(TOGGLE_DEFAULTS.designX * s);
    y = b.y + Math.round(TOGGLE_DEFAULTS.designY * s);
  }
  const c = clampToggleToBounds({ x, y }, size, b);
  return { x: c.x, y: c.y, width: size, height: size, displayId: d.id };
}

// The persistable position for an icon window at top-left win on display
// (an Electron Display or { id, bounds }).
function posFromWindow(win, size, display) {
  const d = _obj(display) || {};
  const b = _bounds(d.bounds) || FALLBACK_BOUNDS;
  const s = _num(size) !== null && size > 0 ? size : TOGGLE_DEFAULTS.baseSize;
  const w = _obj(win) || {};
  const c = clampToggleToBounds({ x: w.x, y: w.y }, s, b);
  const tx = Math.max(1, b.width - s);
  const ty = Math.max(1, b.height - s);
  const r6 = (v) => Math.round(v * 1e6) / 1e6;
  return {
    displayId: _num(d.id),
    fx: r6(Math.min(1, Math.max(0, (c.x - b.x) / tx))),
    fy: r6(Math.min(1, Math.max(0, (c.y - b.y) / ty))),
    x: c.x,
    y: c.y,
  };
}

// Tap-vs-drag state machine for one press. main.js feeds it the cursor's
// screen point (screen.getCursorScreenPoint, DIP) at press and on every move
// tick; it answers the new window top-left once the press has moved past the
// threshold. release() -> "tap" | "drag" | "none"; cancel() never reports a
// tap (a lost pointer must not flip the overlay) but still reports "drag" so a
// moved icon is persisted.
function makeToggleDrag(opts) {
  const o = _obj(opts) || {};
  const t = _num(o.thresholdPx);
  const threshold = t !== null && t >= 0 ? t : TOGGLE_DEFAULTS.dragThresholdPx;
  let st = null;
  function pointOk(p) {
    const q = _obj(p);
    return !!q && _num(q.x) !== null && _num(q.y) !== null;
  }
  return {
    press(cursor, winPos) {
      if (!pointOk(cursor) || !pointOk(winPos)) {
        st = null;
        return false;
      }
      st = { cx: cursor.x, cy: cursor.y, wx: winPos.x, wy: winPos.y, moved: false };
      return true;
    },
    move(cursor) {
      if (!st || !pointOk(cursor)) {
        return null;
      }
      const dx = cursor.x - st.cx;
      const dy = cursor.y - st.cy;
      if (!st.moved && Math.abs(dx) <= threshold && Math.abs(dy) <= threshold) {
        return null;
      }
      st.moved = true;
      return { x: Math.round(st.wx + dx), y: Math.round(st.wy + dy) };
    },
    release() {
      if (!st) {
        return "none";
      }
      const r = st.moved ? "drag" : "tap";
      st = null;
      return r;
    },
    cancel() {
      if (!st) {
        return "none";
      }
      const r = st.moved ? "drag" : "none";
      st = null;
      return r;
    },
    pressed() {
      return st !== null;
    },
  };
}

// Layer the content toggle over the window actions for a surface
// ({ companion, overlay } from overlay_state.windowActions[WithPolicy]):
//   - the icon shows exactly when the in-game surface is up - in BOTH content
//     states, so the operator can always turn the overlay back on; it hides out
//     of a game and under the Alt+Shift+O panic hide (HIDDEN);
//   - the overlay shows only when the surface wants it AND the content is ON
//     (anything but a strict false is ON - the default);
//   - the companion action passes through untouched (keepCompanion survives).
function applyContentToggle(actions, surface, contentOn) {
  const a = _obj(actions) || ov.windowActions(surface);
  return {
    companion: a.companion === "show" ? "show" : "hide",
    overlay: a.overlay === "show" && contentOn !== false ? "show" : "hide",
    toggle: surface === ov.SURFACES.OVERLAY ? "show" : "hide",
  };
}

// Toggle input (an icon tap or the Ctrl+Shift+O signal) only counts while the
// in-game surface is up. Out of a game the chord is just as likely meant for
// another app (VS Code / Chrome bind Ctrl+Shift+O), and acting on it would
// silently flip the persisted choice and start the next match with the HUD off.
function acceptsToggleInput(surface) {
  return surface === ov.SURFACES.OVERLAY;
}

// Validate a toggle-page message: an allow-listed action name or null.
function normToggleAction(raw) {
  const m = _obj(raw);
  if (!m || typeof m.action !== "string") {
    return null;
  }
  const a = m.action.trim().toLowerCase();
  return TOGGLE_ACTIONS.includes(a) ? a : null;
}

module.exports = {
  TOGGLE_DEFAULTS,
  TOGGLE_ACTIONS,
  normDisplays,
  toggleSize,
  sanitizeTogglePos,
  toggleStateFrom,
  mergeToggleStatePatch,
  pickDisplay,
  clampToggleToBounds,
  resolveToggleBounds,
  posFromWindow,
  makeToggleDrag,
  applyContentToggle,
  acceptsToggleInput,
  normToggleAction,
};
