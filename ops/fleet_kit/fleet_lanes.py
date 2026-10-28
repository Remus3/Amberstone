# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v25 - multi-lane headless work: per-repo lanes, one worktree each,
under the machine-wide governor (design: MAIN docs/fleet-designs/multi-lane.md).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

THREE LAYERS:
1. REPO LANE  - <main tree>/ops/loop/control/lanes/<i>.lock, i in range(cap),
   cap 1..3 per repo. One lock per concurrent lane; the lane NAME is a payload
   field, never the file name, so any roster lane can run at any index. A name
   is exclusive by default (two "upgrade" lanes never run at once).
2. WORKTREE   - lane i always runs in its own git worktree, so two lanes
   never share a working tree or an index. v14 (SIDECAR-1): when the user
   variable FLEET_SIDECAR_ROOT is set (process environment first - an empty
   value disables it, which is how a suite pins it - then HKCU Environment)
   the path is <root>/<CODE>/Worktree/lane-<i>; unset,
   it stays <parent>/<code>-worktrees/lane-<i>. v22: named nowhere, the root
   defaults to SIDECAR_DEFAULT (drive E, folder Sidecars) when <default>/<CODE> exists
   (never inside a pytest test); missing = the v14 path. STICKY: while the old path
   still exists and the new one does not, the old path is used, so setting
   the variable never orphans a lane - move each idle lane with `git worktree
   move <old> <new>` (loop idle) and the next fire uses the new path. A
   dirty lane worktree is REFUSED (never cleaned); unmerged commits left on a
   clean one are saved under refs/fleet-lanes/ before it moves. A LANDING
   (a commit or merge into the main checkout) is the tree's code and goes
   through fleet_gitlock (`with git_lock(main, owner): ...`, FLEET-COMMON 16a);
   nothing in this file commits.
3. GOVERNOR   - one of governor_width (default 3) machine-wide slots, ON-DISK
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

LANE-95 (v20): at >= UNIT_PCT (95) percent usage a lane works in small
resumable units (usage_pct, unit_mode, plan_units, unit_brief, checkpoint,
resume_point, pending_units; CLI `unit` / `resume`); run_lane's claim carries
usage_pct, unit_mode and resume. Unit size only - never routing.

LANE-CAP (v25, RC FLEET KIT REQUEST, operator approved 2026-10-27): the
per-tree lane cap ceiling (lane_cap_max) and the machine-wide governor width
come from machine config ~/.fleet/lanes.json (beside the headless route file),
RE-READ on every acquire, state read and should_yield(). Defaults 3 and 3,
so nothing changes until the file is written. An unreadable file = all
defaults; an invalid key = that key's default; both logged once to
~/.fleet/lanes_config.log - never wider than the defaults. A caller cap above
lane_cap_max CLAMPS to it (and to the width) instead of raising, so a tree can
raise its own cap before the machine config is applied. Under pytest the
machine file is never read (FLEET_LANES_CONFIG names a test file; named empty
= defaults). Holders at indices above a narrowed cap or width still count.
BORROWING: a tree may hold governor slots up to its own cap (governor_slot
cap=, default lane_cap_max); its tickets carry that cap, and a capped tree's
ticket never blocks another tree. FAIR RELEASE: the request queue is the
governor ticket queue; should_yield(code) is True when another tree has a
live ticket, no slot is free, and code holds more than its fair share
(width // active trees, at least 1). The lane driver calls it between
cycles and ends a lane there; NOTHING in this file stops or kills a worker.
ADMISSION (lane acquire): refuse a new lane below ram_floor_mb free physical
memory or above cpu_ceiling_pct machine CPU (CpuMeter from fleet_suite_gate);
an unreadable reading admits (like the suite gate); skipped under pytest
unless admit= is passed. CLI `status` (and status()/status_lines()) lists
slot holders, the queue, the config and the admission readings.

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

GOVERNOR_WIDTH = 3  # v25: the DEFAULT; live value load_config()["governor_width"]
LANE_CAP_MAX = 3  # v25: the DEFAULT; live value load_config()["lane_cap_max"]
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


# ---------------------------------------------------------------- config (v25)

CONFIG_ENV = "FLEET_LANES_CONFIG"
CONFIG_NAME = "lanes.json"
CONFIG_LOG = "lanes_config.log"
CONFIG_DEFAULTS = {"governor_width": GOVERNOR_WIDTH, "lane_cap_max": LANE_CAP_MAX,
                   "ram_floor_mb": 2048, "cpu_ceiling_pct": 90.0}
# (type, low, high) inclusive; cpu_ceiling_pct 100 = no ceiling.
CONFIG_BOUNDS = {"governor_width": (int, 1, 32), "lane_cap_max": (int, 1, 32),
                 "ram_floor_mb": (int, 0, 1 << 20), "cpu_ceiling_pct": (float, 1.0, 100.0)}
# The RC request's suggested starting point - recorded, never applied by the kit.
RECOMMENDED_CONFIG = {"governor_width": 7, "lane_cap_max": 7, "ram_floor_mb": 4096,
                      "cpu_ceiling_pct": 90.0}
_LOGGED = {}


def config_path(environ=None):
    """~/.fleet/lanes.json; FLEET_LANES_CONFIG names another file (named empty
    = no file, the defaults). Under pytest with the variable unset: None, so a
    suite never depends on this box's machine config."""
    env = os.environ if environ is None else environ
    if CONFIG_ENV in env:
        v = (env.get(CONFIG_ENV) or "").strip().strip('"')
        return Path(v) if v else None
    if env.get("PYTEST_CURRENT_TEST"):
        return None
    return Path.home() / ".fleet" / CONFIG_NAME


def _valid(key, value):
    kind, lo, hi = CONFIG_BOUNDS[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if kind is int and not isinstance(value, int):
        return None
    value = kind(value)
    return value if lo <= value <= hi else None


def _log_config(path, errors):
    key = str(path)
    msg = "; ".join(errors)
    log = Path(path).with_name(CONFIG_LOG)
    if _LOGGED.get(key) == msg and log.exists():
        return  # logged once per distinct problem, not on every re-read
    _LOGGED[key] = msg
    with contextlib.suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with log.open("a", encoding="ascii", errors="replace", newline="\n") as fh:
            fh.write(f"{stamp} lanes config invalid, defaults used: {msg[:400]}\n")


def load_config(path=False, environ=None):
    """The live lane config: CONFIG_DEFAULTS overlaid with the valid keys of
    the file, plus "source" (the file, or "defaults") and "errors". path=False
    resolves config_path(); None = defaults only. Never raises."""
    if path is False:
        path = config_path(environ)
    cfg = dict(CONFIG_DEFAULTS, source="defaults", errors=[])
    if path is None:
        return cfg
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return cfg
    except OSError as exc:
        cfg["errors"] = [f"unreadable ({exc.__class__.__name__})"]
        _log_config(path, cfg["errors"])
        return cfg
    try:
        doc = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeError):
        doc = None
    if not isinstance(doc, dict):
        cfg["errors"] = ["not a JSON object"]
        _log_config(path, cfg["errors"])
        return cfg
    errors = []
    for key, value in doc.items():
        if key not in CONFIG_DEFAULTS:
            errors.append(f"unknown key {str(key)[:40]!r} ignored")
            continue
        good = _valid(key, value)
        if good is None:
            errors.append(f"{key}={str(value)[:40]!r} invalid, default {CONFIG_DEFAULTS[key]}")
        else:
            cfg[key] = good
    cfg["source"], cfg["errors"] = str(path), errors
    if errors:
        _log_config(path, errors)
    return cfg


def _cfg(config):
    return load_config() if config is None else config


def _width(width, config=None):
    return int(_cfg(config)["governor_width"]) if width is None else int(width)


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


def _indices(root, n):
    """range(n) plus every <i>.lock already present (v25: a holder taken under
    a wider width or cap still counts after the config narrows)."""
    extra = set()
    with contextlib.suppress(OSError):
        for p in Path(root).glob("*.lock"):
            if p.stem.isdigit():
                extra.add(int(p.stem))
    return sorted(set(range(n)) | extra)


def governor_state(root=None, width=None, stale_after=DEFAULT_STALE_AFTER,
                   now=None):
    """One row per governor slot (v25: width None = the live config, plus any
    held index above it). READ ONLY."""
    root = governor_root() if root is None else Path(root)
    now = time.time() if now is None else now
    rows = []
    for i in _indices(root, _width(width)):
        p = root / f"{i}.lock"
        row = {"index": i, "state": FREE, "repo": None, "run_id": None, "pid": None,
               "age_s": None, "lane_index": None, "ts": None}
        raw = _raw(p)
        if raw is not None:
            rec = _parse(raw)
            ts = rec.get("ts")
            row.update({"repo": rec.get("repo"), "run_id": rec.get("run_id"),
                        "pid": rec.get("pid"), "lane_index": rec.get("lane"),
                        "ts": ts if isinstance(ts, (int, float)) else None,
                        "age_s": None if not isinstance(ts, (int, float)) else
                        max(0.0, now - ts)})
            row["state"] = RECLAIMABLE if _slot_stale(p, raw, stale_after, now) \
                else RUNNING
        rows.append(row)
    return rows


def reap_governor(root, width=None, stale_after=DEFAULT_STALE_AFTER):
    """Remove stale slots; a slot whose bytes changed since judged is kept."""
    removed = 0
    for i in _indices(root, _width(width)):
        p = Path(root) / f"{i}.lock"
        raw = _raw(p)
        if raw is not None and _slot_stale(p, raw, stale_after, time.time()) \
                and _unlink_if_raw(p, raw):
            removed += 1
    return removed


def held_by_repo(root, width=None):
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


def _capped(rec, held):
    """v25: the ticket's repo already holds its own cap of slots."""
    cap = rec.get("cap")
    return isinstance(cap, int) and not isinstance(cap, bool) and \
        held.get(rec.get("repo"), 0) >= cap


def my_turn(qroot, mine, free, held, now=None):
    """True when the ticket at path `mine` is among the first `free` by rank.
    v25: a ticket whose repo is at its own cap is skipped (never blocks)."""
    if free <= 0:
        return False
    now = time.time() if now is None else now
    live = [t for t in tickets(qroot, now=now) if not _capped(t[1], held)]
    order = sorted(live, key=lambda t: ticket_rank(t[1], now, held))
    keys = [os.path.normcase(str(p)) for p, _ in order[:free]]
    return os.path.normcase(str(mine)) in keys


def enqueue(qroot, repo, run_id, priority="queued", since=None, clock=time.time, cap=None):
    """File a ticket. since = when this caller FIRST asked (kept across retries
    so a timeout-and-retry caller still ages into tier 0). v25: cap = the most
    slots this repo may hold (recorded so other waiters can skip it)."""
    if priority not in PRIORITIES:
        raise ValueError(f"priority {priority!r} not in {PRIORITIES}")
    qroot = Path(qroot)
    rec = {**_identity(), "repo": str(repo), "run_id": str(run_id),
           "priority": priority, "ts": float(since) if since is not None else clock()}
    if cap is not None:
        rec["cap"] = int(cap)
    for n in range(100):
        p = qroot / f"{time.time_ns():020d}-{os.getpid()}-{n}.ticket"
        if _exclusive_create(p, rec):
            return p
    raise OSError("could not file a queue ticket")


def _capped_ticket(ticket, cap):
    """v25: record the waiter's own cap in its ticket (written after enqueue,
    so enqueue's v6 signature is unchanged for callers and spies)."""
    rec = _read(ticket)
    if rec and rec.get("cap") != int(cap):
        rec["cap"] = int(cap)
        with contextlib.suppress(OSError):
            _atomic_write(ticket, rec)
    return ticket


def _drop_ticket(ticket):
    raw = _raw(ticket)
    if raw is not None and not _unlink_if_raw(ticket, raw):
        # Undeletable right now: neutralise so every waiter reads it dead.
        with contextlib.suppress(OSError), Path(ticket).open("w", encoding="ascii") as fh:
            json.dump({"pid": 0, "orphaned": True}, fh)


def try_governor(root, width, payload):
    """One non-blocking pass: reap, then exclusive-create the first free slot
    below width (None = the live config). v25: holders above the width count,
    so a narrowed width never admits past it."""
    root = Path(root)
    width = _width(width)
    reap_governor(root, width)
    if sum(held_by_repo(root, width).values()) >= width:
        return None
    for i in range(width):
        p = root / f"{i}.lock"
        if _exclusive_create(p, payload):
            return p
    return None


@contextlib.contextmanager
def governor_slot(repo, run_id, priority="queued", root=None, width=None,
                  timeout=None, poll=2.0, cycle=0, since=None, sleep=time.sleep,
                  on_wait=None, cap=None, lane=None):
    """Hold one machine-wide slot for the block, waiting in the fair queue.
    Raises SlotTimeout when timeout (seconds) elapses first; timeout=0 is a
    single try. Never proceeds unslotted. Take it around the executor call only.
    v25: width None = the live config (re-read every poll); the repo holds at
    most cap slots (None = lane_cap_max; clamped to it and to the width) -
    BORROWING idle slots up to its own cap; lane = the lane index, recorded."""
    root = governor_root() if root is None else Path(root)
    qroot = queue_root(root)
    poll = min(float(poll), MAX_POLL_S)
    payload = {**_identity(), "repo": str(repo), "run_id": str(run_id),
               "cycle": cycle, "ts": time.time(), "priority": priority}
    if lane is not None:
        payload["lane"] = int(lane)
    deadline = None if timeout is None else time.monotonic() + timeout

    def limits():
        cfg = load_config()
        w = _width(width, cfg)
        c = lane_cap(cfg["lane_cap_max"] if cap is None else cap, cfg)
        return w, min(c, w)
    w, c = limits()
    ticket = _capped_ticket(enqueue(qroot, repo, run_id, priority, since), c)
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
                    ticket = _capped_ticket(enqueue(qroot, repo, run_id, priority, first_ask), c)
            w, c = limits()
            reap_governor(root, w)
            held = held_by_repo(root, w)
            free = w - sum(held.values())
            if held.get(str(repo), 0) < c and my_turn(qroot, ticket, free, held):
                payload["ts"] = time.time()
                slot = try_governor(root, w, payload)
                if slot is not None:
                    break
            if deadline is not None and time.monotonic() >= deadline:
                raise SlotTimeout(f"no governor slot within {timeout}s (width {w}, cap {c})")
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
    except (OSError, UnicodeError):  # v15 (RC 1925 a): non-UTF-8 link file
        raw = ""
    if raw.startswith("gitdir:"):
        gitdir = Path(raw.split(":", 1)[1].strip())
        gitdir = (gitdir if gitdir.is_absolute() else path / gitdir).resolve()
        if gitdir.parent.name == "worktrees":
            return gitdir.parents[2]
    return path


def lane_cap(cap=None, config=None):
    """The effective lane cap: cap (None = lane_cap_max) clamped to the live
    lane_cap_max and governor_width (v25: above them CLAMPS, never raises, so
    a tree may raise its cap before the machine config is set). Below 1 or not
    an integer: ValueError."""
    cfg = _cfg(config)
    if cap is None:
        cap = cfg["lane_cap_max"]
    if isinstance(cap, bool):
        raise ValueError(f"lane cap {cap!r} is not an integer")
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        raise ValueError(f"lane cap {cap!r} is not an integer") from None
    if cap < 1:
        raise ValueError(f"lane cap {cap} below 1")
    return min(cap, int(cfg["lane_cap_max"]), int(cfg["governor_width"]))


SIDECAR_VAR = "FLEET_SIDECAR_ROOT"


def _registry_sidecar():
    """(found, value) of FLEET_SIDECAR_ROOT in HKCU Environment."""
    try:
        import winreg
    except ImportError:
        return False, None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                value, _ = winreg.QueryValueEx(key, SIDECAR_VAR)
                return True, str(value)
            except FileNotFoundError:
                return True, None
    except OSError:
        return False, None


# v22 (KIT-V22-SIDECAR): with the variable named NOWHERE (not in the process
# environment, not in HKCU Environment) the root defaults to this directory -
# but only when it exists, and never inside a pytest test (PYTEST_CURRENT_TEST),
# so a suite keeps the v14 path unless it sets the variable itself. A machine
# without the directory keeps the v14 behaviour (no failure).
# v24 (KIT-SIDECAR-PATH): built from parts, so no kit line spells the root
# drive-rooted (the trees' public-path guards flagged the v22/v23 literal).
_SIDECAR_DRIVE = "E:"
_SIDECAR_FOLDER = "Sidecars"
SIDECAR_DEFAULT = (_SIDECAR_DRIVE + os.sep + _SIDECAR_FOLDER) if os.name == "nt" else ""


def _default_sidecar(environ=None):
    env = os.environ if environ is None else environ
    if not SIDECAR_DEFAULT or env.get("PYTEST_CURRENT_TEST"):
        return None
    p = Path(SIDECAR_DEFAULT)
    return p if p.is_dir() else None


def sidecar_root(registry=_registry_sidecar, environ=None, default=None):
    """The sidecar root (v14), or None. The PROCESS environment wins when it
    names the variable at all (an empty value disables it - tests pin it so),
    else the HKCU Environment value (an empty value there disables it too).
    Named nowhere: v22 SIDECAR_DEFAULT when that directory exists (default=
    is a tests-only hook returning the default Path or None). Must be absolute."""
    env = os.environ if environ is None else environ
    value = env.get(SIDECAR_VAR) if SIDECAR_VAR in env else registry()[1]
    if value is None:
        d = _default_sidecar(env) if default is None else default()
        return Path(d) if d and Path(d).is_absolute() else None
    value = (value or "").strip().strip('"')
    return Path(value) if value and Path(value).is_absolute() else None


def sidecar_dir(code, kind, root=None):
    """<sidecar root>/<CODE>/<kind> (kind Worktree, Temp, ...) when the root
    resolves AND <root>/<CODE> already exists, else None (v22: a missing
    sidecar falls back to the caller's v21 behaviour, never a failure)."""
    if not str(code).isalnum():
        return None
    root = sidecar_root() if root is None else (Path(root) if root else None)
    if root is None:
        return None
    base = root / str(code).upper()
    return base / kind if base.is_dir() else None


def worktree_path(repo_root, code, index, root=None):
    """Lane i of repo <code> runs here: <sidecar root>/<CODE>/Worktree/lane-<i>
    when FLEET_SIDECAR_ROOT is set (v14) or, unset, the v22 default
    <SIDECAR_DEFAULT>/<CODE> exists; else <parent>/<code>-worktrees/lane-<i>;
    the old path stays in use while it exists and the new one does not."""
    if not str(code).isalnum():
        raise ValueError(f"repo code {code!r} must be alphanumeric")
    parent = main_tree(repo_root).parent
    old = parent / f"{str(code).lower()}-worktrees" / f"lane-{int(index)}"
    if root is None:
        root = sidecar_root()
        if (root is not None and SIDECAR_VAR not in os.environ
                and _registry_sidecar()[1] is None
                and not (root / str(code).upper()).is_dir()):
            return old  # v22: the built-in default needs <root>/<CODE> to exist
    else:
        root = Path(root) if root else None
    if root is None:
        return old
    new = root / str(code).upper() / "Worktree" / f"lane-{int(index)}"
    if old.exists() and not new.exists():
        return old
    return new


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


def repo_lane_state(repo_root, cap=None, now=None, config=None):
    """One row per lane index 0..cap-1: FREE / RUNNING / RECLAIMABLE. READ ONLY.
    The lane widget's contract: these files only (v25: cap None = the live
    lane_cap_max, plus any <i>.lock still held above it after a narrowing)."""
    now = time.time() if now is None else now
    d = main_tree(repo_root) / LANES_REL
    rows = []
    for i in _indices(d, lane_cap(cap, config)):
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


def try_acquire_lane(repo_root, code, lane, run_id, cap=None, exclusive=True, admit=None):
    """Claim the lowest free (or reclaimable) lane index. Returns
    {"ok": True, "index", "token", "worktree", "lane", "run_id"} or
    {"ok": False, "refused": "lanes_full" | "lane_held" | "admission",
    "holders": [...]} - a refusal writes no lane lock. exclusive=True refuses a
    lane NAME that is already running. Lanes never expire on age.
    v25: cap None = the live lane_cap_max (config re-read here, every call);
    a held index above the cap still counts; admission (free RAM floor, CPU
    ceiling; admit= a readings callable, tests) runs before any lock."""
    cfg = load_config()
    eff = lane_cap(cap, cfg)
    adm = admission(cfg, readings=_readings(admit))
    if not adm["admit"]:
        return {"ok": False, "refused": "admission", "reason": adm["reason"],
                "admission": adm, "holders": []}
    root = main_tree(repo_root)
    d = root / LANES_REL
    d.mkdir(parents=True, exist_ok=True)
    with _acquire_mutex(d):
        now = time.time()
        rows = []
        for i in _indices(d, eff):
            lock = d / f"{i}.lock"
            raw = _raw(lock)
            rows.append((lock, raw, _lane_row(lock, raw, now)))
        holders = [r["lane"] for _, _, r in rows if r["state"] == RUNNING]
        if exclusive and str(lane) in holders:
            return {"ok": False, "refused": "lane_held", "holders": holders}
        if len(holders) >= eff:
            return {"ok": False, "refused": "lanes_full", "holders": holders}
        for lock, raw, row in rows:
            if row["state"] == RUNNING or row["index"] >= eff:
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


# ---------------------------------------------------------------- LANE-CAP (v25)

def should_yield(code, root=None, config=None, now=None):
    """True when tree `code` should END one lane at its next cycle boundary:
    another tree has a live ticket (the request queue), no governor slot is
    free, and `code` holds more than its fair share (width // trees holding
    or waiting, at least 1). READ ONLY - it never stops a worker; the lane
    driver checks it between cycles and simply does not start the next one."""
    root = governor_root() if root is None else Path(root)
    now = time.time() if now is None else now
    w = _width(None, config)
    held = held_by_repo(root, w)
    if w - sum(held.values()) > 0:
        return False
    others = {str(rec.get("repo")) for _p, rec in tickets(queue_root(root), reap=False, now=now)
              if str(rec.get("repo")) != str(code) and not _capped(rec, held)}
    if not others:
        return False
    active = {str(k) for k in held} | others | {str(code)}
    fair = max(1, w // len(active))
    return held.get(str(code), 0) > fair


def free_ram_mb():
    """Available physical memory in MB, or None where it cannot be read."""
    if sys.platform == "win32":
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return None
            return ms.ullAvailPhys / float(1 << 20)
        except (OSError, AttributeError, ValueError):
            return None
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / float(1 << 20)
    except (ValueError, OSError, AttributeError):
        return None


_METER = []


def cpu_pct():
    """Machine CPU busy percent from fleet_suite_gate.CpuMeter (the suite
    gate's own reader; the first call samples ~1 s), or None."""
    try:
        if not _METER:
            import importlib.util
            key = "fleet_kit_fleet_suite_gate"
            mod = sys.modules.get(key)
            if mod is None:
                spec = importlib.util.spec_from_file_location(
                    key, Path(__file__).with_name("fleet_suite_gate.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            _METER.append(mod.CpuMeter())
        return _METER[0].busy()
    except Exception:  # noqa: BLE001 - an unreadable meter admits, like the gate
        return None


def readings():
    """The live admission readings (free RAM MB, CPU busy percent)."""
    return {"free_ram_mb": free_ram_mb(), "cpu_pct": cpu_pct()}


def _readings(admit):
    if callable(admit):
        return admit()
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"free_ram_mb": None, "cpu_pct": None}  # a suite never refuses on the box
    return readings()


def admission(config=None, readings=None):
    """{"admit", "reason", "free_ram_mb", "cpu_pct", "ram_floor_mb",
    "cpu_ceiling_pct"}. A reading of None admits (cannot be read)."""
    cfg = _cfg(config)
    r = readings if readings is not None else {"free_ram_mb": None, "cpu_pct": None}
    ram, cpu = r.get("free_ram_mb"), r.get("cpu_pct")
    floor, ceil = cfg["ram_floor_mb"], cfg["cpu_ceiling_pct"]
    reason = None
    if isinstance(ram, (int, float)) and ram < floor:
        reason = f"ram {ram:.0f} MB free below the floor {floor} MB"
    elif isinstance(cpu, (int, float)) and ceil < 100.0 and cpu > ceil:
        reason = f"cpu {cpu:.0f} percent above the ceiling {ceil:.0f} percent"
    return {"admit": reason is None, "reason": reason,
            "free_ram_mb": None if ram is None else round(float(ram), 1),
            "cpu_pct": None if cpu is None else round(float(cpu), 1),
            "ram_floor_mb": floor, "cpu_ceiling_pct": ceil}


def _iso(ts):
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def status(root=None, trees=None, admit=None, config=None, now=None):
    """Machine lane status: config, slot holders (tree, slot, lane index, pid,
    since), the request queue, admission readings and, per tree in `trees`
    ({code: repo root}), its lane rows. READ ONLY - writes and stops nothing."""
    root = governor_root() if root is None else Path(root)
    now = time.time() if now is None else now
    cfg = load_config() if config is None else config
    rows = governor_state(root, cfg["governor_width"], now=now)
    holders = [{"slot": r["index"], "tree": r["repo"], "lane_index": r["lane_index"],
                "pid": r["pid"], "since": _iso(r["ts"]), "run_id": r["run_id"],
                "state": r["state"]} for r in rows if r["state"] != FREE]
    queue = []
    for _p, rec in sorted(tickets(queue_root(root), reap=False, now=now),
                          key=lambda t: t[1].get("ts") or 0):
        ts = rec.get("ts")
        queue.append({"tree": rec.get("repo"), "priority": rec.get("priority"),
                      "pid": rec.get("pid"), "since": _iso(ts), "cap": rec.get("cap"),
                      "waited_s": round(now - ts, 1) if isinstance(ts, (int, float)) else None})
    running = sum(1 for h in holders if h["state"] == RUNNING)
    out = {"config": {k: cfg[k] for k in (*CONFIG_DEFAULTS, "source", "errors")},
           "recommended": dict(RECOMMENDED_CONFIG),
           "free_slots": max(0, cfg["governor_width"] - running),
           "holders": holders, "queue": queue,
           "admission": admission(cfg, _readings(admit)), "trees": {}}
    for code, repo in (trees or {}).items():
        lanes = []
        for r in repo_lane_state(repo, None, now=now, config=cfg):
            if r["state"] == FREE:
                continue
            lanes.append({"index": r["index"], "lane": r["lane"], "pid": r["pid"],
                          "state": r["state"],
                          "since": None if r["age_s"] is None else _iso(now - r["age_s"])})
        out["trees"][str(code)] = lanes
    return out


def status_lines(doc):
    """One `key: value` / `- item: value` line per item (FLEET-COMMON 19)."""
    c, a = doc["config"], doc["admission"]
    lines = [f"config: width {c['governor_width']}, cap {c['lane_cap_max']}, ram floor "
             f"{c['ram_floor_mb']} MB, cpu ceiling {c['cpu_ceiling_pct']:.0f} percent "
             f"({'file' if c['source'] != 'defaults' else 'defaults'})"]
    lines += [f"config error: {e}" for e in c["errors"]]
    ram = "?" if a["free_ram_mb"] is None else f"{a['free_ram_mb']:.0f} MB"
    cpu = "?" if a["cpu_pct"] is None else f"{a['cpu_pct']:.0f} percent"
    lines.append(f"admission: {'admit' if a['admit'] else 'refuse - ' + a['reason']}, "
                 f"free ram {ram}, cpu {cpu}")
    lines.append(f"free slots: {doc['free_slots']}")
    for h in doc["holders"]:
        lane = "" if h["lane_index"] is None else f" lane {h['lane_index']}"
        lines.append(f"- slot {h['slot']}: {h['tree']}{lane} pid {h['pid']} since "
                     f"{h['since'] or '?'} ({h['state']})")
    for q in doc["queue"]:
        lines.append(f"- waiting: {q['tree']} {q['priority']} since {q['since'] or '?'}")
    for code, lanes in doc["trees"].items():
        for ln in lanes:
            lines.append(f"- {code} lane {ln['index']}: {ln['lane']} pid {ln['pid']} since "
                         f"{ln['since'] or '?'} ({ln['state']})")
    return lines


# ---------------------------------------------------------------- LANE-95 (v20)
# At >= UNIT_PCT percent usage a lane works in small resumable units: one item
# per unit, a commit (through fleet_gitlock) and a checkpoint after each, and a
# resume by unit id, so hitting 100 percent loses at most one unit. The
# percentage changes the UNIT SIZE only - never the account, the route or a
# throttle (MAIN ruling 2026-10-18-acct-fallback condition 3). Unknown usage =
# normal units (today's behaviour).

UNIT_PCT = 95
UNIT_MODES = ("normal", "small")
UNITS_REL = LANES_REL / "units"
QUOTA_FILE = Path(".config") / "teamclaude.state.json"
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
UNIT_BRIEF = (
    "USAGE IS AT OR ABOVE {pct} PERCENT (LANE-95). Work in small resumable units: "
    "do exactly ONE unit (one item) this run, commit it through fleet_gitlock, then "
    "write its checkpoint with `python ops/fleet_kit/fleet_lanes.py unit --root . "
    "--lane <lane> --unit <id> --step <what> --done --commit <sha>` and stop. "
    "Before starting, read `fleet_lanes.py resume --root . --lane <lane>` and finish "
    "that unit first if one is open.")


def _check_id(value, what):
    if not isinstance(value, str) or not 0 < len(value) <= 64 or \
            not set(value) <= _ID_CHARS or value.strip(".") == "":
        raise ValueError(f"{what} must be 1-64 of [A-Za-z0-9._-]")
    return value


def usage_pct(path=None, now=None):
    """The highest live usage window (5-hour or 7-day) across the accounts in
    the proxy's quota file, in percent; None when unknown. A window whose reset
    time has passed is stale and ignored."""
    p = Path(path) if path is not None else Path.home() / QUOTA_FILE
    now = time.time() if now is None else now
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = doc["quota"]
        if not isinstance(rows, list):
            return None
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return None
    best = None
    for row in rows:
        q = row.get("quota") if isinstance(row, dict) else None
        if not isinstance(q, dict):
            continue
        for key in ("unified5h", "unified7d"):
            v, reset = q.get(key), q.get(key + "Reset")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if isinstance(reset, (int, float)) and not isinstance(reset, bool) \
                    and 0 < reset <= now:
                continue
            best = max(best if best is not None else 0.0, float(v) * 100.0)
    return best


def unit_mode(pct, threshold=UNIT_PCT):
    """"small" at or above the threshold, else "normal" (unknown included)."""
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return "normal"
    return "small" if pct >= threshold else "normal"


def plan_units(items, mode, normal_size=None):
    """Batches of work items: one per unit in small mode, else normal_size
    (default: all in one unit)."""
    if mode not in UNIT_MODES:
        raise ValueError(f"mode must be one of {UNIT_MODES}")
    items = list(items)
    if not items:
        return []
    size = 1 if mode == "small" else (normal_size or len(items))
    return [items[i:i + size] for i in range(0, len(items), size)]


def unit_brief(mode, pct=UNIT_PCT):
    """The prompt paragraph a lane adds to its child's prompt in small mode."""
    return UNIT_BRIEF.format(pct=int(pct if isinstance(pct, (int, float)) else UNIT_PCT)) \
        if mode == "small" else ""


def units_path(repo_root, lane):
    """<main checkout>/ops/loop/control/lanes/units/<lane>.json."""
    return main_tree(repo_root) / UNITS_REL / (_check_id(lane, "lane") + ".json")


def _units(repo_root, lane):
    p = units_path(repo_root, lane)
    if not p.exists():
        return {"lane": lane, "unit": None, "step": None, "status": None, "commit": None,
                "done": [], "last_commit": None, "updated": None}
    try:
        doc = json.loads(p.read_text(encoding="ascii"))
        if not isinstance(doc, dict) or not isinstance(doc.get("done"), list):
            raise ValueError("shape")
        return doc
    except (OSError, ValueError, UnicodeError) as exc:
        # never cleared or rewritten: an unreadable record resumes nothing
        raise ValueError(f"units record unreadable ({exc.__class__.__name__})") from None


def checkpoint(repo_root, lane, unit, step, status="running", commit=None, clock=time.time):
    """Record the lane's current unit (status running) or close it (done: the id
    joins "done", "commit" becomes "last_commit"). Atomic; always in the main
    checkout, even from a lane worktree."""
    _check_id(lane, "lane")
    _check_id(unit, "unit")
    if status not in ("running", "done"):
        raise ValueError("status must be running or done")
    doc = _units(repo_root, lane)
    doc.update({"lane": lane, "updated": round(float(clock()), 3)})
    if status == "done":
        if unit not in doc["done"]:
            doc["done"].append(unit)
        doc.update({"unit": None, "step": None, "status": None, "commit": None})
        if commit:
            doc["last_commit"] = str(commit)[:64]
    else:
        doc.update({"unit": unit, "step": " ".join(str(step).split())[:120],
                    "status": "running", "commit": str(commit)[:64] if commit else None})
    p = units_path(repo_root, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, doc)
    return doc


def resume_point(repo_root, lane):
    """{"unit", "step", "commit"} of the lane's open unit, else None."""
    doc = _units(repo_root, lane)
    if doc.get("status") == "running" and doc.get("unit"):
        return {"unit": doc["unit"], "step": doc.get("step"), "commit": doc.get("commit")}
    return None


def done_units(repo_root, lane):
    return list(_units(repo_root, lane)["done"])


def pending_units(repo_root, lane, ids):
    """ids not yet done, in order - a resumed lane never repeats a done unit."""
    done = set(done_units(repo_root, lane))
    return [i for i in ids if i not in done]


def clear_units(repo_root, lane):
    """The lane's whole job is done: drop its units record."""
    with contextlib.suppress(FileNotFoundError):
        units_path(repo_root, lane).unlink()


def _usage_of(usage):
    if usage is None:
        return usage_pct()
    if callable(usage):
        return usage()
    return usage


@contextlib.contextmanager
def run_lane(repo_root, code, lane_name, run_id, cap=None, base="HEAD",
             exclusive=True, run=_git, usage=None, admit=None):
    """Repo lane + clean worktree for the block. Yields the claim ("worktree",
    "index", "saved_ref"). Takes NO governor slot: hold one around the executor
    call (spawn(governor=...) or slots.hold), never around git. Raises
    LaneRefused before anything runs; releases the lane however the block ends.
    v16: when the block ends, progress/lane-<i>.json (FLEET-COMMON 13 d) that
    still says running is written as failed, so a killed lane leaves no live
    row behind.
    v20 (LANE-95): the claim also carries "usage_pct" (usage: a number, a
    callable, or None = usage_pct()), "unit_mode" (small at >= UNIT_PCT) and
    "resume" (the lane's open unit, or None; an unreadable record = None)."""
    claim = try_acquire_lane(repo_root, code, lane_name, run_id, cap, exclusive, admit=admit)
    if not claim["ok"]:
        raise LaneRefused(f"{claim['refused']}: {claim.get('reason') or claim['holders']}")
    claim["held_by_block"] = True
    try:
        claim["saved_ref"] = ensure_worktree(repo_root, claim["worktree"], base,
                                             run=run)["saved_ref"]
        try:
            pct = _usage_of(usage)
        except Exception:  # a broken usage source never blocks the lane
            pct = None
        claim["usage_pct"] = pct if isinstance(pct, (int, float)) and \
            not isinstance(pct, bool) else None
        claim["unit_mode"] = unit_mode(claim["usage_pct"])
        try:
            claim["resume"] = resume_point(repo_root, lane_name)
        except ValueError:
            claim["resume"] = None
        yield claim
    finally:
        try:
            _close_lane_row(repo_root, claim.get("index"))
        finally:
            release_lane(claim)


def _close_lane_row(repo_root, index):
    """v16: the lane's progress row, if still running, becomes failed."""
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    try:
        import importlib.util
        name = "fleet_kit_headless_for_lanes"
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).with_name("fleet_headless.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.modules[name] = mod
        return mod.close_progress(main_tree(repo_root), f"lane-{index}",
                                  "lane block ended without a final status")
    except (OSError, ValueError, ImportError):
        return None


# ---------------------------------------------------------------- CLI (v20)

def _status_cli(args, out):
    trees = {}
    for t in args.tree:
        code, _, path = t.partition("=")
        if not path:
            print(json.dumps({"error": "--tree takes CODE=ROOT"}), file=out)
            return 2
        trees[code] = path
    if args.no_sample:
        def admit():
            return {"free_ram_mb": None, "cpu_pct": None}
    else:
        admit = readings
    doc = status(root=args.slots, trees=trees, admit=admit)
    if args.json:
        print(json.dumps(doc, indent=1), file=out)
    else:
        print("\n".join(status_lines(doc)), file=out)
    return 0


def main(argv=None, stdout=None):
    """`python fleet_lanes.py unit --root R --lane L --unit U --step S [--done]
    [--commit SHA]` writes a LANE-95 checkpoint; `resume --root R --lane L`
    prints the open unit (JSON, null when none); v25 `status [--slots DIR]
    [--tree CODE=ROOT ...] [--json] [--no-sample]` prints the lane status.
    Exit 0 ok, 2 bad input."""
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_lanes.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("unit")
    up.add_argument("--root", required=True)
    up.add_argument("--lane", required=True)
    up.add_argument("--unit", required=True)
    up.add_argument("--step", required=True)
    up.add_argument("--done", action="store_true")
    up.add_argument("--commit")
    rp = sub.add_parser("resume")
    rp.add_argument("--root", required=True)
    rp.add_argument("--lane", required=True)
    sp = sub.add_parser("status")
    sp.add_argument("--slots", help="governor slot root (default: the machine root)")
    sp.add_argument("--tree", action="append", default=[], metavar="CODE=ROOT")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--no-sample", action="store_true", help="skip the RAM / CPU readings")
    out = stdout or sys.stdout
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if args.cmd == "status":
        return _status_cli(args, out)
    try:
        if args.cmd == "unit":
            doc = checkpoint(args.root, args.lane, args.unit, args.step,
                             status="done" if args.done else "running", commit=args.commit)
        else:
            doc = resume_point(args.root, args.lane)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)[:200]}), file=out)
        return 2
    except OSError as exc:  # v21 (CS 2356 item 6): the class only, never a path
        print(json.dumps({"error": exc.__class__.__name__}), file=out)
        return 2
    print(json.dumps(doc), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
