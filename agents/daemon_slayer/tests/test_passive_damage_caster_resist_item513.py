"""GAP-2 caster-defensive-stat passive-damage schema lift (item 513).

Some empowered-AA passives deal bonus damage scaling on the CASTER's bonus
armor or bonus magic resistance - the resist-tank "I hit harder the tankier I
am" form (Taric Bravado, Galio Colossal Smash). The ``DamageBlock`` fields
(``bonus_armor_pct`` / ``bonus_mr_pct``), their ``_SCALING_TARGETS`` mappings
(-> ``caster_bonus_armor`` / ``caster_bonus_mr``), and the ``AbilityContext``
attributes already existed; this lift wires them THROUGH the passive-damage
registry:

  * ``PassiveDamageEntry`` + ``PerStackTerm`` gain ``bonus_armor_pct`` /
    ``bonus_mr_pct`` scaling fields (float or per-level tuple).
  * ``to_damage_block`` copies them into the synthetic block so
    ``ability_dps._evaluate_block`` applies them via the existing
    ``_SCALING_TARGETS`` loop with ZERO new evaluator math.
  * 2 SEEDED entries (Taric / Galio P) evaluate to the verbatim 16.11.1
    effects_descriptions value at known (level, caster bonus resist),
    hand-computed (NOT a circular re-derive).
  * Default load (flag OFF) is BYTE-IDENTICAL: both forms stay
    parse_status == "no_damage" with no synthetic block.

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    PassiveDamageEntry,
    PerStackTerm,
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

_CASTER_RESIST_CHAMPS = ("Taric", "Galio")


def _ctx(
    *,
    ad: float = 0.0,
    ap: float = 0.0,
    bonus_armor: float = 0.0,
    bonus_mr: float = 0.0,
) -> AbilityContext:
    # base armor/mr 0 so total armor/mr == caster bonus armor/mr; base ad == ad
    # so total_ad == ad (Galio scales on total AD).
    return AbilityContext.from_build(
        stats={"ad": ad, "ap": ap, "hp": 1800.0, "armor": bonus_armor, "mr": bonus_mr},
        base_stats={"ad": ad, "hp": 1800.0, "armor": 0.0, "mr": 0.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=2500.0,
        target_bonus_hp=0.0,
    )


class CtxWiringTests(unittest.TestCase):
    def test_ctx_exposes_caster_bonus_resists(self) -> None:
        c = _ctx(bonus_armor=120.0, bonus_mr=70.0)
        self.assertAlmostEqual(c.caster_bonus_armor, 120.0, places=6)
        self.assertAlmostEqual(c.caster_bonus_mr, 70.0, places=6)


class EvaluatorScalingTests(unittest.TestCase):
    def test_bonus_armor_pct_scales_caster_bonus_armor(self) -> None:
        b = DamageBlock(
            attribute="x", attribute_kind="damage", base=(0.0,), bonus_armor_pct=(20.0,)
        )
        # 20% of 100 bonus armor = 20
        self.assertAlmostEqual(_evaluate_block(b, 0, _ctx(bonus_armor=100.0)), 20.0, places=6)

    def test_bonus_mr_pct_scales_caster_bonus_mr(self) -> None:
        b = DamageBlock(
            attribute="x", attribute_kind="damage", base=(0.0,), bonus_mr_pct=(60.0,)
        )
        # 60% of 50 bonus MR = 30
        self.assertAlmostEqual(_evaluate_block(b, 0, _ctx(bonus_mr=50.0)), 30.0, places=6)

    def test_caster_resist_terms_zero_when_resist_zero(self) -> None:
        b = DamageBlock(
            attribute="x",
            attribute_kind="damage",
            base=(7.0,),
            bonus_armor_pct=(20.0,),
            bonus_mr_pct=(60.0,),
        )
        self.assertAlmostEqual(_evaluate_block(b, 0, _ctx()), 7.0, places=6)


class DataclassFieldTests(unittest.TestCase):
    def test_entry_defaults_zero(self) -> None:
        e = PassiveDamageEntry(base=(1.0,), damage_type="MAGIC", cadence="on_hit", note="x")
        self.assertEqual(e.bonus_armor_pct, 0.0)
        self.assertEqual(e.bonus_mr_pct, 0.0)

    def test_perstack_defaults_zero(self) -> None:
        ps = PerStackTerm()
        self.assertEqual(ps.bonus_armor_pct, 0.0)
        self.assertEqual(ps.bonus_mr_pct, 0.0)

    def test_to_damage_block_copies_caster_resist_fields(self) -> None:
        e = PassiveDamageEntry(
            base=(0.0,),
            damage_type="MAGIC",
            cadence="on_hit",
            note="x",
            bonus_armor_pct=15.0,
            bonus_mr_pct=60.0,
        )
        b = to_damage_block(e)
        self.assertEqual(b.bonus_armor_pct, (15.0,))
        self.assertEqual(b.bonus_mr_pct, (60.0,))

    def test_to_damage_block_omits_absent_caster_resist_fields(self) -> None:
        e = PassiveDamageEntry(base=(5.0,), damage_type="MAGIC", cadence="on_hit", note="x")
        b = to_damage_block(e)
        self.assertIsNone(b.bonus_armor_pct)
        self.assertIsNone(b.bonus_mr_pct)

    def test_perstack_fold_bonus_armor(self) -> None:
        # flat 10% bonus armor + 5% per stack, assumed 2 stacks -> 20% folded.
        e = PassiveDamageEntry(
            base=(0.0,),
            damage_type="MAGIC",
            cadence="on_hit",
            note="x",
            bonus_armor_pct=10.0,
            per_stack=PerStackTerm(bonus_armor_pct=5.0),
            assumed_stacks=2.0,
        )
        b = to_damage_block(e)
        self.assertEqual(b.bonus_armor_pct, (20.0,))


class RegistrySeedTests(unittest.TestCase):
    def test_both_seeded(self) -> None:
        for cid in _CASTER_RESIST_CHAMPS:
            self.assertIn((cid, "P", 0), _PASSIVE_DAMAGE_OVERRIDES, f"{cid} P must be seeded")

    def test_taric_terms(self) -> None:
        b = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("Taric", "P", 0)])
        self.assertEqual(b.bonus_armor_pct, (15.0,))
        self.assertIsNone(b.bonus_mr_pct)
        self.assertEqual(len(b.base), 18)
        self.assertEqual(b.base[0], 25.0)
        self.assertEqual(b.base[-1], 93.0)

    def test_galio_terms(self) -> None:
        b = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("Galio", "P", 0)])
        self.assertEqual(b.bonus_mr_pct, (60.0,))
        self.assertEqual(b.total_ad_pct, (100.0,))
        self.assertEqual(b.ap_pct, (45.0,))
        self.assertEqual(b.base[0], 15.0)
        self.assertEqual(b.base[-1], 115.0)


class ByteIdenticalDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH)

    def test_forms_stay_no_damage(self) -> None:
        for cid in _CASTER_RESIST_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            self.assertEqual(form.parse_status, "no_damage", f"{cid} P must stay no_damage flag OFF")

    def test_forms_have_no_damage_block(self) -> None:
        for cid in _CASTER_RESIST_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(dmg, [], f"{cid} P must have NO damage block flag OFF")


class InjectOnValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH, apply_passive_damage=True)

    def _val(self, cid: str, level: int, **ctx_kw: float) -> float:
        form = self.snap.get_abilities(cid)["P"][0]
        return _select_blocks(
            form.damage_blocks,
            rank_at_level("P", level),
            _ctx(**ctx_kw),
            "first",
        )

    def test_each_gains_one_block(self) -> None:
        for cid in _CASTER_RESIST_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(len(dmg), 1, f"{cid} should gain exactly 1 synthetic block")

    def test_taric_bravado(self) -> None:
        # 25 : 93 (based on level) (+ 15% bonus armor) magic.
        # L1, 100 bonus armor -> 25 + 15 = 40
        self.assertAlmostEqual(self._val("Taric", 1, bonus_armor=100.0), 40.0, places=4)
        # L18, 100 bonus armor -> 93 + 15 = 108
        self.assertAlmostEqual(self._val("Taric", 18, bonus_armor=100.0), 108.0, places=4)
        # L1, 0 bonus armor -> 25 (pure base)
        self.assertAlmostEqual(self._val("Taric", 1, bonus_armor=0.0), 25.0, places=4)

    def test_galio_colossal_smash(self) -> None:
        # 15 : 115 (+ 100% AD) (+ 45% AP) (+ 60% bonus MR) magic.
        # L1, ad200 ap100 mr50 -> 15 + 200 + 45 + 30 = 290
        self.assertAlmostEqual(
            self._val("Galio", 1, ad=200.0, ap=100.0, bonus_mr=50.0), 290.0, places=4
        )
        # L18, same -> 115 + 200 + 45 + 30 = 390
        self.assertAlmostEqual(
            self._val("Galio", 18, ad=200.0, ap=100.0, bonus_mr=50.0), 390.0, places=4
        )
        # L1, bonus MR only (100) -> 15 + 60 = 75
        self.assertAlmostEqual(self._val("Galio", 1, bonus_mr=100.0), 75.0, places=4)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer._passive_damage_overrides as mod

        with open(mod.__file__, "rb") as fh:
            fh.read().decode("ascii")  # raises on any non-ASCII byte


if __name__ == "__main__":
    unittest.main()
