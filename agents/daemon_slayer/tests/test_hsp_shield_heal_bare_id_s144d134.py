"""S144-D-134..137: the fail-soft HSP / self-heal / shield lanes read a bare id as ONE id.

OFFLINE ONLY - no DS :8860 call, no network. Each helper below types its
argument ``Optional[Iterable[str | int]]`` and documents itself fail-soft on the
page / inventory shape, but a bare id was mishandled (measured before the fix):

  * S144-D-134 ``_rune_hsp_amp.sum_rune_hsp_pct("8453")`` read the string
    character by character ("8", "4", "5", "3") and returned 0.0 instead of
    Revitalize's 0.05; a bare int 8453 hit the TypeError guard -> 0.0.
  * S144-D-135 ``_rune_self_heal.sum_rune_self_heal("8444", ...)`` - the same
    char-by-char read lost Second Wind's heal; a bare int lost it too.
  * S144-D-136 ``_rune_shield_grants.rune_shield_grants("8465", ...)`` - the
    same, losing Guardian's shield.
  * S144-D-137 ``_hsp_amp.sum_wielder_hsp_pct``: a bare "3107" lost
    Redemption's 0.10; a bare int 3107 (or any non-iterable) RAISED TypeError
    out of ``(item_ids or [])``, and an inventory whose truthiness raises (a
    multi-element array) escaped as ValueError - both against the documented
    "fail-soft" contract.

Contract (the S144-D-132 ``total_item_ally_grant_hp`` rule): a bare ``str`` or
``int`` (never ``bool``) is one id; any other non-iterable, or an inventory
whose truthiness or iteration raises, returns 0.0. A list / tuple input is
byte-identical to before - pinned by comparing the bare call to the one-tuple
call, which is the pre-fix path.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct
from agents.daemon_slayer._rune_hsp_amp import sum_rune_hsp_pct
from agents.daemon_slayer._rune_self_heal import sum_rune_self_heal
from agents.daemon_slayer._rune_shield_grants import rune_shield_grants

_REVITALIZE = "8453"
_SECOND_WIND = "8444"
_GUARDIAN = "8465"
_REDEMPTION = "3107"

_POOL = 3000.0


def _shield(page):
    return rune_shield_grants(
        page,
        level=11,
        total_hp=2000.0,
        base_hp=1200.0,
        apply_rune_shield_grants=True,
    )


class _RaisingTruth:
    """An inventory whose truthiness raises (a multi-element numpy array)."""

    def __bool__(self):
        raise ValueError("truth value is ambiguous")

    def __iter__(self):
        return iter([_REDEMPTION])


class RuneHspBareIdTests(unittest.TestCase):
    """S144-D-134."""

    def test_bare_str_is_one_id(self) -> None:
        self.assertAlmostEqual(sum_rune_hsp_pct([_REVITALIZE]), 0.05, places=9)
        self.assertEqual(sum_rune_hsp_pct(_REVITALIZE), sum_rune_hsp_pct([_REVITALIZE]))

    def test_bare_int_is_one_id(self) -> None:
        self.assertEqual(sum_rune_hsp_pct(8453), sum_rune_hsp_pct([_REVITALIZE]))

    def test_bool_and_unknown_bare_ids_stay_zero(self) -> None:
        for bad in (True, False, 12345, "12345", 3.5):
            with self.subTest(bad=bad):
                self.assertEqual(sum_rune_hsp_pct(bad), 0.0)


class RuneSelfHealBareIdTests(unittest.TestCase):
    """S144-D-135."""

    def test_bare_str_is_one_id(self) -> None:
        listed = sum_rune_self_heal([_SECOND_WIND], max_health=_POOL)
        self.assertGreater(listed, 0.0)
        self.assertEqual(sum_rune_self_heal(_SECOND_WIND, max_health=_POOL), listed)

    def test_bare_int_is_one_id(self) -> None:
        listed = sum_rune_self_heal([_SECOND_WIND], max_health=_POOL)
        self.assertEqual(sum_rune_self_heal(8444, max_health=_POOL), listed)

    def test_bool_and_unknown_bare_ids_stay_zero(self) -> None:
        for bad in (True, False, 1234, "1234", 3.5):
            with self.subTest(bad=bad):
                self.assertEqual(sum_rune_self_heal(bad, max_health=_POOL), 0.0)


class RuneShieldBareIdTests(unittest.TestCase):
    """S144-D-136."""

    def test_bare_str_is_one_id(self) -> None:
        listed = _shield([_GUARDIAN])
        self.assertGreater(listed, 0.0)
        self.assertEqual(_shield(_GUARDIAN), listed)

    def test_bare_int_is_one_id(self) -> None:
        self.assertEqual(_shield(8465), _shield([_GUARDIAN]))

    def test_bool_and_unknown_bare_ids_stay_zero(self) -> None:
        for bad in (True, False, 42, "42", 3.5):
            with self.subTest(bad=bad):
                self.assertEqual(_shield(bad), 0.0)

    def test_gate_off_still_inert_for_a_bare_id(self) -> None:
        self.assertEqual(
            rune_shield_grants(
                _GUARDIAN, level=11, total_hp=2000.0, base_hp=1200.0
            ),
            0.0,
        )


class WielderHspBareIdTests(unittest.TestCase):
    """S144-D-137."""

    def test_bare_str_is_one_id(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct([_REDEMPTION]), 0.10, places=6)
        self.assertEqual(
            sum_wielder_hsp_pct(_REDEMPTION), sum_wielder_hsp_pct([_REDEMPTION])
        )

    def test_bare_int_is_one_id_not_a_raise(self) -> None:
        self.assertEqual(sum_wielder_hsp_pct(3107), sum_wielder_hsp_pct([_REDEMPTION]))

    def test_non_iterable_inventory_fails_soft(self) -> None:
        for bad in (3.5, object(), True):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(sum_wielder_hsp_pct(bad), 0.0)

    def test_raising_truthiness_fails_soft(self) -> None:
        self.assertEqual(sum_wielder_hsp_pct(_RaisingTruth()), 0.0)

    def test_scaling_flag_sees_the_bare_id_too(self) -> None:
        self.assertEqual(
            sum_wielder_hsp_pct(_REDEMPTION, assume_scaling_hsp_grants=True),
            sum_wielder_hsp_pct([_REDEMPTION], assume_scaling_hsp_grants=True),
        )


if __name__ == "__main__":
    unittest.main()
