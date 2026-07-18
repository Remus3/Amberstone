"""Kit-less champion guard for the ds.hybrid branch (2026-07-18).

Context: champions absent from the frozen Meraki snapshot have NO ability data
(patch 16.14.1: Locke, Zaahen). The dispatcher already detects this for
ds.ability / ds.burst / ds.hps - those return an all-zero ranking, so it falls
through to ds.dps and reports ``fell_back=True``.

ds.hybrid was NOT covered. The in-code comment claimed the AA-based scorers
"need no kit data", but ``agents/daemon_slayer/hybrid.py`` imports
``compute_ability_dps`` and folds ability damage into every row's base damage.
So a kit-less champion routed to bruiser silently loses its entire
ability-damage term while still reporting ``fell_back=False`` - and bruiser is
Zaahen's DEFAULT route.

A row-delta check cannot catch this: a kit-less champion's auto-DPS and EHP
terms are still non-zero, so the ranking looks healthy. It needs a
champion-level "has ability data" signal, which is what these tests cover.

Scorer calls are mocked - no live DS server on :8893.
"""
from __future__ import annotations

import unittest
from unittest import mock

from core import daemon_slayer_client as C


def _make_bruiser_rows(n: int = 2):
    return [
        C.BruiserRankedItem(
            item_id=f"30{i:02d}", item_name=f"BruiserItem{i}",
            delta_dps=80.0 - i * 5.0, delta_ehp=400.0 - i * 30.0,
            hybrid_delta_pct=0.15 - i * 0.02,
            gold=2700 + i * 100,
            shares_dead_unique=False, dead_unique_key="",
        )
        for i in range(n)
    ]


class TestChampionHasAbilityData(unittest.TestCase):
    """Loader behaviour against the real on-disk snapshot."""

    def test_kitted_champion_is_true(self):
        self.assertTrue(C.champion_has_ability_data("Lux"))

    def test_kitless_champions_are_false(self):
        # The two champions absent from Meraki's bulk map at 16.14.1.
        self.assertFalse(C.champion_has_ability_data("Locke"))
        self.assertFalse(C.champion_has_ability_data("Zaahen"))

    def test_display_name_resolves_like_ddragon_id(self):
        self.assertTrue(C.champion_has_ability_data("Lee Sin"))
        self.assertTrue(C.champion_has_ability_data("LeeSin"))

    def test_unreadable_index_fails_soft_to_true(self):
        """A missing/corrupt snapshot must NOT flag every champion as kit-less."""
        with mock.patch.object(C, "_champ_ability_index", {}):
            self.assertTrue(C.champion_has_ability_data("Locke"))


class TestHybridKitlessGuard(unittest.TestCase):
    def test_kitless_champion_sets_fell_back_on_hybrid(self):
        with mock.patch.object(C, "rank_bruiser_for", return_value=_make_bruiser_rows()), \
             mock.patch.object(C, "champion_has_ability_data", return_value=False):
            out = C.rank_for_primary_archetype(
                "Zaahen", "bruiser", level=16, item_ids=[], top=5,
            )
        self.assertIsNotNone(out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["scorer"], "hybrid")
        self.assertTrue(
            out["fell_back"],
            "a kit-less champion's hybrid ranking must be flagged as degraded",
        )
        self.assertTrue(out["ranked"], "the ranking is still served, just flagged")

    def test_kitted_champion_is_not_flagged(self):
        with mock.patch.object(C, "rank_bruiser_for", return_value=_make_bruiser_rows()), \
             mock.patch.object(C, "champion_has_ability_data", return_value=True):
            out = C.rank_for_primary_archetype(
                "Darius", "bruiser", level=16, item_ids=[], top=5,
            )
        self.assertIsNotNone(out)
        self.assertEqual(out["scorer"], "hybrid")
        self.assertFalse(out["fell_back"])


if __name__ == "__main__":
    unittest.main()
