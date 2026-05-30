"""Unit-map exhaustion pins (2026-05-30 29-string sweep).

Locks the 8 newly-typed Meraki damage-modifier unit strings + the
whitespace-unit canonicalization so future Meraki text drift cannot silently
re-drop them. The 21 intentional leaves (conditional/amp + malformed crit
formulas) are NOT pinned here - they are deliberately left unparsed.
"""
from __future__ import annotations

import unittest

from tools.daemon_slayer_abilities_extract import (
    _UNIT_TO_FIELD,
    _canonicalize_unit,
    _normalize_modifiers,
)


class UnitMapAdditionsTests(unittest.TestCase):
    def test_possessive_ap_names_map_to_ap_pct(self) -> None:
        self.assertEqual(_UNIT_TO_FIELD["% of Ivern's AP"], "ap_pct")
        self.assertEqual(_UNIT_TO_FIELD["% of Sona's AP"], "ap_pct")

    def test_double_space_bonus_ad(self) -> None:
        self.assertEqual(_UNIT_TO_FIELD["%  bonus AD"], "bonus_ad_pct")

    def test_new_caster_stat_fields(self) -> None:
        self.assertEqual(_UNIT_TO_FIELD["% armor"], "caster_armor_pct")
        self.assertEqual(_UNIT_TO_FIELD["% bonus mana"], "caster_bonus_mp_pct")
        self.assertEqual(_UNIT_TO_FIELD["% bonus movement speed"], "caster_bonus_ms_pct")


class WhitespaceCanonicalizeTests(unittest.TestCase):
    def test_blank_units_canonicalize_to_empty(self) -> None:
        self.assertEqual(_canonicalize_unit(" "), "")
        self.assertEqual(_canonicalize_unit("  "), "")
        self.assertEqual(_canonicalize_unit("   "), "")

    def test_non_blank_unchanged(self) -> None:
        self.assertEqual(_canonicalize_unit("% AD"), "% AD")

    def test_whitespace_modifier_types_as_base(self) -> None:
        # TahmKench Q / Lucian R shape: flat per-rank values on a blank unit.
        typed, unparsed = _normalize_modifiers(
            [{"values": [75, 120, 165, 210, 255], "units": [" ", " ", " ", " ", " "]}]
        )
        self.assertEqual(typed.get("base"), [75.0, 120.0, 165.0, 210.0, 255.0])
        self.assertEqual(unparsed, [])

    def test_caster_armor_modifier_types(self) -> None:
        typed, unparsed = _normalize_modifiers(
            [{"values": [15, 15, 15, 15, 15], "units": ["% armor"] * 5}]
        )
        self.assertEqual(typed.get("caster_armor_pct"), [15.0, 15.0, 15.0, 15.0, 15.0])
        self.assertEqual(unparsed, [])


class IntentionalLeavesTests(unittest.TestCase):
    def test_per_100_amp_left_unparsed(self) -> None:
        # "% per 100 AP" amp coefficient is intentionally NOT typed.
        typed, unparsed = _normalize_modifiers(
            [{"values": [3, 3, 3, 3, 3], "units": ["% per 100 AP"] * 5}]
        )
        self.assertEqual(typed, {})
        self.assertEqual(len(unparsed), 1)


if __name__ == "__main__":
    unittest.main()
