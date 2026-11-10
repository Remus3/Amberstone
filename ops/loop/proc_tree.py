"""Kill a lane worker's WHOLE process tree on Windows, a process that left it included
(s158 C9). The s144 lane driver is a gitignored one-off; this is its tested kill helper.

Measured 2026-11-09: queue cycle s144q227 hit its 9000 s timeout and the driver ran
`taskkill /F /T /PID <runner>`; a pytest the worker had started still wrote its 221.56 s
summary (_scratch/q173/green29.txt) 26 s after the kill. Reproduced with real processes
(tests/test_proc_tree_kill.py):
- the kit's spawn job (fleet_headless._WinJob: KILL_ON_JOB_CLOSE plus breakaway allowed)
  does not keep a native program that Git Bash's MSYS2 runtime starts: IsProcessInJob
  reads False for it, so the job closing (the kit's python dying in the tree kill) leaves
  it running;
- taskkill /T walks parent pids, so once that program's shell parent is gone (a tool
  timeout that kills the shell, a background "&" job) the walk cannot reach it either.
A job owned by the driver, with KILL_ON_JOB_CLOSE and NO breakaway, holding the runner
does keep it: MSYS2 still starts the program (no CreateProcess failure), it leaves only
the kit's nested job, and TerminateJobObject ends it.

Use: job = KillJob.create() (None off Windows or on any failure); job.adopt(popen) right
after the runner's Popen (its children inherit the membership; the runner starts nothing
in the microseconds before); kill_tree(pid, job=job) on a timeout; job.close(kill=False)
after a normal end, which swaps kill-on-close for breakaway-OK first (the kit's clean-run
rule) so survivors of a clean run stay as they always did. If the process holding the job
dies, the OS ends the tree.

Stdlib only, ASCII only; imports cleanly on any platform.
"""
from __future__ import annotations

import contextlib
import math
import os
import subprocess
import sys
import time
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"
JOB_KILL_ON_CLOSE = 0x2000
# Set ONLY by close(kill=False), after a clean run, never while the run is live.
JOB_BREAKAWAY_OK_AFTER_CLEAN_END = 0x0800
_EXTENDED_LIMITS = 9         # JobObjectExtendedLimitInformation
_BASIC_PROCESS_ID_LIST = 3    # JobObjectBasicProcessIdList
_ERROR_MORE_DATA = 234
_PID_SLOTS = 4096
_NO_WINDOW = 0x08000000
_K32 = None
# S144-T-731: kill_tree's inputs are bounded. A pid outside 1.._PID_MAX never reaches a
# kill; grace_s is clamped to 0.._GRACE_MAX_S (junk or NaN = the default) so a job that
# will not empty cannot hold the caller forever; poll_s is clamped to the poll band (junk
# or NaN = the default) so the sweep never busy-spins or makes time.sleep raise.
_PID_MAX = 2 ** 31 - 1
_GRACE_DEFAULT_S = 10.0
_GRACE_MAX_S = 300.0
_POLL_DEFAULT_S = 0.1
_POLL_MIN_S = 0.01
_POLL_MAX_S = 1.0


def _kernel32():
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD)
        k32.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.c_void_p)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        _K32 = k32
    return _K32


def _ext_limits():
    """A JOBOBJECT_EXTENDED_LIMIT_INFORMATION instance."""
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Ext(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    return _Ext()


class KillJob:
    """A Windows job object that ends everything in it. KILL_ON_JOB_CLOSE and no
    breakaway limit of any kind, so nothing created inside can leave it."""

    def __init__(self, k32, handle):
        self._k32, self.handle = k32, handle

    @classmethod
    def create(cls):
        if not _IS_WINDOWS:
            return None
        try:
            k32 = _kernel32()
        except (OSError, AttributeError, ImportError):
            return None
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            return None
        job = cls(k32, handle)
        try:
            if not job._set_limits(JOB_KILL_ON_CLOSE):
                raise OSError(f"SetInformationJobObject failed ({_last_error()})")
        except (OSError, ValueError):
            k32.CloseHandle(handle)
            return None
        return job

    def _set_limits(self, flags) -> bool:
        import ctypes
        info = _ext_limits()
        info.BasicLimitInformation.LimitFlags = flags
        return bool(self._k32.SetInformationJobObject(
            self.handle, _EXTENDED_LIMITS, ctypes.byref(info), ctypes.sizeof(info)))

    def limit_flags(self):
        """The job's LimitFlags as the OS reports them, or None."""
        if not self.handle:
            return None
        import ctypes
        info = _ext_limits()
        if not self._k32.QueryInformationJobObject(self.handle, _EXTENDED_LIMITS,
                                                   ctypes.byref(info), ctypes.sizeof(info),
                                                   None):
            return None
        return int(info.BasicLimitInformation.LimitFlags)

    def adopt(self, proc) -> bool:
        """Put a Popen's process (and so every process it starts from now on) in the job.
        Only a handle this caller holds, never a pid. False for a stand-in or a refusal."""
        ph = getattr(proc, "_handle", None)
        if not self.handle or ph is None:
            return False
        try:
            return bool(self._k32.AssignProcessToJobObject(self.handle, int(ph)))
        except (OSError, TypeError, ValueError):
            return False

    def pids(self) -> list:
        """Ids of the processes still in the job ([] once it is empty or closed)."""
        if not self.handle:
            return []
        import ctypes
        from ctypes import wintypes

        class _List(ctypes.Structure):
            _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD),
                        ("NumberOfProcessIdsInList", wintypes.DWORD),
                        ("ProcessIdList", ctypes.c_size_t * _PID_SLOTS)]

        buf = _List()
        if not self._k32.QueryInformationJobObject(self.handle, _BASIC_PROCESS_ID_LIST,
                                                   ctypes.byref(buf), ctypes.sizeof(buf),
                                                   None) \
                and ctypes.get_last_error() != _ERROR_MORE_DATA:
            raise OSError(f"QueryInformationJobObject failed ({_last_error()})")
        return [int(buf.ProcessIdList[i])
                for i in range(min(int(buf.NumberOfProcessIdsInList), _PID_SLOTS))]

    def kill(self) -> bool:
        """TerminateJobObject: every process in the job, at once. False if closed."""
        if not self.handle:
            return False
        try:
            return bool(self._k32.TerminateJobObject(self.handle, 1))
        except OSError:
            return False

    def close(self, kill: bool) -> bool:
        """kill=True ends the tree first; kill=False swaps kill-on-close for breakaway-OK
        first, exactly the kit's _WinJob.close(kill=False), so the processes still in the
        job outlive the handle and are as free as they were before this job existed.

        Returns True when the requested outcome holds. kill=True is always True on an open
        job: closing the last handle of a kill-on-close job ends the tree even when
        TerminateJobObject was refused. kill=False is False when the OS refused the swap
        (S144-T-731): kill-on-close is then still set, so closing the handle ENDS the
        processes still in the job, and the caller should log that. False on a job that
        is already closed (nothing is done)."""
        if not self.handle:
            return False
        ok = False
        try:
            if kill:
                self.kill()
                ok = True
            else:
                with contextlib.suppress(OSError):
                    ok = self._set_limits(JOB_BREAKAWAY_OK_AFTER_CLEAN_END)
        finally:
            self._k32.CloseHandle(self.handle)
            self.handle = None
        return ok


def _last_error() -> int:
    import ctypes
    return ctypes.get_last_error()


def _taskkill_exe() -> str:
    root = os.environ.get("SYSTEMROOT")
    return str(Path(root) / "System32" / "taskkill.exe") if root else "taskkill"


def _valid_pid(pid):
    """`pid` if it is a plain int in 1.._PID_MAX, else None. Never coerced: 0 and the
    negatives are process GROUPS to os.kill (0 = the caller's own group, -1 = every
    process the caller may signal), a bool is not a pid, and a value past pid_t makes
    os.kill raise OverflowError."""
    if isinstance(pid, bool) or not isinstance(pid, int):
        return None
    return pid if 0 < pid <= _PID_MAX else None


def _bounded_s(value, default: float, low: float, high: float) -> float:
    """A seconds argument as a float clamped to low..high; a bool, a non-number or NaN
    is `default`, +inf (or an int too large for a float) is `high`, -inf `low`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        value = float(value)
    except OverflowError:  # an int past float range
        return high if value > 0 else low
    if math.isnan(value):  # value is a float here
        return default
    return min(high, max(low, value))


def kill_tree(pid: int, job: KillJob | None = None, grace_s: float = _GRACE_DEFAULT_S,
              poll_s: float = _POLL_DEFAULT_S) -> dict:
    """End `pid` and everything it started. First the old path, unchanged:
    `taskkill /F /T /PID pid`, a parent-pid walk run while the root still lives (the
    caller holds its Popen, so the pid cannot be reused). Then, with a job, the sweep
    that walk cannot do: TerminateJobObject, repeated until the job is empty or grace_s
    runs out, which ends a process whose parent had already exited. Returns {"job":
    used a job, "taskkill_rc": its exit code or None, "survivors": pids still in the job
    at the end ([] = all gone) or None without a job / when the list is unreadable}.

    S144-T-731: a pid that is not a plain int in 1.._PID_MAX reaches no kill at all
    (taskkill_rc None) but the job sweep still runs, since the job, not the pid, is what
    reaches an orphan; grace_s is clamped to 0.._GRACE_MAX_S and poll_s to
    _POLL_MIN_S.._POLL_MAX_S (a junk or NaN value is the default); a job stand-in with no
    handle attribute counts as no job."""
    out = {"job": bool(job is not None and getattr(job, "handle", None)),
           "taskkill_rc": None, "survivors": None}
    target = _valid_pid(pid)
    if target is not None and _IS_WINDOWS:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            out["taskkill_rc"] = subprocess.run(
                [_taskkill_exe(), "/F", "/T", "/PID", str(target)], capture_output=True,
                timeout=30, creationflags=_NO_WINDOW, check=False).returncode
    elif target is not None:
        import signal
        with contextlib.suppress(OSError):
            os.kill(target, getattr(signal, "SIGKILL", signal.SIGTERM))
    if not out["job"]:
        return out
    grace = _bounded_s(grace_s, _GRACE_DEFAULT_S, 0.0, _GRACE_MAX_S)
    poll_s = _bounded_s(poll_s, _POLL_DEFAULT_S, _POLL_MIN_S, _POLL_MAX_S)
    deadline = time.monotonic() + grace
    try:
        while True:
            job.kill()
            left = job.pids()
            if not left or time.monotonic() >= deadline:
                break
            time.sleep(poll_s)
        out["survivors"] = left
    except OSError:
        out["survivors"] = None
    return out
