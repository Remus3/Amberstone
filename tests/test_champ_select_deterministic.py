"""Tests for the deterministic champ-select brief (items 273/276/280/283).

`dashboard._champ_select_deterministic.brief_deterministic` composes the
champ-select brief with ZERO Haiku call, same {build, runes, ally_notes}
shape + empty-on-error contract as `brief_via_coach`. As of 2026-06-06 the
shadow-mode was flipped: `brief_via_coach` now DELEGATES to this substrate
(Haiku eliminated). The contract guards below pin that the flip stays flipped
- brief_via_coach delegates, and `_champ_select.py` makes no Anthropic call.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

from dashboard._champ_select_deterministic import brief_deterministic

_EMPTY = {"build": [], "runes": {}, "ally_notes": ""}
_CS_SRC = Path(__file__).resolve().parent.parent / "dashboard" / "_champ_select.py"


class ShapeConformanceTests(unittest.TestCase):
    def test_returns_exact_keys(self) -> None:
        out = brief_deterministic("Caitlyn", [], ["Caitlyn", "Lux"],
                                  "BOTTOM", "sr")
        self.assertEqual(set(out.keys()), {"build", "runes", "ally_notes"})

    def test_build_is_list_cap_seven(self) -> None:
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        self.assertIsInstance(out["build"], list)
        self.assertLessEqual(len(out["build"]), 7)

    def test_runes_is_dict_with_keystone(self) -> None:
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        self.assertIsInstance(out["runes"], dict)
        self.assertIn("keystone", out["runes"])
        # mirrors brief_via_coach's runes sub-dict keys
        for k in ("primary_tree", "secondary_tree", "shards"):
            self.assertIn(k, out["runes"])

    def test_ally_notes_is_str(self) -> None:
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        self.assertIsInstance(out["ally_notes"], str)


class GroundingTests(unittest.TestCase):
    """build + runes come from the curated loadout_resolver the build chooser
    already uses - the same items + keystone."""

    def test_build_matches_resolver_raw_items(self) -> None:
        from coaches.loadout_resolver import default_variant, resolve
        v = default_variant("Caitlyn", "sr")
        resolved = resolve("Caitlyn", v, "sr")
        self.assertTrue(resolved.get("ok"))
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        expected = [it for it in (resolved.get("raw_items") or []) if it][:7]
        self.assertEqual(out["build"], expected)

    def test_keystone_matches_resolver(self) -> None:
        from coaches.loadout_resolver import default_variant, resolve
        v = default_variant("Caitlyn", "sr")
        resolved = resolve("Caitlyn", v, "sr")
        first_perk = (resolved.get("rune_cmd") or {}).get("perk_ids", [None])[0]
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        # Caitlyn's curated keystone is non-empty + resolves to a real name.
        self.assertTrue(out["runes"]["keystone"])
        # the keystone is the name for the resolver's first perk id
        from dashboard._champ_select_deterministic import _keystone_id_to_name
        self.assertEqual(out["runes"]["keystone"],
                         _keystone_id_to_name().get(first_perk, ""))

    def test_tree_names_resolved(self) -> None:
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        self.assertIn(out["runes"]["primary_tree"],
                      {"Precision", "Domination", "Sorcery",
                       "Inspiration", "Resolve"})


class AllyNotesHeuristicTests(unittest.TestCase):
    def test_marksman_ally_named_carry(self) -> None:
        out = brief_deterministic("Lux", [], ["Lux", "Ashe", "Malphite"],
                                  "MIDDLE", "sr")
        notes = out["ally_notes"]
        self.assertIn("Ashe", notes)
        self.assertIn("carry", notes)

    def test_tank_ally_named_engage(self) -> None:
        out = brief_deterministic("Caitlyn", [], ["Caitlyn", "Malphite"],
                                  "BOTTOM", "sr")
        # Malphite (tank primary) is the engage when no carry present
        self.assertIn("Malphite", out["ally_notes"])
        self.assertIn("engage", out["ally_notes"])

    def test_empty_allies_yields_empty_notes(self) -> None:
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        self.assertEqual(out["ally_notes"], "")

    def test_self_excluded_from_notes(self) -> None:
        # allies is JUST the operator's own champ -> nothing to say
        out = brief_deterministic("Caitlyn", [], ["Caitlyn"], "BOTTOM", "sr")
        self.assertEqual(out["ally_notes"], "")

    def test_self_not_named_when_others_present(self) -> None:
        # Caitlyn is a marksman; if she were not excluded she'd be the carry.
        out = brief_deterministic("Caitlyn", [],
                                  ["Caitlyn", "Lux", "Leona"], "BOTTOM", "sr")
        self.assertNotIn("Caitlyn", out["ally_notes"])
        # Lux (mage) is the carry instead
        self.assertIn("Lux", out["ally_notes"])

    def test_no_fabricated_names(self) -> None:
        allies = ["Caitlyn", "Lux", "Leona"]
        out = brief_deterministic("Caitlyn", [], allies, "BOTTOM", "sr")
        # only names present in allies may appear
        for word in out["ally_notes"].replace(";", " ").split():
            cap = word.strip(".,-")
            if cap and cap[0].isupper():
                # capitalized leading words that are champ-shaped must be allies
                if cap in {"Lux", "Leona", "Ashe", "Malphite", "Caitlyn",
                           "Orianna", "Yasuo", "Garen", "Jinx"}:
                    self.assertIn(cap, allies)


class DeterminismTests(unittest.TestCase):
    def test_same_input_identical_output(self) -> None:
        a = brief_deterministic("Jinx", ["Garen"],
                                ["Jinx", "Malphite", "Orianna"], "BOTTOM", "sr")
        b = brief_deterministic("Jinx", ["Garen"],
                                ["Jinx", "Malphite", "Orianna"], "BOTTOM", "sr")
        self.assertEqual(a, b)


class FailSoftTests(unittest.TestCase):
    def test_unknown_champ_returns_empty_shape(self) -> None:
        out = brief_deterministic("ZzzGarbage999", [], [], "", "sr")
        self.assertEqual(out, _EMPTY)

    def test_garbage_inputs_no_exception(self) -> None:
        # weird types should fail soft to the empty shape, never raise
        out = brief_deterministic("ZzzGarbage999", None, None, None, "sr")
        self.assertEqual(out, _EMPTY)


class BriefFlipContractTests(unittest.TestCase):
    """The Haiku brief was flipped to the deterministic substrate
    (items 273/276/280/283, 2026-06-06). `brief_via_coach` now delegates to
    `brief_deterministic` with ZERO Anthropic call. These guards pin that the
    flip stays flipped - no silent revert to a Haiku call, shadow-log, or
    cost record."""

    def test_brief_via_coach_delegates_to_deterministic(self) -> None:
        import dashboard._champ_select as CS
        sentinel = {"build": ["X"], "runes": {"keystone": "K"},
                    "ally_notes": "n"}
        with mock.patch.object(CS, "brief_deterministic",
                               return_value=sentinel) as m:
            out = CS.brief_via_coach("Caitlyn", ["Garen"],
                                     ["Caitlyn", "Lux"], "BOTTOM", "sr")
        m.assert_called_once_with("Caitlyn", ["Garen"],
                                  ["Caitlyn", "Lux"], "BOTTOM", "sr")
        self.assertEqual(out, sentinel)

    def test_no_anthropic_import_or_call(self) -> None:
        # _champ_select.py must make no Anthropic call after the flip.
        tree = ast.parse(_CS_SRC.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("anthropic", alias.name.lower())
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("anthropic", node.module.lower())
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "create",
                                    "champ-select brief must not call .create")

    def test_no_shadow_log_or_cost_remnants(self) -> None:
        src = _CS_SRC.read_text(encoding="utf-8")
        self.assertNotIn("champ_select_brief_shadow.jsonl", src)
        self.assertNotIn("record_anthropic_response", src)
        self.assertNotIn("messages.create", src)

    def test_no_anthropic_import_or_call_in_deterministic_module(self) -> None:
        # the module docstring may MENTION Anthropic/Haiku (it explains it has
        # none); the guard is that it never imports or calls anthropic.
        det_src = (_CS_SRC.parent / "_champ_select_deterministic.py").read_text(
            encoding="utf-8")
        tree = ast.parse(det_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("anthropic", alias.name.lower())
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("anthropic", node.module.lower())
            # no `messages.create(` attribute call either
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "create",
                                    "deterministic module must not call .create")


class EnemyItemizationTests(unittest.TestCase):
    """A correct-by-construction enemy damage-type itemization hint (via
    core.aram_comp_verdict.compute_factors) is appended to ally_notes when the
    enemy comp is clearly skewed AD or AP. Shadow-only; the served brief stays
    Haiku. The hint only fires with >= 3 resolvable enemies and a CLEAR lean
    (the opposite type entirely absent), so a mixed comp gets nothing."""

    def test_ad_heavy_enemy_yields_armor_hint(self) -> None:
        out = brief_deterministic(
            "Lux", ["Garen", "Darius", "Aatrox", "Jhin", "Ashe"],
            ["Lux", "Ashe", "Malphite"], "MIDDLE", "sr")
        notes = out["ally_notes"].lower()
        self.assertIn("armor", notes)
        self.assertNotIn("magic resist", notes)

    def test_ap_heavy_enemy_yields_mr_hint(self) -> None:
        out = brief_deterministic(
            "Caitlyn", ["Ahri", "Lux", "Soraka", "Ziggs", "Brand"],
            ["Caitlyn", "Malphite"], "BOTTOM", "sr")
        self.assertIn("magic resist", out["ally_notes"].lower())

    def test_mixed_enemy_yields_no_itemization_hint(self) -> None:
        out = brief_deterministic(
            "Lux", ["Garen", "Ahri", "Aatrox", "Lux", "Darius"],
            ["Lux", "Ashe", "Malphite"], "MIDDLE", "sr")
        notes = out["ally_notes"].lower()
        self.assertNotIn("prioritize armor", notes)
        self.assertNotIn("magic resist", notes)

    def test_few_enemies_yields_no_hint(self) -> None:
        out = brief_deterministic(
            "Lux", ["Garen"], ["Lux", "Ashe", "Malphite"], "MIDDLE", "sr")
        self.assertNotIn("armor", out["ally_notes"].lower())

    def test_empty_enemies_preserves_empty_allies_contract(self) -> None:
        # No enemies + no allies must still yield exactly "" (item-273 contract).
        out = brief_deterministic("Caitlyn", [], [], "BOTTOM", "sr")
        self.assertEqual(out["ally_notes"], "")

    def test_hint_appends_to_existing_ally_note(self) -> None:
        # AD-heavy enemy + a real ally carry -> both clauses present.
        out = brief_deterministic(
            "Lux", ["Garen", "Darius", "Aatrox", "Jhin", "Zed"],
            ["Lux", "Ashe", "Malphite"], "MIDDLE", "sr")
        self.assertIn("Ashe", out["ally_notes"])      # ally carry clause kept
        self.assertIn("armor", out["ally_notes"].lower())  # + itemization clause


class AsciiHygieneTests(unittest.TestCase):
    def test_deterministic_module_ascii(self) -> None:
        p = _CS_SRC.parent / "_champ_select_deterministic.py"
        data = p.read_text(encoding="utf-8")
        bad = [(i, ord(c)) for i, c in enumerate(data) if ord(c) > 127]
        self.assertEqual(bad, [], f"non-ASCII in {p.name}: {bad[:5]}")

    def test_test_file_ascii(self) -> None:
        data = Path(__file__).read_text(encoding="utf-8")
        bad = [(i, ord(c)) for i, c in enumerate(data) if ord(c) > 127]
        self.assertEqual(bad, [], f"non-ASCII in test file: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
