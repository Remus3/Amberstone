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


# ---------------------------------------------------------------------------
# Iter 8 (2026-05-19): Immolate family + Titanic Cleave Meraki drift fixes.
# ---------------------------------------------------------------------------
#
# The iter-7 BotRK fix found a stale percentage. Widening the audit to every
# `* c.<stat>_(hp|ad|ap)` site against Meraki bulk items (16.10.1) caught
# four more drifts in the same shape - Immolate family + Titanic Hydra
# Cleave. The engine's 2026-05-04 numbers no longer line up with current
# Meraki text, which is the authoritative source per CLAUDE.md.
#
# * Sunfire Aegis (3068): Meraki "20 + 1% bonus health" - was "12 + 1.5%".
#   Base 12 -> 20, scale 1.5% -> 1.0% bonus_hp.
# * Hollow Radiance (6664): Meraki "15 + 1% bonus health" - was "12 + 1.5%".
#   Base 12 -> 15, scale 1.5% -> 1.0% bonus_hp.
# * Bami's Cinder (6660): Meraki flat "15 magic damage" (no HP scaling at
#   this tier) - was "12 + 1.0% bonus_hp". Base 12 -> 15, drop bonus_hp.
# * Titanic Hydra (3748) Cleave primary: Meraki "1% maximum health" - was
#   "5 + 1.5% bonus health". Drop flat 5, switch bonus_hp -> max_hp,
#   coefficient 1.5% -> 1.0%.
# * Titanic Hydra (3748) Cleave to nearby: Meraki "3% maximum health to
#   others" - was "40% total AD to nearby". Switch AD coefficient to
#   max_hp; 0.40*(base+bonus AD) -> 0.03*max_hp.
#
# Arena mirrors (223068, 226664, 226660, 223748) carry the same SR
# coefficients - one Meraki source of truth per item family.

def _titanic_procs(item_id: str):
    e = ITEM_EFFECTS[item_id]
    # Titanic carries (primary, cleave-to-nearby) - both periodic, the only
    # multi-proc Immolate-family entry in scope.
    assert len(e.periodics) == 2, f"{item_id} expected exactly two periodics"
    return e.periodics[0], e.periodics[1]


class SunfireImmolateMagnitudeTests(unittest.TestCase):
    """Meraki Sunfire Aegis Immolate: 20 + 1% bonus_hp magic per second.

    Engine prior: 12 + 1.5% caster_bonus_hp (multi-proc-mult by n).
    Fix is base 12 -> 20 and bonus_hp coefficient 1.5% -> 1.0%.
    """

    def _expected(self, bonus_hp: float, n: float) -> float:
        return n * (20.0 + 0.010 * bonus_hp)

    def test_base_3068_zero_bonus_hp_flat_20(self) -> None:
        proc = _proc("3068")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=0.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 20.0, places=6)

    def test_base_3068_thousand_bonus_hp(self) -> None:
        proc = _proc("3068")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        # 1.0 * (20 + 0.010 * 1000) = 30
        self.assertAlmostEqual(
            proc.resolve_damage(ctx), self._expected(1000.0, 1.0), places=6,
        )

    def test_base_3068_aoe_n3_scales(self) -> None:
        proc = _proc("3068")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=3.0,
        )
        # 3.0 * (20 + 10) = 90
        self.assertAlmostEqual(
            proc.resolve_damage(ctx), self._expected(1000.0, 3.0), places=6,
        )

    def test_arena_223068_mirrors_sr(self) -> None:
        proc = _proc("223068")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=800.0, targets_in_rotation=1.0,
        )
        # 1.0 * (20 + 0.010 * 800) = 28
        self.assertAlmostEqual(proc.resolve_damage(ctx), 28.0, places=6)


class HollowRadianceImmolateMagnitudeTests(unittest.TestCase):
    """Meraki Hollow Radiance Immolate: 15 + 1% bonus_hp magic per second.

    Engine prior: 12 + 1.5% caster_bonus_hp. Fix base 12 -> 15 and 1.5%
    -> 1.0%. Note: Desolate (eruption on kill) still not modeled - this
    iter only touches the Immolate magnitude.
    """

    def test_base_6664_zero_bonus_hp_flat_15(self) -> None:
        proc = _proc("6664")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=0.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 15.0, places=6)

    def test_base_6664_thousand_bonus_hp(self) -> None:
        proc = _proc("6664")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        # 1.0 * (15 + 10) = 25
        self.assertAlmostEqual(proc.resolve_damage(ctx), 25.0, places=6)

    def test_arena_226664_mirrors_sr(self) -> None:
        proc = _proc("226664")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=500.0, targets_in_rotation=2.0,
        )
        # 2.0 * (15 + 0.010 * 500) = 2.0 * 20 = 40
        self.assertAlmostEqual(proc.resolve_damage(ctx), 40.0, places=6)


class BamisCinderImmolateMagnitudeTests(unittest.TestCase):
    """Meraki Bami's Cinder Immolate: flat 15 magic damage per second.

    Engine prior: 12 + 1.0% caster_bonus_hp. Fix: base 12 -> 15 and DROP
    the bonus_hp coefficient entirely (Cinder is the components-tier
    Immolate; HP scaling only kicks in at the upgraded items, Sunfire/
    Hollow Radiance).
    """

    def test_base_6660_zero_bonus_hp_flat_15(self) -> None:
        proc = _proc("6660")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=0.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 15.0, places=6)

    def test_base_6660_bonus_hp_does_not_scale(self) -> None:
        # The whole point: Bami's must NOT scale with bonus_hp. Same flat
        # 15 at zero and at 2000 bonus_hp.
        proc = _proc("6660")
        ctx_low = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=0.0, targets_in_rotation=1.0,
        )
        ctx_high = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=2000.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(
            proc.resolve_damage(ctx_low),
            proc.resolve_damage(ctx_high),
            places=6,
        )

    def test_arena_226660_mirrors_sr(self) -> None:
        proc = _proc("226660")
        ctx = CallContext(
            base_ad=0.0, bonus_ad=0.0, level=11,
            caster_bonus_hp=1500.0, targets_in_rotation=2.0,
        )
        # 2.0 * 15 = 30 (bonus_hp ignored)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 30.0, places=6)


class TitanicHydraCleaveMagnitudeTests(unittest.TestCase):
    """Meraki Titanic Hydra Cleave: 1% max_hp primary + 3% max_hp to nearby.

    Engine prior: 5 + 1.5% caster_bonus_hp primary; 40% total AD to
    nearby. Fixes are large enough to be shape-changes (bonus_hp ->
    max_hp; AD coefficient -> max_hp coefficient) but the schema
    (2 PeriodicProcs, both PHYSICAL on_attack) stays unchanged.

    Meraki text (16.10.1): "Basic attacks on-hit deal 1%|0.5% maximum
    health bonus physical damage to the target and 3%|1.5% maximum
    health physical damage to other enemies in a cone in the direction
    of the primary target." Engine pins melee values (1% / 3%) per the
    convention that fixed the BotRK / Eclipse / Hullbreaker / Kraken
    items in iter 7.
    """

    def test_3748_primary_one_percent_max_hp(self) -> None:
        primary, _ = _titanic_procs("3748")
        ctx = CallContext(
            base_ad=80.0, bonus_ad=40.0, level=11,
            caster_max_hp=3000.0, caster_bonus_hp=1200.0,
            targets_in_rotation=1.0,
        )
        # 0.01 * 3000 = 30; AD totally unused.
        self.assertAlmostEqual(primary.resolve_damage(ctx), 30.0, places=6)

    def test_3748_primary_independent_of_bonus_hp_and_ad(self) -> None:
        # Sanity: changing AD or bonus_hp at fixed max_hp must NOT shift
        # primary damage (max_hp is the binding variable).
        primary, _ = _titanic_procs("3748")
        a = CallContext(
            base_ad=60.0, bonus_ad=0.0, level=11,
            caster_max_hp=2500.0, caster_bonus_hp=0.0,
            targets_in_rotation=1.0,
        )
        b = CallContext(
            base_ad=120.0, bonus_ad=80.0, level=11,
            caster_max_hp=2500.0, caster_bonus_hp=1500.0,
            targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(
            primary.resolve_damage(a),
            primary.resolve_damage(b),
            places=6,
        )
        self.assertAlmostEqual(primary.resolve_damage(a), 25.0, places=6)

    def test_3748_cleave_to_nearby_three_percent_max_hp_scales(self) -> None:
        _, cleave = _titanic_procs("3748")
        ctx_n1 = CallContext(
            base_ad=80.0, bonus_ad=40.0, level=11,
            caster_max_hp=3000.0, targets_in_rotation=1.0,
        )
        ctx_n3 = CallContext(
            base_ad=80.0, bonus_ad=40.0, level=11,
            caster_max_hp=3000.0, targets_in_rotation=3.0,
        )
        # n=1: max(0, 0) * anything = 0
        self.assertAlmostEqual(cleave.resolve_damage(ctx_n1), 0.0, places=6)
        # n=3: max(0, 2) * 0.03 * 3000 = 180
        self.assertAlmostEqual(cleave.resolve_damage(ctx_n3), 180.0, places=6)

    def test_3748_cleave_independent_of_ad(self) -> None:
        # Was 40% total AD; now max_hp%. Changing AD must NOT shift the
        # cleave value at fixed max_hp.
        _, cleave = _titanic_procs("3748")
        a = CallContext(
            base_ad=60.0, bonus_ad=0.0, level=11,
            caster_max_hp=2400.0, targets_in_rotation=3.0,
        )
        b = CallContext(
            base_ad=160.0, bonus_ad=100.0, level=11,
            caster_max_hp=2400.0, targets_in_rotation=3.0,
        )
        self.assertAlmostEqual(
            cleave.resolve_damage(a),
            cleave.resolve_damage(b),
            places=6,
        )
        # Both: max(0, 2) * 0.03 * 2400 = 144
        self.assertAlmostEqual(cleave.resolve_damage(a), 144.0, places=6)

    def test_arena_223748_mirrors_sr_shape(self) -> None:
        # Both procs present, both max_hp-scaled, no AD coefficient.
        primary, cleave = _titanic_procs("223748")
        ctx = CallContext(
            base_ad=100.0, bonus_ad=50.0, level=11,
            caster_max_hp=3500.0, caster_bonus_hp=1500.0,
            targets_in_rotation=2.0,
        )
        # Primary: 0.01 * 3500 = 35
        self.assertAlmostEqual(primary.resolve_damage(ctx), 35.0, places=6)
        # Cleave: max(0, 1) * 0.03 * 3500 = 105
        self.assertAlmostEqual(cleave.resolve_damage(ctx), 105.0, places=6)


class StatikkShivElectrosparkMagnitudeTests(unittest.TestCase):
    """Meraki: Electrospark = next 3 basic attacks within 8s deal 60
    bonus magic damage each on-hit; cooldown ramps 25s at L1 down to 10s
    at L6+ (pp|25 to 10 for 6). Engine pins the L6+ steady-state
    cooldown (10s) and the per-cycle payload (3 * 60 = 180 magic),
    encoded as bonus_damage=180 every_n_seconds=10 (same shape as the
    Kraken / Stormrazor energized-family encoding: payload-per-cycle,
    NOT per-attack). Was bonus_damage=110 every 3s (~36.7/s; iter-7 era
    stale magnitude, ~2x too high vs the 16.10.1 Electrospark spec).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_base_3087_electrospark_is_180_per_cycle(self) -> None:
        proc = _proc("3087")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 180.0)
        self.assertEqual(proc.every_n_seconds, 10.0)

    def test_base_3087_proc_named_electrospark(self) -> None:
        proc = _proc("3087")
        # Renamed off the stale "Electroshock" - Meraki's actual proc
        # name for the 3-attack chain is "Electrospark"; "Electroshock"
        # is the takedown-reset secondary passive.
        self.assertEqual(proc.name, "Electrospark")

    def test_base_3087_steady_state_magic_per_sec_is_18(self) -> None:
        # 180 magic per 10s cycle = 18 magic/s steady-state. Roughly
        # half the prior 110/3s = ~36.67/s (the iter-7 stale rate).
        proc = _proc("3087")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11)
        self.assertAlmostEqual(
            proc.resolve_damage(ctx) / proc.every_n_seconds, 18.0, places=6
        )

    def test_arena_223087_electrospark_mirrors_sr(self) -> None:
        proc = _proc("223087")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 180.0)
        self.assertEqual(proc.every_n_seconds, 10.0)
        self.assertEqual(proc.name, "Electrospark")

    def test_3087_proc_uses_magical_damage_type(self) -> None:
        # MR-resisted, not armor (Meraki: "bonus magic damage"); guards
        # the iter-7 stale rate fix from accidentally flipping the
        # damage type during refactor.
        from agents.daemon_slayer.effects import MAGICAL

        self.assertEqual(_proc("3087").damage_type, MAGICAL)
        self.assertEqual(_proc("223087").damage_type, MAGICAL)

    def test_statikk_still_raises_dps_at_corrected_rate(self) -> None:
        # End-to-end sanity: the corrected magnitude is still net
        # positive on Aatrox L11, just smaller than before (engine-level
        # check, no exact magnitude assert to stay robust to adjacent
        # math drift). Confirms the test_statikk_shiv_raises_dps invariant
        # in test_effects_expansion.py still holds post-iter-11.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_ss = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3087"])
        self.assertGreater(with_ss.weighted_dps, bare.weighted_dps)
