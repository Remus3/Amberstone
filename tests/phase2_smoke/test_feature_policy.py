"""
tests/phase2_smoke/test_feature_policy.py
Smoke tests for core/feature_policy.py hot-reload and last-known-good contracts.
No live dependencies required.
"""
import json
import sys
import time
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import core.feature_policy as fp
from core.feature_policy import is_allowed, get_policy_state


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class TestFeaturePolicyHotReload(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._cfg = Path(self._td.name) / "feature_flags.json"

    def tearDown(self):
        fp._reload()          # restore production config
        self._td.cleanup()

    def test_initial_load_all_allow(self):
        """Default all-allow file loads correctly."""
        _write(self._cfg, {"sr": {"live_coaching": "allow"},
                            "aram": {"live_coaching": "allow"},
                            "tft": {"live_coaching": "allow",
                                    "tft_vision_analysis": "allow"}})
        fp._reload(self._cfg)
        self.assertTrue(is_allowed("sr", "live_coaching"))
        self.assertTrue(is_allowed("aram", "live_coaching"))
        self.assertTrue(is_allowed("tft", "tft_vision_analysis"))

    def test_valid_reload_picks_up_change(self):
        """Changing decision from allow to disabled is picked up without restart."""
        _write(self._cfg, {"sr": {"live_coaching": "allow"}})
        fp._reload(self._cfg)
        self.assertTrue(is_allowed("sr", "live_coaching"))

        time.sleep(0.02)
        _write(self._cfg, {"sr": {"live_coaching": "disabled"}})
        result = is_allowed("sr", "live_coaching")
        self.assertFalse(result)
        self.assertEqual(fp._cache._status, "loaded")

    def test_invalid_reload_retains_last_known_good(self):
        """Malformed decision keeps prior good matrix active."""
        _write(self._cfg, {"sr": {"live_coaching": "allow"}})
        fp._reload(self._cfg)
        self.assertTrue(is_allowed("sr", "live_coaching"))

        time.sleep(0.02)
        _write(self._cfg, {"sr": {"live_coaching": "INVALID_VALUE"}})
        result = is_allowed("sr", "live_coaching")
        self.assertTrue(result, "last-known-good allow must be retained")
        self.assertEqual(fp._cache._status, "invalid_reload_retained")
        self.assertIsNotNone(fp._cache._last_warning)

    def test_file_disappears_retains_last_known_good(self):
        """File deletion after valid load keeps prior matrix active."""
        _write(self._cfg, {"sr": {"live_coaching": "disabled"}})
        fp._reload(self._cfg)
        self.assertFalse(is_allowed("sr", "live_coaching"))

        self._cfg.unlink()
        result = is_allowed("sr", "live_coaching")
        self.assertFalse(result, "last-known-good disabled must be retained")
        self.assertEqual(fp._cache._status, "last_known_good")

    def test_get_policy_state_returns_required_keys(self):
        """get_policy_state() exposes all required fields."""
        fp._reload()
        state = get_policy_state()
        self.assertIn("policy_source_status", state)
        self.assertIn("policy_last_reload_ts", state)
        self.assertIn("policy_last_warning", state)
        self.assertIn("effective_decisions", state)
        dec = state["effective_decisions"]
        for mode in ("sr", "aram", "arena", "brawl", "tft"):
            self.assertIn(mode, dec)
        self.assertIn("tft_vision_analysis", dec.get("tft", {}))

    def test_get_policy_state_triggers_reload_in_idle_mode(self):
        """get_policy_state picks up file change without is_allowed()."""
        _write(self._cfg, {"aram": {"live_coaching": "allow"}})
        fp._reload(self._cfg)
        s1 = get_policy_state()
        self.assertEqual(s1["effective_decisions"]["aram"]["live_coaching"], "allow")

        time.sleep(0.02)
        _write(self._cfg, {"aram": {"live_coaching": "disabled"}})
        s2 = get_policy_state()       # no is_allowed() call
        self.assertEqual(s2["effective_decisions"]["aram"]["live_coaching"], "disabled")

    def test_unknown_mode_returns_true(self):
        fp._reload()
        self.assertTrue(is_allowed("unknown_mode_xyz", "live_coaching"))

    def test_unknown_feature_returns_true(self):
        fp._reload()
        self.assertTrue(is_allowed("sr", "nonexistent_feature"))

    def test_missing_file_at_startup_all_allow(self):
        """Non-existent file at startup -> all safe defaults (allow)."""
        missing = Path(self._td.name) / "does_not_exist.json"
        fp._reload(missing)
        self.assertTrue(is_allowed("sr", "live_coaching"))
        self.assertTrue(is_allowed("tft", "tft_vision_analysis"))

    def test_get_policy_state_invalid_reload_retains_last_known_good(self):
        """LKG via get_policy_state (not is_allowed) on invalid rewrite."""
        _write(self._cfg, {"sr": {"live_coaching": "allow"}})
        fp._reload(self._cfg)

        time.sleep(0.02)
        _write(self._cfg, '{"sr": {"live_coaching": "bad"}}')
        state = get_policy_state()
        self.assertEqual(
            state["effective_decisions"]["sr"]["live_coaching"], "allow")
        self.assertEqual(state["policy_source_status"], "invalid_reload_retained")


if __name__ == "__main__":
    unittest.main()
