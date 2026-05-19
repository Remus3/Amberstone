"""Regression tests for tools/cost_health_watchdog.py.

Covers the breach boundary (exactly 1.5x), the idle-floor false-positive
guard, flap detection (pid churn / alive / reload), purpose->tier
classification, and the hard invariant that cron mode never edits config
or code.
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
    def test_two_pid_changes_in_window_is_flap(self):
        now = time.time()
        prev = {"last_pid": 100, "pid_change_ts": [now - 10]}
        r = chw.detect_flap(prev, {"pid": 200, "alive": True,
                                   "last_reload_ok": True}, now)
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


if __name__ == "__main__":
    unittest.main()
