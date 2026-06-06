"""Pin the SR coach's native `choices` array emit + passthrough.

Mirrors tests/test_aram_coach_choices_emit.py. The SR coach has a
STRUCTURAL DEVIATION from ARAM/Arena/Brawl: the system prompt lives in
``coach_integration/_sr_prompt.py`` (as ``SR_SYSTEM_PROMPT``), and the
parser + passthrough live in ``coach_integration/_coach.py`` (in
``CoachIntegration._parse_response`` + ``CoachIntegration._write_fields``).
That split is preserved here so the tests don't pretend the SR coach is a
mode-coach module under ``coaches/``.

Item 120 follow-up - the SR coach now asks the model to optionally
return a JSON `choices` array alongside the existing prose fields
(action / immediate / next / wave / objective / fight_rule / reset_item
/ risk). The output is a single-line JSON list parsed in-handler and
written into the artifact under cur["choices"] so the dashboard's
state builder picks it up via core.coach_choices.parse_choices.

These tests are grep-based DOM-contract smoke tests (cheap text
search) mirroring the aram pattern:

- PromptShapeTests: SR_SYSTEM_PROMPT in _sr_prompt.py carries the
  `Choices:` field description, the JSON schema hint, the A/B/C key
  letters, and the three confidence band tokens.
- ParserPassthroughTests: the _parse_response field_map in _coach.py
  includes `choices`; the _write_fields handler json.loads the value
  into a Python list; malformed JSON / non-list / absent field all
  reduce to [] without crashing; the empty list reaches fields["choices"]
  which then flows into current["choices"] via current.update(fields).
- CachePreservedTests: the Choices line is the LAST line of the
  OUTPUT FORMAT block (appended after the existing Risk line) so prior
  cached prefix bytes are byte-identical.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


PROMPT_SRC = (
    Path(__file__).resolve().parent.parent
    / "coach_integration" / "_sr_prompt.py"
)
COACH_SRC = (
    Path(__file__).resolve().parent.parent
    / "coach_integration" / "_coach.py"
)


class PromptShapeTests(unittest.TestCase):
    """The SR_SYSTEM_PROMPT in _sr_prompt.py carries the new Choices field
    shape."""

    def setUp(self):
        self.src = PROMPT_SRC.read_text(encoding="utf-8")

    def test_choices_field_label_present(self):
        # The field LABEL itself - "Choices:" on its own line inside the
        # SR_SYSTEM_PROMPT block.
        self.assertIn("Choices: <REQUIRED", self.src)

    def test_choices_lives_inside_sr_system_prompt(self):
        # Scope check: the Choices line MUST be inside the SR_SYSTEM_PROMPT
        # triple-quoted block, NOT inside ARAM_SYSTEM_PROMPT (which lives
        # in the same file).
        sr_start = self.src.index("SR_SYSTEM_PROMPT")
        sr_end = self.src.index('"""', self.src.index('"""', sr_start) + 3)
        sr_block = self.src[sr_start:sr_end]
        self.assertIn("Choices: <REQUIRED", sr_block,
                      "Choices line must be inside SR_SYSTEM_PROMPT block")

    def test_schema_hint_describes_json_array(self):
        # The schema hint enumerates the 5 required keys per entry.
        for tok in ('"key"', '"label"', '"expected_outcome"',
                    '"confidence"', '"source_tag"'):
            self.assertIn(tok, self.src)

    def test_keys_are_A_B_C_in_order(self):
        # The schema text MUST mention the A/B/C keys are ordered.
        self.assertIn("A/B/C", self.src)
        self.assertIn("in order", self.src)

    def test_confidence_bands_enumerated(self):
        # The three valid bands MUST be enumerated in the prompt
        # (model has no other signal for the contract).
        self.assertIn('"low"', self.src)
        self.assertIn('"mid"', self.src)
        self.assertIn('"high"', self.src)

    def test_empty_array_is_acceptable(self):
        # The prompt MUST tell the model "[] is OK" so it doesn't
        # padded-emit unrelated junk on idle ticks.
        self.assertIn("Return []", self.src)

    def test_single_line_json_required(self):
        # The line-based parser would break on multi-line JSON; the
        # prompt MUST demand single-line output.
        self.assertIn("single line", self.src)


class ParserPassthroughTests(unittest.TestCase):
    """The CoachIntegration handler json.loads the choices string and
    writes a real Python list into the artifact."""

    def setUp(self):
        self.src = COACH_SRC.read_text(encoding="utf-8")

    def test_parse_response_field_map_includes_choices(self):
        # The field_map in CoachIntegration._parse_response MUST contain
        # an entry mapping "choices" -> "choices"; otherwise the parser
        # never recognizes the line and the passthrough is fed an empty
        # string forever.
        self.assertIn('"choices":      "choices"', self.src)

    def test_handler_decodes_via_shared_helper(self):
        # P2.2 tail: the choices JSON decode moved to the shared, validated
        # core.coach_output.decode_choices (one seam). The SR handler MUST
        # import + call it on the parsed `choices` field.
        self.assertIn("from core.coach_output import decode_choices", self.src)
        self.assertIn("decode_choices(", self.src)

    def test_decode_not_inlined(self):
        # The old inline json.loads / isinstance block MUST be gone so the
        # shared helper is the single source of truth for the decode.
        self.assertNotIn("json.loads(_choices_raw)", self.src)
        self.assertNotIn("isinstance(_parsed, list)", self.src)

    def test_shared_helper_guards_list_and_default(self):
        # The list-guard + []-default live (and are tested) in the shared
        # helper; assert that contract at its home so a change there breaks
        # loudly.
        from core.coach_output import decode_choices
        self.assertEqual(decode_choices(None), [])
        self.assertEqual(decode_choices('{"not": "a list"}'), [])

    def test_passthrough_writes_to_fields_choices(self):
        # SR coach hands off via `current.update(fields)` in _write_fields,
        # so the choices list MUST land in `fields["choices"]` before that
        # update (replacing the raw string parsed earlier).
        self.assertIn('fields["choices"] = decode_choices(fields.get("choices"))', self.src)

    def test_shared_helper_swallows_decode_errors(self):
        # Malformed JSON MUST NOT crash the tick - the shared helper absorbs
        # it and returns [].
        from core.coach_output import decode_choices
        self.assertEqual(decode_choices('[{"key":"A","label":"unterminated'), [])

    def test_choice_schema_matches_coach_choice_dataclass(self):
        # The 5 schema field names in the prompt MUST match the 5 fields
        # exposed by core.coach_choices.CoachChoice exactly.
        from core.coach_choices import CoachChoice  # noqa: WPS433
        from dataclasses import fields
        expected = {f.name for f in fields(CoachChoice)}
        self.assertEqual(
            expected,
            {"key", "label", "expected_outcome", "confidence", "source_tag"},
            "Prompt schema MUST mirror CoachChoice dataclass field set",
        )


class CachePreservedTests(unittest.TestCase):
    """The new Choices line is appended AFTER the existing field
    descriptions in the cached system block (not inserted mid-block)
    so the cache prefix stays stable across the rollout."""

    def setUp(self):
        self.prompt_src = PROMPT_SRC.read_text(encoding="utf-8")
        self.coach_src = COACH_SRC.read_text(encoding="utf-8")

    def test_choices_line_appears_after_risk(self):
        # The cache prefix runs from the SYSTEM block top through the
        # last pre-Choices field. Putting Choices AFTER "Risk:" is what
        # keeps the prior bytes unchanged (Risk is the last existing
        # field in the SR OUTPUT FORMAT block).
        sr_start = self.prompt_src.index("SR_SYSTEM_PROMPT")
        sr_end = self.prompt_src.index('"""', self.prompt_src.index('"""', sr_start) + 3)
        sr_block = self.prompt_src[sr_start:sr_end]
        idx_risk = sr_block.index("Risk:")
        idx_choices = sr_block.index("Choices: <REQUIRED")
        self.assertLess(idx_risk, idx_choices,
                        "Choices line MUST follow Risk line")

    def test_choices_line_is_last_in_output_format(self):
        # After Choices, the SR_SYSTEM_PROMPT block MUST close with the
        # triple quote terminator. Nothing else allowed between Choices
        # and the closing """.
        sr_start = self.prompt_src.index("SR_SYSTEM_PROMPT")
        sr_block_open = self.prompt_src.index('"""', sr_start) + 3
        sr_block_close = self.prompt_src.index('"""', sr_block_open)
        sr_block = self.prompt_src[sr_block_open:sr_block_close]
        idx_choices = sr_block.index("Choices: <REQUIRED")
        # After the Choices line should be at most one newline (the
        # trailing \n before """).
        between = sr_block[idx_choices:]
        self.assertLessEqual(between.count("\n"), 1,
                             "No other lines may follow Choices in the SYSTEM block")

    def test_cache_control_marker_intact(self):
        # The ephemeral cache marker on the system block MUST still be
        # the exact literal in _coach.py's messages.create() call.
        self.assertIn('"cache_control": {"type": "ephemeral"}', self.coach_src)

    def test_choices_not_added_to_aram_prompt_in_same_file(self):
        # _sr_prompt.py also holds ARAM_SYSTEM_PROMPT for legacy paths.
        # The brawl/SR slice does NOT touch the ARAM prompt embedded in
        # this file (that path is owned by coaches/aram_coach.py); make
        # sure no Choices line bled into ARAM_SYSTEM_PROMPT here.
        aram_start = self.prompt_src.index("ARAM_SYSTEM_PROMPT")
        aram_block_open = self.prompt_src.index('"""', aram_start) + 3
        aram_block_close = self.prompt_src.index('"""', aram_block_open)
        aram_block = self.prompt_src[aram_block_open:aram_block_close]
        self.assertNotIn(
            "Choices: <REQUIRED", aram_block,
            "Slice scope: ARAM_SYSTEM_PROMPT inside _sr_prompt.py must NOT "
            "be touched (ARAM coach owns its own prompt under coaches/)",
        )


class JsonDecodeBehaviorTests(unittest.TestCase):
    """End-to-end check on the json.loads behavior the handler relies on
    (no monkeypatching needed - pure-Python contract on the data path)."""

    def test_well_formed_choices_decodes_to_list(self):
        sample = '[{"key":"A","label":"Push","expected_outcome":"crash wave","confidence":"high","source_tag":"lane-state"}]'
        parsed = json.loads(sample)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["key"], "A")

    def test_empty_array_decodes_to_empty_list(self):
        parsed = json.loads("[]")
        self.assertEqual(parsed, [])
        self.assertIsInstance(parsed, list)

    def test_malformed_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            json.loads('[{"key":"A","label":"unterminated')


if __name__ == "__main__":
    unittest.main()
