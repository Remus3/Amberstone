"""R55 - archetype-aware DEFAULT resolver + dispatcher flag (client side).

The resolver ``core.ds_archetype_hp_pct.archetype_target_current_hp_pct`` maps a
champion archetype to a conservative DEFAULT current-HP fraction for the
``target_current_hp_pct`` seam (SUSTAINED / juggernaut -> 0.5; BURST +
non-damage / unknown -> 1.0). The dispatcher
``core.daemon_slayer_client.rank_for_primary_archetype`` opts in via
``assume_archetype_hp_pct=True`` (DEFAULT-OFF -> byte-identical when off).

The resolver lives in ``core`` (not ``agents.daemon_slayer``) so the :8893 HTTP
client never imports the engine package in-process - see the split-brain guard
tests/test_ds_preview_e2e_p1l21.py TestNoEngineSplitBrain. This test therefore
lives in the RC suite (tests/), not the DS engine suite.

Branch fns are mocked (mirrors tests/test_archetype_dispatcher.py) so nothing
hits the live :8893 server.
"""
from __future__ import annotations

import unittest
from unittest import mock

from core import daemon_slayer_client
from core.ds_archetype_hp_pct import archetype_target_current_hp_pct


class ResolverUnitTests(unittest.TestCase):
    def test_burst_and_identity_resolve_to_one(self):
        for arch in ("assassin", "mage", "burst", "tank", "enchanter",
                     "support", "", "unknown"):
            with self.subTest(arch=arch):
                self.assertEqual(archetype_target_current_hp_pct(arch), 1.0)

    def test_sustained_resolve_to_half(self):
        for arch in ("carry", "dps", "adc", "marksman", "bruiser", "fighter",
                     "juggernaut", "skirmisher"):
            with self.subTest(arch=arch):
                self.assertEqual(archetype_target_current_hp_pct(arch), 0.5)

    def test_case_insensitive(self):
        self.assertEqual(archetype_target_current_hp_pct("Bruiser"), 0.5)
        self.assertEqual(archetype_target_current_hp_pct("  CARRY  "), 0.5)
        self.assertEqual(archetype_target_current_hp_pct("Assassin"), 1.0)

    def test_none_resolves_to_one(self):
        self.assertEqual(archetype_target_current_hp_pct(None), 1.0)


class DispatcherArchetypeHpPctTests(unittest.TestCase):
    """assume_archetype_hp_pct flag routing (mocks, no :8893)."""

    def _make_dps_rows(self, n=1):
        return [
            daemon_slayer_client.RankedItem(
                item_id="3153", item_name="BotRK",
                delta_dps=100.0, gold=3000,
                shares_dead_unique=False, dead_unique_key="",
            )
            for _ in range(n)
        ]

    def _make_bruiser_rows(self, n=1):
        return [
            daemon_slayer_client.BruiserRankedItem(
                item_id="3153", item_name="BotRK",
                delta_dps=80.0, delta_ehp=400.0, hybrid_delta_pct=0.15,
                gold=3000, shares_dead_unique=False, dead_unique_key="",
            )
            for _ in range(n)
        ]

    def _make_assassin_rows(self, n=1):
        return [
            daemon_slayer_client.AssassinRankedItem(
                item_id="3147", item_name="Duskblade",
                delta_burst=200.0, new_burst=800.0,
                gold=3000, shares_dead_unique=False, dead_unique_key="",
            )
            for _ in range(n)
        ]

    # DEFAULT-OFF: carry branch gets no target_current_hp_pct override (or the
    # 1.0 default) - byte-identical to today.
    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_flag_off_carry_no_override(self, mock_rank):
        mock_rank.return_value = self._make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            assume_archetype_hp_pct=False,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs.get("target_current_hp_pct", 1.0), 1.0)

    @mock.patch("core.daemon_slayer_client.rank_bruiser_for")
    def test_flag_off_bruiser_no_override(self, mock_rank):
        mock_rank.return_value = self._make_bruiser_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "JarvanIV", "bruiser", level=11, item_ids=[],
            assume_archetype_hp_pct=False,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs.get("target_current_hp_pct", 1.0), 1.0)

    # DEFAULT-ON: sustained archetypes get 0.5, burst get 1.0.
    @mock.patch("core.daemon_slayer_client.rank_bruiser_for")
    def test_flag_on_bruiser_gets_half(self, mock_rank):
        mock_rank.return_value = self._make_bruiser_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "JarvanIV", "bruiser", level=11, item_ids=[],
            assume_archetype_hp_pct=True,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["target_current_hp_pct"], 0.5)

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_flag_on_carry_gets_half(self, mock_rank):
        mock_rank.return_value = self._make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            assume_archetype_hp_pct=True,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["target_current_hp_pct"], 0.5)

    @mock.patch("core.daemon_slayer_client.rank_assassin_for")
    def test_flag_on_assassin_gets_one(self, mock_rank):
        mock_rank.return_value = self._make_assassin_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Zed", "assassin", level=11, item_ids=[],
            assume_archetype_hp_pct=True,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["target_current_hp_pct"], 1.0)


if __name__ == "__main__":
    unittest.main()
