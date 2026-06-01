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

Operator 2026-05-31 (part 4): the YOUR RECORD headline was REMOVED from
the Assessment panel; the operator's lifetime win-rate vs each enemy now
renders in the Enemies panel (left of the icon) via
_csvInjectEnemyWinRates. The _csvRenderPersonalRecordBlock function + the
.csv-pr-* CSS remain as deadcode pending a sweep, so the existence checks
below still pass; the render-WIRING check now targets the injection.
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

    def test_your_record_container_defensively_hidden(self) -> None:
        # Operator 2026-05-31 (part 4): YOUR RECORD removed. The JS keeps
        # a defensive getElementById("csv-sugg-your-record") that empties
        # + hides the container if any cached DOM still carries it. Guard
        # that the lookup (now a hide, not a write) is still present.
        self.assertIn(
            'document.getElementById("csv-sugg-your-record")',
            self.text,
        )

    def test_enemy_and_self_derivation(self) -> None:
        self.assertIn("const enemyIds = (cs.their_team || [])", self.text)
        self.assertIn("let selfCid = myCid | 0;", self.text)

    def test_fetch_called_in_renderpickban(self) -> None:
        self.assertIn("const prData = _csvFetchPersonalRecord(", self.text)
        # Operator 2026-05-31 (part 4): the YOUR RECORD render call was
        # replaced by the per-enemy win-rate injection into the Enemies
        # panel. The old headline render is no longer wired.
        self.assertNotIn(
            "const prHtml = _csvRenderPersonalRecordBlock(prData, selfCid);",
            self.text)
        self.assertIn("_csvInjectEnemyWinRates(prData)", self.text)


class EnemyWinRateInjectTests(unittest.TestCase):
    """Operator 2026-05-31 (part 4): per-enemy lifetime win-rate rendered
    in the Enemies panel (left of the icon), replacing the YOUR RECORD
    block. Grep guards on the inject helper + its wiring."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)
        cls.css = _read(CSV_CSS)

    def test_inject_helper_defined(self) -> None:
        self.assertIn("function _csvInjectEnemyWinRates(", self.text)

    def test_enemies_opts_request_win_rate(self) -> None:
        self.assertIn("withWinRate: true", self.text)

    def test_wr_slot_class_wired(self) -> None:
        self.assertIn("csv-enemy-wr-slot", self.text)
        self.assertIn(".csv-enemy-wr-slot", self.css)

    def test_enemies_cells_carry_cid(self) -> None:
        # _csvInjectEnemyWinRates matches enemy cells by data-cid.
        self.assertIn("li.dataset.cid =", self.text)


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
