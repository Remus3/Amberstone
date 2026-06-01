# arch: item 244 coach-field markdown-emphasis strip | section=coach_integration | frozen=no
"""SR coach field-parse must strip stray markdown emphasis (item 244).

The Haiku SR coach occasionally emits markdown bold into a field value -
observed live as ``coach.action = "** FREEZE WAVE"`` and
``objective = "** Skip drake setup ..."`` during a ranked game. The
existing ``_parse_response`` strip (``s.lstrip("*").rstrip("*")``) only
fires when the WHOLE line begins/ends with ``*``; a ``**`` that sits
AFTER the ``Action:`` label (mid-line) or on a continuation line slips
through into the artifact and renders as a literal ``**`` on the
dashboard. ``_parse_response`` now strips paired ``**bold**`` / ``*em*``
wrappers and leading/trailing emphasis runs from each field value (the
``choices`` JSON field is left untouched).

``_parse_response`` reads nothing off ``self``, so the test drives it on a
bare instance via ``__new__`` (avoids the coach's API-key/config init).
"""
from __future__ import annotations

import unittest

from coach_integration._coach import CoachIntegration


def _parse(text: str) -> dict:
    inst = CoachIntegration.__new__(CoachIntegration)
    return inst._parse_response(text)


class MarkdownEmphasisStripTests(unittest.TestCase):
    def test_leading_double_star_stripped_from_action(self):
        fields = _parse("Action: ** FREEZE WAVE")
        self.assertEqual(fields["action"], "FREEZE WAVE")
        self.assertNotIn("*", fields["action"])

    def test_paired_bold_unwrapped_in_objective(self):
        fields = _parse("Objective: **Skip drake** until 700g [T]2:43")
        self.assertEqual(fields["objective"], "Skip drake until 700g [T]2:43")
        self.assertNotIn("*", fields["objective"])

    def test_inline_bold_unwrapped_in_fight_rule(self):
        fields = _parse("Fight rule: do **not** dive past river")
        self.assertEqual(fields["fight_rule"], "do not dive past river")

    def test_multiple_fields_all_clean(self):
        raw = (
            "Action: **WARD DRAKE PIT**\n"
            "Immediate: ** back off, [E]Ivern pathing top\n"
            "Objective: hold lane\n"
        )
        fields = _parse(raw)
        for k in ("action", "immediate", "objective"):
            self.assertNotIn("*", fields[k], f"field {k} kept a stray *")
        self.assertEqual(fields["action"], "WARD DRAKE PIT")
        self.assertEqual(fields["immediate"], "back off, [E]Ivern pathing top")

    def test_clean_value_unchanged(self):
        # No emphasis present -> value passes through verbatim (no over-strip).
        fields = _parse("Objective: Skip drake setup, stay lane until 50% HP")
        self.assertEqual(
            fields["objective"], "Skip drake setup, stay lane until 50% HP"
        )

    def test_bracket_tags_survive_strip(self):
        # The [A]/[E]/[T] role tags must NOT be touched by the markdown
        # strip (they are cleaned separately in _write_fields for action).
        fields = _parse("Risk: [E]Ivern gank window [T]2:30-3:15")
        self.assertEqual(fields["risk"], "[E]Ivern gank window [T]2:30-3:15")

    def test_choices_json_field_not_markdown_stripped(self):
        # choices is a JSON array passthrough; a literal * inside a JSON
        # string (rare but legal) must not be mangled by the emphasis strip.
        fields = _parse('Choices: [{"key":"A","label":"hold"}]')
        self.assertEqual(fields["choices"], '[{"key":"A","label":"hold"}]')


if __name__ == "__main__":
    unittest.main()
