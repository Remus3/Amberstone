"""tests/test_base_coach_structured_field_limit.py

Root-cause pin for the always-empty live `choices` column across every coach.

coaches/_base_coach.py::parse_fields is shared by the ARAM / Arena / Brawl
coaches. It clipped EVERY extracted value at 220 characters, including the two
values that are not prose at all but a serialized payload handed to a decoder:

  * `choices`      - a single-line JSON array, decoded by CoachOutput
  * `item reasons` - a "Name=reason; Name=reason" pair list

A mid-value clip does not merely shorten those; it destroys them. A clipped
JSON array decodes to [] (total loss) and a clipped pair list silently drops
its tail entries.

Measured 2026-08-02 on the shipped logs, before the fix:
  data/aram_coach_shadow.jsonl  - 4066 rows carry the live `choices` key,
                                  0 are non-empty (deterministic side: 3697)
  data/arena_coach_shadow.jsonl - 614 rows carry it, 0 non-empty
  item_build_reasons, same file - 3800 non-empty rows, and the reconstructed
                                  source line maxes out at EXACTLY 220 chars
                                  with 1167 rows at >= 215, which is the
                                  fingerprint of a hard ceiling rather than a
                                  natural length distribution.

The bound itself is deliberate and is NOT removed here: an unbounded model
response must never land verbatim in a served dashboard field. These tests pin
both halves - structured values survive whole, and they are still bounded.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coaches._base_coach import parse_fields  # noqa: E402
from core.coach_output import CoachOutput  # noqa: E402

# A realistic two-entry array in the schema the ARAM prompt declares.
_CHOICES_JSON = (
    '[{"key":"A","label":"Poke with Q now",'
    '"expected_outcome":"You chip Malzahar below half without taking return '
    'damage","confidence":"mid","source_tag":"fight-trade"},'
    '{"key":"B","label":"Hold for the pack",'
    '"expected_outcome":"You reset HP and re-enter the trade window even",'
    '"confidence":"high","source_tag":"pack-grab"}]'
)

# Six pairs, the modal row count in the shipped shadow log, over 220 chars.
_ITEM_REASONS = (
    "The Collector=lethality spike into squishy backline; "
    "Phantom Dancer=attack speed plus the ghosting to walk through the pack; "
    "Kraken Slayer=true damage on-hit versus the Sett and Singed frontline; "
    "Lord Dominik's=percent penetration once Sett buys Warmog; "
    "Berserker's Greaves=early attack speed for Rend spam; "
    "Bloodthirster=shield to survive the Malzahar suppress"
)


class StructuredFieldSurvivesTests(unittest.TestCase):
    """The payload keys must arrive whole enough to decode."""

    def test_choices_array_is_not_clipped(self):
        self.assertGreater(len(_CHOICES_JSON), 220)
        out = parse_fields("Choices: " + _CHOICES_JSON, ["choices"])
        self.assertEqual(out["choices"], _CHOICES_JSON)

    def test_choices_array_decodes_to_both_entries(self):
        out = parse_fields("Choices: " + _CHOICES_JSON, ["choices"])
        decoded = CoachOutput.from_fields(out).choices
        self.assertEqual([c["key"] for c in decoded], ["A", "B"])
        self.assertEqual(decoded[1]["source_tag"], "pack-grab")

    def test_item_reasons_pair_list_is_not_clipped(self):
        self.assertGreater(len(_ITEM_REASONS), 220)
        out = parse_fields("Item reasons: " + _ITEM_REASONS, ["item reasons"])
        self.assertEqual(out["item reasons"], _ITEM_REASONS)

    def test_item_reasons_keeps_every_pair(self):
        out = parse_fields("Item reasons: " + _ITEM_REASONS, ["item reasons"])
        self.assertEqual(out["item reasons"].count("="), 6)

    def test_positional_fallback_also_spares_a_structured_value(self):
        # No "Label:" prefixes, so parse_fields maps lines to keys in order.
        raw = "POKE PHASE\n" + _CHOICES_JSON
        out = parse_fields(raw, ["action", "choices"])
        self.assertEqual(out["choices"], _CHOICES_JSON)
        self.assertEqual(
            [c["key"] for c in CoachOutput.from_fields(out).choices], ["A", "B"]
        )


class ProseFieldStaysBoundedTests(unittest.TestCase):
    """The 220 cap is what keeps a runaway response out of a served panel."""

    def test_prose_field_still_capped_at_220(self):
        out = parse_fields("Action: " + "x" * 400, ["action"])
        self.assertEqual(len(out["action"]), 220)

    def test_every_non_structured_key_still_capped(self):
        keys = ["action", "immediate", "fight rule", "reset / item",
                "risk", "item build", "item extra"]
        raw = "\n".join(f"{k}: {'y' * 400}" for k in keys)
        out = parse_fields(raw, keys)
        for k in keys:
            self.assertEqual(len(out[k]), 220, k)

    def test_prose_positional_fallback_still_capped(self):
        out = parse_fields("z" * 400 + "\n" + "w" * 400, ["action", "risk"])
        self.assertEqual(len(out["action"]), 220)
        self.assertEqual(len(out["risk"]), 220)


class StructuredFieldIsStillBoundedTests(unittest.TestCase):
    """Widening is not removing. A repetition loop must still be truncated."""

    def test_runaway_choices_value_is_bounded(self):
        out = parse_fields("Choices: " + "q" * 100_000, ["choices"])
        self.assertLess(len(out["choices"]), 100_000)

    def test_runaway_item_reasons_value_is_bounded(self):
        out = parse_fields("Item reasons: " + "q" * 100_000, ["item reasons"])
        self.assertLess(len(out["item reasons"]), 100_000)

    def test_runaway_structured_positional_fallback_is_bounded(self):
        out = parse_fields("HOLD\n" + "q" * 100_000, ["action", "choices"])
        self.assertLess(len(out["choices"]), 100_000)

    def test_bound_is_wide_enough_for_a_three_entry_array(self):
        # The prompt asks for 2-3 choices; three entries must not be clipped.
        three = json.dumps([
            {"key": k, "label": "Hold the wave near tower",
             "expected_outcome": "You reset HP and re-enter the trade window "
                                 "even against the poke comp",
             "confidence": "mid", "source_tag": "pack-grab"}
            for k in ("A", "B", "C")
        ], separators=(",", ":"))
        out = parse_fields("Choices: " + three, ["choices"])
        self.assertEqual(out["choices"], three)
        self.assertEqual(len(CoachOutput.from_fields(out).choices), 3)


class PerModeReachTests(unittest.TestCase):
    """The fix lands in every coach that calls parse_fields, via each one's
    OWN key list - not via a key list this test invented."""

    def _assert_array_survives(self, keys):
        self.assertIn("choices", keys)
        out = parse_fields("Choices: " + _CHOICES_JSON, list(keys))
        self.assertEqual(out["choices"], _CHOICES_JSON)
        self.assertEqual(
            [c["key"] for c in CoachOutput.from_fields(out).choices], ["A", "B"]
        )

    def test_aram_key_list(self):
        # coaches/aram_coach.py builds this list inline at the call site.
        self._assert_array_survives([
            "action", "immediate", "fight rule", "reset / item", "risk",
            "item build", "item extra", "item reasons", "choices",
        ])

    def test_arena_key_list(self):
        from coaches.arena_coach import _OUTPUT_KEYS

        self._assert_array_survives(_OUTPUT_KEYS)

    def test_brawl_key_lists(self):
        from coaches.brawl_coach import (
            _NB_OUTPUT_KEYS,
            _OFA_OUTPUT_KEYS,
            _URF_OUTPUT_KEYS,
        )

        for keys in (_NB_OUTPUT_KEYS, _URF_OUTPUT_KEYS, _OFA_OUTPUT_KEYS):
            with self.subTest(keys=keys[-2]):
                self._assert_array_survives(keys)

    def test_aram_item_reasons_key_survives_through_the_real_list(self):
        out = parse_fields("Item reasons: " + _ITEM_REASONS, [
            "action", "immediate", "fight rule", "reset / item", "risk",
            "item build", "item extra", "item reasons", "choices",
        ])
        self.assertEqual(out["item reasons"], _ITEM_REASONS)


if __name__ == "__main__":
    unittest.main()
