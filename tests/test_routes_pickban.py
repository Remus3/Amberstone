"""s170 - dashboard/routes_pickban.py tests (item #4).

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
            queue_id INTEGER,
            game_creation_ts INTEGER
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
    # Item 168: include game_creation_ts so the new _query_last_in_queue
    # join finds the column. Default to a synthetic monotonic stamp from
    # the row index so ORDER BY ts DESC is deterministic.
    match_ids = set()
    for i, r in enumerate(rows):
        mid = r["match_id"]
        if mid not in match_ids:
            conn.execute(
                "INSERT INTO matches(match_id, queue_id, game_creation_ts) "
                "VALUES (?, ?, ?)",
                (mid, r.get("queue_id", 420),
                 r.get("game_creation_ts", 1_700_000_000_000 + i * 86400)),
            )
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
            # s214: _query_performance returns list[dict] (was dict | None).
            # First entry is the top-WR pick at this role.
            picks = routes_pickban._query_performance(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertTrue(picks)
        perf = picks[0]
        self.assertEqual(perf["champName"], "Vayne")  # 80% beats 60%; MF skipped (<3 games)
        self.assertEqual(perf["wr_pct"], 80)
        self.assertEqual(perf["games"], 5)
        self.assertEqual(perf["wins"], 4)

    def test_returns_none_when_no_qualifying_champs(self):
        # Only one champion, 2 games - below _MIN_GAMES_PICK threshold.
        rows = [
            {"match_id": "a", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 1, "champion_name": "Annie", "win": 1},
            {"match_id": "b", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 1, "champion_name": "Annie", "win": 1},
        ]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            picks = routes_pickban._query_performance(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        # s214: empty list instead of None when no champs qualify.
        self.assertEqual(picks, [])

    def test_role_isolation(self):
        # Same champ played at two roles - only count BOTTOM stats.
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
            picks = routes_pickban._query_performance(conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertTrue(picks)
        self.assertEqual(picks[0]["wins"], 5)
        self.assertEqual(picks[0]["games"], 5)

    def test_queue_filter(self):
        # Same champ in two queues - q=400 (Normal Draft) only.
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
            picks = routes_pickban._query_performance(conn, "me", "BOTTOM", (400,))
        finally:
            conn.close()
        self.assertTrue(picks)
        self.assertEqual(picks[0]["games"], 5)
        self.assertEqual(picks[0]["wins"], 5)


class TestS214CascadeAndMultiPick(unittest.TestCase):
    """s214 - Pick & Ban filter constraints (cascade exclude + top-N
    + synergy ally_ids path). Each test runs against an isolated DB so
    we can assert exact list contents without prior-test bleed-through."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_top_n_returns_multiple_picks(self):
        # Three champs at BOT with descending WR:
        #   Vayne 5/5 (100%), Caitlyn 6/8 (75%), Jinx 4/6 (66%).
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1})
        for i in range(8):
            rows.append({"match_id": f"c{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 51,
                         "champion_name": "Caitlyn", "win": 1 if i < 6 else 0})
        for i in range(6):
            rows.append({"match_id": f"j{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 222,
                         "champion_name": "Jinx", "win": 1 if i < 4 else 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            picks = routes_pickban._query_performance(
                conn, "me", "BOTTOM", (420,), top=3)
        finally:
            conn.close()
        self.assertEqual(len(picks), 3)
        # Sorted by WR desc then games desc.
        self.assertEqual(picks[0]["champName"], "Vayne")
        self.assertEqual(picks[1]["champName"], "Caitlyn")
        self.assertEqual(picks[2]["champName"], "Jinx")

    def test_exclude_skips_specific_champs(self):
        # Vayne 5/5 (100%), Caitlyn 6/8 (75%). Exclude Vayne -> only Caitlyn.
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1})
        for i in range(8):
            rows.append({"match_id": f"c{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 51,
                         "champion_name": "Caitlyn", "win": 1 if i < 6 else 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            picks = routes_pickban._query_performance(
                conn, "me", "BOTTOM", (420,),
                exclude_ids=(67,), top=3)
        finally:
            conn.close()
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["champName"], "Caitlyn")

    def test_parse_csv_ints_handles_blanks(self):
        # Spot-test the CSV int parser used by the HTTP handler for
        # exclude=/allies= params. Blanks and non-int tokens silently drop.
        self.assertEqual(routes_pickban._parse_csv_ints(""), ())
        self.assertEqual(routes_pickban._parse_csv_ints("1,2,3"), (1, 2, 3))
        self.assertEqual(routes_pickban._parse_csv_ints("1, ,2,abc,3"), (1, 2, 3))
        self.assertEqual(routes_pickban._parse_csv_ints(",,"), ())


class TestMoodParamRemoved(unittest.TestCase):
    """A3 (QA 2026-07-03, docs/qa/CHAMP_SELECT_QA_2026-07-03.md): the
    s209 mood system is REMOVED from the backend. The route serves the
    raw top-N picks by score; a stray legacy ``mood=`` query arg is
    tolerated (ignored, never a 400); the response carries no ``mood``
    field; the deleted mood machinery is actually gone."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)
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

    def _seed_two_champs(self):
        # Vayne 4/5 (80%) beats Jinx 3/6 (50%) on raw score.
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1 if i < 4 else 0})
        for i in range(6):
            rows.append({"match_id": f"j{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 222,
                         "champion_name": "Jinx", "win": 1 if i < 3 else 0})
        _build_test_db(self.db_path, rows)

    def _request(self, path):
        h = self._make_handler(path)
        routes_pickban._serve_pickban_recs(h)
        code, body, _ctype = h._send.call_args[0]
        import json as _json
        return code, _json.loads(body)

    def test_stray_mood_param_is_ignored_not_400(self):
        self._seed_two_champs()
        code, payload = self._request(
            "/api/champ-select/pickban-recs?role=BOT&mood=limit")
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        # Raw top pick by score regardless of the stray mood arg.
        self.assertEqual(payload["performance"]["champName"], "Vayne")

    def test_response_has_no_mood_field(self):
        self._seed_two_champs()
        code, payload = self._request(
            "/api/champ-select/pickban-recs?role=BOT")
        self.assertEqual(code, 200)
        self.assertNotIn("mood", payload)

    def test_mood_values_do_not_change_picks(self):
        self._seed_two_champs()
        results = []
        for suffix in ("", "&mood=comfort", "&mood=synergy", "&mood=new"):
            code, payload = self._request(
                f"/api/champ-select/pickban-recs?role=BOT&top=3{suffix}")
            self.assertEqual(code, 200)
            results.append([p["champId"] for p in payload["performance_picks"]])
        self.assertTrue(all(r == results[0] for r in results), results)
        self.assertEqual(results[0], [67, 222])  # raw score order

    def test_mood_machinery_is_gone(self):
        for name in ("_VALID_MOODS", "_MOOD_DEFAULT", "_PERFORMANCE_QUERIES",
                     "_query_performance_limit", "_query_performance_new",
                     "_query_performance_synergy", "_rank_by_smoothed_wr"):
            self.assertFalse(hasattr(routes_pickban, name),
                             f"{name} should have been removed (QA A3)")


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
        # vs Nilah (id 895): 3 encounters, 3 losses -> 100%
        # vs Twitch (29): 2/2 losses -> 100%
        # vs Caitlyn (51): 5 encounters, 3 losses -> 60%
        # vs Jinx (222): 10 encounters, 4 losses -> 40% - should be filtered (<50%)
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
        # Nilah + Twitch both 100% loss; Nilah has more encounters -> first.
        self.assertEqual(names[0], "C895")  # Nilah
        self.assertEqual(names[1], "C29")   # Twitch
        self.assertEqual(names[2], "C51")   # Caitlyn (60%)
        self.assertNotIn("C222", names)     # Jinx filtered (40% < 50% threshold)

    def test_no_bans_when_no_losses(self):
        # Operator wins every game - no ban candidates surface.
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
        # 1 loss vs Mel - below _MIN_GAMES_BAN of 2.
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


class TestChampRecordQuery(unittest.TestCase):
    """s239 - the operator's personal record ON a champion. All-roles
    headline + at-role qualifier. None when zero all-roles games."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_all_roles_plus_role_split(self):
        # Vayne: 5 BOT (4W) + 3 TOP (0W) = 8 games / 4 wins all-roles;
        # at BOTTOM = 5 games / 4 wins.
        rows = []
        for i in range(5):
            rows.append({"match_id": f"b{i}", "puuid": "me",
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1 if i < 4 else 0})
        for i in range(3):
            rows.append({"match_id": f"t{i}", "puuid": "me",
                         "team_position": "TOP", "champion_id": 67,
                         "champion_name": "Vayne", "win": 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_champ_record(
                conn, "me", 67, (420,), role="BOTTOM")
        finally:
            conn.close()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["champId"], 67)
        self.assertEqual(rec["champName"], "Vayne")
        self.assertEqual(rec["games"], 8)
        self.assertEqual(rec["wins"], 4)
        self.assertEqual(rec["wr_pct"], 50)
        self.assertEqual(rec["role"], "BOTTOM")
        self.assertEqual(rec["role_games"], 5)
        self.assertEqual(rec["role_wins"], 4)
        self.assertEqual(rec["role_wr_pct"], 80)

    def test_no_role_arg_leaves_role_fields_none(self):
        rows = [{"match_id": f"v{i}", "puuid": "me", "team_position": "BOTTOM",
                 "champion_id": 67, "champion_name": "Vayne", "win": 1}
                for i in range(4)]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_champ_record(conn, "me", 67, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["games"], 4)
        self.assertIsNone(rec["role"])
        self.assertIsNone(rec["role_games"])
        self.assertIsNone(rec["role_wr_pct"])

    def test_role_with_zero_role_games(self):
        # Played only TOP; asking for BOTTOM role split -> role_* None but
        # all-roles still populated (the headline still shows).
        rows = [{"match_id": f"t{i}", "puuid": "me", "team_position": "TOP",
                 "champion_id": 67, "champion_name": "Vayne", "win": 1}
                for i in range(4)]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_champ_record(
                conn, "me", 67, (420,), role="BOTTOM")
        finally:
            conn.close()
        self.assertEqual(rec["games"], 4)
        self.assertEqual(rec["role"], "BOTTOM")
        self.assertEqual(rec["role_games"], 0)
        self.assertIsNone(rec["role_wr_pct"])

    def test_none_when_never_played(self):
        rows = [{"match_id": "a", "puuid": "me", "team_position": "BOTTOM",
                 "champion_id": 67, "champion_name": "Vayne", "win": 1}]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_champ_record(conn, "me", 222, (420,))
        finally:
            conn.close()
        self.assertIsNone(rec)

    def test_queue_filter_applies(self):
        rows = []
        for i in range(4):
            rows.append({"match_id": f"q{i}", "puuid": "me", "queue_id": 420,
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1})
        for i in range(4):
            rows.append({"match_id": f"a{i}", "puuid": "me", "queue_id": 450,
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_champ_record(conn, "me", 67, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["games"], 4)  # the 450 losses excluded
        self.assertEqual(rec["wins"], 4)


class TestWithAllyQuery(unittest.TestCase):
    """s239 - operator's record when a given ally champion is on their
    team, regardless of what the operator played (assumption A2)."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def _match(self, mid, op_champ, op_win, ally_champ, ally_team=100):
        return [
            {"match_id": mid, "puuid": "me", "team_id": 100,
             "team_position": "BOTTOM", "champion_id": op_champ,
             "champion_name": f"C{op_champ}", "win": op_win},
            {"match_id": mid, "puuid": "ally_p", "team_id": ally_team,
             "team_position": "UTILITY", "champion_id": ally_champ,
             "champion_name": "Thresh", "win": op_win if ally_team == 100 else 1 - op_win},
        ]

    def test_counts_only_same_team_ally(self):
        # 3 games with Thresh(412) on my team (2W); 2 games where Thresh
        # was on the ENEMY team (must NOT count toward "with ally").
        rows = []
        for i in range(3):
            rows.extend(self._match(f"w{i}", 67, 1 if i < 2 else 0, 412))
        for i in range(2):
            rows.extend(self._match(f"x{i}", 67, 1, 412, ally_team=200))
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_with_ally(conn, "me", 412, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["champId"], 412)
        self.assertEqual(rec["champName"], "Thresh")
        self.assertEqual(rec["games"], 3)
        self.assertEqual(rec["wins"], 2)
        self.assertEqual(rec["wr_pct"], 67)

    def test_independent_of_operator_champion(self):
        # Operator plays different champs (Vayne, Jinx) but Thresh is on
        # team both times - both count (assumption A2).
        rows = []
        rows.extend(self._match("a", 67, 1, 412))
        rows.extend(self._match("b", 222, 0, 412))
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_with_ally(conn, "me", 412, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["games"], 2)
        self.assertEqual(rec["wins"], 1)

    def test_zero_games_returns_entry_not_none(self):
        # Never had champ 999 as an ally - return a 0-game entry so the
        # UI can show "first time w/ X" (assumption A5).
        rows = self._match("a", 67, 1, 412)
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_with_ally(conn, "me", 999, (420,))
        finally:
            conn.close()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["champId"], 999)
        self.assertEqual(rec["games"], 0)
        self.assertEqual(rec["wins"], 0)
        self.assertEqual(rec["wr_pct"], 0)


class TestVsEnemyQuery(unittest.TestCase):
    """s239 - operator's record when a given champion was on the
    opposing team, anywhere (assumption A1 - not lane-strict)."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def _match(self, mid, op_win, enemy_champ, enemy_pos="TOP"):
        return [
            {"match_id": mid, "puuid": "me", "team_id": 100,
             "team_position": "BOTTOM", "champion_id": 67,
             "champion_name": "Vayne", "win": op_win},
            {"match_id": mid, "puuid": "enemy_p", "team_id": 200,
             "team_position": enemy_pos, "champion_id": enemy_champ,
             "champion_name": "Darius", "win": 1 - op_win},
        ]

    def test_counts_opposing_team_any_lane(self):
        # vs Darius(122): 5 encounters, operator wins 1 -> 20% WR.
        # enemy_pos varies (TOP/JUNGLE) - lane-agnostic per A1.
        rows = []
        for i in range(5):
            rows.extend(self._match(
                f"d{i}", 1 if i == 0 else 0, 122,
                "TOP" if i % 2 == 0 else "JUNGLE"))
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_vs_enemy(conn, "me", 122, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["champId"], 122)
        self.assertEqual(rec["champName"], "Darius")
        self.assertEqual(rec["games"], 5)
        self.assertEqual(rec["wins"], 1)
        self.assertEqual(rec["losses"], 4)
        self.assertEqual(rec["wr_pct"], 20)

    def test_same_team_does_not_count(self):
        # Darius on operator's OWN team -> not a "vs" encounter.
        rows = [
            {"match_id": "a", "puuid": "me", "team_id": 100,
             "team_position": "BOTTOM", "champion_id": 67,
             "champion_name": "Vayne", "win": 1},
            {"match_id": "a", "puuid": "mate", "team_id": 100,
             "team_position": "TOP", "champion_id": 122,
             "champion_name": "Darius", "win": 1},
        ]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_vs_enemy(conn, "me", 122, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["games"], 0)

    def test_zero_games_returns_entry(self):
        rows = self._match("a", 1, 122)
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rec = routes_pickban._query_vs_enemy(conn, "me", 555, (420,))
        finally:
            conn.close()
        self.assertEqual(rec["champId"], 555)
        self.assertEqual(rec["games"], 0)
        self.assertEqual(rec["wr_pct"], 0)


class TestPersonalRecordEndToEnd(unittest.TestCase):
    """s239 - _serve_personal_record HTTP shape via the stubbed handler."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)
        self._db_patch = mock.patch.object(
            routes_pickban, "_REWIND_DB", self.db_path)
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self.db_path.unlink(missing_ok=True)

    def _make_handler(self, path):
        h = mock.MagicMock()
        h.path = path
        return h

    def _payload(self, h):
        import json as _json
        h._send.assert_called_once()
        code, body, ctype = h._send.call_args[0]
        return code, _json.loads(body)

    def test_bad_queue_returns_400(self):
        rows = [{"match_id": "a", "puuid": "me", "team_id": 100,
                 "team_position": "BOTTOM", "champion_id": 67,
                 "champion_name": "Vayne", "win": 1}]
        _build_test_db(self.db_path, rows)
        h = self._make_handler(
            "/api/champ-select/personal-record?champ=67&queue=abc")
        routes_pickban._serve_personal_record(h)
        code = h._send.call_args[0][0]
        self.assertEqual(code, 400)

    def test_full_shape(self):
        rows = []
        # operator Vayne(67) 4/5 BOT
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me", "team_id": 100,
                         "team_position": "BOTTOM", "champion_id": 67,
                         "champion_name": "Vayne", "win": 1 if i < 4 else 0})
            # ally Thresh(412) on team for 3 of them
            if i < 3:
                rows.append({"match_id": f"v{i}", "puuid": "thr", "team_id": 100,
                             "team_position": "UTILITY", "champion_id": 412,
                             "champion_name": "Thresh", "win": 1 if i < 4 else 0})
            # enemy Darius(122) opposing all 5
            rows.append({"match_id": f"v{i}", "puuid": "dar", "team_id": 200,
                         "team_position": "TOP", "champion_id": 122,
                         "champion_name": "Darius", "win": 0 if i < 4 else 1})
        # Filler solo "me" matches so the operator is the unambiguous
        # most-frequent puuid (resolver tie-break is arbitrary). Champ 1
        # at MIDDLE in distinct matches - doesn't touch the 67/412/122
        # queries under test.
        for i in range(4):
            rows.append({"match_id": f"f{i}", "puuid": "me", "team_id": 100,
                         "team_position": "MIDDLE", "champion_id": 1,
                         "champion_name": "Annie", "win": 1})
        _build_test_db(self.db_path, rows)
        h = self._make_handler(
            "/api/champ-select/personal-record"
            "?champ=67&role=BOT&allies=412&enemies=122")
        routes_pickban._serve_personal_record(h)
        code, p = self._payload(h)
        self.assertEqual(code, 200)
        self.assertTrue(p["ok"])
        self.assertEqual(p["champ"]["champName"], "Vayne")
        self.assertEqual(p["champ"]["wr_pct"], 80)
        self.assertEqual(p["champ"]["role_wr_pct"], 80)
        self.assertEqual(len(p["with_allies"]), 1)
        self.assertEqual(p["with_allies"][0]["champName"], "Thresh")
        self.assertEqual(p["with_allies"][0]["games"], 3)
        self.assertEqual(len(p["vs_enemies"]), 1)
        self.assertEqual(p["vs_enemies"][0]["champName"], "Darius")
        self.assertEqual(p["vs_enemies"][0]["games"], 5)
        self.assertEqual(p["vs_enemies"][0]["wins"], 4)

    def test_no_champ_arg_ok(self):
        # Early CS - no champ hovered yet; allies/enemies still resolve.
        rows = [
            {"match_id": "a", "puuid": "me", "team_id": 100,
             "team_position": "BOTTOM", "champion_id": 67,
             "champion_name": "Vayne", "win": 1},
            {"match_id": "a", "puuid": "thr", "team_id": 100,
             "team_position": "UTILITY", "champion_id": 412,
             "champion_name": "Thresh", "win": 1},
        ]
        # Filler so "me" is the unambiguous most-frequent puuid.
        for i in range(2):
            rows.append({"match_id": f"f{i}", "puuid": "me", "team_id": 100,
                         "team_position": "MIDDLE", "champion_id": 1,
                         "champion_name": "Annie", "win": 1})
        _build_test_db(self.db_path, rows)
        h = self._make_handler(
            "/api/champ-select/personal-record?allies=412")
        routes_pickban._serve_personal_record(h)
        code, p = self._payload(h)
        self.assertEqual(code, 200)
        self.assertIsNone(p["champ"])
        self.assertEqual(p["with_allies"][0]["champName"], "Thresh")
        self.assertEqual(p["vs_enemies"], [])

    def test_missing_db_503(self):
        self.db_path.unlink(missing_ok=True)
        h = self._make_handler(
            "/api/champ-select/personal-record?champ=67")
        routes_pickban._serve_personal_record(h)
        code, _ = self._payload(h)
        self.assertEqual(code, 503)

    def test_empty_query_ok_all_empty(self):
        rows = [{"match_id": "a", "puuid": "me", "team_position": "BOTTOM",
                 "champion_id": 67, "champion_name": "Vayne", "win": 1}]
        _build_test_db(self.db_path, rows)
        h = self._make_handler("/api/champ-select/personal-record")
        routes_pickban._serve_personal_record(h)
        code, p = self._payload(h)
        self.assertEqual(code, 200)
        self.assertTrue(p["ok"])
        self.assertIsNone(p["champ"])
        self.assertEqual(p["with_allies"], [])
        self.assertEqual(p["vs_enemies"], [])

    def test_route_registered(self):
        paths = [pred for pred, _ in routes_pickban.GET_ROUTES]
        self.assertTrue(
            any(p("/api/champ-select/personal-record") for p in paths))


# Item 168 (2026-05-24): P&B panel restructured to 3 stacked sub-panels.
# Backend additions: last_in_queue (4th pick), struggle_ban (4th ban),
# cleanse_advisory (dynamic explanation prose).

class TestLastInQueue(unittest.TestCase):
    """4th pick = operator's most-recent champ in the same queue. Drives
    the "what did I play last time in this queue" cell at the right edge
    of the top sub-panel."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_picks_most_recent_match(self):
        rows = [
            {"match_id": "m1", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 67, "champion_name": "Vayne", "win": 1,
             "game_creation_ts": 1_000},
            {"match_id": "m2", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 51, "champion_name": "Caitlyn", "win": 0,
             "game_creation_ts": 2_000},  # most recent
        ]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            out = routes_pickban._query_last_in_queue(conn, "me", (420,))
        finally:
            conn.close()
        self.assertIsNotNone(out)
        self.assertEqual(out["champId"], 51)
        self.assertEqual(out["champName"], "Caitlyn")
        self.assertEqual(out["source"], "last_in_queue")
        self.assertIn("lost", out["reason"])

    def test_exclude_filters_already_picked(self):
        rows = [
            {"match_id": "m1", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 67, "champion_name": "Vayne", "win": 1,
             "game_creation_ts": 2_000},  # would be picked but excluded
            {"match_id": "m2", "puuid": "me", "team_position": "BOTTOM",
             "champion_id": 51, "champion_name": "Caitlyn", "win": 0,
             "game_creation_ts": 1_000},
        ]
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            out = routes_pickban._query_last_in_queue(
                conn, "me", (420,), exclude_ids=(67,))
        finally:
            conn.close()
        self.assertIsNotNone(out)
        self.assertEqual(out["champId"], 51)

    def test_no_matches_returns_none(self):
        _build_test_db(self.db_path, [])
        conn = sqlite3.connect(str(self.db_path))
        try:
            out = routes_pickban._query_last_in_queue(conn, "me", (420,))
        finally:
            conn.close()
        self.assertIsNone(out)


class TestStruggleBan(unittest.TestCase):
    """4th ban = operator's at-role highest loss-rate enemy with >=2
    encounters. Skips when the worst matchup is <50% loss rate."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_picks_highest_loss_rate(self):
        # Operator (puuid=me) plays BOTTOM. Encounters Draven 3 times
        # (3L), Caitlyn 3 times (1L). Draven should win as struggle.
        rows = []
        for i in range(3):
            rows.append({"match_id": f"d{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 0})  # operator loses to Draven
            rows.append({"match_id": f"d{i}", "puuid": "enemy",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 119, "champion_name": "Draven",
                         "win": 1})
        for i in range(3):
            rows.append({"match_id": f"c{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 1 if i > 0 else 0})  # 1L of 3
            rows.append({"match_id": f"c{i}", "puuid": "enemy",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 51, "champion_name": "Caitlyn",
                         "win": 0 if i > 0 else 1})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            out = routes_pickban._query_struggle_ban(
                conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertIsNotNone(out)
        self.assertEqual(out["champId"], 119)
        self.assertEqual(out["name"], "Draven")
        self.assertEqual(out["pct"], 100)
        self.assertEqual(out["source"], "struggle")

    def test_returns_none_when_no_struggle(self):
        # Operator wins every matchup -> no struggle.
        rows = []
        for i in range(2):
            rows.append({"match_id": f"d{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne", "win": 1})
            rows.append({"match_id": f"d{i}", "puuid": "enemy",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 119, "champion_name": "Draven", "win": 0})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            out = routes_pickban._query_struggle_ban(
                conn, "me", "BOTTOM", (420,))
        finally:
            conn.close()
        self.assertIsNone(out)

    def test_exclude_filters_already_banned(self):
        rows = []
        for i in range(3):
            rows.append({"match_id": f"d{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne", "win": 0})
            rows.append({"match_id": f"d{i}", "puuid": "enemy",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 119, "champion_name": "Draven", "win": 1})
        _build_test_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            out = routes_pickban._query_struggle_ban(
                conn, "me", "BOTTOM", (420,), exclude_ids=(119,))
        finally:
            conn.close()
        self.assertIsNone(out)


class TestCleanseAdvisory(unittest.TestCase):
    """Heuristic CC-cleanse advisory. Surfaces when enemy team has 3+
    heavy-CC champs AND the operator's summoner pair doesn't include
    Cleanse (id 1)."""

    def test_returns_none_with_no_enemies(self):
        self.assertIsNone(routes_pickban._compose_cleanse_advisory((), ()))

    def test_returns_none_when_cleanse_already_equipped(self):
        # Even if enemy team is heavy CC, no advisory when Cleanse is on.
        advisory = routes_pickban._compose_cleanse_advisory(
            (1, 2, 3, 4, 5), (4, 1))  # Flash + Cleanse
        self.assertIsNone(advisory)

    def test_silent_below_threshold(self):
        # Fewer than 3 enemy ids -> never enough heavy CC.
        advisory = routes_pickban._compose_cleanse_advisory((1, 2), (4, 14))
        self.assertIsNone(advisory)


class TestPickBanEndToEndItem168(unittest.TestCase):
    """End-to-end shape pin for the item 168 response fields."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)
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

    def test_response_carries_item168_fields(self):
        # Build a DB with enough rows to populate comfort + last_in_queue.
        # Operator plays Vayne (comfort #1) + 1 recent game on champ 999
        # (synthetic, not in any counter list) so last_in_queue resolves
        # to that NOT-already-picked id. Mock _counters_for_champion to
        # return [] so the bans fallback to _query_bans (DB-driven) and
        # struggle_ban can find a champ NOT in the bans list.
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 1, "game_creation_ts": 1_000 + i})
        # Most-recent game: synthetic champ 999.
        rows.append({"match_id": "x1", "puuid": "me",
                     "team_id": 100, "team_position": "BOTTOM",
                     "champion_id": 999, "champion_name": "Synth",
                     "win": 0, "game_creation_ts": 2_000})
        # Two enemy struggle candidates: Singed (id 27, 3/3 losses) and
        # Olaf (id 2, 2/3 losses = 66%). _query_bans uses TOP-3 ordering
        # so Singed lands in bans; struggle_ban then falls to Olaf
        # (the next-highest loss-rate above 50%). Both lane-matched.
        for i in range(3):
            rows.append({"match_id": f"d{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 0, "game_creation_ts": 500 + i})
            rows.append({"match_id": f"d{i}", "puuid": "enemy",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 27, "champion_name": "Singed",
                         "win": 1, "game_creation_ts": 500 + i})
        for i in range(3):
            rows.append({"match_id": f"o{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 1 if i == 2 else 0, "game_creation_ts": 600 + i})
            rows.append({"match_id": f"o{i}", "puuid": "enemy",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 2, "champion_name": "Olaf",
                         "win": 0 if i == 2 else 1, "game_creation_ts": 600 + i})
        _build_test_db(self.db_path, rows)
        h = self._make_handler("/api/champ-select/pickban-recs?role=BOT")
        # Patch counters lookup to [] so bans use the DB fallback - keeps
        # the struggle-ban path independent of the live counters json.
        with mock.patch.object(routes_pickban, "_counters_for_champion",
                                return_value=[]):
            routes_pickban._serve_pickban_recs(h)
        code, body, ctype = h._send.call_args[0]
        self.assertEqual(code, 200)
        import json as _json
        payload = _json.loads(body)
        self.assertTrue(payload["ok"])
        # Item 168 fields ALWAYS present in response (even when None).
        self.assertIn("last_in_queue", payload)
        self.assertIn("struggle_ban", payload)
        self.assertIn("cleanse_advisory", payload)
        # last_in_queue should resolve to synth champ 999 (most recent +
        # not the already-picked Vayne from comfort #1).
        self.assertIsNotNone(payload["last_in_queue"])
        self.assertEqual(payload["last_in_queue"]["champId"], 999)
        # _query_bans takes top-3 loss-rate enemies (Singed 100% +
        # Olaf 66%); struggle_ban then falls to the NEXT candidate not
        # already in bans. With only 2 struggle enemies and both in
        # bans, struggle_ban resolves to None - acceptable per the
        # endpoint contract (the field is allowed to be None when all
        # candidates are already in the counter-bans list).
        # Field PRESENCE (None or struct) is what the panel reads.
        self.assertTrue(payload["struggle_ban"] is None
                        or payload["struggle_ban"]["champId"] in (27, 2))
        # Cleanse advisory: empty enemies + no my_summoners -> None.
        self.assertIsNone(payload["cleanse_advisory"])


class TestCountersVsComp(unittest.TestCase):
    """RC2 E4 (P2): aggregate counter-picks vs the LIVE enemy comp.

    `_counters_vs_comp` takes the enemy champion ids, walks the existing
    per-champion counters index, and ranks candidate counters by how many
    of the enemy champs each one counters (the at-a-glance "pick into this
    comp" list). Excludes already-picked/banned ids and the enemy ids
    themselves.
    """

    # A tiny self-contained counters graph so the test never depends on the
    # live champion_counters.json content. The index is keyed by the champ
    # being countered -> the champions that beat it (same shape as the real
    # champion_counters.json: "Caitlyn" -> ["Draven","Lucian","Pyke"]).
    # So: Caitlyn(51) counters BOTH enemies (she beats Draven + Lucian);
    # Vayne(67) counters only Draven.
    _COUNTERS = {
        "draven": ["Caitlyn", "Vayne"],   # who beats Draven
        "lucian": ["Caitlyn"],            # who beats Lucian
    }
    _NAME_TO_ID = {"caitlyn": 51, "vayne": 67, "draven": 119, "lucian": 236}
    _ID_TO_NAME = {51: "Caitlyn", 67: "Vayne", 119: "Draven", 236: "Lucian"}

    def _patches(self):
        return (
            mock.patch.object(routes_pickban, "_load_counters_index",
                              return_value=self._COUNTERS),
            mock.patch.object(routes_pickban, "_load_champ_name_to_id",
                              return_value=self._NAME_TO_ID),
            mock.patch.object(routes_pickban, "_load_champ_id_to_name",
                              return_value=self._ID_TO_NAME),
        )

    def test_aggregates_and_ranks_by_coverage(self):
        # Enemy comp = Draven(119) + Lucian(236). Caitlyn counters BOTH;
        # Vayne counters only Draven. So Caitlyn ranks first with count=2.
        with self._patches()[0], self._patches()[1], self._patches()[2]:
            out = routes_pickban._counters_vs_comp((119, 236), (), limit=5)
        self.assertTrue(out)
        self.assertEqual(out[0]["name"], "Caitlyn")
        self.assertEqual(out[0]["counters_count"], 2)
        self.assertEqual(out[0]["champId"], 51)
        # Vayne present but ranked below Caitlyn (counters only 1).
        names = [c["name"] for c in out]
        self.assertIn("Vayne", names)
        self.assertLess(names.index("Caitlyn"), names.index("Vayne"))

    def test_excludes_picked_and_banned(self):
        # Caitlyn already banned/picked -> excluded; Vayne surfaces.
        with self._patches()[0], self._patches()[1], self._patches()[2]:
            out = routes_pickban._counters_vs_comp((119, 236), (51,), limit=5)
        names = [c["name"] for c in out]
        self.assertNotIn("Caitlyn", names)
        self.assertIn("Vayne", names)

    def test_excludes_enemy_ids_themselves(self):
        # A candidate that is itself on the enemy team must not be
        # recommended back to the operator. Make Lucian a "counter" of
        # Draven in the index; since Lucian(236) is an enemy it must be
        # dropped from the output.
        counters = dict(self._COUNTERS)
        counters["draven"] = ["Caitlyn", "Vayne", "Lucian"]
        with mock.patch.object(routes_pickban, "_load_counters_index",
                               return_value=counters), \
             self._patches()[1], self._patches()[2]:
            out = routes_pickban._counters_vs_comp((119, 236), (), limit=5)
        names = [c["name"] for c in out]
        self.assertNotIn("Draven", names)   # Draven(119) is an enemy
        self.assertNotIn("Lucian", names)   # Lucian(236) is an enemy

    def test_empty_comp_returns_empty(self):
        with self._patches()[0], self._patches()[1], self._patches()[2]:
            self.assertEqual(routes_pickban._counters_vs_comp((), (), limit=5), [])

    def test_limit_caps_results(self):
        with self._patches()[0], self._patches()[1], self._patches()[2]:
            out = routes_pickban._counters_vs_comp((119, 236), (), limit=1)
        self.assertEqual(len(out), 1)

    def test_each_row_has_note_and_vs_names(self):
        with self._patches()[0], self._patches()[1], self._patches()[2]:
            out = routes_pickban._counters_vs_comp((119, 236), (), limit=5)
        top = out[0]
        self.assertIn("note", top)
        self.assertTrue(top["note"])
        self.assertIn("vs_names", top)
        # Caitlyn counters both Draven + Lucian.
        self.assertIn("Draven", top["vs_names"])
        self.assertIn("Lucian", top["vs_names"])


class TestCounterPicksRoute(unittest.TestCase):
    """RC2 E4: /api/champ-select/counter-picks route surface."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)
        routes_pickban._reset_caches()
        self._db_patch = mock.patch.object(
            routes_pickban, "_REWIND_DB", self.db_path)
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self.db_path.unlink(missing_ok=True)

    def _make_handler(self, path):
        h = mock.MagicMock()
        h.path = path
        return h

    def test_route_registered(self):
        paths = [
            "/api/champ-select/counter-picks",
        ]
        registered = [p for (m, _fn) in routes_pickban.GET_ROUTES
                      for p in paths if m(p)]
        self.assertIn("/api/champ-select/counter-picks", registered)

    def test_returns_counter_list(self):
        # No DB rows needed - counter-picks reads the counters index, not
        # the operator history. Patch the index helpers to a known graph.
        counters = {"draven": ["Caitlyn", "Vayne"], "lucian": ["Caitlyn"]}
        n2i = {"caitlyn": 51, "vayne": 67, "draven": 119, "lucian": 236}
        i2n = {51: "Caitlyn", 67: "Vayne", 119: "Draven", 236: "Lucian"}
        h = self._make_handler(
            "/api/champ-select/counter-picks?role=BOT&enemies=119,236")
        with mock.patch.object(routes_pickban, "_load_counters_index",
                               return_value=counters), \
             mock.patch.object(routes_pickban, "_load_champ_name_to_id",
                               return_value=n2i), \
             mock.patch.object(routes_pickban, "_load_champ_id_to_name",
                               return_value=i2n):
            routes_pickban._serve_counter_picks(h)
        code, body, ctype = h._send.call_args[0]
        self.assertEqual(code, 200)
        import json as _json
        payload = _json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertIn("counters", payload)
        self.assertTrue(payload["counters"])
        self.assertEqual(payload["counters"][0]["name"], "Caitlyn")
        # icon path present so the JS can render the portrait directly.
        self.assertIn("champId", payload["counters"][0])

    def test_empty_enemies_returns_ok_empty(self):
        h = self._make_handler("/api/champ-select/counter-picks?enemies=")
        routes_pickban._serve_counter_picks(h)
        code, body, ctype = h._send.call_args[0]
        self.assertEqual(code, 200)
        import json as _json
        payload = _json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["counters"], [])


if __name__ == "__main__":
    unittest.main()
