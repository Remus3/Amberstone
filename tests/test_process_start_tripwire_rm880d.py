"""RM-880 (d): a "starts nothing" tripwire that does not depend on a module list.

The refused-route tests in tests/test_headless_route_spawn_paths.py and
tests/test_repo_review_driver.py bind their tripwire into the spawn chain's
OWN `subprocess` names (RM-801), so a spawn path that gains a module outside
that list - a new helper that imports subprocess, `os.system`, `os.startfile` -
starts a real process while the test stays green. `no_process_start()`
(tests/_module_view.py) hears the interpreter's process-start audit events
instead, for the arming thread and the threads it starts, and leaves every
thread that was already alive (another test's leftover server) alone.

The real processes these tests start are `python -c pass` with no window.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import pytest

from tests._module_view import ProcessStartTripped, no_process_start
from tests._timing_budget import fleet_test_guard

_NO_WINDOW = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
_HARMLESS = [sys.executable, "-c", "pass"]


def _real_run():
    return subprocess.run(
        _HARMLESS, capture_output=True, timeout=60, check=False, **_NO_WINDOW)


def test_a_start_through_an_unbound_module_trips():
    with pytest.raises(ProcessStartTripped):
        with no_process_start() as hits:
            _real_run()
    assert [h[0] for h in hits] == ["subprocess.Popen"]


def _run_swallowing_errors():
    try:
        _real_run()
    except Exception:  # noqa: BLE001 - the code under test swallowing it
        pass


def test_a_swallowed_trip_still_fails_when_the_block_ends():
    with pytest.raises(ProcessStartTripped, match=r"subprocess\.Popen"), no_process_start():
        _run_swallowing_errors()


def test_os_system_trips():
    with pytest.raises(ProcessStartTripped):
        with no_process_start() as hits:
            os.system("exit 0")  # noqa: S605 - the tripwire under test must see this call; the command is a constant
    assert [h[0] for h in hits] == ["os.system"]


def test_a_thread_started_inside_the_block_is_armed_too():
    seen = []

    def _worker():
        try:
            _real_run()
            seen.append("started")
        except ProcessStartTripped:
            seen.append("tripped")

    def _run_worker_thread():
        t = threading.Thread(target=_worker)
        t.start()
        t.join(60)

    with pytest.raises(ProcessStartTripped), no_process_start():
        _run_worker_thread()
    assert seen == ["tripped"]


def test_a_thread_alive_before_arming_keeps_real_starts():
    go, done = threading.Event(), threading.Event()
    rc = []

    def _leftover():
        go.wait(60)
        rc.append(_real_run().returncode)
        done.set()

    t = threading.Thread(target=_leftover, daemon=True)
    t.start()
    with no_process_start() as hits:
        go.set()
        assert done.wait(fleet_test_guard.budget(60))
    t.join(60)
    assert rc == [0] and hits == []


def test_a_thread_the_leftover_starts_keeps_real_starts_too():
    go, done = threading.Event(), threading.Event()
    rc = []

    def _child():
        rc.append(_real_run().returncode)
        done.set()

    def _leftover():
        go.wait(60)
        threading.Thread(target=_child, daemon=True).start()

    t = threading.Thread(target=_leftover, daemon=True)
    t.start()
    with no_process_start() as hits:
        go.set()
        assert done.wait(fleet_test_guard.budget(60))
    assert rc == [0] and hits == []


def test_the_block_disarms_on_exit():
    with no_process_start() as hits:
        pass
    assert _real_run().returncode == 0 and hits == []


def test_nested_blocks_each_record_the_start():
    with pytest.raises(ProcessStartTripped), no_process_start() as outer, no_process_start() as inner:
        _real_run()
    assert len(outer) == 1 and len(inner) == 1
