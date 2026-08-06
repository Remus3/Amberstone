"""GET /api/last-match carries a keyed response TTL cache.

Measured 2026-08-06: the route was the one uncached hot dashboard read -
320ms stable across 5 consecutive requests for an 8198-byte body, because
_serve_last_match called _build_last_match on every request while every
other measured route answered in 8-27ms. The frontend fires it on Post
Game Review activation, on historical-PGR activation, and on every
baseline toggle, so the same body was rebuilt repeatedly.

The cache must pin BOTH halves. A TTL that only proves the hit is the
dangerous half-implementation: the body varies with the request's
`baseline` and `match_ts`, so a key that ignored either would serve one
match's Post Game Review under another match's selection - a product
defect strictly worse than 320ms.

Cache-key inputs are exactly (baseline, match_ts): _serve_last_match
touches nothing on the handler but `h.path` and `h._send`, and the body
is _build_last_match(baseline, match_ts) - a two-parameter signature.
Everything else the body depends on is match_history.db state, which is
bounded by the TTL and invalidated explicitly whenever an ingest stamps
a row (_try_ingest_once verdict "ok", reached from both the POST handler
and the background retry drain).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sqlite3
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import dashboard.routes_last_match as rlm


class StubHandler:
    def __init__(self, path: str = "/api/last-match"):
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


class CountingBuilder:
    """Stand-in for _build_last_match that records every call and returns a
    body echoing its arguments, so a wrong cache key shows up as a wrong
    body rather than only as a wrong call count."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, baseline, match_ts=None):
        self.calls.append((baseline, match_ts))
        return {"found": True, "seq": len(self.calls),
                "baseline_seen": baseline, "match_ts_seen": match_ts}


class LastMatchResponseCacheTests(unittest.TestCase):
    def setUp(self):
        rlm._cache_clear()
        self.builder = CountingBuilder()
        self._p = mock.patch.object(rlm, "_build_last_match", self.builder)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        rlm._cache_clear()

    def _get(self, path: str = "/api/last-match") -> StubHandler:
        h = StubHandler(path)
        rlm._serve_last_match(h)
        return h

    # --- the hit half ---------------------------------------------------

    def test_repeat_request_is_served_from_cache(self):
        first = self._get()
        second = self._get()
        self.assertEqual(len(self.builder.calls), 1)
        self.assertEqual(first.last_body, second.last_body)
        self.assertEqual(second.last_status, 200)
        self.assertEqual(second.last_ct, "application/json")

    def test_absent_baseline_and_explicit_20_share_one_entry(self):
        """The handler normalizes a missing ?baseline to 20 before keying,
        so the two request shapes must not build twice."""
        self._get("/api/last-match")
        self._get("/api/last-match?baseline=20")
        self.assertEqual(len(self.builder.calls), 1)

    def test_unrelated_query_param_does_not_split_the_key(self):
        self._get("/api/last-match")
        self._get("/api/last-match?cachebust=99")
        self.assertEqual(len(self.builder.calls), 1)

    # --- the miss half (the half a cache test usually omits) ------------

    def test_changed_baseline_is_not_served_from_cache(self):
        first = self._get("/api/last-match?baseline=20")
        second = self._get("/api/last-match?baseline=50")
        self.assertEqual(len(self.builder.calls), 2)
        self.assertEqual(self.builder.calls[1][0], 50)
        self.assertNotEqual(first.last_body, second.last_body)
        self.assertEqual(second.parsed()["baseline_seen"], 50)

    def test_changed_match_ts_is_not_served_from_cache(self):
        first = self._get("/api/last-match?match_ts=2026-06-01+12:00:00")
        second = self._get("/api/last-match?match_ts=2026-06-03+14:45:00")
        self.assertEqual(len(self.builder.calls), 2)
        self.assertNotEqual(first.last_body, second.last_body)
        self.assertEqual(second.parsed()["match_ts_seen"], "2026-06-03 14:45:00")

    def test_historical_ts_does_not_answer_the_live_request(self):
        """The live (no match_ts) path and a pinned historical row are
        distinct keys - this is the wrong-match-under-the-selection case."""
        hist = self._get("/api/last-match?match_ts=2026-06-01+12:00:00")
        live = self._get("/api/last-match")
        self.assertEqual(len(self.builder.calls), 2)
        self.assertEqual(hist.parsed()["match_ts_seen"], "2026-06-01 12:00:00")
        self.assertIsNone(live.parsed()["match_ts_seen"])

    def test_entry_expires_after_the_ttl(self):
        self._get()
        self.assertEqual(len(self.builder.calls), 1)
        with mock.patch.object(rlm, "_CACHE_TTL_S", -1.0):
            self._get()
        self.assertEqual(len(self.builder.calls), 2)

    def test_cache_is_bounded(self):
        for i in range(rlm._CACHE_MAX + rlm._CACHE_EVICT + 5):
            self._get(f"/api/last-match?baseline={5 + (i % 46)}&match_ts=t{i}")
        self.assertLessEqual(len(rlm._CACHE), rlm._CACHE_MAX)

    def test_error_path_is_not_cached(self):
        """A 500 must not be pinned for the whole TTL."""
        boom = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(rlm, "_build_last_match", boom):
            first = self._get()
            self.assertEqual(first.last_status, 500)
            second = self._get()
        self.assertEqual(second.last_status, 500)
        self.assertEqual(boom.call_count, 2)
        self.assertEqual(rlm._CACHE, {})


class DegradedBodyNotCachedTests(unittest.TestCase):
    """A degraded build returns HTTP 200 with an "error" key in the BODY
    rather than raising, so test_error_path_is_not_cached (which pins the
    raising path) does not cover it. Every degraded return in
    _build_last_match sets that one key - grep `out["error"]` in
    dashboard/builders_last_match.py for all three: "match_history.db
    missing" on the unopenable-db branch, and "internal error - see logs"
    on both the sqlite3.Error and the bare-Exception branches.

    Serving it is pre-existing behavior and stays. STORING it is what the
    cache added, and it converts a transient db hiccup that degraded a
    single request into a Post Game Review pinned degraded for the whole
    30s TTL. The sqlite branch even evicts its poisoned per-thread
    connection on the way out, so the very next build reopens cleanly and
    the next request would likely have succeeded.

    Served-but-not-stored is the fix rather than invalidate-on-degrade:
    a body is only built on a cache MISS, so there is no entry under that
    key to invalidate, and a failed build is no evidence about whether
    some OTHER key's cached body is still accurate.
    """

    def setUp(self):
        rlm._cache_clear()

    def tearDown(self):
        rlm._cache_clear()

    def _get(self, path: str = "/api/last-match") -> StubHandler:
        h = StubHandler(path)
        rlm._serve_last_match(h)
        return h

    def test_degraded_body_is_served_but_not_stored(self):
        calls = []

        def degraded(baseline, match_ts=None):
            calls.append((baseline, match_ts))
            return {"found": False, "match": None, "history_count": 0,
                    "error": "internal error - see logs"}

        with mock.patch.object(rlm, "_build_last_match", degraded):
            first = self._get()
            second = self._get()

        # Still served, still 200 - the degrade contract is unchanged.
        self.assertEqual(first.last_status, 200)
        self.assertEqual(first.parsed()["error"], "internal error - see logs")
        self.assertEqual(second.last_status, 200)
        # ...but rebuilt, not replayed from a stored entry.
        self.assertEqual(len(calls), 2)
        self.assertEqual(rlm._CACHE, {})

    def test_db_missing_body_is_not_stored(self):
        """The unopenable-db shape carries a different message on the same
        key, so the rule must key on the key and not on one message."""
        calls = []

        def no_db(baseline, match_ts=None):
            calls.append((baseline, match_ts))
            return {"found": False, "match": None, "history_count": 0,
                    "error": "match_history.db missing"}

        with mock.patch.object(rlm, "_build_last_match", no_db):
            self._get()
            self._get()
        self.assertEqual(len(calls), 2)
        self.assertEqual(rlm._CACHE, {})

    def test_a_transient_degrade_does_not_pin_the_next_request(self):
        """The blast-radius claim itself: one bad build must not mask the
        good body that the next request would have produced."""
        bodies = [
            {"found": False, "match": None, "error": "internal error - see logs"},
            {"found": True, "match": {"champion": "Caitlyn"}, "history_count": 7},
        ]
        calls = []

        def flaky(baseline, match_ts=None):
            calls.append((baseline, match_ts))
            return bodies[min(len(calls) - 1, len(bodies) - 1)]

        with mock.patch.object(rlm, "_build_last_match", flaky):
            degraded = self._get()
            recovered = self._get()
            # The recovered body IS durable - it caches normally.
            third = self._get()

        self.assertIn("error", degraded.parsed())
        self.assertTrue(recovered.parsed()["found"])
        self.assertEqual(recovered.parsed()["match"]["champion"], "Caitlyn")
        self.assertEqual(third.last_body, recovered.last_body)
        self.assertEqual(len(calls), 2)

    def test_found_false_without_an_error_key_is_still_cached(self):
        """An unknown match_ts legitimately returns found=False with NO
        error key - see the "NOT a silent latest fallback" paragraph in the
        _build_last_match docstring. That is a correct, durable answer, so
        keying the not-stored rule on `found` instead of on the error key
        would wrongly stop caching it."""
        calls = []

        def not_found(baseline, match_ts=None):
            calls.append((baseline, match_ts))
            return {"found": False, "match": None, "history_count": 0}

        with mock.patch.object(rlm, "_build_last_match", not_found):
            self._get("/api/last-match?match_ts=2020-01-01+00:00:00")
            self._get("/api/last-match?match_ts=2020-01-01+00:00:00")
        self.assertEqual(len(calls), 1)


class BaselineKeyNormalizationTests(unittest.TestCase):
    """`baseline` is clamped inside the builder, so keying the RAW value
    made ?baseline=1, ?baseline=2 and ?baseline=-5 three distinct keys
    holding identical bodies, each paying a full build. _CACHE_MAX bounds
    the memory and every request cost a build before the cache existed, so
    this is waste rather than a new exposure - but it is waste the cache
    is supposed to remove.

    The bounds are NOT restated here: each expectation is computed from
    the shared clamp the builder itself applies, so a future change to the
    range cannot leave the route and the test disagreeing.
    """

    def setUp(self):
        rlm._cache_clear()
        self.builder = CountingBuilder()
        self._p = mock.patch.object(rlm, "_build_last_match", self.builder)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        rlm._cache_clear()

    def _get(self, path: str) -> StubHandler:
        h = StubHandler(path)
        rlm._serve_last_match(h)
        return h

    def test_route_keys_the_clamped_value(self):
        from dashboard.builders_last_match import _clamp_baseline
        for raw in (-5, 0, 1, 2, 4, 5, 19, 20, 50, 51, 99, 10000):
            with self.subTest(raw=raw):
                rlm._cache_clear()
                self.builder.calls.clear()
                h = self._get(f"/api/last-match?baseline={raw}")
                self.assertEqual(self.builder.calls[0][0], _clamp_baseline(raw))
                self.assertEqual(h.parsed()["baseline_seen"], _clamp_baseline(raw))

    def test_below_range_values_collapse_to_one_entry(self):
        self._get("/api/last-match?baseline=1")
        self._get("/api/last-match?baseline=2")
        self._get("/api/last-match?baseline=-5")
        self.assertEqual(len(self.builder.calls), 1)
        self.assertEqual(len(rlm._CACHE), 1)

    def test_above_range_values_collapse_onto_the_ceiling(self):
        from dashboard.builders_last_match import _clamp_baseline
        ceiling = _clamp_baseline(10 ** 6)
        self._get(f"/api/last-match?baseline={ceiling}")
        self._get("/api/last-match?baseline=999")
        self.assertEqual(len(self.builder.calls), 1)
        self.assertEqual(self.builder.calls[0][0], ceiling)

    def test_unparseable_baseline_shares_the_default_entry(self):
        self._get("/api/last-match?baseline=abc")
        self._get("/api/last-match")
        self.assertEqual(len(self.builder.calls), 1)
        self.assertEqual(len(rlm._CACHE), 1)

    def test_in_range_values_still_key_separately(self):
        """The collapse must not over-reach into distinct valid windows."""
        self._get("/api/last-match?baseline=10")
        self._get("/api/last-match?baseline=30")
        self.assertEqual(len(self.builder.calls), 2)
        self.assertEqual([c[0] for c in self.builder.calls], [10, 30])


def _detail(game_id: int, *, game_creation_ms: int, game_duration_s: int,
            tracked_puuid: str = "puuid-A") -> dict:
    return {
        "gameId": game_id,
        "gameCreation": game_creation_ms,
        "gameDuration": game_duration_s,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": tracked_puuid}},
        ],
        "participants": [
            {"participantId": 1, "championId": 51,
             "stats": {"item0": 1055, "item1": 3032}},
        ],
    }


class LastMatchCacheIngestInvalidationTests(unittest.TestCase):
    """A completed match is immutable once ingested, but a NEW match must
    never be masked by a stale entry. These pin that a real ingest - via
    the POST handler AND via the background retry drain - drops the cache."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.app_dir = Path(self._tmp.name)
        (self.app_dir / "data").mkdir()
        self.db_path = self.app_dir / "data" / "match_history.db"
        from core.match_db import MatchDB
        MatchDB(self.db_path)
        self._p = mock.patch.object(rlm, "_APP_DIR", self.app_dir)
        self._p.start()
        rlm._cache_clear()
        rlm._INGEST_RETRY_QUEUE.clear()
        self.builder = CountingBuilder()
        self._pb = mock.patch.object(rlm, "_build_last_match", self.builder)
        self._pb.start()

    def tearDown(self):
        self._pb.stop()
        self._p.stop()
        rlm._cache_clear()
        rlm._INGEST_RETRY_QUEUE.clear()
        self._tmp.cleanup()

    def _seed_row(self, *, game_id: int = 0) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c = sqlite3.connect(str(self.db_path))
        c.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade, game_id,"
            " raw_data) VALUES (?,?,?,?,?,?)",
            (ts, "SR", "Caitlyn", "C", game_id, ""),
        )
        c.commit()
        c.close()

    def _body(self, game_id: int) -> dict:
        now_ms = int(time.time() * 1000)
        return {"tracked_puuid": "puuid-A",
                "match_detail": _detail(game_id, game_creation_ms=now_ms,
                                        game_duration_s=0)}

    def test_successful_post_ingest_invalidates(self):
        self._seed_row(game_id=4242)
        h = StubHandler("/api/last-match")
        rlm._serve_last_match(h)
        self.assertEqual(len(self.builder.calls), 1)

        post = StubHandler("/api/last-match/ingest")
        rlm._serve_last_match_ingest(post, self._body(4242))
        self.assertEqual(post.last_status, 200)

        rlm._serve_last_match(StubHandler("/api/last-match"))
        self.assertEqual(len(self.builder.calls), 2)

    def test_drain_completion_invalidates(self):
        rlm._serve_last_match(StubHandler("/api/last-match"))
        self.assertEqual(len(self.builder.calls), 1)

        # Queue an ingest with no matching row, then make the row appear -
        # the drain is what completes it, so the drain must invalidate.
        body = self._body(7777)
        post = StubHandler("/api/last-match/ingest")
        rlm._serve_last_match_ingest(post, body)
        self.assertEqual(post.last_status, 202)
        rlm._serve_last_match(StubHandler("/api/last-match"))
        queued_calls = len(self.builder.calls)

        self._seed_row(game_id=7777)
        self.assertEqual(rlm._drain_ingest_queue_once(), 1)

        rlm._serve_last_match(StubHandler("/api/last-match"))
        self.assertEqual(len(self.builder.calls), queued_calls + 1)

    def test_rejected_ingest_leaves_the_cache_intact(self):
        """A 400 changed no row, so it must not evict a valid entry."""
        self._seed_row(game_id=4242)
        rlm._serve_last_match(StubHandler("/api/last-match"))
        self.assertEqual(len(self.builder.calls), 1)

        bad = StubHandler("/api/last-match/ingest")
        rlm._serve_last_match_ingest(bad, {"tracked_puuid": ""})
        self.assertEqual(bad.last_status, 400)

        rlm._serve_last_match(StubHandler("/api/last-match"))
        self.assertEqual(len(self.builder.calls), 1)


if __name__ == "__main__":
    unittest.main()
