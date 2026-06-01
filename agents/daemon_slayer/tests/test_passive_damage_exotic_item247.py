"""GAP-2 Phase C3 (item 247) - exotic passive damage entries.

Covers the 6 exotic passives seeded in this slice (Aatrox / Jarvan IV / Zed /
Caitlyn / Ekko / Gangplank P) plus the additive schema they ride:
  * ``_step_per_level`` builds the 3-tier even-thirds level step.
  * ``to_damage_block`` coerces a per-level tuple scaling field (Aatrox's
    level-scaled %max-HP, Caitlyn's 60/90/120% AD step) AND a flat float
    (Jarvan IV's 8% current HP) - both via the float|tuple union.
  * ``target_current_hp_pct`` is wired into the synthetic block.
  * Inject-on (apply_passive_damage=True) evaluates each new form to the
    verbatim 16.11.1 effects_descriptions value (hand-computed, NOT a circular
    re-derive of the entry).
  * Default load (flag OFF) is BYTE-IDENTICAL: the 6 new forms stay
    parse_status == "no_damage" with no synthetic block.
  * Gwen P + Kai'Sa P remain STAGED (absent from the registry).

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    _step_per_level,
    to_damage_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _select_blocks,
    rank_at_level,
)

_PATCH = "16.11.1"

_NEW_CHAMPS = ("Aatrox", "JarvanIV", "Zed", "Caitlyn", "Ekko", "Gangplank")


def _ctx(*, ap: float = 0.0, bonus_ad: float = 0.0, cur_pct: float = 1.0) -> AbilityContext:
    base_ad = 60.0
    return AbilityContext.from_build(
        stats={"ad": base_ad + bonus_ad, "ap": ap, "hp": 1800.0},
        base_stats={"ad": base_ad, "hp": 1800.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=2000.0,
        target_bonus_hp=0.0,
        target_current_hp_pct=cur_pct,
    )


class StepPerLevelTests(unittest.TestCase):
    def test_three_tier_even_thirds(self) -> None:
        t = _step_per_level((6.0, 8.0, 10.0))
        self.assertEqual(len(t), 18)
        self.assertEqual(t[0], 6.0)   # level 1 -> tier 1
        self.assertEqual(t[5], 6.0)   # level 6 -> tier 1
        self.assertEqual(t[6], 8.0)   # level 7 -> tier 2
        self.assertEqual(t[11], 8.0)  # level 12 -> tier 2
        self.assertEqual(t[12], 10.0)  # level 13 -> tier 3
        self.assertEqual(t[-1], 10.0)  # level 18 -> tier 3

    def test_empty_is_all_zero(self) -> None:
        self.assertEqual(_step_per_level(()), tuple(0.0 for _ in range(18)))


class SchemaCoercionTests(unittest.TestCase):
    def test_per_level_tuple_passed_through(self) -> None:
        block = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("Aatrox", "P", 0)])
        self.assertEqual(block.attribute_kind, "damage")
        self.assertEqual(len(block.target_max_hp_pct), 18)
        self.assertEqual(block.target_max_hp_pct[0], 4.0)
        self.assertEqual(block.target_max_hp_pct[-1], 8.0)

    def test_flat_current_hp_pct_wired(self) -> None:
        block = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("JarvanIV", "P", 0)])
        self.assertEqual(block.target_current_hp_pct, (8.0,))
        self.assertIsNone(block.target_max_hp_pct)

    def test_caitlyn_total_ad_step(self) -> None:
        block = to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[("Caitlyn", "P", 0)])
        self.assertEqual(len(block.total_ad_pct), 18)
        self.assertEqual(block.total_ad_pct[0], 60.0)
        self.assertEqual(block.total_ad_pct[-1], 120.0)

    def test_all_new_entries_build_damage_blocks(self) -> None:
        for cid in _NEW_CHAMPS:
            entry = _PASSIVE_DAMAGE_OVERRIDES[(cid, "P", 0)]
            self.assertEqual(to_damage_block(entry).attribute_kind, "damage")


class StagedAbsentTests(unittest.TestCase):
    def test_kaisa_not_seeded(self) -> None:
        # Kai'Sa P stays STAGED (per-Plasma-stack ramp - its own decision).
        self.assertNotIn(("Kaisa", "P", 0), _PASSIVE_DAMAGE_OVERRIDES)

    def test_gwen_seeded_by_item248(self) -> None:
        # Gwen P was STAGED here through item 247; the item-248 bilinear
        # schema lift now seeds it (see test_passive_damage_bilinear_item248).
        self.assertIn(("Gwen", "P", 0), _PASSIVE_DAMAGE_OVERRIDES)


class ByteIdenticalDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH)

    def test_new_forms_stay_no_damage(self) -> None:
        for cid in _NEW_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            self.assertEqual(
                form.parse_status, "no_damage",
                f"{cid} P form 0 must stay no_damage with flag OFF",
            )

    def test_new_forms_have_no_damage_block(self) -> None:
        for cid in _NEW_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(dmg, [], f"{cid} P form 0 must have NO damage block with flag OFF")


class InjectOnValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH, apply_passive_damage=True)

    def _val(self, cid: str, level: int, **kw: float) -> float:
        form = self.snap.get_abilities(cid)["P"][0]
        return _select_blocks(form.damage_blocks, rank_at_level("P", level), _ctx(**kw), "first")

    def test_each_new_form_gains_one_block(self) -> None:
        for cid in _NEW_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(len(dmg), 1, f"{cid} should gain exactly 1 synthetic block")

    def test_aatrox_max_hp_lerp(self) -> None:
        # 4%:8% max HP. L11 (rank 10): (4 + 4*10/17)% of 2000 = 127.058824
        self.assertAlmostEqual(self._val("Aatrox", 11), 127.058824, places=3)
        self.assertAlmostEqual(self._val("Aatrox", 18), 160.0, places=3)

    def test_jarvan_current_hp_flat(self) -> None:
        # 8% current HP; full-HP ctx -> current 2000 -> 160 at every level
        self.assertAlmostEqual(self._val("JarvanIV", 1), 160.0, places=3)
        self.assertAlmostEqual(self._val("JarvanIV", 18), 160.0, places=3)

    def test_jarvan_scales_with_current_hp(self) -> None:
        # at 50% current HP -> current 1000 -> 8% = 80
        self.assertAlmostEqual(self._val("JarvanIV", 11, cur_pct=0.5), 80.0, places=3)

    def test_zed_max_hp_step(self) -> None:
        self.assertAlmostEqual(self._val("Zed", 1), 120.0, places=3)   # 6% of 2000
        self.assertAlmostEqual(self._val("Zed", 11), 160.0, places=3)  # 8% of 2000
        self.assertAlmostEqual(self._val("Zed", 18), 200.0, places=3)  # 10% of 2000

    def test_caitlyn_total_ad_step(self) -> None:
        # 90% AD at L11 with total AD 130 (base 60 + bonus 70) = 117
        self.assertAlmostEqual(self._val("Caitlyn", 11, bonus_ad=70.0), 117.0, places=3)
        # 120% AD at L18 with total AD 60 = 72
        self.assertAlmostEqual(self._val("Caitlyn", 18), 72.0, places=3)

    def test_ekko_lerp_plus_ap(self) -> None:
        # 30:140 + 90% AP. L11 AP200: (30 + 110*10/17) + 0.9*200 = 274.705882
        self.assertAlmostEqual(self._val("Ekko", 11, ap=200.0), 274.705882, places=3)

    def test_gangplank_lerp_plus_bonus_ad(self) -> None:
        # 50:250 + 100% bonus AD. L11 bonusAD70: (50 + 200*10/17) + 70 = 237.647059
        self.assertAlmostEqual(self._val("Gangplank", 11, bonus_ad=70.0), 237.647059, places=3)
        self.assertAlmostEqual(self._val("Gangplank", 18, bonus_ad=100.0), 350.0, places=3)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer._passive_damage_overrides as mod

        with open(mod.__file__, "rb") as fh:
            raw = fh.read()
        raw.decode("ascii")  # raises if any non-ASCII byte


if __name__ == "__main__":
    unittest.main()
