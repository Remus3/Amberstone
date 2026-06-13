"""P2 W4 cycle-14 slice E - champion-loadout family regression tests.

Auditor-authored guard for the champion_loadout_* live validators /
generators. Each test pins a correctness / data-integrity contract found
during the deep audit so a future edit cannot silently regress it.

Test classes:

* ``EnforceLengthUniqueFamilyTests`` - the shared item-213 ``Cleaner``
  ``enforce_length`` shaper (used by ``champion_loadout_autogen`` and
  the item-s8 sweep) must never emit a build that holds two items
  sharing a unique-passive family (engine-authoritative no-double-unique
  rule). The DS flat ranker routinely returns Trinity Force + Essence
  Reaver (both ``spellblade``) in its top picks, so an autogen run that
  fed those straight through enforce_length wrote a clash into the
  curated JSON and broke tests/test_champion_loadouts_no_unique_clash.py.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.champion_loadout_cleanup_pollution_item213 import Cleaner


def _norm(s: str) -> str:
    return (s or "").lower().strip().replace(" ", "").replace(
        "'", "").replace("-", "").replace(",", "").replace(".", "")


def _families_in(cleaner: Cleaner, items: list[str]) -> list[str]:
    """Ordered list of the unique-passive families present in ``items``
    (duplicates kept) using the same registry the cleaner uses."""
    out: list[str] = []
    for it in items:
        fam = cleaner.fam.get(_norm(it))
        if fam:
            out.append(fam)
    return out


class EnforceLengthUniqueFamilyTests(unittest.TestCase):
    """enforce_length must drop a second item of any unique-passive
    family before reseating boots / backfilling / trimming."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cleaner = Cleaner()

    def _assert_no_family_clash(self, items: list[str]) -> None:
        fams = _families_in(self.cleaner, items)
        dupes = sorted({f for f in fams if fams.count(f) > 1})
        self.assertEqual(
            dupes, [],
            f"enforce_length emitted a unique-family clash {dupes} in "
            f"{items}",
        )

    def test_drops_preexisting_spellblade_clash_sr_carry(self) -> None:
        # Trinity Force + Essence Reaver both carry unique_passive_key
        # 'spellblade'. The shaper must keep only the first.
        out = self.cleaner.enforce_length(
            "Ezreal", "sr", "carry",
            ["Trinity Force", "Essence Reaver"], frozenset(),
        )
        self.assertIn("Trinity Force", out)  # first of the pair survives
        self.assertNotIn("Essence Reaver", out)
        self._assert_no_family_clash(out)
        # Length contract preserved (SR == 7) and boots reseated to idx 1.
        self.assertEqual(len(out), 7)

    def test_drops_clash_arena_bruiser(self) -> None:
        # Arena bruiser ranker returns Trinity Force + Divine Sunderer +
        # Essence Reaver, all 'spellblade'. Only one may survive.
        out = self.cleaner.enforce_length(
            "Jax", "arena", "bruiser",
            ["Trinity Force", "Divine Sunderer", "Essence Reaver",
             "Black Cleaver"],
            frozenset(),
        )
        self._assert_no_family_clash(out)
        self.assertEqual(len(out), 6)  # Arena == 6, no boots

    def test_clean_input_is_preserved(self) -> None:
        # A clash-free, on-mode, correct-length carry row must come back
        # with the same membership (boots reseated to index 1).
        items = [
            "Infinity Edge", "Berserker's Greaves", "Lord Dominik's Regards",
            "Runaan's Hurricane", "Bloodthirster", "Phantom Dancer",
            "The Collector",
        ]
        out = self.cleaner.enforce_length(
            "Jinx", "sr", "carry", list(items), frozenset(),
        )
        self.assertEqual(len(out), 7)
        self.assertEqual(set(out), set(items))
        self._assert_no_family_clash(out)
        self.assertEqual(_norm(out[1]), _norm("Berserker's Greaves"))


if __name__ == "__main__":
    unittest.main()
