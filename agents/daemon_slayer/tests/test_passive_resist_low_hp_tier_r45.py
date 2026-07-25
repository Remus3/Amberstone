"""R45 (ENGINE 1.158.0) - low-HP DOUBLED percent tier for the effects-text
RESIST-STAT grant registry (Poppy W "doubled to 24% below 40% max HP").

item 268 (ENGINE 1.96.0) shipped the steady-state PERCENT-OF-RESIST mode:
``armor_pct`` / ``mr_pct`` + a ``pct_base`` selector resolve a percent of the
champion's OWN build resist. Poppy W Steadfast Presence is seeded there at the
above-40%-HP value (+12% of TOTAL armor + MR); the Meraki-16.13.1 truth is
"increases total armor and total magic resistance by 12%, DOUBLED to 24% while
below 40% maximum health." R45 adds the INCREMENTAL low-HP half: three
END-appended fields (``low_hp_pct_armor`` / ``low_hp_pct_mr`` /
``low_hp_threshold``) and a new caster-HP-fraction input to ``resist_grants``
(``caster_current_hp_pct``, default 1.0 = full HP). When the caster HP fraction
is strictly below the threshold, the incremental percent ADDS on top of the base
percent (12% + 12% = 24% below 40% HP).

Default-OFF + byte-identical (charter section 5): ``caster_current_hp_pct``
defaults to 1.0 (full HP), and 1.0 < 0.40 is False, so the low-HP tier is dormant
and every pre-R45 call is byte-identical. The tier lives INSIDE the existing
percent block (a "doubled" tier requires a base percent), so ``res_a`` / ``res_m``
are defined. An unseeded champ (no low_hp fields) and Rell W (no low-HP tier) are
byte-identical at any ``caster_current_hp_pct``.

This is the same OFFLINE defaulted-scalar posture as R39's current-HP ramp (a
gated default-OFF input, NOT the operator-CLOSED conditional-target-state arc,
which was live-target PLUMBING). The live default-ON flip (a survivability /
draft consumer passing the live champion HP fraction) is EXCLUDED from this run.

Ground-truth (patch 16.13.1, verbatim Meraki spell text):
  - Poppy W Steadfast Presence (Stubborn to a Fault): "increases total armor and
    total magic resistance by 12%, doubled to 24% while below 40% maximum
    health." -> base 12% (item 268) + incremental 12% below 40% HP (R45). % TOTAL.
  - Rell W (Mount Up form, Dismounted passive): "15% bonus armor + 15% bonus MR"
    (% BONUS) - NO low-HP tier; byte-identical at every caster_current_hp_pct.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_resist_overrides import (
    _PASSIVE_RESIST_OVERRIDES,
    PassiveResistEntry,
    resist_grants,
)


class SchemaTests(unittest.TestCase):
    def test_entry_has_low_hp_fields_default_zero(self):
        e = PassiveResistEntry()
        self.assertEqual(e.low_hp_pct_armor, 0.0)
        self.assertEqual(e.low_hp_pct_mr, 0.0)
        self.assertEqual(e.low_hp_threshold, 0.0)

    def test_poppy_entry_seeded_with_low_hp_tier(self):
        e = _PASSIVE_RESIST_OVERRIDES[("Poppy", "W", 0)]
        self.assertEqual(e.low_hp_pct_armor, 12.0)
        self.assertEqual(e.low_hp_pct_mr, 12.0)
        self.assertEqual(e.low_hp_threshold, 0.40)

    def test_poppy_note_drops_omitted(self):
        e = _PASSIVE_RESIST_OVERRIDES[("Poppy", "W", 0)]
        self.assertNotIn("omitted", e.note.lower())


class ResolverDoubledTierTests(unittest.TestCase):
    def test_poppy_doubled_below_40_hp(self):
        # base 12% + incremental 12% = 24% below 40% HP.
        a, m = resist_grants(
            "Poppy", 11, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
            caster_current_hp_pct=0.30,
        )
        self.assertAlmostEqual(a, 0.24 * 200.0)
        self.assertAlmostEqual(m, 0.24 * 100.0)

    def test_poppy_full_hp_byte_identical_to_base(self):
        # caster_current_hp_pct=1.0 -> dormant -> base 12% only.
        a, m = resist_grants(
            "Poppy", 11, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
            caster_current_hp_pct=1.0,
        )
        self.assertAlmostEqual(a, 0.12 * 200.0)
        self.assertAlmostEqual(m, 0.12 * 100.0)

    def test_poppy_kwarg_omitted_byte_identical_to_base(self):
        # kwarg omitted entirely -> default 1.0 -> base 12% only.
        a, m = resist_grants(
            "Poppy", 11, True,
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        self.assertAlmostEqual(a, 0.12 * 200.0)
        self.assertAlmostEqual(m, 0.12 * 100.0)

    def test_threshold_boundary_strict_less_than(self):
        kw = dict(
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        # exactly AT 0.40 -> NOT below (strict <) -> base 12%.
        a40, m40 = resist_grants("Poppy", 11, True, caster_current_hp_pct=0.40, **kw)
        self.assertAlmostEqual(a40, 0.12 * 200.0)
        self.assertAlmostEqual(m40, 0.12 * 100.0)
        # 0.41 -> above -> base 12%.
        a41, m41 = resist_grants("Poppy", 11, True, caster_current_hp_pct=0.41, **kw)
        self.assertAlmostEqual(a41, 0.12 * 200.0)
        self.assertAlmostEqual(m41, 0.12 * 100.0)
        # 0.39 -> below -> doubled 24%.
        a39, m39 = resist_grants("Poppy", 11, True, caster_current_hp_pct=0.39, **kw)
        self.assertAlmostEqual(a39, 0.24 * 200.0)
        self.assertAlmostEqual(m39, 0.24 * 100.0)

    def test_default_off_zero_with_low_hp(self):
        # apply_passive_resist False short-circuits even with a low HP fraction.
        self.assertEqual(
            resist_grants(
                "Poppy", 11, False,
                total_armor=200.0, total_mr=100.0, caster_current_hp_pct=0.30,
            ),
            (0.0, 0.0),
        )


class UnseededAndRellByteIdenticalTests(unittest.TestCase):
    def test_unseeded_champ_byte_identical_any_hp(self):
        # Malphite has armor_pct but NO low_hp fields -> identical at any HP frac.
        kw = dict(
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        base = resist_grants("Malphite", 11, True, **kw)
        for hp in (1.0, 0.41, 0.40, 0.39, 0.10):
            self.assertEqual(
                resist_grants("Malphite", 11, True, caster_current_hp_pct=hp, **kw),
                base, msg=f"Malphite@{hp}",
            )

    def test_rammus_byte_identical_any_hp(self):
        # Rammus (flat + percent, no low_hp) is byte-identical at any HP frac.
        kw = dict(
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        base = resist_grants("Rammus", 18, True, **kw)
        for hp in (1.0, 0.40, 0.39, 0.10):
            self.assertEqual(
                resist_grants("Rammus", 18, True, caster_current_hp_pct=hp, **kw),
                base, msg=f"Rammus@{hp}",
            )

    def test_rell_byte_identical_any_hp(self):
        # Rell W (15% of BONUS) carries NO low-HP tier -> identical at any HP frac.
        kw = dict(
            total_armor=200.0, total_mr=100.0, base_armor=80.0, base_mr=50.0,
        )
        base = resist_grants("Rell", 11, True, **kw)
        self.assertAlmostEqual(base[0], 0.15 * (200.0 - 80.0))
        self.assertAlmostEqual(base[1], 0.15 * (100.0 - 50.0))
        for hp in (1.0, 0.40, 0.39, 0.10):
            self.assertEqual(
                resist_grants("Rell", 11, True, caster_current_hp_pct=hp, **kw),
                base, msg=f"Rell@{hp}",
            )


class ComputeEhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        cls.armor_build = [3068, 3075]  # Sunfire + Thornmail

    def test_poppy_flag_off_byte_identical_any_hp(self):
        # off-path never reads caster_current_hp_pct.
        off = compute_ehp(self.snap, "Poppy", 11, self.armor_build, mode="SR")
        off_default = compute_ehp(
            self.snap, "Poppy", 11, self.armor_build, mode="SR",
            apply_passive_resist=False,
        )
        off_low = compute_ehp(
            self.snap, "Poppy", 11, self.armor_build, mode="SR",
            apply_passive_resist=False, caster_current_hp_pct=0.30,
        )
        self.assertEqual(off.blended_ehp, off_default.blended_ehp)
        self.assertEqual(off.blended_ehp, off_low.blended_ehp)
        self.assertEqual(off_low.passive_resist_armor, 0.0)
        self.assertEqual(off_low.passive_resist_mr, 0.0)

    def test_poppy_flag_on_full_hp_equals_pre_r45_default(self):
        # apply_passive_resist=True with default full HP == the item-268 result.
        on_default = compute_ehp(
            self.snap, "Poppy", 11, self.armor_build, mode="SR",
            apply_passive_resist=True,
        )
        on_full = compute_ehp(
            self.snap, "Poppy", 11, self.armor_build, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=1.0,
        )
        self.assertEqual(on_default.blended_ehp, on_full.blended_ehp)
        self.assertAlmostEqual(on_default.passive_resist_armor, 0.12 * on_default.armor)
        self.assertAlmostEqual(on_default.passive_resist_mr, 0.12 * on_default.mr)

    def test_poppy_flag_on_low_hp_raises_ehp(self):
        on_full = compute_ehp(
            self.snap, "Poppy", 11, self.armor_build, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=1.0,
        )
        on_low = compute_ehp(
            self.snap, "Poppy", 11, self.armor_build, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=0.30,
        )
        self.assertGreater(on_low.blended_ehp, on_full.blended_ehp)
        # physical + magical EHP both strictly greater below 40% HP.
        self.assertGreater(on_low.physical_ehp, on_full.physical_ehp)
        self.assertGreater(on_low.magical_ehp, on_full.magical_ehp)
        # 24% of resolved armor/MR below 40% HP.
        self.assertAlmostEqual(on_low.passive_resist_armor, 0.24 * on_low.armor)
        self.assertAlmostEqual(on_low.passive_resist_mr, 0.24 * on_low.mr)

    def test_unseeded_champ_flag_on_byte_identical_any_hp(self):
        full = compute_ehp(
            self.snap, "Caitlyn", 11, self.armor_build, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=1.0,
        )
        low = compute_ehp(
            self.snap, "Caitlyn", 11, self.armor_build, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=0.30,
        )
        self.assertEqual(full.blended_ehp, low.blended_ehp)

    def test_rell_flag_on_byte_identical_any_hp(self):
        # Rell has a percent tier but no low-HP half -> identical at any HP frac.
        mixed = [3068, 4401]
        full = compute_ehp(
            self.snap, "Rell", 11, mixed, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=1.0,
        )
        low = compute_ehp(
            self.snap, "Rell", 11, mixed, mode="SR",
            apply_passive_resist=True, caster_current_hp_pct=0.30,
        )
        self.assertEqual(full.blended_ehp, low.blended_ehp)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.246.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self):
        import pathlib
        raw = pathlib.Path(__file__).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(nonascii, [], msg="non-ASCII bytes in test_passive_resist_low_hp_tier_r45.py")

    def test_resolver_module_ascii(self):
        import pathlib
        from agents.daemon_slayer import _passive_resist_overrides as mod
        raw = pathlib.Path(mod.__file__).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(nonascii, [], msg="non-ASCII bytes in _passive_resist_overrides.py")


if __name__ == "__main__":
    unittest.main()
