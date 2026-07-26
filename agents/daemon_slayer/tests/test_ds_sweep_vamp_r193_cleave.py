"""R193 hydra_cleave coefficient drift guard - Ravenous Hydra (3074).

Ground truth: Meraki bulk ``data/daemon_slayer/16.14.1/items_meraki.json``
``items.3074.passives[Cleave].effects`` reads ``{{rd|40% AD|20% AD}}``, i.e.
40 percent total AD melee / 20 percent ranged. The same byte-identical
effects text backs Stridebreaker (6631) and Profane Hydra (6698), which
were already modelled at 0.40 - so Ravenous reading 0.35 was stale-patch
drift, not a deliberate calibration.

The family pins the MELEE value (0.40) for every member. There is no
ranged split in the model: a ranged-carry hydra is off-meta and the
DPS engine has no ranged/melee discriminator on the proc seam, so the
melee pin is the family doctrine and this guard asserts it uniformly.

Two guards, so a future single-item edit cannot desync the family again:
  1. absolute magnitude - each member resolves 40 percent total AD per
     extra target in the rotation;
  2. cross-member parity - every hydra_cleave AD carrier (SR plus its
     Arena mirror) resolves the SAME magnitude at one fixed CallContext.

Titanic Hydra (3748 / 223748) is deliberately excluded: its Cleave is a
caster-bonus-HP formula, not a total-AD one, so it shares the family key
but not the coefficient.
"""

import unittest

from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    CallContext,
    PHYSICAL,
)

# Total AD = 150, n=3 -> cleave lands on 2 other enemies.
# Expected at the family melee pin: 2 * 0.40 * 150 = 120.0.
_TOTAL_AD = 150.0
_EXTRA_TARGETS = 2.0
_MELEE_PIN = 0.40
_EXPECTED = _EXTRA_TARGETS * _MELEE_PIN * _TOTAL_AD

# SR ids and their Arena mirrors. Titanic (3748/223748) excluded - see
# module docstring.
_SR_AD_CLEAVERS = ("3074", "6631", "6698")
_ARENA_AD_CLEAVERS = ("223074", "226631", "226698")


def _multi_target_ctx() -> CallContext:
    return CallContext(
        base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=3.0,
    )


def _single_target_ctx() -> CallContext:
    return CallContext(
        base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=1.0,
    )


class RavenousHydraCleaveCoefficientR193Tests(unittest.TestCase):
    """Ravenous Hydra SR 3074 + Arena mirror 223074 at the Meraki value."""

    def test_sr_ravenous_cleave_is_forty_percent_total_ad(self) -> None:
        proc = ITEM_EFFECTS["3074"].periodics[0]
        self.assertEqual(proc.name, "Cleave")
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertAlmostEqual(
            proc.resolve_damage(_multi_target_ctx()), _EXPECTED, places=3,
        )

    def test_arena_mirror_ravenous_cleave_is_forty_percent_total_ad(self) -> None:
        proc = ITEM_EFFECTS["223074"].periodics[0]
        self.assertEqual(proc.name, "Cleave")
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertAlmostEqual(
            proc.resolve_damage(_multi_target_ctx()), _EXPECTED, places=3,
        )

    def test_ravenous_notes_do_not_advertise_the_stale_coefficient(self) -> None:
        # The note strings are read by the DS preview surface, so a stale
        # "35%" there is user-visible drift even once the math is right.
        for item_id in ("3074", "223074"):
            note = ITEM_EFFECTS[item_id].note
            self.assertNotIn("35%", note, f"{item_id} note still cites 35%")
            self.assertIn("40%", note, f"{item_id} note omits the 40% pin")


class HydraCleaveFamilyParityR193Tests(unittest.TestCase):
    """No family member may drift alone - parity is asserted, not assumed."""

    def test_sr_family_members_resolve_identical_magnitude(self) -> None:
        ctx = _multi_target_ctx()
        magnitudes = {
            item_id: ITEM_EFFECTS[item_id].periodics[0].resolve_damage(ctx)
            for item_id in _SR_AD_CLEAVERS
        }
        for item_id, dmg in magnitudes.items():
            self.assertAlmostEqual(
                dmg, _EXPECTED, places=3,
                msg=f"{item_id} cleave desynced from the family melee pin",
            )
        self.assertEqual(len(set(round(v, 6) for v in magnitudes.values())), 1)

    def test_arena_mirrors_match_their_sr_twins(self) -> None:
        ctx = _multi_target_ctx()
        for sr_id, arena_id in zip(_SR_AD_CLEAVERS, _ARENA_AD_CLEAVERS):
            self.assertAlmostEqual(
                ITEM_EFFECTS[arena_id].periodics[0].resolve_damage(ctx),
                ITEM_EFFECTS[sr_id].periodics[0].resolve_damage(ctx),
                places=3,
                msg=f"Arena {arena_id} desynced from SR {sr_id}",
            )

    def test_family_shares_the_unique_passive_key(self) -> None:
        # Parity of magnitude only matters because collect_effects dedups
        # on this key - a member that lost the key would double-count.
        for item_id in _SR_AD_CLEAVERS + _ARENA_AD_CLEAVERS:
            self.assertEqual(
                ITEM_EFFECTS[item_id].unique_passive_key, "hydra_cleave",
                msg=f"{item_id} dropped the hydra_cleave family key",
            )

    def test_family_contributes_zero_at_single_target(self) -> None:
        # max(0, n-1) keeps the historic all-n=1 rotation shape intact -
        # the coefficient lift must not leak into single-target DPS.
        ctx = _single_target_ctx()
        for item_id in _SR_AD_CLEAVERS + _ARENA_AD_CLEAVERS:
            self.assertAlmostEqual(
                ITEM_EFFECTS[item_id].periodics[0].resolve_damage(ctx),
                0.0, places=6,
                msg=f"{item_id} cleave is non-zero at one target",
            )


if __name__ == "__main__":
    unittest.main()
