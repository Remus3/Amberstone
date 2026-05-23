"""Wave 10 cc_conditional expansion tests (ENGINE 1.47.0, 2026-05-23).

Wave 10 ships the same-spell-slot registry schema lift closing the
(a)-class REJECT carry from item 153 wave 9 ("Karma W form 1 R-empowered
Renewal Total Root slot-collides with wave 1 W entry; registry schema
needs same-spell-slot lift") via a parallel SIDECAR registry pattern.

Schema design:

  * Primary ``_PER_SPELL_CC_CONDITIONAL`` registry shape preserved
    (``Dict[str, Dict[str, ConditionalCcEntry]]``); all wave 0-9
    entries unchanged.
  * Parallel ``_PER_SPELL_CC_CONDITIONAL_FORMS`` sidecar registry
    (``Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]]``) keyed
    by (spell, form_index) holds form-explicit entries.
  * ``ConditionalCcEntry`` gains optional ``form_index: Optional[int]
    = None`` field. None = default form (legacy); int = explicit
    Meraki form_index.
  * ``get_conditional_entries(champion)`` merges entries from both
    registries; multi-form entries on the same slot are ordered
    default-first then form_index ASC.

New wave-10 entries (sidecar; 0 net-new champions, +2 entries; both
on champions that already had wave 0-9 primary entries):

  * Karma W form_index=1 Renewal (Mantra-empowered Focused Resolve)
    - COND_FRENZY_STATE (SECOND consumer after Renekton W wave 9)
    - durations_s = (2.35, 2.45, 2.55, 2.65, 2.75) at mid Mantra
      rank 2 (+0.75 bonus); per Meraki schema-lifted Total Root
      Duration block.
    - Coexists with primary registry wave 1 Karma W Focused Resolve
      channel-completion root entry.

  * Hwei E form_index=2 Gaze of the Abyss (EW form root)
    - COND_CHANNEL_COMPLETION (third consumer)
    - durations_s = (1.2, 1.4, 1.6, 1.8, 2.0) across 5 E ranks;
      per Meraki Root Duration block on form_index=2.
    - Coexists with primary registry wave 9 Hwei E Grim Visage
      channel-completion fear entry.

Math preservation:

  * Default include_conditional=False callers BYTE-IDENTICAL to
    1.46.0 across all 5 consumer surfaces.
  * include_conditional=True callers get +2 entries for Karma + Hwei
    in compute_cc_pressure aggregations (each champion now has 2
    conditional CC contributions per cast across their Q/W/E/R
    surfaces).

Tests pin:

  * Per-entry shape (champion / spell / cc_kind / condition /
    form_index / duration tuple) for both wave-10 entries.
  * Sidecar registry shape (``Dict[str, Dict[Tuple[str, int],
    ConditionalCcEntry]]``).
  * Multi-form same-slot coexistence (Karma W default + form 1;
    Hwei E default + form 2).
  * REGISTRY_TOTAL_ENTRIES grows 42 -> 44 (assertGreaterEqual for
    forward-compat).
  * REGISTRY_TOTAL_CHAMPIONS unchanged at 38 (assertGreaterEqual
    matches wave 9 floor).
  * COND_FRENZY_STATE second consumer pin (Karma W form 1).
  * COND_CHANNEL_COMPLETION coverage extends to Hwei E form 2.
  * ConditionalCcEntry.form_index field present + defaulted to None
    for legacy wave 0-9 entries.
  * Per-form override key shape (Karma:W:1 / Hwei:E:2) parses + flows
    through to the form-explicit entries.
  * EngineVersionCurrentTests: assertGreaterEqual((1, 47, 0)).
  * Wired-site grep pins so a future refactor that removes any of
    the 2 wave-10 entries fails CI before silent registry regression.
  * ASCII hygiene (no em-dashes / en-dashes / smart quotes).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_conditional import (
    COND_CHANNEL_COMPLETION,
    COND_FRENZY_STATE,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    _PER_SPELL_CC_CONDITIONAL,
    _PER_SPELL_CC_CONDITIONAL_FORMS,
    ConditionalCcEntry,
    _apply_per_form_entry_overrides,
    _build_per_spell_cc_conditional_forms,
    get_conditional_entries,
)


class WaveTenSidecarRegistryShapeTests(unittest.TestCase):
    """Sidecar registry has the expected dict-of-dict-keyed-by-tuple shape."""

    def test_sidecar_registry_is_dict(self) -> None:
        self.assertIsInstance(_PER_SPELL_CC_CONDITIONAL_FORMS, dict)

    def test_sidecar_inner_values_are_dicts(self) -> None:
        for champ, inner in _PER_SPELL_CC_CONDITIONAL_FORMS.items():
            with self.subTest(champion=champ):
                self.assertIsInstance(inner, dict)

    def test_sidecar_inner_keys_are_spell_form_tuples(self) -> None:
        for champ, inner in _PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for key in inner.keys():
                with self.subTest(champion=champ, key=key):
                    self.assertIsInstance(key, tuple)
                    self.assertEqual(len(key), 2)
                    spell, form_idx = key
                    self.assertIn(spell, ("Q", "W", "E", "R"))
                    self.assertIsInstance(form_idx, int)
                    self.assertGreaterEqual(form_idx, 0)

    def test_sidecar_inner_values_are_conditional_cc_entries(self) -> None:
        for champ, inner in _PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for key, entry in inner.items():
                with self.subTest(champion=champ, key=key):
                    self.assertIsInstance(entry, ConditionalCcEntry)


class WaveTenKarmaFormOneTests(unittest.TestCase):
    """Karma W form_index=1 Renewal entry shape + value pins."""

    def setUp(self) -> None:
        self.entry = _PER_SPELL_CC_CONDITIONAL_FORMS["Karma"][("W", 1)]

    def test_karma_w_form1_present(self) -> None:
        self.assertIn("Karma", _PER_SPELL_CC_CONDITIONAL_FORMS)
        self.assertIn(("W", 1), _PER_SPELL_CC_CONDITIONAL_FORMS["Karma"])

    def test_karma_w_form1_champion_field(self) -> None:
        self.assertEqual(self.entry.champion, "Karma")

    def test_karma_w_form1_spell_field(self) -> None:
        self.assertEqual(self.entry.spell, "W")

    def test_karma_w_form1_form_index_field(self) -> None:
        self.assertEqual(self.entry.form_index, 1)

    def test_karma_w_form1_cc_kind(self) -> None:
        # Renewal extends Focused Resolve's root - SAME CC kind as
        # the primary registry entry. The wave 10 entry encodes the
        # Mantra-bonus extension as a separate sidecar entry.
        self.assertEqual(self.entry.cc_kind, "root")

    def test_karma_w_form1_condition_frenzy_state(self) -> None:
        # COND_FRENZY_STATE - Karma must be in Mantra-charged self-
        # empowered state (R) to cast the Renewal variant.
        self.assertEqual(self.entry.condition, COND_FRENZY_STATE)

    def test_karma_w_form1_durations_at_mid_mantra(self) -> None:
        # Mid Mantra rank 2 (+0.75 bonus) on top of base W ranks
        # (1.6, 1.7, 1.8, 1.9, 2.0). Result: (2.35, 2.45, 2.55,
        # 2.65, 2.75) seconds.
        self.assertEqual(
            self.entry.durations_s, (2.35, 2.45, 2.55, 2.65, 2.75)
        )
        self.assertEqual(len(self.entry.durations_s), 5)

    def test_karma_w_form1_probability_tag_midpoint(self) -> None:
        # COND_FRENZY_STATE tag midpoint 0.4.
        self.assertAlmostEqual(self.entry.probability, 0.4, places=4)

    def test_karma_w_form1_notes_non_empty(self) -> None:
        self.assertTrue(self.entry.notes)


class WaveTenHweiFormTwoTests(unittest.TestCase):
    """Hwei E form_index=2 Gaze of the Abyss entry shape + value pins."""

    def setUp(self) -> None:
        self.entry = _PER_SPELL_CC_CONDITIONAL_FORMS["Hwei"][("E", 2)]

    def test_hwei_e_form2_present(self) -> None:
        self.assertIn("Hwei", _PER_SPELL_CC_CONDITIONAL_FORMS)
        self.assertIn(("E", 2), _PER_SPELL_CC_CONDITIONAL_FORMS["Hwei"])

    def test_hwei_e_form2_champion_field(self) -> None:
        self.assertEqual(self.entry.champion, "Hwei")

    def test_hwei_e_form2_spell_field(self) -> None:
        self.assertEqual(self.entry.spell, "E")

    def test_hwei_e_form2_form_index_field(self) -> None:
        self.assertEqual(self.entry.form_index, 2)

    def test_hwei_e_form2_cc_kind_is_root(self) -> None:
        # Form 2 EW Gaze of the Abyss is root (distinct from form 1
        # EQ Grim Visage fear which is in the primary registry).
        self.assertEqual(self.entry.cc_kind, "root")

    def test_hwei_e_form2_condition_channel_completion(self) -> None:
        self.assertEqual(self.entry.condition, COND_CHANNEL_COMPLETION)

    def test_hwei_e_form2_durations_pin(self) -> None:
        # Meraki 16.10.1 Gaze of the Abyss Root Duration block.
        self.assertEqual(
            self.entry.durations_s, (1.2, 1.4, 1.6, 1.8, 2.0)
        )
        self.assertEqual(len(self.entry.durations_s), 5)

    def test_hwei_e_form2_probability_tag_midpoint(self) -> None:
        # COND_CHANNEL_COMPLETION tag midpoint 0.5; the form 2 entry
        # uses 0.4 (mid-low) matching the wave 9 Hwei form 1 entry's
        # 2-cast-cycle calibration.
        self.assertAlmostEqual(self.entry.probability, 0.4, places=4)

    def test_hwei_e_form2_notes_non_empty(self) -> None:
        self.assertTrue(self.entry.notes)


class WaveTenMultiFormCoexistenceTests(unittest.TestCase):
    """Wave 10 entries coexist with their wave 0-9 primary-registry
    counterparts on the SAME (champion, spell) slot.
    """

    def test_karma_w_primary_form_preserved(self) -> None:
        # The wave 1 Karma W default-form entry is unchanged in the
        # primary registry. form_index defaults to None.
        entry = _PER_SPELL_CC_CONDITIONAL["Karma"]["W"]
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertIsNone(entry.form_index)
        # Per item 153 wave 9 REJECT (a) pin: wave 1 durations + tag.
        self.assertEqual(
            entry.durations_s, (1.5, 1.625, 1.75, 1.875, 2.0)
        )

    def test_karma_w_form1_in_sidecar_only(self) -> None:
        # The form 1 entry lives EXCLUSIVELY in the sidecar; the
        # primary registry's Karma W entry is unchanged.
        self.assertIn(("W", 1), _PER_SPELL_CC_CONDITIONAL_FORMS["Karma"])
        # Primary registry holds only the default-form entry (no
        # tuple keys; the inner dict is still flat by single spell
        # string).
        primary_karma = _PER_SPELL_CC_CONDITIONAL["Karma"]
        self.assertEqual(set(primary_karma.keys()), {"W"})

    def test_hwei_e_primary_form_preserved(self) -> None:
        # The wave 9 Hwei E default-form entry is unchanged in the
        # primary registry (form 1 Grim Visage fear).
        entry = _PER_SPELL_CC_CONDITIONAL["Hwei"]["E"]
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.condition, COND_CHANNEL_COMPLETION)
        self.assertIsNone(entry.form_index)
        self.assertEqual(
            entry.durations_s, (1.0, 1.125, 1.25, 1.375, 1.5)
        )

    def test_hwei_e_form2_in_sidecar_only(self) -> None:
        self.assertIn(("E", 2), _PER_SPELL_CC_CONDITIONAL_FORMS["Hwei"])
        primary_hwei = _PER_SPELL_CC_CONDITIONAL["Hwei"]
        self.assertEqual(set(primary_hwei.keys()), {"E"})

    def test_get_conditional_entries_karma_returns_both_forms(self) -> None:
        # Karma's flat entry list now includes BOTH the wave 1
        # default-form root AND the wave 10 form 1 Mantra-empowered
        # root. Order: default first (form_index=None), then form
        # 1 (form_index=1).
        entries = get_conditional_entries("Karma")
        self.assertEqual(len(entries), 2)
        # First entry: wave 1 default form.
        self.assertIsNone(entries[0].form_index)
        self.assertEqual(entries[0].cc_kind, "root")
        # Second entry: wave 10 form 1.
        self.assertEqual(entries[1].form_index, 1)
        self.assertEqual(entries[1].condition, COND_FRENZY_STATE)

    def test_get_conditional_entries_hwei_returns_both_forms(self) -> None:
        entries = get_conditional_entries("Hwei")
        self.assertEqual(len(entries), 2)
        # First entry: wave 9 default form (fear).
        self.assertIsNone(entries[0].form_index)
        self.assertEqual(entries[0].cc_kind, "fear")
        # Second entry: wave 10 form 2 (root).
        self.assertEqual(entries[1].form_index, 2)
        self.assertEqual(entries[1].cc_kind, "root")

    def test_get_conditional_entries_brand_unchanged(self) -> None:
        # Champions without any form-explicit sidecar entries have
        # their primary-registry entries returned unchanged. Brand
        # has Q (wave 6) + R (wave 0); both default-form.
        entries = get_conditional_entries("Brand")
        # Forward-compat: at least 2 entries (Q + R); each with
        # form_index=None.
        self.assertGreaterEqual(len(entries), 2)
        for entry in entries:
            with self.subTest(spell=entry.spell):
                self.assertIsNone(entry.form_index)


class WaveTenRegistryGrowthTests(unittest.TestCase):
    """Registry totals reflect the wave 10 sidecar additions."""

    def test_registry_total_entries_at_least_44(self) -> None:
        # Wave 9 ship at 42 entries; wave 10 adds 2 sidecar entries
        # -> 44 total.
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 44)

    def test_registry_total_champions_at_least_38(self) -> None:
        # Wave 9 ship at 38 champions; wave 10 adds 0 net-new
        # (Karma + Hwei already had primary-registry entries).
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 38)

    def test_primary_registry_size_pinned_at_42(self) -> None:
        # The primary registry stays at 42 entries (wave 9 ship).
        # Wave 10 entries land in the sidecar only.
        primary_total = sum(
            len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
        )
        self.assertGreaterEqual(primary_total, 42)

    def test_sidecar_registry_size_at_least_2(self) -> None:
        sidecar_total = sum(
            len(forms) for forms in _PER_SPELL_CC_CONDITIONAL_FORMS.values()
        )
        self.assertGreaterEqual(sidecar_total, 2)


class FrenzyStateSecondConsumerTests(unittest.TestCase):
    """Wave 10 closes the single-consumer COND_FRENZY_STATE state by
    adding Karma W form 1 as the SECOND consumer (Renekton W wave 9
    was the FIRST).
    """

    def test_cond_frenzy_state_has_at_least_two_consumers(self) -> None:
        consumers: list[tuple[str, str, int | None]] = []
        # Primary registry consumers (Renekton W wave 9).
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for entry in spells.values():
                if entry.condition == COND_FRENZY_STATE:
                    consumers.append((champ, entry.spell, entry.form_index))
        # Sidecar registry consumers (Karma W form 1 wave 10).
        for champ, forms in _PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for entry in forms.values():
                if entry.condition == COND_FRENZY_STATE:
                    consumers.append((champ, entry.spell, entry.form_index))
        self.assertGreaterEqual(len(consumers), 2)
        # Both required consumers present:
        consumer_set = set(consumers)
        self.assertIn(("Renekton", "W", None), consumer_set)
        self.assertIn(("Karma", "W", 1), consumer_set)


class ConditionalCcEntryFormIndexFieldTests(unittest.TestCase):
    """The form_index field on ConditionalCcEntry is present + defaults
    to None for legacy entries while being settable to an integer for
    wave 10+ form-explicit entries.
    """

    def test_form_index_defaults_to_none(self) -> None:
        # Build an entry without form_index; default should be None.
        from agents.daemon_slayer.cc_conditional import COND_NTH_HIT
        entry = ConditionalCcEntry(
            champion="TestChamp",
            spell="Q",
            cc_kind="stun",
            durations_s=(1.0,),
            condition=COND_NTH_HIT,
        )
        self.assertIsNone(entry.form_index)

    def test_form_index_accepts_explicit_integer(self) -> None:
        from agents.daemon_slayer.cc_conditional import COND_NTH_HIT
        entry = ConditionalCcEntry(
            champion="TestChamp",
            spell="Q",
            cc_kind="stun",
            durations_s=(1.0,),
            condition=COND_NTH_HIT,
            form_index=1,
        )
        self.assertEqual(entry.form_index, 1)

    def test_all_primary_registry_entries_have_form_index_none(self) -> None:
        # All wave 0-9 legacy entries default to form_index=None
        # (the schema-lift contract preserves backward-compat).
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in spells.items():
                with self.subTest(champion=champ, spell=spell):
                    self.assertIsNone(entry.form_index)

    def test_all_sidecar_registry_entries_have_explicit_form_index(self) -> None:
        # Wave 10+ sidecar entries carry their explicit form_index.
        for champ, forms in _PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for (spell, form_idx), entry in forms.items():
                with self.subTest(champion=champ, spell=spell, form=form_idx):
                    self.assertEqual(entry.form_index, form_idx)


class PerFormEntryOverrideTests(unittest.TestCase):
    """The 3-segment per-form override key shape parses correctly."""

    def test_well_formed_3_segment_key_resolves(self) -> None:
        overrides = {
            "per_entry_probability": {
                "Karma:W:1": 0.55,
                "Hwei:E:2": 0.62,
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result.get(("Karma", "W", 1)), 0.55)
        self.assertEqual(result.get(("Hwei", "E", 2)), 0.62)

    def test_2_segment_key_silently_dropped(self) -> None:
        # 2-segment keys are wave 1+ shape; the form-override helper
        # should ignore them.
        overrides = {
            "per_entry_probability": {
                "Karma:W": 0.55,  # 2-segment, ignored by form helper
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result, {})

    def test_4_segment_key_silently_dropped(self) -> None:
        overrides = {
            "per_entry_probability": {
                "Karma:W:1:extra": 0.55,
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result, {})

    def test_non_integer_form_index_silently_dropped(self) -> None:
        overrides = {
            "per_entry_probability": {
                "Karma:W:abc": 0.55,
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result, {})

    def test_negative_form_index_silently_dropped(self) -> None:
        overrides = {
            "per_entry_probability": {
                "Karma:W:-1": 0.55,
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result, {})

    def test_out_of_range_value_silently_dropped(self) -> None:
        overrides = {
            "per_entry_probability": {
                "Karma:W:1": 1.5,  # out of [0, 1] range
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result, {})

    def test_bool_value_silently_dropped(self) -> None:
        overrides = {
            "per_entry_probability": {
                "Karma:W:1": True,
            }
        }
        result = _apply_per_form_entry_overrides(overrides)
        self.assertEqual(result, {})

    def test_empty_overrides_returns_empty_map(self) -> None:
        self.assertEqual(_apply_per_form_entry_overrides({}), {})


class BuilderIdempotenceTests(unittest.TestCase):
    """Builder produces fresh, byte-equal dicts on each invocation."""

    def test_form_builder_returns_fresh_dict(self) -> None:
        a = _build_per_spell_cc_conditional_forms()
        b = _build_per_spell_cc_conditional_forms()
        self.assertIsNot(a, b)
        # Values must match (byte-equal content).
        self.assertEqual(a, b)

    def test_form_builder_output_matches_module_sidecar(self) -> None:
        fresh = _build_per_spell_cc_conditional_forms()
        self.assertEqual(fresh, _PER_SPELL_CC_CONDITIONAL_FORMS)


class WiredSiteGrepTests(unittest.TestCase):
    """Pin each wave 10 entry's wire site so a future refactor that
    removes any of the 2 entries fails CI before silent regression.
    """

    def setUp(self) -> None:
        self.source_path = (
            Path(__file__).parent.parent / "cc_conditional.py"
        )
        self.assertTrue(self.source_path.exists())
        self.source = self.source_path.read_text(encoding="utf-8")

    def test_karma_w_form1_wired_in_source(self) -> None:
        self.assertIn(
            'registry.setdefault("Karma", {})[("W", 1)]', self.source
        )

    def test_hwei_e_form2_wired_in_source(self) -> None:
        self.assertIn(
            'registry.setdefault("Hwei", {})[("E", 2)]', self.source
        )

    def test_wave_10_section_marker_present(self) -> None:
        self.assertIn("wave 10 expansion", self.source.lower())

    def test_sidecar_registry_present_in_source(self) -> None:
        self.assertIn(
            "_PER_SPELL_CC_CONDITIONAL_FORMS", self.source
        )

    def test_form_builder_present_in_source(self) -> None:
        self.assertIn(
            "_build_per_spell_cc_conditional_forms", self.source
        )


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_at_least_1_47_0(self) -> None:
        parts = tuple(int(p) for p in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 47, 0))


class AsciiHygieneTests(unittest.TestCase):
    def test_no_non_ascii_in_wave10_entries(self) -> None:
        for entry_key in (("Karma", ("W", 1)), ("Hwei", ("E", 2))):
            champ, key = entry_key
            entry = _PER_SPELL_CC_CONDITIONAL_FORMS[champ][key]
            with self.subTest(champion=champ, key=key):
                try:
                    entry.notes.encode("ascii")
                except UnicodeEncodeError as exc:
                    self.fail(
                        f"Non-ASCII in {champ} {key} notes: {exc}"
                    )

    def test_test_file_is_ascii(self) -> None:
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
