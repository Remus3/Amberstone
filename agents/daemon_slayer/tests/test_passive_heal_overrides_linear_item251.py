"""item 251 - LINEAR effects-text-only HEAL registry (sibling of item 250).

Extends ``_passive_heal_overrides`` with 16 LINEAR effects-text self-heals
(flat / caster-stat-scaled / per-level-pct-of-HP, no per-100 product): 14
P-slot + Rakan Q + Talon Q. The only new schema is ``level_scaled`` (on
PassiveHealEntry + DamageBlock + threaded ``level`` through
``ability_hps._eval_heal_shield_block``) - a SPELL-slot heal whose per-level
tuple is indexed by champion LEVEL, not the spell rank (Rakan Q / Talon Q).

DEFAULT (apply_passive_heal=False / load_default) stays byte-identical: the seam
injects only under the opt-in flag. UNLIKE the 3 item-250 bilinear seeds, most
linear entries carry a FLAT / caster-stat term that resolves NON-zero at the
default resolve_target_relative=False - the flag-ON path is where they differ.

Verbatim 16.11.1 effects_descriptions back each pinned value.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    DamageBlock,
    load_default,
)
from agents.daemon_slayer.ability_hps import (
    _eval_heal_shield_block,
    compute_ability_hps,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer._passive_heal_overrides import (
    _PASSIVE_HEAL_OVERRIDES,
    PassiveHealEntry,
    to_heal_block,
)

_PATCH = "16.11.1"

# The 16 LINEAR seeds (item 251) - 14 P-slot + 2 spell-slot level-scaled.
_LINEAR_SEEDS = (
    ("Ahri", "P", 0), ("Alistar", "P", 0), ("Aurora", "P", 0),
    ("Chogath", "P", 0), ("Evelynn", "P", 0), ("Fiora", "P", 0),
    ("Gragas", "P", 0), ("Lillia", "P", 0), ("Maokai", "P", 0),
    ("RekSai", "P", 0), ("Swain", "P", 0), ("Trundle", "P", 0),
    ("XinZhao", "P", 0), ("Yuumi", "P", 0),
    ("Rakan", "Q", 0), ("Talon", "Q", 0),
)
_LEVEL_SCALED_SEEDS = (("Rakan", "Q", 0), ("Talon", "Q", 0))
# item-250 bilinear seeds stay in the same registry.
_BILINEAR_SEEDS = (("Viego", "P", 0), ("Karma", "W", 1), ("Kayn", "R", 0))


def _snap() -> DataSnapshot:
    return DataSnapshot.load()


def _heal(cid, lvl, ab, *, rtr=False, tmh=0.0, cmh=0.0, fio=None):
    r = compute_ability_hps(
        _snap(), cid, lvl, abilities=ab,
        resolve_target_relative=rtr, target_max_hp=tmh,
        caster_missing_hp_pct=cmh, form_index_overrides=fio,
    )
    return {s.key: s.heal_per_cast for s in r.spells}


class RegistryShapeTests(unittest.TestCase):
    def test_all_16_linear_seeds_present(self) -> None:
        for key in _LINEAR_SEEDS:
            self.assertIn(key, _PASSIVE_HEAL_OVERRIDES, key)
            self.assertIsInstance(_PASSIVE_HEAL_OVERRIDES[key], PassiveHealEntry)

    def test_registry_total_is_at_least_19(self) -> None:
        # 3 item-250 bilinear + 16 item-251 linear (+ later per-charge seam
        # entries from item 252+ may grow the registry; the 19 here are pinned).
        self.assertGreaterEqual(len(_PASSIVE_HEAL_OVERRIDES), 19)

    def test_linear_seeds_have_no_bilinear_terms(self) -> None:
        for key in _LINEAR_SEEDS:
            self.assertEqual(_PASSIVE_HEAL_OVERRIDES[key].bilinear_terms, (), key)
            self.assertTrue(_PASSIVE_HEAL_OVERRIDES[key].linear_terms, key)

    def test_only_two_seeds_are_level_scaled(self) -> None:
        scaled = {
            k for k, e in _PASSIVE_HEAL_OVERRIDES.items() if e.level_scaled
        }
        self.assertEqual(scaled, set(_LEVEL_SCALED_SEEDS))

    def test_cadence_is_known(self) -> None:
        for key in _LINEAR_SEEDS:
            self.assertIn(
                _PASSIVE_HEAL_OVERRIDES[key].cadence, ("per_cast", "per_fight"),
                key,
            )

    def test_default_passive_heal_entry_is_not_level_scaled(self) -> None:
        e = PassiveHealEntry(linear_terms=((1.0, ""),), cadence="per_cast", note="x")
        self.assertFalse(e.level_scaled)


class ToHealBlockTests(unittest.TestCase):
    def test_flat_seed_builds_heal_block_no_bilinear(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Fiora", "P", 0)])
        self.assertEqual(b.attribute_kind, "heal")
        self.assertEqual(b.bilinear_terms, ())
        self.assertFalse(b.level_scaled)
        self.assertEqual(len(b.raw_modifiers), 1)
        # flat per-level base: 18 values, lvl1=35, lvl18=100.
        vals = b.raw_modifiers[0]["values"]
        self.assertEqual(len(vals), 18)
        self.assertAlmostEqual(vals[0], 35.0)
        self.assertAlmostEqual(vals[17], 100.0)

    def test_level_scaled_seed_sets_block_flag(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Rakan", "Q", 0)])
        self.assertTrue(b.level_scaled)
        # 2 terms: per-level flat base + 55% AP.
        self.assertEqual(len(b.raw_modifiers), 2)

    def test_xinzhao_two_terms_step_and_ap(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("XinZhao", "P", 0)])
        units = [m["units"][0] for m in b.raw_modifiers]
        self.assertIn("% maximum health", units)
        self.assertIn("% ap", units)


class DefaultByteIdenticalTests(unittest.TestCase):
    def test_load_default_injects_nothing(self) -> None:
        # apply_passive_heal=False (load_default) appends NO heal block to a
        # seeded form: Fiora P stays empty (byte-identical pre-item-251).
        ab = load_default()
        fiora_p = ab.get_abilities("Fiora")["P"][0]
        self.assertFalse(
            any(b.attribute_kind == "heal" for b in fiora_p.damage_blocks)
        )

    def test_flag_on_injects_heal_block(self) -> None:
        ab = AbilitiesSnapshot.load(apply_passive_heal=True)
        fiora_p = ab.get_abilities("Fiora")["P"][0]
        self.assertTrue(
            any(b.attribute_kind == "heal" for b in fiora_p.damage_blocks)
        )

    def test_non_registry_champ_identical_flag_on_off(self) -> None:
        # A champ with no registry entry is byte-identical with the flag ON.
        ab_off = AbilitiesSnapshot.load()
        ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)
        self.assertEqual(_heal("Caitlyn", 11, ab_off), _heal("Caitlyn", 11, ab_on))


class SeededValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ab = AbilitiesSnapshot.load(apply_passive_heal=True)

    def test_fiora_flat_lerp_level_endpoints(self) -> None:
        self.assertAlmostEqual(_heal("Fiora", 1, self.ab)["P"], 35.0, places=2)
        self.assertAlmostEqual(_heal("Fiora", 18, self.ab)["P"], 100.0, places=2)

    def test_gragas_flat_pct_of_caster_max_hp(self) -> None:
        # 5.5% of Gragas max HP at L11 (> 0, scales with caster HP).
        self.assertGreater(_heal("Gragas", 11, self.ab)["P"], 50.0)

    def test_talon_q_level_scaled_endpoints(self) -> None:
        self.assertAlmostEqual(
            _heal("Talon", 18, self.ab, fio={"Q": 0})["Q"], 55.0, places=2,
        )

    def test_rakan_q_level_scaled_not_rank_indexed(self) -> None:
        # Q is maxed (rank 4) by L11 but the heal scales by LEVEL: 40 + 170 *
        # 10/17 = 140 (level-indexed), NOT lerp[4] ~= 80 (rank-indexed).
        self.assertAlmostEqual(
            _heal("Rakan", 11, self.ab, fio={"Q": 0})["Q"], 140.0, places=1,
        )
        self.assertAlmostEqual(
            _heal("Rakan", 18, self.ab, fio={"Q": 0})["Q"], 210.0, places=1,
        )

    def test_trundle_target_relative_zero_at_rest(self) -> None:
        # TARGET max HP scaled -> 0 (spell skipped) at the default resolve-off.
        self.assertNotIn("P", _heal("Trundle", 11, self.ab))

    def test_trundle_resolves_under_target_relative(self) -> None:
        v = _heal("Trundle", 11, self.ab, rtr=True, tmh=2500.0)
        self.assertGreater(v.get("P", 0.0), 50.0)


class LevelScaledEvalTests(unittest.TestCase):
    def test_block_level_scaled_indexes_by_level(self) -> None:
        # A synthetic level_scaled heal block reads at level-1, ignoring rank.
        b = DamageBlock(
            attribute="x", attribute_kind="heal",
            raw_modifiers=({"values": list(range(18)), "units": [""]},),
            level_scaled=True,
        )
        # ctx unused for a flat (empty-unit) term.
        amt, _ = _eval_heal_shield_block(b, 0, None, level=12)
        self.assertEqual(amt, 11.0)  # level 12 -> index 11
        # rank-indexed (level None) reads at rank 0.
        amt0, _ = _eval_heal_shield_block(b, 0, None, level=None)
        self.assertEqual(amt0, 0.0)

    def test_non_level_scaled_block_indexes_by_rank(self) -> None:
        b = DamageBlock(
            attribute="x", attribute_kind="heal",
            raw_modifiers=({"values": list(range(18)), "units": [""]},),
        )
        amt, _ = _eval_heal_shield_block(b, 3, None, level=12)
        self.assertEqual(amt, 3.0)  # rank wins, level ignored


class NoExistingHealBlockGateTests(unittest.TestCase):
    def test_seeded_forms_had_no_heal_block_before_injection(self) -> None:
        ab = load_default()
        for cid, key, fi in _LINEAR_SEEDS:
            form = [f for f in ab.get_abilities(cid)[key] if f.form_index == fi][0]
            self.assertFalse(
                any(b.attribute_kind == "heal" for b in form.damage_blocks),
                (cid, key, fi),
            )


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_ascii_clean(self) -> None:
        import agents.daemon_slayer._passive_heal_overrides as mod
        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                raw = fh.read()
            raw.decode("ascii")  # raises if any non-ASCII byte


if __name__ == "__main__":
    unittest.main()
