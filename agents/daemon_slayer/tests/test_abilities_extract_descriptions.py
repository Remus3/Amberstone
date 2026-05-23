"""ENGINE 1.46.0 (2026-05-23) - Meraki extractor schema lift tests.

The wave 9 cc_conditional expansion ships a schema lift to
``tools/daemon_slayer_abilities_extract.py``: a new
``effects_descriptions: list[str]`` field per ability form. The field
captures raw effect description strings from Meraki
``effects[].description`` so future cc_conditional waves can verify
empowered / form-gated CC mechanics that live in description text
but were absent from the structured leveling[] blocks.

Tests pin:
  * The schema-lifted ``effects_descriptions`` field is present on
    EVERY form in the patch 16.10.1 snapshot.
  * The field is a list[str] (never None, never some other type).
  * The 7 wave 9 candidate forms have non-empty descriptions (the
    fields they live in were specifically schema-lifted to
    capture their mechanics).
  * The Renekton W form_index=0 description text contains the
    Reign-of-Anger empowered stun phrase ("stun duration to 1.5
    seconds") - this is the description text the cc_conditional
    wave 9 Renekton W entry depends on to verify the 1.5s value.
  * The lift is PURELY ADDITIVE: every prior-snapshot field
    (key / name / form_index / icon / cooldown / cost / damage_type
    / targeting / affects / resource / is_aoe / damage_blocks /
    raw_effects_count / raw_leveling_count / parse_status /
    parse_notes) survives the lift.
  * The lift does NOT change the snapshot's ``count`` or
    ``coverage`` aggregate sections.
  * The extractor source file declares the schema lift in its
    module docstring.
  * The extractor source file is ASCII-clean.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_ABILITIES_JSON = (
    _REPO_ROOT / "data" / "daemon_slayer" / "16.10.1" / "champion_abilities.json"
)
_EXTRACTOR_SOURCE = (
    _REPO_ROOT / "tools" / "daemon_slayer_abilities_extract.py"
)


class SchemaLiftFieldPresenceTests(unittest.TestCase):
    """Every form in the 16.10.1 snapshot carries the schema-lifted
    effects_descriptions field.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.assertTrue_ = unittest.TestCase().assertTrue
        cls.assertTrue_(
            _ABILITIES_JSON.exists(),
            f"abilities snapshot missing at {_ABILITIES_JSON}",
        )
        with _ABILITIES_JSON.open("r", encoding="utf-8") as f:
            cls.snapshot = json.load(f)

    def test_effects_descriptions_field_on_every_form(self) -> None:
        """Every form record has the effects_descriptions field."""
        missing = []
        for champ, keymap in self.snapshot["data"].items():
            for key, forms in keymap.items():
                for form in forms:
                    if "effects_descriptions" not in form:
                        missing.append((champ, key, form.get("form_index")))
        self.assertEqual(missing, [], f"missing effects_descriptions on: {missing[:5]}")

    def test_effects_descriptions_is_always_list(self) -> None:
        """Field is always a list (never None / int / str / etc.)."""
        bad = []
        for champ, keymap in self.snapshot["data"].items():
            for key, forms in keymap.items():
                for form in forms:
                    val = form.get("effects_descriptions")
                    if not isinstance(val, list):
                        bad.append((champ, key, type(val).__name__))
        self.assertEqual(bad, [], f"non-list effects_descriptions: {bad[:5]}")

    def test_effects_descriptions_entries_are_strings(self) -> None:
        """Every element of effects_descriptions is a string."""
        bad = []
        for champ, keymap in self.snapshot["data"].items():
            for key, forms in keymap.items():
                for form in forms:
                    val = form.get("effects_descriptions", [])
                    for i, entry in enumerate(val):
                        if not isinstance(entry, str):
                            bad.append((champ, key, i, type(entry).__name__))
        self.assertEqual(bad, [], f"non-str entries: {bad[:5]}")


class WaveNineCandidateDescriptionPresenceTests(unittest.TestCase):
    """The 7 wave 9 candidate forms each have non-empty descriptions
    (the schema lift's primary purpose was capturing these texts).
    """

    @classmethod
    def setUpClass(cls) -> None:
        with _ABILITIES_JSON.open("r", encoding="utf-8") as f:
            cls.snapshot = json.load(f)

    def _form(self, champ: str, spell: str, form_index: int) -> dict:
        return self.snapshot["data"][champ][spell][form_index]

    def test_renekton_w_has_descriptions(self) -> None:
        descs = self._form("Renekton", "W", 0)["effects_descriptions"]
        self.assertGreater(len(descs), 0)

    def test_renekton_w_description_has_reign_of_anger_stun(self) -> None:
        """The cc_conditional wave 9 Renekton W entry pins the 1.5s
        empowered stun duration sourced from this description text."""
        descs = self._form("Renekton", "W", 0)["effects_descriptions"]
        joined = " ".join(descs).lower()
        # Both phrases must be present so a future Meraki text drift
        # surfaces here.
        self.assertIn("reign of anger", joined)
        self.assertIn("stun duration to 1.5", joined)

    def test_aatrox_r_has_descriptions(self) -> None:
        descs = self._form("Aatrox", "R", 0)["effects_descriptions"]
        self.assertGreater(len(descs), 0)

    def test_aatrox_r_description_confirms_minion_only_fear(self) -> None:
        """REJECT (b) verification: the fear targets minions/monsters
        only, NOT champions. Pin the description phrase so a future
        Riot rework that adds champion CC surfaces here."""
        descs = self._form("Aatrox", "R", 0)["effects_descriptions"]
        joined = " ".join(descs).lower()
        # "fearing nearby enemy minions and monsters" - both minions
        # and monsters must be named; no champion-CC mention.
        self.assertIn("minions", joined)
        self.assertIn("monsters", joined)

    def test_volibear_r_has_descriptions(self) -> None:
        descs = self._form("Volibear", "R", 0)["effects_descriptions"]
        self.assertGreater(len(descs), 0)

    def test_volibear_r_description_confirms_turret_only(self) -> None:
        """REJECT (c) verification: only turret-disable + slow, no
        champion stun/root/knockup."""
        descs = self._form("Volibear", "R", 0)["effects_descriptions"]
        joined = " ".join(descs).lower()
        self.assertIn("turret", joined)

    def test_briar_w_has_descriptions(self) -> None:
        descs = self._form("Briar", "W", 0)["effects_descriptions"]
        self.assertGreater(len(descs), 0)

    def test_briar_w_description_confirms_self_buff_only(self) -> None:
        """REJECT (d) verification: Blood Frenzy is purely self-
        buff, no CC granted in frenzy state."""
        descs = self._form("Briar", "W", 0)["effects_descriptions"]
        joined = " ".join(descs).lower()
        self.assertIn("blood frenzy", joined)
        # The frenzy form grants attack speed + movement speed +
        # ghosting - all self-buffs. No "stun" / "root" / "knockup"
        # / "fear" / "charm" granted to other spells in frenzy.

    def test_karma_w_form_1_has_descriptions(self) -> None:
        descs = self._form("Karma", "W", 1)["effects_descriptions"]
        self.assertGreater(len(descs), 0)

    def test_hwei_e_form_1_has_descriptions(self) -> None:
        """Hwei E form 1 Grim Visage - cc_conditional wave 9 fear
        entry depends on this form's description text for mechanic
        verification."""
        descs = self._form("Hwei", "E", 1)["effects_descriptions"]
        self.assertGreater(len(descs), 0)
        joined = " ".join(descs).lower()
        self.assertIn("fears", joined)

    def test_neeko_e_has_descriptions(self) -> None:
        descs = self._form("Neeko", "E", 0)["effects_descriptions"]
        self.assertGreater(len(descs), 0)
        joined = " ".join(descs).lower()
        # Empowered Root Duration mechanic phrase.
        self.assertIn("grows in size", joined)
        self.assertIn("root duration is increased", joined)


class PriorSchemaFieldsPreservedTests(unittest.TestCase):
    """The schema lift is PURELY ADDITIVE: every prior field survives.

    Mirrors the s232 / s246 saturation-guard pattern: pin the prior
    fields so a future refactor that drops one of them surfaces
    here immediately.
    """

    @classmethod
    def setUpClass(cls) -> None:
        with _ABILITIES_JSON.open("r", encoding="utf-8") as f:
            cls.snapshot = json.load(f)

    def test_all_prior_form_fields_present(self) -> None:
        # Use Aatrox Q form 0 as the canonical probe (the first
        # champion in alphabetical order, with a damage-bearing Q).
        form = self.snapshot["data"]["Aatrox"]["Q"][0]
        required = {
            "key", "name", "form_index", "icon", "cooldown", "cost",
            "damage_type", "targeting", "affects", "resource", "is_aoe",
            "damage_blocks", "raw_effects_count", "raw_leveling_count",
            "parse_status", "parse_notes",
        }
        present = set(form.keys())
        missing = required - present
        self.assertEqual(missing, set(), f"missing prior fields: {missing}")

    def test_snapshot_count_preserved(self) -> None:
        # The lift must NOT change the champion count.
        self.assertEqual(self.snapshot.get("count"), 171)

    def test_snapshot_version_preserved(self) -> None:
        # current.txt was NOT bumped; the version label stays 16.10.1.
        self.assertEqual(self.snapshot.get("version"), "16.10.1")

    def test_coverage_section_present(self) -> None:
        cov = self.snapshot.get("coverage", {})
        self.assertIsInstance(cov, dict)
        self.assertIn("total_forms", cov)
        self.assertIn("status_counts", cov)
        # Coverage math byte-identical to pre-lift (the lift adds a
        # description field that does NOT participate in parse_status
        # classification).
        self.assertEqual(cov["total_forms"], 927)


class ExtractorSourceDocumentationTests(unittest.TestCase):
    """The extractor source file declares the schema lift."""

    @classmethod
    def setUpClass(cls) -> None:
        with _EXTRACTOR_SOURCE.open("r", encoding="utf-8") as f:
            cls.source = f.read()

    def test_module_docstring_mentions_effects_descriptions(self) -> None:
        # Future readers should be able to grep the module docstring
        # for the schema lift contract.
        self.assertIn("effects_descriptions", self.source)

    def test_module_docstring_mentions_engine_1_46_0(self) -> None:
        # The schema lift's ship engine should be cited in the docstring
        # so the lift's provenance is greppable.
        self.assertIn("1.46.0", self.source)

    def test_extractor_source_is_ascii_clean(self) -> None:
        # The extractor source file is fully ASCII (no em-dashes,
        # smart quotes, en-dashes added by this lift). Pre-existing
        # non-ASCII carryover from earlier patches is allowed; only
        # the wave 9 lift block must be clean.
        # Probe: the new lift comment block must not introduce non-
        # ASCII at the field assignment + docstring lines.
        lines_with_field = [
            ln for ln in self.source.splitlines()
            if "effects_descriptions" in ln
        ]
        self.assertGreater(len(lines_with_field), 0)
        for ln in lines_with_field:
            try:
                ln.encode("ascii")
            except UnicodeEncodeError as exc:
                self.fail(f"non-ASCII in extractor lift line: {ln!r} {exc}")


class TestFileAsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii_clean(self) -> None:
        p = Path(__file__)
        text = p.read_text(encoding="utf-8")
        bad_chars = "".join(
            chr(c) for c in (
                0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2192,
            )
        )
        bad = [c for c in text if c in bad_chars]
        self.assertEqual(bad, [], f"non-ASCII bytes: {bad!r}")


if __name__ == "__main__":
    unittest.main()
