"""S144-D-130..133: the team_blended ally-grant helpers keep "never raises".

OFFLINE ONLY - no DS :8860 call, no network. The helpers read the cached
champion_abilities / enchanter formula files from data/daemon_slayer.

Defects pinned (measured at lane/ds 1255df9b9 before the fix):
  * S144-D-130 ``champion_ally_reach`` documents "Never raises" but raised
    TypeError on an unhashable ``patch`` (list / dict / set - the lru_cache
    key), and ValueError / RuntimeError on a champion whose ``str()`` raises
    (an int past ``sys.get_int_max_str_digits()``, a hostile ``__str__``).
  * S144-D-131 ``ally_grant_hp`` documents "never raises" but raised the same
    ValueError / RuntimeError on an ``item_id`` whose ``str()`` raises.
  * S144-D-132 ``total_item_ally_grant_hp`` documents "fail-soft" but raised
    TypeError on a non-iterable inventory (int, float, bool, object), let an
    iterator's own exception and a per-item ``str()`` failure escape, and read
    a bare string inventory ``"3107"`` character by character (four unknown
    ids -> 0.0) while ``["3107"]`` gives the real Redemption grant.
  * S144-D-133 ``ally_flat_hp_grant`` documents "never raises" for an unknown
    champion but raised on a champion whose ``str()`` raises; its siblings
    ``ally_resist_grant`` / ``ally_revive_multiplier`` share the
    ``str(champion_id)`` line and raised the same way.

Contract (the S144-D-127 rule): a non-string champion reads as blank - no
reach, no grant - and an unusable item id reads as unknown (0.0). Finite,
well-typed string inputs are unchanged, pinned against the helpers' own
string-input results. A bad ``level`` on the champion-grant helpers still
raises by design (S144-D-126; dsp_live_consumers.ally_protected_ehp documents
it), so it is not exercised here.
"""

from __future__ import annotations

import math
import sys
import unittest

from agents.daemon_slayer._champion_ally_reach import champion_ally_reach
from agents.daemon_slayer._item_ally_grant import (
    ally_grant_hp,
    total_item_ally_grant_hp,
)
from agents.daemon_slayer._passive_ally_grant_overrides import (
    ally_flat_hp_grant,
    ally_resist_grant,
    ally_revive_multiplier,
)

_HUGE_INT = 10 ** (sys.get_int_max_str_digits() + 10)


class _HostileStr:
    def __str__(self) -> str:  # pragma: no cover - raised, never returned
        raise RuntimeError("hostile __str__")


def _raising_iter():
    yield "3107"
    raise RuntimeError("iterator failed mid-way")


_UNSTRINGABLE = (_HUGE_INT, _HostileStr())
_NON_STR_CHAMPIONS = (_HUGE_INT, _HostileStr(), 0, 7, 3.5, b"Janna",
                      ["Janna"], {"a": 1}, {1}, object())


class ChampionAllyReachNeverRaises(unittest.TestCase):
    """S144-D-130."""

    def test_string_inputs_unchanged(self) -> None:
        self.assertTrue(champion_ally_reach("Janna"))
        self.assertEqual(
            champion_ally_reach("Tahm Kench"), champion_ally_reach("TahmKench")
        )
        self.assertFalse(champion_ally_reach(""))
        self.assertFalse(champion_ally_reach(None))

    def test_non_string_champion_reads_blank(self) -> None:
        for champ in _NON_STR_CHAMPIONS:
            with self.subTest(champ=type(champ).__name__):
                self.assertIs(champion_ally_reach(champ), False)

    def test_unhashable_or_non_string_patch_is_false(self) -> None:
        for patch in ([], ["16.21.1"], {"a": 1}, {1}, 16, b"16.21.1",
                      object()):
            with self.subTest(patch=type(patch).__name__):
                self.assertIs(champion_ally_reach("Janna", patch), False)


class AllyGrantHpNeverRaises(unittest.TestCase):
    """S144-D-131."""

    def test_unstringable_item_id_is_zero(self) -> None:
        for iid in _UNSTRINGABLE:
            with self.subTest(iid=type(iid).__name__):
                self.assertEqual(ally_grant_hp(iid, 10), 0.0)

    def test_string_and_int_ids_unchanged(self) -> None:
        ref = ally_grant_hp("3107", 10)
        self.assertGreater(ref, 0.0)
        self.assertEqual(ally_grant_hp(3107, 10), ref)


class TotalItemAllyGrantHpFailSoft(unittest.TestCase):
    """S144-D-132."""

    def setUp(self) -> None:
        self.ref = ally_grant_hp("3107", 10)
        self.assertGreater(self.ref, 0.0)

    def test_bare_string_inventory_is_one_id(self) -> None:
        self.assertEqual(total_item_ally_grant_hp("3107", 10), self.ref)

    def test_bare_int_inventory_is_one_id(self) -> None:
        self.assertEqual(total_item_ally_grant_hp(3107, 10), self.ref)

    def test_non_iterable_inventory_is_zero(self) -> None:
        for inv in (3.5, float("nan"), float("inf"), True, False, object()):
            with self.subTest(inv=repr(inv)[:30]):
                self.assertEqual(total_item_ally_grant_hp(inv, 10), 0.0)

    def test_raising_iterator_is_zero(self) -> None:
        self.assertEqual(total_item_ally_grant_hp(_raising_iter(), 10), 0.0)

    def test_unstringable_item_drops_rest_still_count(self) -> None:
        for bad in _UNSTRINGABLE:
            with self.subTest(bad=type(bad).__name__):
                self.assertEqual(
                    total_item_ally_grant_hp([bad, "3107"], 10), self.ref
                )
                self.assertEqual(total_item_ally_grant_hp([bad], 10), 0.0)

    def test_list_and_empty_inputs_unchanged(self) -> None:
        self.assertEqual(total_item_ally_grant_hp(["3107"], 10), self.ref)
        self.assertEqual(
            total_item_ally_grant_hp(("3107", None, ""), 10), self.ref
        )
        self.assertEqual(total_item_ally_grant_hp(None, 10), 0.0)
        self.assertEqual(total_item_ally_grant_hp([], 10), 0.0)
        self.assertEqual(total_item_ally_grant_hp("", 10), 0.0)

    def test_result_is_finite(self) -> None:
        for inv in ("3107", 3107, ["3107", "3107"]):
            with self.subTest(inv=inv):
                self.assertTrue(math.isfinite(total_item_ally_grant_hp(inv, 10)))


class ChampionGrantHelpersNonStringChampion(unittest.TestCase):
    """S144-D-133 (ally_flat_hp_grant) plus its two str(champion_id) siblings."""

    def test_string_inputs_unchanged(self) -> None:
        self.assertGreater(ally_flat_hp_grant("Janna", 10, True), 0.0)
        self.assertEqual(ally_flat_hp_grant("Janna", 10, False), 0.0)
        armor, mr = ally_resist_grant("Braum", 10, True)
        self.assertGreater(armor + mr, 0.0)
        self.assertGreater(ally_revive_multiplier("Renata", 10, True), 1.0)

    def test_non_string_champion_is_no_grant(self) -> None:
        for champ in _NON_STR_CHAMPIONS:
            with self.subTest(champ=type(champ).__name__):
                self.assertEqual(ally_flat_hp_grant(champ, 10, True), 0.0)
                self.assertEqual(
                    ally_resist_grant(champ, 10, True), (0.0, 0.0)
                )
                self.assertEqual(ally_revive_multiplier(champ, 10, True), 1.0)


if __name__ == "__main__":
    unittest.main()
