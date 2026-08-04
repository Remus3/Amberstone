"""Item 267 - rank-scaled "read the parsed block" RESIST-STAT grant lift.

Extends the item-264 effects-text RESIST-STAT registry
(``_passive_resist_overrides.py``) with grants whose VALUE is NOT in the prose
("gains bonus armor and bonus magic resistance" with no inline number) but lives
in a parsed Meraki ``[other]`` block indexed by ABILITY RANK. The new
``rank_scaled`` flag resolves the ability rank from the champion level via
``ability_dps.rank_at_level(key, level)`` - deterministic for ults (R 6/11/16),
engine-default Q>W>E priority for basics; an unlearned ability grants 0.0.

Seeded 6 (block-value): Olaf R [10/15/20] permanent, Nasus R [40/55/70] active,
Kennen R [20/40/60] active, Hecarim W [5..25] active, Rammus W FLAT [27..47]
active (%-of-total half omitted), Graves E [32..128] armor-only at-cap.

``apply_passive_resist`` defaults False -> byte-identical to ENGINE 1.94.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_resist_overrides import (
    _ACTIVE_RESIST_PROB,
    _PASSIVE_RESIST_OVERRIDES,
    _value_at_level,
    resist_grants,
)

_NEW = ("Olaf", "Nasus", "Kennen", "Hecarim", "Rammus", "Graves")


class RegistryShapeTests(unittest.TestCase):
    def test_total_twelve_entries(self):
        self.assertGreaterEqual(len(_PASSIVE_RESIST_OVERRIDES), 12)  # item 268 adds percent-of-resist entries

    def test_six_new_champs_present_and_rank_scaled(self):
        by_cid = {k[0]: v for k, v in _PASSIVE_RESIST_OVERRIDES.items()}
        for c in _NEW:
            self.assertIn(c, by_cid)
            self.assertTrue(by_cid[c].rank_scaled, f"{c} should be rank_scaled")

    def test_rank_and_level_scaled_mutually_exclusive(self):
        for v in _PASSIVE_RESIST_OVERRIDES.values():
            self.assertFalse(v.rank_scaled and v.level_scaled)

    def test_new_entries_carry_per_rank_tuples(self):
        by_cid = {k[0]: v for k, v in _PASSIVE_RESIST_OVERRIDES.items()}
        for c in _NEW:
            self.assertIsInstance(by_cid[c].armor, tuple)

    def test_new_entries_have_notes(self):
        by_cid = {k[0]: v for k, v in _PASSIVE_RESIST_OVERRIDES.items()}
        for c in _NEW:
            self.assertTrue(by_cid[c].note.strip())


class RankScaledResolverTests(unittest.TestCase):
    def test_olaf_r_permanent_rank_scaled(self):
        # R unlocks 6/11/16 -> 10/15/20; below 6 not learned -> 0; prob 1.0.
        self.assertEqual(resist_grants("Olaf", 5, True), (0.0, 0.0))
        self.assertEqual(resist_grants("Olaf", 6, True), (10.0, 10.0))
        self.assertEqual(resist_grants("Olaf", 11, True), (15.0, 15.0))
        self.assertEqual(resist_grants("Olaf", 16, True), (20.0, 20.0))
        self.assertEqual(resist_grants("Olaf", 18, True), (20.0, 20.0))

    def test_kennen_r_active_amortized(self):
        # 20/40/60 by R rank * 0.3 active midpoint.
        a6, m6 = resist_grants("Kennen", 6, True)
        self.assertAlmostEqual(a6, 20.0 * _ACTIVE_RESIST_PROB)
        self.assertAlmostEqual(m6, 20.0 * _ACTIVE_RESIST_PROB)
        a16, _ = resist_grants("Kennen", 16, True)
        self.assertAlmostEqual(a16, 60.0 * _ACTIVE_RESIST_PROB)

    def test_nasus_r_active(self):
        a16, m16 = resist_grants("Nasus", 16, True)
        self.assertAlmostEqual(a16, 70.0 * _ACTIVE_RESIST_PROB)
        self.assertAlmostEqual(m16, 70.0 * _ACTIVE_RESIST_PROB)

    def test_hecarim_w_basic_rank_scaled(self):
        # W = priority_2; max rank value 25 * 0.3 at level 18.
        a18, m18 = resist_grants("Hecarim", 18, True)
        self.assertAlmostEqual(a18, 25.0 * _ACTIVE_RESIST_PROB)
        self.assertAlmostEqual(m18, 25.0 * _ACTIVE_RESIST_PROB)

    def test_rammus_w_flat_half_only(self):
        # FLAT [27..47] seeded; %-of-total half omitted; active 0.3.
        a18, m18 = resist_grants("Rammus", 18, True)
        self.assertAlmostEqual(a18, 47.0 * _ACTIVE_RESIST_PROB)
        self.assertAlmostEqual(m18, 47.0 * _ACTIVE_RESIST_PROB)

    def test_graves_e_armor_only_at_cap(self):
        # E = priority_3; armor-only (mr 0); seeded at 8-stack cap; prob 1.0.
        a18, m18 = resist_grants("Graves", 18, True)
        self.assertAlmostEqual(a18, 128.0)
        self.assertEqual(m18, 0.0)

    def test_default_off_zero_for_new(self):
        for c in _NEW:
            self.assertEqual(resist_grants(c, 16, False), (0.0, 0.0))


class BackCompatResolverTests(unittest.TestCase):
    def test_flat_positional_call_unchanged(self):
        self.assertEqual(_value_at_level(30.0, 11, False), 30.0)

    def test_level_scaled_positional_call_unchanged(self):
        t = tuple(6.0 + (10.0 - 6.0) * i / 17.0 for i in range(18))
        self.assertAlmostEqual(_value_at_level(t, 1, True), 6.0)
        self.assertAlmostEqual(_value_at_level(t, 18, True), 10.0)

    def test_rank_scaled_keyword_resolves(self):
        v = _value_at_level((10.0, 15.0, 20.0), 11, False, key="R", rank_scaled=True)
        self.assertEqual(v, 15.0)

    def test_rank_scaled_unlearned_is_zero(self):
        v = _value_at_level((10.0, 15.0, 20.0), 5, False, key="R", rank_scaled=True)
        self.assertEqual(v, 0.0)


class ComputeEhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_olaf_flag_off_byte_identical(self):
        off = compute_ehp(self.snap, "Olaf", 16, [], mode="SR")
        on_off = compute_ehp(self.snap, "Olaf", 16, [], mode="SR", apply_passive_resist=False)
        self.assertEqual(off.blended_ehp, on_off.blended_ehp)
        self.assertEqual(on_off.passive_resist_armor, 0.0)

    def test_olaf_flag_on_raises_ehp_and_surfaces_grant(self):
        off = compute_ehp(self.snap, "Olaf", 16, [], mode="SR")
        on = compute_ehp(self.snap, "Olaf", 16, [], mode="SR", apply_passive_resist=True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        # permanent 20/20 at R rank 3 (lvl 16)
        self.assertAlmostEqual(on.passive_resist_armor, 20.0)
        self.assertAlmostEqual(on.passive_resist_mr, 20.0)
        # reported resolved armor unchanged (grant surfaced separately)
        self.assertEqual(on.armor, off.armor)

    def test_graves_flag_on_armor_only(self):
        on = compute_ehp(self.snap, "Graves", 18, [], mode="SR", apply_passive_resist=True)
        self.assertAlmostEqual(on.passive_resist_armor, 128.0)
        self.assertEqual(on.passive_resist_mr, 0.0)

    def test_olaf_below_ult_no_grant(self):
        on = compute_ehp(self.snap, "Olaf", 5, [], mode="SR", apply_passive_resist=True)
        self.assertEqual(on.passive_resist_armor, 0.0)

    def test_unseeded_champ_flag_on_byte_identical(self):
        off = compute_ehp(self.snap, "Caitlyn", 11, [], mode="SR")
        on = compute_ehp(self.snap, "Caitlyn", 11, [], mode="SR", apply_passive_resist=True)
        self.assertEqual(off.blended_ehp, on.blended_ehp)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.272.0")


class AsciiTests(unittest.TestCase):
    def test_no_banned_codepoints(self):
        import pathlib
        from agents.daemon_slayer import _passive_resist_overrides as mod
        text = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        banned = {0x2014: "em", 0x2013: "en", 0x2018: "lq",
                  0x2019: "rq", 0x201C: "ldq", 0x201D: "rdq"}
        hits = [n for cp, n in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
