"""RM-610 (directive X-10, external reference A): History rows keep
unresolved games LISTED with a badge and out of every tally.

Server half: dashboard.builders._load_match_rows stamps each row with
``result`` from core.resolved_wr.classify (win / loss / remake /
unknown; remake = game_time_s under REMAKE_MAX_SECONDS).

Client half (web/js/main.js, read as text): the per-session W-L chip, the
filtered SEASON STATS rate and the result filter all count through one
``_historyResult`` rule, and the shared row builder renders a REMAKE / ?
hx-chip badge for unresolved rows instead of a win/loss tint.

Synthetic temp DB only. ASCII-only authored content.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MAIN_JS = _PROJECT_ROOT / "web" / "js" / "main.js"
PUUID = "SYNTH-PUUID-ME"


def _raw(win):
    if win is None:
        return ""
    return json.dumps({
        "tracked_puuid": PUUID,
        "lcu_match_detail": {
            "participantIdentities": [
                {"participantId": 1, "player": {"puuid": PUUID}}],
            "participants": [{"participantId": 1, "stats": {"win": win}}],
        },
    })


def _js_function(src: str, name: str) -> str:
    """Body text of ``function name(...) { ... }`` (brace-matched)."""
    m = re.search(r"function " + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    assert m, name
    depth, i = 0, m.end() - 1
    while True:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1]
        i += 1


class LoadMatchRowsResultTests(unittest.TestCase):

    def test_result_stamp(self):
        import dashboard.builders as B
        from dashboard import _context
        with TemporaryDirectory() as td:
            app = Path(td)
            (app / "data").mkdir()
            db = app / "data" / "match_history.db"
            c = sqlite3.connect(str(db))
            c.execute(
                "CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
                " game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
                " assists INTEGER, kda_str TEXT, label TEXT, raw_data TEXT)")
            for ts, dur, win in (("2026-01-01 04:00:00", 1800, True),
                                 ("2026-01-01 03:00:00", 1700, False),
                                 ("2026-01-01 02:00:00", 200, False),
                                 ("2026-01-01 01:00:00", 1600, None)):
                c.execute("INSERT INTO matches (timestamp, mode, champion,"
                          " grade, game_time_s, kills, deaths, assists,"
                          " kda_str, label, raw_data)"
                          " VALUES (?,'SR','Annie','A',?,1,1,1,'1/1/1','',?)",
                          (ts, dur, _raw(win)))
            c.commit()
            c.close()
            try:
                with mock.patch.object(B, "_APP_DIR", app):
                    rows = B._load_match_rows()
            finally:
                cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
                    str(db), None)
                if cached is not None:
                    cached.close()
        self.assertEqual([r["result"] for r in rows],
                         ["win", "loss", "remake", "unknown"])


class HistoryJsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = _MAIN_JS.read_text(encoding="utf-8")

    def test_one_result_rule(self):
        rule = _js_function(self.src, "_historyResult")
        self.assertIn('typeof m.result === "string"', rule)

    def test_tallies_count_through_the_rule(self):
        for fn in ("_sessionWL", "_historyAggStats"):
            body = _js_function(self.src, fn)
            with self.subTest(fn=fn):
                self.assertIn("_historyResult(", body)
                self.assertNotIn("m.win === true", body)
                self.assertNotIn("m.win === false", body)

    def test_row_badges_unresolved(self):
        body = _js_function(self.src, "_historyMatchRowEl")
        self.assertIn("_historyResult(m)", body)
        self.assertIn('class="hx-chip"', body)
        self.assertIn(">REMAKE</span>", body)
        self.assertIn(">?</span>", body)
        self.assertIn("badge +", body)

    def test_hx_chip_class_exists(self):
        css = (_PROJECT_ROOT / "web" / "css" / "hextech.css").read_text(
            encoding="utf-8")
        self.assertIn(".hx-chip {", css)
        dash = (_PROJECT_ROOT / "web" / "css" / "dashboard.css").read_text(
            encoding="utf-8")
        self.assertIn("hextech.css", dash)


if __name__ == "__main__":
    unittest.main()
