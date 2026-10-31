"""Tests for the /api/draft-score route helpers - specifically the DS
spike-derived scaling resolver that activates the (previously inert) scaling
layer. The pure _peak_timing math is covered deterministically here (no DS
engine needed); the _SpikeScalingResolver fail-soft contract is covered with a
bad champion id so the layer degrades rather than raising.
"""
from __future__ import annotations

import json
import unittest

from core import draft_score
from dashboard import routes_draft_score as rds


class TestPeakTiming(unittest.TestCase):
    def test_empty_or_none_is_none(self):
        self.assertIsNone(rds._peak_timing(None))
        self.assertIsNone(rds._peak_timing([]))

    def test_all_zero_curve_is_none(self):
        self.assertIsNone(rds._peak_timing([0.0] * 41))

    def test_early_crossing_reads_low(self):
        # crosses 70% of max at index 4 of 41 -> 4/40 = 0.1
        curve = [0.8] + [1.0] * 40   # max 1.0, index 0 already >= 0.7
        self.assertAlmostEqual(rds._peak_timing(curve), 0.0)

    def test_mid_crossing_normalizes_to_fraction(self):
        # linear 0..1 over 41 points; 70% of max(1.0)=0.7 first at index 29
        curve = [i / 40 for i in range(41)]
        # index 28 -> 0.700 is the first entry >= 0.7 (threshold = max*0.70)
        self.assertAlmostEqual(rds._peak_timing(curve), 28 / 40)

    def test_late_only_crossing_reads_high(self):
        # power flat-low then a single late spike at the last index
        curve = [0.1] * 40 + [1.0]
        self.assertAlmostEqual(rds._peak_timing(curve), 1.0)

    def test_threshold_is_relative_to_own_max(self):
        # scaling the whole curve does not move the crossing fraction
        base = [i / 40 for i in range(41)]
        scaled = [v * 1000 for v in base]
        self.assertEqual(rds._peak_timing(base), rds._peak_timing(scaled))


class TestSpikeScalingResolver(unittest.TestCase):
    def test_default_resolver_is_callable(self):
        r = rds._default_scaling_resolver()
        self.assertTrue(callable(r))

    def test_unknown_champ_id_returns_none_not_raise(self):
        # A champ id absent from the DDragon map must fail soft to None so the
        # scaling layer drops that champ instead of raising.
        r = rds._default_scaling_resolver()
        self.assertIsNone(r(999999999))

    def test_resolver_never_raises_on_garbage(self):
        r = rds._default_scaling_resolver()
        for bad in (None, "not-an-int", -1, 0):
            self.assertIsNone(r(bad))


class _Handler:
    """Minimal stand-in for the dashboard request handler: records every
    _send and, optionally, asserts the response cache lock is free while a
    response is written (a slow client must not stall every other caller)."""

    def __init__(self, query: str, *, fail_send: bool = False):
        self.path = "/api/draft-score" + (("?" + query) if query else "")
        self.sent: list[tuple[int, dict]] = []
        self.lock_held_during_send: list[bool] = []
        self._fail_send = fail_send

    def _send(self, status, body, ctype):
        self.lock_held_during_send.append(rds._CACHE_LOCK.locked())
        if self._fail_send:
            raise OSError("client went away")
        self.sent.append((status, json.loads(body.decode("utf-8"))))


class _FakeClock:
    """Stands in for the route module's ``time``: the wall clock can be
    pushed backwards while the monotonic clock moves forwards."""

    def __init__(self):
        self.wall = 1_000_000.0
        self.mono = 50.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def perf_counter(self):
        return self.mono


class _RouteTestBase(unittest.TestCase):
    """Patches compute_draft_score with a recording stub so no test reads the
    live rewind db, the DS snapshot or the 101qq capture."""

    def setUp(self):
        rds._reset_caches()
        self.calls: list[tuple] = []
        self._real_compute = draft_score.compute_draft_score
        self.next_payload = None

        def _stub(ally, enemy_ids=None, *, queue_ids=None, **_kw):
            self.calls.append((list(ally),
                               list(enemy_ids) if enemy_ids else None,
                               tuple(queue_ids) if queue_ids is not None else None))
            if self.next_payload is not None:
                return dict(self.next_payload)
            return {"ok": True, "score": 51.5, "confidence": "MED",
                    "band": [42.0, 58.0], "layers": [],
                    "ally": list(ally),
                    "enemy": list(enemy_ids) if enemy_ids else None,
                    "queue_ids": list(queue_ids) if queue_ids else None}

        draft_score.compute_draft_score = _stub

    def tearDown(self):
        draft_score.compute_draft_score = self._real_compute
        rds._reset_caches()

    def serve(self, query, **kw):
        h = _Handler(query, **kw)
        rds._serve_draft_score(h)
        return h

    def assert_400(self, query, needle=None):
        h = self.serve(query)
        self.assertEqual(len(h.sent), 1, query)
        status, body = h.sent[0]
        self.assertEqual(status, 400, (query, body))
        self.assertIs(body.get("ok"), False)
        if needle is not None:
            self.assertIn(needle, body.get("error", ""), (query, body))
        self.assertEqual(self.calls, [], "a rejected request reached the scorer")
        self.assertEqual(len(rds._CACHE), 0, "a rejected request was cached")
        return body


class TestValidRequestCharacterization(_RouteTestBase):
    def test_ids_reach_the_scorer_in_request_order(self):
        h = self.serve("ally=64,22,1,2,3&enemy=42,67,69,55,12&queue=440,420")
        self.assertEqual(h.sent[0][0], 200)
        self.assertEqual(self.calls, [([64, 22, 1, 2, 3], [42, 67, 69, 55, 12],
                                       (440, 420))])
        body = h.sent[0][1]
        self.assertIs(body["cached"], False)
        self.assertIsInstance(body["elapsed_ms"], int)

    def test_surrounding_whitespace_and_blank_parts_are_tolerated(self):
        h = self.serve("ally=%2064,%2022,,1,2,3")
        self.assertEqual(h.sent[0][0], 200)
        self.assertEqual(self.calls[0][0], [64, 22, 1, 2, 3])

    def test_omitted_or_blank_queue_means_default_set(self):
        for q in ("ally=1,2,3,4,5", "ally=1,2,3,4,5&queue="):
            rds._reset_caches()
            self.calls.clear()
            h = self.serve(q)
            self.assertEqual(h.sent[0][0], 200, q)
            self.assertIsNone(self.calls[0][2], q)

    def test_ally_enemy_overlap_is_allowed(self):
        # Blind pick (queue 430) allows a mirror match.
        h = self.serve("ally=1,2,3,4,5&enemy=1,7,8,9,10")
        self.assertEqual(h.sent[0][0], 200)

    def test_missing_ally_is_400(self):
        self.assert_400("", "ally")
        self.assert_400("ally=", "ally")

    def test_wrong_ally_count_is_400(self):
        self.assert_400("ally=1,2,3,4", "expected 5")
        self.assert_400("ally=1,2,3,4,5,6", "expected 5")


class TestIdValidation(_RouteTestBase):
    def test_signed_underscore_and_non_ascii_ids_are_400(self):
        # int() accepts all of these; a champion key is plain ASCII digits.
        for tok in ("%2B64", "-64", "6_4", "%D9%A6%D9%A4", "0x40", "64.0"):
            with self.subTest(tok=tok):
                self.assert_400(f"ally={tok},22,1,2,3", "ally")

    def test_zero_champion_id_is_400(self):
        self.assert_400("ally=0,22,1,2,3", "ally")
        self.assert_400("ally=1,2,3,4,5&enemy=0,7,8,9,10", "enemy")

    def test_overlong_id_is_400_not_a_cached_neutral_score(self):
        # A 30-digit id reached SQLite as an OverflowError that the scorer's
        # sqlite3.Error catches miss; every layer went inert and a fake
        # neutral 50 was answered 200 and cached for 5 minutes.
        self.assert_400("ally=" + "9" * 30 + ",2,3,4,5", "ally")
        self.assert_400("ally=1,2,3,4,5&enemy=" + "9" * 7 + ",7,8,9,10", "enemy")

    def test_one_for_all_repeated_champion_is_allowed(self):
        # One for All (queue 1020) puts five copies of one champion on each
        # team, and the champ-select card classifies it as "sr", so it sends
        # five identical ally (and enemy) ids. Refusing them would hide the
        # card for a real draft.
        h = self.serve("ally=64,64,64,64,64&enemy=22,22,22,22,22")
        self.assertEqual(h.sent[0][0], 200)
        self.assertEqual(self.calls, [([64] * 5, [22] * 5, None)])

    def test_wrong_enemy_count_is_400(self):
        self.assert_400("ally=1,2,3,4,5&enemy=6,7,8", "enemy")

    def test_repeated_parameter_is_400(self):
        # parse_qs keeps every value; the route silently scored the first.
        self.assert_400("ally=1,2,3,4,5&ally=6,7,8,9,10", "ally")
        self.assert_400("ally=1,2,3,4,5&queue=420&queue=440", "queue")

    def test_rejected_token_is_clipped_in_the_error_body(self):
        body = self.assert_400("ally=" + "x" * 3000 + ",2,3,4,5")
        self.assertLess(len(body["error"]), 120)


class TestQueueValidation(_RouteTestBase):
    def test_queue_with_no_ids_is_400_not_the_default_set(self):
        self.assert_400("ally=1,2,3,4,5&queue=,", "queue")
        self.assert_400("ally=1,2,3,4,5&queue=%20,%20", "queue")

    def test_queue_list_over_the_cap_is_400(self):
        too_many = ",".join(str(400 + i) for i in range(rds._MAX_QUEUE_IDS + 1))
        self.assert_400("ally=1,2,3,4,5&queue=" + too_many, "queue")
        at_cap = ",".join(str(400 + i) for i in range(rds._MAX_QUEUE_IDS))
        h = self.serve("ally=1,2,3,4,5&queue=" + at_cap)
        self.assertEqual(h.sent[0][0], 200)

    def test_duplicate_queue_id_is_400(self):
        self.assert_400("ally=1,2,3,4,5&queue=420,420", "duplicate")

    def test_queue_zero_is_a_valid_queue(self):
        # Queue 0 is the custom-game queue id.
        h = self.serve("ally=1,2,3,4,5&queue=0")
        self.assertEqual(h.sent[0][0], 200)
        self.assertEqual(self.calls[0][2], (0,))

    def test_bad_queue_token_is_400(self):
        self.assert_400("ally=1,2,3,4,5&queue=-420", "queue")
        self.assert_400("ally=1,2,3,4,5&queue=" + "4" * 7, "queue")


class TestCache(_RouteTestBase):
    def test_reordered_request_hits_the_cache(self):
        self.serve("ally=1,2,3,4,5&queue=420,440")
        h = self.serve("ally=5,4,3,2,1&queue=440,420")
        self.assertEqual(len(self.calls), 1, "queue order split the cache key")
        self.assertIs(h.sent[0][1]["cached"], True)

    def test_cached_response_echoes_this_request_not_the_first(self):
        self.serve("ally=1,2,3,4,5&enemy=6,7,8,9,10&queue=420,440")
        h = self.serve("ally=5,4,3,2,1&enemy=10,9,8,7,6&queue=440,420")
        body = h.sent[0][1]
        self.assertEqual(body["ally"], [5, 4, 3, 2, 1])
        self.assertEqual(body["enemy"], [10, 9, 8, 7, 6])
        self.assertEqual(body["queue_ids"], [440, 420])

    def test_cache_hit_is_not_written_under_the_cache_lock(self):
        self.serve("ally=1,2,3,4,5")
        h = self.serve("ally=1,2,3,4,5")
        self.assertIs(h.sent[0][1]["cached"], True)
        self.assertEqual(h.lock_held_during_send, [False])

    def test_ttl_is_monotonic_not_wall_clock(self):
        clock = _FakeClock()
        real_time = rds.time
        rds.time = clock
        try:
            self.serve("ally=1,2,3,4,5")
            # The wall clock steps back an hour (NTP / DST / manual set) while
            # real time moves past the TTL: the entry must still expire.
            clock.wall -= 3600.0
            clock.mono += rds._CACHE_TTL_S + 1.0
            h = self.serve("ally=1,2,3,4,5")
        finally:
            rds.time = real_time
        self.assertEqual(len(self.calls), 2, "a backwards wall clock pinned the cache")
        self.assertIs(h.sent[0][1]["cached"], False)

    def test_stored_payload_is_not_mutated_by_a_response(self):
        self.serve("ally=1,2,3,4,5")
        (stored,) = [v[1] for v in rds._CACHE.values()]
        self.assertNotIn("cached", stored)
        self.assertNotIn("elapsed_ms", stored)
        self.serve("ally=5,4,3,2,1")
        self.assertEqual(stored["ally"], [1, 2, 3, 4, 5])

    def test_not_ok_payload_is_not_cached(self):
        self.next_payload = {"ok": False, "error": "x", "score": 50.0}
        self.serve("ally=1,2,3,4,5")
        self.assertEqual(len(rds._CACHE), 0)


class TestFailurePaths(_RouteTestBase):
    def test_unexpected_failure_is_generic_500_with_traceback_logged(self):
        def _boom(*_a, **_k):
            raise RuntimeError("secret-ish detail <repo>/somewhere")
        draft_score.compute_draft_score = _boom
        with self.assertLogs("rc.web_dashboard", level="ERROR") as cm:
            h = self.serve("ally=1,2,3,4,5")
        status, body = h.sent[0]
        self.assertEqual(status, 500)
        self.assertNotIn("secret-ish", json.dumps(body))
        self.assertTrue(any(r.exc_info for r in cm.records),
                        "the unexpected failure was logged without a traceback")

    def test_failed_500_send_is_logged_not_swallowed(self):
        def _boom(*_a, **_k):
            raise RuntimeError("boom")
        draft_score.compute_draft_score = _boom
        with self.assertLogs("rc.web_dashboard", level="WARNING") as cm:
            self.serve("ally=1,2,3,4,5", fail_send=True)
        self.assertTrue(any("500" in r.getMessage() for r in cm.records),
                        [r.getMessage() for r in cm.records])


if __name__ == "__main__":
    unittest.main()
