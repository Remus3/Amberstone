"""GAP 2 (2026-05-31) - effects-text-only passive damage registry tests.

Covers:
  * to_damage_block builds an attribute_kind=="damage" block.
  * Default load (apply_passive_damage off) is BYTE-IDENTICAL: the seeded
    P forms keep their original damage_blocks (no synthetic block) and stay
    parse_status == "no_damage".
  * Inject-on load appends exactly one synthetic damage block to each seeded
    form, and the block evaluates (via the existing _evaluate_block /
    _select_blocks machinery, pinned AbilityContext + level) to the verbatim
    effects_descriptions formula value for Ziggs / Lux / Akali (hand-computed
    raw value, NOT a circular re-derive of the entry).
  * _lerp_per_level matches the engine's per-level indexing convention.

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    _lerp_per_level,
    to_damage_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _select_blocks,
    rank_at_level,
)

_PATCH = "16.11.1"

# Seeded P-slot champions (champion_id) under (cid, "P", 0).
_SEEDED_CHAMPS = sorted(
    {cid for (cid, key, _form) in _PASSIVE_DAMAGE_OVERRIDES if key == "P"}
)


def _full_hp_ctx(*, ap: float = 0.0, bonus_ad: float = 0.0) -> AbilityContext:
    """A target-at-full-HP context with the requested caster AP / bonus AD.

    bonus_ad is delivered as total_ad - base_ad: base_ad fixed at 60 so a
    requested bonus_ad of 70 means total_ad 130. AP is direct.
    """
    base_ad = 60.0
    return AbilityContext.from_build(
        stats={"ad": base_ad + bonus_ad, "ap": ap, "hp": 1800.0},
        base_stats={"ad": base_ad, "hp": 1800.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=2000.0,
        target_bonus_hp=0.0,
    )


class LerpPerLevelTests(unittest.TestCase):
    def test_endpoints_and_length(self) -> None:
        t = _lerp_per_level(20.0, 160.0)
        self.assertEqual(len(t), 18)
        self.assertEqual(t[0], 20.0)
        self.assertEqual(t[-1], 160.0)

    def test_indexed_by_level_minus_one(self) -> None:
        # rank_at_level("P", level) == level - 1; value_at indexes the tuple
        # by that rank. Confirm the midpoint level lands where expected.
        t = _lerp_per_level(30.0, 200.0)
        rank = rank_at_level("P", 11)  # -> 10
        self.assertEqual(rank, 10)
        # level 11 -> 30 + (200-30)*10/17
        self.assertAlmostEqual(t[rank], 30.0 + (200.0 - 30.0) * 10.0 / 17.0, places=4)


class ToDamageBlockTests(unittest.TestCase):
    def test_builds_damage_kind(self) -> None:
        entry = _PASSIVE_DAMAGE_OVERRIDES[("Ziggs", "P", 0)]
        block = to_damage_block(entry)
        self.assertEqual(block.attribute_kind, "damage")
        self.assertEqual(block.attribute, "Short Fuse")

    def test_scaling_fields_one_element_tuples(self) -> None:
        # Akali carries both bonus_ad_pct + ap_pct; each must be a populated
        # 1-element tuple so value_at returns the flat % at every rank.
        entry = _PASSIVE_DAMAGE_OVERRIDES[("Akali", "P", 0)]
        block = to_damage_block(entry)
        self.assertEqual(block.bonus_ad_pct, (60.0,))
        self.assertEqual(block.ap_pct, (55.0,))

    def test_unused_scaling_fields_stay_none(self) -> None:
        # Lux has only ap_pct; bonus_ad_pct / total_ad_pct must stay None so
        # they contribute 0 via value_at's default.
        entry = _PASSIVE_DAMAGE_OVERRIDES[("Lux", "P", 0)]
        block = to_damage_block(entry)
        self.assertEqual(block.ap_pct, (30.0,))
        self.assertIsNone(block.bonus_ad_pct)
        self.assertIsNone(block.total_ad_pct)
        self.assertIsNone(block.target_max_hp_pct)

    def test_all_registry_entries_build_damage_blocks(self) -> None:
        for entry in _PASSIVE_DAMAGE_OVERRIDES.values():
            self.assertEqual(to_damage_block(entry).attribute_kind, "damage")


class ByteIdenticalDefaultTests(unittest.TestCase):
    """Default load (apply_passive_damage OFF) appends NO synthetic block."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH)

    def test_seeded_forms_still_no_damage(self) -> None:
        for cid in _SEEDED_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            self.assertEqual(
                form.parse_status,
                "no_damage",
                f"{cid} P form 0 should stay no_damage with flag OFF",
            )

    def test_seeded_forms_have_no_synthetic_damage_block(self) -> None:
        for cid in _SEEDED_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            damage = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(
                damage,
                [],
                f"{cid} P form 0 must have NO damage block with flag OFF",
            )


class InjectOnTests(unittest.TestCase):
    """apply_passive_damage=True appends one synthetic damage block per seed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH, apply_passive_damage=True)

    def test_each_seed_gains_exactly_one_damage_block(self) -> None:
        for cid in _SEEDED_CHAMPS:
            form = self.snap.get_abilities(cid)["P"][0]
            damage = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(
                len(damage),
                1,
                f"{cid} P form 0 should gain exactly 1 synthetic damage block",
            )

    def test_ziggs_short_fuse_value(self) -> None:
        # 20:160 by level + 50% AP. L11 (rank 10), AP 200.
        # base[10] = 20 + (160-20)*10/17 = 102.352941; + 0.50*200 = 202.352941
        form = self.snap.get_abilities("Ziggs")["P"][0]
        val = _select_blocks(form.damage_blocks, rank_at_level("P", 11), _full_hp_ctx(ap=200.0), "first")
        self.assertAlmostEqual(val, 202.352941, places=3)

    def test_lux_illumination_value(self) -> None:
        # 30:200 by level + 30% AP. L11, AP 200. base[10]=130; +0.30*200=190
        form = self.snap.get_abilities("Lux")["P"][0]
        val = _select_blocks(form.damage_blocks, rank_at_level("P", 11), _full_hp_ctx(ap=200.0), "first")
        self.assertAlmostEqual(val, 190.0, places=3)

    def test_akali_assassins_mark_value(self) -> None:
        # 35:182 + 60% bonus AD + 55% AP. L11, bonusAD 70, AP 100.
        # base[10] = 35 + (182-35)*10/17 = 121.470588; +0.60*70=42; +0.55*100=55
        # total = 218.470588
        form = self.snap.get_abilities("Akali")["P"][0]
        val = _select_blocks(
            form.damage_blocks,
            rank_at_level("P", 11),
            _full_hp_ctx(ap=100.0, bonus_ad=70.0),
            "first",
        )
        self.assertAlmostEqual(val, 218.470588, places=3)

    def test_velkoz_true_value_level18(self) -> None:
        # 35:180 + 60% AP. L18 (rank 17 -> last element 180), AP 100.
        # 180 + 0.60*100 = 240
        form = self.snap.get_abilities("Velkoz")["P"][0]
        val = _select_blocks(form.damage_blocks, rank_at_level("P", 18), _full_hp_ctx(ap=100.0), "first")
        self.assertAlmostEqual(val, 240.0, places=3)


if __name__ == "__main__":
    unittest.main()
