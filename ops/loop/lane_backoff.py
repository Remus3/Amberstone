"""Empty-cycle back-off for the s144 lane rotator (MAIN ORDER 2026-11-14 0930 section 2,
ruling D1).

Measured by MAIN for 2026-11-08..11-14, all on opus: ds 293 of 427 cycles made no own
commit, gated 65 of 131, research 47 of 131. RULE: a lane whose last EMPTY_STREAK (3)
worker cycles made no own commit skips its next spawn until its queue or the rotator has
new work. Each skip episode is one ledger line (ops/loop/control/lanes/backoff.jsonl),
and so is the resume.

WORKER CYCLES. Only a cycle whose worker ran its course counts (WORKER_OUTCOMES); a
lane_held / rate_limited / launch_failed / refused-before-spawn record neither counts as
empty nor breaks the streak. A cycle's own commits are the driver's "own_commits"
(lane_own_commits), else the older "new_commits"; a record with neither is UNKNOWN and is
never empty (fail open: a lane is never starved on a missing field).

NEW WORK. lane_signals() names what defines a lane's work, and fingerprint() hashes it:
  - main's ROADMAP.md, BACKLOG.md and the lane doc tools/headless-<lane>.md (git blob ids
    on the LOCAL main branch: a merger landing new rows changes them);
  - the lane's directive s144-<lane>.tmpl (its ordered row list), s144-common.tmpl and the
    exclusions file lane_exclusions_s144.txt (the gitignored control files);
  - a kick file ops/loop/control/lanes/S144_WORK_<LANE> (any content change is new work:
    the merger's or operator's way to wake one lane by hand);
  - for gated only, whether a game is in progress (a live game is new work for it).
The driver's child stores the fingerprint it saw at cycle start in the cycle record
("work_fp"); the rotator compares the current fingerprint with the last worker cycle's.
A record written before this module (no "work_fp") arms on the first check: the
fingerprint at that moment becomes the baseline, kept in the lane's state file.

FAIL OPEN. Every caller wraps check() so a fault here never stops a rotator or a lane;
the driver then launches as before.

Stdlib plus core/ (atomic write, append), ASCII only; imported by the gitignored driver
as ops.loop.lane_backoff.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

EMPTY_STREAK = 3
WORKER_OUTCOMES = ("completed", "worker_failed", "timeout_killed", "kill_failed")
RELOG_S = 3600.0          # a skip that lasts re-logs at most once an hour, with its count
TAIL_BYTES = 256 << 10    # a cycle record is about 2-4 KB; 256 KB is the last ~60
PROMPTS_REL = Path("ops/loop/control/lane_prompts")
LANES_REL = Path("ops/loop/control/lanes")
LEDGER_REL = LANES_REL / "backoff.jsonl"
EXCLUSIONS_REL = Path("ops/loop/control/lane_exclusions_s144.txt")
MAIN_FILES = ("ROADMAP.md", "BACKLOG.md")
PREFIX = "s144"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def append_line(path: Path, line: str) -> None:
    """One ASCII line appended in ONE write (Windows FILE_APPEND_DATA through
    core.operator_notify, since a plain O_APPEND is not atomic on Windows)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (line.rstrip("\n") + "\n").encode("ascii", "replace")
    try:
        from core import operator_notify as notify  # noqa: PLC0415
    except ImportError:
        notify = None
    if notify is not None and notify._on_windows():  # noqa: SLF001 - shared helper
        notify._win32_append(path, data)  # noqa: SLF001
        return
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
                 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def write_json(path: Path, doc) -> None:
    from core.polled_json import atomic_write_bytes  # noqa: PLC0415
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, json.dumps(doc, sort_keys=True).encode("ascii", "replace") + b"\n")


def read_json(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


# ------------------------------------------------------------------ cycles

def tail_cycles(path: Path, tail_bytes: int = TAIL_BYTES) -> list:
    """The cycle records in the last `tail_bytes` of a cycles jsonl; a partial first
    line and any unparsable line are skipped. [] when the file is absent."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if size > tail_bytes and lines:
        lines = lines[1:]
    out = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def own_commits(rec: dict):
    """The cycle's own commit count, or None when the record cannot say."""
    for key in ("own_commits", "new_commits"):
        val = rec.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    return None


def worker_cycles(cycles) -> list:
    return [c for c in cycles if isinstance(c, dict) and c.get("outcome") in WORKER_OUTCOMES]


def empty_streak(cycles, n: int = EMPTY_STREAK) -> bool:
    """True when the last `n` worker cycles each made exactly 0 own commits."""
    tail = worker_cycles(cycles)[-n:]
    return len(tail) >= n and all(own_commits(c) == 0 for c in tail)


# ------------------------------------------------------------------ new work

def git_blobs(root, rels, ref: str = "main", run=None) -> dict:
    """{path: blob id} of `rels` on `ref` (git ls-tree); a path absent there is left
    out. Raises on a git failure (the caller fails open)."""
    run = run or subprocess.run
    r = run(["git", "ls-tree", ref, "--", *rels], cwd=str(root), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-tree {ref} failed rc={r.returncode}: "
                           f"{(r.stderr or '').strip()[:200]}")
    out = {}
    for ln in (r.stdout or "").splitlines():
        meta, _tab, path = ln.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and path:
            out[path] = parts[2]
    return out


def _digest(path: Path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def lane_doc_rel(lane: str) -> str:
    return f"tools/headless-{lane}.md"


def kick_name(lane: str) -> str:
    return f"S144_WORK_{lane.upper().replace('-', '_')}"


def lane_signals(root, lane: str, *, in_game=None, git_blobs=git_blobs,
                 prefix: str = PREFIX) -> dict:
    """What defines `lane`'s work now (module docstring, NEW WORK)."""
    root = Path(root)
    prompts = root / PROMPTS_REL
    rels = [*MAIN_FILES, lane_doc_rel(lane)]
    sig = {"main": git_blobs(root, rels),
           "directive": _digest(prompts / f"{prefix}-{lane}.tmpl"),
           "common": _digest(prompts / f"{prefix}-common.tmpl"),
           "exclusions": _digest(root / EXCLUSIONS_REL),
           "kick": _digest(root / LANES_REL / kick_name(lane))}
    if in_game is not None:
        sig["in_game"] = bool(in_game)
    return sig


def fingerprint(signals: dict) -> str:
    return hashlib.sha256(json.dumps(signals, sort_keys=True).encode("ascii",
                                                                     "replace")).hexdigest()


def lane_fingerprint(root, lane: str, *, in_game=None, git_blobs=git_blobs) -> str:
    return fingerprint(lane_signals(root, lane, in_game=in_game, git_blobs=git_blobs))


# ------------------------------------------------------------------ decision

class Decision(NamedTuple):
    skip: bool
    reason: str
    state: dict          # the state to keep ({} = none)
    event: str | None    # "skip" / "resume" -> one ledger line; None -> no line


def decide(cycles, fp: str, state: dict, now: float | None = None,
           n: int = EMPTY_STREAK) -> Decision:
    """Pure decision. `state` is the lane's stored back-off state ({} when none)."""
    now = time.time() if now is None else float(now)
    state = dict(state or {})
    skipping = bool(state.get("skipping"))
    if not empty_streak(cycles, n):
        return Decision(False, "", {}, "resume" if skipping else None)
    tail = worker_cycles(cycles)[-n:]
    last = tail[-1]
    run_id = str(last.get("run_id") or "")
    base = last.get("work_fp")
    if not base:
        base = state.get("fingerprint") if state.get("run_id") == run_id else None
    if not base:
        base = fp  # an older record with no fingerprint: arm on this check
    runs = [str(c.get("run_id") or "") for c in tail]
    if fp != base:
        reason = (f"new work since {run_id} (queue / directive / main rows / kick changed) - "
                  f"spawn")
        new = {"run_id": run_id, "fingerprint": base, "skipping": False, "released_by": fp}
        return Decision(False, reason, new, "resume" if skipping else None)
    reason = (f"{n} consecutive worker cycles with no own commit ({', '.join(runs)}) and no "
              f"new queue or rotator work since {run_id} - next spawn skipped")
    same_episode = skipping and state.get("run_id") == run_id
    skips = int(state.get("skips") or 0) + 1 if same_episode else 1
    logged_at = float(state.get("logged_at") or 0.0) if same_episode else 0.0
    event = None
    if not same_episode or now - logged_at >= RELOG_S:
        event, logged_at = "skip", now
    new = {"run_id": run_id, "fingerprint": base, "skipping": True, "skips": skips,
           "since": state.get("since") if same_episode else now, "logged_at": logged_at,
           "empty_runs": runs}
    return Decision(True, reason, new, event)


def check(root, lane: str, *, cycles_path, state_path, ledger_path=None, in_game=None,
          now: float | None = None, git_blobs=git_blobs, log=None) -> dict:
    """The rotator's one call per candidate lane. Returns {"skip", "reason", "event"};
    writes the state file and, on an event, one ledger line."""
    root = Path(root)
    ledger_path = Path(ledger_path) if ledger_path else root / LEDGER_REL
    cycles = tail_cycles(cycles_path)
    state = read_json(state_path)
    if not empty_streak(cycles) and not state:
        return {"skip": False, "reason": "", "event": None}
    fp = lane_fingerprint(root, lane, in_game=in_game, git_blobs=git_blobs) \
        if empty_streak(cycles) else ""
    d = decide(cycles, fp, state, now)
    if d.state != state:
        if d.state:
            write_json(state_path, d.state)
        else:
            try:
                Path(state_path).unlink()
            except OSError:
                pass
    if d.event:
        row = {"ts": _now_iso(), "lane": lane, "event": d.event, "reason": d.reason or
               "streak broken: a recent worker cycle made an own commit",
               "skips": d.state.get("skips"), "empty_runs": d.state.get("empty_runs") or
               state.get("empty_runs"), "fingerprint": (fp or "")[:12]}
        append_line(ledger_path, json.dumps(row, sort_keys=True))
        if log is not None:
            log(f"backoff {d.event} {lane}: {row['reason']}")
    return {"skip": d.skip, "reason": d.reason, "event": d.event}
