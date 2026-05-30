"""dps_sweep - 1-variable DPS stat-sweep (competitor lift #3).

Engine-layer loop over the EXISTING DS auto-attack DPS engine
(agents.daemon_slayer.dps.compute_dps) with ONE input swept and everything
else held fixed. NO new compute / NO ENGINE math change. Spec:
docs/COMPETITOR_LIFT_2026-05-30.md "Lift 3".

Grounding (live snapshot at write time, Caitlyn marksman with a crit core):
  * target_armor axis: DPS is monotonic NON-increasing as armor rises
    (more armor = same-or-less PHYSICAL DPS). 0 armor >> 300 armor.
  * level axis: agrees with compute_dps_curve point-for-point (same engine,
    same build, same fixed target resists).
  * unknown champion: fail-soft to an EMPTY SweepResult (no raise).

Test surface:
* ContractTests       - dataclass shapes (frozen, field names, to_dict).
* ArmorAxisTests      - monotonic non-increasing armor curve for a marksman.
* MrAxisTests         - mr axis builds points + is non-increasing.
* LevelAxisTests      - delegates to compute_dps_curve (matches it exactly).
* AxisValidationTests - unknown axis raises ValueError; range defaults.
* FailSoftTests       - unknown champion -> empty; level-axis unknown -> empty.
* AsciiHygieneTest    - module + this test file are pure 7-bit ASCII.
"""

from __future__ import annotations

import dataclasses
import pathlib
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DPS_CURVE_LEVELS, compute_dps_curve
from agents.daemon_slayer.dps_sweep import (
    AXIS_LEVEL,
    AXIS_TARGET_ARMOR,
    AXIS_TARGET_MR,
    DEFAULT_SWEEP_LEVEL,
    SWEEP_AXES,
    SweepPoint,
    SweepResult,
    compute_dps_sweep,
)

# Marksman with a physical-AA crit core. Caitlyn is in every modern snapshot
# and her DPS is dominated by physical autos so the armor curve is steeply
# monotonic - the cleanest grounding subject.
_CHAMP = "Caitlyn"
_CRIT_BUILD = ("3094", "3031", "3036", "3072", "3046")


def _snapshot() -> DataSnapshot:
    return DataSnapshot.load()


class ContractTests(unittest.TestCase):
    def test_point_is_frozen(self) -> None:
        p = SweepPoint(x=0.0, weighted_dps=100.0, phase="mid")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.weighted_dps = 5.0  # type: ignore[misc]

    def test_point_field_names(self) -> None:
        names = {f.name for f in dataclasses.fields(SweepPoint)}
        self.assertEqual(names, {"x", "weighted_dps", "phase"})

    def test_result_field_names(self) -> None:
        names = {f.name for f in dataclasses.fields(SweepResult)}
        self.assertEqual(
            names, {"champion_id", "axis", "level", "points"}
        )

    def test_result_default_empty(self) -> None:
        r = SweepResult(champion_id="X", axis=AXIS_TARGET_ARMOR, level=11)
        self.assertEqual(r.points, ())
        self.assertTrue(r.empty)

    def test_point_to_dict(self) -> None:
        d = SweepPoint(x=25.0, weighted_dps=180.5, phase="mid").to_dict()
        self.assertEqual(d, {"x": 25.0, "weighted_dps": 180.5, "phase": "mid"})

    def test_axes_constant(self) -> None:
        self.assertEqual(
            SWEEP_AXES,
            (AXIS_TARGET_ARMOR, AXIS_TARGET_MR, AXIS_LEVEL),
        )


class ArmorAxisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snapshot()
        cls.res = compute_dps_sweep(
            cls.snap, _CHAMP, item_ids=_CRIT_BUILD,
            mode="SR", axis=AXIS_TARGET_ARMOR,
            axis_values=[0, 50, 100, 150, 200, 250, 300],
            level=11,
        )

    def test_points_resolved(self) -> None:
        self.assertFalse(self.res.empty)
        self.assertEqual(len(self.res.points), 7)
        self.assertEqual(self.res.axis, AXIS_TARGET_ARMOR)

    def test_x_values_match_axis(self) -> None:
        xs = [p.x for p in self.res.points]
        self.assertEqual(xs, [0, 50, 100, 150, 200, 250, 300])

    def test_monotonic_non_increasing_in_armor(self) -> None:
        dps = [p.weighted_dps for p in self.res.points]
        for i in range(1, len(dps)):
            self.assertLessEqual(
                dps[i], dps[i - 1] + 1e-6,
                f"DPS rose as armor increased at index {i}: {dps}",
            )

    def test_more_armor_strictly_less_dps_at_extremes(self) -> None:
        # 0 armor should give meaningfully more physical DPS than 300 armor
        # for a marksman; pin the direction (not the magnitude).
        dps = [p.weighted_dps for p in self.res.points]
        self.assertGreater(dps[0], dps[-1])

    def test_default_axis_values_span_0_to_300(self) -> None:
        res = compute_dps_sweep(
            self.snap, _CHAMP, item_ids=_CRIT_BUILD,
            mode="SR", axis=AXIS_TARGET_ARMOR, level=11,
        )
        xs = [p.x for p in res.points]
        self.assertEqual(xs[0], 0.0)
        self.assertEqual(xs[-1], 300.0)

    def test_level_recorded_on_result(self) -> None:
        self.assertEqual(self.res.level, 11)


class MrAxisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snapshot()
        cls.res = compute_dps_sweep(
            cls.snap, _CHAMP, item_ids=_CRIT_BUILD,
            mode="SR", axis=AXIS_TARGET_MR,
            axis_values=[0, 75, 150, 225, 300],
            level=11,
        )

    def test_points_resolved(self) -> None:
        self.assertFalse(self.res.empty)
        self.assertEqual(len(self.res.points), 5)
        self.assertEqual(self.res.axis, AXIS_TARGET_MR)

    def test_non_increasing_in_mr(self) -> None:
        # MR never RAISES DPS. A pure-physical auto-attacker is flat; any
        # magic component (procs / hybrid) only falls. Pin non-increasing.
        dps = [p.weighted_dps for p in self.res.points]
        for i in range(1, len(dps)):
            self.assertLessEqual(dps[i], dps[i - 1] + 1e-6)


class LevelAxisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snapshot()

    def test_level_axis_matches_compute_dps_curve(self) -> None:
        # The level axis must agree with the existing level-swept curve
        # point-for-point (same engine, build, fixed target resists).
        levels = [1, 6, 11, 16, 18]
        sweep = compute_dps_sweep(
            self.snap, _CHAMP, item_ids=_CRIT_BUILD,
            mode="SR", axis=AXIS_LEVEL, axis_values=levels,
            target_armor=0.0, target_mr=0.0,
        )
        curve = compute_dps_curve(
            self.snap, _CHAMP, item_ids=_CRIT_BUILD, mode="SR",
            target_armor=0.0, target_mr=0.0, levels=levels,
        )
        self.assertEqual(len(sweep.points), len(curve))
        for sp, cp in zip(sweep.points, curve):
            self.assertEqual(sp.x, float(cp.level))
            self.assertAlmostEqual(sp.weighted_dps, cp.weighted_dps, places=6)
            self.assertEqual(sp.phase, cp.phase)

    def test_level_axis_default_uses_curve_levels(self) -> None:
        sweep = compute_dps_sweep(
            self.snap, _CHAMP, item_ids=_CRIT_BUILD,
            mode="SR", axis=AXIS_LEVEL,
        )
        xs = [int(p.x) for p in sweep.points]
        self.assertEqual(tuple(xs), DPS_CURVE_LEVELS)

    def test_level_axis_dps_rises_with_level(self) -> None:
        # Sanity: a carry's DPS grows from level 1 to 18 (the level curve is
        # monotonic-increasing for a scaling marksman).
        sweep = compute_dps_sweep(
            self.snap, _CHAMP, item_ids=_CRIT_BUILD,
            mode="SR", axis=AXIS_LEVEL, axis_values=[1, 18],
        )
        self.assertGreater(
            sweep.points[-1].weighted_dps, sweep.points[0].weighted_dps
        )


class AxisValidationTests(unittest.TestCase):
    def test_unknown_axis_raises(self) -> None:
        snap = _snapshot()
        with self.assertRaises(ValueError):
            compute_dps_sweep(
                snap, _CHAMP, item_ids=_CRIT_BUILD, axis="bogus",
            )

    def test_default_axis_is_target_armor(self) -> None:
        snap = _snapshot()
        res = compute_dps_sweep(snap, _CHAMP, item_ids=_CRIT_BUILD)
        self.assertEqual(res.axis, AXIS_TARGET_ARMOR)

    def test_default_level_constant(self) -> None:
        self.assertEqual(DEFAULT_SWEEP_LEVEL, 11)


class FailSoftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snapshot()

    def test_unknown_champion_resist_axis_empty(self) -> None:
        res = compute_dps_sweep(
            self.snap, "NotAChampionXYZ", item_ids=_CRIT_BUILD,
            axis=AXIS_TARGET_ARMOR, axis_values=[0, 100, 200],
        )
        self.assertTrue(res.empty)
        self.assertEqual(res.points, ())

    def test_unknown_champion_level_axis_empty(self) -> None:
        res = compute_dps_sweep(
            self.snap, "NotAChampionXYZ", item_ids=_CRIT_BUILD,
            axis=AXIS_LEVEL, axis_values=[1, 18],
        )
        self.assertTrue(res.empty)

    def test_result_to_dict_shape(self) -> None:
        res = compute_dps_sweep(
            self.snap, _CHAMP, item_ids=_CRIT_BUILD,
            axis=AXIS_TARGET_ARMOR, axis_values=[0, 100],
        )
        d = res.to_dict()
        self.assertEqual(d["champion_id"], _CHAMP)
        self.assertEqual(d["axis"], AXIS_TARGET_ARMOR)
        self.assertEqual(len(d["points"]), 2)
        self.assertEqual(set(d["points"][0]), {"x", "weighted_dps", "phase"})


class AsciiHygieneTest(unittest.TestCase):
    def _assert_ascii(self, path: pathlib.Path) -> None:
        src = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII in {path.name}: {bad[:5]}")

    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer.dps_sweep as mod
        self._assert_ascii(pathlib.Path(mod.__file__))

    def test_this_test_file_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(__file__))


if __name__ == "__main__":
    unittest.main()
