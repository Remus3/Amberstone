"""Tests for web/js/lib/overlay_settings.js - RC2 Phase 3.4 dashboard-persist.

The shared overlay-settings helper is the renderer-side mirror of the rc-shell
overlay settings (docs/RC2_PLAN.md stage 3.4 / E1). E1 wired keepCompanion +
companionAlwaysOnTop through the pure shell state machine + the ipcMain bridge
(default ON = the "dashboard disappears in a game" fix), but the WEB helper that
the ?overlay=1 settings strip writes through only carried pulseNotify +
activeRevertSec - so a keepCompanion / companionAlwaysOnTop toggle from the
dashboard UI was silently dropped before it could reach the shell over IPC.

This characterization suite drives node to import the ESM helper (with a
localStorage + window shim, no rc-shell bridge) and pins that both booleans live
in the defaults, read back true by default, and round-trip a write without
clobbering the sibling settings. Acceptance: the operator can keep the dashboard
in the background + pin it on top WITHOUT a hotkey (3.4 + the operator north star
"every setting changeable without hotkeys").

Skips cleanly when node is unavailable so it never hard-fails CI on a runner
without a JS toolchain (the helper ships as static JS).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = REPO_ROOT / "web" / "js" / "lib" / "overlay_settings.js"
NODE = shutil.which("node")

# An ESM harness: shim a Map-backed localStorage + a bridge-less window, import
# the helper by file URL, run the assertions, print OK. Any failed assert exits
# non-zero and surfaces as a test failure with the node stderr.
_HARNESS = """
import assert from "node:assert";
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
};
globalThis.window = {};  // no rcShell bridge -> localStorage-only path
const mod = await import(%(url)s);
const { OVERLAY_SETTINGS_DEFAULTS, readOverlaySettings, writeOverlaySettings } = mod;

// (1) both booleans live in the defaults, both ON (the disappear-bug fix).
assert.strictEqual(OVERLAY_SETTINGS_DEFAULTS.keepCompanion, true, "default keepCompanion");
assert.strictEqual(OVERLAY_SETTINGS_DEFAULTS.companionAlwaysOnTop, true, "default companionAlwaysOnTop");

// (2) a fresh read (empty mirror) returns the defaults.
let s = readOverlaySettings();
assert.strictEqual(s.keepCompanion, true, "read default keepCompanion");
assert.strictEqual(s.companionAlwaysOnTop, true, "read default companionAlwaysOnTop");

// (3) keepCompanion=false round-trips through write -> read.
let r = writeOverlaySettings({ keepCompanion: false });
assert.strictEqual(r.keepCompanion, false, "write returns keepCompanion false");
assert.strictEqual(readOverlaySettings().keepCompanion, false, "keepCompanion persisted");

// (4) companionAlwaysOnTop=false round-trips and does NOT clobber keepCompanion.
r = writeOverlaySettings({ companionAlwaysOnTop: false });
assert.strictEqual(r.companionAlwaysOnTop, false, "write returns companionAlwaysOnTop false");
assert.strictEqual(readOverlaySettings().keepCompanion, false, "sibling keepCompanion preserved");

// (5) a sibling pulseNotify write does NOT clobber the two new booleans.
r = writeOverlaySettings({ pulseNotify: false });
assert.strictEqual(r.pulseNotify, false, "pulseNotify still writable");
assert.strictEqual(readOverlaySettings().companionAlwaysOnTop, false, "companionAlwaysOnTop preserved");

// (6) garbage in the mirror coerces back to the safe default (true).
store.set("rc_overlay_settings", JSON.stringify({ keepCompanion: "nope", companionAlwaysOnTop: 0 }));
s = readOverlaySettings();
assert.strictEqual(s.keepCompanion, true, "garbage keepCompanion -> true");
assert.strictEqual(s.companionAlwaysOnTop, true, "garbage companionAlwaysOnTop -> true");

// (7) RC2 4.3 separateWindows: default ON, round-trips false, sibling-safe,
// garbage -> default true (mirrors the rc-shell overlay_state authority).
store.clear();
assert.strictEqual(OVERLAY_SETTINGS_DEFAULTS.separateWindows, true, "default separateWindows");
assert.strictEqual(readOverlaySettings().separateWindows, true, "read default separateWindows");
r = writeOverlaySettings({ separateWindows: false });
assert.strictEqual(r.separateWindows, false, "write returns separateWindows false");
assert.strictEqual(readOverlaySettings().separateWindows, false, "separateWindows persisted");
assert.strictEqual(readOverlaySettings().keepCompanion, true, "sibling keepCompanion preserved");
store.set("rc_overlay_settings", JSON.stringify({ separateWindows: "yes" }));
assert.strictEqual(readOverlaySettings().separateWindows, true, "garbage separateWindows -> true");

console.log("OK");
"""


@unittest.skipUnless(NODE, "node not on PATH - JS helper is static, skip")
class OverlaySettingsRc2Test(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(SETTINGS_JS.is_file(), f"missing {SETTINGS_JS}")

    def test_keep_companion_and_pin_round_trip(self):
        url = json.dumps(SETTINGS_JS.as_uri())
        program = _HARNESS % {"url": url}
        proc = subprocess.run(
            [NODE, "--input-type=module", "-e", program],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"node exited {proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}",
        )
        self.assertIn("OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
