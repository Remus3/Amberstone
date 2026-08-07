"""RM-158 residual: the levelling curve must be PER MODE, not one SR curve.

DEFECT (pre-fix): ``core.lead_projection.minutes_for_level(level)`` took no
``mode`` argument and every consumer - the live ``project_lead`` level axis and
the offline laning-scenario ``economy`` block - rode a single
``level = 1.0 + 0.5 * minutes`` curve for SR, ARAM and ARENA alike. Same shape
of defect as the RM-158 gold-income row: a mode-blind input that silently
produces a plausible number, so a per-mode artifact that is really the SR
artifact is indistinguishable from one that is right.

EVIDENCE (measured, ``data/rewind_history.db`` timeline_frames, 2026-08-06):
  * start level at timestamp 0: SR 1 (n=6710, min=max=1), ARAM 1 (n=20804,
    min=max=1), ARENA 3 (n=2702, min=max=3, zero variance).
  * mean level at minute 10: SR 7.04 (sd 1.04, n=6540), ARAM 11.20 (sd 0.68,
    n=19754), ARENA 11.35 (sd 0.69, n=2702). The three modes are ~4 levels
    apart on the same clock; that is far outside the dispersion.
  * weighted slope-through-origin on the midpoint-corrected first-reach minute
    for levels 2/6/11/16, fitted against each mode's own measured base level:
    SR 0.558, ARAM 1.015, ARENA 0.788 levels/min.

The shipped rows are DERIVED from those measurements, not copied from them:
SR is pinned at its existing operator-tuned 0.5 (an unchanged live path), and
ARAM / ARENA carry the measured RATIO to SR. See ``_LEVEL_CURVE`` in
core/lead_projection.py for the full provenance note.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.laning_scenario_precompute as lsp  # noqa: E402
from core import lead_projection as lp  # noqa: E402


class LevelCurveRegistrationTests(unittest.TestCase):
    """Every shipped mode owns a curve; an unshipped one is NOT registered."""

    def test_every_generator_mode_has_a_registered_level_curve(self) -> None:
        for key in lsp._MODE_KEYS:
            ds_mode = lsp._DS_MODE_BY_KEY[key]
            with self.subTest(mode=key):
                self.assertTrue(
                    lp.level_curve_is_registered(ds_mode),
                    f"generator mode {key!r} ({ds_mode}) has no level curve, so "
                    f"its economy block silently rides the SR curve",
                )

    def test_unshipped_mode_is_not_registered(self) -> None:
        self.assertFalse(lp.level_curve_is_registered("URF"))
        self.assertFalse(lp.level_curve_is_registered("NEXUSBLITZ"))

    def test_falsy_mode_resolves_to_the_sr_default_and_is_registered(self) -> None:
        # Documented contract, identical to gold_income_is_registered: a FALSY
        # mode is "unspecified", which means SR, not "unknown". Only a non-empty
        # mode with no row of its own is unregistered. Pinned so the predicate
        # cannot drift into reporting a plain SR read as a fall-through.
        for falsy in ("", None):
            with self.subTest(mode=falsy):
                self.assertTrue(lp.level_curve_is_registered(falsy))
                self.assertTrue(lp.gold_income_is_registered(falsy))

    def test_registration_is_case_insensitive(self) -> None:
        self.assertTrue(lp.level_curve_is_registered("aram"))
        self.assertTrue(lp.level_curve_is_registered("Arena"))


class SrCurveUnchangedTests(unittest.TestCase):
    """SR is a LIVE path. Any movement here is a regression, not a fix."""

    def test_sr_band_minutes_are_the_shipped_values(self) -> None:
        for level, minutes in ((2, 2.0), (6, 10.0), (11, 20.0), (16, 30.0)):
            with self.subTest(level=level):
                self.assertAlmostEqual(lp.minutes_for_level(level, "SR"), minutes)

    def test_default_mode_is_still_sr(self) -> None:
        for level in (1, 2, 6, 11, 16, 18):
            with self.subTest(level=level):
                self.assertAlmostEqual(
                    lp.minutes_for_level(level), lp.minutes_for_level(level, "SR")
                )

    def test_sr_curve_row_is_the_module_benchmark_constants(self) -> None:
        base, rate = lp.level_curve("SR")
        self.assertEqual(base, lp._LEVEL_BASE)
        self.assertEqual(rate, lp._LEVEL_PER_MIN_BENCHMARK)

    def test_sr_level_benchmark_is_unchanged(self) -> None:
        for minutes in (0.0, 5.0, 10.0, 20.0, 30.0):
            with self.subTest(minutes=minutes):
                self.assertAlmostEqual(
                    lp.level_benchmark(minutes, "SR"), 1.0 + 0.5 * minutes
                )


class PerModeCurveTests(unittest.TestCase):
    """Each mode resolves its OWN curve - the whole point of the fix."""

    def test_band_minutes_are_pairwise_distinct_across_modes(self) -> None:
        for level in (6, 11, 16):
            vals = [lp.minutes_for_level(level, m) for m in ("SR", "ARAM", "ARENA")]
            with self.subTest(level=level):
                self.assertEqual(
                    len(set(vals)), 3, f"modes share a minute at level {level}: {vals}"
                )

    def test_aram_and_arena_reach_every_band_sooner_than_sr(self) -> None:
        for level in (6, 11, 16):
            for mode in ("ARAM", "ARENA"):
                with self.subTest(level=level, mode=mode):
                    self.assertLess(
                        lp.minutes_for_level(level, mode),
                        lp.minutes_for_level(level, "SR"),
                    )

    def test_arena_starts_at_level_three(self) -> None:
        # MEASURED: every ARENA timeline frame at timestamp 0 reads level 3
        # (n=2702, min=max=3). Levels 2 and 3 cost zero elapsed minutes there,
        # while the SR curve charges 2.0 and 4.0 minutes for them.
        base, _rate = lp.level_curve("ARENA")
        self.assertEqual(base, 3.0)
        self.assertEqual(lp.minutes_for_level(2, "ARENA"), 0.0)
        self.assertEqual(lp.minutes_for_level(3, "ARENA"), 0.0)
        self.assertGreater(lp.minutes_for_level(2, "SR"), 0.0)

    def test_level_benchmark_differs_by_mode_at_the_same_minute(self) -> None:
        # Taken at minute 10 deliberately. Later minutes are NOT usable: ARAM
        # hits the level-18 clamp at 16.83 and ARENA at 18.99, so by minute 20
        # both read exactly 18.0 and a distinctness assertion there would fail
        # on the clamp rather than on any fall-through.
        vals = [lp.level_benchmark(10.0, m) for m in ("SR", "ARAM", "ARENA")]
        self.assertEqual(len(set(vals)), 3, vals)
        for minutes in (5.0, 10.0, 20.0, 30.0):
            # MEASURED mean level at minute 10: SR 7.04, ARAM 11.20, ARENA 11.35.
            # Both no-lane modes out-level SR at every minute past spawn.
            with self.subTest(minutes=minutes):
                sr = lp.level_benchmark(minutes, "SR")
                self.assertGreater(lp.level_benchmark(minutes, "ARAM"), sr)
                self.assertGreater(lp.level_benchmark(minutes, "ARENA"), sr)

    def test_every_registered_rate_is_positive_and_finite(self) -> None:
        for mode in lp.level_curve_modes():
            base, rate = lp.level_curve(mode)
            with self.subTest(mode=mode):
                self.assertGreater(rate, 0.0)
                self.assertLess(rate, 10.0)
                self.assertGreaterEqual(base, 1.0)
                self.assertLessEqual(base, 18.0)

    def test_minutes_for_level_is_strictly_increasing_per_mode(self) -> None:
        for mode in lp.level_curve_modes():
            seq = [lp.minutes_for_level(lvl, mode) for lvl in (6, 11, 16)]
            with self.subTest(mode=mode):
                self.assertEqual(seq, sorted(seq))
                self.assertEqual(len(set(seq)), len(seq))

    def test_floors_at_zero_below_the_mode_base(self) -> None:
        for mode in lp.level_curve_modes():
            with self.subTest(mode=mode):
                self.assertEqual(lp.minutes_for_level(0, mode), 0.0)
                self.assertEqual(lp.minutes_for_level(1, mode), 0.0)


class LiveReadFailSoftTests(unittest.TestCase):
    """A LIVE read of an unknown mode still fail-softs to SR.

    Mirrors ``gold_income_per_min`` exactly: fail-soft is right for a live read
    (a coach line beats an exception) and WRONG for an offline per-mode artifact
    generator, which is why the refusal lives at the generator gate below and
    not in these accessors.
    """

    def test_unknown_mode_minutes_fall_back_to_sr(self) -> None:
        self.assertEqual(lp.minutes_for_level(11, "URF"), lp.minutes_for_level(11, "SR"))

    def test_none_mode_falls_back_to_sr(self) -> None:
        self.assertEqual(lp.minutes_for_level(11, None), lp.minutes_for_level(11, "SR"))

    def test_unknown_mode_benchmark_falls_back_to_sr(self) -> None:
        self.assertEqual(lp.level_benchmark(10.0, "URF"), lp.level_benchmark(10.0, "SR"))

    def test_level_curve_of_unknown_mode_is_the_sr_row(self) -> None:
        self.assertEqual(lp.level_curve("URF"), lp.level_curve("SR"))

    def test_zero_rate_curve_returns_zero_minutes(self) -> None:
        with mock.patch.dict(lp._LEVEL_CURVE, {"SR": (1.0, 0.0)}):
            self.assertEqual(lp.minutes_for_level(11, "SR"), 0.0)


class LiveProjectLeadAxisTests(unittest.TestCase):
    """The SECOND live consumer. Every test here must DIE if project_lead's
    ``level_bench`` reverts to the mode-blind ``_LEVEL_BASE +
    _LEVEL_PER_MIN_BENCHMARK * minutes`` - verified by hand-reverting it.

    The registry tests above do not cover this: they exercise the accessors and
    the offline generator, and the whole repo stayed green with the live axis
    reverted. Fixtures neutralise every OTHER axis so the level axis alone
    decides the verdict - gold is set to exactly its benchmark
    (``_GOLD_PER_MIN_BENCHMARK`` 350/min) and ``kda`` is omitted, which
    ``_kda_ratio`` fail-softs to a neutral 0.0.
    """

    def _state(self, minutes: float, level: float, **extra) -> dict:
        state = {
            "game_time_s": minutes * 60.0,
            "level": level,
            "gold": 350.0 * minutes,
        }
        state.update(extra)
        return state

    def test_aram_average_player_reads_even_not_ahead(self) -> None:
        # MEASURED ARAM mean level at minute 10 is 11.20. On the per-mode bench
        # (1 + 1.01*10 = 11.1) a level-11 ARAM player is doing exactly as
        # expected. On the SR bench (6.0) they read +83% and are coached as
        # AHEAD - a permanent, mode-wide false positive at weight 0.30.
        verdict = lp.project_lead(self._state(10.0, 11), mode="ARAM")
        self.assertEqual(verdict["state"], "even")

    def test_arena_average_player_reads_even_not_ahead(self) -> None:
        # Same shape: measured ARENA mean at minute 10 is 11.35, bench is
        # 3 + 0.79*10 = 10.9.
        verdict = lp.project_lead(self._state(10.0, 11), mode="ARENA")
        self.assertEqual(verdict["state"], "even")

    def test_sr_verdict_at_the_same_fixture_is_unchanged(self) -> None:
        # CHARACTERIZATION, pinned to pre-fix behaviour. SR rides the identical
        # arithmetic before and after, so this must not move. cs is supplied at
        # its benchmark (8/min) because SR weights cs at 0.40 and a missing cs
        # would swamp the level axis.
        verdict = lp.project_lead(
            self._state(10.0, 11, cs=80.0), mode="SR"
        )
        self.assertEqual(verdict["state"], "ahead")
        self.assertEqual(verdict["magnitude"], "clear")

    def test_the_same_state_reads_differently_per_mode(self) -> None:
        # The single most direct statement of the defect: one game_state, three
        # modes, three level benchmarks. Mode-blind, ARAM and ARENA returned
        # SR's verdict here.
        state = self._state(10.0, 11)
        sr = lp.project_lead(state, mode="SR")
        self.assertNotEqual(sr["state"], lp.project_lead(state, mode="ARAM")["state"])
        self.assertNotEqual(sr["state"], lp.project_lead(state, mode="ARENA")["state"])

    def test_missing_level_defaults_to_the_modes_spawn_level(self) -> None:
        # An ARENA game_state with no ``level`` must default to 3.0, not SR's
        # 1.0. Gold is placed so the two candidate defaults land on opposite
        # sides of the even/behind boundary, otherwise the flat default hides.
        no_level = {"game_time_s": 600.0, "gold": 6037.5}
        at_spawn = dict(no_level, level=3)
        at_sr_spawn = dict(no_level, level=1)
        absent = lp.project_lead(no_level, mode="ARENA")
        self.assertEqual(
            absent, lp.project_lead(at_spawn, mode="ARENA"),
            "a missing level must read as the ARENA spawn level (3)",
        )
        self.assertNotEqual(
            absent, lp.project_lead(at_sr_spawn, mode="ARENA"),
            "a missing level is defaulting to SR's spawn level (1)",
        )


class MaxLevelClampTests(unittest.TestCase):
    """Level 18 is a hard game cap, so the benchmark must stop there.

    Uncapped, the bench crosses 18 at minute 34.00 for SR, 18.81 for ARAM and
    21.99 for ARENA, and MEASURED shares of games running past those crossings
    are 17.7% / 49.4% / 80.1%. Past the crossing the bench is unreachable and
    every player reads permanently behind on the level axis.
    """

    def test_benchmark_never_exceeds_max_level(self) -> None:
        for mode in lp.level_curve_modes():
            for minutes in (0.0, 20.0, 35.0, 60.0, 600.0):
                with self.subTest(mode=mode, minutes=minutes):
                    self.assertLessEqual(
                        lp.level_benchmark(minutes, mode), lp.MAX_CHAMPION_LEVEL
                    )

    def test_sr_is_bit_identical_below_its_crossing(self) -> None:
        # The clamp must not disturb SR anywhere it was already reachable.
        # SR reaches 18.0 at exactly minute 34.0.
        for minutes in (0.0, 1.0, 10.0, 20.0, 30.0, 33.9, 34.0):
            with self.subTest(minutes=minutes):
                self.assertAlmostEqual(
                    lp.level_benchmark(minutes, "SR"), 1.0 + 0.5 * minutes
                )

    def test_clamp_binds_past_each_crossing(self) -> None:
        for mode, past in (("SR", 40.0), ("ARAM", 25.0), ("ARENA", 25.0)):
            with self.subTest(mode=mode):
                self.assertEqual(
                    lp.level_benchmark(past, mode), lp.MAX_CHAMPION_LEVEL
                )

    def test_minutes_for_level_clamps_above_max(self) -> None:
        for mode in lp.level_curve_modes():
            with self.subTest(mode=mode):
                self.assertEqual(
                    lp.minutes_for_level(25, mode), lp.minutes_for_level(18, mode)
                )

    def test_maxed_aram_player_is_not_read_as_behind(self) -> None:
        # MEASURED: the ARAM mean level at minute 25 is exactly 18.000 - the cap
        # itself. Uncapped, the bench there is 26.25 and a MAXED player reads
        # behind. This is the assertion that dies if the clamp is removed.
        state = {"game_time_s": 1800.0, "level": 18, "gold": 350.0 * 30.0}
        self.assertEqual(lp.project_lead(state, mode="ARAM")["state"], "even")


class GeneratorRefusalTests(unittest.TestCase):
    """An unregistered curve must REFUSE the write, not fall through to SR."""

    def test_unregistered_curve_is_skipped_and_exits_nonzero(self) -> None:
        rows = {k: v for k, v in lp._LEVEL_CURVE.items() if k != "ARENA"}
        with mock.patch.object(lp, "_LEVEL_CURVE", rows):
            # Assert the mutation ACTUALLY applied before trusting the result -
            # a patch that silently no-ops would make this test vacuous.
            self.assertFalse(lp.level_curve_is_registered("ARENA"))
            self.assertTrue(lp.gold_income_is_registered("ARENA"))
            with tempfile.TemporaryDirectory() as tmp:
                rc = lsp.main([
                    "--mode", "arena",
                    "--champions", "Garen",
                    "--bands", "L2",
                    "--out", tmp,
                ])
                self.assertEqual(rc, 2)
                self.assertFalse(
                    (Path(tmp) / "laning_scenarios_arena.json").exists(),
                    "generator wrote an arena table whose level curve is the SR "
                    "curve - exactly the RM-158 failure it is supposed to refuse",
                )


class EconomyCellPerModeTests(unittest.TestCase):
    """The consumer actually moves - a curve nobody reads is not a fix."""

    def test_economy_cell_gold_differs_between_modes_at_the_same_band(self) -> None:
        for band in ("L6", "L11", "L16"):
            vals = [
                lsp.economy_cell(band, "ok", mode=m)["gold_at_band"]
                for m in ("SR", "ARAM", "ARENA")
            ]
            with self.subTest(band=band):
                self.assertEqual(len(set(vals)), 3, f"{band}: {vals}")

    def test_sr_economy_cells_are_unchanged(self) -> None:
        # Pinned to the pre-fix shipped values (minutes 2/10/20/30 x 450 g/min).
        for band, gold in (("L2", 900.0), ("L6", 4500.0), ("L11", 9000.0),
                           ("L16", 13500.0)):
            with self.subTest(band=band):
                self.assertAlmostEqual(
                    lsp.economy_cell(band, "ok", mode="SR")["gold_at_band"],
                    gold,
                    places=1,
                )

    def test_arena_l2_economy_is_the_spawn_state(self) -> None:
        cell = lsp.economy_cell("L2", "ok", mode="ARENA")
        self.assertEqual(cell["gold_at_band"], 0.0)


if __name__ == "__main__":
    unittest.main()
