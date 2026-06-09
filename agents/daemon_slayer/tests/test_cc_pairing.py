"""Tests for agents/daemon_slayer/cc_pairing.py - ally CC-pairing join (CS1).

The module is a pure read-only JOIN over the existing cc_conditional
registry: for the operator's OWN roster it surfaces conditional CC
entries whose condition an ALLY can set up, with the plausible enabler
teammates resolved from the same roster. NO ENGINE math change, NO
schema lift.

Covers:
  * AllyEnablableTests - only ally-enablable conditions surface; self-set
    conditions (nth_hit / channel / devour / ...) are excluded.
  * EnablerResolutionTests - teammate enabler list reuses the CC / displace
    registries; owner is never its own enabler; no-engage team -> empty.
  * OrderingTests - cards sorted by duration DESC then champ then slot.
  * ContractTests - empty / blank / unknown rosters fail soft to empty.
  * AsciiHygieneTests - no em-dashes / smart quotes in module + test file.
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer.cc_pairing import (
    CcPairingCard,
    CcPairingResult,
    compute_cc_pairing,
)


def _cards_for(roster):
    return compute_cc_pairing(roster).cards


def _card(roster, champion, spell):
    for c in _cards_for(roster):
        if c.champion == champion and c.spell == spell:
            return c
    return None


class AllyEnablableTests(unittest.TestCase):
    def test_sett_e_dual_enemy_surfaces(self) -> None:
        # Sett E Facebreaker is a dual_enemy stun - an ally engage groups
        # the enemies for it. It MUST surface as a pairing card.
        c = _card(["Sett"], "Sett", "E")
        self.assertIsNotNone(c)
        self.assertEqual(c.cc_kind, "stun")
        self.assertEqual(c.condition, "dual_enemy")
        self.assertEqual(c.cc_duration_s, 1.0)
        self.assertIn("grouped", c.setup_hint)

    def test_vex_e_debuffed_target_surfaces(self) -> None:
        c = _card(["Vex"], "Vex", "E")
        self.assertIsNotNone(c)
        self.assertEqual(c.condition, "debuffed_target")
        self.assertEqual(c.cc_kind, "fear")
        self.assertEqual(c.cc_duration_s, 1.5)

    def test_taliyah_e_traverse_surfaces(self) -> None:
        c = _card(["Taliyah"], "Taliyah", "E")
        self.assertIsNotNone(c)
        self.assertEqual(c.condition, "traverse")
        self.assertIn("forced across", c.setup_hint)

    def test_self_set_conditions_excluded(self) -> None:
        # TahmKench Q (nth_hit), W (channel), R (devour) are all SELF-set:
        # NONE of them is a teammate pairing. The roster yields zero cards.
        self.assertEqual(_cards_for(["TahmKench"]), ())

    def test_brand_only_debuffed_target_entry_surfaces(self) -> None:
        # Brand Q is debuffed_target (ally-enablable) but Brand R is
        # nth_hit (self-set). Only Q surfaces.
        names = {(c.champion, c.spell) for c in _cards_for(["Brand"])}
        self.assertIn(("Brand", "Q"), names)
        self.assertNotIn(("Brand", "R"), names)


class EnablerResolutionTests(unittest.TestCase):
    def test_teammate_with_hard_cc_is_enabler(self) -> None:
        # Leona carries unconditional hard CC (E root / R stun). Paired with
        # Sett (dual_enemy), Leona MUST appear as an enabler on the Sett card.
        c = _card(["Sett", "Leona"], "Sett", "E")
        self.assertIsNotNone(c)
        self.assertIn("Leona", c.enablers)

    def test_owner_is_never_its_own_enabler(self) -> None:
        c = _card(["Sett", "Leona"], "Sett", "E")
        self.assertNotIn("Sett", c.enablers)

    def test_no_engage_team_yields_empty_enablers(self) -> None:
        # A roster of just the owner has no teammate; enablers is empty but
        # the card still surfaces (the operator still sees the opportunity).
        c = _card(["Sett"], "Sett", "E")
        self.assertIsNotNone(c)
        self.assertEqual(c.enablers, ())

    def test_enablers_are_deduped_and_ordered(self) -> None:
        c = _card(["Vex", "Leona", "Leona", "Nautilus"], "Vex", "E")
        self.assertIsNotNone(c)
        # Roster order preserved, owner + dupes removed.
        self.assertEqual(c.enablers.count("Leona"), 1)
        self.assertEqual(list(c.enablers).index("Leona"),
                         0 if "Leona" in c.enablers else -1)


class OrderingTests(unittest.TestCase):
    def test_cards_sorted_by_duration_desc(self) -> None:
        # Vex E 1.5 > Sett E 1.0; Vex must come first.
        cards = _cards_for(["Sett", "Vex"])
        self.assertGreaterEqual(len(cards), 2)
        self.assertEqual(cards[0].champion, "Vex")

    def test_result_is_dataclass(self) -> None:
        r = compute_cc_pairing(["Sett"])
        self.assertIsInstance(r, CcPairingResult)
        for c in r.cards:
            self.assertIsInstance(c, CcPairingCard)


class ContractTests(unittest.TestCase):
    def test_empty_roster(self) -> None:
        self.assertEqual(compute_cc_pairing([]).cards, ())

    def test_none_roster(self) -> None:
        self.assertEqual(compute_cc_pairing(None).cards, ())

    def test_blank_entries_skipped(self) -> None:
        self.assertEqual(compute_cc_pairing(["", "  ", None]).cards, ())

    def test_unknown_champion_yields_empty(self) -> None:
        self.assertEqual(compute_cc_pairing(["NotAChamp"]).cards, ())

    def test_duplicate_owner_collapses(self) -> None:
        # Sett twice yields one card, not two.
        cards = _cards_for(["Sett", "Sett"])
        self.assertEqual(len([c for c in cards if c.champion == "Sett"
                              and c.spell == "E"]), 1)

    def test_does_not_raise_on_mixed_roster(self) -> None:
        # Mixed known / unknown / self-set / blank must never raise.
        compute_cc_pairing(["Sett", "TahmKench", "NotAChamp", "", "Vex"])


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D))

    def _scan(self, path: pathlib.Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer.cc_pairing as mod
        self.assertEqual(self._scan(pathlib.Path(mod.__file__)), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(pathlib.Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
