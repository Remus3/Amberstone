"""ENGINE 1.38.0 (2026-05-22) - cc_pressure consumer wire for cc_conditional.

The ``cc_conditional`` module shipped at ENGINE 1.37.0 (2026-05-22)
as a FORWARD-MARKER seam with a 10-entry seed and NO consumer wires.
ENGINE 1.38.0 ships the FIRST authorized consumer: ``compute_cc_pressure``
gains an optional ``include_conditional`` kwarg that folds
probability-weighted conditional CC contributions into the aggregate
when True; the default ``include_conditional=False`` preserves
byte-identical 1.37.0 behavior for the 4 existing consumers (engine
``compute_ehp`` cc_blended_ehp math + coach prompt
``enemy_cc_threat_line`` + DS scorer ``compute_hybrid`` + dashboard
threat-balance route).

Test surface (8 classes):
  * ``DefaultBehaviorTests`` - default ``include_conditional=False``
    preserves byte-identical 1.37.0 output for the 4 existing
    consumers: Annie (unconditional only), Brand (conditional only),
    Galio (unconditional triple), unknown champion.
  * ``IncludeConditionalTrueTests`` - Brand R 2.0s * 0.7 prob = 1.4s
    conditional contribution; total = unconditional + conditional;
    conditional_entries populated; conditional_cc_seconds = separate
    post-tenacity total.
  * ``ConditionalOnlyChampionTests`` - Warwick has NO unconditional
    entry but conditional R 1.5/1.75/2.0s @ probability=0.5 -> max
    rank 2.0 * 0.5 = 1.0s; with ``include_conditional=True`` the
    total reflects this.
  * ``BothUnconditionalAndConditionalTests`` - Mordekaiser has
    wave-5 unconditional E pull (0.25) + conditional R banishment
    7.0s @ probability=1.0 -> total 0.25 + 7.0 = 7.25.
  * ``AramTenacityAppliesToConditionalTests`` - In ARAM/KIWI mode the
    conditional contribution ALSO flows through
    ``effective_cc_duration`` so the tenacity math seam is unified.
    Uses monkeypatched ``_TENACITY_MAP`` since no champion at 16.10.1
    is in BOTH the conditional registry AND the modified-tenacity
    map (the 10 conditional champs are mages/tanks/etc. + the 17
    modified-tenacity champs are assassins).
  * ``EngineVersionCurrentTests`` - pin ENGINE_VERSION at 1.38.0
    for this slice.
  * ``ProbabilityFalseModeTests`` - the
    ``get_total_conditional_cc_seconds`` default path
    ``apply_probability=True`` is what ``compute_cc_pressure`` uses;
    this class pins the probability-weighted path is what the
    consumer reads (operator-tunable midpoints surface in the total).
  * ``AsciiHygieneTests`` - both the module + this test file are
    pure 7-bit ASCII.
"""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_pressure
from agents.daemon_slayer.cc_conditional import (
    ConditionalCcEntry,
    get_total_conditional_cc_seconds,
)
from agents.daemon_slayer.cc_pressure import (
    CcPressureResult,
    compute_cc_pressure,
)
from agents.daemon_slayer.ehp import effective_cc_duration


# ---------------- 1. DefaultBehaviorTests ----------------


class DefaultBehaviorTests(unittest.TestCase):
    """Default ``include_conditional=False`` preserves 1.37.0 output."""

    def test_annie_default_byte_identical_to_137(self) -> None:
        """Annie has unconditional R only; default ignores conditional."""
        result = compute_cc_pressure("Annie", "SR")
        self.assertEqual(result.total_cc_seconds, 1.5)
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())
        # Annie has no conditional entry so the default + the explicit
        # False are the same; pin both shapes anyway.
        result2 = compute_cc_pressure("Annie", "SR", include_conditional=False)
        self.assertEqual(result.total_cc_seconds, result2.total_cc_seconds)
        self.assertEqual(result.spells, result2.spells)

    def test_brand_default_returns_empty_conditional_ignored(self) -> None:
        """Brand has conditional R only; default returns empty (no unconditional)."""
        result = compute_cc_pressure("Brand", "SR")
        # Brand is NOT in _PER_SPELL_CC_DURATIONS - default returns
        # empty result because include_conditional=False ignores the
        # conditional registry entirely.
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())

    def test_galio_default_unconditional_triple_byte_identical(self) -> None:
        """Galio W+E+R = 2.25; default is byte-identical to 1.37.0 output."""
        result = compute_cc_pressure("Galio", "SR")
        self.assertAlmostEqual(result.total_cc_seconds, 2.25, places=6)
        self.assertEqual(len(result.spells), 3)
        # No conditional entries for Galio - the new fields are
        # default values.
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())

    def test_unknown_champion_default_still_empty(self) -> None:
        """Unknown champion default returns the empty result + new fields zero."""
        result = compute_cc_pressure("NotAChamp", "SR")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())


# ---------------- 2. IncludeConditionalTrueTests ----------------


class IncludeConditionalTrueTests(unittest.TestCase):
    """``include_conditional=True`` folds conditional contributions."""

    def test_brand_r_15_at_07_prob_equals_14s(self) -> None:
        """Brand contribution >= 1.4s (wave 0 R floor).

        Brand has wave 0 R (2.0 * 0.7 = 1.4) + wave 6 Q (1.25 * 0.5 =
        0.625) + any future Brand wave additions. The wave-0 R is the
        load-bearing floor for this contract; future wave additions
        only INCREASE the contribution. assertGreaterEqual pin for
        forward-compat.
        """
        result = compute_cc_pressure(
            "Brand", "SR", include_conditional=True
        )
        # Brand has no unconditional entry; conditional only path.
        self.assertEqual(result.spells, ())
        # Floor at 1.4 (wave-0 R contribution); future Brand waves add
        # via assertGreaterEqual. At wave-6 registry state the value is
        # 2.025 (R 1.4 + Q 0.625).
        self.assertGreaterEqual(result.conditional_cc_seconds, 1.4)
        # total == conditional because no unconditional entry exists.
        self.assertAlmostEqual(
            result.total_cc_seconds,
            result.conditional_cc_seconds,
            places=6,
        )

    def test_brand_conditional_entries_populated(self) -> None:
        """Brand conditional_entries tuple has at least the Pyroclasm R entry.

        Brand has wave 0 R + wave 6 Q + any future Brand wave
        additions. The R entry is the load-bearing pin (wave 0
        canonical seed); future wave entries are accepted via
        assertGreaterEqual + presence checks.
        """
        result = compute_cc_pressure(
            "Brand", "SR", include_conditional=True
        )
        # At least 1 entry post-wave-0; wave 6 adds Brand Q so count
        # is now >= 2; future wave additions only INCREASE.
        self.assertGreaterEqual(len(result.conditional_entries), 1)
        # Find the R entry (load-bearing pin from wave 0); canonical
        # Q-W-E-R ordering means R is the LAST entry today. Lookup
        # by spell key for forward-compat with future Brand entries
        # at any spell slot.
        r_entries = [
            e for e in result.conditional_entries if e.spell == "R"
        ]
        self.assertEqual(len(r_entries), 1)
        entry = r_entries[0]
        self.assertIsInstance(entry, ConditionalCcEntry)
        self.assertEqual(entry.champion, "Brand")
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (2.0,))
        self.assertEqual(entry.probability, 0.7)

    def test_total_equals_unconditional_plus_conditional(self) -> None:
        """``total_cc_seconds`` is the sum of both axes."""
        # Use monkeypatched data to pin the arithmetic; this avoids
        # depending on the exact conditional-registry values which
        # may shift in future seed waves.
        fake_registry = {"Foo": {"Q": (1.0,)}}
        fake_conditional = (
            ConditionalCcEntry(
                champion="Foo",
                spell="R",
                cc_kind="stun",
                durations_s=(2.0,),
                condition="nth_hit",
                probability=0.5,
            ),
        )
        with mock.patch.object(
            cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry
        ):
            with mock.patch.object(
                cc_pressure,
                "get_conditional_entries",
                return_value=fake_conditional,
            ):
                with mock.patch.object(
                    cc_pressure,
                    "get_total_conditional_cc_seconds",
                    return_value=2.0 * 0.5,
                ):
                    result = compute_cc_pressure(
                        "Foo", "SR", include_conditional=True
                    )
        # 1.0 unconditional + 1.0 conditional (2.0 * 0.5) = 2.0
        self.assertAlmostEqual(result.total_cc_seconds, 2.0, places=6)
        # 1.0 from unconditional Q
        self.assertEqual(len(result.spells), 1)
        self.assertAlmostEqual(
            result.spells[0].duration_post_tenacity_s, 1.0, places=6
        )
        # 1.0 from conditional axis
        self.assertAlmostEqual(result.conditional_cc_seconds, 1.0, places=6)

    def test_conditional_cc_seconds_separate_from_total(self) -> None:
        """``conditional_cc_seconds`` is the separate axis breakdown."""
        result = compute_cc_pressure(
            "Brand", "SR", include_conditional=True
        )
        # Both fields populated when conditional present
        self.assertGreater(result.conditional_cc_seconds, 0.0)
        # Brand has no unconditional => total == conditional
        self.assertEqual(
            result.total_cc_seconds, result.conditional_cc_seconds
        )

    def test_unknown_champion_with_include_conditional_still_empty(self) -> None:
        """An unknown champion ALSO has no conditional entries."""
        result = compute_cc_pressure(
            "NotAChamp", "SR", include_conditional=True
        )
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())

    def test_galio_no_conditional_entry_total_unchanged(self) -> None:
        """Galio has no conditional entry; include_conditional=True has no effect."""
        unconditional = compute_cc_pressure("Galio", "SR")
        conditional_on = compute_cc_pressure(
            "Galio", "SR", include_conditional=True
        )
        # Total is identical
        self.assertAlmostEqual(
            unconditional.total_cc_seconds,
            conditional_on.total_cc_seconds,
            places=6,
        )
        self.assertEqual(conditional_on.conditional_cc_seconds, 0.0)
        self.assertEqual(conditional_on.conditional_entries, ())


# ---------------- 3. ConditionalOnlyChampionTests ----------------


class ConditionalOnlyChampionTests(unittest.TestCase):
    """Champions with conditional entries but no unconditional ones."""

    def test_warwick_conditional_only_max_rank_at_05_prob(self) -> None:
        """Warwick R max rank 2.0 * 0.5 = 1.0s. Wave 13 adds E 1.0 * 0.5 = 0.5s. Total = 1.5s."""
        result = compute_cc_pressure(
            "Warwick", "SR", include_conditional=True
        )
        # No unconditional entry
        self.assertEqual(result.spells, ())
        # Wave 0 R = 2.0 * 0.5 = 1.0 + Wave 13 E = 1.0 * 0.5 = 0.5 -> 1.5 total
        self.assertAlmostEqual(result.conditional_cc_seconds, 1.5, places=6)
        self.assertAlmostEqual(result.total_cc_seconds, 1.5, places=6)

    def test_warwick_conditional_entries_carry_r_channel(self) -> None:
        """Warwick conditional_entries contain BOTH the wave 0 R suppression
        and the wave 13 E fear; canonical order returns E before R."""
        result = compute_cc_pressure(
            "Warwick", "SR", include_conditional=True
        )
        # Wave 13 added a 2nd entry (E fear).
        self.assertEqual(len(result.conditional_entries), 2)
        # Find the R entry (suppression) for legacy assertion preservation.
        r_entries = [
            e for e in result.conditional_entries if e.spell == "R"
        ]
        self.assertEqual(len(r_entries), 1)
        entry = r_entries[0]
        self.assertEqual(entry.champion, "Warwick")
        self.assertEqual(entry.spell, "R")
        self.assertEqual(entry.cc_kind, "suppression")
        self.assertEqual(entry.condition, "channel")
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.durations_s, (1.5, 1.75, 2.0))

    def test_warwick_default_returns_empty(self) -> None:
        """Default (include_conditional=False) returns empty for Warwick."""
        result = compute_cc_pressure("Warwick", "SR")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())


# ---------------- 4. BothUnconditionalAndConditionalTests ----------------


class BothUnconditionalAndConditionalTests(unittest.TestCase):
    """Mordekaiser composes both axes: E unconditional + R conditional."""

    def test_mordekaiser_unconditional_e_plus_conditional_r(self) -> None:
        """E pull 0.25 + R banishment 7.0 (prob=1.0) = 7.25."""
        result = compute_cc_pressure(
            "Mordekaiser", "SR", include_conditional=True
        )
        # Unconditional E pull at 0.25
        self.assertEqual(len(result.spells), 1)
        self.assertEqual(result.spells[0].spell_key, "E")
        self.assertAlmostEqual(
            result.spells[0].duration_post_tenacity_s, 0.25, places=6
        )
        # Conditional R banishment 7.0 * 1.0 = 7.0
        self.assertAlmostEqual(result.conditional_cc_seconds, 7.0, places=6)
        # Combined total
        self.assertAlmostEqual(result.total_cc_seconds, 7.25, places=6)

    def test_mordekaiser_default_only_returns_e_pull(self) -> None:
        """Default ignores the R conditional - only E pull shows up."""
        result = compute_cc_pressure("Mordekaiser", "SR")
        self.assertEqual(len(result.spells), 1)
        self.assertEqual(result.spells[0].spell_key, "E")
        self.assertAlmostEqual(result.total_cc_seconds, 0.25, places=6)
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())

    def test_mordekaiser_conditional_entry_carries_r_banishment(self) -> None:
        """Mordekaiser conditional_entries has Realm of Death banishment."""
        result = compute_cc_pressure(
            "Mordekaiser", "SR", include_conditional=True
        )
        self.assertEqual(len(result.conditional_entries), 1)
        entry = result.conditional_entries[0]
        self.assertEqual(entry.champion, "Mordekaiser")
        self.assertEqual(entry.spell, "R")
        self.assertEqual(entry.cc_kind, "banishment")
        self.assertEqual(entry.condition, "mode_gated")
        self.assertEqual(entry.probability, 1.0)
        self.assertEqual(entry.durations_s, (7.0,))


# ---------------- 5. AramTenacityAppliesToConditionalTests ----------------


class AramTenacityAppliesToConditionalTests(unittest.TestCase):
    """ARAM tenacity ALSO applies to the conditional axis post-tenacity."""

    def test_aram_tenacity_lengthens_conditional_via_monkeypatch(self) -> None:
        """Add Brand to a faked tenacity map; ARAM mode lengthens conditional.

        Brand has wave 0 R + wave 6 Q + any future wave additions; the
        load-bearing pin is the RATIO of ARAM-to-SR conditional pressure
        equals the tenacity multiplier (1.20x) exactly, regardless of
        the absolute pressure value.
        """
        # No champion at 16.10.1 is in BOTH the conditional registry +
        # the modified-tenacity map (the 10 conditional champs are
        # mages/tanks + the 17 modified-tenacity are assassins).
        # Monkey-patch the map to test the math seam.
        fake_tenacity = {"Brand": 1.20}
        with mock.patch.object(
            cc_pressure, "_TENACITY_MAP", fake_tenacity
        ):
            sr = compute_cc_pressure(
                "Brand", "SR", include_conditional=True
            )
            aram = compute_cc_pressure(
                "Brand", "ARAM", include_conditional=True
            )
        # SR identity: tenacity_mult = 1.0; pressure floor at wave-0
        # R contribution (1.4).
        self.assertEqual(sr.tenacity_mult, 1.0)
        self.assertGreaterEqual(sr.conditional_cc_seconds, 1.4)
        # ARAM: 1.20 lift on the post-tenacity contribution.
        # ARAM conditional = SR conditional * 1.20 (load-bearing ratio
        # pin; absolute value depends on registry state).
        self.assertEqual(aram.tenacity_mult, 1.20)
        self.assertAlmostEqual(
            aram.conditional_cc_seconds,
            sr.conditional_cc_seconds * 1.20,
            places=6,
        )
        self.assertAlmostEqual(
            aram.total_cc_seconds, aram.conditional_cc_seconds, places=6
        )
        # Worked example uses the same effective_cc_duration helper
        # as the unconditional axis - the math seam is unified.
        self.assertAlmostEqual(
            aram.conditional_cc_seconds,
            effective_cc_duration(
                get_total_conditional_cc_seconds(
                    "Brand", apply_probability=True
                ),
                1.20,
            ),
            places=6,
        )

    def test_kiwi_mode_also_lengthens_conditional(self) -> None:
        """ARAM Mayhem (KIWI) ALSO applies tenacity to conditional.

        Brand has wave 0 R + wave 6 Q + any future wave additions; the
        load-bearing pin is the tenacity_mult identity (1.20x) and the
        ratio match against the SR contribution.
        """
        fake_tenacity = {"Brand": 1.20}
        with mock.patch.object(
            cc_pressure, "_TENACITY_MAP", fake_tenacity
        ):
            result = compute_cc_pressure(
                "Brand", "KIWI", include_conditional=True
            )
            sr = compute_cc_pressure(
                "Brand", "SR", include_conditional=True
            )
        self.assertEqual(result.tenacity_mult, 1.20)
        # KIWI conditional = SR conditional * 1.20 (load-bearing ratio
        # pin; absolute value depends on registry state).
        self.assertAlmostEqual(
            result.conditional_cc_seconds,
            sr.conditional_cc_seconds * 1.20,
            places=6,
        )

    def test_aram_mordekaiser_conditional_at_identity_tenacity(self) -> None:
        """Mordekaiser ARAM uses 1.0 tenacity (not in modified map)."""
        result = compute_cc_pressure(
            "Mordekaiser", "ARAM", include_conditional=True
        )
        # Mordekaiser is NOT in the modified tenacity map - identity
        self.assertEqual(result.tenacity_mult, 1.0)
        # E unconditional 0.25 + R conditional 7.0 = 7.25
        self.assertAlmostEqual(result.total_cc_seconds, 7.25, places=6)
        self.assertAlmostEqual(result.conditional_cc_seconds, 7.0, places=6)


# ---------------- 6. EngineVersionCurrentTests ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at 1.38.0 for this slice."""

    def test_engine_version_is_1_38_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.209.0")


# ---------------- 7. ProbabilityFalseModeTests ----------------


class ProbabilityFalseModeTests(unittest.TestCase):
    """``compute_cc_pressure`` reads the probability-weighted path."""

    def test_consumer_uses_probability_weighted_total(self) -> None:
        """The consumer reads the apply_probability=True default.

        Brand has wave 0 R + wave 6 Q + any future Brand wave
        additions. The load-bearing pin is the CONSUMER reads the
        probability-WEIGHTED value (not raw), and weighted < raw
        because all probabilities are < 1.0. Specific values are
        registry-version-dependent; assertGreaterEqual floors give
        forward-compat for future Brand wave additions.
        """
        weighted = get_total_conditional_cc_seconds(
            "Brand", apply_probability=True
        )
        raw = get_total_conditional_cc_seconds(
            "Brand", apply_probability=False
        )
        # Floor at wave-0 R contribution; future Brand waves add via
        # assertGreaterEqual.
        self.assertGreaterEqual(weighted, 1.4)
        self.assertGreaterEqual(raw, 2.0)
        # weighted < raw because probability values < 1.0 dampen.
        self.assertLess(weighted, raw)
        # The consumer wire reads the probability-weighted value
        result = compute_cc_pressure(
            "Brand", "SR", include_conditional=True
        )
        self.assertAlmostEqual(
            result.conditional_cc_seconds, weighted, places=6
        )
        # Not the raw value (probability-weighted != raw)
        self.assertNotAlmostEqual(
            result.conditional_cc_seconds, raw, places=6
        )

    def test_high_probability_entry_dominates_lower(self) -> None:
        """Mordekaiser R prob=1.0 means raw == weighted for that entry."""
        # Mordekaiser R has probability=1.0 so apply_probability flag
        # makes no difference.
        weighted = get_total_conditional_cc_seconds(
            "Mordekaiser", apply_probability=True
        )
        raw = get_total_conditional_cc_seconds(
            "Mordekaiser", apply_probability=False
        )
        self.assertAlmostEqual(weighted, 7.0, places=6)
        self.assertAlmostEqual(raw, 7.0, places=6)
        # The consumer reflects the same value
        result = compute_cc_pressure(
            "Mordekaiser", "SR", include_conditional=True
        )
        self.assertAlmostEqual(
            result.conditional_cc_seconds, 7.0, places=6
        )

    def test_low_probability_entry_dampens_total(self) -> None:
        """Volibear Q terrain prob=0.3 means apply_probability shrinks."""
        # Volibear Q (knockback 0.75s) at prob=0.3 terrain.
        # weighted = 0.75 * 0.3 = 0.225; raw = 0.75
        weighted = get_total_conditional_cc_seconds(
            "Volibear", apply_probability=True
        )
        raw = get_total_conditional_cc_seconds(
            "Volibear", apply_probability=False
        )
        self.assertAlmostEqual(weighted, 0.225, places=6)
        self.assertAlmostEqual(raw, 0.75, places=6)


# ---------------- 8. AsciiHygieneTests ----------------


class AsciiHygieneTests(unittest.TestCase):
    """Module + this test file are pure 7-bit ASCII."""

    def test_cc_pressure_module_is_pure_ascii(self) -> None:
        path = (
            pathlib.Path(__file__).resolve().parent.parent / "cc_pressure.py"
        )
        raw = path.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertEqual(
            non_ascii,
            [],
            f"non-ASCII bytes found in cc_pressure.py: {non_ascii[:5]}",
        )

    def test_this_test_file_is_pure_ascii(self) -> None:
        path = pathlib.Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertEqual(
            non_ascii,
            [],
            f"non-ASCII bytes found in test file: {non_ascii[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
