"""True-audit hardening of ``tools/ds_keepalive.py`` (S144-T-708).

Findings pinned here, each red on the pre-fix module:

1. No relaunch route, yet it took over. The keepalive relaunches ONLY
   through the RC-DaemonSlayer task (``spawn_ds_task_only``), but it built
   and ticked a ``DsWatchdog`` whether or not that task exists. The watchdog
   KILLS a verified DS that is hung or slow to bind, then the relaunch
   raises - so with RC down on a host without the task (every host since the
   2026-10-31 launcher cutover) the keepalive could only take DS down, never
   bring it back. It now checks the route (``schtasks /Query``) on every step
   and stands down as ``no-task`` while the task is absent.
2. The loop's catch-all logged ``"step failed: %s"`` with no type and no
   traceback on every interval: a deterministic bug wrote the same
   unattributable line every 30 s, and an exception with an empty message
   (``KeyError()``) logged nothing useful at all. Now the first failure of a
   kind logs its type and traceback, repeats go to DEBUG, and the recovery is
   logged with the count.
3. ``_attach_log`` added a new file handler (and an open file handle) on
   every call; it is now idempotent per log file.
"""
from __future__ import annotations

import importlib
import logging
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest

import core.daemon_slayer_client as dsc

OK, DOWN, HUNG = dsc.OK, dsc.DOWN, dsc.HUNG
LOGGER = "rc.tools.ds_keepalive"


def _ka():
    return importlib.import_module("tools.ds_keepalive")


class _Rig:
    """Stubbed probe / holder / DS scan / kill / spawn for one DsWatchdog."""

    def __init__(self, *, state: str = OK, holder=None) -> None:
        self.state = state
        self.holder = holder
        self.probes = 0
        self.kills: list[int] = []
        self.spawns = 0
        self.made: list[dsc.DsWatchdog] = []

    def probe(self, port: int, timeout_s: float) -> str:
        self.probes += 1
        return self.state

    def kill(self, pid: int) -> bool:
        self.kills.append(pid)
        self.holder = None
        return True

    def spawn(self) -> str:
        self.spawns += 1
        return "scheduled task RC-DaemonSlayer"

    def watchdog(self) -> dsc.DsWatchdog:
        wd = dsc.DsWatchdog(
            probe=self.probe, find_holder=lambda port: self.holder,
            find_ds_process=lambda: None, is_ds=lambda pid: True,
            kill=self.kill, spawn=self.spawn, clock=lambda: 1000.0,
            sleep=lambda s: None)
        self.made.append(wd)
        return wd


def _keepalive(rig: _Rig, task: dict):
    return _ka().DsKeepalive(rc_live=lambda: False, stopped=lambda: False,
                             make_watchdog=rig.watchdog,
                             task_registered=lambda: task["up"])


# -- 1. no relaunch route: never take over -------------------------------------


def test_without_the_owner_task_it_never_probes_or_kills() -> None:
    # A wedged DS holds the port. With the task present, three steps kill
    # and relaunch it; without it, a kill is all the keepalive could do.
    rig = _Rig(state=HUNG, holder=4321)
    ka = _keepalive(rig, {"up": False})
    got = [ka.step() for _ in range(5)]
    assert got == ["no-task"] * 5
    assert (rig.probes, rig.kills, rig.spawns, rig.made) == (0, [], 0, [])


def test_the_same_wedge_is_replaced_when_the_task_exists() -> None:
    # Positive control for the test above: identical rig, task registered.
    rig = _Rig(state=HUNG, holder=4321)
    ka = _keepalive(rig, {"up": True})
    assert [ka.step() for _ in range(3)] == ["suspect", "suspect", "replaced"]
    assert (rig.kills, rig.spawns) == ([4321], 1)


def test_a_task_that_disappears_mid_watch_drops_the_watchdog() -> None:
    rig = _Rig(state=HUNG, holder=4321)
    task = {"up": True}
    ka = _keepalive(rig, task)
    assert [ka.step(), ka.step()] == ["suspect", "suspect"]
    task["up"] = False
    # The next tick would have killed pid 4321 with no way to relaunch.
    assert ka.step() == "no-task"
    assert rig.kills == []
    task["up"] = True
    # A carried suspect count would kill now; the new watchdog starts clean.
    assert ka.step() == "suspect"
    assert rig.kills == []
    assert len(rig.made) == 2 and rig.made[0] is not rig.made[1]


def test_stop_flag_and_rc_live_still_win_without_touching_schtasks() -> None:
    rig = _Rig(state=DOWN)
    asked: list[int] = []

    def task() -> bool:
        asked.append(1)
        return True

    ka = _ka().DsKeepalive(rc_live=lambda: True, stopped=lambda: False,
                           make_watchdog=rig.watchdog, task_registered=task)
    assert ka.step() == "deferred"
    ka = _ka().DsKeepalive(rc_live=lambda: False, stopped=lambda: True,
                           make_watchdog=rig.watchdog, task_registered=task)
    assert ka.step() == "stopped"
    assert asked == [] and rig.probes == 0


def test_a_raising_route_check_reads_as_no_task() -> None:
    rig = _Rig(state=HUNG, holder=4321)

    def broken() -> bool:
        raise RuntimeError("route check failure (test)")

    ka = _ka().DsKeepalive(rc_live=lambda: False, stopped=lambda: False,
                           make_watchdog=rig.watchdog, task_registered=broken)
    assert ka.step() == "no-task"
    assert (rig.probes, rig.kills) == (0, [])


def test_no_task_is_logged_once_per_transition(caplog) -> None:
    rig = _Rig(state=OK)
    task = {"up": False}
    ka = _keepalive(rig, task)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        for _ in range(4):
            ka.step()
    lines = [r for r in caplog.records if "no-task" in r.getMessage()]
    assert len(lines) == 1
    assert dsc.DS_TASK_NAME in lines[0].getMessage()


def test_the_default_route_check_is_the_schtasks_query() -> None:
    ka = _ka()
    assert ka.DsKeepalive()._task_registered is ka.ds_task_registered
    with mock.patch.object(dsc, "_schtasks", return_value=0) as q:
        assert ka.ds_task_registered() is True
    q.assert_called_once_with("/Query", "/TN", dsc.DS_TASK_NAME)
    with mock.patch.object(dsc, "_schtasks", return_value=1):
        assert ka.ds_task_registered() is False


@pytest.mark.parametrize("exc", [
    OSError("no schtasks (test)"),
    subprocess.TimeoutExpired(["schtasks"], 15.0),
])
def test_the_route_check_never_raises(exc) -> None:
    with mock.patch.object(dsc, "_schtasks", side_effect=exc):
        assert _ka().ds_task_registered() is False


def test_the_route_check_never_runs_or_ends_a_task() -> None:
    seen: list[tuple] = []

    def record(*args: str) -> int:
        seen.append(args)
        return 0

    with mock.patch.object(dsc, "_schtasks", side_effect=record):
        _ka().ds_task_registered()
    assert all(a[0] == "/Query" for a in seen) and seen


# -- 2. the loop's failure log ---------------------------------------------------


def _run_failing(ka, errors: list, then_ok: int = 0) -> None:
    stop = threading.Event()
    plan = list(errors) + [None] * then_ok

    def step() -> str:
        item = plan.pop(0)
        if not plan:
            stop.set()
        if item is not None:
            raise item
        return "ok"

    with mock.patch.object(ka, "step", step):
        ka.run(stop, interval_s=0.0)


def _ka_obj():
    return _ka().DsKeepalive(rc_live=lambda: True, stopped=lambda: False,
                             make_watchdog=lambda: None,
                             task_registered=lambda: True)


def test_a_repeated_failure_logs_one_traceback_not_one_per_interval(caplog) -> None:
    ka = _ka_obj()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        _run_failing(ka, [RuntimeError("same bug (test)") for _ in range(4)])
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1
    assert warns[0].exc_info is not None
    assert "RuntimeError" in warns[0].getMessage()


def test_a_new_kind_of_failure_logs_again(caplog) -> None:
    ka = _ka_obj()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        _run_failing(ka, [RuntimeError("a (test)"), RuntimeError("a (test)"),
                          ValueError("b (test)")])
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [w.exc_info[0] for w in warns] == [RuntimeError, ValueError]


def test_an_empty_message_failure_still_names_its_type(caplog) -> None:
    ka = _ka_obj()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        _run_failing(ka, [KeyError()])
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1 and "KeyError" in warns[0].getMessage()


def test_recovery_is_logged_with_the_failure_count(caplog) -> None:
    ka = _ka_obj()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run_failing(ka, [RuntimeError("x (test)")] * 3, then_ok=1)
    rec = [r for r in caplog.records if "recovered" in r.getMessage()]
    assert len(rec) == 1 and "3" in rec[0].getMessage()


def test_after_recovery_the_same_failure_logs_its_traceback_again(caplog) -> None:
    ka = _ka_obj()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        _run_failing(ka, [RuntimeError("x (test)")], then_ok=1)
        _run_failing(ka, [RuntimeError("x (test)")])
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 2


# -- 3. _attach_log is idempotent ------------------------------------------------


def test_attach_log_twice_adds_one_handler(tmp_path) -> None:
    ka = _ka()
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    target = tmp_path / "logs" / "ds_keepalive.log"
    try:
        with mock.patch.object(ka, "_LOG_FILE", target), \
                mock.patch.object(ka, "_FALLBACK_LOG_FILE",
                                  tmp_path / "fb" / "ds_keepalive.log"):
            ka._attach_log()
            ka._attach_log()
        mine = [h for h in root.handlers if h not in before_handlers]
        assert len(mine) == 1
        assert Path(mine[0].baseFilename) == target
    finally:
        for h in [h for h in root.handlers if h not in before_handlers]:
            root.removeHandler(h)
            h.close()
        root.setLevel(before_level)
