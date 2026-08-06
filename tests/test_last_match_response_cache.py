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
