#!/usr/bin/env python
r"""Lane lock - the seven headless lanes are mutually exclusive, one holder max.

    LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated")

WHY THREE STATES, NOT TWO. A lock file whose pid is DEAD is indistinguishable
from a live one by file inspection alone. Measured 2026-07-30: the live
`ops/loop/control/RUNNING.lock` carried
`{"pid": 9380, "run_id": "eadf15e3", "ts": ..., "repo": "C:\\Riot Commander"}`
and pid 9380 was gone - so every reader that treated EXISTENCE as RUNNING
reported a loop that was not there. `lane_state` therefore answers FREE /
RUNNING / RECLAIMABLE and decides by PROBING the pid, never by stat-ing the
file. RECLAIMABLE must never render as RUNNING.

READS DO NOT WRITE. `lane_state` is the dashboard's poll path; auto-clearing a
stale lock inside a read would make a rendering pass mutate the control plane,
and two pollers would then race each other into a reclaim. Clearing is a
deliberate act, and it happens only inside `try_acquire_lane`.

REFUSE, DO NOT QUEUE. A fire against a genuinely-held lane returns
`{"ok": False, "refused": "lane_held", ...}` and mutates NOTHING on disk. A
queue would turn one operator click into a run that starts minutes later
against a tree that has moved on.

BUILT ON slots.py, NOT BESIDE IT. `slots.py` is BYTE-IDENTICAL-BY-CONTRACT with
the Sibling-A copy (pinned by SHARED_SHA256 in
tests/test_loop_concurrency.py) - it is CONSUMED here, never edited and never
re-implemented. The exclusive-create bucket at `max_slots=1` is the mutex; its
`pid_alive` is the liveness probe. That also means the lock file is created
with O_CREAT|O_EXCL rather than the usual tmp+os.replace: exclusivity IS the
point, and a replace cannot be exclusive. Any OTHER file this module ever
writes under control/ must use tmp+os.replace.

NOTHING HERE STARTS A PROCESS. This module is pure state management: it decides
who may run, it does not run anything. `pid` in the payload is therefore the
pid of the process that CLAIMED the lane; the later stage that actually spawns
a run re-points it at the spawned process.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent


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
    except OSError:
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

LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated")
MAX_SLOTS = 1
DEFAULT_ROOT = _HERE / "control" / "lanes"
# slots.try_acquire names slot i "<i>.lock"; at max_slots=1 there is only slot 0.
LOCK_NAME = "0.lock"

FREE = "FREE"
RUNNING = "RUNNING"
RECLAIMABLE = "RECLAIMABLE"

# A lock is created empty by O_EXCL and filled a moment later. Inside this
# window an unparseable lock is presumed live (refuse); past it nothing about
# it can be proven alive, so it reads RECLAIMABLE rather than wedging the lane.
WRITE_GRACE_S = 30.0

# Lanes never expire on AGE - a legitimate upgrade run is hours long. Only a
# dead pid frees a lane, so the shared reaper is called with an age bound it
# can never cross.
_NEVER_STALE_BY_AGE = float("inf")

# Token -> the identity this process wrote, so a late release from a previous
# holder cannot unlink the lock of whoever reclaimed the lane after it (ABA).
_OWNED: dict = {}


# ---- small readers ---------------------------------------------------------

def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value):
    return None if value is None else str(value)


def _resolve_root(root) -> Path:
    return DEFAULT_ROOT if root is None else Path(root)


def lock_path(root=None) -> Path:
    """Where the single lane lock lives. Read-only helper - creates nothing."""
    return _resolve_root(root) / LOCK_NAME


def _read_payload(lock: Path) -> dict:
    """The lock's payload, or {} when it is missing, empty or half-written."""
    try:
        raw = lock.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        rec = json.loads(raw)
    except ValueError:
        return {}
    return rec if isinstance(rec, dict) else {}


# ---- state -----------------------------------------------------------------

def lane_state(root=None, now=None) -> dict:
    """FREE / RUNNING / RECLAIMABLE for the lane lock. NEVER mutates anything.

    RECLAIMABLE means a lock file is present but its holder is provably gone.
    It is reported, not acted on: clearing it is `try_acquire_lane`'s job.
    """
    lock = lock_path(root)
    now = time.time() if now is None else float(now)
    blank = {"state": FREE, "lane": None, "pid": None, "run_id": None,
             "worktree": None, "age_s": None}
    if not lock.exists():
        return blank

    rec = _read_payload(lock)
    ts = _float_or_none(rec.get("ts"))
    if ts is None:
        try:
            ts = lock.stat().st_mtime
        except OSError:
            ts = None
    pid = _int_or_none(rec.get("pid"))
    out = {
        "state": RUNNING,
        "lane": _str_or_none(rec.get("lane")),
        "pid": pid,
        "run_id": _str_or_none(rec.get("run_id")),
        "worktree": _str_or_none(rec.get("worktree")),
        "age_s": None if ts is None else max(0.0, now - ts),
    }
    if pid is None:
        # No readable holder at all - see WRITE_GRACE_S.
        if out["age_s"] is not None and out["age_s"] > WRITE_GRACE_S:
            out["state"] = RECLAIMABLE
        return out
    if not slots.pid_alive(pid):
        out["state"] = RECLAIMABLE
    return out


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


def _reclaim(root: Path) -> bool:
    """Clear a lock whose holder is provably gone. Never touches a live one."""
    lock = lock_path(root)
    try:
        # Shared path first: reap() unlinks on the same pid probe, with the age
        # bound set where it cannot fire.
        slots.reap(root, MAX_SLOTS, _NEVER_STALE_BY_AGE)
    except (OSError, TypeError, ValueError):
        pass  # malformed payload - the explicit branch below handles it
    if not lock.exists():
        return True
    if lane_state(root)["state"] != RECLAIMABLE:
        return False
    try:
        lock.unlink()
    except OSError:
        return False
    return True


def try_acquire_lane(lane, *, run_id, worktree, root=None) -> dict:
    """Claim the lane lock for `lane`, or refuse.

    Returns `{"ok": True, "lane", "run_id", "worktree", "token"}` on success -
    `token` is the lock path, and it is what `release_lane` wants back.

    Returns `{"ok": False, "refused": "lane_held", "holder", "pid"}` when the
    lane is genuinely held by a LIVE pid. That is a normal answer, not an
    error, and it writes nothing. A holder whose pid is dead is reclaimed
    instead of respected: a crashed lane must never deadlock the next one.
    """
    if lane not in LANES:
        raise ValueError(
            f"unknown lane {lane!r} - valid lanes are {', '.join(LANES)}")
    wt = _require_worktree(worktree)
    root = _resolve_root(root)

    # Read BEFORE any mkdir so a refusal leaves the filesystem untouched.
    state = lane_state(root)
    if state["state"] == RUNNING:
        return {"ok": False, "refused": "lane_held",
                "holder": state["lane"], "pid": state["pid"]}
    if state["state"] == RECLAIMABLE:
        _reclaim(root)

    payload = {"pid": os.getpid(), "lane": lane, "run_id": str(run_id),
               "worktree": str(wt), "ts": time.time(), "repo": str(REPO_ROOT)}
    token = slots.try_acquire(root, MAX_SLOTS, payload)
    if token is None:
        # Lost a race between the read and the exclusive create.
        state = lane_state(root)
        return {"ok": False, "refused": "lane_held",
                "holder": state["lane"], "pid": state["pid"]}
    _OWNED[_key(token)] = (payload["run_id"], payload["ts"], payload["pid"])
    return {"ok": True, "lane": lane, "run_id": payload["run_id"],
            "worktree": payload["worktree"], "token": str(token)}


def repoint_lane_pid(token, pid, root=None) -> bool:
    """Re-point a held lock at the process that ACTUALLY runs the lane.

    `try_acquire_lane` records the pid of whoever CLAIMED the lane, which for a
    dashboard fire is the long-lived RC server. Left that way, `lane_state`
    probes a pid that is always alive, so the lane would read RUNNING forever
    after its worker died - the exact stale-lock failure the three states exist
    to prevent. The launcher therefore re-points the lock the moment it has a
    worker pid.

    `_OWNED` is updated in the same breath, or the ABA guard in `release_lane`
    would refuse to release a lock this process legitimately owns.

    tmp + os.replace, not an in-place rewrite: `replace` is atomic and never
    leaves the path absent, so the O_EXCL exclusivity another acquirer relies on
    holds throughout. Returns False rather than raising - a launcher failing to
    re-point must fall back to releasing the lane, not crash mid-spawn.
    """
    if token is None or not str(token).strip():
        return False
    lock = Path(str(token).strip())
    if not lock.is_absolute():
        lock = _resolve_root(root) / lock.name
    rec = _read_payload(lock)
    if not rec:
        return False
    try:
        new_pid = int(pid)
    except (TypeError, ValueError):
        return False

    key = _key(lock)
    owned = _OWNED.get(key)
    identity = (_str_or_none(rec.get("run_id")),
                _float_or_none(rec.get("ts")),
                _int_or_none(rec.get("pid")))
    if owned is not None and identity != tuple(owned):
        return False  # someone else holds the lane now
    if owned is None and identity[2] != os.getpid():
        return False

    rec["pid"] = new_pid
    rec["claimed_by_pid"] = identity[2]
    tmp = Path(str(lock) + ".tmp")
    try:
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        os.replace(tmp, lock)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    if owned is not None:
        _OWNED[key] = (owned[0], owned[1], new_pid)
    else:
        _OWNED[key] = (identity[0], identity[1], new_pid)
    return True


def release_lane(token, root=None) -> bool:
    """Release a lock handed out by `try_acquire_lane`. Idempotent.

    True when this call removed the lock; False when there was nothing of ours
    to remove. Never raises - a release runs in a finally, and a release that
    can throw turns one failure into two.

    The ownership check is the ABA guard: if the lane was reclaimed and
    re-acquired after this token was issued, a late release from the previous
    holder must NOT unlink the new holder's lock. The check compares the lock's
    CURRENT payload against the identity this process recorded when it acquired
    that path. Limit, stated rather than hidden: a token is a path string and
    every holder uses the same path, so two acquisitions by THIS process are
    indistinguishable to a release - which is harmless, since both are us.
    Cross-process ABA, the case that matters, is caught.
    """
    if token is None or not str(token).strip():
        return False
    lock = Path(str(token).strip())
    if not lock.is_absolute():
        lock = _resolve_root(root) / lock.name
    key = _key(lock)
    owned = _OWNED.get(key)
    if not lock.exists():
        _OWNED.pop(key, None)
        return False

    rec = _read_payload(lock)
    if not rec:
        return False  # half-written or corrupt - not provably ours to remove
    identity = (_str_or_none(rec.get("run_id")),
                _float_or_none(rec.get("ts")),
                _int_or_none(rec.get("pid")))
    if owned is not None:
        if identity != tuple(owned):
            return False  # someone else holds the lane now
    elif identity[2] != os.getpid():
        return False  # no local record and not our pid - not ours

    try:
        lock.unlink()
    except OSError:
        return False
    _OWNED.pop(key, None)
    return True
