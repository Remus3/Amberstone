"""Wave 11 cc_conditional expansion tests (ENGINE 1.48.0, 2026-05-23).

Wave 11 ships +2 entries / +2 net-new champions closing 2 schema-lift-
verified candidates that did NOT need a separate extractor schema lift:

  * Sion R Unstoppable Onslaught (primary registry) -
    COND_CHANNEL_COMPLETION stun 1.0s representative midpoint
    (channel-time-gated 0.25-1.75s range per effects_descriptions
    "Enemies in a smaller radius are also pulled towards Sion over
    0.5 seconds and become stunned after a brief delay for 0.25 :
    1.75 (based on channel time) seconds"). Coexists with the
    unconditional Sion Q stun 1.25-2.25s in
    ``_PER_SPELL_CC_DURATIONS`` on a different spell slot.

  * Gnar W form_index=1 Wallop (sidecar registry, Mega-rage-form-
    gated stun) - COND_FRENZY_STATE stun 1.25s flat. Mini-form W
    (form_index=0, Hyper) is a passive on-hit stack with NO first-
    order CC. Maps to COND_FRENZY_STATE as the THIRD consumer of
    that tag (after Renekton W wave 9 + Karma W form 1 wave 10).
    Coexists with Gnar R unconditional terrain-collision stun
    0.75s in ``_PER_SPELL_CC_DURATIONS`` on a different spell slot.

Wave 11 REJECT verdicts (effects_descriptions schema-lift-verified
this run; documented in commit body):

  * Aatrox R minion-only fear (CONFIRMED-REJECT)
  * Volibear R turret-only disable + slow only (CONFIRMED-REJECT)
  * Briar W self-buff frenzy state (CONFIRMED-REJECT)
  * Sion E minion-only stun (CONFIRMED-REJECT)
  * Lillia W damage + center-bonus only (CONFIRMED-REJECT)
  * Ekko R self-stasis + damage only (CONFIRMED-REJECT)
  * Smolder R damage + Smolder-heal only (CONFIRMED-REJECT)
  * Karma E shield + MS only both forms (CONFIRMED-REJECT)
  * Vladimir R damage amp + delayed burst + Vlad-heal (CONFIRMED-REJECT)
  * Akshan Q/R damage + buffs only (CONFIRMED-REJECT)
  * Tristana E damage stacking detonation only (CONFIRMED-REJECT)
  * Kayle E/R no CC (CONFIRMED-REJECT)
  * Nidalee R transform only, no CC; sub-forms no CC (CONFIRMED-REJECT)

Wave 11 DEFERRED (would need additional verification):

  * Jayce E Thundering Blow - cast-time root duration value NOT in
    effects_descriptions or damage_blocks; CARRY-FORWARD wave 12+.
  * Singed E Fling Mega-Adhesive overlap root - description says
    "for a duration" with no value; CARRY-FORWARD wave 12+.

Math preservation:

  * Default include_conditional=False callers BYTE-IDENTICAL to
    1.47.0 across all 5 consumer surfaces.
  * include_conditional=True callers gain +1 Sion R contribution +
    +1 Gnar W form 1 contribution.

Tests pin:

  * Per-entry shape (champion / spell / cc_kind / condition /
    form_index / duration tuple) for both wave-11 entries.
  * Multi-wave coexistence: Sion R primary + Sion Q unconditional;
    Gnar W form 1 sidecar + Gnar R unconditional.
  * REGISTRY_TOTAL_ENTRIES grows 44 -> 46 (assertGreaterEqual for
    forward-compat).
  * REGISTRY_TOTAL_CHAMPIONS grows 38 -> 40 (assertGreaterEqual).
  * COND_FRENZY_STATE THIRD consumer pin (Gnar W form 1).
  * COND_CHANNEL_COMPLETION coverage extends to Sion R.
  * Per-form override key shape (Gnar:W:1) parses + flows through
    to the form-explicit Gnar entry.
  * EngineVersionCurrentTests: assertGreaterEqual((1, 48, 0)).
  * Wired-site grep pins so a future refactor that removes either
    wave-11 entry fails CI before silent registry regression.
  * ASCII hygiene (no em-dashes / en-dashes / smart quotes).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_conditional import (
    COND_CHANNEL_COMPLETION,
    COND_FRENZY_STATE,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    _PER_SPELL_CC_CONDITIONAL,
    _PER_SPELL_CC_CONDITIONAL_FORMS,
    ConditionalCcEntry,
    _apply_per_form_entry_overrides,
    _build_per_spell_cc_conditional,
    _build_per_spell_cc_conditional_forms,
    get_conditional_entries,
)


class WaveElevenSionEntryTests(unittest.TestCase):
    """Sion R primary-registry entry has the expected shape."""

    def setUp(self) -> None:
        self.entry = _PER_SPELL_CC_CONDITIONAL["Sion"]["R"]

    def test_champion_is_sion(self) -> None:
        self.assertEqual(self.entry.champion, "Sion")

    def test_spell_is_r(self) -> None:
        self.assertEqual(self.entry.spell, "R")

    def test_cc_kind_is_stun(self) -> None:
        self.assertEqual(self.entry.cc_kind, "stun")

    def test_condition_is_channel_completion(self) -> None:
        self.assertEqual(self.entry.condition, COND_CHANNEL_COMPLETION)

    def test_form_index_is_none_default_form(self) -> None:
        self.assertIsNone(self.entry.form_index)

    def test_durations_is_single_value_tuple(self) -> None:
        # R supports tuple length 1 (same all ranks) or 3 (per-rank).
        # Sion R uses single-value 1.0s representative midpoint per
        # the channel-time-gated 0.25-1.75s range.
        self.assertEqual(self.entry.durations_s, (1.0,))

    def test_probability_is_tag_midpoint(self) -> None:
        self.assertAlmostEqual(self.entry.probability, 0.5, places=6)

    def test_is_conditional_cc_entry(self) -> None:
        self.assertIsInstance(self.entry, ConditionalCcEntry)


class WaveElevenGnarSidecarEntryTests(unittest.TestCase):
    """Gnar W form_index=1 sidecar entry has the expected shape."""

    def setUp(self) -> None:
        self.entry = _PER_SPELL_CC_CONDITIONAL_FORMS["Gnar"][("W", 1)]

    def test_champion_is_gnar(self) -> None:
        self.assertEqual(self.entry.champion, "Gnar")

    def test_spell_is_w(self) -> None:
        self.assertEqual(self.entry.spell, "W")

    def test_form_index_is_one(self) -> None:
        self.assertEqual(self.entry.form_index, 1)

    def test_cc_kind_is_stun(self) -> None:
        self.assertEqual(self.entry.cc_kind, "stun")

    def test_condition_is_frenzy_state(self) -> None:
        self.assertEqual(self.entry.condition, COND_FRENZY_STATE)

    def test_durations_is_one_quarter_second_tuple(self) -> None:
        # Single-value tuple 1.25s flat across all 5 W ranks per
        # effects_descriptions "stunning them for 1.25 seconds".
        self.assertEqual(self.entry.durations_s, (1.25,))

    def test_probability_is_frenzy_tag_midpoint(self) -> None:
        self.assertAlmostEqual(self.entry.probability, 0.4, places=6)

    def test_is_conditional_cc_entry(self) -> None:
        self.assertIsInstance(self.entry, ConditionalCcEntry)


class WaveElevenRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL constants grew to reflect the +2 entries."""

    def test_registry_total_entries_at_least_forty_six(self) -> None:
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 46)

    def test_registry_total_champions_at_least_forty(self) -> None:
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 40)

    def test_sion_is_in_primary_registry(self) -> None:
        self.assertIn("Sion", _PER_SPELL_CC_CONDITIONAL)

    def test_gnar_is_in_sidecar_registry(self) -> None:
        self.assertIn("Gnar", _PER_SPELL_CC_CONDITIONAL_FORMS)

    def test_gnar_only_has_form_one_entry(self) -> None:
        gnar_forms = _PER_SPELL_CC_CONDITIONAL_FORMS["Gnar"]
        self.assertEqual(list(gnar_forms.keys()), [("W", 1)])

    def test_sion_only_has_r_entry(self) -> None:
        sion_primary = _PER_SPELL_CC_CONDITIONAL["Sion"]
        self.assertEqual(list(sion_primary.keys()), ["R"])


class WaveElevenFrenzyStateThirdConsumerTests(unittest.TestCase):
    """COND_FRENZY_STATE now has 3 consumers (Renekton W / Karma W f1 / Gnar W f1)."""

    def test_renekton_w_uses_frenzy_state(self) -> None:
        # Existing wave 9 consumer.
        entry = _PER_SPELL_CC_CONDITIONAL["Renekton"]["W"]
        self.assertEqual(entry.condition, COND_FRENZY_STATE)

    def test_karma_w_form_one_uses_frenzy_state(self) -> None:
        # Existing wave 10 consumer.
        entry = _PER_SPELL_CC_CONDITIONAL_FORMS["Karma"][("W", 1)]
        self.assertEqual(entry.condition, COND_FRENZY_STATE)

    def test_gnar_w_form_one_uses_frenzy_state(self) -> None:
        # New wave 11 consumer.
        entry = _PER_SPELL_CC_CONDITIONAL_FORMS["Gnar"][("W", 1)]
        self.assertEqual(entry.condition, COND_FRENZY_STATE)

    def test_frenzy_state_consumer_count_at_least_three(self) -> None:
        # Count entries across both registries that consume the tag.
        consumers = 0
        for spells in _PER_SPELL_CC_CONDITIONAL.values():
            for entry in spells.values():
                if entry.condition == COND_FRENZY_STATE:
                    consumers += 1
        for forms in _PER_SPELL_CC_CONDITIONAL_FORMS.values():
            for entry in forms.values():
                if entry.condition == COND_FRENZY_STATE:
                    consumers += 1
        self.assertGreaterEqual(consumers, 3)


class WaveElevenChannelCompletionExtensionTests(unittest.TestCase):
    """COND_CHANNEL_COMPLETION coverage extends to Sion R."""

    def test_sion_r_uses_channel_completion(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Sion"]["R"]
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)

    def test_channel_completion_consumer_count_grew(self) -> None:
        # Channel completion has many consumers; pin floor at 8 covering
        # Karma W default + Warwick R + Morgana R + Nunu R + Pantheon Q
        # wave 4 + Briar E wave 5 + Hwei E wave 9 + Sion R wave 11 +
        # Hwei E form 2 wave 10 sidecar + Pyke E wave 2 + Swain E wave 2
        # + Taliyah W wave 1 + Leblanc E wave 3 + Evelynn W wave 8 +
        # Yuumi Q wave 4. Floor 8 leaves headroom for future REJECT
        # revisits without bulk-rewrite churn.
        consumers = 0
        for spells in _PER_SPELL_CC_CONDITIONAL.values():
            for entry in spells.values():
                if entry.condition == COND_CHANNEL_COMPLETION:
                    consumers += 1
        for forms in _PER_SPELL_CC_CONDITIONAL_FORMS.values():
            for entry in forms.values():
                if entry.condition == COND_CHANNEL_COMPLETION:
                    consumers += 1
        self.assertGreaterEqual(consumers, 8)


class WaveElevenMultiWaveCoexistenceTests(unittest.TestCase):
    """Sion + Gnar coexist on different registries with their wave 0 unconditional entries."""

    def test_sion_q_is_unconditional_not_cc_conditional(self) -> None:
        # Sion Q stun is in _PER_SPELL_CC_DURATIONS (unconditional);
        # cc_conditional only carries the Sion R entry.
        sion_primary = _PER_SPELL_CC_CONDITIONAL["Sion"]
        self.assertNotIn("Q", sion_primary)

    def test_gnar_r_is_unconditional_not_cc_conditional(self) -> None:
        # Gnar R stun is in _PER_SPELL_CC_DURATIONS (unconditional);
        # cc_conditional sidecar only carries the Gnar W form 1 entry.
        gnar_primary = _PER_SPELL_CC_CONDITIONAL.get("Gnar", {})
        gnar_sidecar = _PER_SPELL_CC_CONDITIONAL_FORMS["Gnar"]
        self.assertNotIn("R", gnar_primary)
        self.assertNotIn(("R", 0), gnar_sidecar)

    def test_gnar_has_no_primary_w_entry(self) -> None:
        # All Gnar W coverage is in the sidecar (form 1 Wallop). No
        # primary registry entry to collide with.
        gnar_primary = _PER_SPELL_CC_CONDITIONAL.get("Gnar", {})
        self.assertNotIn("W", gnar_primary)


class WaveElevenGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns the new entries in canonical order."""

    def test_sion_returns_only_r_entry(self) -> None:
        entries = get_conditional_entries("Sion")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "R")
        self.assertEqual(entries[0].champion, "Sion")

    def test_gnar_returns_only_w_form_one_entry(self) -> None:
        entries = get_conditional_entries("Gnar")
        # Gnar has no primary entry; only the sidecar W form 1 entry.
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "W")
        self.assertEqual(entries[0].form_index, 1)
        self.assertEqual(entries[0].champion, "Gnar")


class WaveElevenBuilderIdempotenceTests(unittest.TestCase):
    """Re-invoking builders yields fresh dict instances with both wave 11 entries."""

    def test_primary_builder_contains_sion_r(self) -> None:
        fresh = _build_per_spell_cc_conditional()
        self.assertIn("Sion", fresh)
        self.assertIn("R", fresh["Sion"])
        self.assertEqual(fresh["Sion"]["R"].cc_kind, "stun")

    def test_sidecar_builder_contains_gnar_w_form_one(self) -> None:
        fresh = _build_per_spell_cc_conditional_forms()
        self.assertIn("Gnar", fresh)
        self.assertIn(("W", 1), fresh["Gnar"])
        self.assertEqual(fresh["Gnar"][("W", 1)].cc_kind, "stun")

    def test_primary_builder_fresh_dict(self) -> None:
        # Builder returns a fresh dict each invocation (not the cached
        # module-level _PER_SPELL_CC_CONDITIONAL reference).
        fresh = _build_per_spell_cc_conditional()
        self.assertIsNot(fresh, _PER_SPELL_CC_CONDITIONAL)

    def test_sidecar_builder_fresh_dict(self) -> None:
        fresh = _build_per_spell_cc_conditional_forms()
        self.assertIsNot(fresh, _PER_SPELL_CC_CONDITIONAL_FORMS)


class WaveElevenPerFormOverrideTests(unittest.TestCase):
    """Form-explicit override key shape Gnar:W:1 parses + flows through."""

    def test_gnar_w_form_one_override_parses(self) -> None:
        overrides = {"per_entry_probability": {"Gnar:W:1": 0.55}}
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result.get(("Gnar", "W", 1)), 0.55)

    def test_invalid_override_for_gnar_w_form_one_dropped(self) -> None:
        # Out-of-range value silently dropped (per wave 10 semantics).
        overrides = {"per_entry_probability": {"Gnar:W:1": 1.5}}
        result = _apply_per_form_entry_overrides(overrides)
        self.assertNotIn(("Gnar", "W", 1), result)

    def test_bool_value_dropped_for_form_override(self) -> None:
        # bool is an int subclass; must not be silently coerced.
        overrides = {"per_entry_probability": {"Gnar:W:1": True}}
        result = _apply_per_form_entry_overrides(overrides)
        self.assertNotIn(("Gnar", "W", 1), result)


class WaveElevenEngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION reflects the wave 11 ship (1.48.0)."""

    def test_engine_version_is_at_least_one_forty_eight(self) -> None:
        major, minor, patch = (int(p) for p in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 48, 0))


class WaveElevenWiredSitesGrepTests(unittest.TestCase):
    """A future refactor that removes either wave-11 entry fails CI here.

    The 2 grep pins ensure the wave 11 source-code surface persists:
    Sion R in the primary registry builder + Gnar W form 1 in the
    sidecar builder. The grep is on the literal champion/spell/form
    identifier triple plus the canonical ConditionalCcEntry header to
    survive refactors that rename internal locals.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source_path = (
            Path(__file__).resolve().parent.parent / "cc_conditional.py"
        )
        cls.source_text = cls.source_path.read_text(encoding="utf-8")

    def test_sion_r_entry_grep_pin(self) -> None:
        # The Sion R primary entry must persist with these key tokens.
        self.assertIn('registry.setdefault("Sion", {})["R"]', self.source_text)
        self.assertIn("Unstoppable Onslaught", self.source_text)
        self.assertIn("COND_CHANNEL_COMPLETION", self.source_text)

    def test_gnar_w_form_one_entry_grep_pin(self) -> None:
        # The Gnar W form 1 sidecar entry must persist with these tokens.
        self.assertIn(
            'registry.setdefault("Gnar", {})[("W", 1)]', self.source_text
        )
        self.assertIn("Wallop", self.source_text)
        self.assertIn("Mega-form", self.source_text)
        self.assertIn("COND_FRENZY_STATE", self.source_text)

    def test_wave_eleven_section_header_present(self) -> None:
        self.assertIn("wave 11 expansion", self.source_text)


class WaveElevenAsciiHygieneTests(unittest.TestCase):
    """Wave 11 test file + the cc_conditional source wave 11 lines are ASCII-clean.

    No em-dashes (U+2014), en-dashes (U+2013), smart quotes
    (U+2018/2019/201C/201D), ellipsis (U+2026), or NBSP (U+00A0).
    """

    _FORBIDDEN_CODEPOINTS = (
        0x2013,  # en-dash
        0x2014,  # em-dash
        0x2018,  # left single quote
        0x2019,  # right single quote
        0x201C,  # left double quote
        0x201D,  # right double quote
        0x2026,  # ellipsis
        0x00A0,  # non-breaking space
    )

    def test_this_test_file_is_ascii_clean(self) -> None:
        path = Path(__file__).resolve()
        text = path.read_text(encoding="utf-8")
        for cp in self._FORBIDDEN_CODEPOINTS:
            self.assertNotIn(
                chr(cp),
                text,
                f"forbidden codepoint U+{cp:04X} in {path}",
            )

    def test_wave_eleven_source_lines_are_ascii_clean(self) -> None:
        # Probe the wave 11 source section (between the wave 11 header
        # and the return registry that closes the primary builder; also
        # the sidecar wave 11 section). Restricting to the wave 11
        # surface avoids re-flagging pre-existing carryover bytes from
        # other waves that are operator-gated retro-sweep candidates.
        path = (
            Path(__file__).resolve().parent.parent / "cc_conditional.py"
        )
        text = path.read_text(encoding="utf-8")
        # Find both wave 11 sections.
        primary_marker = "wave 11 expansion (2026-05-23 / ENGINE 1.48.0) - +2 entries"
        sidecar_marker = (
            "wave 11 expansion (2026-05-23 / ENGINE 1.48.0) - +1"
        )
        self.assertIn(primary_marker, text)
        self.assertIn(sidecar_marker, text)
        # Extract from each marker to the next "===" line + 200 chars.
        for marker in (primary_marker, sidecar_marker):
            idx = text.find(marker)
            self.assertGreaterEqual(idx, 0)
            slab = text[idx: idx + 6000]
            for cp in self._FORBIDDEN_CODEPOINTS:
                self.assertNotIn(
                    chr(cp),
                    slab,
                    f"forbidden codepoint U+{cp:04X} in wave-11 slab "
                    f"starting at index {idx}",
                )


if __name__ == "__main__":
    unittest.main()
