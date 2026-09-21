"""Stormrazor changed DDragon id between 16.15.1 and 16.18.1.

MEASURED 2026-09-20 (DS patch refresh 16.15.1 -> 16.18.1):

* 16.15.1: ``3097`` = "Stormrazor" (3200g, maps 11/12/21/35/453) and ``3095``
  = "Deprecated item" (3000g, on NO map, so never a build candidate).
* 16.18.1: ``3097`` is GONE from DDragon, and ``3095`` = "Stormrazor" (3200g,
  50 AD / 25% AS / 25% crit, maps 11/12/453).

The Energized Bolt proc was registered only on ``3097``, so without a row on
``3095`` the live Stormrazor would score as a bare stat stick at 16.18.1. The
``3097`` row stays for the frozen 16.15.1 snapshot. Meraki (frozen at content
patch 25.15) still keys Stormrazor as ``3097``, which is where the 100-damage
Bolt magnitude comes from; the id move is DDragon-only.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS


def _const_periodics(item_id: str):
    eff = ITEM_EFFECTS.get(item_id)
    assert eff is not None, f"{item_id} missing from ITEM_EFFECTS"
    return [
        (p.name, p.bonus_damage, p.damage_type, p.every_n_seconds)
        for p in eff.periodics
        if not callable(p.bonus_damage)
    ]


class StormrazorIdMove(unittest.TestCase):
    def test_live_stormrazor_id_carries_the_energized_bolt(self) -> None:
        self.assertTrue(_const_periodics("3095"),
                        "3095 (Stormrazor since 16.17.1) has no Bolt proc")

    def test_both_ids_register_the_identical_bolt(self) -> None:
        # One item, two DDragon ids across patches: the proc must not drift.
        self.assertEqual(_const_periodics("3095"), _const_periodics("3097"))

    def test_the_catalog_ids_match_the_registry_story(self) -> None:
        # Pins the premise so a later patch that moves the id again goes red
        # here instead of silently dropping the proc.
        old = DataSnapshot.load(patch="16.15.1").items
        self.assertEqual(old["3097"]["name"], "Stormrazor")
        self.assertEqual(old["3095"]["name"], "Deprecated item")
        cur = DataSnapshot.load().items
        storm_ids = sorted(i for i, r in cur.items()
                           if r.get("name") == "Stormrazor" and len(i) == 4)
        self.assertTrue(storm_ids, "no 4-digit Stormrazor in the current snapshot")
        for sid in storm_ids:
            self.assertTrue(_const_periodics(sid),
                            f"current Stormrazor id {sid} has no Bolt proc")


if __name__ == "__main__":
    unittest.main()
