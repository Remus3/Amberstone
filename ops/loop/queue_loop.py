#!/usr/bin/env python
# arch: re-fire driver for the one-row `queue` lane worker | section=ops | frozen=no
r"""Queue loop - the thing that turns a ONE-ROW worker into a queue drain.

`lanes.py` decides WHO may run. `lane_launcher.py` turns a claim into a running
headless worker. Neither of them ever runs a second time on its own: a lane is
fired by an operator click, the worker does its work and exits, and the lane
goes FREE with nobody watching. For lane 10 (`queue`) that is the wrong shape -
lane 5 files acceptance-bearing RM rows and this lane is meant to execute them
one after another, unattended, overnight. This module is the missing repeat.

WHY THE DRIVER OWNS THE REPEAT, NOT THE WORKER. The obvious cheaper design is a
worker that loops internally: read a row, do it, read the next. It fails two
ways, and both were paid for elsewhere in this tree. First, context. A
`claude -p` worker accumulates every row's transcript for the whole run, and
quality degrades long before the context window is actually full - the entire
directed-headless-upgrade design exists because continuity has to live on disk
(git history, docs/LEDGER.md, the directive chain) rather than in one long
session. Second, blast radius. A worker that crashes or is killed on row three
loses rows four through twelve with it, because they were never separate units
of work. ONE ROW PER PROCESS makes a crash cost exactly one row, and it makes
every row start from a clean context that reads its state off disk. The price
is a driver, and the driver is this file.

WHY THE LANE LOCK IS TAKEN PER CYCLE, NOT HELD ACROSS THE LOOP. Holding one
claim for all twelve cycles would be simpler and is wrong twice over. The lanes
are mutually exclusive at MAX_SLOTS=1, so a held-across-the-loop claim would
lock the operator out of every OTHER lane for the entire multi-hour run - and
the operator firing a `ds` or `uiux` lane between queue rows is the normal case,
not an edge. Worse, it would be unreclaimable: `lanes.lane_state` decides
FREE / RUNNING / RECLAIMABLE by PROBING the recorded pid, and `launch_lane`
re-points the lock at the WORKER. Across a whole loop the lock would name a
worker that exits after row one while the driver keeps running, so the lane
would read RECLAIMABLE under a live driver - the exact ambiguity the three
states exist to remove. Per-cycle acquire and a `finally` release keeps the
lock's meaning honest: held means a worker is up right now.

WHY A REFUSED ACQUIRE IS NOT AN ERROR. `try_acquire_lane` answers
`{"ok": False, "refused": "lane_held"}` and writes nothing when another lane is
genuinely running. A driver that treated that as fatal would die the first
night the operator's own lane overlapped by a minute. It is retried
ACQUIRE_RETRIES times at ACQUIRE_WAIT_S apart (ten minutes of patience), then
recorded as `lane_held` and the loop moves on to the next cycle.

WHY LIVENESS IS `slots.pid_alive` AND NOT `Popen.wait()`. There is no Popen to
wait on. `launch_lane` spawns THROUGH powershell (`run_lane.ps1`) and hands back
a pid; the Popen handle it briefly held belongs to the launcher, not here, and
waiting on it would in any case wait on the wrapper rather than the worker. The
second reason is restart: this driver may be killed and relaunched while a
worker is still up, and on the next start it has no child handles at all -
only pids it can read back off the lock. A pid probe works in both worlds, and
it is the same probe `lane_state` uses, so the driver and the dashboard can
never disagree about whether a worker is alive.

WHY `taskkill /F` AND NEVER `Stop-Process`. CLAUDE.md hard rule: Stop-Process
hangs the MCP pipe. `/T` is added on purpose and is a deliberate difference from
`lane_launcher._kill`: the pid here is the powershell WRAPPER, `claude` is its
child, and killing only the wrapper would orphan a live worker inside the lane's
worktree while the very next cycle fires a second worker into the SAME
directory. Two writers in one working directory is the concurrent-index
corruption class the launcher's own docstring cites, and it is not recoverable
by retrying. The launcher can use a bare `/F` because it kills a worker it has
only just spawned; a cycle timeout at 5400s cannot assume that.

A KILL IS NOT DONE UNTIL IT IS VERIFIED. `taskkill` can fail - access denied
against a process in another session, or a re-parented subagent that outlives
the wrapper whose pid was killed - and it reports that failure only in output
`_taskkill` deliberately swallows. An UNVERIFIED kill is the same hazard as no
kill at all: cycle N+1 fires a second worker into the same lane worktree while
the first is still writing, which is exactly the unrecoverable corruption named
above. So the kill is followed by a bounded `kill_grace_s` re-probe of the SAME
liveness predicate, and a worker that outlives it is recorded
`timeout_kill_failed` and STOPS the loop. Ending the night early is a cost; a
corrupted index is not recoverable by retrying.

TWO CLOCKS, ON PURPOSE. `clock` (time.time) stamps the ledger, because a JSONL
row an operator reads at 3am has to carry wall time. `monotonic` measures the
worker deadline, because wall time is NOT monotonic - an NTP step backward
silently EXTENDS a 5400s deadline by however far the clock moved, and a frozen
clock extends it forever (measured: an adversarial probe that froze `clock` had
to kill this driver at RC=124). The deadline also starts at LAUNCH rather than
at cycle start: up to ACQUIRE_RETRIES * ACQUIRE_WAIT_S (600s) of legitimate
waiting for another lane sits between the two, and charging that to the worker
both shortens its real budget and made the old timeout message ("still alive
after 5400s") false by up to ten minutes.

A PID IS NOT AN IDENTITY. `slots.pid_alive` answers whether SOMETHING holds the
pid, never whether it is still OUR worker. `lanes.lane_state` pairs it with a
process START TIME for exactly that reason (MEASURED 2026-08-02: a dead lane
worker's pid 8820 became SearchFilterHost three minutes later), so the driver
captures `proc_started(pid)` at launch and reuses `lanes`' own predicate rather
than deriving a second one - one definition means the driver and the dashboard
can never disagree about a lane. It is fail-soft in both directions: every
uncertain case (no start time readable at launch, no psutil, an unqueryable
pid) degrades to the plain pid probe this file used before.

ONE FAULT IS NOT THE WHOLE NIGHT. `run_cycle` is wrapped: an unexpected fault
becomes an `error` record that is appended and emitted like any other, and the
loop continues. The silent half of that defect was worse than the loud half -
`append_record` is only reached on the normal path, so a fault used to leave NO
ledger row at all and the morning's only evidence was a log that stopped. A
fault that REPEATS is different, and `max_consecutive_errors` stops the loop,
because whatever broke cycle 3 will break cycles 4 through 12 as well.

ONE DRIVER PER BOX. The lane lock stops two WORKERS, not two DRIVERS: a second
`launch_queue_loop.ps1` starts a second driver that loses every acquire race,
burns up to ten minutes per cycle recording `lane_held`, and interleaves its
rows into one ledger. A named mutex held for the process lifetime is the guard,
and it is the repo's existing primitive - `winmutex.py`, which `steer.py`
already uses to serialise its own appends. That file is BYTE-IDENTICAL-BY-
CONTRACT with the Sibling-A copy: consumed here, never edited.

STOP IS THREE FILES, CHECKED BEFORE EVERY CYCLE INCLUDING THE FIRST.
`control/STOP` is the loop controller's existing global halt and is honoured
here deliberately - one operator gesture stops everything on the box.
`control/lanes/QUEUE_STOP` stops this lane alone. `control/lanes/QUEUE_DRAINED`
is written by the WORKER when it finds no eligible row, which is how a queue
that empties at cycle four stops instead of firing eight no-op workers. The
check runs before cycle 1 because a driver that only checks between cycles
fires one unwanted worker on every start - against this lane that means one
unwanted RM row executed and committed. Note that `control/STOP` EXISTS on
Legion right now (content: "operator halt via LW session 2026-07-28"), so a
bare `python ops/loop/queue_loop.py` today correctly runs zero cycles, names
WHICH sentinel stopped it and where that file lives, and exits
EXIT_STOP_SENTINEL so no launcher can print a success banner over a no-op;
clear it deliberately, do not special-case it here.

THE CI WAIT IS THE DRIVER'S, NOT THE PROMPT'S. The lane's acceptance is CI
green - specifically the `full dual suite` step of the `check` job, read out of
`jobs[].steps[]`. `.github/workflows/ci.yml:38-40` sets
`cancel-in-progress: true` on the group
`${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}`; a run takes
45 to 67 minutes and a cycle takes 25 to 45, so cycle N+1's run cancels cycle
N's in WHATEVER group - moving groups does not fix it, only serializing does.
That fix was written as PROSE first (`tools/headless-queue.md` section 9 told
the worker to block until its own run completed) and MEASURED over six cycles it
half-held: cycles 2 and 3 blocked (102.7 and 113.3 minutes, both green), but
cycles 4, 5 and 6 ran 45 / 24.2 / 38.5 minutes - shorter than a run - so those
workers exited early and three consecutive dispatch runs were cancelled. An
instruction a worker can rationalize past is not a mechanism. So the wait moved
here: nothing can cancel a run while the only thing that would trigger the next
one is the driver, and the driver is waiting. Cycles are already serial, which
is what makes that structural rather than hopeful.

THE CI GATE FAILS SOFT ON TOOLING AND HARD ON THE VERDICT. `gh` not installed,
an expired token, a 502, an unparseable payload - every one of them returns
`unavailable` and the night goes on, because a CLI hiccup may not end eleven
remaining rows. A `failure` on the named STEP is the opposite: it stops the loop
(`ci_red`, EXIT_CI_RED), because every further cycle would push another row onto
a red `main` and compound a break nobody is watching. `cancelled`, `timeout`,
`skipped` and `unknown` sit in between - recorded, never red. `cancelled`
especially: a superseded run and a job that hit its own ceiling report the same
word, and `gh run watch --exit-status` returns 0 on both, so it may never be
cited as acceptance and is not evidence of a break either.

SIDE-EFFECT FREE AT IMPORT. Nothing below creates a directory, reads the
control plane or spawns anything at import time - the dashboard and the tests
both import this module, and an import that mutated the control plane would
make a rendering pass fire a lane.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _bind(dotted: str, private: str, filename: str):
    """Bind the SAME module object everything else uses - never a second copy.

    Straight from `lane_launcher._load_lanes`, and for the same measured reason:
    `lanes.py` carries process-global state (`_OWNED`, the ABA guard that decides
    whether a release is ours). A file-path bind under a fresh name creates a
    SECOND module object with its OWN `_OWNED`, so a claim recorded in one copy
    is invisible to a release called on the other and the lane can never be
    freed. The launcher's first cut did exactly that and two of its tests failed
    on it.

    The dotted name is tried first because that is what
    `dashboard/routes_loop_control.py` imports, making it the canonical one. The
    file-path fallback exists only for callers with no package on sys.path (the
    detached launcher runs this by absolute path), and it reuses the SAME
    private name the other binders use so the fallback still yields one object.
    """
    try:
        return importlib.import_module(dotted)
    except ImportError:
        pass
    if private in sys.modules:
        return sys.modules[private]
    spec = importlib.util.spec_from_file_location(private, _HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[private] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _bind("ops.loop.lanes", "rc_loop_lanes", "lanes.py")
lane_launcher = _bind("ops.loop.lane_launcher", "rc_loop_lane_launcher",
                      "lane_launcher.py")
# NOT a third `_bind`. lanes.py already binds slots.py under "rc_loop_slots"
# (lanes.py:103); reaching through it is the only way to be sure the driver, the
# lock and the dashboard all probe pids with one module object. slots.py itself
# is stateless, so a second copy would not corrupt anything today - but it is
# BYTE-IDENTICAL-BY-CONTRACT with the Sibling-A copy and must be consumed,
# never re-bound on a guess about what it holds.
slots = lanes.slots
# Bound like the rest, but the "one module object" reasoning above does NOT
# apply here and it is worth saying why rather than implying it: winmutex holds
# no process-global state at all - the shared state IS the Win32 named-mutex
# namespace, keyed by the NAME passed in. Two module objects would therefore
# still serialise against each other, and against Sibling-A's copy. It is
# bound rather than re-implemented because it is BYTE-IDENTICAL-BY-CONTRACT
# with that copy (SHARED_SHA256 in tests/test_loop_concurrency.py): consumed
# here, never edited.
winmutex = _bind("ops.loop.winmutex", "rc_loop_winmutex", "winmutex.py")

LANE = "queue"

REPORTS = _HERE / "reports"
CONTROL = _HERE / "control"

# Relative so `--control-dir` can point the whole set at a sandbox; STOP_FILES
# below is the resolved default, and it is what the operator-facing docs name.
STOP_RELPATHS = ("STOP", "lanes/QUEUE_STOP", "lanes/QUEUE_DRAINED")
STOP_FILES = tuple(CONTROL / rel for rel in STOP_RELPATHS)
# The bare names, in the same order. `stop_reason` reports a NAME, and `main`
# has to turn that name back into a full path for the operator, so the mapping
# is derived from one definition instead of being written out twice.
STOP_NAMES = tuple(Path(rel).name for rel in STOP_RELPATHS)

# Append-only, one JSON object per line. NOT tmp+os.replace: CLAUDE.md's atomic
# -write rule exists for files an overlay POLLS mid-write, and this is the
# opposite shape - a ledger nothing polls, where a replace would rewrite every
# prior row on every cycle and lose any concurrent append. An O_APPEND write of
# a single short line is the durable form here.
CYCLE_LOG = REPORTS / "queue_loop.jsonl"

# Twelve rows is roughly one unattended night at the observed lane cadence, and
# a bound rather than "until stopped" means a driver nobody notices still ends.
DEFAULT_MAX_CYCLES = 12
# RAISED 2026-09-06 from 5400s (90 min), which no longer bounded a wedge - it
# bounded legitimate WORK. The lane's CI acceptance requires the worker to block
# until its own dispatch run reaches `completed`, because a run (roughly 45 to
# 67 minutes, RM-370 measured 67) otherwise gets cancelled by the next cycle's
# run whatever concurrency group it sits in; only serializing fixes that. So a
# healthy cycle is now work plus a block of up to 90 minutes, plus up to another
# 90 if the run is superseded and the worker re-dispatches once. Cycle 3
# measured 83.8 minutes against the old 5400s kill, which is how close this came
# to killing a worker that was doing exactly what it was told.
#
# 4 hours is a WEDGE ceiling, not a work budget: it must sit above the worst
# legitimate cycle, and everything below it is bounded by the prompt's own
# budgets rather than by this kill. It deliberately no longer matches the loop
# controller's 5400s deadline - that number bounds a different workload.
DEFAULT_CYCLE_TIMEOUT_S = 14400
# Between cycles, not after the last. Long enough for the worker's commit and
# push to land and for the DS Share mirror / :8860 bounce to settle before the
# next worker reads the tree - a mid-settle read is the false anchor-mismatch
# class CLAUDE.md warns about.
DEFAULT_SETTLE_S = 45
# A dead worker is noticed within 10s; polling faster buys nothing against a
# multi-hour run and only wakes the box.
DEFAULT_POLL_S = 10
# TOTAL acquire attempts, not attempts-after-the-first: 20 * 30s is ten minutes
# of patience for an operator-fired lane to finish before this cycle gives up
# and is recorded as `lane_held`.
ACQUIRE_RETRIES = 20
ACQUIRE_WAIT_S = 30
# How long a killed worker gets to actually die before the kill is declared
# FAILED. Generous against `taskkill /F /T`, which is effectively immediate when
# it is permitted at all - this is sized for a wedged process tree with children
# to reap, not for a slow shutdown, because /F grants none. Short enough that a
# driver which cannot kill its worker says so within a poll or two instead of
# waiting out another 90-minute cycle to find out.
DEFAULT_KILL_GRACE_S = 15
# Consecutive `error` outcomes before the loop gives up. Three is one genuine
# fault plus two chances for it to be transient; a fourth would be watching the
# same traceback scroll past all night.
DEFAULT_MAX_CONSECUTIVE_ERRORS = 3

# ---- CI acceptance. See "THE CI WAIT IS THE DRIVER'S" in the module docstring.
CI_WORKFLOW = "ci.yml"
# A BRANCH ref, which is what `gh workflow run` takes - so a dispatch builds
# `main` as of trigger time, i.e. our commit or a descendant of it.
CI_REF = "main"
# The job (`.github/workflows/ci.yml:142`) and the step inside it (`:419`). The
# step is matched on a SUBSTRING because its shipped name carries a
# parenthetical - "full dual suite (RM-119 - push CI now gates the whole tree)" -
# and a parenthetical is prose that will be reworded. "full dual suite" is the
# thing. The JOB name is matched exactly: `nightly-full-suite` also contains
# "full" and runs the same command, and grading the wrong job is precisely the
# failure the "read jobs[].steps[]" rule exists to prevent.
CI_JOB = "check"
CI_STEP = "full dual suite"

# The seven words a verdict may be. Anything outside this set is a bug in this
# file, not a state of the world, which is why the tuple is asserted in tests.
CI_SUCCESS = "success"
CI_FAILURE = "failure"
CI_CANCELLED = "cancelled"
CI_SKIPPED = "skipped"
CI_TIMEOUT = "timeout"
CI_UNAVAILABLE = "unavailable"
CI_UNKNOWN = "unknown"
CI_STEPS = (CI_SUCCESS, CI_FAILURE, CI_CANCELLED, CI_SKIPPED, CI_TIMEOUT,
            CI_UNAVAILABLE, CI_UNKNOWN)

# 90 minutes. MEASURED rather than picked: RM-370 timed a real wait at 67
# minutes, so the 60 first written into the prose contract was under-set and a
# worker obeying it would have abandoned a run that was about to pass. This is
# the budget for ONE run; a cancelled run buys one re-dispatch and a second
# budget, which is why DEFAULT_CYCLE_TIMEOUT_S is 4 hours and not 90 minutes.
DEFAULT_CI_WAIT_S = 5400
# A `ci` run is measured in tens of minutes. Polling faster than a minute buys
# nothing and spends API quota that `gh` shares with everything else on the box.
DEFAULT_CI_POLL_S = 60
# Per `gh` / `git` invocation. These are single API round trips, not the run
# itself - the run is waited out by polling, never by holding a subprocess open.
GH_TIMEOUT_S = 120
# One cycle's push plus the dispatch it triggers is 2 runs; 20 covers a night of
# them plus whatever the operator's own lanes pushed in between.
CI_RUN_LIST_LIMIT = 20
# A dispatched run takes a beat to become visible to `gh run list`. Six tries at
# 10s is a minute of patience against an API that normally answers on the first.
CI_TRIGGER_TRIES = 6
CI_TRIGGER_WAIT_S = 10

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW

# Two names, never one. The driver mutex is held for the WHOLE run (hours), so
# an append taken under that same name would block every other appender for the
# length of the night - correct-looking and useless. `steer.py` uses the same
# primitive under its own dedicated name for exactly this reason.
DRIVER_MUTEX = "Global\\RC_QUEUE_LOOP_DRIVER"
LEDGER_MUTEX = "Global\\RC_QUEUE_LOOP_LEDGER"
# The ledger append is a few hundred bytes; 5s is a wedged holder, not a busy
# one. On timeout the append proceeds UNSERIALIZED and says so - see
# append_record.
LEDGER_MUTEX_TIMEOUT_S = 5.0

OUTCOME_COMPLETED = "completed"
OUTCOME_TIMEOUT = "timeout_killed"
OUTCOME_LANE_HELD = "lane_held"
OUTCOME_LAUNCH_FAILED = "launch_failed"
# The kill was issued and the worker OUTLIVED it. Distinct from OUTCOME_TIMEOUT
# because the two demand opposite responses: a killed worker frees the worktree
# and the loop goes on, a surviving one does not and the loop must stop.
OUTCOME_KILL_FAILED = "timeout_kill_failed"
# A fault run_cycle did not convert into an outcome of its own.
OUTCOME_ERROR = "error"

STOPPED_BY_MAX_CYCLES = "max_cycles"
STOPPED_BY_CONSECUTIVE_ERRORS = "consecutive_errors"
# The `full dual suite` step of the `check` job reported `failure` on the sha
# this cycle pushed. Every further cycle would stack another row on top of a
# break, so the night ends here.
STOPPED_BY_CI_RED = "ci_red"

# Process exit codes. Distinct on purpose: the launcher and any future scheduled
# task can only tell "ran the night" from "refused to start" by the number.
EXIT_OK = 0
EXIT_STOP_SENTINEL = 2      # zero cycles because a stop file was already there
EXIT_ALREADY_RUNNING = 3    # another driver holds DRIVER_MUTEX
# The two HARD stops. They were exiting 0 in the first cut, which made the most
# serious condition this driver can reach invisible to the launcher, to a
# scheduled task and to any `if ($LASTEXITCODE -ne 0)` a future operator writes:
# a night that ended at cycle 2 because a worker outlived its kill looked
# exactly like a night that ran all twelve. EXIT_KILL_FAILED is the one to act
# on - it means a worker may STILL be writing in C:\rc-worktrees\rc-lane-queue,
# so the next thing anyone does there must be to check for it by hand.
EXIT_KILL_FAILED = 4        # a worker outlived its taskkill - worktree suspect
EXIT_CONSECUTIVE_ERRORS = 5  # the same fault repeated until the loop gave up
EXIT_CI_RED = 6             # the gating CI step went red on a pushed sha


def _taskkill(pid) -> None:
    """Hard-kill a wedged worker AND its children. Never raises.

    See the module docstring for why this is taskkill with /T and not the
    PowerShell cmdlet. Failure is swallowed on purpose: the caller is already
    recording a timeout, and a kill that could throw would turn one bad cycle
    into a dead driver.
    """
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=20,
                       creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass


def _emit(line: str) -> None:
    """One progress line, FLUSHED.

    The launcher runs this under `pythonw.exe` with stdout redirected to a file,
    and a redirected non-tty stdout is block-buffered - without the flush the
    log stays empty for the whole run and an operator tailing it cannot tell a
    working driver from a hung one.
    """
    print(line, flush=True)


def _driver_singleton():
    """Hold DRIVER_MUTEX for the whole run, or raise MutexTimeout immediately.

    timeout=0 makes this a TEST rather than a wait. A second driver must exit
    at once with a distinct code; queueing it behind the first for six hours
    would start a run nobody asked for, at a time nobody chose.

    winmutex FAILS OPEN when the mutex cannot be created at all (a name or ACL
    problem), yielding None after a loud UNSERIALIZED line. That degrade is the
    right one here: it leaves exactly the behaviour this file had before the
    guard existed, rather than refusing a launch the operator did ask for.
    `log=_emit` puts the acquire / release trace in the driver's own log, where
    an operator tailing it can see the hold window.
    """
    return winmutex.hold(DRIVER_MUTEX, timeout=0.0, log=_emit)


def _ledger_lock():
    """Hold LEDGER_MUTEX for one append.

    No `log=` here, unlike the driver mutex: two winmutex lines per cycle would
    bury the one line per cycle an operator actually reads.
    """
    return winmutex.hold(LEDGER_MUTEX, timeout=LEDGER_MUTEX_TIMEOUT_S)


def stop_path_for(name, control_dir=None):
    """The full path of the sentinel called `name`, or None if it is not one.

    Derived from STOP_RELPATHS rather than re-probing the disk, so `main` can
    still name the file that stopped the run even in the race where someone
    removes it a moment later.
    """
    root = CONTROL if control_dir is None else Path(control_dir)
    for rel in STOP_RELPATHS:
        if Path(rel).name == name:
            return root / rel
    return None


def stop_reason(control_dir=None) -> str | None:
    """The name of whichever stop sentinel exists, or None.

    Checked in STOP_RELPATHS order, so the global halt is reported ahead of the
    lane-local one when both are present. Returns the file NAME rather than the
    path because it is what lands in the summary and in the operator's log line,
    and the three names are unambiguous.
    """
    root = CONTROL if control_dir is None else Path(control_dir)
    for rel in STOP_RELPATHS:
        candidate = root / rel
        if candidate.exists():
            return candidate.name
    return None


def _append_line(path: Path, line: str) -> None:
    """The raw O_APPEND write. Split out only so the serialised and the
    fail-open paths in `append_record` cannot drift apart.

    newline="\\n" so the ledger stays LF on Windows. Python's text mode would
    otherwise translate to CRLF, which silently changes byte counts and makes
    the file disagree with every other .jsonl in this tree (memory
    reference_windows_write_text_crlf_byte_count).
    """
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)


def append_record(record: dict, cycle_log=None, *, hold=None) -> Path:
    """Append one cycle record to the JSONL ledger. Creates its dir on demand.

    Lazily, because `--reports-dir` may name a directory that does not exist yet
    and because import time must stay side-effect free.

    Serialised under LEDGER_MUTEX, the way `steer.py:189` serialises its own
    appends. An O_APPEND write of one short line is close to atomic already, but
    "close to" is what interleaves two half-lines into an unparseable row at 3am,
    and the ledger is the only durable record of the night.

    `hold` is a seam so a test can prove the write happens INSIDE the critical
    section without touching a real OS mutex.
    """
    path = Path(CYCLE_LOG if cycle_log is None else cycle_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    hold = _ledger_lock if hold is None else hold
    try:
        with hold():
            _append_line(path, line)
    except winmutex.MutexTimeout:
        # FAIL OPEN, LOUDLY - the same trade winmutex itself makes on its three
        # unserialized branches. A dropped row loses the only evidence of a
        # cycle; worse, this is called from `run_loop` OUTSIDE its try, so
        # raising here would end the night over a lock nobody else should be
        # holding. The marker word matches winmutex's so one grep finds both.
        _emit(f"queue-loop: UNSERIALIZED ledger append - {LEDGER_MUTEX} not "
              f"free within {LEDGER_MUTEX_TIMEOUT_S}s; appending anyway")
        _append_line(path, line)
    return path


def _worker_is_up(pid, started, *, alive, stranger) -> bool:
    """True only while the ORIGINAL worker process is still running.

    Two probes, not one. `alive` answers whether SOMETHING holds the pid;
    `stranger` answers whether that something is still the process we launched.
    `lanes.lane_state` makes exactly this pair of checks (lanes.py:300-306) and
    reusing its predicate rather than deriving a second one is what keeps the
    driver and the dashboard from ever disagreeing about a lane.

    The predicate is TOTAL by construction: no recorded start time, no readable
    start time, no psutil - every uncertain case answers "not a stranger", so an
    unavailable source degrades to the plain pid probe instead of declaring a
    live worker dead and firing a second one into its worktree.
    """
    if not alive(pid):
        return False
    return not stranger(pid, started)


def _await_death(pid, started, *, alive, stranger, kill_grace_s, poll_s,
                 sleep, monotonic) -> bool:
    """Re-probe after a kill. True when the worker is gone inside the grace.

    This is the whole of the unverified-kill fix. `_taskkill` swallows its own
    failure on purpose, so the only evidence it took is the liveness probe
    coming back false. Bounded, because a driver that waits forever on a
    process it cannot kill is just a wedged driver with extra steps.
    """
    grace = max(0.0, float(kill_grace_s))
    deadline = monotonic() + grace
    # Never slower than the normal poll, and never longer than the whole grace:
    # a 10s step against a 2s grace would sleep straight past the answer and
    # report a failed kill that actually worked.
    step = max(0.0, min(float(poll_s), grace))
    while True:
        if not _worker_is_up(pid, started, alive=alive, stranger=stranger):
            return True
        if monotonic() >= deadline:
            return False
        sleep(step)


def _gh(args) -> tuple[int, str]:
    """The ONE `gh` call site. Returns (returncode, text) and never raises.

    Every CI question goes through here so the timeout, the console-window flag
    and the "a missing gh is an exit code, not a traceback" contract are set
    once. It is also the seam every test injects: a suite that could reach the
    real `gh` would fire a 45-minute runner against the live repo from a unit
    test, and would race whatever the lane is doing at the time.

    On failure the text is stderr FIRST, because that is where `gh` puts the
    reason (`could not find any workflows`, an auth prompt, a 502) while stdout
    is usually empty; both are returned because which one carries the message
    varies by subcommand.
    """
    argv = ["gh", *[str(a) for a in args]]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=GH_TIMEOUT_S, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        # 127 is the shell's "command not found", which is the common case here
        # (no gh on PATH under a detached pythonw) and reads correctly in a log.
        return 127, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return proc.returncode, ((proc.stderr or "") + (proc.stdout or "")).strip()
    return 0, proc.stdout or ""


def _head_sha() -> str | None:
    """The sha `origin/main` points at right now, or None. Never raises.

    `git ls-remote` and not `git rev-parse`, for two independent reasons. The
    driver runs in the MAIN tree while the worker commits and pushes from
    `C:\\rc-worktrees\\rc-lane-queue`, so this tree's own HEAD is not what was
    pushed; and a local `origin/main` ref is only as fresh as the last fetch,
    which nothing in this loop performs. `ls-remote` asks the remote and mutates
    nothing - no fetch, no index, no reflog - which matters because the driver
    must never write into a tree a worker may be using.

    None on every failure. The caller turns that into an `unavailable` verdict
    rather than a skipped cycle: a night whose CI evidence is missing must not
    read like a night of greens.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(lanes.REPO_ROOT), "ls-remote", "origin",
             "refs/heads/" + CI_REF],
            capture_output=True, text=True, timeout=GH_TIMEOUT_S,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    first = (proc.stdout or "").strip().split("\n", 1)[0]
    parts = first.split()
    return parts[0] if parts else None


def _gh_json(gh, args):
    """(parsed, None) or (None, why). Every shape surprise is a `why`.

    A missing field, a payload that is a list where an object was expected, a
    non-zero exit and unparseable output are all the SAME class here - the CLI
    did not answer the question - and all of them have to degrade to
    `unavailable` rather than raise, so they are normalised at the one place
    that talks to `gh`.
    """
    rc, out = gh(args)
    if rc != 0:
        return None, (f"gh {' '.join(str(a) for a in args)} exited {rc}: "
                      f"{str(out).strip()[:300]}")
    try:
        return json.loads(out), None
    except (TypeError, ValueError) as exc:
        return None, (f"gh {' '.join(str(a) for a in args)} returned "
                      f"unparseable JSON: {exc}")


def _ci_run_list(gh):
    """Recent `ci` runs, newest first, as `gh` orders them."""
    data, err = _gh_json(gh, ["run", "list", "--workflow", CI_WORKFLOW,
                              "--limit", str(CI_RUN_LIST_LIMIT), "--json",
                              "databaseId,headSha,status,conclusion,event"])
    if err:
        return [], err
    if not isinstance(data, list):
        return [], (f"gh run list returned {type(data).__name__}, "
                    f"expected a list of runs")
    return [row for row in data if isinstance(row, dict)], None


def _pick_ci_run(rows, sha):
    """The best existing run for `sha`, preferring a dispatch over a push.

    `event_name` is part of the concurrency group, so a `workflow_dispatch` run
    sits in a DIFFERENT group from every push and a later push cannot cancel it.
    A push run has no such protection - it is exactly what got cancelled three
    times in a row - so given both for one sha, the dispatch is the one worth
    waiting on. Rows arrive newest-first, so the first match within an event is
    the freshest.
    """
    matches = [row for row in rows if str(row.get("headSha") or "") == str(sha)]
    for event in ("workflow_dispatch", "push"):
        for row in matches:
            if str(row.get("event") or "") == event:
                return row
    return matches[0] if matches else None


def _trigger_ci_run(gh, sha, seen, *, sleep):
    """Fire one dispatch and return the run it created. (row, None) or (None, why).

    NEW-ID identification, not a timestamp comparison. `seen` holds every run id
    this call has already accounted for, so "the run the trigger created" is
    "the newest run whose id we have not seen", which needs no clock, no
    timezone and no ISO parsing - and cannot mistake the FIRST dispatch for the
    second when a cancelled run is re-dispatched.

    An exact `headSha` match wins when one is offered. Otherwise the newest
    fresh dispatch run is accepted even though its head is a DESCENDANT of the
    sha we asked about: `gh workflow run` takes a branch ref, so it builds
    `main` as of trigger time, and a later sha subsumes an earlier one. What is
    NOT done is claim descent we did not prove - the run's own headSha is
    returned and recorded, so the ledger cites the tree CI actually built.
    """
    rc, out = gh(["workflow", "run", CI_WORKFLOW, "--ref", CI_REF])
    if rc != 0:
        return None, (f"gh workflow run {CI_WORKFLOW} exited {rc}: "
                      f"{str(out).strip()[:300]}")
    why = (f"no new ci run appeared within "
           f"{CI_TRIGGER_TRIES * CI_TRIGGER_WAIT_S}s of the dispatch")
    for _ in range(CI_TRIGGER_TRIES):
        sleep(CI_TRIGGER_WAIT_S)
        rows, err = _ci_run_list(gh)
        if err:
            why = err
            continue
        fresh = [row for row in rows if row.get("databaseId") not in seen]
        exact = [row for row in fresh
                 if str(row.get("headSha") or "") == str(sha)]
        dispatched = [row for row in fresh
                      if str(row.get("event") or "") == "workflow_dispatch"]
        picked = (exact or dispatched or [None])[0]
        if picked is not None:
            seen.add(picked.get("databaseId"))
            return picked, None
    return None, why


def _ci_step_verdict(gh, run_id):
    """(step, detail) for the `full dual suite` step of the `check` job.

    NEVER the run conclusion. Two independent reasons, both measured: a green
    run may have SKIPPED the job that matters (`check` carries
    `if: github.event_name != 'schedule'`, `ci.yml:143`, so the scheduled
    nightly never runs it), and `gh run watch --exit-status` returns 0 on a
    CANCELLED run. The only thing that means "the tree passed" is the named
    step's own conclusion.

    An absent or skipped `check` job is `skipped` - a real answer about the
    world. A `check` job that is present but shaped in a way this function does
    not understand is `unavailable` - an answer about the TOOL. Collapsing the
    two would let a payload change read as a green.
    """
    data, err = _gh_json(gh, ["run", "view", str(run_id), "--json", "jobs"])
    if err:
        return CI_UNAVAILABLE, err
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return CI_UNAVAILABLE, f"run {run_id} carried no jobs list"
    job = None
    for row in jobs:
        if isinstance(row, dict) and str(row.get("name") or "") == CI_JOB:
            job = row
            break
    if job is None:
        return CI_SKIPPED, (f"run {run_id} has no {CI_JOB!r} job - a scheduled "
                            f"run skips it (ci.yml:143)")
    if str(job.get("conclusion") or "") == CI_SKIPPED:
        return CI_SKIPPED, f"the {CI_JOB!r} job was skipped in run {run_id}"
    steps = job.get("steps")
    if not isinstance(steps, list):
        return CI_UNAVAILABLE, (f"the {CI_JOB!r} job in run {run_id} carried "
                                f"no steps list")
    for step in steps:
        if not isinstance(step, dict) or CI_STEP not in str(step.get("name") or ""):
            continue
        verdict = str(step.get("conclusion") or "").strip().lower()
        if verdict in CI_STEPS:
            return verdict, f"{CI_JOB} step {step.get('name')!r} -> {verdict}"
        return CI_UNKNOWN, (f"{CI_JOB} step {step.get('name')!r} reported "
                            f"conclusion {verdict!r}")
    return CI_UNAVAILABLE, (f"run {run_id} has a {CI_JOB!r} job with no step "
                            f"named like {CI_STEP!r}")


def wait_for_ci(sha, *, budget_s: float = DEFAULT_CI_WAIT_S,
                poll_s: float = DEFAULT_CI_POLL_S,
                allow_trigger: bool = True,
                gh=_gh, sleep=time.sleep, monotonic=time.monotonic) -> dict:
    """Block until `sha`'s ci run is graded, and return the verdict.

    Returns `{"sha", "run_id", "status", "step", "waited_s", "detail"}` where
    `step` is one of CI_STEPS. `sha` is the head CI ACTUALLY built, which may be
    a descendant of the one asked about - see `_trigger_ci_run`.

    THIS FUNCTION NEVER RAISES. Every tooling fault - a missing `gh`, a
    non-zero exit, unparseable JSON, a payload missing a field - becomes
    `unavailable` with the reason in `detail`, because a CLI hiccup may not
    wedge or end an overnight loop. Only the VERDICT is allowed to be bad news.

    `monotonic`, never `clock`: this can block for 90 minutes, and wall time is
    not monotonic. The file already pays for that lesson once, in `run_cycle`.
    """
    started_m = monotonic()
    deadline = started_m + max(0.0, float(budget_s))

    def _out(step, *, run_id=None, status="unknown", detail="", head=None):
        return {"sha": str(head or sha), "run_id": run_id, "status": status,
                "step": step, "waited_s": round(monotonic() - started_m, 1),
                "detail": str(detail)[:400]}

    rows, err = _ci_run_list(gh)
    if err:
        return _out(CI_UNAVAILABLE, detail=err)
    # Everything visible BEFORE any trigger of ours. Anything outside this set
    # later is, by construction, a run we caused.
    seen = {row.get("databaseId") for row in rows}

    run = _pick_ci_run(rows, sha)
    if run is None:
        if not allow_trigger:
            return _out(CI_UNAVAILABLE,
                        detail=f"no ci run found for {sha} and triggering is off")
        run, err = _trigger_ci_run(gh, sha, seen, sleep=sleep)
        if err:
            return _out(CI_UNAVAILABLE, detail=err)

    def _watch(row):
        run_id = row.get("databaseId")
        head = str(row.get("headSha") or "") or None
        if run_id is None:
            return _out(CI_UNAVAILABLE, head=head,
                        detail="the ci run row carried no databaseId")
        status = str(row.get("status") or "")
        conclusion = str(row.get("conclusion") or "")
        while status != "completed":
            # Checked BEFORE the sleep so a zero budget answers immediately, and
            # so the last poll cannot overshoot the deadline by a whole poll_s.
            if monotonic() >= deadline:
                return _out(CI_TIMEOUT, run_id=run_id, head=head,
                            status=status or "unknown",
                            detail=f"run {run_id} was still "
                                   f"{status or 'pending'} after {budget_s}s")
            sleep(poll_s)
            view, verr = _gh_json(gh, ["run", "view", str(run_id),
                                       "--json", "status,conclusion"])
            if verr:
                return _out(CI_UNAVAILABLE, run_id=run_id, head=head,
                            status=status or "unknown", detail=verr)
            if not isinstance(view, dict):
                return _out(CI_UNAVAILABLE, run_id=run_id, head=head,
                            status=status or "unknown",
                            detail=f"run {run_id} status payload was not an object")
            status = str(view.get("status") or "")
            conclusion = str(view.get("conclusion") or "")
        if conclusion == CI_CANCELLED:
            # Read here rather than from the step, because a cancelled run's
            # steps carry no useful conclusion - and the caller has a specific
            # remedy for this one word that it has for no other.
            return _out(CI_CANCELLED, run_id=run_id, head=head, status=status,
                        detail=f"run {run_id} completed 'cancelled' - superseded, "
                               f"or a job hit its own ceiling")
        step, detail = _ci_step_verdict(gh, run_id)
        return _out(step, run_id=run_id, head=head, status=status, detail=detail)

    out = _watch(run)
    if out["step"] != CI_CANCELLED or not allow_trigger:
        return out
    # ONCE. Being superseded is the exact failure this wait exists to survive,
    # so one fresh run is worth starting - but a driver that re-dispatched on
    # every cancel would spend the whole budget starting runs instead of
    # watching one, and would keep the runner busy for a night.
    again, err = _trigger_ci_run(gh, sha, seen, sleep=sleep)
    if err:
        return dict(out, detail=f"{out['detail']}; re-dispatch failed: {err}"[:400])
    return _watch(again)


def run_cycle(cycle: int, *, lane: str = LANE, worktree=None, run_id=None,
              poll_s: float = DEFAULT_POLL_S,
              cycle_timeout_s: float = DEFAULT_CYCLE_TIMEOUT_S,
              kill_grace_s: float = DEFAULT_KILL_GRACE_S,
              acquire_retries: int = ACQUIRE_RETRIES,
              acquire_wait_s: float = ACQUIRE_WAIT_S,
              acquire=lanes.try_acquire_lane,
              release=lanes.release_lane,
              launch=lane_launcher.launch_lane,
              alive=slots.pid_alive,
              proc_started=lanes.proc_started,
              stranger=lanes._holder_is_a_stranger,
              kill=_taskkill,
              sleep=time.sleep,
              clock=time.time,
              monotonic=time.monotonic) -> dict:
    """Run exactly one lane cycle: claim, launch, wait for the worker, release.

    Returns a record - it does not raise for any outcome the driver is supposed
    to survive. `lane_held` and `launch_failed` are recorded and returned so the
    loop can go on to the next cycle; only a genuinely unexpected fault (a seam
    that explodes) propagates, and even then the lane is released first.

    Every dependency is a keyword seam with a real default so the tests never
    spawn a process, never sleep and never touch the live control plane. The
    defaults are bound at definition time on purpose: a caller substituting a
    seam is making a deliberate choice, not monkeypatching a module attribute
    from underneath a running driver.
    """
    run_id = uuid.uuid4().hex[:8] if run_id is None else str(run_id)
    # Worktree-mandatory (operator 2026-07-30, enforced again in the lock and a
    # third time in the launcher). Resolved from the launcher rather than
    # hardcoded so a lane relocation moves one definition, not three.
    if worktree is None:
        worktree = lane_launcher.worktree_path(lane)

    started_at = clock()

    def _record(outcome, ok, pid, ended_at, detail=""):
        return {"cycle": int(cycle), "run_id": run_id, "ok": bool(ok),
                "pid": pid, "started_at": started_at, "ended_at": ended_at,
                "duration_s": round(ended_at - started_at, 3),
                "outcome": outcome, "detail": detail}

    # ---- claim, retrying while a DIFFERENT lane legitimately holds the lock
    claim = None
    attempts = max(1, int(acquire_retries))
    for attempt in range(1, attempts + 1):
        claim = acquire(lane, run_id=run_id, worktree=str(worktree))
        if claim.get("ok"):
            break
        # A refusal writes nothing on disk, so retrying is free and safe. No
        # wait after the FINAL attempt - it would only delay the record.
        if attempt < attempts:
            sleep(acquire_wait_s)
    if not (claim and claim.get("ok")):
        holder = (claim or {}).get("holder")
        return _record(
            OUTCOME_LANE_HELD, False, None, clock(),
            f"lane held by {holder!r} (pid {(claim or {}).get('pid')}) "
            f"after {attempts} attempts")

    token = claim.get("token")
    outcome, detail, pid = OUTCOME_COMPLETED, "", None
    try:
        try:
            run = launch(lane, run_id=run_id, token=token)
        except lane_launcher.LaneLaunchError as exc:
            # launch_lane has ALREADY released the lane on this path; the
            # finally below releases again, which is deliberate - release_lane
            # is idempotent and returns False when there is nothing of ours to
            # remove, and an unconditional release is the only shape that
            # survives a future launcher that stops cleaning up after itself.
            outcome, detail = OUTCOME_LAUNCH_FAILED, str(exc)[:400]
        else:
            pid = run.get("pid")
            if not pid:
                outcome, detail = OUTCOME_LAUNCH_FAILED, "launch returned no pid"
            else:
                detail = str(run.get("log") or "")
                # Identity, captured ONCE and only here. A pid alone does not
                # name a process, so every later probe compares (pid, start
                # time) against THIS value. None is the fail-soft answer - no
                # psutil, or the worker already gone - and `stranger` reads it
                # as "cannot prove reuse", which degrades this cycle to the
                # plain pid probe the driver used before.
                worker_started = proc_started(pid)
                # The budget starts HERE, at launch, on the MONOTONIC clock.
                # See the module docstring: the acquire retries above can burn
                # 600s, and none of it is the worker's.
                launched_m = monotonic()
                while _worker_is_up(pid, worker_started,
                                    alive=alive, stranger=stranger):
                    waited = monotonic() - launched_m
                    if waited >= float(cycle_timeout_s):
                        # EXACTLY once - the break is load-bearing. A second
                        # kill could land on a pid Windows has already reissued
                        # to an unrelated process (MEASURED 2026-08-02: a dead
                        # lane worker's pid 8820 became SearchFilterHost three
                        # minutes later).
                        kill(pid)
                        ran_for = round(waited, 1)
                        if _await_death(pid, worker_started, alive=alive,
                                        stranger=stranger,
                                        kill_grace_s=kill_grace_s,
                                        poll_s=poll_s, sleep=sleep,
                                        monotonic=monotonic):
                            outcome = OUTCOME_TIMEOUT
                            detail = (f"worker ran {ran_for}s against a "
                                      f"{cycle_timeout_s}s budget - killed")
                        else:
                            # Unrecoverable for the LOOP, not just this cycle:
                            # run_loop stops on this outcome rather than fire a
                            # second worker into a worktree that may still have
                            # a live writer in it.
                            outcome = OUTCOME_KILL_FAILED
                            detail = (f"worker ran {ran_for}s against a "
                                      f"{cycle_timeout_s}s budget - taskkill did "
                                      f"NOT take within {kill_grace_s}s; pid "
                                      f"{pid} may still be writing to {worktree}")
                        break
                    sleep(poll_s)
    finally:
        # Every path, including an exception nobody predicted. The release runs
        # BEFORE that exception escapes, because a driver that dies holding the
        # only lane slot wedges all ten lanes until someone reclaims by hand.
        release(token)

    return _record(outcome, outcome == OUTCOME_COMPLETED, pid, clock(), detail)


def run_loop(*, max_cycles: int = DEFAULT_MAX_CYCLES,
             settle_s: float = DEFAULT_SETTLE_S,
             poll_s: float = DEFAULT_POLL_S,
             cycle_timeout_s: float = DEFAULT_CYCLE_TIMEOUT_S,
             kill_grace_s: float = DEFAULT_KILL_GRACE_S,
             max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
             ci_gate: bool = True,
             ci_wait_s: float = DEFAULT_CI_WAIT_S,
             ci_poll_s: float = DEFAULT_CI_POLL_S,
             lane: str = LANE, worktree=None,
             control_dir=None, cycle_log=None,
             acquire_retries: int = ACQUIRE_RETRIES,
             acquire_wait_s: float = ACQUIRE_WAIT_S,
             acquire=lanes.try_acquire_lane,
             release=lanes.release_lane,
             launch=lane_launcher.launch_lane,
             alive=slots.pid_alive,
             proc_started=lanes.proc_started,
             stranger=lanes._holder_is_a_stranger,
             kill=_taskkill,
             head_sha=_head_sha,
             gh=_gh,
             wait=wait_for_ci,
             sleep=time.sleep,
             clock=time.time,
             monotonic=time.monotonic,
             emit=_emit) -> dict:
    """Fire cycles until `max_cycles`, a stop sentinel, or a hard stop.

    `stopped_by` is the sentinel's file name, "max_cycles" when the loop ran its
    full course, or one of the three hard stops: OUTCOME_KILL_FAILED (a worker
    survived its kill, so the lane worktree may still have a live writer),
    STOPPED_BY_CONSECUTIVE_ERRORS, and STOPPED_BY_CI_RED.

    The sentinel check is at the TOP of the iteration, which is what makes a
    QUEUE_DRAINED written by the worker mid-cycle stop the NEXT cycle rather
    than retroactively discard the one that wrote it. The hard stops are
    checked at the BOTTOM, after the offending record is appended and emitted -
    the evidence of why the night ended has to reach the ledger.

    THE CI GATE, and why it hangs off `origin/main` rather than off the worker.
    The driver never looks inside the lane worktree and has no channel to the
    worker beyond a pid, so the only push signal available to it is the remote
    ref moving: `head_sha()` is read before and after each cycle, and an
    UNCHANGED answer means the worker shipped nothing (a recall-closed row, a
    refuted row, a drained queue) and there is no run to wait for. The verdict
    is attached to the SAME record as `record["ci"]`, so one JSONL row carries a
    cycle and its acceptance and nobody has to join two files at 3am.

    An ABSENT `ci` key means no gate ran for that cycle - gate off, no push
    detected, or an outcome other than `completed`. It deliberately is NOT
    recorded as `step="skipped"`, because that word already means the `check`
    JOB was skipped, and one word cannot carry two conditions (the same defect
    `main`'s exit codes were split to fix).
    """
    records: list = []
    stopped_by = None
    consecutive_errors = 0
    error_limit = max(1, int(max_consecutive_errors))
    total = max(0, int(max_cycles))
    for cycle in range(1, total + 1):
        reason = stop_reason(control_dir)
        if reason:
            stopped_by = reason
            emit(f"queue-loop stop: {reason} present - {len(records)} cycle(s) run")
            break
        # Minted HERE, not inside run_cycle, so the error record below can name
        # the SAME run as the claim and the worker log. A cycle that faulted
        # before returning would otherwise leave a row nothing can be joined to.
        run_id = uuid.uuid4().hex[:8]
        started_at = clock()
        # BEFORE the cycle, unconditionally when the gate is on: the outcome is
        # not knowable in advance, and one `ls-remote` against a 25-to-45-minute
        # cycle is not a cost worth optimising.
        pre_sha = head_sha() if ci_gate else None
        try:
            record = run_cycle(cycle, lane=lane, worktree=worktree,
                               run_id=run_id, poll_s=poll_s,
                               cycle_timeout_s=cycle_timeout_s,
                               kill_grace_s=kill_grace_s,
                               acquire_retries=acquire_retries,
                               acquire_wait_s=acquire_wait_s,
                               acquire=acquire, release=release, launch=launch,
                               alive=alive, proc_started=proc_started,
                               stranger=stranger, kill=kill, sleep=sleep,
                               clock=clock, monotonic=monotonic)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all, see below
            # A night that ends at cycle 3 on ONE unexpected fault is the defect
            # this closes, and the SILENT half was the worse half: append_record
            # is only reached on the normal path, so the fault used to leave no
            # ledger row at all and the morning's evidence was a log that just
            # stopped. Nothing is leaked by catching here - run_cycle releases
            # the lane in its own `finally` before any exception escapes it.
            # The row is built in the same shape as every other so one consumer
            # reads the whole file.
            ended_at = clock()
            record = {"cycle": int(cycle), "run_id": run_id, "ok": False,
                      "pid": None, "started_at": started_at,
                      "ended_at": ended_at,
                      "duration_s": round(ended_at - started_at, 3),
                      "outcome": OUTCOME_ERROR,
                      "detail": f"{type(exc).__name__}: {exc}"[:400]}

        # ---- CI acceptance, BEFORE the append so one row carries both halves.
        ci_note = ""
        if ci_gate and record["outcome"] == OUTCOME_COMPLETED:
            post_sha = head_sha()
            if pre_sha is None or post_sha is None:
                # A tooling failure, and it is recorded as one. Staying silent
                # here would make a night with no CI evidence read exactly like
                # a night of greens.
                record["ci"] = {"sha": post_sha or pre_sha, "run_id": None,
                                "status": "unknown", "step": CI_UNAVAILABLE,
                                "waited_s": 0.0,
                                "detail": "origin/" + CI_REF + " could not be "
                                          "resolved, so this cycle's push could "
                                          "not be identified"}
            elif post_sha == pre_sha:
                ci_note = " ci=no-push"
            else:
                record["ci"] = wait(post_sha, budget_s=ci_wait_s,
                                    poll_s=ci_poll_s, gh=gh, sleep=sleep,
                                    monotonic=monotonic)
        verdict = record.get("ci")
        if verdict:
            ci_note = (f" ci={verdict['step']} run={verdict['run_id']} "
                       f"{verdict['waited_s']}s")

        records.append(record)
        append_record(record, cycle_log)
        # ONE line per cycle, still. The verdict rides on it rather than taking
        # a line of its own, because an operator tailing this reads a night by
        # counting cycles down the left margin.
        emit(f"queue-loop cycle {cycle}/{total} {record['outcome']} "
             f"run_id={record['run_id']} pid={record['pid']} "
             f"{record['duration_s']}s{ci_note} {record['detail']}".rstrip())

        if verdict and verdict["step"] == CI_FAILURE:
            # HARD STOP, and the only CI verdict that is one. Every further
            # cycle would push another row on top of a break nobody is
            # watching, and the rows would then have to be untangled from each
            # other before either could be judged. `cancelled` / `timeout` /
            # `skipped` / `unavailable` / `unknown` are all recorded and passed
            # over: none of them is evidence that main is broken.
            stopped_by = STOPPED_BY_CI_RED
            emit(f"queue-loop stop: ci is RED on {verdict['sha']} "
                 f"(run {verdict['run_id']}) - refusing to push another row "
                 f"onto a broken {CI_REF}")
            break
        if record["outcome"] == OUTCOME_KILL_FAILED:
            # HARD STOP. The next cycle would fire a second worker into a
            # worktree whose previous writer is still alive, and two writers in
            # one working directory is not recoverable by retrying.
            stopped_by = OUTCOME_KILL_FAILED
            emit(f"queue-loop stop: pid {record['pid']} survived its kill - "
                 f"refusing to launch into {lane} again this run")
            break
        if record["outcome"] == OUTCOME_ERROR:
            consecutive_errors += 1
            if consecutive_errors >= error_limit:
                # A fault that repeats is a fault that will repeat all night.
                stopped_by = STOPPED_BY_CONSECUTIVE_ERRORS
                emit(f"queue-loop stop: {consecutive_errors} consecutive "
                     f"error cycles - {record['detail']}")
                break
        else:
            # CONSECUTIVE, not cumulative. One bad cycle between good ones is a
            # transient the loop is supposed to survive; resetting here is what
            # keeps a flaky night from being scored as a broken one.
            consecutive_errors = 0

        # Between cycles only. A settle after the final cycle would just delay
        # the driver's own exit by 45s for nothing.
        if cycle < total:
            sleep(settle_s)
    if stopped_by is None:
        stopped_by = STOPPED_BY_MAX_CYCLES
    return {"cycles_run": len(records), "stopped_by": stopped_by,
            "records": records}


def main(argv=None, *, singleton=None) -> int:
    """CLI entry point for the detached launcher.

    Distinct exit codes, because the launcher cannot otherwise tell a night
    that ran from a launch that did nothing:

      EXIT_OK              cycles ran, or zero were asked for.
      EXIT_STOP_SENTINEL   zero cycles because a stop file was ALREADY there.
      EXIT_ALREADY_RUNNING another driver holds DRIVER_MUTEX.
      EXIT_KILL_FAILED     a worker outlived its kill - the worktree is suspect.
      EXIT_CONSECUTIVE_ERRORS the same fault repeated until the loop gave up.
      EXIT_CI_RED          the gating ci step went red on a pushed sha.

    The second one supersedes this function's original contract ("always
    returns 0 ... a drained queue is a SUCCESSFUL outcome"), and the reason is
    measured rather than theoretical: `ops/loop/control/STOP` exists on Legion
    right now, so every fire today ran zero cycles and reported success, and the
    launcher printed `queue-loop driver started` over it. A drained queue IS a
    successful outcome - but it is not the same outcome as a night's work, and
    one number cannot mean both. The distinction is drawn on cycles_run, so a
    sentinel that appears MID-run (the worker's own QUEUE_DRAINED, the normal
    end of a successful drain) still exits 0.

    `singleton` is a seam: a zero-argument callable returning a context manager
    that is held for the whole run. Tests pass a fake so they never touch a real
    OS mutex.
    """
    parser = argparse.ArgumentParser(
        prog="queue_loop",
        description="Re-fire the one-row queue lane worker cycle after cycle.")
    parser.add_argument("--cycles", type=int, default=DEFAULT_MAX_CYCLES,
                        help=f"max cycles to run (default {DEFAULT_MAX_CYCLES})")
    parser.add_argument("--settle", type=float, default=DEFAULT_SETTLE_S,
                        help=f"seconds between cycles (default {DEFAULT_SETTLE_S})")
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_S,
                        help=f"worker liveness poll seconds (default {DEFAULT_POLL_S})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_CYCLE_TIMEOUT_S,
                        help=f"hard cycle deadline (default {DEFAULT_CYCLE_TIMEOUT_S})")
    # Constrained to the lock's own roster so a typo fails here with a readable
    # message instead of surfacing as a ValueError from inside the first claim.
    parser.add_argument("--lane", default=LANE, choices=sorted(lanes.LANES),
                        help=f"lane to drive (default {LANE})")
    parser.add_argument("--control-dir", default=None,
                        help="where the stop sentinels live (default ops/loop/control)")
    parser.add_argument("--reports-dir", default=None,
                        help="where queue_loop.jsonl is written (default ops/loop/reports)")
    parser.add_argument("--ci-wait", type=float, default=DEFAULT_CI_WAIT_S,
                        help=(f"seconds to block on a pushed sha's ci run "
                              f"(default {DEFAULT_CI_WAIT_S})"))
    # A kill switch, not a mode. The gate is the point of this driver owning
    # the wait at all; turning it off is for a lane run whose CI is already
    # known bad, or for a box with no `gh` credentials.
    parser.add_argument("--no-ci-gate", action="store_true",
                        help="do not wait on ci after a cycle pushes")
    parser.add_argument("--once", action="store_true",
                        help="run exactly one cycle - overrides --cycles")
    args = parser.parse_args(argv)

    cycles = 1 if args.once else args.cycles
    cycle_log = (None if args.reports_dir is None
                 else Path(args.reports_dir) / CYCLE_LOG.name)
    control_dir = None if args.control_dir is None else Path(args.control_dir)

    guard = _driver_singleton if singleton is None else singleton
    try:
        with guard():
            summary = run_loop(max_cycles=cycles, settle_s=args.settle,
                               poll_s=args.poll, cycle_timeout_s=args.timeout,
                               ci_gate=not args.no_ci_gate,
                               ci_wait_s=args.ci_wait,
                               lane=args.lane, control_dir=control_dir,
                               cycle_log=cycle_log)
    except winmutex.MutexTimeout:
        # Not an error condition, a REFUSAL - and it must be loud, because the
        # symptom of two drivers is invisible at a glance: both survive, both
        # look busy, and each spends up to ten minutes per cycle losing the
        # acquire race to the other while their rows interleave in one ledger.
        # The remedy names taskkill and stops there. The PowerShell cmdlet this
        # repo bans cannot be named even to forbid it: the house-rules guard in
        # tests/test_queue_loop.py scans this file's code STRINGS for it and
        # cannot tell advice from a call site. It caught this line on the first
        # run, which is the guard working, not the guard being wrong.
        _emit(f"queue-loop refused: another driver already holds {DRIVER_MUTEX}. "
              f"Two drivers interleave on the lane lock and append to one "
              f"ledger. Stop that one first: taskkill /F /T /PID <pid>")
        return EXIT_ALREADY_RUNNING

    _emit(f"queue-loop done: {summary['cycles_run']} cycle(s), "
          f"stopped_by={summary['stopped_by']}")
    if summary["cycles_run"] == 0 and summary["stopped_by"] in STOP_NAMES:
        sentinel = stop_path_for(summary["stopped_by"], control_dir)
        _emit(f"queue-loop refused: {summary['stopped_by']} was ALREADY present "
              f"at {sentinel} - zero cycles ran. Delete that file to run.")
        return EXIT_STOP_SENTINEL
    # Checked AFTER the sentinel branch and independently of cycles_run: a hard
    # stop always ran at least one cycle, so the two cannot collide.
    if summary["stopped_by"] == OUTCOME_KILL_FAILED:
        _emit("queue-loop ALERT: a worker outlived its kill - treat "
              f"{lane_launcher.worktree_path(args.lane)} as having a possible "
              "live writer and check by hand before firing again.")
        return EXIT_KILL_FAILED
    if summary["stopped_by"] == STOPPED_BY_CONSECUTIVE_ERRORS:
        return EXIT_CONSECUTIVE_ERRORS
    if summary["stopped_by"] == STOPPED_BY_CI_RED:
        _emit("queue-loop ALERT: ci went RED on a pushed sha - the night "
              "stopped rather than stack more rows onto a broken tree. Read "
              f"the last row of {CYCLE_LOG.name} for the run id, fix the red, "
              "then fire the lane again.")
        return EXIT_CI_RED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
