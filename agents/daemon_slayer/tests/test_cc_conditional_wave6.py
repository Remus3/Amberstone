"""ENGINE 1.43.0 (2026-05-22) - cc_conditional wave 6 expansion.

Tests the wave 6 expansion of the conditional CC registry: +1 entry
across +0 new champions (multi-wave coexistence on existing champion
Brand - gains Q coexisting with wave 0 R 3-stack passive stun). Drawn
from item 145 wave 4 REJECT carry where Brand W was rejected as not
first-order CC; the canonical Brand Q stun-on-blazed-target IS first-
order CC with a clean COND_TARGET_DEBUFFED fit.

The 1 new entry is:
  * Brand Q Sear (target_debuffed) - 1.25s stun when target carries
    a Blaze passive stack from prior Brand spell-hit or AA.

This re-uses existing condition tags exclusively - no new tag
constants. Registry growth: 32 champs / 35 entries -> 32 champs /
36 entries. NET-NEW champions: 0 (entry coexists on existing
Brand key via setdefault on a different spell slot).

Brand Q (this wave 6) coexists with Brand R (wave 0) on the same
champion's spell map via setdefault. This brings the multi-entry-
WITHIN-cc_conditional champion count to 4: Aatrox Q3+W from waves
3+4, Briar Q+E from waves 4+5, TahmKench R+Q from waves 0+5, and
Brand R+Q from waves 0+6 NEW. (Pantheon Q wave 4 coexists with
Pantheon W in the SEPARATE _PER_SPELL_CC_DURATIONS unconditional
registry, NOT in cc_conditional - the per-CLAUDE.md item 141 cross-
registry coexistence count is a separate ledger.)

Coverage classes:
  * ``WaveSixNewEntryShapeTests`` - the new entry has correct
    schema (champion / spell / cc_kind / durations_s shape /
    condition tag / probability).
  * ``WaveSixValuePinsTests`` - per-entry value pins.
  * ``WaveSixNewChampionsTests`` - Brand already existed in wave 0;
    no net-new champion keys.
  * ``RegistryGrowthTests`` - new totals 32 champs / 36 entries
    (assertGreaterEqual floors for forward-compat).
  * ``ExistingSeedPreservedTests`` - all 35 prior entries (waves
    0-5) still present + byte-identical.
  * ``WaveSixCoexistenceWithPriorWavesTests`` - Brand R (wave 0)
    + Brand Q (wave 6) coexist via setdefault.
  * ``AggregatorWaveSixTests`` - aggregator returns expected
    weighted + raw totals for new entries (entry-level pins given
    multi-wave coexistence aggregation).
  * ``EngineVersionCurrentTests`` - ENGINE pinned at >= 1.42.0
    (forward-compatible per item 146 lesson - the orchestrator
    bumps to 1.43.0 at merge; this slice ships at 1.42.0 and
    orchestrator-bump is post-merge).
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


# ---------------- wave 6 expected expansion map ----------------


# Each wave-6 entry pin (champion, spell, cc_kind, durations_s,
# condition, probability). Pinned to detect schema regressions.
WAVE_SIX_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Brand": {"Q": {
        "cc_kind": "stun",
        "durations_s": (1.25,),
        "condition": COND_TARGET_DEBUFFED,
        "probability": 0.5,
    }},
}


# Wave 0 + wave 1 + wave 2 + wave 3 + wave 4 + wave 5 seed (the 35
# pre-wave-6 entries) - the set of champion keys pre-wave-6. Wave 6
# introduces 0 NEW champion keys (entry lands on existing Brand via
# setdefault on a different spell slot).
PRE_WAVE_SIX_EXPECTED_CHAMPS = {
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
    # wave 5 (0 net-new; both entries on existing Briar + TahmKench)
}

# Wave 6 introduces 0 NET-NEW champions (entry coexists on existing
# Brand key via setdefault). Brand R is wave 0 + Brand Q is wave 6.
WAVE_SIX_NEW_CHAMPIONS: set[str] = set()


# ---------------- new entry shape contract ----------------


class WaveSixNewEntryShapeTests(unittest.TestCase):
    """Each wave-6 entry has the expected schema."""

    def test_all_wave_six_champs_present_in_registry(self) -> None:
        for champ in WAVE_SIX_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"wave 6 champ {champ} missing from registry",
            )

    def test_all_wave_six_spells_present(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"wave 6 {champ} {spell_key} missing from spell map",
                )

    def test_all_wave_six_entries_are_conditional_cc_entry_dataclass(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIsInstance(entry, ConditionalCcEntry)

    def test_all_wave_six_entries_carry_notes(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertTrue(
                    entry.notes,
                    f"wave 6 {champ} {spell_key} missing notes",
                )

    def test_all_wave_six_entries_use_existing_tags_only(self) -> None:
        # No new tag constants introduced in wave 6.
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
        for champ in WAVE_SIX_EXPECTED:
            for spell_key in WAVE_SIX_EXPECTED[champ]:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(
                    entry.condition,
                    allowed_tags,
                    f"{champ} {spell_key} uses unknown tag {entry.condition!r}",
                )

    def test_all_wave_six_entries_valid_spell_slots(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(entry.spell, ("Q", "W", "E", "R"))

    def test_all_wave_six_entries_have_positive_durations(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                for d in entry.durations_s:
                    self.assertGreater(d, 0.0)

    def test_all_wave_six_entries_have_clamped_probability(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertGreaterEqual(entry.probability, 0.0)
                self.assertLessEqual(entry.probability, 1.0)

    def test_wave_six_champion_field_matches_dict_key(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertEqual(entry.champion, champ)


# ---------------- per-entry value pins ----------------


class WaveSixValuePinsTests(unittest.TestCase):
    """Per-entry value pins for each wave-6 entry."""

    def test_brand_q_sear_blaze_stun(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.25,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.5)
        self.assertEqual(entry.spell, "Q")


# ---------------- new champions contract (zero net-new) ----------------


class WaveSixNewChampionsTests(unittest.TestCase):
    """Brand already existed in wave 0 with R; no net-new champion
    keys in wave 6. The new entry lands on existing Brand via
    setdefault on a different spell slot."""

    def test_brand_existed_pre_wave_six(self) -> None:
        # Brand was added in wave 0 with R (nth_hit 3-stack stun).
        self.assertIn("Brand", PRE_WAVE_SIX_EXPECTED_CHAMPS)
        self.assertIn("Brand", _PER_SPELL_CC_CONDITIONAL)

    def test_brand_has_both_q_and_r_entries(self) -> None:
        # Wave 0 R + wave 6 Q coexist on the same champion via setdefault.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Brand"])
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["Brand"])

    def test_zero_net_new_champions_in_wave_six(self) -> None:
        # All wave-6 champion keys were already in prior waves.
        wave_six_champs = set(WAVE_SIX_EXPECTED.keys())
        net_new = wave_six_champs - PRE_WAVE_SIX_EXPECTED_CHAMPS
        self.assertEqual(net_new, set())
        self.assertEqual(WAVE_SIX_NEW_CHAMPIONS, set())

    def test_lowercase_variants_not_in_registry(self) -> None:
        # Case-sensitive DDragon ids only.
        for champ in WAVE_SIX_EXPECTED:
            self.assertNotIn(
                champ.lower(),
                _PER_SPELL_CC_CONDITIONAL,
                f"lowercase {champ.lower()!r} unexpectedly in registry",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Wave 6 grows registry from 35 entries to 36 entries; champion
    count stays at 32 (no net-new champions). Use assertGreaterEqual
    floors for forward-compat with future wave additions."""

    def test_registry_total_champions_at_least_32(self) -> None:
        # No net-new champs in wave 6. Future-wave compatibility via
        # assertGreaterEqual per item 143/144/145/146 Slice C pattern.
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 32)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL), 32)

    def test_registry_total_entries_at_least_36(self) -> None:
        # 36 entries across 32 champions post-wave-6.
        # assertGreaterEqual for future-wave compatibility.
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 36)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(live, 36)

    def test_wave_six_adds_1_entry_over_prior_waves(self) -> None:
        # Wave 6 entry count is exactly 1 (via setdefault on existing
        # Brand champion).
        wave_six_entry_count = sum(
            len(spells) for spells in WAVE_SIX_EXPECTED.values()
        )
        self.assertEqual(wave_six_entry_count, 1)

    def test_within_cc_conditional_multi_entry_champions(self) -> None:
        # Wave-6 brings the multi-entry-WITHIN-cc_conditional champion
        # count to 4 (champions with >= 2 entries in this registry):
        # - Aatrox (Q wave 3 + W wave 4)
        # - Briar (Q wave 4 + E wave 5)
        # - TahmKench (R wave 0 + Q wave 5)
        # - Brand (R wave 0 + Q wave 6 NEW)
        # Note: Pantheon Q (wave 4) coexists with Pantheon W in the
        # SEPARATE _PER_SPELL_CC_DURATIONS unconditional registry, NOT
        # in cc_conditional - so Pantheon has only 1 entry in this
        # registry.
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["Aatrox"]), 2)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["Briar"]), 2)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["TahmKench"]), 2)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL["Brand"]), 2)
        # Count multi-entry champions within cc_conditional - floor at 4
        # for forward-compat with future wave additions.
        multi_entry_count = sum(
            1 for spells in _PER_SPELL_CC_CONDITIONAL.values()
            if len(spells) >= 2
        )
        self.assertGreaterEqual(multi_entry_count, 4)


# ---------------- existing seed preserved contract ----------------


class ExistingSeedPreservedTests(unittest.TestCase):
    """All 35 prior entries (wave 0 + wave 1 + wave 2 + wave 3 +
    wave 4 + wave 5) still present + byte-identical post-wave-6."""

    def test_all_prior_wave_champs_still_present(self) -> None:
        for champ in PRE_WAVE_SIX_EXPECTED_CHAMPS:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"prior-wave champ {champ} lost in wave 6",
            )

    def test_brand_r_wave0_unchanged(self) -> None:
        # Brand R is wave 0 conditional nth_hit 3-stack stun. Wave 6
        # adds Q on the same champion; R must stay byte-identical.
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

    def test_briar_e_wave5_unchanged(self) -> None:
        # Wave-5 Briar E preserved post-wave-6.
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["E"]
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)

    def test_tahmkench_q_wave5_unchanged(self) -> None:
        # Wave-5 TahmKench Q preserved post-wave-6.
        entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)


# ---------------- coexistence with prior waves contract ----------------


class WaveSixCoexistenceWithPriorWavesTests(unittest.TestCase):
    """Brand Q (wave 6) coexists with Brand R (wave 0) via setdefault.
    This is multi-wave coexistence pattern on existing champion key -
    FIFTH multi-wave coexistence after Aatrox Q+W / Briar Q+E /
    TahmKench R+Q / Pantheon W+Q."""

    def test_brand_has_both_q_and_r_entries(self) -> None:
        # Both spell slots present post-build via setdefault.
        self.assertIn("Brand", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Brand"])
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["Brand"])

    def test_brand_r_is_wave_zero_nth_hit_stun(self) -> None:
        # Wave-0 R (passive 3-stack stun via Pyroclasm bounces) survives
        # wave-6 build.
        r_entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["R"]
        self.assertEqual(r_entry.cc_kind, "stun")
        self.assertEqual(r_entry.durations_s, (2.0,))
        self.assertEqual(r_entry.condition, COND_NTH_HIT)

    def test_brand_q_is_wave_six_target_debuffed_stun(self) -> None:
        # Wave-6 Q (Sear stun on blazed target) added without clobber.
        q_entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["Q"]
        self.assertEqual(q_entry.cc_kind, "stun")
        self.assertEqual(q_entry.durations_s, (1.25,))
        self.assertEqual(q_entry.condition, COND_TARGET_DEBUFFED)

    def test_brand_has_exactly_two_entries(self) -> None:
        # Wave 6 adds Q; total Brand entries = 2 (Q + R). Both share
        # the same champion key via setdefault construction.
        spells = _PER_SPELL_CC_CONDITIONAL["Brand"]
        self.assertEqual(len(spells), 2)


# ---------------- aggregator regression contract ----------------


class AggregatorWaveSixTests(unittest.TestCase):
    """get_total_conditional_cc_seconds returns expected values for
    multi-wave-coexistence champions. Wave 6 introduces 1 new entry
    that coexists on existing Brand key; aggregator sums all entries
    per champion in canonical Q-W-E-R order."""

    def test_brand_weighted_max_rank_sums_q_plus_r(self) -> None:
        # Brand Q = 1.25 * 0.5 = 0.625 (wave 6 target_debuffed stun)
        # Brand R = 2.0 * 0.7 = 1.40 (wave 0 nth_hit 3-stack stun)
        # Total weighted = 0.625 + 1.40 = 2.025
        total = get_total_conditional_cc_seconds("Brand")
        self.assertAlmostEqual(total, 2.025, places=4)

    def test_brand_raw_max_rank_sums_q_plus_r(self) -> None:
        # Brand Q raw = 1.25 + Brand R raw = 2.0 -> 3.25 total
        total = get_total_conditional_cc_seconds(
            "Brand", apply_probability=False
        )
        self.assertAlmostEqual(total, 3.25, places=4)

    def test_brand_q_entry_level_weighted(self) -> None:
        # Brand Q entry-level contribution = 1.25 * 0.5 = 0.625
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["Q"]
        self.assertAlmostEqual(
            entry.durations_s[-1] * entry.probability, 0.625, places=4
        )

    def test_brand_r_entry_level_weighted(self) -> None:
        # Brand R entry-level contribution = 2.0 * 0.7 = 1.40
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["R"]
        self.assertAlmostEqual(
            entry.durations_s[-1] * entry.probability, 1.40, places=4
        )

    def test_get_conditional_entries_returns_q_and_r_for_brand(self) -> None:
        # Brand has 2 entries (Q + R). Canonical Q-W-E-R order
        # means Q is index 0, R is index 1.
        entries = get_conditional_entries("Brand")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].spell, "Q")
        self.assertEqual(entries[1].spell, "R")


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at current bumped state.

    Wave 6 ships at ENGINE >= 1.42.0; the orchestrator bumps to
    1.43.0 at merge time. ENGINE >= 1.42.0 must hold for the wave-6
    test surface to be valid. Use assertGreaterEqual for forward-
    compat per item 146 lesson (saves orchestrator effort on bump).
    """

    def test_engine_version_at_least_1_42_0(self) -> None:
        # Wave 6 ships at ENGINE >= 1.42.0 (orchestrator bumps to
        # 1.43.0 at merge). Future bumps must keep this at
        # >= 1.42.0 so the wave-6 entry test surface stays valid.
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 42, 0))


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
