"""R93 (ENGINE 1.190.0) - Darius E Apprehend kit-intrinsic % armor-penetration
anti-tank credit.

A fresh adversarial Meraki(16.13.1)-vs-registry refute pass on the anti-tank
CHAMPION-ABILITY registry (``antitank._ANTITANK_REGISTRY``). The directive's
example shred abilities (Nasus E / Wukong Q / Trundle R / Evelynn W) are ALL
already credited; a mechanized scan of ``champion_abilities.json`` 16.13.1 vs the
SHRED / PERCENT_PEN rows surfaced the genuine gap: kit-intrinsic *percentage*
penetration passives. Darius' Apprehend (E) grants an always-on 20% : 40% (per E
rank) armor penetration - a PERCENT_PEN mechanism that scales with how much armor
the tank stacked - yet Darius was absent from the (selective) registry entirely,
so ``compute_antitank("Darius")`` scored 0.0 / empty.

The fix is a single registry row - the SUSTAINED %-armor-pen sibling of the
existing Mordekaiser E (magic-pen) row: ``add("Darius", "E", "PERCENT_PEN",
"SUSTAINED", magnitude=0.7)``. Its value is PERCENT_PEN weight 0.65 * SUSTAINED
mult 1.0 * magnitude 0.7 = 0.455; ``top_kind`` PERCENT_PEN and ``shreds_resist``
True (a kit that lowers the tank's armor for the whole team).

Additive: the anti-tank axis is standalone and read-by-none (the ``/anti-tank``
route is opt-in), so no default live surface changes; every other champion's
score is byte-identical (proved here on the Mordekaiser sibling). The live
default-ON flip (surfacing Darius' shred in a coach) stays operator-gated
(docs/LIVE_GAME_GATED_SYNC.md).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.antitank import (
    _ANTITANK_CADENCE_MULT,
    _ANTITANK_KIND_WEIGHT,
    _ANTITANK_REGISTRY,
    compute_antitank,
)

# PERCENT_PEN weight 0.65 * SUSTAINED mult 1.0 * magnitude 0.7 = 0.455.
_DARIUS_E_VALUE = (
    _ANTITANK_KIND_WEIGHT["PERCENT_PEN"] * _ANTITANK_CADENCE_MULT["SUSTAINED"] * 0.7
)


class DariusRegistryRowTests(unittest.TestCase):
    def test_darius_registered(self):
        self.assertIn("Darius", _ANTITANK_REGISTRY, "Darius must carry an anti-tank row")

    def test_darius_e_percent_pen_sustained(self):
        entries = _ANTITANK_REGISTRY["Darius"]
        e_rows = [e for e in entries if e.source == "E"]
        self.assertEqual(len(e_rows), 1, "exactly one Darius E anti-tank row")
        e = e_rows[0]
        self.assertEqual(e.kind, "PERCENT_PEN")
        self.assertEqual(e.cadence, "SUSTAINED")
        self.assertAlmostEqual(e.magnitude, 0.7, places=4)

    def test_darius_row_is_unconditional(self):
        # Apprehend's armor pen is a permanent passive (no ult / stack / target
        # gate), like Mordekaiser E - non-conditional so it is credited at full
        # value, not the 0.5 conditional midpoint.
        e = next(e for e in _ANTITANK_REGISTRY["Darius"] if e.source == "E")
        self.assertFalse(e.conditional)

    def test_darius_carries_no_ramp_or_ratio(self):
        # A pure static %-pen row: no caster-stat (P3.2) term, no level ramp
        # (R17 / R39). Keeps every no-stats / no-level call byte-identical.
        e = next(e for e in _ANTITANK_REGISTRY["Darius"] if e.source == "E")
        self.assertEqual(e.ap_ratio, 0.0)
        self.assertEqual(e.ad_ratio, 0.0)
        self.assertEqual(e.ramp_hi, 0.0)
        self.assertEqual(e.current_hp_ramp_hi, 0.0)


class DariusScoreTests(unittest.TestCase):
    def test_darius_score_is_percent_pen_value(self):
        r = compute_antitank("Darius")
        self.assertAlmostEqual(r.antitank_score, _DARIUS_E_VALUE, places=6)
        # concretely 0.455 (0.65 * 1.0 * 0.7).
        self.assertAlmostEqual(r.antitank_score, 0.455, places=4)

    def test_darius_top_kind_and_shred_flag(self):
        r = compute_antitank("Darius")
        self.assertEqual(r.top_kind, "PERCENT_PEN")
        # A kit-intrinsic % armor pen lowers the tank's effective armor for the
        # whole team -> the shreds_resist identity a draft consumer keys on.
        self.assertTrue(r.shreds_resist)

    def test_darius_single_source(self):
        r = compute_antitank("Darius")
        self.assertEqual(len(r.sources), 1)
        s = r.sources[0]
        self.assertEqual((s.source_key, s.kind, s.cadence), ("E", "PERCENT_PEN", "SUSTAINED"))
        self.assertAlmostEqual(s.value, _DARIUS_E_VALUE, places=6)

    def test_score_is_sum_of_sources(self):
        r = compute_antitank("Darius")
        self.assertAlmostEqual(
            r.antitank_score, sum(s.value for s in r.sources), places=6
        )


class IsolationTests(unittest.TestCase):
    def test_mordekaiser_sibling_byte_identical(self):
        # The additive row touches only Darius; the closest sibling (Morde E,
        # the other SUSTAINED PERCENT_PEN) is unchanged.
        r = compute_antitank("Mordekaiser")
        self.assertAlmostEqual(r.antitank_score, 1.018125, places=5)
        self.assertEqual(r.top_kind, "PERCENT_PEN")

    def test_darius_matches_mordekaiser_pen_source_value(self):
        # Both are SUSTAINED %-pen at magnitude 0.7, so Darius' whole score
        # equals Morde's single PERCENT_PEN source contribution.
        morde = compute_antitank("Mordekaiser")
        pen = next(s for s in morde.sources if s.kind == "PERCENT_PEN")
        self.assertAlmostEqual(compute_antitank("Darius").antitank_score, pen.value, places=6)


class VersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.269.0")


if __name__ == "__main__":
    unittest.main()
