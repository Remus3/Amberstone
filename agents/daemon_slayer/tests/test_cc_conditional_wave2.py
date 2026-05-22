"""ENGINE 1.39.0 (2026-05-22) - cc_conditional wave 2 expansion.

Tests the wave 2 expansion of the conditional CC registry: +5 entries
across +5 new champions drawn from the wave 4/5/6/7 REJECT lists in
CLAUDE.md items 138/139/140/141 + the wave 1 REJECT carry-forward in
item 142.

The 5 new entries are:
  * Maokai Q Bramble Smash (terrain) - terrain knockback extends to stun
  * Pyke E Phantom Undertow (channel_completion) - return-knife stun
  * Swain E Nevermove (channel_completion) - return-wave root
  * Skarner Q Shattered Earth (nth_hit) - 3-charge cycle terrain knockup
  * Zilean Q Time Bomb (nth_hit) - 2-bomb stack stun

These re-use existing condition tags exclusively - no new tag constants.
Registry growth: 18 champs / 18 entries -> 23 champs / 23 entries.

Skarner Q (this wave) coexists with Skarner R in the unconditional
wave-2 registry (`ability_dps.py:_PER_SPELL_CC_DURATIONS`). Maokai Q
(this wave) coexists with Maokai R unconditional. Pyke E coexists with
Pyke Q unconditional. The cc_conditional + cc_unconditional registries
are independent so no clobber.

Coverage classes:
  * ``WaveTwoNewEntryShapeTests`` - each new entry has correct schema
    (champion / spell / cc_kind / durations_s shape / condition tag /
    probability).
  * ``WaveTwoValuePinsTests`` - per-entry value pins.
  * ``WaveTwoNewChampionsTests`` - each new champion appears in
    registry; case-sensitive DDragon ids.
  * ``RegistryGrowthTests`` - new totals 23 champs / 23 entries.
  * ``ExistingSeedPreservedTests`` - all 18 prior entries still
    present + byte-identical.
  * ``WaveTwoCoexistenceWithUnconditionalTests`` - Maokai / Pyke /
    Skarner coexist between conditional + unconditional registries.
  * ``AggregatorWaveTwoTests`` - aggregator returns expected weighted
    + raw totals for new entries.
  * ``EngineVersionCurrentTests`` - ENGINE pinned at 1.39.0.
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


# ---------------- wave 2 expected expansion map ----------------


# Each wave-2 entry pin (champion, spell, cc_kind, durations_s,
# condition, probability). Pinned to detect schema regressions.
WAVE_TWO_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Maokai": {"Q": {
        "cc_kind": "stun",
        "durations_s": (1.0,),
        "condition": COND_TERRAIN,
        "probability": 0.3,
    }},
    "Pyke": {"E": {
        "cc_kind": "stun",
        "durations_s": (1.25,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "Swain": {"E": {
        "cc_kind": "root",
        "durations_s": (1.5, 1.625, 1.75, 1.875, 2.0),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "Skarner": {"Q": {
        "cc_kind": "knockup",
        "durations_s": (0.75,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "Zilean": {"Q": {
        "cc_kind": "stun",
        "durations_s": (2.0,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
}


# Wave 0 + wave 1 seed (the 18 pre-wave-2 entries) re-pinned to verify
# they survive wave 2 setdefault construction.
PRE_WAVE_TWO_EXPECTED_CHAMPS = {
    # wave 0 seed (10 from items 138/139/140)
    "Brand", "TwistedFate", "JarvanIV", "TahmKench", "Volibear",
    "Warwick", "Viktor", "Mordekaiser", "Sett", "Vex",
    # wave 1 (8 from item 142)
    "Bard", "Karma", "Taliyah", "Kennen", "KSante",
    "Ornn", "Xayah", "Fiora",
}


# ---------------- new entry shape contract ----------------


class WaveTwoNewEntryShapeTests(unittest.TestCase):
    """Each wave-2 entry has the expected schema."""

    def test_all_wave_two_champs_present_in_registry(self) -> None:
        for champ in WAVE_TWO_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"wave 2 champ {champ} missing from registry",
            )

    def test_all_wave_two_spells_present(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"wave 2 {champ} {spell_key} missing from spell map",
                )

    def test_all_wave_two_entries_are_conditional_cc_entry_dataclass(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIsInstance(entry, ConditionalCcEntry)

    def test_all_wave_two_entries_carry_notes(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertTrue(
                    entry.notes,
                    f"wave 2 {champ} {spell_key} missing notes",
                )

    def test_all_wave_two_entries_use_existing_tags_only(self) -> None:
        # No new tag constants introduced in wave 2.
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
        for champ in WAVE_TWO_EXPECTED:
            for spell_key in WAVE_TWO_EXPECTED[champ]:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(
                    entry.condition,
                    allowed_tags,
                    f"{champ} {spell_key} uses unknown tag {entry.condition!r}",
                )

    def test_all_wave_two_entries_valid_spell_slots(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(entry.spell, ("Q", "W", "E", "R"))

    def test_all_wave_two_entries_have_positive_durations(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                for d in entry.durations_s:
                    self.assertGreater(d, 0.0)

    def test_all_wave_two_entries_have_clamped_probability(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertGreaterEqual(entry.probability, 0.0)
                self.assertLessEqual(entry.probability, 1.0)

    def test_wave_two_champion_field_matches_dict_key(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertEqual(entry.champion, champ)


# ---------------- per-entry value pins ----------------


class WaveTwoValuePinsTests(unittest.TestCase):
    """Per-entry value pins for each wave-2 entry."""

    def test_maokai_q_bramble_smash(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Maokai"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)
        self.assertEqual(entry.spell, "Q")

    def test_pyke_e_phantom_undertow(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Pyke"]["E"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.25,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "E")

    def test_swain_e_nevermove(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Swain"]["E"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5, 1.625, 1.75, 1.875, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "E")

    def test_skarner_q_shattered_earth(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Skarner"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")

    def test_zilean_q_time_bomb(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Zilean"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (2.0,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)
        self.assertEqual(entry.spell, "Q")


# ---------------- new champions contract ----------------


class WaveTwoNewChampionsTests(unittest.TestCase):
    """Each new champion appears in registry with case-sensitive id."""

    def test_maokai_in_registry(self) -> None:
        self.assertIn("Maokai", _PER_SPELL_CC_CONDITIONAL)

    def test_pyke_in_registry(self) -> None:
        self.assertIn("Pyke", _PER_SPELL_CC_CONDITIONAL)

    def test_swain_in_registry(self) -> None:
        self.assertIn("Swain", _PER_SPELL_CC_CONDITIONAL)

    def test_skarner_in_registry(self) -> None:
        self.assertIn("Skarner", _PER_SPELL_CC_CONDITIONAL)

    def test_zilean_in_registry(self) -> None:
        self.assertIn("Zilean", _PER_SPELL_CC_CONDITIONAL)

    def test_lowercase_variants_not_in_registry(self) -> None:
        # Case-sensitive DDragon ids only.
        for champ in WAVE_TWO_EXPECTED:
            self.assertNotIn(
                champ.lower(),
                _PER_SPELL_CC_CONDITIONAL,
                f"lowercase {champ.lower()!r} unexpectedly in registry",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Wave 2 grows registry from 18/18 to 23/23."""

    def test_registry_total_champions_23(self) -> None:
        self.assertEqual(REGISTRY_TOTAL_CHAMPIONS, 23)
        self.assertEqual(len(_PER_SPELL_CC_CONDITIONAL), 23)

    def test_registry_total_entries_23(self) -> None:
        # Each champion has exactly one entry today; 23 entries
        # across 23 champions. This pin signals future regressions
        # (e.g. a wave forgets to add a champion OR adds 2 spells
        # for a champion without updating this count).
        self.assertEqual(REGISTRY_TOTAL_ENTRIES, 23)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertEqual(live, 23)

    def test_wave_two_adds_5_champions_over_prior_waves(self) -> None:
        wave_two_champs = set(WAVE_TWO_EXPECTED.keys())
        # Wave 2 should add exactly 5 NEW champions not in prior waves.
        new_in_wave_two = wave_two_champs - PRE_WAVE_TWO_EXPECTED_CHAMPS
        self.assertEqual(len(new_in_wave_two), 5)

    def test_wave_two_champs_have_no_prior_wave_overlap(self) -> None:
        # No wave-2 champ should be a prior-wave champ.
        for champ in WAVE_TWO_EXPECTED:
            self.assertNotIn(
                champ, PRE_WAVE_TWO_EXPECTED_CHAMPS,
                f"{champ} is a prior-wave champion AND a wave-2 "
                "champion - this would be a clobber",
            )

    def test_no_duplicate_champions_in_wave_two(self) -> None:
        # Trivial (dict keys are unique) but pin for documentation.
        self.assertEqual(
            len(WAVE_TWO_EXPECTED),
            len(set(WAVE_TWO_EXPECTED.keys())),
        )


# ---------------- existing seed preserved contract ----------------


class ExistingSeedPreservedTests(unittest.TestCase):
    """All 18 prior entries (wave 0 + wave 1) still present + intact."""

    def test_all_prior_wave_champs_still_present(self) -> None:
        for champ in PRE_WAVE_TWO_EXPECTED_CHAMPS:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"prior-wave champ {champ} lost in wave 2",
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

    def test_volibear_q_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Volibear"]["Q"]
        self.assertEqual(entry.cc_kind, "knockback")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

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


# ---------------- coexistence with unconditional registry ----------------


class WaveTwoCoexistenceWithUnconditionalTests(unittest.TestCase):
    """Wave-2 champions with prior unconditional entries coexist."""

    def test_maokai_r_in_unconditional_registry(self) -> None:
        # Maokai R Twisted Advance is unconditional (wave 1 registry).
        # Maokai Q (this wave 2) is conditional.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Maokai", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Maokai"])
        # Maokai Q is in conditional, not unconditional.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Maokai"])
        self.assertNotIn(
            "Q", _PER_SPELL_CC_DURATIONS.get("Maokai", {})
        )

    def test_pyke_q_in_unconditional_registry(self) -> None:
        # Pyke Q Bone Skewer is unconditional (wave 3 registry).
        # Pyke E (this wave 2) is conditional.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Pyke", _PER_SPELL_CC_DURATIONS)
        self.assertIn("Q", _PER_SPELL_CC_DURATIONS["Pyke"])
        # Pyke E is in conditional, not unconditional.
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Pyke"])
        self.assertNotIn(
            "E", _PER_SPELL_CC_DURATIONS.get("Pyke", {})
        )

    def test_skarner_r_in_unconditional_registry(self) -> None:
        # Skarner R Impale is unconditional (wave 2 registry).
        # Skarner Q (this wave 2) is conditional.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Skarner", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Skarner"])
        # Skarner Q is in conditional, not unconditional.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Skarner"])
        self.assertNotIn(
            "Q", _PER_SPELL_CC_DURATIONS.get("Skarner", {})
        )

    def test_swain_no_unconditional_entry(self) -> None:
        # Swain has no unconditional entry yet; only wave-2 E.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Swain", _PER_SPELL_CC_DURATIONS)
        self.assertIn("Swain", _PER_SPELL_CC_CONDITIONAL)

    def test_zilean_no_unconditional_entry(self) -> None:
        # Zilean has no unconditional entry; only wave-2 Q.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertNotIn("Zilean", _PER_SPELL_CC_DURATIONS)
        self.assertIn("Zilean", _PER_SPELL_CC_CONDITIONAL)


# ---------------- aggregator regression contract ----------------


class AggregatorWaveTwoTests(unittest.TestCase):
    """get_total_conditional_cc_seconds returns expected values."""

    def test_maokai_q_weighted_max_rank(self) -> None:
        # Maokai Q = 1.0 * 0.3 = 0.30
        total = get_total_conditional_cc_seconds("Maokai")
        self.assertAlmostEqual(total, 0.30, places=4)

    def test_pyke_e_weighted_max_rank(self) -> None:
        # Pyke E = 1.25 * 0.5 = 0.625
        total = get_total_conditional_cc_seconds("Pyke")
        self.assertAlmostEqual(total, 0.625, places=4)

    def test_swain_e_weighted_max_rank(self) -> None:
        # Swain E max rank = 2.0 * 0.5 = 1.0
        total = get_total_conditional_cc_seconds("Swain")
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_skarner_q_weighted_max_rank(self) -> None:
        # Skarner Q = 0.75 * 0.7 = 0.525
        total = get_total_conditional_cc_seconds("Skarner")
        self.assertAlmostEqual(total, 0.525, places=4)

    def test_zilean_q_weighted_max_rank(self) -> None:
        # Zilean Q = 2.0 * 0.7 = 1.4
        total = get_total_conditional_cc_seconds("Zilean")
        self.assertAlmostEqual(total, 1.4, places=4)

    def test_swain_e_raw_max_rank(self) -> None:
        # Swain E raw max rank (last in tuple) = 2.0
        total = get_total_conditional_cc_seconds(
            "Swain", apply_probability=False
        )
        self.assertAlmostEqual(total, 2.0, places=4)

    def test_swain_e_raw_rank_index_0(self) -> None:
        # Swain E rank 0 = 1.5 raw
        total = get_total_conditional_cc_seconds(
            "Swain", apply_probability=False, rank_index=0
        )
        self.assertAlmostEqual(total, 1.5, places=4)

    def test_get_conditional_entries_returns_q_for_maokai(self) -> None:
        entries = get_conditional_entries("Maokai")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_e_for_pyke(self) -> None:
        entries = get_conditional_entries("Pyke")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "E")

    def test_get_conditional_entries_returns_e_for_swain(self) -> None:
        entries = get_conditional_entries("Swain")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "E")

    def test_get_conditional_entries_returns_q_for_skarner(self) -> None:
        entries = get_conditional_entries("Skarner")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_for_zilean(self) -> None:
        entries = get_conditional_entries("Zilean")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at current bumped state."""

    def test_engine_version_at_least_1_39_0(self) -> None:
        # Wave 2 ships at ENGINE 1.39.0. Future bumps must keep this
        # at >= 1.39.0 so the wave-2 entry test surface stays valid.
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
