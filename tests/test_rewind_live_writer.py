"""Tests for ``lib/rewind_live_writer.py`` - live post-gameEnd writer.

Coverage:
  * SchedulerTests - Timer is scheduled, daemon=True, non-blocking
  * PuuidResolverTests - state.json present / absent / malformed
  * IdempotencyTests - skip when match already in DB
  * FailureModeTests - 404 silent / no api key / timeout retry / short
    game gate / write errors swallowed
  * WireSeamTests - on_game_end imports + calls schedule_live_insert
    inside an isolated try/except wrapper
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import rewind_live_writer as rlw  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_matches_table(db_path: Path, match_ids: list[str]) -> None:
    """Create the minimum schema + seed given match_ids in the matches table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS matches ("
            "match_id TEXT PRIMARY KEY, "
            "game_duration_s INTEGER, "
            "fetched_at TEXT)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO matches (match_id, game_duration_s, fetched_at) "
            "VALUES (?, ?, ?)",
            [(mid, 1000, "test") for mid in match_ids],
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SchedulerTests
# ---------------------------------------------------------------------------

class SchedulerTests(unittest.TestCase):
    """schedule_live_insert is non-blocking + spawns a daemon Timer."""

    def test_returns_immediately_without_blocking(self):
        called: list[float] = []

        def slow_worker(*args, **kwargs):
            time.sleep(5.0)
            called.append(time.time())

        # Use tiny delay so the Timer would fire if we waited, but
        # we won't.
        with mock.patch.object(rlw, "_do_live_fetch_and_insert", slow_worker):
            t0 = time.time()
            rlw.schedule_live_insert(object(), delay_s=0.05)
            elapsed = time.time() - t0
        # Must return well under 100ms.
        self.assertLess(elapsed, 0.5)

    def test_spawns_daemon_timer(self):
        captured: dict[str, object] = {}

        original_timer = threading.Timer

        class _SpyTimer(original_timer):
            def start(self):
                captured["daemon"] = self.daemon
                captured["interval"] = self.interval
                captured["function"] = self.function
                # Don't actually fire.

        with mock.patch.object(rlw.threading, "Timer", _SpyTimer):
            rlw.schedule_live_insert(object(), delay_s=12.5)

        self.assertTrue(captured.get("daemon"), "Timer must be daemon=True")
        self.assertEqual(captured.get("interval"), 12.5)
        self.assertEqual(captured.get("function"), rlw._do_live_fetch_and_insert)

    def test_runtime_error_at_schedule_swallowed(self):
        """A late-shutdown RuntimeError on Timer.start must not bubble."""
        with mock.patch.object(rlw.threading, "Timer") as MockTimer:
            instance = mock.MagicMock()
            instance.start.side_effect = RuntimeError("can't start new thread")
            MockTimer.return_value = instance
            # Must not raise.
            try:
                rlw.schedule_live_insert(object(), delay_s=1.0)
            except Exception as exc:  # noqa: BLE001 - test guard
                self.fail(f"schedule_live_insert leaked exception: {exc!r}")


# ---------------------------------------------------------------------------
# PuuidResolverTests
# ---------------------------------------------------------------------------

class PuuidResolverTests(unittest.TestCase):
    """_resolve_latest_puuid handles present / absent / malformed state."""

    def setUp(self):
        self._patcher = mock.patch.object(
            rlw, "STATE_PATH", Path(self.makeTempPath())
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def makeTempPath(self) -> str:
        import tempfile
        fd, name = tempfile.mkstemp(suffix=".json")
        import os
        os.close(fd)
        Path(name).unlink()  # Start absent.
        self.addCleanup(lambda: Path(name).unlink(missing_ok=True))
        return name

    def test_absent_state_returns_none(self):
        self.assertFalse(rlw.STATE_PATH.exists())
        self.assertIsNone(rlw._resolve_latest_puuid())

    def test_present_state_returns_puuid(self):
        rlw.STATE_PATH.write_text(
            json.dumps({"puuid": "abc-puuid-123"}),
            encoding="utf-8",
        )
        self.assertEqual(rlw._resolve_latest_puuid(), "abc-puuid-123")

    def test_empty_string_returns_none(self):
        rlw.STATE_PATH.write_text(
            json.dumps({"puuid": ""}),
            encoding="utf-8",
        )
        self.assertIsNone(rlw._resolve_latest_puuid())

    def test_missing_key_returns_none(self):
        rlw.STATE_PATH.write_text(
            json.dumps({"other_key": "foo"}),
            encoding="utf-8",
        )
        self.assertIsNone(rlw._resolve_latest_puuid())

    def test_malformed_json_returns_none(self):
        rlw.STATE_PATH.write_text("not json {{{", encoding="utf-8")
        self.assertIsNone(rlw._resolve_latest_puuid())

    def test_empty_file_returns_none(self):
        rlw.STATE_PATH.write_text("", encoding="utf-8")
        self.assertIsNone(rlw._resolve_latest_puuid())

    def test_non_dict_root_returns_none(self):
        rlw.STATE_PATH.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(rlw._resolve_latest_puuid())

    def test_non_string_puuid_returns_none(self):
        rlw.STATE_PATH.write_text(
            json.dumps({"puuid": 12345}),
            encoding="utf-8",
        )
        self.assertIsNone(rlw._resolve_latest_puuid())


# ---------------------------------------------------------------------------
# IdempotencyTests
# ---------------------------------------------------------------------------

class IdempotencyTests(unittest.TestCase):
    """_match_already_present + skip-on-already-present in the work fn."""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rlw_idem_"))
        self.db_path = self.tmpdir / "rewind_history.db"
        self._db_patcher = mock.patch.object(rlw, "DB_PATH", self.db_path)
        self._db_patcher.start()
        self.addCleanup(self._db_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_true_for_existing_match(self):
        _seed_matches_table(self.db_path, ["NA1_5560540832"])
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertTrue(
                rlw._match_already_present(conn, "NA1_5560540832")
            )
        finally:
            conn.close()

    def test_returns_false_for_missing_match(self):
        _seed_matches_table(self.db_path, ["NA1_OTHER"])
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertFalse(
                rlw._match_already_present(conn, "NA1_NOTYET")
            )
        finally:
            conn.close()

    def test_returns_false_on_sqlite_error(self):
        """Missing matches table - SQLite raises; the helper swallows."""
        # Don't seed - the table doesn't exist.
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertFalse(
                rlw._match_already_present(conn, "NA1_ANY")
            )
        finally:
            conn.close()

    def test_work_fn_skips_when_match_already_present(self):
        _seed_matches_table(self.db_path, ["NA1_DUP_ID"])

        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="puuid"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_DUP_ID"],
                ):
                    with mock.patch("core.riot_api.get_match") as get_match:
                        result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "already_present")
        self.assertEqual(result["match_id"], "NA1_DUP_ID")
        get_match.assert_not_called()


# ---------------------------------------------------------------------------
# FailureModeTests
# ---------------------------------------------------------------------------

class FailureModeTests(unittest.TestCase):
    """All failure modes return a status dict and never raise."""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rlw_fail_"))
        self.db_path = self.tmpdir / "rewind_history.db"
        self._db_patcher = mock.patch.object(rlw, "DB_PATH", self.db_path)
        self._db_patcher.start()
        self.addCleanup(self._db_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_puuid_returns_status(self):
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value=None):
            result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "no_puuid")

    def test_no_api_key_returns_status(self):
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=False):
                result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "no_api_key")

    def test_empty_ids_first_attempt_schedules_retry(self):
        """get_recent_matches returns empty list -> retry scheduled."""
        timer_spawned: list[bool] = []

        original_timer = threading.Timer

        class _NonFiringTimer(original_timer):
            def start(self):
                timer_spawned.append(True)
                # Don't actually fire.

        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=[],
                ):
                    with mock.patch.object(
                        rlw.threading, "Timer", _NonFiringTimer
                    ):
                        result = rlw._do_live_fetch_and_insert(is_retry=False)
        self.assertEqual(result["status"], "retry_scheduled")
        self.assertEqual(timer_spawned, [True])

    def test_empty_ids_retry_attempt_does_not_reschedule(self):
        """is_retry=True -> no further Timer scheduled."""
        timer_spawned: list[bool] = []

        original_timer = threading.Timer

        class _SpyTimer(original_timer):
            def start(self):
                timer_spawned.append(True)

        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=None,
                ):
                    with mock.patch.object(
                        rlw.threading, "Timer", _SpyTimer
                    ):
                        result = rlw._do_live_fetch_and_insert(is_retry=True)
        self.assertEqual(result["status"], "no_id")
        self.assertEqual(timer_spawned, [])

    def test_match_404_returns_silent_status(self):
        """get_match returns None (404 / 403 / event mode) - silent skip."""
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_FAKE_404"],
                ):
                    with mock.patch(
                        "core.riot_api.get_match", return_value=None
                    ):
                        result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "no_detail")
        self.assertEqual(result["match_id"], "NA1_FAKE_404")

    def test_short_game_skipped(self):
        """gameDuration < 180s -> short_game; no write."""
        short_detail = {"info": {"gameDuration": 60}}
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_SHORT_GAME"],
                ):
                    with mock.patch(
                        "core.riot_api.get_match",
                        return_value=short_detail,
                    ):
                        with mock.patch(
                            "core.riot_api.get_match_timeline",
                        ) as timeline_mock:
                            result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "short_game")
        self.assertEqual(result["duration_s"], 60)
        # Timeline should NOT be fetched for short games (we bail before).
        timeline_mock.assert_not_called()

    def test_zero_duration_treated_as_short(self):
        zero_detail = {"info": {"gameDuration": 0}}
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_ZERO"],
                ):
                    with mock.patch(
                        "core.riot_api.get_match",
                        return_value=zero_detail,
                    ):
                        result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "short_game")

    def test_write_error_returns_error_status(self):
        """sqlite3.Error during write_match is logged + swallowed."""
        full_detail = {"info": {"gameDuration": 1500}}
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_BAD_WRITE"],
                ):
                    with mock.patch(
                        "core.riot_api.get_match", return_value=full_detail
                    ):
                        with mock.patch(
                            "core.riot_api.get_match_timeline",
                            return_value=None,
                        ):
                            with mock.patch(
                                "scripts.rewind_catchup.write_match",
                                side_effect=sqlite3.Error("synthetic"),
                            ):
                                result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["match_id"], "NA1_BAD_WRITE")

    def test_unexpected_exception_in_write_swallowed(self):
        """Non-sqlite exception inside write_match is also caught."""
        full_detail = {"info": {"gameDuration": 1500}}
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_UNEXPECTED"],
                ):
                    with mock.patch(
                        "core.riot_api.get_match", return_value=full_detail
                    ):
                        with mock.patch(
                            "core.riot_api.get_match_timeline",
                            return_value=None,
                        ):
                            with mock.patch(
                                "scripts.rewind_catchup.write_match",
                                side_effect=KeyError("shape break"),
                            ):
                                # MUST not raise.
                                result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("cause"), "unexpected")

    def test_happy_path_writes_to_db(self):
        """Full successful round-trip via real write_match into real schema."""
        # Pre-create the matches table with the real production schema by
        # running the rewind_scraper SCHEMA - write_match expects all 28
        # columns. State.json also needs to exist for write_match's
        # load_state call.
        from scripts.rewind_scraper import SCHEMA

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

        # write_match calls scripts.rewind_catchup.load_state which
        # reads STATE_PATH; if absent it returns {} which is fine.
        full_detail = {
            "info": {
                "platformId": "NA1",
                "queueId": 420,
                "gameMode": "CLASSIC",
                "gameType": "MATCHED_GAME",
                "mapId": 11,
                "gameVersion": "16.10.501",
                "gameDuration": 1500,
                "gameCreation": 1700000000000,
                "gameEndTimestamp": 1700000150000,
                "endOfGameResult": "GameComplete",
                "tournamentCode": "",
                "participants": [],
                "teams": [],
            }
        }
        with mock.patch.object(rlw, "_resolve_latest_puuid", return_value="x"):
            with mock.patch("core.riot_api.is_configured", return_value=True):
                with mock.patch(
                    "core.riot_api.get_recent_matches",
                    return_value=["NA1_LIVE_OK"],
                ):
                    with mock.patch(
                        "core.riot_api.get_match", return_value=full_detail
                    ):
                        with mock.patch(
                            "core.riot_api.get_match_timeline",
                            return_value=None,
                        ):
                            result = rlw._do_live_fetch_and_insert()
        self.assertEqual(result["status"], "ok", f"got: {result}")
        self.assertEqual(result["match_id"], "NA1_LIVE_OK")
        self.assertEqual(result["duration_s"], 1500)
        # Verify the row landed.
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT match_id FROM matches WHERE match_id = ?",
                ("NA1_LIVE_OK",),
            ).fetchone()
            self.assertIsNotNone(row)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# WireSeamTests
# ---------------------------------------------------------------------------

class WireSeamTests(unittest.TestCase):
    """The frozen-file wire is present in app/_game_lifecycle.py."""

    def test_wire_imports_module(self):
        path = ROOT / "app" / "_game_lifecycle.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(
            "from lib.rewind_live_writer import schedule_live_insert",
            text,
            "Wire must import schedule_live_insert from lib.rewind_live_writer",
        )

    def test_wire_invokes_schedule_with_app(self):
        path = ROOT / "app" / "_game_lifecycle.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(
            "schedule_live_insert(app)",
            text,
            "Wire must call schedule_live_insert(app) at on_game_end",
        )

    def test_wire_lives_inside_on_game_end(self):
        """The wire is positioned inside on_game_end (not on_game_start)."""
        path = ROOT / "app" / "_game_lifecycle.py"
        text = path.read_text(encoding="utf-8")
        # Find on_game_end span up to start of next def.
        end_idx = text.find("def on_game_end(self)")
        self.assertGreater(end_idx, 0, "on_game_end def must exist")
        next_def_idx = text.find("\n    def ", end_idx + 5)
        if next_def_idx < 0:
            next_def_idx = len(text)
        snippet = text[end_idx:next_def_idx]
        self.assertIn("schedule_live_insert(app)", snippet,
                      "schedule_live_insert must be inside on_game_end")

    def test_wire_wrapped_in_try_except(self):
        """The wire is isolated so any error never bubbles into lifecycle."""
        path = ROOT / "app" / "_game_lifecycle.py"
        text = path.read_text(encoding="utf-8")
        # Locate the schedule call + check try/except surrounds it.
        idx = text.find("schedule_live_insert(app)")
        self.assertGreater(idx, 0)
        # Walk backward up to ~400 chars to find a "try:".
        prefix = text[max(0, idx - 600):idx]
        self.assertIn("try:", prefix,
                      "schedule_live_insert call must sit inside a try block")
        suffix = text[idx:idx + 600]
        self.assertIn("except", suffix,
                      "schedule_live_insert must have an except handler")


if __name__ == "__main__":
    unittest.main()
