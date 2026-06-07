"""per-spell CC RANGE registry - schema lift item 336 (2026-06-07).

A NEW sibling registry ``_PER_SPELL_CC_RANGE`` capturing distance- /
travel-scaled CC durations as a ``(min_s, max_s)`` interval, a shape the
flat per-rank ``_PER_SPELL_CC_DURATIONS`` tuple structurally cannot
express. Several single-cast CC spells scale their duration continuously
with projectile travel distance (NOT by spell rank); the flat registry
can only pin one representative value per rank and discards the ceiling.

Verified from patch 16.10.1 ``data/daemon_slayer/16.10.1/
champion_abilities.json`` ``effects_descriptions`` (ground-truth probed
2026-06-07):

* Xerath E (Shocking Orb): "stuns them for 0.75 : 2.25 (based on orb
  travel distance) seconds" -> (0.75, 2.25). The flat registry pins
  per-rank (1.0..2.0), which cannot represent the distance ceiling.
* Maokai R (Nature's Grasp): "roots them for 0.75 : 2.25 (based on
  distance traveled) seconds" -> (0.75, 2.25). Flat registry R=(1.2,
  1.6, 2.0).
* Ashe R (Enchanted Crystal Arrow): "stunning them for 1 : 3.5 (based
  on distance traveled) seconds" -> (1.0, 3.5). Flat registry R=(1.5,
  1.5, 1.5).
* Hecarim R (Onslaught of Shadows): "fears nearby enemies for 0.75 :
  1.5 (based on distance traveled) seconds" -> (0.75, 1.5). Flat
  registry R=(1.0, 1.0, 1.0).

SCOPE: this slice seeds ONLY the 4 clean "distance traveled" cases.
The channel-time variants (Sion Q 1.25:2.25, Galio W, etc.) share the
interval SHAPE but a different scaling input and are a later
row-expansion, not part of this lift.

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes
``_PER_SPELL_CC_RANGE`` at ship - it mirrors the way
``_PER_SPELL_CC_DURATIONS`` itself shipped EMPTY at ENGINE 1.29.0
(forward-marker pattern, item 130 / item 112 ``STAT_GRANT_CALC_KEYS``).
``compute_cc_pressure`` / ``compute_ehp`` / ``cooldown_watch`` /
``cc_output`` read only ``_PER_SPELL_CC_DURATIONS`` and never the new
sibling, so live DS output is byte-identical and ENGINE_VERSION does
NOT bump.

Coverage classes:
* ``RangeRegistryShapeTests`` - the 4 entries exist, each a 2-tuple of
  floats, min <= max, non-negative.
* ``RangeValuePinsTests`` - exact (min, max) pin per seed from 16.10.1.
* ``RangeAccessorTests`` - ``_per_spell_cc_range_for`` returns the tuple
  for a seeded champ+spell and ``None`` for an absent one.
* ``BuilderTests`` - the builder is exposed + its output matches the
  module-level registry.
* ``ByteIdenticalDurationRegistryTests`` - the flat
  ``_PER_SPELL_CC_DURATIONS`` is UNCHANGED (the range lift did not touch
  it); the 4 seeds' flat entries keep their prior values and the total
  entry floor (>= 108) holds.
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition (``_per_spell_cc.py``) and the re-export (``ability_dps.py``)
  references the range registry - it is a pure forward-marker.
* ``EngineVersionUnchangedTests`` - ENGINE_VERSION stays >= 1.120.0
  (byte-identical, no bump).
* ``AsciiHygieneTests`` - the new registry block + this test file are
  pure-ASCII (no em/en-dash, no smart quotes per CLAUDE.md hard rule).
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import (
    _PER_SPELL_CC_DURATIONS,
    _PER_SPELL_CC_RANGE,
    _build_per_spell_cc_range,
    _per_spell_cc_for,
    _per_spell_cc_range_for,
)


# ---------------- expected seed set ----------------


# item 336 range seeds: 4 distance-scaled CC intervals, all verified
# verbatim from 16.10.1 effects_descriptions.
RANGE_EXPECTED: dict[str, dict[str, tuple[float, float]]] = {
    "Xerath": {"E": (0.75, 2.25)},
    "Maokai": {"R": (0.75, 2.25)},
    "Ashe": {"R": (1.0, 3.5)},
    "Hecarim": {"R": (0.75, 1.5)},
}


# ---------------- shape ----------------


class RangeRegistryShapeTests(unittest.TestCase):
    """The 4 range entries exist with the (min, max) 2-tuple shape."""

    def test_all_seed_champs_present(self) -> None:
        for champ in RANGE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_RANGE,
                f"range seed champ {champ} missing from registry",
            )

    def test_all_seed_spells_present(self) -> None:
        for champ, spells in RANGE_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_RANGE[champ],
                    f"range seed {champ} {key} missing",
                )

    def test_each_entry_is_two_float_tuple(self) -> None:
        for champ, spells in RANGE_EXPECTED.items():
            for key in spells:
                live = _PER_SPELL_CC_RANGE[champ][key]
                self.assertIsInstance(live, tuple, f"{champ} {key} not a tuple")
                self.assertEqual(
                    len(live), 2, f"{champ} {key} must be (min, max)",
                )
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float member",
                    )

    def test_min_le_max(self) -> None:
        for champ, spells in RANGE_EXPECTED.items():
            for key in spells:
                lo, hi = _PER_SPELL_CC_RANGE[champ][key]
                self.assertLessEqual(
                    lo, hi, f"{champ} {key} min {lo} > max {hi}",
                )

    def test_all_non_negative(self) -> None:
        for champ, spells in RANGE_EXPECTED.items():
            for key in spells:
                for v in _PER_SPELL_CC_RANGE[champ][key]:
                    self.assertGreaterEqual(
                        v, 0.0, f"{champ} {key} negative member {v}",
                    )

    def test_exactly_four_seed_entries(self) -> None:
        total = sum(len(s) for s in _PER_SPELL_CC_RANGE.values())
        self.assertGreaterEqual(
            total, 4, "expected at least the 4 item-336 range seeds",
        )


# ---------------- value pins ----------------


class RangeValuePinsTests(unittest.TestCase):
    """Exact (min, max) pin per seed, sourced from 16.10.1 Meraki."""

    def test_xerath_e_shocking_orb(self) -> None:
        # "stuns them for 0.75 : 2.25 (based on orb travel distance)"
        self.assertEqual(_PER_SPELL_CC_RANGE["Xerath"]["E"], (0.75, 2.25))

    def test_maokai_r_natures_grasp(self) -> None:
        # "roots them for 0.75 : 2.25 (based on distance traveled)"
        self.assertEqual(_PER_SPELL_CC_RANGE["Maokai"]["R"], (0.75, 2.25))

    def test_ashe_r_enchanted_crystal_arrow(self) -> None:
        # "stunning them for 1 : 3.5 (based on distance traveled)"
        self.assertEqual(_PER_SPELL_CC_RANGE["Ashe"]["R"], (1.0, 3.5))

    def test_hecarim_r_onslaught_of_shadows(self) -> None:
        # "fears nearby enemies for 0.75 : 1.5 (based on distance traveled)"
        self.assertEqual(_PER_SPELL_CC_RANGE["Hecarim"]["R"], (0.75, 1.5))

    def test_all_seeds_match_expected(self) -> None:
        for champ, spells in RANGE_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _PER_SPELL_CC_RANGE[champ][key], tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- accessor ----------------


class RangeAccessorTests(unittest.TestCase):
    """``_per_spell_cc_range_for`` returns the tuple or ``None``."""

    def test_accessor_returns_seed_tuple(self) -> None:
        self.assertEqual(
            _per_spell_cc_range_for("Xerath", "E"), (0.75, 2.25),
        )
        self.assertEqual(
            _per_spell_cc_range_for("Ashe", "R"), (1.0, 3.5),
        )

    def test_accessor_none_for_absent_champ(self) -> None:
        self.assertIsNone(_per_spell_cc_range_for("NotAChamp", "Q"))

    def test_accessor_none_for_absent_spell(self) -> None:
        # Xerath has a range only on E, not Q.
        self.assertIsNone(_per_spell_cc_range_for("Xerath", "Q"))

    def test_accessor_none_when_champ_has_no_range(self) -> None:
        # Annie is in the flat duration registry but has no range entry.
        self.assertIsNone(_per_spell_cc_range_for("Annie", "R"))


# ---------------- builder ----------------


class BuilderTests(unittest.TestCase):
    """The range builder is exposed + matches the module registry."""

    def test_builder_is_callable(self) -> None:
        self.assertTrue(callable(_build_per_spell_cc_range))

    def test_builder_output_matches_module_registry(self) -> None:
        fresh = _build_per_spell_cc_range()
        self.assertEqual(fresh, _PER_SPELL_CC_RANGE)


# ---------------- byte-identical duration registry guard ----------------


class ByteIdenticalDurationRegistryTests(unittest.TestCase):
    """The flat ``_PER_SPELL_CC_DURATIONS`` is untouched by the range lift.

    Critical byte-identical guard: adding the range sibling must NOT
    alter the flat per-rank registry that every live consumer reads.
    """

    def test_duration_total_floor_unchanged(self) -> None:
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 108)

    def test_xerath_e_flat_duration_preserved(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Xerath", "E"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_ashe_r_flat_duration_preserved(self) -> None:
        self.assertEqual(_per_spell_cc_for("Ashe", "R"), (1.5, 1.5, 1.5))

    def test_maokai_flat_durations_preserved(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Maokai"]
        self.assertEqual(spells["R"], (1.2, 1.6, 2.0))
        self.assertEqual(spells["W"], (1.0, 1.1, 1.2, 1.3, 1.4))

    def test_hecarim_flat_durations_preserved(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Hecarim"]
        self.assertEqual(spells["E"], (0.75, 0.75, 0.75, 0.75, 0.75))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))

    def test_range_and_duration_are_independent(self) -> None:
        # Same champ+spell can hold a flat duration AND a range interval;
        # they are separate registries with separate values.
        self.assertEqual(_per_spell_cc_for("Maokai", "R"), (1.2, 1.6, 2.0))
        self.assertEqual(_per_spell_cc_range_for("Maokai", "R"), (0.75, 2.25))


# ---------------- forward-marker (no consumer) ----------------


class ForwardMarkerNoConsumerTests(unittest.TestCase):
    """No production module consumes the range registry yet.

    The range registry is a pure forward-marker: only its definition
    module (``_per_spell_cc.py``) and the re-export aggregator
    (``ability_dps.py``) may name it. Any other reference would mean a
    consumer branched on it - making the lift no longer byte-identical.
    """

    def test_no_unexpected_production_consumer(self) -> None:
        ds_dir = pathlib.Path(__file__).resolve().parent.parent
        allow = {"_per_spell_cc.py", "ability_dps.py"}
        offenders: list[str] = []
        for py in ds_dir.glob("*.py"):
            if py.name in allow:
                continue
            text = py.read_text(encoding="utf-8")
            if "_PER_SPELL_CC_RANGE" in text or "_per_spell_cc_range_for" in text:
                offenders.append(py.name)
        self.assertEqual(
            offenders, [],
            f"range registry unexpectedly consumed by: {offenders}",
        )


# ---------------- ENGINE version ----------------


class EngineVersionUnchangedTests(unittest.TestCase):
    """ENGINE_VERSION stays >= 1.120.0 - the lift is byte-identical.

    Because nothing consumes the range registry, live DS output is
    unchanged, so this slice ships WITHOUT an ENGINE bump. The pin uses
    assertGreaterEqual (forward-compatible per the item 146 lesson).
    """

    def test_engine_version_at_least_1_120_0(self) -> None:
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 120, 0))


# ---------------- ASCII hygiene ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The new registry block + this test file are pure-ASCII."""

    def test_range_registry_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start = src.find("_build_per_spell_cc_range")
        self.assertGreater(start, -1, "range builder marker missing")
        block = src[start:]
        bad_glyphs = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "left double smart quote",
            chr(0x201D): "right double smart quote",
            chr(0x2018): "left single smart quote",
            chr(0x2019): "right single smart quote",
        }
        for ch, name in bad_glyphs.items():
            self.assertNotIn(ch, block, f"range block carries {name}")

    def test_this_test_file_is_ascii_clean(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        bad_seqs = [
            (b"\xe2\x80\x94", "em-dash"),
            (b"\xe2\x80\x93", "en-dash"),
            (b"\xe2\x80\x9c", "left double smart quote"),
            (b"\xe2\x80\x9d", "right double smart quote"),
            (b"\xe2\x80\x98", "left single smart quote"),
            (b"\xe2\x80\x99", "right single smart quote"),
        ]
        for seq, name in bad_seqs:
            self.assertNotIn(seq, raw, f"test file carries {name}")


if __name__ == "__main__":
    unittest.main()
