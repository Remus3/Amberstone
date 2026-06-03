"""Regression tests for tools/cost_health_watchdog.py.

Covers the breach boundary (exactly 1.5x), the idle-floor false-positive
guard, flap detection (pid churn / alive / reload), purpose->tier
classification, the nearest-rank percentile helper + per-lane
p95-cost-doubling signal, and the hard invariant that cron mode never edits
config or code (including on a p95-only breach).
"""
import importlib.util
import json
import time
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "chw",
    str(Path(__file__).parent.parent / "tools" / "cost_health_watchdog.py"),
)
chw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chw)


def _write(p: Path, total_usd, by_purpose=None):
    p.write_text(json.dumps({
        "total_usd": total_usd,
        "by_purpose": by_purpose or {},
    }), encoding="utf-8")


def _lane(usd, calls):
    return {"usd": usd, "calls": calls}


class SpendBaselineTests(unittest.TestCase):
    def _dir(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        for i, v in enumerate(("01", "02", "03")):
            _write(d / f"2026-05-{v}.json", 1.0)
        return d

    def test_no_breach_just_below_1_5x(self):
        d = self._dir()
        _write(d / "2026-05-09.json", 1.49)  # baseline median == 1.0
        r = chw.spend_baseline(d, "2026-05-09")
        self.assertEqual(r["baseline_usd"], 1.0)
        self.assertFalse(r["breach"])

    def test_breach_just_above_1_5x(self):
        d = self._dir()
        _write(d / "2026-05-09.json", 1.51)
        r = chw.spend_baseline(d, "2026-05-09")
        self.assertTrue(r["breach"])

    def test_idle_floor_suppresses_false_positive(self):
        # tiny baseline, today 0.40 is >1.5x but below the absolute floor.
        import tempfile
        d = Path(tempfile.mkdtemp())
        _write(d / "2026-05-01.json", 0.10)
        _write(d / "2026-05-02.json", 0.10)
        _write(d / "2026-05-09.json", 0.40)
        r = chw.spend_baseline(d, "2026-05-09")
        self.assertFalse(r["breach"])

    def test_no_prior_no_breach(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        _write(d / "2026-05-09.json", 99.0)
        r = chw.spend_baseline(d, "2026-05-09")
        self.assertEqual(r["baseline_usd"], 0.0)
        self.assertFalse(r["breach"])


class FlapTests(unittest.TestCase):
    def test_two_pid_changes_in_window_is_not_flap(self):
        # Two clean restarts in a dev/fix session (both healthy) is benign,
        # NOT a flap. The supervisor relaunches a crashed daemon within ~5s,
        # so a real crash loop produces far more than two changes/hour.
        now = time.time()
        prev = {"last_pid": 100, "pid_change_ts": [now - 10]}
        r = chw.detect_flap(prev, {"pid": 200, "alive": True,
                                   "last_reload_ok": True}, now)
        self.assertFalse(r["flap"])
        self.assertEqual(r["pid_changes_in_window"], 2)

    def test_three_pid_changes_in_window_is_flap(self):
        now = time.time()
        prev = {"last_pid": 100, "pid_change_ts": [now - 20, now - 10]}
        r = chw.detect_flap(prev, {"pid": 200, "alive": True,
                                   "last_reload_ok": True}, now)
        self.assertTrue(r["flap"])
        self.assertEqual(r["pid_changes_in_window"], 3)

    def test_two_changes_plus_unhealthy_is_flap(self):
        # The health overrides are count-independent: 2 pid changes (below the
        # churn threshold) still flap if the daemon is currently sick.
        now = time.time()
        prev = {"last_pid": 100, "pid_change_ts": [now - 10]}
        r = chw.detect_flap(prev, {"pid": 200, "alive": True,
                                   "last_reload_ok": False}, now)
        self.assertTrue(r["flap"])
        self.assertEqual(r["pid_changes_in_window"], 2)

    def test_stable_pid_no_flap(self):
        now = time.time()
        prev = {"last_pid": 100, "pid_change_ts": []}
        r = chw.detect_flap(prev, {"pid": 100, "alive": True,
                                   "last_reload_ok": True}, now)
        self.assertFalse(r["flap"])

    def test_dead_daemon_is_flap(self):
        now = time.time()
        r = chw.detect_flap({"last_pid": 100, "pid_change_ts": []},
                            {"pid": 100, "alive": False,
                             "last_reload_ok": True}, now)
        self.assertTrue(r["flap"])

    def test_reload_fail_is_flap(self):
        now = time.time()
        r = chw.detect_flap({"last_pid": 100, "pid_change_ts": []},
                            {"pid": 100, "alive": True,
                             "last_reload_ok": False}, now)
        self.assertTrue(r["flap"])

    def test_old_changes_expire_from_window(self):
        now = time.time()
        prev = {"last_pid": 100,
                "pid_change_ts": [now - chw.FLAP_WINDOW_S - 5]}
        r = chw.detect_flap(prev, {"pid": 100, "alive": True,
                                   "last_reload_ok": True}, now)
        self.assertEqual(r["pid_changes_in_window"], 0)
        self.assertFalse(r["flap"])


class ClassifyTests(unittest.TestCase):
    def test_sonnet_purpose(self):
        r = chw.classify({"vision_relay": {"usd": 5.0},
                          "aram_coach": {"usd": 1.0}})
        self.assertEqual(r["hot_purpose"], "vision_relay")
        self.assertEqual(r["tier"], "SONNET")
        self.assertIn("vision_calls_per_min", r["proposal"])

    def test_haiku_purpose(self):
        r = chw.classify({"aram_coach": {"usd": 9.0}})
        self.assertEqual(r["tier"], "HAIKU")
        self.assertIn("interval", r["proposal"])

    def test_unmapped_purpose(self):
        r = chw.classify({"mystery_purpose": {"usd": 2.0}})
        self.assertEqual(r["tier"], "UNKNOWN")
        self.assertIn("record_call", r["proposal"])

    def test_empty(self):
        r = chw.classify({})
        self.assertIsNone(r["hot_purpose"])


class CronModeInvariantTests(unittest.TestCase):
    def test_cron_mode_never_edits_config_or_code(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        # spend that WOULD breach (today >> baseline) so the incident path runs
        _write(d / "2026-05-01.json", 1.0)
        _write(d / "2026-05-02.json", 1.0)
        _write(d / (chw.date.today().isoformat() + ".json"), 99.0,
               {"vision_relay": {"usd": 99.0}})
        state = d / "state.json"
        cfg_before = (chw._COACH_CFG.read_bytes()
                      if chw._COACH_CFG.exists() else None)
        src_before = Path(chw.__file__).read_bytes()
        rc = chw.main(["--spend-dir", str(d), "--state", str(state)])
        cfg_after = (chw._COACH_CFG.read_bytes()
                     if chw._COACH_CFG.exists() else None)
        src_after = Path(chw.__file__).read_bytes()
        self.assertEqual(rc, 1)                       # breach detected
        self.assertEqual(cfg_before, cfg_after)       # config untouched
        self.assertEqual(src_before, src_after)       # code untouched
        st = json.loads(state.read_text(encoding="utf-8"))
        self.assertTrue(st["breached"])
        self.assertEqual(st["incidents"][-1]["remediated"], False)


class PercentileTests(unittest.TestCase):
    """Nearest-rank percentile, hand-derived (no magic numbers)."""

    def test_p95_of_1_to_20(self):
        # N=20, rank = ceil(0.95*20) = ceil(19.0) = 19 -> sorted[18] == 19.
        self.assertEqual(chw.percentile(list(range(1, 21)), 95), 19)

    def test_p50_of_1_to_20(self):
        # rank = ceil(0.50*20) = 10 -> sorted[9] == 10.
        self.assertEqual(chw.percentile(list(range(1, 21)), 50), 10)

    def test_p95_of_1_to_10(self):
        # rank = ceil(0.95*10) = ceil(9.5) = 10 -> sorted[9] == 10 (max).
        self.assertEqual(chw.percentile(list(range(1, 11)), 95), 10)

    def test_unsorted_input_is_sorted_first(self):
        self.assertEqual(chw.percentile([9, 1, 5, 3, 7], 50), 5)

    def test_empty_is_zero(self):
        self.assertEqual(chw.percentile([], 95), 0.0)

    def test_clamps_at_bounds(self):
        self.assertEqual(chw.percentile([2, 4, 6], 100), 6)
        self.assertEqual(chw.percentile([2, 4, 6], 0), 2)


class LaneCostSignalTests(unittest.TestCase):
    """Per-lane mean-cost/call escalation (week-over-week p95 proxy)."""

    def _dir(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        # 3 prior days: aram_coach steady at 0.01 usd/call (100 calls, $1).
        for v in ("01", "02", "03"):
            _write(d / f"2026-05-{v}.json", 1.0,
                   {"aram_coach": _lane(1.0, 100)})
        return d

    def test_flags_lane_when_cost_per_call_doubles(self):
        d = self._dir()
        # today: same call count but 2.2x the per-call cost (0.022 vs 0.01).
        _write(d / "2026-05-09.json", 2.2,
               {"aram_coach": _lane(2.2, 100)})
        r = chw.lane_cost_signals(d, "2026-05-09")
        self.assertTrue(r["p95_doubled"])
        self.assertIn("aram_coach", r["flagged_lanes"])
        self.assertEqual(r["lanes"]["aram_coach"]["baseline_cost_per_call"],
                         0.01)
        self.assertAlmostEqual(
            r["lanes"]["aram_coach"]["today_cost_per_call"], 0.022)

    def test_no_flag_just_below_2x(self):
        d = self._dir()
        # 1.9x the per-call cost - below the 2.0 multiplier.
        _write(d / "2026-05-09.json", 1.9,
               {"aram_coach": _lane(1.9, 100)})
        r = chw.lane_cost_signals(d, "2026-05-09")
        self.assertFalse(r["p95_doubled"])
        self.assertEqual(r["flagged_lanes"], [])

    def test_low_call_count_suppresses_signal(self):
        d = self._dir()
        # cost/call quadrupled but only 5 calls today (< P95_MIN_CALLS=20):
        # one expensive call must not trip a week-over-week alert.
        _write(d / "2026-05-09.json", 0.2,
               {"aram_coach": _lane(0.2, 5)})
        r = chw.lane_cost_signals(d, "2026-05-09")
        self.assertFalse(r["p95_doubled"])

    def test_sub_floor_lane_ignored(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        # baseline 0.0005/call, today 0.0015/call (3x) but both below the
        # P95_FLOOR_USD=0.002 sub-cent noise floor -> ignored.
        for v in ("01", "02"):
            _write(d / f"2026-05-{v}.json", 0.05,
                   {"sr_coach": _lane(0.05, 100)})
        _write(d / "2026-05-09.json", 0.15,
               {"sr_coach": _lane(0.15, 100)})
        r = chw.lane_cost_signals(d, "2026-05-09")
        self.assertFalse(r["p95_doubled"])

    def test_no_prior_no_signal(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        _write(d / "2026-05-09.json", 9.0,
               {"aram_coach": _lane(9.0, 100)})
        r = chw.lane_cost_signals(d, "2026-05-09")
        self.assertFalse(r["p95_doubled"])
        self.assertEqual(r["lanes"]["aram_coach"]["baseline_cost_per_call"],
                         0.0)


class P95BreachCronInvariantTests(unittest.TestCase):
    def test_p95_only_breach_detects_logs_proposes_no_mutation(self):
        """A p95-only escalation (daily total NOT breached) must still
        trip rc=1, classify + propose, and never touch config/code in
        cron mode."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        today = chw.date.today().isoformat()
        # Daily totals are FLAT (no spend_baseline breach): ~$1/day every
        # day. But today's vision_relay cost/call tripled vs the prior
        # baseline (0.03 vs 0.01) -> p95 signal only.
        for v in ("01", "02", "03"):
            _write(d / f"2026-05-{v}.json", 1.0,
                   {"vision_relay": _lane(1.0, 100)})
        _write(d / (today + ".json"), 1.0,
               {"vision_relay": _lane(3.0, 100)})
        state = d / "state.json"
        cfg_before = (chw._COACH_CFG.read_bytes()
                      if chw._COACH_CFG.exists() else None)
        src_before = Path(chw.__file__).read_bytes()
        rc = chw.main(["--spend-dir", str(d), "--state", str(state)])
        cfg_after = (chw._COACH_CFG.read_bytes()
                     if chw._COACH_CFG.exists() else None)
        src_after = Path(chw.__file__).read_bytes()
        self.assertEqual(rc, 1)                       # breach via p95 only
        self.assertEqual(cfg_before, cfg_after)       # config untouched
        self.assertEqual(src_before, src_after)       # code untouched
        st = json.loads(state.read_text(encoding="utf-8"))
        self.assertTrue(st["breached"])
        self.assertFalse(st["spend"]["breach"])       # NOT a daily-total breach
        inc = st["incidents"][-1]
        self.assertTrue(inc["p95_doubled"])
        self.assertIn("vision_relay", inc["p95_flagged_lanes"])
        self.assertEqual(inc["remediated"], False)
        self.assertIn("p95_proposal", inc["classification"])
        self.assertIn("vision_relay",
                      inc["classification"]["p95_proposal"])

    def test_remediate_not_triggered_by_p95_only(self):
        """--remediate only debounces on a SONNET daily-cost breach; a
        p95-only signal must NOT mutate config even with --remediate."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        today = chw.date.today().isoformat()
        for v in ("01", "02", "03"):
            _write(d / f"2026-05-{v}.json", 1.0,
                   {"vision_relay": _lane(1.0, 100)})
        _write(d / (today + ".json"), 1.0,
               {"vision_relay": _lane(3.0, 100)})
        state = d / "state.json"
        cfg_before = (chw._COACH_CFG.read_bytes()
                      if chw._COACH_CFG.exists() else None)
        rc = chw.main(["--remediate", "--spend-dir", str(d),
                       "--state", str(state)])
        cfg_after = (chw._COACH_CFG.read_bytes()
                     if chw._COACH_CFG.exists() else None)
        self.assertEqual(rc, 1)
        self.assertEqual(cfg_before, cfg_after)       # p95-only != remediable
        st = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(st["incidents"][-1]["remediated"], False)


if __name__ == "__main__":
    unittest.main()
