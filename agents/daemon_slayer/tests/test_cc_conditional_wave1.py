"""ENGINE 1.37.0 (2026-05-22) - cc_conditional wave 1 expansion.

Tests the wave 1 expansion of the conditional CC registry: +8 entries
across +8 new champions drawn from the wave 4/5/6/7 REJECT lists in
CLAUDE.md items 138/139/140/141.

The 8 new entries are:
  * Bard Q Cosmic Binding (terrain) - wall-bounce double stun
  * Karma W Focused Resolve (channel_completion) - full-tether root
  * Taliyah W Seismic Shove (channel_completion) - recast knockup
  * Kennen E Lightning Rush (nth_hit) - Mark of the Storm stun
  * KSante Q Ntofo Strikes (nth_hit) - 3rd-cast root
  * Ornn Q Volcanic Rupture (debuffed_target) - post-Brittle knockup
  * Xayah E Bladecaller (nth_hit) - 3+ feathers root
  * Fiora W Riposte (debuffed_target) - parry-stun

These re-use existing condition tags exclusively - no new tag constants.
Registry growth: 10 champs / 10 entries -> 18 champs / 18 entries.

KSante Q + Ornn Q each coexist on the same champion's spell map as a
prior unconditional registry entry (KSante R wave 5; Ornn R wave 7) -
the conditional + unconditional registries are independent so no
clobber.

Coverage classes:
  * ``WaveOneNewEntryShapeTests`` - each new entry has correct schema
    (champion / spell / cc_kind / durations_s shape / condition tag /
    probability).
  * ``WaveOneValuePinsTests`` - per-entry value pins.
  * ``WaveOneNewChampionsTests`` - each new champion appears in
    registry; case-sensitive DDragon ids.
  * ``RegistryGrowthTests`` - new totals 18 champs / 18 entries.
  * ``ExistingSeedPreservedTests`` - all 10 original entries still
    present + byte-identical.
  * ``MultiSpellCoexistenceTests`` - KSante / Ornn coexist between
    conditional + unconditional registries.
  * ``AsciiHygieneTests`` - module + this test file pure ASCII.
"""

from __future__ import annotations

import pathlib
import unittest

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


# ---------------- wave 1 expected expansion map ----------------


# Each wave-1 entry pin (champion, spell, cc_kind, durations_s,
# condition, probability). Pinned to detect schema regressions.
WAVE_ONE_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
    "Bard": {"Q": {
        "cc_kind": "stun",
        "durations_s": (1.5, 1.75, 2.0, 2.25, 2.5),
        "condition": COND_TERRAIN,
        "probability": 0.3,
    }},
    "Karma": {"W": {
        "cc_kind": "root",
        "durations_s": (1.5, 1.625, 1.75, 1.875, 2.0),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.4,
    }},
    "Taliyah": {"W": {
        "cc_kind": "knockup",
        "durations_s": (0.75,),
        "condition": COND_CHANNEL_COMPLETION,
        "probability": 0.5,
    }},
    "Kennen": {"E": {
        "cc_kind": "stun",
        "durations_s": (1.25,),
        "condition": COND_NTH_HIT,
        "probability": 0.6,
    }},
    "KSante": {"Q": {
        "cc_kind": "root",
        "durations_s": (0.75,),
        "condition": COND_NTH_HIT,
        "probability": 0.7,
    }},
    "Ornn": {"Q": {
        "cc_kind": "knockup",
        "durations_s": (1.5,),
        "condition": COND_TARGET_DEBUFFED,
        "probability": 0.5,
    }},
    "Xayah": {"E": {
        "cc_kind": "root",
        "durations_s": (1.25,),
        "condition": COND_NTH_HIT,
        "probability": 0.6,
    }},
    "Fiora": {"W": {
        "cc_kind": "stun",
        "durations_s": (1.5,),
        "condition": COND_TARGET_DEBUFFED,
        "probability": 0.4,
    }},
}


# ---------------- pre-wave-1 seed expected map ----------------


# The 10 seed entries from items 138/139/140 - re-pinned here to
# verify they are not clobbered by wave 1 setdefault construction.
PRE_WAVE_SEED_EXPECTED: dict[str, dict[str, dict[str, object]]] = {
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


# ---------------- new entry shape contract ----------------


class WaveOneNewEntryShapeTests(unittest.TestCase):
    """Each wave-1 entry has the expected schema."""

    def test_all_wave_one_champs_present_in_registry(self) -> None:
        for champ in WAVE_ONE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"wave 1 champ {champ} missing from registry",
            )

    def test_all_wave_one_spells_present(self) -> None:
        for champ, spells in WAVE_ONE_EXPECTED.items():
            for spell_key in spells:
                self.assertIn(
                    spell_key, _PER_SPELL_CC_CONDITIONAL[champ],
                    f"wave 1 {champ} {spell_key} missing from spell map",
                )

    def test_all_wave_one_entries_are_conditional_cc_entry_dataclass(self) -> None:
        for champ, spells in WAVE_ONE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIsInstance(entry, ConditionalCcEntry)

    def test_all_wave_one_entries_carry_notes(self) -> None:
        for champ, spells in WAVE_ONE_EXPECTED.items():
            for spell_key in spells:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertTrue(
                    entry.notes,
                    f"wave 1 {champ} {spell_key} missing notes",
                )

    def test_all_wave_one_entries_use_existing_tags_only(self) -> None:
        # No new tag constants introduced in wave 1.
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
        for champ in WAVE_ONE_EXPECTED:
            for spell_key in WAVE_ONE_EXPECTED[champ]:
                entry = _PER_SPELL_CC_CONDITIONAL[champ][spell_key]
                self.assertIn(
                    entry.condition,
                    allowed_tags,
                    f"{champ} {spell_key} uses unknown tag {entry.condition!r}",
                )


# ---------------- per-entry value pins ----------------


class WaveOneValuePinsTests(unittest.TestCase):
    """Per-entry value pins for each wave-1 entry."""

    def test_bard_q_cosmic_binding(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Bard"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5, 1.75, 2.0, 2.25, 2.5))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_karma_w_focused_resolve(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Karma"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.5, 1.625, 1.75, 1.875, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.4)

    def test_taliyah_w_seismic_shove(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Taliyah"]["W"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)

    def test_kennen_e_lightning_rush(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Kennen"]["E"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.25,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.6)

    def test_ksante_q_ntofo_strikes(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["KSante"]["Q"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.7)

    def test_ornn_q_volcanic_rupture(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Ornn"]["Q"]
        self.assertEqual(entry.cc_kind, "knockup")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.5)

    def test_xayah_e_bladecaller(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Xayah"]["E"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (1.25,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.6)

    def test_fiora_w_riposte(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Fiora"]["W"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.4)


# ---------------- new champions contract ----------------


class WaveOneNewChampionsTests(unittest.TestCase):
    """Each new champion appears in registry with case-sensitive id."""

    def test_bard_in_registry(self) -> None:
        self.assertIn("Bard", _PER_SPELL_CC_CONDITIONAL)

    def test_karma_in_registry(self) -> None:
        self.assertIn("Karma", _PER_SPELL_CC_CONDITIONAL)

    def test_taliyah_in_registry(self) -> None:
        self.assertIn("Taliyah", _PER_SPELL_CC_CONDITIONAL)

    def test_kennen_in_registry(self) -> None:
        self.assertIn("Kennen", _PER_SPELL_CC_CONDITIONAL)

    def test_ksante_in_registry(self) -> None:
        # Canonical DDragon id - punctuation-stripped per portrait
        # convention. NOT "K'Sante" with apostrophe.
        self.assertIn("KSante", _PER_SPELL_CC_CONDITIONAL)
        self.assertNotIn("K'Sante", _PER_SPELL_CC_CONDITIONAL)

    def test_ornn_in_registry(self) -> None:
        self.assertIn("Ornn", _PER_SPELL_CC_CONDITIONAL)

    def test_xayah_in_registry(self) -> None:
        self.assertIn("Xayah", _PER_SPELL_CC_CONDITIONAL)

    def test_fiora_in_registry(self) -> None:
        self.assertIn("Fiora", _PER_SPELL_CC_CONDITIONAL)

    def test_lowercase_variants_not_in_registry(self) -> None:
        # Case-sensitive DDragon ids only.
        for champ in WAVE_ONE_EXPECTED:
            self.assertNotIn(
                champ.lower(),
                _PER_SPELL_CC_CONDITIONAL,
                f"lowercase {champ.lower()!r} unexpectedly in registry",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Wave 1 grows registry from 10/10 to 18/18."""

    def test_registry_total_champions_18(self) -> None:
        # Wave 1 ships >= 18 champs; future waves expand. Mirrors
        # wave 6/7 _PER_SPELL_CC_DURATIONS pattern (item 141 Slice A
        # relaxation). Pin lower bound only.
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 18)
        self.assertGreaterEqual(len(_PER_SPELL_CC_CONDITIONAL), 18)

    def test_registry_total_entries_18(self) -> None:
        # Wave 1 ships >= 18 entries; future waves expand. Mirrors
        # wave 6/7 _PER_SPELL_CC_DURATIONS pattern (item 141 Slice A
        # relaxation). Pin lower bound only.
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 18)
        live = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(live, 18)

    def test_wave_one_adds_8_champions_over_seed(self) -> None:
        seed_champs = set(PRE_WAVE_SEED_EXPECTED.keys())
        wave_one_champs = set(WAVE_ONE_EXPECTED.keys())
        # Wave 1 should add exactly 8 NEW champions that were not
        # in the seed.
        new_in_wave_one = wave_one_champs - seed_champs
        self.assertEqual(len(new_in_wave_one), 8)

    def test_wave_one_champs_have_no_seed_overlap(self) -> None:
        # No wave-1 champ should be a seed champ (seed champs already
        # have their entries; wave 1 adds new champions).
        seed_champs = set(PRE_WAVE_SEED_EXPECTED.keys())
        for champ in WAVE_ONE_EXPECTED:
            self.assertNotIn(
                champ, seed_champs,
                f"{champ} is a seed champion AND a wave-1 champion - "
                "this would be a clobber",
            )


# ---------------- existing seed preserved contract ----------------


class ExistingSeedPreservedTests(unittest.TestCase):
    """All 10 seed entries from items 138/139/140 still byte-identical."""

    def test_all_seed_champs_still_present(self) -> None:
        for champ in PRE_WAVE_SEED_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_CONDITIONAL,
                f"seed champ {champ} lost in wave 1",
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

    def test_tahmkench_r_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["TahmKench"]["R"]
        self.assertEqual(entry.cc_kind, "suppression")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_DEVOUR_TARGET)
        self.assertEqual(entry.probability, 0.4)

    def test_volibear_q_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Volibear"]["Q"]
        self.assertEqual(entry.cc_kind, "knockback")
        self.assertEqual(entry.durations_s, (0.75,))
        self.assertEqual(entry.condition, COND_TERRAIN)
        self.assertEqual(entry.probability, 0.3)

    def test_warwick_r_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Warwick"]["R"]
        self.assertEqual(entry.cc_kind, "suppression")
        self.assertEqual(entry.durations_s, (1.5, 1.75, 2.0))
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(entry.probability, 0.5)

    def test_viktor_w_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Viktor"]["W"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_NTH_HIT)
        self.assertEqual(entry.probability, 0.6)

    def test_mordekaiser_r_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Mordekaiser"]["R"]
        self.assertEqual(entry.cc_kind, "banishment")
        self.assertEqual(entry.durations_s, (7.0,))
        self.assertEqual(entry.condition, COND_MODE_GATED)
        self.assertEqual(entry.probability, 1.0)

    def test_sett_e_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Sett"]["E"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.durations_s, (1.0,))
        self.assertEqual(entry.condition, COND_DUAL_ENEMY)
        self.assertEqual(entry.probability, 0.6)

    def test_vex_e_unchanged(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Vex"]["E"]
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.durations_s, (1.0, 1.125, 1.25, 1.375, 1.5))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertEqual(entry.probability, 0.5)


# ---------------- multi-spell coexistence with unconditional ----------------


class MultiSpellCoexistenceTests(unittest.TestCase):
    """KSante + Ornn have entries in both conditional + unconditional."""

    def test_ksante_r_in_unconditional_registry(self) -> None:
        # KSante R All Out is in the unconditional wave-5 registry.
        # KSante Q (this wave 1) is in the conditional registry.
        # Both coexist independently because they live in different
        # registries (cc_conditional.py vs ability_dps.py).
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("KSante", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["KSante"])
        # KSante R is NOT in the conditional registry (it is
        # unconditional).
        self.assertNotIn("R", _PER_SPELL_CC_CONDITIONAL.get("KSante", {}))
        # KSante Q IS in the conditional registry (this wave).
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["KSante"])

    def test_ornn_r_in_unconditional_registry(self) -> None:
        # Ornn R Call of the Forge God is in the unconditional wave-7
        # registry. Ornn Q (this wave 1) is in the conditional
        # registry.
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        self.assertIn("Ornn", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Ornn"])
        # Ornn Q IS in the conditional registry (this wave).
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Ornn"])


# ---------------- aggregator regression contract ----------------


class AggregatorWaveOneTests(unittest.TestCase):
    """get_total_conditional_cc_seconds returns expected values."""

    def test_bard_q_weighted_max_rank(self) -> None:
        # Bard Q max rank = 2.5 * 0.3 = 0.75
        total = get_total_conditional_cc_seconds("Bard")
        self.assertAlmostEqual(total, 0.75, places=4)

    def test_karma_w_weighted_max_rank(self) -> None:
        # Karma W wave 1 entry contribution = 2.0 * 0.4 = 0.8.
        # Wave 10 (ENGINE 1.47.0) added a Karma W form_index=1 entry
        # in the sidecar registry (Mantra-empowered Renewal Total Root,
        # 2.75s at mid Mantra rank * 0.4 = 1.1); the aggregator now
        # sums BOTH the primary wave 1 default-form entry AND the
        # form 1 sidecar entry. Total weighted CC at min: 0.8 (just
        # wave 1); pre-wave-10 the exact value was 0.8. Forward-compat:
        # assertGreaterEqual since future waves may add more entries
        # on the same champion.
        total = get_total_conditional_cc_seconds("Karma")
        self.assertGreaterEqual(total, 0.8)

    def test_ksante_q_weighted(self) -> None:
        # KSante Q = 0.75 * 0.7 = 0.525
        total = get_total_conditional_cc_seconds("KSante")
        self.assertAlmostEqual(total, 0.525, places=4)

    def test_fiora_w_weighted(self) -> None:
        # Fiora W = 1.5 * 0.4 = 0.6
        total = get_total_conditional_cc_seconds("Fiora")
        self.assertAlmostEqual(total, 0.6, places=4)

    def test_bard_q_raw_max_rank(self) -> None:
        # Bard Q raw max rank = 2.5
        total = get_total_conditional_cc_seconds(
            "Bard", apply_probability=False
        )
        self.assertAlmostEqual(total, 2.5, places=4)

    def test_get_conditional_entries_returns_q_for_ksante(self) -> None:
        entries = get_conditional_entries("KSante")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].spell, "Q")

    def test_get_conditional_entries_returns_q_for_ornn(self) -> None:
        # Wave 1 baseline: Ornn returns Q only.
        # Wave 15 added Ornn E (terrain-collision stun) so the
        # registry now returns 2 entries for Ornn. Relaxed
        # to assertGreaterEqual + assertIn("Q", slots) for
        # forward compat across waves.
        entries = get_conditional_entries("Ornn")
        self.assertGreaterEqual(len(entries), 1)
        slots = {e.spell for e in entries}
        self.assertIn("Q", slots)


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
