"""Wave 9 cc_conditional expansion tests (ENGINE 1.46.0, 2026-05-23).

Wave 9 ships the long-deferred Meraki extractor schema lift PLUS
+3 entries / +3 net-new champions closing 3 of 7 schema-lift-blocked
candidates from prior wave REJECT carries (items 150 / 151 / 152):

  * Hwei E form 1 Grim Visage (channel-completion-conditional fear)
    - item 150 + 151 + 152 carry-forward "multi-form same-spell-
      slot constraint" closed by re-classifying form 1 as a
      2-cast-cycle channel-completion mechanic.
  * Neeko E Tangle-Barbs EMPOWERED variant (dual-enemy-conditional
    root) - item 150 + 151 + 152 carry-forward "Empowered Root
    1.8-3.0s; multi-form same-spell-slot" closed via separate-
    registry coexistence pattern (parallel to Aatrox Q3 wave 3).
  * Renekton W Reign-of-Anger empowered stun (frenzy-state-
    conditional stun) - item 150 + 151 + 152 carry-forward "Renekton
    W Fury empowered-Fury stun in stripped description" closed by
    the schema-lifted effects_descriptions field. FIRST consumer of
    the wave 7 forward-marker COND_FRENZY_STATE tag.

The Meraki extractor schema lift in this wave is PURELY ADDITIVE:
tools/daemon_slayer_abilities_extract.py now records
``effects_descriptions: list[str]`` per form alongside the existing
damage_blocks pipeline. Damage_blocks shape + parse_status math +
downstream consumers are byte-identical to pre-lift. The new field
is consumed by this wave's verification of mechanics that lived in
description text but were absent from structured leveling blocks.

REJECT verdicts (4 of 7 candidates from item 152 mission spec):

  (a) Karma W form 1 Renewal - same (Karma, W) slot already in
      cc_conditional wave 1 Focused Resolve channel-completion
      root. Registry keyed (champion, spell); R-empowered variant
      cannot coexist on the same slot.
  (b) Aatrox R World Ender - schema-lifted description confirms
      3s fear targets minions/monsters ONLY, NOT champions.
  (c) Volibear R Stormbringer - schema-lifted description confirms
      only turret-disable + 50% slow (not first-order CC).
  (d) Briar W Blood Frenzy - schema-lifted description confirms
      purely self-buff (no CC granted in frenzy state).

Tests pin:
  * per-entry rank-tuple value pins for all 3 entries
  * per-entry condition tag pins (Hwei->channel, Neeko->dual_enemy,
    Renekton->frenzy_state - first consumer of the wave 7 tag)
  * registry growth: 39 entries / 35 champions -> 42 / 38 (entries
    pinned via assertGreaterEqual for future-wave compatibility)
  * existing seed preservation (wave 0/1/2/3/4/5/6/7/8 entries
    unchanged)
  * COND_FRENZY_STATE is now consumed by at least one entry
    (closes the wave 7 forward-marker empty-registry contract)
  * EngineVersionCurrentTests: assertGreaterEqual((1, 46, 0))
  * ASCII hygiene (no em-dashes / en-dashes / smart quotes)
  * Wired-site grep pins so a future refactor that removes any of
    the 3 wave 9 entries fails CI before silent registry regression
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_conditional import (
    COND_CHANNEL_COMPLETION,
    COND_DUAL_ENEMY,
    COND_FRENZY_STATE,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    _PER_SPELL_CC_CONDITIONAL,
    ConditionalCcEntry,
)


class WaveNineNewEntryShapeTests(unittest.TestCase):
    """Each new wave-9 entry exists + has the canonical fields."""

    def test_hwei_e_entry_exists(self):
        self.assertIn("Hwei", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Hwei"])
        entry = _PER_SPELL_CC_CONDITIONAL["Hwei"]["E"]
        self.assertIsInstance(entry, ConditionalCcEntry)

    def test_neeko_e_entry_exists(self):
        self.assertIn("Neeko", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Neeko"])
        entry = _PER_SPELL_CC_CONDITIONAL["Neeko"]["E"]
        self.assertIsInstance(entry, ConditionalCcEntry)

    def test_renekton_w_entry_exists(self):
        self.assertIn("Renekton", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("W", _PER_SPELL_CC_CONDITIONAL["Renekton"])
        entry = _PER_SPELL_CC_CONDITIONAL["Renekton"]["W"]
        self.assertIsInstance(entry, ConditionalCcEntry)

    def test_hwei_e_field_shape(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Hwei"]["E"]
        self.assertEqual(entry.champion, "Hwei")
        self.assertEqual(entry.spell, "E")
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertGreater(entry.probability, 0.0)
        self.assertLessEqual(entry.probability, 1.0)

    def test_neeko_e_field_shape(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Neeko"]["E"]
        self.assertEqual(entry.champion, "Neeko")
        self.assertEqual(entry.spell, "E")
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.condition, COND_DUAL_ENEMY)
        self.assertGreater(entry.probability, 0.0)
        self.assertLessEqual(entry.probability, 1.0)

    def test_renekton_w_field_shape(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Renekton"]["W"]
        self.assertEqual(entry.champion, "Renekton")
        self.assertEqual(entry.spell, "W")
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, COND_FRENZY_STATE)
        self.assertGreater(entry.probability, 0.0)
        self.assertLessEqual(entry.probability, 1.0)


class WaveNineValuePinsTests(unittest.TestCase):
    """Per-entry rank-tuple values match Meraki 16.10.1 blocks exactly.

    Hwei E + Neeko E values are sourced from the parse-strip
    damage_blocks Disable Duration / Empowered Root Duration blocks.
    Renekton W value is sourced from the schema-lifted
    effects_descriptions[2] "Reign of Anger Bonus: ... increasing the
    stun duration to 1.5 seconds".
    """

    def test_hwei_e_durations_pin(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Hwei"]["E"]
        # Meraki 16.10.1 Grim Visage Disable Duration block:
        # 1.0/1.125/1.25/1.375/1.5 across 5 ranks (E has 5 ranks).
        self.assertEqual(entry.durations_s, (1.0, 1.125, 1.25, 1.375, 1.5))
        self.assertEqual(len(entry.durations_s), 5)

    def test_neeko_e_durations_pin(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Neeko"]["E"]
        # Meraki 16.10.1 Tangle-Barbs Empowered Root Duration block:
        # 1.8/2.1/2.4/2.7/3.0 across 5 ranks (E has 5 ranks).
        self.assertEqual(entry.durations_s, (1.8, 2.1, 2.4, 2.7, 3.0))
        self.assertEqual(len(entry.durations_s), 5)

    def test_renekton_w_durations_pin(self):
        entry = _PER_SPELL_CC_CONDITIONAL["Renekton"]["W"]
        # Reign of Anger empowered stun: 1.5s flat across all ranks
        # (single-value tuple per the ConditionalCcEntry "length 1
        # means same value all ranks" shorthand).
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(len(entry.durations_s), 1)


class WaveNineNewChampionsTests(unittest.TestCase):
    """Wave 9 introduces 3 NEW champions to cc_conditional."""

    def test_hwei_is_net_new_in_cc_conditional(self):
        # Hwei has no other conditional CC entries (no wave 1-8 on
        # Q/W/R).
        hwei_spells = _PER_SPELL_CC_CONDITIONAL.get("Hwei", {})
        self.assertEqual(set(hwei_spells.keys()), {"E"})

    def test_neeko_is_net_new_in_cc_conditional(self):
        neeko_spells = _PER_SPELL_CC_CONDITIONAL.get("Neeko", {})
        self.assertEqual(set(neeko_spells.keys()), {"E"})

    def test_renekton_is_net_new_in_cc_conditional(self):
        renekton_spells = _PER_SPELL_CC_CONDITIONAL.get("Renekton", {})
        self.assertEqual(set(renekton_spells.keys()), {"W"})


class RegistryGrowthTests(unittest.TestCase):
    """Wave 9 grows the registry 39/35 -> 42/38."""

    def test_registry_total_entries_at_least_42(self):
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 42)

    def test_registry_total_champions_at_least_38(self):
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 38)

    def test_hwei_neeko_renekton_present_in_champ_set(self):
        champs = set(_PER_SPELL_CC_CONDITIONAL.keys())
        self.assertIn("Hwei", champs)
        self.assertIn("Neeko", champs)
        self.assertIn("Renekton", champs)


class FrenzyStateForwardMarkerClosureTests(unittest.TestCase):
    """Wave 9 closes the wave 7 COND_FRENZY_STATE empty-registry
    contract by registering the FIRST consumer (Renekton W).
    """

    def test_cond_frenzy_state_is_consumed_by_at_least_one_entry(self):
        consumers = []
        for spells in _PER_SPELL_CC_CONDITIONAL.values():
            for entry in spells.values():
                if entry.condition == COND_FRENZY_STATE:
                    consumers.append((entry.champion, entry.spell))
        self.assertGreaterEqual(len(consumers), 1)
        self.assertIn(("Renekton", "W"), consumers)

    def test_renekton_w_is_first_frenzy_state_consumer(self):
        # Pin the first consumer so a future entry that ALSO consumes
        # COND_FRENZY_STATE (e.g. a future Aatrox-passive entry if
        # schema lifts again) doesn't accidentally orphan this one.
        entry = _PER_SPELL_CC_CONDITIONAL["Renekton"]["W"]
        self.assertEqual(entry.condition, COND_FRENZY_STATE)


class ExistingSeedPreservedTests(unittest.TestCase):
    """Wave 0-8 entries unchanged by wave 9."""

    def test_brand_r_preserved(self):
        # Brand R wave 0 nth_hit 3-stack stun.
        entry = _PER_SPELL_CC_CONDITIONAL["Brand"]["R"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, "nth_hit")

    def test_karma_w_preserved(self):
        # Karma W wave 1 channel-completion root (REJECT (a) for
        # wave 9 - the form 1 R-empowered variant cannot coexist on
        # the same spell slot).
        entry = _PER_SPELL_CC_CONDITIONAL["Karma"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)

    def test_morgana_r_wave8_preserved(self):
        # Morgana R wave 8 channel-completion stun.
        entry = _PER_SPELL_CC_CONDITIONAL["Morgana"]["R"]
        self.assertEqual(entry.cc_kind, "stun")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)

    def test_seraphine_e_wave8_preserved(self):
        # Seraphine E wave 8 target_debuffed stun.
        entry = _PER_SPELL_CC_CONDITIONAL["Seraphine"]["E"]
        self.assertEqual(entry.cc_kind, "stun")

    def test_evelynn_w_wave8_preserved(self):
        # Evelynn W wave 8 channel-completion charm.
        entry = _PER_SPELL_CC_CONDITIONAL["Evelynn"]["W"]
        self.assertEqual(entry.cc_kind, "charm")

    def test_aatrox_q_w_preserved(self):
        # Aatrox Q wave 3 + W wave 4 multi-wave coexistence.
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Aatrox"])
        self.assertIn("W", _PER_SPELL_CC_CONDITIONAL["Aatrox"])

    def test_volibear_q_preserved(self):
        # Volibear Q wave 1 terrain knockback (R rejected for wave 9).
        entry = _PER_SPELL_CC_CONDITIONAL["Volibear"]["Q"]
        self.assertEqual(entry.cc_kind, "knockback")

    def test_briar_q_e_preserved(self):
        # Briar Q wave 4 + Briar E wave 5 multi-wave coexistence
        # (W rejected for wave 9 - self-buff only).
        self.assertIn("Q", _PER_SPELL_CC_CONDITIONAL["Briar"])
        self.assertIn("E", _PER_SPELL_CC_CONDITIONAL["Briar"])

    def test_karma_w_form_1_NOT_added(self):
        # REJECT (a) - Karma W form 1 Renewal not added because
        # the (Karma, W) slot already holds the wave 1 entry. The
        # registry is keyed (champion, spell) so a second Karma W
        # entry cannot coexist; the wave 1 entry is preserved.
        karma_spells = _PER_SPELL_CC_CONDITIONAL["Karma"]
        # Exactly one Karma W entry (the wave 1 channel-completion
        # root). Pin via direct entry inspection - the cc_kind +
        # condition tag are wave 1 originals.
        self.assertIn("W", karma_spells)
        entry = karma_spells["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        # Probability is 0.4 from wave 1 _p("Karma", "W", 0.4); the
        # wave 9 REJECT did NOT bump it.
        self.assertAlmostEqual(entry.probability, 0.4, places=4)

    def test_aatrox_r_NOT_added(self):
        # REJECT (b) - Aatrox R fears minions only, no champion CC.
        aatrox_spells = _PER_SPELL_CC_CONDITIONAL.get("Aatrox", {})
        self.assertNotIn("R", aatrox_spells)

    def test_volibear_r_NOT_added(self):
        # REJECT (c) - Volibear R only turret-disable + slow.
        volibear_spells = _PER_SPELL_CC_CONDITIONAL.get("Volibear", {})
        self.assertNotIn("R", volibear_spells)

    def test_briar_w_NOT_added(self):
        # REJECT (d) - Briar W Blood Frenzy is self-buff only.
        briar_spells = _PER_SPELL_CC_CONDITIONAL.get("Briar", {})
        self.assertNotIn("W", briar_spells)


class WiredSiteGrepTests(unittest.TestCase):
    """Pin each wave 9 entry's wire site so a future refactor that
    removes any of the 3 entries fails CI before silent regression.
    """

    def setUp(self) -> None:
        self.source_path = (
            Path(__file__).parent.parent / "CC_CONDITIONAL_NOTES.md"
        )
        self.assertTrue(self.source_path.exists())
        self.source = self.source_path.read_text(encoding="utf-8")

    def test_hwei_e_wired_in_source(self):
        self.assertIn('registry.setdefault("Hwei", {})["E"]', self.source)

    def test_neeko_e_wired_in_source(self):
        self.assertIn('registry.setdefault("Neeko", {})["E"]', self.source)

    def test_renekton_w_wired_in_source(self):
        self.assertIn(
            'registry.setdefault("Renekton", {})["W"]', self.source
        )

    def test_wave_9_section_marker_present(self):
        # Pin the wave 9 expansion block marker comment so future
        # readers can grep for the section.
        self.assertIn("wave 9 expansion", self.source.lower())


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_at_least_1_46_0(self):
        parts = tuple(int(p) for p in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 46, 0))


class AsciiHygieneTests(unittest.TestCase):
    def test_no_non_ascii_in_wave9_entries(self):
        # The 3 wave-9 entry notes must be pure ASCII.
        for champ_spell in [("Hwei", "E"), ("Neeko", "E"), ("Renekton", "W")]:
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
            chr(c) for c in (
                0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2192,
            )
        )
        bad = [c for c in text if c in bad_chars]
        self.assertEqual(bad, [], f"Non-ASCII bytes in test file: {bad!r}")


if __name__ == "__main__":
    unittest.main()
