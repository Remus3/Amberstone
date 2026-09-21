"""Regression: a Riot 429 was written into rewind_history.db as a PERMANENT answer.

Defect (2026-09-20). Every Match-V5 helper returns a bare None for BOTH "Riot
has no such resource" and "Riot rate-limited us". The rewind writers read that
None as "no data":

  * lib/rewind_live_writer.py - a 429 on the timeline fetch wrote the match
    with has_timeline=0, and nothing ever revisits a written match, so the
    timeline was lost for good. A 429 on the match-id fetch burned the single
    "event mode" retry and gave up. A 429 on the detail fetch was dropped.
  * scripts/rewind_catchup.py - the same None -> has_timeline=0 collapse in
    hydrate_match, a dropped detail on 429, and a 429 mid-pagination treated
    as end-of-window, after which newer matches advance the window past the
    unfetched older ones.

Fix: callers read ``riot_api.track_outcomes().rate_limited``; a 429 gets a
bounded in-call retry, and if it persists the match is parked in the
``fetch_retry`` queue table instead of being recorded as absent. The catchup
drains that queue (bounded by ``MAX_RETRY_RUNS`` across runs). A real 404/403
is still permanent - event-mode matches (ARAM Mayhem, queue 2400 / KIWI) have
no Match-V5 timeline and has_timeline=0 is CORRECT for them.

Backfill: scripts/rewind_timeline_backfill.py enqueues the already-written
has_timeline=0 rows that are not event-mode.

Offline throughout: the Riot helpers are stubbed and publish their outcome
through ``riot_api._record_outcome``, the seam ``_call_ex`` uses.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import riot_api as RA  # noqa: E402
from lib import rewind_live_writer as rlw  # noqa: E402
from scripts import rewind_catchup as rc  # noqa: E402
from scripts import rewind_scraper as rs  # noqa: E402
from scripts import rewind_timeline_backfill as bf  # noqa: E402

NO_SLEEP = (lambda _s: None)


def _detail(queue_id: int = 400, game_mode: str = "CLASSIC") -> dict:
    return {"info": {
        "queueId": queue_id, "gameMode": game_mode, "gameDuration": 1800,
        "gameCreation": 1_700_000_000_000, "platformId": "NA1",
        "gameVersion": "16.14.1", "participants": [], "teams": [],
    }}


def _timeline() -> dict:
    return {"info": {"frames": [
        {"timestamp": 0,
         "participantFrames": {"1": {"participantId": 1, "totalGold": 500},
                               "2": {"participantId": 2, "totalGold": 500}},
         "events": [{"type": "ITEM_PURCHASED", "timestamp": 10,
                     "participantId": 1, "itemId": 1055}]},
        {"timestamp": 60000,
         "participantFrames": {"1": {"participantId": 1, "totalGold": 900},
                               "2": {"participantId": 2, "totalGold": 800}},
         "events": []},
    ]}}


def _rate_limited(*_a, **_k):
    RA._record_outcome("429")
    return None


def _not_found(*_a, **_k):
    RA._record_outcome("404")
    return None


def _returns(value):
    def _fn(*_a, **_k):
        RA._record_outcome("ok")
        return value
    return _fn


def _sequence(*fns):
    """Call each stub in turn (the last one repeats)."""
    calls = {"n": 0}

    def _fn(*a, **k):
        i = min(calls["n"], len(fns) - 1)
        calls["n"] += 1
        return fns[i](*a, **k)
    _fn.calls = calls
    return _fn


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "rewind_history.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(rs.SCHEMA)
        conn.commit()
        conn.close()
        self._patches = [
            mock.patch.object(rc, "STATE_PATH", self.tmp / "state.json"),
            mock.patch.object(rc, "DB_PATH", self.db_path),
            mock.patch.object(rlw, "DB_PATH", self.db_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def q(self, sql: str, args: tuple = ()):
        c = self.conn()
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def retry_rows(self):
        c = self.conn()
        try:
            rc.ensure_retry_table(c)
            return c.execute(
                "SELECT match_id, kind, attempts FROM fetch_retry "
                "ORDER BY match_id").fetchall()
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Shared fetch primitive
# ---------------------------------------------------------------------------

class FetchPrimitiveTests(unittest.TestCase):
    def test_rate_limit_then_success_is_ok(self):
        fn = _sequence(_rate_limited, _returns({"x": 1}))
        slept: list[float] = []
        res, status = rc.fetch_with_rate_limit_retry(
            fn, backoff_s=(1.0, 2.0), sleep=slept.append)
        self.assertEqual(status, rc.FETCH_OK)
        self.assertEqual(res, {"x": 1})
        self.assertEqual(slept, [1.0])

    def test_persistent_rate_limit_is_bounded_and_reported(self):
        fn = _sequence(_rate_limited)
        slept: list[float] = []
        res, status = rc.fetch_with_rate_limit_retry(
            fn, backoff_s=(1.0, 2.0), sleep=slept.append)
        self.assertIsNone(res)
        self.assertEqual(status, rc.FETCH_RATE_LIMITED)
        self.assertEqual(fn.calls["n"], 3)
        self.assertEqual(slept, [1.0, 2.0])

    def test_not_found_is_absent_without_retry(self):
        fn = _sequence(_not_found)
        res, status = rc.fetch_with_rate_limit_retry(
            fn, backoff_s=(1.0, 2.0), sleep=NO_SLEEP)
        self.assertIsNone(res)
        self.assertEqual(status, rc.FETCH_ABSENT)
        self.assertEqual(fn.calls["n"], 1)


# ---------------------------------------------------------------------------
# Catchup
# ---------------------------------------------------------------------------

class CatchupHydrateTests(_DbCase):
    def test_timeline_429_is_rate_limited_not_absent(self):
        with mock.patch.object(RA, "get_match", _returns(_detail())), \
             mock.patch.object(RA, "get_match_timeline", _sequence(_rate_limited)):
            detail, timeline, d_st, t_st = rc.hydrate_match(
                "NA1_1", True, backoff_s=(0.0,), sleep=NO_SLEEP)
        self.assertIsNotNone(detail)
        self.assertIsNone(timeline)
        self.assertEqual(d_st, rc.FETCH_OK)
        self.assertEqual(t_st, rc.FETCH_RATE_LIMITED)

    def test_event_mode_timeline_404_is_absent(self):
        with mock.patch.object(RA, "get_match", _returns(_detail(2400, "KIWI"))), \
             mock.patch.object(RA, "get_match_timeline", _sequence(_not_found)):
            _d, timeline, _ds, t_st = rc.hydrate_match(
                "NA1_K", True, backoff_s=(0.0,), sleep=NO_SLEEP)
        self.assertIsNone(timeline)
        self.assertEqual(t_st, rc.FETCH_ABSENT)

    def test_record_hydrated_enqueues_on_timeline_429(self):
        c = self.conn()
        rc.record_hydrated(c, "NA1_1", _detail(), None, rc.FETCH_RATE_LIMITED)
        c.commit()
        c.close()
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])
        self.assertEqual(self.retry_rows(), [("NA1_1", "timeline", 0)])

    def test_record_hydrated_does_not_enqueue_event_mode_404(self):
        c = self.conn()
        rc.record_hydrated(c, "NA1_K", _detail(2400, "KIWI"), None, rc.FETCH_ABSENT)
        c.commit()
        c.close()
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])
        self.assertEqual(self.retry_rows(), [])


class CatchupPaginationTests(unittest.TestCase):
    def test_rate_limited_page_raises_instead_of_ending_window(self):
        pages = _sequence(_returns([f"NA1_{i}" for i in range(100)]),
                          _rate_limited)
        with mock.patch.object(RA, "get_recent_matches", pages):
            with self.assertRaises(rc.PaginationRateLimited):
                rc.collect_new_match_ids(
                    "p", 0, set(), backoff_s=(0.0,), sleep=NO_SLEEP)

    def test_empty_page_still_ends_window(self):
        with mock.patch.object(RA, "get_recent_matches", _returns([])):
            self.assertEqual(
                rc.collect_new_match_ids("p", 0, set(), sleep=NO_SLEEP), [])


class CatchupDrainTests(_DbCase):
    def _seed_written_without_timeline(self, mid: str = "NA1_1",
                                       stale_frames: int = 0) -> None:
        c = self.conn()
        rc.write_match(c, mid, _detail(), None)
        for _ in range(stale_frames):
            c.execute("INSERT INTO timeline_frames (match_id, timestamp_ms, "
                      "participant_id) VALUES (?, 0, 1)", (mid,))
        rc.enqueue_retry(c, mid, "timeline", "test")
        c.commit()
        c.close()

    def test_drain_recovers_timeline_and_flips_flag(self):
        self._seed_written_without_timeline(stale_frames=3)
        c = self.conn()
        with mock.patch.object(RA, "get_match_timeline", _returns(_timeline())):
            counts = rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(counts["recovered"], 1)
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(1,)])
        # Replaced, not appended: the 3 stale frames are gone, 4 fresh remain.
        self.assertEqual(self.q("SELECT COUNT(*) FROM timeline_frames"), [(4,)])
        self.assertEqual(self.q("SELECT COUNT(*) FROM timeline_events"), [(1,)])
        self.assertEqual(self.retry_rows(), [])

    def test_drain_404_is_permanent_and_keeps_has_timeline_zero(self):
        self._seed_written_without_timeline(stale_frames=2)
        c = self.conn()
        with mock.patch.object(RA, "get_match_timeline", _sequence(_not_found)):
            counts = rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(counts["permanent"], 1)
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])
        # A failed fetch never deletes what is there.
        self.assertEqual(self.q("SELECT COUNT(*) FROM timeline_frames"), [(2,)])
        self.assertEqual(self.retry_rows(), [])

    def test_drain_429_defers_then_abandons_after_max_runs(self):
        self._seed_written_without_timeline()
        for run in range(1, 4):
            c = self.conn()
            with mock.patch.object(RA, "get_match_timeline", _sequence(_rate_limited)):
                counts = rc.drain_retry_queue(
                    c, max_runs=3, backoff_s=(), sleep=NO_SLEEP)
            c.close()
            if run < 3:
                self.assertEqual(counts["deferred"], 1)
                self.assertEqual(self.retry_rows(), [("NA1_1", "timeline", run)])
        self.assertEqual(counts["abandoned"], 1)
        self.assertEqual(self.retry_rows(), [])
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])

    def test_drain_stops_after_first_rate_limit(self):
        self._seed_written_without_timeline("NA1_1")
        self._seed_written_without_timeline("NA1_2")
        fn = _sequence(_rate_limited)
        c = self.conn()
        with mock.patch.object(RA, "get_match_timeline", fn):
            counts = rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(fn.calls["n"], 1)
        self.assertEqual(counts["deferred"], 1)

    def test_drain_match_kind_writes_full_match(self):
        c = self.conn()
        rc.enqueue_retry(c, "NA1_9", "match", "test")
        c.commit()
        with mock.patch.object(RA, "get_match", _returns(_detail())), \
             mock.patch.object(RA, "get_match_timeline", _returns(_timeline())):
            counts = rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(counts["recovered"], 1)
        self.assertEqual(self.q("SELECT match_id, has_timeline FROM matches"),
                         [("NA1_9", 1)])
        self.assertEqual(self.retry_rows(), [])

    def test_drain_match_kind_with_timeline_429_downgrades_to_timeline(self):
        c = self.conn()
        rc.enqueue_retry(c, "NA1_9", "match", "test")
        c.commit()
        with mock.patch.object(RA, "get_match", _returns(_detail())), \
             mock.patch.object(RA, "get_match_timeline", _sequence(_rate_limited)):
            rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])
        self.assertEqual(self.retry_rows(), [("NA1_9", "timeline", 1)])


# ---------------------------------------------------------------------------
# Live writer
# ---------------------------------------------------------------------------

class LiveWriterTests(_DbCase):
    def setUp(self):
        super().setUp()
        state = self.tmp / "state.json"
        state.write_text(json.dumps({"puuid": "abc"}), encoding="utf-8")
        self._p2 = [
            mock.patch.object(rlw, "STATE_PATH", state),
            mock.patch.object(RA, "is_configured", lambda: True),
        ]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in reversed(self._p2):
            p.stop()
        super().tearDown()

    def _run(self, **kw):
        kw.setdefault("backoff_s", (0.0,))
        kw.setdefault("sleep", NO_SLEEP)
        return rlw._do_live_fetch_and_insert(**kw)

    def test_timeline_429_parks_match_for_retry_not_permanent_zero(self):
        with mock.patch.object(RA, "get_recent_matches", _returns(["NA1_1"])), \
             mock.patch.object(RA, "get_match", _returns(_detail())), \
             mock.patch.object(RA, "get_match_timeline", _sequence(_rate_limited)):
            res = self._run(is_retry=True)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["timeline_status"], rc.FETCH_RATE_LIMITED)
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])
        self.assertEqual(self.retry_rows(), [("NA1_1", "timeline", 0)])

    def test_timeline_429_then_success_within_bounded_retry(self):
        tl = _sequence(_rate_limited, _returns(_timeline()))
        with mock.patch.object(RA, "get_recent_matches", _returns(["NA1_1"])), \
             mock.patch.object(RA, "get_match", _returns(_detail())), \
             mock.patch.object(RA, "get_match_timeline", tl):
            res = self._run(is_retry=True)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(1,)])
        self.assertEqual(self.retry_rows(), [])

    def test_event_mode_timeline_404_stays_zero_and_not_queued(self):
        with mock.patch.object(RA, "get_recent_matches", _returns(["NA1_K"])), \
             mock.patch.object(RA, "get_match", _returns(_detail(2400, "KIWI"))), \
             mock.patch.object(RA, "get_match_timeline", _sequence(_not_found)):
            res = self._run(is_retry=True)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.q("SELECT has_timeline FROM matches"), [(0,)])
        self.assertEqual(self.retry_rows(), [])

    def test_detail_429_is_parked_as_match_retry(self):
        with mock.patch.object(RA, "get_recent_matches", _returns(["NA1_1"])), \
             mock.patch.object(RA, "get_match", _sequence(_rate_limited)):
            res = self._run(is_retry=True)
        self.assertEqual(res["status"], "detail_rate_limited")
        self.assertEqual(self.q("SELECT COUNT(*) FROM matches"), [(0,)])
        self.assertEqual(self.retry_rows(), [("NA1_1", "match", 0)])

    def test_id_fetch_429_reschedules_even_on_the_event_retry(self):
        spawned: list[dict] = []

        class _SpyTimer(threading.Timer):
            def start(self):
                spawned.append(dict(self.kwargs))

        with mock.patch.object(RA, "get_recent_matches", _rate_limited), \
             mock.patch.object(rlw.threading, "Timer", _SpyTimer):
            res = self._run(is_retry=True)
        self.assertEqual(res["status"], "rate_limited_retry_scheduled")
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0]["rate_limit_attempt"], 1)

    def test_id_fetch_429_retries_are_bounded(self):
        spawned: list[dict] = []

        class _SpyTimer(threading.Timer):
            def start(self):
                spawned.append(dict(self.kwargs))

        with mock.patch.object(RA, "get_recent_matches", _rate_limited), \
             mock.patch.object(rlw.threading, "Timer", _SpyTimer):
            res = self._run(
                is_retry=True,
                rate_limit_attempt=rlw.MAX_ID_RATE_LIMIT_RETRIES)
        self.assertEqual(res["status"], "rate_limited")
        self.assertEqual(spawned, [])


# ---------------------------------------------------------------------------
# Backfill script
# ---------------------------------------------------------------------------

class BackfillTests(_DbCase):
    def _insert(self, c, mid, queue_id, game_mode, has_timeline=0,
                has_stats=1, platform="NA1"):
        c.execute(
            "INSERT INTO matches (match_id, platform, queue_id, game_mode, "
            "has_stats, has_timeline) VALUES (?,?,?,?,?,?)",
            (mid, platform, queue_id, game_mode, has_stats, has_timeline))

    def _seed(self):
        c = self.conn()
        self._insert(c, "NA1_SR", 400, "CLASSIC")
        self._insert(c, "NA1_AR", 1750, "CHERRY")
        self._insert(c, "NA1_KIWI", 2400, "KIWI")
        self._insert(c, "NA1_KIWIMODE", None, "KIWI")
        self._insert(c, "NA1_UNK", None, None, platform=None)
        self._insert(c, "NA1_OK", 420, "CLASSIC", has_timeline=1)
        self._insert(c, "NA1_NOSTATS", 420, "CLASSIC", has_stats=0)
        c.commit()
        c.close()

    def test_classify_excludes_event_mode_and_unknown_queue(self):
        self._seed()
        c = self.conn()
        report = bf.classify(c)
        c.close()
        self.assertEqual(sorted(r["match_id"] for r in report["candidates"]),
                         ["NA1_AR", "NA1_SR"])
        self.assertEqual(sorted(report["excluded_event_mode"]),
                         ["NA1_KIWI", "NA1_KIWIMODE"])
        self.assertEqual(report["excluded_unknown_queue"], ["NA1_UNK"])

    def test_dry_run_writes_nothing(self):
        self._seed()
        before = self.db_path.read_bytes()
        rc_code = bf.main(["--db", str(self.db_path), "--dry-run"])
        self.assertEqual(rc_code, 0)
        self.assertEqual(self.db_path.read_bytes(), before)
        tables = {r[0] for r in self.q(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("fetch_retry", tables)

    def test_apply_enqueues_candidates_idempotently(self):
        self._seed()
        self.assertEqual(bf.main(["--db", str(self.db_path)]), 0)
        self.assertEqual(bf.main(["--db", str(self.db_path)]), 0)
        self.assertEqual(self.retry_rows(),
                         [("NA1_AR", "timeline", 0), ("NA1_SR", "timeline", 0)])
        # Flags untouched: the retry drain is what flips has_timeline.
        self.assertEqual(
            self.q("SELECT COUNT(*) FROM matches WHERE has_timeline=1"), [(1,)])

    def test_backfilled_row_is_recovered_by_the_catchup_drain(self):
        self._seed()
        bf.main(["--db", str(self.db_path)])
        c = self.conn()
        with mock.patch.object(RA, "get_match_timeline", _returns(_timeline())):
            counts = rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(counts["recovered"], 2)
        self.assertEqual(
            self.q("SELECT match_id FROM matches WHERE has_timeline=0 "
                   "ORDER BY match_id"),
            [("NA1_KIWI",), ("NA1_KIWIMODE",), ("NA1_NOSTATS",), ("NA1_UNK",)])


if __name__ == "__main__":
    unittest.main()
