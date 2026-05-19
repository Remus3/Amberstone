"""tests/test_resource_manager_mem_remediation.py

P2-B: ResourceManager high-memory -> remediation wiring.

The 500 MB watchdog used to only log + gc.collect(). It now also drives the
SAME remediation entrypoint the system uses for an unhealthy coach
(RemediationService.restart_game_poll, injected as a callable), gated by a
sustained-N-samples debounce and a cooldown so a single spike cannot restart
the live RC and a flapping process cannot restart-loop.

These tests exercise the gate logic directly with a stub RSS source and a
fake hook. No live RC is restarted: the hook is a Mock.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from core.resource_manager import (
    ResourceManager,
    _LIMIT_MB,
    _MEM_SUSTAINED_SAMPLES,
)


@pytest.fixture
def rm(tmp_path: Path) -> ResourceManager:
    return ResourceManager(tmp_path)


# -- Single spike must NOT trigger -------------------------------------------

def test_single_spike_does_not_trigger(rm: ResourceManager):
    calls = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})

    # One sample over the limit - below the sustained-N gate.
    fired = rm._mem_remediation_step(_LIMIT_MB + 50.0)

    assert fired is False
    assert calls == []


# -- Sustained breach DOES trigger exactly once, then cooldown ----------------

def test_sustained_breach_triggers_once_then_cooldown(rm: ResourceManager):
    calls = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})

    over = _LIMIT_MB + 80.0

    # First N-1 breaches: arming, no trigger yet.
    for _ in range(_MEM_SUSTAINED_SAMPLES - 1):
        assert rm._mem_remediation_step(over) is False
    assert calls == []

    # Nth consecutive breach: fires exactly one remediation.
    assert rm._mem_remediation_step(over) is True
    assert calls == [1]

    # Still breaching, but inside the cooldown window: must NOT re-fire.
    for _ in range(_MEM_SUSTAINED_SAMPLES + 3):
        assert rm._mem_remediation_step(over) is False
    assert calls == [1]


def test_cooldown_expiry_allows_a_second_trigger(rm: ResourceManager):
    calls = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})
    over = _LIMIT_MB + 80.0

    for _ in range(_MEM_SUSTAINED_SAMPLES):
        rm._mem_remediation_step(over)
    assert calls == [1]

    # Simulate the cooldown elapsing.
    rm._mem_last_remediation_mono -= (rm._MEM_REMEDIATION_COOLDOWN_S + 1.0)

    # Need to re-arm the sustained counter (cooldown also reset the streak).
    for _ in range(_MEM_SUSTAINED_SAMPLES):
        rm._mem_remediation_step(over)
    assert calls == [1, 1]


# -- Below-threshold never triggers, and resets the streak -------------------

def test_below_threshold_never_triggers(rm: ResourceManager):
    calls = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})

    for _ in range(_MEM_SUSTAINED_SAMPLES * 3):
        assert rm._mem_remediation_step(_LIMIT_MB - 1.0) is False
    assert calls == []


def test_a_dip_below_threshold_resets_the_sustained_streak(rm: ResourceManager):
    calls = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})
    over = _LIMIT_MB + 80.0

    # Almost there...
    for _ in range(_MEM_SUSTAINED_SAMPLES - 1):
        rm._mem_remediation_step(over)
    # ...one healthy sample wipes the streak.
    rm._mem_remediation_step(_LIMIT_MB - 10.0)
    # So the next breach is sample #1 again, not the trigger.
    assert rm._mem_remediation_step(over) is False
    assert calls == []


# -- Degrades safely when no hook / hook raises ------------------------------

def test_no_hook_degrades_safely(rm: ResourceManager, caplog):
    over = _LIMIT_MB + 80.0
    # No hook set at all.
    with caplog.at_level(logging.ERROR, logger="rc.resources"):
        for _ in range(_MEM_SUSTAINED_SAMPLES):
            rm._mem_remediation_step(over)
    # Sustained breach was reached and logged, but nothing crashed.
    assert any("MEM-REMEDIATION" in r.message for r in caplog.records)


def test_hook_exception_does_not_crash_and_is_logged(rm: ResourceManager, caplog):
    def _boom():
        raise RuntimeError("restart path unavailable")

    rm.set_remediation_hook(_boom)
    over = _LIMIT_MB + 80.0

    with caplog.at_level(logging.ERROR, logger="rc.resources"):
        result = None
        for _ in range(_MEM_SUSTAINED_SAMPLES):
            result = rm._mem_remediation_step(over)

    # The trigger was attempted (returns True - we DID act), the exception was
    # swallowed and logged, and the cooldown still latched (no restart-loop).
    assert result is True
    assert any("MEM-REMEDIATION" in r.message for r in caplog.records)
    assert any("error" in r.message.lower() for r in caplog.records)
    # Cooldown latched even though the hook failed.
    over2_fired = rm._mem_remediation_step(over)
    assert over2_fired is False


# -- Every triggered remediation is logged (never silent) --------------------

def test_trigger_emits_structured_log_line(rm: ResourceManager, caplog):
    rm.set_remediation_hook(lambda: {"ok": True, "detail": "SrAramWorker restarted"})
    over = _LIMIT_MB + 120.0

    with caplog.at_level(logging.ERROR, logger="rc.resources"):
        for _ in range(_MEM_SUSTAINED_SAMPLES):
            rm._mem_remediation_step(over)

    triggered = [r.message for r in caplog.records
                 if "MEM-REMEDIATION TRIGGERED" in r.message]
    assert triggered, "no structured MEM-REMEDIATION TRIGGERED line emitted"
    line = triggered[-1]
    # Must carry the load-bearing facts: the rss, the limit, the sample count.
    assert str(_LIMIT_MB) in line
    assert "rss" in line.lower()
    assert "sustained" in line.lower()
    assert str(_MEM_SUSTAINED_SAMPLES) in line
    # The hook's return value is also logged (audit trail; never silent).
    assert any("MEM-REMEDIATION result" in r.message for r in caplog.records)


# -- The watchdog loop path calls the gate (integration-ish, mocked RSS) -----

def test_watchdog_loop_invokes_gate(monkeypatch, tmp_path: Path):
    rm = ResourceManager(tmp_path)
    seen = []

    def _stub_step(rss):
        seen.append(rss)
        # First call (this pass) - stop the loop so it runs exactly once.
        rm._shutdown_done = True
        return False

    monkeypatch.setattr(rm, "_mem_remediation_step", _stub_step)
    # The breach path reads RSS twice (sample, then post-GC). Both high so
    # the value handed to the gate is unambiguously a breach. The gate is
    # fed the POST-GC reading by design (gc may not reclaim a real leak).
    monkeypatch.setattr(rm, "_rss_mb", lambda: _LIMIT_MB + 200.0)
    rm._watchdog_loop(interval_s=0.0)

    assert seen and seen[0] >= _LIMIT_MB
