"""Pin the vendored kit's platform check for its tree-kill, per test.

`ops/fleet_kit/fleet_headless._kill_tree` branches on `sys.platform`: win32
runs `taskkill /T /F /PID <pid>` then `proc.kill()`; POSIX (kit v10) asks
`os.getpgid(pid)` and, only for a group the child leads, sends SIGTERM to it,
waits, sends SIGKILL, then calls `proc.kill()`. A test that fakes taskkill and
asserts it ran therefore passes on Legion and fails on the ubuntu CI. The
`kit_platform` fixture runs the REAL `_kill_tree` with the platform pinned to
each branch in turn, so both are covered on every host, and
`assert_kit_killed` asserts the branch-appropriate kill.

Only the kill call sees the pinned platform; the rest of the kit is untouched.
On the POSIX branch the kit's `os` is pinned too: `getpgid` reports that the
fake child leads its own group and `killpg` only RECORDS the signal, so no
real process group is ever signalled (a fake pid can be a live one on the CI
runner) and Windows, which has no `getpgid` / `killpg` / SIGKILL, runs the
branch as well. Import both names into a test module to use them.
"""
from __future__ import annotations

import os
import signal
import sys

import pytest

from ops.loop import fleet_route

# (pgid, signal) pairs the POSIX branch sent during the current test.
GROUP_SIGNALS: list = []
_SIGKILL = getattr(signal, "SIGKILL", 9)


class _PlatformSys:
    """`sys` as the kit sees it, with only `platform` pinned."""

    def __init__(self, platform):
        self.platform = platform

    def __getattr__(self, name):
        return getattr(sys, name)


class _PosixGroupOs:
    """`os` as the kit sees it on the pinned POSIX branch: the fake child leads
    its own process group, and signalling the group is recorded, never sent."""

    @staticmethod
    def getpgid(pid):
        return pid

    @staticmethod
    def killpg(pgid, sig):
        GROUP_SIGNALS.append((pgid, sig))

    def __getattr__(self, name):
        return getattr(os, name)


@pytest.fixture(params=["win32", "linux"])
def kit_platform(request, monkeypatch):
    """Returns the pinned platform name for this parametrization."""
    plat = request.param
    k = fleet_route.kit()
    real = k._kill_tree
    GROUP_SIGNALS.clear()
    if plat == "win32":
        # The kit finds taskkill under SYSTEMROOT; a Linux host has none.
        monkeypatch.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT") or r"C:\Windows")
    else:
        # Windows' signal module has no SIGKILL; the kit names it on POSIX.
        monkeypatch.setattr(signal, "SIGKILL", _SIGKILL, raising=False)

    def pinned(proc):
        saved_sys, saved_os = k.sys, k.os
        k.sys = _PlatformSys(plat)
        if plat != "win32":
            k.os = _PosixGroupOs()
        try:
            return real(proc, grace=0)
        finally:
            k.sys, k.os = saved_sys, saved_os

    monkeypatch.setattr(k, "_kill_tree", pinned)
    return plat


def assert_kit_killed(plat, kills, proc_killed, pid):
    """The kit's platform-appropriate kill ran. `kills` = every faked
    subprocess.run argv; `proc_killed` = whether the child's kill() was called."""
    assert proc_killed is True, "the child itself is always killed"
    if plat == "win32":
        tree = [k for k in kills if "/T" in k]
        assert len(tree) == 1, kills
        (tk,) = tree
        assert tk[0].lower().endswith(("taskkill.exe", "taskkill"))
        assert tk[1:] == ["/T", "/F", "/PID", str(pid)], "the WHOLE tree, by pid"
        assert GROUP_SIGNALS == [], "no process-group signal on win32"
    else:
        assert kills == [], "the kit runs no taskkill on POSIX"
        assert GROUP_SIGNALS == [(pid, signal.SIGTERM), (pid, _SIGKILL)], \
            "the child's WHOLE group: SIGTERM, then SIGKILL"
