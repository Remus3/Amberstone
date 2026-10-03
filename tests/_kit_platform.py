"""Pin the vendored kit's platform check for its tree-kill, per test.

`ops/fleet_kit/fleet_headless._kill_tree` branches on `sys.platform`: win32
runs `taskkill /T /F /PID <pid>` then `proc.kill()`; POSIX only calls
`proc.kill()`. A test that fakes taskkill and asserts it ran therefore passes on
Legion and fails on the ubuntu CI. The `kit_platform` fixture runs the REAL
`_kill_tree` with the platform pinned to each branch in turn, so both are
covered on every host, and `assert_kit_killed` asserts the branch-appropriate
kill. Only the kill call sees the pinned platform; the rest of the kit is
untouched. Import both names into a test module to use them.
"""
from __future__ import annotations

import os
import sys

import pytest

from ops.loop import fleet_route


class _PlatformSys:
    """`sys` as the kit sees it, with only `platform` pinned."""

    def __init__(self, platform):
        self.platform = platform

    def __getattr__(self, name):
        return getattr(sys, name)


@pytest.fixture(params=["win32", "linux"])
def kit_platform(request, monkeypatch):
    """Returns the pinned platform name for this parametrization."""
    plat = request.param
    k = fleet_route.kit()
    real = k._kill_tree
    if plat == "win32":
        # The kit finds taskkill under SYSTEMROOT; a Linux host has none.
        monkeypatch.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT") or r"C:\Windows")

    def pinned(proc):
        saved = k.sys
        k.sys = _PlatformSys(plat)
        try:
            return real(proc)
        finally:
            k.sys = saved

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
    else:
        assert kills == [], "the kit runs no taskkill on POSIX"
