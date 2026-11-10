"""S144-D-142..147: six item-side id-list helpers read a bare id as ONE id.

OFFLINE ONLY - no DS :8860 call, no network. Each helper below types its page
``Iterable[str | int]`` and keys its registry by ``str(iid)``, but a bare id was
mishandled (measured before the fix, this cycle):

  * S144-D-142 ``_item_ability_haste.total_item_ability_haste("2020")`` read
    the string character by character and returned 0 instead of The
    Brutalizer's 10 AH; a bare int 2020 or None raised TypeError.
  * S144-D-143 ``_item_bonus_hp_amp.item_bonus_hp_amp_hp("3083", ...)`` - the
    same char-by-char read lost Warmog's Vitality; int / None raised.
  * S144-D-144 ``_item_general_dr.item_general_dr_multiplier("3869", ...)`` -
    the same, losing Celestial Opposition's DR (identity 1.0); int / None
    raised with the flag armed.
  * S144-D-145 ``_item_health_stack.item_health_stack_hp("3084", ...)`` - the
    same, losing Heartsteel's stacks; int / None raised.
  * S144-D-146 ``_item_mana_health.item_mana_health_hp("3119", ...)`` - the
    same, losing Winter's Approach's Awe; int / None raised.
  * S144-D-147 ``_item_omnivamp.item_omnivamp_fraction("4633", ...)`` - the
    same, losing Riftmaker's omnivamp; int / None raised.

Contract (the S144-D-134 / S144-D-138 rule): a bare ``str`` or ``int`` (never
``bool``) is one id, and None is an empty page. A list / tuple input is
byte-identical to before - pinned by comparing the bare call to the one-tuple
call, which is the pre-fix path. The DEFAULT-OFF general-DR gate is untouched:
a bare id with the flag off still returns identity.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._item_ability_haste import total_item_ability_haste
from agents.daemon_slayer._item_bonus_hp_amp import item_bonus_hp_amp_hp
from agents.daemon_slayer._item_general_dr import item_general_dr_multiplier
from agents.daemon_slayer._item_health_stack import item_health_stack_hp
from agents.daemon_slayer._item_mana_health import item_mana_health_hp
from agents.daemon_slayer._item_omnivamp import item_omnivamp_fraction


def _haste(ids):
    return total_item_ability_haste(ids)


def _hp_amp(ids):
    return item_bonus_hp_amp_hp(ids, 1500.0)


def _general_dr(ids):
    return item_general_dr_multiplier(ids, True, assume_item_general_dr=True)


def _health_stack(ids):
    return item_health_stack_hp(ids, 3000.0, 13)


def _mana_health(ids):
    return item_mana_health_hp(ids, 800.0)


def _omnivamp(ids):
    return item_omnivamp_fraction(ids, False)


# (label, call, registered item id, empty-page result)
_CASES = (
    ("S144-D-142 ability haste", _haste, "2020", 0),
    ("S144-D-143 bonus hp amp", _hp_amp, "3083", 0.0),
    ("S144-D-144 general dr", _general_dr, "3869", 1.0),
    ("S144-D-145 health stack", _health_stack, "3084", 0.0),
    ("S144-D-146 mana health", _mana_health, "3119", 0.0),
    ("S144-D-147 omnivamp", _omnivamp, "4633", 0.0),
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
    def test_general_dr_bare_id_flag_off_is_identity(self):
        self.assertEqual(item_general_dr_multiplier("3869", True), 1.0)
        self.assertEqual(item_general_dr_multiplier(None, True), 1.0)


if __name__ == "__main__":
    unittest.main()
