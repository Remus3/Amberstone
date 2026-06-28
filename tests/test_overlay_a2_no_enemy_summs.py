"""A2 (OVERLAY_BUILD_MASTER_PLAN WP-A2): drop the legacy dashboard STATS-panel
"Enemy summs" row. It was producerless for the live stats payload (the
`#st-enemy-summs` cell always rendered "-" and was hidden by _hideEmptyStatRows),
and the new overlay tap-tracker (`web/js/panels/enemy_spells.js`) is the sole
enemy-summoner surface now.

Grep-style contract test, mirroring tests/test_overlay_a1_slider_apply.py:
pathlib reads + substring asserts, no DOM emulation (there is no jsdom/node
harness for web/js page code). Acceptance: zero `st-enemy-summs` in the repo
frontend; the overlay enemy_spells tracker stays intact.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "web" / "index.html"
RIGHT_NOW_JS = REPO / "web" / "js" / "panels" / "right_now.js"
ENEMY_SPELLS_JS = REPO / "web" / "js" / "panels" / "enemy_spells.js"


class LegacyEnemySummsRowRemoved(unittest.TestCase):
    """The dead STATS row + its setter are gone from both frontend files."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")
        self.rn = RIGHT_NOW_JS.read_text(encoding="utf-8")

    def test_index_html_has_no_enemy_summs_span(self):
        self.assertNotIn("st-enemy-summs", self.html)

    def test_index_html_has_no_enemy_summs_label(self):
        # The "Enemy summs" stats-label row is removed wholesale.
        self.assertNotIn("Enemy summs", self.html)

    def test_right_now_js_has_no_enemy_summs_setv(self):
        self.assertNotIn("st-enemy-summs", self.rn)

    def test_right_now_js_no_longer_reads_enemy_summs_tracked(self):
        # The producerless payload field is no longer consumed by the panel.
        self.assertNotIn("enemy_summs_tracked", self.rn)

    def test_ally_summs_row_untouched(self):
        # Sibling row directly above must survive - the deletion is scoped.
        self.assertIn("st-ally-summs", self.html)
        self.assertIn("st-ally-summs", self.rn)


class OverlayEnemySpellsTrackerUnaffected(unittest.TestCase):
    """The NEW overlay surface (the sole enemy-summoner surface) is intact."""

    def test_enemy_spells_panel_still_present(self):
        self.assertTrue(
            ENEMY_SPELLS_JS.is_file(),
            "web/js/panels/enemy_spells.js (the overlay tap-tracker) must survive A2",
        )
        self.assertGreater(len(ENEMY_SPELLS_JS.read_text(encoding="utf-8")), 100)


class AsciiTests(unittest.TestCase):
    # NOTE: index.html + right_now.js carry a pre-existing non-ASCII tail
    # (dashboard box-drawing / rendered glyphs) that predates A2 and is out of
    # this WP's scope (a deletion cannot introduce non-ASCII). The dedicated
    # smart-quote / glyph retro-sweep is a separate operator-gated pass per
    # CLAUDE.md, so this WP only guards its own test file.
    def _assert_ascii(self, path: Path):
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad[:5], [], f"non-ASCII bytes in {path.name}")

    def test_this_file_ascii(self):
        self._assert_ascii(Path(__file__).resolve())


if __name__ == "__main__":
    unittest.main()
