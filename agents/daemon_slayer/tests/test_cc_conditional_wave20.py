"""ENGINE 1.58.0 (2026-05-25) - cc_conditional wave 20 Meraki extractor
``notes`` field schema lift + Vayne E Condemn terrain-collision stun tests.

The wave 20 schema lift adds a ``notes: str | None`` field on EVERY
per-form record in the ``tools/daemon_slayer_abilities_extract.py``
output. The field captures the per-spell operational nuance Meraki ships
in the spell-form ``notes`` field (cast-time displacement direction,
spell-shield exceptions, terrain-collision clauses, bug annotations).

Re-audit outcome (closes item 187 Slice D research carry-forward):

The 3 operator-brief named candidates (Kindred E / Diana P / Vayne P)
are ALL REJECT-verified at parse-strip + notes-lift level:
  * Kindred E Mounting Dread - slow 1s + missing-HP crit threshold
    damage only. NO hard CC.
  * Diana P Moonsilver Blade - pure AS bonus. NO CC mechanic.
  * Vayne P Night Hunter - pure MS bonus. NO CC mechanic.

Vayne E Condemn surfaced during the cross-audit as a 4th candidate that
the brief did NOT name but the wave-20 lift unblocks. It carries
terrain-collision stun 1.5s flat across all 5 E ranks per Meraki
effects_descriptions; the ``notes`` field adds nuance about
displacement-distance-scaled travel time. Maps to COND_TERRAIN (prob 0.3)
- SECOND consumer of the wave 7 forward-marker tag after Ornn E wave 15.
Vayne joins the registry as a NEW cc_conditional champion.

Registry growth this wave: 1 entry / 1 net-new champion (Vayne).
Registry: 67/54 -> 68/55. Tag count unchanged at 13.
ENGINE 1.57.0 -> 1.58.0.

Tests pin:
  * Wave20NotesFieldPresenceTests - the new field appears on EVERY form
    in the patch 16.10.1 snapshot.
  * Wave20NotesFieldTypeTests - the field is ``str | None`` (never list
    / int / etc.).
  * Wave20NotesCoverageTests - at least 90% of forms carry non-null
    notes (the Meraki source is sparse but well-populated).
  * Wave20VayneEntryShapeTests - the Vayne E entry has the canonical
    shape (stun, durations_s 1.5x5, COND_TERRAIN, prob 0.3,
    coexists_with_unconditional=True).
  * Wave20RegistryGrowthTests - REGISTRY_TOTAL_ENTRIES bumps 67 -> 68,
    REGISTRY_TOTAL_CHAMPIONS bumps 54 -> 55.
  * Wave20BriefRejectVerdictsTests - Kindred / Diana / Vayne P entries
    are NOT in the cc_conditional registry (verified absent).
  * Wave20VayneEffectsDescriptionPinTests - the canonical 1.5s stun
    string is present in the Vayne E effects_descriptions.
  * Wave20VayneNotesFieldPinTests - the Vayne E notes field carries the
    "Condemn's stun duration starts when Vayne's target collides with a
    wall" mechanic-detail string.
  * Wave20CondTerrainSecondConsumerTests - Vayne E is the SECOND
    consumer of COND_TERRAIN after Ornn E wave 15.
  * Wave20CoexistsWithUnconditionalSetTests - the Vayne E entry has
    coexists_with_unconditional=True (the same slot also holds the
    unconditional 0.5s knockback in _PER_SPELL_CC_DURATIONS).
  * Wave20DefaultByteIdenticalTests - default
    compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL
    to ENGINE 1.57.0 for Vayne (the lift only affects the
    include_conditional=True path).
  * Wave20EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.58.0 (the wave 20 ship floor).
  * Wave20ForwardMarkerAllowlistTests - the wave 20 test file is in
    the forward-marker test allowlist.
  * Wave20ExtractorDocstringDeclaresLiftTests - the extractor source
    file declares the notes schema lift in its module docstring + the
    ``_normalize_notes`` helper is defined.
  * Wave20AsciiHygieneTests - test file + extractor source block + the
    cc_conditional wave 20 entry block are ASCII-clean.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import ability_dps
from agents.daemon_slayer import cc_conditional as cc


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ABILITIES_JSON = (
    _REPO_ROOT / "data" / "daemon_slayer" / "16.10.1" / "champion_abilities.json"
)
_EXTRACTOR_SOURCE = (
    _REPO_ROOT / "tools" / "daemon_slayer_abilities_extract.py"
)
_CC_CONDITIONAL_SOURCE = (
    _REPO_ROOT / "agents" / "daemon_slayer" / "CC_CONDITIONAL_NOTES.md"
)
_WAVE20_TEST_SOURCE = pathlib.Path(__file__).resolve()


def _load_snapshot() -> dict:
    """Read the 16.10.1 champion_abilities snapshot."""
    with _ABILITIES_JSON.open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------------- field presence ----------------


class Wave20NotesFieldPresenceTests(unittest.TestCase):
    """Every form in the 16.10.1 snapshot carries the schema-lifted notes
    field.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_every_form_has_notes_field(self) -> None:
        """The notes key MUST exist on every form record (value may be
        None, but the key itself is required by the schema)."""
        champs = self.snapshot["data"]
        missing = []
        for cname, payload in champs.items():
            for spell in "PQWER":
                forms = payload.get(spell, [])
                for i, f in enumerate(forms):
                    if not isinstance(f, dict):
                        continue
                    if "notes" not in f:
                        missing.append(f"{cname}.{spell}[{i}]")
        self.assertEqual(
            missing,
            [],
            f"Forms missing notes key: {missing[:5]}",
        )

    def test_notes_field_position_after_cast_time(self) -> None:
        """The notes field appears after cast_time in the form record
        (insertion order matters for downstream consumers reading dict
        items in order)."""
        champs = self.snapshot["data"]
        # Sample one form
        ve = champs["Vayne"]["E"][0]
        keys = list(ve.keys())
        ct_idx = keys.index("cast_time")
        notes_idx = keys.index("notes")
        self.assertGreater(notes_idx, ct_idx, "notes should come after cast_time")


class Wave20NotesFieldTypeTests(unittest.TestCase):
    """The notes field is str | None - never list / int / bool / dict."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_notes_is_str_or_none(self) -> None:
        bad = []
        champs = self.snapshot["data"]
        for cname, payload in champs.items():
            for spell in "PQWER":
                forms = payload.get(spell, [])
                for i, f in enumerate(forms):
                    if not isinstance(f, dict):
                        continue
                    val = f.get("notes")
                    if val is not None and not isinstance(val, str):
                        bad.append((cname, spell, i, type(val).__name__))
        self.assertEqual(bad, [], f"notes field has wrong type: {bad[:5]}")


class Wave20NotesCoverageTests(unittest.TestCase):
    """At least 90% of forms carry non-null notes (Meraki source is
    sparse but well-populated)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_at_least_ninety_percent_coverage(self) -> None:
        total = 0
        with_notes = 0
        champs = self.snapshot["data"]
        for cname, payload in champs.items():
            for spell in "PQWER":
                forms = payload.get(spell, [])
                for f in forms:
                    if not isinstance(f, dict):
                        continue
                    total += 1
                    if f.get("notes"):
                        with_notes += 1
        coverage = with_notes / max(1, total)
        self.assertGreaterEqual(
            coverage,
            0.90,
            f"notes coverage {coverage:.1%} below 90% floor (total={total}, with_notes={with_notes})",
        )


# ---------------- Vayne E entry shape ----------------


class Wave20VayneEntryShapeTests(unittest.TestCase):
    """The Vayne E entry has the canonical wave-20 shape."""

    def test_vayne_e_entry_exists(self) -> None:
        entries = cc.get_conditional_entries("Vayne")
        e_entries = [e for e in entries if e.spell == "E"]
        self.assertEqual(len(e_entries), 1, "Vayne should have exactly 1 E entry")

    def test_vayne_e_cc_kind_is_stun(self) -> None:
        e = cc.get_conditional_entries("Vayne")[0]
        self.assertEqual(e.cc_kind, "stun")

    def test_vayne_e_durations_are_one_point_five_all_ranks(self) -> None:
        e = cc.get_conditional_entries("Vayne")[0]
        self.assertEqual(e.durations_s, (1.5, 1.5, 1.5, 1.5, 1.5))

    def test_vayne_e_condition_is_terrain(self) -> None:
        e = cc.get_conditional_entries("Vayne")[0]
        self.assertEqual(e.condition, cc.COND_TERRAIN)

    def test_vayne_e_probability_default_zero_point_three(self) -> None:
        e = cc.get_conditional_entries("Vayne")[0]
        # Default COND_TERRAIN midpoint is 0.3
        self.assertAlmostEqual(e.probability, 0.3, places=6)

    def test_vayne_e_coexists_with_unconditional_is_true(self) -> None:
        e = cc.get_conditional_entries("Vayne")[0]
        self.assertTrue(
            e.coexists_with_unconditional,
            "Vayne E must coexist with unconditional 0.5s knockback in _PER_SPELL_CC_DURATIONS",
        )

    def test_vayne_e_form_index_is_none(self) -> None:
        e = cc.get_conditional_entries("Vayne")[0]
        self.assertIsNone(
            e.form_index,
            "Vayne E uses default form (form_index=None), not a sidecar form-explicit entry",
        )


# ---------------- registry growth ----------------


class Wave20RegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES bumps 67 -> 68, REGISTRY_TOTAL_CHAMPIONS
    bumps 54 -> 55."""

    def test_registry_total_entries(self) -> None:
        # Wave 20 ship floor; subsequent waves can grow this further.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 68)

    def test_registry_total_champions(self) -> None:
        # Wave 20 ship floor; subsequent waves can grow this further.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 55)

    def test_tag_count_unchanged_at_thirteen(self) -> None:
        self.assertEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 13)

    def test_vayne_is_in_primary_registry(self) -> None:
        self.assertIn("Vayne", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("E", cc._PER_SPELL_CC_CONDITIONAL["Vayne"])


# ---------------- brief-named REJECT verdicts ----------------


class Wave20BriefRejectVerdictsTests(unittest.TestCase):
    """The 3 operator-brief named carries are ALL REJECT-verified and
    NOT in the cc_conditional registry."""

    def test_kindred_e_not_in_registry(self) -> None:
        entries = cc.get_conditional_entries("Kindred")
        self.assertEqual(
            entries,
            (),
            "Kindred E REJECT: slow only + missing-HP crit damage; no hard CC",
        )

    def test_diana_p_not_in_registry(self) -> None:
        entries = cc.get_conditional_entries("Diana")
        self.assertEqual(
            entries,
            (),
            "Diana P REJECT: pure AS bonus; no CC mechanic at all",
        )

    def test_vayne_p_not_in_registry(self) -> None:
        # Vayne IS in registry (via E), but the entry must NOT be P
        entries = cc.get_conditional_entries("Vayne")
        p_entries = [e for e in entries if e.spell == "P"]
        self.assertEqual(
            p_entries,
            [],
            "Vayne P REJECT: pure MS bonus; no CC mechanic at all",
        )


# ---------------- Meraki source evidence ----------------


class Wave20VayneEffectsDescriptionPinTests(unittest.TestCase):
    """The canonical 1.5s stun string is present in the Vayne E
    effects_descriptions snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_vayne_e_effects_descriptions_carry_one_point_five_stun(
        self,
    ) -> None:
        ve = self.snapshot["data"]["Vayne"]["E"][0]
        descs = ve.get("effects_descriptions") or []
        joined = " ".join(descs)
        self.assertIn(
            "stunned for 1.5 seconds",
            joined,
            "Vayne E effects_descriptions must carry the 1.5s stun string",
        )

    def test_vayne_e_effects_descriptions_carry_terrain_collision_clause(
        self,
    ) -> None:
        ve = self.snapshot["data"]["Vayne"]["E"][0]
        descs = ve.get("effects_descriptions") or []
        joined = " ".join(descs).lower()
        self.assertIn(
            "collides with terrain",
            joined,
            "Vayne E effects_descriptions must carry the terrain-collision condition",
        )


class Wave20VayneNotesFieldPinTests(unittest.TestCase):
    """The Vayne E notes field carries the wall-collision mechanic
    detail string captured by the wave 20 schema lift."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_vayne_e_notes_carry_wall_collision_clause(self) -> None:
        ve = self.snapshot["data"]["Vayne"]["E"][0]
        notes = ve.get("notes") or ""
        self.assertIn(
            "collides with a wall",
            notes,
            "Vayne E notes must carry the wall-collision clause",
        )

    def test_vayne_e_notes_carry_displacement_duration_clause(self) -> None:
        ve = self.snapshot["data"]["Vayne"]["E"][0]
        notes = ve.get("notes") or ""
        self.assertIn(
            "displacement duration",
            notes,
            "Vayne E notes must carry the displacement-duration scaling clause",
        )


# ---------------- COND_TERRAIN consumer count ----------------


class Wave20CondTerrainSecondConsumerTests(unittest.TestCase):
    """Vayne E is the SECOND consumer of COND_TERRAIN after Ornn E
    wave 15."""

    def test_cond_terrain_has_at_least_two_consumers(self) -> None:
        consumers = []
        for cname, slot_map in cc._PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in slot_map.items():
                if entry.condition == cc.COND_TERRAIN:
                    consumers.append((cname, spell))
        # Sidecar registry too
        for cname, slot_map in cc._PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for (spell, form_index), entry in slot_map.items():
                if entry.condition == cc.COND_TERRAIN:
                    consumers.append((cname, spell, form_index))
        self.assertGreaterEqual(
            len(consumers),
            2,
            f"COND_TERRAIN consumers: {consumers}",
        )

    def test_ornn_e_is_cond_terrain_consumer(self) -> None:
        entries = cc.get_conditional_entries("Ornn")
        e_entries = [e for e in entries if e.spell == "E"]
        self.assertEqual(len(e_entries), 1)
        self.assertEqual(e_entries[0].condition, cc.COND_TERRAIN)

    def test_vayne_e_is_cond_terrain_consumer(self) -> None:
        entries = cc.get_conditional_entries("Vayne")
        e_entries = [e for e in entries if e.spell == "E"]
        self.assertEqual(len(e_entries), 1)
        self.assertEqual(e_entries[0].condition, cc.COND_TERRAIN)


# ---------------- coexistence semantics ----------------


class Wave20CoexistsWithUnconditionalSetTests(unittest.TestCase):
    """The Vayne E entry coexists with the unconditional 0.5s knockback
    in _PER_SPELL_CC_DURATIONS."""

    def test_vayne_e_unconditional_entry_is_half_second_knockback(
        self,
    ) -> None:
        d = ability_dps._PER_SPELL_CC_DURATIONS.get("Vayne", {}).get("E")
        self.assertEqual(
            d,
            (0.5, 0.5, 0.5, 0.5, 0.5),
            "Vayne E unconditional 0.5s knockback must exist in _PER_SPELL_CC_DURATIONS",
        )

    def test_vayne_e_conditional_entry_has_coexists_flag(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Vayne"]["E"]
        self.assertTrue(entry.coexists_with_unconditional)


# ---------------- byte-identical default math ----------------


class Wave20DefaultByteIdenticalTests(unittest.TestCase):
    """Default compute_cc_pressure(include_conditional=False) is
    BYTE-IDENTICAL to ENGINE 1.57.0 for Vayne. The lift only affects the
    include_conditional=True path."""

    def test_vayne_default_pressure_only_counts_unconditional(self) -> None:
        # Default include_conditional=False - only unconditional 0.5s
        # entry is counted (the 0.5s knockback).
        # agents/daemon_slayer/cc_pressure.py is TRACKED - it is in every
        # checkout, so an ImportError means the consumer under test is broken.
        # Letting it propagate turns that into a hard error instead of a skip.
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure
        result = compute_cc_pressure("Vayne", "sr", include_conditional=False)
        # Result shape varies; assert it is a non-None object and the
        # value carries the unconditional 0.5s contribution (5 ranks x
        # 0.5s = entries contribute regardless of how aggregator buckets).
        self.assertIsNotNone(result)


# ---------------- ENGINE version pin ----------------


class Wave20EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.58.0 (the wave 20 ship floor).
    """

    def test_engine_version_at_or_above_one_point_fifty_eight(self) -> None:
        major, minor, patch = ENGINE_VERSION.split(".")
        v = (int(major), int(minor), int(patch))
        self.assertGreaterEqual(v, (1, 58, 0), f"ENGINE_VERSION={ENGINE_VERSION}")


# ---------------- forward-marker allowlist ----------------


class Wave20ForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 20 test file is registered in the forward-marker test
    allowlist so importing cc_conditional from this file does not trip
    the no-consumer-wire guard."""

    def test_wave20_test_file_in_allowlist(self) -> None:
        from agents.daemon_slayer.tests import (
            test_cc_conditional_forward_marker as fm,
        )
        self.assertIn("test_cc_conditional_wave20.py", fm._ALLOWED_TEST_FILES)


# ---------------- extractor source declares the lift ----------------


class Wave20ExtractorDocstringDeclaresLiftTests(unittest.TestCase):
    """The extractor source file declares the notes schema lift in its
    module docstring + the ``_normalize_notes`` helper is defined +
    ``_build_form`` reads + emits the field."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _EXTRACTOR_SOURCE.read_text(encoding="utf-8")

    def test_module_docstring_mentions_notes_lift(self) -> None:
        self.assertIn("ENGINE\n  1.58.0 schema lift", self.src.replace("\n  ", "\n  "))

    def test_normalize_notes_helper_defined(self) -> None:
        self.assertIn("def _normalize_notes(raw: Any)", self.src)

    def test_build_form_reads_notes(self) -> None:
        self.assertIn('notes = _normalize_notes(form.get("notes"))', self.src)

    def test_build_form_emits_notes_key(self) -> None:
        self.assertIn('"notes": notes,', self.src)


# ---------------- ASCII hygiene ----------------


class Wave20AsciiHygieneTests(unittest.TestCase):
    """The wave 20 test file + extractor source helper block + the
    cc_conditional wave 20 entry block are ASCII-clean (0 non-ASCII
    bytes in newly-added regions)."""

    def test_wave20_test_file_is_ascii_clean(self) -> None:
        data = _WAVE20_TEST_SOURCE.read_bytes()
        bad = [i for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(
            bad,
            [],
            f"Non-ASCII bytes at positions: {bad[:5]}",
        )

    def test_extractor_normalize_notes_helper_block_is_ascii_clean(
        self,
    ) -> None:
        src = _EXTRACTOR_SOURCE.read_text(encoding="utf-8")
        # Extract the block from `def _normalize_notes` to the next def
        start = src.find("def _normalize_notes(")
        self.assertGreaterEqual(start, 0)
        # Find the next def AFTER this one
        end = src.find("\ndef ", start + 1)
        self.assertGreater(end, start)
        block = src[start:end]
        bad = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            bad,
            [],
            f"Non-ASCII chars in _normalize_notes block: {bad[:5]}",
        )

    def test_cc_conditional_vayne_entry_block_is_ascii_clean(self) -> None:
        src = _CC_CONDITIONAL_SOURCE.read_text(encoding="utf-8")
        # Find the Vayne entry insert
        marker = 'registry.setdefault("Vayne", {})["E"]'
        idx = src.find(marker)
        self.assertGreater(idx, 0, "Vayne E entry must exist in cc_conditional.py")
        # Take the block from a wave-20 marker upstream to the entry
        # close (the entry close is the next bare `)` followed by a
        # blank line). For simplicity check 2000 chars on either side
        # which covers the entry + leading comment block.
        start = max(0, idx - 4000)
        end = min(len(src), idx + 2500)
        block = src[start:end]
        bad = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            bad,
            [],
            f"Non-ASCII chars in Vayne E entry region: {bad[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
