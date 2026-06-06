# arch: P2.2 structured-output hardening - characterization golden-master | section=coaches | frozen=no
"""Characterization (golden-master) tests for the base-coach LLM parse seam.

P2.2 hardens `coaches/_base_coach.py::parse_fields` / `parse_field` (the
free-text "Label: value" parser shared by the ARAM / Arena / Brawl coaches)
with a Pydantic structured-output layer. Before swapping any parsing logic we
PIN the exact current behavior here so the refactor cannot silently change
what the three live coach pipelines receive.

These assertions capture CURRENT behavior verbatim (including the known
footguns: the lowercase-key contract and the positional fallback that can
absorb whole lines as values). They are not aspirational - if a future change
intends to alter one of these, it must update the pinned value deliberately.

Pure functions, no `self` / no API key / no network - safe to import direct.
"""
from __future__ import annotations

import unittest

from coaches._base_coach import parse_field, parse_fields


class ParseFieldsLabeledTests(unittest.TestCase):
    def test_basic_lowercase_labels(self):
        out = parse_fields("action: dive\nrisk: low", ["action", "risk"])
        self.assertEqual(out, {"action": "dive", "risk": "low"})

    def test_keys_with_spaces_and_slashes(self):
        # Real coach keys contain spaces/slashes ("fight rule", "reset / item").
        raw = "fight rule: 2v2 only\nreset / item: B at 1100g"
        out = parse_fields(raw, ["fight rule", "reset / item"])
        self.assertEqual(out["fight rule"], "2v2 only")
        self.assertEqual(out["reset / item"], "B at 1100g")

    def test_global_markdown_bold_stripped_before_match(self):
        out = parse_fields("action: **dive** now", ["action"])
        self.assertEqual(out["action"], "dive now")
        self.assertNotIn("*", out["action"])

    def test_leading_header_hash_stripped(self):
        out = parse_fields("# action: go", ["action"])
        self.assertEqual(out["action"], "go")

    def test_value_truncated_to_220_chars(self):
        long_val = "x" * 400
        out = parse_fields(f"action: {long_val}", ["action"])
        self.assertEqual(len(out["action"]), 220)
        self.assertEqual(out["action"], "x" * 220)

    def test_value_after_second_colon_retained(self):
        out = parse_fields("action: go: now", ["action"])
        self.assertEqual(out["action"], "go: now")

    def test_value_is_stripped(self):
        out = parse_fields("action:    spaced out   ", ["action"])
        self.assertEqual(out["action"], "spaced out")

    def test_choices_json_string_passthrough(self):
        raw = 'choices: [{"key":"A","label":"hold"}]'
        out = parse_fields(raw, ["choices"])
        self.assertEqual(out["choices"], '[{"key":"A","label":"hold"}]')

    def test_unmatched_key_absent_not_empty(self):
        # A key with no line in the text is simply absent from the dict.
        out = parse_fields("action: dive", ["action", "risk"])
        self.assertIn("action", out)
        self.assertNotIn("risk", out)


class ParseFieldsLowercaseContractTests(unittest.TestCase):
    """The labeled path lowercases the LINE but NOT the key, so callers MUST
    pass lowercase keys. Pinned because all live coaches rely on it."""

    def test_uppercase_key_single_line_yields_empty(self):
        # No label match (case mismatch) + only one line -> positional
        # fallback threshold (>=2 lines) not met -> {}.
        out = parse_fields("Action: go", ["Action"])
        self.assertEqual(out, {})

    def test_uppercase_key_multiline_triggers_positional_footgun(self):
        # KNOWN FOOTGUN: uppercase keys miss the label match, then the
        # positional fallback absorbs each WHOLE line (label included) as the
        # value. Pinned so the Pydantic hardening can address it knowingly.
        out = parse_fields("Action: go\nRisk: low", ["Action", "Risk"])
        self.assertEqual(out, {"Action": "Action: go", "Risk": "Risk: low"})


class ParseFieldsPositionalFallbackTests(unittest.TestCase):
    def test_positional_fallback_two_keys_two_lines(self):
        out = parse_fields("dive now\nlow", ["action", "risk"])
        self.assertEqual(out, {"action": "dive now", "risk": "low"})

    def test_positional_fallback_threshold_six_keys_needs_three_lines(self):
        keys = ["a", "b", "c", "d", "e", "f"]  # max(2, 6//2) = 3 lines required
        self.assertEqual(parse_fields("l1\nl2", keys), {})
        self.assertEqual(
            parse_fields("l1\nl2\nl3", keys),
            {"a": "l1", "b": "l2", "c": "l3"},
        )

    def test_positional_fallback_skipped_when_any_label_matched(self):
        # One labeled hit suppresses the positional fallback entirely.
        out = parse_fields("action: dive\njust a stray line", ["action", "risk"])
        self.assertEqual(out, {"action": "dive"})

    def test_positional_fallback_zip_stops_at_shortest(self):
        out = parse_fields("only one line here", ["action", "risk"])
        # 1 line < max(2,1)=2 -> fallback not triggered -> {}
        self.assertEqual(out, {})


class ParseFieldsEdgeTests(unittest.TestCase):
    def test_empty_text_returns_empty(self):
        self.assertEqual(parse_fields("", ["action"]), {})

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(parse_fields("   \n  \n", ["action"]), {})

    def test_blank_lines_ignored(self):
        out = parse_fields("\n\naction: dive\n\nrisk: low\n", ["action", "risk"])
        self.assertEqual(out, {"action": "dive", "risk": "low"})


class ParseFieldTests(unittest.TestCase):
    def test_basic_extraction(self):
        self.assertEqual(parse_field("Take: Heal", "Take"), "Heal")

    def test_case_insensitive_both_sides(self):
        # Unlike parse_fields, parse_field lowercases the key too.
        self.assertEqual(parse_field("take: heal", "Take"), "heal")

    def test_missing_returns_empty_string(self):
        self.assertEqual(parse_field("Other: x", "Take"), "")

    def test_no_markdown_strip_asymmetry(self):
        # parse_field does NOT strip markdown (parse_fields does). Pin the gap.
        self.assertEqual(parse_field("Take: **Heal**", "Take"), "**Heal**")

    def test_no_truncation(self):
        long_val = "y" * 400
        self.assertEqual(parse_field(f"Take: {long_val}", "Take"), long_val)

    def test_first_match_wins(self):
        self.assertEqual(parse_field("Take: first\nTake: second", "Take"), "first")

    def test_value_is_stripped(self):
        self.assertEqual(parse_field("Take:   Heal  ", "Take"), "Heal")


if __name__ == "__main__":
    unittest.main()
