"""DOM-contract tests for the in-overlay DS fight-model controls pane.

HZ-D1 Phase 4 (docs/ELECTRON_OVERLAY.md): an overlay-only pane inside the
active-match grid that lets the operator tweak the DS fight model (enemy
armor / enemy MR / gold cap / fight length) mid-match and watch the build
re-rank live via the existing /api/ds-knobs backend (item 219C - zero
backend changes in this slice).

Cheap grep-style smoke mirroring test_coach_choices_panel_dom.py: no JSDOM,
just contract pins on the mount block, the renderer module, the CSS gating
chain (default-off everywhere, overlay shell re-enables, coach/threat
panelsets narrow it back off) and the main.js dispatch wiring.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "web" / "index.html"
PANEL_JS = REPO / "web" / "js" / "panels" / "overlay_ds_controls.js"
PANEL_CSS = REPO / "web" / "css" / "panels" / "overlay_ds_controls.css"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"
DASHBOARD_CSS = REPO / "web" / "css" / "dashboard.css"
MAIN_JS = REPO / "web" / "js" / "main.js"


class MountTests(unittest.TestCase):
    """The pane mounts inside .am-grid immediately after the BUILD pane so
    the overlay dock stacks CALL -> BUILD -> FIGHT MODEL top-down."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_mount_div_present(self):
        self.assertIn('id="am-pane-ovds"', self.html)

    def test_mount_hidden_by_default(self):
        self.assertRegex(
            self.html, r'<div class="am-pane am-pane-ovds" id="am-pane-ovds" hidden>')

    def test_mount_lives_inside_active_match_section(self):
        section = re.search(
            r'<section id="view-active-match"(.*?)</section>',
            self.html, re.DOTALL,
        )
        self.assertIsNotNone(section)
        self.assertIn('id="am-pane-ovds"', section.group(1))

    def test_mount_after_build_pane_before_map_pane(self):
        build = self.html.index('class="am-pane am-pane-build"')
        ovds = self.html.index('id="am-pane-ovds"')
        map_pane = self.html.index('class="am-pane am-pane-map"')
        self.assertLess(build, ovds)
        self.assertLess(ovds, map_pane)

    def test_mount_contains_body_and_head(self):
        self.assertIn('id="ovds-body"', self.html)
        self.assertIn('<div class="am-pane-head">FIGHT MODEL</div>', self.html)


class PanelJsTests(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_exports(self):
        self.assertIn("export function renderOverlayDsControls", self.js)
        self.assertIn("export function _resetOverlayDsControls", self.js)
        self.assertIn("export const __test", self.js)

    def test_knob_and_rows_mount_ids(self):
        for kid in ("ovds-armor", "ovds-mr", "ovds-budget", "ovds-flen"):
            self.assertIn(f'id="{kid}"', self.js)
        self.assertIn('id="ovds-rows"', self.js)

    def test_imports_shared_knob_cache_helpers_only(self):
        # fetchDsKnobs/getCachedDsKnobs are pure keyed-cache helpers, safe
        # to share with the champ-select panel. renderDsKnobs carries
        # singleton wiring state and must NOT be imported here.
        self.assertIn("fetchDsKnobs", self.js)
        self.assertIn("getCachedDsKnobs", self.js)
        self.assertIn("./ds_knobs.js", self.js)
        self.assertNotIn("renderDsKnobs", self.js)

    def test_overlay_shell_gate(self):
        # Pane is overlay-only: the renderer bails (and hides) unless
        # main.js stamped body[data-shell="overlay"].
        self.assertIn('dataset.shell !== "overlay"', self.js)

    def test_canonicalization_recipe(self):
        # liveclient championName is a DISPLAY name ("Tahm Kench"); the
        # /api/ds-knobs champion param needs the canonical DDragon slug
        # ("TahmKench") - same normalization as active_match.js
        # _SPK_NAME_TO_KEY.
        self.assertIn("replace(/[^a-z0-9]/g", self.js)
        self.assertIn("CHAMPS", self.js)

    def test_items_resolved_to_ids(self):
        # The live coach payload carries item NAMES ("Mortal Reminder");
        # /api/ds-knobs only accepts item IDS (names 503 the route -
        # probed live 2026-06-10). The panel must bridge via the shared
        # items_index resolver, passing numeric ids through untouched and
        # dropping unresolved names.
        self.assertIn("_resolveItemId", self.js)
        self.assertIn(r"/^\d+$/", self.js)

    def test_mode_map(self):
        for pair in ('sr: "SR"', 'classic: "SR"', 'aram: "ARAM"',
                     'arena: "ARENA"', 'cherry: "ARENA"', 'brawl: "BRAWL"'):
            self.assertIn(pair, self.js)

    def test_friendly_degraded_copy(self):
        # Repo Error Handling rule: never a raw error string in a
        # user-facing panel.
        self.assertIn("no items rank under this fight model", self.js)
        self.assertIn("resolving fight model...", self.js)

    def test_debounce_and_sig_dedup(self):
        # Knob edits debounce ~350ms; repaints dedup on a knobs+rows
        # signature so the 1Hz state tick does not thrash the DOM.
        self.assertIn("350", self.js)
        self.assertIn("_signature", self.js)

    def test_wire_once_per_champion_guard(self):
        self.assertIn("data-ovds-champ", self.js)


class CssTests(unittest.TestCase):
    def setUp(self):
        self.css = PANEL_CSS.read_text(encoding="utf-8")
        self.dash = DASHBOARD_CSS.read_text(encoding="utf-8")
        self.ov = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_base_default_display_none(self):
        # Hard default off on every non-overlay surface; only the overlay
        # shell rule below re-enables it. The selector MUST out-rank
        # active_match.css "#view-active-match .am-pane { display: flex }"
        # ((0,1,1,0)) - a bare "#am-pane-ovds" ((0,1,0,0)) loses the
        # cascade and a blank FIGHT MODEL pane leaks onto the normal 1920
        # dashboard (2026-06-10 UI-audit MUST-FIX 1). Two ids = (0,2,0,0).
        self.assertRegex(
            self.css,
            r"#view-active-match\s+#am-pane-ovds\s*\{[^}]*display:\s*none",
        )

    def test_inputs_meet_hit_target_floor(self):
        self.assertIn("min-height: var(--hit-min", self.css)

    def test_dashboard_imports_panel(self):
        self.assertIn("./panels/overlay_ds_controls.css", self.dash)

    def test_overlay_unhide_rule(self):
        self.assertIn(
            'body[data-shell="overlay"] #am-pane-ovds:not([hidden])', self.ov)
        m = re.search(
            r'#am-pane-ovds:not\(\[hidden\]\)\s*\{([^}]*)\}', self.ov)
        self.assertIsNotNone(m)
        self.assertIn("display: block !important", m.group(1))

    def test_overlay_coach_and_threat_panelsets_exclude_pane(self):
        self.assertIn(
            'body[data-shell="overlay"][data-panelset="coach"] #am-pane-ovds',
            self.ov)
        self.assertIn(
            'body[data-shell="overlay"][data-panelset="threat"] #am-pane-ovds',
            self.ov)
        m = re.search(
            r'\[data-panelset="threat"\] #am-pane-ovds\s*\{([^}]*)\}', self.ov)
        self.assertIsNotNone(m)
        self.assertIn("display: none !important", m.group(1))

    def test_overlay_gate_order(self):
        # The unhide rule and the panelset gates tie on specificity
        # (1 id + 2 attrs each), so source order is load-bearing: the
        # narrowing gates MUST come after the unhide rule to win.
        unhide = self.ov.index("#am-pane-ovds:not([hidden])")
        coach = self.ov.index('[data-panelset="coach"] #am-pane-ovds')
        self.assertLess(unhide, coach)


class MainJsWireTests(unittest.TestCase):
    def setUp(self):
        self.js = MAIN_JS.read_text(encoding="utf-8")

    def test_imports_renderer(self):
        self.assertIn("renderOverlayDsControls", self.js)
        self.assertIn("./panels/overlay_ds_controls.js", self.js)

    def test_calls_renderer_at_both_dispatch_sites(self):
        # The import line carries no paren, so this counts call sites
        # only: the onState ui_mock branch + the live branch at minimum.
        calls = self.js.count("renderOverlayDsControls(")
        self.assertGreaterEqual(calls, 2)


class AsciiTests(unittest.TestCase):
    """Repo hard rule: authored bytes stay 7-bit ASCII (no em/en dashes,
    no smart quotes). Byte-level check on the NEW slice files; the edited
    files carry pre-existing non-ASCII (e.g. the middot in #am-sub) so
    they are pinned by selector/content asserts above instead."""

    def _assert_ascii(self, path: Path):
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad[:5], [], f"non-ASCII bytes in {path.name}")

    def test_panel_js_ascii(self):
        self._assert_ascii(PANEL_JS)

    def test_panel_css_ascii(self):
        self._assert_ascii(PANEL_CSS)

    def test_this_test_file_ascii(self):
        self._assert_ascii(Path(__file__).resolve())


if __name__ == "__main__":
    unittest.main()
