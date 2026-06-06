"""Pin the Brawl coach's native `choices` array emit + passthrough.

Mirrors tests/test_aram_coach_choices_emit.py. The brawl coach has THREE
system prompts (Nexus Blitz / URF / OneForAll) so the prompt-shape tests
walk all three; the parser-passthrough + cache-preserved tests pin the
single shared write path in _run_coach.

Item 120 follow-up - the brawl coach now asks the model to optionally
return a JSON `choices` array alongside the existing prose fields
(action / immediate / fight rule / objective / risk / etc). The
output is a single-line JSON list parsed in-handler and written into
the artifact under cur["choices"] so the dashboard's state builder
picks it up via core.coach_choices.parse_choices.

These tests are grep-based DOM-contract smoke tests (cheap text
search) mirroring the aram pattern:

- PromptShapeTests: each of the 3 SYSTEM prompts (NB/URF/OFA) carries
  the `Choices:` field description, the JSON schema hint, the A/B/C
  key letters, and the three confidence band tokens.
- ParserPassthroughTests: the three _*_OUTPUT_KEYS lists include
  `choices`; the handler json.loads the value into a Python list;
  malformed JSON / non-list / absent field all reduce to []
  without crashing; the empty list reaches current["choices"].
- CachePreservedTests: the Choices line is the LAST line of each
  OUTPUT FORMAT block (appended after the existing last field) so
  prior cached prefix bytes are byte-identical.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "coaches" / "brawl_coach.py"


class PromptShapeTests(unittest.TestCase):
    """Each of the 3 SYSTEM prompts carries the new Choices field shape."""

    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_choices_field_label_appears_3_times(self):
        # One Choices: <OPTIONAL ... line per system prompt
        # (NB + URF + OFA = 3 occurrences).
        self.assertEqual(self.src.count("Choices: <REQUIRED"), 3)

    def test_schema_hint_describes_json_array(self):
        # The schema hint enumerates the 5 required keys per entry.
        # Each shows up 3x (one per prompt).
        for tok in ('"key"', '"label"', '"expected_outcome"',
                    '"confidence"', '"source_tag"'):
            self.assertGreaterEqual(self.src.count(tok), 3,
                                    f"{tok!r} should appear in all 3 brawl prompts")

    def test_keys_are_A_B_C_in_order(self):
        # The schema text MUST mention the A/B/C keys are ordered.
        # Each prompt has one occurrence => 3 total.
        self.assertEqual(self.src.count("A/B/C"), 3)
        self.assertGreaterEqual(self.src.count("in order"), 3)

    def test_confidence_bands_enumerated(self):
        # The three valid bands MUST be enumerated in each prompt
        # (model has no other signal for the contract). 3 prompts -> >=3.
        self.assertGreaterEqual(self.src.count('"low"'), 3)
        self.assertGreaterEqual(self.src.count('"mid"'), 3)
        self.assertGreaterEqual(self.src.count('"high"'), 3)

    def test_empty_array_is_acceptable(self):
        # Each prompt MUST tell the model "[] is OK" so it doesn't
        # padded-emit unrelated junk on idle ticks.
        self.assertGreaterEqual(self.src.count("Return []"), 3)

    def test_single_line_json_required(self):
        # parse_fields is line-based; multi-line JSON would break
        # the labeled-pass for downstream fields. Each prompt MUST
        # demand single-line output.
        self.assertGreaterEqual(self.src.count("single line"), 3)


class ParserPassthroughTests(unittest.TestCase):
    """The coach handler json.loads the choices string and writes a
    real Python list into the artifact."""

    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_nb_output_keys_includes_choices(self):
        # The _NB_OUTPUT_KEYS list MUST end with `"choices"` so that
        # parse_fields() retains the field for the passthrough block.
        self.assertIn('"risk", "choices"', self.src)
        # Locate _NB_OUTPUT_KEYS specifically.
        idx = self.src.index("_NB_OUTPUT_KEYS")
        end = self.src.index("\n", idx)
        line = self.src[idx:end]
        self.assertIn('"choices"', line)

    def test_urf_output_keys_includes_choices(self):
        # The _URF_OUTPUT_KEYS list MUST end with `"choices"`.
        idx = self.src.index("_URF_OUTPUT_KEYS")
        end = self.src.index("\n", idx)
        line = self.src[idx:end]
        self.assertIn('"comp analysis", "choices"', line)

    def test_ofa_output_keys_includes_choices(self):
        # The _OFA_OUTPUT_KEYS list MUST end with `"choices"`.
        idx = self.src.index("_OFA_OUTPUT_KEYS")
        end = self.src.index("\n", idx)
        line = self.src[idx:end]
        self.assertIn('"choices"', line)

    def test_handler_decodes_via_shared_helper(self):
        # P2.2 tail: the choices JSON decode moved to the shared, validated
        # core.coach_output.decode_choices (one seam). The coach MUST import
        # + call it on the parsed `choices` field.
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

    def test_passthrough_writes_to_current_choices(self):
        # The final current.update MUST carry the parsed list under the
        # canonical "choices" key the state builder reads.
        self.assertIn('"choices":       _choices_list,', self.src)

    def test_shared_helper_swallows_decode_errors(self):
        # Malformed JSON MUST NOT crash the tick - the shared helper absorbs
        # it and returns [].
        from core.coach_output import decode_choices
        self.assertEqual(decode_choices('[{"key":"A","label":"unterminated'), [])

    def test_choice_schema_matches_coach_choice_dataclass(self):
        # The 5 schema field names in the prompt MUST match the 5 fields
        # exposed by core.coach_choices.CoachChoice exactly. Imported here
        # so any future rename of the dataclass breaks the test loudly
        # rather than silently shipping a contract drift.
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
    descriptions in each cached system block (not inserted mid-block)
    so the cache prefix stays stable across the rollout."""

    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_nb_choices_after_risk(self):
        # NB prompt: Risk line is the last field pre-Choices.
        nb_start = self.src.index("_NB_SYSTEM_PROMPT")
        nb_end = self.src.index('"""', self.src.index('"""', nb_start) + 3)
        block = self.src[nb_start:nb_end]
        idx_risk = block.index("Risk:")
        idx_choices = block.index("Choices: <REQUIRED")
        self.assertLess(idx_risk, idx_choices,
                        "NB: Choices line MUST follow Risk line")

    def test_urf_choices_after_comp_analysis(self):
        # URF prompt: Comp analysis line is the last field pre-Choices.
        urf_start = self.src.index("_URF_SYSTEM_PROMPT")
        urf_end = self.src.index('"""', self.src.index('"""', urf_start) + 3)
        block = self.src[urf_start:urf_end]
        idx_comp = block.index("Comp analysis:")
        idx_choices = block.index("Choices: <REQUIRED")
        self.assertLess(idx_comp, idx_choices,
                        "URF: Choices line MUST follow Comp analysis line")

    def test_ofa_choices_after_risk(self):
        # OFA prompt: Risk line is the last field pre-Choices.
        ofa_start = self.src.index("_OFA_SYSTEM_PROMPT")
        ofa_end = self.src.index('"""', self.src.index('"""', ofa_start) + 3)
        block = self.src[ofa_start:ofa_end]
        idx_risk = block.index("Risk:")
        idx_choices = block.index("Choices: <REQUIRED")
        self.assertLess(idx_risk, idx_choices,
                        "OFA: Choices line MUST follow Risk line")

    def test_choices_line_is_last_in_each_output_format(self):
        # After each Choices line, the SYSTEM block MUST close with the
        # triple quote terminator. Nothing else allowed between Choices
        # and the closing """.
        idx = 0
        count = 0
        while True:
            try:
                idx_choices = self.src.index("Choices: <REQUIRED", idx)
            except ValueError:
                break
            idx_close = self.src.index('"""', idx_choices)
            between = self.src[idx_choices:idx_close]
            # Must be a single line: one newline after the > closer.
            self.assertLessEqual(between.count("\n"), 1,
                                 "No other lines may follow Choices in a SYSTEM block")
            idx = idx_close
            count += 1
        self.assertEqual(count, 3, "Expected Choices block in 3 brawl prompts")

    def test_cache_control_marker_intact(self):
        # The ephemeral cache marker on the system block MUST still be
        # the exact literal aram coach uses. Sanity-check it survived
        # the prompt edit.
        self.assertIn('"cache_control": {"type": "ephemeral"}', self.src)


class JsonDecodeBehaviorTests(unittest.TestCase):
    """End-to-end check on the json.loads behavior the handler relies on
    (no monkeypatching needed - pure-Python contract on the data path)."""

    def test_well_formed_choices_decodes_to_list(self):
        sample = '[{"key":"A","label":"Engage","expected_outcome":"win fight","confidence":"mid","source_tag":"fight-trade"}]'
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
