"""Item 264 - effects-text-only RESIST-STAT grant registry tests.

The FOURTH survivability axis, sibling of the effects-text HEAL (items 250-254),
SHIELD (item 260), and DAMAGE-REDUCTION (items 261-262) registries. A resist
grant raises the armor/MR DENOMINATOR DIRECTLY (bonus armor / MR added BEFORE
``_armor_factor``), the axis item 261 documented as a DELIBERATE EXCLUSION from
the DR registry. ``apply_passive_resist`` defaults False -> byte-identical to
ENGINE 1.92.0.

Seeded 6 (4 permanent + 2 active): Garen W (30/30 cap), Wukong P (6:10 armor),
Shyvana P (5/5), Sejuani P (10/10), Gwen W (22/22 active), Pantheon E (5:30
level active). The 2 actives amortize by conditional_probability=0.3.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.hybrid import compute_hybrid
from agents.daemon_slayer._passive_damage_overrides import _lerp_per_level
from agents.daemon_slayer._passive_resist_overrides import (
    _ACTIVE_RESIST_PROB,
    _PASSIVE_RESIST_OVERRIDES,
    PassiveResistEntry,
    _value_at_level,
    resist_grants,
)

_SEEDED = ("Garen", "MonkeyKing", "Shyvana", "Sejuani", "Gwen", "Pantheon")


class RegistryShapeTests(unittest.TestCase):
    def test_six_entries(self):
        self.assertGreaterEqual(len(_PASSIVE_RESIST_OVERRIDES), 6)  # item 267 adds rank-scaled block-value grants

    def test_keys_are_cid_key_form_tuples(self):
        for k, v in _PASSIVE_RESIST_OVERRIDES.items():
            self.assertIsInstance(k, tuple)
            self.assertEqual(len(k), 3)
            self.assertIsInstance(k[0], str)
            self.assertIsInstance(k[1], str)
            self.assertIsInstance(k[2], int)
            self.assertIsInstance(v, PassiveResistEntry)

    def test_each_seeded_champ_present(self):
        cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        for c in _SEEDED:
            self.assertIn(c, cids)

    def test_every_entry_has_a_note(self):
        for v in _PASSIVE_RESIST_OVERRIDES.values():
            self.assertTrue(v.note.strip())

    def test_active_prob_constant(self):
        self.assertAlmostEqual(_ACTIVE_RESIST_PROB, 0.3)


class ResistGrantsResolverTests(unittest.TestCase):
    def test_default_off_is_zero(self):
        for c in _SEEDED:
            self.assertEqual(resist_grants(c, 11, False), (0.0, 0.0))

    def test_no_entry_champ_zero_even_on(self):
        for c in ("Caitlyn", "Annie", "Lux"):
            self.assertEqual(resist_grants(c, 11, True), (0.0, 0.0))

    def test_garen_cap_permanent(self):
        self.assertEqual(resist_grants("Garen", 11, True), (30.0, 30.0))
        # permanent (prob 1.0) -> level-invariant
        self.assertEqual(resist_grants("Garen", 1, True), (30.0, 30.0))
        self.assertEqual(resist_grants("Garen", 18, True), (30.0, 30.0))

    def test_wukong_armor_only_level_scaled(self):
        a1, m1 = resist_grants("MonkeyKing", 1, True)
        a18, m18 = resist_grants("MonkeyKing", 18, True)
        self.assertAlmostEqual(a1, 6.0)
        self.assertAlmostEqual(a18, 10.0)
        self.assertEqual(m1, 0.0)  # armor-only, no MR
        self.assertEqual(m18, 0.0)
        self.assertTrue(6.0 < resist_grants("MonkeyKing", 9, True)[0] < 10.0)

    def test_shyvana_flat_base(self):
        self.assertEqual(resist_grants("Shyvana", 11, True), (5.0, 5.0))

    def test_sejuani_flat_base(self):
        self.assertEqual(resist_grants("Sejuani", 11, True), (10.0, 10.0))

    def test_gwen_active_amortized(self):
        a, m = resist_grants("Gwen", 11, True)
        self.assertAlmostEqual(a, 22.0 * 0.3)
        self.assertAlmostEqual(m, 22.0 * 0.3)

    def test_pantheon_level_scaled_active(self):
        # 5:30 level-lerped * 0.3
        lo_a, lo_m = resist_grants("Pantheon", 1, True)
        hi_a, hi_m = resist_grants("Pantheon", 18, True)
        self.assertAlmostEqual(lo_a, 5.0 * 0.3)
        self.assertAlmostEqual(hi_a, 30.0 * 0.3)
        self.assertAlmostEqual(lo_m, lo_a)
        self.assertAlmostEqual(hi_m, hi_a)
        self.assertTrue(lo_a < resist_grants("Pantheon", 11, True)[0] < hi_a)


class ValueAtLevelTests(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(_value_at_level(30.0, 11, False), 30.0)

    def test_level_scaled_tuple(self):
        t = _lerp_per_level(6.0, 10.0)
        self.assertAlmostEqual(_value_at_level(t, 1, True), 6.0)
        self.assertAlmostEqual(_value_at_level(t, 18, True), 10.0)

    def test_level_clamp(self):
        t = _lerp_per_level(5.0, 30.0)
        self.assertAlmostEqual(_value_at_level(t, 0, True), 5.0)
        self.assertAlmostEqual(_value_at_level(t, 99, True), 30.0)


class ComputeEhpByteIdenticalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_default_flag_is_off(self):
        # explicit-False == default-omitted for every seeded champ
        for c in _SEEDED:
            a = compute_ehp(self.snap, c, 11, [], mode="SR")
            b = compute_ehp(self.snap, c, 11, [], mode="SR", apply_passive_resist=False)
            self.assertEqual(a.blended_ehp, b.blended_ehp)
            self.assertEqual(a.passive_resist_armor, 0.0)
            self.assertEqual(a.passive_resist_mr, 0.0)

    def test_no_entry_champ_byte_identical_flag_on(self):
        off = compute_ehp(self.snap, "Caitlyn", 11, [], mode="SR")
        on = compute_ehp(self.snap, "Caitlyn", 11, [], mode="SR", apply_passive_resist=True)
        self.assertEqual(off.blended_ehp, on.blended_ehp)
        self.assertEqual(on.passive_resist_armor, 0.0)
        self.assertEqual(on.passive_resist_mr, 0.0)


class ComputeEhpFlagOnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_garen_resist_raises_ehp_reported_stats_unchanged(self):
        off = compute_ehp(self.snap, "Garen", 11, [], mode="SR")
        on = compute_ehp(self.snap, "Garen", 11, [], mode="SR", apply_passive_resist=True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        # reported armor/mr stay the RESOLVED build stats; grant surfaced separately
        self.assertEqual(on.armor, off.armor)
        self.assertEqual(on.mr, off.mr)
        self.assertEqual(on.passive_resist_armor, 30.0)
        self.assertEqual(on.passive_resist_mr, 30.0)

    def test_gwen_active_smaller_than_garen_permanent(self):
        gwen = compute_ehp(self.snap, "Gwen", 11, [], mode="SR", apply_passive_resist=True)
        self.assertAlmostEqual(gwen.passive_resist_armor, 6.6)

    def test_to_dict_has_resist_keys(self):
        on = compute_ehp(self.snap, "Garen", 11, [], mode="SR", apply_passive_resist=True)
        d = on.to_dict()
        self.assertIn("passive_resist_armor", d)
        self.assertIn("passive_resist_mr", d)
        self.assertEqual(d["passive_resist_armor"], 30.0)

    def test_note_appended_when_on(self):
        on = compute_ehp(self.snap, "Garen", 11, [], mode="SR", apply_passive_resist=True)
        self.assertTrue(any("passive_resist" in n for n in on.notes))
        off = compute_ehp(self.snap, "Garen", 11, [], mode="SR")
        self.assertFalse(any("passive_resist" in n for n in off.notes))


class HybridWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_hybrid_default_byte_identical(self):
        a = compute_hybrid(self.snap, "Garen", 11, [], mode="SR")
        b = compute_hybrid(self.snap, "Garen", 11, [], mode="SR", apply_passive_resist=False)
        self.assertEqual(a.hybrid_score, b.hybrid_score)

    def test_hybrid_resist_raises_score(self):
        off = compute_hybrid(self.snap, "Garen", 11, [], mode="SR")
        on = compute_hybrid(self.snap, "Garen", 11, [], mode="SR", apply_passive_resist=True)
        self.assertGreater(on.hybrid_score, off.hybrid_score)

    def test_hybrid_no_entry_champ_byte_identical(self):
        off = compute_hybrid(self.snap, "Caitlyn", 11, [], mode="SR")
        on = compute_hybrid(self.snap, "Caitlyn", 11, [], mode="SR", apply_passive_resist=True)
        self.assertEqual(off.hybrid_score, on.hybrid_score)


class RankWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_rank_default_byte_identical(self):
        a = rank_items_by_ehp(self.snap, "Garen", 11, [], mode="SR", top_n=10)
        b = rank_items_by_ehp(
            self.snap, "Garen", 11, [], mode="SR", top_n=10, apply_passive_resist=False
        )
        self.assertEqual(
            [r.item_id for r in a.ranked], [r.item_id for r in b.ranked]
        )

    def test_rank_flag_on_runs_and_returns_valid(self):
        # flag-on MAY re-rank (resist add goes through the non-linear armor
        # curve) - assert it produces a valid non-empty ranking, not that the
        # order matches.
        on = rank_items_by_ehp(
            self.snap, "Garen", 11, [], mode="SR", top_n=10, apply_passive_resist=True
        )
        self.assertTrue(on.ranked)
        for r in on.ranked:
            self.assertGreaterEqual(r.new_ehp, 0.0)


class ExclusionDocTests(unittest.TestCase):
    """The documented EXCLUSIONS stay OUT of the seeded registry."""

    def test_excluded_champs_absent(self):
        cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        # revive / ball-attached - the documented NEGATIVES that each still need a
        # DIFFERENT seam. (Olaf/Rammus/Kennen/Nasus/Hecarim/Graves -> SEEDED
        # rank_scaled by item 267; Malphite/Taric/Poppy/Rell -> SEEDED percent-mode
        # by item 268; Singed/Braum/Leona/Jax were the unlabeled-multi-stat-block
        # exclusion -> SEEDED flat-base by item 270; Jayce R was the form-gated
        # exclusion -> SEEDED form-occupancy by item 271; Thresh P was the per-
        # stack-unbounded exclusion -> SEEDED per_stack by item 272; all no longer
        # exclusions.)
        for c in ("Anivia", "Orianna"):
            self.assertNotIn(c, cids)


class EngineVersionTests(unittest.TestCase):
    def test_engine_pin(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.99.0")
        self.assertEqual(ENGINE_VERSION, "1.99.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_ascii(self):
        import agents.daemon_slayer._passive_resist_overrides as mod

        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                raw.decode("ascii")
            except UnicodeDecodeError as e:  # pragma: no cover
                self.fail(f"non-ASCII in {path}: {e}")


if __name__ == "__main__":
    unittest.main()
