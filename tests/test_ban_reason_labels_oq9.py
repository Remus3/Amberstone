"""OQ9 (QA26 remainder): ban-reason labels on champ-select bans.

RC2_QA_CONSOLIDATED.md row 26: "pick reasons ship; ban/profile do not" -
the Pick & Ban panel renders a per-pick `reason` string (routes_pickban.py
:505) but the ban cells render name-only (champ_select.js operator
2026-05-31 #6 stripped the % tag). QA26's remaining half surfaces a short
honest why-banned label on the two RC SUGGESTION surfaces:

  1. P&B panel ban cells (.csv-pb168-ban): the /api/champ-select/
     pickban-recs payload ALREADY carries pct/losses/encounters per ban
     (routes_pickban.py:833-839) - the label is a client-side formatter
     ("beats you 67% (4/6)"). No server change.
  2. Suggestions panel global-top-bans grid (.csv-sugg-ban-card): the
     /api/champ-select/ban-suggestions payload carried no reason field, so
     the route gains an ADDITIVE `rank` (1-based position in the meta
     top_bans list, appended at END of dict) and the card renders
     "meta ban #N".

The LCU actual-bans strip (_csvBannedListRow) is intentionally excluded:
no honest reason data exists for opponents' bans. The dual-score
HURTS-THEM/HELPS-US list already carries its own explicit why (mode chip
+ score + n=) and is untouched.

Grep-based string assertions mirror tests/test_ban_suggest_toggle_panel_dom.py;
route tests mirror the _StubHandler pattern from tests/test_p2w1_dash_c.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_ban_suggestions as rbsu

ROOT = Path(__file__).resolve().parent.parent
CHAMP_SELECT_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
VIEW_CSS = ROOT / "web" / "css" / "panels" / "champ_select_view.css"
ROUTE_PY = ROOT / "dashboard" / "routes_ban_suggestions.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class _StubHandler:
    """Captures _send calls; mirrors tests/test_p2w1_dash_c.py."""

    def __init__(self, path: str = "/", headers: dict | None = None):
        self.path = path
        self.headers = headers or {}
        self.client_address = ("127.0.0.1", 0)
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))

    @property
    def code(self) -> int:
        return self.responses[-1][0]

    @property
    def body(self) -> bytes:
        return self.responses[-1][1]


_BANS_DOC = {
    "patch": "16.13.1",
    "top_bans": ["Yone", "Zed", "Yasuo", "Master Yi"],
}
_NAME_TO_ID = {
    "Yone": 777, "Zed": 238, "Yasuo": 157,
    "Master Yi": 11, "MasterYi": 11,
}


class RouteRankFieldTests(unittest.TestCase):
    """/api/champ-select/ban-suggestions gains an additive 1-based rank."""

    def _serve(self, path: str) -> dict:
        h = _StubHandler(path)
        with mock.patch.object(rbsu, "_load_bans_file",
                               return_value=dict(_BANS_DOC)), \
             mock.patch.object(rbsu, "_load_name_to_id",
                               return_value=dict(_NAME_TO_ID)):
            rbsu._serve_ban_suggestions(h)
        self.assertEqual(h.code, 200)
        return json.loads(h.body.decode("utf-8"))

    def test_rank_present_and_one_based(self):
        data = self._serve("/api/champ-select/ban-suggestions?top=4")
        self.assertTrue(data["ok"])
        ranks = [s.get("rank") for s in data["suggestions"]]
        self.assertEqual(ranks, [1, 2, 3, 4])

    def test_rank_survives_exclusion_filter(self):
        # Excluding the #1 meta ban (Yone, 777) must NOT re-rank the
        # remainder - the first suggestion keeps its true meta rank 2.
        data = self._serve(
            "/api/champ-select/ban-suggestions?exclude=777&top=3")
        self.assertEqual(data["suggestions"][0]["name"], "Zed")
        self.assertEqual(data["suggestions"][0]["rank"], 2)
        self.assertEqual([s["rank"] for s in data["suggestions"]],
                         [2, 3, 4])

    def test_rank_is_last_key_additive_convention(self):
        # Additive field appended at END of dict (repo convention).
        data = self._serve("/api/champ-select/ban-suggestions?top=2")
        for s in data["suggestions"]:
            self.assertEqual(list(s.keys())[-1], "rank")


class PickBanCellReasonTests(unittest.TestCase):
    """champ_select.js renders a why-banned sub-label on .csv-pb168-ban
    cells from payload fields that already exist (pct/losses/encounters)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(CHAMP_SELECT_JS)

    def test_reason_formatter_exists(self):
        self.assertIn("_csvBanReasonLabel", self.js)

    def test_reason_div_in_ban_cell_template(self):
        self.assertIn("csv-pb168-reason", self.js)

    def test_beats_you_label_text(self):
        self.assertIn("beats you ", self.js)

    def test_counter_ban_mapping_carries_sample_fields(self):
        # The counterBans mapping must carry encounters + losses through
        # so the label can show the sample (routes_pickban.py:833-839
        # already returns them; pre-OQ9 the mapping dropped both).
        idx = self.js.index("const counterBans")
        block = self.js[idx:idx + 900]
        self.assertIn("encounters", block)
        self.assertIn("losses", block)


class SuggestionCardReasonTests(unittest.TestCase):
    """QA 2026-07-03 slice A (A2, docs/qa/CHAMP_SELECT_QA_2026-07-03.md):
    the global top-bans suggestion grid was a hidden ghost (display:none
    since 2026-05-23) and was REMOVED with its meta-rank sub-label. The
    P&B ban-cell reason labels (the visible OQ9 surface) stay - guarded
    by PbBanReasonTests above."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(CHAMP_SELECT_JS)

    def test_ghost_suggestion_card_template_removed(self):
        self.assertNotIn("csv-sugg-ban-reason", self.js)
        self.assertNotIn("meta ban #", self.js)


class ReasonCssTests(unittest.TestCase):
    """Both reason sub-labels use tokens: >= var(--fs-xs), var(--text-dim)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(VIEW_CSS)

    def _rule(self, selector: str) -> str:
        idx = self.css.index(selector)
        return self.css[idx:self.css.index("}", idx)]

    def test_pb168_reason_rule(self):
        rule = self._rule(".csv-pb168-reason")
        self.assertIn("var(--fs-xs)", rule)
        self.assertIn("var(--text-dim)", rule)

    def test_sugg_ban_reason_rule_removed(self):
        # QA 2026-07-03 slice A (A2): removed with the ghost grid.
        self.assertNotIn(".csv-sugg-ban-reason", self.css)


class AsciiHygieneTests(unittest.TestCase):
    """Every file touched by OQ9 stays 7-bit ASCII."""

    def test_touched_files_ascii(self):
        for p in (CHAMP_SELECT_JS, VIEW_CSS, ROUTE_PY, Path(__file__)):
            raw = p.read_bytes()
            bad = [b for b in raw if b > 0x7F]
            self.assertFalse(
                bad, f"{p.name} carries {len(bad)} bytes > 0x7F")


if __name__ == "__main__":
    unittest.main()
