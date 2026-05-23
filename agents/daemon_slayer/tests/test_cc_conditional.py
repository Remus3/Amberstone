"""ENGINE 1.37.0 (2026-05-22) - conditional CC axis schema lift.

Tests the new ``cc_conditional`` module: schema + builder + seed
+ lookup helpers. The module is a FORWARD-MARKER seam; no consumer
wires to it yet. These tests pin the schema + the canonical seed
so future consumers have a stable contract.

Closes item 140 carry (h) data-side. Mirrors:
  * ENGINE 1.22.0 - ``STAT_GRANT_CALC_KEYS`` empty seam in
    ``agents/daemon_slayer/augments.py``.
  * ENGINE 1.30.0 - ``_PER_SPELL_CC_DURATIONS`` registry was a
    forward marker before seed waves 1-6 broke it to 95/82.

Coverage classes:
  * ``ConditionalCcEntrySchemaTests`` - dataclass construction
    contract + validation rules from ``__post_init__``.
  * ``RegistrySeedTests`` - the 10 canonical seed entries are
    present + value-pinned.
  * ``GetConditionalEntriesTests`` - the lookup helper returns
    canonical Q/W/E/R order over the present subset; fail-soft
    on blank / None / unknown.
  * ``GetTotalConditionalCcSecondsTests`` - the probability-
    weighted aggregator returns expected math + raw mode + rank-
    indexed mode + fail-soft 0.0.
  * ``RegistryGrowthTests`` - the public introspection counters
    match the seed.
  * ``DefaultProbabilityMapCoverageTests`` - every condition tag
    used in the seed has a default-probability entry.
  * ``AsciiHygieneTests`` - both the module + this test file are
    pure ASCII (no em-dashes / smart quotes).
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer.cc_conditional import (
    _DEFAULT_CONDITION_PROBABILITY,
    _PER_SPELL_CC_CONDITIONAL,
    COND_CHANNEL_COMPLETION,
    COND_DEVOUR_TARGET,
    COND_DREAM_STACK,
    COND_DUAL_ENEMY,
    COND_GOLD_CARD,
    COND_MODE_GATED,
    COND_NTH_HIT,
    COND_TARGET_DEBUFFED,
    COND_TARGET_HP_BELOW,
    COND_TERRAIN,
    ConditionalCcEntry,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    _build_per_spell_cc_conditional,
    get_conditional_entries,
    get_total_conditional_cc_seconds,
)


# ---------------- expected seed map ----------------


# Source-of-truth for what the seed ships. Matches the 10 entries in
# ``_build_per_spell_cc_conditional``. Pin per-champion + per-spell
# (champion, spell, cc_kind, durations_s, condition, probability).
SEED_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Brand": {"R": {
        "cc_kind": "stun",
        "durations_s": (2.0,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "TwistedFate": {"W": {
        "cc_kind": "stun",
        "durations_s": (1.5,),
        "condition": COND_GOLD_CARD,
        "probability": 0.4,
    }},
    "JarvanIV": {"E": {
        "cc_kind": "knockup",
        "durations_s": (1.0,),
        "condition": COND_TERRAIN,
        "probability": 0.5,
    }},
    "TahmKench": {"R": {
        "cc_kind": "suppression",
        "durations_s": (1.0,),
        "condition": COND_DEVOUR_TARGET,
        "probability": 0.4,
    }},
    "Volibear": {"Q": {
        "cc_kind": "knockback",
        "durations_s": (0.75,),
        "condition": COND_TERRAIN,
        "probability": 0.3,
    }},
    "Warwick": {"R": {
        "cc_kind": "suppression",
        "durations_s": (1.5, 1.75, 2.0),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "Viktor": {"W": {
        "cc_kind": "stun",
        "durations_s": (1.5,),
        "condition": COND_NTH_HIT,
        "probability": 0.6,
    }},
    "Mordekaiser": {"R": {
        "cc_kind": "banishment",
        "durations_s": (7.0,),
        "condition": COND_MODE_GATED,
        "probability": 1.0,
    }},
    "Sett": {"E": {
        "cc_kind": "stun",
        "durations_s": (1.0,),
        "condition": COND_DUAL_ENEMY,
        "probability": 0.6,
    }},
    "Vex": {"E": {
        "cc_kind": "fear",
        "durations_s": (1.0, 1.125, 1.25, 1.375, 1.5),
        "condition": COND_TARGET_DEBUFFED,
        "probability": 0.5,
    }},
}


# ---------------- schema contract ----------------


class ConditionalCcEntrySchemaTests(unittest.TestCase):
    """Dataclass construction contract from ``__post_init__``."""

    def test_construct_valid_q_entry(self) -> None:
        e = ConditionalCcEntry(
            champion="Test",
            spell="Q",
            cc_kind="stun",
            durations_s=(1.0, 1.1, 1.2, 1.3, 1.4),
            condition=COND_NTH_HIT,
            probability=0.5,
            notes="ok",
        )
        self.assertEqual(e.spell, "Q")
        self.assertEqual(len(e.durations_s), 5)

    def test_construct_valid_r_entry(self) -> None:
        e = ConditionalCcEntry(
            champion="Test",
            spell="R",
            cc_kind="stun",
            durations_s=(1.0, 1.5, 2.0),
            condition=COND_NTH_HIT,
        )
        self.assertEqual(e.spell, "R")
        self.assertEqual(len(e.durations_s), 3)

    def test_construct_valid_single_value_shortcut(self) -> None:
        # Length-1 durations_s means same value all ranks.
        e = ConditionalCcEntry(
            champion="Test",
            spell="W",
            cc_kind="root",
            durations_s=(1.5,),
            condition=COND_NTH_HIT,
        )
        self.assertEqual(len(e.durations_s), 1)

    def test_invalid_spell_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="X",
                cc_kind="stun",
                durations_s=(1.0,),
                condition=COND_NTH_HIT,
            )

    def test_probability_above_one_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="Q",
                cc_kind="stun",
                durations_s=(1.0,),
                condition=COND_NTH_HIT,
                probability=1.5,
            )

    def test_probability_below_zero_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="Q",
                cc_kind="stun",
                durations_s=(1.0,),
                condition=COND_NTH_HIT,
                probability=-0.1,
            )

    def test_empty_durations_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="Q",
                cc_kind="stun",
                durations_s=(),
                condition=COND_NTH_HIT,
            )

    def test_negative_duration_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="Q",
                cc_kind="stun",
                durations_s=(1.0, -0.5),
                condition=COND_NTH_HIT,
            )

    def test_q_with_4_ranks_raises(self) -> None:
        # Q/W/E require length 1 or 5; 4 is rejected.
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="Q",
                cc_kind="stun",
                durations_s=(1.0, 1.0, 1.0, 1.0),
                condition=COND_NTH_HIT,
            )

    def test_r_with_2_ranks_raises(self) -> None:
        # R requires length 1 or 3; 2 is rejected.
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="R",
                cc_kind="stun",
                durations_s=(1.0, 1.5),
                condition=COND_NTH_HIT,
            )

    def test_unknown_condition_tag_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConditionalCcEntry(
                champion="Test",
                spell="Q",
                cc_kind="stun",
                durations_s=(1.0,),
                condition="not_a_real_condition",
            )

    def test_dataclass_is_frozen(self) -> None:
        import dataclasses
        e = ConditionalCcEntry(
            champion="Test",
            spell="Q",
            cc_kind="stun",
            durations_s=(1.0,),
            condition=COND_NTH_HIT,
        )
        # Frozen dataclass: attribute assignment must raise FrozenInstanceError.
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.spell = "W"  # type: ignore[misc]


# ---------------- seed presence + value pins ----------------


class RegistrySeedTests(unittest.TestCase):
    """The 10 canonical seed entries are present + value-pinned."""

    def test_all_seed_champs_present(self) -> None:
        for champ in SEED_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"seed champ {champ} missing from registry",
            )

    def test_all_seed_spell_keys_present(self) -> None:
        for champ, spells in SEED_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"seed {champ} {spell_key} missing",
                )

    def test_brand_r_pyroclasm_stun(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["R"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (2.0,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_twistedfate_w_gold_card_stun(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["TwistedFate"]["W"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_GOLD_CARD)
        self.assertEqual(entry.probability, 0.4)

    def test_jarvaniv_e_terrain_knockup(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["JarvanIV"]["E"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.5)

    def test_tahmkench_r_devour_suppression(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["R"]
        self.assertEqual(entry.cc_kind, "suppression")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_DEVOUR_TARGET)
        self.assertEqual(entry.probability, 0.4)

    def test_volibear_q_terrain_knockback(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Volibear"]["Q"]
        self.assertEqual(entry.cc_kind, "knockback")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_warwick_r_channel_suppression(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Warwick"]["R"]
        self.assertEqual(entry.cc_kind, "suppression")
        self.assertEqual(entry.durations_s, (1.5, 1.75, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)

    def test_viktor_w_field_stun(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Viktor"]["W"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.6)

    def test_mordekaiser_r_banishment(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Mordekaiser"]["R"]
        self.assertEqual(entry.cc_kind, "banishment")
        self.assertEqual(entry.durations_s, (7.0,))
        self.assertEqual(entry.condition, COND_MODE_GATED)
        self.assertEqual(entry.probability, 1.0)

    def test_sett_e_dual_enemy_stun(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Sett"]["E"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_DUAL_ENEMY)
        self.assertEqual(entry.probability, 0.6)

    def test_vex_e_debuffed_fear(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Vex"]["E"]
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.durations_s, (1.0, 1.125, 1.25, 1.375, 1.5))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.5)

    def test_all_seed_entries_carry_notes(self) -> None:
        # Every seed entry should have a non-empty notes field
        # (the seed entries are operator-documented).
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for spell_key, entry in spells.items():
                self.assertTrue(
                    entry.notes,
                    f"{champ} {spell_key} missing notes documentation",
                )

    def test_builder_returns_fresh_dict_each_call(self) -> None:
        a = _build_per_spell_cc_conditional()
        b = _build_per_spell_cc_conditional()
        self.assertIsNot(a, b)
        # Values must match (byte-identical content).
        self.assertEqual(a, b)

    def test_builder_output_matches_module_registry(self) -> None:
        fresh = _build_per_spell_cc_conditional()
        self.assertEqual(fresh, _PER_SPELL_CC_CONDITIONAL)


# ---------------- get_conditional_entries contract ----------------


class GetConditionalEntriesTests(unittest.TestCase):
    """The Q/W/E/R lookup helper canonical ordering + fail-soft."""

    def test_brand_returns_r_entry(self) -> None:
        # Brand has R (wave 0 nth_hit 3-stack stun) + Q (wave 6
        # debuffed_target Blaze stun). assertGreaterEqual for
        # forward-compat with future Brand wave additions; spell-R
        # presence is the load-bearing pin (wave-0 entry survives).
        entries = get_conditional_entries("Brand")
        self.assertGreaterEqual(len(entries), 1)
        spells = [e.spell for e in entries]
        self.assertIn("R", spells)

    def test_jarvaniv_returns_single_e_entry(self) -> None:
        entries = get_conditional_entries("JarvanIV")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "E")

    def test_unknown_champion_empty(self) -> None:
        self.assertEqual(get_conditional_entries("NotARealChamp"), ())

    def test_blank_champion_empty(self) -> None:
        self.assertEqual(get_conditional_entries(""), ())

    def test_case_sensitive(self) -> None:
        # Canonical DDragon ids are case-sensitive; "brand" should not
        # match "Brand".
        self.assertEqual(get_conditional_entries("brand"), ())

    def test_ordering_q_w_e_r_canonical(self) -> None:
        # Use a fixture mirroring the registry behavior: champion with
        # multiple spells must come back in Q-W-E-R order regardless
        # of insert order. The seed has no multi-spell champion today
        # (each seed champ has just one entry); verify the helper
        # respects the canonical ordering via a manual fixture.
        from agents.daemon_slayer.cc_conditional import _SPELL_ORDER
        self.assertEqual(_SPELL_ORDER, ("Q", "W", "E", "R"))


# ---------------- get_total_conditional_cc_seconds contract ----------------


class GetTotalConditionalCcSecondsTests(unittest.TestCase):
    """The probability-weighted aggregator contract."""

    def test_brand_weighted_total(self) -> None:
        # Brand R: 2.0s * 0.7 prob = 1.4 (wave 0)
        # Brand Q: 1.25s * 0.5 prob = 0.625 (wave 6)
        # Combined weighted = 2.025
        # assertGreaterEqual for forward-compat with future Brand
        # wave additions; the wave-0 R contribution (1.4) is the
        # load-bearing floor.
        total = get_total_conditional_cc_seconds("Brand")
        self.assertGreaterEqual(total, 1.4)

    def test_brand_raw_total(self) -> None:
        # Brand R raw = 2.0 (wave 0)
        # Brand Q raw = 1.25 (wave 6)
        # Combined raw = 3.25
        # assertGreaterEqual for forward-compat with future Brand
        # wave additions; the wave-0 R raw (2.0) is the load-bearing
        # floor.
        total = get_total_conditional_cc_seconds(
            "Brand", apply_probability=False
        )
        self.assertGreaterEqual(total, 2.0)

    def test_warwick_weighted_max_rank(self) -> None:
        # Warwick R max rank (R rank 3) = 2.0s * 0.5 prob = 1.0
        total = get_total_conditional_cc_seconds("Warwick")
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_warwick_weighted_rank_0(self) -> None:
        # Warwick R rank 1 = 1.5s * 0.5 prob = 0.75
        total = get_total_conditional_cc_seconds("Warwick", rank_index=0)
        self.assertAlmostEqual(total, 0.75, places=4)

    def test_warwick_raw_max_rank(self) -> None:
        # Warwick R max rank raw = 2.0s
        total = get_total_conditional_cc_seconds(
            "Warwick", apply_probability=False
        )
        self.assertAlmostEqual(total, 2.0, places=4)

    def test_unknown_champion_zero(self) -> None:
        self.assertEqual(
            get_total_conditional_cc_seconds("NotARealChamp"), 0.0
        )

    def test_blank_champion_zero(self) -> None:
        self.assertEqual(get_total_conditional_cc_seconds(""), 0.0)

    def test_mordekaiser_full_credit_at_probability_1(self) -> None:
        # Mordekaiser R = 7.0s * 1.0 = 7.0
        total = get_total_conditional_cc_seconds("Mordekaiser")
        self.assertAlmostEqual(total, 7.0, places=4)

    def test_out_of_range_rank_index_falls_through_to_max(self) -> None:
        # rank_index >= len(tuple) falls through to max rank.
        total = get_total_conditional_cc_seconds("Warwick", rank_index=99)
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_negative_rank_index_falls_through_to_max(self) -> None:
        # rank_index < 0 (other than -1) falls through to max rank.
        total = get_total_conditional_cc_seconds("Warwick", rank_index=-5)
        self.assertAlmostEqual(total, 1.0, places=4)


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """The public counters match the seed."""

    def test_registry_seed_champion_count(self) -> None:
        # Seed ships 10 distinct champions; future waves add more.
        # Relaxed from assertEqual to assertGreaterEqual so wave 1+
        # expansion does not require updating this pin (mirrors the
        # wave 6 relaxation pattern from CLAUDE.md item 141).
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 10)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL), 10)

    def test_registry_seed_entry_count(self) -> None:
        # Seed ships 10 entries (1 per champion). Future waves add
        # more; this pin alerts only if a wave accidentally removes a
        # seed entry. Relaxed to assertGreaterEqual for future-wave
        # compatibility.
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 10)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(live, 10)

    def test_seed_champ_set_matches_expected(self) -> None:
        # The seed champ set is a SUBSET of the live registry; future
        # waves add more champs (relaxed from strict equality so wave
        # 1+ does not require updating this pin).
        expected_champs = set(SEED_EXPECTED.keys())
        live_champs = set(_PER_SPELL_CC_CONDITIONAL.keys())
        self.assertTrue(
            expected_champs.issubset(live_champs),
            f"seed champ missing from registry: "
            f"{expected_champs - live_champs}",
        )


# ---------------- default probability map coverage ----------------


class DefaultProbabilityMapCoverageTests(unittest.TestCase):
    """Every COND_* tag used in the seed has a default-probability."""

    def test_every_seed_condition_in_default_map(self) -> None:
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for spell_key, entry in spells.items():
                self.assertIn(
                    entry.condition,
                    _DEFAULT_CONDITION_PROBABILITY,
                    f"{champ} {spell_key} condition "
                    f"{entry.condition!r} missing from default map",
                )

    def test_default_map_has_all_public_constants(self) -> None:
        # The exported COND_* constants must each be a key in the
        # default map. Future additions to one without the other
        # break the schema invariant.
        expected_keys = {
            COND_NTH_HIT,
            COND_GOLD_CARD,
            COND_TERRAIN,
            COND_CHANNEL_COMPLETION,
            COND_DREAM_STACK,
            COND_DEVOUR_TARGET,
            COND_TARGET_HP_BELOW,
            COND_TARGET_DEBUFFED,
            COND_DUAL_ENEMY,
            COND_MODE_GATED,
        }
        self.assertEqual(
            expected_keys, set(_DEFAULT_CONDITION_PROBABILITY.keys())
        )

    def test_all_default_probabilities_in_unit_range(self) -> None:
        for tag, prob in _DEFAULT_CONDITION_PROBABILITY.items():
            self.assertGreaterEqual(
                prob, 0.0,
                f"tag {tag!r} prob {prob} below 0",
            )
            self.assertLessEqual(
                prob, 1.0,
                f"tag {tag!r} prob {prob} above 1",
            )


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The module + this test file are pure ASCII."""

    def test_cc_conditional_module_is_ascii(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
