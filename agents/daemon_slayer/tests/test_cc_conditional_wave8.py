"""Wave 8 cc_conditional expansion tests (ENGINE 1.45.0, 2026-05-22).

Wave 8 ships +3 entries / +3 net-new champions closing prior-wave
REJECT carries that DO NOT need the Meraki extractor schema lift:

  * Morgana R Soul Shackles (channel-completion-conditional stun)
    - wave 8 unconditional REJECT (item 146) + wave 9 REJECT (item
      147) both said "belongs in cc_conditional parallel to Karma W".
  * Seraphine E Beat Drop (debuffed-target-conditional stun)
    - wave 4 / 8 / 9 REJECT notes said "target-state-conditional".
  * Evelynn W Allure (channel-completion-conditional charm)
    - wave 4 + wave 8 REJECT notes said "detonation-on-Eve-attack
      conditional charm".

Tests pin:
  * per-entry rank-tuple value pins for all 3 entries
  * registry growth: 36 entries / 32 champions -> 39 / 35 (entries
    pinned via assertGreaterEqual for future-wave compatibility)
  * existing seed preservation (wave 0/1/2/3/4/5/6 entries unchanged)
  * EngineVersionCurrentTests: assertGreaterEqual((1, 45, 0))
  * ASCII hygiene (no em-dashes / en-dashes / smart quotes)
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_conditional import (
    COND_CHANNEL_COMPLETION,
    COND_TARGET_DEBUFFED,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    _PER_SPELL_CC_CONDITIONAL,
    ConditionalCcEntry,
)


class WaveEightNewEntryShapeTests(unittest.TestCase):
    """Each new wave-8 entry exists + has the canonical fields."""

    def test_morgana_r_entry_exists(self):
        self.assertIn("Morgana", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["Morgana"])
        entry = _PER_SPELL_CC_CONDITIONAL["Morgana"]["R"]
        self.assertIsInstance(entry, ConditionalCcEntry)

    def test_seraphine_e_entry_exists(self):
        self.assertIn("Seraphine", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Seraphine"])
        entry = _PER_SPELL_CC_CONDITIONAL["Seraphine"]["E"]
        self.assertIsInstance(entry, ConditionalCcEntry)

    def test_evelynn_w_entry_exists(self):
        self.assertIn("Evelynn", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("W", _PER_SPELL_CC_CONDITIONAL["Evelynn"])
        entry = _PER_SPELL_CC_CONDITIONAL["Evelynn"]["W"]
        self.assertIsInstance(entry, ConditionalCcEntry)

    def test_morgana_r_field_shape(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Morgana"]["R"]
        self.assertEqual(entry.champion, "Morgana")
        self.assertEqual(entry.spell, "R")
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertGreater(entry.probability, 0.0)
        self.assertLessEqual(entry.probability, 1.0)

    def test_seraphine_e_field_shape(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Seraphine"]["E"]
        self.assertEqual(entry.champion, "Seraphine")
        self.assertEqual(entry.spell, "E")
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertGreater(entry.probability, 0.0)
        self.assertLessEqual(entry.probability, 1.0)

    def test_evelynn_w_field_shape(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Evelynn"]["W"]
        self.assertEqual(entry.champion, "Evelynn")
        self.assertEqual(entry.spell, "W")
        self.assertEqual(entry.cc_kind, "charm")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertGreater(entry.probability, 0.0)
        self.assertLessEqual(entry.probability, 1.0)


class WaveEightValuePinsTests(unittest.TestCase):
    """Per-entry rank-tuple values match Meraki 16.10.1 Disable/Stun
    Duration blocks exactly."""

    def test_morgana_r_durations_pin(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Morgana"]["R"]
        # Meraki 16.10.1 Soul Shackles Stun Duration: 1.5/1.75/2.0
        # across 3 ranks (R has 3 ranks).
        self.assertEqual(entry.durations_s, (1.5, 1.75, 2.0))
        self.assertEqual(len(entry.durations_s), 3)

    def test_seraphine_e_durations_pin(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Seraphine"]["E"]
        # Meraki 16.10.1 Beat Drop Disable Duration: 1.1/1.2/1.3/1.4/
        # 1.5 across 5 ranks (E has 5 ranks).
        self.assertEqual(entry.durations_s, (1.1, 1.2, 1.3, 1.4, 1.5))
        self.assertEqual(len(entry.durations_s), 5)

    def test_evelynn_w_durations_pin(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Evelynn"]["W"]
        # Meraki 16.10.1 Allure Disable Duration: 1.25/1.5/1.75/2.0/
        # 2.25 across 5 ranks (W has 5 ranks).
        self.assertEqual(entry.durations_s, (1.25, 1.5, 1.75, 2.0, 2.25))
        self.assertEqual(len(entry.durations_s), 5)


class WaveEightNewChampionsTests(unittest.TestCase):
    """Wave 8 introduces 3 NEW champions to cc_conditional."""

    def test_morgana_is_net_new_in_cc_conditional(self):
        # Morgana has no other conditional CC entries (no wave 1-7
        # entries on Q/W/E).
        morgana_spells = _PER_SPELL_CC_CONDITIONAL.get("Morgana", {})
        self.assertEqual(set(morgana_spells.keys()), {"R"})

    def test_seraphine_is_net_new_in_cc_conditional(self):
        seraphine_spells = _PER_SPELL_CC_CONDITIONAL.get("Seraphine", {})
        self.assertEqual(set(seraphine_spells.keys()), {"E"})

    def test_evelynn_is_net_new_in_cc_conditional(self):
        evelynn_spells = _PER_SPELL_CC_CONDITIONAL.get("Evelynn", {})
        self.assertEqual(set(evelynn_spells.keys()), {"W"})


class RegistryGrowthTests(unittest.TestCase):
    """Wave 8 grows the registry 36/32 -> 39/35."""

    def test_registry_total_entries_at_least_39(self):
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 39)

    def test_registry_total_champions_at_least_35(self):
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 35)

    def test_morgana_seraphine_evelynn_present_in_champ_set(self):
        champs = set(_PER_SPELL_CC_CONDITIONAL.keys())
        self.assertIn("Morgana", champs)
        self.assertIn("Seraphine", champs)
        self.assertIn("Evelynn", champs)


class ExistingSeedPreservedTests(unittest.TestCase):
    """Wave 0-7 entries unchanged by wave 8."""

    def test_brand_r_preserved(self):
        # Brand R wave 0 nth_hit 3-stack stun.
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["R"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, "nth_hit")

    def test_karma_w_preserved(self):
        # Karma W wave 1 channel-completion root - the canonical
        # parallel for Morgana R.
        entry = _PER_SPELL_CC_CONDITIONAL["Karma"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)

    def test_brand_q_preserved(self):
        # Brand Q wave 6 target_debuffed stun (multi-wave coexistence
        # with Brand R).
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["Q"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)

    def test_aatrox_q_and_w_preserved(self):
        # Aatrox Q wave 3 + Aatrox W wave 4 multi-wave coexistence.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Aatrox"])
        self.assertIn("W", _PER_SPELL_CC_CONDITIONAL["Aatrox"])

    def test_morgana_q_NOT_added(self):
        # Morgana Q Dark Binding is unconditional (already in
        # _PER_SPELL_CC_DURATIONS); do NOT add to cc_conditional.
        morgana_spells = _PER_SPELL_CC_CONDITIONAL.get("Morgana", {})
        self.assertNotIn("Q", morgana_spells)

    def test_evelynn_r_NOT_added(self):
        # Evelynn R Last Caress is damage only, no CC.
        evelynn_spells = _PER_SPELL_CC_CONDITIONAL.get("Evelynn", {})
        self.assertNotIn("R", evelynn_spells)

    def test_seraphine_r_NOT_added(self):
        # Seraphine R Encore is unconditional (already in
        # _PER_SPELL_CC_DURATIONS wave 4).
        seraphine_spells = _PER_SPELL_CC_CONDITIONAL.get("Seraphine", {})
        self.assertNotIn("R", seraphine_spells)


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_at_least_1_45_0(self):
        parts = tuple(int(p) for p in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 45, 0))


class AsciiHygieneTests(unittest.TestCase):
    def test_no_non_ascii_in_wave8_entries(self):
        # The 3 wave-8 entry notes must be pure ASCII.
        for champ_spell in [("Morgana", "R"), ("Seraphine", "E"), ("Evelynn", "W")]:
            champ, spell = champ_spell
            entry = _PER_SPELL_CC_CONDITIONAL[champ][spell]
            with self.subTest(champ=champ, spell=spell):
                try:
                    entry.notes.encode("ascii")
                except UnicodeEncodeError as exc:
                    self.fail(
                        f"Non-ASCII in {champ} {spell} notes: {exc}"
                    )

    def test_test_file_is_ascii(self):
        # This test file itself must be ASCII clean.
        p = Path(__file__)
        text = p.read_text(encoding="utf-8")
        # Build BAD chars via chr() so this assertion stays clean
        # against its own scan.
        bad_chars = "".join(
            chr(c) for c in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2192)
        )
        bad = [c for c in text if c in bad_chars]
        self.assertEqual(bad, [], f"Non-ASCII bytes in test file: {bad!r}")


if __name__ == "__main__":
    unittest.main()
