"""
tests/phase2_smoke/test_daemon_slayer_client_target_bonus_hp.py
Phase 4 batch 19 wire-in - daemon_slayer_client passes target_max_hp +
target_bonus_hp through to /rank and /dps request bodies.

The client is a thin urllib wrapper, so the test surface is the request
body shape. Patches _post_json and asserts the body fields. Engine-side
correctness is covered by agents/daemon_slayer/tests; this file is just
about transport.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import daemon_slayer_client


class RankForTargetBonusHpTests(unittest.TestCase):
    """rank_for must thread target_max_hp + target_bonus_hp into the body."""

    def test_kwargs_default_zero(self) -> None:
        # Pre-batch-19 callers omit the kwargs - body should still
        # carry both fields with 0.0 (engine treats 0 as no signal).
        captured: dict = {}

        def fake_post(path, body, timeout):
            captured["path"] = path
            captured["body"] = body
            return {"ranked": []}

        with mock.patch.object(daemon_slayer_client, "_post_json", side_effect=fake_post):
            daemon_slayer_client.rank_for(
                champion="Aatrox", level=11,
                item_ids=["3036"],
            )
        self.assertEqual(captured["path"], "/rank")
        self.assertEqual(captured["body"]["target_max_hp"], 0.0)
        self.assertEqual(captured["body"]["target_bonus_hp"], 0.0)

    def test_kwargs_passed_through(self) -> None:
        captured: dict = {}

        def fake_post(path, body, timeout):
            captured["body"] = body
            return {"ranked": []}

        with mock.patch.object(daemon_slayer_client, "_post_json", side_effect=fake_post):
            daemon_slayer_client.rank_for(
                champion="Aatrox", level=11,
                item_ids=["3036"],
                target_max_hp=2400.0,
                target_bonus_hp=1500.0,
            )
        self.assertEqual(captured["body"]["target_max_hp"], 2400.0)
        self.assertEqual(captured["body"]["target_bonus_hp"], 1500.0)

    def test_engine_failure_returns_none(self) -> None:
        with mock.patch.object(daemon_slayer_client, "_post_json", return_value=None):
            result = daemon_slayer_client.rank_for(
                champion="Aatrox", level=11,
                item_ids=["3036"],
                target_bonus_hp=1500.0,
            )
        self.assertIsNone(result)


class DpsForTargetBonusHpTests(unittest.TestCase):
    """dps_for must thread the same fields into /dps."""

    def test_kwargs_default_zero(self) -> None:
        captured: dict = {}

        def fake_post(path, body, timeout):
            captured["path"] = path
            captured["body"] = body
            return {"weighted_dps": 0.0}

        with mock.patch.object(daemon_slayer_client, "_post_json", side_effect=fake_post):
            daemon_slayer_client.dps_for(
                champion="Aatrox", level=11,
                item_ids=["3036"],
            )
        self.assertEqual(captured["path"], "/dps")
        self.assertEqual(captured["body"]["target_max_hp"], 0.0)
        self.assertEqual(captured["body"]["target_bonus_hp"], 0.0)

    def test_kwargs_passed_through(self) -> None:
        captured: dict = {}

        def fake_post(path, body, timeout):
            captured["body"] = body
            return {"weighted_dps": 0.0}

        with mock.patch.object(daemon_slayer_client, "_post_json", side_effect=fake_post):
            daemon_slayer_client.dps_for(
                champion="Aatrox", level=11,
                item_ids=["3036"],
                target_max_hp=2400.0,
                target_bonus_hp=750.0,
            )
        self.assertEqual(captured["body"]["target_max_hp"], 2400.0)
        self.assertEqual(captured["body"]["target_bonus_hp"], 750.0)


if __name__ == "__main__":
    unittest.main()
