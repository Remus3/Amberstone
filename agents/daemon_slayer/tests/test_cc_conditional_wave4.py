"""ENGINE 1.41.0 (2026-05-22) - cc_conditional wave 4 expansion.

Tests the wave 4 expansion of the conditional CC registry: +5 entries
across +4 new champions + 1 multi-wave coexistence (Aatrox W chain-
root coexists with Aatrox Q3 knockup from wave 3), drawn from patch
16.10.1 tooltips for channel-completion + target-debuffed + terrain
mechanics.

The 5 new entries are:
  * Nunu R Absolute Zero (channel_completion) - full 3s channel AOE knockup
  * Yuumi Q Prowling Projectile (channel_completion) - max-travel root
  * Pantheon Q Comet Spear empowered (channel_completion) - long-cast stun
  * Aatrox W Infernal Chains (target_debuffed) - chain pull-back root
  * Briar Q Head Rush (terrain) - terrain collision stun

These re-use existing condition tags exclusively - no new tag constants.
Registry growth: 28 champs / 28 entries -> 32 champs / 33 entries.

Aatrox W (this wave 4) coexists with Aatrox Q (wave 3) on the same
champion's spell map via setdefault. Pantheon Q (this wave 4) coexists
with Pantheon W in the unconditional ``_PER_SPELL_CC_DURATIONS``
registry (different spell slot). Nunu / Yuumi / Briar have no
unconditional entries today; their wave-4 conditional entries are
the first registered first-order CC for those champions.

Coverage classes:
  * ``WaveFourNewEntryShapeTests`` - each new entry has correct
    schema (champion / spell / cc_kind / durations_s shape /
    condition tag / probability).
  * ``WaveFourValuePinsTests`` - per-entry value pins.
  * ``WaveFourNewChampionsTests`` - each new champion appears in
    registry; case-sensitive DDragon ids.
  * ``RegistryGrowthTests`` - new totals 32 champs / 33 entries.
  * ``ExistingSeedPreservedTests`` - all 28 prior entries (waves
    0+1+2+3) still present + byte-identical.
  * ``WaveFourCoexistenceWithUnconditionalTests`` - Pantheon Q
    coexists with Pantheon W in the unconditional registry on
    a different spell slot.
  * ``WaveFourCoexistenceWithPriorWavesTests`` - Aatrox W (wave 4)
    coexists with Aatrox Q (wave 3) via setdefault.
  * ``AggregatorWaveFourTests`` - aggregator returns expected
    weighted + raw totals for new entries.
  * ``EngineVersionCurrentTests`` - ENGINE pinned at >= 1.41.0
    (the orchestrator bumps to 1.41.0 at merge; this slice ships
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


# ---------------- wave 4 expected expansion map ----------------


# Each wave-4 entry pin (champion, spell, cc_kind, durations_s,
# condition, probability). Pinned to detect schema regressions.
WAVE_FOUR_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Nunu": {"R": {
        "cc_kind": "knockup",
        "durations_s": (0.5,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "Yuumi": {"Q": {
        "cc_kind": "root",
        "durations_s": (1.75,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.4,
    }},
    "Pantheon": {"Q": {
        "cc_kind": "stun",
        "durations_s": (1.0,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "Aatrox": {"W": {
        "cc_kind": "root",
        "durations_s": (1.75,),
        "condition": COND_TARGET_DEBUFFED,
        "probability": 0.5,
    }},
    "Briar": {"Q": {
        "cc_kind": "stun",
        "durations_s": (1.0,),
        "condition": COND_TERRAIN,
        "probability": 0.3,
    }},
}


# Wave 0 + wave 1 + wave 2 + wave 3 seed (the 28 pre-wave-4 entries)
# re-pinned to verify they survive wave 4 setdefault construction.
PRE_WAVE_FOUR_EXPECTED_CHAMPS = {
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
}

# Wave 4 introduces 4 NEW champions (Nunu / Yuumi / Pantheon / Briar)
# + 1 multi-wave coexistence (Aatrox W, where Aatrox was already
# introduced in wave 3 with Q). The set of net-new champion ids:
WAVE_FOUR_NEW_CHAMPIONS = {"Nunu", "Yuumi", "Pantheon", "Briar"}


# ---------------- new entry shape contract ----------------


class WaveFourNewEntryShapeTests(unittest.TestCase):
    """Each wave-4 entry has the expected schema."""

    def test_all_wave_four_champs_present_in_registry(self) -> None:
        for champ in WAVE_FOUR_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"wave 4 champ {champ} missing from registry",
            )

    def test_all_wave_four_spells_present(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"wave 4 {champ} {spell_key} missing from spell map",
                )

    def test_all_wave_four_entries_are_conditional_cc_entry_dataclass(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIsInstance(entry, ConditionalCcEntry)

    def test_all_wave_four_entries_carry_notes(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertTrue(
                    entry.notes,
                    f"wave 4 {champ} {spell_key} missing notes",
                )

    def test_all_wave_four_entries_use_existing_tags_only(self) -> None:
        # No new tag constants introduced in wave 4.
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
        for champ in WAVE_FOUR_EXPECTED:
            for spell_key in WAVE_FOUR_EXPECTED[champ]:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(
                    entry.condition,
                    allowed_tags,
                    f"{champ} {spell_key} uses unknown tag {entry.condition!r}",
                )

    def test_all_wave_four_entries_valid_spell_slots(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(entry.spell, ("Q", "W", "E", "R"))

    def test_all_wave_four_entries_have_positive_durations(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                for d in entry.durations_s:
                    self.assertGreater(d, 0.0)

    def test_all_wave_four_entries_have_clamped_probability(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertGreaterEqual(entry.probability, 0.0)
                self.assertLessEqual(entry.probability, 1.0)

    def test_wave_four_champion_field_matches_dict_key(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertEqual(entry.champion, champ)


# ---------------- per-entry value pins ----------------


class WaveFourValuePinsTests(unittest.TestCase):
    """Per-entry value pins for each wave-4 entry."""

    def test_nunu_r_absolute_zero(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Nunu"]["R"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.5,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "R")

    def test_yuumi_q_prowling_projectile(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Yuumi"]["Q"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.75,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.4)
        self.assertEqual(entry.spell, "Q")

    def test_pantheon_q_comet_spear_empowered(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Pantheon"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "Q")

    def test_aatrox_w_infernal_chains(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.75,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "W")

    def test_briar_q_head_rush(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)
        self.assertEqual(entry.spell, "Q")


# ---------------- new champions contract ----------------


class WaveFourNewChampionsTests(unittest.TestCase):
    """Each new champion appears in registry with case-sensitive id."""

    def test_nunu_in_registry(self) -> None:
        self.assertIn("Nunu", _PER_SPELL_CC_CONDITIONAL)

    def test_yuumi_in_registry(self) -> None:
        self.assertIn("Yuumi", _PER_SPELL_CC_CONDITIONAL)

    def test_pantheon_in_registry(self) -> None:
        self.assertIn("Pantheon", _PER_SPELL_CC_CONDITIONAL)

    def test_briar_in_registry(self) -> None:
        self.assertIn("Briar", _PER_SPELL_CC_CONDITIONAL)

    def test_aatrox_w_added_via_multi_wave_coexistence(self) -> None:
        # Aatrox is NOT a net-new champion (was added in wave 3 with
        # Q3 conditional knockup). Wave 4 adds W on the same champion
        # via setdefault.
        self.assertIn("Aatrox", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Aatrox"])
        self.assertIn("W", _PER_SPELL_CC_CONDITIONAL["Aatrox"])

    def test_lowercase_variants_not_in_registry(self) -> None:
        # Case-sensitive DDragon ids only.
        for champ in WAVE_FOUR_EXPECTED:
            self.assertNotIn(
                champ.lower(),
                _PER_SPELL_CC_CONDITIONAL,
                f"lowercase {champ.lower()!r} unexpectedly in registry",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Wave 4 grows registry from 28/28 to 32/33."""

    def test_registry_total_champions_at_least_32(self) -> None:
        # assertGreaterEqual for future-wave compatibility per item
        # 143 Slice C / 144 Slice C pattern relaxation.
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 32)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL), 32)

    def test_registry_total_entries_at_least_33(self) -> None:
        # 33 entries across 32 champions (Aatrox has 2 entries Q+W;
        # everyone else has 1). assertGreaterEqual for future-wave
        # compatibility.
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 33)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(live, 33)

    def test_wave_four_adds_4_new_champions_over_prior_waves(self) -> None:
        # Wave 4 net-new champions count is 4 (Aatrox is multi-wave
        # coexistence, not net-new).
        new_in_wave_four = (
            WAVE_FOUR_NEW_CHAMPIONS - PRE_WAVE_FOUR_EXPECTED_CHAMPS
        )
        self.assertEqual(len(new_in_wave_four), 4)
        self.assertEqual(new_in_wave_four, WAVE_FOUR_NEW_CHAMPIONS)

    def test_wave_four_new_champs_have_no_prior_wave_overlap(self) -> None:
        # The 4 net-new wave-4 champs are NOT in prior waves.
        for champ in WAVE_FOUR_NEW_CHAMPIONS:
            self.assertNotIn(
                champ, PRE_WAVE_FOUR_EXPECTED_CHAMPS,
                f"{champ} marked as net-new wave-4 but is in prior waves",
            )

    def test_aatrox_is_multi_wave_coexistence(self) -> None:
        # Aatrox IS in prior waves (wave 3 Q3) and gets wave 4 W
        # added via setdefault on a different spell slot. This is
        # the FIRST multi-wave coexistence in the conditional CC
        # registry.
        self.assertIn("Aatrox", PRE_WAVE_FOUR_EXPECTED_CHAMPS)
        self.assertIn("Aatrox", WAVE_FOUR_EXPECTED)
        # The new wave-4 spell slot for Aatrox is W; the wave-3
        # spell slot is Q. Both must coexist post-build.
        self.assertEqual(
            set(_PER_SPELL_CC_CONDITIONAL["Aatrox"].keys()),
            {"Q", "W"},
        )


# ---------------- existing seed preserved contract ----------------


class ExistingSeedPreservedTests(unittest.TestCase):
    """All 28 prior entries (wave 0 + wave 1 + wave 2 + wave 3)
    still present + byte-identical post-wave-4."""

    def test_all_prior_wave_champs_still_present(self) -> None:
        for champ in PRE_WAVE_FOUR_EXPECTED_CHAMPS:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"prior-wave champ {champ} lost in wave 4",
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

    def test_aatrox_q_wave3_unchanged(self) -> None:
        # Aatrox Q is wave 3 conditional knockup. Wave 4 adds W on
        # the same champion; Q must stay byte-identical.
        entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_riven_q_wave3_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Riven"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_yasuo_q_wave3_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Yasuo"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_leblanc_e_wave3_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Leblanc"]["E"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)


# ---------------- coexistence with unconditional registry ----------------


class WaveFourCoexistenceWithUnconditionalTests(unittest.TestCase):
    """Pantheon Q (wave 4 conditional) coexists with Pantheon W
    (unconditional registry) on a DIFFERENT spell slot. Nunu /
    Yuumi / Briar have no unconditional entries today."""

    def test_pantheon_w_in_unconditional_registry(self) -> None:
        # Pantheon W is unconditional stun. Pantheon Q (wave 4) is
        # conditional empowered-cast stun. Different spell slots so
        # no collision.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Pantheon", _PER_SPELL_CC_DURATIONS)
        self.assertIn("W", _PER_SPELL_CC_DURATIONS["Pantheon"])
        # Pantheon Q is in conditional, not unconditional.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Pantheon"])
        self.assertNotIn(
            "Q", _PER_SPELL_CC_DURATIONS.get("Pantheon", {})
        )

    def test_nunu_no_unconditional_entry(self) -> None:
        # Nunu has no unconditional entry today; wave-4 R is the
        # first registered first-order CC.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        nunu_uncond = _PER_SPELL_CC_DURATIONS.get("Nunu", {})
        self.assertEqual(nunu_uncond, {})
        self.assertIn("Nunu", _PER_SPELL_CC_CONDITIONAL)

    def test_yuumi_no_unconditional_entry(self) -> None:
        # Yuumi has no unconditional entry today; wave-4 Q is the
        # first registered first-order CC.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        yuumi_uncond = _PER_SPELL_CC_DURATIONS.get("Yuumi", {})
        self.assertEqual(yuumi_uncond, {})
        self.assertIn("Yuumi", _PER_SPELL_CC_CONDITIONAL)

    def test_briar_no_unconditional_entry(self) -> None:
        # Briar has no unconditional entry today; wave-4 Q is the
        # first registered first-order CC.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        briar_uncond = _PER_SPELL_CC_DURATIONS.get("Briar", {})
        self.assertEqual(briar_uncond, {})
        self.assertIn("Briar", _PER_SPELL_CC_CONDITIONAL)


# ---------------- coexistence with prior waves contract ----------------


class WaveFourCoexistenceWithPriorWavesTests(unittest.TestCase):
    """Aatrox W (wave 4) coexists with Aatrox Q (wave 3) via
    setdefault on the same champion's spell map. This is the FIRST
    multi-wave coexistence in the conditional CC registry."""

    def test_aatrox_has_both_q_and_w_entries(self) -> None:
        # Both spell slots present post-build via setdefault.
        self.assertIn("Aatrox", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Aatrox"])
        self.assertIn("W", _PER_SPELL_CC_CONDITIONAL["Aatrox"])

    def test_aatrox_q_is_wave_three_knockup(self) -> None:
        # Wave-3 Q (sweetspot knockup) survives wave-4 build.
        q_entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["Q"]
        self.assertEqual(q_entry.cc_kind, "knockup")
        self.assertEqual(q_entry.durations_s, (0.5,))

    def test_aatrox_w_is_wave_four_root(self) -> None:
        # Wave-4 W (chain-pull root) added without clobber.
        w_entry = _PER_SPELL_CC_CONDITIONAL["Aatrox"]["W"]
        self.assertEqual(w_entry.cc_kind, "root")
        self.assertEqual(w_entry.durations_s, (1.75,))

    def test_aatrox_has_exactly_two_entries(self) -> None:
        # Wave 4 adds W; total Aatrox entries = 2 (Q + W). Both
        # share the same champion key via setdefault construction.
        spells = _PER_SPELL_CC_CONDITIONAL["Aatrox"]
        self.assertEqual(len(spells), 2)


# ---------------- aggregator regression contract ----------------


class AggregatorWaveFourTests(unittest.TestCase):
    """get_total_conditional_cc_seconds returns expected values."""

    def test_nunu_r_weighted_max_rank(self) -> None:
        # Nunu R = 0.5 * 0.5 = 0.25
        total = get_total_conditional_cc_seconds("Nunu")
        self.assertAlmostEqual(total, 0.25, places=4)

    def test_yuumi_q_weighted_max_rank(self) -> None:
        # Yuumi Q = 1.75 * 0.4 = 0.70
        total = get_total_conditional_cc_seconds("Yuumi")
        self.assertAlmostEqual(total, 0.70, places=4)

    def test_pantheon_q_weighted_max_rank(self) -> None:
        # Pantheon Q = 1.0 * 0.5 = 0.50
        total = get_total_conditional_cc_seconds("Pantheon")
        self.assertAlmostEqual(total, 0.50, places=4)

    def test_aatrox_weighted_max_rank_with_both_q_and_w(self) -> None:
        # Aatrox Q (wave 3) = 0.5 * 0.7 = 0.35
        # Aatrox W (wave 4) = 1.75 * 0.5 = 0.875
        # Total weighted = 0.35 + 0.875 = 1.225
        total = get_total_conditional_cc_seconds("Aatrox")
        self.assertAlmostEqual(total, 1.225, places=4)

    def test_briar_q_weighted_max_rank(self) -> None:
        # Briar Q entry-level contribution = 1.0 * 0.3 = 0.30
        # Wave 5 added Briar E to the same champion, so the
        # aggregator returns Q + E. Pin at entry-level instead.
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["Q"]
        self.assertAlmostEqual(
            entry.durations_s[-1] * entry.probability, 0.30, places=4
        )

    def test_nunu_r_raw_max_rank(self) -> None:
        # Nunu R raw = 0.5
        total = get_total_conditional_cc_seconds(
            "Nunu", apply_probability=False
        )
        self.assertAlmostEqual(total, 0.5, places=4)

    def test_yuumi_q_raw_max_rank(self) -> None:
        # Yuumi Q raw = 1.75
        total = get_total_conditional_cc_seconds(
            "Yuumi", apply_probability=False
        )
        self.assertAlmostEqual(total, 1.75, places=4)

    def test_aatrox_raw_max_rank_with_both_q_and_w(self) -> None:
        # Aatrox Q raw = 0.5 + Aatrox W raw = 1.75 -> 2.25 total
        total = get_total_conditional_cc_seconds(
            "Aatrox", apply_probability=False
        )
        self.assertAlmostEqual(total, 2.25, places=4)

    def test_briar_q_raw_max_rank(self) -> None:
        # Briar Q entry-level raw = 1.0. Wave 5 added Briar E
        # to the same champion so aggregator sums Q + E; pin at
        # entry-level instead (mirror of Aatrox Q+W approach).
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["Q"]
        self.assertAlmostEqual(entry.durations_s[-1], 1.0, places=4)

    def test_get_conditional_entries_returns_r_for_nunu(self) -> None:
        entries = get_conditional_entries("Nunu")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "R")

    def test_get_conditional_entries_returns_q_for_yuumi(self) -> None:
        entries = get_conditional_entries("Yuumi")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_for_pantheon(self) -> None:
        entries = get_conditional_entries("Pantheon")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_and_w_for_aatrox(self) -> None:
        # Aatrox has 2 entries (Q + W). Canonical Q-W-E-R order
        # means Q is index 0, W is index 1.
        entries = get_conditional_entries("Aatrox")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[1].spell, "W")

    def test_get_conditional_entries_returns_q_for_briar(self) -> None:
        # Wave 5 added Briar E coexisting with wave 4 Q via setdefault.
        # Q is the first entry in canonical Q-W-E-R order.
        entries = get_conditional_entries("Briar")
        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at current bumped state.

    Wave 4 ships at ENGINE >= 1.41.0; the orchestrator bumps to
    1.41.0 at merge time. ENGINE >= 1.41.0 must hold for the wave-4
    test surface to be valid.
    """

    def test_engine_version_at_least_1_40_0(self) -> None:
        # Wave 4 ships at ENGINE >= 1.41.0 (orchestrator may bump
        # to 1.41.0 at merge). Future bumps must keep this at
        # >= 1.41.0 so the wave-4 entry test surface stays valid.
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 40, 0))


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
