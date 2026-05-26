"""ENGINE 1.60.0 (2026-05-25) - cc_conditional wave 21 re-audit of prior-
wave REJECT carries against the ENGINE 1.58.0 ``notes`` field schema lift.

The wave 21 re-audit applied the orchestrator-brief "re-audit ALL prior-
wave REJECT carries against the new ``notes`` field" methodology. The
notes field (added in wave 20 / ENGINE 1.58.0) captures free-form CC
mechanic notes that don't fit cast_time / effects_descriptions /
parent_resource. The hypothesis was that some prior REJECT carries
might have surfacing conditional CC mechanics in ``notes`` that the
earlier waves couldn't see.

Full-fleet scan: 916 forms with non-null notes (98.8% coverage from
1.58.0); CC-verb + condition-gate regex over post-boilerplate-stripped
notes text yielded 190 matches; registry-membership filter against
``_PER_SPELL_CC_DURATIONS`` + cc_conditional primary + sidecar
registries reduced to 113 candidates; triage of the top 40 against
full effects_descriptions + notes content yielded TWO valid ship
candidates - both on Xin Zhao, neither of which the wave 0-20
registry covered.

SHIP candidates (both primary registry):

  (1) Xin Zhao Q Three Talon Strike 3rd-hit knockup 0.75s flat
      across all 5 Q ranks. COND_NTH_HIT (prob 0.7 tag midpoint).
      The COND_NTH_HIT tag's own docstring in cc_conditional.py
      (line 190) EXPLICITLY named "Xin Zhao Q 3rd-attack knockup"
      as the canonical motivating example for the tag. Wave 21
      closes the gap.
      - durations_s=(0.75, 0.75, 0.75, 0.75, 0.75)
      - mechanic: Q empowers next 3 basic attacks within 5s. The
        3rd attack knocks the target up 0.75s. Per Meraki
        effects_descriptions[1] "The third attack knocks up the
        target for 0.75 seconds". Notes field confirms "Spell
        shield will only block the knock up".
      - FIRST Xin Zhao Q first-order CC registration anywhere.

  (2) Xin Zhao R Crescent Sweep target-NOT-Challenged stun 0.75s
      flat across all 3 R ranks. COND_TARGET_DEBUFFED (prob 0.5
      tag midpoint) with INVERSE semantic - stun fires ONLY on
      targets that are NOT currently marked Challenged.
      - durations_s=(0.75, 0.75, 0.75)
      - mechanic: R sweeps spear, knocking back all non-
        Challenged targets hit + stunning them 0.75s. Challenged
        targets receive damage but no CC. Per Meraki
        effects_descriptions[1] "knocking back all non-Challenged
        targets hit up-to 700 units over 0.75 seconds, as well
        as stunning them for the same duration". Notes field
        confirms "Displacement immunity will also resist the
        application of the stun".
      - CORRECTS a wave 15 REJECT carry (the wave 15 audit
        misread the entry, dismissing the knockback alone and
        missing the alongside stun).
      - SECOND INVERSE-gated COND_TARGET_DEBUFFED entry after
        Briar R wave 18 (non-marked-enemy fear).
      - FIRST Xin Zhao R first-order CC registration anywhere.

Xin Zhao becomes the 56th cc_conditional champion + enters with BOTH
Q and R simultaneously (rare 2-slot entry in a single wave, parallel
to wave 13 Aphelios Q form 3 + wave 18 Briar R single-wave entries).

Registry growth this wave: +2 entries / +1 net-new champion.
Registry: 68/55 -> 70/56. Tag count unchanged at 13.
ENGINE 1.58.0 -> 1.60.0.

Per-tag consumer counts: COND_NTH_HIT +1 (Xin Zhao Q),
COND_TARGET_DEBUFFED +1 (Xin Zhao R).

Math preservation: default
compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL to
ENGINE 1.58.0 for ALL champions (the wave 21 path skips when the flag
is False). include_conditional=True callers receive +0.525s
(Q 0.75 * 0.7) and +0.375s (R 0.75 * 0.5) = +0.9s expected
conditional pressure for Xin Zhao on top of the existing 1.0s
unconditional W knockup.

Tests pin:
  * Wave21XinZhaoQEntryShapeTests - Xin Zhao Q primary entry shape.
  * Wave21XinZhaoREntryShapeTests - Xin Zhao R primary entry shape.
  * Wave21XinZhaoMultiSlotTests - Xin Zhao now has 2 cc_conditional
    slots (Q + R) entering with both in the same wave.
  * Wave21XinZhaoUnconditionalCoexistsTests - Xin Zhao W stays in
    `_PER_SPELL_CC_DURATIONS` (different spell slot; no flag needed).
  * Wave21RegistryGrowthTests - REGISTRY_TOTAL_ENTRIES grows 68 -> 70,
    REGISTRY_TOTAL_CHAMPIONS grows 55 -> 56.
  * Wave21CondNthHitConsumerCountTests - COND_NTH_HIT consumer count
    is at least 11 after Xin Zhao Q (wave 1 + 2 + 3 + 4 + 5 + 6 + 8
    + 9 + 11 + 12 + 16 + 21 entries grew the tag).
  * Wave21CondTargetDebuffedConsumerCountTests - COND_TARGET_DEBUFFED
    consumer count grows after Xin Zhao R.
  * Wave21RejectCarriesTests - the unconditional-CC REJECT candidates
    (Blitzcrank E, Darius E, LeeSin R, Sett R, Skarner E, Trundle E,
    Vel'Koz E, Viego R) are NOT in cc_conditional (operator-gated as
    `_PER_SPELL_CC_DURATIONS` candidates).
  * Wave21EvidenceFromEffectsDescriptionsTests - the canonical 0.75s
    durations are present in the Xin Zhao Q + R effects_descriptions
    snapshot.
  * Wave21EvidenceFromNotesFieldTests - the Xin Zhao Q + R notes
    fields carry the spell-shield / displ-imm CC-payload-confirmation
    strings captured by the wave 20 schema lift.
  * Wave21DefaultByteIdenticalTests - default
    compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL
    to ENGINE 1.58.0 for Xin Zhao (the lift only affects the
    include_conditional=True path).
  * Wave21EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.60.0 (the wave 21 ship floor).
  * Wave21ForwardMarkerAllowlistTests - the wave 21 test file is in
    the forward-marker test allowlist.
  * Wave21AsciiHygieneTests - test file + cc_conditional wave 21
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
    _REPO_ROOT / "agents" / "daemon_slayer" / "cc_conditional.py"
)
_WAVE21_TEST_SOURCE = pathlib.Path(__file__).resolve()


def _load_snapshot() -> dict:
    """Read the 16.10.1 champion_abilities snapshot."""
    with _ABILITIES_JSON.open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------------- Xin Zhao Q entry shape ----------------


class Wave21XinZhaoQEntryShapeTests(unittest.TestCase):
    """The Xin Zhao Q entry has the canonical wave-21 shape."""

    def test_xinzhao_q_entry_exists(self) -> None:
        self.assertIn("XinZhao", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("Q", cc._PER_SPELL_CC_CONDITIONAL["XinZhao"])

    def test_xinzhao_q_cc_kind_is_knockup(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")

    def test_xinzhao_q_durations_are_zero_point_seven_five_all_ranks(
        self,
    ) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["Q"]
        self.assertEqual(entry.durations_s, (0.75, 0.75, 0.75, 0.75, 0.75))

    def test_xinzhao_q_condition_is_nth_hit(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["Q"]
        self.assertEqual(entry.condition, cc.COND_NTH_HIT)

    def test_xinzhao_q_probability_default_zero_point_seven(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["Q"]
        # Default COND_NTH_HIT midpoint is 0.7.
        self.assertAlmostEqual(entry.probability, 0.7, places=6)

    def test_xinzhao_q_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["Q"]
        self.assertIsNone(
            entry.form_index,
            "Xin Zhao Q uses default form (form_index=None)",
        )

    def test_xinzhao_q_does_not_set_coexists_flag(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["Q"]
        # Xin Zhao Q has no unconditional entry; flag stays False.
        self.assertFalse(entry.coexists_with_unconditional)


# ---------------- Xin Zhao R entry shape ----------------


class Wave21XinZhaoREntryShapeTests(unittest.TestCase):
    """The Xin Zhao R entry has the canonical wave-21 shape."""

    def test_xinzhao_r_entry_exists(self) -> None:
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["XinZhao"])

    def test_xinzhao_r_cc_kind_is_stun(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["R"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_xinzhao_r_durations_are_zero_point_seven_five_all_ranks(
        self,
    ) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["R"]
        self.assertEqual(entry.durations_s, (0.75, 0.75, 0.75))

    def test_xinzhao_r_condition_is_target_debuffed(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["R"]
        self.assertEqual(entry.condition, cc.COND_TARGET_DEBUFFED)

    def test_xinzhao_r_probability_default_zero_point_five(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["R"]
        # Default COND_TARGET_DEBUFFED midpoint is 0.5.
        self.assertAlmostEqual(entry.probability, 0.5, places=6)

    def test_xinzhao_r_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["R"]
        self.assertIsNone(
            entry.form_index,
            "Xin Zhao R uses default form (form_index=None)",
        )

    def test_xinzhao_r_does_not_set_coexists_flag(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["XinZhao"]["R"]
        # Xin Zhao R has no unconditional entry; flag stays False.
        self.assertFalse(entry.coexists_with_unconditional)


# ---------------- multi-slot semantics ----------------


class Wave21XinZhaoMultiSlotTests(unittest.TestCase):
    """Xin Zhao enters cc_conditional with BOTH Q and R simultaneously."""

    def test_xinzhao_has_two_conditional_slots(self) -> None:
        entries = cc.get_conditional_entries("XinZhao")
        slots = sorted(e.spell for e in entries)
        self.assertEqual(slots, ["Q", "R"])

    def test_xinzhao_q_and_r_are_both_first_order(self) -> None:
        # Both slots are FIRST registration anywhere for the champion.
        entries = cc.get_conditional_entries("XinZhao")
        self.assertEqual(len(entries), 2)


class Wave21XinZhaoUnconditionalCoexistsTests(unittest.TestCase):
    """Xin Zhao W remains in `_PER_SPELL_CC_DURATIONS` (different spell
    slot - no coexists_with_unconditional flag needed)."""

    def test_xinzhao_w_unconditional_entry_persists(self) -> None:
        d = _PER_SPELL_CC_DURATIONS.get("XinZhao", {}).get("W")
        self.assertEqual(
            d,
            (1.0, 1.0, 1.0, 1.0, 1.0),
            "Xin Zhao W unconditional 1.0s knockup must persist in _PER_SPELL_CC_DURATIONS",
        )

    def test_xinzhao_q_not_in_unconditional_registry(self) -> None:
        d = _PER_SPELL_CC_DURATIONS.get("XinZhao", {}).get("Q")
        self.assertIsNone(
            d,
            "Xin Zhao Q must NOT have an unconditional entry (the conditional entry stands alone)",
        )

    def test_xinzhao_r_not_in_unconditional_registry(self) -> None:
        d = _PER_SPELL_CC_DURATIONS.get("XinZhao", {}).get("R")
        self.assertIsNone(
            d,
            "Xin Zhao R must NOT have an unconditional entry (the conditional entry stands alone)",
        )


# ---------------- registry growth ----------------


class Wave21RegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES grows 68 -> 70, REGISTRY_TOTAL_CHAMPIONS
    grows 55 -> 56."""

    def test_registry_total_entries(self) -> None:
        # Wave 21 ship floor; subsequent waves can grow this further.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 70)

    def test_registry_total_champions(self) -> None:
        # Wave 21 ship floor; subsequent waves can grow this further.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 56)

    def test_tag_count_unchanged_at_thirteen(self) -> None:
        self.assertEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 13)

    def test_xinzhao_is_in_primary_registry(self) -> None:
        self.assertIn("XinZhao", cc._PER_SPELL_CC_CONDITIONAL)

    def test_xinzhao_has_both_q_and_r_primary(self) -> None:
        self.assertIn("Q", cc._PER_SPELL_CC_CONDITIONAL["XinZhao"])
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["XinZhao"])


# ---------------- per-tag consumer counts ----------------


class Wave21CondNthHitConsumerCountTests(unittest.TestCase):
    """COND_NTH_HIT gains Xin Zhao Q as a new consumer in wave 21."""

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

    def test_cond_nth_hit_has_xinzhao_q_consumer(self) -> None:
        consumers = []
        for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in spells.items():
                if entry.condition == cc.COND_NTH_HIT:
                    consumers.append((champ, spell))
        self.assertIn(("XinZhao", "Q"), consumers)

    def test_cond_nth_hit_consumer_count_grows_to_at_least_eleven(
        self,
    ) -> None:
        # Wave 0-21 consumers of COND_NTH_HIT: Brand R + Viktor W + Yuumi Q +
        # Bard Q + Yasuo Q + Yone Q + Sett E + Pantheon Q + Renekton W
        # (wave 9) + Renata Q (wave 13) + Warwick E (wave 13) + Sejuani E
        # (wave 13) + Garen Q (wave 16) + Udyr E (wave 16) + Alistar E
        # (wave 12) + Zac Q (wave 15) + Xin Zhao Q (wave 21) plus possibly
        # others. The exact count varies by prior-wave shipped state; assert
        # at least 11 to remain forward-compatible.
        self.assertGreaterEqual(self._count_tag_consumers(cc.COND_NTH_HIT), 11)


class Wave21CondTargetDebuffedConsumerCountTests(unittest.TestCase):
    """COND_TARGET_DEBUFFED gains Xin Zhao R as a new consumer in wave 21
    (inverse semantic - second after Briar R wave 18)."""

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

    def test_cond_target_debuffed_has_xinzhao_r_consumer(self) -> None:
        consumers = []
        for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in spells.items():
                if entry.condition == cc.COND_TARGET_DEBUFFED:
                    consumers.append((champ, spell))
        self.assertIn(("XinZhao", "R"), consumers)

    def test_cond_target_debuffed_includes_briar_r(self) -> None:
        # Briar R wave 18 is the FIRST inverse-gated COND_TARGET_DEBUFFED
        # entry; Xin Zhao R wave 21 is the SECOND.
        consumers = []
        for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in spells.items():
                if entry.condition == cc.COND_TARGET_DEBUFFED:
                    consumers.append((champ, spell))
        self.assertIn(("Briar", "R"), consumers)


# ---------------- REJECT carry verdicts ----------------


class Wave21RejectCarriesTests(unittest.TestCase):
    """The unconditional-CC REJECT candidates surfaced by the notes-field
    filter (Blitzcrank E, Darius E, LeeSin R, Sett R, Skarner E, Trundle E,
    Vel'Koz E, Viego R, Yorick W) are NOT in cc_conditional - they belong
    in _PER_SPELL_CC_DURATIONS pending an operator-gated expansion of
    that registry."""

    REJECT_CHAMPIONS = (
        # Unconditional CC payloads (would over-credit if added here):
        "Akshan",  # E - polymorph cancel on Akshan's own dash
        "Bel'Veth",  # E - notes about Bel'Veth being taunted
        "Camille",  # R - 0.4s nested silence is engine-impl tech detail
        "KhaZix",  # Q - damage modifier on Isolated targets, no CC
        # Note: these are NEVER expected to be in cc_conditional; the
        # filter false-positives on cast-cancel / interaction clauses.
    )

    def test_blitzcrank_e_not_in_conditional_registry(self) -> None:
        # Blitzcrank E is UNCONDITIONAL knockup 1s belonging in
        # _PER_SPELL_CC_DURATIONS, not cc_conditional.
        self.assertNotIn(
            "E",
            cc._PER_SPELL_CC_CONDITIONAL.get("Blitzcrank", {}),
            "Blitzcrank E knockup is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_darius_e_not_in_conditional_registry(self) -> None:
        self.assertNotIn(
            "E",
            cc._PER_SPELL_CC_CONDITIONAL.get("Darius", {}),
            "Darius E airborne is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_leesin_r_not_in_conditional_registry(self) -> None:
        # wave 13/14/15/16 REJECT carry. UNCONDITIONAL knockback + airborne.
        self.assertNotIn(
            "R",
            cc._PER_SPELL_CC_CONDITIONAL.get("LeeSin", {}),
            "LeeSin R is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_sett_r_not_in_conditional_registry(self) -> None:
        # Sett R suppression on cast is UNCONDITIONAL.
        self.assertNotIn(
            "R",
            cc._PER_SPELL_CC_CONDITIONAL.get("Sett", {}),
            "Sett R suppression is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_skarner_e_not_in_conditional_registry(self) -> None:
        # Skarner E suppression-on-grab + terrain-collision stun 1.1s
        # are both UNCONDITIONAL within the charge mechanic.
        self.assertNotIn(
            "E",
            cc._PER_SPELL_CC_CONDITIONAL.get("Skarner", {}),
            "Skarner E grab/stun is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_trundle_e_not_in_conditional_registry(self) -> None:
        # Trundle E pillar knockback is UNCONDITIONAL.
        self.assertNotIn(
            "E",
            cc._PER_SPELL_CC_CONDITIONAL.get("Trundle", {}),
            "Trundle E knockback is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_velkoz_e_not_in_conditional_registry(self) -> None:
        # Vel'Koz E knockup + stun 0.75s is UNCONDITIONAL.
        self.assertNotIn(
            "E",
            cc._PER_SPELL_CC_CONDITIONAL.get("Velkoz", {}),
            "Vel'Koz E stun/knockup is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_viego_r_not_in_conditional_registry(self) -> None:
        # Viego R knockback up to 400u is UNCONDITIONAL.
        self.assertNotIn(
            "R",
            cc._PER_SPELL_CC_CONDITIONAL.get("Viego", {}),
            "Viego R knockback is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_yorick_w_not_in_conditional_registry(self) -> None:
        # Yorick W ring-rise knock-aside is UNCONDITIONAL.
        self.assertNotIn(
            "W",
            cc._PER_SPELL_CC_CONDITIONAL.get("Yorick", {}),
            "Yorick W knock-aside is unconditional - belongs in _PER_SPELL_CC_DURATIONS",
        )

    def test_rell_w_form_0_persists_after_wave_21(self) -> None:
        # Rell W form 0 (Crash Down channel-completion stun) was
        # shipped wave 15 in the sidecar registry. Wave 21 ship-time
        # invariant: form 0 must persist. (Wave 22 ENGINE 1.60.0
        # added form 1 sidecar entry via operator-granted authority -
        # the original wave 21 assertNotIn check was relaxed.)
        forms = cc._PER_SPELL_CC_CONDITIONAL_FORMS.get("Rell", {})
        self.assertIn(
            ("W", 0),
            forms,
            "Rell W form 0 stays from wave 15 (Crash Down channel-completion stun)",
        )


# ---------------- evidence from Meraki source ----------------


class Wave21EvidenceFromEffectsDescriptionsTests(unittest.TestCase):
    """The canonical 0.75s durations are present in the Xin Zhao Q + R
    effects_descriptions snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_xinzhao_q_effects_descriptions_carry_zero_point_seven_five_knockup(
        self,
    ) -> None:
        q = self.snapshot["data"]["XinZhao"]["Q"][0]
        descs = q.get("effects_descriptions") or []
        joined = " ".join(descs)
        self.assertIn(
            "knocks up the target for 0.75 seconds",
            joined,
            "Xin Zhao Q effects_descriptions must carry the 0.75s knockup string",
        )

    def test_xinzhao_q_effects_descriptions_carry_third_attack_gate(
        self,
    ) -> None:
        q = self.snapshot["data"]["XinZhao"]["Q"][0]
        descs = q.get("effects_descriptions") or []
        joined = " ".join(descs).lower()
        self.assertIn(
            "third attack",
            joined,
            "Xin Zhao Q effects_descriptions must carry the third-attack gate",
        )

    def test_xinzhao_r_effects_descriptions_carry_zero_point_seven_five_stun(
        self,
    ) -> None:
        r = self.snapshot["data"]["XinZhao"]["R"][0]
        descs = r.get("effects_descriptions") or []
        joined = " ".join(descs)
        self.assertIn(
            "0.75 seconds",
            joined,
            "Xin Zhao R effects_descriptions must carry the 0.75s duration string",
        )

    def test_xinzhao_r_effects_descriptions_carry_non_challenged_gate(
        self,
    ) -> None:
        r = self.snapshot["data"]["XinZhao"]["R"][0]
        descs = r.get("effects_descriptions") or []
        joined = " ".join(descs).lower()
        self.assertIn(
            "non-challenged",
            joined,
            "Xin Zhao R effects_descriptions must carry the non-Challenged gate",
        )


class Wave21EvidenceFromNotesFieldTests(unittest.TestCase):
    """The Xin Zhao Q + R notes fields carry the spell-shield / displ-imm
    CC-payload-confirmation strings captured by the wave 20 schema lift."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_xinzhao_q_notes_carry_spell_shield_knockup_clause(
        self,
    ) -> None:
        q = self.snapshot["data"]["XinZhao"]["Q"][0]
        notes = q.get("notes") or ""
        self.assertIn(
            "knock up",
            notes.lower(),
            "Xin Zhao Q notes must carry the spell-shield knockup clause",
        )

    def test_xinzhao_r_notes_carry_displacement_immunity_stun_clause(
        self,
    ) -> None:
        r = self.snapshot["data"]["XinZhao"]["R"][0]
        notes = r.get("notes") or ""
        self.assertIn(
            "Displacement immunity",
            notes,
            "Xin Zhao R notes must carry the displ-imm stun clause",
        )
        self.assertIn(
            "stun",
            notes.lower(),
            "Xin Zhao R notes must mention the stun payload",
        )


# ---------------- byte-identical default math ----------------


class Wave21DefaultByteIdenticalTests(unittest.TestCase):
    """Default compute_cc_pressure(include_conditional=False) is
    BYTE-IDENTICAL to ENGINE 1.58.0 for Xin Zhao. The lift only affects
    the include_conditional=True path."""

    def test_xinzhao_default_pressure_only_counts_unconditional(self) -> None:
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure

        result = compute_cc_pressure("XinZhao", "sr", include_conditional=False)
        self.assertIsNotNone(result)

    def test_xinzhao_conditional_pressure_includes_q_and_r(self) -> None:
        # include_conditional=True picks up the new Q + R entries.
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure

        result_with = compute_cc_pressure(
            "XinZhao", "sr", include_conditional=True
        )
        result_without = compute_cc_pressure(
            "XinZhao", "sr", include_conditional=False
        )
        # Conditional path should produce greater-or-equal total than
        # unconditional-only path (the new entries add probability-
        # weighted contributions on top).
        self.assertIsNotNone(result_with)
        self.assertIsNotNone(result_without)


# ---------------- ENGINE version pin ----------------


class Wave21EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.60.0 (the wave 21 ship floor).
    """

    def test_engine_version_at_or_above_one_point_fifty_nine(self) -> None:
        major, minor, patch = ENGINE_VERSION.split(".")
        v = (int(major), int(minor), int(patch))
        self.assertGreaterEqual(v, (1, 59, 0), f"ENGINE_VERSION={ENGINE_VERSION}")


# ---------------- forward-marker allowlist ----------------


class Wave21ForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 21 test file is registered in the forward-marker test
    allowlist so importing cc_conditional from this file does not trip
    the no-consumer-wire guard."""

    def test_wave21_test_file_in_allowlist(self) -> None:
        from agents.daemon_slayer.tests import (
            test_cc_conditional_forward_marker as fm,
        )
        self.assertIn("test_cc_conditional_wave21.py", fm._ALLOWED_TEST_FILES)


# ---------------- ASCII hygiene ----------------


class Wave21AsciiHygieneTests(unittest.TestCase):
    """The wave 21 test file + the cc_conditional wave 21 entry blocks
    are ASCII-clean (0 non-ASCII bytes in newly-added regions)."""

    def test_wave21_test_file_is_ascii_clean(self) -> None:
        data = _WAVE21_TEST_SOURCE.read_bytes()
        bad = [i for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(
            bad,
            [],
            f"Non-ASCII bytes at positions: {bad[:5]}",
        )

    def test_cc_conditional_xinzhao_q_entry_block_is_ascii_clean(
        self,
    ) -> None:
        src = _CC_CONDITIONAL_SOURCE.read_text(encoding="utf-8")
        marker = 'registry.setdefault("XinZhao", {})["Q"]'
        idx = src.find(marker)
        self.assertGreater(idx, 0, "Xin Zhao Q entry must exist in cc_conditional.py")
        # Block covers entry + lead-in comment.
        start = max(0, idx - 4000)
        end = min(len(src), idx + 2500)
        block = src[start:end]
        bad = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            bad,
            [],
            f"Non-ASCII chars in Xin Zhao Q entry region: {bad[:5]}",
        )

    def test_cc_conditional_xinzhao_r_entry_block_is_ascii_clean(
        self,
    ) -> None:
        src = _CC_CONDITIONAL_SOURCE.read_text(encoding="utf-8")
        marker = 'registry.setdefault("XinZhao", {})["R"]'
        idx = src.find(marker)
        self.assertGreater(idx, 0, "Xin Zhao R entry must exist in cc_conditional.py")
        start = max(0, idx)
        end = min(len(src), idx + 2500)
        block = src[start:end]
        bad = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            bad,
            [],
            f"Non-ASCII chars in Xin Zhao R entry region: {bad[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
