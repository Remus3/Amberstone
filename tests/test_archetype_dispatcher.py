"""Phase 3 (s176, 2026-05-12) - rank_for_primary_archetype dispatcher tests.

Covers the 6-archetype routing matrix. Underlying scorer calls are
mocked so the test doesn't touch the live DS server on :8860.
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
    """Phase 4c (s179) - build mock MageRankedItem rows for the ability path."""
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


def _make_assassin_rows(n: int = 2):
    """Phase 5 (s180) - build mock AssassinRankedItem rows for the burst path."""
    return [
        daemon_slayer_client.AssassinRankedItem(
            item_id=f"30{i:02d}", item_name=f"AssassinItem{i}",
            delta_burst=200.0 - i * 20.0,
            new_burst=800.0 - i * 20.0,
            gold=3000 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _make_enchanter_rows(n: int = 2):
    """Phase 6 (s181) - build mock EnchanterRankedItem rows for the hps path."""
    return [
        daemon_slayer_client.EnchanterRankedItem(
            item_id=f"30{i:02d}", item_name=f"EnchanterItem{i}",
            delta_hps=20.0 - i * 2.0,
            new_hps=80.0 - i * 2.0,
            gold=2200 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _zero_mage_rows(n: int = 3):
    """A kit-less champ: the ability scorer returns delta 0.0 for every
    item (no ability data in the frozen Meraki snapshot), so the ranker
    surfaces the cheapest starters at +0.0 (the Locke 16.14.1 symptom)."""
    return [
        daemon_slayer_client.MageRankedItem(
            item_id=f"10{i:02d}", item_name=f"Starter{i}",
            delta_ability_dps=0.0, new_ability_dps=0.0,
            gold=450 + i * 50,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _zero_assassin_rows(n: int = 3):
    return [
        daemon_slayer_client.AssassinRankedItem(
            item_id=f"10{i:02d}", item_name=f"Starter{i}",
            delta_burst=0.0, new_burst=0.0,
            gold=450 + i * 50,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


def _zero_enchanter_rows(n: int = 3):
    return [
        daemon_slayer_client.EnchanterRankedItem(
            item_id=f"10{i:02d}", item_name=f"Starter{i}",
            delta_hps=0.0, new_hps=0.0,
            gold=450 + i * 50,
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
        # Vayne is a carry that is NOT in the fight_length allow-map, so the L4
        # squishy-carry target swap does not apply and the caller's target
        # propagates verbatim (this test isolates the propagation plumbing).
        mock_rank.return_value = _make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Vayne", "carry", level=11, item_ids=[],
            target_armor=120.0, target_mr=80.0,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["target_armor"], 120.0)
        self.assertEqual(kwargs["target_mr"], 80.0)

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_carry_mapped_burst_champ_swaps_to_squishy_target(self, mock_rank):
        # L4 crit-burst fix: a champion IN the fight_length allow-map (Caitlyn)
        # is a burst carry that deletes the enemy squishy carry, so the caller's
        # tanky team-average target is REPLACED with the squishy-carry stat line
        # before rank_for. The swap is on by default (apply_squishy_burst_target)
        # and lowers target_armor well below the passed 120.0.
        mock_rank.return_value = _make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            target_armor=120.0, target_mr=80.0,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertLess(kwargs["target_armor"], 120.0)
        # The opt-out (used by the offline build_order_variants) restores verbatim
        # propagation even for a mapped champ.
        mock_rank.reset_mock()
        mock_rank.return_value = _make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            target_armor=120.0, target_mr=80.0, apply_squishy_burst_target=False,
        )
        self.assertEqual(mock_rank.call_args.kwargs["target_armor"], 120.0)


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
    """Phase 4c (s179) - mage routes to ds.ability via rank_mage_for."""

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


class AssassinRoutingTests(unittest.TestCase):
    """Phase 5 (s180) - assassin routes to ds.burst via rank_assassin_for."""

    @mock.patch("core.daemon_slayer_client.rank_assassin_for")
    def test_assassin_routes_to_rank_assassin_for(self, mock_rank):
        mock_rank.return_value = _make_assassin_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Zed", "assassin", level=11, item_ids=[],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["scorer"], "burst")
        self.assertEqual(out["archetype"], "assassin")
        self.assertFalse(out["fell_back"])
        self.assertEqual(len(out["ranked"]), 3)
        # Burst rows surface delta (= delta_burst) + new_burst.
        self.assertEqual(out["ranked"][0]["delta"], 200.0)
        self.assertIn("new_burst", out["ranked"][0])
        mock_rank.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_assassin_for")
    def test_assassin_passes_combo_sequence(self, mock_rank):
        mock_rank.return_value = _make_assassin_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Talon", "assassin", level=11, item_ids=[],
            combo_sequence=("W", "Q", "AA", "R", "AA"),
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["combo_sequence"], ("W", "Q", "AA", "R", "AA"))

    @mock.patch("core.daemon_slayer_client.rank_assassin_for")
    def test_assassin_passes_target_current_hp_pct(self, mock_rank):
        mock_rank.return_value = _make_assassin_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Zed", "assassin", level=11, item_ids=[],
            target_current_hp_pct=0.4,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["target_current_hp_pct"], 0.4)

    @mock.patch("core.daemon_slayer_client.rank_assassin_for")
    def test_assassin_passes_max_priority(self, mock_rank):
        mock_rank.return_value = _make_assassin_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Akali", "assassin", level=11, item_ids=[],
            max_priority=("Q", "E", "W"),
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(kwargs["max_priority"], ("Q", "E", "W"))

    @mock.patch("core.daemon_slayer_client.rank_assassin_for", return_value=None)
    def test_assassin_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Zed", "assassin", level=11, item_ids=[],
        )
        self.assertIsNone(out)


class EnchanterRoutingTests(unittest.TestCase):
    """Phase 6 (s181) - enchanter routes to ds.hps via rank_enchanter_for."""

    @mock.patch("core.daemon_slayer_client.rank_enchanter_for")
    def test_enchanter_routes_to_rank_enchanter_for(self, mock_rank):
        mock_rank.return_value = _make_enchanter_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Soraka", "enchanter", level=11, item_ids=[],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["scorer"], "hps")
        self.assertEqual(out["archetype"], "enchanter")
        self.assertFalse(out["fell_back"])
        self.assertEqual(len(out["ranked"]), 3)
        # HPS rows surface delta (= delta_hps) + new_hps.
        self.assertEqual(out["ranked"][0]["delta"], 20.0)
        self.assertIn("new_hps", out["ranked"][0])
        mock_rank.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_enchanter_for")
    def test_enchanter_passes_targets_per_proc_override(self, mock_rank):
        mock_rank.return_value = _make_enchanter_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Lulu", "enchanter", level=11, item_ids=[],
            targets_per_proc_override=1.0,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertAlmostEqual(kwargs["targets_per_proc_override"], 1.0)

    @mock.patch("core.daemon_slayer_client.rank_enchanter_for")
    def test_enchanter_passes_only_item_ids(self, mock_rank):
        mock_rank.return_value = _make_enchanter_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Janna", "enchanter", level=11, item_ids=[],
            only_item_ids=["6617", "3107"],
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertEqual(list(kwargs["only_item_ids"]), ["6617", "3107"])

    @mock.patch("core.daemon_slayer_client.rank_enchanter_for")
    def test_enchanter_passes_filter_shared_uniques(self, mock_rank):
        mock_rank.return_value = _make_enchanter_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Soraka", "enchanter", level=11, item_ids=[],
            filter_shared_uniques=False,
        )
        kwargs = mock_rank.call_args.kwargs
        self.assertFalse(kwargs["filter_shared_uniques"])

    @mock.patch("core.daemon_slayer_client.rank_enchanter_for", return_value=None)
    def test_enchanter_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Soraka", "enchanter", level=11, item_ids=[],
        )
        self.assertIsNone(out)


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

    @mock.patch("core.daemon_slayer_client.rank_enchanter_for", return_value=None)
    def test_enchanter_returns_none_when_engine_down(self, _):
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Soraka", "enchanter", level=11, item_ids=[],
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
        # An unknown string isn't mage/assassin/enchanter/bruiser/tank/carry
        # so it falls through to dps as the default; fell_back=False
        # post-Phase-6 (all 6 archetypes have their own scorer; this path
        # handles only catch-all labels).
        mock_rank.return_value = _make_dps_rows(1)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Aatrox", "unknown_archetype", level=11, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")
        self.assertFalse(out["fell_back"])


class KitlessFallbackTests(unittest.TestCase):
    """A champ with NO ability data (released after the frozen Meraki
    `latest` content_patch, e.g. Locke on 16.14.1) makes the kit-dependent
    scorers (ability / burst / hps) return an all-zero ranking -> a
    useless +0.0 starter build. The dispatcher detects the all-zero case
    and falls back to ds.dps (pure auto-attack, no kit data needed).

    The AA-based scorers (dps / ehp / hybrid) are self-protecting and MUST
    NOT be touched: a real kit (non-zero deltas) never triggers the
    fallback, and a partial-zero ranking (some items score, some don't)
    stays on the requested scorer.
    """

    @mock.patch("core.daemon_slayer_client.rank_for")
    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_kitless_all_zero_falls_back_to_dps(self, mock_mage, mock_dps):
        mock_mage.return_value = _zero_mage_rows(3)
        mock_dps.return_value = _make_dps_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=13, item_ids=[],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["scorer"], "dps")   # NOT "ability"
        self.assertEqual(out["archetype"], "carry")  # coherent carry/dps label
        self.assertTrue(out["fell_back"])
        self.assertEqual(len(out["ranked"]), 3)
        self.assertGreater(out["ranked"][0]["delta"], 0.0)
        mock_dps.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_for")
    @mock.patch("core.daemon_slayer_client.rank_assassin_for")
    def test_assassin_kitless_all_zero_falls_back_to_dps(self, mock_ass, mock_dps):
        mock_ass.return_value = _zero_assassin_rows(3)
        mock_dps.return_value = _make_dps_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Zed", "assassin", level=13, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")   # NOT "burst"
        self.assertEqual(out["archetype"], "carry")  # coherent carry/dps label
        self.assertTrue(out["fell_back"])
        self.assertGreater(out["ranked"][0]["delta"], 0.0)
        mock_dps.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_for")
    @mock.patch("core.daemon_slayer_client.rank_enchanter_for")
    def test_enchanter_kitless_all_zero_falls_back_to_dps(self, mock_ench, mock_dps):
        mock_ench.return_value = _zero_enchanter_rows(3)
        mock_dps.return_value = _make_dps_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Soraka", "enchanter", level=13, item_ids=[],
        )
        self.assertEqual(out["scorer"], "dps")   # NOT "hps"
        self.assertEqual(out["archetype"], "carry")  # coherent carry/dps label
        self.assertTrue(out["fell_back"])
        self.assertGreater(out["ranked"][0]["delta"], 0.0)
        mock_dps.assert_called_once()

    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_partial_zero_stays_ability(self, mock_mage):
        # Only ALL-zero triggers the fallback. A real kit where one item
        # happens to score 0 but others score > 0 stays on ds.ability.
        rows = _make_mage_rows(2)          # deltas 30.0, 27.0
        rows.append(_zero_mage_rows(1)[0])  # + one 0.0 row
        mock_mage.return_value = rows
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=13, item_ids=[],
        )
        self.assertEqual(out["scorer"], "ability")
        self.assertFalse(out["fell_back"])

    @mock.patch("core.daemon_slayer_client.rank_mage_for")
    def test_mage_with_kit_unchanged(self, mock_mage):
        # Regression guard: a normal mage (all non-zero) is byte-identical
        # to pre-fix behavior - stays ability, fell_back False.
        mock_mage.return_value = _make_mage_rows(3)
        out = daemon_slayer_client.rank_for_primary_archetype(
            "Veigar", "mage", level=13, item_ids=[],
        )
        self.assertEqual(out["scorer"], "ability")
        self.assertFalse(out["fell_back"])


class DispatchForCoachSquishyBurstTristateTests(unittest.TestCase):
    """``dispatch_for_coach`` must be able to express all THREE states of
    ``apply_squishy_burst_target``.

    Every other dispatcher seam defaults FALSE, so `if flag: seams[k] = True`
    covers its whole range. This one defaults TRUE in the engine
    (core/daemon_slayer_client.py:1410), so that idiom can only ever say
    "on" - the OFF half was unreachable through the dispatcher, and
    core/build_order_variants.py:333 had to build its rank_kwargs by hand to
    get it. The parameter is therefore Optional[bool] with None = inherit.
    """

    class _Stats:
        armor = 80.0
        mr = 30.0
        max_hp = 2000.0
        bonus_hp = 500.0

    @staticmethod
    def _response() -> dict:
        return {
            "ok": True, "scorer": "dps", "archetype": "carry",
            "ranked": [{"item_id": "3078", "item_name": "Trinity Force",
                        "delta": 60.0, "gold": 3333,
                        "shares_dead_unique": False, "dead_unique_key": ""}],
            "fell_back": False,
        }

    def _dispatch(self, m_rk, **kw):
        """Run one dispatch with the ranker spied; return (flat_kwargs,
        plan_rank_kwargs). The spy is the point: it records exactly what the
        engine call was handed, so an OFF claim is proven, not assumed."""
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_rk.return_value = self._response()
        with mock.patch("core.build_order.plan_build_order") as m_plan:
            m_plan.return_value = None
            res = dispatch_for_coach(
                "Caitlyn", mode_engine="SR", level=11, item_ids=[],
                enemy_stats=self._Stats(), with_build_order=True, **kw,
            )
        self.assertIsNotNone(res)
        self.assertEqual(m_plan.call_count, 1)
        return (m_rk.call_args.kwargs,
                m_plan.call_args.kwargs.get("rank_kwargs") or {})

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_omitted_parameter_forwards_nothing(self, m_arch, m_rk):
        """PIN: default None must leave the call byte-identical - no
        apply_squishy_burst_target kwarg on either the flat rank or the
        planner, so the engine's own True default still applies."""
        m_arch.return_value = {"primary": "carry"}
        flat, plan = self._dispatch(m_rk)
        self.assertNotIn("apply_squishy_burst_target", flat)
        self.assertNotIn("apply_squishy_burst_target", plan)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_explicit_true_reaches_rank_and_plan(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "carry"}
        flat, plan = self._dispatch(m_rk, apply_squishy_burst_target=True)
        self.assertIs(flat.get("apply_squishy_burst_target"), True)
        self.assertIs(plan.get("apply_squishy_burst_target"), True)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_explicit_false_reaches_rank_and_plan(self, m_arch, m_rk):
        """The previously unreachable state. RANK and PLAN must agree on it
        for the same reason the other seams do."""
        m_arch.return_value = {"primary": "carry"}
        flat, plan = self._dispatch(m_rk, apply_squishy_burst_target=False)
        self.assertIn("apply_squishy_burst_target", flat)
        self.assertIs(flat["apply_squishy_burst_target"], False)
        self.assertIn("apply_squishy_burst_target", plan)
        self.assertIs(plan["apply_squishy_burst_target"], False)

    @mock.patch("core.daemon_slayer_client.rank_for")
    def test_dispatcher_off_actually_changes_the_engine_target(self, mock_rank):
        """End of the thread: the OFF value the dispatcher now forwards is
        the same one that suppresses the L4 squishy-target swap inside
        rank_for_primary_archetype for a MAPPED burst carry."""
        mock_rank.return_value = _make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            target_armor=120.0, target_mr=80.0,
            apply_squishy_burst_target=True,
        )
        swapped = mock_rank.call_args.kwargs["target_armor"]
        mock_rank.reset_mock()
        mock_rank.return_value = _make_dps_rows(1)
        daemon_slayer_client.rank_for_primary_archetype(
            "Caitlyn", "carry", level=11, item_ids=[],
            target_armor=120.0, target_mr=80.0,
            apply_squishy_burst_target=False,
        )
        verbatim = mock_rank.call_args.kwargs["target_armor"]
        self.assertLess(swapped, 120.0)
        self.assertEqual(verbatim, 120.0)
        self.assertNotEqual(swapped, verbatim)


if __name__ == "__main__":
    unittest.main()
