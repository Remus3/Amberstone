# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v20 - RACE GUARDS: the machine-wide whole-suite gate (FLEET-COMMON 16).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: whole test suites from several trees ran at once on one box. Four
concurrent suites lost xdist workers, and timing tests flaked under the load:
the number graded was the sibling load, not the code.

    python fleet_suite_gate.py run --owner <session_id>.<agent_id> [--slots N]
                                   [--timeout S] -- <suite cmd>
    python fleet_suite_gate.py status

`run`:
  1. refuses (exit 3) while the tree holds uncommitted edits to a path claimed
     in fleet_claims by a live owner other than --owner (env FLEET_CLAIM_OWNER):
     a run straddling an edit says nothing. v14 (KIT-14): only TEST-RELEVANT
     paths count - anything under a tests/ directory, conftest*, pytest /
     project config and requirements files, and every other path except
     docs/ and prose (.md .rst .adoc .txt); another agent's doc or ROADMAP
     edit no longer blocks the suite;
  2. takes one of N machine-wide slots - N = --slots, else env
     FLEET_SUITE_SLOTS, default 2 (v13; was 1), at most MAX_SLOTS - as
     <dir>/slot-<k>.lock by exclusive create, holder {pid, pid_started, start};
     <dir> = env FLEET_SUITE_DIR, else %LOCALAPPDATA%/fleet/suite (POSIX:
     ~/.cache/fleet/suite). A slot whose pid is dead or provably reused is
     broken. v13 FIFO: a waiter first takes a queue ticket
     <dir>/queue/t-<ns>-<pid>.json and may take a slot only while its ticket
     is among the oldest LIVE tickets that fit the free slots, so the oldest
     waiter is served first and none is starved; a ticket whose pid is dead
     or reused is dropped. While waiting it prints a progress line to stderr every 30 s;
     after --timeout (default 3600 s) it FAILS CLOSED (exit 3) without running;
  3. re-checks 1 inside the slot, runs the suite (env FLEET_SUITE_SLOT=k),
     releases the slot, exits with the suite's code. v14: the suite starts
     with CREATE_NO_WINDOW when this process has no visible console
     (fleet_gitlock.quiet_inherit; LW 0000), its output still inherited; a
     relative command path (env/Scripts/python.exe) is anchored to the cwd
     (resolve_exe; was WinError 2).

v15 (KIT-15; ruling MACH-ENH-2, MAIN docs/suite-gate-waits.md):
  4. every run appends ONE line to <dir>/durations.jsonl: {ts, tree (the main
     checkout's folder name), cmd (sha256 of the command words, 16 hex), slot,
     lane, wait_s, hold_s, exit}; a write failure never fails the suite;
  5. SHORT-SUITE LANE: one extra slot, index = N (the regular slot count),
     only while N < MAX_SLOTS (MAX_SLOTS includes the lane). A (tree, cmd)
     whose median hold over its last LANE_WINDOW runs (at least LANE_MIN_RUNS)
     is <= LANE_MAX_S may take the lane slot when no regular slot is free to
     it; unknown or longer commands stay FIFO on the N regular slots, which
     count only indices < N. A lane holder that runs past LANE_OVERRUN_S
     finishes normally; its line carries "overrun": true and a stderr line
     says so, and its own record then moves it to the regular slots.

v16 (KIT-16; KIT-15 adjudication c9836ae):
  6. resolve_exe never answers from the working directory (CS 2304): on
     Windows a BARE command word is replaced by its full path found on PATH
     ONLY - empty, relative and cwd-equal PATH entries skipped, PATHEXT
     tried - because shutil.which and CreateProcess both search the cwd
     first, so a planted python.exe / npm.cmd in the tree would run. A bare
     word found nowhere on PATH is refused (exit 3), never left to
     CreateProcess. Off Windows a bare word is left as given (execvp does
     not search the cwd). Relative path words are anchored as in v14;
  7. a path-free pytest run is refused (exit 3) ONLY when the tree has no
     testpaths config (RC 1925 b): the command runs pytest (`pytest`,
     `py.test`, `python -m pytest`), names no path (no positional word
     with a / or \\, .py or ::, and none that exists under the cwd), is not
     an info call (--version, --help, --collect-only, ...), AND no
     `testpaths` is set in pytest.ini [pytest], pyproject.toml
     [tool.pytest.ini_options], tox.ini [pytest] or setup.cfg [tool:pytest]
     in the cwd or any parent up to the tree top (or in the -c file). Such
     a run collects the whole tree - lane worktrees and sidecars included.

v18 (CS FIX 2026-10-14-1840): the bare word is resolved against the CHILD's
PATH (the env run() hands to subprocess.run), cwd excluded, so from a venv a
bare `python` is the venv interpreter on that PATH - CreateProcess would
otherwise search the gate's own image folder (the BASE interpreter) first.

v18 KIT-15-REPICK (ruling MAIN docs/rulings/2026-10-17-kit-15.md): the lane
thresholds are re-picked from 7 days of durations.jsonl - LANE_MAX_S 130 s
(was 120), LANE_OVERRUN_S 200 s (was 240). Both stay hard-coded.

v18 RM737-GATE (ruling MAIN docs/rulings/2026-10-10-rc-rm737-memory-gate.md):
  8. every durations line gains peak_commit_mb: the peak private commit of
     the suite's whole process tree, sampled every SAMPLE_S (2 s) with
     ctypes on Windows (omitted elsewhere, or when the runner is injected);
     sampling never fails the suite;
  9. COMMIT-AWARE ADMISSION before taking ANY slot, regular or lane: free
     commit (CommitLimit - CommitTotal, GetPerformanceInfo) must be >=
     required + margin; required = median peak_commit_mb of the (tree,
     cmd)'s last COMMIT_WINDOW runs (at least COMMIT_MIN_RUNS) else
     COMMIT_DEFAULT_MB (8 GiB); margin COMMIT_MARGIN_MB (4 GiB) or env
     FLEET_SUITE_COMMIT_MARGIN_MB. A waiter short of commit keeps its
     ticket (passable since KIT-GATE-HOL, below), and its 30 s wait line
     names "commit" and the shortfall. The
     WAIT_S fail-closed timeout still applies. Where commit cannot be read
     (POSIX, an API error) admission is a no-op.
KIT-GATE-HOL (FIX, train-exempt; MAIN ROADMAP S49): head-of-line. A waiter
short of commit used to block the whole FIFO even with a slot free (2026-10-18:
lane-eligible LW and MAIN runs waited 827-1477 s behind an RC -n 8 suite at
23.7 GB peak commit).
 10. a waiter that finds itself short of commit marks its ticket
     {"short": true} (atomic replace) and clears the mark once it fits; a
     marked ticket is not counted ahead, so a later waiter that fits runs
     past it. FIFO still holds among the waiters that fit, and an unmarked
     live ticket is never passed. BYPASS AGE CAP: a short ticket older than
     BYPASS_MAX_S (900 s; env FLEET_SUITE_BYPASS_MAX_S), aged from its name
     stamp, counts as ahead again, so the queue drains commit for it instead
     of starving it to the WAIT_S fail-close. The queue sweep also removes
     stray t-*.json.tmp files older than TMP_STALE_S (1 h);
 11. the durations line gains commit_wait_s (seconds spent short of commit)
     when it is above 0, so slot waits and commit waits can be told apart.
Pure stdlib plus the sibling kit files fleet_claims.py and fleet_gitlock.py.
"""

import contextlib
import hashlib
import importlib.util
import configparser
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ENV_DIR = "FLEET_SUITE_DIR"
ENV_SLOTS = "FLEET_SUITE_SLOTS"
DEFAULT_SLOTS = 2
MAX_SLOTS = 4
QUEUE = "queue"
DURATIONS = "durations.jsonl"
LANE_MAX_S = 130.0  # v18 KIT-15-REPICK (was 120)
LANE_OVERRUN_S = 200.0  # v18 KIT-15-REPICK (was 240)
ENV_COMMIT_MARGIN = "FLEET_SUITE_COMMIT_MARGIN_MB"
COMMIT_MARGIN_MB = 4096
COMMIT_DEFAULT_MB = 8192
COMMIT_WINDOW = 5
COMMIT_MIN_RUNS = 3
SAMPLE_S = 2.0
LANE_MIN_RUNS = 3
LANE_WINDOW = 5
DURATIONS_TAIL_BYTES = 1 << 20
WAIT_S = 3600.0
ENV_BYPASS_MAX = "FLEET_SUITE_BYPASS_MAX_S"
BYPASS_MAX_S = 900.0  # KIT-GATE-HOL: a short ticket is passable this long
TMP_STALE_S = 3600.0
PROGRESS_EVERY_S = 30.0
POLL_S = 1.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class GateRefused(RuntimeError):
    """No slot in time, or a claim straddles the run."""


def _sibling(name):
    key = "fleet_kit_" + name
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


claims = _sibling("fleet_claims")
gitlock = _sibling("fleet_gitlock")


def gate_dir(env=None):
    env = os.environ if env is None else env
    if env.get(ENV_DIR):
        return Path(env[ENV_DIR])
    base = env.get("LOCALAPPDATA")
    if base:
        return Path(base) / "fleet" / "suite"
    return Path.home() / ".cache" / "fleet" / "suite"


def slots(n=None, env=None):
    env = os.environ if env is None else env
    try:
        v = int(n if n is not None else (env.get(ENV_SLOTS) or DEFAULT_SLOTS))
    except ValueError:
        v = DEFAULT_SLOTS
    return max(1, min(MAX_SLOTS, v))


def _slot(d, k):
    return Path(d) / f"slot-{int(k)}.lock"


def _rec(path):
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def slot_live(path, alive=None, started=None):
    """True while the slot file names a live, unreused holder. A half-written
    file younger than 30 s counts as live."""
    alive = alive or gitlock.pid_alive
    started = started or gitlock.proc_started
    doc = _rec(path)
    if doc is None:
        try:
            return time.time() - path.stat().st_mtime < 30.0
        except OSError:
            return False
    pid = doc.get("pid")
    if not alive(pid):
        return False
    want, have = doc.get("pid_started"), started(pid)
    return not (want is not None and have is not None and abs(float(want) - have) > 1.0)


def held(d, alive=None, started=None, upto=None):
    """Indices of live slots (stale slot files are removed on the way).
    upto=N limits the look to the N regular slots (KIT-15: the lane slot N
    does not count against them)."""
    out = []
    for k in range(MAX_SLOTS if upto is None else min(int(upto), MAX_SLOTS)):
        p = _slot(d, k)
        if not p.exists():
            continue
        if slot_live(p, alive, started):
            out.append(k)
        else:
            with contextlib.suppress(OSError):
                p.unlink()
    return out


def try_slot(d, n, pid=None, alive=None, started=None, clock=time.time):
    """(k, raw) for a slot taken now, or None."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    started = started or gitlock.proc_started
    if len(held(d, alive, started, upto=n)) >= n:
        return None
    for k in range(n):
        p = _slot(d, k)
        raw = json.dumps({"pid": pid, "pid_started": started(pid), "start": clock(),
                          "n": int(n)}, sort_keys=True).encode("ascii")
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            continue
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
        if len(held(d, alive, started, upto=n)) > n:  # a wider runner raced us
            release(d, k, raw)
            return None
        return k, raw
    return None


def lane_index(n):
    """The short-suite lane slot for N regular slots, or None when N already
    uses every slot MAX_SLOTS allows (the lane is inside MAX_SLOTS)."""
    return int(n) if int(n) < MAX_SLOTS else None


def try_lane(d, n, pid=None, alive=None, started=None, clock=time.time, ticket=None):
    """(k, raw) for the lane slot taken now, or None (KIT-15). v20 (LW 1120):
    refused while slot k is a REGULAR slot for any other live ticket (its N
    is above k), so a narrower runner's lane never takes a wider waiter's slot."""
    k = lane_index(n)
    if k is None:
        return None
    if any(tn > k for tn in live_ticket_ns(d, alive, started, exclude=ticket)):
        return None
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    started = started or gitlock.proc_started
    p = _slot(d, k)
    if p.exists():
        if slot_live(p, alive, started):
            return None
        with contextlib.suppress(OSError):
            p.unlink()
    raw = json.dumps({"pid": pid, "pid_started": started(pid), "start": clock(),
                      "lane": True, "n": int(n)}, sort_keys=True).encode("ascii")
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return None
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    return k, raw


def release(d, k, raw):
    p = _slot(d, k)
    with contextlib.suppress(OSError):
        if p.read_bytes() == raw:
            p.unlink()


def _say(msg):
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


# ---------------------------------------------------------------- FIFO queue (v13)

def take_ticket(d, pid=None, started=None, ns=None, n=None):
    """Create this waiter's queue ticket; returns its path. v20 (LW 1120): the
    ticket carries the waiter's slot count "n" (default DEFAULT_SLOTS)."""
    q = Path(d) / QUEUE
    q.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    started = started or gitlock.proc_started
    raw = json.dumps({"pid": pid, "pid_started": started(pid),
                      "n": int(n) if n is not None else DEFAULT_SLOTS}, sort_keys=True)
    while True:
        stamp = time.time_ns() if ns is None else ns
        p = q / f"t-{stamp:020d}-{pid}.json"
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if ns is not None:
                ns += 1
            continue
        try:
            os.write(fd, raw.encode("ascii"))
        finally:
            os.close(fd)
        return p


def drop_ticket(ticket):
    with contextlib.suppress(OSError):
        Path(ticket).unlink()


def ticket_n(ticket):
    """The slot count a ticket was filed with; a ticket from an older kit (no
    "n") or with a bad value counts as DEFAULT_SLOTS."""
    doc = _rec(Path(ticket))
    v = doc.get("n") if doc else None
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= MAX_SLOTS:
        return DEFAULT_SLOTS
    return v


def live_ticket_ns(d, alive=None, started=None, exclude=None):
    """The "n" of every live ticket in the queue except `exclude`."""
    q = Path(d) / QUEUE
    try:
        names = sorted(x.name for x in q.glob("t-*.json"))
    except OSError:
        return []
    skip = Path(exclude).name if exclude is not None else None
    return [ticket_n(q / name) for name in names
            if name != skip and slot_live(q / name, alive, started)]


def ticket_short(ticket):
    """True when the ticket carries the KIT-GATE-HOL short-of-commit mark."""
    doc = _rec(Path(ticket))
    return bool(doc and doc.get("short") is True)


def mark_ticket(ticket, short):
    """Set or clear the ticket's short-of-commit mark by atomic replace; a
    failed write (a reader holds the file on Windows) is retried next poll."""
    ticket = Path(ticket)
    doc = _rec(ticket)
    if doc is None or bool(doc.get("short")) == bool(short):
        return
    if short:
        doc["short"] = True
    else:
        doc.pop("short", None)
    tmp = ticket.with_name(ticket.name + ".tmp")
    try:
        tmp.write_bytes(json.dumps(doc, sort_keys=True).encode("ascii"))
        os.replace(str(tmp), str(ticket))
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def bypass_max_s(env=None):
    env = os.environ if env is None else env
    try:
        return max(0.0, float(str(env.get(ENV_BYPASS_MAX, "")).strip()))
    except ValueError:
        return BYPASS_MAX_S


def ticket_age_s(name, now):
    """Seconds since the ticket's name stamp (t-<ns>-<pid>.json), or None."""
    try:
        return now - int(str(name).split("-")[1]) / 1e9
    except (IndexError, ValueError):
        return None


def sweep_tmp(q, now=None):
    """Remove stray t-*.json.tmp files (a mark_ticket cut short) older than
    TMP_STALE_S by mtime; never raises."""
    now = time.time() if now is None else now
    try:
        stray = list(Path(q).glob("t-*.json.tmp"))
    except OSError:
        return
    for p in stray:
        with contextlib.suppress(OSError):
            if now - p.stat().st_mtime > TMP_STALE_S:
                p.unlink()


def tickets_ahead(d, ticket, alive=None, started=None, clock=time.time):
    """Paths of the live tickets older than `ticket` that count against it
    (dead / reused ones are removed). KIT-GATE-HOL: a live ticket marked short
    of commit is not counted while younger than bypass_max_s(); stale .tmp
    files are swept on the way."""
    q = Path(d) / QUEUE
    sweep_tmp(q)
    try:
        names = sorted(x.name for x in q.glob("t-*.json"))
    except OSError:
        return []
    now, cap = clock(), bypass_max_s()
    ahead = []
    for name in names:
        if name >= Path(ticket).name:
            break
        if slot_live(q / name, alive, started):
            if not ticket_short(q / name):
                ahead.append(q / name)
            else:
                age = ticket_age_s(name, now)
                if age is None or age > cap:
                    ahead.append(q / name)
        else:
            with contextlib.suppress(OSError):
                (q / name).unlink()
    return ahead


def queue_ahead(d, ticket, alive=None, started=None, clock=time.time):
    """How many live tickets older than `ticket` count against it."""
    return len(tickets_ahead(d, ticket, alive, started, clock))


def acquire(d, n, timeout=WAIT_S, clock=time.time, sleep=time.sleep, alive=None,
            started=None, pid=None, lane=False, commit=None, stats=None, **kw):
    """FIFO: wait for a slot only while no older live waiter could take it.
    lane=True (KIT-15, a known short suite) may also take the lane slot when
    no regular slot is free to it; the lane is not FIFO-ordered.
    v18 (RM737-GATE): commit() -> shortfall in MB (<= 0 or None = enough
    free commit); while short, NO slot is taken (regular or lane) and the
    ticket is kept. KIT-GATE-HOL: while short the ticket is marked, so a later
    waiter that fits may pass it; stats (a dict) gets commit_wait_s."""
    begin = said = clock()
    ticket = take_ticket(d, pid, started, n=n)
    short = 0
    was_short, last, cwait = False, begin, 0.0
    try:
        while True:
            short = (commit() or 0) if commit else 0
            t = clock()
            if was_short:
                cwait += t - last
            last, was_short = t, short > 0
            if stats is not None:
                stats["commit_wait_s"] = cwait
            mark_ticket(ticket, short > 0)
            if short <= 0:
                # v20 (LW 1120): with mixed slot counts the waiter plays by the
                # SMALLEST N among itself and the older waiters it must not
                # pass, so a wider newcomer never takes a narrower waiter's slot.
                ahead = tickets_ahead(d, ticket, alive, started, clock)
                m = min([n] + [ticket_n(t) for t in ahead])
                free = m - len(held(d, alive, started, upto=m))
                if free > 0 and len(ahead) < free:
                    got = try_slot(d, m, pid=pid, alive=alive, started=started, clock=clock,
                                   **kw)
                    if got:
                        return got
                if lane:
                    got = try_lane(d, n, pid=pid, alive=alive, started=started, clock=clock,
                                   ticket=ticket)
                    if got:
                        return got
            now = clock()
            if now - begin >= timeout:
                if short > 0:
                    raise GateRefused(f"SUITE-GATE: free commit still {int(short)} MB short "
                                      f"after {int(timeout)}s; not running the suite")
                raise GateRefused(f"SUITE-GATE: no suite slot free after {int(timeout)}s "
                                  f"({n} of {n} held); not running the suite")
            if now - said >= PROGRESS_EVERY_S:
                said = now
                what = (f"free commit ({int(short)} MB short)" if short > 0
                        else "a suite slot")
                _say(f"suite gate: waiting for {what} ({n} slot(s), "
                     f"{queue_ahead(d, ticket, alive, started, clock)} waiter(s) ahead, "
                     f"{int(now - begin)}s of {int(timeout)}s)")
            sleep(POLL_S)
    finally:
        drop_ticket(ticket)
        with contextlib.suppress(OSError):
            Path(str(ticket) + ".tmp").unlink()


# ---------------------------------------------------------------- commit (v18 RM737-GATE)

def free_commit_mb():
    """CommitLimit - CommitTotal in MB (GetPerformanceInfo), or None where it
    cannot be read (POSIX, an API error): admission is then a no-op."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PI(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD)] + [
                (f, ctypes.c_size_t) for f in (
                    "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
                    "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged",
                    "KernelNonpaged", "PageSize")] + [
                (f, wintypes.DWORD) for f in ("HandleCount", "ProcessCount", "ThreadCount")]

        pi = PI()
        pi.cb = ctypes.sizeof(PI)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k32.K32GetPerformanceInfo(ctypes.byref(pi), pi.cb):
            return None
        return (pi.CommitLimit - pi.CommitTotal) * pi.PageSize / float(1 << 20)
    except (OSError, AttributeError, ValueError):
        return None


def tree_private_mb(root):
    """Private commit (MB) of process `root` and all its descendants, or None
    (Windows only; never raises)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (f, ctypes.c_size_t) for f in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                    "PrivateUsage")]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(PE)]
        k32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(PE)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC),
                                                wintypes.DWORD]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return None
        kids = {}
        try:
            pe = PE()
            pe.dwSize = ctypes.sizeof(PE)
            ok = k32.Process32First(snap, ctypes.byref(pe))
            while ok:
                kids.setdefault(pe.th32ParentProcessID, []).append(pe.th32ProcessID)
                ok = k32.Process32Next(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)
        todo, seen, total = [int(root)], set(), 0
        while todo:
            p = todo.pop()
            if p in seen or p == 0:
                continue
            seen.add(p)
            todo += kids.get(p, [])
            h = k32.OpenProcess(0x1000, False, p)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                continue
            try:
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    total += pmc.PrivateUsage
            finally:
                k32.CloseHandle(h)
        return total / float(1 << 20)
    except (OSError, AttributeError, ValueError, TypeError):
        return None


def commit_margin_mb(env=None):
    env = os.environ if env is None else env
    try:
        v = int(str(env.get(ENV_COMMIT_MARGIN, "")).strip())
        return max(0, v)
    except ValueError:
        return COMMIT_MARGIN_MB


def required_commit_mb(d, tree, chash, window=COMMIT_WINDOW, min_runs=COMMIT_MIN_RUNS):
    """Median peak_commit_mb of the (tree, cmd)'s last `window` sampled runs
    (at least min_runs), else COMMIT_DEFAULT_MB."""
    peaks = [float(r["peak_commit_mb"]) for r in read_durations(d)
             if r.get("tree") == tree and r.get("cmd") == chash
             and isinstance(r.get("peak_commit_mb"), (int, float))][-window:]
    if len(peaks) < min_runs:
        return float(COMMIT_DEFAULT_MB)
    peaks.sort()
    m = len(peaks) // 2
    return peaks[m] if len(peaks) % 2 else (peaks[m - 1] + peaks[m]) / 2.0


def commit_check(need_mb, free=free_commit_mb):
    """A callable for acquire(): shortfall in MB, 0 when free commit covers
    need_mb or cannot be read."""
    def short():
        f = free()
        if f is None:
            return 0
        return max(0.0, need_mb - f)
    return short


class PeakSampler:
    """Samples tree_private_mb(pid) every `every` s on a daemon thread; .peak
    is the max seen (None when nothing could be read). Never raises."""

    def __init__(self, pid, every=SAMPLE_S, probe=None):
        import threading
        self.pid, self.every, self.peak = pid, every, None
        self.probe = probe or tree_private_mb
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _take(self):
        try:
            v = self.probe(self.pid)
        except Exception:  # noqa: BLE001 - sampling never fails the suite
            v = None
        if v is not None and (self.peak is None or v > self.peak):
            self.peak = v

    def _loop(self):
        while True:
            self._take()
            if self._stop.wait(self.every):
                return

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(5)
        return False


def dirty_paths(cwd):
    """Absolute paths with uncommitted changes in the tree at cwd."""
    t = claims.tree_of(cwd)
    if t is None:
        return []
    git = os.environ.get("FLEET_GIT") or "git"
    try:
        r = subprocess.run([git, "-C", str(t[0]), "status", "--porcelain", "-uall"],
                           capture_output=True, text=True, timeout=120,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for ln in r.stdout.splitlines():
        name = ln[3:].split(" -> ")[-1].strip().strip('"')
        if name:
            out.append(Path(t[0]) / name)
    return out


PROSE_SUFFIXES = (".md", ".rst", ".adoc", ".txt")
CONFIG_NAMES = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "package.json",
                "package-lock.json")


def test_relevant(rel):
    """True when an edit at tree-relative path rel can change a suite's result
    (v14 KIT-14): docs/ and prose files cannot; tests, conftest, config,
    requirements and every other path can."""
    rel = str(rel).replace("\\", "/").lower().removeprefix("./")
    parts = rel.split("/")
    name = parts[-1]
    if "tests" in parts[:-1] or "test" in parts[:-1] or name.startswith("conftest"):
        return True
    if name in CONFIG_NAMES or name.startswith("requirements"):
        return True
    if parts[0] == "docs":
        return False
    return not name.endswith(PROSE_SUFFIXES)


def check_straddle(cwd, owner, dirty=dirty_paths, now=None):
    t = claims.tree_of(cwd)
    paths = dirty(cwd)
    if t is not None:
        paths = [p for p in paths if test_relevant(claims.rel_in(p, t[0]))]
    hits = claims.foreign_claims(paths, owner, now)
    if hits:
        where = claims.rel_in(hits[0][0], t[0]) if t else hits[0][0]
        raise GateRefused("SUITE-GATE: {} has uncommitted edits by another live agent; "
                          "a run straddling an edit says nothing - wait for it to commit".format(where))


def parse(argv):
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        raise GateRefused("SUITE-GATE: usage: run [--owner O] [--slots N] [--timeout S] -- <cmd>")
    k = argv.index("--")
    opts, cmd = argv[:k], argv[k + 1:]
    owner, n, timeout = os.environ.get(claims.ENV_OWNER) or None, None, WAIT_S
    i = 0
    while i < len(opts):
        o = opts[i]
        if o == "--owner" and i + 1 < len(opts):
            owner, i = opts[i + 1], i + 2
        elif o.startswith("--owner="):
            owner, i = o.split("=", 1)[1], i + 1
        elif o == "--slots" and i + 1 < len(opts):
            n, i = opts[i + 1], i + 2
        elif o == "--timeout" and i + 1 < len(opts):
            timeout, i = float(opts[i + 1]), i + 2
        else:
            raise GateRefused("SUITE-GATE: unknown option {}".format(o))
    return owner, slots(n), timeout, cmd


def path_which(name, environ=None, cwd=None):
    """Full path of a bare command name from PATH only (v16, CS 2304): empty,
    relative and cwd-equal entries are skipped; PATHEXT is tried on Windows
    (a name that already has an extension is tried as given first). None
    when absent."""
    env = os.environ if environ is None else environ
    try:
        here = os.path.normcase(os.path.realpath(str(cwd or os.getcwd())))
    except OSError:
        here = None
    exts = [""]
    if sys.platform == "win32":
        pe = [e for e in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
        exts = ([""] if Path(name).suffix else []) + pe
    for entry in env.get("PATH", "").split(os.pathsep):
        d = entry.strip().strip('"')
        if not d or not os.path.isabs(d):
            continue
        try:
            if os.path.normcase(os.path.realpath(d)) == here:
                continue
        except OSError:
            continue
        for ext in exts:
            f = Path(d) / (name + ext)
            if f.is_file() and (sys.platform == "win32" or os.access(f, os.X_OK)):
                return str(f)
    return None


def resolve_exe(cmd, cwd, which=None, environ=None):
    """v14 (KIT-13 carry-over): Windows CreateProcess does not find a RELATIVE
    executable path such as env/py312/Scripts/python.exe (WinError 2), so a
    relative path-like command word is anchored to cwd when the file exists
    there (with .exe tried on Windows). Off Windows a bare name is left to
    execvp (PATH only); on Windows it is never left to CreateProcess (below).
    v15 (EW 1955): on Windows a BARE name whose PATH hit is a .cmd/.bat shim
    (npm -> npm.cmd) is replaced by that full path, since CreateProcess finds
    only .exe from a bare name (WinError 2); any other hit is left as given.
    v16 (CS 2304): on Windows EVERY bare name becomes its PATH-only full path
    (path_which; never the cwd), and a bare name not on PATH raises
    GateRefused instead of being left to CreateProcess's cwd-first search.
    v18 (CS 1840): environ = the CHILD's env; its PATH is the one searched
    (cwd still excluded), because CreateProcess searches the parent image's
    folder first - from a venv that is the BASE interpreter's folder."""
    if not cmd:
        return list(cmd)
    w = cmd[0]
    if "/" not in w and "\\" not in w and not Path(w).is_absolute():
        if sys.platform == "win32":
            hit = (which or path_which)(w, environ=environ, cwd=cwd)
            if not hit:
                raise GateRefused("SUITE-GATE: {} is not on PATH; not searching the "
                                  "working directory - give its full path".format(w))
            return [hit, *cmd[1:]]
        return list(cmd)
    if Path(w).is_absolute():
        return list(cmd)
    for cand in (Path(cwd) / w, Path(cwd) / (w + ".exe")):
        if cand.is_file():
            return [str(cand), *cmd[1:]]
    return list(cmd)


# ---------------------------------------------------------------- path-free pytest (v16)

_PYTEST_INFO = frozenset(("--version", "-V", "-h", "--help", "--co", "--collect-only",
                          "--fixtures", "--markers", "--fixtures-per-test"))
_PYTEST_WORD = re.compile(r"(?:^|[/\\])(?:py\.test|pytest)(?:\.exe)?$", re.I)
_TESTPATHS_FILES = (("pytest.ini", "pytest"), ("pyproject.toml", None),
                    ("tox.ini", "pytest"), ("setup.cfg", "tool:pytest"))


def pytest_args(cmd):
    """The words after pytest when cmd runs pytest, else None."""
    for k, w in enumerate(cmd):
        if not _PYTEST_WORD.search(str(w)):
            continue
        if k == 0 or cmd[k - 1] == "-m":
            return [str(x) for x in cmd[k + 1:]]
        return None
    return None


def names_a_path(args, cwd):
    """True when a positional pytest word names a path (or the call is info)."""
    if any(a in _PYTEST_INFO for a in args):
        return True
    for a in args:
        if a.startswith("-"):
            continue
        if "/" in a or "\\" in a or ".py" in a or "::" in a:
            return True
        try:
            if (Path(cwd) / a).exists():
                return True
        except (OSError, ValueError):
            continue
    return False


def _ini_testpaths(path, section):
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(str(path), encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return False
    return cp.has_section(section) and bool(cp.get(section, "testpaths", fallback="").strip())


def _toml_testpaths(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        import tomllib
        doc = tomllib.loads(text)
        opts = doc.get("tool", {}).get("pytest", {}).get("ini_options", {})
        return bool(opts.get("testpaths"))
    except Exception:  # noqa: BLE001 - no tomllib or a bad file: read the text
        m = re.search(r"^\[tool\.pytest\.ini_options\]\s*$(.*?)(?=^\[|\Z)", text,
                      re.M | re.S)
        return bool(m and re.search(r"^\s*testpaths\s*=", m.group(1), re.M))


def has_testpaths(cwd, config=None):
    """True when pytest's config for a run at cwd sets testpaths: the -c file
    when given, else pytest.ini / pyproject.toml / tox.ini / setup.cfg in cwd
    or a parent up to the tree top (the filesystem root outside git)."""
    if config:
        c = Path(cwd) / config
        if c.name == "pyproject.toml":
            return _toml_testpaths(c)
        return any(_ini_testpaths(c, sec) for sec in ("pytest", "tool:pytest"))
    t = claims.tree_of(cwd)
    top = Path(t[0]).resolve() if t else None
    d = Path(cwd).resolve()
    while True:
        for name, section in _TESTPATHS_FILES:
            f = d / name
            if not f.is_file():
                continue
            if _toml_testpaths(f) if section is None else _ini_testpaths(f, section):
                return True
        if d == top or d.parent == d:
            return False
        d = d.parent


def check_path_free(cmd, cwd):
    """Refuse a pytest run that names no path in a tree without testpaths."""
    args = pytest_args(cmd)
    if args is None or names_a_path(args, cwd):
        return
    config = None
    for k, a in enumerate(args):
        if a in ("-c", "--config-file") and k + 1 < len(args):
            config = args[k + 1]
        elif a.startswith("--config-file="):
            config = a.split("=", 1)[1]
    if has_testpaths(cwd, config):
        return
    raise GateRefused("SUITE-GATE: pytest names no test path and no testpaths is set "
                      "(pytest.ini / pyproject.toml / tox.ini / setup.cfg); it would collect "
                      "the whole tree - name the test paths")


# ---------------------------------------------------------------- durations + lane (KIT-15)

def cmd_hash(cmd):
    """16 hex of sha256 over the command words as given (before resolve_exe)."""
    return hashlib.sha256(json.dumps([str(w) for w in cmd]).encode("utf-8")).hexdigest()[:16]


def tree_name(cwd):
    """The main checkout's folder name, so a lane worktree counts as its tree."""
    t = claims.tree_of(cwd)
    if t is None:
        return Path(os.path.abspath(str(cwd))).name
    return Path(t[2] or t[0]).name


def read_durations(d, tail=DURATIONS_TAIL_BYTES):
    """Parsed lines of <d>/durations.jsonl (its last `tail` bytes); bad lines skipped."""
    p = Path(d) / DURATIONS
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - tail))
            data = f.read()
    except OSError:
        return []
    lines = data.split(b"\n")
    if size > tail:
        lines = lines[1:]
    out = []
    for ln in lines:
        try:
            doc = json.loads(ln)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def median_hold(d, tree, chash, window=LANE_WINDOW, min_runs=LANE_MIN_RUNS):
    """Median hold_s of the last `window` runs of (tree, cmd); None under min_runs."""
    holds = [float(r["hold_s"]) for r in read_durations(d)
             if r.get("tree") == tree and r.get("cmd") == chash
             and isinstance(r.get("hold_s"), (int, float))][-window:]
    if len(holds) < min_runs:
        return None
    holds.sort()
    m = len(holds) // 2
    return holds[m] if len(holds) % 2 else (holds[m - 1] + holds[m]) / 2.0


def lane_eligible(d, tree, chash):
    m = median_hold(d, tree, chash)
    return m is not None and m <= LANE_MAX_S


def record(d, line):
    """Append one durations line; never raises."""
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(line, sort_keys=True) + "\n").encode("ascii")
        fd = os.open(str(Path(d) / DURATIONS), os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        pass


def run(argv, cwd=None, runner=None, dirty=dirty_paths, d=None, **kw):
    cwd = Path(cwd or os.getcwd())
    owner, n, timeout, cmd = parse(argv)
    check_path_free(cmd, cwd)
    resolve_exe(cmd, cwd)  # v16: a bare word not on PATH refuses before the queue
    check_straddle(cwd, owner, dirty)
    d = Path(d) if d else gate_dir()
    clock = kw.get("clock", time.time)
    tree, chash = tree_name(cwd), cmd_hash(cmd)
    lane = lane_index(n) is not None and lane_eligible(d, tree, chash)
    need = required_commit_mb(d, tree, chash) + commit_margin_mb()
    kw.setdefault("commit", commit_check(need, kw.pop("free_commit", free_commit_mb)))
    asked = clock()
    stats = {}
    k, raw = acquire(d, n, timeout, lane=lane, stats=stats, **kw)
    got = clock()
    rc = None
    peak = {"mb": None}

    def default_runner(c, e):
        p = subprocess.Popen(c, cwd=str(cwd), env=e, **gitlock.quiet_inherit())
        try:
            with PeakSampler(p.pid) as s:
                rc_ = p.wait()
            peak["mb"] = s.peak
            return rc_
        except BaseException:
            with contextlib.suppress(OSError):
                p.kill()
            raise

    try:
        check_straddle(cwd, owner, dirty)
        env = dict(os.environ, FLEET_SUITE_SLOT=str(k))
        runner = runner or default_runner
        rc = runner(resolve_exe(cmd, cwd, environ=env), env)
        return rc
    finally:
        release(d, k, raw)
        hold = clock() - got
        line = {"ts": round(got, 3), "tree": tree, "cmd": chash, "slot": k,
                "lane": k == lane_index(n), "wait_s": round(got - asked, 3),
                "hold_s": round(hold, 3), "exit": rc}
        if stats.get("commit_wait_s", 0) > 0:
            line["commit_wait_s"] = round(stats["commit_wait_s"], 3)
        if peak["mb"] is not None:
            line["peak_commit_mb"] = round(peak["mb"], 1)
        if line["lane"] and hold > LANE_OVERRUN_S:
            line["overrun"] = True
            _say(f"suite gate: lane run held {int(hold)}s (> {int(LANE_OVERRUN_S)}s); "
                 f"its record moves it to the regular slots")
        record(d, line)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["run"]:
            return run(argv[1:])
        if argv[:1] == ["status"]:
            d = gate_dir()
            n = slots()
            lane = lane_index(n)
            lane_txt = "" if lane is None else (
                ", lane " + ("held" if lane in held(d) else "free"))
            print(f"{len(held(d, upto=n))} of {n} slot(s) held{lane_txt}")
            return 0
    except GateRefused as exc:
        _say(str(exc))
        return 3
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
