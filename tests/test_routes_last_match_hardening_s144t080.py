"""s144 true-audit cycle 80 - dashboard/routes_last_match.py hardening.

POST /api/last-match/ingest is a LAN-reachable write (tools/lcu_agent.py
posts it with no auth header; it is not a control endpoint), and GET
/api/last-match keys a response cache on the request query. Each class
below pins one finding of the cycle-80 audit; every test was RED against
the pre-fix module.

F1  the retry queue was unbounded and never de-duplicated: every 202 kept
    a body of up to 1 MiB for 60 s, and a Refresh click re-queued the same
    game again.
F2  one raising entry aborted the whole drain AFTER the snapshot had been
    cleared, so every other queued ingest was lost.
F3  malformed numeric fields (gameId "abc", a bool, an over-int64 id, a
    negative or string gameCreation) answered 500 instead of 400.
F4  a non-list participants / participantIdentities or a non-dict entry
    raised AttributeError -> 500.
F5  a non-string, overlong or control-character tracked_puuid was
    persisted into the row.
F6  a row whose raw_data was valid JSON but not an object raised
    TypeError, and an undecodable blob was silently discarded.
F7  a GET build straddling an ingest's invalidation cached the pre-ingest
    body for the full TTL.
F8  the cache TTL and the retry deadline used the wall clock.
F9  _ensure_retry_thread was check-then-set without a lock.
F10 match_ts reached the cache key raw: unstripped and unbounded.
F11 a match-store failure answered a generic 500; only DB / OS failures
    are now a degraded 503, the rest a traceback-logged 500.

Hand-written synthetic ids only (RM-906). ASCII-only authored content.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import dashboard.routes_last_match as rlm


class StubHandler:
    def __init__(self, path: str = "/api/last-match/ingest"):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


def _detail(game_id=900001, *, puuid="synthetic-puuid-A",
            creation_ms=None, duration_s=0) -> dict:
    if creation_ms is None:
        creation_ms = int(time.time() * 1000)
    return {
        "gameId": game_id,
        "gameCreation": creation_ms,
        "gameDuration": duration_s,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": puuid}},
        ],
        "participants": [{"participantId": 1, "championId": 51}],
    }


def _body(game_id=900001, **kw) -> dict:
    return {"tracked_puuid": "synthetic-puuid-A",
            "match_detail": _detail(game_id, **kw)}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app_dir = Path(self._tmp.name)
        (self.app_dir / "data").mkdir()
        self.db_path = self.app_dir / "data" / "match_history.db"
        from core.match_db import MatchDB
        MatchDB(self.db_path)
        self._p = mock.patch.object(rlm, "_APP_DIR", self.app_dir)
        self._p.start()
        rlm._cache_clear()
        rlm._INGEST_RETRY_QUEUE.clear()
        self._started = rlm._INGEST_RETRY_THREAD_STARTED
        rlm._INGEST_RETRY_THREAD_STARTED = True

    def tearDown(self):
        rlm._INGEST_RETRY_THREAD_STARTED = self._started
        rlm._INGEST_RETRY_QUEUE.clear()
        rlm._cache_clear()
        self._p.stop()
        self._tmp.cleanup()

    def _seed(self, *, game_id=0, raw_data="", ts=None) -> int:
        ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c = sqlite3.connect(str(self.db_path))
        try:
            cur = c.execute(
                "INSERT INTO matches (timestamp, mode, champion, grade,"
                " game_id, raw_data) VALUES (?,?,?,?,?,?)",
                (ts, "SR", "Caitlyn", "C", game_id, raw_data))
            c.commit()
            return int(cur.lastrowid)
        finally:
            c.close()

    def _raw(self, mid: int) -> str:
        c = sqlite3.connect(str(self.db_path))
        try:
            return c.execute("SELECT raw_data FROM matches WHERE id=?",
                             (mid,)).fetchone()[0]
        finally:
            c.close()

    def _post(self, body) -> StubHandler:
        h = StubHandler()
        rlm._serve_last_match_ingest(h, body)
        return h


class F1RetryQueueBoundAndDedupe(_Base):
    def test_same_game_queued_twice_holds_one_entry(self):
        self.assertEqual(self._post(_body(900101)).last_status, 202)
        self.assertEqual(self._post(_body(900101)).last_status, 202)
        self.assertEqual(len(rlm._INGEST_RETRY_QUEUE), 1)

    def test_requeue_keeps_the_newest_body(self):
        first = _body(900102)
        second = _body(900102)
        second["match_detail"]["marker"] = "newest"
        self._post(first)
        self._post(second)
        (_deadline, kept), = list(rlm._INGEST_RETRY_QUEUE)
        self.assertEqual(kept["match_detail"].get("marker"), "newest")

    def test_queue_is_bounded_and_refuses_with_503(self):
        cap = rlm.INGEST_RETRY_QUEUE_MAX
        for i in range(cap):
            self.assertEqual(self._post(_body(910000 + i)).last_status, 202)
        h = self._post(_body(919999))
        self.assertEqual(h.last_status, 503)
        self.assertIn("error", h.parsed())
        self.assertEqual(len(rlm._INGEST_RETRY_QUEUE), cap)

    def test_full_queue_still_accepts_a_requeue_of_a_queued_game(self):
        cap = rlm.INGEST_RETRY_QUEUE_MAX
        for i in range(cap):
            self._post(_body(920000 + i))
        self.assertEqual(self._post(_body(920000)).last_status, 202)
        self.assertEqual(len(rlm._INGEST_RETRY_QUEUE), cap)


class F2DrainSurvivesARaisingEntry(_Base):
    def test_one_raising_entry_does_not_lose_the_others(self):
        self._post(_body(900201))
        self._post(_body(900202))
        self.assertEqual(len(rlm._INGEST_RETRY_QUEUE), 2)
        real = rlm._try_ingest_once

        def flaky(body):
            if body["match_detail"]["gameId"] == 900201:
                raise sqlite3.OperationalError("database is locked")
            return real(body)

        with mock.patch.object(rlm, "_try_ingest_once", flaky), \
                self.assertLogs("rc.web_dashboard", logging.WARNING):
            rlm._drain_ingest_queue_once()
        gids = sorted(b["match_detail"]["gameId"]
                      for _d, b in rlm._INGEST_RETRY_QUEUE)
        self.assertEqual(gids, [900201, 900202])

    def test_drain_does_not_duplicate_a_game_requeued_mid_drain(self):
        self._post(_body(900203))
        real = rlm._try_ingest_once

        def requeue_then_miss(body):
            # A Refresh click lands while the drain is walking its snapshot.
            with rlm._INGEST_RETRY_LOCK:
                rlm._INGEST_RETRY_QUEUE.append(
                    (time.monotonic() + 60, _body(900203)))
            return real(body)

        with mock.patch.object(rlm, "_try_ingest_once", requeue_then_miss):
            rlm._drain_ingest_queue_once()
        self.assertEqual(len(rlm._INGEST_RETRY_QUEUE), 1)


class F3NumericFieldValidation(_Base):
    def _assert_400(self, **detail_overrides):
        body = _body()
        body["match_detail"].update(detail_overrides)
        h = self._post(body)
        self.assertEqual(h.last_status, 400, (detail_overrides, h.parsed()))
        self.assertIn("error", h.parsed())
        self.assertEqual(len(rlm._INGEST_RETRY_QUEUE), 0)

    def test_non_numeric_game_id(self):
        self._assert_400(gameId="abc")

    def test_bool_game_id(self):
        self._assert_400(gameId=True)

    def test_fractional_game_id(self):
        self._assert_400(gameId=1.5)

    def test_negative_game_id(self):
        self._assert_400(gameId=-5)

    def test_over_int64_game_id(self):
        self._assert_400(gameId=2 ** 63)

    def test_string_game_creation(self):
        self._assert_400(gameCreation="yesterday")

    def test_negative_game_duration(self):
        self._assert_400(gameDuration=-1)

    def test_digit_string_game_id_still_accepted(self):
        self._seed(game_id=900301)
        body = _body()
        body["match_detail"]["gameId"] = "900301"
        h = self._post(body)
        self.assertEqual(h.last_status, 200, h.parsed())
        self.assertEqual(h.parsed()["game_id"], 900301)


class F4ParticipantShapes(_Base):
    def _post_detail(self, **overrides) -> StubHandler:
        self._seed(game_id=900401)
        body = _body(900401)
        body["match_detail"].update(overrides)
        return self._post(body)

    def test_participants_string_is_400(self):
        self.assertEqual(self._post_detail(participants="xyz").last_status, 400)

    def test_participants_dict_is_400(self):
        h = self._post_detail(participants={"participantId": 1})
        self.assertEqual(h.last_status, 400)

    def test_identities_not_a_list_is_400(self):
        h = self._post_detail(participantIdentities="abc")
        self.assertEqual(h.last_status, 400)

    def test_non_dict_entries_are_skipped_not_500(self):
        h = self._post_detail(
            participantIdentities=["junk", {"participantId": 1, "player": "x"},
                                   {"participantId": 1,
                                    "player": {"puuid": "synthetic-puuid-A"}}],
            participants=[7, {"participantId": 1, "championId": 51}])
        self.assertEqual(h.last_status, 200, h.parsed())
        self.assertEqual(h.parsed()["champion_lcu_id"], 51)


class F5TrackedPuuidValidation(_Base):
    def _assert_400(self, puuid):
        body = _body()
        body["tracked_puuid"] = puuid
        h = self._post(body)
        self.assertEqual(h.last_status, 400, repr(puuid))

    def test_non_string_puuid(self):
        self._assert_400({"a": 1})

    def test_int_puuid(self):
        self._assert_400(12345)

    def test_overlong_puuid(self):
        self._assert_400("p" * (rlm.TRACKED_PUUID_MAX_LEN + 1))

    def test_control_char_puuid(self):
        self._assert_400("synthetic\npuuid")

    def test_valid_puuid_is_stored_stripped(self):
        mid = self._seed(game_id=900501)
        body = _body(900501)
        body["tracked_puuid"] = "  synthetic-puuid-A  "
        self.assertEqual(self._post(body).last_status, 200)
        self.assertEqual(json.loads(self._raw(mid))["tracked_puuid"],
                         "synthetic-puuid-A")


class F6RawDataShapes(_Base):
    def test_non_object_raw_data_is_preserved_not_500(self):
        mid = self._seed(game_id=900601, raw_data=json.dumps([1, 2, 3]))
        h = self._post(_body(900601))
        self.assertEqual(h.last_status, 200, h.parsed())
        rd = json.loads(self._raw(mid))
        self.assertIn("lcu_match_detail", rd)
        self.assertEqual(rd["prior_raw_data"], json.dumps([1, 2, 3]))

    def test_undecodable_raw_data_is_preserved(self):
        mid = self._seed(game_id=900602, raw_data="{not json")
        h = self._post(_body(900602))
        self.assertEqual(h.last_status, 200, h.parsed())
        rd = json.loads(self._raw(mid))
        self.assertEqual(rd["prior_raw_data"], "{not json")

    def test_object_raw_data_keeps_its_keys_without_prior(self):
        mid = self._seed(game_id=900603, raw_data=json.dumps({"kills": 4}))
        self._post(_body(900603))
        rd = json.loads(self._raw(mid))
        self.assertEqual(rd["kills"], 4)
        self.assertNotIn("prior_raw_data", rd)


class F7StaleSetRace(_Base):
    def test_build_straddling_an_ingest_is_not_cached(self):
        self._seed(game_id=900701)
        calls = []

        def builder(baseline, match_ts=None):
            calls.append(1)
            if len(calls) == 1:
                # The ingest commits and invalidates while this build runs.
                post = StubHandler()
                rlm._serve_last_match_ingest(post, _body(900701))
                assert post.last_status == 200, post.parsed()
            return {"found": True, "seq": len(calls)}

        with mock.patch.object(rlm, "_build_last_match", builder):
            rlm._serve_last_match(StubHandler("/api/last-match"))
            h = StubHandler("/api/last-match")
            rlm._serve_last_match(h)
        self.assertEqual(len(calls), 2)
        self.assertEqual(h.parsed()["seq"], 2)


class F8MonotonicClocks(_Base):
    def test_cache_entry_survives_a_wall_clock_jump_back_only_for_the_ttl(self):
        calls = []

        def builder(baseline, match_ts=None):
            calls.append(1)
            return {"found": True, "seq": len(calls)}

        with mock.patch.object(rlm, "_build_last_match", builder):
            rlm._serve_last_match(StubHandler("/api/last-match"))
            # A wall-clock jump an hour back must not make the entry
            # immortal; a monotonic stamp is immune to it.
            with mock.patch.object(rlm.time, "time",
                                   return_value=time.time() - 3600):
                with mock.patch.object(rlm, "_CACHE_TTL_S", -1.0):
                    rlm._serve_last_match(StubHandler("/api/last-match"))
        self.assertEqual(len(calls), 2)

    def test_retry_deadline_is_monotonic(self):
        self._post(_body(900801))
        (deadline, _b), = list(rlm._INGEST_RETRY_QUEUE)
        self.assertLessEqual(deadline,
                             time.monotonic() + rlm.INGEST_RETRY_DEADLINE_S + 1)
        self.assertGreater(deadline, time.monotonic())


class F9RetryThreadStartsOnce(_Base):
    def test_concurrent_first_calls_start_one_thread(self):
        rlm._INGEST_RETRY_THREAD_STARTED = False
        # rlm.threading IS the threading module, so the workers are built
        # from the real class captured before the patch.
        real_thread = threading.Thread
        started = []
        barrier = threading.Barrier(8)

        class FakeThread:
            def __init__(self, *a, **kw):
                started.append(kw.get("name"))

            def start(self):
                time.sleep(0.01)

        def call():
            barrier.wait()
            rlm._ensure_retry_thread()

        with mock.patch.object(rlm.threading, "Thread", FakeThread):
            # Widen the check-then-set window so the race is deterministic.
            orig = rlm._retry_thread_should_start

            def slow_check():
                ok = orig()
                time.sleep(0.02)
                return ok

            with mock.patch.object(rlm, "_retry_thread_should_start", slow_check):
                workers = [real_thread(target=call) for _ in range(8)]
                for w in workers:
                    w.start()
                for w in workers:
                    w.join(5)
        self.assertEqual(len(started), 1, started)


class F10MatchTsValidation(_Base):
    def _get(self, qs: str):
        calls = []

        def builder(baseline, match_ts=None):
            calls.append(match_ts)
            return {"found": False, "match_ts_seen": match_ts}

        h = StubHandler("/api/last-match" + qs)
        with mock.patch.object(rlm, "_build_last_match", builder):
            rlm._serve_last_match(h)
        return h, calls

    def test_overlong_match_ts_is_400_without_a_build(self):
        h, calls = self._get("?match_ts=" + "9" * (rlm.MATCH_TS_MAX_LEN + 1))
        self.assertEqual(h.last_status, 400)
        self.assertEqual(calls, [])

    def test_control_char_match_ts_is_400(self):
        h, calls = self._get("?match_ts=2026-06-01%0A12:00:00")
        self.assertEqual(h.last_status, 400)
        self.assertEqual(calls, [])

    def test_padded_match_ts_shares_the_stripped_key(self):
        self._get("?match_ts=2026-06-01+12:00:00")
        h, calls = self._get("?match_ts=++2026-06-01+12:00:00++")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(calls, [], "padded ts must hit the stripped entry")

    def test_blank_match_ts_is_the_live_path(self):
        h, calls = self._get("?match_ts=+++")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(calls, [None])


class F11ErrorClassification(_Base):
    def test_ingest_db_failure_is_503_degraded(self):
        with mock.patch.object(rlm.sqlite3, "connect",
                               side_effect=sqlite3.OperationalError(
                                   "unable to open database file")), \
                self.assertLogs("rc.web_dashboard", logging.WARNING):
            h = self._post(_body(901101))
        self.assertEqual(h.last_status, 503)
        self.assertNotIn("unable to open", h.last_body.decode())

    def test_ingest_unexpected_failure_is_500_with_traceback(self):
        with mock.patch.object(rlm, "_try_ingest_once",
                               side_effect=RuntimeError("boom-secret-path")), \
                self.assertLogs("rc.web_dashboard", logging.ERROR) as cm:
            h = self._post(_body(901102))
        self.assertEqual(h.last_status, 500)
        self.assertNotIn("boom-secret-path", h.last_body.decode())
        self.assertTrue(any(r.exc_info for r in cm.records))

    def test_get_db_failure_is_503_degraded(self):
        with mock.patch.object(rlm, "_build_last_match",
                               side_effect=sqlite3.DatabaseError("malformed")), \
                self.assertLogs("rc.web_dashboard", logging.WARNING):
            h = StubHandler("/api/last-match")
            rlm._serve_last_match(h)
        self.assertEqual(h.last_status, 503)
        self.assertNotIn("malformed", h.last_body.decode())

    def test_get_unexpected_failure_is_500_with_traceback(self):
        with mock.patch.object(rlm, "_build_last_match",
                               side_effect=KeyError("x")), \
                self.assertLogs("rc.web_dashboard", logging.ERROR) as cm:
            h = StubHandler("/api/last-match")
            rlm._serve_last_match(h)
        self.assertEqual(h.last_status, 500)
        self.assertTrue(any(r.exc_info for r in cm.records))


if __name__ == "__main__":
    unittest.main()
