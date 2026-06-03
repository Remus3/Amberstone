"""Conditional-CC consumer parity - pins the raw-helper vs MAX-consumer divergence.

``get_total_conditional_cc_seconds`` (cc_conditional) is a context-free
probability-weighted sum over the CONDITIONAL registry alone. The live
consumer ``compute_cc_pressure(include_conditional=True)`` (cc_pressure)
applies the wave-18 coexistence MAX-rule: for an entry tagged
``coexists_with_unconditional=True`` it credits MAX(same-slot
unconditional, conditional) and never sums both.

These two therefore DIVERGE on coexisting slots by construction - the
helper over-credits (returns the raw conditional contribution) while the
consumer drops it whenever the same-slot unconditional value dominates.
That divergence is intentional (the helper stays raw as a diagnostic /
forward-marker primitive); this file pins it so a future "fix" that
silently makes the helper apply the MAX-rule trips a red test and is
forced to confront the contract.

Resolves "Conditional-CC consumer parity" (04_GAPS_AND_ROADMAP.md
section 3): the helper is documented as intentionally raw and the
divergence is now machine-guarded.

Fixtures at the active patch (coexists=True entries): Hecarim R, Maokai
R, Vayne E. All three have the same-slot unconditional value winning the
MAX comparison, so all three are clean divergence cases. Brand is the
non-coexisting control where the two AGREE (SR tenacity 1.0).
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer.cc_conditional import (
    get_conditional_entries,
    get_total_conditional_cc_seconds,
)
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class CoexistingSlotDivergenceTests(unittest.TestCase):
    """The helper over-credits a coexisting slot; the consumer drops it."""

    def test_maokai_helper_sums_both_consumer_drops_coexisting_R(self) -> None:
        # Q (coexists=False) 1.0 * 0.3 = 0.3 ; R (coexists=True) 2.25 * 0.4 = 0.9.
        # Helper sums both -> 1.2. Consumer: Q credited 0.3, R MAX(2.0, 0.9)=2.0
        # -> unconditional wins -> conditional bucket gets only Q's 0.3.
        helper = get_total_conditional_cc_seconds("Maokai", apply_probability=True)
        consumer = compute_cc_pressure("Maokai", "sr", include_conditional=True)
        self.assertAlmostEqual(helper, 1.2, places=6)
        self.assertAlmostEqual(consumer.conditional_cc_seconds, 0.3, places=6)
        # The coexisting R's 0.9 is exactly the gap.
        self.assertAlmostEqual(
            helper - consumer.conditional_cc_seconds, 0.9, places=6
        )

    def test_hecarim_single_coexisting_entry_diverges(self) -> None:
        # R (coexists=True) 1.5 * 0.4 = 0.6 raw. Unconditional R = 1.0 wins MAX.
        helper = get_total_conditional_cc_seconds("Hecarim", apply_probability=True)
        consumer = compute_cc_pressure("Hecarim", "sr", include_conditional=True)
        self.assertAlmostEqual(helper, 0.6, places=6)
        self.assertAlmostEqual(consumer.conditional_cc_seconds, 0.0, places=6)

    def test_vayne_single_coexisting_entry_diverges(self) -> None:
        # E (coexists=True) 1.5 * 0.3 = 0.45 raw. Unconditional E = 0.5 wins MAX.
        helper = get_total_conditional_cc_seconds("Vayne", apply_probability=True)
        consumer = compute_cc_pressure("Vayne", "sr", include_conditional=True)
        self.assertAlmostEqual(helper, 0.45, places=6)
        self.assertAlmostEqual(consumer.conditional_cc_seconds, 0.0, places=6)


class NonCoexistingControlTests(unittest.TestCase):
    """Where no slot coexists, the helper and consumer agree (SR tenacity 1.0)."""

    def test_brand_no_coexistence_helper_equals_consumer(self) -> None:
        # Brand Q (debuffed, 0.5) + R (nth_hit, 0.7), both coexists=False.
        # SR tenacity 1.0 -> no reduction -> helper == consumer conditional total.
        helper = get_total_conditional_cc_seconds("Brand", apply_probability=True)
        consumer = compute_cc_pressure("Brand", "sr", include_conditional=True)
        for entry in get_conditional_entries("Brand"):
            self.assertFalse(entry.coexists_with_unconditional)
        self.assertAlmostEqual(helper, consumer.conditional_cc_seconds, places=6)


class HelperIsRawAcrossRegistryTests(unittest.TestCase):
    """Structural invariant: helper >= consumer conditional bucket, always.

    For every champion in the conditional registry, the raw helper total
    is >= the MAX-applied consumer's conditional bucket in SR (tenacity
    1.0). Equality holds when no slot coexists OR a coexisting
    conditional wins its MAX; the helper is strictly greater only when a
    coexisting unconditional dominates. This pins that the helper never
    UNDER-credits relative to the consumer - it is the raw ceiling.
    """

    def test_helper_is_upper_bound_on_consumer_conditional_bucket(self) -> None:
        # Walk the coexists=True champions plus the controls.
        for champ in ("Maokai", "Hecarim", "Vayne", "Brand", "Warwick"):
            with self.subTest(champ=champ):
                helper = get_total_conditional_cc_seconds(
                    champ, apply_probability=True
                )
                consumer = compute_cc_pressure(
                    champ, "sr", include_conditional=True
                )
                self.assertGreaterEqual(
                    helper + 1e-9, consumer.conditional_cc_seconds
                )

    def test_coexisting_champions_strictly_diverge(self) -> None:
        for champ in ("Maokai", "Hecarim", "Vayne"):
            with self.subTest(champ=champ):
                helper = get_total_conditional_cc_seconds(
                    champ, apply_probability=True
                )
                consumer = compute_cc_pressure(
                    champ, "sr", include_conditional=True
                )
                self.assertGreater(
                    helper, consumer.conditional_cc_seconds + 1e-9
                )


class AsciiHygieneTests(unittest.TestCase):
    """This test file is pure 7-bit ASCII."""

    def test_test_file_is_ascii(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(non_ascii, [], f"non-ASCII bytes: {non_ascii[:8]}")


if __name__ == "__main__":
    unittest.main()
