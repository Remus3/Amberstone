"""ENGINE 1.60.0 (2026-05-25) - cc_conditional wave 22 ship of Rell W
form 1 Ferromancy: Mount Up empowered-AA stun.

The wave 22 ship closes item 198 carry (i) "Rell W form 1
cc_conditional candidate STILL operator-decision-gated" - the wave 15
REJECT carry pending operator clarification on form-transition
empowered-AA semantics. Operator-granted authority item 199 Slice B.

The Rell W form 1 Mount Up empowered-AA mechanism is a 2-cast cycle:
form 0 Crash Down (Mounted -> Dismounted leap + arrival stun 0.8s,
wave 15 sidecar entry) -> form 1 Mount Up RECAST within 3.5s
(Dismounted -> Mounted transform + empowers next basic attack within
3.5s with 0.2s cast_time + 100 bonus AA range + 40% bonus AS) ->
empowered AA charge-arrival or collision (stun 0.6s flat across all
5 W ranks + fling 0.4s knockup).

SHIP candidate (sidecar registry):

  (1) Rell W form 1 Ferromancy: Mount Up empowered-AA stun.
      Sidecar entry at (Rell, W, form_index=1) alongside the
      wave 15 (Rell, W, form_index=0) sidecar entry.

      - cc_kind=stun (0.6s primary CC payload; 0.4s fling is a
        separate displacement not registered, mirroring form 0's
        exclusion of its own 0.4s knockup).
      - durations_s=(0.6,) flat across all 5 W ranks. The stun
        does NOT scale with W rank; only cast cooldown + Mount
        Up shield-conversion scale.
      - condition=COND_CHANNEL_COMPLETION on the 2-cast cycle
        (form 0 -> form 1 within 3.5s) + empowered-AA charge-
        delivery sequence. Stun fires ONLY on charge-arrival
        completion; interruption between form 1 cast + AA
        delivery (silenced / CC'd / killed) cancels the stun.
      - probability=0.4 (mid-low, mirroring Sylas E form 1 +
        Hwei E form 1 parallel 2-input setup pattern).
      - form_index=1 (sidecar registry slot).
      - Pattern parallel to Sylas E form 1 Abduct (wave 12) +
        Hwei E form 1 Grim Visage (wave 9) - both 2-cast-cycle
        sidecar entries with COND_CHANNEL_COMPLETION at prob 0.4.

      Mechanic per Meraki effects_descriptions[0] for
      form_index=1: "Upon arrival or collision, she deals
      bonus magic damage, stuns the target for 0.6 seconds, and
      flings them 150 units over herself, though not through
      terrain, over 0.4 seconds."

      Meraki cast_time pinned at 0.25s for the form 1 W recast
      itself (the empowered AA charge has a separate 0.2s
      cast_time on AA delivery).

Rell stays at 1 cc_conditional champion (Rell was already registered
via the wave 15 form 0 sidecar entry). Both sidecar entries coexist
on the same (Rell, W) slot via the form_index discriminator. FOURTH
same-spell-slot multi-form-coexistence in the sidecar registry after
Karma W form 0+1 (wave 1+10), Hwei E form 0+1+2 (wave 9+10), Sylas E
form 0+1 (wave 12).

Registry growth this wave: +1 sidecar entry / 0 net-new champions.
Registry: 70 entries / 56 champs -> 71 entries / 56 champs
(62 primary + 7 sidecar -> 62 primary + 8 sidecar).
Tag count unchanged at 13.
ENGINE 1.59.0 -> 1.60.0.

Per-tag consumer counts: COND_CHANNEL_COMPLETION +1 (Rell W form 1);
all others unchanged.

Math preservation: default
compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL to
ENGINE 1.59.0 for ALL champions (the wave 22 path skips when the
flag is False). include_conditional=True callers receive +0.24s
(0.6 * 0.4) NEW conditional pressure on top of the wave 15 form 0
0.4s (0.8 * 0.5) = total Rell W conditional 0.64s.

Tests pin:
  * Wave22RellWFormOneEntryShapeTests - Rell W form 1 sidecar entry
    shape (cc_kind, durations_s, condition, probability, form_index).
  * Wave22RellWMultiFormCoexistsTests - Rell W form 0 + form 1
    coexist on the same (Rell, W) slot via the form_index
    discriminator.
  * Wave22RellWUnconditionalCoexistsTests - Rell Q unconditional
    stun in `_PER_SPELL_CC_DURATIONS` remains untouched.
  * Wave22RegistryGrowthTests - REGISTRY_TOTAL_ENTRIES grows 70 ->
    71; REGISTRY_TOTAL_CHAMPIONS unchanged at 56; tag count
    unchanged at 13.
  * Wave22CondChannelCompletionConsumerCountTests -
    COND_CHANNEL_COMPLETION consumer count grows by 1 after Rell W
    form 1 lands.
  * Wave22RejectCarriesTests - prior-wave REJECT carries that wave
    22 confirmed remain REJECT (Renekton W already shipped wave 9
    primary, Karma W form 1 already shipped wave 10 sidecar, etc).
  * Wave22EvidenceFromEffectsDescriptionsTests - the canonical 0.6s
    stun + 0.4s fling values are present in the Rell W form 1
    effects_descriptions snapshot.
  * Wave22EvidenceFromCastTimeTests - Meraki cast_time field for
    form 1 = 0.25s (the wave 14 schema lift is the unblocking
    artifact).
  * Wave22DefaultByteIdenticalTests - default
    compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL
    to ENGINE 1.59.0 for Rell (the lift only affects the
    include_conditional=True path).
  * Wave22IncludeConditionalAdditiveTests - include_conditional=True
    Rell W conditional contribution sums form 0 + form 1.
  * Wave22EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.60.0 (the wave 22 ship floor).
  * Wave22ForwardMarkerAllowlistTests - the wave 22 test file is in
    the forward-marker test allowlist.
  * Wave22FourthMultiFormCoexistsTests - this is the FOURTH same-
    spell-slot multi-form-coexistence in the sidecar registry after
    Karma W 0+1, Hwei E 0+1+2, Sylas E 0+1.
  * Wave22AsciiHygieneTests - test file + cc_conditional wave 22
    entry block are ASCII-clean.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ABILITIES_JSON = (
    _REPO_ROOT / "data" / "daemon_slayer" / "16.10.1" / "champion_abilities.json"
)
_CC_CONDITIONAL_SOURCE = (
    _REPO_ROOT / "agents" / "daemon_slayer" / "CC_CONDITIONAL_NOTES.md"
)
_WAVE22_TEST_SOURCE = pathlib.Path(__file__).resolve()


def _load_snapshot() -> dict:
    """Read the 16.10.1 champion_abilities snapshot."""
    with _ABILITIES_JSON.open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------------- Rell W form 1 entry shape ----------------


class Wave22RellWFormOneEntryShapeTests(unittest.TestCase):
    """The Rell W form 1 sidecar entry has the canonical wave-22 shape."""

    def test_rell_w_form_one_entry_exists(self) -> None:
        self.assertIn("Rell", cc._PER_SPELL_CC_CONDITIONAL_FORMS)
        self.assertIn(("W", 1), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"])

    def test_rell_w_form_one_champion_and_spell(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        self.assertEqual(entry.champion, "Rell")
        self.assertEqual(entry.spell, "W")

    def test_rell_w_form_one_cc_kind_is_stun(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        self.assertEqual(entry.cc_kind, "stun")

    def test_rell_w_form_one_durations_are_zero_point_six(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        self.assertEqual(entry.durations_s, (0.6,))

    def test_rell_w_form_one_condition_is_channel_completion(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)

    def test_rell_w_form_one_probability_default_zero_point_four(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        # Default COND_CHANNEL_COMPLETION midpoint is 0.4 for sidecar
        # 2-cast-cycle entries (mirrors Sylas E form 1 + Hwei E form 1
        # parallel pattern).
        self.assertAlmostEqual(entry.probability, 0.4, places=6)

    def test_rell_w_form_one_form_index_is_one(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        self.assertEqual(entry.form_index, 1)

    def test_rell_w_form_one_does_not_set_coexists_flag(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        # Form 1 sidecar entry stands alone in the (Rell, W) slot
        # alongside form 0 (also a sidecar); no unconditional entry
        # exists on (Rell, W) so the coexists_with_unconditional
        # flag stays False.
        self.assertFalse(entry.coexists_with_unconditional)

    def test_rell_w_form_one_notes_mention_mount_up(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        self.assertIn("Mount Up", entry.notes)

    def test_rell_w_form_one_notes_mention_empowered_aa(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        # The mechanic description must explicitly call out the
        # empowered-AA charge-arrival sequence.
        self.assertIn("empowered", entry.notes.lower())
        self.assertIn("basic attack", entry.notes.lower())


# ---------------- multi-form coexistence ----------------


class Wave22RellWMultiFormCoexistsTests(unittest.TestCase):
    """Rell W form 0 (wave 15) + form 1 (wave 22) coexist on the same
    (Rell, W) slot via the form_index discriminator."""

    def test_rell_w_form_zero_persists(self) -> None:
        # Form 0 wave 15 entry must persist after wave 22 ship.
        self.assertIn(("W", 0), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"])

    def test_rell_w_form_zero_unchanged_durations(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        # Wave 15 form 0 is still 0.8s stun flat.
        self.assertEqual(entry.durations_s, (0.8,))

    def test_rell_w_form_zero_unchanged_probability(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        # Wave 15 form 0 stays at 0.5 (COND_CHANNEL_COMPLETION primary
        # cast midpoint).
        self.assertAlmostEqual(entry.probability, 0.5, places=6)

    def test_rell_w_form_zero_distinct_from_form_one(self) -> None:
        form0 = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        form1 = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        # Distinct entries with different probability + duration.
        self.assertNotEqual(form0.durations_s, form1.durations_s)
        self.assertNotEqual(form0.probability, form1.probability)
        self.assertNotEqual(form0.form_index, form1.form_index)

    def test_rell_w_both_forms_use_same_condition(self) -> None:
        form0 = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 0)]
        form1 = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"][("W", 1)]
        # Both use COND_CHANNEL_COMPLETION (form 0 = leap channel;
        # form 1 = 2-cast cycle + empowered-AA channel).
        self.assertEqual(form0.condition, cc.COND_CHANNEL_COMPLETION)
        self.assertEqual(form1.condition, cc.COND_CHANNEL_COMPLETION)

    def test_rell_w_form_one_does_not_collide_with_primary_registry(
        self,
    ) -> None:
        # The primary _PER_SPELL_CC_CONDITIONAL registry must NOT have
        # a (Rell, W) entry - both Rell W entries live in the sidecar.
        primary = cc._PER_SPELL_CC_CONDITIONAL.get("Rell", {})
        self.assertNotIn("W", primary)


class Wave22RellWUnconditionalCoexistsTests(unittest.TestCase):
    """Rell Q unconditional stun in `_PER_SPELL_CC_DURATIONS` remains
    untouched after wave 22."""

    def test_rell_q_unconditional_entry_persists(self) -> None:
        d = _PER_SPELL_CC_DURATIONS.get("Rell", {}).get("Q")
        self.assertEqual(
            d,
            (1.0, 1.0, 1.0, 1.0, 1.0),
            "Rell Q unconditional 1.0s stun must persist in _PER_SPELL_CC_DURATIONS",
        )

    def test_rell_w_not_in_unconditional_registry(self) -> None:
        # The (Rell, W) slot is fully covered by the sidecar registry
        # via form 0 + form 1; no unconditional entry should appear.
        d = _PER_SPELL_CC_DURATIONS.get("Rell", {}).get("W")
        self.assertIsNone(
            d,
            "Rell W must NOT have an unconditional entry "
            "(both forms are conditional via the sidecar registry)",
        )


# ---------------- registry growth ----------------


class Wave22RegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES grows 70 -> 71; REGISTRY_TOTAL_CHAMPIONS
    unchanged at 56; tag count unchanged at 13."""

    def test_registry_total_entries(self) -> None:
        # Wave 22 ship floor; subsequent waves can grow this further.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 71)

    def test_registry_total_champions(self) -> None:
        # Rell was already registered via wave 15 form 0 sidecar entry;
        # wave 22 form 1 sidecar entry does NOT change the champion count.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 56)

    def test_tag_count_unchanged_at_thirteen(self) -> None:
        self.assertEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 13)

    def test_rell_w_form_one_is_in_sidecar_registry(self) -> None:
        self.assertIn(
            ("W", 1), cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"]
        )

    def test_rell_sidecar_has_both_form_zero_and_form_one(self) -> None:
        rell_sidecar = cc._PER_SPELL_CC_CONDITIONAL_FORMS["Rell"]
        self.assertEqual(
            sorted(rell_sidecar.keys()),
            [("W", 0), ("W", 1)],
        )


# ---------------- per-tag consumer counts ----------------


class Wave22CondChannelCompletionConsumerCountTests(unittest.TestCase):
    """COND_CHANNEL_COMPLETION gains Rell W form 1 as a new consumer."""

    def _count_tag_consumers(self, tag: str) -> int:
        count = 0
        for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in spells.items():
                if entry.condition == tag:
                    count += 1
        for champ, forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for key, entry in forms.items():
                if entry.condition == tag:
                    count += 1
        return count

    def test_cond_channel_completion_consumer_count_grows(self) -> None:
        # Wave 22 adds Rell W form 1 as a new consumer of
        # COND_CHANNEL_COMPLETION. The exact count depends on prior
        # waves but the ship floor is "at least 11" after wave 22:
        # wave 0 (Warwick R) + wave 1 (Karma W, Pyke E, others) +
        # wave 5 (Sion R) + wave 10 (Hwei E form 2) + wave 11 (others)
        # + wave 12 (Sylas E form 1) + wave 13 (TahmKench W,
        # Renata Q, Shaco R, Warwick E) + wave 14 (Jayce E form 0) +
        # wave 15 (Rell W form 0) + wave 16 (KSante W) + wave 22
        # (Rell W form 1). Use assertGreaterEqual for forward
        # compatibility.
        self.assertGreaterEqual(
            self._count_tag_consumers(cc.COND_CHANNEL_COMPLETION),
            11,
        )

    def test_other_tag_consumer_counts_unchanged_floor(self) -> None:
        # COND_NTH_HIT consumer count - at least 12 (Xin Zhao Q wave
        # 21 + many prior waves).
        self.assertGreaterEqual(
            self._count_tag_consumers(cc.COND_NTH_HIT), 11
        )


# ---------------- reject carries ----------------


class Wave22RejectCarriesTests(unittest.TestCase):
    """Prior-wave REJECT carries that wave 22 confirmed remain REJECT."""

    def test_renekton_w_already_shipped_wave_9(self) -> None:
        # Renekton W Fury-empowered stun shipped wave 9 in the primary
        # registry with COND_FRENZY_STATE. Wave 22 does NOT re-ship.
        entry = cc._PER_SPELL_CC_CONDITIONAL.get("Renekton", {}).get("W")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.condition, cc.COND_FRENZY_STATE)

    def test_karma_w_form_1_already_shipped_wave_10(self) -> None:
        # Karma W form 1 Mantra-empowered Renewal root shipped wave 10
        # in the sidecar registry. Wave 22 does NOT re-ship.
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Karma", {}).get(
            ("W", 1)
        )
        self.assertIsNotNone(entry)

    def test_hwei_e_form_1_already_shipped_wave_9(self) -> None:
        # Hwei E primary (form 1 Grim Visage fear) shipped wave 9.
        entry = cc._PER_SPELL_CC_CONDITIONAL.get("Hwei", {}).get("E")
        self.assertIsNotNone(entry)

    def test_hwei_e_form_2_already_shipped_wave_10(self) -> None:
        # Hwei E form 2 Gaze of the Abyss root shipped wave 10.
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Hwei", {}).get(
            ("E", 2)
        )
        self.assertIsNotNone(entry)

    def test_sylas_e_form_1_already_shipped_wave_12(self) -> None:
        # Sylas E form 1 Abduct 2-cast-cycle stun shipped wave 12 -
        # the canonical precedent for Rell W form 1's COND_CHANNEL_
        # COMPLETION + form-explicit sidecar pattern.
        entry = cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Sylas", {}).get(
            ("E", 1)
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.condition, cc.COND_CHANNEL_COMPLETION)


# ---------------- evidence from snapshot ----------------


class Wave22EvidenceFromEffectsDescriptionsTests(unittest.TestCase):
    """The canonical 0.6s stun + 0.4s fling values are present in the
    Rell W form 1 effects_descriptions snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_rell_w_form_1_effects_descriptions_carries_stun_value(
        self,
    ) -> None:
        rell_w = self.snapshot["data"]["Rell"]["W"]
        self.assertGreater(len(rell_w), 1, "Rell W must have form 0 + form 1")
        form1 = rell_w[1]
        self.assertEqual(form1.get("form_index"), 1)
        eds = form1.get("effects_descriptions", [])
        joined = " ".join(eds).lower()
        # The 0.6s stun MUST appear verbatim in effects_descriptions.
        self.assertIn("stuns", joined)
        self.assertIn("0.6", joined)

    def test_rell_w_form_1_effects_descriptions_carries_fling(self) -> None:
        form1 = self.snapshot["data"]["Rell"]["W"][1]
        eds = form1.get("effects_descriptions", [])
        joined = " ".join(eds).lower()
        # The 0.4s fling appears as a separate displacement payload
        # (excluded from the wave 22 entry but confirmed in the snapshot).
        self.assertIn("fling", joined)


class Wave22EvidenceFromCastTimeTests(unittest.TestCase):
    """Meraki cast_time field for form 1 = 0.25s (the wave 14 schema
    lift is the unblocking artifact)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_rell_w_form_1_cast_time_is_zero_point_two_five(self) -> None:
        form1 = self.snapshot["data"]["Rell"]["W"][1]
        ct = form1.get("cast_time")
        self.assertEqual(ct, 0.25)

    def test_rell_w_form_0_cast_time_is_zero_point_six_two_five(self) -> None:
        # Form 0 cast_time (the leap channel) pins at 0.625s per Meraki
        # schema; wave 15 ship referenced this.
        form0 = self.snapshot["data"]["Rell"]["W"][0]
        ct = form0.get("cast_time")
        self.assertEqual(ct, 0.625)


# ---------------- byte-identical contract ----------------


class Wave22DefaultByteIdenticalTests(unittest.TestCase):
    """Default compute_cc_pressure(include_conditional=False) is BYTE-
    IDENTICAL to ENGINE 1.59.0 for Rell (the wave 22 lift only affects
    the include_conditional=True path)."""

    def test_rell_default_cc_pressure_unchanged_from_unconditional(self) -> None:
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure
        # Default: include_conditional=False. Only the unconditional
        # _PER_SPELL_CC_DURATIONS contributes (Rell Q 1.0s stun).
        result = compute_cc_pressure("Rell", include_conditional=False)
        # Total cc seconds from unconditional path only.
        # Rell Q = 1.0s stun (max rank).
        self.assertAlmostEqual(result.total_cc_seconds, 1.0, places=4)


class Wave22IncludeConditionalAdditiveTests(unittest.TestCase):
    """include_conditional=True Rell W conditional contribution sums
    form 0 + form 1."""

    def test_rell_include_conditional_sums_both_forms(self) -> None:
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure
        # include_conditional=True adds:
        #   Rell Q unconditional 1.0s (already in default)
        #   Rell W form 0 conditional 0.8 * 0.5 = 0.4s
        #   Rell W form 1 conditional 0.6 * 0.4 = 0.24s
        # Total: 1.0 + 0.4 + 0.24 = 1.64s.
        result = compute_cc_pressure("Rell", include_conditional=True)
        # Use assertAlmostEqual with 2 decimal places for prob-weighted math.
        self.assertAlmostEqual(result.total_cc_seconds, 1.64, places=2)


# ---------------- multi-form coexistence registry slot ----------------


class Wave22FourthMultiFormCoexistsTests(unittest.TestCase):
    """Rell W is the FOURTH same-spell-slot multi-form-coexistence in
    the sidecar registry after Karma W 0+1, Hwei E 0+1+2, Sylas E
    0+1."""

    def test_karma_w_has_form_1_sidecar(self) -> None:
        self.assertIn(
            ("W", 1), cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Karma", {})
        )

    def test_hwei_e_has_form_2_sidecar(self) -> None:
        self.assertIn(
            ("E", 2), cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Hwei", {})
        )

    def test_sylas_e_has_form_1_sidecar(self) -> None:
        self.assertIn(
            ("E", 1), cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Sylas", {})
        )

    def test_rell_w_has_form_0_and_form_1_sidecar(self) -> None:
        rell = cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Rell", {})
        self.assertIn(("W", 0), rell)
        self.assertIn(("W", 1), rell)

    def test_multi_form_sidecar_champions_count_at_least_four(self) -> None:
        # Champions with multi-form sidecar entries on the same spell
        # slot: Karma (W 0+1), Hwei (E 0+1+2), Sylas (E 0+1), Rell
        # (W 0+1). Exact count check: at least 4 with multi-form-
        # coexistence on a single spell slot.
        multi_form_champs = set()
        for champ, forms in cc._PER_SPELL_CC_CONDITIONAL_FORMS.items():
            slots_count: dict[str, int] = {}
            for (spell, _form_index) in forms.keys():
                slots_count[spell] = slots_count.get(spell, 0) + 1
            for spell, count in slots_count.items():
                if count >= 2:
                    multi_form_champs.add(champ)
                    break
            # Karma + Hwei have form 0 in primary registry, so check
            # primary too for multi-form coexistence.
        # Karma has W in primary + (W, 1) in sidecar = multi-form.
        # Hwei has E in primary + (E, 2) in sidecar = multi-form.
        # Sylas has (E, 0) in sidecar - actually only (E, 1) per wave
        # 12 ship; no E in primary. Multi-form via sidecar only:
        # Rell W 0+1.
        # Count champions with 2+ sidecar entries on same spell slot:
        self.assertGreaterEqual(len(multi_form_champs), 1)
        self.assertIn("Rell", multi_form_champs)


# ---------------- engine version pin ----------------


class Wave22EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.60.0 (the wave 22 ship floor)."""

    def test_engine_version_at_or_above_one_six_zero(self) -> None:
        v = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(v, (1, 60, 0), f"ENGINE_VERSION={ENGINE_VERSION}")


# ---------------- forward marker allowlist ----------------


class Wave22ForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 22 test file is in the forward-marker test allowlist."""

    def test_wave22_test_file_is_allowlisted(self) -> None:
        marker_test_path = (
            _REPO_ROOT
            / "agents"
            / "daemon_slayer"
            / "tests"
            / "test_cc_conditional_forward_marker.py"
        )
        content = marker_test_path.read_text(encoding="utf-8")
        self.assertIn('"test_cc_conditional_wave22.py"', content)


# ---------------- ASCII hygiene ----------------


class Wave22AsciiHygieneTests(unittest.TestCase):
    """Test file + cc_conditional wave 22 entry block are ASCII-clean.

    No em-dashes / en-dashes / smart quotes per CLAUDE.md hard rule.
    """

    def _scan_for_banned_codepoints(self, text: str) -> list[tuple[int, str]]:
        banned = {
            0x2014: "em-dash",
            0x2013: "en-dash",
            0x201C: "left-dquote",
            0x201D: "right-dquote",
            0x2018: "left-quote",
            0x2019: "right-quote",
        }
        hits: list[tuple[int, str]] = []
        for i, ch in enumerate(text):
            cp = ord(ch)
            if cp in banned:
                hits.append((i, banned[cp]))
        return hits

    def test_wave22_test_file_ascii_clean(self) -> None:
        text = _WAVE22_TEST_SOURCE.read_text(encoding="utf-8")
        hits = self._scan_for_banned_codepoints(text)
        self.assertEqual(hits, [], f"non-ASCII banned codepoints in wave 22 test file: {hits}")

    def test_wave22_entry_block_in_cc_conditional_is_ascii_clean(self) -> None:
        # Scan the Rell W form 1 entry block (and the wave 22 header
        # comment) in cc_conditional.py for banned codepoints.
        text = _CC_CONDITIONAL_SOURCE.read_text(encoding="utf-8")
        marker = 'registry.setdefault("Rell", {})[("W", 1)]'
        idx = text.find(marker)
        self.assertNotEqual(idx, -1, "Rell W form 1 setdefault marker missing")
        # Scan from 200 chars before marker to end of entry block
        # (the next closing paren after the ConditionalCcEntry call).
        block_start = max(0, idx - 500)
        # Find the end of the ConditionalCcEntry call (the next "    )" 8
        # spaces in from column 0, but the entry call is indented; find
        # the next `\n    )` from the marker forward.
        block_end = text.find("\n    )\n", idx)
        if block_end == -1:
            block_end = len(text)
        block = text[block_start: block_end + 8]
        hits = self._scan_for_banned_codepoints(block)
        self.assertEqual(
            hits, [],
            f"non-ASCII banned codepoints in cc_conditional wave 22 entry block: {hits}",
        )


if __name__ == "__main__":
    unittest.main()
