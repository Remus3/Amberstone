"""compute_cc_pairing keeps its "Never raises" fail-soft contract (S144-T-577).

The builder's docstring promises it never raises and fails soft to an
empty result on a bad roster. Measured at HEAD before this slice:

  * a bare string roster ("Sett") was iterated character by character,
    so a one-champion roster silently produced ZERO cards;
  * a non-iterable roster (5, 3.5, object()) raised TypeError;
  * a roster element whose ``__str__`` raises propagated the exception;
  * a str subclass could forge a registry hit through ``__eq__`` /
    ``__hash__`` and carry its own text into ``CcPairingCard.champion``;
  * an unbounded iterator (itertools.repeat) never returned;
  * a non-str element was ``str()``-ed (b"Leona" -> "b'Leona'").

The only production caller (dashboard/routes_cc_pairing.py) splits a
query string into a capped list of plain str, so the live route was never
reached by these inputs; the fix holds the contract for direct callers.
The enabler-equivalence test pins that the per-call enabler memo did not
move a single card on the full registry roster.
"""
from __future__ import annotations

import itertools
import pathlib
import unittest

from agents.daemon_slayer import cc_pairing
from agents.daemon_slayer.cc_conditional import (
    _PER_SPELL_CC_CONDITIONAL,
    _PER_SPELL_CC_CONDITIONAL_FORMS,
)
from agents.daemon_slayer.cc_pairing import CcPairingResult, compute_cc_pairing


def _keys(result):
    return [(c.champion, c.spell, c.enablers) for c in result.cards]


class _RaisingStr:
    def __str__(self):
        raise RuntimeError("boom")


class _Forge(str):
    """A str subclass that claims equality with every registry key."""

    __slots__ = ()

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __hash__(self):
        return hash("Sett")

    def __str__(self):
        return self

    def strip(self, *a):
        return self


class BareStringRosterTests(unittest.TestCase):
    def test_bare_string_is_one_champion(self) -> None:
        self.assertEqual(
            _keys(compute_cc_pairing("Sett")),
            _keys(compute_cc_pairing(["Sett"])),
        )
        self.assertTrue(compute_cc_pairing("Sett").cards)

    def test_bare_string_is_stripped(self) -> None:
        self.assertEqual(
            _keys(compute_cc_pairing("  Sett  ")),
            _keys(compute_cc_pairing(["Sett"])),
        )

    def test_bytes_roster_is_not_a_roster(self) -> None:
        self.assertEqual(compute_cc_pairing(b"Sett").cards, ())


class NonIterableRosterTests(unittest.TestCase):
    def test_non_iterable_rosters_fail_soft(self) -> None:
        for bad in (5, 3.5, object(), True, float("nan")):
            with self.subTest(bad=repr(bad)):
                res = compute_cc_pairing(bad)
                self.assertIsInstance(res, CcPairingResult)
                self.assertEqual(res.cards, ())

    def test_raising_iterator_fails_soft_to_empty(self) -> None:
        def gen():
            yield "Sett"
            yield "Leona"
            raise RuntimeError("mid-iteration")

        self.assertEqual(compute_cc_pairing(gen()).cards, ())

    def test_generator_roster_still_works(self) -> None:
        self.assertEqual(
            _keys(compute_cc_pairing(c for c in ["Sett", "Leona"])),
            _keys(compute_cc_pairing(["Sett", "Leona"])),
        )


class ElementTests(unittest.TestCase):
    def test_raising_str_element_is_skipped(self) -> None:
        self.assertEqual(
            _keys(compute_cc_pairing([_RaisingStr(), "Sett", "Leona"])),
            _keys(compute_cc_pairing(["Sett", "Leona"])),
        )

    def test_non_str_elements_are_skipped(self) -> None:
        got = compute_cc_pairing(["Sett", b"Leona", 5, 2.5, True])
        self.assertEqual(_keys(got), _keys(compute_cc_pairing(["Sett"])))

    def test_str_subclass_cannot_forge_a_match(self) -> None:
        res = compute_cc_pairing([_Forge("Evil")])
        self.assertEqual(res.cards, ())

    def test_str_subclass_cannot_forge_an_enabler(self) -> None:
        sett = [c for c in compute_cc_pairing(["Sett", _Forge("Evil")]).cards
                if c.champion == "Sett"]
        self.assertTrue(sett)
        for card in sett:
            self.assertEqual(card.enablers, ())

    def test_card_fields_are_exact_str(self) -> None:
        for card in compute_cc_pairing(["Sett", "Leona"]).cards:
            self.assertIs(type(card.champion), str)
            for e in card.enablers:
                self.assertIs(type(e), str)


class RosterBoundTests(unittest.TestCase):
    def test_unbounded_iterator_returns_empty(self) -> None:
        self.assertEqual(
            compute_cc_pairing(itertools.repeat("Sett")).cards, ()
        )

    def test_roster_at_cap_is_read(self) -> None:
        cap = cc_pairing._MAX_ROSTER_ENTRIES
        roster = ["Sett"] + ["Leona"] * (cap - 1)
        self.assertEqual(
            _keys(compute_cc_pairing(roster)),
            _keys(compute_cc_pairing(["Sett", "Leona"])),
        )

    def test_roster_over_cap_is_refused(self) -> None:
        cap = cc_pairing._MAX_ROSTER_ENTRIES
        roster = ["Sett"] + ["Leona"] * cap
        self.assertEqual(compute_cc_pairing(roster).cards, ())

    def test_cap_clears_every_real_lobby(self) -> None:
        # dashboard/_get_caps.MAX_CHAMPION_LIST is 16 (Arena lobby).
        self.assertGreaterEqual(cc_pairing._MAX_ROSTER_ENTRIES, 16)


class EnablerEquivalenceTests(unittest.TestCase):
    def test_full_registry_enablers_match_reference(self) -> None:
        roster = sorted(
            set(_PER_SPELL_CC_CONDITIONAL) | set(_PER_SPELL_CC_CONDITIONAL_FORMS)
        ) + ["Leona", "Malzahar", "Teemo", "Unknown"]
        res = compute_cc_pairing(roster)
        self.assertTrue(res.cards)
        for card in res.cards:
            want = tuple(
                t for t in dict.fromkeys(roster)
                if t != card.champion and cc_pairing._has_enabler_tool(t)
            )
            self.assertEqual(card.enablers, want, card.champion)


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        raw.decode("ascii")
        self.assertNotIn(b"\r", raw)


if __name__ == "__main__":
    unittest.main()
