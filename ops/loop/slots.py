#!/usr/bin/env python
r"""Machine-wide concurrency governor for headless loop runs.

SHARED FILE - this must stay BYTE-IDENTICAL across the Legion Wallpaper, Riot
Commander and Resin Compute repos. The three loops coordinate with each other
THROUGH this file's on-disk protocol, so a divergence is not a merge conflict
you notice, it is a silent concurrency bug. Nothing here may reference ANY of
them: every project-specific value arrives as an argument.

WHY A GOVERNOR AT ALL. Once the executor stops being the AHK GUI bridge (a
machine-wide singleton keyed on a window title), two loops CAN run at once - so
the things they still share need bounding. Slots bound total concurrent executor
calls on the box: the Anthropic account is one rate-limit pool, and a runaway
fan-out from two repos degrades both.

PROTOCOL. A token bucket of exclusive-create lockfiles in a shared directory.
  acquire: O_CREAT|O_EXCL on slots/<i>.lock for i in range(max_slots); first
           success wins. The file carries {pid, repo, run_id, cycle, ts}.
  reap:    a lock whose ts is older than stale_after OR whose pid is not alive
           is reclaimed. FAIL-OPEN by design - a crashed holder must never
           deadlock the other repo, so a stale lock is reclaimed rather than
           respected forever.
  release: unlink, always, in a finally.
  wait:    jittered backoff so two loops do not lockstep into each other.

HELD ONLY AROUND THE EXECUTOR CALL, never around git or the adjudicator, so a
long merge in one repo cannot starve the other.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_ROOT = Path(r"C:\ProgramData\lw-loop\slots")

# A cycle deadline is 5400s; a lock older than well past that belongs to a
# process that died without cleaning up.
DEFAULT_STALE_AFTER = 3.0 * 5400.0


class SlotTimeout(RuntimeError):
    """No slot became free inside the caller's timeout."""


def pid_alive(pid: int) -> bool:
    """True if the pid is a live process.

    Windows: OpenProcess with QUERY_LIMITED_INFORMATION, which succeeds for
    processes owned by other users too - important, since one loop may run as a
    scheduled task and the other interactively. A pid we cannot query is treated
    as ALIVE (conservative: we would rather wait than double-book a slot).
    """
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        # ERROR_INVALID_PARAMETER (87) means no such process; anything else
        # (e.g. access denied) means it exists but we cannot see it.
        return k32.GetLastError() != 87
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_stale(path: Path, stale_after: float, now: float | None = None) -> bool:
    """A lock is stale if its holder is gone or it has outlived stale_after."""
    rec = _read(path)
    if not rec:
        # Unreadable or half-written: fall back to mtime so a corrupt lock
        # cannot wedge the bucket forever.
        try:
            return (time.time() - path.stat().st_mtime) > stale_after
        except OSError:
            return True
    now = time.time() if now is None else now
    if (now - float(rec.get("ts", 0))) > stale_after:
        return True
    return not pid_alive(int(rec.get("pid", 0)))


def reap(root: Path, max_slots: int, stale_after: float, log=None) -> int:
    """Reclaim dead locks. Returns how many were removed."""
    removed = 0
    for i in range(max_slots):
        p = root / f"{i}.lock"
        if not p.exists():
            continue
        if is_stale(p, stale_after):
            try:
                rec = _read(p)
                p.unlink()
                removed += 1
                if log:
                    log(f"slots: reaped stale slot {i} "
                        f"(pid={rec.get('pid')} repo={rec.get('repo')})")
            except OSError:
                pass  # someone else reaped it first - fine, that is the point
    return removed


RELEASE_ATTEMPTS = 6
RELEASE_BACKOFF = 0.02


def release(slot: Path, log=None, attempts: int = RELEASE_ATTEMPTS,
            backoff: float = RELEASE_BACKOFF) -> bool:
    """Give up a slot we hold. Returns True only if the lockfile is GONE.

    Windows refuses the holder's unlink while any waiter has the lock open for
    reading - is_stale -> _read -> Path.read_text opens the file without
    FILE_SHARE_DELETE - so a release can fail through no fault of the holder
    (measured: PermissionError, WinError 32). The reader's handle lives for
    microseconds, so a short bounded retry clears nearly all of it (measured:
    the unlink succeeds the moment the reader closes).

    If it STILL cannot be deleted, neutralise the payload rather than leave a
    live-looking orphan. This is the part that matters: a leaked lock keeps the
    pid and ts written at hold() entry, so both fast arms of is_stale answer
    "not stale" and reap() skips it - the fail-open valve disarmed by exactly
    the case that produces the leak. A caller running many cycles under one pid
    then loses that lane for the whole run. Zeroing ts and pid makes the next
    reap() take it immediately.

    The neutralising write is IN PLACE, deliberately not the usual
    tmp-then-replace: measured on Windows, os.replace onto a file held open by a
    reader fails (WinError 5) while an in-place write succeeds. A torn write is
    safe in this one direction - _read returns {} and is_stale falls back to
    mtime, which reports stale too.
    """
    for i in range(max(1, attempts)):
        try:
            slot.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if i + 1 < max(1, attempts):
                time.sleep(backoff)
    rec = _read(slot)
    rec.update({"pid": 0, "ts": 0.0, "orphaned": True})
    try:
        with open(slot, "w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        if log:
            log(f"slots: WARNING release of {slot.name} failed - lock neutralised "
                f"for the next reap (it is NOT released)")
    except OSError:
        if log:
            log(f"slots: WARNING release of {slot.name} failed AND it could not be "
                f"neutralised - the lane is held until stale_after elapses")
    return False


def try_acquire(root: Path, max_slots: int, payload: dict) -> Path | None:
    """One non-blocking pass over the bucket. Returns the slot path or None."""
    root.mkdir(parents=True, exist_ok=True)
    for i in range(max_slots):
        p = root / f"{i}.lock"
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        except OSError:
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError:
            try:
                p.unlink()
            except OSError:
                pass
            continue
        return p
    return None


@contextmanager
def hold(max_slots: int = 2, *, repo: str = "", run_id: str = "", cycle: int = 0,
         root: Path | None = None, stale_after: float = DEFAULT_STALE_AFTER,
         timeout: float | None = None, backoff: float = 2.0,
         jitter: float = 2.0, log=None):
    """Hold one slot for the duration of the block.

    Blocks with jittered backoff until a slot frees, reaping stale locks each
    pass. Raises SlotTimeout if `timeout` elapses first - callers treat that as
    a failed cycle, never as permission to proceed unslotted.
    """
    root = Path(root) if root is not None else DEFAULT_ROOT
    payload = {"pid": os.getpid(), "repo": repo, "run_id": run_id,
               "cycle": cycle, "ts": time.time()}
    deadline = None if timeout is None else time.time() + timeout
    slot = None
    waited = False
    while True:
        slot = try_acquire(root, max_slots, payload)
        if slot is not None:
            break
        if reap(root, max_slots, stale_after, log):
            continue  # a slot just freed - retry immediately, do not sleep
        if deadline is not None and time.time() >= deadline:
            raise SlotTimeout(
                f"no slot free within {timeout}s (max_slots={max_slots}, root={root})")
        if not waited and log:
            log(f"slots: all {max_slots} busy - waiting")
            waited = True
        time.sleep(backoff + random.random() * jitter)
    try:
        if log:
            log(f"slots: acquired {slot.name} (run_id={run_id} cycle={cycle})")
        yield slot
    finally:
        # The log must not claim a release that did not happen: this line used
        # to sit outside the try, so an ACQUIRED/RELEASED pairing analysis read
        # perfectly clean while a lane was stuck.
        if release(slot, log=log) and log:
            log(f"slots: released {slot.name}")
