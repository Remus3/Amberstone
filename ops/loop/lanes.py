#!/usr/bin/env python
r"""Lane locks - up to LANE_CAP headless lanes at once, each lane NAME exclusive.

The roster is stated ONCE, immediately below, and the prose deliberately does
not recite its size: "the seven headless lanes" sat here while the tuple two
lines down already carried eight (caught 2026-09-05 when the `queue` lane
landed), and a count in prose goes stale the moment a lane is added.

    LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit",
             "gated", "queue")

FLEET-KIT v6 (MAIN order 2026-10-04 2237 section 4a; v7 rides it). Until then
every lane was mutually exclusive with every other one: `MAX_SLOTS = 1` and a
single `0.lock`. The lock layer now IS the vendored kit's `fleet_lanes`
(ops/fleet_kit/fleet_lanes.py, byte-pinned by its MANIFEST, never edited here):
lane locks `<main tree>/ops/loop/control/lanes/<i>.lock` for i in
range(LANE_CAP), the lane NAME a payload field, a name exclusive by default.
So any three DIFFERENT lanes may run at once and no lane runs twice.

THE CAP IS THE MACHINE'S, READ LIVE (FLEET-KIT v25 LANE-CAP, MAIN 2026-10-27
2136 ORDER section 5 step 2). RC takes the kit's whole per-tree cap and asks for
no less: `lane_cap()` is `fleet_lanes.lane_cap(None)`, the live `lane_cap_max`
of the machine config `~/.fleet/lanes.json` (clamped to its governor width),
re-read on every acquire and state read, so a widened machine config needs no
restart and no RC edit. With the file missing it is the kit default (3), so
nothing changes until MAIN writes the file. `LANE_CAP` below is that DEFAULT
only, kept for readers that want the no-config value; no code path here sizes
anything by it. Each lane is worktree-isolated and each executor call still
takes its own governor slot, so the governor - not this cap - bounds total
concurrent model calls across the fleet.

FAIR RELEASE (v25). `should_yield()` is the kit's `should_yield("RC")`: True
when another tree waits for a slot, none is free, and RC holds more than its
fair share. A multi-cycle lane driver (queue_loop.run_loop) asks it BETWEEN
cycles and, on True, ends that lane instead of starting the next cycle. It is
advisory and read-only: nothing here or in the driver kills, terminates or
signals a running worker because of it.

ADMISSION (v25). The kit may refuse an acquire with `refused == "admission"`
(free RAM below ram_floor_mb or CPU above cpu_ceiling_pct); it writes no lock
and is handled exactly like `lanes_full` - recorded, retried next tick.

THE LOCK DIR IS RESOLVED AGAINST THE MAIN TREE (SS 2245 section 5a, measured in
RC too). `DEFAULT_ROOT` used to be `Path(__file__).parent / "control/lanes"`;
imported from inside a lane worktree that is the WORKTREE's gitignored control
dir, so a driver started there claimed into a private directory and three lanes
became three private caps of one. It is now `REPO_ROOT / LANES_REL`, and
REPO_ROOT is the main tree even from a worktree.

WORKTREES STAY PER LANE NAME (adjudicated; SS 2245 section 5c applies to RC).
The kit's own layer 2 puts lane index i in `<parent>/rc-worktrees/lane-<i>`,
DETACHED. RC's lanes run on a long-lived branch per lane name
(`lane/<name>` in `rc-lane-<name>`, lane_launcher.py), and every lane prompt
under tools/headless-*.md is written against that layout. Because names are
exclusive, a per-name worktree is never shared by two concurrent lanes - the
invariant the kit's per-index worktree exists to guarantee - so RC keeps its
layout and records the worktree it ACTUALLY uses in the lock payload.
Alternative rejected: the kit's detached lane-<i> worktrees, which would strand
each lane's branch history and rewrite eight prompts in one slice. Reverses if:
MAIN rules the kit worktree path mandatory, or a non-exclusive lane is added.

THREE STATES, NOT TWO. A lock whose pid is DEAD is indistinguishable from a
live one by file inspection alone (measured 2026-07-30, RUNNING.lock pid 9380).
FREE / RUNNING / RECLAIMABLE is decided by probing the pid AND its start time
(the 2026-08-02 pid-reuse wedge, tests/test_lane_pid_reuse.py) - both now the
kit's `_lane_row` rules. RECLAIMABLE must never render as RUNNING.

READS DO NOT WRITE. `lane_state` / `lanes_state` are the dashboard's poll path.
Clearing a stale lock happens only inside `try_acquire_lane`.

REFUSE, DO NOT QUEUE. A fire against a held name, or with every index held,
returns `{"ok": False, "refused": "lane_held" | "lanes_full" | "admission", ...}`
and writes no lane lock.

ONE GOVERNOR SLOT PER EXECUTOR CALL, NOT HERE. Nothing in this module takes a
governor slot; loop_controller's slots.hold around its executor call is that
call's one slot. Never also pass governor= to a spawn inside it.

NOTHING HERE STARTS A PROCESS. `pid` in the payload is the CLAIMER's; the
launcher re-points it at the worker via `repoint_lane_pid`.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# RM-836: the module had no logger, so a lane-lock write fault was recorded
# nowhere. The cause goes here, scrubbed (RM-321); results carry fixed lines.
log = logging.getLogger("rc.loop.lanes")


def _main_tree_root(start: Path | None = None) -> Path:
    """Resolve the MAIN working tree, even when imported from a worktree.

    `Path(__file__).parents[2]` alone is wrong the moment this module is
    imported from inside a git worktree - it returns the WORKTREE, and the
    worktree-mandatory guard below then inverts: it would reject the worktree a
    lane legitimately runs in, and ACCEPT the main tree it must never touch.
    That is exactly the configuration this feature ships in (lanes are
    worktree-mandatory by operator decision 2026-07-30), so the naive form is a
    latent hole rather than a theoretical one.

    Detection needs no subprocess. In a main tree `.git` is a DIRECTORY; in a
    worktree it is a FILE holding `gitdir: <main>/.git/worktrees/<name>`, and
    the main tree is that path's parents[2] parent. Falls back to the naive
    answer if `.git` is missing or unreadable (a plain export, a test tmpdir),
    which keeps this total rather than raising at import time.
    """
    root = (start or Path(__file__).resolve()).parents[2] if start is None else start
    dotgit = root / ".git"
    try:
        if dotgit.is_file():
            raw = dotgit.read_text(encoding="utf-8").strip()
            if raw.startswith("gitdir:"):
                gitdir = Path(raw.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (root / gitdir).resolve()
                # <main>/.git/worktrees/<name> -> parents[2] is <main>/.git's parent
                if gitdir.parent.name == "worktrees":
                    return gitdir.parents[2]
    except (OSError, UnicodeError):
        # Git writes the link as UTF-8. A link that cannot be read, or that is
        # not UTF-8, is an unreadable link: fall back, never raise at import
        # (same fallback as core/claude_project.main_checkout).
        pass
    return root


REPO_ROOT = _main_tree_root()


def _bind(modname: str, filename: str):
    """Absolute-path module bind - the same shim loop_controller.py uses.

    ops/loop is not a package, so this module has to be importable both as
    `ops.loop.lanes` and by file path.
    """
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, _HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


slots = _bind("rc_loop_slots", "slots.py")

def _bind_core(stem: str):
    """core/<stem>.py - plain import first so a repo-root process shares one
    module object; absolute-path bind as the fallback for the script /
    launcher context where the repo root is not on sys.path."""
    try:
        return importlib.import_module(f"core.{stem}")
    except ModuleNotFoundError:
        pass
    name = f"rc_core_{stem}"
    if name in sys.modules:
        return sys.modules[name]
    try:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parents[2] / "core" / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    except OSError as exc:
        sys.modules.pop(name, None)
        raise ModuleNotFoundError(
            f"core/{stem}.py could not be loaded by absolute path") from exc
    return mod


# core/polled_json.py holds the repo's atomic-write contract - LANE 8 CYCLE 48,
# RM-250 sibling sweep. core/log_scrub.py is the RM-321 log scrub (RM-836).
_atomic_write_bytes = _bind_core("polled_json").atomic_write_bytes
_scrub_log = _bind_core("log_scrub").scrub_log

# RM-836: the fixed `detail` of a `lane_lock_unwritable` refusal. The cause
# (an OSError naming its file) is logged, never returned.
LOCK_UNWRITABLE_DETAIL = ("the lane lock could not be written - the claim was "
                          "released, see logs")



def _bind_kit_lanes():
    """The vendored kit's fleet_lanes - the package import first, so every
    caller on a repo-root sys.path shares one module object; an absolute-path
    bind as the fallback for the script / launcher context. The kit module is
    stateless (all state is on disk), so two copies cannot disagree."""
    try:
        return importlib.import_module("ops.fleet_kit.fleet_lanes")
    except ImportError:
        pass
    name = "rc_fleet_kit_fleet_lanes"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, _HERE.parent / "fleet_kit" / "fleet_lanes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fleet_lanes = _bind_kit_lanes()

LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated",
         "queue")
# v25: the kit DEFAULT cap (no machine config); the live cap is lane_cap().
LANE_CAP = fleet_lanes.LANE_CAP_MAX
REPO_CODE = "RC"
LANES_REL = fleet_lanes.LANES_REL
DEFAULT_ROOT = REPO_ROOT / LANES_REL

FREE = fleet_lanes.FREE
RUNNING = fleet_lanes.RUNNING
RECLAIMABLE = fleet_lanes.RECLAIMABLE

# A lock is created by O_EXCL and filled in the same call, but a reader can
# still catch it empty. Inside this window an unparseable lock is presumed
# live; past it it reads RECLAIMABLE rather than wedging the index.
WRITE_GRACE_S = fleet_lanes.WRITE_GRACE_S

# (pid, start time) names a process; a pid alone does not (2026-08-02 wedge).
# Both are the kit's now - Win32 GetProcessTimes, psutil elsewhere - so the
# value a lock records and the value a reader compares come from one source.
proc_started = fleet_lanes.proc_started
_holder_is_a_stranger = fleet_lanes.holder_is_a_stranger

# Token (lock path) -> the kit claim this process holds, so a late release from
# a previous holder cannot unlink the lock of whoever reclaimed it (ABA).
_OWNED: dict = {}


# ---- small helpers ---------------------------------------------------------

def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _int_or_none(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_root(root) -> Path:
    return DEFAULT_ROOT if root is None else Path(root)


def _repo_for(root) -> Path:
    """The repo whose lanes dir `root` is. The kit addresses lanes by REPO
    root, so a lanes dir must sit at <repo>/ops/loop/control/lanes."""
    root = _resolve_root(root)
    rel = tuple(p.lower() for p in LANES_REL.parts)
    tail = tuple(p.lower() for p in root.parts[-len(rel):])
    if len(root.parts) <= len(rel) or tail != rel:
        raise ValueError(
            f"lane root {root} is not <repo>/{LANES_REL.as_posix()}")
    repo = root
    for _ in rel:
        repo = repo.parent
    return repo


def lock_path(root=None, index: int = 0) -> Path:
    """Where lane index `index`'s lock lives. Read-only - creates nothing."""
    return _resolve_root(root) / f"{int(index)}.lock"


def index_of(token) -> int | None:
    """The lane-lock index a token names (`<i>.lock`), or None."""
    try:
        return int(Path(str(token)).stem)
    except (TypeError, ValueError):
        return None


def _read_payload(lock: Path) -> dict:
    try:
        rec = json.loads(Path(lock).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return rec if isinstance(rec, dict) else {}


# ---- state -----------------------------------------------------------------

def lane_cap() -> int:
    """The live per-tree lane cap (v25): the machine config's lane_cap_max,
    clamped to its governor width; the kit default with no config."""
    return int(fleet_lanes.lane_cap(None))


def should_yield() -> bool:
    """v25 FAIR RELEASE: True when RC should end one lane at its next cycle
    boundary. Read-only and advisory; a kit fault reads False (an unreadable
    governor never ends a lane)."""
    try:
        return bool(fleet_lanes.should_yield(REPO_CODE))
    except Exception as exc:  # noqa: BLE001 - advisory read, fail open
        log.warning("lanes: should_yield unreadable, not yielding: %s: %s",
                    type(exc).__name__, _scrub_log(str(exc)))
        return False


def lanes_state(root=None, now=None) -> list:
    """One row per lane index 0..lane_cap()-1 (plus any index still held above
    a narrowed cap) - {index, state, lane, run_id, pid, worktree, age_s}.
    NEVER mutates anything; reads only the kit's lane lock files."""
    return fleet_lanes.repo_lane_state(_repo_for(root), None, now)


def lane_state(root=None, now=None) -> dict:
    """Back-compatible single answer over every lane index. NEVER mutates.

    `state` is RUNNING when ANY lane runs (the first running row's fields),
    else RECLAIMABLE when any lock is provably dead, else FREE. `running`
    counts the live lanes and `lanes` carries every row, so a reader that
    needs all of them never has to re-read."""
    rows = lanes_state(root, now)
    pick = next((r for r in rows if r["state"] == RUNNING), None) or \
        next((r for r in rows if r["state"] == RECLAIMABLE), None)
    out = {"state": FREE, "lane": None, "pid": None, "run_id": None,
           "worktree": None, "age_s": None}
    if pick is not None:
        out.update({k: pick.get(k) for k in out})
    out["running"] = sum(1 for r in rows if r["state"] == RUNNING)
    out["lanes"] = rows
    return out


# ---- lane status log (MAIN ORDER 2026-10-31 2215 item 6) -------------------

LANE_STATUS_LOG = "lane_status.log"
LANE_EVENT_ACTIONS = ("stop", "resume")
LANE_EVENT_REASONS = ("limit", "STOP", "operator", "cap")
# A kit refusal that means this lane stopped, and why. lane_held is not a stop:
# the lane is running, just not again.
_REFUSED_STOP_REASON = {"lanes_full": "cap", "admission": "cap", "usd_ceiling": "limit"}
_STATUS_TAIL_BYTES = 64 * 1024


def _append_status_line(path: Path, data: bytes) -> None:
    """Windows O_APPEND is not atomic, so the shared FILE_APPEND_DATA helper."""
    notify = _bind_core("operator_notify")
    path.parent.mkdir(parents=True, exist_ok=True)
    if notify._on_windows():
        notify._win32_append(path, data)
    else:
        notify._portable_append(path, data)


def log_lane_event(lane, action, reason, root=None) -> bool:
    """Append `<ts> <lane> <stop|resume> <limit|STOP|operator|cap>` to
    ops/loop/control/lane_status.log. A bad argument is a ValueError; a log
    fault is logged and returns False, so it can never fail a lane."""
    name = str(lane)
    if not name or len(name.split()) != 1:
        raise ValueError(f"bad lane name {lane!r}")
    if action not in LANE_EVENT_ACTIONS:
        raise ValueError(f"bad lane action {action!r}")
    if reason not in LANE_EVENT_REASONS:
        raise ValueError(f"bad lane reason {reason!r}")
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{ts} {name} {action} {reason}\n".encode("ascii", "replace")
    try:
        _append_status_line(_resolve_root(root).parent / LANE_STATUS_LOG, line)
    except (OSError, ImportError) as exc:
        log.warning("lane %s: status log append failed: %s: %s",
                    name, type(exc).__name__, _scrub_log(str(exc)))
        return False
    return True


def _open_stop(lane, root=None):
    """The reason of `lane`'s latest line when that line is a stop, else None.

    Read from the log, not from memory: the driver that stops a lane and the
    one that resumes it can be different processes, and a stop whose append
    failed must be retried. The newest stop is the open one, so a second stop
    with another reason replaces the first, and one resume closes the lane."""
    path = _resolve_root(root).parent / LANE_STATUS_LOG
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - _STATUS_TAIL_BYTES))
            tail = fh.read().decode("ascii", "replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        parts = line.split()
        if len(parts) == 4 and parts[1] == str(lane):
            return parts[3] if parts[2] == "stop" else None
    return None


def mark_lane_stopped(lane, reason, root=None) -> bool:
    """Record a stop once per transition, not once per poll: a driver retries
    a refused acquire every tick. True when this call wrote the line."""
    if _open_stop(lane, root) == reason:
        return False
    return log_lane_event(lane, "stop", reason, root=root)


def mark_lane_resumed(lane, root=None) -> bool:
    """Close the open stop with its own reason; a lane not stopped logs nothing.
    True when this call wrote the line."""
    reason = _open_stop(lane, root)
    if reason is None:
        return False
    return log_lane_event(lane, "resume", reason, root=root)


# ---- acquire / release -----------------------------------------------------

def _require_worktree(worktree) -> Path:
    """A lane may NEVER run against the main tree (operator, 2026-07-30).

    An upgrade lane rewrites files while it works; pointed at the checkout the
    operator is reading, it edits the tree out from under them. Only a git
    worktree is a legal target, so an absent worktree is a hard error rather
    than a default.
    """
    if worktree is None or not str(worktree).strip():
        raise ValueError("worktree is mandatory")
    wt = Path(str(worktree).strip()).expanduser()
    try:
        wt = wt.resolve()
    except OSError:
        wt = Path(os.path.abspath(str(wt)))
    if _key(wt) == _key(REPO_ROOT):
        raise ValueError(
            "worktree is mandatory - a lane may never run against the main tree "
            f"({REPO_ROOT})")
    return wt


def try_acquire_lane(lane, *, run_id, worktree, root=None) -> dict:
    """Claim the lowest free (or reclaimable) lane index for `lane`, or refuse.

    Returns `{"ok": True, "lane", "run_id", "worktree", "token", "index"}` -
    `token` is the lock path, and it is what `release_lane` wants back.

    Returns `{"ok": False, "refused": "lane_held" | "lanes_full", "holder",
    "pid", "holders"}` when the same lane NAME is running, or every index is
    held by a live lane, and `{"ok": False, "refused": "admission", "reason",
    ...}` when the kit's v25 admission check refuses (RAM floor / CPU
    ceiling; retry next tick). A refusal writes no lane lock. A dead holder is
    reclaimed instead of respected.

    Returns `{"ok": False, "refused": "lane_lock_unwritable", "holder": None,
    "pid": None, "holders": [], "detail": LOCK_UNWRITABLE_DETAIL}` when the
    claimed lock cannot be rewritten; the claim is released and the cause is
    logged scrubbed with its type (RM-836), so no holder is implied.
    """
    if lane not in LANES:
        raise ValueError(
            f"unknown lane {lane!r} - valid lanes are {', '.join(LANES)}")
    wt = _require_worktree(worktree)
    repo = _repo_for(root)
    # v25: cap=None = the live machine lane_cap_max (re-read per call).
    claim = fleet_lanes.try_acquire_lane(repo, REPO_CODE, lane, str(run_id),
                                         None, exclusive=True)
    if not claim.get("ok"):
        holders = list(claim.get("holders") or [])
        refused = claim.get("refused") or "lanes_full"
        holder, pid = ", ".join(str(h) for h in holders) or None, None
        if refused == "lane_held":
            holder = lane
            for row in lanes_state(root):
                if row["state"] == RUNNING and row["lane"] == lane:
                    pid = _int_or_none(row["pid"])
                    break
        out = {"ok": False, "refused": refused, "holder": holder, "pid": pid,
               "holders": holders}
        if refused == "admission":
            out["reason"] = str(claim.get("reason") or "")[:200]
        if refused in _REFUSED_STOP_REASON:
            mark_lane_stopped(lane, _REFUSED_STOP_REASON[refused], root=root)
        return out

    token = claim["token"]
    # The kit records ITS per-index worktree; RC runs in the per-name one (see
    # the module docstring), so the lock is made to say where the lane really
    # runs. Same identity (run_id, ts), so the kit's ABA guard still matches.
    rec = _read_payload(Path(token))
    ident = claim["_identity"]
    try:
        if not rec or any(rec.get(k) != v for k, v in ident.items()):
            raise OSError("lane lock changed under the claim")
        rec["kit_worktree"] = rec.get("worktree")
        rec["worktree"] = str(wt)
        _atomic_write_bytes(Path(token), json.dumps(rec).encode("utf-8"))
    except OSError as exc:
        fleet_lanes.release_lane(claim)
        log.warning("lane %s: lane lock rewrite failed, claim released: %s: %s",
                    lane, type(exc).__name__, _scrub_log(str(exc)))
        return {"ok": False, "refused": "lane_lock_unwritable", "holder": None,
                "pid": None, "holders": [], "detail": LOCK_UNWRITABLE_DETAIL}
    _OWNED[_key(token)] = claim
    mark_lane_resumed(lane, root=root)
    return {"ok": True, "lane": lane, "run_id": str(run_id),
            "worktree": str(wt), "token": str(token), "index": claim["index"]}


def _claim_for(token, root=None):
    """(lock path, kit claim) for a token, or (lock, None) when not ours.

    Without a local record a lock still counts as ours when its pid is this
    process - the previous module's rule, kept."""
    lock = Path(str(token).strip())
    if not lock.is_absolute():
        lock = _resolve_root(root) / lock.name
    claim = _OWNED.get(_key(lock))
    if claim is not None:
        return lock, claim
    rec = _read_payload(lock)
    if not rec or _int_or_none(rec.get("pid")) != os.getpid():
        return lock, None
    return lock, {"token": str(lock),
                  "_identity": {"run_id": rec.get("run_id"), "ts": rec.get("ts")}}


def repoint_lane_pid(token, pid, root=None) -> bool:
    """Re-point a held lock at the process that ACTUALLY runs the lane.

    The claimer is often the long-lived RC server; left on its pid the lane
    would read RUNNING forever after its worker died. The kit re-records the
    start time for the pid it installs and keeps the claim identity, so a
    later release still matches. Returns False rather than raising - a
    launcher that cannot re-point releases the lane instead.
    """
    if token is None or not str(token).strip():
        return False
    new_pid = _int_or_none(pid)
    if new_pid is None or new_pid <= 0:
        return False
    _lock, claim = _claim_for(token, root)
    if claim is None:
        return False
    return bool(fleet_lanes.repoint_lane_pid(claim, new_pid))


def release_lane(token, root=None) -> bool:
    """Release a lock handed out by `try_acquire_lane`. Idempotent; never raises.

    True when this call removed the lock; False when there was nothing of ours
    to remove. The kit's ownership check is the ABA guard: a lock reclaimed and
    re-acquired by someone else after this token was issued is left alone.
    """
    if token is None or not str(token).strip():
        return False
    try:
        lock, claim = _claim_for(token, root)
        if not lock.exists():
            _OWNED.pop(_key(lock), None)
            return False
        if claim is None:
            return False
        ok = bool(fleet_lanes.release_lane(claim))
    except (OSError, ValueError, TypeError):
        return False
    if ok:
        _OWNED.pop(_key(lock), None)
    return ok
