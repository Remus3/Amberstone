"""DELETION GUARD for the home hero "true season WR" readout (HOME_QA H5).

The QA ruling removed the ranked season-WR readout from the home hero:
the `_homeRenderSeasonWr` render fn, the `#home-hero-season-wr` DOM node,
the `.home-season-wr*` CSS, the `_compute_season_wr` builder + its
re-export, and the `season_wr` payload key are ALL gone. This file was the
typography/wiring guard for that feature; per the LEDGER 766 champ-select
precedent it is converted to a deletion guard that FAILS if any of those
symbols reappear (so a future edit cannot silently resurrect the readout).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOME_CSS = ROOT / "web" / "css" / "panels" / "home.css"
INDEX_HTML = ROOT / "web" / "index.html"
MAIN_JS = ROOT / "web" / "js" / "main.js"

SELECTOR = ".home-season-wr"
DOM_ID = "home-hero-season-wr"
RENDER_FN = "_homeRenderSeasonWr"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _non_ascii(text: str) -> list[str]:
    return sorted({c for c in text if ord(c) > 0x7F})


class SeasonWrFrontendRemovedTests(unittest.TestCase):
    """The season-WR DOM node, render fn, and CSS selector are all gone."""

    def test_dom_node_removed(self):
        self.assertNotIn(DOM_ID, _read(INDEX_HTML),
                         f"index.html still carries #{DOM_ID}")

    def test_render_fn_removed(self):
        js = _read(MAIN_JS)
        self.assertNotIn(f"function {RENDER_FN}", js,
                         f"main.js still defines {RENDER_FN}")
        self.assertNotIn(f"{RENDER_FN}(", js,
                         f"main.js still calls {RENDER_FN}")

    def test_css_selector_removed(self):
        # The specific season-wr selectors are gone. (Guard on the label /
        # value children too, which were unique to this readout.)
        css = _read(HOME_CSS)
        self.assertNotIn(SELECTOR + " ", css)
        self.assertNotIn(SELECTOR + "-lbl", css)
        self.assertNotIn(SELECTOR + "-val", css)


class SeasonWrBackendRemovedTests(unittest.TestCase):
    """_compute_season_wr is gone from dashboard.builders (+ re-export), and
    the season_wr key is absent from the home payload."""

    def test_compute_season_wr_removed_from_builders(self):
        import dashboard.builders as B
        self.assertFalse(
            hasattr(B, "_compute_season_wr"),
            "dashboard.builders still exposes _compute_season_wr")

    def test_season_wr_absent_from_payload(self):
        import dashboard.builders_home as H
        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            mh = app_dir / "data" / "match_history.db"
            conn = sqlite3.connect(str(mh))
            conn.execute(
                "CREATE TABLE matches ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
                "  game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
                "  assists INTEGER, cs INTEGER, cs_per_min REAL,"
                "  gold INTEGER, gold_per_min REAL, kda_str TEXT,"
                "  kp_pct REAL, label TEXT, raw_data TEXT,"
                "  game_id INTEGER DEFAULT 0)"
            )
            conn.commit()
            conn.close()
            try:
                with mock.patch.object(H, "_get_lcu_for_rank",
                                       return_value=None):
                    with mock.patch.object(H, "_APP_DIR", app_dir):
                        out = H._build_home_summary()
            finally:
                from dashboard import _context
                conns = getattr(_context.DB_CONN_LOCAL, "conns", {})
                for k in [k for k in list(conns.keys())
                          if k.startswith(str(app_dir))]:
                    c = conns.pop(k, None)
                    if c is not None:
                        c.close()
        self.assertNotIn("season_wr", out,
                         "home payload still carries season_wr")

    def test_home_json_mock_has_no_season_wr(self):
        import json
        mock_path = ROOT / "web" / "data" / "ui_mock" / "home.json"
        data = json.loads(mock_path.read_text(encoding="utf-8"))
        self.assertNotIn("season_wr", data,
                         "home.json mock still carries season_wr")


class GuardAsciiTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        self.assertEqual([], _non_ascii(_read(Path(__file__))),
                         "this guard file has non-ASCII glyphs")


if __name__ == "__main__":
    unittest.main()
