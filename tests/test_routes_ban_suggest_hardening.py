"""Hardening tests for ``dashboard.routes_ban_suggest`` (s144 true-audit cycle 79).

One test (or test group) per audited weakness:

F1 id tokens: only ASCII decimal digits, bounded length, positive
   champion ids; an over-long id is a 400, never a SQLite OverflowError
   reported as a 503; a rejected token is clipped in the error body.
F2 queue list: a comma-only ``queue=`` no longer silently drops the
   queue filter (and so no longer poisons the default-queue cache key);
   the queue count is capped.
F3 duplicate ids within one list are a 400.
F4 a cache hit echoes the CALLER's ally / enemy order and candidate
   order, not the first caller's.
F5 no response is written while the module cache lock is held.
F6 only a database / filesystem failure maps to the 503 "rewind history
   unavailable" body; any other compute failure is a 500 logged with a
   traceback.
F7 the outer failure path logs a traceback.
F8 the cache TTL runs on a monotonic clock, not the wall clock.
F9 ``min_matchup_n`` reports the matchup sample density the
   hurts-them score is built on.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import unittest
from unittest.mock import patch

from dashboard import routes_ban_suggest as rbs
from tests._draft_elo_fixture import DraftEloFixtureMixin


class _Harness:
    def __init__(self, qs: str, *, check_lock: bool = False):
        self.path = f"/api/ban-suggest?{qs}"
        self.sent_status = None
        self.sent_body = b""
        self.check_lock = check_lock
        self.lock_held_at_send = None

    def _send(self, status, body, content_type):
        if self.check_lock:
            self.lock_held_at_send = rbs._CACHE_LOCK.locked()
        self.sent_status = status
        self.sent_body = body

    def json(self) -> dict:
        return json.loads(self.sent_body)


def _serve(qs: str, **kw) -> _Harness:
    h = _Harness(qs, **kw)
    rbs._serve_ban_suggest(h)
    return h


class IdTokenValidationTests(unittest.TestCase):
    """F1 - the trust boundary on every id token."""

    def setUp(self):
        rbs._reset_caches()

    def _assert_400(self, qs: str, needle: str | None = None):
        # _compute is patched so a token that slips past validation shows
        # up as a 200, not as a fixture-dependent 503.
        with patch.object(rbs, "_compute",
                          return_value={"ok": True, "ally": [], "enemy": [],
                                        "candidates": [], "queue_ids": []}):
            h = _serve(qs)
        self.assertEqual(h.sent_status, 400, h.sent_body)
        body = h.json()
        self.assertFalse(body["ok"])
        if needle is not None:
            self.assertIn(needle, body["error"])
        return body

    def test_overflow_id_is_400_not_db_error(self):
        # Before: int() accepted it, SQLite raised OverflowError inside
        # _compute and the caller got 503 "rewind history unavailable".
        self._assert_400("ally=99999999999999999999&candidates=64", "ally")

    def test_negative_champion_id_rejected(self):
        self._assert_400("ally=-5&candidates=64", "ally")

    def test_zero_champion_id_rejected(self):
        self._assert_400("ally=22&candidates=0", "candidates")

    def test_non_ascii_digit_rejected(self):
        # %D9%A3 is ARABIC-INDIC DIGIT THREE; int() accepts it.
        self._assert_400("ally=%D9%A3&candidates=64", "ally")

    def test_underscore_digit_rejected(self):
        # int("2_2") == 22.
        self._assert_400("ally=2_2&candidates=64", "ally")

    def test_plus_sign_rejected(self):
        self._assert_400("ally=%2B22&candidates=64", "ally")

    def test_rejected_token_is_clipped_in_error(self):
        body = self._assert_400("ally=" + "a" * 5000 + "&candidates=64")
        self.assertLess(len(body["error"]), 200)

    def test_valid_ids_still_accepted(self):
        with patch.object(rbs, "_compute",
                          return_value={"ok": True, "ally": [22],
                                        "enemy": [],
                                        "candidates": [{"champ_id": 64}],
                                        "queue_ids": [0, 420]}) as comp:
            h = _serve("ally=22&candidates=64&queue=0,420")
        self.assertEqual(h.sent_status, 200, h.sent_body)
        comp.assert_called_once_with([22], [], [64], (0, 420))


class QueueListTests(unittest.TestCase):
    """F2 - the queue filter cannot be dropped or inflated by input."""

    def setUp(self):
        rbs._reset_caches()

    def test_comma_only_queue_rejected(self):
        with patch.object(rbs, "_compute") as comp:
            h = _serve("ally=22&candidates=64&queue=,")
        self.assertEqual(h.sent_status, 400, h.sent_body)
        comp.assert_not_called()

    def test_too_many_queue_ids_rejected(self):
        # Literal 17, not _MAX_QUEUE_IDS + 1: a test derived from the
        # constant survives any change to the constant.
        qs = ",".join(str(400 + i) for i in range(17))
        with patch.object(rbs, "_compute") as comp:
            h = _serve(f"ally=22&candidates=64&queue={qs}")
        self.assertEqual(h.sent_status, 400, h.sent_body)
        self.assertIn("queue", h.json()["error"])
        comp.assert_not_called()

    def test_sixteen_queue_ids_accepted(self):
        qs = ",".join(str(400 + i) for i in range(16))
        with patch.object(rbs, "_compute",
                          return_value={"ok": True, "ally": [22],
                                        "enemy": [],
                                        "candidates": [{"champ_id": 64}],
                                        "queue_ids": []}) as comp:
            h = _serve(f"ally=22&candidates=64&queue={qs}")
        self.assertEqual(h.sent_status, 200, h.sent_body)
        comp.assert_called_once()

    def test_negative_queue_rejected(self):
        with patch.object(rbs, "_compute") as comp:
            h = _serve("ally=22&candidates=64&queue=-1")
        self.assertEqual(h.sent_status, 400, h.sent_body)
        comp.assert_not_called()


class QueueCachePoisonTests(DraftEloFixtureMixin, unittest.TestCase):
    """F2 - an all-queues answer must never be served for the default."""

    def setUp(self):
        rbs._reset_caches()

    def test_cache_key_uses_resolved_queues(self):
        default = rbs.draft_elo_db.DEFAULT_SR_QUEUES
        self.assertEqual(rbs._cache_key([22], [], [64], None),
                         rbs._cache_key([22], [], [64], tuple(default)))
        self.assertNotEqual(rbs._cache_key([22], [], [64], None),
                            rbs._cache_key([22], [], [64], ()))

    def test_comma_queue_does_not_poison_default_cache(self):
        _serve("ally=22&candidates=64&queue=,")
        h = _serve("ally=22&candidates=64")
        self.assertEqual(h.sent_status, 200, h.sent_body)
        body = h.json()
        self.assertFalse(body["cached"])
        self.assertEqual(body["queue_ids"],
                         list(rbs.draft_elo_db.DEFAULT_SR_QUEUES))


class DuplicateIdTests(unittest.TestCase):
    """F3 - one champion cannot appear twice in one list."""

    def setUp(self):
        rbs._reset_caches()

    def _assert_dup_400(self, qs: str, field: str):
        with patch.object(rbs, "_compute") as comp:
            h = _serve(qs)
        self.assertEqual(h.sent_status, 400, h.sent_body)
        err = h.json()["error"]
        self.assertIn(field, err)
        self.assertIn("duplicate", err)
        comp.assert_not_called()

    def test_duplicate_ally(self):
        self._assert_dup_400("ally=22,22&candidates=64", "ally")

    def test_duplicate_enemy(self):
        self._assert_dup_400("ally=22&enemy=42,42&candidates=64", "enemy")

    def test_duplicate_candidate(self):
        self._assert_dup_400("ally=22&candidates=64,64", "candidates")

    def test_duplicate_queue(self):
        self._assert_dup_400("ally=22&candidates=64&queue=420,420", "queue")


class CacheEchoTests(DraftEloFixtureMixin, unittest.TestCase):
    """F4 + F5 - cache hits answer THIS request, outside the lock."""

    def setUp(self):
        rbs._reset_caches()

    def test_cache_hit_echoes_request_order(self):
        h1 = _serve("ally=22,64&enemy=42,67&candidates=64,22,8")
        self.assertEqual(h1.json()["ally"], [22, 64])
        h2 = _serve("ally=64,22&enemy=67,42&candidates=8,22,64")
        body = h2.json()
        self.assertTrue(body["cached"])
        self.assertEqual(body["ally"], [64, 22])
        self.assertEqual(body["enemy"], [67, 42])
        self.assertEqual([c["champ_id"] for c in body["candidates"]],
                         [8, 22, 64])

    def test_cache_hit_scores_match_miss_scores(self):
        h1 = _serve("ally=22&candidates=64,22")
        h2 = _serve("ally=22&candidates=22,64")
        miss = {c["champ_id"]: c for c in h1.json()["candidates"]}
        hit = {c["champ_id"]: c for c in h2.json()["candidates"]}
        self.assertTrue(h2.json()["cached"])
        self.assertEqual(miss, hit)

    def test_no_send_while_cache_lock_held(self):
        h1 = _serve("ally=22&candidates=64", check_lock=True)
        h2 = _serve("ally=22&candidates=64", check_lock=True)
        self.assertTrue(h2.json()["cached"])
        self.assertIs(h1.lock_held_at_send, False)
        self.assertIs(h2.lock_held_at_send, False)


class ComputeFailureTests(unittest.TestCase):
    """F6 + F7 - failure classes map to the right status and log."""

    def setUp(self):
        rbs._reset_caches()

    def test_sqlite_error_is_503(self):
        with patch.object(rbs, "_compute",
                          side_effect=sqlite3.OperationalError("locked")):
            h = _serve("ally=22&candidates=64")
        self.assertEqual(h.sent_status, 503)
        self.assertEqual(h.json()["error"], "rewind history unavailable")

    def test_os_error_is_503(self):
        with patch.object(rbs, "_compute",
                          side_effect=OSError("disk gone")):
            h = _serve("ally=22&candidates=64")
        self.assertEqual(h.sent_status, 503)

    def test_unexpected_compute_error_is_500_with_traceback(self):
        with patch.object(rbs, "_compute",
                          side_effect=KeyError("programming error")), \
                self.assertLogs("rc.web_dashboard", logging.WARNING) as cm:
            h = _serve("ally=22&candidates=64")
        self.assertEqual(h.sent_status, 500)
        body = h.json()
        self.assertNotIn("programming error", body["error"])
        self.assertTrue(any(r.exc_info for r in cm.records),
                        "unexpected failure logged without a traceback")

    def test_outer_failure_logs_traceback(self):
        with patch.object(rbs, "_parse_ids",
                          side_effect=TypeError("boom")), \
                self.assertLogs("rc.web_dashboard", logging.WARNING) as cm:
            h = _serve("ally=22&candidates=64")
        self.assertEqual(h.sent_status, 500)
        self.assertNotIn("boom", h.json()["error"])
        self.assertTrue(any(r.exc_info for r in cm.records))

    def test_failures_are_not_cached(self):
        with patch.object(rbs, "_compute",
                          side_effect=sqlite3.OperationalError("x")):
            _serve("ally=22&candidates=64")
        self.assertEqual(rbs._CACHE, {})


class _FakeClock:
    def __init__(self, wall: float, mono: float):
        self.wall = wall
        self.mono = mono

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def perf_counter(self) -> float:
        return self.mono


class MonotonicTtlTests(DraftEloFixtureMixin, unittest.TestCase):
    """F8 - a wall-clock step back must not extend a cache entry."""

    def setUp(self):
        rbs._reset_caches()

    def test_wall_clock_step_back_does_not_serve_expired_entry(self):
        clock = _FakeClock(wall=10_000.0, mono=500.0)
        with patch.object(rbs, "time", clock):
            _serve("ally=22&candidates=64")
            # Wall clock stepped back an hour; monotonic advanced past TTL.
            clock.wall = 6_400.0
            clock.mono = 500.0 + rbs._CACHE_TTL_S + 1.0
            h = _serve("ally=22&candidates=64")
        self.assertFalse(h.json()["cached"])

    def test_entry_within_ttl_is_served(self):
        clock = _FakeClock(wall=10_000.0, mono=500.0)
        with patch.object(rbs, "time", clock):
            _serve("ally=22&candidates=64")
            clock.mono = 500.0 + rbs._CACHE_TTL_S - 1.0
            h = _serve("ally=22&candidates=64")
        self.assertTrue(h.json()["cached"])


class MatchupDensityTests(DraftEloFixtureMixin, unittest.TestCase):
    """F9 - the matchup sample density is reported, not discarded."""

    def setUp(self):
        rbs._reset_caches()

    def test_min_matchup_n_reported(self):
        # Fixture: 64 vs 22 cross-team = 1 game in q420.
        h = _serve("ally=22&candidates=64&queue=420")
        cand = h.json()["candidates"][0]
        self.assertEqual(cand["min_matchup_n"], 1)
        self.assertEqual(cand["min_pair_n"], 1)

    def test_min_matchup_n_zero_without_matchups(self):
        # Candidate equal to the only ally: every query is skipped.
        h = _serve("ally=22&candidates=22&queue=420")
        cand = h.json()["candidates"][0]
        self.assertEqual(cand["min_matchup_n"], 0)


if __name__ == "__main__":
    unittest.main()
