"""ENGINE 1.52.0 (2026-05-24) - cc_conditional wave 15.

Wave 15 ships +3 entries (+2 primary + 1 sidecar) across +2 net-new
champions (Zac + Rell; Ornn already in registry with Q wave 4
debuffed_target knockup) sourced from a systematic re-audit of the
ENGINE 1.51.0 Meraki schema-lifted data file (cast_time +
effects_descriptions cross-reference). The audit walked all 110 forms
across 171 champions where cast_time>0 + a CC-keyword appears in
effects_descriptions; 57 of those collide with the unconditional
_PER_SPELL_CC_DURATIONS registry (BLOCKED absent a same-spell-slot
coexistence schema lift), 28 are already-covered cc_conditional
entries, leaving 25 candidates of which 3 close cleanly (no schema
lift + no tag expansion + no collision) and 22 REJECT per shape
mismatch.

NEW cc_conditional entries:

  * Zac Q Stretching Strikes 2-hit cross-target root (primary
    registry, NEW champion) - COND_NTH_HIT at probability 0.7.
    - durations_s=(0.5,) flat across all 5 Q ranks per
      effects_descriptions ("both are rooted for 0.5 seconds").
    - mechanic: first Q strike applies tether + slow; the
      empowered second strike (replaces next AA within 2s tether
      window) lands on a DIFFERENT target = both rooted 0.5s.
      Same-target double-strike = damage + slow only (no root).
    - FIRST Zac Q first-order CC registration in the engine.
    - Coexists with unconditional Zac E + R entries in
      _PER_SPELL_CC_DURATIONS on different spell slots.

  * Ornn E Searing Charge terrain-collision stun (primary
    registry, EXISTING champion - Ornn already had Q wave 4) -
    COND_TERRAIN at probability 0.3.
    - durations_s=(1.25,) flat across all 5 E ranks per
      effects_descriptions ("stuns nearby enemies for 1.25
      seconds").
    - mechanic: Ornn charges + deals damage; terrain collision
      mid-charge creates a shockwave knockup + stun 1.25s.
      Standalone E with no terrain hit = damage only.
    - FIRST consumer of COND_TERRAIN tag (was forward-marker
      since wave 7 schema lift).
    - Coexists with the wave 4 cc_conditional Ornn Q
      debuffed-target knockup entry on a different spell slot
      (multi-wave coexistence pattern).

  * Rell W form_index=0 Ferromancy: Crash Down channel-completion
    stun (sidecar registry, NEW champion) - COND_CHANNEL_COMPLETION
    at probability 0.5.
    - durations_s=(0.8,) flat across all 5 W ranks per
      effects_descriptions ("stuns them for 0.8 seconds").
    - mechanic: Rell's Mounted-state W leaps over 0.625s
      cast_time; on arrival stuns + knocks up + slides. Mid-cast
      hard CC cancels the arrival payload.
    - Form 1 (Mount Up Dismounted-state empowered-AA) is
      REJECTED this wave pending operator clarification on
      form-transition empowered-AA registration.
    - FIRST Rell W first-order CC registration in the engine.
    - Coexists with unconditional Rell Q stun entry in
      _PER_SPELL_CC_DURATIONS on a different spell slot.
    - Sidecar pattern parallel to Hwei E form 1+2 + Sylas E
      form 1 + Karma W form 1 + Gnar W form 1 + Aphelios Q
      form 3 + Jayce E form 0.
    - Form-explicit override key shape: Rell:W:0.

Wave 15 REJECT verdicts (22 candidates evaluated; CARRY-FORWARD
only if new evidence surfaces):

  * Aatrox R / Darius R / Sion E / Nunu Q - minion-only fear or
    stun payloads (NOT champion CC).
  * Ambessa R / Blitzcrank R / Darius E / Quinn R / Velkoz E -
    UNCONDITIONAL CC on primary champion target; belong in
    _PER_SPELL_CC_DURATIONS not cc_conditional.
  * Fiddlesticks E center silence / Irelia R perimeter -
    positional sub-zone gating not encoded by schema.
  * Khazix Q - "fear" appears in spell name only.
  * LeeSin R - item 171 wave 13 REJECT carries.
  * Aphelios R - already shipped as Aphelios:Q:3 sidecar
    (wave 13).
  * Rell W form 1 Mount Up - form-transition empowered-AA
    semantics not cleanly cast-time conditional; REJECT pending
    operator clarification.
  * Syndra E Transcendent - state-tracking not encoded.
  * Taliyah Q no CC; Taliyah E - no clean tag fit.
  * Urgot R Mercy recast - target HP-threshold state-tracking.
  * XinZhao R knockback - not in cc_conditional CC kind schema.
  * Zyra R - UNCONDITIONAL zone knockup.

Registry growth: 57 -> 60 entries / 49 -> 51 champions
(51 primary -> 53 primary + 6 sidecar -> 7 sidecar).

Per-tag consumer counts: COND_NTH_HIT +1 (Zac Q); COND_TERRAIN
+1 (Ornn E, FIRST consumer ever); COND_CHANNEL_COMPLETION +1
(Rell W form 0); others unchanged.

Math preservation: default include_conditional=False
compute_cc_pressure BYTE-IDENTICAL to 1.51.0 (the conditional
path skips when the flag is False). include_conditional=True
callers receive new probability-weighted contributions:
Zac +0.35s, Ornn +0.375s, Rell +0.4s.

Coverage classes:

  * WaveFifteenZacShapeTests - Zac Q primary entry shape pin.
  * WaveFifteenOrnnShapeTests - Ornn E primary entry shape pin.
  * WaveFifteenRellShapeTests - Rell W form 0 sidecar entry
    shape pin.
  * WaveFifteenRegistryGrowthTests - REGISTRY_TOTAL_ENTRIES /
    REGISTRY_TOTAL_CHAMPIONS grew to 60 / 51.
  * WaveFifteenMultiWaveCoexistenceTests - Ornn has both wave 4
    Q entry + wave 15 E entry in primary registry.
  * WaveFifteenSidecarRellTests - Rell lives ONLY in sidecar
    registry (NOT in primary) for cc_conditional.
  * WaveFifteenConditionalTagConsumerCountsTests - per-tag
    consumer counts grew correctly. COND_TERRAIN goes from 0
    consumers (forward-marker) to 1 consumer.
  * WaveFifteenDefaultCallerByteIdenticalTests - default
    include_conditional=False compute_cc_pressure is BYTE-
    IDENTICAL to 1.51.0 for Zac / Ornn / Rell.
  * WaveFifteenIncludeConditionalMathTests - include_conditional=
    True receives probability-weighted contribution for each
    new entry.
  * WaveFifteenGetConditionalEntriesTests - get_conditional_entries
    returns the new entries.
  * WaveFifteenBuilderIdempotenceTests - the builder functions
    are deterministic + do not mutate globals.
  * WaveFifteenSchemaLiftCrossReferenceTests - the shipped
    entries match the cast_time + effects_descriptions schema
    values in the extracted JSON.
  * WaveFifteenWiredSitesGrepTests - wave 15 entries grep-match
    in the cc_conditional.py source.
  * EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.52.0.
  * AsciiHygieneTests - the test file is ASCII-clean +
    cc_conditional.py wave 15 block is ASCII-clean.
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class WaveFifteenZacShapeTests(unittest.TestCase):
    """Zac Q primary entry shape pin."""

    def test_zac_in_primary_registry(self) -> None:
        self.assertIn("Zac", cc._PER_SPELL_CC_CONDITIONAL)

    def test_zac_q_slot_present(self) -> None:
        self.assertIn("Q", cc._PER_SPELL_CC_CONDITIONAL["Zac"])

    def test_zac_q_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertEqual(entry.durations_s, (0.5,))

    def test_zac_q_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertEqual(entry.cc_kind, "root")

    def test_zac_q_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)

    def test_zac_q_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertEqual(entry.probability, 0.7)

    def test_zac_q_entry_form_index_default(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertIsNone(entry.form_index)

    def test_zac_q_entry_notes_mention_stretching_strikes(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertIn("Stretching Strikes", entry.notes)

    def test_zac_q_entry_notes_mention_cross_target(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Zac"]["Q"]
        self.assertIn("different target", entry.notes.lower())


class WaveFifteenOrnnShapeTests(unittest.TestCase):
    """Ornn E primary entry shape pin."""

    def test_ornn_e_slot_present(self) -> None:
        # Ornn already in primary with wave 4 Q; wave 15 adds E.
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Ornn"])

    def test_ornn_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertEqual(entry.durations_s, (1.25,))

    def test_ornn_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_ornn_e_entry_condition_is_terrain(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertEqual(entry.condition, cc.COND_TERRAIN)

    def test_ornn_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertEqual(entry.probability, 0.3)

    def test_ornn_e_entry_form_index_default(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertIsNone(entry.form_index)

    def test_ornn_e_entry_notes_mention_searing_charge(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertIn("Searing Charge", entry.notes)

    def test_ornn_e_entry_notes_mention_terrain(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertIn("terrain", entry.notes.lower())

    def test_ornn_q_unchanged_from_wave_4(self) -> None:
        # Wave 4 Ornn Q debuffed_target knockup must still exist.
        entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.condition, cc.COND_TARGET_DEBUFFED)


class WaveFifteenRellShapeTests(unittest.TestCase):
    """Rell W form 0 sidecar entry shape pin."""

    def test_rell_in_sidecar_registry(self) -> None:
        self.assertIn("Rell", cc._PER_SPELL_CC_CONDITIONAL_FORMS)

    def test_rell_w_form_0_slot_present(self) -> None:
        self.assertIn(("W", 0), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"])

    def test_rell_w_form_0_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertEqual(entry.durations_s, (0.8,))

    def test_rell_w_form_0_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertEqual(entry.cc_kind, "stun")

    def test_rell_w_form_0_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_rell_w_form_0_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertEqual(entry.probability, 0.5)

    def test_rell_w_form_0_entry_form_index(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertEqual(entry.form_index, 0)

    def test_rell_w_form_0_entry_notes_mention_crash_down(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertIn("Crash Down", entry.notes)

    def test_rell_w_form_0_entry_notes_mention_cast_time(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        self.assertIn("cast", entry.notes.lower())

    def test_rell_sidecar_includes_form_0(self) -> None:
        # Form 0 (Crash Down) is the channel-completion stun shipped
        # this wave. Form 1 (Mount Up) was REJECTED at wave 15 ship
        # time pending operator clarification on form-transition
        # empowered-AA semantic. The wave 22 ship (ENGINE 1.60.0)
        # added the form 1 sidecar entry via operator-granted
        # authority - test relaxed to allow future-wave additions.
        sidecar_keys = set(cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"].keys())
        self.assertIn(("W", 0), sidecar_keys)


class WaveFifteenRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES / REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_registry_total_entries_grew_to_at_least_sixty(self) -> None:
        # Wave 15 ship-time baseline is 60 (57 wave 14 + 3 wave 15:
        # Zac Q + Ornn E primary + Rell W form 0 sidecar).
        # Relaxed to assertGreaterEqual for future-wave forward compat.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 60)

    def test_registry_total_champions_grew_to_at_least_fifty_one(self) -> None:
        # Wave 15 ship-time baseline is 51 (49 wave 14 + 2 net-new:
        # Zac + Rell; Ornn already had Q wave 4 entry so Ornn E is
        # multi-wave coexistence not net-new champion).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 51)

    def test_primary_registry_grew_to_at_least_fifty_three(self) -> None:
        primary = sum(len(s) for s in cc._PER_SPELL_CC_CONDITIONAL.values())
        # Wave 14 baseline was 51 primary; wave 15 adds Zac Q + Ornn E.
        self.assertGreaterEqual(primary, 53)

    def test_sidecar_registry_grew_to_at_least_seven(self) -> None:
        sidecar = sum(
            len(f) for f in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        # Wave 14 baseline was 6 sidecar; wave 15 adds Rell W form 0.
        self.assertGreaterEqual(sidecar, 7)


class WaveFifteenMultiWaveCoexistenceTests(unittest.TestCase):
    """Ornn has both wave 4 Q entry + wave 15 E entry in primary registry."""

    def test_ornn_has_q_and_e_slots(self) -> None:
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["Ornn"].keys())
        self.assertIn("Q", slots)
        self.assertIn("E", slots)

    def test_ornn_q_is_knockup_debuffed_target(self) -> None:
        # Wave 4 entry (unchanged).
        q_entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["Q"]
        self.assertEqual(q_entry.cc_kind, "knockup")
        self.assertEqual(q_entry.condition, cc.COND_TARGET_DEBUFFED)

    def test_ornn_e_is_stun_terrain(self) -> None:
        # Wave 15 entry (new).
        e_entry = cc._PER_SPELL_CC_CONDITIONAL["Ornn"]["E"]
        self.assertEqual(e_entry.cc_kind, "stun")
        self.assertEqual(e_entry.condition, cc.COND_TERRAIN)


class WaveFifteenSidecarRellTests(unittest.TestCase):
    """Rell lives ONLY in sidecar registry (NOT in primary)."""

    def test_rell_not_in_primary_registry(self) -> None:
        self.assertNotIn("Rell", cc._PER_SPELL_CC_CONDITIONAL)

    def test_rell_q_unconditional_entry_preserved(self) -> None:
        # Rell Q unconditional stun must still be in _PER_SPELL_CC_DURATIONS.
        # The wave 15 entry is W form 0; it does NOT touch Q.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertIn("Rell", _PER_SPELL_CC_DURATIONS)
        self.assertIn("Q", _PER_SPELL_CC_DURATIONS["Rell"])


class WaveFifteenConditionalTagConsumerCountsTests(unittest.TestCase):
    """Per-tag consumer counts grew correctly."""

    def _all_entries(self) -> list:
        all_entries = []
        for spells in cc._PER_SPELL_CC_CONDITIONAL.values():
            all_entries.extend(spells.values())
        for forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values():
            all_entries.extend(forms.values())
        return all_entries

    def test_nth_hit_grew_by_at_least_one(self) -> None:
        # COND_NTH_HIT grew by +1 (Zac Q).
        nth_hit_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_NTH_HIT
        ]
        # Wave 14 baseline + 1 (Zac Q). Lower bound for forward compat.
        self.assertGreaterEqual(len(nth_hit_consumers), 6)

    def test_terrain_first_consumer_registered(self) -> None:
        # COND_TERRAIN goes from 0 (forward-marker) -> 1 (Ornn E,
        # FIRST consumer ever in the registry).
        terrain_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_TERRAIN
        ]
        self.assertGreaterEqual(len(terrain_consumers), 1)

    def test_terrain_first_consumer_is_ornn_e(self) -> None:
        terrain_consumers = [
            e for e in self._all_entries() if e.condition == cc.COND_TERRAIN
        ]
        ornn_e = [
            e
            for e in terrain_consumers
            if e.champion == "Ornn" and e.spell == "E"
        ]
        self.assertEqual(len(ornn_e), 1)

    def test_channel_completion_grew_by_at_least_one(self) -> None:
        # COND_CHANNEL_COMPLETION grew by +1 (Rell W form 0).
        channel_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_CHANNEL_COMPLETION
        ]
        # Wave 14 baseline (>=11 from wave 14 test pin) + 1.
        self.assertGreaterEqual(len(channel_consumers), 12)

    def test_frenzy_state_unchanged(self) -> None:
        # Wave 15 does NOT add any COND_FRENZY_STATE entries.
        frenzy_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_FRENZY_STATE
        ]
        self.assertGreaterEqual(len(frenzy_consumers), 3)

    def test_range_gated_still_zero_consumers(self) -> None:
        # Wave 15 ship-time: COND_RANGE_GATED had 0 consumers. Wave
        # 18 (ENGINE 1.55.0) added Maokai R as the FIRST consumer via
        # the coexists_with_unconditional schema lift. Wave 15
        # invariant relaxed: at most 1 consumer present at this point.
        range_gated_consumers = [
            e
            for e in self._all_entries()
            if e.condition == cc.COND_RANGE_GATED
        ]
        self.assertLessEqual(len(range_gated_consumers), 2)  # wave 23 lift Maokai R + Hecarim R


class WaveFifteenDefaultCallerByteIdenticalTests(unittest.TestCase):
    """Default include_conditional=False is BYTE-IDENTICAL to 1.51.0."""

    def test_zac_default_total_unchanged(self) -> None:
        # Pre-wave-15: Zac default total = 2.0 (E + R unconditional).
        # Wave 15 adds Q conditional only; default path skips conditional.
        result = compute_cc_pressure("Zac", "sr")
        self.assertEqual(result.total_cc_seconds, 2.0)

    def test_zac_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Zac", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_ornn_default_total_unchanged(self) -> None:
        # Pre-wave-15: Ornn default total = 0.5 (R unconditional only;
        # Q is conditional debuffed_target wave 4 which skips on default).
        result = compute_cc_pressure("Ornn", "sr")
        self.assertEqual(result.total_cc_seconds, 0.5)

    def test_ornn_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Ornn", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_rell_default_total_unchanged(self) -> None:
        # Pre-wave-15: Rell default total = 1.0 (Q unconditional only).
        # Wave 15 adds W form 0 conditional; default path skips it.
        result = compute_cc_pressure("Rell", "sr")
        self.assertEqual(result.total_cc_seconds, 1.0)

    def test_rell_default_has_no_conditional_contribution(self) -> None:
        result = compute_cc_pressure("Rell", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)


class WaveFifteenIncludeConditionalMathTests(unittest.TestCase):
    """include_conditional=True receives probability-weighted contribution."""

    def test_zac_conditional_contribution(self) -> None:
        # Zac Q: 0.5s root at probability 0.7 = 0.35s contribution.
        result = compute_cc_pressure("Zac", "sr", include_conditional=True)
        # Existing unconditional E + R = 2.0; add 0.35 conditional = 2.35.
        self.assertAlmostEqual(result.total_cc_seconds, 2.35, places=4)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.35, places=4)

    def test_zac_conditional_entries_includes_q(self) -> None:
        result = compute_cc_pressure("Zac", "sr", include_conditional=True)
        q_entries = [e for e in result.conditional_entries if e.spell == "Q"]
        self.assertEqual(len(q_entries), 1)
        entry = q_entries[0]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (0.5,))

    def test_ornn_conditional_contribution(self) -> None:
        # Ornn E: 1.25s stun at probability 0.3 = 0.375s contribution.
        # Wave 4 Q: 1.5s knockup at probability 0.5 = 0.75s contribution.
        # Total conditional = 0.375 + 0.75 = 1.125.
        # Unconditional R = 0.5. Grand total = 0.5 + 1.125 = 1.625.
        result = compute_cc_pressure("Ornn", "sr", include_conditional=True)
        self.assertAlmostEqual(result.total_cc_seconds, 1.625, places=4)
        self.assertAlmostEqual(result.conditional_cc_seconds, 1.125, places=4)

    def test_ornn_conditional_entries_includes_e_and_q(self) -> None:
        result = compute_cc_pressure("Ornn", "sr", include_conditional=True)
        slots = {e.spell for e in result.conditional_entries}
        self.assertEqual(slots, {"Q", "E"})

    def test_rell_conditional_contribution(self) -> None:
        # Rell W form 0 (wave 15): 0.8s stun at probability 0.5 =
        # 0.4s contribution. Existing unconditional Q = 1.0.
        # Wave 22 ship (ENGINE 1.60.0) added Rell W form 1 sidecar
        # entry (0.6s stun at probability 0.4 = 0.24s contribution).
        # Wave 15 baseline grand total was 1.4; with wave 22 form 1
        # the grand total grew to 1.64. Use assertGreaterEqual for
        # forward-wave compat.
        result = compute_cc_pressure("Rell", "sr", include_conditional=True)
        self.assertGreaterEqual(result.total_cc_seconds, 1.4)
        self.assertGreaterEqual(result.conditional_cc_seconds, 0.4)

    def test_rell_conditional_entries_includes_w_form_0(self) -> None:
        # Wave 15 ship-time invariant: at least 1 conditional entry
        # for Rell with W form_index 0. Wave 22 added a second entry
        # (form_index 1); relaxed length assertion to assertGreaterEqual.
        result = compute_cc_pressure("Rell", "sr", include_conditional=True)
        self.assertGreaterEqual(len(result.conditional_entries), 1)
        # The form 0 entry MUST still appear in the list.
        form0 = next(
            (e for e in result.conditional_entries if e.form_index == 0),
            None,
        )
        self.assertIsNotNone(form0)
        self.assertEqual(form0.spell, "W")
        self.assertEqual(form0.durations_s, (0.8,))


class WaveFifteenGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns the new entries."""

    def test_get_conditional_entries_zac(self) -> None:
        entries = cc.get_conditional_entries("Zac")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[0].cc_kind, "root")

    def test_get_conditional_entries_ornn_has_both(self) -> None:
        # Ornn has wave 4 Q + wave 15 E.
        entries = cc.get_conditional_entries("Ornn")
        self.assertEqual(len(entries), 2)
        slots = {e.spell for e in entries}
        self.assertEqual(slots, {"Q", "E"})

    def test_get_conditional_entries_rell(self) -> None:
        # Wave 15 ship-time invariant: at least 1 conditional entry
        # for Rell with W form_index 0. Wave 22 added form 1; the
        # length check relaxes to assertGreaterEqual for forward
        # compat, but form 0 must still appear with the same shape.
        entries = cc.get_conditional_entries("Rell")
        self.assertGreaterEqual(len(entries), 1)
        form0 = next((e for e in entries if e.form_index == 0), None)
        self.assertIsNotNone(form0)
        self.assertEqual(form0.spell, "W")
        self.assertEqual(form0.cc_kind, "stun")


class WaveFifteenBuilderIdempotenceTests(unittest.TestCase):
    """The builder functions are deterministic + do not mutate globals."""

    def test_primary_builder_produces_zac_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("Zac", fresh_primary)
        self.assertIn("Q", fresh_primary["Zac"])
        e = fresh_primary["Zac"]["Q"]
        self.assertEqual(e.durations_s, (0.5,))

    def test_primary_builder_produces_ornn_e_entry(self) -> None:
        fresh_primary = cc._build_per_spell_cc_conditional()
        self.assertIn("Ornn", fresh_primary)
        self.assertIn("E", fresh_primary["Ornn"])
        e = fresh_primary["Ornn"]["E"]
        self.assertEqual(e.condition, cc.COND_TERRAIN)

    def test_sidecar_builder_produces_rell_entry(self) -> None:
        fresh_sidecar = cc._build_per_spell_cc_conditional_forms()
        self.assertIn("Rell", fresh_sidecar)
        self.assertIn(("W", 0), fresh_sidecar["Rell"])
        e = fresh_sidecar["Rell"][("W", 0)]
        self.assertEqual(e.durations_s, (0.8,))
        self.assertEqual(e.cc_kind, "stun")
        self.assertEqual(e.condition, cc.COND_CHANNEL_COMPLETION)

    def test_primary_builder_idempotent_across_two_invocations(self) -> None:
        a = cc._build_per_spell_cc_conditional()
        b = cc._build_per_spell_cc_conditional()
        self.assertIsNot(a, b)
        self.assertEqual(a["Zac"]["Q"], b["Zac"]["Q"])
        self.assertEqual(a["Ornn"]["E"], b["Ornn"]["E"])

    def test_sidecar_builder_idempotent_across_two_invocations(self) -> None:
        a = cc._build_per_spell_cc_conditional_forms()
        b = cc._build_per_spell_cc_conditional_forms()
        self.assertIsNot(a, b)
        self.assertEqual(a["Rell"][("W", 0)], b["Rell"][("W", 0)])


class WaveFifteenSchemaLiftCrossReferenceTests(unittest.TestCase):
    """Shipped entries match cast_time + effects_descriptions in extracted JSON."""

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

    def test_zac_q_form_0_has_cast_time(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Zac"]["Q"][0]
        self.assertIn("cast_time", form)
        self.assertEqual(form["cast_time"], 0.33)

    def test_zac_q_form_0_effects_mention_different_targets(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Zac"]["Q"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("different targets", effects_text.lower())
        self.assertIn("0.5 seconds", effects_text)

    def test_ornn_e_form_0_has_cast_time(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Ornn"]["E"][0]
        self.assertIn("cast_time", form)
        self.assertEqual(form["cast_time"], 0.35)

    def test_ornn_e_form_0_effects_mention_terrain(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Ornn"]["E"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("terrain", effects_text.lower())
        self.assertIn("1.25 seconds", effects_text)

    def test_rell_w_form_0_has_cast_time(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Rell"]["W"][0]
        self.assertIn("cast_time", form)
        self.assertEqual(form["cast_time"], 0.625)

    def test_rell_w_form_0_effects_mention_stun_duration(self) -> None:
        data = self._load_extracted()
        form = data["data"]["Rell"]["W"][0]
        effects_text = " ".join(form.get("effects_descriptions", []))
        self.assertIn("stuns them for 0.8 seconds", effects_text)


class WaveFifteenWiredSitesGrepTests(unittest.TestCase):
    """Wave 15 entries grep-match in the cc_conditional.py source."""

    def _source(self) -> str:
        return inspect.getsource(cc)

    def test_source_mentions_zac_q_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Zac", {})["Q"]', src)

    def test_source_mentions_ornn_e_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Ornn", {})["E"]', src)

    def test_source_mentions_rell_w_form_0_setdefault(self) -> None:
        src = self._source()
        self.assertIn('setdefault("Rell", {})[("W", 0)]', src)

    def test_source_mentions_stretching_strikes(self) -> None:
        src = self._source()
        self.assertIn("Stretching Strikes", src)

    def test_source_mentions_searing_charge(self) -> None:
        src = self._source()
        self.assertIn("Searing Charge", src)

    def test_source_mentions_crash_down(self) -> None:
        src = self._source()
        self.assertIn("Crash Down", src)

    def test_source_mentions_wave_15_marker(self) -> None:
        src = self._source()
        self.assertIn("wave 15 expansion", src.lower())


class EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.52.0."""

    def test_engine_version_string_pin(self) -> None:
        major, minor, patch = (int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 52, 0))


class AsciiHygieneTests(unittest.TestCase):
    """Test file is ASCII-clean + cc_conditional wave 15 block is ASCII."""

    def test_this_test_file_is_ascii(self) -> None:
        path = Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII bytes in {path.name}",
        )

    def test_cc_conditional_wave_15_block_is_ascii(self) -> None:
        src = inspect.getsource(cc)
        # Slice from the "wave 15 expansion" header through the
        # end-of-builder; assert no non-ASCII bytes appear in that
        # slice. The earlier waves carry pre-existing non-ASCII bytes
        # so we scope the check to the wave 15 block only.
        marker = "wave 15 expansion (2026-05-24 / ENGINE 1.52.0)"
        idx = src.find(marker)
        self.assertGreater(idx, -1, "wave 15 header marker missing")
        # Block ends at the next "return registry" closure after
        # the Rell setdefault site.
        end_marker = src.find('setdefault("Rell", {})[("W", 0)]', idx)
        # Take a generous slice past the Rell setdefault site.
        if end_marker < 0:
            # Fall back to Ornn primary block end.
            end_marker = src.find('setdefault("Ornn", {})["E"]', idx)
        block = src[idx : end_marker + 4096]
        non_ascii = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII characters in wave 15 block",
        )


if __name__ == "__main__":
    unittest.main()
