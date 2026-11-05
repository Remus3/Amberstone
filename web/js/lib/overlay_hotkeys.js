// web/js/lib/overlay_hotkeys.js
//
// RC-HOTKEY-HINTS (MAIN ORDER 2215 item 10, docs/OVERLAY_DOCTRINE.md section 11):
// the binding each interactive widget's reminder shows.
//
// The authority is the rc-shell, not this file: overlay_state.overlayHotkeyMap
// answers window.rcShell.getOverlayHotkeys, and hydrateOverlayHotkeys() pulls it
// once at field init. HOTKEY_DEFAULTS is the fallback for a plain browser or an
// older shell binary with no such channel, pinned equal to the authority by
// tests/snapshot_panels/test_overlay_hotkey_hints.py. No binding is rebindable
// today (they are constants in rc-shell and in tools/hotkey_listener.py); the hint
// reads a map, so a later rebind reaches it with no change here.

export const HOTKEY_DEFAULTS = Object.freeze({
  active: "Ctrl+Shift+A",
  visible: "Ctrl+Shift+O",
  hide: "Alt+Shift+O",
  reset: "Alt+Shift+R",
});

// The menu's reference rows, in reading order. Win32-listener keys deliver while
// the game holds focus; the Alt+Shift pair is Electron globalShortcut, which does
// not (docs/ELECTRON_OVERLAY.md section 5), so those say so. The panel-cycle key
// (Ctrl+Shift+B, Alt+Shift+C) is left out on purpose: the panel sets no longer
// gate any widget, so all it does is reload the overlay window. Telling an operator
// to press it would cost a visible reload for nothing.
export const HOTKEY_REFERENCE = Object.freeze([
  ["active", "interact"],
  ["visible", "overlay on/off"],
  ["hide", "hide all (out of game)"],
  ["reset", "reset layout (out of game)"],
]);

// Which binding each interactive field widget reminds of. Every one of these
// accepts input beyond its drag handle, and in PASSIVE the window is click-through
// until the ACTIVE flip, so that is the key an operator needs. The display-only
// widgets carry no reminder (rule 8). The per-chip Alt+1/2/3 pick keys on w-choices
// live in panels/coach_choices.js.
export const WIDGET_HOTKEYS = Object.freeze({
  "w-launcher": "active",
  "w-choices": "active",
  "w-build": "active",
  "w-ovds": "active",
});

// A binding the shell may hand back: printable ASCII, the accelerator shape, short.
const _BINDING = /^[A-Za-z0-9]+(\+[A-Za-z0-9]+)*$/;

let _live = { ...HOTKEY_DEFAULTS };

/** The live binding for an action, "" when the action is not one. */
export function hotkeyFor(action) {
  return Object.prototype.hasOwnProperty.call(_live, action) ? _live[action] : "";
}

/** The widget's action key, "" for a widget with no reminder. */
export function hotkeyActionFor(widget) {
  const w = widget && typeof widget === "object" ? widget : {};
  const action = typeof w.hotkey === "string" ? w.hotkey : WIDGET_HOTKEYS[w.id];
  return action && hotkeyFor(action) ? action : "";
}

/**
 * Pull the shell's live bindings into the map. Keeps the last good value for a
 * missing or malformed key, so a partial reply can never blank a hint.
 *
 * @returns {Promise<boolean>} true when the shell answered with a usable map.
 */
export function hydrateOverlayHotkeys() {
  try {
    const shell = typeof window !== "undefined" ? window.rcShell : null;
    if (!shell || typeof shell.getOverlayHotkeys !== "function") return Promise.resolve(false);
    return Promise.resolve(shell.getOverlayHotkeys())
      .then((map) => {
        if (!map || typeof map !== "object" || Array.isArray(map)) return false;
        let took = false;
        for (const key of Object.keys(HOTKEY_DEFAULTS)) {
          const v = map[key];
          if (typeof v === "string" && v.length <= 32 && _BINDING.test(v)) {
            _live[key] = v;
            took = true;
          }
        }
        return took;
      })
      .catch(() => false);
  } catch (_e) {
    return Promise.resolve(false); // locked-down bridge: the fallback map stands.
  }
}

export const _internals = {
  _resetForTest: () => {
    _live = { ...HOTKEY_DEFAULTS };
  },
};
