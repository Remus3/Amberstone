"""Repo guard for the item-245 A3 cc_conditional registry externalization.

The ~3300-line Python builders in agents/daemon_slayer/cc_conditional.py were
replaced by JSON loaders reading cc_conditional_registry.json (co-located).
The hand-authored builder source + REJECT rationale were relocated VERBATIM to
CC_CONDITIONAL_NOTES.md. This guard pins the new structure so a regression
(deleted data file, builders re-inlined, drift between the data file and the
loaders) fails CI.

Lives in tests/ (RC suite), NOT agents/daemon_slayer/tests/, because it drives
tools/ds_cc_conditional_to_json.py, which sits outside the engine package that
the DS suite is meant to exercise standalone.
Mirrors tests/test_ds_changelog_relocation_item241.py (the A1 repo guard).
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ENG = _REPO / "agents" / "daemon_slayer"
_JSON = _ENG / "cc_conditional_registry.json"
_NOTES = _ENG / "CC_CONDITIONAL_NOTES.md"
_SRC = _ENG / "cc_conditional.py"
_GEN = _REPO / "tools" / "ds_cc_conditional_to_json.py"


class DataFileShapeTests(unittest.TestCase):
    def test_registry_json_exists_and_parses(self) -> None:
        self.assertTrue(_JSON.exists(), "cc_conditional_registry.json missing")
        data = json.loads(_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data.get("_schema"), "cc_conditional_registry_v1")
        self.assertIn("primary", data)
        self.assertIn("forms", data)

    def test_registry_json_counts(self) -> None:
        data = json.loads(_JSON.read_text(encoding="utf-8"))
        self.assertEqual(len(data["primary"]), 65)
        self.assertEqual(len(data["forms"]), 8)
        # Every primary entry is a default-form (form_index null); every forms
        # entry carries an explicit integer form_index.
        self.assertTrue(all(e["form_index"] is None for e in data["primary"]))
        self.assertTrue(all(isinstance(e["form_index"], int) for e in data["forms"]))

    def test_entry_records_carry_full_schema(self) -> None:
        data = json.loads(_JSON.read_text(encoding="utf-8"))
        need = {
            "champion", "spell", "cc_kind", "durations_s", "condition",
            "probability", "notes", "form_index", "coexists_with_unconditional",
            "durations_floor_s",
        }
        for e in data["primary"] + data["forms"]:
            self.assertEqual(set(e.keys()), need, e.get("champion"))


class LoaderMatchesDataTests(unittest.TestCase):
    def test_loaded_registry_counts_match_json(self) -> None:
        from agents.daemon_slayer import cc_conditional as cc
        data = json.loads(_JSON.read_text(encoding="utf-8"))
        primary = sum(len(v) for v in cc._PER_SPELL_CC_CONDITIONAL.values())
        forms = sum(len(v) for v in cc._PER_SPELL_CC_CONDITIONAL_FORMS.values())
        self.assertEqual(primary, len(data["primary"]))
        self.assertEqual(forms, len(data["forms"]))
        self.assertEqual(cc.REGISTRY_TOTAL_ENTRIES, primary + forms)

    def test_builders_still_return_fresh_dicts(self) -> None:
        from agents.daemon_slayer import cc_conditional as cc
        a = cc._build_per_spell_cc_conditional()
        b = cc._build_per_spell_cc_conditional()
        self.assertIsNot(a, b)  # fresh instance per call
        self.assertEqual(
            {k: set(v) for k, v in a.items()},
            {k: set(v) for k, v in b.items()},
        )

    def test_generator_check_round_trips_clean(self) -> None:
        # The data file is in sync with what the loaders re-serialize.
        r = subprocess.run(
            [sys.executable, str(_GEN), "--check"],
            cwd=str(_REPO), capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class StructureRelocationTests(unittest.TestCase):
    def test_source_is_slim(self) -> None:
        # The ~3300-line builders are gone; the slimmed module is well under.
        n = len(_SRC.read_text(encoding="utf-8").splitlines())
        self.assertLess(n, 1200, f"cc_conditional.py is {n} lines (builders re-inlined?)")

    def test_builder_entry_literals_not_in_source(self) -> None:
        # The setdefault entry construction moved out of the .py.
        src = _SRC.read_text(encoding="utf-8")
        self.assertNotIn('setdefault("Brand", {})["R"] = ConditionalCcEntry', src)
        self.assertNotIn('setdefault("Sion", {})["R"] = ConditionalCcEntry', src)

    def test_notes_archive_carries_verbatim_builders(self) -> None:
        self.assertTrue(_NOTES.exists(), "CC_CONDITIONAL_NOTES.md missing")
        notes = _NOTES.read_text(encoding="utf-8")
        self.assertIn('setdefault("Brand", {})["R"] = ConditionalCcEntry', notes)
        self.assertIn("_build_per_spell_cc_conditional_forms", notes)


class AsciiHygieneTests(unittest.TestCase):
    def test_new_files_ascii_clean(self) -> None:
        for p in (_JSON, _SRC, _NOTES, _GEN):
            raw = p.read_bytes()
            bad = [(i, hex(b)) for i, b in enumerate(raw) if b > 0x7F]
            self.assertEqual(bad, [], f"{p.name}: {len(bad)} non-ASCII bytes {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
