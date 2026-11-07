"""Landing-run sampler: launch ONE gated whole-suite command and enforce its STOPs.

The s152 NA2 ruling (docs/_archive/2026-11/2026-11-07-s152-na2-gated-suite-
launch-ruling.md, condition 8 and STOPS) requires the landing agent's sampler
to run BEFORE launch, read every 10 s, write to a file in its own scratch
subfolder and enforce the stops. Until NA6 it existed only as prose. This tool
enforces the two STOPs owed by the s151 hand-off (LEDGER 2056):

- physical-memory STOP: available physical memory under PHYS_STOP_MB (1024)
  on PHYS_STOP_READS (2) CONSECUTIVE reads. A read at or above the floor
  resets the count; an unreadable read neither counts nor resets it.
- game-process STOP: any League / Riot / Vanguard process image (game_hits)
  on ONE read. An unreadable process list is no evidence, not a stop.

It also RECORDS (no stop) free commit and, with --repo, that checkout's HEAD.
The other ruling stops (free commit on 3 reads, a HEAD / porcelain straddle,
harness reaps, WinError 1455) stay with the landing agent.

"Stop the run" targets ONLY the ONE child this sampler launched itself (the
gate process; its descendants are pytest and the xdist workers). It never
targets any other pid and never kills a game process: a game is a reason to
stop the suite, not a target. Once a STOP is decided the KILL runs FIRST and
unconditionally: no log write, git call or clock read sits between the
decision and PopenChild.stop():
1. `taskkill /F /T /PID <child pid>` (the whole tree), then a REAP_TIMEOUT_S
   wait for the child;
2. on ANY taskkill failure - TimeoutExpired, a missing taskkill
   (FileNotFoundError), a non-zero rc, or rc 0 with the child still alive -
   the fallback Popen.kill() (TerminateProcess on the held handle: the child
   pid only, NOT its descendants), then another REAP_TIMEOUT_S wait.
3. a child that EXITED BEFORE the kill (its pytest tree may not have):
   taskkill /F /T on its pid ONLY while handle_held() proves this sampler
   still holds the child's open process handle; else no taskkill. Either way
   it is 92 unless taskkill returned 0 ("child exited before kill;
   descendants unverified"); in practice taskkill reports an exited root as
   not found.
VOID.json records taskkill_rc / taskkill_error, fallback, child_rc,
child_exited, exited_before_kill, handle_held, note and tree_confirmed
(taskkill rc 0 AND the child exited).

Pid-reuse basis for step 3 (checked 2026-11-07): Microsoft Learn "Process
Handles and Identifiers" documents that a process handle stays valid until
closed even after the process terminates, but formally promises the
identifier only "until the process has been terminated". The reservation
past termination is kernel behaviour described by Microsoft's Raymond Chen
(The Old New Thing, 2011-01-07, "When does a process ID become available for
reuse?"): the PID lives as long as the process object, and the object lives
while any handle to it is open. CPython's Windows Popen keeps that handle in
`_handle` and its poll() / wait() / kill() never close it (Lib/subprocess.py,
Python 3.14: Handle.Close runs only on Close() or garbage collection), and
PopenChild holds the Popen for the sampler's lifetime.

Diagnostics come AFTER the kill and are best-effort, each guarded: a failed
samples.jsonl row never stops monitoring or the kill (loud stderr once), and
a failed VOID.json write forces exit 92 with a loud stderr line - never a
traceback exit 1.

Residual (documented, not fixed): `/T` walks descendants by their recorded
parent pid at kill time. Windows does not invalidate a parent pid when the
parent exits, so pid reuse can, rarely, put an unrelated process whose dead
parent had the same pid as a member of this tree under the /T walk. The held
handle protects only the child's own pid.

Sequence: one "pre" read; a stop already holding there REFUSES (exit 91,
REFUSED.json, nothing launched). Then the command is launched (child stdout
and stderr to --child-log, CREATE_NO_WINDOW on Windows); a launch that raises
OSError is exit 93 (a "launch_failed" row, no VOID.json). Then a read every
--interval seconds until the child exits (its exit code is returned) or a
stop holds. EVERY stop kills first, then tries to write VOID.json (never
graded), and returns:
- 90 EXIT_VOID: taskkill /F /T returned 0, the child is confirmed exited,
  and VOID.json was written;
- 92 EXIT_VOID_UNCONFIRMED: anything else - the fallback was needed (the
  gate is dead but pytest and its workers are NOT confirmed dead, since the
  gate holds no job object), the child exited before the kill and taskkill
  did not return 0, the child is not confirmed exited, stop() itself raised,
  or VOID.json could not be written. The sampler prints a loud stderr line;
  the landing agent must then find and end the remaining suite tree by hand.

Readers reuse the vendored kit and the launcher (no subprocess per read):
physical = ops/fleet_kit/fleet_lanes.py free_ram_mb (GlobalMemoryStatusEx
ullAvailPhys; read 2026-11-07 against GetPerformanceInfo PhysicalAvailable:
25045.1 vs 25045.3 MB), commit = ops/fleet_kit/fleet_suite_gate.py
free_commit_mb, process names = ops/launcher/updater.py running_process_names
(Toolhelp32 snapshot).

Usage (from the repo root; the gate command words unchanged after `--`):
    python tools/landing_sampler.py --dir <scratch>/landing-sampler \
        --child-log <scratch>/suite.txt --repo <main checkout> \
        -- python ops/fleet_kit/fleet_suite_gate.py run --owner <id> ...
Output: <dir>/samples.jsonl (one ASCII JSON line per read), plus VOID.json or
REFUSED.json; one final stdout line `landing_sampler: ...`.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import importlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

PHYS_STOP_MB = 1024
PHYS_STOP_READS = 2
INTERVAL_S = 10.0
KILL_TIMEOUT_S = 30
REAP_TIMEOUT_S = 10.0
EXIT_LAUNCH_FAILED = 93
EXIT_VOID = 90
EXIT_REFUSED = 91
EXIT_VOID_UNCONFIRMED = 92

# Lower-case image names. The s152 ruling's list: LeagueClient*, League of
# Legends, RiotClient*, vgc, vgtray; plus "Riot Client.exe" and the TFT game
# image (core/hot_reload.py GAME_PROCESS_NAMES).
GAME_IMAGE_PREFIXES = ("league of legends", "leagueclient", "riotclient", "riot client")
GAME_IMAGES = frozenset({"vgc.exe", "vgtray.exe", "tftclient-win64-shipping.exe"})

_CREATE_NO_WINDOW = 0x08000000


def _flags() -> int:
    """CREATE_NO_WINDOW on Windows (a windowless parent's console child);
    0 elsewhere, where creationflags must be 0."""
    return _CREATE_NO_WINDOW if sys.platform == "win32" else 0


def game_hits(names: Iterable[str]) -> list:
    """Sorted lower-case League / Riot / Vanguard images among `names`."""
    hits = set()
    for name in names:
        low = str(name).lower()
        if low in GAME_IMAGES or low.startswith(GAME_IMAGE_PREFIXES):
            hits.add(low)
    return sorted(hits)


class StopTracker:
    """The two STOPs over a stream of reads; update() returns a reason or None."""

    def __init__(self, phys_stop_mb: float = PHYS_STOP_MB, phys_stop_reads: int = PHYS_STOP_READS) -> None:
        self.phys_stop_mb = phys_stop_mb
        self.phys_stop_reads = phys_stop_reads
        self.low_streak = 0

    def update(self, physical_mb: Optional[float], names: Optional[Iterable[str]]) -> Optional[str]:
        if physical_mb is not None:
            if physical_mb < self.phys_stop_mb:
                self.low_streak += 1
            else:
                self.low_streak = 0
        hits = game_hits(names) if names is not None else []
        if hits:
            return "game process " + ", ".join(hits)
        if self.low_streak >= self.phys_stop_reads:
            return f"physical {physical_mb:.0f} MB < {self.phys_stop_mb} MB on {self.low_streak} consecutive reads"
        return None


# ---------------------------------------------------------------- readers


def _kit(name: str):
    return importlib.import_module(f"ops.fleet_kit.{name}")


def read_physical_mb() -> Optional[float]:
    return _kit("fleet_lanes").free_ram_mb()


def read_commit_mb() -> Optional[float]:
    return _kit("fleet_suite_gate").free_commit_mb()


def read_process_names() -> frozenset:
    from ops.launcher.updater import running_process_names

    return running_process_names()


def read_head(repo: Path) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_flags(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


# ---------------------------------------------------------------- the child


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]


class PopenChild:
    """The one launched child. stop() is the sampler's ONLY kill."""

    def __init__(self, proc, run: Callable = subprocess.run) -> None:
        self.proc = proc
        self.pid = proc.pid
        self._run = run

    def wait(self, timeout: float) -> Optional[int]:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def handle_held(self) -> bool:
        """True only while this sampler provably holds an OPEN process handle
        to the child: CPython's Windows Popen keeps it in `_handle`, a
        Handle(int) that poll() / wait() / kill() never close (only Close()
        or GC does). Anything else (POSIX, a closed or missing handle) is
        False: the pid is then not provably unreused."""
        handle = getattr(self.proc, "_handle", None)
        return handle is not None and getattr(handle, "closed", True) is False

    def _taskkill(self, out: dict) -> None:
        try:
            res = self._run(
                kill_tree_argv(self.pid),
                capture_output=True,
                text=True,
                timeout=KILL_TIMEOUT_S,
                creationflags=_flags(),
                check=False,
            )
            out["taskkill_rc"] = res.returncode
        except Exception as exc:  # noqa: BLE001 - timeout, missing exe, anything: recorded
            out["taskkill_error"] = _err(exc)

    def stop(self, reap_s: float = REAP_TIMEOUT_S) -> dict:
        """taskkill /F /T on the child's pid; on any failure, Popen.kill on
        the held handle (child pid only). Never raises from taskkill."""
        out = {
            "pid": self.pid,
            "taskkill_rc": None,
            "taskkill_error": None,
            "fallback": None,
            "child_rc": None,
            "child_exited": False,
            "tree_confirmed": False,
            "exited_before_kill": False,
            "handle_held": None,
            "note": None,
        }
        rc = self.proc.poll()
        if rc is not None:
            # The gate exited on its own before the kill; its pytest tree
            # may not have. /T on its pid only while the held handle keeps
            # that pid from being reused.
            out.update(child_rc=rc, child_exited=True, exited_before_kill=True)
            out["handle_held"] = self.handle_held()
            if not out["handle_held"]:
                out["note"] = (
                    "child exited before kill; descendants unverified "
                    "(no open handle, so the pid may be reused: taskkill skipped)"
                )
                return out
            self._taskkill(out)
            out["tree_confirmed"] = out["taskkill_rc"] == 0
            if not out["tree_confirmed"]:
                out["note"] = "child exited before kill; descendants unverified"
            return out
        self._taskkill(out)
        if out["taskkill_rc"] == 0:
            rc = self.wait(reap_s)
        if rc is None:
            try:
                self.proc.kill()
                out["fallback"] = "Popen.kill"
            except Exception as exc:  # noqa: BLE001 - recorded; the child is then unconfirmed
                out["fallback"] = "Popen.kill failed: " + _err(exc)
            rc = self.wait(reap_s)
        out["child_rc"] = rc
        out["child_exited"] = rc is not None
        out["tree_confirmed"] = out["taskkill_rc"] == 0 and out["fallback"] is None and rc is not None
        return out


def kill_tree_argv(pid: int) -> list:
    return ["taskkill", "/F", "/T", "/PID", str(int(pid))]


def launch_child(cmd: list, child_log: Path) -> PopenChild:
    """Start `cmd` with stdout + stderr appended to `child_log`."""
    child_log.parent.mkdir(parents=True, exist_ok=True)
    with open(child_log, "ab") as fh:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, creationflags=_flags()
        )
    return PopenChild(proc)


# ---------------------------------------------------------------- the loop


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _append(path: Path, row: dict) -> None:
    with open(path, "ab") as fh:
        fh.write((json.dumps(row) + "\n").encode("ascii"))


def _marker(path: Path, row: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((json.dumps(row, indent=1) + "\n").encode("ascii"))
    tmp.replace(path)


def _call(reader: Optional[Callable], errors: dict, key: str):
    if reader is None:
        return None
    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 - a failed read is recorded, not fatal
        errors[key] = f"{type(exc).__name__}: {exc}"[:200]
        return None


def run_sampler(
    cmd: list,
    out_dir: Path,
    *,
    launch: Callable,
    physical: Optional[Callable] = read_physical_mb,
    commit: Optional[Callable] = read_commit_mb,
    names: Optional[Callable] = read_process_names,
    head: Optional[Callable] = None,
    interval: float = INTERVAL_S,
    clock: Callable[[], str] = _now,
    reap_s: float = REAP_TIMEOUT_S,
) -> int:
    """Read, launch, read every `interval` s. Returns the child's rc, or
    EXIT_REFUSED / EXIT_LAUNCH_FAILED / EXIT_VOID / EXIT_VOID_UNCONFIRMED."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "samples.jsonl"
    tracker = StopTracker()
    warned = []

    def write(fn: Callable, *args) -> Optional[str]:
        """A best-effort diagnostic write: never raises; loud once on failure."""
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 - a diagnostic write never ends monitoring
            msg = _err(exc)
            if not warned:
                warned.append(msg)
                _loud(f"landing_sampler: WARNING diagnostic write failed ({msg}); monitoring continues")
            return msg
        return None

    def read() -> tuple:
        """The stop-deciding reads only (no subprocess); commit rides along."""
        errors: dict = {}
        phys = _call(physical, errors, "physical")
        procs = _call(names, errors, "names")
        com = _call(commit, errors, "commit")
        return tracker.update(phys, procs), phys, procs, com, errors

    def stamp() -> Optional[str]:
        try:
            return clock()
        except Exception:  # noqa: BLE001 - a clock failure costs a timestamp, nothing else
            return None

    def row_for(phase: str, reason, phys, procs, com, errors: dict) -> dict:
        return {
            "phase": phase,
            "t": stamp(),
            "physical_mb": _mb(phys),
            "commit_mb": _mb(com),
            "games": None if procs is None else game_hits(procs),
            "head": _call(head, errors, "head"),
            "low_streak": tracker.low_streak,
            "stop": reason,
            "errors": errors,
        }

    reason, *vals = read()
    write(_append, log, row_for("pre", reason, *vals))
    if reason:
        refused = {"phase": "refused", "t": stamp(), "reason": reason, "cmd": list(cmd)}
        failed = write(_marker, out_dir / "REFUSED.json", refused)
        if failed:
            _loud(f"landing_sampler: REFUSED ({reason}) but REFUSED.json NOT written ({failed}); nothing launched")
        return EXIT_REFUSED
    try:
        child = launch(cmd)
    except OSError as exc:
        launch_row = {"phase": "launch_failed", "t": stamp(), "error": _err(exc), "cmd": list(cmd)}
        write(_append, log, launch_row)
        return EXIT_LAUNCH_FAILED
    while True:
        rc = child.wait(interval)
        if rc is not None:
            write(_append, log, {"phase": "exit", "t": stamp(), "rc": rc})
            return rc
        reason, *vals = read()
        if reason:
            # KILL FIRST: nothing (no write, no git, no clock) runs between
            # the stop decision and stop(); every diagnostic comes after.
            kill = _stop_child(child, reap_s)
            run_row = functools.partial(row_for, "run", reason, *vals)
            return _void(child, kill, reason, out_dir, log, write, run_row, stamp)
        write(_append, log, row_for("run", None, *vals))


def _mb(value) -> Optional[float]:
    try:
        return None if value is None else round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _loud(msg: str) -> None:
    """stderr, flushed; a closed stderr must not turn a VOID into exit 1."""
    with contextlib.suppress(Exception):
        print(msg, file=sys.stderr, flush=True)


def _stop_child(child, reap_s: float) -> dict:
    """child.stop(), never raising: an exception is recorded as unconfirmed."""
    try:
        return dict(child.stop(reap_s=reap_s))
    except Exception as exc:  # noqa: BLE001 - VOID.json is written whatever stop() does
        return {"stop_error": _err(exc), "child_exited": False, "tree_confirmed": False}


def _void(
    child, kill: dict, reason: str, out_dir: Path, log: Path, write: Callable, run_row: Callable, stamp: Callable
) -> int:
    """After the kill: best-effort, individually guarded diagnostics; 90 only
    when the tree is confirmed AND VOID.json was written, else 92 + loud."""
    failures = []
    failed = write(lambda: _append(log, run_row()))
    if failed:
        failures.append(f"samples.jsonl run row: {failed}")
    row = {"phase": "void", "t": stamp(), "reason": reason, "pid": child.pid}
    row.update(kill)
    failed = write(_append, log, row)
    if failed:
        failures.append(f"samples.jsonl void row: {failed}")
    void_failed = write(_marker, out_dir / "VOID.json", row)
    confirmed = row.get("tree_confirmed") is True
    if confirmed and not void_failed:
        if failures:
            _loud(f"landing_sampler: VOID written, tree confirmed dead; log rows lost: {'; '.join(failures)}")
        return EXIT_VOID
    what = []
    if void_failed:
        what.append(f"VOID.json NOT written ({void_failed})")
    if row.get("stop_error"):
        what.append(f"stop() raised ({row['stop_error']})")
    if not row.get("child_exited"):
        what.append("child NOT confirmed exited")
    elif row.get("exited_before_kill") and not confirmed:
        what.append("child exited before kill; descendants unverified")
    elif not confirmed:
        what.append("suite tree NOT confirmed dead (fallback kill: the gate pid only)")
    _loud(
        f"landing_sampler: VOID {reason}: {'; '.join(what)} (pid {child.pid}; taskkill_rc "
        f"{row.get('taskkill_rc')}, fallback {row.get('fallback')}) - end the remaining suite tree by hand"
    )
    return EXIT_VOID_UNCONFIRMED


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", required=True, type=Path, help="own scratch subfolder")
    p.add_argument("--child-log", required=True, type=Path, help="child stdout + stderr")
    p.add_argument("--repo", type=Path, default=None, help="checkout whose HEAD is recorded")
    p.add_argument("--interval", type=float, default=INTERVAL_S)
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        p.error("no command after --")
    if a.interval <= 0:
        p.error("--interval must be > 0")
    head = (lambda: read_head(a.repo)) if a.repo is not None else None
    rc = run_sampler(cmd, a.dir, launch=lambda c: launch_child(c, a.child_log), head=head, interval=a.interval)
    verdict = {
        EXIT_LAUNCH_FAILED: "launch failed (see samples.jsonl)",
        EXIT_VOID: "VOID (see VOID.json)",
        EXIT_REFUSED: "REFUSED (see REFUSED.json)",
        EXIT_VOID_UNCONFIRMED: "VOID, suite tree NOT confirmed dead (see VOID.json)",
    }
    print(f"landing_sampler: exit {rc} {verdict.get(rc, 'child exit code')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
