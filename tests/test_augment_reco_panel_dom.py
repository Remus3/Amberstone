"""Regression guards for the CLAUDE #88 augment-recommender foregrounding.

The data-driven Arena/Mayhem augment recommender (core/augment_recommender.py
+ core/augment_external_source.py, wired through coaches/arena_coach.py) is
already heavily covered by its own backend suites. What was *not* covered -
and is the whole point of this session - is the four-file wiring that
foregrounds the ranking as a prominent in-game block instead of an
invisible #augments-pill hover tooltip:

  - web/index.html declares #ib-aug-reco-block + its sub-elements inside
    the #item-build panel
  - web/js/panels/augment_reco.js exports renderAugmentReco
  - web/js/main.js imports the panel + calls renderAugmentReco(p) on the
    state render path (right after renderItemBuild)
  - web/css/panels/augment_reco.css carries the styles and is @import'd
    into web/css/dashboard.css

A future refactor that drops one of these (an ESM split that forgets the
re-export, an index.html rebuild that misses the block, a main.js cleanup
that orphans the import, a dashboard.css that loses the @import) would
silently revert the pillar back to the buried tooltip. These are
grep-based smoke checks - cheap, fast, enough to catch a missing wire.

The arena_coach surface tweak (per-row `syn` synergy field) is also
guarded here since the panel renders it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "augment_reco.js"
MAIN_JS = WEB / "js" / "main.js"
PANEL_CSS = WEB / "css" / "panels" / "augment_reco.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"
ARENA_COACH = ROOT / "coaches" / "arena_coach.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class IndexHtmlTests(unittest.TestCase):
    """The block + its sub-elements must live inside #item-build."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_block_present(self) -> None:
        self.assertIn('id="ib-aug-reco-block"', self.text)
        self.assertIn('class="build-section ib-aug-reco-block"', self.text)

    def test_block_hidden_by_default(self) -> None:
        # Ships with `hidden` so first paint is collapsed; JS un-hides only
        # when the arena coach has stamped p.aug_reco.
        self.assertIn('id="ib-aug-reco-block" hidden', self.text)

    def test_sub_elements_present(self) -> None:
        for el_id in (
            "ib-aug-reco-top",
            "ib-aug-reco-list",
            "ib-aug-reco-meta",
        ):
            self.assertIn(f'id="{el_id}"', self.text)

    def test_block_is_inside_item_build(self) -> None:
        # The block must sit between the #item-build section open tag and
        # its close - that placement is what guarantees no reflow of the
        # other info panels (it toggles as a whole, like #ib-ds-block).
        ib_open = self.text.index('id="item-build"')
        block_at = self.text.index('id="ib-aug-reco-block"')
        # #adaptation is the panel that immediately follows #item-build.
        adapt_at = self.text.index('id="adaptation"')
        self.assertLess(ib_open, block_at)
        self.assertLess(block_at, adapt_at)


class PanelJsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderAugmentReco", self.text)

    def test_reads_expected_state_fields(self) -> None:
        # The panel is useless if it stops reading the fields the arena
        # coach stamps - pin the contract.
        for field in (
            "aug_reco",
            "aug_reco_top",
            "aug_reco_conf",
            "aug_reco_mode",
            "aug_reco_stage",
            "aug_reco_n_matches",
            "aug_reco_external",
            "augment_select",
        ):
            self.assertIn(field, self.text)

    def test_has_idempotency_guard(self) -> None:
        # 2s state cadence - a sig guard is mandatory (dashboard-render
        # idempotency rule). Reset helper is the test seam.
        self.assertIn("_lastSig", self.text)
        self.assertIn("export function _resetAugmentRecoSig", self.text)

    def test_presence_is_the_mode_gate(self) -> None:
        # Empty/absent aug_reco must hide the block (the recommender only
        # emits it for Arena/Mayhem - presence IS the gate).
        self.assertIn("if (!reco.length)", self.text)


class MainJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAIN_JS)

    def test_imports_panel(self) -> None:
        self.assertIn(
            "import { renderAugmentReco } from './panels/augment_reco.js'",
            self.text,
        )

    def test_called_on_render_path(self) -> None:
        self.assertIn("renderAugmentReco(p)", self.text)

    def test_called_after_item_build(self) -> None:
        # Render order: the augment block lives inside #item-build, so it
        # must render after renderItemBuild(p) lays the panel out.
        ib = self.text.index("renderItemBuild(p);")
        ar = self.text.index("renderAugmentReco(p);")
        self.assertLess(ib, ar)


class CssTests(unittest.TestCase):
    def test_panel_css_has_core_rules(self) -> None:
        css = _read(PANEL_CSS)
        self.assertIn(".ib-aug-reco-block", css)
        self.assertIn(".ib-aug-reco-block.is-active", css)
        self.assertIn(".ib-aug-reco-block[hidden]", css)

    def test_dashboard_css_imports_panel(self) -> None:
        self.assertIn(
            "@import './panels/augment_reco.css';", _read(DASHBOARD_CSS)
        )


class ArenaCoachSurfaceTests(unittest.TestCase):
    """The panel renders per-row synergy - the coach must surface it."""

    def test_aug_reco_row_carries_syn(self) -> None:
        src = _read(ARENA_COACH)
        # The per-row dict in _augment_recommendation must include "syn".
        self.assertIn('"syn":', src)
        self.assertIn("s.synergy", src)


if __name__ == "__main__":
    unittest.main()
