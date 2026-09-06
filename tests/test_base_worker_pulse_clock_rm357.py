"""RM-357 - BaseCoachWorker's subclass contract named the WRONG clock.

`core/base_worker.py` instructed subclass authors to set
`self.pulse_ts = time.time()` on each poll iteration. Both shipped subclasses
ignore that and use `time.monotonic()` (`core/sr_aram_worker.py`,
`core/tft_worker.py`), and so does the consumer - the FROZEN
`app/_health_monitor.py` differences `pulse_ts` against `time.monotonic()`.

The two clocks are different epochs. A third subclass written to the DOCUMENTED
contract would make `worker_age = now - w_pulse` roughly -1.7e9, so the gate
`game_poll_worker_alive = worker_age < 12.0` evaluates True permanently: the
health monitor would report a dead worker as alive forever, which is the exact
inversion of what the pulse exists to detect.

`app/_health_monitor.py` is frozen (CLAUDE.md), so the whole fix lives in
`core/base_worker.py`: the contract is corrected to name `time.monotonic()`,
and `pulse_ts` gained a fail-safe setter so a worker written to the old
contract reads as NOT alive rather than alive-forever.

Note on where the guard lives: the filed row offered `health_pulse()` as an
optional home for the rejection. It is not one. `health_pulse()` has zero
callers in the tree and the consumer reads the `pulse_ts` attribute directly,
so a guard placed there would have been inert.
"""

from __future__ import annotations

import inspect
import re
import time
from types import SimpleNamespace

import pytest

from app._health_monitor import HealthMonitor
from core.base_worker import BaseCoachWorker
from core.sr_aram_worker import SrAramWorker
from core.tft_worker import TftWorker

# Matches `time.monotonic()` / `time.time()` and captures the clock name.
_CLOCK_RE = re.compile(r"\btime\.(monotonic|time)\(\)")
# Matches an assignment of the pulse timestamp from a stdlib clock.
_PULSE_ASSIGN_RE = re.compile(r"self\.pulse_ts\s*=\s*time\.(monotonic|time)\(\)")


def _clocks_named(text: str) -> set[str]:
    return set(_CLOCK_RE.findall(text))


def _make_app(worker) -> SimpleNamespace:
    """Minimal stand-in carrying exactly the attributes get_health_state reads."""
    return SimpleNamespace(
        mode="sr",
        _tft_mode=False,
        _aram_mode=False,
        _arena_mode=False,
        _was_in_game=True,
        _sr_aram_worker=worker,
        _overlay_visible=False,
    )


class _Worker(BaseCoachWorker):
    """Concrete subclass - the base's `_run` is abstract."""

    def _run(self, my_gen: int) -> None:  # pragma: no cover - never started
        raise AssertionError("not started in these tests")


# -- Acceptance clause 1: the contract names the consumer's clock -------------


def test_contract_clock_matches_the_clock_the_health_monitor_differences_against():
    """The clock named in BaseCoachWorker's subclass contract must be the same
    one app/_health_monitor.py subtracts pulse_ts from.

    Derived from both sources rather than hardcoded, so the assertion keeps
    holding if the consumer's clock ever changes.
    """
    contract = _clocks_named(BaseCoachWorker.__doc__ or "")
    consumer = _clocks_named(inspect.getsource(HealthMonitor.get_health_state))

    assert consumer == {"monotonic"}, (
        f"consumer's clock changed; re-derive this contract: {consumer!r}"
    )
    assert contract == consumer, (
        f"BaseCoachWorker's subclass contract names {contract!r} but the health "
        f"monitor differences pulse_ts against {consumer!r} - a subclass written "
        f"to the contract would invert the liveness gate"
    )


def test_both_shipped_subclasses_pulse_on_the_contracted_clock():
    """Sibling guard: neither concrete worker may drift off the contract."""
    contract = _clocks_named(BaseCoachWorker.__doc__ or "")

    for cls in (SrAramWorker, TftWorker):
        found = set(_PULSE_ASSIGN_RE.findall(inspect.getsource(cls)))
        assert found, f"no `self.pulse_ts = time.<clock>()` found in {cls.__name__}"
        assert found == contract, (
            f"{cls.__name__} pulses on {found!r} but the contract names {contract!r}"
        )


# -- Acceptance clause 2: a wall-clock pulse must not read as alive -----------


def test_wall_clock_pulse_does_not_report_the_worker_alive():
    """The defect, end to end through the REAL frozen consumer.

    Unguarded, `worker_age` is about -1.7e9, which passes `< 12.0`, so a worker
    that never pulses again is reported alive forever.
    """
    worker = _Worker()
    worker.pulse_ts = time.time()  # the clock the old contract instructed

    state = HealthMonitor(_make_app(worker)).get_health_state()

    assert state["game_poll_worker_alive"] is False, (
        "a wall-clock pulse_ts inverted the liveness gate: "
        f"age={state['game_poll_worker_age_s']!r}"
    )


def test_monotonic_pulse_still_reports_the_worker_alive():
    """The guard must not be so broad that it rejects a legitimate pulse."""
    worker = _Worker()
    worker.pulse_ts = time.monotonic()

    state = HealthMonitor(_make_app(worker)).get_health_state()

    assert state["game_poll_worker_alive"] is True
    assert state["game_poll_worker_age_s"] is not None


def test_absent_pulse_still_reports_not_alive():
    """A worker that never pulsed keeps the pre-existing no-pulse behaviour."""
    state = HealthMonitor(_make_app(_Worker())).get_health_state()

    assert state["game_poll_worker_alive"] is False
    assert state["game_poll_worker_age_s"] is None


# -- The guard itself, at unit level ------------------------------------------


def test_pulse_ts_preserves_a_monotonic_timestamp_exactly():
    worker = _Worker()
    stamp = time.monotonic()
    worker.pulse_ts = stamp
    assert worker.pulse_ts == stamp


def test_pulse_ts_rejects_a_timestamp_from_the_wrong_epoch():
    worker = _Worker()
    worker.pulse_ts = time.monotonic()
    worker.pulse_ts = time.time()
    assert worker.pulse_ts == 0.0, "wall-clock pulse must degrade to no-pulse"


def test_pulse_ts_defaults_to_zero_and_accepts_zero():
    worker = _Worker()
    assert worker.pulse_ts == 0.0
    worker.pulse_ts = time.monotonic()
    worker.pulse_ts = 0.0
    assert worker.pulse_ts == 0.0


@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), float("-inf"), -1.0, None, "later", object()],
)
def test_pulse_ts_rejects_values_that_cannot_be_a_monotonic_reading(bad):
    """None of these can come from time.monotonic(); all must fail safe.

    The non-numeric cases cover the coercion branch, which is otherwise never
    exercised - a guard on a path no test takes is an untested guard.
    """
    worker = _Worker()
    worker.pulse_ts = bad
    assert worker.pulse_ts == 0.0


def test_future_slack_is_tight_enough_to_still_catch_a_wall_clock_stamp():
    """Pin the tolerance itself.

    An adversarial pass found the guard stayed green with the slack widened to
    1e5 and even 1e9 seconds, because a wall-clock stamp is ~1.79e9 and clears
    any of those. The slack only exists to absorb scheduling noise between the
    caller's clock read and ours, so anything above a minute is a bug, and an
    unpinned constant is one edit away from being useless.
    """
    from core.base_worker import _PULSE_FUTURE_SLACK_S

    assert 0.0 < _PULSE_FUTURE_SLACK_S <= 60.0


def test_a_stamp_just_past_the_slack_is_rejected():
    """The boundary, not just the far-away wall-clock case."""
    worker = _Worker()
    worker.pulse_ts = time.monotonic() + 3600.0
    assert worker.pulse_ts == 0.0


def test_health_pulse_reports_the_guarded_value():
    worker = _Worker()
    worker.pulse_ts = time.time()
    assert worker.health_pulse()["pulse_ts"] == 0.0
