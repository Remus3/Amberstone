"""Tests for dashboard.routes_personal_build GET /api/personal-build.

Builds a temp disk rewind DB with the minimal schema compute_personal_build
needs and points RC_REWIND_DB at it - deterministic + clean-checkout safe. A raw
exception string is never leaked; validation returns structured 400s.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import personal_build_wr
from dashboard import routes_personal_build


class _RouteHarness:
    def __init__(self, qs: str):
        self.path = "/api/personal-build" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type

    def json(self):
        return json.loads(self.sent_body.decode("utf-8"))


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, tracked_champion_name TEXT, "
        "tracked_champion_id INTEGER, tracked_team_id INTEGER, tracked_win INTEGER, "
        "map_id INTEGER, game_duration_s INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, champion_id INTEGER, team_id INTEGER, "
        "item0 INTEGER, item1 INTEGER, item2 INTEGER, item3 INTEGER, item4 INTEGER, "
        "item5 INTEGER)"
    )
    # 20 SR games on TestChamp: 12 wins w/ IE (3031), 8 losses w/ Black Cleaver (3071).
    for i in range(20):
        win = 1 if i < 12 else 0
        leg = 3031 if win else 3071
        conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
                     (f"T_{i}", "TestChamp", 999, 100, win, 11, 1800))
        conn.execute("INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"T_{i}", 999, 100, leg, 3009, 0, 0, 0, 0))
    conn.commit()
    conn.close()


class PersonalBuildRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="rc_personal_build_")
        cls._db = Path(cls._tmp.name) / "rewind_history.db"
        _make_db(cls._db)
        cls._prev = os.environ.get("RC_REWIND_DB")
        os.environ["RC_REWIND_DB"] = str(cls._db)

    @classmethod
    def tearDownClass(cls):
        if cls._prev is None:
            os.environ.pop("RC_REWIND_DB", None)
        else:
            os.environ["RC_REWIND_DB"] = cls._prev
        cls._tmp.cleanup()

    def setUp(self):
        routes_personal_build._reset_caches()
        personal_build_wr.reset_cache()

    def test_happy_path(self):
        h = _RouteHarness("champion=TestChamp&mode=sr")
        routes_personal_build._serve_personal_build(h)
        self.assertEqual(h.sent_status, 200)
        body = h.json()
        self.assertEqual(body["games"], 20)
        self.assertEqual(body["mode"], "sr")
        self.assertFalse(body["cached"])
        self.assertIn("items", body)
        ids = {it["item_id"] for it in body["items"]}
        self.assertIn(3031, ids)

    def test_default_mode_is_sr(self):
        h = _RouteHarness("champion=TestChamp")
        routes_personal_build._serve_personal_build(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.json()["mode"], "sr")

    def test_missing_champion_400(self):
        h = _RouteHarness("mode=sr")
        routes_personal_build._serve_personal_build(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(h.json()["ok"])

    def test_bad_mode_400(self):
        h = _RouteHarness("champion=TestChamp&mode=nonsense")
        routes_personal_build._serve_personal_build(h)
        self.assertEqual(h.sent_status, 400)

    def test_malformed_champion_400(self):
        h = _RouteHarness("champion=%3Cscript%3E")
        routes_personal_build._serve_personal_build(h)
        self.assertEqual(h.sent_status, 400)

    def test_cache_second_call(self):
        h1 = _RouteHarness("champion=TestChamp&mode=sr")
        routes_personal_build._serve_personal_build(h1)
        self.assertFalse(h1.json()["cached"])
        h2 = _RouteHarness("champion=TestChamp&mode=sr")
        routes_personal_build._serve_personal_build(h2)
        self.assertTrue(h2.json()["cached"])

    def test_unknown_champion_is_empty_not_error(self):
        h = _RouteHarness("champion=Nobody&mode=sr")
        routes_personal_build._serve_personal_build(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.json()["confidence"], "insufficient")


if __name__ == "__main__":
    unittest.main()
