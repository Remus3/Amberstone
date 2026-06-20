"""Pin the Arena coach's native `choices` array emit + passthrough.

Mirrors tests/test_aram_coach_choices_emit.py (item 120 ARAM commit
6b92382 by H). Arena coach now asks the model to optionally return
a JSON `choices` array alongside the existing 7 prose fields (action
/ round strategy / fight rule / augment advice / anvil advice /
target priority / risk). The output is a single-line JSON list
parsed in-handler and written into the artifact under
current["choices"] so the dashboard's state builder picks it up via
core.coach_choices.parse_choices.

These tests are grep-based DOM-contract smoke tests (cheap text
search) mirroring tests/test_aram_coach_choices_emit.py:

- PromptShapeTests: the SYSTEM prompt carries the `Choices:` field
  description, the JSON schema hint, the A/B/C key letters, and the
  three confidence band tokens.
- ParserPassthroughTests: the parse_fields call (via _OUTPUT_KEYS)
  includes `choices` as a key; the handler json.loads the value into
  a Python list; malformed JSON / non-list / absent field all reduce
  to [] without crashing; the empty list reaches current["choices"].
- CachePreservedTests: the Choices line is APPENDED after the
  existing Risk line in the OUTPUT FORMAT block (not inserted
  mid-block) so prior cached prefix bytes are byte-identical.

Scope: arena coach only. ARAM was H's pass-3 commit; brawl + sr are
a separate task per the run prompt.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "coaches" / "arena_coach.py"


class PromptShapeTests(unittest.TestCase):
    """The SYSTEM prompt block carries the new Choices field shape."""

    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_choices_field_label_present(self):
        # The field LABEL itself - "Choices:" on its own line.
        self.assertIn("Choices: <OPTIONAL", self.src)

    def test_schema_hint_describes_json_array(self):
        # The schema hint enumerates the 5 required keys per entry.
        for tok in ('"key"', '"label"', '"expected_outcome"',
                    '"confidence"', '"source_tag"'):
            self.assertIn(tok, self.src)

    def test_keys_are_A_B_C_in_order(self):
        # The schema text MUST mention the A/B/C keys are ordered.
        # The literal "A/B/C" + "in order" together is the contract.
        self.assertIn("A/B/C", self.src)
        self.assertIn("in order", self.src)

    def test_confidence_bands_enumerated(self):
        # The three valid bands MUST be enumerated in the prompt
        # (model has no other signal for the contract).
        # Match against the prompt's own quoted-band text.
        self.assertIn('"low"', self.src)
        self.assertIn('"mid"', self.src)
        self.assertIn('"high"', self.src)

    def test_empty_array_is_acceptable(self):
        # The prompt MUST tell the model "[] is OK" so it doesn't
        # padded-emit unrelated junk on idle ticks.
        self.assertIn("Return [] if", self.src)

    def test_single_line_json_required(self):
        # parse_fields is line-based; multi-line JSON would break
        # the labeled-pass for downstream fields. The prompt MUST
        # demand single-line output.
        self.assertIn("single line", self.src)

    def test_arena_source_tag_examples(self):
        # Arena-specific source_tag hints belong in the prompt
        # (mode-specific decision flavor; was specified in the run
        # prompt). At least one of the Arena-shaped tags MUST appear.
        self.assertTrue(
            ("augment-pick" in self.src)
            or ("round-trade" in self.src)
            or ("duo-rotate" in self.src),
            "Arena prompt MUST include Arena-flavored source_tag examples",
        )


class ParserPassthroughTests(unittest.TestCase):
    """The coach handler json.loads the choices string and writes a
    real Python list into the artifact."""

    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_output_keys_include_choices(self):
        # _OUTPUT_KEYS is the parse_fields() keys list. The trailing
        # entry MUST be "choices" so the field survives the labeled
        # pass and reaches the handler.
        # The exact literal in source so the contract is testable.
        self.assertIn('"risk", "choices"', self.src)

    def test_handler_decodes_via_shared_helper(self):
        # P2.2 tail: the choices JSON decode reads from the shared, validated
        # core.coach_output.CoachOutput.from_fields model (one seam). The coach
        # MUST import + build it from the parsed-fields dict.
        self.assertIn("from core.coach_output import CoachOutput", self.src)
        self.assertIn("CoachOutput.from_fields(", self.src)

    def test_shared_model_parity_with_decode_helper(self):
        # The new model seam MUST yield the same list the old helper did, so
        # the swap is behavior-preserving (CoachOutput.from_fields routes the
        # `choices` field through the SAME before-validator as decode_choices).
        from core.coach_output import CoachOutput, decode_choices
        sample = '[{"key":"A","label":"x"}]'
        self.assertEqual(
            CoachOutput.from_fields({"choices": sample}).choices,
            decode_choices(sample),
        )

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

    def test_passthrough_writes_to_current_choices(self):
        # The final current.update MUST carry the parsed list under
        # the canonical "choices" key the state builder reads.
        self.assertIn('"choices":       _choices_list,', self.src)

    def test_shared_helper_swallows_decode_errors(self):
        # Malformed JSON MUST NOT crash the tick - the shared helper absorbs
        # it and returns [].
        from core.coach_output import decode_choices
        self.assertEqual(decode_choices('[{"key":"A","label":"unterminated'), [])

    def test_choice_schema_matches_coach_choice_dataclass(self):
        # The prompt documents the model-EMITTED choice keys. CoachChoice may
        # ALSO carry server-derived fields (RC2 5.3 trigger) the model is not
        # asked to emit; those are excluded from the prompt-schema mirror.
        # Imported here so a rename of the dataclass breaks the test loudly.
        from core.coach_choices import CoachChoice  # noqa: WPS433
        from dataclasses import fields
        SERVER_DERIVED = {"trigger"}
        emitted = {f.name for f in fields(CoachChoice)} - SERVER_DERIVED
        self.assertEqual(
            emitted,
            {"key", "label", "expected_outcome", "confidence", "source_tag"},
            "Prompt schema MUST mirror CoachChoice model-emitted field set",
        )

    def test_passthrough_runs_before_current_update(self):
        # The handler MUST decode _choices_list BEFORE current.update
        # so the parsed value is in scope at update time. Order matters.
        idx_decode = self.src.index("_choices_list = CoachOutput.from_fields(")
        idx_update = self.src.index("current.update({", idx_decode)
        self.assertLess(
            idx_decode, idx_update,
            "Choices passthrough MUST run before current.update so "
            "the parsed list is in scope for the update dict",
        )


class CachePreservedTests(unittest.TestCase):
    """The new Choices line is appended AFTER the existing field
    descriptions in the cached system block (not inserted mid-block)
    so the cache prefix stays stable across the rollout."""

    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_choices_line_appears_after_risk(self):
        # The cache prefix runs from the SYSTEM block top through the
        # last pre-Choices field. Putting Choices AFTER "Risk:"
        # is what keeps the prior bytes unchanged.
        idx_risk = self.src.index("Risk: ")
        idx_choices = self.src.index("Choices: <OPTIONAL")
        self.assertLess(idx_risk, idx_choices,
                        "Choices line MUST follow Risk line in OUTPUT FORMAT")

    def test_choices_line_is_last_in_output_format(self):
        # After Choices, the SYSTEM block MUST close with the triple
        # quote terminator + the _USER_TEMPLATE definition. Nothing
        # else is allowed between Choices and the closing """.
        idx_choices = self.src.index("Choices: <OPTIONAL")
        idx_close = self.src.index('"""', idx_choices)
        between = self.src[idx_choices:idx_close]
        # Must be a single line: one newline after the > closer.
        # If extra label lines slipped in (e.g. "Notes: ..."), the
        # newline count would exceed 1.
        self.assertLessEqual(between.count("\n"), 1,
                             "No other lines may follow Choices in the SYSTEM block")

    def test_cache_control_marker_intact(self):
        # The ephemeral cache marker on the system block MUST still be
        # the exact literal aram_coach / aram_team_analyzer / champ_select
        # all use. Sanity-check it survived the prompt edit.
        self.assertIn('"cache_control": {"type": "ephemeral"}', self.src)

    def test_user_template_not_polluted(self):
        # The choices field belongs in SYSTEM (it's a model output
        # contract, not per-tick state). Make sure no Choices: line
        # leaked into _USER_TEMPLATE.
        idx_user = self.src.index("_USER_TEMPLATE")
        idx_close = self.src.index('"""', self.src.index('"""', idx_user) + 3)
        user_block = self.src[idx_user:idx_close]
        self.assertNotIn("Choices:", user_block)

    def test_augment_select_prompt_not_polluted(self):
        # Arena has a SECOND short system prompt for augment-select
        # ticks (_AUGMENT_SELECT_PROMPT). Choices contract belongs in
        # the main coach prompt only - the augment-select sub-prompt
        # stays a separate Take/Why/Gameplan shape.
        idx_aug = self.src.index("_AUGMENT_SELECT_PROMPT")
        idx_close = self.src.index('"""', self.src.index('"""', idx_aug) + 3)
        aug_block = self.src[idx_aug:idx_close]
        self.assertNotIn("Choices:", aug_block)


class JsonDecodeBehaviorTests(unittest.TestCase):
    """End-to-end check on the json.loads behavior the handler relies on
    (no monkeypatching needed - pure-Python contract on the data path)."""

    def test_well_formed_choices_decodes_to_list(self):
        sample = '[{"key":"A","label":"Take Cyclone","expected_outcome":"AoE clears wave fights","confidence":"mid","source_tag":"augment-pick"}]'
        parsed = json.loads(sample)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["key"], "A")
        self.assertEqual(parsed[0]["source_tag"], "augment-pick")

    def test_empty_array_decodes_to_empty_list(self):
        parsed = json.loads("[]")
        self.assertEqual(parsed, [])
        self.assertIsInstance(parsed, list)

    def test_malformed_json_raises(self):
        # Confirm the except Exception in the handler catches the
        # expected error class (so the swallow-on-error path is real).
        with self.assertRaises(json.JSONDecodeError):
            json.loads('[{"key":"A","label":"unterminated')


if __name__ == "__main__":
    unittest.main()
