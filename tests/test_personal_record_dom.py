"""Regression guards for the per-user enemy win-rate surface - updated for
the 2026-07-03 champ-select QA (slice A, ruling A4 in
docs/qa/CHAMP_SELECT_QA_2026-07-03.md).

A4: the deprecated YOUR RECORD code path was REMOVED - the
/api/champ-select/personal-record fetch, its _CSV_PR_CACHE, the
_csvRenderPersonalRecordBlock headline, the chip helpers, and the
_csvInjectEnemyWinRates bulk-injection are all gone. The enemy WR slot
(.csv-enemy-wr-slot, left of each enemy icon on the SR Enemies panel) is a
DIFFERENT feature and STAYS - now fed per-champion by /api/personal-vs via
_csvWrSlotFetch (60s client cache, data-champ-id repaint).

Grep-based smoke checks - cheap, fast, enough to catch a re-wire drift.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PANEL_JS = WEB / "js" / "panels" / "champ_select.js"
CSV_CSS = WEB / "css" / "panels" / "champ_select_view.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class PersonalRecordRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_fetch_helper_removed(self) -> None:
        self.assertNotIn("_csvFetchPersonalRecord", self.text)
        self.assertNotIn("/api/champ-select/personal-record", self.text)

    def test_cache_removed(self) -> None:
        self.assertNotIn("_CSV_PR_CACHE", self.text)
        self.assertNotIn("_CSV_PR_INFLIGHT", self.text)

    def test_render_block_removed(self) -> None:
        self.assertNotIn("_csvRenderPersonalRecordBlock", self.text)
        self.assertNotIn("_csvPrChipIcon", self.text)
        self.assertNotIn("_csvInjectEnemyWinRates", self.text)
        self.assertNotIn("csv-sugg-your-record", self.text)


class EnemyWrSlotTests(unittest.TestCase):
    """The enemy WR slot stays - now riding /api/personal-vs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)
        cls.css = _read(CSV_CSS)

    def test_slot_fetch_defined(self) -> None:
        self.assertIn("function _csvWrSlotFetch(", self.text)
        self.assertIn("/api/personal-vs", self.text)

    def test_slot_apply_defined(self) -> None:
        self.assertIn("function _csvWrSlotApply(", self.text)

    def test_60s_cache_dedupe(self) -> None:
        self.assertIn("_csvWrCache", self.text)
        self.assertIn("_CSV_WR_TTL_MS", self.text)

    def test_tint_helper_retained(self) -> None:
        # _csvPrTint survives - it colors the WR slot bands.
        self.assertIn("function _csvPrTint(", self.text)
        for cls_name in ("is-good", "is-mid", "is-bad", "is-new"):
            self.assertIn(cls_name, self.text)

    def test_enemies_opts_request_win_rate(self) -> None:
        self.assertIn("withWinRate: true", self.text)

    def test_wr_slot_class_wired(self) -> None:
        self.assertIn("csv-enemy-wr-slot", self.text)
        self.assertIn(".csv-enemy-wr-slot", self.css)

    def test_slot_repaints_by_champ_id(self) -> None:
        # The in-flight resolver repaints every live slot by data-champ-id
        # (the cell may have been re-rendered since the fetch fired).
        self.assertIn(".csv-enemy-wr-slot[data-champ-id=", self.text)


class CsvCssRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(CSV_CSS)

    def test_your_record_styles_removed(self) -> None:
        for sel in (".csv-pr {", ".csv-pr-title", ".csv-pr-chip",
                    ".csv-pr-hint"):
            self.assertNotIn(sel, self.text)

    def test_wr_slot_styles_stay(self) -> None:
        self.assertIn(".csv-enemy-wr-slot", self.text)
        self.assertIn(".csv-enemy-wr-slot.is-good", self.text)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
