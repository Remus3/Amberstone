"""Regression guards for the s239 per-user pick-ban contextual read
(AUTONOMOUS_AUDIT opportunity #2 - foreground the per-user draft model).

The backend is heavily covered by test_routes_pickban.py (the
_query_champ_record / _query_with_ally / _query_vs_enemy helpers +
_serve_personal_record e2e). What's NOT covered there is the
champ_select.js wiring that foregrounds it:

  - _csvFetchPersonalRecord hits /api/champ-select/personal-record
  - _csvRenderPersonalRecordBlock builds the "YOUR RECORD" headline
  - _csvRenderPickBan derives enemyIds + selfCid and PREPENDS the
    headline above the mood recs (the actual "foregrounding")
  - champ_select_view.css carries .csv-pr-* styles + the row-2 grid
    floor was raised to budget the headline

A future ESM split / render refactor / CSS purge that drops one of
these would silently un-foreground the feature. Grep-based smoke
checks - cheap, fast, enough to catch a missing wire.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PANEL_JS = WEB / "js" / "panels" / "champ_select.js"
CSV_CSS = WEB / "css" / "panels" / "champ_select_view.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class PanelJsFetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_fetch_helper_defined(self) -> None:
        self.assertIn("function _csvFetchPersonalRecord(", self.text)

    def test_hits_personal_record_endpoint(self) -> None:
        self.assertIn("/api/champ-select/personal-record", self.text)

    def test_passes_champ_allies_enemies_params(self) -> None:
        for frag in ("&champ=", "&allies=", "&enemies="):
            self.assertIn(frag, self.text)

    def test_no_queue_param_lifetime_read(self) -> None:
        # A7: the lifetime read intentionally omits &queue= so a
        # normal-draft lobby still counts ranked games. Guard the
        # decision - a future "helpfully add queue" edit trips this.
        url_region = self.text.split("_csvFetchPersonalRecord", 1)[1][:1400]
        self.assertNotIn("&queue=", url_region)

    def test_60s_cache_dedupe(self) -> None:
        self.assertIn("_CSV_PR_CACHE", self.text)
        self.assertIn("_CSV_PR_INFLIGHT", self.text)
        self.assertIn("_CSV_PR_TTL_MS", self.text)


class PanelJsRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_render_block_defined(self) -> None:
        self.assertIn("function _csvRenderPersonalRecordBlock(", self.text)

    def test_headline_classes_present(self) -> None:
        for cls in ("csv-pr-title", "csv-pr-champ", "csv-pr-row",
                    "csv-pr-chip", "csv-pr-hint"):
            self.assertIn(cls, self.text)

    def test_tint_classes_present(self) -> None:
        for cls in ("is-good", "is-mid", "is-bad", "is-new"):
            self.assertIn(cls, self.text)

    def test_headline_prepended_above_mood_recs(self) -> None:
        # The actual foregrounding: prHtml is prepended to the panel
        # html so the per-user model is the FIRST thing in the card.
        self.assertIn("let html = prHtml + `", self.text)

    def test_enemy_and_self_derivation(self) -> None:
        self.assertIn("const enemyIds = (cs.their_team || [])", self.text)
        self.assertIn("let selfCid = myCid | 0;", self.text)

    def test_fetch_called_in_renderpickban(self) -> None:
        self.assertIn("const prData = _csvFetchPersonalRecord(", self.text)
        self.assertIn(
            "const prHtml = _csvRenderPersonalRecordBlock(prData, selfCid);",
            self.text)


class CsvCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(CSV_CSS)

    def test_headline_styles_present(self) -> None:
        for sel in (".csv-pr {", ".csv-pr-title", ".csv-pr-champ-name",
                    ".csv-pr-chip", ".csv-pr-chip.is-bad", ".csv-pr-hint"):
            self.assertIn(sel, self.text)

    def test_grid_floor_raised_for_headline(self) -> None:
        # Headline budget: floor lifted off the old 354 so the 3 mood
        # pick-rows aren't crushed on short viewports.
        self.assertIn("minmax(460px, 1fr)", self.text)
        self.assertNotIn("minmax(354px, 1fr)", self.text)

    def test_s239_css_block_is_ascii(self) -> None:
        # Project hard rule - authored content is 7-bit ASCII. Scoped to
        # the s239-authored .csv-pr block: the file at large carries
        # pre-existing legacy non-ASCII whose retroactive purge is an
        # explicitly separate operator-gated pass (CLAUDE.md), out of
        # this task's scope - asserting the whole file would be wrong.
        start = self.text.index("/* s239: foregrounded per-user")
        end = self.text.index(".csv-pb-role-row {")
        self.text[start:end].encode("ascii")


class PanelJsAsciiTests(unittest.TestCase):
    def test_s239_block_is_ascii(self) -> None:
        # Only the s239-authored region must be ASCII; the file at large
        # has pre-existing rendered-string chars out of this task's
        # scope. Slice the personal-record helpers + render block.
        text = _read(PANEL_JS)
        start = text.index("function _csvFetchPersonalRecord(")
        end = text.index("function _csvMergePickBanData(")
        text[start:end].encode("ascii")


if __name__ == "__main__":
    unittest.main()
