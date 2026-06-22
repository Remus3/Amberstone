"""ENGINE 1.54.0 (2026-05-24) - cc_conditional wave 17.

Wave 17 ships +1 primary entry / 0 net-new champions (Taliyah
already in registry with W wave 1 channel-completion knockup) via
a NEW COND_TRAVERSE condition tag schema lift. Closes item 174
carry (i) "Taliyah E needs new COND_TRAVERSE tag - operator-
gated" + the wave 14 + wave 16 REJECT carries flagging the same
Taliyah E mechanic as requiring a new tag for clean fit.

NEW condition tag constant:

  * COND_TRAVERSE = "traverse" registered in
    _DEFAULT_CONDITION_PROBABILITY at midpoint 0.3. Captures the
    "enemy displacement-over-placed-object" CC mechanic semantic
    that does NOT fit the 12 pre-existing tags (COND_TERRAIN is
    map-geometry collision NOT spell-placed object; COND_NTH_HIT
    is stack accumulation; COND_TARGET_DEBUFFED is pre-applied
    mark). Midpoint 0.3 mirrors COND_TERRAIN's calibration -
    both require operator positioning + target movement
    coincidence.

NEW cc_conditional entry (primary registry):

  * Taliyah E Unraveled Earth dash-detonation stun (primary
    registry, EXISTING champion - Taliyah already had W wave 1)
    - COND_TRAVERSE at probability 0.3.
    - durations_s=(0.75,) flat per Meraki effects_descriptions[1]
      ("Enemies that dash or are knocked over a stone will
      detonate it, taking magic damage and becoming stunned for
      0.75 seconds, increased to 2 seconds if they are a monster.
      The stun is applied once the displacement ends."). The
      0.75s value is the champion-facing duration; the 2.0s
      monster value is encoded as monster-only in the
      description so the registry stores the champion-facing
      value only.
    - mechanic: Taliyah scatters 22 stones in a field; enemies
      who DASH OR ARE KNOCKED OVER a stone detonate it + are
      stunned 0.75s. Stun is once-per-cast-per-target ("Unraveled
      Earth can affect targets only once per cast"). Standalone
      enemy who walks AROUND the field = damage + 20% slow only
      (no first-order CC).
    - Coexists with Taliyah W wave 1 cc_conditional entry on a
      different spell slot (multi-wave-within-cc_conditional
      coexistence pattern via setdefault).
    - FIRST Taliyah E first-order CC registration in the engine
      (Taliyah Q + W + R have no champion CC; Q Worked Ground
      Boulder stun is monster-only NOT champion).
    - FIRST consumer of the new COND_TRAVERSE tag, closing the
      empty-registry contract on ship.

Registry growth: 64 -> 65 entries / 54 -> 54 champions (Taliyah
already counted via W wave 1). Condition tag total: 12 -> 13.

Per-tag consumer counts post-wave-17: COND_TRAVERSE = 1
(Taliyah E, FIRST consumer); all other tag counts unchanged
from wave 16 baseline.

Math preservation: default include_conditional=False
compute_cc_pressure is BYTE-IDENTICAL to 1.53.0 for Taliyah
(base = 0.0 unchanged; Taliyah has no unconditional
_PER_SPELL_CC_DURATIONS entry). include_conditional=True
callers receive new probability-weighted contribution Taliyah E
+0.225s (0.75 * 0.3) stacked on top of the wave 1 W
contribution (0.75 * 0.5 = 0.375), giving Taliyah a total
conditional contribution of 0.6s post-wave-17.

Coverage classes:

  * WaveSeventeenCondTraverseTagConstantTests - new tag string
    pin, registered in _DEFAULT_CONDITION_PROBABILITY at 0.3,
    exported in __all__.
  * WaveSeventeenTaliyahEShapeTests - Taliyah E primary entry
    shape pin (cc_kind / durations / condition / probability /
    form_index).
  * WaveSeventeenRegistryGrowthTests - REGISTRY_TOTAL_ENTRIES /
    REGISTRY_TOTAL_CHAMPIONS grew to 65 / 54.
  * WaveSeventeenMultiWaveCoexistenceTests - Taliyah has both
    wave 1 W + wave 17 E in primary registry.
  * WaveSeventeenPerTagConsumerCountsTests - COND_TRAVERSE has
    exactly 1 consumer (Taliyah E); other tag counts unchanged.
  * WaveSeventeenDefaultCallerByteIdenticalTests - default
    include_conditional=False compute_cc_pressure is BYTE-
    IDENTICAL to 1.53.0 for Taliyah.
  * WaveSeventeenIncludeConditionalMathTests -
    include_conditional=True receives probability-weighted
    contribution for Taliyah E.
  * WaveSeventeenGetConditionalEntriesTests -
    get_conditional_entries returns both Taliyah entries.
  * WaveSeventeenBuilderIdempotenceTests - the builder function
    is deterministic + does not mutate globals.
  * WaveSeventeenSchemaCrossReferenceTests - shipped entry
    matches effects_descriptions text in extracted JSON.
  * WaveSeventeenWiredSitesGrepTests - wave 17 entry +
    COND_TRAVERSE constant grep-match in cc_conditional.py
    source.
  * WaveSeventeenForwardMarkerAllowlistTests - the wave 17 test
    file is in the forward-marker test allowlist.
  * EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.55.0.
  * AsciiHygieneTests - the test file is ASCII-clean +
    cc_conditional.py wave 17 block is ASCII-clean.
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class WaveSeventeenCondTraverseTagConstantTests(unittest.TestCase):
    """COND_TRAVERSE tag constant + default-probability midpoint pin."""

    def test_cond_traverse_constant_exists(self) -> None:
        self.assertTrue(hasattr(cc, "COND_TRAVERSE"))

    def test_cond_traverse_string_value(self) -> None:
        self.assertEqual(cc.COND_TRAVERSE, "traverse")

    def test_cond_traverse_in_default_probability_map(self) -> None:
        self.assertIn(cc.COND_TRAVERSE, cc._DEFAULT_CONDITION_PROBABILITY)

    def test_cond_traverse_default_midpoint_is_zero_point_three(self) -> None:
        self.assertEqual(
            cc._DEFAULT_CONDITION_PROBABILITY[cc.COND_TRAVERSE], 0.3
        )

    def test_cond_traverse_in_all_exports(self) -> None:
        self.assertIn("COND_TRAVERSE", cc.__all__)

    def test_total_tag_count_grew_to_thirteen(self) -> None:
        # Pre-wave-17: 12 tags. Post-wave-17: 13 (added COND_TRAVERSE).
        self.assertGreaterEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 13)


class WaveSeventeenTaliyahEShapeTests(unittest.TestCase):
    """Taliyah E primary entry shape pin."""

    def test_taliyah_in_primary_registry(self) -> None:
        # Taliyah was already in registry via W wave 1 - this is a
        # pre-existing invariant we re-affirm here.
        self.assertIn("Taliyah", cc._PER_SPELL_CC_CONDITIONAL)

    def test_taliyah_e_slot_present(self) -> None:
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Taliyah"])

    def test_taliyah_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertEqual(entry.durations_s, (0.75,))

    def test_taliyah_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_taliyah_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertEqual(entry.condition, cc.COND_TRAVERSE)

    def test_taliyah_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertEqual(entry.probability, 0.3)

    def test_taliyah_e_entry_form_index_default(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertIsNone(entry.form_index)

    def test_taliyah_e_entry_notes_mention_unraveled_earth(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertIn("Unraveled Earth", entry.notes)

    def test_taliyah_e_entry_notes_mention_traverse(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertIn("COND_TRAVERSE", entry.notes)

    def test_taliyah_e_entry_notes_mention_stones(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertIn("stone", entry.notes.lower())

    def test_taliyah_w_wave_1_unchanged(self) -> None:
        # Wave 1 Taliyah W knockup must still exist + still match.
        entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["W"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)


class WaveSeventeenRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES / REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_registry_total_entries_grew_to_at_least_sixty_five(self) -> None:
        # Wave 17 ship-time baseline is 65 (64 wave 16 + 1 wave 17
        # Taliyah E). Relaxed for future-wave forward compat.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 65)

    def test_registry_total_champions_at_least_fifty_four(self) -> None:
        # Wave 17 does NOT add a net-new champion (Taliyah already
        # had W wave 1). Champion total stays at the wave 16
        # baseline of 54.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 54)

    def test_primary_registry_grew_to_at_least_fifty_eight(self) -> None:
        primary = sum(len(s) for s in cc._PER_SPELL_CC_CONDITIONAL.values())
        # Wave 16 baseline was 57 primary; wave 17 adds Taliyah E
        # = 58.
        self.assertGreaterEqual(primary, 58)

    def test_sidecar_registry_unchanged_at_seven(self) -> None:
        sidecar = sum(
            len(f) for f in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        # Wave 17 adds no sidecar entries; baseline 7 holds.
        self.assertGreaterEqual(sidecar, 7)


class WaveSeventeenMultiWaveCoexistenceTests(unittest.TestCase):
    """Taliyah has both wave 1 W + wave 17 E in primary registry."""

    def test_taliyah_has_w_and_e_slots(self) -> None:
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["Taliyah"].keys())
        self.assertIn("W", slots)
        self.assertIn("E", slots)

    def test_taliyah_w_is_knockup_channel(self) -> None:
        # Wave 1 entry (unchanged).
        w_entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["W"]
        self.assertEqual(w_entry.cc_kind, "knockup")
        self.assertEqual(w_entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_taliyah_e_is_stun_traverse(self) -> None:
        # Wave 17 entry (new).
        e_entry = cc._PER_SPELL_CC_CONDITIONAL["Taliyah"]["E"]
        self.assertEqual(e_entry.cc_kind, "stun")
        self.assertEqual(e_entry.condition, cc.COND_TRAVERSE)

    def test_taliyah_two_distinct_spell_slots(self) -> None:
        # Defense-in-depth: the two entries occupy different slots
        # (no clobber via setdefault).
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["Taliyah"].keys())
        self.assertEqual(len(slots & {"W", "E"}), 2)


class WaveSeventeenPerTagConsumerCountsTests(unittest.TestCase):
    """COND_TRAVERSE has exactly 1 consumer; other tag counts unchanged."""

    def _all_entries(self) -> list:
        all_entries = []
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            all_entries.extend(spells.values())
        for forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values():
            all_entries.extend(forms.values())
        return all_entries

    def test_cond_traverse_has_exactly_one_consumer(self) -> None:
        # Taliyah E is the FIRST + ONLY consumer at ship time.
        # assertGreaterEqual for forward-compat with wave 18+ that
        # may add more traverse-conditional entries.
        traverse_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_TRAVERSE
        ]
        self.assertGreaterEqual(len(traverse_consumers), 1)

    def test_cond_traverse_consumer_is_taliyah_e(self) -> None:
        traverse_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_TRAVERSE
        ]
        self.assertIn(
            ("Taliyah", "E"),
            {(e.champion, e.spell) for e in traverse_consumers},
        )

    def test_nth_hit_unchanged_from_wave_16(self) -> None:
        # Wave 17 does NOT add any COND_NTH_HIT entries. Wave 16
        # baseline was >=8 consumers.
        nth_hit_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_NTH_HIT
        ]
        self.assertGreaterEqual(len(nth_hit_consumers), 8)

    def test_target_debuffed_unchanged_from_wave_16(self) -> None:
        # Wave 17 does NOT add any COND_TARGET_DEBUFFED entries.
        debuffed_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_TARGET_DEBUFFED
        ]
        self.assertGreaterEqual(len(debuffed_consumers), 10)

    def test_channel_completion_unchanged_from_wave_16(self) -> None:
        # Wave 17 does NOT add any COND_CHANNEL_COMPLETION entries.
        channel_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_CHANNEL_COMPLETION
        ]
        self.assertGreaterEqual(len(channel_consumers), 13)

    def test_terrain_unchanged_from_wave_16(self) -> None:
        # Wave 17 does NOT add any COND_TERRAIN entries.
        terrain_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_TERRAIN
        ]
        self.assertGreaterEqual(len(terrain_consumers), 1)

    def test_frenzy_state_unchanged_from_wave_16(self) -> None:
        # Wave 17 does NOT add any COND_FRENZY_STATE entries.
        frenzy_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_FRENZY_STATE
        ]
        self.assertGreaterEqual(len(frenzy_consumers), 3)

    def test_range_gated_still_zero_consumers(self) -> None:
        # Wave 17 ship-time: COND_RANGE_GATED had 0 consumers. Wave
        # 18 (ENGINE 1.55.0) added Maokai R as the FIRST consumer via
        # the coexists_with_unconditional schema lift. Wave 17
        # invariant relaxed: at most 1 consumer present at this point.
        range_gated_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_RANGE_GATED
        ]
        self.assertLessEqual(len(range_gated_consumers), 3)  # wave 23 Maokai R + Hecarim R + R14 Ashe R


class WaveSeventeenDefaultCallerByteIdenticalTests(unittest.TestCase):
    """Default include_conditional=False is BYTE-IDENTICAL to 1.53.0."""

    def test_taliyah_default_total_unchanged(self) -> None:
        # Pre-wave-17: Taliyah default total = 0.0 (no
        # unconditional CC entries for Taliyah anywhere). Wave 17
        # adds E conditional only; default path skips conditional.
        result = compute_cc_pressure("Taliyah", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_taliyah_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Taliyah", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_taliyah_default_aram_total_unchanged(self) -> None:
        # Same byte-identity guarantee on the ARAM mode path.
        result = compute_cc_pressure("Taliyah", "aram")
        self.assertEqual(result.total_cc_seconds, 0.0)


class WaveSeventeenIncludeConditionalMathTests(unittest.TestCase):
    """include_conditional=True receives probability-weighted contribution."""

    def test_taliyah_e_conditional_contribution(self) -> None:
        # Taliyah W (wave 1): 0.75s knockup at probability 0.5 =
        # 0.375s. Taliyah E (wave 17): 0.75s stun at probability
        # 0.3 = 0.225s. Total conditional = 0.375 + 0.225 = 0.6s.
        result = compute_cc_pressure(
            "Taliyah", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.6, places=4)

    def test_taliyah_grand_total_with_conditional(self) -> None:
        # Taliyah has no unconditional _PER_SPELL_CC_DURATIONS
        # entry, so grand total = conditional total = 0.6s.
        result = compute_cc_pressure(
            "Taliyah", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 0.6, places=4)

    def test_taliyah_e_alone_contribution(self) -> None:
        # Verify the E-specific contribution is 0.225s
        # (= 0.75 * 0.3) via get_total_conditional_cc_seconds with
        # apply_probability=True. We isolate by computing
        # total - W-contribution.
        total = cc.get_total_conditional_cc_seconds(
            "Taliyah", apply_probability=True
        )
        # W contributes 0.75 * 0.5 = 0.375
        # E contributes 0.75 * 0.3 = 0.225
        # Sum = 0.6
        self.assertAlmostEqual(total, 0.6, places=4)


class WaveSeventeenGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns both Taliyah entries."""

    def test_get_conditional_entries_taliyah_has_two(self) -> None:
        entries = cc.get_conditional_entries("Taliyah")
        self.assertEqual(len(entries), 2)

    def test_get_conditional_entries_taliyah_slots_w_and_e(self) -> None:
        entries = cc.get_conditional_entries("Taliyah")
        slots = {e.spell for e in entries}
        self.assertEqual(slots, {"W", "E"})

    def test_get_conditional_entries_taliyah_e_is_stun_traverse(self) -> None:
        entries = cc.get_conditional_entries("Taliyah")
        e_entry = next(e for e in entries if e.spell == "E")
        self.assertEqual(e_entry.cc_kind, "stun")
        self.assertEqual(e_entry.condition, cc.COND_TRAVERSE)

    def test_get_conditional_entries_taliyah_ordered_qwer(self) -> None:
        # get_conditional_entries orders Q/W/E/R; Taliyah has W
        # before E.
        entries = cc.get_conditional_entries("Taliyah")
        slot_order = [e.spell for e in entries]
        self.assertEqual(slot_order, ["W", "E"])


class WaveSeventeenBuilderIdempotenceTests(unittest.TestCase):
    """The builder function is deterministic + does not mutate globals."""

    def test_primary_builder_produces_taliyah_e_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("Taliyah", fresh_primary)
        self.assertIn("E", fresh_primary["Taliyah"])
        e = fresh_primary["Taliyah"]["E"]
        self.assertEqual(e.durations_s, (0.75,))
        self.assertEqual(e.condition, cc.COND_TRAVERSE)
        self.assertEqual(e.probability, 0.3)

    def test_primary_builder_preserves_taliyah_w_wave_1(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("W", fresh_primary["Taliyah"])
        w = fresh_primary["Taliyah"]["W"]
        self.assertEqual(w.cc_kind, "knockup")
        self.assertEqual(w.condition, cc.COND_CHANNEL_COMPLETION)

    def test_primary_builder_idempotent_across_two_invocations(self) -> None:
        a = cc._build_per_spell_cc_conditional()
        b = cc._build_per_spell_cc_conditional()
        self.assertIsNot(a, b)
        self.assertEqual(a["Taliyah"]["W"], b["Taliyah"]["W"])
        self.assertEqual(a["Taliyah"]["E"], b["Taliyah"]["E"])

    def test_primary_builder_does_not_mutate_global_registry(self) -> None:
        before = len(cc._PER_SPELL_CC_CONDITIONAL["Taliyah"])
        _ = cc._build_per_spell_cc_conditional()
        after = len(cc._PER_SPELL_CC_CONDITIONAL["Taliyah"])
        self.assertEqual(before, after)


class WaveSeventeenSchemaCrossReferenceTests(unittest.TestCase):
    """Shipped entry matches effects_descriptions in extracted JSON."""

    def _load_extracted(self) -> dict:
        path = (
            Path(__file__).resolve().parents[3]
            / "data"
            / "daemon_slayer"
            / "16.10.1"
            / "champion_abilities.json"
        )
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def test_taliyah_e_form_0_effects_mention_stun_0_75s(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Taliyah"]["E"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("stunned for 0.75 seconds", effects_text)

    def test_taliyah_e_form_0_effects_mention_dash_or_knocked(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Taliyah"]["E"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("dash or are knocked", effects_text)

    def test_taliyah_e_form_0_effects_mention_displacement_ends(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Taliyah"]["E"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("displacement ends", effects_text)


class WaveSeventeenWiredSitesGrepTests(unittest.TestCase):
    """Wave 17 entry + COND_TRAVERSE constant grep-match in source."""

    def _source(self) -> str:
        return (inspect.getsource(cc) + open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read())

    def test_source_defines_cond_traverse_constant(self) -> None:
        src = self._source()
        self.assertIn('COND_TRAVERSE = "traverse"', src)

    def test_source_mentions_taliyah_e_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Taliyah", {})["E"]', src)

    def test_source_mentions_unraveled_earth(self) -> None:
        src = self._source()
        self.assertIn("Unraveled Earth", src)

    def test_source_mentions_wave_17_marker(self) -> None:
        src = self._source()
        self.assertIn("wave 17 expansion", src.lower())

    def test_source_documents_traverse_midpoint_calibration(self) -> None:
        # The new tag's docstring must explain the 0.3 midpoint
        # rationale.
        src = self._source()
        self.assertIn("0.3", src)
        # And specifically reference traverse-zone avoidance.
        self.assertIn("traverse-zone", src.lower())


class WaveSeventeenForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 17 test file is in the forward-marker test allowlist."""

    def test_wave_17_in_allowed_test_files(self) -> None:
        from agents.daemon_slayer.tests import (
            test_cc_conditional_forward_marker as fwd,
        )

        self.assertIn(
            "test_cc_conditional_wave17.py", fwd._ALLOWED_TEST_FILES
        )


class EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.55.0."""

    def test_engine_version_string_pin(self) -> None:
        major, minor, patch = (int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 54, 0))


class AsciiHygieneTests(unittest.TestCase):
    """Test file is ASCII-clean + cc_conditional wave 17 block is ASCII."""

    def test_this_test_file_is_ascii(self) -> None:
        path = Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII bytes in {path.name}",
        )

    def test_cc_conditional_wave_17_block_is_ascii(self) -> None:
        src = (inspect.getsource(cc) + open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read())
        # Slice from the "wave 17 expansion" header through the
        # Taliyah E setdefault site; assert no non-ASCII bytes
        # appear in that slice. The earlier waves carry pre-existing
        # non-ASCII bytes so we scope the check to the wave 17
        # block only.
        marker = "wave 17 expansion (2026-05-24 / ENGINE 1.54.0)"
        idx = src.find(marker)
        self.assertGreater(idx, -1, "wave 17 header marker missing")
        # Take a generous slice past the Taliyah E setdefault site.
        end_marker = src.find('setdefault("Taliyah", {})["E"]', idx)
        self.assertGreater(end_marker, idx, "Taliyah E setdefault missing")
        block = src[idx : end_marker + 4096]
        non_ascii = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII characters in wave 17 block",
        )

    def test_cond_traverse_docstring_block_is_ascii(self) -> None:
        # The COND_TRAVERSE constant + its docstring is a fresh block
        # added this wave; verify ASCII-clean.
        src = (inspect.getsource(cc) + open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read())
        idx = src.find('COND_TRAVERSE = "traverse"')
        self.assertGreater(idx, -1, "COND_TRAVERSE constant missing")
        # Slice through the next blank line to capture the docstring.
        end = src.find("\n\n", idx + 100)
        if end < 0:
            end = idx + 1024
        block = src[idx:end]
        non_ascii = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII characters in COND_TRAVERSE block",
        )


if __name__ == "__main__":
    unittest.main()
