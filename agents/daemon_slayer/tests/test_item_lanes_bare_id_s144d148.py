"""S144-D-148..153: the last six item-side id-list helpers read a bare id as ONE id.

OFFLINE ONLY - no DS :8860 call, no network. Each helper below types its page
``Iterable[str | int]`` and keys its registry by ``str(iid)``, but a bare id was
mishandled (measured before the fix, this cycle):

  * S144-D-148 ``_item_proc_heal.item_proc_heal_hp("2502", ...)`` (flag armed)
    read the string character by character and returned 0.0 instead of
    Unending Despair's Anguish heal; a bare int 2502 or None raised TypeError.
  * S144-D-149 ``_item_resist_grants.item_resist_grants("6665", ...)`` - the
    same char-by-char read lost Jak'Sho's percent-of-bonus grant; int / None
    raised.
  * S144-D-150 ``_item_revive.item_revive_max_hp_fraction("3026", ...)`` - the
    same, losing Guardian Angel's revive; int / None raised.
  * S144-D-151 ``_item_spell_shield_overrides.item_spell_shield_fraction("3102")``
    - the same, losing Banshee's Veil's Annul; int / None raised.
  * S144-D-152 ``_item_survival_window.item_survival_window_fraction("3157", ...)``
    - the same, losing Zhonya's stasis; int / None raised.
  * S144-D-153 ``_item_tenacity.total_item_tenacity("3111")`` - the same,
    losing Mercury's Treads' tenacity; int / None raised.

Contract (the S144-D-142 rule): a bare ``str`` or ``int`` (never ``bool``) is
one id, and None is an empty page. A list / tuple input is byte-identical to
before - pinned by comparing the bare call to the one-tuple call, which is the
pre-fix path. The DEFAULT-OFF proc-heal gate is untouched: with the flag off a
bare id, None or even a bool still returns 0.0 before the page is read.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._item_proc_heal import item_proc_heal_hp
from agents.daemon_slayer._item_resist_grants import item_resist_grants
from agents.daemon_slayer._item_revive import item_revive_max_hp_fraction
from agents.daemon_slayer._item_spell_shield_overrides import (
    item_spell_shield_fraction,
)
from agents.daemon_slayer._item_survival_window import (
    item_survival_window_fraction,
)
from agents.daemon_slayer._item_tenacity import total_item_tenacity


def _proc_heal(ids):
    return item_proc_heal_hp(ids, 1200.0, assume_item_proc_heal=True)


def _resist_grants(ids):
    return item_resist_grants(
        ids, total_armor=150.0, total_mr=90.0, base_armor=40.0, base_mr=32.0
    )


def _revive(ids):
    return item_revive_max_hp_fraction(ids, 1000.0, 2500.0)


def _spell_shield(ids):
    return item_spell_shield_fraction(ids)


def _survival_window(ids):
    return item_survival_window_fraction(ids, 6.0)


def _tenacity(ids):
    return total_item_tenacity(ids)


# (label, call, registered item id, empty-page result)
_CASES = (
    ("S144-D-148 proc heal", _proc_heal, "2502", 0.0),
    ("S144-D-149 resist grants", _resist_grants, "6665", (0.0, 0.0)),
    ("S144-D-150 revive", _revive, "3026", 0.0),
    ("S144-D-151 spell shield", _spell_shield, "3102", 0.0),
    ("S144-D-152 survival window", _survival_window, "3157", 0.0),
    ("S144-D-153 tenacity", _tenacity, "3111", 0.0),
)


class TestBareIdIsOneId(unittest.TestCase):
    def test_tuple_page_credits_the_item(self):
        # Anchor: the one-tuple (pre-fix) path really credits something, so the
        # equality checks below cannot pass on two empty results.
        for label, fn, iid, empty in _CASES:
            with self.subTest(label):
                self.assertNotEqual(fn((iid,)), empty)

    def test_bare_str_matches_the_one_tuple(self):
        for label, fn, iid, _empty in _CASES:
            with self.subTest(label):
                self.assertEqual(fn(iid), fn((iid,)))

    def test_bare_int_matches_the_one_tuple(self):
        for label, fn, iid, _empty in _CASES:
            with self.subTest(label):
                self.assertEqual(fn(int(iid)), fn((iid,)))

    def test_none_is_an_empty_page(self):
        for label, fn, _iid, empty in _CASES:
            with self.subTest(label):
                self.assertEqual(fn(None), empty)
                self.assertEqual(fn(None), fn(()))

    def test_bool_is_not_an_id(self):
        # True must not be read as item id "True" or 1; it stays a TypeError
        # (not iterable) exactly as before the fix.
        for label, fn, _iid, _empty in _CASES:
            with self.subTest(label):
                with self.assertRaises(TypeError):
                    fn(True)

    def test_list_page_is_unchanged(self):
        for label, fn, iid, _empty in _CASES:
            with self.subTest(label):
                self.assertEqual(fn([iid, "0000"]), fn((iid,)))


class TestDefaultOffGateStillWins(unittest.TestCase):
    def test_proc_heal_flag_off_returns_zero_before_reading_the_page(self):
        self.assertEqual(item_proc_heal_hp("2502", 1200.0), 0.0)
        self.assertEqual(item_proc_heal_hp(None, 1200.0), 0.0)
        self.assertEqual(item_proc_heal_hp(True, 1200.0), 0.0)


if __name__ == "__main__":
    unittest.main()
