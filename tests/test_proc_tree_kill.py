"""ops/loop/proc_tree.py (s158 C9): a lane worker's timeout kill ends its WHOLE tree, a
process that left that tree included.

Measured 2026-11-09: queue cycle s144q227 was timeout_killed at 9000 s by the s144 driver's
`taskkill /F /T /PID <runner>`, and a pytest the worker had started still wrote its 221.56 s
summary 26 s later. Reproduced here with real processes, on the two ways a worker's
grandchild leaves the tree: the kit's spawn job (KILL_ON_JOB_CLOSE | BREAKAWAY_OK) lets a
process started with CREATE_BREAKAWAY_FROM_JOB leave it (Git Bash's MSYS2 runtime does that
for every native program it starts), and once that process's parent has exited, taskkill /T
(a parent-pid walk) cannot reach it either. The positive control proves the old kill path
misses it; the fix holds the runner in a job of the driver's own with no breakaway.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from ops.loop import proc_tree as PT

REPO_ROOT = Path(__file__).resolve().parent.parent
WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000
win_only = pytest.mark.skipif(not WIN, reason="Windows job objects and taskkill")

GIT_BASH = next((p for p in (r"C:\Program Files\Git\usr\bin\bash.exe",
                             r"C:\Program Files\Git\bin\bash.exe") if Path(p).is_file()), None)

# The grandchild: writes its pid, then lives long enough to be seen surviving.
GRANDCHILD = (
    "import os, sys, time\n"
    "tmp = sys.argv[1] + '.tmp'\n"
    "open(tmp, 'w').write(str(os.getpid()))\n"
    "os.replace(tmp, sys.argv[1])\n"
    "time.sleep(90)\n"
)

# The fake worker: holds a job with the kit's flags (ops/fleet_kit/fleet_headless.py
# _WinJob: _JOB_KILL_ON_CLOSE | _JOB_BREAKAWAY_OK), starts an intermediate in it that
# starts the grandchild out of that job and exits at once (the grandchild is orphaned),
# then sleeps like a long verifier round.
WORKER = r"""
import ctypes, os, subprocess, sys, time
from ctypes import wintypes

mode, grandchild, pidfile, bash = sys.argv[1:5]
NO_WINDOW, SUSPENDED, BREAKAWAY = 0x08000000, 0x00000004, 0x01000000


class _Basic(ctypes.Structure):
    _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD),
                ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]


class _Ext(ctypes.Structure):
    _fields_ = [("Basic", _Basic), ("io", ctypes.c_uint64 * 6), ("p", ctypes.c_size_t),
                ("j", ctypes.c_size_t), ("pp", ctypes.c_size_t), ("pj", ctypes.c_size_t)]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wintypes.DWORD)
k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
nt = ctypes.WinDLL("ntdll")
nt.NtResumeProcess.argtypes = (ctypes.c_void_p,)
job = k32.CreateJobObjectW(None, None)
info = _Ext()
info.Basic.LimitFlags = 0x2000 | 0x0800  # the kit's KILL_ON_JOB_CLOSE | BREAKAWAY_OK
assert k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
if mode == "breakaway":
    # an intermediate starts it with CREATE_BREAKAWAY_FROM_JOB, then exits
    starter = ("import subprocess, sys; subprocess.Popen(sys.argv[1:], creationflags=%d, "
               "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
               "stderr=subprocess.DEVNULL)" % (NO_WINDOW | BREAKAWAY))
    cmd = [sys.executable, "-c", starter, sys.executable, grandchild, pidfile]
else:  # gitbash: the real MSYS2 runtime starts it; then the shell is killed under it
    cmd = [bash, "-c", "'%s' '%s' '%s'" % (sys.executable, grandchild, pidfile)]
p = subprocess.Popen(cmd, creationflags=NO_WINDOW | SUSPENDED, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
assert k32.AssignProcessToJobObject(job, int(p._handle))
nt.NtResumeProcess(ctypes.c_void_p(int(p._handle)))
if mode != "breakaway":  # like a tool timeout that kills the shell, not its tree
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not os.path.exists(pidfile):
        time.sleep(0.05)
    p.kill()
p.wait()
time.sleep(90)
"""


def _psutil():
    return pytest.importorskip("psutil")


def _write_scripts(tmp_path):
    (tmp_path / "grandchild.py").write_text(GRANDCHILD, encoding="ascii", newline="\n")
    (tmp_path / "worker.py").write_text(WORKER, encoding="ascii", newline="\n")
    return tmp_path / "grandchild.py", tmp_path / "worker.py", tmp_path / "grandchild.pid"


def _start_worker(tmp_path, mode, job=None):
    grandchild, worker, pidfile = _write_scripts(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(worker), mode, str(grandchild), str(pidfile), GIT_BASH or "-"],
        creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    if job is not None:
        assert job.adopt(proc), "the runner stand-in could not join the kill job"
    return proc, pidfile


def _grandchild(pidfile, within=30.0):
    """(pid, create_time) of the orphaned grandchild, once its parent has exited."""
    psutil = _psutil()
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if pidfile.is_file():
            pid = int(pidfile.read_text(encoding="ascii"))
            proc = psutil.Process(pid)
            ctime = proc.create_time()
            while time.monotonic() < deadline:  # the intermediate exits right after
                parent = proc.parent()
                if parent is None or parent.create_time() > ctime:
                    return pid, ctime
                time.sleep(0.1)
            break
        time.sleep(0.1)
    pytest.fail("the fake worker's grandchild did not start and orphan in time")


def _alive(pid, ctime):
    psutil = _psutil()
    try:
        return psutil.Process(pid).create_time() == ctime
    except psutil.Error:
        return False


def _gone_within(pid, ctime, within):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not _alive(pid, ctime):
            return True
        time.sleep(0.1)
    return not _alive(pid, ctime)


def _reap(pid, ctime, proc, job=None):
    psutil = _psutil()
    if _alive(pid, ctime):
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass
    if proc.poll() is None:
        proc.kill()
    if job is not None:
        job.close(kill=True)


@win_only
@pytest.mark.parametrize("mode", ["breakaway", "gitbash"])
def test_positive_control_taskkill_tree_alone_misses_the_orphan(tmp_path, mode):
    """The old driver kill (taskkill /F /T on the runner) leaves the orphan running, and
    the kit-like job the worker held does not take it down either."""
    if mode == "gitbash" and GIT_BASH is None:
        pytest.skip("Git Bash not installed")
    proc, pidfile = _start_worker(tmp_path, mode)
    pid, ctime = _grandchild(pidfile)
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       timeout=30, creationflags=NO_WINDOW)
        proc.wait(timeout=15)
        time.sleep(1.5)
        assert _alive(pid, ctime), "control failed: taskkill /T reached the orphan"
    finally:
        _reap(pid, ctime, proc)


@win_only
@pytest.mark.parametrize("mode", ["breakaway", "gitbash"])
def test_kill_tree_with_the_job_ends_the_orphan_too(tmp_path, mode):
    if mode == "gitbash" and GIT_BASH is None:
        pytest.skip("Git Bash not installed")
    job = PT.KillJob.create()
    assert job is not None
    proc, pidfile = _start_worker(tmp_path, mode, job=job)
    pid, ctime = _grandchild(pidfile)
    try:
        assert pid in job.pids(), "the orphan left the driver's job"
        result = PT.kill_tree(proc.pid, job=job)
        assert _gone_within(pid, ctime, within=15.0), "the orphan survived the kill"
        proc.wait(timeout=15)
        assert result["job"] is True
        assert result["survivors"] == []
        assert job.pids() == []
    finally:
        _reap(pid, ctime, proc, job)


@win_only
def test_closing_the_job_after_a_normal_end_leaves_survivors_alone(tmp_path):
    """close(kill=False) clears kill-on-close first, as the kit does after a clean run:
    only the timeout path (and the driver dying) ends the tree."""
    job = PT.KillJob.create()
    proc, pidfile = _start_worker(tmp_path, "breakaway", job=job)
    pid, ctime = _grandchild(pidfile)
    try:
        job.close(kill=False)
        time.sleep(1.0)
        assert _alive(pid, ctime)
        assert job.pids() == [] and job.kill() is False  # a closed job is inert
    finally:
        _reap(pid, ctime, proc)


@win_only
def test_the_driver_dying_closes_the_job_and_ends_the_tree(tmp_path):
    """KILL_ON_JOB_CLOSE: if the process holding the job dies (a crash, or the rotator's
    backstop taskkill of the child driver), the OS ends everything in it."""
    psutil = _psutil()
    holder_src = (
        "import subprocess, sys, time\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from ops.loop import proc_tree as PT\n"
        "job = PT.KillJob.create()\n"
        "p = subprocess.Popen([sys.executable] + sys.argv[1:], creationflags=0x08000000,\n"
        "                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        "                     stderr=subprocess.DEVNULL)\n"
        "assert job.adopt(p)\n"
        "time.sleep(90)\n")
    grandchild, worker, pidfile = _write_scripts(tmp_path)
    (tmp_path / "holder.py").write_text(holder_src, encoding="ascii", newline="\n")
    holder = subprocess.Popen(
        [sys.executable, str(tmp_path / "holder.py"), str(worker), "breakaway",
         str(grandchild), str(pidfile), "-"], creationflags=NO_WINDOW,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid, ctime = _grandchild(pidfile)
    try:
        psutil.Process(holder.pid).kill()  # TerminateProcess: no cleanup code runs
        holder.wait(timeout=15)
        assert _gone_within(pid, ctime, within=15.0)
    finally:
        _reap(pid, ctime, holder)


@win_only
def test_kill_tree_without_a_job_is_the_old_taskkill_path(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    try:
        result = PT.kill_tree(proc.pid)
        assert proc.wait(timeout=15) is not None
        assert result == {"job": False, "taskkill_rc": 0, "survivors": None}
    finally:
        if proc.poll() is None:
            proc.kill()


def test_adopt_refuses_a_stand_in_without_a_process_handle():
    job = PT.KillJob.create()
    if job is None:
        assert not WIN
        return
    try:
        assert job.adopt(object()) is False
    finally:
        job.close(kill=False)


def test_create_returns_none_off_windows(monkeypatch):
    monkeypatch.setattr(PT, "_IS_WINDOWS", False)
    assert PT.KillJob.create() is None


@win_only
def test_the_job_kills_on_close_and_never_allows_breakaway():
    """Read back from the OS: a breakaway-OK job is the defect this module fixes."""
    job = PT.KillJob.create()
    try:
        flags = job.limit_flags()
        assert flags & 0x2000, "KILL_ON_JOB_CLOSE missing"
        assert not flags & 0x0800 and not flags & 0x1000, "the job allows breakaway"
    finally:
        job.close(kill=False)
