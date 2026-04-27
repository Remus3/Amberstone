"""
tests/phase2_smoke/test_metrics_cache.py
Smoke tests for core/metrics_cache.py summary behavior.
No live dependencies required.
"""
import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.metrics_cache import MetricsCache
import core.feature_policy as fp


def _mc(td: Path) -> MetricsCache:
    mc = MetricsCache(td, refresh_interval_s=9999)
    mc._refresh()
    return mc


class TestMetricsCacheSummary(unittest.TestCase):

    def setUp(self):
        self._td_obj = tempfile.TemporaryDirectory()
        self._td = Path(self._td_obj.name)

    def tearDown(self):
        fp._reload()
        self._td_obj.cleanup()

    # ── Helper ─────────────────────────────────────────────────────────────
    def _write(self, filename, data):
        p = self._td / filename
        p.write_text(json.dumps(data), encoding="utf-8")

    # ── Tests ──────────────────────────────────────────────────────────────

    def test_missing_files_yield_none_not_crash(self):
        """All fields default to None when runtime dir is empty."""
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertIsNone(s.supervisor_state)
        self.assertIsNone(s.process_running)
        self.assertIsNone(s.current_mode)
        self.assertIsNone(s.last_coaching_ts)
        self.assertEqual(s.last_5_incidents, [])

    def test_status_json_fields(self):
        self._write("status.json", {
            "supervisor_state": "healthy_ready",
            "process_running": True,
            "awaiting_first_heartbeat": False,
        })
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertEqual(s.supervisor_state, "healthy_ready")
        self.assertTrue(s.process_running)
        self.assertFalse(s.awaiting_first_heartbeat)

    def test_monitor_state_fields(self):
        self._write("monitor_state.json", {
            "consecutive_fails": 2,
            "ladder_index": 1,
            "circuit_breaker": {"tripped": False},
        })
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertEqual(s.consecutive_fails, 2)
        self.assertEqual(s.ladder_idx, 1)
        self.assertFalse(s.circuit_breaker_tripped)

    def test_health_json_requires_process_running(self):
        """current_mode is None if process_running is not True."""
        self._write("status.json", {"process_running": False})
        self._write("health.json", {"mode": "game"})
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertIsNone(s.current_mode)

    def test_health_json_mode_when_running(self):
        self._write("status.json", {"process_running": True})
        self._write("health.json", {"mode": "game"})
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertEqual(s.current_mode, "game")

    def test_last_coaching_ts_from_artifact(self):
        """Phase 3 Step 1: MetricsCache reads per-mode artifacts and picks the latest."""
        self._write("status.json", {"process_running": True})
        self._write("health.json", {"mode": "client"})
        # Write per-mode artifacts; SR is the latest.
        self._write("coaching_ts_sr.json",    {"ts": "2026-04-13T10:05:00+00:00", "mode": "sr"})
        self._write("coaching_ts_aram.json",  {"ts": "2026-04-13T10:03:00+00:00", "mode": "aram"})
        self._write("coaching_ts_arena.json", {"ts": "2026-04-13T10:01:00+00:00", "mode": "arena"})
        mc = _mc(self._td)
        s = mc.get_summary()
        # Most recent across all present modes must be returned.
        self.assertEqual(s.last_coaching_ts, "2026-04-13T10:05:00+00:00")

    def test_last_coaching_ts_missing_is_none(self):
        self._write("status.json", {"process_running": True})
        self._write("health.json", {"mode": "client"})
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertIsNone(s.last_coaching_ts)

    def test_last_coaching_ts_malformed_is_none(self):
        """A malformed per-mode artifact is non-fatal; other modes still work."""
        self._write("status.json", {"process_running": True})
        self._write("health.json", {"mode": "client"})
        # Malformed SR artifact; no other mode artifact written.
        (self._td / "coaching_ts_sr.json").write_text("NOT JSON {{{", encoding="utf-8")
        mc = _mc(self._td)
        s = mc.get_summary()
        # Malformed file ignored; no other valid artifacts -> None.
        self.assertIsNone(s.last_coaching_ts)

    def test_incident_tail_read(self):
        log_path = self._td / "incident_log.jsonl"
        entries = [
            {"ts": "2026-04-13T10:00:01Z", "severity": "WARN",
             "subsystem": "rc.super", "trigger": "restart", "detail": "attempt 1"},
            {"ts": "2026-04-13T10:00:02Z", "severity": "ERROR",
             "subsystem": "rc.super", "trigger": "restart", "detail": "attempt 2"},
        ]
        log_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertEqual(len(s.last_5_incidents), 2)
        self.assertEqual(s.last_5_incidents[0]["severity"], "WARN")

    def test_get_summary_returns_safe_copy(self):
        """Mutating the returned summary must not affect the cache."""
        mc = _mc(self._td)
        s1 = mc.get_summary()
        s1.supervisor_state = "mutated"
        s2 = mc.get_summary()
        self.assertNotEqual(s2.supervisor_state, "mutated")

    def test_policy_fields_populated(self):
        """MetricsCache exposes policy state via feature_policy."""
        fp._reload()   # ensure default all-allow
        self._write("status.json", {"process_running": True})
        self._write("health.json", {"mode": "client"})
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertIsNotNone(s.policy_source_status)
        self.assertEqual(s.policy_sr_live_coaching, "allow")
        self.assertEqual(s.policy_tft_vision_analysis, "allow")

    def test_malformed_status_json_non_fatal(self):
        (self._td / "status.json").write_text("{bad json{{", encoding="utf-8")
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertIsNone(s.supervisor_state)  # graceful None, no crash

    def test_refreshed_at_present(self):
        mc = _mc(self._td)
        s = mc.get_summary()
        self.assertTrue(len(s.refreshed_at) > 0)


if __name__ == "__main__":
    unittest.main()
