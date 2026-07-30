"""ARAM Mayhem augment-reco cadence: bounded early-game fast vision poll.

Root cause (live-eyeballed 2026-07-12, offline-confirmed): the ARAM coach polls
vision every `_VISION_INTERVAL` = 25.0s (coaches/aram_coach.py:552) but the
Mayhem augment panel is on screen for only ~10-15s at game start. The single
early tick usually lands outside that window and the next is 25s later, by
which time the augment is already picked. Detection, the `is_augment_select` ->
`augment_select` alias, `augment_choices`, `read_tiered` and the
`_fetch_game_data` vision gate are all PROVEN GOOD - the blocker is CADENCE.

These tests pin the SCHEDULE, not a constant. A test that asserted
`_FAST_VISION_INTERVAL == 6.0` would be worthless: the bug is that no scan
lands inside a brief window, which is a property of the emitted scan
TIMESTAMPS. So `_simulate_scans` below replays the real vision-loop gate
(`coaches/_base_coach.py:462` `if forced or now - self._last_vision >=
self._VISION_INTERVAL`) at the real loop granularity
(`coaches/_base_coach.py:491` `await asyncio.sleep(3.0)`) and asserts over the
resulting timestamps.

The regression that would actually cost money is the short interval LEAKING
past the augment window, so that is pinned explicitly
(`test_fast_cadence_does_not_leak_past_the_window`), as is the zero-extra-cost
guarantee on plain non-Mayhem ARAM, which has no augments at all.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import aram_coach  # noqa: E402

# coaches/_base_coach.py:491 - the vision loop's per-iteration sleep. The gate
# can therefore only ever fire on a multiple of this, which is what makes the
# achievable inter-scan gap (not the nominal interval) the thing under test.
_LOOP_SLEEP_S = 3.0

# The PROVEN augment window: panel up ~10-15s at game start with the game clock
# frozen near 0:05. 12.0s is the mid estimate used as the coverage target.
_AUGMENT_WINDOW_LEN_S = 12.0
_CLOCK_FROZEN_AT_S = 5.0
_CLOCK_UNFREEZES_AT_WALL_S = 15.0


def _make_coach() -> aram_coach.Coach:
    """Build a Coach without BaseCoach.__init__ (no loops / SDK / AppLoop).

    Mirrors tests/test_aram_state_debounce.py::_make_coach. `_init_extra` is
    the real hook the live lifecycle calls at coaches/_base_coach.py:312, so
    calling it here is what seeds the fast-poll counters.
    """
    c = aram_coach.Coach.__new__(aram_coach.Coach)
    c._MODE_NAME = "aram"
    c._overlay = {}
    c._vision_state = {}
    c._last_state = {}
    c._init_extra()
    return c


def _frozen_then_running(wall: float) -> float:
    """gameTime as the live client reports it during augment select.

    The clock is FROZEN near 0:05 for the whole panel, then runs. This is why
    `game_seconds` is a usable window signal at all.
    """
    if wall < _CLOCK_UNFREEZES_AT_WALL_S:
        return _CLOCK_FROZEN_AT_S
    return _CLOCK_FROZEN_AT_S + (wall - _CLOCK_UNFREEZES_AT_WALL_S)


def _simulate_scans(
    coach: aram_coach.Coach,
    *,
    wall_end: float,
    game_mode: str = "KIWI",
    game_seconds_at=_frozen_then_running,
    resolve_at: "float | None" = None,
) -> list:
    """Replay the real loops and return the wall times a vision scan fires.

    Reproduces exactly three live behaviours:
      - `_last_vision` starts at 0.0 while `now` is a real epoch
        (coaches/_base_coach.py:306), so the first tick always scans.
      - the poll loop runs every ~1.5s, i.e. at least once between two 3.0s
        vision ticks, so the cadence setter has always run before the gate.
      - the fast-scan counter is bumped inside `_run_vision`, i.e. only when a
        scan actually runs, never on a skipped tick.
    """
    now = 1_000_000.0
    t0 = now
    last_vision = 0.0
    scans: list = []
    while now - t0 <= wall_end:
        wall = now - t0
        coach._update_vision_cadence(
            {"game_mode": game_mode, "game_seconds": game_seconds_at(wall)}
        )
        if now - last_vision >= coach._VISION_INTERVAL:
            last_vision = now
            scans.append(wall)
            if coach._fast_mode:
                coach._augment_fast_scans += 1
            if resolve_at is not None and wall >= resolve_at:
                coach._augment_resolved = True
        now += _LOOP_SLEEP_S
    return scans


def _gaps(scans: list) -> list:
    return [b - a for a, b in zip(scans, scans[1:])]


def _covers_every_window(scans: list, *, search_end: float, window: float) -> bool:
    """True if EVERY window of `window` seconds starting in [0, search_end]
    contains at least one scan. Probed on a fine grid so the answer does not
    depend on a lucky alignment."""
    step = 0.25
    starts = [i * step for i in range(int(search_end / step) + 1)]
    for w in starts:
        if not any(w <= s <= w + window for s in scans):
            return False
    return True


class SelectIntervalUnitTests(unittest.TestCase):
    """Direct coverage of the pure interval selector (no I/O, no Sonnet)."""

    def setUp(self) -> None:
        self.c = _make_coach()

    def _sel(self, gs, resolved=False, fast_scans=0, mode="KIWI"):
        return self.c._select_vision_interval(
            {"game_mode": mode, "game_seconds": gs},
            augment_resolved=resolved,
            fast_scans=fast_scans,
        )

    def test_inside_window_selects_fast(self) -> None:
        self.assertEqual(self._sel(5.0), aram_coach.Coach._FAST_VISION_INTERVAL)
        self.assertEqual(self._sel(30.0), aram_coach.Coach._FAST_VISION_INTERVAL)

    def test_at_and_past_ceiling_selects_default(self) -> None:
        ceiling = aram_coach.Coach._AUGMENT_WINDOW_S
        self.assertEqual(self._sel(ceiling), aram_coach.Coach._VISION_INTERVAL)
        self.assertEqual(self._sel(ceiling + 15.0), aram_coach.Coach._VISION_INTERVAL)

    def test_latch_set_selects_default_even_inside_window(self) -> None:
        self.assertEqual(self._sel(5.0, resolved=True), aram_coach.Coach._VISION_INTERVAL)

    def test_cap_hit_selects_default_even_inside_window(self) -> None:
        cap = aram_coach.Coach._AUGMENT_FAST_MAX_SCANS
        self.assertEqual(self._sel(5.0, fast_scans=cap), aram_coach.Coach._VISION_INTERVAL)

    def test_non_mayhem_never_fast(self) -> None:
        # Plain ARAM has no augments, so it must never pay a fast scan.
        self.assertEqual(self._sel(5.0, mode="ARAM"), aram_coach.Coach._VISION_INTERVAL)

    def test_missing_or_junk_game_seconds_selects_default(self) -> None:
        for bad in (None, "", "abc", object()):
            self.assertEqual(self._sel(bad), aram_coach.Coach._VISION_INTERVAL)

    def test_selector_does_not_read_the_mutated_instance_attr(self) -> None:
        # The setter mutates self._VISION_INTERVAL; if the selector read the
        # instance attr for its default it would latch fast forever.
        self.c._VISION_INTERVAL = aram_coach.Coach._FAST_VISION_INTERVAL
        self.assertEqual(self._sel(600.0), aram_coach.Coach._VISION_INTERVAL)


class ScheduleCoverageTests(unittest.TestCase):
    """The bug itself: does a scan land inside the brief augment window."""

    def test_every_augment_window_start_gets_a_scan(self) -> None:
        scans = _simulate_scans(_make_coach(), wall_end=40.0)
        self.assertTrue(
            _covers_every_window(
                scans,
                search_end=_CLOCK_UNFREEZES_AT_WALL_S,
                window=_AUGMENT_WINDOW_LEN_S,
            ),
            f"a {_AUGMENT_WINDOW_LEN_S}s augment window can still be missed: {scans}",
        )

    def test_the_coverage_assertion_is_not_vacuous(self) -> None:
        # Same property against the unpatched 25s cadence (modelled here as
        # plain non-Mayhem ARAM, which never fast-polls) MUST fail. Without
        # this, test_every_augment_window_start_gets_a_scan could pass for
        # reasons unrelated to the fix.
        scans = _simulate_scans(_make_coach(), wall_end=40.0, game_mode="ARAM")
        self.assertFalse(
            _covers_every_window(
                scans,
                search_end=_CLOCK_UNFREEZES_AT_WALL_S,
                window=_AUGMENT_WINDOW_LEN_S,
            ),
            f"the 25s baseline unexpectedly covers every window: {scans}",
        )

    def test_achievable_gap_inside_window_is_at_most_the_fast_interval(self) -> None:
        scans = _simulate_scans(_make_coach(), wall_end=30.0)
        in_window = [s for s in scans if s <= _CLOCK_UNFREEZES_AT_WALL_S]
        self.assertGreaterEqual(len(in_window), 2)
        for gap in _gaps(in_window):
            self.assertLessEqual(gap, aram_coach.Coach._FAST_VISION_INTERVAL + _LOOP_SLEEP_S)


class FastCadenceBoundedTests(unittest.TestCase):
    """The regression that costs money: the fast interval must not persist."""

    def test_fast_cadence_does_not_leak_past_the_window(self) -> None:
        c = _make_coach()
        # Worst case: a Mayhem game where the augment is NEVER detected, so the
        # latch never sets and only the window ceiling + cap can stop the fast
        # poll. Ten minutes of wall time.
        scans = _simulate_scans(c, wall_end=600.0)
        cap = aram_coach.Coach._AUGMENT_FAST_MAX_SCANS
        default = aram_coach.Coach._VISION_INTERVAL

        self.assertFalse(c._fast_mode, "still in fast mode 10 minutes into the game")
        self.assertLessEqual(c._augment_fast_scans, cap)

        # Every scan beyond the capped fast burst must be a full default
        # interval apart - this is the leak assertion.
        tail = scans[cap:]
        self.assertGreater(len(tail), 5, "simulation too short to prove the tail")
        for gap in _gaps(tail):
            self.assertGreaterEqual(gap, default)

    def test_total_scans_stay_within_baseline_plus_the_cap(self) -> None:
        fast = _simulate_scans(_make_coach(), wall_end=600.0)
        base = _simulate_scans(_make_coach(), wall_end=600.0, game_mode="ARAM")
        self.assertLessEqual(
            len(fast) - len(base), aram_coach.Coach._AUGMENT_FAST_MAX_SCANS
        )

    def test_non_mayhem_aram_pays_exactly_zero_extra_scans(self) -> None:
        c = _make_coach()
        base = _simulate_scans(c, wall_end=600.0, game_mode="ARAM")
        self.assertEqual(c._augment_fast_scans, 0)
        for gap in _gaps(base):
            self.assertGreaterEqual(gap, aram_coach.Coach._VISION_INTERVAL)

    def test_latch_reverts_cadence_on_the_tick_after_the_catch(self) -> None:
        c = _make_coach()
        scans = _simulate_scans(c, wall_end=200.0, resolve_at=7.0)
        self.assertTrue(c._augment_resolved)
        after = [s for s in scans if s > 7.0]
        self.assertGreater(len(after), 2)
        for gap in _gaps([s for s in scans if s >= 7.0]):
            self.assertGreaterEqual(gap, aram_coach.Coach._VISION_INTERVAL)

    def test_window_ceiling_is_a_small_slice_of_a_game(self) -> None:
        # The ceiling is the self-terminating fallback for a stuck-frozen
        # clock; if it ever grew past a minute the "bounded" claim dies.
        self.assertLessEqual(aram_coach.Coach._AUGMENT_WINDOW_S, 60.0)
        self.assertLess(
            aram_coach.Coach._FAST_VISION_INTERVAL, aram_coach.Coach._VISION_INTERVAL
        )


class LatchLifecycleTests(unittest.TestCase):
    """Per-game latch/counter reset (coaches/_base_coach.py:312 / :361)."""

    def test_init_extra_seeds_the_counters(self) -> None:
        c = _make_coach()
        self.assertFalse(c._augment_resolved)
        self.assertEqual(c._augment_fast_scans, 0)
        self.assertFalse(c._fast_mode)

    def test_reset_extra_clears_a_used_latch(self) -> None:
        c = _make_coach()
        c._augment_resolved = True
        c._augment_fast_scans = 4
        c._fast_mode = True
        c._VISION_INTERVAL = aram_coach.Coach._FAST_VISION_INTERVAL
        c._reset_extra()
        self.assertFalse(c._augment_resolved)
        self.assertEqual(c._augment_fast_scans, 0)
        self.assertFalse(c._fast_mode)
        self.assertEqual(c._VISION_INTERVAL, aram_coach.Coach._VISION_INTERVAL)


class RunVisionSurfaceTests(unittest.TestCase):
    """The Haiku/Sonnet surface must not widen: one read_tiered per scan."""

    def test_read_tiered_fires_once_and_latches_the_augment(self) -> None:
        from modes.shared_vision import GameVisionReader

        c = _make_coach()
        c._api_key = "sk-ant-test"
        c._out = Path(self._tmp.name) / "aram_coaching_data.json"
        c._out.write_text('{"mode": "aram"}', encoding="utf-8")

        calls = {"n": 0}

        def _fake_read_tiered(_self):
            calls["n"] += 1
            return {
                "augment_select": True,
                "augment_choices": ["A", "B", "C"],
                "timer": "0:05",
            }

        handled = {"n": 0}
        with (
            mock.patch.object(GameVisionReader, "read_tiered", _fake_read_tiered),
            mock.patch.object(
                aram_coach.Coach, "_fetch_game_data", lambda _self: {}
            ),
            mock.patch.object(
                aram_coach.Coach,
                "_handle_augment_select",
                lambda _self, _vs: handled.__setitem__("n", handled["n"] + 1),
            ),
        ):
            c._run_vision()

        self.assertEqual(calls["n"], 1, "read_tiered must fire exactly once")
        self.assertEqual(handled["n"], 1, "the existing augment reco must still fire")
        self.assertTrue(c._augment_resolved, "catching the augment must set the latch")

    def test_no_augment_on_screen_leaves_the_latch_open(self) -> None:
        from modes.shared_vision import GameVisionReader

        c = _make_coach()
        c._api_key = "sk-ant-test"
        c._out = Path(self._tmp.name) / "aram_coaching_data.json"
        c._out.write_text('{"mode": "aram"}', encoding="utf-8")

        with (
            mock.patch.object(
                GameVisionReader, "read_tiered", lambda _self: {"timer": "0:05"}
            ),
            mock.patch.object(
                aram_coach.Coach, "_fetch_game_data", lambda _self: {}
            ),
        ):
            c._run_vision()

        self.assertFalse(c._augment_resolved)

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
