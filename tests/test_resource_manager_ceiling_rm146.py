"""tests/test_resource_manager_ceiling_rm146.py

RM-146: the memory ceiling must sit ABOVE RC's normal in-game working set.

Measured 2026-08-02 on Legion (pid 21348, one clean from-boot run, two full
back-to-back ARAM matches on the SAME process, sampled under a live dashboard
client doing ~1600 req/min):

    idle, 10 min          RSS 88-147 MB, flat, no trend
    game 1 start          RSS 97.5 -> 489.7   (+392 MB one-time warm-up)
    game 1 in-game n=140  min 499.7  max 547.6  mean 518.8
    game 2 start          RSS 494.2 -> 549.2   (+55 MB only)
    game 2 in-game n=29   min 532.3  max 547.9  mean 538.9
    committed memory      1007.3 -> 1031.7 MB across the whole second match

The two games agree on a roof within 0.3 MB and the second match added ~24 MB
of committed memory rather than another ~835 MB, so the game-start step is a
ONE-TIME lazy warm-up that is reused, NOT per-game residue. Nothing leaks.

At the old _LIMIT_MB = 500 that steady state was a permanent breach, so the
watchdog logged at ERROR every 60s for the whole of every match and the
restart-loop guard (correctly) declined to act on it forever. The defect was
the ceiling, not the guard.

These tests pin the ceiling against the MEASURED numbers so a future edit
cannot silently walk it back under the working set.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.resource_manager import (
    ResourceManager,
    _LIMIT_MB,
    _MEM_SUSTAINED_SAMPLES,
    _WARN_MB,
)

# Highest RSS observed in normal play across both measured matches.
MEASURED_INGAME_MAX_MB = 547.9
# Highest RSS observed on this machine on 2026-08-02 at all, on the aged
# pre-restart process. Cause is NOT explained by the two measured matches;
# the leading hypothesis is the G6-04 session's repeated desktop resolution
# flips (2560x1440 <-> 1920x1080). The ceiling must clear it anyway, because
# it is real observed behaviour on this box.
OBSERVED_PEAK_MB = 810.0
# Idle RSS, cold process, no game.
MEASURED_IDLE_MB = 147.0


def test_warn_is_below_limit():
    assert _WARN_MB < _LIMIT_MB


def test_limit_clears_the_measured_in_game_working_set():
    """The steady state of simply playing a game must not be a breach."""
    assert _LIMIT_MB > MEASURED_INGAME_MAX_MB


def test_limit_clears_the_observed_peak():
    """A known-real excursion must not trip remediation either."""
    assert _LIMIT_MB > OBSERVED_PEAK_MB


def test_warn_clears_the_measured_in_game_working_set():
    """Normal play must not warn every 60s either - that was the log spam."""
    assert _WARN_MB > MEASURED_INGAME_MAX_MB


def test_warn_still_fires_below_the_limit():
    """The ceiling must not be raised so far that WARN loses its job."""
    assert _WARN_MB > MEASURED_IDLE_MB


@pytest.fixture
def rm(tmp_path: Path) -> ResourceManager:
    return ResourceManager(tmp_path)


def test_sustained_in_game_working_set_never_remediates(rm: ResourceManager):
    """The regression that RM-146 actually filed.

    Feed the measured in-game maximum for well past the sustained-sample gate
    and assert remediation is never armed and never fires. At _LIMIT_MB = 500
    this failed on sample _MEM_SUSTAINED_SAMPLES.
    """
    calls: list[int] = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})

    for _ in range(_MEM_SUSTAINED_SAMPLES * 5):
        assert rm._mem_remediation_step(MEASURED_INGAME_MAX_MB) is False

    assert calls == []
    assert rm._mem_breach_streak == 0


def test_a_genuine_runaway_still_remediates(rm: ResourceManager):
    """Raising the ceiling must not disarm the watchdog."""
    calls: list[int] = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})

    runaway = _LIMIT_MB + 250.0
    fired = False
    for _ in range(_MEM_SUSTAINED_SAMPLES):
        fired = rm._mem_remediation_step(runaway)

    assert fired is True
    assert calls == [1]
