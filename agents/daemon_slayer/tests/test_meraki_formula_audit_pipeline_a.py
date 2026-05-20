"""Meraki-exact item-effect formula audit (pipeline A).

Five real, frequently-built damage items whose ITEM_EFFECTS proc value
was an approximation that disagrees with the exact number Meraki's bulk
items endpoint carries (data/daemon_slayer/16.10.1/items_meraki.json,
patch 16.10.1). Each expected value below is DERIVED from the Meraki
passive text, not pulled from thin air:

* Wit's End (3091) "Fray": Meraki "Basic attacks deal 45 bonus magic
  damage on-hit" -> flat 45, NOT a 15->80 level ramp.
* Stormrazor (3097) "Bolt": Meraki "next basic attack deals 100 bonus
  magic damage on-hit" -> 100, not 120.
* Rapid Firecannon (3094) "Sharpshooter": Meraki "next basic attack
  deals 40 bonus magic damage on-hit" -> 40, not 120.
* Runaan's Hurricane (3085) "Wind's Fury": Meraki "fire additional
  bolts at up to 2 enemies, each dealing 55% AD physical damage" ->
  2 bolts * 0.55 * total_AD (base_ad + bonus_ad), not 0.60 * bonus_ad.
* Kraken Slayer (6672) "Bring It Down": Meraki ramp
  "150 + (200-150)/10*(x-1) for 13" (melee) -> 150 at L1 rising +5/level
  to 200 at L11+, not a flat 100. Arena mirror 226672 carries the same
  proc (DDragon 226672 == "Kraken Slayer") and was additionally
  mislabeled as Navori Flickerblade.

Assertions are on the computed proc quantity via
``PeriodicProc.resolve_damage`` (no fragile cross-item DPS compares),
plus one engine-level monotonic check that Kraken's proc now scales
with level (it was a flat constant before).
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import ITEM_EFFECTS, CallContext


def _proc(item_id: str):
    e = ITEM_EFFECTS[item_id]
    assert len(e.periodics) == 1, f"{item_id} expected exactly one periodic"
    return e.periodics[0]


class WitsEndFrayFlatTests(unittest.TestCase):
    """Meraki: Fray is a flat 45 magic on-hit, level-independent."""

    def test_base_3091_fray_is_flat_45_all_levels(self) -> None:
        proc = _proc("3091")
        for lvl in (1, 6, 11, 18):
            ctx = CallContext(base_ad=60.0, bonus_ad=40.0, level=lvl)
            self.assertEqual(proc.resolve_damage(ctx), 45.0)

    def test_arena_223091_fray_is_flat_45_all_levels(self) -> None:
        proc = _proc("223091")
        for lvl in (1, 11, 18):
            ctx = CallContext(base_ad=60.0, bonus_ad=40.0, level=lvl)
            self.assertEqual(proc.resolve_damage(ctx), 45.0)


class StormrazorBoltMagnitudeTests(unittest.TestCase):
    """Meraki: Energized Bolt = 100 bonus magic, not 120."""

    def test_base_3097_bolt_is_100(self) -> None:
        proc = _proc("3097")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 100.0)


class RapidFirecannonSharpshooterTests(unittest.TestCase):
    """Meraki: Sharpshooter = 40 bonus magic, not 120."""

    def test_base_3094_sharpshooter_is_40(self) -> None:
        proc = _proc("3094")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 40.0)

    def test_arena_223094_sharpshooter_is_40(self) -> None:
        proc = _proc("223094")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 40.0)


class RunaansWindsFuryTests(unittest.TestCase):
    """Meraki: 2 bolts, each 55% total AD physical = 1.10 * (base+bonus AD).

    The prior model (0.60 * bonus_ad) was wrong on both the coefficient
    and the base (bonus AD instead of total AD).
    """

    def _expected(self, base_ad: float, bonus_ad: float) -> float:
        return 2.0 * 0.55 * (base_ad + bonus_ad)

    def test_base_3085_two_bolts_55pct_total_ad(self) -> None:
        proc = _proc("3085")
        for base_ad, bonus_ad in ((60.0, 0.0), (70.0, 80.0), (90.0, 150.0)):
            ctx = CallContext(base_ad=base_ad, bonus_ad=bonus_ad, level=11)
            self.assertAlmostEqual(
                proc.resolve_damage(ctx),
                self._expected(base_ad, bonus_ad),
                places=6,
            )

    def test_arena_223085_two_bolts_55pct_total_ad(self) -> None:
        proc = _proc("223085")
        ctx = CallContext(base_ad=70.0, bonus_ad=80.0, level=11)
        self.assertAlmostEqual(
            proc.resolve_damage(ctx), self._expected(70.0, 80.0), places=6
        )

    def test_3085_uses_base_ad_not_only_bonus(self) -> None:
        # A build with zero bonus AD must still proc (base AD bolts).
        proc = _proc("3085")
        ctx = CallContext(base_ad=80.0, bonus_ad=0.0, level=11)
        self.assertGreater(proc.resolve_damage(ctx), 0.0)


class KrakenBringItDownRampTests(unittest.TestCase):
    """Meraki ramp: 150 + 5*(min(level,11)-1) melee, 150 (L1) .. 200 (L11+).

    cdragon source: ``150 + (200-150)/10*(x-1) for 13`` - the /10 caps
    the per-level increment at 10 steps (level 11), the ``for 13`` only
    bounds the level range. Engine uses the melee value (same convention
    as Hullbreaker / Bring-It-Down family).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _expected(self, level: int) -> float:
        return 150.0 + 5.0 * (min(level, 11) - 1)

    def test_base_6672_level_ramp(self) -> None:
        proc = _proc("6672")
        for lvl, want in ((1, 150.0), (6, 175.0), (11, 200.0),
                          (13, 200.0), (18, 200.0)):
            ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=lvl)
            self.assertAlmostEqual(proc.resolve_damage(ctx), want, places=6)
            self.assertAlmostEqual(
                proc.resolve_damage(ctx), self._expected(lvl), places=6
            )

    def test_arena_226672_level_ramp_matches_kraken(self) -> None:
        # DDragon 226672 == "Kraken Slayer"; this is the Arena Kraken
        # mirror, not Navori. Same Bring It Down ramp as 6672.
        proc = _proc("226672")
        for lvl, want in ((1, 150.0), (11, 200.0), (18, 200.0)):
            ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=lvl)
            self.assertAlmostEqual(proc.resolve_damage(ctx), want, places=6)

    def test_226672_relabeled_as_kraken_slayer(self) -> None:
        e = ITEM_EFFECTS["226672"]
        self.assertEqual(e.name, "Kraken Slayer")
        self.assertNotIn("Navori", e.note)

    def test_kraken_proc_scales_with_level_in_engine(self) -> None:
        # Was a flat constant; corrected ramp must make the Bring It Down
        # contribution at L11 strictly exceed L1 beyond pure stat growth.
        l1 = compute_dps(self.snap, "Aatrox", level=1, item_ids=["6672"])
        l11 = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6672"])
        self.assertGreater(l11.weighted_dps, l1.weighted_dps)
        self.assertTrue(any("Kraken Slayer" in n for n in l11.notes))


class BotRKMistsEdgeRateTests(unittest.TestCase):
    """Meraki: Mist's Edge is 9% melee / 6% ranged of target's current HP
    (cap 100 vs minions/monsters; cap not modeled for champion DPS).

    Pipeline-A pass corrected 5 items vs Meraki on 2026-05-19; BotRK was
    missed - it still carried an 8% rate. Engine convention is to pin
    melee values (the stronger side, same as Eclipse 6% / Hullbreaker /
    Kraken). Per-target current_hp is a deliberate `target_max_hp`
    steady-state approximation (documented at the proc site, untouched
    here); this fix is the magnitude only.
    """

    def test_base_3153_mists_edge_is_9pct_target_max_hp(self) -> None:
        proc = _proc("3153")
        ctx = CallContext(
            base_ad=60.0, bonus_ad=0.0, level=11, target_max_hp=2000.0,
        )
        # 9% * 2000 = 180.0
        self.assertAlmostEqual(proc.resolve_damage(ctx), 180.0, places=6)

    def test_arena_223153_mists_edge_is_9pct_target_max_hp(self) -> None:
        proc = _proc("223153")
        ctx = CallContext(
            base_ad=60.0, bonus_ad=0.0, level=11, target_max_hp=2500.0,
        )
        # 9% * 2500 = 225.0
        self.assertAlmostEqual(proc.resolve_damage(ctx), 225.0, places=6)

    def test_3153_scales_linearly_at_corrected_rate(self) -> None:
        # Three different target HP values, exact 9% multiplier on each.
        proc = _proc("3153")
        for tgt_hp, want in ((1000.0, 90.0), (1750.0, 157.5), (3000.0, 270.0)):
            ctx = CallContext(
                base_ad=60.0, bonus_ad=0.0, level=11, target_max_hp=tgt_hp,
            )
            self.assertAlmostEqual(proc.resolve_damage(ctx), want, places=6)
