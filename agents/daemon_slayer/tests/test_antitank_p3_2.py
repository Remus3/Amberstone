"""P3.2 (item 315) - anti-tank dynamic %HP scaling via injected ResolvedStats.

Item 308 shipped the anti-tank scorer with hand-authored 0..1 magnitudes that are
deliberately STATIC (a qualitative "how reliably this melts a tank", not a damage
number). P3.2 is the operator-accepted schema lift: ``AntiTankEntry`` gains
optional ``ap_ratio`` / ``ad_ratio`` coefficients (default 0.0) and
``compute_antitank`` / ``_mechanism_value`` take an optional ``stats`` object
(a ``ResolvedStats`` or any ``.get("ap"/"ad")`` mapping). When a row carries a
non-zero ratio AND stats are injected, its EFFECTIVE magnitude becomes
``base + stats.ap * ap_ratio + stats.ad * ad_ratio`` (the operator's exact
formula); every other path is byte-identical to item 308.

The blanket-multiplier model was rejected on domain grounds: pure %max-HP rows
(Vayne W, Fiora P) do NOT scale with caster AP/AD, so ONLY the rows that truly
carry a caster-stat term are seeded (Gwen P, Kog'Maw W - both AP). The AD path is
proven with a synthetic entry rather than mis-seeding an AD champion that has no
real AD-scaled %HP term.

These characterization tests pin: (a) the new schema fields + their 0.0 defaults,
(b) the byte-identical static path (stats=None) and the additive guarantee
(un-seeded rows return their EXACT item-308 value even WITH stats injected),
(c) the seeded Gwen P / Kog'Maw W scaling math at pinned AP, (d) the synthetic
ap/ad/conditional math (registry-independent), (e) a real ResolvedStats injection
matches a plain-dict injection, (f) the result/source dataclass SHAPE is unchanged
(no new to_dict keys), (g) exactly two rows are seeded.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.antitank import (
    _ANTITANK_REGISTRY,
    AntiTankEntry,
    _effective_magnitude,
    _mechanism_value,
    compute_antitank,
)
from agents.daemon_slayer.engine import ResolvedStats


def _rs(**stats: float) -> ResolvedStats:
    """Minimal ResolvedStats carrying just the stat dict under test."""
    return ResolvedStats(
        champion_id="Test",
        champion_name="Test",
        level=11,
        item_ids=(),
        mode="SR",
        stats={k: float(v) for k, v in stats.items()},
    )


class SchemaFieldTests(unittest.TestCase):
    def test_new_ratio_fields_default_zero(self):
        e = AntiTankEntry("Q", "MAX_HP", "SUSTAINED", magnitude=0.5)
        self.assertEqual(e.ap_ratio, 0.0)
        self.assertEqual(e.ad_ratio, 0.0)

    def test_ratio_fields_are_keyword_constructible(self):
        e = AntiTankEntry(
            "P", "MAX_HP", "SUSTAINED", magnitude=0.5, ap_ratio=0.001, ad_ratio=0.002
        )
        self.assertEqual(e.ap_ratio, 0.001)
        self.assertEqual(e.ad_ratio, 0.002)

    def test_positional_construction_still_works(self):
        # The item-308 positional shape (source, kind, cadence) must survive the
        # END-appended fields.
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=1.0, conditional=True)
        self.assertEqual(e.ap_ratio, 0.0)
        self.assertEqual(e.ad_ratio, 0.0)
        self.assertTrue(e.conditional)


class EffectiveMagnitudeMathTests(unittest.TestCase):
    def test_no_stats_returns_base(self):
        e = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0005)
        self.assertAlmostEqual(_effective_magnitude(e, None), 0.85, places=6)

    def test_zero_ratio_with_stats_returns_base(self):
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=0.95)
        self.assertAlmostEqual(
            _effective_magnitude(e, _rs(ap=500, ad=500)), 0.95, places=6
        )

    def test_ap_ratio_scales(self):
        e = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0005)
        # 0.85 + 200 * 0.0005 = 0.95
        self.assertAlmostEqual(_effective_magnitude(e, _rs(ap=200)), 0.95, places=6)

    def test_ad_ratio_scales(self):
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=0.5, ad_ratio=0.001)
        # 0.5 + 300 * 0.001 = 0.8
        self.assertAlmostEqual(_effective_magnitude(e, _rs(ad=300)), 0.8, places=6)

    def test_ap_only_entry_ignores_ad(self):
        e = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0005)
        self.assertAlmostEqual(_effective_magnitude(e, _rs(ad=999)), 0.85, places=6)

    def test_both_ratios_sum(self):
        e = AntiTankEntry(
            "R", "CURRENT_HP", "BURST", magnitude=0.4, ap_ratio=0.001, ad_ratio=0.0005
        )
        # 0.4 + 100*0.001 + 200*0.0005 = 0.6
        self.assertAlmostEqual(
            _effective_magnitude(e, _rs(ap=100, ad=200)), 0.6, places=6
        )

    def test_plain_dict_is_accepted(self):
        e = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0005)
        self.assertAlmostEqual(_effective_magnitude(e, {"ap": 200}), 0.95, places=6)


class MechanismValueScalingTests(unittest.TestCase):
    def test_mechanism_value_single_arg_unchanged(self):
        # The item-308 single-arg call path is preserved.
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=6)

    def test_mechanism_value_scales_with_stats(self):
        # MAX_HP 1.0 * SUSTAINED 1.0 * (0.5 + 300*0.001) = 0.8
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=0.5, ad_ratio=0.001)
        self.assertAlmostEqual(_mechanism_value(e, _rs(ad=300)), 0.8, places=6)

    def test_conditional_scaled_value(self):
        # CURRENT_HP 0.75 * BURST 0.65 * (0.4 + 0.1 + 0.1) * 0.5(cond) = 0.14625
        e = AntiTankEntry(
            "R", "CURRENT_HP", "BURST", magnitude=0.4,
            ap_ratio=0.001, ad_ratio=0.0005, conditional=True,
        )
        self.assertAlmostEqual(
            _mechanism_value(e, _rs(ap=100, ad=200)), 0.14625, places=6
        )
        # static (no stats): 0.75 * 0.65 * 0.4 * 0.5 = 0.0975
        self.assertAlmostEqual(_mechanism_value(e), 0.0975, places=6)

    def test_zero_ratio_unaffected_by_stats(self):
        e = AntiTankEntry("E", "SHRED", "PERIODIC", magnitude=0.5)
        # 0.85 * 0.8 * 0.5 = 0.34, with or without stats.
        self.assertAlmostEqual(_mechanism_value(e, _rs(ap=500)), 0.34, places=6)
        self.assertAlmostEqual(_mechanism_value(e), 0.34, places=6)


class SeededChampionTests(unittest.TestCase):
    def test_gwen_static_unchanged(self):
        # Gwen P MAX_HP SUSTAINED 0.85 -> 0.85 (item-308 value).
        self.assertAlmostEqual(
            compute_antitank("Gwen").antitank_score, 0.85, places=6
        )
        self.assertAlmostEqual(
            compute_antitank("Gwen", stats=None).antitank_score, 0.85, places=6
        )

    def test_gwen_scales_with_ap(self):
        # 0.85 + 200*0.0005 = 0.95
        r = compute_antitank("Gwen", stats=_rs(ap=200))
        self.assertAlmostEqual(r.antitank_score, 0.95, places=6)
        self.assertEqual(r.top_kind, "MAX_HP")
        # 0.85 + 600*0.0005 = 1.15
        self.assertAlmostEqual(
            compute_antitank("Gwen", stats=_rs(ap=600)).antitank_score, 1.15, places=6
        )

    def test_gwen_ignores_ad(self):
        # Gwen P is AP-only: an AD-heavy build does not move the score.
        self.assertAlmostEqual(
            compute_antitank("Gwen", stats=_rs(ad=999)).antitank_score, 0.85, places=6
        )

    def test_kogmaw_static_unchanged(self):
        # Q SHRED PERIODIC 0.7 -> 0.476; W MAX_HP SUSTAINED 0.9 cond -> 0.45.
        self.assertAlmostEqual(
            compute_antitank("KogMaw").antitank_score, 0.926, places=6
        )

    def test_kogmaw_w_scales_with_ap(self):
        # Q unchanged 0.476; W (0.9 + 200*0.0004)=0.98 -> 0.98*0.5 = 0.49.
        r = compute_antitank("KogMaw", stats=_rs(ap=200))
        self.assertAlmostEqual(r.antitank_score, 0.966, places=6)
        # The SHRED Q row carries no ratio and is unmoved.
        q = next(s for s in r.sources if s.source_key == "Q")
        self.assertAlmostEqual(q.value, 0.476, places=6)

    def test_seeded_source_reports_effective_magnitude(self):
        r = compute_antitank("Gwen", stats=_rs(ap=200))
        p = next(s for s in r.sources if s.source_key == "P")
        self.assertAlmostEqual(p.magnitude, 0.95, places=6)
        self.assertAlmostEqual(p.value, 0.95, places=6)

    def test_real_resolvedstats_matches_dict_injection(self):
        by_obj = compute_antitank("Gwen", stats=_rs(ap=200)).antitank_score
        by_dict = compute_antitank("Gwen", stats={"ap": 200}).antitank_score
        self.assertAlmostEqual(by_obj, by_dict, places=6)


class AdditiveGuaranteeTests(unittest.TestCase):
    UNSEEDED = (
        "Vayne", "Fiora", "Trundle", "Rumble", "KSante", "Sion", "Vi",
        "Mordekaiser", "DrMundo", "Nasus", "Ornn", "Aatrox",
    )

    def test_unseeded_champions_byte_identical_with_heavy_stats(self):
        # The operator's explicit requirement: un-seeded champions return their
        # EXACT prior static value even when stats are injected.
        heavy = _rs(ap=800, ad=800)
        for champ in self.UNSEEDED:
            static = compute_antitank(champ).antitank_score
            injected = compute_antitank(champ, stats=heavy).antitank_score
            self.assertAlmostEqual(static, injected, places=9, msg=champ)

    def test_static_to_dict_shape_unchanged(self):
        # stats=None to_dict is identical to the no-arg call, and the source dict
        # carries no new ratio keys (the schema lift lives on the registry entry,
        # not the scored source).
        base = compute_antitank("Gwen").to_dict()
        self.assertEqual(compute_antitank("Gwen", stats=None).to_dict(), base)
        for s in base["sources"]:
            self.assertEqual(
                set(s),
                {
                    "source_key", "kind", "cadence", "kind_weight",
                    "cadence_mult", "magnitude", "conditional", "value",
                },
            )


class SeedCoverageTests(unittest.TestCase):
    def test_exactly_two_rows_seeded(self):
        seeded = [
            (champ, e.source)
            for champ, entries in _ANTITANK_REGISTRY.items()
            for e in entries
            if e.ap_ratio != 0.0 or e.ad_ratio != 0.0
        ]
        self.assertEqual(sorted(seeded), [("Gwen", "P"), ("KogMaw", "W")])

    def test_gwen_p_ratio_value(self):
        e = next(e for e in _ANTITANK_REGISTRY["Gwen"] if e.source == "P")
        self.assertEqual(e.ap_ratio, 0.0005)
        self.assertEqual(e.ad_ratio, 0.0)

    def test_kogmaw_w_ratio_value(self):
        e = next(e for e in _ANTITANK_REGISTRY["KogMaw"] if e.source == "W")
        self.assertEqual(e.ap_ratio, 0.0004)
        self.assertEqual(e.ad_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
