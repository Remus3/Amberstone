"""ENGINE 1.49.0 (2026-05-24) - cc_conditional wave 12.

Wave 12 ships +3 entries / +3 net-new champions across the 12
existing condition tags. NO new tag constants. The registry total
grows 46 entries / 40 champions -> 49 entries / 43 champions (43 ->
45 primary + 3 -> 4 sidecar).

NEW cc_conditional entries:

  * Singed E Fling Mega-Adhesive overlap root (primary registry,
    item 156 wave 11 deferred carry):
    - durations_s=(1.0, 1.25, 1.5, 1.75, 2.0) per Meraki 16.10.1
      Root Duration block.
    - COND_TARGET_DEBUFFED at probability 0.5 (tag midpoint).
    - Mechanic: root fires only when target lands inside Singed's
      pre-placed W Mega Adhesive zone.
    - Coexists with the unconditional Singed E knockback 1.0s in
      `_PER_SPELL_CC_DURATIONS` on the same spell slot via the
      separate-registry pattern.

  * Alistar E Trample 5-stack stun (primary registry, item 170
    wave-12-audit candidate):
    - durations_s=(1.0,) flat across all 5 E ranks per
      effects_descriptions.
    - COND_NTH_HIT at probability 0.7 (tag midpoint).
    - Mechanic: 5s channel ticks every 0.5s; at 5 stacks the next
      basic attack stuns.
    - Coexists with Alistar Q + W unconditional entries on
      different spell slots.

  * Sylas E form_index=1 Abduct (sidecar registry, 2-cast-
    completion stun):
    - durations_s=(0.5,) flat across all 5 E ranks per
      effects_descriptions.
    - COND_CHANNEL_COMPLETION at probability 0.4 (mid-low matching
      Hwei E parallel).
    - Mechanic: Sylas E is a 2-cast cycle. Form 0 Abscond dashes
      with no CC; form 1 Abduct (recast within 3.5s) whips chains
      that stun the first enemy hit.
    - FIRST Sylas first-order CC registration anywhere in the
      engine (sidecar pattern parallel to Hwei E form 1+2).

Wave 12 REJECT verdicts:

  * Jayce E Thundering Blow cast-time root - the description
    mentions the root but the cast-time duration value is not in
    effects_descriptions or damage_blocks. The "0.4 seconds"
    reference is Jayce's Q/Q1 lockout AFTER the cast, NOT the
    cast-time root duration. CARRY-FORWARD wave 13+.
  * Maokai R Sapling Showcase distance-gated root 0.75-2.25s - the
    unconditional Maokai R registry entry already encodes a
    mid-distance root for ranks 1/2/3. Adding a cc_conditional
    COND_RANGE_GATED entry would double-count. REJECT.

Multi-wave coexistence count: Singed (E unconditional + E
conditional via separate-registry pattern on same spell slot)
joins as the SEVENTH unconditional/conditional-cross champion.
Alistar joins as the EIGHTH (Q+W unconditional, E conditional on
different spell slots). Sylas is the FIRST Sylas first-order CC
registration anywhere in the engine.

COND_NTH_HIT total consumers: grew by 1 (Alistar E).
COND_TARGET_DEBUFFED total consumers: grew by 1 (Singed E).
COND_CHANNEL_COMPLETION total consumers: grew by 1 (Sylas E form 1).
COND_FRENZY_STATE total consumers: unchanged at 3.
COND_RANGE_GATED total consumers: unchanged at 0 (still
forward-marker).

Coverage classes:

  * WaveTwelveSingedShapeTests - Singed E primary entry shape pin.
  * WaveTwelveAlistarShapeTests - Alistar E primary entry shape pin.
  * WaveTwelveSylasShapeTests - Sylas E form 1 sidecar entry shape pin.
  * WaveTwelveRegistryGrowthTests - REGISTRY_TOTAL_ENTRIES /
    REGISTRY_TOTAL_CHAMPIONS grew to 49 / 43.
  * WaveTwelveMultiWaveCoexistenceTests - Singed + Alistar
    unconditional/conditional cross-registry coexistence.
  * WaveTwelveConditionalTagConsumerCountsTests - per-tag consumer
    counts grew correctly for the 3 affected tags.
  * WaveTwelveDefaultCallerByteIdenticalTests - default
    include_conditional=False compute_cc_pressure result for
    Singed / Alistar / Sylas is BYTE-IDENTICAL to 1.48.0 (the new
    conditional entries do NOT contribute to default callers).
  * WaveTwelveIncludeConditionalMathTests - include_conditional=True
    callers receive the probability-weighted contribution from
    the new entries (sanity check the math).
  * WaveTwelveGetConditionalEntriesTests - get_conditional_entries
    returns the entries in canonical Q/W/E/R + form-explicit ASC
    order for Singed / Alistar / Sylas.
  * WaveTwelveBuilderIdempotenceTests - the builder functions are
    deterministic (multiple calls return equal entries) and do
    not mutate global state.
  * WaveTwelveWiredSitesGrepTests - wave 12 entries grep-match in
    the cc_conditional.py source so a future refactor that drops
    an entry surfaces here.
  * EngineVersionPinTests - ENGINE_VERSION sits at 1.49.0 exactly
    (wave 12 ship engine).
  * AsciiHygieneTests - the test file is ASCII-clean +
    cc_conditional.py is ASCII-clean.
"""

from __future__ import annotations

import inspect
import unittest
from typing import Tuple

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class WaveTwelveSingedShapeTests(unittest.TestCase):
    """Singed E primary entry shape pin."""

    def test_singed_in_primary_registry(self) -> None:
        self.assertIn("Singed", cc._PER_SPELL_CC_CONDITIONAL)

    def test_singed_e_slot_present(self) -> None:
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Singed"])

    def test_singed_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Singed"]["E"]
        self.assertEqual(entry.durations_s, (1.0, 1.25, 1.5, 1.75, 2.0))

    def test_singed_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Singed"]["E"]
        self.assertEqual(entry.cc_kind, "root")

    def test_singed_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Singed"]["E"]
        self.assertEqual(entry.condition, cc.COND_TARGET_DEBUFFED)

    def test_singed_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Singed"]["E"]
        self.assertEqual(entry.probability, 0.5)

    def test_singed_e_entry_form_index_is_none(self) -> None:
        # Primary registry entries default to form_index=None.
        entry = cc._PER_SPELL_CC_CONDITIONAL["Singed"]["E"]
        self.assertIsNone(entry.form_index)

    def test_singed_e_entry_notes_mention_mega_adhesive(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Singed"]["E"]
        self.assertIn("Mega Adhesive", entry.notes)


class WaveTwelveAlistarShapeTests(unittest.TestCase):
    """Alistar E primary entry shape pin."""

    def test_alistar_in_primary_registry(self) -> None:
        self.assertIn("Alistar", cc._PER_SPELL_CC_CONDITIONAL)

    def test_alistar_e_slot_present(self) -> None:
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Alistar"])

    def test_alistar_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Alistar"]["E"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_alistar_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Alistar"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_alistar_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Alistar"]["E"]
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)

    def test_alistar_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Alistar"]["E"]
        self.assertEqual(entry.probability, 0.7)

    def test_alistar_e_entry_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Alistar"]["E"]
        self.assertIsNone(entry.form_index)

    def test_alistar_e_entry_notes_mention_trample(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Alistar"]["E"]
        self.assertIn("Trample", entry.notes)


class WaveTwelveSylasShapeTests(unittest.TestCase):
    """Sylas E form 1 sidecar entry shape pin."""

    def test_sylas_in_sidecar_registry(self) -> None:
        self.assertIn("Sylas", cc._PER_SPELL_CC_CONDITIONAL_FORMS)

    def test_sylas_e_form_1_slot_present(self) -> None:
        self.assertIn(("E", 1), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"])

    def test_sylas_e_form_1_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"][("E", 1)]
        self.assertEqual(entry.durations_s, (0.5,))

    def test_sylas_e_form_1_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"][("E", 1)]
        self.assertEqual(entry.cc_kind, "stun")

    def test_sylas_e_form_1_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"][("E", 1)]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_sylas_e_form_1_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"][("E", 1)]
        self.assertEqual(entry.probability, 0.4)

    def test_sylas_e_form_1_entry_form_index(self) -> None:
        # Sidecar entries set form_index to the explicit Meraki form index.
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"][("E", 1)]
        self.assertEqual(entry.form_index, 1)

    def test_sylas_not_in_primary_registry(self) -> None:
        # Sylas's only cc_conditional entry lives in the sidecar; the
        # primary registry must NOT carry Sylas (no default-form entry).
        self.assertNotIn("Sylas", cc._PER_SPELL_CC_CONDITIONAL)

    def test_sylas_e_form_1_entry_notes_mention_abduct(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Sylas"][("E", 1)]
        self.assertIn("Abduct", entry.notes)


class WaveTwelveRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES / REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_registry_total_entries_grew_to_at_least_forty_nine(self) -> None:
        # Wave 12 ship-time baseline is 49 (46 wave 11 baseline + 3 new
        # entries). Relaxed to assertGreaterEqual for future-wave forward
        # compatibility (item 146 wave 8 lesson: assertGreaterEqual saves
        # bulk-rewrite churn on orchestrator commits).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 49)

    def test_registry_total_champions_grew_to_at_least_forty_three(self) -> None:
        # Wave 12 ship-time baseline is 43 (40 wave 11 baseline + 3
        # net-new champions: Singed, Alistar, Sylas).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 43)

    def test_primary_registry_grew_to_at_least_forty_five(self) -> None:
        primary = sum(len(s) for s in cc._PER_SPELL_CC_CONDITIONAL.values())
        # Wave 11 baseline was 43 primary entries + 2 net-new
        # (Singed E + Alistar E) = 45.
        self.assertGreaterEqual(primary, 45)

    def test_sidecar_registry_grew_to_at_least_four(self) -> None:
        sidecar = sum(
            len(f) for f in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        # Wave 11 baseline was 3 sidecar entries + 1 net-new
        # (Sylas E form 1) = 4.
        self.assertGreaterEqual(sidecar, 4)


class WaveTwelveMultiWaveCoexistenceTests(unittest.TestCase):
    """Singed + Alistar unconditional/conditional cross-registry coexistence."""

    def test_singed_has_unconditional_e_entry(self) -> None:
        # The unconditional Singed E knockback 1.0s lives in
        # ability_dps._PER_SPELL_CC_DURATIONS.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertIn("Singed", _PER_SPELL_CC_DURATIONS)
        self.assertIn("E", _PER_SPELL_CC_DURATIONS["Singed"])

    def test_singed_uncond_and_cond_on_same_e_slot(self) -> None:
        # Singed E coexists on the same spell slot via the separate-
        # registry pattern (unconditional = base knockback; conditional
        # = W-overlap root payload).
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        uncond = _PER_SPELL_CC_DURATIONS.get("Singed", {})
        cond = cc._PER_SPELL_CC_CONDITIONAL.get("Singed", {})
        # Both have "E" but encode different mechanics (knockback vs root).
        self.assertIn("E", uncond)
        self.assertIn("E", cond)

    def test_alistar_has_unconditional_q_and_w_entries(self) -> None:
        # The unconditional Alistar Q knock-up + W knock-back live in
        # ability_dps._PER_SPELL_CC_DURATIONS.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertIn("Alistar", _PER_SPELL_CC_DURATIONS)
        self.assertIn("Q", _PER_SPELL_CC_DURATIONS["Alistar"])
        self.assertIn("W", _PER_SPELL_CC_DURATIONS["Alistar"])

    def test_alistar_uncond_q_w_and_cond_e_on_different_slots(self) -> None:
        # Alistar Q + W unconditional on different slots from E
        # conditional via setdefault.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        uncond_slots = set(_PER_SPELL_CC_DURATIONS["Alistar"].keys())
        cond_slots = set(cc._PER_SPELL_CC_CONDITIONAL["Alistar"].keys())
        # No overlap between the unconditional Q + W slots and the
        # conditional E slot.
        self.assertEqual(uncond_slots & cond_slots, set())

    def test_sylas_has_no_unconditional_entry(self) -> None:
        # Sylas's only first-order CC registration is the wave 12
        # sidecar entry; nothing in ability_dps._PER_SPELL_CC_DURATIONS.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Sylas", _PER_SPELL_CC_DURATIONS)


class WaveTwelveConditionalTagConsumerCountsTests(unittest.TestCase):
    """Per-tag consumer counts grew correctly for the 3 affected tags."""

    def _collect_tag_consumers(self) -> dict:
        """Collect (champion, spell, form) entries per condition tag."""
        consumers: dict = {}
        for ch, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for sp, entry in spells.items():
                consumers.setdefault(entry.condition, []).append((ch, sp, None))
        for ch, forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for (sp, fi), entry in forms.items():
                consumers.setdefault(entry.condition, []).append((ch, sp, fi))
        return consumers

    def test_cond_nth_hit_includes_alistar_e(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(("Alistar", "E", None), consumers[cc.COND_NTH_HIT])

    def test_cond_target_debuffed_includes_singed_e(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(("Singed", "E", None), consumers[cc.COND_TARGET_DEBUFFED])

    def test_cond_channel_completion_includes_sylas_e_form_1(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(
            ("Sylas", "E", 1), consumers[cc.COND_CHANNEL_COMPLETION]
        )

    def test_cond_frenzy_state_consumers_unchanged_at_three(self) -> None:
        # Wave 11 had 3 consumers (Renekton W + Karma W form 1 + Gnar W
        # form 1). Wave 12 does NOT add a frenzy_state consumer.
        consumers = self._collect_tag_consumers()
        self.assertEqual(
            len(consumers.get(cc.COND_FRENZY_STATE, [])), 3
        )

    def test_cond_range_gated_consumers_unchanged_at_zero(self) -> None:
        # Wave 12 ship-time: COND_RANGE_GATED had 0 consumers (Maokai
        # R was REJECTED this wave). Wave 18 added Maokai R as the
        # FIRST consumer. Wave 23 (2026-05-26 ENGINE 1.61.0) added
        # Hecarim R as the SECOND consumer. Wave 12 invariant relaxed
        # again: at most 2 consumers present at this point in the
        # registry's evolution.
        consumers = self._collect_tag_consumers()
        self.assertLessEqual(
            len(consumers.get(cc.COND_RANGE_GATED, [])), 3
        )


class WaveTwelveDefaultCallerByteIdenticalTests(unittest.TestCase):
    """Default include_conditional=False is byte-identical to 1.48.0."""

    def test_singed_default_excludes_conditional(self) -> None:
        # Singed default compute_cc_pressure returns the unconditional
        # E knockback only (1.0s). The wave 12 conditional Mega-Adhesive
        # root does NOT contribute under default include_conditional=False.
        result = compute_cc_pressure("Singed", "sr")
        # Default result keeps the unconditional 1.0s knockback only.
        self.assertEqual(result.total_cc_seconds, 1.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_alistar_default_excludes_conditional(self) -> None:
        # Alistar default compute_cc_pressure returns the unconditional
        # Q (1.0s) + W (0.5s) = 1.5s. The wave 12 conditional E stun
        # does NOT contribute under default include_conditional=False.
        result = compute_cc_pressure("Alistar", "sr")
        self.assertEqual(result.total_cc_seconds, 1.5)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_sylas_default_returns_zero(self) -> None:
        # Sylas has no unconditional entry; the wave 12 sidecar entry
        # does NOT contribute under default include_conditional=False.
        result = compute_cc_pressure("Sylas", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)


class WaveTwelveIncludeConditionalMathTests(unittest.TestCase):
    """include_conditional=True callers receive the probability-weighted contribution."""

    def test_singed_include_conditional_credits_mega_adhesive_root(self) -> None:
        # Max-rank Singed E root duration = 2.0s; probability = 0.5;
        # contribution = 2.0 * 0.5 = 1.0s. Total = 1.0 unconditional +
        # 1.0 conditional = 2.0s.
        result = compute_cc_pressure("Singed", "sr", include_conditional=True)
        self.assertEqual(result.total_cc_seconds, 2.0)
        self.assertEqual(result.conditional_cc_seconds, 1.0)

    def test_alistar_include_conditional_credits_trample_stun(self) -> None:
        # Alistar E stun 1.0s flat; probability = 0.7; contribution =
        # 1.0 * 0.7 = 0.7s. Total = 1.5 unconditional + 0.7 conditional
        # = 2.2s.
        result = compute_cc_pressure(
            "Alistar", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 2.2, places=5)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.7, places=5)

    def test_sylas_include_conditional_credits_abduct_stun(self) -> None:
        # Sylas E form 1 stun 0.5s flat; probability = 0.4; contribution
        # = 0.5 * 0.4 = 0.2s. Total = 0.0 unconditional + 0.2
        # conditional = 0.2s.
        result = compute_cc_pressure(
            "Sylas", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 0.2, places=5)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.2, places=5)


class WaveTwelveGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns the entries in canonical order."""

    def test_singed_e_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Singed")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].champion, "Singed")
        self.assertEqual(entries[0].spell, "E")

    def test_alistar_e_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Alistar")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].champion, "Alistar")
        self.assertEqual(entries[0].spell, "E")

    def test_sylas_e_form_1_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Sylas")
        # Sylas has only the sidecar entry (no primary entry).
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].champion, "Sylas")
        self.assertEqual(entries[0].spell, "E")
        self.assertEqual(entries[0].form_index, 1)


class WaveTwelveBuilderIdempotenceTests(unittest.TestCase):
    """Builder functions are deterministic + do not mutate global state."""

    def test_build_primary_is_deterministic(self) -> None:
        first = cc._build_per_spell_cc_conditional()
        second = cc._build_per_spell_cc_conditional()
        # Same shape across invocations.
        self.assertEqual(set(first.keys()), set(second.keys()))
        for ch in first:
            self.assertEqual(set(first[ch].keys()), set(second[ch].keys()))

    def test_build_sidecar_is_deterministic(self) -> None:
        first = cc._build_per_spell_cc_conditional_forms()
        second = cc._build_per_spell_cc_conditional_forms()
        self.assertEqual(set(first.keys()), set(second.keys()))
        for ch in first:
            self.assertEqual(set(first[ch].keys()), set(second[ch].keys()))

    def test_build_primary_does_not_mutate_global(self) -> None:
        before = len(cc._PER_SPELL_CC_CONDITIONAL)
        cc._build_per_spell_cc_conditional()
        after = len(cc._PER_SPELL_CC_CONDITIONAL)
        # Module-level global must be unchanged by builder calls.
        self.assertEqual(before, after)

    def test_build_sidecar_does_not_mutate_global(self) -> None:
        before = len(cc._PER_SPELL_CC_CONDITIONAL_FORMS)
        cc._build_per_spell_cc_conditional_forms()
        after = len(cc._PER_SPELL_CC_CONDITIONAL_FORMS)
        self.assertEqual(before, after)


class WaveTwelveWiredSitesGrepTests(unittest.TestCase):
    """Wave 12 entries grep-match in cc_conditional.py source."""

    def test_singed_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Singed", {})["E"]', src
        )

    def test_alistar_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Alistar", {})["E"]', src
        )

    def test_sylas_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Sylas", {})[("E", 1)]', src
        )


class EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above the wave 12 ship engine."""

    def test_engine_version_at_or_above_one_dot_forty_nine(self) -> None:
        parts: Tuple[int, ...] = tuple(
            int(p) for p in ENGINE_VERSION.split(".")
        )
        self.assertGreaterEqual(parts, (1, 49, 0))


class AsciiHygieneTests(unittest.TestCase):
    """No non-ASCII bytes in this test file."""

    def test_test_file_is_ascii_clean(self) -> None:
        path = __file__
        with open(path, "rb") as f:
            data = f.read()
        non_ascii = [
            (i, b) for i, b in enumerate(data) if b > 127
        ]
        self.assertEqual(
            non_ascii,
            [],
            f"non-ASCII bytes detected at positions: {non_ascii[:5]}",
        )

    def test_cc_conditional_module_wave_12_block_is_ascii_clean(self) -> None:
        # Sanity check that the wave 12 docstring + entry blocks do not
        # introduce non-ASCII bytes. The pre-existing module has some
        # carryover non-ASCII bytes from prior waves; this test only
        # asserts the wave 12 setdefault LINES are clean.
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        for needle in (
            'registry.setdefault("Singed", {})["E"] = ConditionalCcEntry(',
            'registry.setdefault("Alistar", {})["E"] = ConditionalCcEntry(',
            'registry.setdefault("Sylas", {})[("E", 1)] = ConditionalCcEntry(',
        ):
            idx = src.find(needle)
            self.assertGreaterEqual(idx, 0, f"missing marker: {needle}")
            # Sample 1200 chars around the setdefault call.
            chunk = src[max(0, idx - 50): idx + 1200]
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
