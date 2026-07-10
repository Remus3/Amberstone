"""ENGINE 1.150.0 (2026-06-22) - cc_conditional durations_floor_s schema lift.

R14 (DIRECTOR REFILL ds-sweep). Adds an optional guaranteed-minimum CC
floor band to ConditionalCcEntry for distance / channel-scaled CC, plus a
default-OFF ``apply_cc_floor`` seam on ``compute_cc_pressure``. Pins:

  * schema field exists + defaults None + __post_init__ floor validation;
  * the 5 Meraki-grounded seed floors (Maokai R 0.75 / KSante W 0.5 /
    Sion R 0.25 / Hecarim R 0.75 / NEW Ashe R 1.0);
  * the NEW Ashe R coexisting entry (mirrors the Maokai / Hecarim R
    distance-gated coexistence pattern);
  * default-OFF byte-identical parity vs the no-floor baseline;
  * seam-ON floor math: credited conditional duration = floor +
    prob * (max - floor), in BOTH the standalone and the coexistence
    MAX-rule consumer paths.

Floors are the Meraki 16.12.1 effects_descriptions minimums (the close-
range / min-channel guaranteed band) that the existing entries encode at
their MAX payoff in ``durations_s``: Maokai R 0.75 : 2.25, Hecarim R
0.75 : 1.5, Ashe R 1.0 : 3.5 (distance traveled); KSante W 0.5 : 1.75,
Sion R 0.25 : 1.75 (channel time).
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_conditional import (
    COND_RANGE_GATED,
    ConditionalCcEntry,
    get_conditional_entries,
)
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


# (champion, spell) -> expected guaranteed-minimum floor (Meraki 16.12.1).
SEED_FLOORS = {
    ("Maokai", "R"): 0.75,
    ("KSante", "W"): 0.5,
    ("Sion", "R"): 0.25,
    ("Hecarim", "R"): 0.75,
    ("Ashe", "R"): 1.0,
}


class EngineVersionPinTest(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.185.0")


class SchemaTests(unittest.TestCase):
    def test_field_defaults_none(self) -> None:
        entry = ConditionalCcEntry(
            "Foo", "R", "stun", (2.0,), COND_RANGE_GATED
        )
        self.assertIsNone(entry.durations_floor_s)

    def test_floor_accepted(self) -> None:
        entry = ConditionalCcEntry(
            "Foo", "R", "stun", (3.5,), COND_RANGE_GATED,
            durations_floor_s=1.0,
        )
        self.assertEqual(entry.durations_floor_s, 1.0)

    def test_floor_zero_accepted(self) -> None:
        entry = ConditionalCcEntry(
            "Foo", "R", "stun", (3.5,), COND_RANGE_GATED,
            durations_floor_s=0.0,
        )
        self.assertEqual(entry.durations_floor_s, 0.0)

    def test_floor_negative_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                "Foo", "R", "stun", (3.5,), COND_RANGE_GATED,
                durations_floor_s=-0.1,
            )

    def test_floor_above_max_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                "Foo", "R", "stun", (3.5,), COND_RANGE_GATED,
                durations_floor_s=4.0,
            )


class SeedFloorTests(unittest.TestCase):
    def test_seed_floors_match_meraki_minimums(self) -> None:
        for (champ, spell), floor in SEED_FLOORS.items():
            entries = {e.spell: e for e in get_conditional_entries(champ)}
            self.assertIn(spell, entries, f"{champ} {spell} entry missing")
            self.assertEqual(
                entries[spell].durations_floor_s, floor,
                f"{champ} {spell} floor",
            )
            # The floor must never exceed the encoded MAX payoff.
            self.assertLessEqual(
                entries[spell].durations_floor_s,
                entries[spell].durations_s[-1],
                f"{champ} {spell} floor > max",
            )

    def test_new_ashe_r_entry(self) -> None:
        entries = {e.spell: e for e in get_conditional_entries("Ashe")}
        self.assertIn("R", entries, "Ashe R conditional entry missing")
        ashe = entries["R"]
        self.assertEqual(ashe.cc_kind, "stun")
        self.assertEqual(ashe.condition, COND_RANGE_GATED)
        self.assertTrue(ashe.coexists_with_unconditional)
        self.assertEqual(ashe.durations_s[-1], 3.5)
        self.assertEqual(ashe.durations_floor_s, 1.0)


class SeamParityTests(unittest.TestCase):
    """Default-OFF must be byte-identical to the no-floor baseline."""

    CHAMPS = ("Maokai", "Ashe", "Hecarim", "KSante", "Sion", "Brand")

    def test_default_off_byte_identical(self) -> None:
        for champ in self.CHAMPS:
            base = compute_cc_pressure(champ, "SR", include_conditional=True)
            off = compute_cc_pressure(
                champ, "SR", include_conditional=True, apply_cc_floor=False
            )
            self.assertEqual(
                base.total_cc_seconds, off.total_cc_seconds, champ
            )
            self.assertEqual(
                base.conditional_cc_seconds, off.conditional_cc_seconds, champ
            )

    def test_floor_noop_without_include_conditional(self) -> None:
        # apply_cc_floor is a no-op unless the conditional axis is on.
        a = compute_cc_pressure("Ashe", "SR")
        b = compute_cc_pressure("Ashe", "SR", apply_cc_floor=True)
        self.assertEqual(a.total_cc_seconds, b.total_cc_seconds)


class SeamFloorMathTests(unittest.TestCase):
    def test_ashe_floor_lifts_coexisting_credit(self) -> None:
        # Ashe R: unconditional 1.5 flat; conditional max 3.5, prob 0.4,
        # floor 1.0. OFF: cond = 3.5*0.4 = 1.4 < unc 1.5 -> unconditional
        # wins -> total 1.5, conditional bucket 0.0.
        off = compute_cc_pressure("Ashe", "SR", include_conditional=True)
        self.assertAlmostEqual(off.total_cc_seconds, 1.5, places=4)
        self.assertAlmostEqual(off.conditional_cc_seconds, 0.0, places=4)
        # ON: cond = 1.0 + 0.4*(3.5-1.0) = 2.0 > unc 1.5 -> conditional
        # wins the MAX rule -> total 2.0, conditional bucket 2.0.
        on = compute_cc_pressure(
            "Ashe", "SR", include_conditional=True, apply_cc_floor=True
        )
        self.assertAlmostEqual(on.total_cc_seconds, 2.0, places=4)
        self.assertAlmostEqual(on.conditional_cc_seconds, 2.0, places=4)
        self.assertGreater(on.total_cc_seconds, off.total_cc_seconds)

    def test_ksante_w_standalone_floor_math(self) -> None:
        # KSante W: standalone (coexists False), max 1.0, prob 0.5,
        # floor 0.5. OFF W credit = 1.0*0.5 = 0.5; ON = 0.5 + 0.5*(1.0-0.5)
        # = 0.75. The W contribution rises by exactly 0.25 (SR tenacity 1.0);
        # KSante's other (Q) conditional entry is floor-free and unchanged.
        off = compute_cc_pressure("KSante", "SR", include_conditional=True)
        on = compute_cc_pressure(
            "KSante", "SR", include_conditional=True, apply_cc_floor=True
        )
        self.assertAlmostEqual(
            on.conditional_cc_seconds - off.conditional_cc_seconds,
            0.25, places=4,
        )

    def test_floor_free_champ_unchanged_by_seam(self) -> None:
        # Brand R carries no floor -> ON == OFF for a floor-free kit.
        off = compute_cc_pressure("Brand", "SR", include_conditional=True)
        on = compute_cc_pressure(
            "Brand", "SR", include_conditional=True, apply_cc_floor=True
        )
        self.assertEqual(off.total_cc_seconds, on.total_cc_seconds)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
