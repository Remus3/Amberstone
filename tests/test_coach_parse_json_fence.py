# arch: coach _parse_response JSON-fenced-reply fallback | section=coach_integration | frozen=no
"""SR coach _parse_response must read a markdown ```json-fenced JSON object.

Observed live 2026-06-21 (SR practice, Caitlyn): the Haiku coach returned its
reply as a ```json-fenced JSON OBJECT instead of the line format, so the
line-oriented parser read ZERO fields and the live coach text went BLANK (the
overlay stuck on its "will render mid-game" scaffold) until the next
state-change re-tick. The parser now falls back to JSON when the reply is a
(fenced or bare) JSON object, mapping its keys through the same field_map; the
line-format path stays byte-identical.

_parse_response reads nothing off self, so the test drives it on a bare instance
via __new__ (avoids the coach's API-key/config init), mirroring item 244.
"""
from __future__ import annotations

import unittest

from coach_integration._coach import CoachIntegration


def _parse(text):
    inst = CoachIntegration.__new__(CoachIntegration)
    return inst._parse_response(text)


# The exact shape observed live (a fenced object with prose values).
_FENCED = (
    "```json\n"
    "{\n"
    '  "action": "SETUP DRAKE CONTEST",\n'
    '  "wave": "neutral mid - no immediate pressure, macro window open",\n'
    '  "objective": "setup drake pit [T]0:03, full team required"\n'
    "}\n"
    "```"
)


class JsonFenceParseTests(unittest.TestCase):
    def test_fenced_json_object_fields_extracted(self):
        fields = _parse(_FENCED)
        self.assertEqual(fields.get("action"), "SETUP DRAKE CONTEST")
        self.assertEqual(
            fields.get("wave"),
            "neutral mid - no immediate pressure, macro window open",
        )
        self.assertIn("objective", fields)

    def test_bare_json_object_no_fence(self):
        fields = _parse('{"action": "BACK OFF", "risk": "Zed ult up"}')
        self.assertEqual(fields.get("action"), "BACK OFF")
        self.assertEqual(fields.get("risk"), "Zed ult up")

    def test_underscore_and_space_keys_both_map(self):
        # fight_rule (the internal name) and "fight rule" (the label) both resolve.
        self.assertEqual(_parse('{"fight_rule": "do not dive"}').get("fight_rule"),
                         "do not dive")
        self.assertEqual(_parse('{"fight rule": "hold the line"}').get("fight_rule"),
                         "hold the line")

    def test_choices_json_array_passthrough(self):
        fields = _parse('{"action":"FARM","choices":[{"key":"A","label":"hold"}]}')
        self.assertEqual(fields.get("action"), "FARM")
        # choices stays a JSON string for the downstream decode_choices seam.
        self.assertIn('"key"', fields.get("choices", ""))


class LineFormatUnchangedTests(unittest.TestCase):
    """The JSON fallback only fires when the reply starts with ``` or { , so the
    line-format path is byte-identical."""

    def test_line_format_still_parses(self):
        fields = _parse("Action: FREEZE WAVE\nObjective: hold until 700g")
        self.assertEqual(fields.get("action"), "FREEZE WAVE")
        self.assertEqual(fields.get("objective"), "hold until 700g")

    def test_line_value_with_brace_not_json(self):
        # A line value containing a brace must NOT be mis-read as a JSON object.
        self.assertEqual(_parse("Action: ward {drake} pit").get("action"),
                         "ward {drake} pit")

    def test_garbage_yields_empty(self):
        # Non-JSON, non-line prose -> {} (the synthesizer fallback path).
        self.assertEqual(_parse("just some prose with no fields"), {})


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_ascii(self):
        raw = open(__file__, encoding="utf-8").read()
        self.assertEqual(raw, raw.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
