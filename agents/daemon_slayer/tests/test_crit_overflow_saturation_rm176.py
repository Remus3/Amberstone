"""R212 crit-OVERFLOW saturation - GROUND TRUTH, deliberately left unchanged.

READ THIS BEFORE RE-FILING IT. An audit filed the Yasuo / Yone overflow-to-
bonus-AD term as a defect because it saturates at +50.0 AD no matter how much
crit the build carries. An adversarial adjudication REFUTED that filing and the
engine was NOT changed. This file exists so the behaviour is recorded as pinned
ground truth rather than rediscovered and re-filed.

WHY IT WAS LEFT ALONE, both halves:

  1. The filed ROOT CAUSE was wrong. The filing blamed the engine-wide crit
     clamp at ``engine.py:217-218``. That clamp is not what binds. The binding
     clamp is ``crit_total = min(raw_crit + crit_from_effects, 1.0)`` at
     ``dps.py:1148``, which runs AFTER the engine one and re-clamps a sum the
     engine never saw. Simulating removal of the ``engine.py`` clamp leaves the
     term at +50.0 unchanged.
     ``test_effect_sourced_crit_still_saturates_at_fifty`` demonstrates this
     against the live engine rather than by argument: crit arriving from an
     ``ItemEffect`` bypasses ``engine.py:217-218`` entirely, lands on a build
     whose DDragon crit is exactly 1.00 (so the engine clamp is not even
     triggered), and is still discarded - by ``dps.py:1148``.

  2. Game truth is UNRESOLVED, so a "fix" would be a guess. The DDragon prose
     ("every 1% critical strike chance in excess of 100% is converted into 0.5
     bonus attack damage") is silent on whether the PRE-doubling crit sum is
     itself capped, which is exactly the ordering question that decides whether
     the ceiling is +50.0 or +100.0. The module author knew about the clamp and
     reasoned about its consequence in writing - see
     ``_crit_chance_overrides.py:264-267``, where Senna's overflow is recorded
     as structurally zero on the shipped engine for the same reason.

  And the clamp itself is CORRECT for the other 171 champions: crit chance above
  100 percent is meaningless for everyone without an overflow conversion, so
  moving or removing it to serve two champions would be the larger change.

TO REVISIT IT you need a wiki-verified re-derivation of whether Riot caps crit
chance BEFORE or AFTER Yasuo's doubling. Not a re-reading of the DDragon
string, which has already been read and does not answer it. If the answer turns
out to be "after", the fix is to hand the overflow helper the UNCLAMPED sum at
``dps.py:1148`` - the registry helper is already unsaturated and needs no
change, which ``test_registry_helper_is_not_saturated`` pins.

WHAT THIS FILE ADDS over ``test_crit_chance_overrides_r212.py``: that suite's
``test_yasuo_overflow_ad_is_credited_above_the_cap`` is TAUTOLOGICAL above the
cap - it recomputes ``min(off.stats["crit"], 1.0)`` on a value the engine has
already clamped, so the ``min`` is a no-op and the expectation is re-derived
from the engine's own output. Its ``OVERFLOW_BUILD`` also carries only three
crit items (0.75 raw, 1.50 doubled), which never reaches saturation. Nothing in
the suite exercised above the cap. These tests do, and they compute the raw crit
sum straight off the snapshot's item stat blocks so no assertion can be
satisfied by the clamped value it is meant to be checking.

OFFLINE ONLY: no live :8860, no network.
"""

from __future__ import annotations

import re
import unittest

from agents.daemon_slayer._crit_chance_overrides import (
    crit_chance_entry,
    overflow_bonus_ad,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

YASUO = "Yasuo"

# The raw-crit level at which the term stops growing. This is the ``1.0`` in
# ``dps.py:1148``, not a property of any build - measured by the boundary test
# below rather than assumed by it.
SATURATION_RAW_CRIT = 1.00
SATURATED_OVERFLOW_AD = 50.0

# All crit ids used below are asserted against the snapshot by
# ``SnapshotCritPoolTests`` before any build is trusted; their crit VALUES are
# read from the snapshot, never hardcoded into a rung.
LADDER = (
    ("3031", "1018"),
    ("3031", "3046"),
    ("3031", "3046", "1018"),
    ("3031", "3046", "3085"),
    ("3031", "3046", "3085", "1018"),
    ("3031", "3046", "3085", "3094"),
    ("3031", "3046", "3085", "1018", "3086"),
    ("3031", "3046", "3085", "3094", "3033"),
    ("3031", "3046", "3085", "3094", "3033", "3036"),
)
# Yun Tal Wildarrows: zero DDragon crit, +0.25 from its ItemEffect. The only
# crit source in this file that does not pass through ``engine.py:217-218``.
YUN_TAL = "3032"

LEVEL = 16
TARGET = dict(
    target_armor=110.0,
    target_mr=52.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)

_NOTE_OVERFLOW = re.compile(r"overflow bonus AD \+([0-9.]+)")

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _ddragon_crit(item_id: str) -> float:
    """The item's crit off its DDragon stat block - the pre-clamp truth."""
    stats = _snap().items[item_id].get("stats") or {}
    return float(stats.get("FlatCritChanceMod", 0.0) or 0.0)


def _raw_crit_sum(build) -> float:
    """Unclamped DDragon crit for a build.

    Computed from the snapshot rather than from ``result.stats["crit"]``, which
    the engine has already clamped. This is what keeps every assertion below
    non-tautological: the input is measured independently of the output.
    """
    return sum(_ddragon_crit(i) for i in build)


def _sr_crit_pool() -> frozenset[str]:
    """Purchasable Summoner's Rift items carrying DDragon crit, at this patch."""
    pool = set()
    for item_id, item in _snap().items.items():
        if _ddragon_crit(item_id) <= 0.0:
            continue
        gold = item.get("gold") or {}
        if not gold.get("purchasable"):
            continue
        if not (item.get("maps") or {}).get("11"):
            continue
        pool.add(item_id)
    return frozenset(pool)


def _emitted_overflow_ad(build) -> float:
    """The overflow AD the engine actually credited, read off its own note.

    ``compute_dps`` folds the grant into three internal channels and reports the
    magnitude only in the R212 note (``dps.py:1197-1203``), so the note is the
    emitted artifact. Absent note means the seam credited nothing.
    """
    result = compute_dps(
        _snap(),
        champion_id=YASUO,
        level=LEVEL,
        item_ids=list(build),
        mode="SR",
        apply_crit_chance_overrides=True,
        **TARGET,
    )
    for note in result.notes:
        if "crit chance override" in note:
            found = _NOTE_OVERFLOW.search(note)
            return float(found.group(1)) if found else 0.0
    return 0.0


class SnapshotCritPoolTests(unittest.TestCase):
    """Every ladder id is a real, purchasable, crit-carrying SR item here."""

    def test_every_ladder_id_is_in_the_live_purchasable_crit_pool(self) -> None:
        pool = _sr_crit_pool()
        self.assertTrue(pool)
        for build in LADDER:
            for item_id in build:
                with self.subTest(item_id=item_id):
                    self.assertIn(item_id, pool)

    def test_the_ladder_straddles_the_hundred_percent_line(self) -> None:
        sums = [_raw_crit_sum(b) for b in LADDER]
        self.assertTrue(any(s < SATURATION_RAW_CRIT for s in sums))
        self.assertTrue(any(s > SATURATION_RAW_CRIT for s in sums))
        self.assertIn(SATURATION_RAW_CRIT, [round(s, 10) for s in sums])

    def test_yun_tal_carries_no_ddragon_crit(self) -> None:
        # Its 0.25 rides on the ItemEffect, which is why it can bypass the
        # engine-wide clamp the audit blamed.
        self.assertEqual(_ddragon_crit(YUN_TAL), 0.0)
        self.assertNotIn(YUN_TAL, _sr_crit_pool())


class SaturationTests(unittest.TestCase):
    def test_above_one_hundred_percent_the_term_is_exactly_fifty(self) -> None:
        above = [b for b in LADDER if _raw_crit_sum(b) > SATURATION_RAW_CRIT]
        self.assertGreaterEqual(len(above), 2)
        for build in above:
            with self.subTest(raw_crit=_raw_crit_sum(build)):
                self.assertAlmostEqual(
                    _emitted_overflow_ad(build), SATURATED_OVERFLOW_AD, places=6
                )

    def test_adding_more_crit_items_does_not_move_it(self) -> None:
        # The audit's headline observation, pinned as recorded behaviour: 1.25
        # and 1.50 raw crit buy exactly what 1.00 buys.
        saturated = sorted(
            (b for b in LADDER if _raw_crit_sum(b) >= SATURATION_RAW_CRIT),
            key=_raw_crit_sum,
        )
        emitted = {_emitted_overflow_ad(b) for b in saturated}
        self.assertEqual(emitted, {SATURATED_OVERFLOW_AD})
        self.assertGreater(_raw_crit_sum(saturated[-1]), _raw_crit_sum(saturated[0]))


class SaturationBoundaryTests(unittest.TestCase):
    """The assertion the existing R212 suite structurally cannot make."""

    def test_the_term_grows_strictly_below_the_boundary(self) -> None:
        # Restricted to raw crit above 0.50: below that the doubling does not
        # reach 100 percent at all and the term is a flat zero, which is a
        # different region and is pinned separately.
        rungs = sorted(
            (b for b in LADDER if 0.50 < _raw_crit_sum(b) <= SATURATION_RAW_CRIT),
            key=_raw_crit_sum,
        )
        self.assertGreaterEqual(len(rungs), 4)
        previous = 0.0
        for build in rungs:
            with self.subTest(raw_crit=_raw_crit_sum(build)):
                emitted = _emitted_overflow_ad(build)
                self.assertGreater(emitted, previous)
                previous = emitted

    def test_the_term_is_zero_at_or_below_fifty_percent_raw_crit(self) -> None:
        for build in LADDER:
            if _raw_crit_sum(build) > 0.50:
                continue
            with self.subTest(raw_crit=_raw_crit_sum(build)):
                self.assertEqual(_emitted_overflow_ad(build), 0.0)

    def test_the_boundary_sits_exactly_at_one_hundred_percent_raw_crit(self) -> None:
        """Last growing rung below, flat forever at and above - that is the cap.

        Located from the emitted values, so the constant at the top of this file
        is confirmed rather than assumed.
        """
        by_raw = sorted(LADDER, key=_raw_crit_sum)
        highest_below = max(
            (b for b in by_raw if _raw_crit_sum(b) < SATURATION_RAW_CRIT),
            key=_raw_crit_sum,
        )
        at_and_above = [b for b in by_raw if _raw_crit_sum(b) >= SATURATION_RAW_CRIT]
        self.assertLess(
            _emitted_overflow_ad(highest_below), SATURATED_OVERFLOW_AD
        )
        for build in at_and_above:
            with self.subTest(raw_crit=_raw_crit_sum(build)):
                self.assertEqual(
                    _emitted_overflow_ad(build), SATURATED_OVERFLOW_AD
                )

    def test_effect_sourced_crit_still_saturates_at_fifty(self) -> None:
        """The refutation of the filed root cause, run against the engine.

        ``engine.py:217-218`` clamps only when the DDragon sum EXCEEDS 1.0. On
        this build it is exactly 1.00, so that clamp never fires - and Yun Tal's
        +0.25 rides on an ItemEffect the engine stat pass never sees. The extra
        crit is still discarded and the term is still +50.0, which can only be
        ``dps.py:1148``.
        """
        base = ("3031", "3046", "3085", "3094")
        self.assertAlmostEqual(_raw_crit_sum(base), SATURATION_RAW_CRIT, places=12)
        self.assertAlmostEqual(
            _raw_crit_sum(base + (YUN_TAL,)), SATURATION_RAW_CRIT, places=12
        )
        self.assertAlmostEqual(
            _emitted_overflow_ad(base + (YUN_TAL,)),
            SATURATED_OVERFLOW_AD,
            places=6,
        )

    def test_effect_sourced_crit_does_reach_the_term_below_the_boundary(self) -> None:
        # Control for the test above: the effect crit is genuinely plumbed into
        # the overflow input, so its disappearance at the cap is the clamp and
        # not an unwired channel.
        base = ("3031", "3046", "3085")
        self.assertAlmostEqual(_raw_crit_sum(base), 0.75, places=12)
        self.assertGreater(
            _emitted_overflow_ad(base + (YUN_TAL,)), _emitted_overflow_ad(base)
        )


class RegistryHelperTests(unittest.TestCase):
    def test_registry_helper_is_not_saturated(self) -> None:
        """The divergence is a clamp-POSITION question, not a registry bug.

        Handed 1.50 in isolation the helper returns 100.0, exactly linear. Any
        future re-derivation that concludes Riot caps AFTER the doubling changes
        ``dps.py``, not ``_crit_chance_overrides.py``.
        """
        entry = crit_chance_entry(YASUO)
        self.assertIsNotNone(entry)
        self.assertAlmostEqual(overflow_bonus_ad(entry, 1.50), 100.0, places=12)
        self.assertAlmostEqual(overflow_bonus_ad(entry, 1.00), 50.0, places=12)

    def test_the_engine_and_the_helper_disagree_above_the_cap(self) -> None:
        # Stated as an assertion so the gap is a recorded fact with a number on
        # it, not a paragraph someone has to take on trust.
        entry = crit_chance_entry(YASUO)
        build = ("3031", "3046", "3085", "3094", "3033", "3036")
        raw = _raw_crit_sum(build)
        self.assertAlmostEqual(raw, 1.50, places=12)
        self.assertAlmostEqual(overflow_bonus_ad(entry, raw), 100.0, places=12)
        self.assertAlmostEqual(
            _emitted_overflow_ad(build), SATURATED_OVERFLOW_AD, places=6
        )


if __name__ == "__main__":
    unittest.main()
