"""R50 - K'Sante P All Out Bonus bilinear caster-resist seam.

The item-255 K'Sante entry seeds the BASE Dauntless Instinct mark consume
(12 + 1% : 2% by level of target max HP). Its "All Out Bonus" - active only
while K'Sante is in the R-empowered All Out state - was the documented OMIT in
``_passive_damage_overrides`` (reject notes: a bilinear caster_bonus_resist x
target_max_hp PRODUCT gated on the All Out state). R50 seeds it as a SEPARATE
default-OFF seam so the base entry stays byte-identical (item-255's 51.706
magnitude is untouched, and the ``_PASSIVE_DAMAGE_OVERRIDES`` prior-entry
invariants are untouched).

Verbatim 16.13.1 effects_descriptions (champion_abilities.json KSante P):
  "All Out Bonus: K'Sante's basic attacks and ability damage, as well as
   Dauntless Instinct's mark consumption, are empowered to deal bonus physical
   damage equal to 1% (+ 1% per 100 bonus armor) (+ 1% per 100 bonus magic
   resistance) of the target's maximum health."

Model: target_max_hp_pct 1.0 (the flat 1%) + two bilinear terms
(``_per_100(1.0, caster_bonus_armor, target_max_hp)`` + the caster_bonus_mr
sibling), gated by conditional_probability 0.5 (the documented amortized
All-Out-uptime firing midpoint, operator-tunable - the same convention as the
Brand / Sejuani gates). Injected only when the NEW ``apply_all_out_bonus`` load
flag is True; default OFF = byte-identical.

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import (
    _ALL_OUT_BONUS_OVERRIDES,
    _PASSIVE_DAMAGE_OVERRIDES,
    _per_100,
    to_damage_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _evaluate_block,
    rank_at_level,
)

_PATCH = "16.13.1"
_KEY = ("KSante", "P", 0)


def _ctx(*, bonus_armor: float = 0.0, bonus_mr: float = 0.0,
         target_max_hp: float = 2500.0) -> AbilityContext:
    # base_stats carries no armor/mr, so caster_bonus_{armor,mr} == the stats value.
    return AbilityContext.from_build(
        stats={"ad": 60.0, "ap": 0.0, "hp": 1800.0, "armor": bonus_armor, "mr": bonus_mr},
        base_stats={"ad": 60.0, "hp": 1800.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=target_max_hp,
        target_bonus_hp=0.0,
    )


class RegistryShapeTests(unittest.TestCase):
    def test_seeded_in_separate_registry(self) -> None:
        self.assertIn(_KEY, _ALL_OUT_BONUS_OVERRIDES)

    def test_base_entry_untouched(self) -> None:
        # The item-255 base mark-consume entry keeps conditional_probability 1.0
        # (the All Out bonus must NOT leak into the base registry).
        self.assertEqual(_PASSIVE_DAMAGE_OVERRIDES[_KEY].conditional_probability, 1.0)

    def test_entry_carries_two_resist_bilinears(self) -> None:
        e = _ALL_OUT_BONUS_OVERRIDES[_KEY]
        self.assertEqual(e.conditional_probability, 0.5)
        self.assertEqual(e.target_max_hp_pct, 1.0)
        self.assertEqual(e.damage_type, "PHYSICAL")
        attrs = {(a, b) for (_f, a, b) in e.bilinear_terms}
        self.assertEqual(
            attrs,
            {("caster_bonus_armor", "target_max_hp"),
             ("caster_bonus_mr", "target_max_hp")},
        )

    def test_per_100_factor(self) -> None:
        f = _per_100(1.0, "caster_bonus_armor", "target_max_hp")
        self.assertAlmostEqual(f[0], 0.0001, places=8)
        self.assertEqual((f[1], f[2]), ("caster_bonus_armor", "target_max_hp"))


class MagnitudeTests(unittest.TestCase):
    def _val(self, **ctx_kw: float) -> float:
        block = to_damage_block(_ALL_OUT_BONUS_OVERRIDES[_KEY])
        return _evaluate_block(block, rank_at_level("P", 11), _ctx(**ctx_kw))

    def test_zero_resist_is_half_pct(self) -> None:
        # 0.5 gate * 1% * 2500 = 12.5 (both bilinear terms vanish at 0 resist).
        self.assertAlmostEqual(self._val(), 12.5, places=4)

    def test_full_build_resists(self) -> None:
        # linear 0.5%*2500=12.5 + armor 0.00005*200*2500=25 + mr 0.00005*100*2500=12.5 = 50.
        self.assertAlmostEqual(self._val(bonus_armor=200.0, bonus_mr=100.0), 50.0, places=4)

    def test_armor_only_is_linear_in_resist(self) -> None:
        # 12.5 + 0.00005*300*2500 = 12.5 + 37.5 = 50.0.
        self.assertAlmostEqual(self._val(bonus_armor=300.0), 50.0, places=4)


class SnapshotSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.off = AbilitiesSnapshot.load(patch=_PATCH)
        cls.pd = AbilitiesSnapshot.load(patch=_PATCH, apply_passive_damage=True)
        cls.ao = AbilitiesSnapshot.load(patch=_PATCH, apply_all_out_bonus=True)
        cls.both = AbilitiesSnapshot.load(
            patch=_PATCH, apply_passive_damage=True, apply_all_out_bonus=True)

    def _dmg_blocks(self, snap):
        form = snap.get_abilities("KSante")["P"][0]
        return [b for b in form.damage_blocks if b.attribute_kind == "damage"]

    def test_default_off_byte_identical(self) -> None:
        self.assertEqual(self._dmg_blocks(self.off), [])

    def test_passive_damage_flag_yields_only_base(self) -> None:
        # apply_passive_damage alone injects exactly the item-255 base block (1).
        self.assertEqual(len(self._dmg_blocks(self.pd)), 1)

    def test_all_out_flag_injects_one(self) -> None:
        self.assertEqual(len(self._dmg_blocks(self.ao)), 1)

    def test_both_flags_inject_two(self) -> None:
        self.assertEqual(len(self._dmg_blocks(self.both)), 2)

    def test_all_out_block_carries_bilinear(self) -> None:
        blocks = self._dmg_blocks(self.ao)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].bilinear_terms)


class OnlyKsanteSeededTests(unittest.TestCase):
    def test_registry_is_ksante_only(self) -> None:
        self.assertEqual(set(_ALL_OUT_BONUS_OVERRIDES), {_KEY})


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_ascii(self) -> None:
        import agents.daemon_slayer._passive_damage_overrides as m
        from pathlib import Path
        for p in (Path(m.__file__), Path(__file__)):
            self.assertEqual([x for x in p.read_bytes() if x > 0x7F], [], f"non-ASCII in {p.name}")


if __name__ == "__main__":
    unittest.main()
