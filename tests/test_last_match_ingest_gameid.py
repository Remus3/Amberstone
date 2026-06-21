"""Item 211 - /api/last-match/ingest must row-match by gameId, not "latest row".

Pre-fix race (operator-reported, Home page Recent-5):
  - the LCU agent fires /api/last-match/ingest on EndOfGame phase entry
  - Local performance_tracker.save_match writes the new match_history.db row
    a few seconds AFTER the LCU EndOfGame transition
  - The ingest's "ORDER BY timestamp DESC LIMIT 1" picked the PREVIOUS row,
    overwriting it with the new game's lcu_match_detail (and items)
  - When the new row finally wrote, no later ingest landed on it, so its
    items=[] forever. Result: items off-by-one against champion/grade
    across Home Recent-5 cards.

Post-fix:
  - matches schema gains game_id INTEGER DEFAULT 0 + idx_matches_game_id
  - Ingest resolves the target row by:
    (1) WHERE game_id = match_detail.gameId
    (2) fallback: gameCreation+gameDuration end-time within +/- 180s of
        matches.timestamp AND matches.game_id = 0  (legacy / pre-stamp rows)
    (3) no row yet -> enqueue retry up to ~60s; respond 202
  - On match, the row's game_id is stamped so re-ingest is idempotent.
  - Drain helper retries pending ingests every tick; expired entries drop.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


class StubHandler:
    def __init__(self, path: str = "/api/last-match/ingest"):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


def _detail(game_id: int, *, game_creation_ms: int, game_duration_s: int,
            tracked_puuid: str = "puuid-A", participant_champion_id: int = 51) -> dict:
    """Synthetic LCU /lol-match-history/v1/games/{gameId} payload."""
    return {
        "gameId": game_id,
        "gameCreation": game_creation_ms,
        "gameDuration": game_duration_s,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": tracked_puuid}},
        ],
        "participants": [
            {
                "participantId": 1,
                "championId": participant_champion_id,
                "stats": {
                    "item0": 1055, "item1": 3032, "item2": 3031,
                    "item3": 3094, "item4": 3036, "item5": 0,
                },
            },
        ],
    }


def _seed_row(db_path: Path, *, timestamp: str, champion: str = "Caitlyn",
              mode: str = "SR", grade: str = "C", game_id: int = 0,
              raw_data: str = "") -> int:
    """Insert a non-TFT row directly and return its id."""
    from core.match_db import MatchDB
    MatchDB(db_path)  # ensure schema migrated
    c = sqlite3.connect(str(db_path))
    try:
        cur = c.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade, game_id, raw_data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, mode, champion, grade, game_id, raw_data),
        )
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def _row(db_path: Path, mid: int) -> dict:
    c = sqlite3.connect(str(db_path))
    try:
        cur = c.execute(
            "SELECT id, mode, champion, game_id, raw_data FROM matches WHERE id = ?",
            (mid,),
        )
        r = cur.fetchone()
        if not r:
            return {}
        return {"id": r[0], "mode": r[1], "champion": r[2], "game_id": r[3],
                "raw_data": r[4]}
    finally:
        c.close()


class _IngestTestBase(unittest.TestCase):
    """Shared setUp: tempdir DB + patched _APP_DIR + fresh module state."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.app_dir = Path(self.tmpdir.name)
        (self.app_dir / "data").mkdir(parents=True, exist_ok=True)
        self.db_path = self.app_dir / "data" / "match_history.db"

        from dashboard import _context as _ctx
        from dashboard import routes_last_match as _rlm
        self._patch_ctx = mock.patch.object(_ctx, "APP_DIR", self.app_dir)
        self._patch_rlm = mock.patch.object(_rlm, "_APP_DIR", self.app_dir)
        self._patch_ctx.start()
        self._patch_rlm.start()
        # Reset retry queue between tests so state doesn't bleed.
        if hasattr(_rlm, "_INGEST_RETRY_QUEUE"):
            _rlm._INGEST_RETRY_QUEUE.clear()
        # Suppress lazy background drain thread so it never races test
        # assertions on the queue.
        _rlm._INGEST_RETRY_THREAD_STARTED = True
        # Eagerly create the empty DB so /api/last-match/ingest no-row path
        # exercises the queue branch instead of the missing-DB 503 branch.
        from core.match_db import MatchDB
        MatchDB(self.db_path)

    def tearDown(self):
        self._patch_ctx.stop()
        self._patch_rlm.stop()
        self.tmpdir.cleanup()


class SchemaMigrationTests(_IngestTestBase):
    """game_id column + idx_matches_game_id index exist + legacy ALTER."""

    def test_new_db_has_game_id_column_and_index(self):
        from core.match_db import MatchDB
        MatchDB(self.db_path)
        c = sqlite3.connect(str(self.db_path))
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(matches)")]
            self.assertIn("game_id", cols,
                          "matches table must carry game_id column")
            idxs = [r[1] for r in c.execute("PRAGMA index_list(matches)")]
            self.assertIn("idx_matches_game_id", idxs,
                          "idx_matches_game_id must be created on schema init")
        finally:
            c.close()

    def test_alter_legacy_db_adds_game_id_column(self):
        """A pre-fix DB (no game_id col) is migrated on MatchDB open."""
        # setUp eagerly created a full-schema DB; wipe it so we can write
        # the legacy narrow-table form this test exercises.
        try:
            self.db_path.unlink()
        except FileNotFoundError:
            pass
        c = sqlite3.connect(str(self.db_path))
        try:
            c.executescript(
                "CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "timestamp TEXT NOT NULL, mode TEXT NOT NULL, "
                "champion TEXT DEFAULT '', grade TEXT DEFAULT '', "
                "raw_data TEXT DEFAULT '');"
            )
            c.execute(
                "INSERT INTO matches (timestamp, mode, champion, grade, raw_data) "
                "VALUES (?, ?, ?, ?, ?)",
                ("2026-05-27 22:00:00", "SR", "Jinx", "C", ""),
            )
            c.commit()
        finally:
            c.close()

        from core.match_db import MatchDB
        MatchDB(self.db_path)  # must NOT raise; must ALTER TABLE in place.
        c = sqlite3.connect(str(self.db_path))
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(matches)")]
            self.assertIn("game_id", cols)
            # Existing row's game_id defaults to 0.
            cur = c.execute("SELECT game_id FROM matches WHERE champion='Jinx'")
            self.assertEqual(cur.fetchone()[0], 0)
        finally:
            c.close()


class IngestByGameIdTests(_IngestTestBase):
    """Primary path: gameId-matched row gets the detail; idempotent."""

    def test_ingest_stamps_matching_row_by_game_id(self):
        from dashboard import routes_last_match
        # Existing row pre-stamped with game_id = 5569828374
        mid = _seed_row(self.db_path, timestamp="2026-05-27 22:54:03",
                        champion="Jinx", grade="C", game_id=5569828374)
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=5569828374,
                game_creation_ms=int(time.time() * 1000),
                game_duration_s=1700,
            ),
        }
        h = StubHandler()
        routes_last_match._serve_last_match_ingest(h, body)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed().get("match_id"), mid)
        rd = json.loads(_row(self.db_path, mid)["raw_data"])
        self.assertIn("lcu_match_detail", rd)
        self.assertEqual(rd["lcu_match_detail"]["gameId"], 5569828374)
        self.assertEqual(rd["tracked_puuid"], "puuid-A")

    def test_reingest_is_idempotent(self):
        from dashboard import routes_last_match
        mid = _seed_row(self.db_path, timestamp="2026-05-27 22:54:03",
                        champion="Jinx", game_id=5569828374)
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=5569828374,
                game_creation_ms=int(time.time() * 1000),
                game_duration_s=1700,
            ),
        }
        for _ in range(3):
            h = StubHandler()
            routes_last_match._serve_last_match_ingest(h, body)
            self.assertEqual(h.last_status, 200)
            self.assertEqual(h.parsed().get("match_id"), mid)
        # Exactly one row in total (no fan-out).
        c = sqlite3.connect(str(self.db_path))
        try:
            n = c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        finally:
            c.close()
        self.assertEqual(n, 1)

    def test_ingest_stamps_game_id_on_unstamped_match(self):
        """Legacy row at game_id=0 still gets stamped via gameCreation window
        fallback so re-ingest is gameId-keyed thereafter."""
        from dashboard import routes_last_match
        # Row timestamp = game end time. Compute window so window matches.
        now_unix = int(time.time())
        ts = datetime.fromtimestamp(now_unix).strftime("%Y-%m-%d %H:%M:%S")
        mid = _seed_row(self.db_path, timestamp=ts, champion="Caitlyn",
                        game_id=0)
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=5569999999,
                game_creation_ms=(now_unix - 1700) * 1000,
                game_duration_s=1700,
            ),
        }
        h = StubHandler()
        routes_last_match._serve_last_match_ingest(h, body)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(_row(self.db_path, mid)["game_id"], 5569999999,
                         "matched-by-window row must have game_id stamped")


class IngestTimestampFallbackTests(_IngestTestBase):
    """gameCreation+gameDuration end-time within +/- 180s of an
    unstamped non-TFT row matches; outside the window does not."""

    def test_match_within_window(self):
        from dashboard import routes_last_match
        now_unix = int(time.time())
        ts = datetime.fromtimestamp(now_unix - 30).strftime("%Y-%m-%d %H:%M:%S")
        mid = _seed_row(self.db_path, timestamp=ts, champion="Caitlyn",
                        game_id=0)
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=5569999999,
                game_creation_ms=(now_unix - 1700) * 1000,
                game_duration_s=1700,
            ),
        }
        h = StubHandler()
        routes_last_match._serve_last_match_ingest(h, body)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed().get("match_id"), mid)

    def test_no_match_outside_window_returns_202_queued(self):
        from dashboard import routes_last_match
        # Row timestamp 1 hour in the past; ingest is for a game ending now.
        long_ago = int(time.time()) - 3600
        ts = datetime.fromtimestamp(long_ago).strftime("%Y-%m-%d %H:%M:%S")
        _seed_row(self.db_path, timestamp=ts, champion="Jinx", game_id=0)
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=5569999999,
                game_creation_ms=(int(time.time()) - 1700) * 1000,
                game_duration_s=1700,
            ),
        }
        h = StubHandler()
        routes_last_match._serve_last_match_ingest(h, body)
        self.assertEqual(h.last_status, 202)
        self.assertTrue(h.parsed().get("queued"))


class IngestRetryQueueTests(_IngestTestBase):
    """No row yet at ingest time -> queue. Later drain finds the row."""

    def test_queue_drains_when_matching_row_appears(self):
        from dashboard import routes_last_match
        # No row yet.
        gid = 5570000001
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=gid,
                game_creation_ms=int(time.time() * 1000),
                game_duration_s=1700,
            ),
        }
        h = StubHandler()
        routes_last_match._serve_last_match_ingest(h, body)
        self.assertEqual(h.last_status, 202)
        self.assertEqual(len(routes_last_match._INGEST_RETRY_QUEUE), 1)

        # Operator's local writer finally lands. game_id stamped.
        mid = _seed_row(self.db_path, timestamp="2026-05-27 22:54:03",
                        champion="Caitlyn", game_id=gid)
        # Drain once.
        drained = routes_last_match._drain_ingest_queue_once()
        self.assertEqual(drained, 1)
        self.assertEqual(len(routes_last_match._INGEST_RETRY_QUEUE), 0)
        rd = json.loads(_row(self.db_path, mid)["raw_data"])
        self.assertIn("lcu_match_detail", rd)
        self.assertEqual(rd["lcu_match_detail"]["gameId"], gid)

    def test_queue_entry_ages_out_after_deadline(self):
        from dashboard import routes_last_match
        gid = 5570000002
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=gid,
                game_creation_ms=int(time.time() * 1000),
                game_duration_s=1700,
            ),
        }
        # Manually shove a stale entry so we don't have to wait 60s.
        routes_last_match._INGEST_RETRY_QUEUE.append(
            (time.time() - 1, body)  # deadline already past
        )
        dropped = routes_last_match._drain_ingest_queue_once()
        self.assertEqual(dropped, 0)
        self.assertEqual(len(routes_last_match._INGEST_RETRY_QUEUE), 0,
                         "expired entries must be evicted")


class WrongRowRegressionItem211Tests(_IngestTestBase):
    """Item 211 pin: race must NOT attach new game's items to prior row."""

    def test_race_does_not_overwrite_older_row(self):
        from dashboard import routes_last_match
        # Older Jinx row, no game_id, timestamped 1 hour ago.
        long_ago = int(time.time()) - 3600
        ts_old = datetime.fromtimestamp(long_ago).strftime("%Y-%m-%d %H:%M:%S")
        mid_jinx = _seed_row(self.db_path, timestamp=ts_old, champion="Jinx",
                             game_id=0, raw_data=json.dumps({"sentinel": "untouched"}))

        # LCU ingest arrives for a Caitlyn game ending NOW. New row hasn't
        # been written by performance_tracker yet (race window).
        gid = 5570000003
        body = {
            "tracked_puuid": "puuid-A",
            "match_detail": _detail(
                game_id=gid,
                game_creation_ms=(int(time.time()) - 1700) * 1000,
                game_duration_s=1700,
                participant_champion_id=51,  # Caitlyn
            ),
        }
        h = StubHandler()
        routes_last_match._serve_last_match_ingest(h, body)

        # Pre-fix behavior: status would be 200 + Jinx row stomped.
        # Post-fix: 202 queued, Jinx row untouched.
        self.assertEqual(h.last_status, 202,
                         "ingest must NOT silently attach new game's detail to "
                         "the most-recent row when nothing actually matches "
                         "by gameId or by timestamp window")
        rd = json.loads(_row(self.db_path, mid_jinx)["raw_data"])
        self.assertEqual(rd, {"sentinel": "untouched"},
                         "older Jinx row's raw_data must be byte-untouched")
        self.assertEqual(_row(self.db_path, mid_jinx)["game_id"], 0)


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        p = Path(__file__)
        data = p.read_bytes()
        # CLAUDE.md hard rule + drift guard.
        offending = [b for b in data if b >= 0x80]
        self.assertEqual(offending, [],
                         "test file must be 7-bit ASCII per CLAUDE.md")


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
