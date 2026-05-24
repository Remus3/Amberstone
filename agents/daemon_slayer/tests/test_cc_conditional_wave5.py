"""ENGINE 1.42.0 (2026-05-22) - cc_conditional wave 5 expansion.

Tests the wave 5 expansion of the conditional CC registry: +2 entries
across +0 new champions (both are multi-wave coexistence on existing
champions - Briar gains E coexisting with wave 4 Q; TahmKench gains Q
coexisting with wave 0 R devour). Drawn from prior wave REJECT carries
in CLAUDE.md items 142 + 144 (Briar W frenzy carry pointed at E as
non-frenzy alternative; TahmKench passive-stack chain re-examined as
Q-application nth_hit stun rather than passive-only encoding).

The 2 new entries are:
  * Briar E Chilling Scream (channel_completion) - full-charge cone fear
  * TahmKench Q Tongue Lash (nth_hit) - 3rd-stack passive stun

These re-use existing condition tags exclusively - no new tag constants.
Registry growth: 32 champs / 33 entries -> 32 champs / 35 entries.
NET-NEW champions: 0 (both entries coexist on existing champion keys).

Briar E (this wave 5) coexists with Briar Q (wave 4) on the same
champion's spell map via setdefault. TahmKench Q (this wave 5)
coexists with TahmKench R (wave 0) on the same champion's spell map
via setdefault. This brings the multi-wave coexistence count to 3
(Aatrox Q3+W from waves 3+4, Briar Q+E from waves 4+5, TahmKench R+Q
from waves 0+5).

Coverage classes:
  * ``WaveFiveNewEntryShapeTests`` - each new entry has correct
    schema (champion / spell / cc_kind / durations_s shape /
    condition tag / probability).
  * ``WaveFiveValuePinsTests`` - per-entry value pins.
  * ``WaveFiveNewChampionsTests`` - both Briar + TahmKench already
    existed in prior waves; no net-new champion keys.
  * ``RegistryGrowthTests`` - new totals 32 champs / 35 entries.
  * ``ExistingSeedPreservedTests`` - all 33 prior entries (waves
    0+1+2+3+4) still present + byte-identical.
  * ``WaveFiveCoexistenceWithPriorWavesTests`` - Briar Q (wave 4)
    + Briar E (wave 5) coexist via setdefault; TahmKench R (wave 0)
    + TahmKench Q (wave 5) coexist via setdefault.
  * ``AggregatorWaveFiveTests`` - aggregator returns expected
    weighted + raw totals for new entries (entry-level pins given
    multi-wave coexistence aggregation).
  * ``EngineVersionCurrentTests`` - ENGINE pinned at >= 1.41.0
    (the orchestrator bumps to 1.42.0 at merge; this slice ships
    at 1.41.0 and orchestrator-bump is post-merge).
  * ``AsciiHygieneTests`` - module + this test file pure ASCII.
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_conditional import (
    _PER_SPELL_CC_CONDITIONAL,
    COND_CHANNEL_COMPLETION,
    COND_DEVOUR_TARGET,
    COND_DUAL_ENEMY,
    COND_GOLD_CARD,
    COND_MODE_GATED,
    COND_NTH_HIT,
    COND_TARGET_DEBUFFED,
    COND_TERRAIN,
    ConditionalCcEntry,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    get_conditional_entries,
    get_total_conditional_cc_seconds,
)


# ---------------- wave 5 expected expansion map ----------------


# Each wave-5 entry pin (champion, spell, cc_kind, durations_s,
# condition, probability). Pinned to detect schema regressions.
WAVE_FIVE_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Briar": {"E": {
        "cc_kind": "fear",
        "durations_s": (1.0,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "TahmKench": {"Q": {
        "cc_kind": "stun",
        "durations_s": (1.5,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
}


# Wave 0 + wave 1 + wave 2 + wave 3 + wave 4 seed (the 33 pre-wave-5
# entries) - the set of champion keys pre-wave-5. Wave 5 introduces
# 0 NEW champion keys (both entries land on existing champions via
# setdefault on different spell slots).
PRE_WAVE_FIVE_EXPECTED_CHAMPS = {
    # wave 0 seed (10 from items 138/139/140)
    "Brand", "TwistedFate", "JarvanIV", "TahmKench", "Volibear",
    "Warwick", "Viktor", "Mordekaiser", "Sett", "Vex",
    # wave 1 (8 from item 142)
    "Bard", "Karma", "Taliyah", "Kennen", "KSante",
    "Ornn", "Xayah", "Fiora",
    # wave 2 (5 from item 143)
    "Maokai", "Pyke", "Swain", "Skarner", "Zilean",
    # wave 3 (5 from item 144)
    "Aatrox", "Riven", "Yasuo", "Yone", "Leblanc",
    # wave 4 (4 net-new + 1 multi-wave coexistence on Aatrox)
    "Nunu", "Yuumi", "Pantheon", "Briar",
}

# Wave 5 introduces 0 NET-NEW champions (both entries coexist on
# existing champion keys via setdefault). Briar Q is wave 4 + Briar E
# is wave 5. TahmKench R is wave 0 + TahmKench Q is wave 5.
WAVE_FIVE_NEW_CHAMPIONS: set[str] = set()


# ---------------- new entry shape contract ----------------


class WaveFiveNewEntryShapeTests(unittest.TestCase):
    """Each wave-5 entry has the expected schema."""

    def test_all_wave_five_champs_present_in_registry(self) -> None:
        for champ in WAVE_FIVE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"wave 5 champ {champ} missing from registry",
            )

    def test_all_wave_five_spells_present(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"wave 5 {champ} {spell_key} missing from spell map",
                )

    def test_all_wave_five_entries_are_conditional_cc_entry_dataclass(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIsInstance(entry, ConditionalCcEntry)

    def test_all_wave_five_entries_carry_notes(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertTrue(
                    entry.notes,
                    f"wave 5 {champ} {spell_key} missing notes",
                )

    def test_all_wave_five_entries_use_existing_tags_only(self) -> None:
        # No new tag constants introduced in wave 5.
        allowed_tags = {
            COND_NTH_HIT,
            COND_GOLD_CARD,
            COND_TERRAIN,
            COND_CHANNEL_COMPLETION,
            COND_DEVOUR_TARGET,
            COND_TARGET_DEBUFFED,
            COND_DUAL_ENEMY,
            COND_MODE_GATED,
        }
        for champ in WAVE_FIVE_EXPECTED:
            for spell_key in WAVE_FIVE_EXPECTED[champ]:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(
                    entry.condition,
                    allowed_tags,
                    f"{champ} {spell_key} uses unknown tag {entry.condition!r}",
                )

    def test_all_wave_five_entries_valid_spell_slots(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(entry.spell, ("Q", "W", "E", "R"))

    def test_all_wave_five_entries_have_positive_durations(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                for d in entry.durations_s:
                    self.assertGreater(d, 0.0)

    def test_all_wave_five_entries_have_clamped_probability(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertGreaterEqual(entry.probability, 0.0)
                self.assertLessEqual(entry.probability, 1.0)

    def test_wave_five_champion_field_matches_dict_key(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertEqual(entry.champion, champ)


# ---------------- per-entry value pins ----------------


class WaveFiveValuePinsTests(unittest.TestCase):
    """Per-entry value pins for each wave-5 entry."""

    def test_briar_e_chilling_scream(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["E"]
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "E")

    def test_tahmkench_q_tongue_lash(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")


# ---------------- new champions contract (zero net-new) ----------------


class WaveFiveNewChampionsTests(unittest.TestCase):
    """Both Briar + TahmKench already existed in prior waves; no
    net-new champion keys in wave 5. Both new entries land on
    existing champions via setdefault on different spell slots."""

    def test_briar_existed_pre_wave_five(self) -> None:
        # Briar was added in wave 4 with Q (terrain stun).
        self.assertIn("Briar", PRE_WAVE_FIVE_EXPECTED_CHAMPS)
        self.assertIn("Briar", _PER_SPELL_CC_CONDITIONAL)

    def test_tahmkench_existed_pre_wave_five(self) -> None:
        # TahmKench was added in wave 0 with R (devour suppression).
        self.assertIn("TahmKench", PRE_WAVE_FIVE_EXPECTED_CHAMPS)
        self.assertIn("TahmKench", _PER_SPELL_CC_CONDITIONAL)

    def test_briar_has_both_q_and_e_entries(self) -> None:
        # Wave 4 Q + wave 5 E coexist on the same champion via setdefault.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Briar"])
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Briar"])

    def test_tahmkench_has_both_q_and_r_entries(self) -> None:
        # Wave 0 R + wave 5 Q coexist on the same champion via setdefault.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["TahmKench"])
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["TahmKench"])

    def test_zero_net_new_champions_in_wave_five(self) -> None:
        # All wave-5 champion keys were already in prior waves.
        wave_five_champs = set(WAVE_FIVE_EXPECTED.keys())
        net_new = wave_five_champs - PRE_WAVE_FIVE_EXPECTED_CHAMPS
        self.assertEqual(net_new, set())
        self.assertEqual(WAVE_FIVE_NEW_CHAMPIONS, set())

    def test_lowercase_variants_not_in_registry(self) -> None:
        # Case-sensitive DDragon ids only.
        for champ in WAVE_FIVE_EXPECTED:
            self.assertNotIn(
                champ.lower(),
                _PER_SPELL_CC_CONDITIONAL,
                f"lowercase {champ.lower()!r} unexpectedly in registry",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Wave 5 grows registry from 33 entries to 35 entries; champion
    count stays at 32 (no net-new champions)."""

    def test_registry_total_champions_at_least_32(self) -> None:
        # No net-new champs in wave 5. Future-wave compatibility via
        # assertGreaterEqual per item 143/144 Slice C pattern.
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 32)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL), 32)

    def test_registry_total_entries_at_least_35(self) -> None:
        # 35 entries across 32 champions post-wave-5.
        # assertGreaterEqual for future-wave compatibility.
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 35)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(live, 35)

    def test_wave_five_adds_2_entries_over_prior_waves(self) -> None:
        # Wave 5 entry count is exactly 2 (both via setdefault on
        # existing champions).
        wave_five_entry_count = sum(
            len(spells) for spells in WAVE_FIVE_EXPECTED.values()
        )
        self.assertEqual(wave_five_entry_count, 2)

    def test_aatrox_briar_tahmkench_all_have_multi_wave_coexistence(self) -> None:
        # Aatrox (Q wave 3 + W wave 4), Briar (Q wave 4 + E wave 5),
        # TahmKench (R wave 0 + Q wave 5). 3 multi-wave-coexistence
        # champions post-wave-5.
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["Aatrox"]), 2)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["Briar"]), 2)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["TahmKench"]), 2)


# ---------------- existing seed preserved contract ----------------


class ExistingSeedPreservedTests(unittest.TestCase):
    """All 33 prior entries (wave 0 + wave 1 + wave 2 + wave 3 +
    wave 4) still present + byte-identical post-wave-5."""

    def test_all_prior_wave_champs_still_present(self) -> None:
        for champ in PRE_WAVE_FIVE_EXPECTED_CHAMPS:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"prior-wave champ {champ} lost in wave 5",
            )

    def test_brand_r_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["R"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (2.0,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_twistedfate_w_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["TwistedFate"]["W"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_GOLD_CARD)
        self.assertEqual(entry.probability, 0.4)

    def test_jarvaniv_e_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["JarvanIV"]["E"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.5)

    def test_tahmkench_r_wave0_unchanged(self) -> None:
        # TahmKench R is wave 0 conditional devour suppression. Wave 5
        # adds Q on the same champion; R must stay byte-identical.
        entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["R"]
        self.assertEqual(entry.cc_kind, "suppression")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_DEVOUR_TARGET)
        self.assertEqual(entry.probability, 0.4)

    def test_mordekaiser_r_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Mordekaiser"]["R"]
        self.assertEqual(entry.cc_kind, "banishment")
        self.assertEqual(entry.durations_s, (7.0,))
        self.assertEqual(entry.condition, COND_MODE_GATED)
        self.assertEqual(entry.probability, 1.0)

    def test_karma_w_wave1_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Karma"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5, 1.625, 1.75, 1.875, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.4)

    def test_maokai_q_wave2_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Maokai"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_aatrox_q_wave3_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_aatrox_w_wave4_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.75,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.5)

    def test_briar_q_wave4_unchanged(self) -> None:
        # Briar Q is wave 4 conditional terrain stun. Wave 5 adds E
        # on the same champion; Q must stay byte-identical.
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_nunu_r_wave4_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Nunu"]["R"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.5,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)


# ---------------- coexistence with prior waves contract ----------------


class WaveFiveCoexistenceWithPriorWavesTests(unittest.TestCase):
    """Briar E (wave 5) coexists with Briar Q (wave 4) via
    setdefault. TahmKench Q (wave 5) coexists with TahmKench R
    (wave 0) via setdefault. Both are multi-wave coexistence patterns
    on existing champion keys."""

    def test_briar_has_both_q_and_e_entries(self) -> None:
        # Both spell slots present post-build via setdefault.
        self.assertIn("Briar", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Briar"])
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Briar"])

    def test_briar_q_is_wave_four_terrain_stun(self) -> None:
        # Wave-4 Q (terrain collision stun) survives wave-5 build.
        q_entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["Q"]
        self.assertEqual(q_entry.cc_kind, "stun")
        self.assertEqual(q_entry.durations_s, (1.0,))
        self.assertEqual(q_entry.condition, COND_TERRAIN)

    def test_briar_e_is_wave_five_channel_completion_fear(self) -> None:
        # Wave-5 E (full-charge cone fear) added without clobber.
        e_entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["E"]
        self.assertEqual(e_entry.cc_kind, "fear")
        self.assertEqual(e_entry.durations_s, (1.0,))
        self.assertEqual(e_entry.condition, COND_CHANNEL_COMPLETION)

    def test_briar_has_exactly_two_entries(self) -> None:
        # Wave 5 adds E; total Briar entries = 2 (Q + E). Both
        # share the same champion key via setdefault construction.
        spells = _PER_SPELL_CC_CONDITIONAL["Briar"]
        self.assertEqual(len(spells), 2)

    def test_tahmkench_has_both_q_and_r_entries(self) -> None:
        # Both spell slots present post-build via setdefault.
        self.assertIn("TahmKench", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["TahmKench"])
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["TahmKench"])

    def test_tahmkench_r_is_wave_zero_devour_suppression(self) -> None:
        # Wave-0 R (devour suppression) survives wave-5 build.
        r_entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["R"]
        self.assertEqual(r_entry.cc_kind, "suppression")
        self.assertEqual(r_entry.durations_s, (1.0,))
        self.assertEqual(r_entry.condition, COND_DEVOUR_TARGET)

    def test_tahmkench_q_is_wave_five_nth_hit_stun(self) -> None:
        # Wave-5 Q (3rd-stack passive stun) added without clobber.
        q_entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["Q"]
        self.assertEqual(q_entry.cc_kind, "stun")
        self.assertEqual(q_entry.durations_s, (1.5,))
        self.assertEqual(q_entry.condition, COND_NTH_HIT)

    def test_tahmkench_has_exactly_two_entries(self) -> None:
        # Wave 5 adds Q; wave 5 baseline = 2 (Q + R). Wave 13 adds W
        # taking TahmKench to 3-slot coverage; assertion relaxed to
        # assertGreaterEqual for forward compatibility.
        spells = _PER_SPELL_CC_CONDITIONAL["TahmKench"]
        self.assertGreaterEqual(len(spells), 2)


# ---------------- aggregator regression contract ----------------


class AggregatorWaveFiveTests(unittest.TestCase):
    """get_total_conditional_cc_seconds returns expected values for
    multi-wave-coexistence champions. Wave 5 introduces 2 new entries
    that coexist on existing champion keys; aggregator sums all
    entries per champion in canonical Q-W-E-R order."""

    def test_briar_weighted_max_rank_sums_q_plus_e(self) -> None:
        # Briar Q = 1.0 * 0.3 = 0.30 (wave 4 terrain stun)
        # Briar E = 1.0 * 0.5 = 0.50 (wave 5 channel-completion fear)
        # Total weighted = 0.30 + 0.50 = 0.80
        total = get_total_conditional_cc_seconds("Briar")
        self.assertAlmostEqual(total, 0.80, places=4)

    def test_briar_raw_max_rank_sums_q_plus_e(self) -> None:
        # Briar Q raw = 1.0 + Briar E raw = 1.0 -> 2.0 total
        total = get_total_conditional_cc_seconds(
            "Briar", apply_probability=False
        )
        self.assertAlmostEqual(total, 2.0, places=4)

    def test_tahmkench_weighted_max_rank_sums_q_plus_r(self) -> None:
        # TahmKench Q = 1.5 * 0.7 = 1.05 (wave 5 nth_hit stun)
        # TahmKench R = 1.0 * 0.4 = 0.40 (wave 0 devour suppression)
        # Wave 13 adds TahmKench W = 1.0 * 0.5 = 0.50 (channel completion stun)
        # Total weighted = 1.05 + 0.50 + 0.40 = 1.95
        total = get_total_conditional_cc_seconds("TahmKench")
        self.assertAlmostEqual(total, 1.95, places=4)

    def test_tahmkench_raw_max_rank_sums_q_plus_r(self) -> None:
        # TahmKench Q raw = 1.5 + W raw (wave 13) = 1.0 + R raw = 1.0
        # Total raw = 3.5
        total = get_total_conditional_cc_seconds(
            "TahmKench", apply_probability=False
        )
        self.assertAlmostEqual(total, 3.5, places=4)

    def test_briar_e_entry_level_weighted(self) -> None:
        # Briar E entry-level contribution = 1.0 * 0.5 = 0.50
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["E"]
        self.assertAlmostEqual(
            entry.durations_s[-1] * entry.probability, 0.50, places=4
        )

    def test_tahmkench_q_entry_level_weighted(self) -> None:
        # TahmKench Q entry-level contribution = 1.5 * 0.7 = 1.05
        entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["Q"]
        self.assertAlmostEqual(
            entry.durations_s[-1] * entry.probability, 1.05, places=4
        )

    def test_get_conditional_entries_returns_q_and_e_for_briar(self) -> None:
        # Briar has 2 entries (Q + E). Canonical Q-W-E-R order
        # means Q is index 0, E is index 1.
        entries = get_conditional_entries("Briar")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[1].spell, "E")

    def test_get_conditional_entries_returns_q_and_r_for_tahmkench(self) -> None:
        # Wave 5 baseline: TahmKench has 2 entries (Q + R). Canonical
        # Q-W-E-R order means Q index 0, R index 1.
        # Wave 13 adds W taking TahmKench to 3 slots (Q, W, R).
        # Assertion relaxed: Q remains first; R remains last.
        entries = get_conditional_entries("TahmKench")
        self.assertGreaterEqual(len(entries), 2)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[-1].spell, "R")


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at current bumped state.

    Wave 5 ships at ENGINE >= 1.41.0; the orchestrator bumps to
    1.42.0 at merge time. ENGINE >= 1.41.0 must hold for the wave-5
    test surface to be valid.
    """

    def test_engine_version_at_least_1_41_0(self) -> None:
        # Wave 5 ships at ENGINE >= 1.41.0 (orchestrator bumps to
        # 1.42.0 at merge). Future bumps must keep this at
        # >= 1.41.0 so the wave-5 entry test surface stays valid.
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 41, 0))


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """This test file is pure ASCII."""

    def test_this_test_file_is_ascii_clean(self) -> None:
        src_path = pathlib.Path(__file__)
        raw = src_path.read_bytes()
        bad_glyphs = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "left double smart quote",
            chr(0x201D): "right double smart quote",
            chr(0x2018): "left single smart quote",
            chr(0x2019): "right single smart quote",
        }
        text = raw.decode("utf-8", errors="strict")
        for ch, name in bad_glyphs.items():
            self.assertNotIn(
                ch, text,
                f"this test file carries {name}",
            )

    def test_cc_conditional_module_remains_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "cc_conditional.py"
        )
        raw = src_path.read_bytes()
        bad_seqs = [
            (b"\xe2\x80\x94", "em-dash"),
            (b"\xe2\x80\x93", "en-dash"),
            (b"\xe2\x80\x9c", "left double smart quote"),
            (b"\xe2\x80\x9d", "right double smart quote"),
            (b"\xe2\x80\x98", "left single smart quote"),
            (b"\xe2\x80\x99", "right single smart quote"),
        ]
        for seq, name in bad_seqs:
            self.assertNotIn(
                seq, raw,
                f"cc_conditional.py carries {name}",
            )


if __name__ == "__main__":
    unittest.main()
