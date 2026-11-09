"""S144-T-687 - the RM-41 off-axis gate fails SOFT on junk input.

``_burst_off_axis`` reads two untrusted-shape blocks off the DS snapshot: the
champion record's ``lolmath.damage_distribution`` and the item record's
DDragon ``stats``. Its docstring promises fail-soft: a missing record, a
missing block or a non-numeric entry returns ``None`` (champion) and a junk
item never strips. The ranker that calls it (``burst.rank_items_by_burst`` and
``rank.rank_items``) runs on the DS :8860 request path, so a raise here is an
HTTP 500, and a junk value that DECIDES an axis or an offense strips real
items from a build list.

Findings pinned here (each test fails against the pre-fix module):

* F1 a truthy NON-MAPPING ``lolmath`` (a list, a string) raised
  ``AttributeError`` out of ``champion_burst_axis``.
* F2 an integer share too large for a float raised ``OverflowError`` (the
  handler caught ``TypeError`` / ``ValueError`` only); same for an item stat
  in ``_offense``.
* F3 a non-finite, negative, above-1 or bool share DECIDED an axis: an
  ``inf`` magical share or a ``True`` one resolved ``"ap"``, a negative other
  share inflated the margin past the 0.20 gate. A damage distribution is a
  set of fractions in [0, 1]; anything else is junk and resolves ``None``
  (the caller's no-op), exactly like a non-numeric entry already did.
* F4 a non-finite or bool item stat counted as offense, so an ``inf`` AD
  stat on an otherwise empty item stripped it for an AP champion.

Valid input is unchanged: the measured 16.x snapshot carries 346 float shares,
all finite and in [0, 1], and every champion verdict and off-axis item set is
byte-identical before and after (checked in the cycle report, and pinned
class-wide by ``test_burst_off_axis_rm41.py``).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._burst_off_axis import (
    _offense,
    _PHYSICAL_OFFENSE_KEYS,
    champion_burst_axis,
    is_off_axis_candidate,
)

_HUGE = 10 ** 400  # an int no float can hold - float() raises OverflowError


def _champ(magical, physical) -> dict:
    return {"lolmath": {"damage_distribution": {"magical": magical, "physical": physical}}}


class ChampionAxisFailSoftTests(unittest.TestCase):
    def test_f1_non_mapping_lolmath_is_none_not_a_raise(self) -> None:
        for lolmath in (["damage_distribution"], "lolmath", 5, (1, 2)):
            with self.subTest(lolmath=lolmath):
                self.assertIsNone(champion_burst_axis({"lolmath": lolmath}))

    def test_f2_overflowing_share_is_none_not_a_raise(self) -> None:
        # Labelled by index: a 400-digit int cannot cross the xdist channel
        # (tests/_subtest_channel_guard.py).
        for case, (mag, phys) in enumerate(((_HUGE, 0.1), (0.1, _HUGE), (-_HUGE, 0.9))):
            with self.subTest(case=case):
                self.assertIsNone(champion_burst_axis(_champ(mag, phys)))

    def test_f3_non_finite_share_decides_no_axis(self) -> None:
        inf, nan = float("inf"), float("nan")
        for mag, phys in ((inf, 0.1), (0.1, inf), (inf, inf), (nan, 0.9),
                          (0.9, nan), (-inf, 0.9), ("inf", 0.0), ("nan", 0.9)):
            with self.subTest(mag=mag, phys=phys):
                self.assertIsNone(champion_burst_axis(_champ(mag, phys)))

    def test_f3_bool_share_decides_no_axis(self) -> None:
        # True is an int subclass, so float(True) == 1.0 - a 100 percent share.
        for mag, phys in ((True, 0.0), (0.0, True), (True, False)):
            with self.subTest(mag=mag, phys=phys):
                self.assertIsNone(champion_burst_axis(_champ(mag, phys)))

    def test_f3_out_of_range_share_decides_no_axis(self) -> None:
        # 0.56 / 0.40 is INDECISIVE (margin 0.16 < 0.20); a negative magical
        # share must not manufacture the margin that turns it into "ad".
        self.assertIsNone(champion_burst_axis(_champ(0.40, 0.56)))
        for mag, phys in ((-0.1, 0.56), (0.56, -0.5), (5.0, 0.1), (0.1, 1.5)):
            with self.subTest(mag=mag, phys=phys):
                self.assertIsNone(champion_burst_axis(_champ(mag, phys)))

    def test_valid_shares_keep_their_verdicts(self) -> None:
        # Characterization: the fix must not move a real verdict.
        self.assertEqual(champion_burst_axis(_champ(0.855, 0.10)), "ap")
        self.assertEqual(champion_burst_axis(_champ(0.05, 0.95)), "ad")
        self.assertEqual(champion_burst_axis(_champ(1.0, 0.0)), "ap")
        self.assertEqual(champion_burst_axis(_champ(0, 1)), "ad")
        self.assertIsNone(champion_burst_axis(_champ(0.521, 0.347)))  # Shaco
        self.assertIsNone(champion_burst_axis(_champ(0.0, 0.0)))
        # A missing key is a zero share (pre-fix behaviour, kept).
        self.assertEqual(
            champion_burst_axis({"lolmath": {"damage_distribution": {"physical": 0.9}}}),
            "ad",
        )
        # A numeric string is still read as its number (pre-fix behaviour, kept).
        self.assertEqual(champion_burst_axis(_champ("0.8", "0.1")), "ap")
        # The boundary values sit ON the gates (>=), as before.
        self.assertEqual(champion_burst_axis(_champ(0.55, 0.35)), "ap")


class OffenseFailSoftTests(unittest.TestCase):
    def test_f2_overflowing_stat_is_no_offense_not_a_raise(self) -> None:
        self.assertFalse(_offense({"FlatPhysicalDamageMod": _HUGE}, _PHYSICAL_OFFENSE_KEYS))
        self.assertFalse(is_off_axis_candidate({"stats": {"FlatPhysicalDamageMod": _HUGE}}, "ap"))

    def test_f2_overflow_on_one_key_does_not_hide_the_next(self) -> None:
        stats = {"FlatPhysicalDamageMod": _HUGE, "FlatCritChanceMod": 0.25}
        self.assertTrue(_offense(stats, _PHYSICAL_OFFENSE_KEYS))

    def test_f4_non_finite_stat_is_no_offense(self) -> None:
        for value in (float("inf"), float("nan"), "inf", "Infinity"):
            with self.subTest(value=value):
                self.assertFalse(
                    is_off_axis_candidate({"stats": {"FlatPhysicalDamageMod": value}}, "ap")
                )
                self.assertFalse(
                    is_off_axis_candidate({"stats": {"FlatMagicDamageMod": value}}, "ad")
                )

    def test_f4_bool_stat_is_no_offense(self) -> None:
        self.assertFalse(is_off_axis_candidate({"stats": {"FlatPhysicalDamageMod": True}}, "ap"))
        self.assertFalse(is_off_axis_candidate({"stats": {"FlatMagicDamageMod": True}}, "ad"))

    def test_f4_junk_off_axis_stat_does_not_shield_a_real_on_axis_strip(self) -> None:
        # A junk MAGIC stat must not count as on-axis offense either: a pure-AD
        # item carrying a junk AP field is still stripped for an AP champion.
        rec = {"stats": {"FlatPhysicalDamageMod": 40, "FlatMagicDamageMod": float("inf")}}
        self.assertTrue(is_off_axis_candidate(rec, "ap"))

    def test_valid_stats_keep_their_verdicts(self) -> None:
        self.assertTrue(is_off_axis_candidate({"stats": {"FlatPhysicalDamageMod": 40}}, "ap"))
        self.assertTrue(is_off_axis_candidate({"stats": {"FlatCritChanceMod": 0.25}}, "ap"))
        self.assertTrue(is_off_axis_candidate({"stats": {"FlatMagicDamageMod": 80}}, "ad"))
        self.assertFalse(
            is_off_axis_candidate(
                {"stats": {"FlatMagicDamageMod": 80, "FlatPhysicalDamageMod": 40}}, "ap"
            )
        )
        self.assertFalse(is_off_axis_candidate({"stats": {"FlatHPPoolMod": 400}}, "ap"))
        self.assertFalse(is_off_axis_candidate({"stats": {"FlatPhysicalDamageMod": 40}}, None))
        self.assertFalse(is_off_axis_candidate({"stats": {"FlatPhysicalDamageMod": -5}}, "ap"))
        self.assertFalse(is_off_axis_candidate({"stats": ["FlatPhysicalDamageMod"]}, "ap"))
        self.assertFalse(is_off_axis_candidate(None, "ap"))


if __name__ == "__main__":
    unittest.main()
