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

"Stop the run" means exactly one act: `taskkill /F /T /PID <pid>` of the ONE
child this sampler launched itself (the gate process and its descendants:
pytest and its xdist workers). It never targets any other pid and never kills
a game process: a game is a reason to stop the suite, not a target. The child
is held as a Popen handle, so its pid cannot be reused while the sampler
lives; a child that already exited is never signalled.

Sequence: one "pre" read; a stop already holding there REFUSES (exit 91,
REFUSED.json, nothing launched). Then the command is launched (child stdout
and stderr to --child-log, CREATE_NO_WINDOW on Windows) and read every
--interval seconds until it exits (its exit code is returned) or a stop holds
(VOID.json written, exit 90 - never graded).

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
REAP_TIMEOUT_S = 30.0
EXIT_VOID = 90
EXIT_REFUSED = 91

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


class PopenChild:
    """The one launched child. kill_tree() is the sampler's ONLY kill."""

    def __init__(self, proc, run: Callable = subprocess.run) -> None:
        self.proc = proc
        self.pid = proc.pid
        self._run = run

    def wait(self, timeout: float) -> Optional[int]:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill_tree(self) -> Optional[int]:
        """taskkill /F /T on this child's pid; None if it already exited."""
        if self.proc.poll() is not None:
            return None
        res = self._run(
            kill_tree_argv(self.pid),
            capture_output=True,
            text=True,
            timeout=KILL_TIMEOUT_S,
            creationflags=_flags(),
            check=False,
        )
        return res.returncode


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
) -> int:
    """Read, launch, read every `interval` s; the child's rc, EXIT_VOID or EXIT_REFUSED."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "samples.jsonl"
    tracker = StopTracker()

    def sample(phase: str) -> Optional[str]:
        errors: dict = {}
        phys = _call(physical, errors, "physical")
        procs = _call(names, errors, "names")
        com = _call(commit, errors, "commit")
        reason = tracker.update(phys, procs)
        _append(
            log,
            {
                "phase": phase,
                "t": clock(),
                "physical_mb": None if phys is None else round(float(phys), 1),
                "commit_mb": None if com is None else round(float(com), 1),
                "games": None if procs is None else game_hits(procs),
                "head": _call(head, errors, "head"),
                "low_streak": tracker.low_streak,
                "stop": reason,
                "errors": errors,
            },
        )
        return reason

    reason = sample("pre")
    if reason:
        row = {"phase": "refused", "t": clock(), "reason": reason, "cmd": list(cmd)}
        _append(log, row)
        _marker(out_dir / "REFUSED.json", row)
        return EXIT_REFUSED
    child = launch(cmd)
    while True:
        rc = child.wait(interval)
        if rc is not None:
            _append(log, {"phase": "exit", "t": clock(), "rc": rc})
            return rc
        reason = sample("run")
        if reason:
            taskkill_rc = child.kill_tree()
            row = {
                "phase": "void",
                "t": clock(),
                "reason": reason,
                "pid": child.pid,
                "taskkill_rc": taskkill_rc,
                "child_rc": child.wait(REAP_TIMEOUT_S),
            }
            _append(log, row)
            _marker(out_dir / "VOID.json", row)
            return EXIT_VOID


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
    try:
        rc = run_sampler(cmd, a.dir, launch=lambda c: launch_child(c, a.child_log), head=head, interval=a.interval)
    except OSError as exc:
        print(f"landing_sampler: launch failed: {type(exc).__name__}: {exc}"[:300])
        return 2
    verdict = {EXIT_VOID: "VOID (see VOID.json)", EXIT_REFUSED: "REFUSED (see REFUSED.json)"}
    print(f"landing_sampler: exit {rc} {verdict.get(rc, 'child exit code')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
