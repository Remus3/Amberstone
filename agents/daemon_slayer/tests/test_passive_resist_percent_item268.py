"""item 268 (ENGINE 1.96.0) - PERCENT-OF-RESIST mode for the effects-text
RESIST-STAT grant registry (the candidate-B base-vs-bonus split named in items
264/267 as the documented percent-mode exclusion).

A percent-of-resist grant is bonus armor / MR equal to a PERCENT of the
champion's OWN resist STAT (NOT a flat add) - e.g. Malphite W "10/15/20/25/30%
of his armor", Poppy W "12% of total armor and MR", Rell W "15% bonus armor".
The flat-add seam (items 264/267) could not express it; this lift adds
``armor_pct`` / ``mr_pct`` + a ``pct_base`` selector ("total" | "bonus") to
``PassiveResistEntry`` and threads the RESOLVED build resists (total + base) into
``resist_grants`` so the percent resolves against the build's armor / MR.

Ground-truth (patch 16.11.1, verbatim ``effects_descriptions`` / parsed blocks):
  - Malphite W Thunderclap: "Bonus Armor" [10,15,20,25,30] % armor (% TOTAL, ARMOR
    ONLY); Granite-Shield "Increased" tier omitted. PERMANENT prob 1.0.
  - Taric W Bastion: "Bonus Armor" [6,7,8,9,10] % of Taric's armor (% TOTAL, ARMOR
    ONLY). PERMANENT prob 1.0.
  - Poppy W Steadfast Presence: "12% total armor + total MR, doubled to 24% below
    40% HP" (% TOTAL, FLAT). low-HP double omitted. PERMANENT prob 1.0.
  - Rammus W Defensive Ball Curl: "% total armor + % total MR" [30,37.5,45,52.5,60]
    (% TOTAL) - the %-half item 267 OMITTED (flat half [27..47] already seeded);
    7s active amortized 0.3.
  - Rell W (Mount Up form, Dismounted passive): "15% bonus armor + 15% bonus MR"
    (% BONUS, FLAT). Dismounted = steady-state combat stance, prob 1.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_resist_overrides import (
    _ACTIVE_RESIST_PROB,
    _PASSIVE_RESIST_OVERRIDES,
    PassiveResistEntry,
    resist_grants,
)

_NEW_PERCENT = ("Malphite", "Taric", "Poppy", "Rell")  # Rammus already seeded (267)


class SchemaTests(unittest.TestCase):
    def test_entry_has_percent_fields(self):
        e = PassiveResistEntry()
        self.assertEqual(e.armor_pct, 0.0)
        self.assertEqual(e.mr_pct, 0.0)
        self.assertEqual(e.pct_base, "total")

    def test_registry_grew(self):
        # 6 (item264) + 6 (item267) + 4 NEW percent champs = 16; Rammus extended
        # in place (no new key).
        self.assertGreaterEqual(len(_PASSIVE_RESIST_OVERRIDES), 16)

    def test_new_percent_entries_present(self):
        self.assertIn(("Malphite", "W", 0), _PASSIVE_RESIST_OVERRIDES)
        self.assertIn(("Taric", "W", 0), _PASSIVE_RESIST_OVERRIDES)
        self.assertIn(("Poppy", "W", 0), _PASSIVE_RESIST_OVERRIDES)
        self.assertIn(("Rell", "W", 1), _PASSIVE_RESIST_OVERRIDES)

    def test_pct_base_values_legal(self):
        for k, e in _PASSIVE_RESIST_OVERRIDES.items():
            self.assertIn(e.pct_base, ("total", "bonus"), msg=str(k))

    def test_notes_nonempty(self):
        for c in _NEW_PERCENT:
            for k, e in _PASSIVE_RESIST_OVERRIDES.items():
                if k[0] == c:
                    self.assertTrue(e.note.strip(), msg=str(k))


class ResolverPercentTests(unittest.TestCase):
    def test_malphite_pct_of_total_armor_only(self):
        # W rank 2 at L11 -> 20% of TOTAL armor; ARMOR ONLY.
        a, m = resist_grants(
            "Malphite", 11, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a, 0.20 * 200.0)
        self.assertEqual(m, 0.0)

    def test_malphite_unlearned_w_is_zero(self):
        a, m = resist_grants(
            "Malphite", 1, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertEqual(a, 0.0)
        self.assertEqual(m, 0.0)

    def test_taric_pct_of_total_armor_only(self):
        # W rank 4 at L16 -> 10% of TOTAL armor; ARMOR ONLY.
        a, m = resist_grants(
            "Taric", 16, True,
            total_armor=120.0, total_mr=60.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a, 0.10 * 120.0)
        self.assertEqual(m, 0.0)

    def test_poppy_flat_pct_of_total_both(self):
        # flat 12% of TOTAL armor + MR; level-invariant; prob 1.0.
        a, m = resist_grants(
            "Poppy", 11, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a, 0.12 * 200.0)
        self.assertAlmostEqual(m, 0.12 * 100.0)
        # level-invariant (flat percent, not rank-scaled)
        a1, m1 = resist_grants(
            "Poppy", 1, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a1, a)
        self.assertAlmostEqual(m1, m)

    def test_rammus_flat_plus_percent_amortized(self):
        # L18 -> W rank 4: flat 47 + 60% of TOTAL, BOTH armor + MR, * 0.3 active.
        a, m = resist_grants(
            "Rammus", 18, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a, (47.0 + 0.60 * 200.0) * _ACTIVE_RESIST_PROB)
        self.assertAlmostEqual(m, (47.0 + 0.60 * 100.0) * _ACTIVE_RESIST_PROB)

    def test_rell_pct_of_bonus_resist(self):
        # form 1 Dismounted passive: 15% of BONUS armor + MR; prob 1.0.
        a, m = resist_grants(
            "Rell", 11, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a, 0.15 * (200.0 - 80.0))
        self.assertAlmostEqual(m, 0.15 * (100.0 - 50.0))

    def test_rell_itemless_bonus_zero(self):
        # % of BONUS -> 0 with no bonus resist (itemless).
        a, m = resist_grants(
            "Rell", 11, True,
            total_armor=80.0, total_mr=50.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertEqual(a, 0.0)
        self.assertEqual(m, 0.0)

    def test_default_off_zero_for_new(self):
        for c in _NEW_PERCENT:
            self.assertEqual(
                resist_grants(c, 16, False, total_armor=200.0, total_mr=100.0),
                (0.0, 0.0),
            )


class BackCompatTests(unittest.TestCase):
    def test_no_kwargs_percent_entry_contributes_zero(self):
        # legacy positional call (no resist kwargs) -> percent * 0 == 0.
        for c in _NEW_PERCENT:
            self.assertEqual(resist_grants(c, 16, True), (0.0, 0.0))

    def test_no_kwargs_rammus_keeps_flat_half(self):
        # Rammus extended in place: flat half survives a no-kwargs call (item 267
        # contract); percent half * 0 == 0.
        a, m = resist_grants("Rammus", 18, True)
        self.assertAlmostEqual(a, 47.0 * _ACTIVE_RESIST_PROB)
        self.assertAlmostEqual(m, 47.0 * _ACTIVE_RESIST_PROB)


class ComputeEhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        cls.armor_build = [3068, 3075]  # Sunfire + Thornmail

    def test_malphite_flag_off_byte_identical(self):
        off = compute_ehp(self.snap, "Malphite", 11, self.armor_build, mode="SR")
        on_off = compute_ehp(self.snap, "Malphite", 11, self.armor_build, mode="SR", apply_passive_resist=False)
        self.assertEqual(off.blended_ehp, on_off.blended_ehp)
        self.assertEqual(on_off.passive_resist_armor, 0.0)

    def test_malphite_flag_on_raises_ehp(self):
        off = compute_ehp(self.snap, "Malphite", 11, self.armor_build, mode="SR")
        on = compute_ehp(self.snap, "Malphite", 11, self.armor_build, mode="SR", apply_passive_resist=True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        # 20% of total armor (W rank 2 @ L11), ARMOR ONLY
        self.assertAlmostEqual(on.passive_resist_armor, 0.20 * on.armor)
        self.assertEqual(on.passive_resist_mr, 0.0)
        # reported resolved armor unchanged
        self.assertEqual(on.armor, off.armor)

    def test_poppy_flag_on_both_resists(self):
        off = compute_ehp(self.snap, "Poppy", 11, self.armor_build, mode="SR")
        on = compute_ehp(self.snap, "Poppy", 11, self.armor_build, mode="SR", apply_passive_resist=True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        self.assertAlmostEqual(on.passive_resist_armor, 0.12 * on.armor)
        self.assertAlmostEqual(on.passive_resist_mr, 0.12 * on.mr)

    def test_rammus_flag_on_percent_fires(self):
        on = compute_ehp(self.snap, "Rammus", 18, self.armor_build, mode="SR", apply_passive_resist=True)
        # flat 47 + 60% total, * 0.3
        self.assertAlmostEqual(on.passive_resist_armor, (47.0 + 0.60 * on.armor) * _ACTIVE_RESIST_PROB)

    def test_rell_flag_on_bonus_percent(self):
        # mixed armor + MR build so BOTH bonus resists are non-zero (Sunfire armor
        # + Force of Nature MR); the pure-armor self.armor_build gives 0 bonus MR.
        mixed = [3068, 4401]
        off = compute_ehp(self.snap, "Rell", 11, mixed, mode="SR")
        on = compute_ehp(self.snap, "Rell", 11, mixed, mode="SR", apply_passive_resist=True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        # 15% of BONUS armor / MR (build deltas from base) -> both positive
        self.assertGreater(on.passive_resist_armor, 0.0)
        self.assertGreater(on.passive_resist_mr, 0.0)

    def test_rell_itemless_flag_on_byte_identical(self):
        off = compute_ehp(self.snap, "Rell", 11, [], mode="SR")
        on = compute_ehp(self.snap, "Rell", 11, [], mode="SR", apply_passive_resist=True)
        # % of BONUS resist -> 0 itemless -> byte-identical
        self.assertEqual(off.blended_ehp, on.blended_ehp)

    def test_unseeded_champ_flag_on_byte_identical(self):
        off = compute_ehp(self.snap, "Caitlyn", 11, self.armor_build, mode="SR")
        on = compute_ehp(self.snap, "Caitlyn", 11, self.armor_build, mode="SR", apply_passive_resist=True)
        self.assertEqual(off.blended_ehp, on.blended_ehp)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.259.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self):
        import pathlib
        from agents.daemon_slayer import _passive_resist_overrides as mod
        raw = pathlib.Path(mod.__file__).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(nonascii, [], msg="non-ASCII bytes in _passive_resist_overrides.py")


if __name__ == "__main__":
    unittest.main()
