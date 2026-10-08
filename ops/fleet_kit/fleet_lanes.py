# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v6 - multi-lane headless work: per-repo lanes, one worktree each,
under the machine-wide governor (design: MAIN docs/fleet-designs/multi-lane.md).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

THREE LAYERS:
1. REPO LANE  - <main tree>/ops/loop/control/lanes/<i>.lock, i in range(cap),
   cap 1..3 per repo. One lock per concurrent lane; the lane NAME is a payload
   field, never the file name, so any roster lane can run at any index. A name
   is exclusive by default (two "upgrade" lanes never run at once).
2. WORKTREE   - lane i always runs in <parent>/<code>-worktrees/lane-<i>, its
   own git worktree, so two lanes never share a working tree or an index. A
   dirty lane worktree is REFUSED (never cleaned); unmerged commits left on a
   clean one are saved under refs/fleet-lanes/ before it moves.
3. GOVERNOR   - one of GOVERNOR_WIDTH (3) machine-wide slots, ON-DISK
   COMPATIBLE with the vendored slots.py (same root, same <i>.lock names, same
   O_CREAT|O_EXCL create, same {pid, repo, run_id, cycle, ts} payload, same
   reap rules). Extra payload keys are ignored by slots.py.

ONE SLOT PER EXECUTOR CALL, TAKEN AT THE CALL. run_lane() holds layers 1-2
only. The governor slot is held around the executor call itself - by
fleet_headless.spawn(governor=...) or by an existing slots.hold() - NEVER both,
and never around git or a merge (slots.py's own rule). Nesting two slots in
one lane would deadlock three lanes against a width of three.

FAIRNESS. A waiter for a governor slot files a ticket in <slot root>/../queue
and refreshes its mtime every poll. Tickets are served by rank: tier (aged,
interactive, queued), then the fewest slots held by the ticket's repo, then
age. An interactive operator ask jumps the queue but PREEMPTS NOTHING - no
holder is ever stopped - and a ticket that has waited MAX_WAIT_S outranks
every interactive ask, so queued work never starves. A caller that retries
after a timeout passes since= so its age survives the retry.

REAPING. A repo lane lock is RECLAIMABLE when its pid (and, for a run_lane
claim that was repointed, its claiming process) is dead or provably a
different process (start time differs), or when unreadable past
WRITE_GRACE_S. Lanes never expire on age. Governor slots follow slots.py plus
the start-time guard, and stay live while the executor child recorded by
mark_child() runs, so killing the process that took a slot cannot let a
fourth executor start. A ticket is dead when its pid is dead or a stranger,
or its heartbeat is older than TICKET_HEARTBEAT_S. Every delete re-reads the
bytes it judged and deletes only if they are unchanged. *_state() functions
are poll paths and never write.

Pure stdlib (psutil used only if present). No machine path, account id or repo
name appears in this file; the governor root derives from %ProgramData%.
"""

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

GOVERNOR_WIDTH = 3
LANE_CAP_MAX = 3
LANES_REL = Path("ops/loop/control/lanes")
ACQUIRE_MUTEX = ".acquire"
DEFAULT_STALE_AFTER = 3.0 * 5400.0
HARD_STALE_MULTIPLE = 2.0
WRITE_GRACE_S = 30.0
MAX_WAIT_S = 1800.0
TICKET_HEARTBEAT_S = 120.0
MAX_POLL_S = 30.0
PID_IDENTITY_EPS_S = 1.0
RETRIES, RETRY_SLEEP = 12, 0.025
PRIORITIES = ("interactive", "queued")
FREE, RUNNING, RECLAIMABLE = "FREE", "RUNNING", "RECLAIMABLE"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class SlotTimeout(RuntimeError):
    """No governor slot became free inside the caller's timeout."""


class LaneRefused(RuntimeError):
    """The repo's lanes are held, or the lane's worktree is unusable."""


# ---------------------------------------------------------------- processes

def pid_alive(pid):
    """True if pid is a live process. A pid we cannot query counts as ALIVE
    (wait rather than double-book)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return k32.GetLastError() != 87
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return True
        return code.value == 259
    finally:
        k32.CloseHandle(h)


def proc_started(pid):
    """Process creation time (epoch seconds) or None when it cannot be read.
    None always means "cannot prove reuse" to every caller."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            t = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
                return None
            ft = (t[0].dwHighDateTime << 32) | t[0].dwLowDateTime
            return ft / 1e7 - 11644473600.0
        finally:
            k32.CloseHandle(h)
    try:
        import psutil
        return float(psutil.Process(pid).create_time())
    except Exception:  # noqa: BLE001 - not installed, no such process, denied
        return None


def holder_is_a_stranger(pid, recorded):
    """True only when the live pid is PROVABLY not the recorded process."""
    try:
        recorded = float(recorded)
    except (TypeError, ValueError):
        return False
    actual = proc_started(pid)
    return actual is not None and abs(actual - recorded) > PID_IDENTITY_EPS_S


def _identity(pid=None):
    pid = os.getpid() if pid is None else int(pid)
    return {"pid": pid, "pid_started": proc_started(pid)}


# ---------------------------------------------------------------- files

def _raw(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _parse(raw):
    try:
        rec = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return rec if isinstance(rec, dict) else {}


def _read(path):
    """The JSON object in path, or {} when missing, empty or half-written."""
    return _parse(_raw(path))


def _exclusive_create(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as fh:
            json.dump(payload, fh)
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()
        return False
    return True


def _retry(fn):
    """fn() with a bounded retry: Windows refuses unlink/replace while another
    process holds the file open for reading (slots.py release, measured)."""
    for i in range(RETRIES):
        try:
            return fn()
        except FileNotFoundError:
            raise
        except OSError:
            if i + 1 == RETRIES:
                raise
            time.sleep(RETRY_SLEEP)
    return None


def _atomic_write(path, payload):
    """tmp + replace with the bounded retry; the tmp never outlives a failure."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="ascii", newline="\n")
        _retry(lambda: tmp.replace(path))
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _unlink_if_raw(path, raw):
    """Unlink path only while its bytes are still `raw` (what the caller judged).
    True = gone. Never raises."""
    path = Path(path)
    for i in range(RETRIES):
        now = _raw(path)
        if now is None:
            return not path.exists()
        if now != raw:
            return False
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if i + 1 < RETRIES:
                time.sleep(RETRY_SLEEP)
    return False


def _release(path, identity):
    """Unlink path only if its payload still carries identity (ABA guard). If
    it cannot be unlinked, neutralise it (pid 0, ts 0) - re-checking ownership
    first - so the next reap takes it at once. True = gone."""
    path = Path(path)
    raw = _raw(path)
    if raw is None:
        return not path.exists()
    rec = _parse(raw)
    if any(rec.get(k) != v for k, v in identity.items()):
        return False
    if _unlink_if_raw(path, raw):
        return True
    if _raw(path) != raw:
        return False
    # v11 (CS 1623 item 6): clear every liveness pid, not only pid - a kept
    # holder_pid / child_pid of a live claimer held the lane RUNNING.
    rec.update({"pid": 0, "ts": 0.0, "orphaned": True, "holder_pid": 0,
                "holder_started": None, "child_pid": 0, "child_started": None})
    with contextlib.suppress(OSError), path.open("w", encoding="ascii") as fh:
        json.dump(rec, fh)
    return False


# ---------------------------------------------------------------- governor

def governor_root(environ=None):
    """The shared slot root slots.py uses: %ProgramData%/lw-loop/slots."""
    env = os.environ if environ is None else environ
    base = env.get("ProgramData") or env.get("PROGRAMDATA") or "/var/lib"
    return Path(base) / "lw-loop" / "slots"


def queue_root(root):
    return Path(root).parent / "queue"


def _slot_stale(path, raw, stale_after, now):
    rec = _parse(raw)
    if not rec:
        try:
            return (now - Path(path).stat().st_mtime) > stale_after
        except OSError:
            return True
    try:
        age = now - float(rec.get("ts", 0))
    except (TypeError, ValueError):
        age = float("inf")
    if age > stale_after * HARD_STALE_MULTIPLE:
        return True
    return not (_live(rec.get("pid", 0), rec.get("pid_started")) or
                _live(rec.get("child_pid", 0), rec.get("child_started")))


def _live(pid, started):
    return bool(pid) and pid_alive(pid) and not holder_is_a_stranger(pid, started)


def mark_child(slot, pid):
    """Record the executor child in a held slot, so the slot stays live while
    the child runs even if the process that took the slot is killed (the
    slots.py ceiling still applies). False, never raises, if not possible."""
    rec = _read(slot)
    if not rec:
        return False
    rec.update({"child_pid": int(pid), "child_started": proc_started(pid)})
    try:
        _atomic_write(slot, rec)
    except OSError:
        return False
    return True


def governor_slot_stale(path, stale_after=DEFAULT_STALE_AFTER, now=None):
    """slots.py is_stale, plus the start-time guard when pid_started is set."""
    now = time.time() if now is None else now
    return _slot_stale(path, _raw(path), stale_after, now)


def governor_state(root=None, width=GOVERNOR_WIDTH, stale_after=DEFAULT_STALE_AFTER,
                   now=None):
    """One row per governor slot. READ ONLY."""
    root = governor_root() if root is None else Path(root)
    now = time.time() if now is None else now
    rows = []
    for i in range(width):
        p = root / f"{i}.lock"
        row = {"index": i, "state": FREE, "repo": None, "run_id": None, "pid": None,
               "age_s": None}
        raw = _raw(p)
        if raw is not None:
            rec = _parse(raw)
            ts = rec.get("ts")
            row.update({"repo": rec.get("repo"), "run_id": rec.get("run_id"),
                        "pid": rec.get("pid"),
                        "age_s": None if not isinstance(ts, (int, float)) else
                        max(0.0, now - ts)})
            row["state"] = RECLAIMABLE if _slot_stale(p, raw, stale_after, now) \
                else RUNNING
        rows.append(row)
    return rows


def reap_governor(root, width=GOVERNOR_WIDTH, stale_after=DEFAULT_STALE_AFTER):
    """Remove stale slots; a slot whose bytes changed since judged is kept."""
    removed = 0
    for i in range(width):
        p = Path(root) / f"{i}.lock"
        raw = _raw(p)
        if raw is not None and _slot_stale(p, raw, stale_after, time.time()) \
                and _unlink_if_raw(p, raw):
            removed += 1
    return removed


def held_by_repo(root, width=GOVERNOR_WIDTH):
    counts = {}
    for row in governor_state(root, width):
        if row["state"] == RUNNING:
            counts[row["repo"]] = counts.get(row["repo"], 0) + 1
    return counts


def _ticket_live(path, raw, now):
    try:
        beat = Path(path).stat().st_mtime
    except OSError:
        return False
    rec = _parse(raw)
    if not rec:
        return now - beat <= WRITE_GRACE_S
    if now - beat > TICKET_HEARTBEAT_S:
        return False
    pid = rec.get("pid", 0)
    return pid_alive(pid) and not holder_is_a_stranger(pid, rec.get("pid_started"))


def tickets(qroot, reap=True, now=None):
    """Live tickets as (path, record). Dead waiters' tickets are removed when
    reap is True (a waiter that crashed or stopped polling loses its place)."""
    out = []
    qroot = Path(qroot)
    if not qroot.is_dir():
        return out
    now = time.time() if now is None else now
    for p in sorted(qroot.glob("*.ticket")):
        raw = _raw(p)
        if raw is None:
            continue
        if _ticket_live(p, raw, now):
            out.append((p, _parse(raw)))
        elif reap:
            _unlink_if_raw(p, raw)
    return out


def ticket_rank(rec, now, held):
    """Smaller is served first: (tier, slots held by its repo, enqueue time).
    tier 0 = waited MAX_WAIT_S (anti-starvation), 1 = interactive, 2 = queued."""
    ts = rec.get("ts")
    ts = float(ts) if isinstance(ts, (int, float)) else now
    interactive = rec.get("priority") == "interactive"
    tier = 0 if now - ts >= MAX_WAIT_S else (1 if interactive else 2)
    return (tier, held.get(rec.get("repo"), 0), ts)


def my_turn(qroot, mine, free, held, now=None):
    """True when the ticket at path `mine` is among the first `free` by rank."""
    if free <= 0:
        return False
    now = time.time() if now is None else now
    live = tickets(qroot, now=now)
    order = sorted(live, key=lambda t: ticket_rank(t[1], now, held))
    keys = [os.path.normcase(str(p)) for p, _ in order[:free]]
    return os.path.normcase(str(mine)) in keys


def enqueue(qroot, repo, run_id, priority="queued", since=None, clock=time.time):
    """File a ticket. since = when this caller FIRST asked (kept across retries
    so a timeout-and-retry caller still ages into tier 0)."""
    if priority not in PRIORITIES:
        raise ValueError(f"priority {priority!r} not in {PRIORITIES}")
    qroot = Path(qroot)
    rec = {**_identity(), "repo": str(repo), "run_id": str(run_id),
           "priority": priority, "ts": float(since) if since is not None else clock()}
    for n in range(100):
        p = qroot / f"{time.time_ns():020d}-{os.getpid()}-{n}.ticket"
        if _exclusive_create(p, rec):
            return p
    raise OSError("could not file a queue ticket")


def _drop_ticket(ticket):
    raw = _raw(ticket)
    if raw is not None and not _unlink_if_raw(ticket, raw):
        # Undeletable right now: neutralise so every waiter reads it dead.
        with contextlib.suppress(OSError), Path(ticket).open("w", encoding="ascii") as fh:
            json.dump({"pid": 0, "orphaned": True}, fh)


def try_governor(root, width, payload):
    """One non-blocking pass: reap, then exclusive-create the first free slot."""
    root = Path(root)
    reap_governor(root, width)
    for i in range(width):
        p = root / f"{i}.lock"
        if _exclusive_create(p, payload):
            return p
    return None


@contextlib.contextmanager
def governor_slot(repo, run_id, priority="queued", root=None, width=GOVERNOR_WIDTH,
                  timeout=None, poll=2.0, cycle=0, since=None, sleep=time.sleep,
                  on_wait=None):
    """Hold one machine-wide slot for the block, waiting in the fair queue.
    Raises SlotTimeout when timeout (seconds) elapses first; timeout=0 is a
    single try. Never proceeds unslotted. Take it around the executor call only."""
    root = governor_root() if root is None else Path(root)
    qroot = queue_root(root)
    poll = min(float(poll), MAX_POLL_S)
    payload = {**_identity(), "repo": str(repo), "run_id": str(run_id),
               "cycle": cycle, "ts": time.time(), "priority": priority}
    deadline = None if timeout is None else time.monotonic() + timeout
    ticket = enqueue(qroot, repo, run_id, priority, since)
    first_ask = _read(ticket).get("ts", since)
    slot, waited = None, False
    try:
        while True:
            try:
                os.utime(ticket)
            except OSError:
                if not ticket.exists():
                    # Reaped while we were suspended (sleep, hibernate): re-file
                    # with the ORIGINAL ask time so no age is lost.
                    ticket = enqueue(qroot, repo, run_id, priority, first_ask)
            reap_governor(root, width)
            held = held_by_repo(root, width)
            free = width - sum(held.values())
            if my_turn(qroot, ticket, free, held):
                payload["ts"] = time.time()
                slot = try_governor(root, width, payload)
                if slot is not None:
                    break
            if deadline is not None and time.monotonic() >= deadline:
                raise SlotTimeout(f"no governor slot within {timeout}s (width {width})")
            if not waited and on_wait:
                on_wait()
            waited = True
            sleep(poll)
    finally:
        _drop_ticket(ticket)
    try:
        yield slot
    finally:
        _release(slot, {"pid": payload["pid"], "run_id": payload["run_id"],
                        "ts": payload["ts"]})


# ---------------------------------------------------------------- repo lanes

def main_tree(path):
    """The MAIN working tree for path, even when path is a linked worktree: its
    .git is then a FILE `gitdir: <main>/.git/worktrees/<name>` (absolute, or
    relative to path). Anything else answers path itself."""
    path = Path(path).resolve()
    dotgit = path / ".git"
    try:
        raw = dotgit.read_text(encoding="utf-8").strip() if dotgit.is_file() else ""
    except OSError:
        raw = ""
    if raw.startswith("gitdir:"):
        gitdir = Path(raw.split(":", 1)[1].strip())
        gitdir = (gitdir if gitdir.is_absolute() else path / gitdir).resolve()
        if gitdir.parent.name == "worktrees":
            return gitdir.parents[2]
    return path


def lane_cap(cap):
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        raise ValueError(f"lane cap {cap!r} is not an integer") from None
    if not 1 <= cap <= LANE_CAP_MAX:
        raise ValueError(f"lane cap {cap} outside 1..{LANE_CAP_MAX}")
    return min(cap, GOVERNOR_WIDTH)


def worktree_path(repo_root, code, index):
    """Lane i of repo <code> always runs here: <parent>/<code>-worktrees/lane-<i>."""
    if not str(code).isalnum():
        raise ValueError(f"repo code {code!r} must be alphanumeric")
    parent = main_tree(repo_root).parent
    return parent / f"{str(code).lower()}-worktrees" / f"lane-{int(index)}"


def _lane_row(lock, raw, now):
    row = {"index": int(lock.stem), "state": FREE, "lane": None, "run_id": None,
           "pid": None, "worktree": None, "age_s": None}
    if raw is None:
        return row
    rec = _parse(raw)
    ts = rec.get("ts")
    if not isinstance(ts, (int, float)):
        try:
            ts = lock.stat().st_mtime
        except OSError:
            ts = None
    row.update({"state": RUNNING, "lane": rec.get("lane"), "run_id": rec.get("run_id"),
                "pid": rec.get("pid"), "worktree": rec.get("worktree"),
                "age_s": None if ts is None else max(0.0, now - ts)})
    pid = rec.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        if row["age_s"] is None or row["age_s"] > WRITE_GRACE_S:
            row["state"] = RECLAIMABLE
    elif not (_live(pid, rec.get("pid_started")) or
              _live(rec.get("holder_pid", 0), rec.get("holder_started"))):
        row["state"] = RECLAIMABLE
    return row


def repo_lane_state(repo_root, cap=LANE_CAP_MAX, now=None):
    """One row per lane index 0..cap-1: FREE / RUNNING / RECLAIMABLE. READ ONLY.
    The lane widget's contract: exactly these files, no directory walk."""
    now = time.time() if now is None else now
    d = main_tree(repo_root) / LANES_REL
    rows = []
    for i in range(lane_cap(cap)):
        lock = d / f"{i}.lock"
        rows.append(_lane_row(lock, _raw(lock), now))
    return rows


@contextlib.contextmanager
def _acquire_mutex(d, wait=5.0):
    """Serialise scan + reclaim + create per repo, so two acquirers can never
    both reclaim one index (and then share its worktree)."""
    m = Path(d) / ACQUIRE_MUTEX
    deadline = time.monotonic() + wait
    while not _exclusive_create(m, _identity()):
        raw = _raw(m)
        rec = _parse(raw)
        dead = (rec and (not pid_alive(rec.get("pid", 0)) or
                         holder_is_a_stranger(rec.get("pid"), rec.get("pid_started"))))
        if raw is not None and (dead or (not rec and _age(m) > WRITE_GRACE_S)):
            _unlink_if_raw(m, raw)
            continue
        if time.monotonic() >= deadline:
            raise LaneRefused("lane acquire mutex busy")
        time.sleep(0.05)
    try:
        yield
    finally:
        _release(m, {"pid": os.getpid()})


def _age(path):
    try:
        return time.time() - Path(path).stat().st_mtime
    except OSError:
        return 0.0


def try_acquire_lane(repo_root, code, lane, run_id, cap=LANE_CAP_MAX, exclusive=True):
    """Claim the lowest free (or reclaimable) lane index. Returns
    {"ok": True, "index", "token", "worktree", "lane", "run_id"} or
    {"ok": False, "refused": "lanes_full" | "lane_held", "holders": [...]} - a
    refusal writes no lane lock. exclusive=True refuses a lane NAME that is
    already running. Lanes never expire on age."""
    root = main_tree(repo_root)
    d = root / LANES_REL
    d.mkdir(parents=True, exist_ok=True)
    with _acquire_mutex(d):
        now = time.time()
        rows = []
        for i in range(lane_cap(cap)):
            lock = d / f"{i}.lock"
            raw = _raw(lock)
            rows.append((lock, raw, _lane_row(lock, raw, now)))
        holders = [r["lane"] for _, _, r in rows if r["state"] == RUNNING]
        if exclusive and str(lane) in holders:
            return {"ok": False, "refused": "lane_held", "holders": holders}
        for lock, raw, row in rows:
            if row["state"] == RUNNING:
                continue
            if row["state"] == RECLAIMABLE and not _unlink_if_raw(lock, raw):
                continue
            wt = worktree_path(root, code, row["index"])
            payload = {**_identity(), "lane": str(lane), "run_id": str(run_id),
                       "worktree": str(wt), "repo": str(code), "index": row["index"],
                       "ts": time.time()}
            if _exclusive_create(lock, payload):
                return {"ok": True, "index": row["index"], "token": str(lock),
                        "worktree": str(wt), "lane": str(lane), "run_id": str(run_id),
                        "_identity": {"run_id": payload["run_id"], "ts": payload["ts"]}}
    return {"ok": False, "refused": "lanes_full", "holders": holders}


def repoint_lane_pid(claim, pid, keep_claimer=False):
    """Point a held lane lock at the worker that actually runs the lane.
    keep_claimer=True (forced for run_lane claims) keeps the lane RUNNING while
    the claiming process is alive too - it still merges / gates after the
    worker exits. Without it (a long-lived server that claims for others) the
    lane frees when the worker dies. False, never raises, when the lock is no
    longer ours or cannot be written."""
    lock = Path(claim["token"])
    rec = _read(lock)
    if not rec or any(rec.get(k) != v for k, v in claim["_identity"].items()):
        return False
    if keep_claimer or claim.get("held_by_block"):
        rec.update({"holder_pid": rec.get("pid"), "holder_started": rec.get("pid_started")})
    rec.update({"claimed_by_pid": rec.get("pid"), **_identity(pid)})
    try:
        _atomic_write(lock, rec)
    except OSError:
        return False
    return True


def release_lane(claim):
    """Release a claim from try_acquire_lane. Never raises; False when the lock
    is no longer ours (reclaimed and re-acquired - the ABA guard)."""
    try:
        return _release(claim["token"], claim["_identity"])
    except (OSError, KeyError, TypeError):
        return False


# ---------------------------------------------------------------- worktrees

def find_git(environ=None, cwd=None):
    """Absolute path of git from PATH, never from the working directory (v10,
    RSC 0523 item 5: a bare "git" lets Windows run a planted cwd git.exe).
    Empty, relative and cwd-equal PATH entries are skipped; None if absent."""
    env = os.environ if environ is None else environ
    here = os.path.normcase(Path(cwd or Path.cwd()).resolve())
    exts = [""]
    if sys.platform == "win32":
        exts = [e for e in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for entry in env.get("PATH", "").split(os.pathsep):
        d = entry.strip().strip('"')
        if not d or not Path(d).is_absolute() or os.path.normcase(Path(d).resolve()) == here:
            continue
        for ext in exts:
            p = Path(d) / ("git" + ext)
            if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
                return str(p)
    return None


def _git(*args, git=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    exe = git or find_git()
    if not exe:
        raise LaneRefused("git not found on PATH (working directory excluded)")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=300,
                          env=env, creationflags=_NO_WINDOW)


def ensure_worktree(repo_root, path, base="HEAD", run=_git, clock=time.time):
    """Make `path` a clean git worktree of the repo, at the main tree's `base`.
    Missing: prune stale registrations, then add it detached. Present: it must
    be a worktree of this repo and CLEAN, else LaneRefused (a dirty lane
    worktree is a crashed run's work and is never cleaned). Commits on it that
    `base` does not contain are saved under refs/fleet-lanes/ before it moves.
    Returns {"created": bool, "saved_ref": str | None}."""
    repo_root, path = main_tree(repo_root), Path(path)
    sha = run("-C", str(repo_root), "rev-parse", "--verify", base + "^{commit}")
    if sha.returncode != 0:
        raise LaneRefused(f"base {base!r} does not resolve in {repo_root}")
    sha = sha.stdout.strip()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        run("-C", str(repo_root), "worktree", "prune")
        r = run("-C", str(repo_root), "worktree", "add", "--detach", str(path), sha)
        if r.returncode != 0:
            raise LaneRefused(f"git worktree add failed: {r.stderr.strip()[:200]}")
        return {"created": True, "saved_ref": None}
    if os.path.normcase(str(main_tree(path))) != os.path.normcase(str(repo_root)) or \
            os.path.normcase(str(path.resolve())) == os.path.normcase(str(repo_root)):
        raise LaneRefused(f"{path} is not a linked worktree of {repo_root}")
    r = run("-C", str(path), "status", "--porcelain")
    if r.returncode != 0 or r.stdout.strip():
        raise LaneRefused(f"lane worktree {path} is dirty - resolve it by hand")
    head = run("-C", str(path), "rev-parse", "--verify", "HEAD")
    saved = None
    if head.returncode == 0 and run("-C", str(path), "merge-base", "--is-ancestor",
                                    head.stdout.strip(), sha).returncode != 0:
        saved = f"refs/fleet-lanes/{path.name}-{int(clock())}"
        if run("-C", str(repo_root), "update-ref", saved, head.stdout.strip()).returncode:
            raise LaneRefused(f"could not save unmerged lane commits from {path}")
    r = run("-C", str(path), "checkout", "--detach", sha)
    if r.returncode != 0:
        raise LaneRefused(f"lane worktree {path} could not move to {base!r}")
    return {"created": False, "saved_ref": saved}


@contextlib.contextmanager
def run_lane(repo_root, code, lane_name, run_id, cap=LANE_CAP_MAX, base="HEAD",
             exclusive=True, run=_git):
    """Repo lane + clean worktree for the block. Yields the claim ("worktree",
    "index", "saved_ref"). Takes NO governor slot: hold one around the executor
    call (spawn(governor=...) or slots.hold), never around git. Raises
    LaneRefused before anything runs; releases the lane however the block ends."""
    claim = try_acquire_lane(repo_root, code, lane_name, run_id, cap, exclusive)
    if not claim["ok"]:
        raise LaneRefused(f"{claim['refused']}: {claim['holders']}")
    claim["held_by_block"] = True
    try:
        claim["saved_ref"] = ensure_worktree(repo_root, claim["worktree"], base,
                                             run=run)["saved_ref"]
        yield claim
    finally:
        release_lane(claim)
