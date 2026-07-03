"""R17 (ENGINE 1.151.0) - anti-tank level-ramp %max-HP endpoints (ramp_lo/ramp_hi).

Item 308 shipped the anti-tank scorer with hand-authored 0..1 magnitudes; P3.2
(item 315) added the optional caster-stat seam (ap_ratio / ad_ratio, engaged by an
injected ``stats``). R17 is the same shape for CHAMPION-LEVEL ramp: a real subset
of the %max-HP rows deal a percentage that scales with the caster's level
(Aatrox P "4% : 8% (based on level)", Brand P "8% : 12%", Skarner P "5% : 9%",
etc.). ``AntiTankEntry`` gains optional ``ramp_lo`` / ``ramp_hi`` endpoints
(default 0.0, END-appended so every positional construction survives), and
``compute_antitank`` / ``_mechanism_value`` / ``_effective_magnitude`` take an
optional ``level``. The hand-tuned magnitude encodes the LATE-game (max-ramp)
reliability; when a level is injected, a ramp-seeded row's effective magnitude
scales by ``lerp(ramp_lo, ramp_hi, (level-1)/17) / ramp_hi`` - so level 18 (and
``level=None``, the /anti-tank route default) is byte-identical to item 308/315,
and early levels are discounted toward the ramp_lo endpoint.

Default-OFF seam (charter section 5): with ``level=None`` every path is
byte-identical, and a row carrying no ramp data (ramp_hi == 0.0) is byte-identical
at ANY injected level - exactly the P3.2 additive guarantee. The live default-ON
flip (a survivability / draft consumer calling with the live champion level) is
EXCLUDED from this run (docs/LIVE_GAME_GATED_SYNC.md).

Offline characterization vs Meraki: the seeded (ramp_lo, ramp_hi) endpoints are
the verbatim "X% : Y% (based on level)" figures in antitank_registry_notes.json
(patch 16.12.1 kit source_quotes), pinned per row below.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.antitank import (
    _ANTITANK_REGISTRY,
    AntiTankEntry,
    _effective_magnitude,
    _level_ramp_factor,
    _mechanism_value,
    compute_antitank,
)

# The verified level-ramp %max-HP rows: (champion, source) -> (ramp_lo, ramp_hi).
# Each endpoint is the verbatim "lo% : hi% (based on level)" figure from the
# patch-16.12.1 kit source_quote in antitank_registry_notes.json.
EXPECTED_RAMP = {
    ("Aatrox", "P"): (4.0, 8.0),       # "4% : 8% (based on level)"
    ("Brand", "P"): (8.0, 12.0),       # "8% : 12% (based on level)"
    ("KSante", "P"): (1.0, 2.0),       # "1% : 2% (based on level)"
    ("Mordekaiser", "P"): (1.0, 5.0),  # "1% : 5% (based on level)"
    ("Ornn", "P"): (10.0, 18.0),       # "10% : 18% (based on Ornn's level)"
    ("Renata", "P"): (1.0, 2.0),       # "1% : 2% (based on level)"
    ("Skarner", "P"): (5.0, 9.0),      # "5% : 9% (based on level)"
    ("Urgot", "P"): (2.0, 6.0),        # "2% : 6% (based on level)"
    ("Zed", "P"): (6.0, 10.0),         # "6% / 8% / 10% (based on level)"
    ("Zeri", "P"): (1.0, 11.0),        # "1% : 11% (based on level)"
}


class RampSchemaFieldTests(unittest.TestCase):
    def test_ramp_fields_default_zero(self):
        e = AntiTankEntry("Q", "MAX_HP", "SUSTAINED", magnitude=0.5)
        self.assertEqual(e.ramp_lo, 0.0)
        self.assertEqual(e.ramp_hi, 0.0)

    def test_ramp_fields_keyword_constructible(self):
        e = AntiTankEntry(
            "P", "MAX_HP", "SUSTAINED", magnitude=0.5, ramp_lo=4.0, ramp_hi=8.0
        )
        self.assertEqual((e.ramp_lo, e.ramp_hi), (4.0, 8.0))

    def test_item308_positional_shape_survives(self):
        # The item-308 / P3.2 positional + keyword shape must survive the new
        # END-appended ramp fields (Python Conventions: append-at-end-with-default).
        e = AntiTankEntry(
            "W", "MAX_HP", "SUSTAINED", magnitude=1.0, conditional=True,
            ap_ratio=0.001, ad_ratio=0.002,
        )
        self.assertEqual((e.ramp_lo, e.ramp_hi), (0.0, 0.0))
        self.assertTrue(e.conditional)
        self.assertEqual((e.ap_ratio, e.ad_ratio), (0.001, 0.002))


class LevelRampFactorTests(unittest.TestCase):
    RAMP = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ramp_lo=4.0, ramp_hi=8.0)
    FLAT = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ramp_lo=8.0, ramp_hi=8.0)
    NODATA = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85)

    def test_none_level_is_unity(self):
        self.assertEqual(_level_ramp_factor(self.RAMP, None), 1.0)

    def test_no_ramp_data_is_unity(self):
        self.assertEqual(_level_ramp_factor(self.NODATA, 1), 1.0)
        self.assertEqual(_level_ramp_factor(self.NODATA, 18), 1.0)

    def test_flat_ramp_is_unity(self):
        self.assertEqual(_level_ramp_factor(self.FLAT, 1), 1.0)

    def test_level18_is_unity(self):
        self.assertAlmostEqual(_level_ramp_factor(self.RAMP, 18), 1.0, places=9)

    def test_level1_is_lo_over_hi(self):
        # 4 / 8 = 0.5
        self.assertAlmostEqual(_level_ramp_factor(self.RAMP, 1), 0.5, places=9)

    def test_midpoint_interpolates(self):
        # level 9 (rising 8): t = 8/17; pct = 4 + 4*(8/17) = 5.882...; /8 = 0.7353...
        self.assertAlmostEqual(
            _level_ramp_factor(self.RAMP, 9), (4.0 + 4.0 * (8 / 17)) / 8.0, places=9
        )

    def test_clamps_below_1_and_above_18(self):
        self.assertAlmostEqual(_level_ramp_factor(self.RAMP, 0), 0.5, places=9)
        self.assertAlmostEqual(_level_ramp_factor(self.RAMP, 99), 1.0, places=9)


class ByteIdenticalTests(unittest.TestCase):
    def test_effective_magnitude_level_none_is_base(self):
        e = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=0.85, ramp_lo=4.0, ramp_hi=8.0)
        self.assertAlmostEqual(_effective_magnitude(e, None, None), 0.85, places=9)

    def test_mechanism_value_single_arg_unchanged(self):
        e = AntiTankEntry("P", "MAX_HP", "SUSTAINED", magnitude=1.0, ramp_lo=4.0, ramp_hi=8.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=9)

    def test_route_path_byte_identical_for_seeded(self):
        # level=None (what compute_antitank / the /anti-tank route passes) is the
        # EXACT item-308 score for every ramp-seeded champion.
        for champ, _src in EXPECTED_RAMP:
            base = compute_antitank(champ).antitank_score
            self.assertAlmostEqual(
                compute_antitank(champ, level=None).antitank_score, base, places=9,
                msg=champ,
            )

    def test_level18_byte_identical_for_seeded(self):
        # The magnitude encodes max-ramp power, so level 18 == the no-level score.
        for champ, _src in EXPECTED_RAMP:
            base = compute_antitank(champ).antitank_score
            self.assertAlmostEqual(
                compute_antitank(champ, level=18).antitank_score, base, places=9,
                msg=champ,
            )

    def test_all_unramped_rows_byte_identical_at_any_level(self):
        # EVERY champion carrying no ramp endpoint of ANY kind - max-HP (R17,
        # ramp_hi) or current-HP (R39, current_hp_ramp_hi) - is byte-identical even
        # when a level is injected (the additive guarantee, mirrors P3.2). The skip
        # set is derived from the registry so a future ramp seed cannot silently
        # break this invariant.
        for champ, entries in _ANTITANK_REGISTRY.items():
            if any(e.ramp_hi != 0.0 or e.current_hp_ramp_hi != 0.0 for e in entries):
                continue
            base = compute_antitank(champ).antitank_score
            for lvl in (1, 6, 11, 18):
                self.assertAlmostEqual(
                    compute_antitank(champ, level=lvl).antitank_score, base,
                    places=9, msg=f"{champ}@{lvl}",
                )


class SeededRampMathTests(unittest.TestCase):
    def _ramp_source(self, champ, src, level):
        r = compute_antitank(champ, level=level)
        return next(s for s in r.sources if s.source_key == src)

    def test_aatrox_single_row_score_ramps(self):
        # Aatrox P is the only row (MAX_HP w=1.0, SUSTAINED m=1.0, magnitude 0.85).
        self.assertAlmostEqual(compute_antitank("Aatrox").antitank_score, 0.85, places=9)
        self.assertAlmostEqual(
            compute_antitank("Aatrox", level=1).antitank_score, 0.425, places=9
        )
        self.assertAlmostEqual(
            compute_antitank("Aatrox", level=18).antitank_score, 0.85, places=9
        )

    def test_seeded_source_reports_scaled_magnitude_and_value(self):
        # The reported source magnitude/value reflect the level-scaled figure.
        p1 = self._ramp_source("Aatrox", "P", 1)
        self.assertAlmostEqual(p1.magnitude, 0.425, places=9)
        self.assertAlmostEqual(p1.value, 0.425, places=9)
        p18 = self._ramp_source("Aatrox", "P", 18)
        self.assertAlmostEqual(p18.magnitude, 0.85, places=9)

    def test_skarner_p_row_isolated_ramp(self):
        # Skarner P is conditional (value halved); isolate the P row from the Q row.
        p_none = self._ramp_source("Skarner", "P", None)
        p1 = self._ramp_source("Skarner", "P", 1)
        # level 1 factor 5/9; magnitude 0.7 -> 0.7 * 5/9.
        self.assertAlmostEqual(p1.magnitude, 0.7 * (5.0 / 9.0), places=9)
        self.assertAlmostEqual(p_none.magnitude, 0.7, places=9)
        self.assertLess(p1.value, p_none.value)

    def test_early_level_strictly_below_none_for_every_seed(self):
        for champ, src in EXPECTED_RAMP:
            none_v = self._ramp_source(champ, src, None).value
            early_v = self._ramp_source(champ, src, 1).value
            self.assertLess(early_v, none_v, msg=f"{champ} {src}")


class RampSeedCoverageTests(unittest.TestCase):
    def test_seeded_set_is_the_verified_rows(self):
        seeded = sorted(
            (champ, e.source)
            for champ, entries in _ANTITANK_REGISTRY.items()
            for e in entries
            if e.ramp_hi != 0.0
        )
        self.assertEqual(seeded, sorted(EXPECTED_RAMP))

    def test_each_seed_endpoint_matches_meraki(self):
        for (champ, src), (lo, hi) in EXPECTED_RAMP.items():
            e = next(
                e for e in _ANTITANK_REGISTRY[champ]
                if e.source == src and e.ramp_hi != 0.0
            )
            self.assertEqual((e.ramp_lo, e.ramp_hi), (lo, hi), f"{champ} {src}")

    def test_ramp_rows_are_max_hp(self):
        # The directive scope is %max-HP level-ramp; every seed is a MAX_HP row.
        for (champ, src) in EXPECTED_RAMP:
            e = next(
                e for e in _ANTITANK_REGISTRY[champ]
                if e.source == src and e.ramp_hi != 0.0
            )
            self.assertEqual(e.kind, "MAX_HP", f"{champ} {src}")

    def test_ramp_lo_le_ramp_hi(self):
        for entries in _ANTITANK_REGISTRY.values():
            for e in entries:
                if e.ramp_hi != 0.0:
                    self.assertLessEqual(e.ramp_lo, e.ramp_hi)


class ToDictShapeTests(unittest.TestCase):
    def test_source_to_dict_has_no_new_ramp_keys(self):
        # The ramp lift lives on the registry entry, not the scored source - the
        # existing source dict shape (item 308 / P3.2) is unchanged.
        base = compute_antitank("Aatrox").to_dict()
        self.assertEqual(compute_antitank("Aatrox", level=None).to_dict(), base)
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
        self.assertEqual(ENGINE_VERSION, "1.175.0")


if __name__ == "__main__":
    unittest.main()
