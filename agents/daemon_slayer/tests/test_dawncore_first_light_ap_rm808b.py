"""RM-808 (b) - Dawncore First Light: the AP half is modeled.

First Light reads "Gain 2% Heal and Shield Power and 15 Ability Power per 100%
Base Mana Regen" (DDragon 16.21.1 on SR 6621 / ARAM 326621; 3% HSP on Arena
226621). The HSP half rides the R197 ``_scaling_hsp`` lane. The AP half was
recorded "not modeled" by RM-804, so every Dawncore build was scored 15 AP (30
in Arena) short of the item's real stat panel.

Sources, measured 2026-10-24:

  * DDragon 16.21.1 (``data/daemon_slayer/16.21.1/items.json``): 15 AP per 100%
    on all three rows (16.20.1 read 10).
  * CommunityDragon 16.21 game data (``items.cdtb.bin.json``, Items/<id>
    mDataValues): ``APPerManaRegen 15.0`` on 6621 / 226621 / 326621 (16.20 read
    10.0, matching DDragon 16.20.1). DDragon and the game data agree.
  * Meraki (content patch 25.15) still reads 10 - stale, so the passive-formula
    doctrine yields to the measured game data here exactly as in RM-808 (a).

Step rule: the R197 reading, unchanged - ``floor(printed base mana regen /
100)`` steps from the item's OWN printed ``<stats>`` line (SR 100% -> 1 step,
Arena 200% -> 2, ARAM 150% -> 1), so the AP half is 15 / 30 / 15. Recorded
limit: the AP half counts only the item's own regen (the R197 HSP lane also
counts other items' printed regen); a build stacking a second regen item is
credited the conservative own-item floor.

Carrier: ``ItemEffect.bonus_ap_stacked`` - the engine's "AP not captured in
the DDragon FlatMagicDamageMod stat" field, already read by every AP consumer
(compute_dps, compute_burst_damage, compute_ability_dps, compute_ability_hps)
before the Rabadon amp. A moved modeled number: Tier-2 (ENGINE bump owed to the
merger).

ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import math
import re
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agents.daemon_slayer._scaling_hsp import (
    load_base_mana_regen_pct_table,
    sum_scaling_hsp_pct,
)
from agents.daemon_slayer.ability_hps import compute_ability_hps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_stacked_ap,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

DAWNCORE_IDS = ("6621", "226621", "326621")
# CommunityDragon 16.21 items.cdtb.bin.json Items/<id> APPerManaRegen.
CDRAGON_16_21_AP_PER_STEP = {"6621": 15.0, "226621": 15.0, "326621": 15.0}
EXPECTED_AP = {"6621": 15.0, "226621": 30.0, "326621": 15.0}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_FIRST_LIGHT_AP = re.compile(
    r"and (\d+(?:\.\d+)?) Ability Power per 100% Base Mana Regen", re.IGNORECASE
)


def _ddragon_items() -> dict:
    patch = (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()
    return json.loads(
        (_DATA_ROOT / patch / "items.json").read_text(encoding="utf-8")
    )["data"]


def _plain(text: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", text or "")).strip()


class SourceTests(unittest.TestCase):
    """The live DDragon prose and the measured game data agree on 15."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ddragon = _ddragon_items()

    def test_live_ddragon_per_step_matches_the_game_data(self) -> None:
        for iid in DAWNCORE_IDS:
            with self.subTest(item_id=iid):
                found = _FIRST_LIGHT_AP.search(_plain(self.ddragon[iid]["description"]))
                self.assertIsNotNone(found)
                self.assertEqual(float(found.group(1)), CDRAGON_16_21_AP_PER_STEP[iid])

    def test_first_light_ap_class_is_exactly_the_three_dawncore_rows(self) -> None:
        # Tightest set, re-derived from the shipped prose: only Dawncore states
        # AP per base mana regen, so no other regen item may borrow the credit.
        hits = sorted(
            iid for iid, row in self.ddragon.items()
            if _FIRST_LIGHT_AP.search(_plain(row.get("description", "")))
        )
        self.assertEqual(hits, sorted(DAWNCORE_IDS))

    def test_expected_ap_is_the_r197_step_rule(self) -> None:
        regen = load_base_mana_regen_pct_table()
        self.assertTrue(regen)
        for iid in DAWNCORE_IDS:
            with self.subTest(item_id=iid):
                steps = math.floor(regen[iid] / 100.0)
                self.assertEqual(steps * CDRAGON_16_21_AP_PER_STEP[iid], EXPECTED_AP[iid])


class DataTests(unittest.TestCase):
    def test_rows_carry_the_first_light_ap(self) -> None:
        for iid in DAWNCORE_IDS:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS[iid]
                self.assertEqual(eff.bonus_ap_stacked, EXPECTED_AP[iid])
                # Promoted: the row now contributes offense, so it is no longer
                # a "no DPS effect" entry (the RM-94 Mejai's precedent).
                self.assertFalse(eff.defensive_only)
                self.assertEqual(eff.periodics, ())

    def test_helper_sums_the_ap(self) -> None:
        for iid in DAWNCORE_IDS:
            with self.subTest(item_id=iid):
                self.assertEqual(total_stacked_ap(collect_effects([iid])), EXPECTED_AP[iid])

    def test_unrelated_regen_items_carry_no_ap(self) -> None:
        # Redemption / Moonstone / Helia print base mana regen but have no
        # First Light clause; Mejai's and Innervating Locket keep their own pins.
        for iid in ("3107", "6617", "6620", "3504", "3222"):
            with self.subTest(item_id=iid):
                self.assertEqual(ITEM_EFFECTS[iid].bonus_ap_stacked, 0.0)
        self.assertEqual(ITEM_EFFECTS["3041"].bonus_ap_stacked, 25.0)
        self.assertEqual(ITEM_EFFECTS["447104"].bonus_ap_stacked, 175.0)

    def test_hsp_half_is_unchanged(self) -> None:
        # The R197 HSP lane did not move (2% / 3% / 2% per step).
        self.assertAlmostEqual(sum_scaling_hsp_pct(["6621"]), 0.02, places=12)
        self.assertAlmostEqual(sum_scaling_hsp_pct(["226621"]), 0.06, places=12)
        self.assertAlmostEqual(sum_scaling_hsp_pct(["326621"]), 0.02, places=12)


class EngineOutputTests(unittest.TestCase):
    """The enchanter scorer sees the AP: computed on a named champion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _ap(self, iid: str, mode: str, zero_first_light: bool) -> float:
        if zero_first_light:
            stub = replace(ITEM_EFFECTS[iid], bonus_ap_stacked=0.0)
            with mock.patch.dict(ITEM_EFFECTS, {iid: stub}):
                return compute_ability_hps(self.snap, "Soraka", 11,
                                           item_ids=[iid], mode=mode).ap
        return compute_ability_hps(self.snap, "Soraka", 11,
                                   item_ids=[iid], mode=mode).ap

    def test_soraka_ap_rises_by_the_first_light_ap(self) -> None:
        for iid, mode in (("6621", "SR"), ("326621", "ARAM"), ("226621", "ARENA")):
            with self.subTest(item_id=iid, mode=mode):
                with_ap = self._ap(iid, mode, zero_first_light=False)
                without = self._ap(iid, mode, zero_first_light=True)
                self.assertAlmostEqual(with_ap - without, EXPECTED_AP[iid], places=9)

    def test_soraka_heal_throughput_rises(self) -> None:
        stub = replace(ITEM_EFFECTS["6621"], bonus_ap_stacked=0.0)
        with mock.patch.dict(ITEM_EFFECTS, {"6621": stub}):
            before = compute_ability_hps(self.snap, "Soraka", 11, item_ids=["6621"])
        after = compute_ability_hps(self.snap, "Soraka", 11, item_ids=["6621"])
        self.assertGreater(after.total_ability_hps, before.total_ability_hps)


if __name__ == "__main__":
    unittest.main()
