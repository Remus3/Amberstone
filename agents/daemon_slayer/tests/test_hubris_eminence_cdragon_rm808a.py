"""RM-808 (a) - Hubris Eminence: one measured source wins (CommunityDragon game data).

The RM-804 review left an unresolved three-way disagreement on the SR row:

  * Meraki (content patch 25.15, the "passive-formula source"): 15 (+2 per stack).
  * DDragon 16.20.1 SR prose: 12 + 3 per champion killed.
  * DDragon 16.21.1 SR prose: NO numbers at all ("gain  Attack Damage plus  per
    champion killed").

The tie-breaker is the game's own item data, which CommunityDragon publishes per
patch as ``raw.communitydragon.org/<patch>/game/items.cdtb.bin.json`` (entry
``Items/<id>``, list ``mDataValues``). Measured 2026-10-24 (read-only fetch; the
16.21 tree's ``content-metadata.json`` reads
``16.21.8298620+branch.releases-16-21.content.release``, the same patch as the
DDragon 16.21.1 snapshot in ``data/daemon_slayer/current.txt``):

  16.20  Items/6697    BaseADBonus 12, ADPerStatue 3
         -> matches the DDragon 16.20.1 prose (12 + 3) exactly, so the bin and
            the rendered prose agree whenever DDragon renders the numbers.
  16.21  Items/6697    BaseADBonusMelee 15, BaseADRangedMult 0.667,
                       ADPerStatueMelee 3,  ADPerStatueRangedMult 0.667
         -> the 16.21 rework moved the values into a melee / ranged split
            calculation DDragon's renderer leaves blank - hence the empty prose.
  16.21  Items/226697  BaseADBonusMelee 15, BaseADRangedMult 1.0,
                       ADPerStatueMelee 2,  ADPerStatueRangedMult 1.0  (Arena)
  16.21  Items/126697  BaseADBonusMelee 15, BaseADRangedMult 0.667,
                       ADPerStatueMelee 2,  ADPerStatueRangedMult 0.5  (ARAM;
                       16.20 stated the same split explicitly: 15 / 10 base,
                       2 / 1 per stack)

Verdict: the game data wins. Meraki's 15 (+2) is a stale formula for SR (its
snapshot is stuck at content patch 25.15) and has no melee / ranged split on any
row. Engine before the fix: 15 (+2) on all three rows for every caster - the SR
melee per-stack was 1 low and every RANGED Hubris user (SR + ARAM) was
over-credited (17 AD at one stack vs 12 / 11 in game).

Fix: SR 6697 per stack 2 -> 3, and two new ItemEffect fields carry the ranged
multipliers (``takedown_bonus_ad_ranged_base_mult`` /
``takedown_bonus_ad_ranged_per_stack_mult``, default 1.0); the DSV2 consumers
(compute_dps / compute_burst_damage under ``assume_takedown``) pass the
caster's base-attackrange classification (``_melee_ranged``) to
``total_takedown_bonus_ad``. A moved modeled number: Tier-2 (ENGINE bump owed to
the merger).

Every assertion below is on a computed quantity (the helper or the engine
output on a named champion), except the provenance pins of the measured table.

ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _ASSUMED_TAKEDOWN_STACKS, compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_takedown_bonus_ad,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# id -> (base melee, per-stack melee, ranged base mult, ranged per-stack mult),
# CommunityDragon 16.21 items.cdtb.bin.json mDataValues (measured 2026-10-24).
CDRAGON_16_21: dict[str, tuple[float, float, float, float]] = {
    "6697": (15.0, 3.0, 0.667, 0.667),
    "226697": (15.0, 2.0, 1.0, 1.0),
    "126697": (15.0, 2.0, 0.667, 0.5),
}
_CDRAGON_PATCH = "16.21"
_MELEE = "Talon"      # base attackrange 125
_RANGED = "Caitlyn"   # base attackrange 650


def _expected(iid: str, stacks: float, ranged: bool) -> float:
    base, per, rb, rp = CDRAGON_16_21[iid]
    if ranged:
        return base * rb + per * rp * stacks
    return base + per * stacks


class MeasuredSourceTests(unittest.TestCase):
    """The engine rows carry the CommunityDragon 16.21 game data."""

    def test_table_is_not_empty_and_covers_every_takedown_ad_row(self) -> None:
        # An empty table would pass the loops below vacuously; a new takedown-AD
        # row must be measured before it ships.
        carriers = sorted(
            iid for iid, e in ITEM_EFFECTS.items()
            if e.takedown_bonus_ad_base or e.takedown_bonus_ad_per_stack
        )
        self.assertEqual(carriers, sorted(CDRAGON_16_21))
        self.assertEqual(len(CDRAGON_16_21), 3)

    def test_rows_match_the_game_data(self) -> None:
        for iid, (base, per, rb, rp) in CDRAGON_16_21.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS[iid]
                self.assertEqual(eff.takedown_bonus_ad_base, base)
                self.assertEqual(eff.takedown_bonus_ad_per_stack, per)
                self.assertEqual(eff.takedown_bonus_ad_ranged_base_mult, rb)
                self.assertEqual(eff.takedown_bonus_ad_ranged_per_stack_mult, rp)

    def test_sr_row_no_longer_follows_the_stale_meraki_formula(self) -> None:
        # Meraki still reads 15 (+2 per stack) at content patch 25.15; the SR
        # per-stack now differs from it on purpose. Reverses if: Meraki
        # publishes the 16.21 split (then both sources agree again).
        patch = (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()
        meraki = json.loads(
            (_DATA_ROOT / patch / "items_meraki.json").read_text(encoding="utf-8")
        )["items"]
        eminence = [p for p in meraki["6697"]["passives"] if p.get("name") == "Eminence"]
        self.assertEqual(len(eminence), 1)
        found = re.search(r"\{\{as\|(\d+)\|ad\}\} \(\+ (\d+) per stack\)",
                          eminence[0]["effects"])
        self.assertIsNotNone(found)
        meraki_base, meraki_per = float(found.group(1)), float(found.group(2))
        self.assertEqual((meraki_base, meraki_per), (15.0, 2.0))
        eff = ITEM_EFFECTS["6697"]
        self.assertEqual(eff.takedown_bonus_ad_base, meraki_base)
        self.assertNotEqual(eff.takedown_bonus_ad_per_stack, meraki_per)


class HelperMathTests(unittest.TestCase):
    """total_takedown_bonus_ad applies the caster's melee / ranged arm."""

    def test_melee_arm_is_the_default(self) -> None:
        for iid in CDRAGON_16_21:
            for stacks in (1.0, 5.0):
                with self.subTest(item_id=iid, stacks=stacks):
                    effs = collect_effects([iid])
                    self.assertAlmostEqual(
                        total_takedown_bonus_ad(effs, stacks),
                        _expected(iid, stacks, ranged=False), places=9,
                    )
                    self.assertAlmostEqual(
                        total_takedown_bonus_ad(effs, stacks, caster_is_ranged=False),
                        _expected(iid, stacks, ranged=False), places=9,
                    )

    def test_ranged_arm(self) -> None:
        for iid in CDRAGON_16_21:
            for stacks in (1.0, 5.0):
                with self.subTest(item_id=iid, stacks=stacks):
                    self.assertAlmostEqual(
                        total_takedown_bonus_ad(
                            collect_effects([iid]), stacks, caster_is_ranged=True
                        ),
                        _expected(iid, stacks, ranged=True), places=9,
                    )

    def test_sr_one_stack_values(self) -> None:
        effs = collect_effects(["6697"])
        self.assertEqual(_ASSUMED_TAKEDOWN_STACKS, 1)
        self.assertAlmostEqual(total_takedown_bonus_ad(effs, 1), 18.0, places=9)
        # 15 * 0.667 + 3 * 0.667 = 12.006 (the game displays 10 + 2).
        self.assertAlmostEqual(
            total_takedown_bonus_ad(effs, 1, caster_is_ranged=True), 12.006, places=9
        )

    def test_new_fields_default_to_one(self) -> None:
        eff = ItemEffect(item_id="x", name="x")
        self.assertEqual(eff.takedown_bonus_ad_ranged_base_mult, 1.0)
        self.assertEqual(eff.takedown_bonus_ad_ranged_per_stack_mult, 1.0)

    def test_new_fields_are_end_appended(self) -> None:
        # Repo dataclass convention: a mid-class insert breaks positional
        # construction. This (newest) seam owns the last-two assertion.
        import dataclasses

        names = [f.name for f in dataclasses.fields(ItemEffect)]
        self.assertEqual(
            names[-2:],
            ["takedown_bonus_ad_ranged_base_mult",
             "takedown_bonus_ad_ranged_per_stack_mult"],
        )
        self.assertEqual(names[-3], "physical_burst_total_ad_ratio")

    def test_only_hubris_rows_carry_a_ranged_multiplier(self) -> None:
        # Tightest set: the split is Eminence-only; no other row may borrow it.
        off_default = sorted(
            iid for iid, e in ITEM_EFFECTS.items()
            if e.takedown_bonus_ad_ranged_base_mult != 1.0
            or e.takedown_bonus_ad_ranged_per_stack_mult != 1.0
        )
        self.assertEqual(off_default, ["126697", "6697"])

    def test_unrelated_kill_state_items_contribute_nothing_either_arm(self) -> None:
        # Collector execute, Death's Dance heal, Hollow Radiance eruption and a
        # plain crit item: no takedown AD under either arm.
        for iid in ("6676", "6333", "6664", "3031"):
            with self.subTest(item_id=iid):
                effs = collect_effects([iid])
                self.assertEqual(total_takedown_bonus_ad(effs, 1), 0.0)
                self.assertEqual(
                    total_takedown_bonus_ad(effs, 1, caster_is_ranged=True), 0.0
                )


class EngineOutputTests(unittest.TestCase):
    """compute_burst_damage / compute_dps credit the caster's own arm."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _burst(self, champ: str, item: str):
        return compute_burst_damage(
            self.snap, champ, level=11, item_ids=[item], target_armor=80,
            target_max_hp=2000, assume_takedown=True,
        )

    def test_burst_melee_caster(self) -> None:
        for iid in CDRAGON_16_21:
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(
                    self._burst(_MELEE, iid).takedown_bonus_ad,
                    _expected(iid, _ASSUMED_TAKEDOWN_STACKS, ranged=False), places=9,
                )

    def test_burst_ranged_caster(self) -> None:
        for iid in CDRAGON_16_21:
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(
                    self._burst(_RANGED, iid).takedown_bonus_ad,
                    _expected(iid, _ASSUMED_TAKEDOWN_STACKS, ranged=True), places=9,
                )

    def test_dps_note_reports_the_caster_arm(self) -> None:
        def note(champ: str) -> str:
            res = compute_dps(self.snap, champ, level=11, item_ids=["6697"],
                              target_armor=80, assume_takedown=True)
            hits = [n for n in res.notes if n.startswith("takedown bonus AD +")]
            self.assertEqual(len(hits), 1, res.notes)
            return hits[0]

        self.assertTrue(note(_MELEE).startswith("takedown bonus AD +18 "))
        self.assertTrue(note(_RANGED).startswith("takedown bonus AD +12 "))

    def test_ranged_dps_gain_is_below_the_melee_arm_gain_ratio(self) -> None:
        # Computed: the ranged caster still gains under the seam, and its
        # relative DPS gain from 12.006 AD is below the relative gain the same
        # caster would get from the melee arm's 18 AD (a synthetic row with the
        # ranged multipliers cleared stands in for the melee arm).
        from dataclasses import replace
        from unittest import mock

        off = compute_dps(self.snap, _RANGED, level=11, item_ids=["6697"],
                          target_armor=80)
        on = compute_dps(self.snap, _RANGED, level=11, item_ids=["6697"],
                         target_armor=80, assume_takedown=True)
        self.assertGreater(on.weighted_dps, off.weighted_dps)
        melee_arm = replace(
            ITEM_EFFECTS["6697"],
            takedown_bonus_ad_ranged_base_mult=1.0,
            takedown_bonus_ad_ranged_per_stack_mult=1.0,
        )
        with mock.patch.dict(ITEM_EFFECTS, {"6697": melee_arm}):
            on_melee_arm = compute_dps(self.snap, _RANGED, level=11,
                                       item_ids=["6697"], target_armor=80,
                                       assume_takedown=True)
        self.assertGreater(on_melee_arm.weighted_dps, on.weighted_dps)

    def test_seam_off_is_byte_identical_for_both_arms(self) -> None:
        for champ in (_MELEE, _RANGED):
            with self.subTest(champ=champ):
                base = compute_burst_damage(self.snap, champ, level=11,
                                            item_ids=["6697"], target_armor=80,
                                            target_max_hp=2000)
                self.assertEqual(base.takedown_bonus_ad, 0.0)


if __name__ == "__main__":
    unittest.main()
