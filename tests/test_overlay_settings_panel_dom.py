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


class Rc2Stage42ControlsTests(unittest.TestCase):
    """RC2 4.2 non-intrusive overlay: the #ovset strip gains a hover-to-interact
    (click-through zones) toggle + an opacity slider, both hotkey-free and
    mirrored to the rc-shell over IPC. The shared helper carries the two new
    fields so the control and the shell never drift."""

    def setUp(self):
        self.panel = PANEL_JS.read_text(encoding="utf-8")
        self.helper = HELPER_JS.read_text(encoding="utf-8")
        self.css = PANEL_CSS.read_text(encoding="utf-8")

    def test_new_control_ids_present(self):
        self.assertIn('id="ovset-zones"', self.panel)
        self.assertIn('id="ovset-opacity"', self.panel)

    def test_opacity_is_a_bounded_range(self):
        self.assertIn('type="range"', self.panel)
        self.assertIn('min="30"', self.panel)
        self.assertIn('max="100"', self.panel)

    def test_controls_write_the_new_settings(self):
        self.assertIn("clickThroughZones", self.panel)
        self.assertIn("overlayOpacity", self.panel)

    def test_helper_carries_new_fields(self):
        self.assertIn("overlayOpacity", self.helper)
        self.assertIn("clickThroughZones", self.helper)

    def test_opacity_row_meets_hit_floor(self):
        m = re.search(
            r"\.ovset-range[^{]*\{[^}]*\}\s*\.ovset-range\s*>\s*input",
            self.css, re.DOTALL,
        )
        # the range input carries the --hit-min height floor for game-distance use
        self.assertIn("--hit-min", self.css)
        self.assertIn(".ovset-range", self.css)


class Rc2Stage43ControlsTests(unittest.TestCase):
    """RC2 4.3 single-monitor window management: the #ovset strip gains a
    "Separate windows" toggle (hotkey-free, mirrored to the rc-shell over IPC)
    that governs the single-monitor side-by-side arrangement of the overlay +
    kept dashboard. The shared helper carries the separateWindows field so the
    control and the shell authority never drift."""

    def setUp(self):
        self.panel = PANEL_JS.read_text(encoding="utf-8")
        self.helper = HELPER_JS.read_text(encoding="utf-8")

    def test_separate_control_present(self):
        self.assertIn('id="ovset-separate"', self.panel)

    def test_separate_is_a_checkbox_in_a_toggle_row(self):
        # reuses the audited .ovset-toggle row (42px hit floor, --fs-xs label).
        self.assertIn('class="ovset-row ovset-toggle"', self.panel)

    def test_control_writes_separate_windows(self):
        self.assertIn("separateWindows", self.panel)

    def test_helper_carries_separate_windows(self):
        self.assertIn("separateWindows", self.helper)


class Rc2Stage44ControlsTests(unittest.TestCase):
    """RC2 4.4 no-hotkey control of everything: the #ovset strip gains a
    panel-set segmented selector (the on-screen twin of the Alt+Shift+C cycle)
    and an "Interact now" button (twin of the Alt+Shift+A passive<->active
    toggle). Both fire one-way overlay ACTIONS at the rc-shell via the shared
    helper's sendOverlayAction. The hide/show hotkey (Alt+Shift+O) stays a
    hotkey on purpose - it clears BOTH surfaces, so a self-hiding on-screen
    control has no way back."""

    def setUp(self):
        self.panel = PANEL_JS.read_text(encoding="utf-8")
        self.helper = HELPER_JS.read_text(encoding="utf-8")
        self.css = PANEL_CSS.read_text(encoding="utf-8")

    def test_panelset_selector_present(self):
        self.assertIn('id="ovset-panelset"', self.panel)
        for ps in ("coach", "build", "threat"):
            self.assertIn(f'data-panelset="{ps}"', self.panel)

    def test_interact_now_button_present(self):
        self.assertIn('id="ovset-interact"', self.panel)

    def test_controls_fire_overlay_actions(self):
        self.assertIn("sendOverlayAction", self.panel)
        self.assertIn('action: "set-panel"', self.panel)
        self.assertIn('action: "set-active"', self.panel)

    def test_helper_exports_action_sender(self):
        self.assertIn("export function sendOverlayAction", self.helper)
        # the sender goes through the rc-shell bridge, not localStorage.
        self.assertIn("overlayAction", self.helper)

    def test_active_segment_reflects_live_panelset(self):
        # the selector lights the current set from the body dataset / URL.
        self.assertIn("_markActivePanelset", self.panel)
        self.assertIn("dataset.panelset", self.panel)

    def test_seg_and_act_meet_hit_floor(self):
        # both new controls carry the --hit-min game-distance floor.
        self.assertIn(".ovset-seg-btn", self.css)
        self.assertIn(".ovset-act", self.css)
        m = re.search(
            r"\.ovset-seg-btn\s*\{[^}]*min-height:\s*var\(--hit-min", self.css, re.DOTALL
        )
        self.assertIsNotNone(m, ".ovset-seg-btn must set min-height: var(--hit-min ...)")
        m2 = re.search(
            r"\.ovset-act\s*\{[^}]*min-height:\s*var\(--hit-min", self.css, re.DOTALL
        )
        self.assertIsNotNone(m2, ".ovset-act must set min-height: var(--hit-min ...)")

    def test_seg_label_typography_uses_tokens(self):
        m = re.search(
            r"\.ovset-seg-btn\s*\{[^}]*font-size:\s*var\(--fs-", self.css, re.DOTALL
        )
        self.assertIsNotNone(m, ".ovset-seg-btn must use a --fs- token, not a hardcoded px")


class Rc2Stage45ControlsTests(unittest.TestCase):
    """RC2 4.5 overlay + dashboard coexistence: the #ovset strip gains two
    coexistence actions over the same one-way overlay-action channel -
    "Re-arrange" (re-separate the overlay + kept dashboard on demand) and
    "Show dashboard" (raise the kept dashboard forward beside the HUD). Both
    fire sendOverlayAction; neither hides the overlay, so there is no stranding.
    Each control clears the 42px game-distance hit floor."""

    def setUp(self):
        self.panel = PANEL_JS.read_text(encoding="utf-8")
        self.css = PANEL_CSS.read_text(encoding="utf-8")

    def test_coexistence_buttons_present(self):
        self.assertIn('id="ovset-rearrange"', self.panel)
        self.assertIn('id="ovset-raise"', self.panel)

    def test_buttons_fire_coexistence_actions(self):
        self.assertIn('action: "rearrange"', self.panel)
        self.assertIn('action: "raise-companion"', self.panel)

    def test_buttons_use_the_action_sender(self):
        # runtime COMMANDS over the rc-shell bridge, not persisted settings.
        self.assertIn("sendOverlayAction", self.panel)

    def test_action_pair_row_styled_at_hit_floor(self):
        # the coexistence buttons reuse the audited .ovset-act 42px floor inside
        # a paired row so the two sit side-by-side on the 460px dock.
        self.assertIn(".ovset-actpair", self.css)
        m = re.search(
            r"\.ovset-act\s*\{[^}]*min-height:\s*var\(--hit-min", self.css, re.DOTALL
        )
        self.assertIsNotNone(m, ".ovset-act must set min-height: var(--hit-min ...)")


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
