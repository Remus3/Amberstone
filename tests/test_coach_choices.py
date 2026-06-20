"""Contract tests for core.coach_choices.

The on-the-wire shape (CoachChoice) is what the dashboard JSON expects;
the parser is forgiving (missing fields, bad types, out-of-range bands);
the synthesizer is conservative (returns [] when no binary verb is present).
"""

from __future__ import annotations

import unittest

from core import coach_choices as cc


class ParserHappyPath(unittest.TestCase):
    def test_well_formed_two_choice_round_trip(self):
        coach = {
            "action": "Contest dragon",
            "choices": [
                {"key": "A", "label": "Contest", "expected_outcome": "Win drake",
                 "confidence": "high", "source_tag": "archetype_sim"},
                {"key": "B", "label": "Concede", "expected_outcome": "Trade for top tower",
                 "confidence": "mid", "source_tag": "winrate_hist"},
            ],
        }
        out = cc.parse_choices(coach)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].key, "A")
        self.assertEqual(out[0].label, "Contest")
        self.assertEqual(out[0].confidence, "high")
        self.assertEqual(out[1].key, "B")
        self.assertEqual(out[1].confidence, "mid")

    def test_three_choice_supported(self):
        coach = {"choices": [
            {"key": "A", "label": "Engage"},
            {"key": "B", "label": "Disengage"},
            {"key": "C", "label": "Stall"},
        ]}
        self.assertEqual(len(cc.parse_choices(coach)), 3)

    def test_truncates_to_three(self):
        coach = {"choices": [{"key": k, "label": k * 3} for k in "ABCDE"]}
        out = cc.parse_choices(coach)
        self.assertEqual(len(out), 3)
        self.assertEqual([c.key for c in out], ["A", "B", "C"])


class ParserSafetyContract(unittest.TestCase):
    def test_none_coach_returns_empty(self):
        self.assertEqual(cc.parse_choices(None), [])

    def test_non_dict_coach_returns_empty(self):
        self.assertEqual(cc.parse_choices("not a dict"), [])

    def test_choices_field_absent_returns_empty(self):
        self.assertEqual(cc.parse_choices({"action": "anything"}), [])

    def test_choices_not_a_list_returns_empty(self):
        self.assertEqual(cc.parse_choices({"choices": "string not list"}), [])
        self.assertEqual(cc.parse_choices({"choices": {"a": 1}}), [])

    def test_entry_not_a_dict_skipped(self):
        coach = {"choices": ["not a dict", {"label": "Ok"}, 42]}
        out = cc.parse_choices(coach)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].label, "Ok")

    def test_entry_missing_label_skipped(self):
        coach = {"choices": [{"key": "A"}, {"key": "B", "label": "Has"}]}
        out = cc.parse_choices(coach)
        # First entry skipped (no label); second retains its key "B".
        self.assertEqual([c.key for c in out], ["B"])

    def test_bad_band_falls_back_to_mid(self):
        coach = {"choices": [{"key": "A", "label": "x", "confidence": "ultra"}]}
        self.assertEqual(cc.parse_choices(coach)[0].confidence, "mid")

    def test_missing_key_assigned_by_position(self):
        coach = {"choices": [
            {"label": "first"},
            {"label": "second"},
            {"label": "third"},
        ]}
        out = cc.parse_choices(coach)
        self.assertEqual([c.key for c in out], ["A", "B", "C"])

    def test_overlong_label_truncated(self):
        coach = {"choices": [{"key": "A", "label": "x" * 500}]}
        out = cc.parse_choices(coach)
        self.assertLess(len(out[0].label), 90)
        self.assertTrue(out[0].label.endswith("..."))


class SynthesizerTests(unittest.TestCase):
    def test_contest_pattern(self):
        out = cc.synthesize_simple_choices({"action": "Contest the dragon now"})
        self.assertEqual([c.key for c in out], ["A", "B"])
        self.assertEqual(out[0].label, "Contest")
        self.assertEqual(out[1].label, "Concede")
        self.assertEqual(out[0].source_tag, "synth")
        self.assertEqual(out[1].source_tag, "synth")

    def test_engage_pattern(self):
        out = cc.synthesize_simple_choices({"action": "Engage the back line"})
        self.assertEqual([c.label for c in out], ["Engage", "Disengage"])

    def test_no_binary_verb_returns_empty(self):
        out = cc.synthesize_simple_choices({"action": "Farm safely under tower"})
        self.assertEqual(out, [])

    def test_none_returns_empty(self):
        self.assertEqual(cc.synthesize_simple_choices(None), [])

    def test_missing_action_returns_empty(self):
        self.assertEqual(cc.synthesize_simple_choices({"immediate": "x"}), [])

    def test_uses_immediate_as_outcome_when_present(self):
        out = cc.synthesize_simple_choices({
            "action": "Contest baron",
            "immediate": "5v5 mid",
            "fight_rule": "Stall til 6 items",
        })
        self.assertEqual(out[0].expected_outcome, "5v5 mid")
        self.assertEqual(out[1].expected_outcome, "Stall til 6 items")


class TriggerFieldTests(unittest.TestCase):
    """RC2 5.3 - the optional server-derived ``trigger`` condition field."""

    def test_trigger_defaults_empty(self):
        c = cc.CoachChoice(key="A", label="X")
        self.assertEqual(c.trigger, "")

    def test_parse_choices_reads_trigger(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "Trade", "trigger": "Zed, lvl 6"},
        ]})
        self.assertEqual(out[0].trigger, "Zed, lvl 6")

    def test_parse_choices_trigger_absent_defaults_empty(self):
        out = cc.parse_choices({"choices": [{"key": "A", "label": "Trade"}]})
        self.assertEqual(out[0].trigger, "")

    def test_parse_choices_trigger_length_capped(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "trigger": "z" * 500},
        ]})
        self.assertTrue(out[0].trigger.endswith("..."))
        self.assertLessEqual(len(out[0].trigger), cc._MAX_TRIGGER_LEN + 3)

    def test_parse_choices_trigger_coerced_to_str(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "trigger": 123},
        ]})
        self.assertEqual(out[0].trigger, "123")


class RebranchFieldTests(unittest.TestCase):
    """RC2 5.4 - the optional server-derived condition-change branch fields."""

    def test_rebranch_defaults_empty(self):
        c = cc.CoachChoice(key="A", label="X")
        self.assertEqual(c.rebranch_when, "")
        self.assertEqual(c.rebranch_to, "")

    def test_parse_choices_reads_rebranch(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "Trade", "rebranch_when": "if Zed roams",
             "rebranch_to": "B"},
        ]})
        self.assertEqual(out[0].rebranch_when, "if Zed roams")
        self.assertEqual(out[0].rebranch_to, "B")

    def test_parse_choices_rebranch_absent_defaults_empty(self):
        out = cc.parse_choices({"choices": [{"key": "A", "label": "Trade"}]})
        self.assertEqual(out[0].rebranch_when, "")
        self.assertEqual(out[0].rebranch_to, "")

    def test_parse_choices_rebranch_when_length_capped(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "rebranch_when": "z" * 500},
        ]})
        self.assertTrue(out[0].rebranch_when.endswith("..."))
        self.assertLessEqual(len(out[0].rebranch_when), cc._MAX_REBRANCH_LEN + 3)

    def test_parse_choices_rebranch_to_first_upper_letter(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "rebranch_to": "bcd"},
        ]})
        self.assertEqual(out[0].rebranch_to, "B")

    def test_parse_choices_rebranch_to_empty_stays_empty(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "rebranch_to": ""},
        ]})
        self.assertEqual(out[0].rebranch_to, "")

    def test_parse_choices_rebranch_when_coerced_to_str(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "x", "rebranch_when": 123},
        ]})
        self.assertEqual(out[0].rebranch_when, "123")


class SerializationTests(unittest.TestCase):
    def test_to_jsonable_round_trip(self):
        cs = [cc.CoachChoice(key="A", label="X")]
        out = cc.to_jsonable(cs)
        self.assertEqual(out, [{
            "key": "A", "label": "X", "expected_outcome": "",
            "confidence": "mid", "source_tag": "", "trigger": "",
            "rebranch_when": "", "rebranch_to": "",
        }])

    def test_frozen_dataclass(self):
        c = cc.CoachChoice(key="A", label="X")
        with self.assertRaises(AttributeError):
            c.label = "mutated"


class AsciiHygiene(unittest.TestCase):
    """Guard against em/en-dash drift in the module body."""

    def test_no_em_dash_in_module_source(self):
        from pathlib import Path
        src = Path(cc.__file__).read_text(encoding="utf-8")
        BAD = {
            chr(0x2013): "en-dash",
            chr(0x2014): "em-dash",
            chr(0x2018): "left smart quote",
            chr(0x2019): "right smart quote",
            chr(0x201C): "left smart dq",
            chr(0x201D): "right smart dq",
        }
        for ch, name in BAD.items():
            self.assertNotIn(ch, src, f"{name} found in coach_choices.py")


if __name__ == "__main__":
    unittest.main()
