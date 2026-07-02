"""OQ12 slice A: core/carry_benchmarks.py reader characterization.

Pins the mtime-cached reader over data/coach_reference/carry_benchmarks.json:

  - bucket_for boundaries (1199 / 1200 / 1799 / 1800);
  - resolve() fallback chain role|bucket -> role|all -> mode|bucket ->
    mode|all -> (None, {}), where a key only qualifies when its kp_pct n
    meets the JSON's min_n;
  - band() fences: value == p25 -> "avg", < p25 -> "low", > p75 -> "high",
    None -> None;
  - the real committed carry_benchmarks.json parses and carries the
    ARAM|all + CLASSIC|all groups (CI has no DB; the JSON is tracked).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import core.carry_benchmarks as cb

ROOT = Path(__file__).resolve().parent.parent


def _doc(groups: dict, min_n: int = 50) -> dict:
    return {
        "generated_at": "2026-07-01T00:00:00+00:00",
        "min_n": min_n,
        "buckets": {"short": [0, 1199], "mid": [1200, 1799],
                    "long": [1800, None]},
        "groups": groups,
    }


def _grp(kp_n: int) -> dict:
    return {
        "n": kp_n,
        "metrics": {
            "kp_pct":         {"p25": 40.0, "p50": 50.0, "p75": 60.0, "n": kp_n},
            "gold_share_pct": {"p25": 18.0, "p50": 20.0, "p75": 24.0, "n": kp_n},
            "dmg_share_pct":  {"p25": 20.0, "p50": 26.0, "p75": 32.0, "n": kp_n},
        },
    }


class BucketForTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(cb.bucket_for(0), "short")
        self.assertEqual(cb.bucket_for(1199), "short")
        self.assertEqual(cb.bucket_for(1200), "mid")
        self.assertEqual(cb.bucket_for(1799), "mid")
        self.assertEqual(cb.bucket_for(1800), "long")
        self.assertEqual(cb.bucket_for(5000), "long")


class _TmpJsonBase(unittest.TestCase):
    """Point the reader at a throwaway JSON; fresh cache per test."""

    def _use(self, doc: dict) -> None:
        self._tmp = TemporaryDirectory()
        p = Path(self._tmp.name) / "carry_benchmarks.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        self._patches = [
            mock.patch.object(cb, "CARRY_BENCHMARKS_PATH", p),
            mock.patch.object(cb, "_cache", cb._Cache()),
        ]
        for pt in self._patches:
            pt.start()

    def tearDown(self):
        for pt in getattr(self, "_patches", []):
            pt.stop()
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()


class ResolveFallbackTests(_TmpJsonBase):
    def test_role_bucket_wins_when_qualified(self):
        self._use(_doc({"BOTTOM|mid": _grp(60), "BOTTOM|all": _grp(200),
                        "CLASSIC|mid": _grp(500), "CLASSIC|all": _grp(900)}))
        key, metrics = cb.resolve("BOTTOM", "CLASSIC", 1500)
        self.assertEqual(key, "BOTTOM|mid")
        self.assertEqual(metrics["kp_pct"]["n"], 60)

    def test_min_n_skip_falls_to_role_all(self):
        self._use(_doc({"BOTTOM|mid": _grp(10), "BOTTOM|all": _grp(200),
                        "CLASSIC|mid": _grp(500)}))
        key, metrics = cb.resolve("BOTTOM", "CLASSIC", 1500)
        self.assertEqual(key, "BOTTOM|all")
        self.assertEqual(metrics["kp_pct"]["n"], 200)

    def test_falls_to_mode_bucket_then_mode_all(self):
        self._use(_doc({"CLASSIC|mid": _grp(500), "CLASSIC|all": _grp(900)}))
        key, _ = cb.resolve("BOTTOM", "CLASSIC", 1500)
        self.assertEqual(key, "CLASSIC|mid")
        self._patches[0].stop()
        self._patches[1].stop()
        self._use(_doc({"CLASSIC|mid": _grp(10), "CLASSIC|all": _grp(900)}))
        key, _ = cb.resolve("BOTTOM", "CLASSIC", 1500)
        self.assertEqual(key, "CLASSIC|all")

    def test_role_none_goes_straight_to_mode(self):
        self._use(_doc({"ARAM|short": _grp(300), "ARAM|all": _grp(2000)}))
        key, _ = cb.resolve(None, "ARAM", 900)
        self.assertEqual(key, "ARAM|short")

    def test_nothing_qualifies_returns_none_empty(self):
        self._use(_doc({"CLASSIC|all": _grp(10)}))
        key, metrics = cb.resolve("TOP", "CLASSIC", 1500)
        self.assertIsNone(key)
        self.assertEqual(metrics, {})

    def test_missing_file_returns_none_empty(self):
        self._use(_doc({}))
        # Repoint at a path that does not exist.
        self._patches[0].stop()
        self._patches[0] = mock.patch.object(
            cb, "CARRY_BENCHMARKS_PATH",
            Path(self._tmp.name) / "does-not-exist.json")
        self._patches[0].start()
        key, metrics = cb.resolve("BOTTOM", "CLASSIC", 1500)
        self.assertIsNone(key)
        self.assertEqual(metrics, {})

    def test_min_n_honors_json_value(self):
        """min_n comes from the JSON, not a hardcoded 50."""
        self._use(_doc({"BOTTOM|mid": _grp(6)}, min_n=5))
        key, _ = cb.resolve("BOTTOM", "CLASSIC", 1500)
        self.assertEqual(key, "BOTTOM|mid")


class BandTests(unittest.TestCase):
    BENCH = {"p25": 40.0, "p50": 50.0, "p75": 60.0, "n": 100}

    def test_equal_p25_is_avg(self):
        self.assertEqual(cb.band(40.0, self.BENCH), "avg")

    def test_below_p25_is_low(self):
        self.assertEqual(cb.band(39.9, self.BENCH), "low")

    def test_equal_p75_is_avg(self):
        self.assertEqual(cb.band(60.0, self.BENCH), "avg")

    def test_above_p75_is_high(self):
        self.assertEqual(cb.band(60.1, self.BENCH), "high")

    def test_none_value_is_none(self):
        self.assertIsNone(cb.band(None, self.BENCH))

    def test_empty_bench_is_none(self):
        self.assertIsNone(cb.band(50.0, {}))
        self.assertIsNone(cb.band(50.0, None))


class CommittedJsonTests(unittest.TestCase):
    """CI has no rewind_history.db - the generated JSON must be tracked
    and must carry the two groups every consumer path depends on."""

    def test_committed_json_parses_with_required_groups(self):
        p = ROOT / "data" / "coach_reference" / "carry_benchmarks.json"
        self.assertTrue(p.exists(), f"{p} missing - run the builder + commit")
        doc = json.loads(p.read_text(encoding="utf-8"))
        groups = doc.get("groups", {})
        self.assertIn("ARAM|all", groups)
        self.assertIn("CLASSIC|all", groups)
        for role in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
            self.assertIn(f"{role}|all", groups)


if __name__ == "__main__":
    unittest.main()
