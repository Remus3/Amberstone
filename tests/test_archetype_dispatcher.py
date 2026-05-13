"""Phase 3 (s176, 2026-05-12) — rank_for_primary_archetype dispatcher tests.

Covers the 6-archetype routing matrix. Underlying scorer calls are
mocked so the test doesn't touch the live DS server on :8893.
"""
from __future__ import annotations

import unittest
from unittest import mock

from core import daemon_slayer_client


def _make_dps_rows(n: int = 2):
    """Build mock RankedItem-like dataclass instances for the DPS path."""
    return [
        daemon_slayer_client.RankedItem(
            item_id=f"30{i:02d}", item_name=f"Item{i}",
            delta_dps=100.0 - i * 10.0, gold=2500 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _make_tank_rows(n: int = 2):
    return [
        daemon_slayer_client.TankRankedItem(
            item_id=f"30{i:02d}", item_name=f"TankItem{i}",
            delta_ehp=500.0 - i * 50.0, gold=2700 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _make_bruiser_rows(n: int = 2):
    return [
        daemon_slayer_client.BruiserRankedItem(
            item_id=f"30{i:02d}", item_name=f"BruiserItem{i}",
            delta_dps=80.0 - i * 5.0, delta_ehp=400.0 - i * 30.0,
            hybrid_delta_pct=0.15 - i * 0.02,
            gold=2700 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _make_mage_rows(n: int = 2):
    """Phase 4c (s179) — build mock MageRankedItem rows for the ability path."""
    return [
        daemon_slayer_client.MageRankedItem(
            item_id=f"30{i:02d}", item_name=f"MageItem{i}",
            delta_ability_dps=30.0 - i * 3.0,
            new_ability_dps=140.0 - i * 3.0,
            gold=3000 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


class CarryRoutingTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_carry_routes_to_rank_for(self, mock_rank):
        mock_rank.return_value = _make_dps_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=["3031"],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["scorer"], "dps")
        self.assertEqual(out["archetype"], "carry")
        self.assertFalse(out["fell_back"])
        self.assertEqual(len(out["ranked"]), 3)
        # Verify shape: dps rows have a "delta" alias
        self.assertEqual(out["ranked"][0]["delta"], 100.0)
        mock_rank.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_carry_propagates_target_armor(self, mock_rank):
        mock_rank.return_value = _make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            target_armor=120.0, target_mr=80.0,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["target_armor"], 120.0)
        self.assertEqual(kwargs["target_mr"], 80.0)


class BruiserRoutingTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_bruiser_for")
    def test_bruiser_routes_to_rank_bruiser_for(self, mock_rank):
        mock_rank.return_value = _make_bruiser_rows(2)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "JarvanIV", "bruiser", level=11, item_ids=[],
        )
        self.assertEqual(out["scorer"], "hybrid")
        self.assertEqual(out["archetype"], "bruiser")
        self.assertFalse(out["fell_back"])
        # Hybrid rows expose delta_dps / delta_ehp / hybrid_delta_pct
        for key in ("delta_dps", "delta_ehp", "hybrid_delta_pct"):
            self.assertIn(key, out["ranked"][0])
        mock_rank.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_bruiser_for")
    def test_bruiser_passes_alpha_beta(self, mock_rank):
        mock_rank.return_value = _make_bruiser_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "JarvanIV", "bruiser", level=11, item_ids=[],
            alpha=0.7, beta=0.3,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["alpha"], 0.7)
        self.assertAlmostEqual(kwargs["beta"], 0.3)


class TankRoutingTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_tank_for")
    def test_tank_routes_to_rank_tank_for(self, mock_rank):
        mock_rank.return_value = _make_tank_rows(2)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Malphite", "tank", level=11, item_ids=[],
            enemy_ad_share=0.8, enemy_ap_share=0.2,
        )
        self.assertEqual(out["scorer"], "ehp")
        self.assertEqual(out["archetype"], "tank")
        self.assertFalse(out["fell_back"])
        # Tank rows expose delta (= delta_ehp)
        self.assertEqual(out["ranked"][0]["delta"], 500.0)

    @mock.patch("core.daemon_slayer_client.rank_tank_for")
    def test_tank_passes_shares(self, mock_rank):
        mock_rank.return_value = _make_tank_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Malphite", "tank", level=11, item_ids=[],
            enemy_ad_share=0.9, enemy_ap_share=0.1,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["enemy_ad_share"], 0.9)
        self.assertEqual(kwargs["enemy_ap_share"], 0.1)

    @mock.patch("core.daemon_slayer_client.rank_tank_for")
    def test_tank_passes_only_item_ids_whitelist(self, mock_rank):
        mock_rank.return_value = _make_tank_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Malphite", "tank", level=11, item_ids=[],
            only_item_ids=["3075", "3143"],
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(list(kwargs["only_item_ids"]), ["3075", "3143"])


class MageRoutingTests(unittest.TestCase):
    """Phase 4c (s179) — mage routes to ds.ability via rank_mage_for."""

    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_routes_to_rank_mage_for(self, mock_rank):
        mock_rank.return_value = _make_mage_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=11, item_ids=[],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["scorer"], "ability")
        self.assertEqual(out["archetype"], "mage")
        self.assertFalse(out["fell_back"])
        self.assertEqual(len(out["ranked"]), 3)
        # Mage rows surface delta (= delta_ability_dps) + new_ability_dps.
        self.assertEqual(out["ranked"][0]["delta"], 30.0)
        self.assertIn("new_ability_dps", out["ranked"][0])
        mock_rank.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_passes_target_current_hp_pct(self, mock_rank):
        mock_rank.return_value = _make_mage_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=11, item_ids=[],
            target_current_hp_pct=0.4,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["target_current_hp_pct"], 0.4)

    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_passes_max_priority(self, mock_rank):
        mock_rank.return_value = _make_mage_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=11, item_ids=[],
            max_priority=("W", "E", "Q"),
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["max_priority"], ("W", "E", "Q"))

    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_passes_form_index(self, mock_rank):
        mock_rank.return_value = _make_mage_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Aphelios", "mage", level=11, item_ids=[],
            form_index={"Q": 3},
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["form_index"], {"Q": 3})

    @mock.patch("core.daemon_slayer_client.rank_mage_for", return_value=None)
    def test_mage_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=11, item_ids=[],
        )
        self.assertIsNone(out)


class FallbackArchetypesTests(unittest.TestCase):
    """assassin / enchanter route to ds.dps with fell_back=True until
    Phases 5-6 ship dedicated scorers."""

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_assassin_falls_back_to_dps(self, mock_rank):
        mock_rank.return_value = _make_dps_rows(1)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Zed", "assassin", level=11, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")
        self.assertTrue(out["fell_back"])

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_enchanter_falls_back_to_dps(self, mock_rank):
        mock_rank.return_value = _make_dps_rows(1)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Lulu", "enchanter", level=11, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")
        self.assertTrue(out["fell_back"])


class EngineDownTests(unittest.TestCase):
    """All routes return None when the engine is unreachable (mock
    underlying call returns None)."""

    @mock.patch("core.daemon_slayer_client.rank_for", return_value=None)
    def test_carry_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
        )
        self.assertIsNone(out)

    @mock.patch("core.daemon_slayer_client.rank_bruiser_for", return_value=None)
    def test_bruiser_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "JarvanIV", "bruiser", level=11, item_ids=[],
        )
        self.assertIsNone(out)

    @mock.patch("core.daemon_slayer_client.rank_tank_for", return_value=None)
    def test_tank_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Malphite", "tank", level=11, item_ids=[],
        )
        self.assertIsNone(out)


class UnknownArchetypeTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_empty_archetype_defaults_to_carry(self, mock_rank):
        mock_rank.return_value = _make_dps_rows(1)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "", level=11, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")
        self.assertEqual(out["archetype"], "carry")
        self.assertFalse(out["fell_back"])

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_unknown_archetype_falls_through_to_dps_not_marked_fell_back(self, mock_rank):
        # An unknown string isn't mage/assassin/enchanter so it doesn't
        # mark fell_back — it just routes to dps as the default.
        mock_rank.return_value = _make_dps_rows(1)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Aatrox", "unknown_archetype", level=11, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")
        self.assertFalse(out["fell_back"])


if __name__ == "__main__":
    unittest.main()
