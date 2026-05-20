"""Tests for dashboard/routes_personal_vs.py.

Exercises the personal-vs threat-tag backend (champ-select UX win):
band classifier, route shape, days-window filter, cache TTL, and the
small-sample override.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_personal_vs as rpv


_PUUID = "OPERATOR_PUUID_FIXTURE"
_OTHER_PUUID = "OTHER_PLAYER_PUUID"


def _build_test_db(path: Path, rows: list[dict]) -> None:
    """Create a minimal rewind_history.db that satisfies the route's
    queries. ``rows`` is a list of match descriptors:

      {
        "match_id":      "NA1_001",
        "queue_id":      420,
        "ts_ms":         1700_000_000_000,
        "op_team":       100,
        "op_champ_id":   64,
        "op_win":        1,
        "enemy_champs":  [134, 22, ...],   # all on team 200
      }
    """
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE matches (
            match_id          TEXT PRIMARY KEY,
            queue_id          INTEGER,
            game_creation_ts  INTEGER
        );
        CREATE TABLE participants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            puuid           TEXT,
            team_id         INTEGER,
            champion_id     INTEGER,
            champion_name   TEXT,
            win             INTEGER
        );
    """)
    seen: set[str] = set()
    for r in rows:
        mid = r["match_id"]
        if mid not in seen:
            conn.execute(
                "INSERT INTO matches(match_id, queue_id, game_creation_ts) VALUES (?,?,?)",
                (mid, r.get("queue_id", 420), r.get("ts_ms", 0)),
            )
            seen.add(mid)
        # Operator row.
        conn.execute(
            "INSERT INTO participants(match_id, puuid, team_id, champion_id, "
            "champion_name, win) VALUES (?,?,?,?,?,?)",
            (mid, _PUUID, r.get("op_team", 100), r.get("op_champ_id", 1),
             r.get("op_champ_name", "Annie"), r.get("op_win", 0)),
        )
        # Enemy rows on the opposing team. Each enemy gets a unique
        # puuid (real Match-V5 shape) so the operator's puuid wins the
        # most-frequent count over multiple matches.
        for idx, ecid in enumerate(r.get("enemy_champs") or []):
            enemy_puuid = f"{_OTHER_PUUID}_{mid}_{idx}"
            conn.execute(
                "INSERT INTO participants(match_id, puuid, team_id, champion_id, "
                "champion_name, win) VALUES (?,?,?,?,?,?)",
                (mid, enemy_puuid, 200 if r.get("op_team", 100) == 100 else 100,
                 ecid, f"Cid{ecid}", 0 if r.get("op_win", 0) else 1),
            )
    conn.commit()
    conn.close()


class TestClassifyBand(unittest.TestCase):
    def test_unknown_when_sample_below_threshold(self):
        for n in range(0, rpv._BAND_MIN_SAMPLE):
            self.assertEqual(rpv._classify_band(n, 0), "unknown")
            self.assertEqual(rpv._classify_band(n, 50), "unknown")
            self.assertEqual(rpv._classify_band(n, 100), "unknown")

    def test_red_band(self):
        # WR strictly less than 40 with adequate sample.
        self.assertEqual(rpv._classify_band(10, 0), "red")
        self.assertEqual(rpv._classify_band(10, 39), "red")
        self.assertEqual(rpv._classify_band(5, 25), "red")

    def test_amber_band(self):
        # 40 <= WR <= 55 inclusive.
        self.assertEqual(rpv._classify_band(10, 40), "amber")
        self.assertEqual(rpv._classify_band(10, 50), "amber")
        self.assertEqual(rpv._classify_band(10, 55), "amber")

    def test_green_band(self):
        # WR strictly greater than 55.
        self.assertEqual(rpv._classify_band(10, 56), "green")
        self.assertEqual(rpv._classify_band(10, 75), "green")
        self.assertEqual(rpv._classify_band(10, 100), "green")

    def test_boundary_exclusive_red_vs_amber(self):
        self.assertEqual(rpv._classify_band(10, 39), "red")
        self.assertEqual(rpv._classify_band(10, 40), "amber")

    def test_boundary_inclusive_amber_vs_green(self):
        self.assertEqual(rpv._classify_band(10, 55), "amber")
        self.assertEqual(rpv._classify_band(10, 56), "green")


class TestParseQueueFilter(unittest.TestCase):
    def test_empty_returns_default(self):
        self.assertEqual(rpv._parse_queue_filter(""), rpv._DEFAULT_SR_QUEUES)
        self.assertEqual(rpv._parse_queue_filter("   "), rpv._DEFAULT_SR_QUEUES)

    def test_single_queue(self):
        self.assertEqual(rpv._parse_queue_filter("420"), (420,))

    def test_multi_queue(self):
        self.assertEqual(rpv._parse_queue_filter("400,420,490"), (400, 420, 490))

    def test_bogus_falls_back(self):
        self.assertEqual(rpv._parse_queue_filter("not-an-int"), rpv._DEFAULT_SR_QUEUES)


class TestResolveOperatorPuuid(unittest.TestCase):
    def test_picks_most_frequent(self):
        # Operator appears in every match (the dominant participant);
        # other puuids are scattered. The resolver picks the highest-
        # count puuid which is the operator's even though each match
        # carries multiple opposing-team participant rows.
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "rh.db"
            rows = []
            for i in range(50):
                # Each "match" carries one operator row + ONE enemy row,
                # so operator-count (50) cleanly beats per-enemy-cid count.
                rows.append({
                    "match_id": f"M{i}",
                    "ts_ms": i,
                    "enemy_champs": [i + 1000],  # unique enemy each match
                })
            _build_test_db(db_path, rows)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(rpv._resolve_operator_puuid(conn), _PUUID)
            finally:
                conn.close()

    def test_empty_db_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "rh.db"
            _build_test_db(db_path, [])
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertIsNone(rpv._resolve_operator_puuid(conn))
            finally:
                conn.close()


class _StubHandler:
    """Minimal handler that captures `_send` calls for assertions."""

    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.responses.append((status, body, content_type))


class TestQueryPersonalVs(unittest.TestCase):
    def _make_db(self, td: Path, rows: list[dict]) -> Path:
        db = td / "rh.db"
        _build_test_db(db, rows)
        return db

    def test_no_games_returns_empty_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td), [])
            conn = sqlite3.connect(str(db))
            try:
                out = rpv._query_personal_vs(conn, _PUUID, 64, 30, (420,))
            finally:
                conn.close()
            self.assertEqual(out["sample_n"], 0)
            self.assertEqual(out["wins"], 0)
            self.assertEqual(out["losses"], 0)
            self.assertEqual(out["threat_band"], "unknown")
            self.assertEqual(out["recent"], [])

    def test_basic_aggregation(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td), [
                # 3W 2L vs champ 64 in last 30d (60% -> green, n=5 -> not unknown)
                {"match_id": "M1", "ts_ms": now_ms - 1 * 86400_000, "op_win": 1, "enemy_champs": [64]},
                {"match_id": "M2", "ts_ms": now_ms - 2 * 86400_000, "op_win": 1, "enemy_champs": [64]},
                {"match_id": "M3", "ts_ms": now_ms - 3 * 86400_000, "op_win": 1, "enemy_champs": [64]},
                {"match_id": "M4", "ts_ms": now_ms - 4 * 86400_000, "op_win": 0, "enemy_champs": [64]},
                {"match_id": "M5", "ts_ms": now_ms - 5 * 86400_000, "op_win": 0, "enemy_champs": [64]},
                # A match where champ 64 is on the operator's team - should NOT count.
                {"match_id": "M6", "ts_ms": now_ms - 6 * 86400_000, "op_win": 1, "op_champ_id": 64, "enemy_champs": [99]},
            ])
            conn = sqlite3.connect(str(db))
            try:
                out = rpv._query_personal_vs(conn, _PUUID, 64, 30, (420,))
            finally:
                conn.close()
            self.assertEqual(out["sample_n"], 5)
            self.assertEqual(out["wins"], 3)
            self.assertEqual(out["losses"], 2)
            self.assertEqual(out["wr_pct"], 60)
            self.assertEqual(out["threat_band"], "green")
            self.assertEqual(len(out["recent"]), 5)
            # Recent ordered desc.
            ts_seq = [r["ts"] for r in out["recent"]]
            self.assertEqual(ts_seq, sorted(ts_seq, reverse=True))

    def test_days_window_filters_older(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td), [
                {"match_id": "OLD", "ts_ms": now_ms - 100 * 86400_000, "op_win": 1, "enemy_champs": [10]},
                {"match_id": "RECENT", "ts_ms": now_ms - 5 * 86400_000, "op_win": 0, "enemy_champs": [10]},
            ])
            conn = sqlite3.connect(str(db))
            try:
                window = rpv._query_personal_vs(conn, _PUUID, 10, 30, (420,))
                lifetime = rpv._query_personal_vs(conn, _PUUID, 10, 0, (420,))
            finally:
                conn.close()
            # 30d window sees only RECENT (1 loss).
            self.assertEqual(window["sample_n"], 1)
            self.assertEqual(window["losses"], 1)
            # Lifetime (days=0) sees both.
            self.assertEqual(lifetime["sample_n"], 2)
            self.assertEqual(lifetime["wins"], 1)

    def test_queue_filter_excludes_other_queues(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td), [
                {"match_id": "SR", "queue_id": 420, "ts_ms": now_ms, "op_win": 1, "enemy_champs": [10]},
                {"match_id": "ARAM", "queue_id": 450, "ts_ms": now_ms, "op_win": 1, "enemy_champs": [10]},
            ])
            conn = sqlite3.connect(str(db))
            try:
                sr_only = rpv._query_personal_vs(conn, _PUUID, 10, 0, (420,))
                aram = rpv._query_personal_vs(conn, _PUUID, 10, 0, (450,))
            finally:
                conn.close()
            self.assertEqual(sr_only["sample_n"], 1)
            self.assertEqual(aram["sample_n"], 1)

    def test_small_sample_band_is_unknown(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td), [
                # 2 games at 100% WR - should still be unknown (n < 5).
                {"match_id": "S1", "ts_ms": now_ms, "op_win": 1, "enemy_champs": [10]},
                {"match_id": "S2", "ts_ms": now_ms, "op_win": 1, "enemy_champs": [10]},
            ])
            conn = sqlite3.connect(str(db))
            try:
                out = rpv._query_personal_vs(conn, _PUUID, 10, 0, (420,))
            finally:
                conn.close()
            self.assertEqual(out["sample_n"], 2)
            self.assertEqual(out["wr_pct"], 100)
            self.assertEqual(out["threat_band"], "unknown")


class TestServeRoute(unittest.TestCase):
    """End-to-end through the dispatcher entry point."""

    def setUp(self):
        rpv._CACHE.clear()

    def _serve(self, db_path: Path, path: str) -> tuple[int, dict]:
        h = _StubHandler(path)
        with mock.patch.object(rpv, "_REWIND_DB", db_path):
            rpv._serve_personal_vs(h)
        self.assertEqual(len(h.responses), 1, "_send called exactly once")
        status, body, ctype = h.responses[0]
        self.assertEqual(ctype, "application/json")
        return status, json.loads(body.decode("utf-8"))

    def test_missing_champ_id_returns_400(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _build_test_db(db, [])
            status, payload = self._serve(db, "/api/personal-vs")
            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])

    def test_zero_champ_id_returns_400(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _build_test_db(db, [])
            status, payload = self._serve(db, "/api/personal-vs?champ_id=0")
            self.assertEqual(status, 400)

    def test_missing_db_returns_503(self):
        # Point at a non-existent path.
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "nope.db"
            status, payload = self._serve(missing, "/api/personal-vs?champ_id=64")
            self.assertEqual(status, 503)
            self.assertIn("rewind_history.db missing", payload["error"])

    def test_no_operator_puuid_returns_503(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _build_test_db(db, [])  # Empty - no operator puuid.
            status, payload = self._serve(db, "/api/personal-vs?champ_id=64")
            self.assertEqual(status, 503)
            self.assertIn("no operator puuid", payload["error"])

    def test_happy_path_response_shape(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _build_test_db(db, [
                {"match_id": f"M{i}", "ts_ms": now_ms - i * 86400_000,
                 "op_win": 1 if i % 2 == 0 else 0, "enemy_champs": [64]}
                for i in range(1, 11)  # 10 matches, 5W 5L
            ])
            status, payload = self._serve(db, "/api/personal-vs?champ_id=64&days=30")
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["champ_id"], 64)
            self.assertEqual(payload["days"], 30)
            self.assertEqual(payload["sample_n"], 10)
            self.assertEqual(payload["wins"] + payload["losses"], 10)
            self.assertIn(payload["threat_band"], {"red", "amber", "green"})
            self.assertIn("queue_ids", payload)
            self.assertIn("elapsed_ms", payload)
            self.assertLessEqual(len(payload["recent"]), 5)

    def test_cache_hit_marks_cached_flag(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            # >=3 matches so the operator puuid wins the most-frequent
            # tie-breaker over the (unique-per-match) enemy puuids.
            _build_test_db(db, [
                {"match_id": f"M{i}", "ts_ms": now_ms, "op_win": 1, "enemy_champs": [64]}
                for i in range(3)
            ])
            # Cold call seeds the cache.
            _, first = self._serve(db, "/api/personal-vs?champ_id=64&days=30")
            self.assertFalse(first["cached"])
            # Warm call hits.
            _, second = self._serve(db, "/api/personal-vs?champ_id=64&days=30")
            self.assertTrue(second["cached"])
            self.assertEqual(second["sample_n"], first["sample_n"])

    def test_days_clamp_negative_to_zero(self):
        # Spot-check: ?days=-5 should clamp to 0 (lifetime) without
        # crashing. Use a very old (but still positive) timestamp so the
        # `days=0 -> since_ms=0` predicate (ts >= 0) admits the row. Seed
        # multiple matches so the operator puuid wins the most-frequent
        # tie-breaker against the (unique-per-match) enemy puuids.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _build_test_db(db, [
                {"match_id": f"M{i}", "ts_ms": i, "op_win": 1, "enemy_champs": [64]}
                for i in range(1, 6)
            ])
            status, payload = self._serve(db, "/api/personal-vs?champ_id=64&days=-5")
            self.assertEqual(status, 200)
            self.assertEqual(payload["days"], 0)
            self.assertEqual(payload["sample_n"], 5)

    def test_invalid_days_falls_back_to_default(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            # Multiple matches so the operator puuid wins the
            # most-frequent tie-breaker.
            _build_test_db(db, [
                {"match_id": f"M{i}", "ts_ms": now_ms, "op_win": 0, "enemy_champs": [64]}
                for i in range(3)
            ])
            status, payload = self._serve(db, "/api/personal-vs?champ_id=64&days=not-a-num")
            self.assertEqual(status, 200)
            self.assertEqual(payload["days"], 30)

    def test_queue_filter_param_passed_through(self):
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _build_test_db(db, [
                {"match_id": "M1", "queue_id": 420, "ts_ms": now_ms, "op_win": 1, "enemy_champs": [64]},
                {"match_id": "M2", "queue_id": 450, "ts_ms": now_ms, "op_win": 0, "enemy_champs": [64]},
            ])
            _, sr = self._serve(db, "/api/personal-vs?champ_id=64&queue=420")
            self.assertEqual(sr["queue_ids"], [420])
            self.assertEqual(sr["sample_n"], 1)


class TestCacheLifecycle(unittest.TestCase):
    def setUp(self):
        rpv._CACHE.clear()

    def test_cache_get_returns_none_on_miss(self):
        self.assertIsNone(rpv._cache_get(("k",)))

    def test_cache_put_then_get(self):
        rpv._cache_put(("k",), {"v": 1})
        out = rpv._cache_get(("k",))
        self.assertEqual(out, {"v": 1})

    def test_cache_expires(self):
        rpv._cache_put(("k",), {"v": 1})
        # Force the timestamp into the past.
        ts, payload = rpv._CACHE[("k",)]
        rpv._CACHE[("k",)] = (ts - rpv._CACHE_TTL_S - 1, payload)
        self.assertIsNone(rpv._cache_get(("k",)))


class TestRouteRegistration(unittest.TestCase):
    def test_get_routes_exports_personal_vs(self):
        matchers = [m for m, _ in rpv.GET_ROUTES]
        self.assertTrue(any(m("/api/personal-vs") for m in matchers))
        # Query string should not affect the match.
        self.assertTrue(any(m("/api/personal-vs?champ_id=64") for m in matchers))
        # Sibling paths should NOT match.
        self.assertFalse(any(m("/api/personal-vs/other") for m in matchers))

    def test_module_imports_cleanly(self):
        # Smoke - if any import-time error sneaks in, this surfaces it.
        import importlib
        importlib.reload(rpv)
        self.assertTrue(hasattr(rpv, "GET_ROUTES"))
        self.assertTrue(hasattr(rpv, "POST_ROUTES"))

    def test_dispatch_includes_personal_vs_routes(self):
        # Round-trip through the dispatcher cache.
        from dashboard import _dispatch
        # Force a refresh so changes are reflected if the cache was warm.
        _dispatch._GET_CACHE = None
        routes = _dispatch._gather_get()
        matched = [m for m, _ in routes if m("/api/personal-vs?champ_id=1")]
        self.assertGreaterEqual(len(matched), 1,
                                "routes_personal_vs must be wired into _dispatch._gather_get")


if __name__ == "__main__":
    unittest.main()
