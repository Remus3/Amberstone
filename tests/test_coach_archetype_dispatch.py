"""Tests for coach_integration/archetype_dispatch.py (s182, 2026-05-13).

The helper wires `core.archetype_picks.get_archetype_for` + the DS
dispatcher (`core.daemon_slayer_client.rank_for_primary_archetype`) +
formatting for the coach's LLM prompt + the `daemon_slayer_picks`
payload shape.

Engine calls are mocked at the dispatcher boundary - no live DS server
needed.
"""
from __future__ import annotations

import unittest
from unittest import mock

from coach_integration import archetype_dispatch
from coach_integration.archetype_dispatch import (
    CoachDispatchResult,
    dispatch_for_coach,
    display_label,
)


class _Stats:
    """Stub for coach_integration.enemy_stats.EnemyStats - duck-typed by
    the helper via getattr(..., 'armor'/'mr'/'max_hp'/'bonus_hp')."""
    def __init__(self, armor=80.0, mr=30.0, max_hp=2000.0, bonus_hp=500.0):
        self.armor = armor
        self.mr = mr
        self.max_hp = max_hp
        self.bonus_hp = bonus_hp


def _make_dispatcher_response(scorer: str, rows: list[dict]) -> dict:
    return {
        "ok":        True,
        "scorer":    scorer,
        "archetype": "carry" if scorer == "dps" else scorer,
        "ranked":    rows,
        "fell_back": False,
    }


class DispatchEmptyAndEngineDownTests(unittest.TestCase):
    """Edge cases that don't call the dispatcher."""

    def test_empty_champion_returns_none(self):
        self.assertIsNone(dispatch_for_coach(
            "", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        ))

    def test_whitespace_champion_returns_none(self):
        self.assertIsNone(dispatch_for_coach(
            "   ", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        ))

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_engine_unreachable_returns_none(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = None
        self.assertIsNone(dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        ))


class DispatchDpsScorerTests(unittest.TestCase):
    """Carry archetype routes via ds.dps -> delta field is delta_dps."""

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_dispatches_and_formats_dps(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _make_dispatcher_response("dps", [
            {"item_id": "3094", "item_name": "Rapid Firecannon",
             "delta": 54.0, "gold": 2900},
            {"item_id": "3031", "item_name": "Infinity Edge",
             "delta": 48.0, "gold": 3500},
        ])
        result = dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIsInstance(result, CoachDispatchResult)
        self.assertEqual(result.archetype, "carry")
        self.assertEqual(result.scorer, "dps")
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.picks_str,
                         "Rapid Firecannon(+54dps,2900g) > Infinity Edge(+48dps,3500g)")
        # Display rows preserve the legacy 4-field shape + add delta/scorer.
        self.assertEqual(result.display_rows[0]["id"], "3094")
        self.assertEqual(result.display_rows[0]["name"], "Rapid Firecannon")
        self.assertEqual(result.display_rows[0]["delta_dps"], 54.0)
        self.assertEqual(result.display_rows[0]["delta"], 54.0)
        self.assertEqual(result.display_rows[0]["scorer"], "dps")
        self.assertEqual(result.display_rows[0]["gold"], 2900)


class DispatchTankScorerTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_tank_routes_with_ehp_unit(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "tank"}
        mock_disp.return_value = _make_dispatcher_response("ehp", [
            {"item_id": "3143", "item_name": "Randuin's Omen",
             "delta": 520.0, "gold": 2700},
            {"item_id": "3068", "item_name": "Sunfire Aegis",
             "delta": 440.0, "gold": 2900},
        ])
        result = dispatch_for_coach(
            "Malphite", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertEqual(result.scorer, "ehp")
        self.assertEqual(result.picks_str,
                         "Randuin's Omen(+520ehp,2700g) > Sunfire Aegis(+440ehp,2900g)")
        # display_rows.delta_dps carries the EHP value (mislabeled key, but
        # numerically correct - scorer field disambiguates).
        self.assertEqual(result.display_rows[0]["delta_dps"], 520.0)
        self.assertEqual(result.display_rows[0]["scorer"], "ehp")


class DispatchHybridScorerTests(unittest.TestCase):
    """Bruiser uses hybrid_delta_pct as the display unit (scaled to 100)."""

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_bruiser_uses_pct_unit(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "bruiser"}
        mock_disp.return_value = _make_dispatcher_response("hybrid", [
            {"item_id": "3078", "item_name": "Trinity Force",
             "delta_dps": 18.5, "delta_ehp": 90.0,
             "hybrid_delta_pct": 0.08, "gold": 3333},
            {"item_id": "6333", "item_name": "Death's Dance",
             "delta_dps": 12.0, "delta_ehp": 150.0,
             "hybrid_delta_pct": 0.06, "gold": 3300},
        ])
        result = dispatch_for_coach(
            "JarvanIV", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertEqual(result.scorer, "hybrid")
        self.assertEqual(result.picks_str,
                         "Trinity Force(+8%,3333g) > Death's Dance(+6%,3300g)")
        # Display rows carry pct*100 in the delta_dps slot.
        self.assertEqual(result.display_rows[0]["delta_dps"], 8.0)
        self.assertEqual(result.display_rows[0]["delta"], 8.0)
        self.assertEqual(result.display_rows[0]["scorer"], "hybrid")


class DispatchMageAssassinEnchanterTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_mage_picks_str_uses_adps(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "mage"}
        mock_disp.return_value = _make_dispatcher_response("ability", [
            {"item_id": "3089", "item_name": "Rabadon's",
             "delta": 13.5, "new_ability_dps": 38.65, "gold": 3500},
        ])
        result = dispatch_for_coach(
            "Veigar", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIn("(+14adps,3500g)", result.picks_str)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_assassin_picks_str_uses_burst(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "assassin"}
        mock_disp.return_value = _make_dispatcher_response("burst", [
            {"item_id": "3031", "item_name": "Infinity Edge",
             "delta": 250.0, "new_burst": 583.9, "gold": 3500},
        ])
        result = dispatch_for_coach(
            "Zed", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIn("(+250burst,3500g)", result.picks_str)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_enchanter_picks_str_uses_hps(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "enchanter"}
        mock_disp.return_value = _make_dispatcher_response("hps", [
            {"item_id": "6620", "item_name": "Echoes of Helia",
             "delta": 25.14, "new_hps": 25.14, "gold": 2200},
        ])
        result = dispatch_for_coach(
            "Soraka", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIn("(+25hps,2200g)", result.picks_str)


class DispatchEmptyRankedTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_engine_up_but_no_rows(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _make_dispatcher_response("dps", [])
        result = dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.picks_str, "none")
        self.assertEqual(result.display_rows, [])


class DispatchArchetypeResolutionTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_archetype_from_picks_file(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "tank", "source": "user_cs"}
        mock_disp.return_value = _make_dispatcher_response("ehp", [
            {"item_id": "3143", "item_name": "Randuin's",
             "delta": 500.0, "gold": 2700},
        ])
        result = dispatch_for_coach(
            "Malphite", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        # Helper passes archetype through to dispatcher kwargs.
        kwargs = mock_disp.call_args.kwargs
        self.assertEqual(kwargs["archetype"], "tank")
        self.assertEqual(result.archetype, "tank")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_archetype_missing_falls_through_to_carry(self, mock_arch, mock_disp):
        mock_arch.return_value = {}  # No 'primary' key
        mock_disp.return_value = _make_dispatcher_response("dps", [])
        result = dispatch_for_coach(
            "MysteryChampion", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        kwargs = mock_disp.call_args.kwargs
        self.assertEqual(kwargs["archetype"], "carry")
        self.assertEqual(result.archetype, "carry")


class DispatchEnemyStatsPropagationTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_enemy_stats_passed_to_dispatcher(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _make_dispatcher_response("dps", [])
        dispatch_for_coach(
            "Caitlyn", mode_engine="ARAM", level=14, item_ids=["3031"],
            enemy_stats=_Stats(armor=120.0, mr=80.0, max_hp=2800.0, bonus_hp=900.0),
            augments=["TheBrutalizer"],
            top=8,
        )
        kwargs = mock_disp.call_args.kwargs
        self.assertEqual(kwargs["target_armor"], 120.0)
        self.assertEqual(kwargs["target_mr"], 80.0)
        self.assertEqual(kwargs["target_max_hp"], 2800.0)
        self.assertEqual(kwargs["target_bonus_hp"], 900.0)
        self.assertEqual(kwargs["mode"], "ARAM")
        self.assertEqual(kwargs["level"], 14)
        self.assertEqual(kwargs["item_ids"], ["3031"])
        self.assertEqual(kwargs["top"], 8)
        self.assertEqual(kwargs["augments"], ["TheBrutalizer"])


class DisplayLabelTests(unittest.TestCase):
    def test_known_scorers(self):
        self.assertEqual(display_label("dps"), "DPS")
        self.assertEqual(display_label("ehp"), "EHP")
        self.assertEqual(display_label("hybrid"), "hybrid")
        self.assertEqual(display_label("ability"), "ability-DPS")
        self.assertEqual(display_label("burst"), "burst")
        self.assertEqual(display_label("hps"), "HPS")

    def test_unknown_scorer_falls_back_to_input(self):
        self.assertEqual(display_label("unknown"), "unknown")
        self.assertEqual(display_label(""), "")


class InternalHelperTests(unittest.TestCase):
    def test_row_delta_dps(self):
        self.assertEqual(
            archetype_dispatch._row_delta({"delta": 54.0}, "dps"), 54.0,
        )

    def test_row_delta_falls_back_to_delta_dps_key(self):
        # Legacy row from older dispatcher payloads.
        self.assertEqual(
            archetype_dispatch._row_delta({"delta_dps": 42.0}, "dps"), 42.0,
        )

    def test_row_delta_hybrid_scales_pct(self):
        self.assertEqual(
            archetype_dispatch._row_delta({"hybrid_delta_pct": 0.08}, "hybrid"),
            8.0,
        )

    def test_row_delta_missing_field_returns_zero(self):
        self.assertEqual(archetype_dispatch._row_delta({}, "ehp"), 0.0)


if __name__ == "__main__":
    unittest.main()
