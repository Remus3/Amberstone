"""True-audit regressions for GET /api/champ-benchmarks (S144-T-629).

dashboard/routes_champ_benchmarks.py is a GET route on :8888 (a LAN peer
reaches it with any query) whose live client is
web/js/panels/champ_benchmarks.js (mode=sr|aram|arena). Its rows come from
core.benchmarks.rows_for_mode over data/coach_reference/champion_benchmarks.json,
a file RC writes but a hand edit, a builder change or a half-merged file can
put any JSON value in. Each class pins one finding of the s144 true-audit
cycle 224 against the route module; rows_for_mode is patched, so nothing here
reads data/ (clean-checkout safe, like tests/test_routes_champ_benchmarks.py).
"""
from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import patch

from dashboard import routes_champ_benchmarks as rcb

_ROWS = "dashboard.routes_champ_benchmarks.benchmarks.rows_for_mode"
_COLS = ["cs_at_10", "gold_at_10", "gold_at_15", "kill_participation_pct",
         "level_at_10"]


def _strict_loads(raw: bytes):
    """json.loads that refuses NaN / Infinity, as the browser's JSON.parse."""
    def _refuse(token):
        raise ValueError(f"non-finite token {token}")
    return json.loads(raw.decode("utf-8"), parse_constant=_refuse)


def _metric(p50, n=12):
    return {"p25": p50 - 1, "p50": p50, "p75": p50 + 1, "avg": p50,
            "n": n, "weighted_n": float(n)}


def _good(champ="Vayne", games=50):
    return {"champion": champ, "games": games,
            "metrics": {m: _metric(6.0 + i) for i, m in enumerate(_COLS)}}


class _Harness:
    def __init__(self, qs: str = "", fail_send: BaseException | None = None):
        self.path = "/api/champ-benchmarks" + (f"?{qs}" if qs else "")
        self.status = None
        self.body = None
        self.lock_held_at_send = None
        self._fail = fail_send

    def _send(self, status, body, content_type):
        self.lock_held_at_send = rcb._CACHE_LOCK.locked()
        if self._fail is not None:
            raise self._fail
        self.status = status
        self.body = body

    def json(self):
        return _strict_loads(self.body)


class _Base(unittest.TestCase):
    rows: list = []

    def setUp(self):
        rcb._reset_caches()
        self.addCleanup(rcb._reset_caches)
        self._p = patch(_ROWS, side_effect=lambda mode: list(self.rows))
        self.reader = self._p.start()
        self.addCleanup(self._p.stop)

    def get(self, qs="", **kw):
        h = _Harness(qs, **kw)
        rcb._serve_champ_benchmarks(h)
        return h

    def champs(self, h):
        return [r["champion"] for r in h.json()["rows"]]


class MonotonicCacheClockTests(_Base):
    """The 5 min TTL ran on time.time: a wall clock stepped back kept an
    entry fresh for the whole step, and elapsed_ms could go negative."""

    rows = [_good()]

    def test_entry_expires_on_the_monotonic_clock_whatever_the_wall_clock(self):
        mono = [1000.0]
        with patch.object(rcb.time, "monotonic", lambda: mono[0]), \
                patch.object(rcb.time, "time", lambda: 5.0):
            self.get()
            mono[0] += rcb._CACHE_TTL_S + 1
            h = self.get()
        self.assertFalse(h.json()["cached"])
        self.assertEqual(self.reader.call_count, 2)

    def test_an_entry_stamped_in_the_future_is_never_served(self):
        mono = [1000.0]
        with patch.object(rcb.time, "monotonic", lambda: mono[0]):
            self.get()
            mono[0] -= 50.0
            h = self.get()
        self.assertFalse(h.json()["cached"])

    def test_a_fresh_entry_is_still_served_from_cache(self):
        self.get()
        h = self.get()
        self.assertTrue(h.json()["cached"])
        self.assertEqual(self.reader.call_count, 1)

    def test_elapsed_ms_is_never_negative_when_the_wall_clock_steps_back(self):
        clock = iter([1000.0, 900.0, 900.0, 900.0, 900.0, 900.0])
        with patch.object(rcb.time, "time", lambda: next(clock, 900.0)):
            h = self.get()
        self.assertGreaterEqual(h.json()["elapsed_ms"], 0)


class SendOutsideLockTests(_Base):
    """A cache hit was written to the socket while _CACHE_LOCK was held, so
    a client that stopped reading held every other request behind it."""

    rows = [_good()]

    def test_a_miss_is_sent_without_the_lock(self):
        h = self.get()
        self.assertEqual(h.status, 200)
        self.assertFalse(h.lock_held_at_send)

    def test_a_hit_is_sent_without_the_lock(self):
        self.get()
        h = self.get()
        self.assertTrue(h.json()["cached"])
        self.assertFalse(h.lock_held_at_send)


class AsciiQueryTests(_Base):
    """str.strip() with no argument also strips Unicode blanks."""

    rows = [_good()]

    def test_mode_with_ideographic_space_padding_is_refused(self):
        h = self.get("mode=sr%E3%80%80")
        self.assertEqual(h.status, 400)

    def test_mode_with_nbsp_padding_is_refused(self):
        h = self.get("mode=%C2%A0aram")
        self.assertEqual(h.status, 400)

    def test_ascii_padding_still_parses(self):
        h = self.get("mode=%20sr%09")
        self.assertEqual(h.status, 200)
        self.assertEqual(h.json()["mode"], "sr")

    def test_the_400_does_not_echo_the_value(self):
        h = self.get("mode=%3Cscript%3E")
        self.assertEqual(h.status, 400)
        self.assertNotIn(b"script", h.body)


class JunkGamesTests(_Base):
    """games went through int(): one junk row 500ed the whole table (a str,
    NaN, inf, dict or list), and a fractional or huge count was served."""

    def _with(self, games):
        self.rows = [_good("Vayne", 50),
                     dict(_good("Junk", 9), games=games),
                     _good("Jinx", 12)]
        return self.get()

    def _assert_junk_dropped(self, games):
        h = self._with(games)
        self.assertEqual(h.status, 200, games)
        self.assertEqual(self.champs(h), ["Vayne", "Jinx"], games)
        self.assertEqual(h.json()["n"], 2)

    def test_non_digit_str_drops_that_row_only(self):
        self._assert_junk_dropped("abc")

    def test_nan_drops_that_row_only(self):
        self._assert_junk_dropped(float("nan"))

    def test_inf_drops_that_row_only(self):
        self._assert_junk_dropped(float("inf"))

    def test_dict_drops_that_row_only(self):
        self._assert_junk_dropped({"n": 9})

    def test_list_drops_that_row_only(self):
        self._assert_junk_dropped([9])

    def test_fractional_count_is_not_truncated_into_the_table(self):
        self._assert_junk_dropped(3.7)

    def test_digit_str_is_not_a_count(self):
        self._assert_junk_dropped("9")

    def test_huge_count_is_dropped(self):
        # The panel renders games with `| 0`, which wraps past 2**31.
        self._assert_junk_dropped(10 ** 20)

    def test_bool_is_not_a_count(self):
        self._assert_junk_dropped(True)

    def test_integral_float_count_is_kept_as_an_int(self):
        h = self._with(9.0)
        self.assertEqual(self.champs(h), ["Vayne", "Junk", "Jinx"])
        junk = h.json()["rows"][1]
        self.assertEqual(junk["games"], 9)
        self.assertIsInstance(junk["games"], int)

    def test_null_or_absent_games_is_below_the_gate_as_before(self):
        self._assert_junk_dropped(None)
        rcb._reset_caches()
        row = _good("Junk", 9)
        del row["games"]
        self.rows = [_good("Vayne", 50), row, _good("Jinx", 12)]
        self.assertEqual(self.champs(self.get()), ["Vayne", "Jinx"])


class JunkRowTests(_Base):
    """A non-dict row, or a non-str / empty champion, 500ed or was served."""

    def test_non_dict_row_is_skipped(self):
        self.rows = [_good("Vayne"), ["Junk", 9], None, "x", _good("Jinx", 12)]
        h = self.get()
        self.assertEqual(h.status, 200)
        self.assertEqual(self.champs(h), ["Vayne", "Jinx"])

    def test_non_str_or_empty_champion_is_skipped(self):
        self.rows = [_good("Vayne"), dict(_good(), champion=7),
                     dict(_good(), champion=""), dict(_good(), champion=None),
                     _good("Jinx", 12)]
        self.assertEqual(self.champs(self.get()), ["Vayne", "Jinx"])


class JunkMetricsTests(_Base):
    """A non-dict metrics block or metric cell 500ed the whole table."""

    def test_list_metrics_keeps_the_row_with_no_stats(self):
        self.rows = [dict(_good("Vayne"), metrics=["cs_at_10"]),
                     _good("Jinx", 12)]
        h = self.get()
        self.assertEqual(h.status, 200)
        self.assertEqual(self.champs(h), ["Vayne", "Jinx"])
        self.assertEqual(h.json()["rows"][0]["stats"], {})

    def test_str_metrics_keeps_the_row_with_no_stats(self):
        self.rows = [dict(_good("Vayne"), metrics="cs_at_10")]
        h = self.get()
        self.assertEqual(h.status, 200)
        self.assertEqual(h.json()["rows"][0]["stats"], {})

    def test_non_dict_cell_is_omitted_and_the_rest_kept(self):
        row = _good("Vayne")
        row["metrics"]["cs_at_10"] = 17.0
        row["metrics"]["gold_at_10"] = ["p50"]
        row["metrics"]["gold_at_15"] = "p50"
        self.rows = [row]
        h = self.get()
        self.assertEqual(h.status, 200)
        stats = h.json()["rows"][0]["stats"]
        self.assertEqual(sorted(stats),
                         ["kill_participation_pct", "level_at_10"])


class StatValueTests(_Base):
    """Stat values were passed through: a NaN / Infinity became a bare token
    the browser's JSON.parse rejects for the whole panel, and a str / bool /
    nested value reached the client as data."""

    def _cell(self, **fields):
        row = _good("Vayne")
        row["metrics"]["cs_at_10"] = dict(_metric(17.0), **fields)
        self.rows = [row]
        h = self.get()
        self.assertEqual(h.status, 200)
        return h.json()["rows"][0]["stats"]["cs_at_10"]

    def test_nan_p50_is_null_in_strict_json(self):
        self.assertIsNone(self._cell(p50=float("nan"))["p50"])

    def test_infinite_spread_is_null(self):
        cell = self._cell(p25=float("-inf"), p75=float("inf"))
        self.assertIsNone(cell["p25"])
        self.assertIsNone(cell["p75"])
        self.assertEqual(cell["p50"], 17.0)

    def test_the_cached_copy_is_strict_too(self):
        self._cell(avg=float("nan"))
        h = self.get()
        self.assertTrue(h.json()["cached"])
        self.assertIsNone(h.json()["rows"][0]["stats"]["cs_at_10"]["avg"])

    def test_str_bool_and_nested_values_are_null(self):
        cell = self._cell(p50="17", p25=True, p75={"v": 1}, avg=[1])
        self.assertEqual(
            {k: cell[k] for k in ("p50", "p25", "p75", "avg")},
            {"p50": None, "p25": None, "p75": None, "avg": None})

    def test_huge_int_value_is_null_not_a_500(self):
        cell = self._cell(p50=10 ** 400)
        self.assertIsNone(cell["p50"])

    def test_n_must_be_a_non_negative_whole_count(self):
        for bad in (-1, 2.5, True, "12", float("nan"), 10 ** 20):
            rcb._reset_caches()
            self.assertIsNone(self._cell(n=bad)["n"], bad)
        rcb._reset_caches()
        cell = self._cell(n=12.0)
        self.assertEqual(cell["n"], 12)
        self.assertIsInstance(cell["n"], int)

    def test_absent_sub_field_stays_absent(self):
        row = _good("Vayne")
        row["metrics"]["cs_at_10"] = {"p50": 17.0}
        self.rows = [row]
        cell = self.get().json()["rows"][0]["stats"]["cs_at_10"]
        self.assertEqual(cell, {"p50": 17.0})


class ValidPayloadUnchangedTests(_Base):
    """A clean corpus serialises exactly as before (order, types, values)."""

    rows = [_good("Vayne", 50),
            {"champion": "Jinx", "games": 12,
             "metrics": {m: _metric(7, n=4) for m in _COLS if m != "gold_at_15"}},
            _good("Teemo", 2)]

    def test_exact_body(self):
        body = self.get().json()
        body.pop("elapsed_ms")
        vayne_stats = {m: {"p50": 6.0 + i, "p25": 5.0 + i, "p75": 7.0 + i,
                           "avg": 6.0 + i, "n": 12}
                       for i, m in enumerate(_COLS)}
        jinx_stats = {m: {"p50": 7, "p25": 6, "p75": 8, "avg": 7, "n": 4}
                      for m in _COLS if m != "gold_at_15"}
        self.assertEqual(body, {
            "ok": True, "mode": "sr", "n": 2, "min_games": 3,
            "metrics": _COLS,
            "rows": [{"champion": "Vayne", "games": 50, "stats": vayne_stats},
                     {"champion": "Jinx", "games": 12, "stats": jinx_stats}],
            "cached": False})
        self.assertIsInstance(
            body["rows"][1]["stats"]["cs_at_10"]["p50"], int)


class LastResortTests(_Base):
    """The last-resort arm logged the raw exception text with no type name,
    unscrubbed, and swallowed every failure of the error send."""

    rows = [_good()]

    def test_the_log_line_names_the_exception_type(self):
        self.reader.side_effect = RuntimeError("boom")
        with self.assertLogs(level=logging.WARNING) as cm:
            h = self.get()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.json(),
                         {"ok": False, "error": "internal error - see logs"})
        self.assertTrue(any("RuntimeError" in line for line in cm.output),
                        cm.output)

    def test_an_exception_whose_str_raises_still_gets_the_fixed_500(self):
        class Nasty(Exception):
            def __str__(self):
                raise ValueError("no str")
        self.reader.side_effect = Nasty()
        with self.assertLogs(level=logging.WARNING):
            h = self.get()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.json(),
                         {"ok": False, "error": "internal error - see logs"})

    def test_a_client_gone_during_send_does_not_raise(self):
        with self.assertLogs(level=logging.WARNING):
            self.get(fail_send=ConnectionResetError("gone"))

    def test_a_non_finite_value_the_scrub_missed_is_the_fixed_500(self):
        # Backstop: the body is dumped with allow_nan=False, so anything the
        # row shaping did not see becomes the fixed 500, never a bare NaN
        # token, and nothing is cached.
        with patch.object(rcb, "_build_payload",
                          lambda mode: {"ok": True, "n": float("nan")}):
            with self.assertLogs(level=logging.WARNING):
                h = self.get()
        self.assertEqual(h.status, 500)
        self.assertEqual(len(rcb._CACHE), 0)


if __name__ == "__main__":
    unittest.main()
