"""Tests for dashboard/routes_post_game_wpa.py.

Covers:
  - 400 when match_id missing
  - 503 when rewind_history.db absent
  - 404 when match_id not in matches table
  - 200 with WPA decomposition on a real (synthetic) match
  - Model signature switch (fallback -> trained) invalidates the cache
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import post_game_score as pgs
from dashboard import routes_post_game_wpa as rpgw


class _StubHandler:
    """Minimal handler that captures `_send` calls for assertions."""

    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.responses.append((status, body, content_type))


def _seed_db(path: Path, match_id: str = "TEST_M1") -> None:
    """Build a minimal rewind_history.db schema with one match that has
    a small but real timeline. Reuses the synthetic builder from the
    core post_game_score tests."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE matches (
            match_id          TEXT PRIMARY KEY,
            has_timeline      INTEGER,
            map_id            INTEGER,
            queue_id          INTEGER,
            game_creation_ts  INTEGER
        );
        CREATE TABLE teams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            team_id         INTEGER,
            win             INTEGER
        );
        CREATE TABLE timeline_frames (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            timestamp_ms    INTEGER,
            participant_id  INTEGER,
            total_gold      INTEGER,
            xp              INTEGER,
            current_gold    INTEGER,
            level           INTEGER,
            minions_killed  INTEGER
        );
        CREATE TABLE timeline_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            timestamp_ms    INTEGER,
            event_type      TEXT,
            killer_id       INTEGER,
            victim_id       INTEGER,
            assisting_ids_json TEXT,
            building_type   TEXT,
            tower_type      TEXT,
            team_id         INTEGER,
            monster_type    TEXT,
            monster_subtype TEXT,
            level_up_type   TEXT,
            level           INTEGER
        );
    """)
    conn.execute(
        "INSERT INTO matches(match_id, has_timeline, map_id, queue_id, "
        "game_creation_ts) VALUES (?, 1, 11, 420, 0)",
        (match_id,),
    )
    conn.execute(
        "INSERT INTO teams(match_id, team_id, win) VALUES (?, 0, 1)",
        (match_id,),
    )
    conn.execute(
        "INSERT INTO teams(match_id, team_id, win) VALUES (?, 1, 0)",
        (match_id,),
    )
    # Two frames + three strong events.
    for pid in range(1, 11):
        conn.execute(
            "INSERT INTO timeline_frames(match_id, timestamp_ms, participant_id, "
            "total_gold, xp) VALUES (?,?,?,?,?)",
            (match_id, 0, pid, 500, 0),
        )
    for pid in range(1, 6):
        conn.execute(
            "INSERT INTO timeline_frames(match_id, timestamp_ms, participant_id, "
            "total_gold, xp) VALUES (?,?,?,?,?)",
            (match_id, 300_000, pid, 3000, 2000),
        )
    for pid in range(6, 11):
        conn.execute(
            "INSERT INTO timeline_frames(match_id, timestamp_ms, participant_id, "
            "total_gold, xp) VALUES (?,?,?,?,?)",
            (match_id, 300_000, pid, 1800, 1200),
        )
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, victim_id, assisting_ids_json) VALUES (?,?,?,?,?,?)",
        (match_id, 60_000, "CHAMPION_KILL", 5, 7, "[]"),
    )
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, monster_type, monster_subtype) VALUES (?,?,?,?,?,?)",
        (match_id, 240_000, "ELITE_MONSTER_KILL", 3, "DRAGON", "WATER_DRAGON"),
    )
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, building_type, tower_type, team_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (match_id, 300_000, "BUILDING_KILL", 4, "TOWER_BUILDING",
         "OUTER_TURRET", 200),
    )
    conn.commit()
    conn.close()


class TestPostGameWpaRoute(unittest.TestCase):
    """End-to-end route tests using a temporary SQLite DB."""

    def setUp(self):
        # Reset module-level caches each test so cache hits don't leak
        # between tests.
        rpgw._CACHE.clear()
        rpgw._MODEL_CACHE["mtime"] = None
        rpgw._MODEL_CACHE["model"] = None

    def _serve(self, path: str, db_path: Path, model_path: Path | None = None):
        with mock.patch.object(rpgw, "_REWIND_DB", db_path):
            with mock.patch.object(rpgw, "_MODEL_PATH",
                                   model_path or db_path.parent / "absent.json"):
                h = _StubHandler(path)
                rpgw._serve_post_game_wpa(h)
                return h.responses

    def test_missing_match_id_returns_400(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _seed_db(db)
            resp = self._serve("/api/post-game-wpa", db)
            self.assertEqual(len(resp), 1)
            status, body, ct = resp[0]
            self.assertEqual(status, 400)
            payload = json.loads(body)
            self.assertFalse(payload["ok"])
            self.assertIn("match_id required", payload["error"])

    def test_empty_match_id_returns_400(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _seed_db(db)
            resp = self._serve("/api/post-game-wpa?match_id=", db)
            self.assertEqual(resp[0][0], 400)

    def test_db_absent_returns_503(self):
        with tempfile.TemporaryDirectory() as td:
            absent = Path(td) / "nope.db"  # not created
            resp = self._serve("/api/post-game-wpa?match_id=X", absent)
            status, body, ct = resp[0]
            self.assertEqual(status, 503)
            self.assertIn("rewind_history.db missing", json.loads(body)["error"])

    def test_unknown_match_id_returns_404(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _seed_db(db)
            resp = self._serve("/api/post-game-wpa?match_id=DOES_NOT_EXIST", db)
            status, body, ct = resp[0]
            self.assertEqual(status, 404)
            payload = json.loads(body)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["match_id"], "DOES_NOT_EXIST")

    def test_real_match_returns_200_with_events(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _seed_db(db, "M_OK")
            resp = self._serve("/api/post-game-wpa?match_id=M_OK", db)
            status, body, ct = resp[0]
            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["match_id"], "M_OK")
            self.assertIn("events", payload)
            self.assertIn("top_phases", payload)
            self.assertEqual(payload["event_count"], 3)
            # Fallback model used when no file present.
            self.assertEqual(payload["model"], "fallback")
            self.assertIn("elapsed_ms", payload)
            self.assertFalse(payload["cached"])

    def test_second_request_is_cached(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _seed_db(db, "M_CACHE")
            self._serve("/api/post-game-wpa?match_id=M_CACHE", db)
            resp = self._serve("/api/post-game-wpa?match_id=M_CACHE", db)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["cached"])

    def test_trained_model_switches_signature(self):
        """When a model file is dropped in mid-session, the cache key
        must change so the prior fallback payload doesn't get served."""
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            _seed_db(db, "M_MODEL")
            model_path = Path(td) / "model.json"

            # First request - no model file.
            resp1 = self._serve("/api/post-game-wpa?match_id=M_MODEL",
                                db, model_path)
            self.assertEqual(json.loads(resp1[0][1])["model"], "fallback")

            # Write a tiny zero-weight model.
            m = pgs.WpaModel(
                weights=(0.0,) * pgs.WPA_FEATURE_COUNT,
                feature_names=pgs.FEATURE_NAMES,
                n_samples=99,
            )
            pgs.save_model(m, model_path)
            # Force mtime refresh.
            rpgw._MODEL_CACHE["mtime"] = None

            resp2 = self._serve("/api/post-game-wpa?match_id=M_MODEL",
                                db, model_path)
            payload2 = json.loads(resp2[0][1])
            self.assertEqual(payload2["model"], "trained")
            self.assertFalse(payload2["cached"])  # new sig -> miss


class TestModelSignature(unittest.TestCase):
    def test_no_file_returns_fallback_sig(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(rpgw, "_MODEL_PATH",
                                   Path(td) / "absent.json"):
                rpgw._MODEL_CACHE["mtime"] = None
                rpgw._MODEL_CACHE["model"] = None
                m, sig = rpgw._current_model()
                self.assertIsNone(m)
                self.assertEqual(sig, "fallback")

    def test_trained_model_signature(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            m = pgs.WpaModel(
                weights=(0.1,) * pgs.WPA_FEATURE_COUNT,
                feature_names=pgs.FEATURE_NAMES,
                n_samples=123,
            )
            pgs.save_model(m, p)
            with mock.patch.object(rpgw, "_MODEL_PATH", p):
                rpgw._MODEL_CACHE["mtime"] = None
                rpgw._MODEL_CACHE["model"] = None
                got_model, sig = rpgw._current_model()
                self.assertIsNotNone(got_model)
                self.assertEqual(sig, f"v{m.version}.n123")


class TestRouteRegistration(unittest.TestCase):
    def test_route_listed_in_get(self):
        # Ensure GET_ROUTES is non-empty and the matcher hits the right path.
        self.assertEqual(len(rpgw.GET_ROUTES), 1)
        matcher, fn = rpgw.GET_ROUTES[0]
        self.assertTrue(matcher("/api/post-game-wpa"))
        self.assertTrue(matcher("/api/post-game-wpa?match_id=X"))
        self.assertFalse(matcher("/api/post-game-wpa-x"))
        self.assertFalse(matcher("/api/other"))

    def test_dispatch_registers_routes(self):
        from dashboard import _dispatch
        # Reset gather cache so re-init picks up our route.
        _dispatch._GET_CACHE = None
        routes = _dispatch._gather_get()
        # Look for our matcher on /api/post-game-wpa.
        found = any(
            matcher("/api/post-game-wpa?match_id=X")
            for matcher, _ in routes
        )
        self.assertTrue(found, "post-game-wpa not registered in _dispatch")


if __name__ == "__main__":
    unittest.main()
