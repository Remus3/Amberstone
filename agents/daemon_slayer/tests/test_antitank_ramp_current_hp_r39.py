"""R39 (ENGINE 1.155.0) - anti-tank current-HP level-ramp endpoints.

R17 (ENGINE 1.151.0) shipped the %max-HP level-ramp seam: optional
``ramp_lo`` / ``ramp_hi`` endpoints + ``_level_ramp_factor`` discounting a
MAX_HP row's magnitude toward its early-game ``ramp_lo`` when a caster ``level``
is injected. R39 is the exact same shape for the CURRENT_HP kind: a real subset
of the %current-HP rows deal a percentage that scales with the caster's level -
Senna P Absolution "1% : 10% (based on level) of target's current health".

``AntiTankEntry`` gains optional ``current_hp_ramp_lo`` / ``current_hp_ramp_hi``
endpoints (default 0.0, END-appended so every positional construction - item 308
/ P3.2 / R17 - survives), and a parallel ``_current_hp_level_ramp_factor`` shares
the R17 lerp (``lerp(lo, hi, (level-1)/17) / hi``). ``_effective_magnitude``
multiplies BOTH ramp factors; a row carries at most one ramp pair, so the other
factor is always 1.0 and existing rows are byte-identical.

Default-OFF seam (charter section 5): with ``level=None`` every path is
byte-identical, and a row carrying no current-HP ramp data
(``current_hp_ramp_hi == 0.0``) is byte-identical at ANY injected level - the
additive guarantee. The live default-ON flip (a survivability / draft consumer
calling with the live champion level) is EXCLUDED from this run
(docs/LIVE_GAME_GATED_SYNC.md).

Offline characterization vs Meraki: the seeded (current_hp_ramp_lo,
current_hp_ramp_hi) endpoints are the verbatim "X% : Y% (based on level)" figure
in antitank_registry_notes.json (patch 16.12.1 Senna P source_quote), pinned
below.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.antitank import (
    _ANTITANK_KIND_WEIGHT,
    _ANTITANK_REGISTRY,
    AntiTankEntry,
    _current_hp_level_ramp_factor,
    _effective_magnitude,
    _level_ramp_factor,
    _mechanism_value,
    compute_antitank,
)

# The verified current-HP level-ramp rows: (champion, source) -> (lo, hi). The
# endpoint is the verbatim "lo% : hi% (based on level)" current-health figure from
# the patch-16.12.1 kit source_quote in antitank_registry_notes.json.
EXPECTED_CURRENT_HP_RAMP = {
    ("Senna", "P"): (1.0, 10.0),  # "1% : 10% (based on level) of target's current health"
}


class CurrentHpRampSchemaFieldTests(unittest.TestCase):
    def test_current_hp_ramp_fields_default_zero(self):
        e = AntiTankEntry("Q", "CURRENT_HP", "SUSTAINED", magnitude=0.5)
        self.assertEqual(e.current_hp_ramp_lo, 0.0)
        self.assertEqual(e.current_hp_ramp_hi, 0.0)

    def test_current_hp_ramp_fields_keyword_constructible(self):
        e = AntiTankEntry(
            "P", "CURRENT_HP", "SUSTAINED", magnitude=0.5,
            current_hp_ramp_lo=1.0, current_hp_ramp_hi=10.0,
        )
        self.assertEqual((e.current_hp_ramp_lo, e.current_hp_ramp_hi), (1.0, 10.0))

    def test_prior_positional_shape_survives(self):
        # The item-308 / P3.2 / R17 positional + keyword shape must survive the new
        # END-appended current-HP ramp fields (Python Conventions: append-at-end).
        e = AntiTankEntry(
            "W", "MAX_HP", "SUSTAINED", magnitude=1.0, conditional=True,
            ap_ratio=0.001, ad_ratio=0.002, ramp_lo=4.0, ramp_hi=8.0,
        )
        self.assertEqual((e.current_hp_ramp_lo, e.current_hp_ramp_hi), (0.0, 0.0))
        self.assertEqual((e.ramp_lo, e.ramp_hi), (4.0, 8.0))
        self.assertTrue(e.conditional)
        self.assertEqual((e.ap_ratio, e.ad_ratio), (0.001, 0.002))


class CurrentHpLevelRampFactorTests(unittest.TestCase):
    RAMP = AntiTankEntry(
        "P", "CURRENT_HP", "SUSTAINED", magnitude=0.5,
        current_hp_ramp_lo=1.0, current_hp_ramp_hi=10.0,
    )
    FLAT = AntiTankEntry(
        "P", "CURRENT_HP", "SUSTAINED", magnitude=0.5,
        current_hp_ramp_lo=10.0, current_hp_ramp_hi=10.0,
    )
    NODATA = AntiTankEntry("P", "CURRENT_HP", "SUSTAINED", magnitude=0.5)

    def test_none_level_is_unity(self):
        self.assertEqual(_current_hp_level_ramp_factor(self.RAMP, None), 1.0)

    def test_no_ramp_data_is_unity(self):
        self.assertEqual(_current_hp_level_ramp_factor(self.NODATA, 1), 1.0)
        self.assertEqual(_current_hp_level_ramp_factor(self.NODATA, 18), 1.0)

    def test_flat_ramp_is_unity(self):
        self.assertEqual(_current_hp_level_ramp_factor(self.FLAT, 1), 1.0)

    def test_level18_is_unity(self):
        self.assertAlmostEqual(_current_hp_level_ramp_factor(self.RAMP, 18), 1.0, places=9)

    def test_level1_is_lo_over_hi(self):
        # 1 / 10 = 0.1
        self.assertAlmostEqual(_current_hp_level_ramp_factor(self.RAMP, 1), 0.1, places=9)

    def test_midpoint_interpolates(self):
        # level 9 (rising 8): t = 8/17; pct = 1 + 9*(8/17) = 5.2353...; /10 = 0.52353...
        self.assertAlmostEqual(
            _current_hp_level_ramp_factor(self.RAMP, 9),
            (1.0 + 9.0 * (8 / 17)) / 10.0, places=9,
        )

    def test_clamps_below_1_and_above_18(self):
        self.assertAlmostEqual(_current_hp_level_ramp_factor(self.RAMP, 0), 0.1, places=9)
        self.assertAlmostEqual(_current_hp_level_ramp_factor(self.RAMP, 99), 1.0, places=9)

    def test_max_hp_ramp_factor_ignores_current_hp_endpoints(self):
        # The two ramp systems are independent: the MAX_HP factor reads ramp_lo/hi,
        # so a row carrying ONLY current-HP endpoints is unity under _level_ramp_factor.
        self.assertEqual(_level_ramp_factor(self.RAMP, 1), 1.0)
        self.assertEqual(_level_ramp_factor(self.RAMP, 18), 1.0)


class ByteIdenticalTests(unittest.TestCase):
    def test_effective_magnitude_level_none_is_base(self):
        e = AntiTankEntry(
            "P", "CURRENT_HP", "SUSTAINED", magnitude=0.5,
            current_hp_ramp_lo=1.0, current_hp_ramp_hi=10.0,
        )
        self.assertAlmostEqual(_effective_magnitude(e, None, None), 0.5, places=9)

    def test_mechanism_value_single_arg_unchanged(self):
        e = AntiTankEntry(
            "P", "CURRENT_HP", "SUSTAINED", magnitude=1.0,
            current_hp_ramp_lo=1.0, current_hp_ramp_hi=10.0,
        )
        # CURRENT_HP weight 0.75 * SUSTAINED 1.0 * magnitude 1.0 = 0.75.
        self.assertAlmostEqual(_mechanism_value(e), 0.75, places=9)

    def test_route_path_byte_identical_for_seeded(self):
        # level=None (what compute_antitank / the /anti-tank route passes) is the
        # EXACT item-308 score for every current-HP-ramp-seeded champion.
        for champ, _src in EXPECTED_CURRENT_HP_RAMP:
            base = compute_antitank(champ).antitank_score
            self.assertAlmostEqual(
                compute_antitank(champ, level=None).antitank_score, base, places=9,
                msg=champ,
            )

    def test_level18_byte_identical_for_seeded(self):
        # The magnitude encodes max-ramp power, so level 18 == the no-level score.
        for champ, _src in EXPECTED_CURRENT_HP_RAMP:
            base = compute_antitank(champ).antitank_score
            self.assertAlmostEqual(
                compute_antitank(champ, level=18).antitank_score, base, places=9,
                msg=champ,
            )

    def test_unramped_current_hp_rows_byte_identical_at_any_level(self):
        # EVERY other CURRENT_HP champion (DrMundo, Viego, Elise, ...) carries no
        # current-HP ramp endpoint and is byte-identical even when a level is
        # injected (the additive guarantee). Excludes the seeded set AND any row
        # carrying a MAX_HP ramp (those are the R17 seam, not R39).
        seeded = {champ for champ, _src in EXPECTED_CURRENT_HP_RAMP}
        for champ, entries in _ANTITANK_REGISTRY.items():
            if champ in seeded:
                continue
            if any(e.ramp_hi != 0.0 for e in entries):
                continue  # R17 max-HP ramp rows move with level by design
            base = compute_antitank(champ).antitank_score
            for lvl in (1, 6, 11, 18):
                self.assertAlmostEqual(
                    compute_antitank(champ, level=lvl).antitank_score, base,
                    places=9, msg=f"{champ}@{lvl}",
                )


class SeededCurrentHpRampMathTests(unittest.TestCase):
    def _source(self, champ, src, level):
        r = compute_antitank(champ, level=level)
        return next(s for s in r.sources if s.source_key == src)

    def test_senna_single_row_score_ramps(self):
        # Senna P is the only row: CURRENT_HP w=0.75, SUSTAINED m=1.0, magnitude 0.5
        # -> static value 0.375.
        self.assertAlmostEqual(compute_antitank("Senna").antitank_score, 0.375, places=9)
        # level 1 factor 1/10=0.1 -> 0.375 * 0.1 = 0.0375.
        self.assertAlmostEqual(
            compute_antitank("Senna", level=1).antitank_score, 0.0375, places=9
        )
        self.assertAlmostEqual(
            compute_antitank("Senna", level=18).antitank_score, 0.375, places=9
        )

    def test_senna_source_reports_scaled_magnitude_and_value(self):
        # The reported source magnitude/value reflect the level-scaled figure.
        p1 = self._source("Senna", "P", 1)
        self.assertAlmostEqual(p1.magnitude, 0.05, places=9)   # 0.5 * 0.1
        self.assertAlmostEqual(p1.value, 0.0375, places=9)     # 0.75 * 1.0 * 0.05
        p18 = self._source("Senna", "P", 18)
        self.assertAlmostEqual(p18.magnitude, 0.5, places=9)
        self.assertAlmostEqual(p18.value, 0.375, places=9)

    def test_senna_top_kind_is_current_hp(self):
        r = compute_antitank("Senna", level=6)
        self.assertEqual(r.top_kind, "CURRENT_HP")
        self.assertFalse(r.shreds_resist)

    def test_early_level_strictly_below_none_for_every_seed(self):
        for champ, src in EXPECTED_CURRENT_HP_RAMP:
            none_v = self._source(champ, src, None).value
            early_v = self._source(champ, src, 1).value
            self.assertLess(early_v, none_v, msg=f"{champ} {src}")


class CurrentHpRampSeedCoverageTests(unittest.TestCase):
    def test_seeded_set_is_the_verified_rows(self):
        seeded = sorted(
            (champ, e.source)
            for champ, entries in _ANTITANK_REGISTRY.items()
            for e in entries
            if e.current_hp_ramp_hi != 0.0
        )
        self.assertEqual(seeded, sorted(EXPECTED_CURRENT_HP_RAMP))

    def test_each_seed_endpoint_matches_meraki(self):
        for (champ, src), (lo, hi) in EXPECTED_CURRENT_HP_RAMP.items():
            e = next(
                e for e in _ANTITANK_REGISTRY[champ]
                if e.source == src and e.current_hp_ramp_hi != 0.0
            )
            self.assertEqual(
                (e.current_hp_ramp_lo, e.current_hp_ramp_hi), (lo, hi), f"{champ} {src}"
            )

    def test_current_hp_ramp_rows_are_current_hp_kind(self):
        # The directive scope is %current-HP level-ramp; every seed is a CURRENT_HP row.
        for (champ, src) in EXPECTED_CURRENT_HP_RAMP:
            e = next(
                e for e in _ANTITANK_REGISTRY[champ]
                if e.source == src and e.current_hp_ramp_hi != 0.0
            )
            self.assertEqual(e.kind, "CURRENT_HP", f"{champ} {src}")

    def test_current_hp_ramp_lo_le_hi(self):
        for entries in _ANTITANK_REGISTRY.values():
            for e in entries:
                if e.current_hp_ramp_hi != 0.0:
                    self.assertLessEqual(e.current_hp_ramp_lo, e.current_hp_ramp_hi)

    def test_no_row_carries_both_ramp_kinds(self):
        # A row ramps EITHER max-HP (R17) OR current-HP (R39), never both - so the
        # two factors never compound on one mechanism.
        for entries in _ANTITANK_REGISTRY.values():
            for e in entries:
                self.assertFalse(
                    e.ramp_hi != 0.0 and e.current_hp_ramp_hi != 0.0,
                    msg=f"{e.source} {e.kind}",
                )

    def test_current_hp_weight_present(self):
        # Guard the kind weight the Senna math depends on is still registered.
        self.assertIn("CURRENT_HP", _ANTITANK_KIND_WEIGHT)


class ToDictShapeTests(unittest.TestCase):
    def test_source_to_dict_has_no_new_ramp_keys(self):
        # The ramp lift lives on the registry entry, not the scored source - the
        # existing source dict shape (item 308 / P3.2 / R17) is unchanged.
        base = compute_antitank("Senna").to_dict()
        self.assertEqual(compute_antitank("Senna", level=None).to_dict(), base)
        for s in base["sources"]:
            self.assertEqual(
                set(s),
                {
                    "source_key", "kind", "cadence", "kind_weight",
                    "cadence_mult", "magnitude", "conditional", "value",
                },
            )


class EngineVersionTest(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.158.0")


if __name__ == "__main__":
    unittest.main()
