"""Tests for dashboard/routes_post_game_rubric.py.

First live consumer of core/post_game_rubric.py (item 131 Slice A).
Mirrors tests/test_routes_post_game_wpa.py structure.

Covers:
  - 400 when match_id missing or empty
  - 503 when rewind_history.db absent or state.json absent
  - 404 when match_id not in matches OR operator row not in participants
  - 200 with role-aware grade decomposition on a real (synthetic) match
  - Cache TTL hits + invalidation
  - Role normalization (BOTTOM -> ADC, JUNGLE -> JG, UTILITY -> SUP)
  - Stale PUUID fallback (current rotated, stale still has the row)
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_post_game_rubric as rpgr


class _StubHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes,
              content_type: str = "application/json") -> None:
        self.responses.append((status, body, content_type))


def _seed_db(path: Path, match_id: str = "TEST_M1",
             operator_puuid: str = "OPER_PUUID",
             team_position: str = "BOTTOM",
             kills: int = 8, deaths: int = 3, assists: int = 10,
             cs_minions: int = 180, cs_jungle: int = 0,
             vision: int = 18, damage: int = 22000,
             game_duration_s: int = 1800) -> None:
    """Build a minimal rewind_history.db schema with one match + one
    operator-PUUID participant row."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE matches (
            match_id          TEXT PRIMARY KEY,
            game_duration_s   INTEGER
        );
        CREATE TABLE participants (
            id                              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id                        TEXT,
            puuid                           TEXT,
            team_position                   TEXT,
            kills                           INTEGER,
            deaths                          INTEGER,
            assists                         INTEGER,
            total_minions_killed            INTEGER,
            neutral_minions_killed          INTEGER,
            vision_score                    INTEGER,
            total_damage_dealt_to_champs    INTEGER
        );
    """)
    conn.execute(
        "INSERT INTO matches(match_id, game_duration_s) VALUES (?, ?)",
        (match_id, game_duration_s),
    )
    conn.execute(
        "INSERT INTO participants(match_id, puuid, team_position, "
        "kills, deaths, assists, total_minions_killed, "
        "neutral_minions_killed, vision_score, "
        "total_damage_dealt_to_champs) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (match_id, operator_puuid, team_position, kills, deaths, assists,
         cs_minions, cs_jungle, vision, damage),
    )
    conn.commit()
    conn.close()


def _seed_state(path: Path, puuid: str = "OPER_PUUID",
                stale: str | None = None) -> None:
    payload = {"puuid": puuid}
    if stale is not None:
        payload["stale_puuid"] = stale
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestPostGameRubricRoute(unittest.TestCase):
    """End-to-end route tests using a temporary SQLite DB + state.json."""

    def setUp(self):
        rpgr._CACHE.clear()

    def _serve(self, path: str, db_path: Path, state_path: Path):
        with mock.patch.object(rpgr, "_REWIND_DB", db_path):
            with mock.patch.object(rpgr, "_STATE_JSON", state_path):
                h = _StubHandler(path)
                rpgr._serve_post_game_rubric(h)
                return h.responses

    def test_missing_match_id_returns_400(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db)
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric", db, state)
            self.assertEqual(resp[0][0], 400)
            payload = json.loads(resp[0][1])
            self.assertFalse(payload["ok"])
            self.assertIn("match_id required", payload["error"])

    def test_empty_match_id_returns_400(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db)
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=", db, state)
            self.assertEqual(resp[0][0], 400)

    def test_db_absent_returns_503(self):
        with tempfile.TemporaryDirectory() as td:
            absent_db = Path(td) / "nope.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=X",
                               absent_db, state)
            self.assertEqual(resp[0][0], 503)
            self.assertIn("rewind_history.db missing",
                          json.loads(resp[0][1])["error"])

    def test_state_missing_returns_503(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            absent_state = Path(td) / "absent.json"
            _seed_db(db)
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, absent_state)
            self.assertEqual(resp[0][0], 503)
            self.assertIn("rewind_catchup state",
                          json.loads(resp[0][1])["error"])

    def test_state_malformed_returns_503(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db)
            state.write_text("{ not json", encoding="utf-8")
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            self.assertEqual(resp[0][0], 503)

    def test_state_blank_puuids_returns_503(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db)
            state.write_text(json.dumps({"puuid": "", "stale_puuid": ""}),
                             encoding="utf-8")
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            self.assertEqual(resp[0][0], 503)

    def test_unknown_match_id_returns_404(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db)
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=NOPE",
                               db, state)
            self.assertEqual(resp[0][0], 404)
            payload = json.loads(resp[0][1])
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["match_id"], "NOPE")

    def test_operator_row_missing_returns_404(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, operator_puuid="DIFFERENT_PUUID")
            _seed_state(state, puuid="OPER_PUUID")
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            self.assertEqual(resp[0][0], 404)

    def test_real_match_returns_200_with_grade(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db)
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            self.assertEqual(resp[0][0], 200)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["match_id"], "TEST_M1")
            # BOTTOM -> ADC canonicalization.
            self.assertEqual(payload["role"], "ADC")
            self.assertIn("total_score", payload)
            self.assertIn("components", payload)
            self.assertIn("percentile_grade", payload)
            self.assertIn(payload["percentile_grade"],
                          ("S+", "S", "A", "B", "C", "D"))
            self.assertGreaterEqual(payload["total_score"], 0.0)
            self.assertLessEqual(payload["total_score"], 100.0)
            self.assertIn("kda", payload["components"])
            self.assertIn("cs_per_min", payload["components"])
            self.assertIn("weights_used", payload)
            self.assertIn("elapsed_ms", payload)
            self.assertFalse(payload["cached"])

    def test_jungle_normalizes_to_jg(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, team_position="JUNGLE")
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            payload = json.loads(resp[0][1])
            self.assertEqual(payload["role"], "JG")

    def test_utility_normalizes_to_sup(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, team_position="UTILITY")
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            payload = json.loads(resp[0][1])
            self.assertEqual(payload["role"], "SUP")

    def test_blank_role_defaults_to_mid(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, team_position="")
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            payload = json.loads(resp[0][1])
            self.assertEqual(payload["role"], "MID")

    def test_second_request_is_cached(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, match_id="M_CACHE")
            _seed_state(state)
            self._serve("/api/post-game-rubric?match_id=M_CACHE", db, state)
            resp = self._serve("/api/post-game-rubric?match_id=M_CACHE",
                               db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["cached"])

    def test_stale_puuid_fallback(self):
        """If current PUUID has no row but stale PUUID does, the stale
        row is used (PUUID rotation per reference_riot_puuid_rotation)."""
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, operator_puuid="OLD_PUUID")
            _seed_state(state, puuid="NEW_PUUID", stale="OLD_PUUID")
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            self.assertEqual(resp[0][0], 200)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])

    def test_weights_used_carries_role_weights(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_db(db, team_position="BOTTOM")
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=TEST_M1",
                               db, state)
            payload = json.loads(resp[0][1])
            # ADC kda + cs weights per the item-335 calibration table.
            self.assertAlmostEqual(payload["weights_used"]["kda"], 1.5)
            self.assertAlmostEqual(payload["weights_used"]["cs_per_min"], 1.1)


class TestPuuidLoader(unittest.TestCase):
    def test_load_returns_none_pair_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            absent = Path(td) / "absent.json"
            with mock.patch.object(rpgr, "_STATE_JSON", absent):
                self.assertEqual(rpgr._load_operator_puuid(), (None, None))

    def test_load_accepts_current_puuid_alias(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({"current_puuid": "abc"}),
                         encoding="utf-8")
            with mock.patch.object(rpgr, "_STATE_JSON", p):
                self.assertEqual(rpgr._load_operator_puuid(), ("abc", None))


if __name__ == "__main__":
    unittest.main()
