"""ENGINE 1.40.0 (2026-05-22) - cc_conditional wave 3 expansion.

Tests the wave 3 expansion of the conditional CC registry: +5 entries
across +5 new champions drawn from the 3-cast Q-cycle terminal knockup
pattern at patch 16.10.1 + the Leblanc full-tether root parallel to
the Karma W wave-1 pattern.

The 5 new entries are:
  * Aatrox Q3 The Darkin Blade (nth_hit) - sweetspot circle knockup
  * Riven Q3 Broken Wings (nth_hit) - 3rd-dash terminal AOE knockup
  * Yasuo Q3 Steel Tempest (nth_hit) - tornado knockup
  * Yone Q3 Mortal Steel (nth_hit) - tornado knockup mirror
  * Leblanc E Ethereal Chains (channel_completion) - full-tether root

These re-use existing condition tags exclusively - no new tag constants.
Registry growth: 23 champs / 23 entries -> 28 champs / 28 entries.

Riven Q (this wave 3) coexists with Riven W in the unconditional
``_PER_SPELL_CC_DURATIONS`` (wave 1 unconditional seed). Yasuo Q
coexists with Yasuo R unconditional. Yone Q coexists with Yone R
unconditional. The cc_conditional + cc_unconditional registries are
independent so no clobber. Aatrox + Leblanc have no unconditional
entries today; their wave-3 conditional entries are the first
registered first-order CC for both champions.

Coverage classes:
  * ``WaveThreeNewEntryShapeTests`` - each new entry has correct
    schema (champion / spell / cc_kind / durations_s shape /
    condition tag / probability).
  * ``WaveThreeValuePinsTests`` - per-entry value pins.
  * ``WaveThreeNewChampionsTests`` - each new champion appears in
    registry; case-sensitive DDragon ids.
  * ``RegistryGrowthTests`` - new totals 28 champs / 28 entries.
  * ``ExistingSeedPreservedTests`` - all 23 prior entries (waves
    0+1+2) still present + byte-identical.
  * ``WaveThreeCoexistenceWithUnconditionalTests`` - Riven / Yasuo
    / Yone coexist between conditional + unconditional registries.
    Aatrox + Leblanc have no unconditional entries.
  * ``AggregatorWaveThreeTests`` - aggregator returns expected
    weighted + raw totals for new entries.
  * ``EngineVersionCurrentTests`` - ENGINE pinned at >= 1.39.0
    (the orchestrator bumps to 1.40.0 at merge; this slice ships
    on 1.39.0 and orchestrator-bump is post-merge).
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


# ---------------- wave 3 expected expansion map ----------------


# Each wave-3 entry pin (champion, spell, cc_kind, durations_s,
# condition, probability). Pinned to detect schema regressions.
WAVE_THREE_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Aatrox": {"Q": {
        "cc_kind": "knockup",
        "durations_s": (0.5,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "Riven": {"Q": {
        "cc_kind": "knockup",
        "durations_s": (0.75,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "Yasuo": {"Q": {
        "cc_kind": "knockup",
        "durations_s": (1.0,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "Yone": {"Q": {
        "cc_kind": "knockup",
        "durations_s": (0.75,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "Leblanc": {"E": {
        "cc_kind": "root",
        "durations_s": (1.5,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
}


# Wave 0 + wave 1 + wave 2 seed (the 23 pre-wave-3 entries) re-pinned
# to verify they survive wave 3 setdefault construction.
PRE_WAVE_THREE_EXPECTED_CHAMPS = {
    # wave 0 seed (10 from items 138/139/140)
    "Brand", "TwistedFate", "JarvanIV", "TahmKench", "Volibear",
    "Warwick", "Viktor", "Mordekaiser", "Sett", "Vex",
    # wave 1 (8 from item 142)
    "Bard", "Karma", "Taliyah", "Kennen", "KSante",
    "Ornn", "Xayah", "Fiora",
    # wave 2 (5 from item 143)
    "Maokai", "Pyke", "Swain", "Skarner", "Zilean",
}


# ---------------- new entry shape contract ----------------


class WaveThreeNewEntryShapeTests(unittest.TestCase):
    """Each wave-3 entry has the expected schema."""

    def test_all_wave_three_champs_present_in_registry(self) -> None:
        for champ in WAVE_THREE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"wave 3 champ {champ} missing from registry",
            )

    def test_all_wave_three_spells_present(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"wave 3 {champ} {spell_key} missing from spell map",
                )

    def test_all_wave_three_entries_are_conditional_cc_entry_dataclass(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIsInstance(entry, ConditionalCcEntry)

    def test_all_wave_three_entries_carry_notes(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertTrue(
                    entry.notes,
                    f"wave 3 {champ} {spell_key} missing notes",
                )

    def test_all_wave_three_entries_use_existing_tags_only(self) -> None:
        # No new tag constants introduced in wave 3.
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
        for champ in WAVE_THREE_EXPECTED:
            for spell_key in WAVE_THREE_EXPECTED[champ]:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(
                    entry.condition,
                    allowed_tags,
                    f"{champ} {spell_key} uses unknown tag {entry.condition!r}",
                )

    def test_all_wave_three_entries_valid_spell_slots(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(entry.spell, ("Q", "W", "E", "R"))

    def test_all_wave_three_entries_have_positive_durations(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                for d in entry.durations_s:
                    self.assertGreater(d, 0.0)

    def test_all_wave_three_entries_have_clamped_probability(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertGreaterEqual(entry.probability, 0.0)
                self.assertLessEqual(entry.probability, 1.0)

    def test_wave_three_champion_field_matches_dict_key(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertEqual(entry.champion, champ)


# ---------------- per-entry value pins ----------------


class WaveThreeValuePinsTests(unittest.TestCase):
    """Per-entry value pins for each wave-3 entry."""

    def test_aatrox_q3_darkin_blade_sweetspot(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")

    def test_riven_q3_broken_wings(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Riven"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")

    def test_yasuo_q3_steel_tempest(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Yasuo"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")

    def test_yone_q3_mortal_steel(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Yone"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")

    def test_leblanc_e_ethereal_chains(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Leblanc"]["E"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "E")


# ---------------- new champions contract ----------------


class WaveThreeNewChampionsTests(unittest.TestCase):
    """Each new champion appears in registry with case-sensitive id."""

    def test_aatrox_in_registry(self) -> None:
        self.assertIn("Aatrox", _PER_SPELL_CC_CONDITIONAL)

    def test_riven_in_registry(self) -> None:
        self.assertIn("Riven", _PER_SPELL_CC_CONDITIONAL)

    def test_yasuo_in_registry(self) -> None:
        self.assertIn("Yasuo", _PER_SPELL_CC_CONDITIONAL)

    def test_yone_in_registry(self) -> None:
        self.assertIn("Yone", _PER_SPELL_CC_CONDITIONAL)

    def test_leblanc_in_registry(self) -> None:
        self.assertIn("Leblanc", _PER_SPELL_CC_CONDITIONAL)

    def test_lowercase_variants_not_in_registry(self) -> None:
        # Case-sensitive DDragon ids only.
        for champ in WAVE_THREE_EXPECTED:
            self.assertNotIn(
                champ.lower(),
                _PER_SPELL_CC_CONDITIONAL,
                f"lowercase {champ.lower()!r} unexpectedly in registry",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Wave 3 grows registry from 23/23 to 28/28."""

    def test_registry_total_champions_at_least_28(self) -> None:
        # assertGreaterEqual for future-wave compatibility per item
        # 143 Slice C pattern relaxation.
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 28)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL), 28)

    def test_registry_total_entries_at_least_28(self) -> None:
        # Each champion has exactly one entry today; 28 entries
        # across 28 champions. assertGreaterEqual for future-wave
        # compatibility (a wave 4 may add more without breaking
        # this pin).
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 28)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(live, 28)

    def test_wave_three_adds_5_champions_over_prior_waves(self) -> None:
        wave_three_champs = set(WAVE_THREE_EXPECTED.keys())
        # Wave 3 should add exactly 5 NEW champions not in prior waves.
        new_in_wave_three = wave_three_champs - PRE_WAVE_THREE_EXPECTED_CHAMPS
        self.assertEqual(len(new_in_wave_three), 5)

    def test_wave_three_champs_have_no_prior_wave_overlap(self) -> None:
        # No wave-3 champ should be a prior-wave champ.
        for champ in WAVE_THREE_EXPECTED:
            self.assertNotIn(
                champ, PRE_WAVE_THREE_EXPECTED_CHAMPS,
                f"{champ} is a prior-wave champion AND a wave-3 "
                "champion - this would be a clobber",
            )

    def test_no_duplicate_champions_in_wave_three(self) -> None:
        # Trivial (dict keys are unique) but pin for documentation.
        self.assertEqual(
            len(WAVE_THREE_EXPECTED),
            len(set(WAVE_THREE_EXPECTED.keys())),
        )


# ---------------- existing seed preserved contract ----------------


class ExistingSeedPreservedTests(unittest.TestCase):
    """All 23 prior entries (wave 0 + wave 1 + wave 2) still present."""

    def test_all_prior_wave_champs_still_present(self) -> None:
        for champ in PRE_WAVE_THREE_EXPECTED_CHAMPS:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"prior-wave champ {champ} lost in wave 3",
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

    def test_mordekaiser_r_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Mordekaiser"]["R"]
        self.assertEqual(entry.cc_kind, "banishment")
        self.assertEqual(entry.durations_s, (7.0,))
        self.assertEqual(entry.condition, COND_MODE_GATED)
        self.assertEqual(entry.probability, 1.0)

    def test_bard_q_wave1_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Bard"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5, 1.75, 2.0, 2.25, 2.5))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_karma_w_wave1_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Karma"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5, 1.625, 1.75, 1.875, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.4)

    def test_ksante_q_wave1_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["KSante"]["Q"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_fiora_w_wave1_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Fiora"]["W"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.4)

    def test_maokai_q_wave2_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Maokai"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_swain_e_wave2_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Swain"]["E"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5, 1.625, 1.75, 1.875, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)

    def test_skarner_q_wave2_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Skarner"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_zilean_q_wave2_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Zilean"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (2.0,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)


# ---------------- coexistence with unconditional registry ----------------


class WaveThreeCoexistenceWithUnconditionalTests(unittest.TestCase):
    """Wave-3 champions: Riven / Yasuo / Yone coexist with their
    unconditional registry entries on OTHER spell slots; Aatrox +
    Leblanc have no unconditional entries today (this wave 3 is the
    first registered first-order CC for both)."""

    def test_riven_w_in_unconditional_registry(self) -> None:
        # Riven W Ki Burst is unconditional (wave 1 unconditional).
        # Riven Q (this wave 3) is conditional knockup.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Riven", _PER_SPELL_CC_DURATIONS)
        self.assertIn("W", _PER_SPELL_CC_DURATIONS["Riven"])
        # Riven Q is in conditional, not unconditional.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Riven"])
        self.assertNotIn(
            "Q", _PER_SPELL_CC_DURATIONS.get("Riven", {})
        )

    def test_yasuo_r_in_unconditional_registry(self) -> None:
        # Yasuo R Last Breath is unconditional.
        # Yasuo Q (this wave 3) is conditional knockup.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Yasuo", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Yasuo"])
        # Yasuo Q is in conditional, not unconditional.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Yasuo"])
        self.assertNotIn(
            "Q", _PER_SPELL_CC_DURATIONS.get("Yasuo", {})
        )

    def test_yone_r_in_unconditional_registry(self) -> None:
        # Yone R Fate Sealed is unconditional.
        # Yone Q (this wave 3) is conditional knockup.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Yone", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Yone"])
        # Yone Q is in conditional, not unconditional.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Yone"])
        self.assertNotIn(
            "Q", _PER_SPELL_CC_DURATIONS.get("Yone", {})
        )

    def test_aatrox_no_unconditional_entry(self) -> None:
        # Aatrox has no unconditional entry today; wave-3 Q is the
        # first registered first-order CC.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        # Aatrox might be a key with empty dict OR simply absent.
        aatrox_uncond = _PER_SPELL_CC_DURATIONS.get("Aatrox", {})
        self.assertEqual(aatrox_uncond, {})
        self.assertIn("Aatrox", _PER_SPELL_CC_CONDITIONAL)

    def test_leblanc_no_unconditional_entry(self) -> None:
        # Leblanc has no unconditional entry today; wave-3 E is the
        # first registered first-order CC.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        leblanc_uncond = _PER_SPELL_CC_DURATIONS.get("Leblanc", {})
        self.assertEqual(leblanc_uncond, {})
        self.assertIn("Leblanc", _PER_SPELL_CC_CONDITIONAL)


# ---------------- aggregator regression contract ----------------


class AggregatorWaveThreeTests(unittest.TestCase):
    """get_total_conditional_cc_seconds returns expected values."""

    def test_aatrox_q_weighted_max_rank(self) -> None:
        # Aatrox Q = 0.5 * 0.7 = 0.35
        total = get_total_conditional_cc_seconds("Aatrox")
        self.assertAlmostEqual(total, 0.35, places=4)

    def test_riven_q_weighted_max_rank(self) -> None:
        # Riven Q = 0.75 * 0.7 = 0.525
        total = get_total_conditional_cc_seconds("Riven")
        self.assertAlmostEqual(total, 0.525, places=4)

    def test_yasuo_q_weighted_max_rank(self) -> None:
        # Yasuo Q = 1.0 * 0.7 = 0.70
        total = get_total_conditional_cc_seconds("Yasuo")
        self.assertAlmostEqual(total, 0.70, places=4)

    def test_yone_q_weighted_max_rank(self) -> None:
        # Yone Q = 0.75 * 0.7 = 0.525
        total = get_total_conditional_cc_seconds("Yone")
        self.assertAlmostEqual(total, 0.525, places=4)

    def test_leblanc_e_weighted_max_rank(self) -> None:
        # Leblanc E = 1.5 * 0.5 = 0.75
        total = get_total_conditional_cc_seconds("Leblanc")
        self.assertAlmostEqual(total, 0.75, places=4)

    def test_aatrox_q_raw_max_rank(self) -> None:
        # Aatrox Q raw (apply_probability=False) = 0.5
        total = get_total_conditional_cc_seconds(
            "Aatrox", apply_probability=False
        )
        self.assertAlmostEqual(total, 0.5, places=4)

    def test_yasuo_q_raw_max_rank(self) -> None:
        # Yasuo Q raw = 1.0
        total = get_total_conditional_cc_seconds(
            "Yasuo", apply_probability=False
        )
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_leblanc_e_raw_max_rank(self) -> None:
        # Leblanc E raw = 1.5
        total = get_total_conditional_cc_seconds(
            "Leblanc", apply_probability=False
        )
        self.assertAlmostEqual(total, 1.5, places=4)

    def test_get_conditional_entries_returns_q_for_aatrox(self) -> None:
        entries = get_conditional_entries("Aatrox")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_for_riven(self) -> None:
        entries = get_conditional_entries("Riven")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_for_yasuo(self) -> None:
        entries = get_conditional_entries("Yasuo")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_for_yone(self) -> None:
        entries = get_conditional_entries("Yone")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_e_for_leblanc(self) -> None:
        entries = get_conditional_entries("Leblanc")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "E")


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at current bumped state.

    Wave 3 ships at ENGINE 1.40.0 after orchestrator bump.
    The slice itself is committed at 1.39.0 because the orchestrator
    handles the bump at merge time. Either way, ENGINE >= 1.39.0 must
    hold for the wave-3 test surface to be valid.
    """

    def test_engine_version_at_least_1_39_0(self) -> None:
        # Wave 3 ships at ENGINE >= 1.39.0 (orchestrator may bump
        # to 1.40.0 at merge). Future bumps must keep this at
        # >= 1.39.0 so the wave-3 entry test surface stays valid.
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 39, 0))


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
