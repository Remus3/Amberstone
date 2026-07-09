"""Regression guard for the cost_tracker config path (audit 2026-07-09,
Lane 2.1).

Bug: core.cost_tracker._RC_CFG pointed at a phantom repo-root
rc_config.json that never existed. read_json_dict(default={}) swallowed
the miss, so an operator who followed CONFIG_AUTHORITY.md and added
daily_budget_usd to ops/rc_config.json got it silently ignored - the daily
spend cap was never enforced.

Fix: _RC_CFG resolves to _APP_DIR / "ops" / "rc_config.json" (the config
authority named in CONFIG_AUTHORITY.md).

test_rc_cfg_points_at_ops_config + test_rc_cfg_file_exists are the
red-before / green-after guards. The read-path class proves the mechanism:
whatever _RC_CFG points at, a daily_budget_usd key in that file flows
through _read_config -> _budget_usd (hermetic: temp files, no repo mutation).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import cost_tracker


class RcCfgPathTests(unittest.TestCase):
    def test_rc_cfg_points_at_ops_config(self) -> None:
        # The authority file lives under ops/, not the repo root.
        self.assertEqual(
            cost_tracker._RC_CFG,
            cost_tracker._APP_DIR / "ops" / "rc_config.json",
        )

    def test_rc_cfg_file_exists(self) -> None:
        # A phantom path would fail silently; the authority file must be real.
        self.assertTrue(
            cost_tracker._RC_CFG.is_file(),
            f"cost_tracker._RC_CFG does not exist: {cost_tracker._RC_CFG}",
        )


class RcCfgReadPathTests(unittest.TestCase):
    """A daily_budget_usd key placed in the _RC_CFG file is honored by the
    read path (_read_config -> _budget_usd). Patches _RC_CFG + _COACH_CFG to
    temp files so nothing in the repo is touched."""

    def setUp(self) -> None:
        self._td = tempfile.mkdtemp()
        self._rc_cfg = Path(self._td) / "rc_config.json"
        self._coach_cfg = Path(self._td) / "coach_settings.json"  # absent
        self._rc_cfg.write_text(
            json.dumps({"daily_budget_usd": 5.0}), encoding="utf-8")
        self._patch_rc = mock.patch.object(
            cost_tracker, "_RC_CFG", self._rc_cfg)
        self._patch_coach = mock.patch.object(
            cost_tracker, "_COACH_CFG", self._coach_cfg)
        self._patch_rc.start()
        self._patch_coach.start()

    def tearDown(self) -> None:
        self._patch_coach.stop()
        self._patch_rc.stop()

    def test_read_config_surfaces_daily_budget(self) -> None:
        merged = cost_tracker._read_config()
        self.assertEqual(merged.get("daily_budget_usd"), 5.0)

    def test_budget_usd_honors_ops_config_value(self) -> None:
        tracker = cost_tracker.CostTracker(
            config_provider=cost_tracker._read_config,
            spend_dir=Path(self._td) / "spend",
        )
        # 5.0, not 0.0 (unlimited) - proves the key was read, not defaulted.
        self.assertEqual(tracker._budget_usd(), 5.0)

    def test_missing_budget_key_is_unlimited(self) -> None:
        # Sanity: an empty config yields the unlimited (0.0) sentinel, so the
        # positive test above is not a false pass.
        self._rc_cfg.write_text(json.dumps({}), encoding="utf-8")
        tracker = cost_tracker.CostTracker(
            config_provider=cost_tracker._read_config,
            spend_dir=Path(self._td) / "spend2",
        )
        self.assertEqual(tracker._budget_usd(), 0.0)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
