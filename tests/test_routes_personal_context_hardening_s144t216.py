"""s144 true-audit cycle 216 (S144-T-609): GET /api/personal-context hardening.

dashboard/routes_personal_context.py serves the postmortem death-pattern top-3
and the role-grade distribution from data/coaching/death_patterns.json, behind
a 60 s in-process cache keyed on the file. 13 of the 17 tests below were RED
on the pre-fix module; the other four (valid role_grades unchanged, a fresh
hit skips the build, the future-stamp guard, concurrent requests) pin
behaviour the fix must keep. The defects:

- a payload built from the OLD file was cached under the NEW file's mtime when
  the producer replaced the file mid-build, so the stale payload was served
  until the TTL ran out (the cache stat ran AFTER the build);
- the payload was assembled from three separate reads of the file, so a
  replace between them served the old top-3 with the new totals;
- a same-mtime rewrite with a different size was a cache hit (float mtime was
  the whole key);
- the TTL ran on the wall clock, so a clock stepped back kept an entry fresh
  for the whole step;
- role_grades was served verbatim from the file: any key, any type, any size;
- a non-finite float in a built payload went out as a bare NaN token under 200;
- the last-resort log line carried the raw exception text (CR / LF included)
  with no type name.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_personal_context as routes

_RG = {
    "total_matches_scored": 6,
    "overall": {
        "count": 6,
        "median_score": 41,
        "tier_distribution": {"S+": 0, "S": 1, "A": 1, "B": 2, "C": 1, "D": 1},
    },
    "by_role": {
        "ADC": {"count": 4, "median_score": 44,
                "tier_distribution": {"S+": 0, "S": 1, "A": 1, "B": 1, "C": 1, "D": 0}},
        "SUP": {"count": 2, "median_score": 30,
                "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 1, "C": 0, "D": 1}},
        "JG": {"count": 0, "median_score": 0,
               "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
        "MID": {"count": 0, "median_score": 0,
                "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
        "TOP": {"count": 0, "median_score": 0,
                "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
    },
}


def _report(total_deaths: int, key: str = "solo_pickoff", pad: str = "") -> dict:
    return {
        "schema_version": 2,
        "generated_at": "2026-11-08T00:00:00Z",
        "total_deaths": total_deaths,
        "total_matches": 10,
        "patterns": {
            key: {"count": 5, "rate": 0.5, "confidence": 0.9,
                  "label": "Label " + key, "description": "d" + pad},
        },
        "top3": [key],
        "role_grades": _RG,
    }


class _Handler:
    def __init__(self):
        self.path = "/api/personal-context"
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status, body, ctype):
        self.responses.append((status, body, ctype))

    def body(self) -> dict:
        return json.loads(self.responses[-1][1])


class _Case(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(prefix="rc-pc-s144t216-")
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "death_patterns.json"
        p = patch.object(routes, "_DEATH_PATTERNS_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        routes._CACHE["payload"] = None
        routes._CACHE["expires_at"] = 0.0
        self.addCleanup(routes._CACHE.__setitem__, "payload", None)

    def write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(json.dumps(data).encode("utf-8"))
        os.replace(tmp, self.path)

    def serve(self) -> _Handler:
        h = _Handler()
        routes._serve_personal_context(h)
        return h


class StaleCacheTests(_Case):
    def test_replace_during_build_is_not_pinned_under_new_mtime(self):
        self.write(_report(111))
        real_build = routes._build_payload
        state = {"n": 0}

        def build_then_replace():
            payload = real_build()
            if state["n"] == 0:
                # Producer replaces the file after the route read it.
                self.write(_report(222, pad="xxxx"))
                st = self.path.stat()
                os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
            state["n"] += 1
            return payload

        with patch.object(routes, "_build_payload", build_then_replace):
            self.serve()
            h2 = self.serve()
        self.assertEqual(h2.body()["total_deaths"], 222)

    def test_one_payload_never_mixes_two_file_versions(self):
        self.write(_report(111, key="solo_pickoff"))
        real_top = routes.top_patterns
        state = {"n": 0}

        def top_then_replace(path):
            out = real_top(path)
            if state["n"] == 0:
                self.write(_report(222, key="caught_4plus", pad="yy"))
            state["n"] += 1
            return out

        with patch.object(routes, "top_patterns", top_then_replace):
            body = self.serve().body()
        pair = (body["top3"][0]["key"], body["total_deaths"])
        self.assertIn(pair, {("solo_pickoff", 111), ("caught_4plus", 222)})

    def test_same_mtime_rewrite_with_new_size_is_a_miss(self):
        self.write(_report(111))
        mtime_ns = self.path.stat().st_mtime_ns
        self.serve()
        self.path.write_bytes(json.dumps(_report(222, pad="z" * 50)).encode("utf-8"))
        os.utime(self.path, ns=(mtime_ns, mtime_ns))
        self.assertEqual(self.serve().body()["total_deaths"], 222)

    def test_ttl_runs_on_monotonic_clock_not_wall_clock(self):
        self.write(_report(111))
        calls = {"n": 0}
        real_build = routes._build_payload

        def counting():
            calls["n"] += 1
            return real_build()

        clock = {"wall": 1_000_000.0, "mono": 500.0}
        with patch.object(routes, "_build_payload", counting), \
                patch.object(routes.time, "time", lambda: clock["wall"]), \
                patch.object(routes.time, "monotonic", lambda: clock["mono"]):
            self.serve()
            # 61 s really elapsed, but the wall clock was stepped back by
            # exactly that much, so it reads the same as at the store.
            clock["mono"] += 61.0
            self.serve()
            # A wall clock stepped back an hour cannot keep it fresh either.
            clock["wall"] -= 3600.0
            clock["mono"] += 61.0
            self.serve()
        self.assertEqual(calls["n"], 3)

    def test_a_file_that_keeps_moving_is_served_but_not_cached(self):
        self.write(_report(111))
        real_build = routes._build_payload
        state = {"n": 0}

        def build_then_bump():
            payload = real_build()
            state["n"] += 1
            st = self.path.stat()
            os.utime(self.path, ns=(st.st_atime_ns,
                                    st.st_mtime_ns + state["n"] * 1_000_000_000))
            return payload

        with patch.object(routes, "_build_payload", build_then_bump):
            h = self.serve()
        self.assertEqual(h.responses[-1][0], 200)
        self.assertEqual(h.body()["total_deaths"], 111)
        self.assertEqual(state["n"], 2)
        self.assertIsNone(routes._CACHE["payload"])

    def test_a_fresh_hit_skips_the_build(self):
        self.write(_report(111))
        calls = {"n": 0}
        real_build = routes._build_payload

        def counting():
            calls["n"] += 1
            return real_build()

        with patch.object(routes, "_build_payload", counting):
            bodies = [self.serve().responses[-1][1] for _ in range(5)]
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(set(bodies)), 1)

    def test_entry_stamped_in_the_future_is_never_served(self):
        self.write(_report(111))
        self.serve()
        routes._CACHE["expires_at"] = routes.time.monotonic() + 10 * routes._CACHE_TTL_S
        calls = {"n": 0}
        real_build = routes._build_payload

        def counting():
            calls["n"] += 1
            return real_build()

        with patch.object(routes, "_build_payload", counting):
            self.serve()
        self.assertEqual(calls["n"], 1)

    def test_concurrent_requests_all_get_a_whole_body(self):
        self.write(_report(111))
        bodies: list[dict] = []
        errors: list[BaseException] = []

        def worker():
            try:
                for _ in range(20):
                    bodies.append(self.serve().body())
            except BaseException as exc:  # noqa: BLE001 - collected for the assert
                errors.append(exc)

        threads = [threading.Thread(target=worker, name=f"pc-{i}") for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(len(bodies), 120)
        self.assertTrue(all(b["total_deaths"] == 111 for b in bodies))


class RoleGradesShapeTests(_Case):
    def _rg(self, rg) -> dict:
        data = _report(111)
        data["role_grades"] = rg
        self.write(data)
        return self.serve().body()

    def test_valid_role_grades_unchanged(self):
        self.assertEqual(self._rg(_RG)["role_grades"], _RG)

    def test_unknown_keys_are_dropped(self):
        rg = json.loads(json.dumps(_RG))
        rg["puuid"] = "synthetic-puuid-0000"
        rg["overall"]["extra"] = "x"
        rg["by_role"]["NOT_A_ROLE"] = rg["by_role"]["ADC"]
        rg["by_role"]["ADC"]["tier_distribution"]["<b>"] = 9
        out = self._rg(rg)["role_grades"]
        self.assertEqual(out, _RG)

    def test_wrong_typed_numbers_read_zero(self):
        rg = json.loads(json.dumps(_RG))
        rg["total_matches_scored"] = "x" * 5000
        rg["overall"]["count"] = True
        rg["overall"]["median_score"] = "41"
        rg["overall"]["tier_distribution"]["S"] = -3
        rg["by_role"]["ADC"]["count"] = 2.5
        rg["by_role"]["ADC"]["median_score"] = 1e9
        rg["by_role"]["SUP"]["median_score"] = None
        out = self._rg(rg)["role_grades"]
        self.assertEqual(out["total_matches_scored"], 0)
        self.assertEqual(out["overall"]["count"], 0)
        self.assertEqual(out["overall"]["median_score"], 0)
        self.assertEqual(out["overall"]["tier_distribution"]["S"], 0)
        self.assertEqual(out["by_role"]["ADC"]["count"], 0)
        self.assertEqual(out["by_role"]["ADC"]["median_score"], 0)
        self.assertEqual(out["by_role"]["SUP"]["median_score"], 0)

    def test_float_median_is_rounded_to_int(self):
        rg = json.loads(json.dumps(_RG))
        rg["overall"]["median_score"] = 40.6
        self.assertEqual(self._rg(rg)["role_grades"]["overall"]["median_score"], 41)

    def test_non_dict_buckets_are_dropped_and_tiers_filled(self):
        rg = {
            "total_matches_scored": 3,
            "overall": [1, 2],
            "by_role": {"ADC": [1], "TOP": {"count": 3, "median_score": 50,
                                            "tier_distribution": {"B": 3}}},
        }
        out = self._rg(rg)["role_grades"]
        self.assertNotIn("overall", out)
        self.assertEqual(list(out["by_role"]), ["TOP"])
        self.assertEqual(out["by_role"]["TOP"]["tier_distribution"],
                         {"S+": 0, "S": 0, "A": 0, "B": 3, "C": 0, "D": 0})

    def test_non_dict_by_role_is_dropped(self):
        rg = json.loads(json.dumps(_RG))
        rg["by_role"] = "ADC"
        out = self._rg(rg)["role_grades"]
        self.assertNotIn("by_role", out)
        self.assertEqual(out["overall"], _RG["overall"])


class ErrorPathTests(_Case):
    def test_non_finite_float_is_a_500_not_a_nan_token(self):
        with patch.object(routes, "_build_payload",
                          lambda: {"ok": True, "top3": [], "x": float("nan")}):
            h = self.serve()
        status, body, _ = h.responses[-1]
        self.assertEqual(status, 500)
        self.assertNotIn(b"NaN", body)
        self.assertEqual(json.loads(body),
                         {"ok": False, "error": "internal error - see logs"})
        self.assertIsNone(routes._CACHE["payload"])

    def test_log_line_names_type_and_escapes_control_chars(self):
        def boom():
            raise RuntimeError("first\nFAKE INJECTED LINE")

        with patch.object(routes, "_build_payload", boom), \
                self.assertLogs("rc.web_dashboard", level=logging.WARNING) as cm:
            h = self.serve()
        self.assertEqual(h.responses[-1][0], 500)
        joined = "\n".join(r.getMessage() for r in cm.records)
        self.assertIn("RuntimeError", joined)
        self.assertNotIn("\nFAKE INJECTED LINE", joined)

    def test_send_failure_on_the_500_path_is_swallowed_only_for_oserror(self):
        class _Gone(_Handler):
            def _send(self, status, body, ctype):
                raise BrokenPipeError("client went away")

        def boom():
            raise RuntimeError("x")

        with patch.object(routes, "_build_payload", boom), \
                self.assertLogs("rc.web_dashboard", level=logging.DEBUG):
            routes._serve_personal_context(_Gone())

        class _Bug(_Handler):
            def _send(self, status, body, ctype):
                raise TypeError("handler bug")

        with patch.object(routes, "_build_payload", boom), \
                self.assertLogs("rc.web_dashboard", level=logging.WARNING), \
                self.assertRaises(TypeError):
            routes._serve_personal_context(_Bug())


if __name__ == "__main__":
    unittest.main()
