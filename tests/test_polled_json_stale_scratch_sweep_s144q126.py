"""S144-Q-126 - a hard kill orphans core.polled_json scratch; a writer sweeps its own.

`core/polled_json.py` `_write_then_replace` unlinks its per-writer scratch
(`<dest>.<pid>.<8 hex>.tmp`) in an `except BaseException` arm, but a hard kill
(`taskkill /F`, the prescribed restart path) between the scratch write and the
rename runs no Python at all, so the scratch stays on disk for ever. Measured
read-only on the live tree 2026-11-08: one `monitor_state.json.<pid>.<hex>.tmp`
(writer: ops/rc_self_monitor.py) and 23 `health.json.<pid>.<hex>.tmp` (writer:
the FROZEN ops/rc_dev_runtime.py, RM-718 (f), not this row).

Fix under test:
  - `core.polled_json.sweep_stale_scratch(dest, max_age_s, now=None)` removes
    only regular files whose name is `dest.name` plus exactly the polled_json
    scratch suffix, strictly older than `max_age_s`, and never raises. Another
    destination's scratch, a young (possibly in-flight) scratch, a directory
    and near-miss names are kept.
  - `SelfMonitor.start()` sweeps the scratch of the two fixed destinations it
    writes (monitor_state.json and config/self_monitor_profile.json) once,
    before its threads start.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from core import polled_json
from ops import rc_self_monitor as rsm

if TYPE_CHECKING:
    import pytest

NOW = 2_000_000_000.0
AGE = 3600.0


def _make(path: Path, mtime: float) -> Path:
    path.write_bytes(b"{}")
    os.utime(path, (mtime, mtime))
    return path


def test_sweep_removes_old_own_scratch_and_keeps_everything_else(tmp_path: Path) -> None:
    dest = tmp_path / "monitor_state.json"
    _make(dest, NOW - 10 * AGE)
    old = _make(tmp_path / "monitor_state.json.4242.deadbeef.tmp", NOW - AGE - 1)
    old2 = _make(tmp_path / "monitor_state.json.7.0123abcd.tmp", NOW - 50 * AGE)
    young = _make(tmp_path / "monitor_state.json.4242.cafef00d.tmp", NOW - 5)
    at_cutoff = _make(tmp_path / "monitor_state.json.1.00000000.tmp", NOW - AGE)
    foreign = _make(tmp_path / "health.json.4242.deadbeef.tmp", NOW - 50 * AGE)
    near_misses = [
        _make(tmp_path / name, NOW - 50 * AGE)
        for name in (
            "monitor_state.json.tmp",               # legacy shape, not polled_json's
            "monitor_state.json.tmp.4242",          # legacy shape, not polled_json's
            # token_hex is lowercase (a name distinct from every other one
            # here even on a case-insensitive filesystem)
            "monitor_state.json.4242.ABCDEF12.tmp",
            "monitor_state.json.4242.deadbee.tmp",   # 7 hex
            "monitor_state.json.4242.deadbeef0.tmp",  # 9 hex
            "monitor_state.json.x.deadbeef.tmp",     # pid not digits
            "monitor_state.json.4242.deadbeef.tmp.bak",
            "xmonitor_state.json.4242.deadbeef.tmp",
            "monitor_stateXjson.4242.deadbeef.tmp",  # a regex dot would match this
        )
    ]
    a_dir = tmp_path / "monitor_state.json.9.abcdef01.tmp"
    a_dir.mkdir()
    os.utime(a_dir, (NOW - 50 * AGE, NOW - 50 * AGE))

    removed = polled_json.sweep_stale_scratch(dest, AGE, now=NOW)

    assert removed == 2
    assert not old.exists()
    assert not old2.exists()
    for kept in (dest, young, at_cutoff, foreign, a_dir, *near_misses):
        assert kept.exists(), kept.name


def test_sweep_matches_the_name_the_writer_actually_uses(tmp_path: Path) -> None:
    """Pin the sweep to `_scratch_path`, not to a restated pattern: a scratch
    name minted by the real writer helper is a candidate."""
    dest = tmp_path / "x.json"
    scratch = polled_json._scratch_path(dest)
    _make(scratch, NOW - AGE - 1)
    assert polled_json.sweep_stale_scratch(dest, AGE, now=NOW) == 1
    assert not scratch.exists()


def test_sweep_defaults_now_to_the_clock(tmp_path: Path) -> None:
    dest = tmp_path / "x.json"
    import time
    old = _make(tmp_path / "x.json.12.abcdef12.tmp", time.time() - AGE - 60)
    young = _make(tmp_path / "x.json.12.abcdef13.tmp", time.time())
    assert polled_json.sweep_stale_scratch(dest, AGE) == 1
    assert not old.exists()
    assert young.exists()


def test_sweep_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert polled_json.sweep_stale_scratch(tmp_path / "absent" / "x.json", AGE, now=NOW) == 0

    dest = tmp_path / "x.json"
    victim = _make(tmp_path / "x.json.12.abcdef12.tmp", NOW - 50 * AGE)

    def boom(self: Path, *a: object, **k: object) -> None:
        raise PermissionError("held open")

    monkeypatch.setattr(Path, "unlink", boom)
    assert polled_json.sweep_stale_scratch(dest, AGE, now=NOW) == 0
    assert victim.exists()


class _NullIncidentLog:
    def record(self, **kwargs: object) -> None:
        pass


class _InertThread:
    def __init__(self, *a: object, **k: object) -> None:
        pass

    def start(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        pass


def _monitor(tmp_path: Path) -> rsm.SelfMonitor:
    runtime = tmp_path / "ops" / "runtime"
    runtime.mkdir(parents=True)
    return rsm.SelfMonitor(
        project_root=tmp_path,
        runtime_dir=runtime,
        incident_log=_NullIncidentLog(),
        state_validator=None,
        health_file=runtime / "health.json",
    )


def test_self_monitor_start_sweeps_its_own_stale_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mon = _monitor(tmp_path)
    runtime = tmp_path / "ops" / "runtime"
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    long_ago = 1_000_000_000.0
    state_orphan = _make(runtime / "monitor_state.json.4242.deadbeef.tmp", long_ago)
    profile_orphan = _make(config / "self_monitor_profile.json.4242.deadbeef.tmp", long_ago)
    health_orphan = _make(runtime / "health.json.4242.deadbeef.tmp", long_ago)
    import time
    young = _make(runtime / "monitor_state.json.4242.cafef00d.tmp", time.time())

    monkeypatch.setattr(rsm.threading, "Thread", _InertThread)
    mon.start()

    assert not state_orphan.exists()
    assert not profile_orphan.exists()
    # Not the self-monitor's file: the frozen dev runtime writes health.json.
    assert health_orphan.exists()
    assert young.exists()


def test_self_monitor_start_survives_a_sweep_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mon = _monitor(tmp_path)

    def boom(*a: object, **k: object) -> int:
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(rsm, "sweep_stale_scratch", boom, raising=False)
    monkeypatch.setattr(rsm.threading, "Thread", _InertThread)
    mon.start()
    assert len(mon._threads) == 2
