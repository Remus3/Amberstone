#!/usr/bin/env python
r"""Named-mutex wrapper for the two genuinely exclusive machine-wide resources.

SHARED FILE - must stay BYTE-IDENTICAL between the Legion Wallpaper and Riot
Commander repos. The two loops coordinate through the OS namespace these names
live in, so a divergence is a silent concurrency bug. Nothing here may reference
either repo.

WHAT NEEDS SERIALIZING, and why slots are not enough. Slots bound how many
executor calls run at once; these bound access to resources where even two is
one too many:

  GEMINI_MUTEX - one metered Gemini account. Two concurrent director calls burn
    quota in parallel and can trip RESOURCE_EXHAUSTED, which the adjudicator's
    failover logic would then misread as genuine credit exhaustion and stickily
    swap the backend for the REST OF THE RUN. Serializing is cheap: director
    calls are seconds.

  GPU_MUTEX - one GPU. Acquired by the TOOL that touches CUDA rather than by the
    loop, so a manual run is protected too.

ABANDONED MUTEX. If a holder dies without releasing, Windows hands the next
waiter WAIT_ABANDONED. That is treated as ACQUIRED, with a warning: the previous
holder's work may be half-done, but refusing to proceed would let one crashed
process deadlock the other repo indefinitely.

On non-Windows this degrades to a no-op context manager so the module imports
and unit-tests cleanly in CI.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

GEMINI_MUTEX = "Global\\LWRC_GEMINI"
GPU_MUTEX = "Global\\LW_GPU"

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_INFINITE = 0xFFFFFFFF


class MutexTimeout(RuntimeError):
    """The named mutex did not become free inside the caller's timeout."""


@contextmanager
def hold(name: str, *, timeout: float | None = None, log=None):
    """Hold a named mutex for the duration of the block.

    timeout None waits forever; otherwise MutexTimeout is raised, which callers
    treat as a failed step rather than as permission to proceed unserialized.
    """
    if sys.platform != "win32":
        # Non-Windows: nothing to serialize against (the loops are Windows-only).
        yield None
        return

    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = k32.CreateMutexW(None, False, name)
    if not handle:
        # Cannot create the mutex (rare: name/ACL problem). Fail OPEN with a
        # loud log rather than wedging the run - an unserialized gemini call is
        # a cost risk, a deadlocked loop is a dead run.
        if log:
            log(f"winmutex: CreateMutexW failed for {name} - proceeding UNSERIALIZED")
        yield None
        return

    ms = _INFINITE if timeout is None else int(max(0.0, timeout) * 1000)
    acquired = False
    try:
        rc = k32.WaitForSingleObject(handle, ms)
        if rc == _WAIT_TIMEOUT:
            raise MutexTimeout(f"{name} not free within {timeout}s")
        acquired = rc in (_WAIT_OBJECT_0, _WAIT_ABANDONED)
        if rc == _WAIT_ABANDONED and log:
            log(f"winmutex: {name} was ABANDONED by a dead holder - acquiring anyway "
                f"(its work may be half-done)")
        if not acquired and log:
            log(f"winmutex: unexpected wait result {rc} for {name} - proceeding")
        # ACQUIRED/RELEASED are logged so the hold window is OBSERVABLE in each
        # repo's controller.log. Without them "the two runs' gemini calls never
        # overlap" is only arguable from reading the code; with them it is
        # measurable from two log files after a concurrent run. Both repos pass
        # log= here, so the trace appears on both sides for free.
        if log:
            log(f"winmutex: ACQUIRED {name}")
        yield handle
    finally:
        if acquired and log:
            log(f"winmutex: RELEASED {name}")
        if acquired:
            try:
                k32.ReleaseMutex(handle)
            except OSError:
                pass
        try:
            k32.CloseHandle(handle)
        except OSError:
            pass
