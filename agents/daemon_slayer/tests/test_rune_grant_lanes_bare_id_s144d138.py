"""S144-D-138..141: the four rune grant lanes read a bare id as ONE id.

OFFLINE ONLY - no DS :8860 call, no network. Each helper below types its page
``Iterable[str | int]`` and keys its registry by ``str(rid)``, but a bare id was
mishandled (measured before the fix, this cycle):

  * S144-D-138 ``_rune_flat_mitigation.rune_flat_mitigation_hp("8473", ...)``
    read the string character by character and returned (0, 0, 0) instead of
    Bone Plating's prevented HP; a bare int 8473 or None raised TypeError.
  * S144-D-139 ``_rune_health_grants.rune_health_grants("8451", ...)`` - the
    same char-by-char read lost Overgrowth; int / None raised.
  * S144-D-140 ``_rune_offense_grants.rune_offense_grants("8236", ...)`` - the
    same, losing Gathering Storm; int / None raised.
  * S144-D-141 ``_rune_resist_grants.rune_resist_grants("8429", ...)`` - the
    same, losing Conditioning; int / None raised.

Contract (the S144-D-132 / S144-D-134 rule): a bare ``str`` or ``int`` (never
``bool``) is one id, and None is an empty page. A list / tuple input is
byte-identical to before - pinned by comparing the bare call to the one-tuple
call, which is the pre-fix path. The DEFAULT-OFF gates are untouched: a bare id
with the flag off still credits nothing.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._rune_flat_mitigation import rune_flat_mitigation_hp
from agents.daemon_slayer._rune_health_grants import rune_health_grants
from agents.daemon_slayer._rune_offense_grants import rune_offense_grants
from agents.daemon_slayer._rune_resist_grants import rune_resist_grants

_FLAT_KW = {"level": 13, "apply_rune_flat_mitigation": True}
_HEALTH_KW = {"level": 13, "max_hp": 2000.0, "apply_rune_health_grants": True}
_OFFENSE_KW = {"level": 13, "bonus_ad": 100.0, "ap": 0.0}
_RESIST_KW = {
    "level": 13,
    "total_armor": 120.0,
    "total_mr": 80.0,
    "base_armor": 80.0,
    "base_mr": 50.0,
}

# (label, function, kwargs, registered rune id, zero result)
_CASES = (
    ("S144-D-138 flat mitigation", rune_flat_mitigation_hp, _FLAT_KW, "8473",
     (0.0, 0.0, 0.0)),
    ("S144-D-139 health grants", rune_health_grants, _HEALTH_KW, "8451",
     (0.0, 0.0)),
    ("S144-D-140 offense grants", rune_offense_grants, _OFFENSE_KW, "8236",
     (0.0, 0.0, 0.0)),
    ("S144-D-141 resist grants", rune_resist_grants, _RESIST_KW, "8429",
     (0.0, 0.0)),
)


class TestBareIdIsOneId(unittest.TestCase):
    def test_tuple_page_credits_the_rune(self):
        # Anchor: the one-tuple (pre-fix) path really credits something, so the
        # equality checks below cannot pass on two zero results.
        for label, fn, kw, rid, zero in _CASES:
            with self.subTest(label):
                self.assertNotEqual(fn((rid,), **kw), zero)

    def test_bare_str_matches_the_one_tuple(self):
        for label, fn, kw, rid, _zero in _CASES:
            with self.subTest(label):
                self.assertEqual(fn(rid, **kw), fn((rid,), **kw))

    def test_bare_int_matches_the_one_tuple(self):
        for label, fn, kw, rid, _zero in _CASES:
            with self.subTest(label):
                self.assertEqual(fn(int(rid), **kw), fn((rid,), **kw))

    def test_none_is_an_empty_page(self):
        for label, fn, kw, _rid, zero in _CASES:
            with self.subTest(label):
                self.assertEqual(fn(None, **kw), zero)
                self.assertEqual(fn(None, **kw), fn((), **kw))

    def test_bool_is_not_an_id(self):
        # True must not be read as rune id "True" or 1; it stays a TypeError
        # (not iterable) exactly as before the fix.
        for label, fn, kw, _rid, _zero in _CASES:
            with self.subTest(label):
                with self.assertRaises(TypeError):
                    fn(True, **kw)

    def test_list_page_is_unchanged(self):
        for label, fn, kw, rid, _zero in _CASES:
            with self.subTest(label):
                self.assertEqual(fn([rid, "0000"], **kw), fn((rid,), **kw))


class TestDefaultOffGatesStillWin(unittest.TestCase):
    def test_flat_mitigation_bare_id_flag_off_is_zero(self):
        self.assertEqual(
            rune_flat_mitigation_hp("8473", level=13), (0.0, 0.0, 0.0)
        )

    def test_health_grants_bare_id_flag_off_is_zero(self):
        self.assertEqual(
            rune_health_grants("8451", level=13, max_hp=2000.0), (0.0, 0.0)
        )


if __name__ == "__main__":
    unittest.main()
