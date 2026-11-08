"""True-audit s144 (S144-T-632) for dashboard/routes_bench_role_bracket.py.

GET /api/role-bracket-bench is a :8888 GET route, so a LAN peer reaches it
with any query. Each test pins one measured defect of the pre-audit module:

  1. a non-finite stat in the grid was served under 200 as a bare
     Infinity / NaN token the browser's JSON.parse rejects;
  2. one junk cell field (n not a count, a non-dict grid / role entry / cell /
     stat) raised into a 500, or passed a non-dict stat through verbatim;
  3. a cache hit was answered while the cache lock was held, so one stalled
     client blocked every other request on the route;
  4. the 5 min TTL ran on the wall clock, so a clock stepped back kept an
     entry fresh for the whole step;
  5. role / bracket were stripped with str.strip() and lowered with Unicode
     rules, so U+3000 / NBSP padding and a KELVIN SIGN spelling were accepted;
  6. the last-resort arm logged the raw exception text with no type name;
  7. the module docstring documented a retired "late" bracket and 25 / 35 min
     boundaries the reader does not use.

The grid reader is stubbed: no real rewind corpus is touched.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import unittest
from unittest.mock import patch

from dashboard import routes_bench_role_bracket as rbb

_GRID = "dashboard.routes_bench_role_bracket.bench.role_bracket_grid"
_STAT_KEYS = ("lvl", "cs", "tf", "kda")
_EMPTY = {"avg": None, "p50": None, "n": 0}


def _stat(avg, p50=None, n=3):
    return {"avg": avg, "p50": avg if p50 is None else p50, "n": n}


def _cell(n=3, **over):
    cell = {"n": n}
    for k in _STAT_KEYS:
        cell[k] = _stat(1.5)
    cell.update(over)
    return cell


class _H:
    def __init__(self, qs: str = "role=mid&bracket=mid"):
        self.path = "/api/role-bracket-bench" + (f"?{qs}" if qs else "")
        self.status = None
        self.body = None
        self.ct = None

    def _send(self, status, body, content_type):
        self.status = status
        self.body = body
        self.ct = content_type


def _strict(body: bytes) -> dict:
    def _bad(tok):
        raise ValueError(f"non-strict JSON token {tok}")
    return json.loads(body, parse_constant=_bad)


class _Case(unittest.TestCase):
    def setUp(self):
        rbb._reset_caches()
        self.addCleanup(rbb._reset_caches)

    def serve(self, grid, qs="role=mid&bracket=mid"):
        with patch(_GRID, side_effect=lambda: grid):
            h = _H(qs)
            rbb._serve_role_bracket_bench(h)
        return h


class NonFiniteTests(_Case):
    def test_infinite_and_nan_stats_are_null_and_body_is_strict(self):
        grid = {"mid": {"mid": _cell(lvl=_stat(float("inf"), float("nan")),
                                     cs=_stat(float("-inf")))}}
        h = self.serve(grid)
        self.assertEqual(h.status, 200)
        p = _strict(h.body)
        self.assertIsNone(p["stats"]["lvl"]["avg"])
        self.assertIsNone(p["stats"]["lvl"]["p50"])
        self.assertIsNone(p["stats"]["cs"]["avg"])
        self.assertEqual(p["stats"]["tf"]["avg"], 1.5)

    def test_bool_and_str_stat_values_are_null(self):
        grid = {"mid": {"mid": _cell(lvl={"avg": True, "p50": "12", "n": 3})}}
        p = _strict(self.serve(grid).body)
        self.assertIsNone(p["stats"]["lvl"]["avg"])
        self.assertIsNone(p["stats"]["lvl"]["p50"])
        self.assertEqual(p["stats"]["lvl"]["n"], 3)

    def test_huge_int_stat_is_null(self):
        grid = {"mid": {"mid": _cell(cs=_stat(10 ** 400))}}
        p = _strict(self.serve(grid).body)
        self.assertIsNone(p["stats"]["cs"]["avg"])

    def test_valid_numbers_pass_unchanged(self):
        grid = {"mid": {"mid": _cell(n=20, lvl=_stat(15, 14.5, 20),
                                     kda=_stat(3.41, 3.0, 20))}}
        p = _strict(self.serve(grid).body)
        self.assertEqual(p["n"], 20)
        self.assertEqual(p["stats"]["lvl"], {"avg": 15, "p50": 14.5, "n": 20})
        self.assertIsInstance(p["stats"]["lvl"]["avg"], int)
        self.assertEqual(p["stats"]["kda"], {"avg": 3.41, "p50": 3.0, "n": 20})


class JunkShapeTests(_Case):
    def assert_empty_column(self, h, n=0):
        self.assertEqual(h.status, 200)
        p = _strict(h.body)
        self.assertTrue(p["ok"])
        self.assertEqual(p["n"], n)
        self.assertEqual(set(p["stats"]), set(_STAT_KEYS))
        return p

    def test_infinite_n_reads_zero(self):
        self.assert_empty_column(self.serve({"mid": {"mid": _cell(n=float("inf"))}}))

    def test_str_n_reads_zero(self):
        self.assert_empty_column(self.serve({"mid": {"mid": _cell(n="x")}}))

    def test_bool_n_reads_zero(self):
        self.assert_empty_column(self.serve({"mid": {"mid": _cell(n=True)}}))

    def test_negative_n_reads_zero(self):
        self.assert_empty_column(self.serve({"mid": {"mid": _cell(n=-4)}}))

    def test_integral_float_n_is_int(self):
        p = _strict(self.serve({"mid": {"mid": _cell(n=7.0)}}).body)
        self.assertEqual(p["n"], 7)
        self.assertIsInstance(p["n"], int)

    def test_grid_not_a_dict_is_empty_column(self):
        p = self.assert_empty_column(self.serve(["x"]))
        for k in _STAT_KEYS:
            self.assertEqual(p["stats"][k], _EMPTY)

    def test_grid_none_is_empty_column(self):
        self.assert_empty_column(self.serve(None))

    def test_role_entry_not_a_dict_is_empty_column(self):
        self.assert_empty_column(self.serve({"mid": ["x"]}))

    def test_cell_not_a_dict_is_empty_column(self):
        self.assert_empty_column(self.serve({"mid": {"mid": [1, 2]}}))

    def test_stat_not_a_dict_is_empty_stat(self):
        p = _strict(self.serve({"mid": {"mid": _cell(lvl=[1, 2], cs="9")}}).body)
        self.assertEqual(p["stats"]["lvl"], _EMPTY)
        self.assertEqual(p["stats"]["cs"], _EMPTY)
        self.assertEqual(p["stats"]["tf"]["avg"], 1.5)

    def test_stat_missing_fields_are_filled(self):
        p = _strict(self.serve({"mid": {"mid": _cell(lvl={"avg": 2})}}).body)
        self.assertEqual(p["stats"]["lvl"], {"avg": 2, "p50": None, "n": 0})

    def test_stat_extra_fields_are_dropped(self):
        p = _strict(self.serve(
            {"mid": {"mid": _cell(lvl={"avg": 2, "p50": 2, "n": 1, "x": "y"})}}).body)
        self.assertEqual(p["stats"]["lvl"], {"avg": 2, "p50": 2, "n": 1})

    def test_payload_never_aliases_the_reader_grid(self):
        grid = {"mid": {"mid": _cell()}}
        with patch(_GRID, side_effect=lambda: grid):
            p = rbb._build_payload("mid", "mid")
        self.assertIsNot(p["stats"]["lvl"], grid["mid"]["mid"]["lvl"])
        p["stats"]["lvl"]["avg"] = 99
        self.assertEqual(grid["mid"]["mid"]["lvl"]["avg"], 1.5)


class CacheLockTests(_Case):
    def test_cache_hit_is_not_sent_under_the_lock(self):
        with patch(_GRID, side_effect=lambda: {}):
            rbb._serve_role_bracket_bench(_H())
            seen = []

            class _Probe(_H):
                def _send(self, status, body, content_type):
                    seen.append(rbb._CACHE_LOCK.locked())
                    super()._send(status, body, content_type)

            h = _Probe()
            rbb._serve_role_bracket_bench(h)
        self.assertTrue(_strict(h.body)["cached"])
        self.assertEqual(seen, [False])

    def test_stalled_client_does_not_block_another_request(self):
        started = threading.Event()
        release = threading.Event()

        class _Stall(_H):
            def _send(self, status, body, content_type):
                started.set()
                release.wait(5)
                super()._send(status, body, content_type)

        with patch(_GRID, side_effect=lambda: {}):
            rbb._serve_role_bracket_bench(_H())
            t = threading.Thread(target=rbb._serve_role_bracket_bench,
                                 args=(_Stall(),), daemon=True)
            t.start()
            self.assertTrue(started.wait(5))
            done = threading.Event()

            def _other():
                rbb._serve_role_bracket_bench(_H("role=bot&bracket=mid"))
                done.set()

            t2 = threading.Thread(target=_other, daemon=True)
            t2.start()
            finished = done.wait(2)
            release.set()
            t.join(5)
            t2.join(5)
        self.assertTrue(finished, "a stalled client held the cache lock")


class MonotonicTtlTests(_Case):
    def test_wall_clock_step_back_does_not_keep_entry_fresh(self):
        with patch(_GRID, side_effect=lambda: {}) as g:
            with patch("time.time", return_value=1e9):
                rbb._serve_role_bracket_bench(_H())
            with patch("time.time", return_value=1e9 - 10_000):
                rbb._serve_role_bracket_bench(_H())
            self.assertEqual(g.call_count, 1)  # still a hit: within TTL
        # TTL is measured on the monotonic clock: an entry older than the TTL
        # on that clock is a miss even if the wall clock went backwards.
        rbb._reset_caches()
        with patch(_GRID, side_effect=lambda: {}) as g:
            with patch("dashboard.routes_bench_role_bracket.time.monotonic",
                       return_value=1000.0):
                rbb._serve_role_bracket_bench(_H())
            with patch("dashboard.routes_bench_role_bracket.time.monotonic",
                       return_value=1000.0 + rbb._CACHE_TTL_S + 1):
                h = _H()
                rbb._serve_role_bracket_bench(h)
            self.assertEqual(g.call_count, 2)
        self.assertFalse(_strict(h.body)["cached"])

    def test_entry_stamped_in_the_future_is_not_served(self):
        with patch(_GRID, side_effect=lambda: {}) as g:
            with patch("dashboard.routes_bench_role_bracket.time.monotonic",
                       return_value=5000.0):
                rbb._serve_role_bracket_bench(_H())
            with patch("dashboard.routes_bench_role_bracket.time.monotonic",
                       return_value=4000.0):
                rbb._serve_role_bracket_bench(_H())
            self.assertEqual(g.call_count, 2)

    def test_elapsed_ms_never_negative_on_wall_clock_step(self):
        ticks = iter([2e9, 1e9, 1e9, 1e9, 1e9])
        with patch(_GRID, side_effect=lambda: {}), \
                patch("time.time", side_effect=lambda: next(ticks, 1e9)):
            h = _H()
            rbb._serve_role_bracket_bench(h)
        self.assertGreaterEqual(_strict(h.body)["elapsed_ms"], 0)

    def test_strict_json_failure_is_not_cached(self):
        calls = []

        def _grid():
            calls.append(1)
            return {}

        with patch(_GRID, side_effect=_grid), \
                patch.object(rbb, "_build_payload",
                             side_effect=lambda r, b: {"ok": True, "x": float("nan")}):
            h = _H()
            rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.status, 500)
        self.assertEqual(rbb._CACHE, {})


class QueryShapeTests(_Case):
    def status(self, qs):
        return self.serve({}, qs).status

    def test_unicode_blank_padding_is_refused(self):
        for qs in ("role=%E3%80%80&bracket=mid",       # U+3000 alone
                   "role=mid%E3%80%80&bracket=mid",
                   "role=mid%C2%A0&bracket=mid",       # NBSP
                   "role=mid&bracket=mid%E3%80%80",
                   "role=mid&bracket=%C2%A0mid",
                   "role=mid%C2%85&bracket=mid"):      # NEL
            self.assertEqual(self.status(qs), 400, qs)

    def test_ascii_control_separators_are_refused(self):
        for qs in ("role=mid%1F&bracket=mid", "role=mid&bracket=mid%1C"):
            self.assertEqual(self.status(qs), 400, qs)

    def test_kelvin_sign_spelling_is_refused(self):
        self.assertEqual(self.status("role=mar%E2%84%AAsman&bracket=mid"), 400)

    def test_dotted_capital_i_is_refused(self):
        self.assertEqual(self.status("role=m%C4%B0d&bracket=mid"), 400)

    def test_ascii_blank_padding_and_case_still_accepted(self):
        h = self.serve({}, "role=%20ADC%09&bracket=%20Early%20")
        self.assertEqual(h.status, 200)
        p = _strict(h.body)
        self.assertEqual((p["role"], p["bracket"]), ("bot", "early"))

    def test_every_alias_and_bracket_accepted(self):
        from core import role_bracket_bench as bench
        for alias, canon in bench.ROLE_ALIASES.items():
            for br in rbb.VALID_BRACKETS:
                for spelled in (alias, alias.upper()):
                    rbb._reset_caches()
                    h = self.serve({}, f"role={spelled}&bracket={br.upper()}")
                    self.assertEqual(h.status, 200, (spelled, br))
                    p = _strict(h.body)
                    self.assertEqual((p["role"], p["bracket"]), (canon, br))

    def test_late_bracket_is_refused_and_named_in_no_error(self):
        h = self.serve({}, "role=mid&bracket=late")
        self.assertEqual(h.status, 400)
        self.assertEqual(_strict(h.body)["error"],
                         "bracket must be one of early, mid")

    def test_refusal_never_echoes_the_value(self):
        h = self.serve({}, "role=%3Cscript%3E&bracket=mid")
        self.assertEqual(h.status, 400)
        self.assertNotIn(b"script", h.body)

    def test_refusal_does_not_read_the_grid(self):
        with patch(_GRID, side_effect=lambda: {}) as g:
            rbb._serve_role_bracket_bench(_H("role=wizard&bracket=mid"))
            rbb._serve_role_bracket_bench(_H("role=mid&bracket=late"))
        self.assertEqual(g.call_count, 0)


class LastResortTests(_Case):
    def test_last_resort_logs_type_name(self):
        with self.assertLogs("rc.web_dashboard", level=logging.WARNING) as cm, \
                patch(_GRID, side_effect=RuntimeError("db exploded")):
            h = _H()
            rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.status, 500)
        self.assertEqual(_strict(h.body),
                         {"ok": False, "error": "internal error - see logs"})
        self.assertTrue(any("RuntimeError" in line for line in cm.output),
                        cm.output)

    def test_exception_whose_str_raises_still_gets_fixed_500(self):
        class _Bad(Exception):
            def __str__(self):
                raise ValueError("boom")

        with patch(_GRID, side_effect=_Bad()):
            h = _H()
            rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.status, 500)
        self.assertEqual(_strict(h.body),
                         {"ok": False, "error": "internal error - see logs"})

    def test_client_gone_while_sending_500_does_not_raise(self):
        class _Gone(_H):
            def _send(self, status, body, content_type):
                raise ConnectionResetError("gone")

        with patch(_GRID, side_effect=RuntimeError("x")), \
                patch.object(rbb, "log") as route_log:
            rbb._serve_role_bracket_bench(_Gone())  # must not raise
        # A gone client is not an envelope failure: no second send, no
        # misleading "error envelope failed" line.
        self.assertEqual(route_log.warning.call_count, 0)


class DocstringTests(unittest.TestCase):
    def test_docstring_matches_the_reader_brackets(self):
        doc = rbb.__doc__
        self.assertNotIn("late", doc.split("Response:")[0])
        self.assertNotIn("25-35m", doc)
        self.assertIn("14:00", doc)
        self.assertEqual(rbb.VALID_BRACKETS, ("early", "mid"))


class TimingSanityTests(_Case):
    def test_elapsed_ms_is_int(self):
        t0 = time.perf_counter()
        p = _strict(self.serve({}).body)
        self.assertIsInstance(p["elapsed_ms"], int)
        self.assertLessEqual(p["elapsed_ms"],
                             int((time.perf_counter() - t0) * 1000) + 1)


if __name__ == "__main__":
    unittest.main()
