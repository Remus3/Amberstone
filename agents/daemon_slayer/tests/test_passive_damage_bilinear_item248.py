"""GAP-2 bilinear AP-on-HP schema lift (item 248).

The bilinear schema lift adds the ONE passive-damage form a single linear
``_SCALING_TARGETS`` field cannot express: an AP-scaled %-of-HP term, i.e. a
PRODUCT of two ctx stats (``ctx[ap] * ctx[target_hp]``). Covered here:

  * ``_per_100(pct, per_attr, of_attr)`` converts Riot's "X% per 100 {a} of
    {b}" notation to a flat ``(factor, a, b)`` term (factor = pct / 10000).
  * ``DamageBlock.bilinear_terms`` defaults ``()`` so every existing block is
    byte-identical; ``ability_dps._evaluate_block`` adds each term as
    ``factor * ctx[a] * ctx[b]`` AFTER the per-rank linear terms.
  * ``has_damage_scaling`` is True for a bilinear-only block.
  * The 4 SEEDED entries (Gwen / Aurora / Lillia / Renata P) evaluate to the
    verbatim 16.11.1 effects_descriptions value at known (level, AP, max HP),
    hand-computed (NOT a circular re-derive).
  * Default load (flag OFF) is BYTE-IDENTICAL: the 4 forms stay
    parse_status == "no_damage" with no synthetic block.
  * Kai'Sa P stays STAGED (per-stack ramp, absent from the registry).

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    _per_100,
    to_damage_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot, DamageBlock
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _evaluate_block,
    _select_blocks,
    rank_at_level,
)

_PATCH = "16.11.1"

_BILINEAR_CHAMPS = ("Gwen", "Aurora", "Lillia", "Renata")


def _ctx(*, ap: float = 0.0, target_max_hp: float = 2500.0) -> AbilityContext:
    base_ad = 60.0
    return AbilityContext.from_build(
        stats={"ad": base_ad, "ap": ap, "hp": 1800.0},
        base_stats={"ad": base_ad, "hp": 1800.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=target_max_hp,
        target_bonus_hp=0.0,
    )


class Per100ConversionTests(unittest.TestCase):
    def test_gwen_factor(self) -> None:
        self.assertEqual(_per_100(0.55, "ap", "target_max_hp"), (5.5e-05, "ap", "target_max_hp"))

    def test_per_100_is_pct_over_10000(self) -> None:
        # "2% per 100 AP" -> (2/100) * (1/100) = 0.0002
        self.assertEqual(_per_100(2.0, "ap", "target_max_hp")[0], 0.0002)

    def test_attrs_passthrough(self) -> None:
        f = _per_100(6.0, "ap", "target_missing_hp")
        self.assertEqual(f[1], "ap")
        self.assertEqual(f[2], "target_missing_hp")


class DamageBlockBilinearFieldTests(unittest.TestCase):
    def test_default_empty_byte_identical(self) -> None:
        # a block with no bilinear term keeps the old default - existing blocks
        # are byte-identical.
        b = DamageBlock(attribute="x", attribute_kind="damage", base=(10.0,))
        self.assertEqual(b.bilinear_terms, ())

    def test_has_damage_scaling_for_bilinear_only(self) -> None:
        b = DamageBlock(
            attribute="x",
            attribute_kind="damage",
            bilinear_terms=((5.5e-05, "ap", "target_max_hp"),),
        )
        self.assertTrue(b.has_damage_scaling())

    def test_evaluate_bilinear_product(self) -> None:
        # 0.000055 * ap * target_max_hp ; ap=200, thp=2500 -> 27.5
        b = DamageBlock(
            attribute="x",
            attribute_kind="damage",
            base=(0.0,),
            bilinear_terms=((5.5e-05, "ap", "target_max_hp"),),
        )
        self.assertAlmostEqual(_evaluate_block(b, 0, _ctx(ap=200.0, target_max_hp=2500.0)), 27.5, places=6)

    def test_evaluate_linear_plus_bilinear(self) -> None:
        # 1% max HP (linear) + 0.55% per 100 AP (bilinear).
        b = DamageBlock(
            attribute="x",
            attribute_kind="damage",
            base=(0.0,),
            target_max_hp_pct=(1.0,),
            bilinear_terms=((5.5e-05, "ap", "target_max_hp"),),
        )
        # ap=200, thp=2500 -> 25 (linear 1%) + 27.5 (bilinear) = 52.5
        self.assertAlmostEqual(_evaluate_block(b, 0, _ctx(ap=200.0, target_max_hp=2500.0)), 52.5, places=6)

    def test_zero_factor_skipped(self) -> None:
        b = DamageBlock(
            attribute="x",
            attribute_kind="damage",
            base=(7.0,),
            bilinear_terms=((0.0, "ap", "target_max_hp"),),
        )
        self.assertAlmostEqual(_evaluate_block(b, 0, _ctx(ap=200.0)), 7.0, places=6)


class RegistrySeedTests(unittest.TestCase):
    def test_all_four_seeded(self) -> None:
        for cid in _BILINEAR_CHAMPS:
            self.assertIn((cid, "P", 0), _PASSIVE_DAMAGE_OVERRIDES, f"{cid} P must be seeded")

    def test_each_builds_damage_block_with_bilinear(self) -> None:
        for cid in _BILINEAR_CHAMPS:
            b = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[(cid, "P", 0)])
            self.assertEqual(b.attribute_kind, "damage")
            self.assertTrue(b.bilinear_terms, f"{cid} block must carry a bilinear term")
            self.assertEqual(b.bilinear_terms[0][1], "ap")
            self.assertEqual(b.bilinear_terms[0][2], "target_max_hp")

    def test_gwen_terms(self) -> None:
        b = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("Gwen", "P", 0)])
        self.assertEqual(b.target_max_hp_pct, (1.0,))
        self.assertEqual(b.bilinear_terms, ((5.5e-05, "ap", "target_max_hp"),))

    def test_renata_linear_is_level_scaled(self) -> None:
        b = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("Renata", "P", 0)])
        self.assertEqual(len(b.target_max_hp_pct), 18)
        self.assertEqual(b.target_max_hp_pct[0], 1.0)
        self.assertEqual(b.target_max_hp_pct[-1], 2.0)

    def test_kaisa_stays_staged(self) -> None:
        self.assertNotIn(("Kaisa", "P", 0), _PASSIVE_DAMAGE_OVERRIDES)


class ByteIdenticalDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH)

    def test_forms_stay_no_damage(self) -> None:
        for cid in _BILINEAR_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            self.assertEqual(form.parse_status, "no_damage", f"{cid} P must stay no_damage flag OFF")

    def test_forms_have_no_damage_block(self) -> None:
        for cid in _BILINEAR_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(dmg, [], f"{cid} P must have NO damage block flag OFF")


class InjectOnValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH, apply_passive_damage=True)

    def _val(self, cid: str, level: int, *, ap: float = 0.0, target_max_hp: float = 2500.0) -> float:
        form = self.snap.get_abilities(cid)["P"][0]
        return _select_blocks(
            form.damage_blocks,
            rank_at_level("P", level),
            _ctx(ap=ap, target_max_hp=target_max_hp),
            "first",
        )

    def test_each_gains_one_block(self) -> None:
        for cid in _BILINEAR_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(len(dmg), 1, f"{cid} should gain exactly 1 synthetic block")

    def test_gwen_one_pct_plus_bilinear(self) -> None:
        # 1% (+ 0.55% per 100 AP) max HP. AP200 thp2500 -> 1.1% extra = 2.1% of 2500 = 52.5
        self.assertAlmostEqual(self._val("Gwen", 9, ap=200.0, target_max_hp=2500.0), 52.5, places=4)
        # AP0 -> pure 1% = 25
        self.assertAlmostEqual(self._val("Gwen", 1, ap=0.0, target_max_hp=2500.0), 25.0, places=4)

    def test_aurora_two_and_half_pct_plus_bilinear(self) -> None:
        # 2.5% (+ 2% per 100 AP) max HP. AP100 thp2000 -> (2.5 + 2*1)% = 4.5% of 2000 = 90
        self.assertAlmostEqual(self._val("Aurora", 9, ap=100.0, target_max_hp=2000.0), 90.0, places=4)

    def test_lillia_five_pct_plus_bilinear(self) -> None:
        # 5% (+ 1.25% per 100 AP) max HP. AP200 thp3000 -> (5 + 2.5)% = 7.5% of 3000 = 225
        self.assertAlmostEqual(self._val("Lillia", 9, ap=200.0, target_max_hp=3000.0), 225.0, places=4)

    def test_renata_level_scaled_plus_bilinear(self) -> None:
        # L1 = 1% linear (+ 2% per 100 AP). AP100 thp2000 -> (1 + 2)% = 3% of 2000 = 60
        self.assertAlmostEqual(self._val("Renata", 1, ap=100.0, target_max_hp=2000.0), 60.0, places=4)
        # L18 = 2% linear, AP0 -> 2% of 2000 = 40
        self.assertAlmostEqual(self._val("Renata", 18, ap=0.0, target_max_hp=2000.0), 40.0, places=4)

    def test_bilinear_is_zero_with_no_ap(self) -> None:
        # the bilinear term vanishes at AP=0, leaving only the linear %max HP.
        # Aurora 2.5% of 2000 = 50.
        self.assertAlmostEqual(self._val("Aurora", 9, ap=0.0, target_max_hp=2000.0), 50.0, places=4)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer._passive_damage_overrides as mod

        with open(mod.__file__, "rb") as fh:
            fh.read().decode("ascii")  # raises on any non-ASCII byte


if __name__ == "__main__":
    unittest.main()
