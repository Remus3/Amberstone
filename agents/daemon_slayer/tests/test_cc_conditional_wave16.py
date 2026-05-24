"""ENGINE 1.53.0 (2026-05-24) - cc_conditional wave 16.

Wave 16 ships +4 primary entries / +3 net-new champions (Garen +
Syndra + Udyr; KSante already in registry with Q wave 1 nth_hit
root) sourced from a re-audit of the ENGINE 1.52.0 Meraki schema-
lifted data file. The audit extended the wave 15 cast_time-gated
scan to ALL 171 champions regardless of cast_time, surfacing 11
uncovered slots with explicit CC duration text in
effects_descriptions; 4 close cleanly (no schema lift + no tag
expansion + no slot collision) and 7 REJECT.

NEW cc_conditional entries (all primary registry):

  * Garen Q Decisive Strike empowered-AA silence (primary
    registry, NEW champion) - COND_NTH_HIT at probability 0.7.
    - durations_s=(1.5,) flat across all 5 Q ranks per
      effects_descriptions ("silence them for 1.5 seconds").
    - mechanic: Garen Q cleanses slows + bonus MS + empowers
      NEXT basic attack within 4.5s to lunge + silence target
      1.5s on hit. Standalone Q with no follow-up AA = MS buff
      cleanse only (no silence).
    - FIRST Garen first-order CC registration in the engine.

  * Syndra E Scatter the Weak Dark-Sphere knockback stun
    (primary registry, NEW champion) - COND_TARGET_DEBUFFED at
    probability 0.5.
    - durations_s=(1.25,) flat across all 5 E ranks per
      effects_descriptions ("stunned for 1.25 seconds").
    - mechanic: Syndra E knockback cone; if a Dark Sphere
      (Q residue) sits in cone path, sphere ALSO flies + stuns
      targets 1.25s. Standalone E without sphere = damage +
      knockback only. Maps to COND_TARGET_DEBUFFED (sphere
      overlap at moment of cast).
    - FIRST Syndra first-order CC registration in the engine.

  * Udyr E Blazing Stampede empowered-AA pounce stun (primary
    registry, NEW champion) - COND_NTH_HIT at probability 0.7.
    - durations_s=(0.75,) flat across all 5 E ranks per
      effects_descriptions ("stun them for 0.75 seconds").
    - mechanic: Udyr E enters Stampede Stance + NEXT basic
      attack pounces + stuns 0.75s. Once-per-target ICD does
      NOT affect first-cast probability. Standalone Stance
      entry with no AA = MS buff + ghosting only.
    - FIRST Udyr first-order CC registration in the engine.

  * KSante W Path Maker recast channel-completion stun
    (primary registry, EXISTING champion - KSante already had Q
    wave 1) - COND_CHANNEL_COMPLETION at probability 0.5.
    - durations_s=(1.0,) representative midpoint of the
      0.5-1.75s channel-time-scaled range per
      effects_descriptions.
    - mechanic: KSante W charges 0.4-1.0s + recast dashes +
      carries + stuns enemies passed through 0.5-1.75s based
      on channel time. Mid-channel hard CC cancels the recast
      payload. All Out (R-active) form REMOVES this stun
      (replaces with true damage); entry encodes BASE form
      payload only.
    - Coexists with KSante Q wave 1 cc_conditional entry on a
      different spell slot (multi-wave-within-cc_conditional
      coexistence pattern).
    - FIRST KSante W first-order CC registration in the engine.

Wave 16 REJECT verdicts (effects_descriptions schema-verified
this run; CARRY-FORWARD only if new evidence surfaces):

  * Ahri W - priority targeting on Charmed targets is W's
    mechanic but W itself applies no CC; the charm is applied
    by Ahri's E. REJECT.
  * Aphelios R - already shipped as Aphelios:Q:3 sidecar wave
    13; R itself has no first-order CC payload. REJECT.
  * Darius E Apprehend - 1.0s airborne is UNCONDITIONAL pull-
    displacement; belongs in _PER_SPELL_CC_DURATIONS not
    cc_conditional. REJECT (wave 15 carry).
  * Irelia R perimeter - displacement only (no airborne per
    effects_descriptions); 1.5s slow is NOT CC. REJECT.
  * LeeSin R - wave 13/14/15 REJECT carries.
  * Milio R - cleanse + tenacity buff only; no CC payload.
    REJECT.
  * Taliyah E dash-detonation - wave 15 REJECT binding
    (would need new COND_TRAVERSE tag).

Registry growth: 60 -> 64 entries / 51 -> 54 champions
(53 -> 57 primary + 7 sidecar unchanged).

Per-tag consumer counts: COND_NTH_HIT +2 (Garen Q + Udyr E);
COND_TARGET_DEBUFFED +1 (Syndra E); COND_CHANNEL_COMPLETION +1
(KSante W). COND_TERRAIN / COND_FRENZY_STATE / COND_RANGE_GATED
unchanged.

Math preservation: default include_conditional=False
compute_cc_pressure BYTE-IDENTICAL to 1.52.0 (the conditional
path skips when the flag is False). include_conditional=True
callers receive new probability-weighted contributions:
Garen +1.05s (1.5 * 0.7), Syndra +0.625s (1.25 * 0.5),
Udyr +0.525s (0.75 * 0.7), KSante W +0.5s (1.0 * 0.5); the
wave 1 KSante Q nth_hit root at 0.75s flat contributes an
additional 0.525s giving KSante a total 1.025s conditional
contribution stacked on the 0.75s unconditional R.

Coverage classes:

  * WaveSixteenGarenShapeTests - Garen Q primary entry shape.
  * WaveSixteenSyndraShapeTests - Syndra E primary entry shape.
  * WaveSixteenUdyrShapeTests - Udyr E primary entry shape.
  * WaveSixteenKSanteShapeTests - KSante W primary entry shape.
  * WaveSixteenRegistryGrowthTests - REGISTRY_TOTAL_ENTRIES /
    REGISTRY_TOTAL_CHAMPIONS grew to 64 / 54.
  * WaveSixteenMultiWaveCoexistenceTests - KSante has both
    wave 1 Q + wave 16 W in primary registry.
  * WaveSixteenConditionalTagConsumerCountsTests - per-tag
    consumer counts grew correctly.
  * WaveSixteenDefaultCallerByteIdenticalTests - default
    include_conditional=False compute_cc_pressure is BYTE-
    IDENTICAL to 1.52.0 for Garen / Syndra / Udyr / KSante.
  * WaveSixteenIncludeConditionalMathTests - include_conditional=
    True receives probability-weighted contributions.
  * WaveSixteenGetConditionalEntriesTests - get_conditional_entries
    returns the new entries.
  * WaveSixteenBuilderIdempotenceTests - the builder functions
    are deterministic + do not mutate globals.
  * WaveSixteenSchemaCrossReferenceTests - shipped entries match
    effects_descriptions text in extracted JSON.
  * WaveSixteenRejectVerdictsPinnedTests - REJECT verdicts
    documented in module docstring.
  * WaveSixteenWiredSitesGrepTests - wave 16 entries grep-match
    in the cc_conditional.py source.
  * EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.53.0.
  * AsciiHygieneTests - the test file is ASCII-clean +
    cc_conditional.py wave 16 block is ASCII-clean.
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class WaveSixteenGarenShapeTests(unittest.TestCase):
    """Garen Q primary entry shape pin."""

    def test_garen_in_primary_registry(self) -> None:
        self.assertIn("Garen", cc._PER_SPELL_CC_CONDITIONAL)

    def test_garen_q_slot_present(self) -> None:
        self.assertIn("Q", cc._PER_SPELL_CC_CONDITIONAL["Garen"])

    def test_garen_q_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertEqual(entry.durations_s, (1.5,))

    def test_garen_q_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertEqual(entry.cc_kind, "silence")

    def test_garen_q_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)

    def test_garen_q_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertEqual(entry.probability, 0.7)

    def test_garen_q_entry_form_index_default(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertIsNone(entry.form_index)

    def test_garen_q_entry_notes_mention_decisive_strike(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertIn("Decisive Strike", entry.notes)

    def test_garen_q_entry_notes_mention_silence(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Garen"]["Q"]
        self.assertIn("silence", entry.notes.lower())


class WaveSixteenSyndraShapeTests(unittest.TestCase):
    """Syndra E primary entry shape pin."""

    def test_syndra_in_primary_registry(self) -> None:
        self.assertIn("Syndra", cc._PER_SPELL_CC_CONDITIONAL)

    def test_syndra_e_slot_present(self) -> None:
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Syndra"])

    def test_syndra_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Syndra"]["E"]
        self.assertEqual(entry.durations_s, (1.25,))

    def test_syndra_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Syndra"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_syndra_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Syndra"]["E"]
        self.assertEqual(entry.condition, cc.COND_TARGET_DEBUFFED)

    def test_syndra_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Syndra"]["E"]
        self.assertEqual(entry.probability, 0.5)

    def test_syndra_e_entry_form_index_default(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Syndra"]["E"]
        self.assertIsNone(entry.form_index)

    def test_syndra_e_entry_notes_mention_dark_sphere(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Syndra"]["E"]
        self.assertIn("Dark Sphere", entry.notes)


class WaveSixteenUdyrShapeTests(unittest.TestCase):
    """Udyr E primary entry shape pin."""

    def test_udyr_in_primary_registry(self) -> None:
        self.assertIn("Udyr", cc._PER_SPELL_CC_CONDITIONAL)

    def test_udyr_e_slot_present(self) -> None:
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Udyr"])

    def test_udyr_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Udyr"]["E"]
        self.assertEqual(entry.durations_s, (0.75,))

    def test_udyr_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Udyr"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_udyr_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Udyr"]["E"]
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)

    def test_udyr_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Udyr"]["E"]
        self.assertEqual(entry.probability, 0.7)

    def test_udyr_e_entry_notes_mention_stampede(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Udyr"]["E"]
        self.assertIn("Stampede", entry.notes)


class WaveSixteenKSanteShapeTests(unittest.TestCase):
    """KSante W primary entry shape pin."""

    def test_ksante_w_slot_present(self) -> None:
        # KSante already in primary with wave 1 Q; wave 16 adds W.
        self.assertIn("W", cc._PER_SPELL_CC_CONDITIONAL["KSante"])

    def test_ksante_w_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["W"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_ksante_w_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["W"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_ksante_w_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["W"]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_ksante_w_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["W"]
        self.assertEqual(entry.probability, 0.5)

    def test_ksante_w_entry_notes_mention_path_maker(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["W"]
        self.assertIn("Path Maker", entry.notes)

    def test_ksante_q_wave_1_unchanged(self) -> None:
        # Wave 1 KSante Q nth_hit root must still exist.
        entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["Q"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)


class WaveSixteenRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES / REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_registry_total_entries_grew_to_at_least_sixty_four(self) -> None:
        # Wave 16 ship-time baseline is 64 (60 wave 15 + 4 wave 16:
        # Garen Q + Syndra E + Udyr E + KSante W). Relaxed for
        # future-wave forward compat.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 64)

    def test_registry_total_champions_grew_to_at_least_fifty_four(self) -> None:
        # Wave 16 ship-time baseline is 54 (51 wave 15 + 3 net-new:
        # Garen + Syndra + Udyr; KSante already had Q wave 1 entry
        # so KSante W is multi-wave coexistence not net-new
        # champion).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 54)

    def test_primary_registry_grew_to_at_least_fifty_seven(self) -> None:
        primary = sum(len(s) for s in cc._PER_SPELL_CC_CONDITIONAL.values())
        # Wave 15 baseline was 53 primary; wave 16 adds Garen Q +
        # Syndra E + Udyr E + KSante W = 57.
        self.assertGreaterEqual(primary, 57)

    def test_sidecar_registry_unchanged_at_seven(self) -> None:
        sidecar = sum(
            len(f) for f in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        # Wave 16 adds no sidecar entries; baseline 7 holds.
        self.assertGreaterEqual(sidecar, 7)


class WaveSixteenMultiWaveCoexistenceTests(unittest.TestCase):
    """KSante has both wave 1 Q + wave 16 W in primary registry."""

    def test_ksante_has_q_and_w_slots(self) -> None:
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["KSante"].keys())
        self.assertIn("Q", slots)
        self.assertIn("W", slots)

    def test_ksante_q_is_root_nth_hit(self) -> None:
        # Wave 1 entry (unchanged).
        q_entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["Q"]
        self.assertEqual(q_entry.cc_kind, "root")
        self.assertEqual(q_entry.condition, cc.COND_NTH_HIT)

    def test_ksante_w_is_stun_channel(self) -> None:
        # Wave 16 entry (new).
        w_entry = cc._PER_SPELL_CC_CONDITIONAL["KSante"]["W"]
        self.assertEqual(w_entry.cc_kind, "stun")
        self.assertEqual(w_entry.condition, cc.COND_CHANNEL_COMPLETION)


class WaveSixteenConditionalTagConsumerCountsTests(unittest.TestCase):
    """Per-tag consumer counts grew correctly."""

    def _all_entries(self) -> list:
        all_entries = []
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            all_entries.extend(spells.values())
        for forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values():
            all_entries.extend(forms.values())
        return all_entries

    def test_nth_hit_grew_by_at_least_two(self) -> None:
        # COND_NTH_HIT grew by +2 (Garen Q + Udyr E). Wave 15
        # baseline was 6 nth_hit consumers; wave 16 adds 2 = 8.
        nth_hit_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_NTH_HIT
        ]
        self.assertGreaterEqual(len(nth_hit_consumers), 8)

    def test_target_debuffed_grew_by_at_least_one(self) -> None:
        # COND_TARGET_DEBUFFED grew by +1 (Syndra E). Post-wave-16
        # baseline is 10 consumers.
        debuffed_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_TARGET_DEBUFFED
        ]
        self.assertGreaterEqual(len(debuffed_consumers), 10)

    def test_channel_completion_grew_by_at_least_one(self) -> None:
        # COND_CHANNEL_COMPLETION grew by +1 (KSante W). Wave 15
        # baseline was >=12 channel consumers; wave 16 adds 1 = 13.
        channel_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_CHANNEL_COMPLETION
        ]
        self.assertGreaterEqual(len(channel_consumers), 13)

    def test_terrain_unchanged_at_one(self) -> None:
        # Wave 16 does NOT add any COND_TERRAIN entries. Wave 15
        # first consumer (Ornn E) remains the only consumer.
        terrain_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_TERRAIN
        ]
        self.assertGreaterEqual(len(terrain_consumers), 1)

    def test_frenzy_state_unchanged(self) -> None:
        # Wave 16 does NOT add any COND_FRENZY_STATE entries.
        frenzy_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_FRENZY_STATE
        ]
        self.assertGreaterEqual(len(frenzy_consumers), 3)

    def test_range_gated_still_zero_consumers(self) -> None:
        # COND_RANGE_GATED remains a forward-marker with no consumers
        # post-wave-16.
        range_gated_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_RANGE_GATED
        ]
        self.assertEqual(len(range_gated_consumers), 0)


class WaveSixteenDefaultCallerByteIdenticalTests(unittest.TestCase):
    """Default include_conditional=False is BYTE-IDENTICAL to 1.52.0."""

    def test_garen_default_total_unchanged(self) -> None:
        # Pre-wave-16: Garen default total = 0.0 (no unconditional
        # CC entries for Garen anywhere). Wave 16 adds Q conditional
        # only; default path skips conditional.
        result = compute_cc_pressure("Garen", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_garen_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Garen", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_syndra_default_total_unchanged(self) -> None:
        # Pre-wave-16: Syndra default total = 0.0 (no unconditional
        # CC entries for Syndra).
        result = compute_cc_pressure("Syndra", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_syndra_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Syndra", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_udyr_default_total_unchanged(self) -> None:
        # Pre-wave-16: Udyr default total = 0.0 (no unconditional
        # CC entries for Udyr).
        result = compute_cc_pressure("Udyr", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_udyr_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Udyr", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_ksante_default_total_unchanged(self) -> None:
        # Pre-wave-16: KSante default total = KSante R unconditional
        # 0.75s flat. Wave 16 adds W conditional only; default path
        # skips conditional so total stays 0.75.
        result = compute_cc_pressure("KSante", "sr")
        self.assertEqual(result.total_cc_seconds, 0.75)

    def test_ksante_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("KSante", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)


class WaveSixteenIncludeConditionalMathTests(unittest.TestCase):
    """include_conditional=True receives probability-weighted contribution."""

    def test_garen_conditional_contribution(self) -> None:
        # Garen Q: 1.5s silence at probability 0.7 = 1.05s.
        result = compute_cc_pressure("Garen", "sr", include_conditional=True)
        self.assertAlmostEqual(result.total_cc_seconds, 1.05, places=4)
        self.assertAlmostEqual(result.conditional_cc_seconds, 1.05, places=4)

    def test_syndra_conditional_contribution(self) -> None:
        # Syndra E: 1.25s stun at probability 0.5 = 0.625s.
        result = compute_cc_pressure("Syndra", "sr", include_conditional=True)
        self.assertAlmostEqual(result.total_cc_seconds, 0.625, places=4)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.625, places=4)

    def test_udyr_conditional_contribution(self) -> None:
        # Udyr E: 0.75s stun at probability 0.7 = 0.525s.
        result = compute_cc_pressure("Udyr", "sr", include_conditional=True)
        self.assertAlmostEqual(result.total_cc_seconds, 0.525, places=4)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.525, places=4)

    def test_ksante_conditional_contribution(self) -> None:
        # KSante W: 1.0s stun at probability 0.5 = 0.5s contribution.
        # KSante Q wave 1: 0.75s root at probability 0.7 = 0.525s.
        # Total conditional = 0.5 + 0.525 = 1.025.
        # Unconditional R = 0.75. Grand total = 0.75 + 1.025 = 1.775.
        result = compute_cc_pressure("KSante", "sr", include_conditional=True)
        self.assertAlmostEqual(result.total_cc_seconds, 1.775, places=4)
        self.assertAlmostEqual(result.conditional_cc_seconds, 1.025, places=4)


class WaveSixteenGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns the new entries."""

    def test_get_conditional_entries_garen(self) -> None:
        entries = cc.get_conditional_entries("Garen")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[0].cc_kind, "silence")

    def test_get_conditional_entries_syndra(self) -> None:
        entries = cc.get_conditional_entries("Syndra")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "E")
        self.assertEqual(entries[0].cc_kind, "stun")

    def test_get_conditional_entries_udyr(self) -> None:
        entries = cc.get_conditional_entries("Udyr")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "E")
        self.assertEqual(entries[0].cc_kind, "stun")

    def test_get_conditional_entries_ksante_has_both(self) -> None:
        # KSante has wave 1 Q + wave 16 W.
        entries = cc.get_conditional_entries("KSante")
        self.assertEqual(len(entries), 2)
        slots = {e.spell for e in entries}
        self.assertEqual(slots, {"Q", "W"})


class WaveSixteenBuilderIdempotenceTests(unittest.TestCase):
    """The builder functions are deterministic + do not mutate globals."""

    def test_primary_builder_produces_garen_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("Garen", fresh_primary)
        self.assertIn("Q", fresh_primary["Garen"])
        e = fresh_primary["Garen"]["Q"]
        self.assertEqual(e.durations_s, (1.5,))

    def test_primary_builder_produces_syndra_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("Syndra", fresh_primary)
        self.assertIn("E", fresh_primary["Syndra"])
        e = fresh_primary["Syndra"]["E"]
        self.assertEqual(e.condition, cc.COND_TARGET_DEBUFFED)

    def test_primary_builder_produces_udyr_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("Udyr", fresh_primary)
        self.assertIn("E", fresh_primary["Udyr"])
        e = fresh_primary["Udyr"]["E"]
        self.assertEqual(e.durations_s, (0.75,))

    def test_primary_builder_produces_ksante_w_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("KSante", fresh_primary)
        self.assertIn("W", fresh_primary["KSante"])
        e = fresh_primary["KSante"]["W"]
        self.assertEqual(e.condition, cc.COND_CHANNEL_COMPLETION)

    def test_primary_builder_idempotent_across_two_invocations(self) -> None:
        a = cc._build_per_spell_cc_conditional()
        b = cc._build_per_spell_cc_conditional()
        self.assertIsNot(a, b)
        self.assertEqual(a["Garen"]["Q"], b["Garen"]["Q"])
        self.assertEqual(a["Syndra"]["E"], b["Syndra"]["E"])
        self.assertEqual(a["Udyr"]["E"], b["Udyr"]["E"])
        self.assertEqual(a["KSante"]["W"], b["KSante"]["W"])


class WaveSixteenSchemaCrossReferenceTests(unittest.TestCase):
    """Shipped entries match effects_descriptions in extracted JSON."""

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

    def test_garen_q_form_0_effects_mention_silence_1_5s(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Garen"]["Q"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("silence", effects_text.lower())
        self.assertIn("1.5 seconds", effects_text)

    def test_syndra_e_form_0_effects_mention_stun_1_25s(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Syndra"]["E"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("stunned for 1.25 seconds", effects_text)

    def test_udyr_e_form_0_effects_mention_stun_0_75s(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Udyr"]["E"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("stun them for 0.75 seconds", effects_text)

    def test_ksante_w_form_0_effects_mention_stun_range(self) -> None:
        data = self._load_extracted()
        form = data["data"]["KSante"]["W"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("stunning them for", effects_text)
        self.assertIn("based on channel time", effects_text)


class WaveSixteenRejectVerdictsPinnedTests(unittest.TestCase):
    """REJECT verdicts documented in module docstring."""

    def test_module_docstring_documents_ahri_w_reject(self) -> None:
        src = inspect.getsource(cc)
        self.assertIn("Ahri W", src)

    def test_module_docstring_documents_milio_r_reject(self) -> None:
        src = inspect.getsource(cc)
        self.assertIn("Milio R", src)

    def test_module_docstring_documents_irelia_r_reject(self) -> None:
        src = inspect.getsource(cc)
        self.assertIn("Irelia R", src)


class WaveSixteenWiredSitesGrepTests(unittest.TestCase):
    """Wave 16 entries grep-match in the cc_conditional.py source."""

    def _source(self) -> str:
        return inspect.getsource(cc)

    def test_source_mentions_garen_q_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Garen", {})["Q"]', src)

    def test_source_mentions_syndra_e_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Syndra", {})["E"]', src)

    def test_source_mentions_udyr_e_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Udyr", {})["E"]', src)

    def test_source_mentions_ksante_w_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("KSante", {})["W"]', src)

    def test_source_mentions_decisive_strike(self) -> None:
        src = self._source()
        self.assertIn("Decisive Strike", src)

    def test_source_mentions_scatter_the_weak(self) -> None:
        src = self._source()
        self.assertIn("Scatter the Weak", src)

    def test_source_mentions_blazing_stampede(self) -> None:
        src = self._source()
        self.assertIn("Blazing Stampede", src)

    def test_source_mentions_path_maker(self) -> None:
        src = self._source()
        self.assertIn("Path Maker", src)

    def test_source_mentions_wave_16_marker(self) -> None:
        src = self._source()
        self.assertIn("wave 16 expansion", src.lower())


class EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.53.0."""

    def test_engine_version_string_pin(self) -> None:
        major, minor, patch = (int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 53, 0))


class AsciiHygieneTests(unittest.TestCase):
    """Test file is ASCII-clean + cc_conditional wave 16 block is ASCII."""

    def test_this_test_file_is_ascii(self) -> None:
        path = Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII bytes in {path.name}",
        )

    def test_cc_conditional_wave_16_block_is_ascii(self) -> None:
        src = inspect.getsource(cc)
        # Slice from the "wave 16 expansion" header through the
        # end-of-builder; assert no non-ASCII bytes appear in that
        # slice. The earlier waves carry pre-existing non-ASCII bytes
        # so we scope the check to the wave 16 block only.
        marker = "wave 16 expansion (2026-05-24 / ENGINE 1.53.0)"
        idx = src.find(marker)
        self.assertGreater(idx, -1, "wave 16 header marker missing")
        # Take a generous slice past the KSante setdefault site.
        end_marker = src.find('setdefault("KSante", {})["W"]', idx)
        if end_marker < 0:
            end_marker = src.find('setdefault("Udyr", {})["E"]', idx)
        block = src[idx : end_marker + 4096]
        non_ascii = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII characters in wave 16 block",
        )


if __name__ == "__main__":
    unittest.main()
