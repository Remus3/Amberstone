"""s144 true-audit (S144-T-619): dashboard/routes_ward_heat.py hardening.

GET /api/ward-heat is served on :8888 to any LAN peer and polled by the
Active Match ward strip (web/js/panels/ward_heat.js, every 4 s). Measured
on the module before this change:

  * one response was assembled from FIVE separate reads of the ward
    buffer (recent_wards, counts_by_lane, lanes_uncovered x2,
    buffer_size), each under its own lock acquisition, so a ward the
    producer recorded between two reads was in the counts but not in the
    wards list (or the reverse) of the same body;
  * a cache hit called h._send WHILE HOLDING _CACHE_LOCK, so a peer that
    stopped reading its socket held every other /api/ward-heat request
    behind the lock (the handler sets no socket write timeout);
  * the 2 s cache TTL ran on the wall clock, so a clock stepped back kept
    a grid "fresh" for the whole step, and elapsed_ms could go negative;
  * window_s went through float() on the raw text, so "1_0" read 10 and
    Arabic-Indic or fullwidth digits read as a number, and str.strip()
    also ate Unicode blanks such as U+3000;
  * the 200 body was dumped without allow_nan=False, so a non-finite
    number from the buffer would ship as a bare NaN token the browser's
    JSON.parse rejects for the whole body, and be cached;
  * the last-resort arm logged the raw exception text with no type name
    and no scrub.
"""
from __future__ import annotations

import json
import logging
import threading
import unittest
from unittest import mock

from core import ward_events
from dashboard import routes_ward_heat
from tests._timing_budget import fleet_test_guard


def _reject_constant(token: str):
    raise ValueError(f"non-standard JSON constant {token}")


class _Handler:
    def __init__(self, path: str):
        self.path = path
        self.status: int | None = None
        self.body: bytes | None = None
        self.lock_held_at_send: list[bool] = []

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.lock_held_at_send.append(routes_ward_heat._CACHE_LOCK.locked())
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"),
                          parse_constant=_reject_constant)


def _do(path: str = "/api/ward-heat") -> _Handler:
    h = _Handler(path)
    routes_ward_heat._serve_ward_heat(h)
    return h


class _FakeClock:
    """Stands in for the route module's ``time`` import."""

    def __init__(self, wall: float, mono: float):
        self.wall = wall
        self.mono = mono
        self.wall_step = 0.0
        self.perf = 0.0
        self.perf_step = 0.0

    def time(self) -> float:
        out = self.wall
        self.wall += self.wall_step
        return out

    def monotonic(self) -> float:
        return self.mono

    def perf_counter(self) -> float:
        out = self.perf
        self.perf += self.perf_step
        return out


class _Base(unittest.TestCase):
    def setUp(self):
        routes_ward_heat._reset_caches()
        ward_events.reset()

    def tearDown(self):
        routes_ward_heat._reset_caches()
        ward_events.reset()


class OneSnapshotPerBodyTests(_Base):
    def test_a_ward_recorded_mid_build_never_splits_the_body(self):
        # A producer append between the route's reads of the buffer is
        # simulated by recording one more ward after every recent_wards
        # read. Whatever the body holds, its counts and uncovered lists
        # must describe exactly its own wards list.
        base = 1_700_000_000.0
        real = ward_events.recent_wards
        lanes = iter(["top", "mid", "bot", "jg", "top", "mid", "bot", "jg"])

        def racing(*a, **kw):
            out = real(*a, **kw)
            ward_events.record_ward("ally", next(lanes), "yellow",
                                    ts=base - 1.0)
            return out

        ward_events.record_ward("enemy", "mid", "yellow", ts=base - 2.0)
        with mock.patch.object(ward_events, "recent_wards", racing):
            payload = routes_ward_heat._build_payload(90.0, base)
        wards = payload["wards"]
        total = sum(sum(v.values()) for v in payload["counts"].values())
        self.assertEqual(total, len(wards))
        for side in ("ally", "enemy"):
            covered = {w["lane"] for w in wards if w["side"] == side}
            want = [ln for ln in ward_events.NAMED_LANES if ln not in covered]
            self.assertEqual(payload[f"lanes_uncovered_{side}"], want)

    def test_uncovered_still_uses_the_narrower_60s_view(self):
        base = 1_700_000_000.0
        ward_events.record_ward("ally", "mid", "yellow", ts=base - 70.0)
        ward_events.record_ward("ally", "top", "yellow", ts=base - 10.0)
        ward_events.record_ward("enemy", "bot", "control", ts=base - 59.0)
        payload = routes_ward_heat._build_payload(90.0, base)
        self.assertEqual(len(payload["wards"]), 3)
        self.assertEqual(payload["counts"]["ally"]["mid"], 1)
        # mid is 70 s old: in the 90 s wards but outside the 60 s view.
        self.assertEqual(payload["lanes_uncovered_ally"], ["mid", "bot", "jg"])
        self.assertEqual(payload["lanes_uncovered_enemy"], ["top", "mid", "jg"])
        # A 30 s window narrows the uncovered view to 30 s too.
        narrow = routes_ward_heat._build_payload(30.0, base)
        self.assertEqual(narrow["lanes_uncovered_enemy"],
                         ["top", "mid", "bot", "jg"])

    def test_window_edges_match_the_store(self):
        base = 1_700_000_000.0
        for age in (90.0, 60.0, 0.0, -1.0, 90.5):
            ward_events.record_ward("ally", "jg", "yellow", ts=base - age)
        payload = routes_ward_heat._build_payload(90.0, base)
        self.assertEqual(sorted(base - w["ts"] for w in payload["wards"]),
                         [0.0, 60.0, 90.0])
        self.assertEqual(payload["lanes_uncovered_ally"], ["top", "mid", "bot"])

    def test_a_ward_exactly_60s_old_still_covers_its_lane(self):
        base = 1_700_000_000.0
        ward_events.record_ward("enemy", "top", "yellow", ts=base - 60.0)
        ward_events.record_ward("enemy", "mid", "yellow", ts=base - 60.25)
        payload = routes_ward_heat._build_payload(90.0, base)
        self.assertEqual(payload["lanes_uncovered_enemy"], ["mid", "bot", "jg"])


class NoSendUnderTheCacheLockTests(_Base):
    def test_miss_and_hit_both_send_with_the_lock_released(self):
        first = _do()
        second = _do()
        self.assertEqual(first.status, 200)
        self.assertFalse(first.parsed()["cached"])
        self.assertTrue(second.parsed()["cached"])
        self.assertEqual(first.lock_held_at_send, [False])
        self.assertEqual(second.lock_held_at_send, [False])

    def test_a_stalled_hit_does_not_block_another_request(self):
        _do()  # prime the cache
        entered = threading.Event()
        release = threading.Event()

        class _Stalled(_Handler):
            def _send(self, status, body, content_type):
                entered.set()
                release.wait(5.0)
                super()._send(status, body, content_type)

        stalled = _Stalled("/api/ward-heat")
        t = threading.Thread(target=routes_ward_heat._serve_ward_heat,
                             args=(stalled,), daemon=True)
        t.start()
        try:
            self.assertTrue(entered.wait(fleet_test_guard.budget(5.0)))
            other = _Handler("/api/ward-heat")
            done = threading.Event()

            def _run():
                routes_ward_heat._serve_ward_heat(other)
                done.set()

            threading.Thread(target=_run, daemon=True).start()
            self.assertTrue(done.wait(fleet_test_guard.budget(2.0)),
                            "a stalled send held the cache lock")
            self.assertEqual(other.status, 200)
        finally:
            release.set()
            t.join(5.0)


class MonotonicCacheTests(_Base):
    def test_a_wall_clock_step_back_does_not_keep_an_entry_fresh(self):
        clock = _FakeClock(wall=1_700_000_000.0, mono=500.0)
        with mock.patch.object(routes_ward_heat, "time", clock):
            first = _do().parsed()
            self.assertFalse(first["cached"])
            # One hour back on the wall clock, 2.5 s of real time later.
            clock.wall -= 3600.0
            clock.mono += 2.5
            second = _do().parsed()
        self.assertFalse(second["cached"])

    def test_within_ttl_on_the_monotonic_clock_is_a_hit(self):
        clock = _FakeClock(wall=1_700_000_000.0, mono=500.0)
        with mock.patch.object(routes_ward_heat, "time", clock):
            _do()
            clock.wall += 3600.0
            clock.mono += 1.0
            second = _do().parsed()
        self.assertTrue(second["cached"])

    def test_an_entry_stamped_in_the_future_is_never_served(self):
        clock = _FakeClock(wall=1_700_000_000.0, mono=500.0)
        with mock.patch.object(routes_ward_heat, "time", clock):
            _do()
            clock.mono -= 30.0
            second = _do().parsed()
        self.assertFalse(second["cached"])

    def test_elapsed_ms_runs_on_perf_counter_not_the_wall_clock(self):
        clock = _FakeClock(wall=1_700_000_000.0, mono=500.0)
        clock.wall_step = -10.0  # every wall read steps 10 s back
        clock.perf_step = 0.25   # 250 ms between a request's two reads
        with mock.patch.object(routes_ward_heat, "time", clock):
            miss = _do().parsed()
            hit = _do().parsed()
        self.assertFalse(miss["cached"])
        self.assertEqual(miss["elapsed_ms"], 250)
        self.assertTrue(hit["cached"])
        self.assertEqual(hit["elapsed_ms"], 250)


class WindowShapeTests(_Base):
    _NUMERIC = "window_s must be numeric"

    def test_non_ascii_or_underscore_spellings_are_refused(self):
        for raw in ("1_0", "3_0", "\u0669\u0660", "\uff19\uff10",
                    "\u300090", "90\u3000", "9\u00a00", "\u00a090",
                    "\U0001d7d7\U0001d7ce", "\x1f90", "90\x1c"):
            with self.subTest(raw=ascii(raw)):
                val, err = routes_ward_heat._parse_window({"window_s": [raw]})
                self.assertEqual(err, self._NUMERIC)
                self.assertEqual(val, 0.0)

    def test_route_refuses_them_with_the_fixed_body_and_no_cache(self):
        for q in ("1_0", "%D9%A9%D9%A0", "%EF%BC%99%EF%BC%90",
                  "%E3%80%8090"):
            with self.subTest(q=q):
                routes_ward_heat._reset_caches()
                h = _do(f"/api/ward-heat?window_s={q}")
                self.assertEqual(h.status, 400)
                self.assertEqual(h.parsed(),
                                 {"ok": False, "error": self._NUMERIC})
                self.assertEqual(routes_ward_heat._CACHE, {})

    def test_ascii_spellings_keep_their_old_reading(self):
        for raw, want in (("30", 30.0), ("30.5", 30.5), (" 30 ", 30.0),
                          ("\t60\n", 60.0), ("3e1", 30.0), ("+30", 30.0),
                          ("030", 30.0), ("600.0", 600.0), ("5", 5.0),
                          ("", 90.0), ("   ", 90.0)):
            with self.subTest(raw=raw):
                self.assertEqual(
                    routes_ward_heat._parse_window({"window_s": [raw]}),
                    (want, None))
        h = _do("/api/ward-heat?window_s=+30")  # '+' is a space in a query
        self.assertEqual(h.status, 200)
        self.assertEqual(h.parsed()["window_s"], 30.0)


class StrictJsonBodyTests(_Base):
    def test_a_non_finite_number_is_the_fixed_500_and_not_cached(self):
        bad = [{"ts": float("nan"), "side": "ally", "lane": "mid",
                "ward_type": "yellow"}]
        with mock.patch.object(ward_events, "recent_wards",
                               return_value=bad), \
                self.assertLogs("rc.web_dashboard", level="WARNING"):
            h = _do()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.parsed(),
                         {"ok": False, "error": "internal error - see logs"})
        self.assertEqual(routes_ward_heat._CACHE, {})
        self.assertEqual(h.lock_held_at_send, [False])


class LastResortLogTests(_Base):
    def test_the_log_names_the_type_and_escapes_control_characters(self):
        def boom(*_a, **_kw):
            raise RuntimeError("on fire\r\nFORGED rc.web_dashboard line")

        with mock.patch.object(routes_ward_heat, "_build_payload", boom), \
                self.assertLogs("rc.web_dashboard", level="WARNING") as cm:
            h = _do()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.parsed(),
                         {"ok": False, "error": "internal error - see logs"})
        text = "\n".join(r.getMessage() for r in cm.records)
        self.assertIn("RuntimeError", text)
        self.assertNotIn("\r\nFORGED", text)

    def test_an_exception_whose_str_raises_still_gets_the_fixed_500(self):
        class _Hostile(Exception):
            def __str__(self):
                raise RuntimeError("str() refused")

        with mock.patch.object(routes_ward_heat, "_build_payload",
                               side_effect=_Hostile()),                 self.assertLogs("rc.web_dashboard", level="WARNING"):
            h = _do()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.parsed(),
                         {"ok": False, "error": "internal error - see logs"})

    def test_a_failing_error_send_is_contained(self):
        class _Dead(_Handler):
            def _send(self, status, body, content_type):
                raise ConnectionResetError("peer gone")

        with mock.patch.object(routes_ward_heat, "_build_payload",
                               side_effect=RuntimeError("x")), \
                self.assertLogs("rc.web_dashboard", level="WARNING"):
            routes_ward_heat._serve_ward_heat(_Dead("/api/ward-heat"))


if __name__ == "__main__":
    unittest.main()
