"""Lane-8 (true-audit) regressions for ``core.coach_choices``.

The coach JSON ``choices`` array is model output (untrusted at this boundary),
and ``synthesize_simple_choices`` reads free coach prose. Each test names the
weakness it pins; every one was red against the pre-audit module.

- F1 a truncated field overshot its cap by 3 ("..." appended AFTER the cap), so
  the chip renderer's own slice (web/js/panels/coach_choices.js: label 80,
  outcome 160, trigger / rebranch_when 120) cut the ellipsis off.
- F2 a non-scalar or bool field became its Python repr ("{'text': 'x'}",
  "True", "nan") on a chip; a >4300-digit int raised ValueError out of parse.
- F3 an embedded newline / tab / control character / lone surrogate reached
  the chip text and the shadow logs verbatim.
- F4 keys were not restricted to the A / B / C the Alt+1..3 hotkeys address,
  and two entries could share one key (the panel's key->chip map collides).
- F5 rebranch_to took any first character ("1", "?") and could name the chip's
  own key.
- F6 malformed entries counted against the 3-choice cap, so a valid fourth
  entry was dropped, and a lone valid chip took its raw index as its key.
- F7 the synthesizer matched trigger SUBSTRINGS and ignored negation:
  "Disengage" read Engage, "Move toward dragon" read Ward, "Don't push"
  read Push.
"""
from __future__ import annotations

import json
import unittest

from core import coach_choices as cc


def _one(entry: dict):
    out = cc.parse_choices({"choices": [entry]})
    return out[0] if out else None


class TruncationCapTests(unittest.TestCase):
    """F1 - a truncated field ends in "..." and never exceeds its cap."""

    def test_each_field_stays_within_its_cap_with_marker(self):
        c = _one({
            "key": "A", "label": "x" * 500, "expected_outcome": "y" * 500,
            "trigger": "z" * 500, "rebranch_when": "w" * 500,
            "source_tag": "s" * 500,
        })
        for value, cap in (
            (c.label, cc._MAX_LABEL_LEN),
            (c.expected_outcome, cc._MAX_OUTCOME_LEN),
            (c.trigger, cc._MAX_TRIGGER_LEN),
            (c.rebranch_when, cc._MAX_REBRANCH_LEN),
            (c.source_tag, 32),
        ):
            self.assertTrue(value.endswith("..."), value)
            self.assertLessEqual(len(value), cap)

    def test_marker_survives_the_chip_renderer_slice(self):
        # web/js/panels/coach_choices.js slices label to 80 chars.
        c = _one({"key": "A", "label": "word " * 40})
        self.assertTrue(c.label[:80].endswith("..."))

    def test_exactly_cap_is_not_truncated(self):
        c = _one({"key": "A", "label": "x" * cc._MAX_LABEL_LEN})
        self.assertEqual(c.label, "x" * cc._MAX_LABEL_LEN)


class NonTextValueTests(unittest.TestCase):
    """F2 - only text and finite numbers are readings."""

    def test_container_label_is_no_reading(self):
        self.assertIsNone(_one({"key": "A", "label": {"text": "Contest"}}))
        self.assertIsNone(_one({"key": "A", "label": ["Contest"]}))

    def test_bool_label_is_no_reading(self):
        self.assertIsNone(_one({"key": "A", "label": True}))

    def test_container_outcome_is_empty(self):
        c = _one({"key": "A", "label": "Go", "expected_outcome": {"a": 1},
                  "trigger": [1, 2], "rebranch_when": False})
        self.assertEqual(c.expected_outcome, "")
        self.assertEqual(c.trigger, "")
        self.assertEqual(c.rebranch_when, "")

    def test_non_finite_number_is_empty(self):
        c = _one({"key": "A", "label": "Go", "trigger": float("nan"),
                  "expected_outcome": float("inf")})
        self.assertEqual(c.trigger, "")
        self.assertEqual(c.expected_outcome, "")

    def test_huge_int_never_raises(self):
        c = _one({"key": "A", "label": "Go", "trigger": 10 ** 5000})
        self.assertEqual(c.trigger, "")

    def test_finite_numbers_still_read(self):
        c = _one({"key": "A", "label": 7, "trigger": 123, "rebranch_when": 1.5})
        self.assertEqual(c.label, "7")
        self.assertEqual(c.trigger, "123")
        self.assertEqual(c.rebranch_when, "1.5")

    def test_container_confidence_is_mid(self):
        self.assertEqual(_one({"key": "A", "label": "Go",
                               "confidence": ["high"]}).confidence, "mid")


class ControlCharacterTests(unittest.TestCase):
    """F3 - whitespace runs collapse; controls and lone surrogates drop."""

    def test_newline_and_tab_collapse(self):
        c = _one({"key": "A", "label": "Contest\n\n the\tdragon"})
        self.assertEqual(c.label, "Contest the dragon")

    def test_control_chars_dropped(self):
        c = _one({"key": "A", "label": "Con\x1b[31mtest\x00\x7f\x85"})
        self.assertEqual(c.label, "Con[31mtest")

    def test_lone_surrogate_dropped_and_utf8_encodable(self):
        c = _one({"key": "A", "label": "Go\ud800 now"})
        self.assertEqual(c.label, "Go now")
        c.label.encode("utf-8")  # strict: raises on a surrogate

    def test_only_controls_is_no_reading(self):
        self.assertIsNone(_one({"key": "A", "label": "\x00\x01\n\t"}))

    def test_synth_outcome_scrubbed(self):
        out = cc.synthesize_simple_choices({
            "action": "Contest baron", "immediate": "5v5\nmid\x00"})
        self.assertEqual(out[0].expected_outcome, "5v5 mid")


class KeyTests(unittest.TestCase):
    """F4 - keys are A / B / C and unique."""

    def test_duplicate_keys_are_deduplicated(self):
        out = cc.parse_choices({"choices": [
            {"key": "A", "label": "one"}, {"key": "A", "label": "two"},
        ]})
        self.assertEqual([c.key for c in out], ["A", "B"])

    def test_key_outside_abc_takes_first_free_letter(self):
        out = cc.parse_choices({"choices": [
            {"key": "1", "label": "one"}, {"key": "Z", "label": "two"},
            {"key": "?", "label": "three"},
        ]})
        self.assertEqual([c.key for c in out], ["A", "B", "C"])

    def test_non_ascii_key_does_not_expand(self):
        # "ss".upper() is "SS"; any non-A/B/C first letter is no key.
        out = cc.parse_choices({"choices": [{"key": chr(0xDF), "label": "x"}]})
        self.assertEqual(out[0].key, "A")

    def test_given_keys_out_of_order_kept(self):
        out = cc.parse_choices({"choices": [
            {"key": "b", "label": "one"}, {"label": "two"},
        ]})
        self.assertEqual([c.key for c in out], ["B", "A"])

    def test_wire_keys_are_unique_and_hotkey_addressable(self):
        out = cc.parse_choices({"choices": [
            {"key": k, "label": "x"} for k in ("C", "C", "c")
        ]})
        keys = [c.key for c in out]
        self.assertEqual(sorted(keys), ["A", "B", "C"])


class RebranchToTests(unittest.TestCase):
    """F5 - rebranch_to is A / B / C, never the chip's own key."""

    def test_non_letter_rebranch_to_is_empty(self):
        for raw in ("1", "?", "-B", "Z", chr(0xDF)):
            c = _one({"key": "A", "label": "x", "rebranch_to": raw})
            self.assertEqual(c.rebranch_to, "", raw)

    def test_self_reference_is_empty(self):
        c = _one({"key": "B", "label": "x", "rebranch_to": "b"})
        self.assertEqual(c.rebranch_to, "")

    def test_valid_rebranch_kept(self):
        c = _one({"key": "A", "label": "x", "rebranch_to": " c "})
        self.assertEqual(c.rebranch_to, "C")


class MalformedEntryCapTests(unittest.TestCase):
    """F6 - the cap counts valid choices; a lone chip is A."""

    def test_malformed_entries_do_not_consume_the_cap(self):
        out = cc.parse_choices({"choices": [
            "junk", {"key": "A"}, 42,
            {"label": "first"}, {"label": "second"},
            {"label": "third"}, {"label": "fourth"},
        ]})
        self.assertEqual([c.label for c in out], ["first", "second", "third"])
        self.assertEqual([c.key for c in out], ["A", "B", "C"])

    def test_lone_valid_chip_after_junk_is_a(self):
        out = cc.parse_choices({"choices": ["not a dict", {"label": "Ok"}]})
        self.assertEqual([c.key for c in out], ["A"])

    def test_scan_is_bounded(self):
        junk = ["x"] * (cc._MAX_SCAN + 5) + [{"label": "late"}]
        self.assertEqual(cc.parse_choices({"choices": junk}), [])


class SynthesizerWordTests(unittest.TestCase):
    """F7 - triggers match at a word start and a negated trigger is skipped."""

    def _labels(self, action: str):
        return [c.label for c in cc.synthesize_simple_choices({"action": action})]

    def test_disengage_is_not_engage(self):
        self.assertEqual(self._labels("Disengage now"), [])

    def test_toward_is_not_ward(self):
        self.assertEqual(self._labels("Move toward dragon pit"), [])
        self.assertEqual(self._labels("Step forward"), [])

    def test_negated_trigger_skipped(self):
        self.assertEqual(self._labels("Don't push, freeze the wave"),
                         ["Freeze", "Push"])
        self.assertEqual(self._labels("Do not engage"), [])
        self.assertEqual(self._labels("Avoid contesting"), [])
        self.assertEqual(self._labels("Never all-in Darius"), [])
        self.assertEqual(self._labels("Don" + chr(0x2019) + "t siege"), [])

    def test_inflected_trigger_still_matches(self):
        self.assertEqual(self._labels("Pushing bot is fine"), ["Push", "Freeze"])
        self.assertEqual(self._labels("Warding river now"),
                         ["Ward", "Skip vision"])

    def test_negation_word_inside_other_word_does_not_negate(self):
        # "piano" ends in "no" only as a substring, not a word.
        self.assertEqual(self._labels("Casino push"), ["Push", "Freeze"])

    def test_synth_wire_is_strict_json(self):
        out = cc.synthesize_simple_choices({
            "action": "Contest baron", "immediate": float("nan")})
        json.dumps(cc.to_jsonable(out), allow_nan=False)
        self.assertEqual(out[0].expected_outcome, "follow the coach call")


if __name__ == "__main__":
    unittest.main()
