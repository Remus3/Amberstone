"""Hardening tests for ``dashboard.routes_player_profile`` (s144 true-audit).

Each class pins one audited weakness of GET /api/player-profile:

- the integer params accepted every ``int()`` spelling (an Arabic-Indic digit,
  ``1_0``, ``+5``) instead of plain ASCII digits;
- a champion id too big for SQLite raised ``OverflowError`` inside the
  compute and was served as a misleading 503 "rewind history unavailable"
  instead of the documented 400; zero and negatives reached the query;
- a non-finite float in the payload was serialised as ``Infinity`` / ``NaN``,
  which the panel's ``r.json()`` rejects, and the bad body was cached;
- the cache-hit path wrote the response while holding ``_CACHE_LOCK``, so one
  slow client stalled every other request on the route;
- the cache TTL and ``elapsed_ms`` ran on the wall clock, so a backward clock
  step served a stale entry past its TTL and reported a negative elapsed;
- every compute exception, a programming bug included, became the 503
  "rewind history unavailable", logged without a traceback.

The compute is stubbed (``_compute``), so these tests need no rewind DB.
"""
from __future__ import annotations

import itertools
import json
import logging
import sqlite3
import time
import unittest
from unittest.mock import patch

from dashboard import routes_player_profile as rpp


class _Harness:
    def __init__(self, qs: str = "", on_send=None):
        self.path = "/api/player-profile" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None
        self._on_send = on_send

    def _send(self, status, body, content_type):
        if self._on_send is not None:
            self._on_send()
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


def _strict_loads(body: bytes):
    """json.loads that refuses the non-standard NaN / Infinity tokens, the
    way a browser's JSON.parse does."""
    def _reject(tok):
        raise ValueError(f"non-standard JSON constant {tok}")
    return json.loads(body, parse_constant=_reject)


def _ok_payload(**extra) -> dict:
    out = {"ok": True, "mode": "sr", "overall": 61.5, "axes": [],
           "champions": []}
    out.update(extra)
    return out


class _StubCompute:
    def __init__(self, payload=None, exc=None):
        self.calls: list[tuple] = []
        self._payload = payload
        self._exc = exc

    def __call__(self, mode, window, champion):
        self.calls.append((mode, window, champion))
        if self._exc is not None:
            raise self._exc
        return dict(self._payload if self._payload is not None
                    else _ok_payload())


class _Base(unittest.TestCase):
    def setUp(self):
        rpp._reset_caches()
        self.addCleanup(rpp._reset_caches)

    def serve(self, qs: str = "", stub=None, on_send=None) -> _Harness:
        stub = stub if stub is not None else _StubCompute()
        h = _Harness(qs, on_send=on_send)
        with patch.object(rpp, "_compute", stub):
            rpp._serve_player_profile(h)
        return h


class StrictIntegerParamTests(_Base):
    def test_window_rejects_non_ascii_int_spellings(self):
        # %D9%A5 is U+0665 ARABIC-INDIC DIGIT FIVE: int() reads it as 5.
        for raw in ("%D9%A5", "1_0", "%2B5", "5.0", "-1", "0x10", "0"):
            with self.subTest(raw=raw):
                stub = _StubCompute()
                h = self.serve(f"window={raw}", stub)
                self.assertEqual(h.sent_status, 400)
                self.assertEqual(stub.calls, [])

    def test_champion_rejects_non_ascii_int_spellings(self):
        for raw in ("%D9%A6%D9%A4", "6_4", "%2B64", "64.0", "0x40"):
            with self.subTest(raw=raw):
                stub = _StubCompute()
                h = self.serve(f"champion={raw}", stub)
                self.assertEqual(h.sent_status, 400)
                self.assertEqual(stub.calls, [])

    def test_champion_out_of_range_is_400_not_503(self):
        for raw in ("0", "-64", "1" + "0" * 30, "9" * 5000,
                    str(rpp._CHAMPION_MAX + 1)):
            with self.subTest(raw=raw[:20]):
                stub = _StubCompute()
                h = self.serve(f"champion={raw}", stub)
                self.assertEqual(h.sent_status, 400)
                self.assertEqual(stub.calls, [])
                body = json.loads(h.sent_body)
                self.assertFalse(body["ok"])
                self.assertNotIn(raw[:20], body["error"])

    def test_valid_ints_still_accepted(self):
        stub = _StubCompute()
        h = self.serve("window=007&champion=0064", stub)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(stub.calls, [("sr", 7, 64)])
        stub2 = _StubCompute()
        h2 = self.serve(f"window=100&champion={rpp._CHAMPION_MAX}", stub2)
        self.assertEqual(h2.sent_status, 200)
        self.assertEqual(stub2.calls, [("sr", 100, rpp._CHAMPION_MAX)])

    def test_real_champion_ids_with_sqlite_round_trip(self):
        # The upper bound must fit a SQLite INTEGER bind.
        conn = sqlite3.connect(":memory:")
        try:
            self.assertEqual(
                conn.execute("SELECT ?", (rpp._CHAMPION_MAX,)).fetchone()[0],
                rpp._CHAMPION_MAX)
        finally:
            conn.close()


class NonFinitePayloadTests(_Base):
    def test_non_finite_floats_serialise_as_null(self):
        stub = _StubCompute(_ok_payload(
            overall=float("inf"),
            axes=[{"key": "dpm", "score": float("nan"),
                   "recent_value": float("-inf"), "sample_n": 3}],
            kda_mean=2.5))
        h = self.serve("", stub)
        self.assertEqual(h.sent_status, 200)
        body = _strict_loads(h.sent_body)
        self.assertIsNone(body["overall"])
        self.assertIsNone(body["axes"][0]["score"])
        self.assertIsNone(body["axes"][0]["recent_value"])
        self.assertEqual(body["axes"][0]["sample_n"], 3)
        self.assertEqual(body["kda_mean"], 2.5)
        self.assertFalse(body["cached"])

        h2 = self.serve("", stub)
        self.assertEqual(h2.sent_status, 200)
        body2 = _strict_loads(h2.sent_body)
        self.assertTrue(body2["cached"])
        self.assertIsNone(body2["overall"])
        self.assertEqual(len(stub.calls), 1)


class CacheLockNotHeldDuringSendTests(_Base):
    def test_send_happens_outside_the_cache_lock(self):
        held: list[bool] = []

        def probe():
            held.append(rpp._CACHE_LOCK.locked())

        stub = _StubCompute()
        h1 = self.serve("", stub, on_send=probe)   # cold
        h2 = self.serve("", stub, on_send=probe)   # cache hit
        self.assertEqual(h1.sent_status, 200)
        self.assertEqual(h2.sent_status, 200)
        self.assertTrue(json.loads(h2.sent_body)["cached"])
        self.assertEqual(held, [False, False])


class MonotonicCacheClockTests(_Base):
    def test_backward_wall_clock_step_does_not_extend_ttl(self):
        stub = _StubCompute()
        self.assertEqual(self.serve("", stub).sent_status, 200)
        real_wall = time.time()
        real_mono = time.monotonic()
        with patch("time.time", return_value=real_wall - 3600.0), \
                patch("time.monotonic",
                      return_value=real_mono + rpp._CACHE_TTL_S + 1.0):
            h = self.serve("", stub)
        self.assertEqual(h.sent_status, 200)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(len(stub.calls), 2)

    def test_forward_wall_clock_step_does_not_expire_entry(self):
        stub = _StubCompute()
        self.assertEqual(self.serve("", stub).sent_status, 200)
        with patch("time.time", return_value=time.time() + 3600.0):
            h = self.serve("", stub)
        self.assertTrue(json.loads(h.sent_body)["cached"])
        self.assertEqual(len(stub.calls), 1)

    def test_elapsed_ms_never_negative_on_backward_step(self):
        counter = itertools.count()
        base = time.time()

        def stepping_back():
            return base - 10.0 * next(counter)

        for _ in range(2):  # cold, then cache hit
            with patch("time.time", side_effect=stepping_back):
                h = self.serve("", _StubCompute())
            self.assertEqual(h.sent_status, 200)
            self.assertGreaterEqual(json.loads(h.sent_body)["elapsed_ms"], 0)


class ComputeFailureClassificationTests(_Base):
    def test_db_errors_are_503(self):
        for exc in (sqlite3.OperationalError("unable to open database file"),
                    sqlite3.DatabaseError("file is not a database"),
                    OSError("disk gone")):
            with self.subTest(exc=type(exc).__name__):
                rpp._reset_caches()
                h = self.serve("", _StubCompute(exc=exc))
                self.assertEqual(h.sent_status, 503)
                body = json.loads(h.sent_body)
                self.assertEqual(body,
                                 {"ok": False,
                                  "error": "rewind history unavailable"})

    def test_programming_error_is_500_with_traceback_logged(self):
        with self.assertLogs("rc.web_dashboard", level=logging.WARNING) as cm:
            h = self.serve("", _StubCompute(exc=TypeError("secret-ish detail")))
        self.assertEqual(h.sent_status, 500)
        body = json.loads(h.sent_body)
        self.assertFalse(body["ok"])
        self.assertNotIn("secret-ish detail", h.sent_body.decode("utf-8"))
        self.assertTrue(any(r.exc_info for r in cm.records))

    def test_failure_is_not_cached(self):
        h = self.serve("", _StubCompute(exc=sqlite3.OperationalError("x")))
        self.assertEqual(h.sent_status, 503)
        stub = _StubCompute()
        h2 = self.serve("", stub)
        self.assertEqual(h2.sent_status, 200)
        self.assertFalse(json.loads(h2.sent_body)["cached"])
        self.assertEqual(len(stub.calls), 1)


class CacheBoundTests(_Base):
    def test_cache_stays_bounded(self):
        for champ in range(1, rpp._CACHE_MAX + 20):
            self.assertEqual(self.serve(f"champion={champ}").sent_status, 200)
        self.assertLessEqual(len(rpp._CACHE), rpp._CACHE_MAX)


if __name__ == "__main__":
    unittest.main()
