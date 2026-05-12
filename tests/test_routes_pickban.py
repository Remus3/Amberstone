"""s170 — dashboard/routes_pickban.py tests (item #4).

Validates the new /api/champ-select/pickban-recs endpoint that surfaces
operator WR per role + ban suggestions from rewind_history.db.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_pickban


def _build_test_db(path: Path, rows: list[dict]) -> None:
    """Create a minimal rewind_history.db shape with the columns the
    endpoint queries. ``rows`` is a list of participant dicts; missing
    fields default sensibly.
    """
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            queue_id INTEGER
        );
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            puuid TEXT,
            team_id INTEGER,
            team_position TEXT,
            champion_id INTEGER,
            champion_name TEXT,
            win INTEGER
        );
    """)
    match_ids = set()
    for r in rows:
        mid = r["match_id"]
        if mid not in match_ids:
            conn.execute("INSERT INTO matches(match_id, queue_id) VALUES (?, ?)",
                         (mid, r.get("queue_id", 420)))
            match_ids.add(mid)
        conn.execute(
            "INSERT INTO participants(match_id, puuid, team_id, team_position, "
            "champion_id, champion_name, win) VALUES (?,?,?,?,?,?,?)",
            (mid, r["puuid"], r.get("team_id", 100), r["team_position"],
             r["champion_id"], r["champion_name"], r["win"]),
        )
    conn.commit()
    conn.close()


class TestNormalizeRole(unittest.TestCase):
    def test_dashboard_form(self):
        self.assertEqual(routes_pickban._normalize_role("BOT"), "BOTTOM")
        self.assertEqual(routes_pickban._normalize_role("JNG"), "JUNGLE")
        self.assertEqual(routes_pickban._normalize_role("MID"), "MIDDLE")
        self.assertEqual(routes_pickban._normalize_role("SUP"), "UTILITY")
        self.assertEqual(routes_pickban._normalize_role("TOP"), "TOP")

    def test_lcu_form_passthrough(self):
        self.assertEqual(routes_pickban._normalize_role("BOTTOM"), "BOTTOM")
        self.assertEqual(routes_pickban._normalize_role("JUNGLE"), "JUNGLE")
        self.assertEqual(routes_pickban._normalize_role("UTILITY"), "UTILITY")

    def test_case_insensitive(self):
        self.assertEqual(routes_pickban._normalize_role("bot"), "BOTTOM")
        self.assertEqual(routes_pickban._normalize_role("Middle"), "MIDDLE")

    def test_aliases(self):
        # ADC is a common alias for BOTTOM; SUPP for UTILITY.
        self.assertEqual(routes_pickban._normalize_role("ADC"), "BOTTOM")
        self.assertEqual(routes_pickban._normalize_role("SUPP"), "UTILITY")
        self.assertEqual(routes_pickban._normalize_role("SUPPORT"), "UTILITY")

    def test_unknown_returns_none(self):
        self.assertIsNone(routes_pickban._normalize_role("FILL"))
        self.assertIsNone(routes_pickban._normalize_role(""))
        self.assertIsNone(routes_pickban._normalize_role("NONE"))


class TestPerformanceQuery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_picks_highest_wr_with_min_games(self):
        # Vayne 4/5 (80%), Jinx 6/10 (60%), MissFortune 2/2 (100% but <3 games)
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1 if i < 4 else 0})
        for i in range(10):
            rows.append({"match_id": f"j{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 222,
                         "champion_name": "Jinx", "win": 1 if i < 6 else 0})
        for i in range(2):
            rows.append({"match_id": f"mf{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 21,
                         "champion_name": "MissFortune", "win": 1})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            perf = routes_pickban._query_performance(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertIsNotNone(perf)
        self.assertEqual(perf["champName"], "Vayne")  # 80% beats 60%; MF skipped (<3 games)
        self.assertEqual(perf["wr_pct"], 80)
        self.assertEqual(perf["games"], 5)
        self.assertEqual(perf["wins"], 4)

    def test_returns_none_when_no_qualifying_champs(self):
        # Only one champion, 2 games — below _MIN_GAMES_PICK threshold.
        rows = [
            {"match_id": "a", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 1, "champion_name": "Annie", "win": 1},
            {"match_id": "b", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 1, "champion_name": "Annie", "win": 1},
        ]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            perf = routes_pickban._query_performance(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertIsNone(perf)

    def test_role_isolation(self):
        # Same champ played at two roles — only count BOTTOM stats.
        rows = []
        for i in range(5):
            rows.append({"match_id": f"b{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1})
        for i in range(5):
            rows.append({"match_id": f"t{i}", "puuid": "me",
                         "team_position": "TOP", "champion_id": 67,
                         "champion_name": "Vayne", "win": 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            perf = routes_pickban._query_performance(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertEqual(perf["wins"], 5)
        self.assertEqual(perf["games"], 5)

    def test_queue_filter(self):
        # Same champ in two queues — q=400 (Normal Draft) only.
        rows = []
        for i in range(5):
            rows.append({"match_id": f"a{i}", "puuid": "me", "queue_id": 400,
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1})
        for i in range(5):
            rows.append({"match_id": f"b{i}", "puuid": "me", "queue_id": 450,
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            # Filter to q=400 only.
            perf = routes_pickban._query_performance(conn, "me", "BOTTOM", (400,))
        finally:
            conn.close()
        self.assertEqual(perf["games"], 5)
        self.assertEqual(perf["wins"], 5)


class TestBansQuery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def _add_match(self, match_id, ally_champ, ally_win, enemy_champ, queue=420):
        # 4 rows per match: ally at BOT, enemy at BOT. team_ids differ.
        return [
            {"match_id": match_id, "queue_id": queue, "puuid": "me",
             "team_id": 100, "team_position": "BOTTOM",
             "champion_id": ally_champ, "champion_name": f"C{ally_champ}",
             "win": ally_win},
            {"match_id": match_id, "queue_id": queue, "puuid": "enemy",
             "team_id": 200, "team_position": "BOTTOM",
             "champion_id": enemy_champ, "champion_name": f"C{enemy_champ}",
             "win": 1 - ally_win},
        ]

    def test_top_3_bans_by_loss_rate(self):
        # vs Nilah (id 895): 3 encounters, 3 losses → 100%
        # vs Twitch (29): 2/2 losses → 100%
        # vs Caitlyn (51): 5 encounters, 3 losses → 60%
        # vs Jinx (222): 10 encounters, 4 losses → 40% — should be filtered (<50%)
        rows = []
        for i in range(3):
            rows.extend(self._add_match(f"n{i}", 67, 0, 895))  # operator loses to Nilah
        for i in range(2):
            rows.extend(self._add_match(f"t{i}", 67, 0, 29))   # operator loses to Twitch
        for i in range(5):
            rows.extend(self._add_match(f"c{i}", 67, 1 if i < 2 else 0, 51))  # 60% loss vs Cait
        for i in range(10):
            rows.extend(self._add_match(f"j{i}", 67, 1 if i < 6 else 0, 222))  # 40% loss vs Jinx
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            bans = routes_pickban._query_bans(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertEqual(len(bans), 3)
        # Sorted by loss-rate desc, then encounters desc.
        names = [b["name"] for b in bans]
        # Nilah + Twitch both 100% loss; Nilah has more encounters → first.
        self.assertEqual(names[0], "C895")  # Nilah
        self.assertEqual(names[1], "C29")   # Twitch
        self.assertEqual(names[2], "C51")   # Caitlyn (60%)
        self.assertNotIn("C222", names)     # Jinx filtered (40% < 50% threshold)

    def test_no_bans_when_no_losses(self):
        # Operator wins every game — no ban candidates surface.
        rows = []
        for i in range(5):
            rows.extend(self._add_match(f"w{i}", 67, 1, 895))
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            bans = routes_pickban._query_bans(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertEqual(bans, [])

    def test_min_encounters_threshold(self):
        # 1 loss vs Mel — below _MIN_GAMES_BAN of 2.
        rows = self._add_match("a", 67, 0, 800)  # loss to Mel
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            bans = routes_pickban._query_bans(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertEqual(bans, [])


class TestResolveOperatorPuuid(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_picks_most_frequent_puuid(self):
        rows = []
        for i in range(10):
            rows.append({"match_id": f"a{i}", "puuid": "operator",
                         "team_position": "BOTTOM", "champion_id": 1,
                         "champion_name": "Annie", "win": 1})
        for i in range(3):
            rows.append({"match_id": f"a{i}", "puuid": "friend",
                         "team_position": "TOP", "champion_id": 2,
                         "champion_name": "Olaf", "win": 1})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            puuid = routes_pickban._resolve_operator_puuid(conn)
        finally:
            conn.close()
        self.assertEqual(puuid, "operator")

    def test_returns_none_for_empty_db(self):
        _build_test_db(self.db_path, [])
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertIsNone(routes_pickban._resolve_operator_puuid(conn))
        finally:
            conn.close()


class TestEndToEnd(unittest.TestCase):
    """Smoke-test _serve_pickban_recs by stubbing the HTTP handler shim."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)
        # Patch _REWIND_DB to point at the temp DB.
        self._db_patch = mock.patch.object(
            routes_pickban, "_REWIND_DB", self.db_path,
        )
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self.db_path.unlink(missing_ok=True)

    def _make_handler(self, path):
        h = mock.MagicMock()
        h.path = path
        return h

    def test_missing_role_returns_400(self):
        rows = [{"match_id": "a", "puuid": "me", "team_position": "BOTTOM",
                 "champion_id": 1, "champion_name": "Annie", "win": 1}]
        _build_test_db(self.db_path, rows)
        h = self._make_handler("/api/champ-select/pickban-recs")
        routes_pickban._serve_pickban_recs(h)
        h._send.assert_called_once()
        code = h._send.call_args[0][0]
        self.assertEqual(code, 400)

    def test_happy_path_returns_payload(self):
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1 if i < 4 else 0})
        _build_test_db(self.db_path, rows)
        h = self._make_handler("/api/champ-select/pickban-recs?role=BOT")
        routes_pickban._serve_pickban_recs(h)
        h._send.assert_called_once()
        code, body, ctype = h._send.call_args[0]
        self.assertEqual(code, 200)
        import json as _json
        payload = _json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["role"], "BOTTOM")
        self.assertEqual(payload["performance"]["champName"], "Vayne")

    def test_missing_db_returns_503(self):
        self.db_path.unlink(missing_ok=True)  # remove the temp DB
        h = self._make_handler("/api/champ-select/pickban-recs?role=BOT")
        routes_pickban._serve_pickban_recs(h)
        code = h._send.call_args[0][0]
        self.assertEqual(code, 503)


if __name__ == "__main__":
    unittest.main()
