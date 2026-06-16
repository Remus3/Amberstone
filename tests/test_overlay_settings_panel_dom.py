"""DOM/contract tests for the OVL1 overlay-settings controls.

OVL1 (docs/ELECTRON_OVERLAY.md Phase 4): the ?overlay=1 surface gains two
operator settings - a change-pulse toggle and the ACTIVE auto-revert delay
(seconds) - mounted in the in-overlay controls pane
(web/js/panels/overlay_ds_controls.js). They persist in-page via a shared
helper (web/js/lib/overlay_settings.js, localStorage) and mirror to the
rc-shell Electron config over IPC (window.rcShell) when running inside the
shell. The pulse toggle gates web/js/overlay_pulse.js; the revert seconds
drive the rc-shell main-process auto-revert (rc-shell/src/main.js). The live
IPC round-trip + the in-game visual are OWED.

Grep-style, mirroring tests/test_overlay_ds_controls_panel_dom.py: pathlib
reads + substring/regex asserts only, no DOM emulation.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL_JS = REPO / "web" / "js" / "panels" / "overlay_ds_controls.js"
PANEL_CSS = REPO / "web" / "css" / "panels" / "overlay_ds_controls.css"
HELPER_JS = REPO / "web" / "js" / "lib" / "overlay_settings.js"
PULSE_JS = REPO / "web" / "js" / "overlay_pulse.js"


class HelperTests(unittest.TestCase):
    """The shared helper is the single source of the in-page settings shape
    so the controls and the pulse gate never drift."""

    def setUp(self):
        self.assertTrue(HELPER_JS.is_file(), "web/js/lib/overlay_settings.js missing")
        self.js = HELPER_JS.read_text(encoding="utf-8")

    def test_exports(self):
        self.assertIn("export function readOverlaySettings", self.js)
        self.assertIn("export function writeOverlaySettings", self.js)
        self.assertIn("export function hydrateOverlaySettings", self.js)

    def test_localstorage_key_and_fields(self):
        self.assertIn("rc_overlay_settings", self.js)
        self.assertIn("pulseNotify", self.js)
        self.assertIn("activeRevertSec", self.js)

    def test_clamp_range_matches_shell(self):
        # mirror rc-shell overlaySettingsFrom clamp [3,120].
        self.assertIn("120", self.js)
        self.assertIn("3", self.js)

    def test_mirrors_to_rcshell_bridge_when_present(self):
        self.assertIn("window.rcShell", self.js)
        self.assertIn("setOverlaySettings", self.js)
        self.assertIn("getOverlaySettings", self.js)


class PanelControlsTests(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_control_ids_present(self):
        self.assertIn('id="ovset-pulse"', self.js)
        self.assertIn('id="ovset-revert"', self.js)

    def test_pulse_is_a_checkbox(self):
        self.assertIn('type="checkbox"', self.js)

    def test_revert_is_a_bounded_number_input(self):
        self.assertIn('min="3"', self.js)
        self.assertIn('max="120"', self.js)

    def test_uses_the_shared_helper(self):
        self.assertIn("./lib/overlay_settings.js", self.js)
        self.assertIn("writeOverlaySettings", self.js)
        self.assertIn("readOverlaySettings", self.js)
        self.assertIn("hydrateOverlaySettings", self.js)

    def test_settings_strip_mounts_independently_of_the_knob_strip(self):
        # The settings strip mounts once (data-ovds-init) into its own wrap so
        # the per-champion knob-strip rebuild (data-ovds-champ) cannot wipe it,
        # and it shows even before a champion resolves.
        self.assertIn("data-ovds-init", self.js)
        self.assertIn("ovds-knobwrap", self.js)

    def test_existing_knob_contract_intact(self):
        # OVL1 must not regress the HZ-D1 fight-model controls.
        for kid in ("ovds-armor", "ovds-mr", "ovds-budget", "ovds-flen"):
            self.assertIn(f'id="{kid}"', self.js)
        self.assertIn('id="ovds-rows"', self.js)
        self.assertIn("data-ovds-champ", self.js)


class PulseGateTests(unittest.TestCase):
    """The pulse toggle must actually gate the change-pulse hook."""

    def setUp(self):
        self.js = PULSE_JS.read_text(encoding="utf-8")

    def test_pulse_imports_shared_helper(self):
        self.assertIn("./lib/overlay_settings.js", self.js)
        self.assertIn("readOverlaySettings", self.js)

    def test_pulse_checks_pulseNotify(self):
        self.assertIn("pulseNotify", self.js)


class CssTests(unittest.TestCase):
    def setUp(self):
        self.css = PANEL_CSS.read_text(encoding="utf-8")

    def test_settings_strip_styled(self):
        self.assertIn(".ovset", self.css)

    def test_settings_inputs_meet_hit_target_floor(self):
        # The number input + the checkbox row carry the --hit-min floor so the
        # UI-audit HIT-TARGETS phase passes on the overlay dock.
        m = re.search(r"\.ovset[^{]*\{[^}]*min-height:\s*var\(--hit-min", self.css, re.DOTALL)
        self.assertIsNotNone(m, ".ovset controls must set min-height: var(--hit-min ...)")

    def test_settings_label_typography_uses_tokens(self):
        m = re.search(r"\.ovset[^{]*\{[^}]*font-size:\s*var\(--fs-", self.css, re.DOTALL)
        self.assertIsNotNone(m, ".ovset labels must use a --fs- token, not a hardcoded px")


class AsciiTests(unittest.TestCase):
    """Repo hard rule: authored bytes stay 7-bit ASCII (no em/en dashes, no
    smart quotes). Byte-level on the NEW slice files."""

    def _assert_ascii(self, path: Path):
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad[:5], [], f"non-ASCII bytes in {path.name}")

    def test_helper_js_ascii(self):
        self._assert_ascii(HELPER_JS)

    def test_this_test_file_ascii(self):
        self._assert_ascii(Path(__file__).resolve())


if __name__ == "__main__":
    unittest.main()
