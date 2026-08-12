"""OQ16 (OQ3 variant A): peripheral objective gauge cluster on the overlay.

The operator picked OQ3 variant A (web/mock/oq3_variant_a.html - "Radial
Ring Cluster"): a 2x2 grid of full ring dials (DRAKE / BARON / ELDER /
SUMMS) with the exact ETA in each ring center and the ring arc filling
toward ready. This slice ships it as a LIVE overlay widget:

  - web/js/panels/objective_gauges.js  - pure ESM render module
    (idiom mirror of web/js/panels/objective_chips.js: self-gates on
    body[data-shell="overlay"], sig-dedup, defensive inputs).
  - web/css/panels/objective_gauges.css (+ @import in web/css/dashboard.css).
  - web/index.html mount #am-obj-gauges as a direct am-grid child.
  - web/js/lib/overlay_layout.js WIDGETS registry entry w-objgauges.
  - web/js/main.js threads {mode, liveclient, cooldowns} at BOTH active-match
    dispatch sites (ui_mock + live), beside renderObjectiveChips
    (main.js:1411 / main.js:1475 pre-slice anchors).

Data contract (grep-verified producers):
  - liveclient.game_time_s + liveclient.objective_events:
    dashboard/_liveclient.py:97 + :265-301.
  - summoner_cooldowns rows: dashboard/_state_cooldowns.py ->
    core/summoner_cooldowns.compute_cooldowns rows (:317-324; summs
    d_/f_cd_remaining_s per :219-225, ult cd_remaining_s per :242-247).
  - Objective schedule literals MIRROR core/event_callouts.py; the
    ScheduleMirrorTests below pin the JS copies against the Python
    constants so drift fails CI (never fabricate a timer beyond the
    canonical schedule + game_time arithmetic).

Grep-based string assertions mirror tests/test_ban_reason_labels_oq9.py.
Rendered-Chromium coverage lives in
tests/snapshot_panels/test_objective_gauges_view.py.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import core.event_callouts as ec

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = ROOT / "web" / "js" / "panels" / "objective_gauges.js"
PANEL_MJS = ROOT / "web" / "js" / "panels" / "objective_gauges.test.mjs"
PANEL_CSS = ROOT / "web" / "css" / "panels" / "objective_gauges.css"
DASH_CSS = ROOT / "web" / "css" / "dashboard.css"
MAIN_JS = ROOT / "web" / "js" / "main.js"
INDEX_HTML = ROOT / "web" / "index.html"
LAYOUT_JS = ROOT / "web" / "js" / "lib" / "overlay_layout.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ModuleExistsTests(unittest.TestCase):
    """The panel module ships with the objective_chips.js discipline."""

    def test_panel_js_exists(self):
        self.assertTrue(PANEL_JS.is_file(), f"{PANEL_JS} missing")

    def test_exports_render_and_test_hooks(self):
        js = _read(PANEL_JS)
        self.assertIn("export function renderObjectiveGauges", js)
        self.assertIn("export const __test", js)

    def test_self_gates_on_overlay_shell(self):
        js = _read(PANEL_JS)
        self.assertIn('dataset.shell !== "overlay"', js)

    def test_sig_dedup_present(self):
        # Idempotent-render discipline (objective_chips.js:98-127 idiom).
        js = _read(PANEL_JS)
        self.assertIn("_sig", js)


class ScheduleMirrorTests(unittest.TestCase):
    """JS schedule literals == core/event_callouts.py canonical constants."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(PANEL_JS)

    def _js_num(self, key: str) -> int:
        m = re.search(rf"{key}:\s*(\d+)", self.js)
        self.assertIsNotNone(m, f"OG_SCHED.{key} literal missing")
        return int(m.group(1))

    def test_drake_first(self):
        self.assertEqual(self._js_num("drakeFirstS"),
                         int(ec.SR_DRAGON_FIRST_S))

    def test_drake_respawn(self):
        self.assertEqual(self._js_num("drakeRespawnS"),
                         int(ec.SR_DRAGON_RESPAWN_S))

    def test_baron_first(self):
        self.assertEqual(self._js_num("baronFirstS"),
                         int(ec.SR_BARON_FIRST_S))

    def test_baron_respawn(self):
        self.assertEqual(self._js_num("baronRespawnS"),
                         int(ec.SR_BARON_RESPAWN_S))

    def test_elder_nominal(self):
        self.assertEqual(self._js_num("elderNominalS"),
                         int(ec._SR_ELDER_NOMINAL_S))

    def test_active_window(self):
        self.assertEqual(self._js_num("activeWindowS"),
                         int(ec._OBJ_ACTIVE_WINDOW_S))

    def test_soul_secured_stacks(self):
        self.assertEqual(self._js_num("soulSecuredStacks"),
                         int(ec._SOUL_SECURED_STACKS))


class SrOnlyGateTests(unittest.TestCase):
    """HONEST NO-DATA: SR-only, whole-widget hide, '-' single-dial sentinel."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(PANEL_JS)

    def test_sr_gate_literal(self):
        self.assertIn('!== "sr"', self.js)

    def test_dash_sentinel(self):
        # The approved "-" no-data glyph for a single dial mid-game.
        self.assertIn('"none"', self.js)
        self.assertIn('"-"', self.js)

    def test_hides_whole_widget_when_no_data(self):
        self.assertIn("mount.hidden = true", self.js)


class WiringTests(unittest.TestCase):
    """main.js dispatch + index.html mount + overlay_layout registry."""

    def test_main_js_import(self):
        self.assertIn(
            "import { renderObjectiveGauges } from"
            " './panels/objective_gauges.js';",
            _read(MAIN_JS))

    def test_main_js_dispatches_both_branches(self):
        # ui_mock branch AND live branch (mirror of renderObjectiveChips at
        # both sites). The summoner_cooldowns thread was dropped 2026-08-11
        # (Riot compliance - the cooldown ledger is gone).
        js = _read(MAIN_JS)
        self.assertEqual(js.count("renderObjectiveGauges({"), 2)
        live = js[js.rindex("renderObjectiveGauges({"):]
        live = live[:live.index(");")]
        self.assertIn("state.latest.liveclient", live)
        self.assertIn("state.mode", live)

    def test_index_html_mount_is_am_grid_child(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="am-obj-gauges"', html)
        # Direct am-grid child (like #am-ward-cue / #am-statspanel), NOT
        # inside a transformed pane, so position:fixed stays viewport-true.
        m = re.search(
            r'<div class="obj-gauges" id="am-obj-gauges" hidden></div>', html)
        self.assertIsNotNone(m, "mount div missing or not data-gated hidden")
        pane_idx = html.index('<div class="am-pane am-pane-call">')
        self.assertLess(m.start(), pane_idx,
                        "mount must sit before the panes (am-grid child)")

    def test_overlay_layout_registry_entry(self):
        js = _read(LAYOUT_JS)
        self.assertIn('id: "w-objgauges"', js)
        self.assertIn('sel: "#am-obj-gauges"', js)


class CssTests(unittest.TestCase):
    """Doctrine hues + bundle parity + typography tokens."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(PANEL_CSS)

    def test_dashboard_css_imports_bundle(self):
        self.assertIn("@import './panels/objective_gauges.css';",
                      _read(DASH_CSS))

    def test_dashboard_surface_hidden(self):
        # Overlay-only: base rule hides the widget on the 1920 dashboard.
        idx = self.css.index(".obj-gauges {")
        rule = self.css[idx:self.css.index("}", idx)]
        self.assertIn("display: none", rule)

    def test_doctrine_hues(self):
        # Operator OQ3/OQ16 directive over doctrine sec 5: BARON gold,
        # ELDER red, SUMMS cyan ride the ovx tokens; DRAKE warn #E8A33D is
        # the one literal (no ovx token exists for it - documented inline).
        self.assertIn("var(--ovx-gold", self.css)
        self.assertIn("var(--ovx-red", self.css)
        self.assertIn("var(--ovx-cyan", self.css)
        self.assertIn("#E8A33D", self.css)
        self.assertIn("OQ16", self.css)

    def test_label_uses_overlay_chip_token(self):
        # Game-distance sub-floor token (13px), same operator-accepted
        # exception as objective_chips.css:32.
        idx = self.css.index(".og-label")
        rule = self.css[idx:self.css.index("}", idx)]
        self.assertIn("var(--fs-ov-chip)", rule)

    def test_eta_tabular_nums(self):
        idx = self.css.index(".og-eta")
        rule = self.css[idx:self.css.index("}", idx)]
        self.assertIn("tabular-nums", rule)


class AsciiHygieneTests(unittest.TestCase):
    """Everything OQ16 AUTHORED stays 7-bit ASCII.

    The new files must be byte-clean. The edited files (main.js /
    index.html / dashboard.css) carry pre-existing legacy non-ASCII
    (box-drawing section separators etc. - repo hygiene suites own those),
    so for them we assert only the OQ16-added regions are clean.
    """

    def test_new_files_ascii(self):
        for p in (PANEL_JS, PANEL_MJS, PANEL_CSS, Path(__file__),
                  ROOT / "tests" / "snapshot_panels"
                       / "test_objective_gauges_view.py"):
            raw = p.read_bytes()
            bad = [b for b in raw if b > 0x7F]
            self.assertFalse(
                bad, f"{p.name} carries {len(bad)} bytes > 0x7F")

    def test_added_regions_ascii(self):
        # Every OQ16 anchor region in the edited files is pure ASCII.
        for path, anchor, span in (
            (MAIN_JS, "renderObjectiveGauges", 500),
            (INDEX_HTML, 'id="am-obj-gauges"', 700),
            (LAYOUT_JS, '"w-objgauges"', 500),
            (DASH_CSS, "objective_gauges.css", 60),
        ):
            text = _read(path)
            idx = 0
            while True:
                idx = text.find(anchor, idx)
                if idx < 0:
                    break
                region = text[max(0, idx - span):idx + span]
                self.assertTrue(
                    region.isascii(),
                    f"non-ASCII near {anchor!r} in {path.name}")
                idx += len(anchor)


if __name__ == "__main__":
    unittest.main()
