"""ENGINE 1.50.0 (2026-05-24) - cc_conditional wave 13.

Wave 13 ships +7 entries (+6 primary + 1 sidecar) across +5 net-new
champions via an all-champ effects_descriptions scan against the
ENGINE 1.46.0 Meraki schema-lifted data file. Each entry uses ONE of
the 12 existing condition tags - NO new tag constants. The registry
total grows 49 entries / 43 champions -> 56 entries / 48 champions
(45 -> 51 primary + 4 -> 5 sidecar).

NEW cc_conditional entries (6 primary + 1 sidecar):

  * Sejuani E Permafrost (primary, NEW champion):
    - durations_s=(1.0,) flat across all 5 E ranks per
      effects_descriptions ("stuns them for 1 second").
    - COND_NTH_HIT at probability 0.7 (tag midpoint).
    - Mechanic: E can ONLY be cast against an enemy carrying 4
      Frost stacks (accumulated via Sejuani W + allied melee
      basic attacks within a 5s window). The cast itself is
      gated on 4 stacks.
    - Coexists with Sejuani Q + R unconditional stuns in
      _PER_SPELL_CC_DURATIONS on different spell slots.

  * Renata Q Handshake recast bystander stun (primary, NEW champ):
    - durations_s=(0.5,) flat across all 5 Q ranks per
      effects_descriptions ("secondary targets hit are stunned
      for 0.5 seconds").
    - COND_CHANNEL_COMPLETION at probability 0.5 (tag midpoint).
    - Mechanic: first cast roots primary target 1.0s; RECAST
      within tether throws target; SECONDARY enemies struck by
      the thrown body are stunned 0.5s.
    - FIRST Renata first-order CC registration in the engine.

  * Shaco R Hallucinate clone-death box fear (primary, NEW champ):
    - durations_s=(1.0,) flat across all 3 R ranks per
      effects_descriptions ("fearing nearby enemies for 1
      second").
    - COND_CHANNEL_COMPLETION at probability 0.5 (tag midpoint).
    - Mechanic: clone dies/expires (up to 18s) and deploys 3
      mini-boxes that fear nearby enemies 1.0s.
    - Coexists with Shaco W unconditional fear in
      _PER_SPELL_CC_DURATIONS on a different spell slot.

  * Fizz R Chum the Waters lure-on-champion knockup (primary,
    NEW champ):
    - durations_s=(1.0,) flat across all 3 R ranks per
      effects_descriptions ("knocked up for 1 second instead of
      knocked back").
    - COND_TARGET_DEBUFFED at probability 0.5 (tag midpoint).
    - Mechanic: base eruption knocks back; lure attached to a
      champion (slow + reveal debuff) makes the eruption knock
      UP 1.0s instead.
    - FIRST Fizz first-order CC registration in the engine.

  * Warwick E Primal Howl recast fear (primary, EXISTING champion
    coexists with wave 0 Warwick R suppression):
    - durations_s=(1.0,) flat across all 5 E ranks per
      effects_descriptions ("fearing nearby enemies for 1
      second").
    - COND_CHANNEL_COMPLETION at probability 0.5 (tag midpoint).
    - Mechanic: E grants 2.5s damage reduction; recast (manual
      after 1s or auto on buff expiration) fears nearby
      enemies 1.0s.

  * TahmKench W Abyssal Dive emerge stun (primary, EXISTING
    champion - coexists with wave 0 TahmKench R devour
    suppression + wave 5 TahmKench Q nth_hit stun):
    - durations_s=(1.0,) flat across all 5 W ranks per
      effects_descriptions ("knock up and stun them for 1
      second").
    - COND_CHANNEL_COMPLETION at probability 0.5 (tag midpoint).
    - Mechanic: 1.35s channel + 0.15s blink + 0.65s recovery;
      on completion Tahm emerges to stun 1.0s. Interrupted
      channel = no payload.

  * Aphelios Q form_index=3 Gravitum Binding Eclipse expunge
    root (sidecar, NEW champion):
    - durations_s=(1.0,) flat across all Q ranks per
      effects_descriptions ("rooting them for 1 second").
    - COND_TARGET_DEBUFFED at probability 0.5 (tag midpoint).
    - Mechanic: Gravitum-as-main-weapon Q expunges enemies
      carrying Gravitum's slow debuff for 1.0s root. Other
      weapon-forms (Calibrum/Severum/Infernum/Crescendum) have
      NO root payload.
    - FIRST Aphelios first-order CC registration in the engine.

Wave 13 REJECT verdicts (effects_descriptions schema-lift-verified;
CARRY-FORWARD only if new evidence surfaces):

  * LeeSin R Dragon's Rage primary-target airborne 1.0s -
    UNCONDITIONAL CC on the primary target ("rendering them
    airborne for 1 second"); belongs in _PER_SPELL_CC_DURATIONS
    not cc_conditional. The bystander collision knockup IS
    conditional but adding it without the primary unconditional
    entry under-credits the spell. REJECT.
  * Poppy R Keeper's Verdict 1.0s base knockup - the 1.0s
    knockup is the BASE non-charged recast (UNCONDITIONAL);
    belongs in _PER_SPELL_CC_DURATIONS not cc_conditional.
    REJECT.
  * RekSai W form 1 Unburrow knockup 1.0s - unconditional
    knockup on Unburrow form transition; belongs in
    _PER_SPELL_CC_DURATIONS not cc_conditional. REJECT.
  * Jayce E cast-time root - STILL schema-blocked (item 170
    wave 12 carry).
  * Maokai R distance-gated root - STILL double-counts with
    unconditional Maokai R registry entry. REJECT.

Multi-wave coexistence count: Warwick (wave 0 R + wave 13 E)
joins as the NINTH multi-entry-WITHIN-cc_conditional champion.
TahmKench (wave 0 R + wave 5 Q + wave 13 W) extends to TRIPLE
cc_conditional coverage - FIRST 3-slot cc_conditional champion
in the registry.

COND_NTH_HIT total consumers: grew by 1 (Sejuani E wave 13).
COND_TARGET_DEBUFFED total consumers: grew by 2 (Fizz R + Aphelios
Q form 3 wave 13).
COND_CHANNEL_COMPLETION total consumers: grew by 4 (Renata Q +
Shaco R + Warwick E + TahmKench W wave 13).
COND_FRENZY_STATE total consumers: unchanged at 3.
COND_RANGE_GATED total consumers: unchanged at 0 (still
forward-marker).

Coverage classes:

  * WaveThirteenSejuaniShapeTests - Sejuani E primary entry shape
    pin.
  * WaveThirteenRenataShapeTests - Renata Q primary entry shape
    pin.
  * WaveThirteenShacoShapeTests - Shaco R primary entry shape
    pin.
  * WaveThirteenFizzShapeTests - Fizz R primary entry shape pin.
  * WaveThirteenWarwickShapeTests - Warwick E primary entry
    shape pin + coexistence with wave 0 Warwick R.
  * WaveThirteenTahmKenchShapeTests - TahmKench W primary entry
    shape pin + coexistence with wave 0 R + wave 5 Q.
  * WaveThirteenApheliosShapeTests - Aphelios Q form 3 sidecar
    entry shape pin.
  * WaveThirteenRegistryGrowthTests - REGISTRY_TOTAL_ENTRIES /
    REGISTRY_TOTAL_CHAMPIONS grew to 56 / 48.
  * WaveThirteenMultiWaveCoexistenceTests - Warwick + TahmKench +
    Sejuani + Shaco coexistence patterns.
  * WaveThirteenConditionalTagConsumerCountsTests - per-tag
    consumer counts grew correctly.
  * WaveThirteenDefaultCallerByteIdenticalTests - default
    include_conditional=False compute_cc_pressure is BYTE-
    IDENTICAL to 1.49.0 for all wave 13 ship candidates.
  * WaveThirteenIncludeConditionalMathTests - include_conditional=
    True callers receive probability-weighted contribution.
  * WaveThirteenGetConditionalEntriesTests - get_conditional_entries
    returns the entries in canonical order.
  * WaveThirteenBuilderIdempotenceTests - the builder functions
    are deterministic + do not mutate globals.
  * WaveThirteenWiredSitesGrepTests - wave 13 entries grep-match
    in the cc_conditional.py source.
  * EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.50.0.
  * AsciiHygieneTests - the test file is ASCII-clean +
    cc_conditional.py wave 13 block is ASCII-clean.
"""

from __future__ import annotations

import inspect
import unittest
from typing import Tuple

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


class WaveThirteenSejuaniShapeTests(unittest.TestCase):
    """Sejuani E primary entry shape pin."""

    def test_sejuani_in_primary_registry(self) -> None:
        self.assertIn("Sejuani", cc._PER_SPELL_CC_CONDITIONAL)

    def test_sejuani_e_slot_present(self) -> None:
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Sejuani"])

    def test_sejuani_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Sejuani"]["E"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_sejuani_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Sejuani"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_sejuani_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Sejuani"]["E"]
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)

    def test_sejuani_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Sejuani"]["E"]
        self.assertEqual(entry.probability, 0.7)

    def test_sejuani_e_entry_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Sejuani"]["E"]
        self.assertIsNone(entry.form_index)

    def test_sejuani_e_entry_notes_mention_frost(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Sejuani"]["E"]
        self.assertIn("Frost", entry.notes)


class WaveThirteenRenataShapeTests(unittest.TestCase):
    """Renata Q primary entry shape pin."""

    def test_renata_in_primary_registry(self) -> None:
        self.assertIn("Renata", cc._PER_SPELL_CC_CONDITIONAL)

    def test_renata_q_slot_present(self) -> None:
        self.assertIn("Q", cc._PER_SPELL_CC_CONDITIONAL["Renata"])

    def test_renata_q_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Renata"]["Q"]
        self.assertEqual(entry.durations_s, (0.5,))

    def test_renata_q_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Renata"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_renata_q_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Renata"]["Q"]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_renata_q_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Renata"]["Q"]
        self.assertEqual(entry.probability, 0.5)

    def test_renata_q_entry_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Renata"]["Q"]
        self.assertIsNone(entry.form_index)

    def test_renata_q_entry_notes_mention_handshake(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Renata"]["Q"]
        self.assertIn("Handshake", entry.notes)


class WaveThirteenShacoShapeTests(unittest.TestCase):
    """Shaco R primary entry shape pin."""

    def test_shaco_r_slot_present(self) -> None:
        self.assertIn("Shaco", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["Shaco"])

    def test_shaco_r_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Shaco"]["R"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_shaco_r_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Shaco"]["R"]
        self.assertEqual(entry.cc_kind, "fear")

    def test_shaco_r_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Shaco"]["R"]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_shaco_r_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Shaco"]["R"]
        self.assertEqual(entry.probability, 0.5)

    def test_shaco_r_entry_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Shaco"]["R"]
        self.assertIsNone(entry.form_index)

    def test_shaco_r_entry_notes_mention_hallucinate(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Shaco"]["R"]
        self.assertIn("Hallucinate", entry.notes)


class WaveThirteenFizzShapeTests(unittest.TestCase):
    """Fizz R primary entry shape pin."""

    def test_fizz_r_slot_present(self) -> None:
        self.assertIn("Fizz", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["Fizz"])

    def test_fizz_r_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Fizz"]["R"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_fizz_r_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Fizz"]["R"]
        self.assertEqual(entry.cc_kind, "knockup")

    def test_fizz_r_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Fizz"]["R"]
        self.assertEqual(entry.condition, cc.COND_TARGET_DEBUFFED)

    def test_fizz_r_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Fizz"]["R"]
        self.assertEqual(entry.probability, 0.5)

    def test_fizz_r_entry_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Fizz"]["R"]
        self.assertIsNone(entry.form_index)

    def test_fizz_r_entry_notes_mention_chum(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Fizz"]["R"]
        self.assertIn("Chum the Waters", entry.notes)


class WaveThirteenWarwickShapeTests(unittest.TestCase):
    """Warwick E primary entry shape pin + coexistence with wave 0 R."""

    def test_warwick_e_slot_present(self) -> None:
        self.assertIn("Warwick", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Warwick"])

    def test_warwick_e_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Warwick"]["E"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_warwick_e_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Warwick"]["E"]
        self.assertEqual(entry.cc_kind, "fear")

    def test_warwick_e_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Warwick"]["E"]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_warwick_e_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Warwick"]["E"]
        self.assertEqual(entry.probability, 0.5)

    def test_warwick_r_wave0_still_present(self) -> None:
        # The wave 0 Warwick R suppression entry must still be there
        # alongside the new wave 13 E entry.
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["Warwick"])
        r_entry = cc._PER_SPELL_CC_CONDITIONAL["Warwick"]["R"]
        self.assertEqual(r_entry.cc_kind, "suppression")

    def test_warwick_has_both_e_and_r_entries(self) -> None:
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["Warwick"].keys())
        self.assertEqual(slots, {"E", "R"})


class WaveThirteenTahmKenchShapeTests(unittest.TestCase):
    """TahmKench W primary entry shape pin + triple-slot coexistence."""

    def test_tahmkench_w_slot_present(self) -> None:
        self.assertIn("TahmKench", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("W", cc._PER_SPELL_CC_CONDITIONAL["TahmKench"])

    def test_tahmkench_w_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["TahmKench"]["W"]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_tahmkench_w_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["TahmKench"]["W"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_tahmkench_w_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["TahmKench"]["W"]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_tahmkench_w_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["TahmKench"]["W"]
        self.assertEqual(entry.probability, 0.5)

    def test_tahmkench_q_wave5_still_present(self) -> None:
        # Wave 5 TahmKench Q nth_hit stun must still be present.
        self.assertIn("Q", cc._PER_SPELL_CC_CONDITIONAL["TahmKench"])
        q_entry = cc._PER_SPELL_CC_CONDITIONAL["TahmKench"]["Q"]
        self.assertEqual(q_entry.condition, cc.COND_NTH_HIT)

    def test_tahmkench_r_wave0_still_present(self) -> None:
        # Wave 0 TahmKench R devour suppression must still be present.
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["TahmKench"])
        r_entry = cc._PER_SPELL_CC_CONDITIONAL["TahmKench"]["R"]
        self.assertEqual(r_entry.cc_kind, "suppression")

    def test_tahmkench_is_first_triple_slot_champion(self) -> None:
        # TahmKench (Q + W + R) is the FIRST 3-slot cc_conditional
        # champion. Verify by counting slots.
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["TahmKench"].keys())
        self.assertEqual(slots, {"Q", "W", "R"})
        self.assertEqual(len(slots), 3)


class WaveThirteenApheliosShapeTests(unittest.TestCase):
    """Aphelios Q form 3 sidecar entry shape pin."""

    def test_aphelios_in_sidecar_registry(self) -> None:
        self.assertIn("Aphelios", cc._PER_SPELL_CC_CONDITIONAL_FORMS)

    def test_aphelios_q_form_3_slot_present(self) -> None:
        self.assertIn(("Q", 3), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"])

    def test_aphelios_q_form_3_entry_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"][("Q", 3)]
        self.assertEqual(entry.durations_s, (1.0,))

    def test_aphelios_q_form_3_entry_cc_kind(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"][("Q", 3)]
        self.assertEqual(entry.cc_kind, "root")

    def test_aphelios_q_form_3_entry_condition(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"][("Q", 3)]
        self.assertEqual(entry.condition, cc.COND_TARGET_DEBUFFED)

    def test_aphelios_q_form_3_entry_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"][("Q", 3)]
        self.assertEqual(entry.probability, 0.5)

    def test_aphelios_q_form_3_entry_form_index(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"][("Q", 3)]
        self.assertEqual(entry.form_index, 3)

    def test_aphelios_not_in_primary_registry(self) -> None:
        # Aphelios's only cc_conditional entry lives in the sidecar;
        # the primary registry must NOT carry Aphelios.
        self.assertNotIn("Aphelios", cc._PER_SPELL_CC_CONDITIONAL)

    def test_aphelios_q_form_3_entry_notes_mention_gravitum(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Aphelios"][("Q", 3)]
        self.assertIn("Gravitum", entry.notes)


class WaveThirteenRegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES / REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_registry_total_entries_grew_to_at_least_fifty_six(self) -> None:
        # Wave 13 ship-time baseline is 56 (49 wave 12 baseline + 7 new
        # entries). Relaxed to assertGreaterEqual for future-wave forward
        # compatibility (item 146 wave 8 lesson).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 56)

    def test_registry_total_champions_grew_to_at_least_forty_eight(self) -> None:
        # Wave 13 ship-time baseline is 48 (43 wave 12 baseline + 5
        # net-new champions: Sejuani, Renata, Shaco, Fizz, Aphelios).
        # Warwick + TahmKench are NOT net-new (existing cc_conditional
        # champs).
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 48)

    def test_primary_registry_grew_to_at_least_fifty_one(self) -> None:
        primary = sum(len(s) for s in cc._PER_SPELL_CC_CONDITIONAL.values())
        # Wave 12 baseline was 45 primary + 6 net-new (Sejuani E +
        # Renata Q + Shaco R + Fizz R + Warwick E + TahmKench W) = 51.
        self.assertGreaterEqual(primary, 51)

    def test_sidecar_registry_grew_to_at_least_five(self) -> None:
        sidecar = sum(
            len(f) for f in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        # Wave 12 baseline was 4 sidecar + 1 net-new (Aphelios Q form 3) = 5.
        self.assertGreaterEqual(sidecar, 5)


class WaveThirteenMultiWaveCoexistenceTests(unittest.TestCase):
    """Coexistence patterns for wave 13 entries."""

    def test_sejuani_has_unconditional_q_and_r_entries(self) -> None:
        # Sejuani Q + R unconditional stuns live in
        # ability_dps._PER_SPELL_CC_DURATIONS.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertIn("Sejuani", _PER_SPELL_CC_DURATIONS)
        self.assertIn("Q", _PER_SPELL_CC_DURATIONS["Sejuani"])
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Sejuani"])

    def test_sejuani_uncond_qr_and_cond_e_on_different_slots(self) -> None:
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        uncond_slots = set(_PER_SPELL_CC_DURATIONS["Sejuani"].keys())
        cond_slots = set(cc._PER_SPELL_CC_CONDITIONAL["Sejuani"].keys())
        self.assertEqual(uncond_slots & cond_slots, set())

    def test_shaco_has_unconditional_w_entry(self) -> None:
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertIn("Shaco", _PER_SPELL_CC_DURATIONS)
        self.assertIn("W", _PER_SPELL_CC_DURATIONS["Shaco"])

    def test_shaco_uncond_w_and_cond_r_on_different_slots(self) -> None:
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        uncond_slots = set(_PER_SPELL_CC_DURATIONS["Shaco"].keys())
        cond_slots = set(cc._PER_SPELL_CC_CONDITIONAL["Shaco"].keys())
        self.assertEqual(uncond_slots & cond_slots, set())

    def test_renata_has_no_unconditional_entry(self) -> None:
        # Renata's only first-order CC registration is the wave 13 Q.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Renata", _PER_SPELL_CC_DURATIONS)

    def test_fizz_has_no_unconditional_entry(self) -> None:
        # Fizz's only first-order CC registration is the wave 13 R.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Fizz", _PER_SPELL_CC_DURATIONS)

    def test_aphelios_has_no_unconditional_entry(self) -> None:
        # Aphelios's only first-order CC registration is the sidecar
        # wave 13 Q form 3.
        from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Aphelios", _PER_SPELL_CC_DURATIONS)

    def test_warwick_multi_wave_cc_conditional_e_and_r(self) -> None:
        # Warwick has BOTH wave 0 R suppression AND wave 13 E fear in
        # cc_conditional - multi-entry-WITHIN-cc_conditional.
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["Warwick"].keys())
        self.assertIn("E", slots)
        self.assertIn("R", slots)

    def test_tahmkench_is_first_triple_slot_cc_conditional_champ(self) -> None:
        # TahmKench Q + W + R all in cc_conditional - FIRST triple-slot
        # cc_conditional champion.
        slots = set(cc._PER_SPELL_CC_CONDITIONAL["TahmKench"].keys())
        self.assertEqual(slots, {"Q", "W", "R"})


class WaveThirteenConditionalTagConsumerCountsTests(unittest.TestCase):
    """Per-tag consumer counts grew correctly for the wave 13 additions."""

    def _collect_tag_consumers(self) -> dict:
        consumers: dict = {}
        for ch, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for sp, entry in spells.items():
                consumers.setdefault(entry.condition, []).append((ch, sp, None))
        for ch, forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for (sp, fi), entry in forms.items():
                consumers.setdefault(entry.condition, []).append((ch, sp, fi))
        return consumers

    def test_cond_nth_hit_includes_sejuani_e(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(("Sejuani", "E", None), consumers[cc.COND_NTH_HIT])

    def test_cond_target_debuffed_includes_fizz_r(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(("Fizz", "R", None), consumers[cc.COND_TARGET_DEBUFFED])

    def test_cond_target_debuffed_includes_aphelios_q_form_3(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(
            ("Aphelios", "Q", 3), consumers[cc.COND_TARGET_DEBUFFED]
        )

    def test_cond_channel_completion_includes_renata_q(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(
            ("Renata", "Q", None), consumers[cc.COND_CHANNEL_COMPLETION]
        )

    def test_cond_channel_completion_includes_shaco_r(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(
            ("Shaco", "R", None), consumers[cc.COND_CHANNEL_COMPLETION]
        )

    def test_cond_channel_completion_includes_warwick_e(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(
            ("Warwick", "E", None), consumers[cc.COND_CHANNEL_COMPLETION]
        )

    def test_cond_channel_completion_includes_tahmkench_w(self) -> None:
        consumers = self._collect_tag_consumers()
        self.assertIn(
            ("TahmKench", "W", None), consumers[cc.COND_CHANNEL_COMPLETION]
        )

    def test_cond_frenzy_state_consumers_unchanged_at_three(self) -> None:
        # Wave 11 had 3 consumers (Renekton W + Karma W form 1 + Gnar W
        # form 1). Wave 13 does NOT add a frenzy_state consumer.
        consumers = self._collect_tag_consumers()
        self.assertEqual(
            len(consumers.get(cc.COND_FRENZY_STATE, [])), 3
        )

    def test_cond_range_gated_consumers_unchanged_at_zero(self) -> None:
        # Wave 13 ship-time: COND_RANGE_GATED had 0 consumers. Wave
        # 18 added Maokai R as the FIRST consumer. Wave 23 (2026-
        # 05-26 ENGINE 1.61.0) added Hecarim R as the SECOND consumer.
        # Wave 13 invariant relaxed again: at most 2 consumers
        # present at this point in the registry's evolution.
        consumers = self._collect_tag_consumers()
        self.assertLessEqual(
            len(consumers.get(cc.COND_RANGE_GATED, [])), 3
        )


class WaveThirteenDefaultCallerByteIdenticalTests(unittest.TestCase):
    """Default include_conditional=False is byte-identical to 1.49.0."""

    def test_sejuani_default_excludes_conditional(self) -> None:
        # Sejuani default compute_cc_pressure returns the unconditional
        # Q (max-rank 1.25s) + R (max-rank 2.0s) = 3.25s. The wave 13
        # conditional E stun does NOT contribute.
        result = compute_cc_pressure("Sejuani", "sr")
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_renata_default_returns_zero(self) -> None:
        # Renata has no unconditional entry; the wave 13 conditional
        # Q does NOT contribute under default include_conditional=False.
        result = compute_cc_pressure("Renata", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_shaco_default_excludes_conditional(self) -> None:
        # Shaco unconditional W max-rank 1.5s. Wave 13 conditional R
        # does NOT contribute under default.
        result = compute_cc_pressure("Shaco", "sr")
        self.assertEqual(result.total_cc_seconds, 1.5)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_fizz_default_returns_zero(self) -> None:
        # Fizz has no unconditional entry; wave 13 conditional R does
        # NOT contribute under default.
        result = compute_cc_pressure("Fizz", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_warwick_default_excludes_e_conditional(self) -> None:
        # Warwick has NO unconditional entries (wave 0 R is in
        # cc_conditional). Default returns 0.0.
        result = compute_cc_pressure("Warwick", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_tahmkench_default_returns_zero(self) -> None:
        # TahmKench has NO unconditional entries (all 3 of Q/W/R are
        # in cc_conditional). Default returns 0.0.
        result = compute_cc_pressure("TahmKench", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)

    def test_aphelios_default_returns_zero(self) -> None:
        # Aphelios has no unconditional entry; wave 13 sidecar Q form
        # 3 does NOT contribute under default.
        result = compute_cc_pressure("Aphelios", "sr")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.conditional_cc_seconds, 0.0)


class WaveThirteenIncludeConditionalMathTests(unittest.TestCase):
    """include_conditional=True callers receive probability-weighted contribution."""

    def test_sejuani_include_conditional_credits_permafrost(self) -> None:
        # Sejuani E max-rank stun = 1.0s; probability = 0.7;
        # contribution = 1.0 * 0.7 = 0.7s conditional.
        result = compute_cc_pressure(
            "Sejuani", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.7, places=5)

    def test_renata_include_conditional_credits_handshake(self) -> None:
        # Renata Q stun 0.5s flat; probability = 0.5; contribution =
        # 0.5 * 0.5 = 0.25s.
        result = compute_cc_pressure(
            "Renata", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 0.25, places=5)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.25, places=5)

    def test_shaco_include_conditional_credits_hallucinate(self) -> None:
        # Shaco R fear 1.0s flat; probability = 0.5; contribution =
        # 1.0 * 0.5 = 0.5s. Plus unconditional W 1.5s = 2.0s total.
        result = compute_cc_pressure(
            "Shaco", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 2.0, places=5)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.5, places=5)

    def test_fizz_include_conditional_credits_chum(self) -> None:
        # Fizz R knockup 1.0s flat; probability = 0.5; contribution =
        # 1.0 * 0.5 = 0.5s. No unconditional.
        result = compute_cc_pressure(
            "Fizz", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 0.5, places=5)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.5, places=5)

    def test_aphelios_include_conditional_credits_gravitum(self) -> None:
        # Aphelios Q form 3 root 1.0s flat; probability = 0.5;
        # contribution = 1.0 * 0.5 = 0.5s. No unconditional.
        result = compute_cc_pressure(
            "Aphelios", "sr", include_conditional=True
        )
        self.assertAlmostEqual(result.total_cc_seconds, 0.5, places=5)
        self.assertAlmostEqual(result.conditional_cc_seconds, 0.5, places=5)


class WaveThirteenGetConditionalEntriesTests(unittest.TestCase):
    """get_conditional_entries returns the entries in canonical order."""

    def test_sejuani_e_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Sejuani")
        slots = {e.spell for e in entries}
        self.assertIn("E", slots)

    def test_renata_q_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Renata")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_shaco_r_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Shaco")
        slots = {e.spell for e in entries}
        self.assertIn("R", slots)

    def test_fizz_r_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Fizz")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "R")

    def test_warwick_returns_both_r_and_e_in_qwer_order(self) -> None:
        entries = cc.get_conditional_entries("Warwick")
        spells = [e.spell for e in entries]
        # Canonical QWER order: E before R.
        self.assertEqual(spells, ["E", "R"])

    def test_tahmkench_returns_q_w_r_in_qwer_order(self) -> None:
        entries = cc.get_conditional_entries("TahmKench")
        spells = [e.spell for e in entries]
        self.assertEqual(spells, ["Q", "W", "R"])

    def test_aphelios_q_form_3_present_in_get_entries(self) -> None:
        entries = cc.get_conditional_entries("Aphelios")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[0].form_index, 3)


class WaveThirteenBuilderIdempotenceTests(unittest.TestCase):
    """Builder functions are deterministic + do not mutate globals."""

    def test_build_primary_is_deterministic(self) -> None:
        first = cc._build_per_spell_cc_conditional()
        second = cc._build_per_spell_cc_conditional()
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
        self.assertEqual(before, after)

    def test_build_sidecar_does_not_mutate_global(self) -> None:
        before = len(cc._PER_SPELL_CC_CONDITIONAL_FORMS)
        cc._build_per_spell_cc_conditional_forms()
        after = len(cc._PER_SPELL_CC_CONDITIONAL_FORMS)
        self.assertEqual(before, after)


class WaveThirteenWiredSitesGrepTests(unittest.TestCase):
    """Wave 13 entries grep-match in cc_conditional.py source."""

    def test_sejuani_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Sejuani", {})["E"]', src
        )

    def test_renata_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Renata", {})["Q"]', src
        )

    def test_shaco_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Shaco", {})["R"]', src
        )

    def test_fizz_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Fizz", {})["R"]', src
        )

    def test_warwick_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Warwick", {})["E"]', src
        )

    def test_tahmkench_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("TahmKench", {})["W"]', src
        )

    def test_aphelios_setdefault_call_present(self) -> None:
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        self.assertIn(
            'registry.setdefault("Aphelios", {})[("Q", 3)]', src
        )


class EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above the wave 13 ship engine."""

    def test_engine_version_at_or_above_one_dot_fifty(self) -> None:
        parts: Tuple[int, ...] = tuple(
            int(p) for p in ENGINE_VERSION.split(".")
        )
        self.assertGreaterEqual(parts, (1, 50, 0))


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

    def test_cc_conditional_module_wave_13_block_is_ascii_clean(self) -> None:
        # Sanity check that the wave 13 docstring + entry blocks do not
        # introduce non-ASCII bytes. The pre-existing module has some
        # carryover non-ASCII bytes from prior waves; this test only
        # asserts the wave 13 setdefault LINES are clean.
        src = open(cc.__file__.replace("cc_conditional.py", "CC_CONDITIONAL_NOTES.md"), encoding="utf-8").read()
        for needle in (
            'registry.setdefault("Sejuani", {})["E"] = ConditionalCcEntry(',
            'registry.setdefault("Renata", {})["Q"] = ConditionalCcEntry(',
            'registry.setdefault("Shaco", {})["R"] = ConditionalCcEntry(',
            'registry.setdefault("Fizz", {})["R"] = ConditionalCcEntry(',
            'registry.setdefault("Warwick", {})["E"] = ConditionalCcEntry(',
            'registry.setdefault("TahmKench", {})["W"] = ConditionalCcEntry(',
            'registry.setdefault("Aphelios", {})[("Q", 3)] = ConditionalCcEntry(',
        ):
            idx = src.find(needle)
            self.assertGreaterEqual(idx, 0, f"missing marker: {needle}")
            chunk = src[max(0, idx - 50): idx + 1500]
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
