# arch: P2.2 structured-output hardening - coach_choices wire golden-master | section=core | frozen=no
"""Wire-preservation golden master for core.coach_choices (P2.2).

Pins the EXACT serialized dict bytes that the dashboard consumes, plus the
parse / synthesize coercion edges, so the CoachChoice dataclass -> pydantic
swap cannot change what crosses the wire. Complements the broader behavior
tests in test_coach_choices.py; this file locks the serialized shape itself.

Shape-agnostic: introspects fields via to_dict().keys() (works for a stdlib
dataclass or any pydantic shape), so it stays green through the swap.
"""
from __future__ import annotations

import unittest

from core import coach_choices as cc


class WireShapeTests(unittest.TestCase):
    def test_field_set_exact(self):
        keys = set(cc.CoachChoice(key="A", label="X").to_dict().keys())
        self.assertEqual(
            keys,
            {"key", "label", "expected_outcome", "confidence", "source_tag"},
        )

    def test_to_dict_full_dict_equality(self):
        c = cc.CoachChoice(
            key="A", label="Contest", expected_outcome="Win drake",
            confidence="high", source_tag="archetype_sim",
        )
        self.assertEqual(c.to_dict(), {
            "key": "A", "label": "Contest", "expected_outcome": "Win drake",
            "confidence": "high", "source_tag": "archetype_sim",
        })

    def test_to_dict_defaults(self):
        c = cc.CoachChoice(key="B", label="Concede")
        self.assertEqual(c.to_dict(), {
            "key": "B", "label": "Concede", "expected_outcome": "",
            "confidence": "mid", "source_tag": "",
        })

    def test_to_jsonable_empty_list(self):
        self.assertEqual(cc.to_jsonable([]), [])

    def test_to_jsonable_multi(self):
        cs = [
            cc.CoachChoice(key="A", label="Engage"),
            cc.CoachChoice(key="B", label="Disengage"),
        ]
        self.assertEqual(cc.to_jsonable(cs), [
            {"key": "A", "label": "Engage", "expected_outcome": "",
             "confidence": "mid", "source_tag": ""},
            {"key": "B", "label": "Disengage", "expected_outcome": "",
             "confidence": "mid", "source_tag": ""},
        ])


class ParsePipelineWireTests(unittest.TestCase):
    def test_full_two_choice_wire_bytes(self):
        coach = {"choices": [
            {"key": "A", "label": "Contest", "expected_outcome": "Win drake",
             "confidence": "high", "source_tag": "archetype_sim"},
            {"key": "B", "label": "Concede", "expected_outcome": "Trade top",
             "confidence": "mid", "source_tag": "winrate_hist"},
        ]}
        self.assertEqual(cc.to_jsonable(cc.parse_choices(coach)), [
            {"key": "A", "label": "Contest", "expected_outcome": "Win drake",
             "confidence": "high", "source_tag": "archetype_sim"},
            {"key": "B", "label": "Concede", "expected_outcome": "Trade top",
             "confidence": "mid", "source_tag": "winrate_hist"},
        ])

    def test_key_coercion_multichar_to_first_upper(self):
        out = cc.parse_choices({"choices": [{"key": "abc", "label": "x"}]})
        self.assertEqual(out[0].key, "A")

    def test_key_coercion_empty_uses_positional_fallback(self):
        out = cc.parse_choices({"choices": [{"label": "first"}, {"label": "second"}]})
        self.assertEqual([c.key for c in out], ["A", "B"])

    def test_band_invalid_falls_back_mid(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "confidence": "ULTRA"},
        ]})
        self.assertEqual(out[0].confidence, "mid")

    def test_band_valid_preserved(self):
        for band in ("low", "mid", "high"):
            out = cc.parse_choices({"choices": [
                {"key": "A", "label": "x", "confidence": band},
            ]})
            self.assertEqual(out[0].confidence, band)

    def test_label_truncation_marker(self):
        out = cc.parse_choices({"choices": [{"key": "A", "label": "x" * 500}]})
        self.assertTrue(out[0].label.endswith("..."))
        self.assertLessEqual(len(out[0].label), 83)


class SynthesizeWireTests(unittest.TestCase):
    def test_synth_wire_bytes(self):
        out = cc.synthesize_simple_choices({
            "action": "Contest baron", "immediate": "5v5 mid",
            "fight_rule": "Stall til 6 items",
        })
        self.assertEqual(cc.to_jsonable(out), [
            {"key": "A", "label": "Contest", "expected_outcome": "5v5 mid",
             "confidence": "mid", "source_tag": "synth"},
            {"key": "B", "label": "Concede", "expected_outcome": "Stall til 6 items",
             "confidence": "mid", "source_tag": "synth"},
        ])


if __name__ == "__main__":
    unittest.main()
