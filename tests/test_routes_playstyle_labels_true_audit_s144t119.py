"""s144 true-audit cycle 119: GET /api/playstyle-labels hardening.

dashboard/routes_playstyle_labels.py is the thin HTTP surface the snapshot
card polls; it parses two caller-supplied query values and forwards
core.playstyle_labels.compute_playstyle_labels to the browser. Findings,
each pinned red before the fix:

- RM-1495 the cache-hit path wrote the socket while holding _CACHE_LOCK,
             so one stalled client blocked every other request on the route.
- RM-1496 the cache TTL and elapsed_ms ran on time.time: a wall-clock step
             back froze an entry past its TTL and reported a negative
             elapsed_ms.
- RM-1497 a non-finite float in the payload (an Infinity tracked_kp row
             reaches the kp mean) was re-emitted as a bare Infinity / NaN
             token, so JSON.parse rejected the WHOLE body.
- RM-1498 a queue token was parsed with bare int(): a sign, "_"
             separators and non-ASCII digits were accepted, and an id past
             SQLite's 64-bit INTEGER raised OverflowError inside the core
             (not a sqlite3.Error, so it escaped) -> 500 instead of 400.
- RM-1499 a present-but-empty queue value (queue=,) became an EMPTY
             filter: a 200 with n=0 served and cached as if the corpus were
             empty.
- RM-1500 the queue list was unbounded and its cache key order- and
             duplicate-sensitive: 420,450 / 450,420 / 420,420,450 were three
             corpus scans and three cache entries.
- RM-1501 min_games was parsed with bare int() (sign, "_", non-ASCII
             digits accepted) and had no upper bound.
"""
from __future__ import annotations

import json
import math
import threading
import time
import unittest
from unittest.mock import patch

from dashboard import routes_playstyle_labels as rpl

_COMPUTE = "dashboard.routes_playstyle_labels.playstyle_labels." \
           "compute_playstyle_labels"


def _payload(**over):
    body = {
        "ok": True, "n": 7, "min_games": 5, "rel_threshold": 0.2,
        "overall_wr": 0.5, "overall_wins": 3,
        "baseline": {"kills": 5.0, "deaths": 4.0, "assists": 9.0,
                     "kp": 0.5, "kda_ratio": 3.5},
        "champions": [{
            "champion_id": 64, "champion_name": "LeeSin", "games": 7,
            "wins": 3, "wr": 0.4444, "wr_blended": 0.47,
            "means": {"kills": 5.0, "deaths": 4.0, "assists": 9.0,
                      "kp": 0.5, "kda_ratio": 3.5},
            "kda_cv": 0.4, "labels": [],
        }],
    }
    body.update(over)
    return body


class _Harness:
    def __init__(self, qs: str = ""):
        self.path = "/api/playstyle-labels" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = b""
        self.lock_held_during_send = None

    def _send(self, status, body, content_type):
        self.lock_held_during_send = rpl._CACHE_LOCK.locked()
        self.sent_status = status
        self.sent_body = body


def _serve(qs: str = "", result=None):
    h = _Harness(qs)
    with patch(_COMPUTE, return_value=result if result is not None
               else _payload()) as comp:
        rpl._serve_playstyle_labels(h)
    return h, comp


class _Base(unittest.TestCase):
    def setUp(self):
        rpl._reset_caches()

    def tearDown(self):
        rpl._reset_caches()

    def body(self, h):
        return json.loads(h.sent_body.decode("utf-8"))


class LockTests(_Base):
    """RM-1495: no socket write while _CACHE_LOCK is held."""

    def test_cache_hit_sends_outside_the_lock(self):
        _serve()
        h, comp = _serve()
        comp.assert_not_called()
        self.assertTrue(self.body(h)["cached"])
        self.assertIs(h.lock_held_during_send, False)

    def test_cache_miss_sends_outside_the_lock(self):
        h, _ = _serve()
        self.assertIs(h.lock_held_during_send, False)

    def test_a_hit_does_not_mutate_the_cached_entry(self):
        _serve()
        _serve()
        with rpl._CACHE_LOCK:
            (_, cached), = rpl._CACHE.values()
        self.assertNotIn("cached", cached)
        self.assertNotIn("elapsed_ms", cached)

    def test_stalled_client_does_not_block_another_request(self):
        _serve()
        release = threading.Event()
        entered = threading.Event()

        class _Stall(_Harness):
            def _send(self, status, body, content_type):
                entered.set()
                release.wait(5)
                super()._send(status, body, content_type)

        stalled = _Stall()
        t = threading.Thread(target=rpl._serve_playstyle_labels,
                             args=(stalled,), daemon=True)
        with patch(_COMPUTE, return_value=_payload()):
            t.start()
            self.assertTrue(entered.wait(5))
            got = rpl._CACHE_LOCK.acquire(timeout=1)
            if got:
                rpl._CACHE_LOCK.release()
            release.set()
            t.join(5)
        self.assertTrue(got, "_CACHE_LOCK held across a stalled send")


class ClockTests(_Base):
    """RM-1496: TTL and elapsed_ms run on a monotonic route clock."""

    def test_route_clock_is_monotonic(self):
        self.assertIs(rpl._clock, time.monotonic)

    def test_backward_clock_never_negative_elapsed(self):
        ticks = iter([1000.0, 1000.0, 990.0])
        with patch.object(rpl, "_clock", side_effect=lambda: next(ticks)):
            h, _ = _serve()
        self.assertGreaterEqual(self.body(h)["elapsed_ms"], 0)

    def test_cache_expires_on_the_route_clock(self):
        now = [1000.0]
        with patch.object(rpl, "_clock", side_effect=lambda: now[0]):
            _serve()
            now[0] += rpl._CACHE_TTL_S + 1
            h, comp = _serve()
        comp.assert_called_once()
        self.assertFalse(self.body(h)["cached"])

    def test_entry_from_the_future_is_not_served(self):
        now = [1000.0]
        with patch.object(rpl, "_clock", side_effect=lambda: now[0]):
            _serve()
            now[0] -= 50.0
            h, comp = _serve()
        comp.assert_called_once()
        self.assertFalse(self.body(h)["cached"])


class NonFiniteTests(_Base):
    """RM-1497: the body is strict JSON whatever floats the core hands."""

    def _strict(self, h):
        raw = h.sent_body.decode("utf-8")
        for tok in ("NaN", "Infinity"):
            self.assertNotIn(tok, raw)
        return json.loads(raw, parse_constant=lambda c: self.fail(c))

    def test_infinite_kp_mean_reads_null(self):
        p = _payload()
        p["champions"][0]["means"]["kp"] = math.inf
        p["baseline"]["kp"] = -math.inf
        h, _ = _serve(result=p)
        self.assertEqual(h.sent_status, 200)
        body = self._strict(h)
        self.assertIsNone(body["champions"][0]["means"]["kp"])
        self.assertIsNone(body["baseline"]["kp"])

    def test_label_built_on_a_non_number_is_dropped(self):
        p = _payload()
        p["champions"][0]["labels"] = [
            {"tag": "team-involved", "value": math.nan, "baseline": 0.5},
            {"tag": "death-prone", "value": 6.0, "baseline": math.inf},
            {"tag": "consistent", "value": 0.2, "baseline": None},
        ]
        p["overall_wr"] = math.nan
        h, _ = _serve(result=p)
        body = self._strict(h)
        self.assertEqual([lb["tag"] for lb in body["champions"][0]["labels"]],
                         ["consistent"])
        self.assertIsNone(body["overall_wr"])

    def test_malformed_champions_and_labels_pass_untouched(self):
        p = _payload(champions=[{"labels": "x"}, "junk", None])
        h, _ = _serve(result=p)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(self._strict(h)["champions"],
                         [{"labels": "x"}, "junk", None])

    def test_finite_values_and_types_kept(self):
        h, _ = _serve()
        body = self._strict(h)
        self.assertEqual(body["n"], 7)
        self.assertIs(type(body["n"]), int)
        self.assertEqual(body["champions"][0]["means"]["kp"], 0.5)
        self.assertIs(body["ok"], True)

    def test_cached_copy_is_clean_too(self):
        p = _payload()
        p["champions"][0]["means"]["kp"] = math.inf
        _serve(result=p)
        h, comp = _serve()
        comp.assert_not_called()
        self.assertIsNone(self._strict(h)["champions"][0]["means"]["kp"])


class QueueTokenTests(_Base):
    """RM-1498 / -181 / -182: queue is 1..16 ASCII-digit ids."""

    _ERR_INT = "queue must be comma-separated integers"

    def _bad(self, qs, expected=None):
        h, comp = _serve(qs)
        comp.assert_not_called()
        self.assertEqual(h.sent_status, 400, qs)
        if expected is not None:
            self.assertEqual(self.body(h), {"ok": False, "error": expected})
        return h

    def test_id_past_sqlite_integer_is_a_400(self):
        self._bad("queue=99999999999999999999", self._ERR_INT)

    def test_signed_underscored_and_non_ascii_ids_refused(self):
        # %2B is a literal "+" (a bare "+" in a query string decodes to a
        # space, which the strip removes - that one is a plain 420)
        for tok in ("-420", "%2B420", "4_20", chr(0x664) + chr(0x662) + chr(0x660),
                    "%D9%A4%D9%A2%D9%A0"):
            with self.subTest(tok=tok):
                self._bad("queue=" + tok, self._ERR_INT)

    def test_present_but_empty_queue_refused(self):
        for raw in (",", " , ,"):
            with self.subTest(raw=raw):
                self._bad("queue=" + raw.replace(" ", "%20"), self._ERR_INT)

    def test_too_many_ids_refused(self):
        many = ",".join(str(400 + i) for i in range(rpl._MAX_QUEUE_IDS + 1))
        h = self._bad("queue=" + many)
        self.assertNotIn("400", self.body(h)["error"])

    def test_max_ids_accepted(self):
        many = ",".join(str(400 + i) for i in range(rpl._MAX_QUEUE_IDS))
        h, comp = _serve("queue=" + many)
        self.assertEqual(h.sent_status, 200)
        comp.assert_called_once()

    def test_order_and_duplicates_share_one_entry(self):
        _, comp = _serve("queue=420,450")
        kwargs = comp.call_args.kwargs
        self.assertEqual(tuple(kwargs["queue_ids"]), (420, 450))
        for qs in ("queue=450,420", "queue=420,450,420",
                   "queue=%20450%20,420"):
            with self.subTest(qs=qs):
                h, comp2 = _serve(qs)
                comp2.assert_not_called()
                self.assertTrue(self.body(h)["cached"])
        self.assertEqual(len(rpl._CACHE), 1)

    def test_absent_and_blank_queue_mean_all(self):
        for qs in ("", "queue=", "queue=%20"):
            with self.subTest(qs=qs):
                rpl._reset_caches()
                h, comp = _serve(qs)
                self.assertEqual(h.sent_status, 200)
                self.assertIsNone(comp.call_args.kwargs["queue_ids"])

    def test_plain_ids_pass_through(self):
        h, comp = _serve("queue=0,2400")
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(tuple(comp.call_args.kwargs["queue_ids"]),
                         (0, 2400))


class MinGamesTests(_Base):
    """RM-1501: min_games is 1..1000 ASCII digits."""

    def _bad(self, raw, expected):
        h, comp = _serve("min_games=" + raw)
        comp.assert_not_called()
        self.assertEqual(h.sent_status, 400, raw)
        self.assertEqual(self.body(h), {"ok": False, "error": expected})

    def test_lenient_int_forms_refused(self):
        for raw in ("%2B5", "1_0", "%D9%A5", "5.0", "-3"):
            with self.subTest(raw=raw):
                self._bad(raw, "min_games must be an integer")

    def test_out_of_range_refused_without_echo(self):
        # 5000 digits: past int()'s 4300-digit conversion limit, so a parse
        # that reaches int() raises ValueError -> a 500, not this 400
        for raw in ("0", "1001", "987654321987654321", "9" * 5000,
                    "0" * 5000 + "5000"):
            with self.subTest(raw=raw):
                self._bad(raw, "min_games must be between 1 and 1000")

    def test_bounds_accepted(self):
        for raw, want in (("1", 1), ("1000", 1000), ("007", 7)):
            with self.subTest(raw=raw):
                rpl._reset_caches()
                h, comp = _serve("min_games=" + raw)
                self.assertEqual(h.sent_status, 200)
                self.assertEqual(comp.call_args.kwargs["min_games"], want)

    def test_absent_uses_core_default(self):
        _, comp = _serve()
        self.assertEqual(comp.call_args.kwargs["min_games"],
                         rpl.playstyle_labels.MIN_GAMES)


class RealCoreTests(_Base):
    """The two root causes end to end, through the REAL core over a tmp DB."""

    def setUp(self):
        super().setUp()
        import sqlite3
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "rewind_history.db"
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE matches (queue_id INTEGER, tracked_champion_id "
            "INTEGER, tracked_champion_name TEXT, tracked_win INTEGER, "
            "tracked_kills INTEGER, tracked_deaths INTEGER, "
            "tracked_assists INTEGER, tracked_kp REAL)")
        rows = [(450, 64, "LeeSin", 1, 5, 3, 9, 0.5)] * 6
        rows.append((450, 64, "LeeSin", 0, 2, 6, 4, math.inf))
        conn.executemany("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def _real(self, qs):
        real = rpl.playstyle_labels.compute_playstyle_labels
        h = _Harness(qs)
        with patch(_COMPUTE, side_effect=lambda **kw: real(
                db_path=self.db, **kw)):
            rpl._serve_playstyle_labels(h)
        return h

    def test_overflowing_queue_id_is_a_400_not_a_500(self):
        h = self._real("queue=99999999999999999999")
        self.assertEqual(h.sent_status, 400)

    def test_infinite_kp_row_keeps_the_body_parseable(self):
        h = self._real("queue=450")
        self.assertEqual(h.sent_status, 200)
        raw = h.sent_body.decode("utf-8")
        self.assertNotIn("Infinity", raw)
        body = json.loads(raw)
        self.assertEqual(body["n"], 7)
        self.assertIsNone(body["baseline"]["kp"])
        # the core's spurious inf >= inf * 1.2 "team-involved" label is not
        # served (core root cause filed as RM-1502)
        tags = [lb["tag"] for lb in body["champions"][0]["labels"]]
        self.assertNotIn("team-involved", tags)


class FailureTests(_Base):
    def test_core_exception_is_a_generic_500(self):
        h = _Harness()
        with patch(_COMPUTE, side_effect=OverflowError("SECRETISH detail")):
            with self.assertLogs("rc.web_dashboard", "WARNING"):
                rpl._serve_playstyle_labels(h)
        self.assertEqual(h.sent_status, 500)
        self.assertNotIn(b"SECRETISH", h.sent_body)
        self.assertEqual(json.loads(h.sent_body),
                         {"ok": False, "error": "internal error - see logs"})


if __name__ == "__main__":
    unittest.main()
