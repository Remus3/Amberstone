# arch: P2.2 tail - shared coach-output model parity golden master | section=core | frozen=no
"""Golden master for the shared `core/coach_output.py` choices decode (P2.2 tail).

`decode_choices` replaces the native-emit choices JSON decode that was
duplicated verbatim in all 4 coaches. This pins that it is byte-for-byte
equivalent to the prior inline block, so the caller migration cannot change
what reaches the coaching artifact (and thus the dashboard).
"""
from __future__ import annotations

import json
import unittest

from core.coach_output import CoachOutput, decode_choices
from pydantic import BaseModel


def _old_inline_decode(raw_value) -> list:
    """Verbatim reproduction of the pre-P2.2 inline block in every coach:

        _choices_list = []
        _choices_raw = fields.get("choices", "").strip()
        if _choices_raw:
            try:
                _parsed = json.loads(_choices_raw)
                if isinstance(_parsed, list):
                    _choices_list = _parsed
            except Exception:
                pass
    """
    _choices_list: list = []
    _choices_raw = (raw_value or "").strip() if isinstance(raw_value, str) else (
        "" if raw_value is None else raw_value)
    # The old code only ever received a str (parse_fields values are str) or an
    # absent key (-> "" via .get default). Model both: str path mirrors exactly.
    if isinstance(raw_value, str):
        _choices_raw = raw_value.strip()
        if _choices_raw:
            try:
                _parsed = json.loads(_choices_raw)
                if isinstance(_parsed, list):
                    _choices_list = _parsed
            except Exception:
                pass
    return _choices_list


_STR_CASES = [
    '[{"key":"A","label":"hold"},{"key":"B","label":"push"}]',
    '[]',
    '[{"key":"A","label":"x","expected_outcome":"win","confidence":"high","source_tag":"sim"}]',
    '',
    '   ',
    'not json at all',
    '{"a": 1}',          # valid JSON but a dict, not a list
    '[1, 2, 3]',         # list of non-dicts (decode is raw; cleaning is downstream)
    '[{"key":"A"}',      # truncated / malformed JSON
    '"a string"',        # valid JSON but not a list
    '42',                # valid JSON but not a list
]


class DecodeChoicesParityTests(unittest.TestCase):
    def test_matches_old_inline_for_every_str_case(self):
        for raw in _STR_CASES:
            with self.subTest(raw=raw):
                self.assertEqual(decode_choices(raw), _old_inline_decode(raw))

    def test_none_returns_empty(self):
        self.assertEqual(decode_choices(None), [])

    def test_absent_key_get_default_returns_empty(self):
        # Callers pass fields.get("choices") -> None when absent.
        self.assertEqual(decode_choices({}.get("choices")), [])

    def test_valid_array_decoded_raw(self):
        raw = '[{"key":"A","label":"hold"},{"key":"B","label":"push"}]'
        self.assertEqual(decode_choices(raw), [
            {"key": "A", "label": "hold"},
            {"key": "B", "label": "push"},
        ])

    def test_dict_payload_returns_empty(self):
        self.assertEqual(decode_choices('{"key":"A"}'), [])

    def test_already_a_list_passes_through(self):
        v = [{"key": "A", "label": "x"}]
        self.assertEqual(decode_choices(v), v)

    def test_raw_not_cleaned(self):
        # decode is raw; non-dict / extra-field entries survive (parse_choices
        # cleans downstream, not here).
        self.assertEqual(decode_choices('[1, 2, 3]'), [1, 2, 3])


class CoachOutputModelTests(unittest.TestCase):
    def test_is_pydantic_model(self):
        self.assertTrue(issubclass(CoachOutput, BaseModel))

    def test_from_fields_decodes_choices_and_keeps_extras(self):
        fields = {
            "action": "FREEZE WAVE",
            "fight_rule": "2v2 only",
            "choices": '[{"key":"A","label":"hold"}]',
        }
        art = CoachOutput.from_fields(fields).to_artifact()
        self.assertEqual(art["action"], "FREEZE WAVE")
        self.assertEqual(art["fight_rule"], "2v2 only")
        self.assertEqual(art["choices"], [{"key": "A", "label": "hold"}])

    def test_from_fields_none_safe(self):
        self.assertEqual(CoachOutput.from_fields(None).to_artifact(), {"choices": []})

    def test_to_artifact_is_json_safe(self):
        art = CoachOutput.from_fields({"choices": '[{"key":"A","label":"x"}]'}).to_artifact()
        json.dumps(art)  # must not raise


if __name__ == "__main__":
    unittest.main()
