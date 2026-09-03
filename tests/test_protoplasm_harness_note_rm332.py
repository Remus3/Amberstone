"""RM-332 - the Protoplasm Harness notes must describe what the item grants.

Both `ITEM_EFFECTS` rows for Protoplasm Harness (SR 2525 and its Arena mirror
222525) used to call the Lifeline passive a "shield". The pinned authority
`data/daemon_slayer/16.15.1/items.json` says otherwise: the item grants MAXIMUM
HEALTH for 5 seconds and then HEALS over that duration. Immortal Shieldbow 6673
in the same file is the contrast case - its Lifeline really does grant a Shield,
and its description carries the `<shield>` tag that 2525 lacks.

**The defect this row was originally filed as is REFUTED and must not be
re-filed.** `unique_passive_key` is a DEDUP family, not a shield family, so
`shield=None` on 2525 / 222525 is CORRECT, and the family roster is CORRECT.
These tests therefore pin `shield=None` as intended behaviour rather than
treating it as a gap, and pin `LIFELINE_ITEM_IDS` as a deliberate target-side
subset that must NOT be widened into a derived family census.

Tier-0: note text only. No engine behaviour is asserted or changed here.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._lifeline_target_shield import LIFELINE_ITEM_IDS

_REPO = Path(__file__).resolve().parents[1]
_ITEMS = _REPO / "data" / "daemon_slayer" / "16.15.1" / "items.json"

# Protoplasm Harness: the SR row and its Arena mirror.
_HARNESS_IDS = ("2525", "222525")
# The contrast case whose Lifeline genuinely does grant a shield.
_SHIELDBOW_ID = "6673"

# Exact phrasings removed by RM-332. Anchoring on the literals keeps the guard
# from passing vacuously if the notes are later reworded back toward "shield".
_REFUTED_PHRASES = (
    "triggered shield",
    "Lifeline shield",
    "Shield/sustain",
    "then heals max HP over 5s",
)


def _descriptions() -> dict[str, str]:
    with _ITEMS.open(encoding="utf-8") as fh:
        blob = json.load(fh)
    data = blob.get("data", blob)
    return {i: row.get("description", "") for i, row in data.items()}


class HarnessNoteMatchesAuthorityTests(unittest.TestCase):
    """The note text agrees with the pinned DDragon description."""

    @classmethod
    def setUpClass(cls):
        cls.desc = _descriptions()

    def test_authority_says_max_health_and_heal_not_shield(self):
        """Ground truth first: 2525 grants max Health + a heal, and carries no
        `<shield>` tag, while Shieldbow 6673 does carry one."""
        for iid in _HARNESS_IDS:
            with self.subTest(item=iid):
                d = self.desc[iid]
                self.assertIn("maximum Health", d)
                self.assertIn("heal", d)
                self.assertNotIn("<shield>", d)
        self.assertIn("<shield>", self.desc[_SHIELDBOW_ID])

    def test_notes_do_not_claim_a_triggered_shield(self):
        """None of the refuted phrasings survive in either note."""
        for iid in _HARNESS_IDS:
            note = ITEM_EFFECTS[iid].note or ""
            for phrase in _REFUTED_PHRASES:
                with self.subTest(item=iid, phrase=phrase):
                    self.assertNotIn(
                        phrase.lower(), note.lower(),
                        f"{iid} note still describes a shield grant: {note!r}",
                    )

    def test_notes_describe_the_max_health_grant_and_the_heal(self):
        """The replacement wording states the mechanic the item actually has."""
        for iid in _HARNESS_IDS:
            note = (ITEM_EFFECTS[iid].note or "").lower()
            with self.subTest(item=iid):
                self.assertTrue(
                    re.search(r"max[- ]health", note),
                    f"{iid} note does not mention a max-Health grant: {note!r}",
                )
                self.assertIn("heal", note)


class RefutedDefectFenceTests(unittest.TestCase):
    """`shield=None` on the Harness rows is CORRECT - do not "fix" it."""

    def test_harness_rows_carry_no_item_shield(self):
        for iid in _HARNESS_IDS:
            with self.subTest(item=iid):
                self.assertIsNone(
                    ITEM_EFFECTS[iid].shield,
                    f"{iid} must stay shield-less; it grants max Health, not a shield",
                )

    def test_shieldbow_does_carry_an_item_shield(self):
        """The contrast case proves the assertion above is not vacuous."""
        self.assertIsNotNone(ITEM_EFFECTS[_SHIELDBOW_ID].shield)

    def test_harness_stays_in_the_lifeline_dedup_family(self):
        """Membership is a DEDUP key, never a claim that the item shields."""
        for iid in _HARNESS_IDS:
            with self.subTest(item=iid):
                self.assertEqual(ITEM_EFFECTS[iid].unique_passive_key, "lifeline")


class LifelineTargetSubsetCommentTests(unittest.TestCase):
    """Pins the facts the corrected `_lifeline_target_shield.py` comment states."""

    @staticmethod
    def _family() -> list[str]:
        return [i for i, e in ITEM_EFFECTS.items() if e.unique_passive_key == "lifeline"]

    def test_modeled_subset_is_three_and_smaller_than_the_family(self):
        """The tuple is a target-side subset, not a census of the family."""
        family = self._family()
        self.assertEqual(len(LIFELINE_ITEM_IDS), 3)
        self.assertLess(
            len(LIFELINE_ITEM_IDS), len(family),
            "the comment calls this a subset; it must not equal the family",
        )

    def test_every_modeled_id_carries_a_shield(self):
        """The corrected comment claims all three do carry an ItemShield."""
        for iid in LIFELINE_ITEM_IDS:
            with self.subTest(item=iid):
                self.assertIsNotNone(ITEM_EFFECTS[iid].shield)

    def test_family_contains_shield_less_members(self):
        """Why the tuple must not be derived: widening it would pull in rows
        that carry no shield and invent EHP that does not exist."""
        shield_less = [
            i for i in self._family() if ITEM_EFFECTS[i].shield is None
        ]
        self.assertTrue(shield_less, "expected shield-less lifeline members")
        for iid in _HARNESS_IDS:
            self.assertIn(iid, shield_less)


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        text = Path(__file__).read_text(encoding="utf-8")
        bad = [(i, c) for i, c in enumerate(text) if ord(c) > 126]
        self.assertEqual(bad, [], f"non-ASCII in {Path(__file__).name}: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
