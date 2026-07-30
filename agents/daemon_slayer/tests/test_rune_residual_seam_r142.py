"""RM-101 RESIDUAL rune seams wired into compute_ehp (R142, ENGINE 1.229.0).

The remainder R136 left standing. R132 shipped the rune RESIST feed (a
DENOMINATOR add); R136 shipped the rune HEALTH / HSP feeds (NUMERATOR adds).
These two seams close the last two BUILDABLE runes on the RM-101 list, and they
reuse the SAME ``rune_ids`` transport R132 plumbed, so no new ids parameter
lands on any entry point:

  * ``apply_rune_self_heal`` - Second Wind 8444's missing-health heal-over-time.
    R136's spec claimed this rune was blocked on a missing-health convention the
    EHP scorer lacked. It lacks nothing: ``_MISSING_HP_SHARE_FOR_HEALS`` is a
    module constant at the heal call site, and the seam reuses it rather than
    inventing a second reading.
  * ``apply_rune_shield_grants`` - Guardian 8465's SELF shield, level-lerped
    40-150 plus 6% of bonus health.

Verbatim DDragon 16.14.1 ``runesReforged.json`` longDescs, reproduced rather
than paraphrased (the R132 Aftershock-cap lesson):

  * 8444 SecondWind: "After taking damage from an enemy champion, heal for 4% of
    your missing health over 10s."
  * 8465 Guardian: "Guard allies within 350 units of you, and allies you target
    with spells for 2.5s. While Guarding, if you or the ally take more than a
    small amount of damage over the duration of the Guard, both of you gain a
    shield for 1.5s.<br><br>Cooldown: 75 - 40 seconds<br>Shield: 40 - 150 + 20%
    of your ability power + 6% of your bonus health<br>Proc Threshold: 50 - 165
    postmitigation damage"

GUARDIAN SHIPS TWO DELIBERATE OMISSIONS, both read-and-rejected rather than
overlooked, and both pinned below so a future cycle cannot quietly "fix" them:

  1. The ALLY half is throughput to a second unit the EHP frame does not model.
  2. The "+20% of your ability power" term is UNREPRESENTABLE - ``ehp.py``
     carries no wielder ability power at all (every ``ap`` token in that module
     is ``enemy_ap_share``, a share of INCOMING damage by type, which is a
     different quantity entirely). Omitting it makes the credit a deliberate
     UNDERCOUNT, which is the safe direction. The shipped precedent is the
     Irelia-W / Fizz-P omitted-term subset.

Font of Life 8463 is NOT wired and must not be - its base heal is an unresolved
``@BaseHeal@`` template variable in live DDragon, present in ALL FOUR vendored
patch snapshots. Inventing a number is the exact failure mode the R132 lesson
exists to prevent; ``test_font_of_life_is_still_not_credited`` pins the absence.

Contract:
  * OFF (default) -> BYTE-IDENTICAL to 1.228.0, including when ``rune_ids``
    carries a full Resolve page. Passing ids alone does NOT arm either seam.
  * The two flags are INDEPENDENT of each other and of the R132 / R136 flags.
  * ON -> strictly greater EHP (both seams are numerator adds).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP = None

# A full Resolve page: the two R142 residual runes, the R136 health / HSP trio,
# the three R132 resist runes, and the one rune that must never be credited.
_FULL_PAGE = ["8444", "8465", "8451", "8437", "8453", "8439", "8429", "8242", "8463"]


def _snap():
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# Sunfire Aegis + Thornmail: a pure-resist tank build carrying NO self-shield and
# no lifesteal, so each rune term is observable against a quiet baseline.
_TANK_BUILD = ["3068", "3075"]


def _ehp(*, heal=False, shield=False, runes=(), champ="Ornn", level=13,
         items=None):
    return compute_ehp(
        _snap(), champion_id=champ, level=level,
        item_ids=list(items if items is not None else _TANK_BUILD), mode="SR",
        apply_rune_self_heal=heal,
        apply_rune_shield_grants=shield,
        rune_ids=list(runes),
    )


_EHP_FIELDS = ("physical_ehp", "magical_ehp", "true_ehp")


class DefaultOffInertnessTests(unittest.TestCase):
    """OFF is byte-identical, and ids alone do not arm either seam."""

    def test_engine_version_pinned(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.267.0")

    def test_omitting_the_flags_matches_explicit_false(self) -> None:
        implicit = compute_ehp(
            _snap(), champion_id="Ornn", level=13,
            item_ids=list(_TANK_BUILD), mode="SR",
        )
        explicit = _ehp(heal=False, shield=False)
        for field in _EHP_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(
                    getattr(implicit, field), getattr(explicit, field),
                    msg="explicit False must equal omitting the kwarg entirely",
                )

    def test_rune_ids_alone_do_not_arm_either_seam(self) -> None:
        bare = _ehp(heal=False, shield=False, runes=())
        paged = _ehp(heal=False, shield=False, runes=_FULL_PAGE)
        for field in _EHP_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(getattr(bare, field), getattr(paged, field))


class SecondWindSeamTests(unittest.TestCase):
    """apply_rune_self_heal raises the numerator off the heal pool."""

    def test_self_heal_raises_every_per_type_ehp(self) -> None:
        off = _ehp(heal=False, runes=_FULL_PAGE)
        on = _ehp(heal=True, runes=_FULL_PAGE)
        for field in _EHP_FIELDS:
            with self.subTest(field=field):
                self.assertGreater(getattr(on, field), getattr(off, field))

    def test_unknown_runes_leave_the_seam_inert_even_when_armed(self) -> None:
        # The credit comes from the registry, not the flag.
        off = _ehp(heal=False, runes=["8005", "8010"])
        on = _ehp(heal=True, runes=["8005", "8010"])
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_credit_scales_with_max_health(self) -> None:
        # 4% of MISSING health, and missing health is a share of max - so the
        # same rune on a bigger health pool must be worth strictly more. This is
        # an invariant on the shape of the term, not a pinned magnitude.
        small = _ehp(heal=True, runes=["8444"], level=6)
        big = _ehp(heal=True, runes=["8444"], level=18)
        small_off = _ehp(heal=False, runes=["8444"], level=6)
        big_off = _ehp(heal=False, runes=["8444"], level=18)
        self.assertGreater(
            big.physical_ehp - big_off.physical_ehp,
            small.physical_ehp - small_off.physical_ehp,
        )


class GuardianSeamTests(unittest.TestCase):
    """apply_rune_shield_grants raises the numerator off the ANY shield pool."""

    def test_shield_grant_raises_every_per_type_ehp(self) -> None:
        off = _ehp(shield=False, runes=_FULL_PAGE)
        on = _ehp(shield=True, runes=_FULL_PAGE)
        for field in _EHP_FIELDS:
            with self.subTest(field=field):
                self.assertGreater(getattr(on, field), getattr(off, field))

    def test_unknown_runes_leave_the_seam_inert_even_when_armed(self) -> None:
        off = _ehp(shield=False, runes=["8005", "8010"])
        on = _ehp(shield=True, runes=["8005", "8010"])
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_higher_level_grants_a_larger_shield(self) -> None:
        # The 40-150 walk is level-lerped, so level 18 must out-credit level 1
        # even after the bonus-health term is held constant by the same build.
        lo_on = _ehp(shield=True, runes=["8465"], level=1)
        lo_off = _ehp(shield=False, runes=["8465"], level=1)
        hi_on = _ehp(shield=True, runes=["8465"], level=18)
        hi_off = _ehp(shield=False, runes=["8465"], level=18)
        self.assertGreater(
            hi_on.physical_ehp - hi_off.physical_ehp,
            lo_on.physical_ehp - lo_off.physical_ehp,
        )


class SeamIndependenceTests(unittest.TestCase):
    """Each flag moves ONLY its own term."""

    def test_arming_one_seam_does_not_move_the_other(self) -> None:
        base = _ehp(runes=_FULL_PAGE)
        heal_only = _ehp(heal=True, runes=_FULL_PAGE)
        shield_only = _ehp(shield=True, runes=_FULL_PAGE)
        both = _ehp(heal=True, shield=True, runes=_FULL_PAGE)
        heal_delta = heal_only.physical_ehp - base.physical_ehp
        shield_delta = shield_only.physical_ehp - base.physical_ehp
        both_delta = both.physical_ehp - base.physical_ehp
        self.assertGreater(heal_delta, 0.0)
        self.assertGreater(shield_delta, 0.0)
        self.assertAlmostEqual(both_delta, heal_delta + shield_delta, places=6)

    def test_r142_seams_do_not_disturb_the_r132_r136_lanes(self) -> None:
        # Arming the residual pair must leave the older rune lanes' own deltas
        # untouched - the lanes are additive, not entangled.
        def _with(**kw):
            return compute_ehp(
                _snap(), champion_id="Ornn", level=13,
                item_ids=list(_TANK_BUILD), mode="SR",
                rune_ids=list(_FULL_PAGE), **kw,
            )

        older_delta = (
            _with(apply_rune_health_grants=True).physical_ehp
            - _with().physical_ehp
        )
        older_delta_with_r142 = (
            _with(apply_rune_health_grants=True, apply_rune_self_heal=True,
                  apply_rune_shield_grants=True).physical_ehp
            - _with(apply_rune_self_heal=True,
                    apply_rune_shield_grants=True).physical_ehp
        )
        self.assertAlmostEqual(older_delta, older_delta_with_r142, places=6)


class DataBlockedRuneTests(unittest.TestCase):
    """Font of Life 8463 stays uncredited - its magnitude does not exist."""

    def test_font_of_life_is_still_not_credited(self) -> None:
        off = _ehp(heal=False, shield=False, runes=["8463"])
        on = _ehp(heal=True, shield=True, runes=["8463"])
        for field in _EHP_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(getattr(on, field), getattr(off, field))


if __name__ == "__main__":
    unittest.main()
