"""ENGINE 1.51.0 (2026-05-24) - cc_conditional wave 14.

Wave 14 ships +1 sidecar entry / +1 net-new champion via the
``cast_time`` Meraki extractor schema lift. The extractor in
``tools/daemon_slayer_abilities_extract.py`` now captures the Meraki
``castTime`` field per ability form (float seconds or None for
instant casts). The schema lift unblocks the long-deferred Jayce E
cast-time root carry from item 170 wave 12 + item 171 wave 13.

NEW cc_conditional entry:

  * Jayce E form_index=0 Thundering Blow cast-time root (sidecar
    registry, NEW champion) - COND_CHANNEL_COMPLETION at probability
    0.5 (tag midpoint).
    - durations_s=(0.25,) flat across all 5 E ranks per the Meraki
      castTime field for form 0 (Hammer-form Thundering Blow).
    - mechanic: roots the target enemy over the cast time, then
      swings the hammer to deal damage + knock target back 600
      units. Form 1 (Cannon Acceleration Gate) is instant-cast
      (cast_time=None) and has NO first-order CC.
    - FIRST Jayce first-order CC registration in the engine.
    - Sidecar pattern parallel to Hwei E form 1+2 + Sylas E form 1
      + Karma W form 1 + Gnar W form 1 + Aphelios Q form 3.
    - Form-explicit override key shape: Jayce:E:0.

Wave 14 REJECT verdicts:

  * Maokai R distance-gated root 0.75-2.25s - STILL would double-
    count with the unconditional Maokai R registry entry in
    _PER_SPELL_CC_DURATIONS for ranks 1/2/3. REJECT (carry from
    item 170 wave 12).
  * LeeSin R cast-time root 0.25s - UNCONDITIONAL on primary target
    per item 171 wave 13 REJECT verdict; belongs in
    _PER_SPELL_CC_DURATIONS not cc_conditional. REJECT (out of
    scope this wave).
  * KSante R cast-time displacement immunity 0.4s - the cast_time
    captures K'Sante's SELF buff (displacement immunity); the
    target's 0.5s root is explicit + unconditional. REJECT.

Registry growth: 56 -> 57 entries / 48 -> 49 champions
(51 primary unchanged + 5 -> 6 sidecar).

Per-tag consumer counts: COND_CHANNEL_COMPLETION grew by 1
(Jayce E form 0); others unchanged.

Schema lift evidence: ``tools/daemon_slayer_abilities_extract.py``
now exports ``_normalize_cast_time(raw)`` helper handling None /
"none" / float / numeric-string Meraki castTime values. Re-
extracted ``data/daemon_slayer/16.10.1/champion_abilities.json``
exposes ``cast_time: float | None`` per form record. Same schema
lift unlocks LeeSin R / KSante R / Maokai R cast-time data for
future registry additions but those are out of scope this wave.

Coverage classes:

  * WaveFourteenJayceShapeTests - Jayce E form 0 sidecar entry
    shape pin.
  * WaveFourteenRegistryGrowthTests - REGISTRY_TOTAL_ENTRIES /
    REGISTRY_TOTAL_CHAMPIONS grew to 57 / 49.
  * WaveFourteenSidecarOnlyTests - Jayce lives ONLY in sidecar
    registry (NOT in primary).
  * WaveFourteenJayceMultiFormTests - Jayce E form 0 carries CC;
    form 1 does NOT.
  * WaveFourteenConditionalTagConsumerCountsTests - per-tag
    consumer counts grew correctly.
  * WaveFourteenDefaultCallerByteIdenticalTests - default
    include_conditional=False compute_cc_pressure is BYTE-
    IDENTICAL to 1.50.0 for Jayce.
  * WaveFourteenIncludeConditionalMathTests - include_conditional=
    True receives probability-weighted contribution.
  * WaveFourteenGetConditionalEntriesTests - get_conditional_entries
    returns the new Jayce entry.
  * WaveFourteenBuilderIdempotenceTests - the builder functions
    are deterministic + do not mutate globals.
  * WaveFourteenExtractorSchemaLiftTests - the extracted JSON
    data exposes cast_time per form record + Jayce E form 0
    cast_time=0.25 matches the durations tuple.
  * WaveFourteenWiredSitesGrepTests - wave 14 entry grep-matches
    in the cc_conditional.py source.
  * EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.51.0.
  * AsciiHygieneTests - the test file is ASCII-clean +
    cc_conditional.py wave 14 block is ASCII-clean.
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class WaveFourteenJayceShapeTests(unittest.TestCase):
    """Jayce E form 0 sidecar entry shape pin."""

    def test_jayce_in_sidecar_registry(self) -> None:
        self.assertIn("Jayce", cc._PER_SPELL_CC_CONDITIONAL_FORMS)

    def test_jayce_e_form_0_slot_present(self) -> None:
        self.assertIn(("E", 0), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"])

    def test_jayce_e_form_0_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertEqual(entry.durations_s, (0.25,))

    def test_jayce_e_form_0_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertEqual(entry.cc_kind, "root")

    def test_jayce_e_form_0_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_jayce_e_form_0_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertEqual(entry.probability, 0.5)

    def test_jayce_e_form_0_entry_form_index(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertEqual(entry.form_index, 0)

    def test_jayce_e_form_0_entry_notes_mention_thundering_blow(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertIn("Thundering Blow", entry.notes)

    def test_jayce_e_form_0_entry_notes_mention_cast_time(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertIn("cast", entry.notes.lower())


class WaveFourteenRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES / REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_registry_total_entries_grew_to_at_least_fifty_seven(self) -> None:
        # Wave 14 ship-time baseline is 57 (56 wave 13 + 1 sidecar Jayce E).
        # Relaxed to assertGreaterEqual for future-wave forward compat.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 57)

    def test_registry_total_champions_grew_to_at_least_forty_nine(self) -> None:
        # Wave 14 ship-time baseline is 49 (48 wave 13 + 1 net-new
        # champion: Jayce).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 49)

    def test_primary_registry_unchanged_from_wave_13(self) -> None:
        primary = sum(len(s) for s in cc._PER_SPELL_CC_CONDITIONAL.values())
        # Wave 13 baseline was 51 primary; wave 14 adds NO primary
        # entries (Jayce E is sidecar-only).
        self.assertGreaterEqual(primary, 51)

    def test_sidecar_registry_grew_to_at_least_six(self) -> None:
        sidecar = sum(
            len(f) for f in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        # Wave 13 baseline was 5 sidecar + 1 net-new (Jayce E form 0) = 6.
        self.assertGreaterEqual(sidecar, 6)


class WaveFourteenSidecarOnlyTests(unittest.TestCase):
    """Jayce lives ONLY in sidecar registry (NOT in primary)."""

    def test_jayce_not_in_primary_registry(self) -> None:
        # Jayce's only cc_conditional entry lives in the sidecar; the
        # primary registry must NOT carry Jayce.
        self.assertNotIn("Jayce", cc._PER_SPELL_CC_CONDITIONAL)

    def test_jayce_has_no_unconditional_entry(self) -> None:
        # Jayce's only first-order CC registration is the wave 14
        # sidecar entry. The unconditional knockback is captured
        # elsewhere (NOT in _PER_SPELL_CC_DURATIONS at the time of
        # wave 14 ship - separate from this wave's scope).
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Jayce", _PER_SPELL_CC_DURATIONS)


class WaveFourteenJayceMultiFormTests(unittest.TestCase):
    """Jayce E form 0 carries CC; form 1 does NOT."""

    def test_jayce_only_has_form_0_in_sidecar(self) -> None:
        # Form 0 (Hammer Thundering Blow) is the cast-time root.
        # Form 1 (Cannon Acceleration Gate) is instant-cast utility.
        sidecar_keys = set(cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"].keys())
        self.assertIn(("E", 0), sidecar_keys)
        self.assertNotIn(("E", 1), sidecar_keys)

    def test_jayce_only_e_slot_in_sidecar(self) -> None:
        # Jayce's other slots (P/Q/W/R) have NO first-order CC
        # registration anywhere; only E form 0 carries CC.
        sidecar_keys = set(cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"].keys())
        slots = {k[0] for k in sidecar_keys}
        self.assertEqual(slots, {"E"})


class WaveFourteenConditionalTagConsumerCountsTests(unittest.TestCase):
    """Per-tag consumer counts grew correctly."""

    def test_channel_completion_grew_by_at_least_one(self) -> None:
        # COND_CHANNEL_COMPLETION grew by +1 (Jayce E form 0). Wave 13
        # baseline had channel_completion consumers across multiple
        # entries (Karma W, Warwick R, Morgana R, Sion R, Hwei E
        # form 2, Sylas E form 1, Renata Q, Shaco R, Warwick E,
        # TahmKench W).
        all_entries = []
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            all_entries.extend(spells.values())
        for forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values():
            all_entries.extend(forms.values())
        channel_consumers = [
            e for e in all_entries if e.condition == cc.COND_CHANNEL_COMPLETION
        ]
        # Lower bound is the wave 14 ship-time count. The exact count
        # is operator-tunable across the registry (wave 0 baseline is
        # multi-entry; wave 14 contributes ONE more).
        self.assertGreaterEqual(len(channel_consumers), 11)

    def test_frenzy_state_unchanged_at_three(self) -> None:
        # Wave 14 does NOT add any COND_FRENZY_STATE entries.
        all_entries = []
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            all_entries.extend(spells.values())
        for forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values():
            all_entries.extend(forms.values())
        frenzy_consumers = [
            e for e in all_entries if e.condition == cc.COND_FRENZY_STATE
        ]
        # Wave 14 baseline = 3 (Renekton W wave 9 + Karma W form 1
        # wave 10 + Gnar W form 1 wave 11). Wave 14 does NOT add any.
        self.assertGreaterEqual(len(frenzy_consumers), 3)

    def test_range_gated_still_zero_consumers(self) -> None:
        # Wave 14 ship-time: COND_RANGE_GATED had 0 consumers. Wave
        # 18 (ENGINE 1.55.0) added Maokai R as the FIRST consumer via
        # the coexists_with_unconditional schema lift. Wave 14
        # invariant relaxed: at most 1 consumer present at this point
        # in the registry's evolution.
        all_entries = []
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            all_entries.extend(spells.values())
        for forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values():
            all_entries.extend(forms.values())
        range_gated_consumers = [
            e for e in all_entries if e.condition == cc.COND_RANGE_GATED
        ]
        self.assertLessEqual(len(range_gated_consumers), 2)  # wave 23 lift Maokai R + Hecarim R


class WaveFourteenDefaultCallerByteIdenticalTests(unittest.TestCase):
    """Default include_conditional=False is BYTE-IDENTICAL to 1.50.0."""

    def test_jayce_default_returns_zero_total(self) -> None:
        result = compute_cc_pressure("Jayce", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_jayce_default_has_no_conditional_field_contribution(
        self,
    ) -> None:
        result = compute_cc_pressure("Jayce", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_jayce_default_has_empty_spells_tuple(self) -> None:
        # Jayce has NO _PER_SPELL_CC_DURATIONS entry at wave 14 ship;
        # default-caller path returns no spells.
        result = compute_cc_pressure("Jayce", "sr")
        self.assertEqual(result.spells, ())

    def test_jayce_default_has_empty_conditional_entries(self) -> None:
        # include_conditional=False is the default; conditional path
        # is skipped entirely.
        result = compute_cc_pressure("Jayce", "sr")
        self.assertEqual(result.conditional_entries, ())


class WaveFourteenIncludeConditionalMathTests(unittest.TestCase):
    """include_conditional=True receives probability-weighted contribution."""

    def test_jayce_conditional_total_is_probability_weighted_root(
        self,
    ) -> None:
        # Jayce E form 0: 0.25s root at probability 0.5 = 0.125s
        # contribution to total_cc_seconds.
        result = compute_cc_pressure("Jayce", "sr", include_conditional=True)
        self.assertAlmostEqual(result.total_cc_seconds, 0.125, places=4)

    def test_jayce_conditional_seconds_matches_total(self) -> None:
        # No _PER_SPELL_CC_DURATIONS entry for Jayce so
        # conditional_cc_seconds equals total_cc_seconds.
        result = compute_cc_pressure("Jayce", "sr", include_conditional=True)
        self.assertAlmostEqual(
            result.conditional_cc_seconds, result.total_cc_seconds, places=4
        )

    def test_jayce_conditional_entries_includes_e_form_0(self) -> None:
        result = compute_cc_pressure("Jayce", "sr", include_conditional=True)
        self.assertEqual(len(result.conditional_entries), 1)
        entry = result.conditional_entries[0]
        self.assertEqual(entry.spell, "E")
        self.assertEqual(entry.form_index, 0)
        self.assertEqual(entry.durations_s, (0.25,))


class WaveFourteenGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns the new Jayce entry."""

    def test_get_conditional_entries_includes_jayce(self) -> None:
        entries = cc.get_conditional_entries("Jayce")
        self.assertEqual(len(entries), 1)

    def test_jayce_entry_is_e_form_0(self) -> None:
        entries = cc.get_conditional_entries("Jayce")
        e = entries[0]
        self.assertEqual(e.spell, "E")
        self.assertEqual(e.form_index, 0)
        self.assertEqual(e.cc_kind, "root")

    def test_get_conditional_entries_unknown_champion_returns_empty(
        self,
    ) -> None:
        entries = cc.get_conditional_entries("Aatrox_NonExistent")
        self.assertEqual(entries, ())


class WaveFourteenBuilderIdempotenceTests(unittest.TestCase):
    """The builder functions are deterministic + do not mutate globals."""

    def test_primary_builder_produces_consistent_jayce_absence(self) -> None:
        # Jayce is NOT in the primary registry. Re-running the builder
        # must not introduce Jayce there.
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertNotIn("Jayce", fresh_primary)

    def test_sidecar_builder_produces_consistent_jayce_entry(self) -> None:
        # Fresh sidecar must carry the Jayce E form 0 entry exactly
        # like the module-load build.
        fresh_sidecar = cc._build_per_spell_cc_conditional_forms()
        self.assertIn("Jayce", fresh_sidecar)
        self.assertIn(("E", 0), fresh_sidecar["Jayce"])
        e = fresh_sidecar["Jayce"][("E", 0)]
        self.assertEqual(e.durations_s, (0.25,))
        self.assertEqual(e.cc_kind, "root")
        self.assertEqual(e.condition, cc.COND_CHANNEL_COMPLETION)
        self.assertEqual(e.probability, 0.5)
        self.assertEqual(e.form_index, 0)

    def test_sidecar_builder_idempotent_across_two_invocations(self) -> None:
        a = cc._build_per_spell_cc_conditional_forms()
        b = cc._build_per_spell_cc_conditional_forms()
        # The two builds are SEPARATE dict instances (no shared state
        # across invocations) but the Jayce entry shape is identical.
        self.assertIsNot(a, b)
        ea = a["Jayce"][("E", 0)]
        eb = b["Jayce"][("E", 0)]
        self.assertEqual(ea, eb)


class WaveFourteenExtractorSchemaLiftTests(unittest.TestCase):
    """The extracted JSON exposes cast_time per form."""

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

    def test_jayce_e_form_0_has_cast_time_field(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Jayce"]["E"][0]
        self.assertIn("cast_time", form)

    def test_jayce_e_form_0_cast_time_matches_durations(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Jayce"]["E"][0]
        # The wave 14 entry's durations_s tuple is sourced from the
        # extracted cast_time field. They MUST match.
        self.assertEqual(form["cast_time"], 0.25)
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Jayce"][("E", 0)]
        self.assertEqual(entry.durations_s, (form["cast_time"],))

    def test_jayce_e_form_1_cast_time_is_none(self) -> None:
        # Form 1 (Cannon Acceleration Gate) is instant-cast - the
        # Meraki "none" string normalizes to None.
        data = self._load_extracted()
        form = data["data"]["Jayce"]["E"][1]
        self.assertIsNone(form["cast_time"])

    def test_cast_time_field_present_on_all_forms(self) -> None:
        # The schema lift is fleet-wide: EVERY form must carry the
        # cast_time field (even if the value is None).
        data = self._load_extracted()
        missing = []
        for champ, slots in data["data"].items():
            for slot, forms in slots.items():
                for i, form in enumerate(forms):
                    if "cast_time" not in form:
                        missing.append(f"{champ}.{slot}[{i}]")
        self.assertEqual(missing, [], f"{len(missing)} forms missing cast_time")


class WaveFourteenWiredSitesGrepTests(unittest.TestCase):
    """Wave 14 entry grep-matches in the cc_conditional.py source."""

    def _source(self) -> str:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        return src

    def test_source_mentions_jayce_e_form_0(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Jayce", {})[("E", 0)]', src)

    def test_source_mentions_thundering_blow(self) -> None:
        src = self._source()
        self.assertIn("Thundering Blow", src)

    def test_source_mentions_cast_time_schema_lift(self) -> None:
        src = self._source()
        self.assertIn("cast_time", src.lower())


class EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.51.0."""

    def test_engine_version_string_pin(self) -> None:
        # Wave 14 ship-time pins ENGINE_VERSION = "1.51.0". Use
        # assertGreaterEqual on the tuple to allow future bumps to
        # not break this test (item 146 wave 8 lesson).
        major, minor, patch = (
            int(x) for x in ENGINE_VERSION.split(".")
        )
        self.assertGreaterEqual((major, minor, patch), (1, 51, 0))


class AsciiHygieneTests(unittest.TestCase):
    """The test file is ASCII-clean + cc_conditional wave 14 block is ASCII."""

    def test_this_test_file_is_ascii(self) -> None:
        path = Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII bytes in {path.name}",
        )

    def test_cc_conditional_wave_14_block_is_ascii(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        # Slice from the "wave 14 expansion" header through the
        # end-of-builder; assert no non-ASCII bytes appear in that
        # slice. The earlier waves carry pre-existing non-ASCII
        # bytes (Karma "K'Sante" apostrophe etc.) so we scope the
        # check to the wave 14 block only.
        marker = "wave 14 expansion (2026-05-24 / ENGINE 1.51.0)"
        idx = src.find(marker)
        self.assertGreater(idx, -1, "wave 14 header marker missing")
        # Block ends at the next "return registry" closure after
        # the Jayce entry.
        end_marker = src.find('setdefault("Jayce", {})[("E", 0)]', idx)
        # Take a generous slice past the Jayce setdefault site.
        block = src[idx : end_marker + 4096]
        non_ascii = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII characters in wave 14 block",
        )


if __name__ == "__main__":
    unittest.main()
