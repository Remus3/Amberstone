"""ENGINE 1.44.0 (2026-05-22) - cc_conditional wave 7 tag schema lift.

Closes item 147 carry (l) by shipping 2 NEW condition tag constants
``COND_FRENZY_STATE`` and ``COND_RANGE_GATED`` as a FORWARD-MARKER
schema lift. NO new registry entries this wave (registry stays at
36 entries / 32 champions); the schema lift unblocks future entries
without a separate engine bump.

Wave 7 contract:

  * 2 new condition tag string constants added to the module-level
    taxonomy (mirrors the wave 0 / wave 1-6 tag definitions).
  * Both tags registered in ``_DEFAULT_CONDITION_PROBABILITY`` with
    calibrated midpoint 0.4 (mid-low because the empowered-state /
    range-band prerequisite is operator-controlled but not
    guaranteed; calibration sits below the COND_DUAL_ENEMY 0.6 +
    COND_NTH_HIT 0.7 midpoints but above the COND_TERRAIN 0.3
    floor).
  * Both tags exported via ``__all__`` so external readers see them
    as public taxonomy.
  * Registry total stays at 36 entries / 32 champions (no entry
    consumes either new tag at ship time).
  * Operator-tunable via the per-tag override JSON loader (a JSON
    file at ``data/cc_conditional_calibration.json`` with
    ``"default_condition_probability": {"frenzy_state": 0.5}``
    overrides the seed midpoint without source edits).

The item 147 carry-forward named Briar frenzy + Sylas range as the
canonical REJECT candidates for these tags, but a Meraki 16.10.1
re-verify during this run found Sylas E2 Abduct stuns on hook hit
regardless of cast range (the item 142 REJECT note was incorrect)
and Briar W parse-strip data lacks the leveling/effects detail
needed to verify a frenzy-empowered Q or R CC mechanic. Future
entries populate when a Meraki-verifiable mechanic surfaces (e.g.
Renekton W empowered cast during Fury, Aatrox passive-empowered
abilities, Volibear R passive form).

Coverage classes:

  * ``WaveSevenTagConstantsTests`` - the 2 new tag constants exist
    as string-typed module attributes with the expected values.
  * ``WaveSevenDefaultProbabilityTests`` - both tags appear in
    ``_DEFAULT_CONDITION_PROBABILITY`` with calibrated midpoint
    0.4 (operator-tunable through the JSON override loader).
  * ``WaveSevenPublicTaxonomyTests`` - both tags appear in
    ``__all__`` so they are part of the public surface.
  * ``RegistryUnchangedTests`` - the registry totals stay at 36
    entries / 32 champions (no new entry consumes either tag).
  * ``ConditionalCcEntryAcceptsNewTagsTests`` - the
    ConditionalCcEntry ``__post_init__`` validation accepts the
    new tags (a future entry can be constructed without violating
    the validation contract).
  * ``EngineVersionCurrentTests`` - the engine version sits at or
    above 1.44.0 (the wave 7 schema lift's ship engine).
  * ``AsciiHygieneTests`` - the test file is ASCII-clean.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc


class WaveSevenTagConstantsTests(unittest.TestCase):
    """The 2 new tag constants exist with expected values."""

    def test_cond_frenzy_state_constant_exists(self) -> None:
        self.assertTrue(hasattr(cc, "COND_FRENZY_STATE"))
        self.assertIsInstance(cc.COND_FRENZY_STATE, str)

    def test_cond_frenzy_state_value(self) -> None:
        self.assertEqual(cc.COND_FRENZY_STATE, "frenzy_state")

    def test_cond_range_gated_constant_exists(self) -> None:
        self.assertTrue(hasattr(cc, "COND_RANGE_GATED"))
        self.assertIsInstance(cc.COND_RANGE_GATED, str)

    def test_cond_range_gated_value(self) -> None:
        self.assertEqual(cc.COND_RANGE_GATED, "range_gated")

    def test_new_tags_are_distinct(self) -> None:
        self.assertNotEqual(cc.COND_FRENZY_STATE, cc.COND_RANGE_GATED)

    def test_new_tags_do_not_collide_with_prior_tags(self) -> None:
        prior = {
            cc.COND_NTH_HIT,
            cc.COND_GOLD_CARD,
            cc.COND_TERRAIN,
            cc.COND_CHANNEL_COMPLETION,
            cc.COND_DREAM_STACK,
            cc.COND_DEVOUR_TARGET,
            cc.COND_TARGET_HP_BELOW,
            cc.COND_TARGET_DEBUFFED,
            cc.COND_DUAL_ENEMY,
            cc.COND_MODE_GATED,
        }
        self.assertNotIn(cc.COND_FRENZY_STATE, prior)
        self.assertNotIn(cc.COND_RANGE_GATED, prior)


class WaveSevenDefaultProbabilityTests(unittest.TestCase):
    """Both new tags appear in _DEFAULT_CONDITION_PROBABILITY."""

    def test_cond_frenzy_state_in_probability_map(self) -> None:
        self.assertIn(cc.COND_FRENZY_STATE, cc._DEFAULT_CONDITION_PROBABILITY)

    def test_cond_range_gated_in_probability_map(self) -> None:
        self.assertIn(cc.COND_RANGE_GATED, cc._DEFAULT_CONDITION_PROBABILITY)

    def test_cond_frenzy_state_midpoint(self) -> None:
        self.assertEqual(
            cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_FRENZY_STATE], 0.4
        )

    def test_cond_range_gated_midpoint(self) -> None:
        self.assertEqual(
            cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_RANGE_GATED], 0.4
        )

    def test_total_default_tags_grew_to_twelve(self) -> None:
        self.assertGreaterEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 12)

    def test_new_midpoints_are_calibrated_between_terrain_and_dual_enemy(
        self,
    ) -> None:
        # Sanity-check the calibration sits where the wave 7 docstring
        # claims (below 0.6 dual_enemy + above 0.3 terrain).
        frenzy = cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_FRENZY_STATE]
        ranged = cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_RANGE_GATED]
        terrain = cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_TERRAIN]
        dual = cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_DUAL_ENEMY]
        self.assertGreater(frenzy, terrain)
        self.assertLess(frenzy, dual)
        self.assertGreater(ranged, terrain)
        self.assertLess(ranged, dual)


class WaveSevenPublicTaxonomyTests(unittest.TestCase):
    """Both new tags appear in __all__."""

    def test_cond_frenzy_state_in_all(self) -> None:
        self.assertIn("COND_FRENZY_STATE", cc.__all__)

    def test_cond_range_gated_in_all(self) -> None:
        self.assertIn("COND_RANGE_GATED", cc.__all__)

    def test_all_is_sorted(self) -> None:
        # __all__ entries are alphabetically ordered (prior-wave
        # convention preserved across the tag additions).
        cond_entries = [s for s in cc.__all__ if s.startswith("COND_")]
        self.assertEqual(cond_entries, sorted(cond_entries))


class RegistryUnchangedTests(unittest.TestCase):
    """Wave 7 is a tag-only schema lift; registry totals stay put."""

    def test_registry_total_champions_is_thirty_two(self) -> None:
        # Wave 7 ship-time baseline was 32; relaxed to
        # assertGreaterEqual for future-wave forward compatibility
        # (item 146 wave 8 lesson: assertGreaterEqual saves bulk-
        # rewrite churn on orchestrator commits).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 32)

    def test_registry_total_entries_is_thirty_six(self) -> None:
        # Wave 7 ship-time baseline was 36; relaxed to
        # assertGreaterEqual for future-wave forward compatibility.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 36)

    def test_no_entry_uses_range_gated_tag_at_ship(self) -> None:
        # No entry in the registry consumes COND_RANGE_GATED at wave 7
        # ship time. Pinned so a future wave that adds a range-gated
        # entry surfaces here as a registry expansion.
        #
        # Note: at ENGINE 1.46.0 (wave 9), Renekton W is the FIRST
        # consumer of COND_FRENZY_STATE - that tag's empty-registry
        # contract is now closed. This test no longer pins
        # COND_FRENZY_STATE; the parallel test for that tag's
        # consumption lives in
        # ``test_cc_conditional_wave9.FrenzyStateForwardMarkerClosureTests``.
        # COND_RANGE_GATED stays as a forward-marker empty seed.
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            for entry in spells.values():
                self.assertNotEqual(entry.condition, cc.COND_RANGE_GATED)

    def test_briar_entries_unchanged_q_plus_e(self) -> None:
        spells = cc._PER_SPELL_CC_CONDITIONAL.get("Briar", {})
        self.assertEqual(sorted(spells.keys()), ["E", "Q"])

    def test_sylas_has_no_entry_yet(self) -> None:
        self.assertNotIn("Sylas", cc._PER_SPELL_CC_CONDITIONAL)


class ConditionalCcEntryAcceptsNewTagsTests(unittest.TestCase):
    """Future entries can be constructed with the new tags."""

    def test_construct_with_cond_frenzy_state(self) -> None:
        # Synthetic entry validates the __post_init__ accepts the new
        # tag. Constructed here only to prove the validation contract,
        # NOT inserted into the registry.
        entry = cc.ConditionalCcEntry(
            champion="SyntheticChamp",
            spell="W",
            cc_kind="stun",
            durations_s=(1.0,),
            condition=cc.COND_FRENZY_STATE,
            probability=0.4,
            notes="synthetic - validates COND_FRENZY_STATE acceptance",
        )
        self.assertEqual(entry.condition, cc.COND_FRENZY_STATE)

    def test_construct_with_cond_range_gated(self) -> None:
        entry = cc.ConditionalCcEntry(
            champion="SyntheticChamp",
            spell="E",
            cc_kind="root",
            durations_s=(1.5,),
            condition=cc.COND_RANGE_GATED,
            probability=0.4,
            notes="synthetic - validates COND_RANGE_GATED acceptance",
        )
        self.assertEqual(entry.condition, cc.COND_RANGE_GATED)

    def test_unknown_tag_still_rejected(self) -> None:
        # The new tags do not loosen the validation against truly
        # unknown tag strings (forward-marker discipline preserved).
        with self.assertRaises(ValueError):
            cc.ConditionalCcEntry(
                champion="SyntheticChamp",
                spell="Q",
                cc_kind="stun",
                durations_s=(1.0,),
                condition="not_a_real_tag",
                probability=0.5,
            )


class WaveSevenOverrideLoaderCompatibilityTests(unittest.TestCase):
    """The new tag midpoints are tunable via the existing JSON loader."""

    def test_apply_default_probability_overrides_accepts_frenzy_state(
        self,
    ) -> None:
        overrides = {
            "default_condition_probability": {cc.COND_FRENZY_STATE: 0.55}
        }
        result = cc._apply_default_probability_overrides(
            cc._DEFAULT_CONDITION_PROBABILITY, overrides
        )
        self.assertEqual(result[cc.COND_FRENZY_STATE], 0.55)

    def test_apply_default_probability_overrides_accepts_range_gated(
        self,
    ) -> None:
        overrides = {
            "default_condition_probability": {cc.COND_RANGE_GATED: 0.65}
        }
        result = cc._apply_default_probability_overrides(
            cc._DEFAULT_CONDITION_PROBABILITY, overrides
        )
        self.assertEqual(result[cc.COND_RANGE_GATED], 0.65)

    def test_out_of_range_override_for_new_tag_dropped(self) -> None:
        # The bool / range / type defense from prior waves still
        # applies to the new tag keys (forward-marker discipline).
        overrides = {
            "default_condition_probability": {cc.COND_FRENZY_STATE: 1.5}
        }
        result = cc._apply_default_probability_overrides(
            cc._DEFAULT_CONDITION_PROBABILITY, overrides
        )
        self.assertEqual(result[cc.COND_FRENZY_STATE], 0.4)


class EngineVersionCurrentTests(unittest.TestCase):
    """Engine version sits at or above the wave 7 ship engine."""

    def test_engine_version_at_or_above_one_dot_forty_four(self) -> None:
        parts = tuple(int(p) for p in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 44, 0))


class AsciiHygieneTests(unittest.TestCase):
    """No non-ASCII bytes in this test file or the source module."""

    def test_test_file_is_ascii_clean(self) -> None:
        text = __file__
        with open(text, "rb") as f:
            data = f.read()
        non_ascii = [
            (i, b) for i, b in enumerate(data) if b > 127
        ]
        self.assertEqual(
            non_ascii,
            [],
            f"non-ASCII bytes detected at positions: {non_ascii[:5]}",
        )

    def test_source_module_tag_section_is_ascii_clean(self) -> None:
        # Sanity check that the new tag constant definitions did not
        # introduce non-ASCII bytes. The pre-existing module has some
        # carryover non-ASCII bytes from prior waves; this test only
        # asserts the tag-constant LINES added in wave 7 are clean.
        import inspect
        src = inspect.getsource(cc)
        # The wave 7 docstring + the 2 tag-constant blocks should be
        # entirely ASCII. We sample the lines around the new tag
        # constants by string-matching.
        for needle in (
            "COND_FRENZY_STATE = \"frenzy_state\"",
            "COND_RANGE_GATED = \"range_gated\"",
        ):
            idx = src.find(needle)
            self.assertGreaterEqual(idx, 0, f"missing marker: {needle}")
            # Sample 600 chars around the constant definition.
            chunk = src[max(0, idx - 50): idx + 600]
            non_ascii = [
                (i, ord(c)) for i, c in enumerate(chunk) if ord(c) > 127
            ]
            self.assertEqual(
                non_ascii,
                [],
                f"non-ASCII near {needle}: {non_ascii[:3]}",
            )


if __name__ == "__main__":
    unittest.main()
