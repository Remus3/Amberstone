"""item 254 - LINEAR effects-text HEAL registry RE-OPEN (item-251 sibling).

The item-253 AS-aware roster pass logged Mordekaiser R "heal 10% of their
maximum health" as a clean target-max-HP linear heal the original item-251
84-candidate scan overlooked. This slice re-runs the exhaustive scan and seeds
4 recovered misses, all on the EXISTING item-251 linear machinery (NO schema
change - same _PASSIVE_HEAL_OVERRIDES dict, same to_heal_block, same
_eval_heal_shield_block; a linear entry carries no bilinear_terms / no
per_charge):

  - Mordekaiser R Realm of Death: 10% TARGET max HP (flat, all 3 R ranks) -
    target-relative, 0 at rest, surfaces under resolve_target_relative +
    target_max_hp. cadence per_cast (ult cooldown).
  - Illaoi P Prophet of an Elder God: 5% caster MISSING HP per Tentacle that
    hits a champion - missing-HP, 0 at rest, surfaces under
    resolve_target_relative + caster_missing_hp_pct.
  - Zac P Cell Division (Goo): 4% : 8% by level caster MAX HP per chunk
    consumed - resolves at the default (caster max HP), like Maokai/Swain.
  - Dr. Mundo P Goes Where He Pleases: 4% caster MAX HP on the canister
    consume - resolves at the default, like Gragas.

DEFAULT (apply_passive_heal=False / load_default) stays byte-identical (the seam
injects only under the flag, gated on no existing heal block - all 4 forms have
empty damage_blocks). Verbatim 16.11.1 effects_descriptions back each value.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    load_default,
)
from agents.daemon_slayer.ability_hps import compute_ability_hps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer._passive_heal_overrides import (
    _PASSIVE_HEAL_OVERRIDES,
    PassiveHealEntry,
    to_heal_block,
)

# The 4 item-254 re-open seeds.
_REOPEN_SEEDS = (
    ("Mordekaiser", "R", 0),
    ("Illaoi", "P", 0),
    ("Zac", "P", 0),
    ("DrMundo", "P", 0),
)
# Of those, the 2 that stay GATED (0 at the default resolve-off).
_GATED_SEEDS = (("Mordekaiser", "R", 0), ("Illaoi", "P", 0))
# ...and the 2 that resolve at the default (caster max HP).
_RESTING_SEEDS = (("Zac", "P", 0), ("DrMundo", "P", 0))


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
    def test_all_four_reopen_seeds_present(self) -> None:
        for key in _REOPEN_SEEDS:
            self.assertIn(key, _PASSIVE_HEAL_OVERRIDES, key)
            self.assertIsInstance(_PASSIVE_HEAL_OVERRIDES[key], PassiveHealEntry)

    def test_registry_total_grew_to_at_least_23(self) -> None:
        # 3 item-250 bilinear + 16 item-251 linear + 1 item-252 per-charge +
        # 4 item-254 re-open = 24 (the >= 23 is the floor; later slices may add).
        self.assertGreaterEqual(len(_PASSIVE_HEAL_OVERRIDES), 23)

    def test_reopen_seeds_are_plain_linear(self) -> None:
        # No bilinear_terms, no per_charge, not level_scaled - they ride the
        # existing item-251 linear path with zero schema change.
        for key in _REOPEN_SEEDS:
            e = _PASSIVE_HEAL_OVERRIDES[key]
            self.assertEqual(e.bilinear_terms, (), key)
            self.assertEqual(e.per_charge, (), key)
            self.assertFalse(e.level_scaled, key)
            self.assertTrue(e.linear_terms, key)

    def test_cadence_known(self) -> None:
        for key in _REOPEN_SEEDS:
            self.assertIn(
                _PASSIVE_HEAL_OVERRIDES[key].cadence, ("per_cast", "per_fight"),
                key,
            )

    def test_reopen_does_not_add_level_scaled_entries(self) -> None:
        scaled = {k for k, e in _PASSIVE_HEAL_OVERRIDES.items() if e.level_scaled}
        for key in _REOPEN_SEEDS:
            self.assertNotIn(key, scaled, key)


class ToHealBlockTests(unittest.TestCase):
    def test_mordekaiser_target_max_hp_flat(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Mordekaiser", "R", 0)])
        self.assertEqual(b.attribute_kind, "heal")
        self.assertEqual(b.bilinear_terms, ())
        self.assertEqual(len(b.raw_modifiers), 1)
        m = b.raw_modifiers[0]
        self.assertEqual(m["units"], ["% of target's maximum health"])
        self.assertEqual(m["values"], [10.0])

    def test_illaoi_caster_missing_hp_flat(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Illaoi", "P", 0)])
        m = b.raw_modifiers[0]
        self.assertEqual(m["units"], ["% missing health"])
        self.assertEqual(m["values"], [5.0])

    def test_zac_caster_max_hp_per_level(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Zac", "P", 0)])
        m = b.raw_modifiers[0]
        self.assertEqual(m["units"], ["% maximum health"])
        # per-level lerp: 18 values, lvl1=4, lvl18=8.
        self.assertEqual(len(m["values"]), 18)
        self.assertAlmostEqual(m["values"][0], 4.0)
        self.assertAlmostEqual(m["values"][17], 8.0)

    def test_drmundo_caster_max_hp_flat(self) -> None:
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("DrMundo", "P", 0)])
        m = b.raw_modifiers[0]
        self.assertEqual(m["units"], ["% maximum health"])
        self.assertEqual(m["values"], [4.0])


class DefaultByteIdenticalTests(unittest.TestCase):
    def test_load_default_injects_no_heal_block(self) -> None:
        ab = load_default()
        for cid, key, fi in _REOPEN_SEEDS:
            form = [f for f in ab.get_abilities(cid)[key] if f.form_index == fi][0]
            self.assertFalse(
                any(b.attribute_kind == "heal" for b in form.damage_blocks),
                (cid, key, fi),
            )

    def test_flag_on_injects_heal_block(self) -> None:
        ab = AbilitiesSnapshot.load(apply_passive_heal=True)
        for cid, key, fi in _REOPEN_SEEDS:
            form = [f for f in ab.get_abilities(cid)[key] if f.form_index == fi][0]
            self.assertTrue(
                any(b.attribute_kind == "heal" for b in form.damage_blocks),
                (cid, key, fi),
            )

    def test_non_registry_champ_identical_flag_on_off(self) -> None:
        ab_off = AbilitiesSnapshot.load()
        ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)
        self.assertEqual(_heal("Caitlyn", 11, ab_off), _heal("Caitlyn", 11, ab_on))


class NoExistingHealBlockGateTests(unittest.TestCase):
    def test_reopen_forms_had_no_heal_block_before_injection(self) -> None:
        ab = load_default()
        for cid, key, fi in _REOPEN_SEEDS:
            form = [f for f in ab.get_abilities(cid)[key] if f.form_index == fi][0]
            self.assertFalse(
                any(b.attribute_kind == "heal" for b in form.damage_blocks),
                (cid, key, fi),
            )


class SeededValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ab = AbilitiesSnapshot.load(apply_passive_heal=True)

    # --- gated (target-relative / caster-missing-HP): 0 at rest ---
    def test_mordekaiser_target_relative_zero_at_rest(self) -> None:
        # TARGET max HP scaled -> 0 (spell skipped) at the default resolve-off.
        self.assertNotIn("R", _heal("Mordekaiser", 11, self.ab))

    def test_mordekaiser_resolves_to_ten_pct_target_max_hp(self) -> None:
        v = _heal("Mordekaiser", 11, self.ab, rtr=True, tmh=2500.0)
        self.assertAlmostEqual(v.get("R", 0.0), 250.0, places=1)  # 10% of 2500

    def test_illaoi_missing_hp_zero_at_rest(self) -> None:
        self.assertNotIn("P", _heal("Illaoi", 11, self.ab))

    def test_illaoi_resolves_under_missing_hp(self) -> None:
        # 5% of caster missing HP (caster_max_hp * 0.5 missing) > 0.
        v = _heal("Illaoi", 11, self.ab, rtr=True, cmh=0.5)
        self.assertGreater(v.get("P", 0.0), 0.0)

    def test_illaoi_scales_with_missing_hp_pct(self) -> None:
        lo = _heal("Illaoi", 11, self.ab, rtr=True, cmh=0.25).get("P", 0.0)
        hi = _heal("Illaoi", 11, self.ab, rtr=True, cmh=0.75).get("P", 0.0)
        self.assertGreater(hi, lo)

    # --- resting-resolvable (caster max HP): NON-zero at the default ---
    def test_zac_resolves_at_default_and_scales_with_level(self) -> None:
        lo = _heal("Zac", 1, self.ab).get("P", 0.0)
        hi = _heal("Zac", 18, self.ab).get("P", 0.0)
        self.assertGreater(lo, 0.0)
        self.assertGreater(hi, lo)  # 8% at L18 > 4% at L1 (and bigger HP pool)

    def test_drmundo_resolves_at_default(self) -> None:
        # 4% of Dr. Mundo max HP at L11 - Mundo's a high-HP juggernaut, > 50.
        self.assertGreater(_heal("DrMundo", 11, self.ab).get("P", 0.0), 50.0)

    def test_drmundo_flat_pct_scales_only_with_hp_not_level_curve(self) -> None:
        # flat 4% (not per-level): L18 heal > L11 purely via the bigger HP pool.
        v11 = _heal("DrMundo", 11, self.ab).get("P", 0.0)
        v18 = _heal("DrMundo", 18, self.ab).get("P", 0.0)
        self.assertGreater(v18, v11)


class RegressionTests(unittest.TestCase):
    def test_trundle_target_relative_still_works(self) -> None:
        # item-251 Trundle P (target-max-HP) unaffected by the re-open.
        ab = AbilitiesSnapshot.load(apply_passive_heal=True)
        self.assertNotIn("P", _heal("Trundle", 11, ab))
        v = _heal("Trundle", 11, ab, rtr=True, tmh=2500.0)
        self.assertGreater(v.get("P", 0.0), 50.0)

    def test_engine_version_pin(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.100.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_ascii_clean(self) -> None:
        import agents.daemon_slayer._passive_heal_overrides as mod
        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                fh.read().decode("ascii")  # raises on any non-ASCII byte


if __name__ == "__main__":
    unittest.main()
