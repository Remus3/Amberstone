# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v14 - RACE GUARDS: the machine-wide whole-suite gate (FLEET-COMMON 16).

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
Pure stdlib plus the sibling kit files fleet_claims.py and fleet_gitlock.py.
"""

import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
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
LANE_MAX_S = 120.0
LANE_OVERRUN_S = 240.0
LANE_MIN_RUNS = 3
LANE_WINDOW = 5
DURATIONS_TAIL_BYTES = 1 << 20
WAIT_S = 3600.0
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
        raw = json.dumps({"pid": pid, "pid_started": started(pid), "start": clock()},
                         sort_keys=True).encode("ascii")
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


def try_lane(d, n, pid=None, alive=None, started=None, clock=time.time):
    """(k, raw) for the lane slot taken now, or None (KIT-15)."""
    k = lane_index(n)
    if k is None:
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
                      "lane": True}, sort_keys=True).encode("ascii")
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

def take_ticket(d, pid=None, started=None, ns=None):
    """Create this waiter's queue ticket; returns its path."""
    q = Path(d) / QUEUE
    q.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    started = started or gitlock.proc_started
    raw = json.dumps({"pid": pid, "pid_started": started(pid)}, sort_keys=True)
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


def queue_ahead(d, ticket, alive=None, started=None):
    """Live tickets older than `ticket` (dead / reused ones are removed)."""
    q = Path(d) / QUEUE
    try:
        names = sorted(x.name for x in q.glob("t-*.json"))
    except OSError:
        return 0
    ahead = 0
    for name in names:
        if name >= Path(ticket).name:
            break
        if slot_live(q / name, alive, started):
            ahead += 1
        else:
            with contextlib.suppress(OSError):
                (q / name).unlink()
    return ahead


def acquire(d, n, timeout=WAIT_S, clock=time.time, sleep=time.sleep, alive=None,
            started=None, pid=None, lane=False, **kw):
    """FIFO: wait for a slot only while no older live waiter could take it.
    lane=True (KIT-15, a known short suite) may also take the lane slot when
    no regular slot is free to it; the lane is not FIFO-ordered."""
    begin = said = clock()
    ticket = take_ticket(d, pid, started)
    try:
        while True:
            free = n - len(held(d, alive, started, upto=n))
            if free > 0 and queue_ahead(d, ticket, alive, started) < free:
                got = try_slot(d, n, pid=pid, alive=alive, started=started, clock=clock, **kw)
                if got:
                    return got
            if lane:
                got = try_lane(d, n, pid=pid, alive=alive, started=started, clock=clock)
                if got:
                    return got
            now = clock()
            if now - begin >= timeout:
                raise GateRefused(f"SUITE-GATE: no suite slot free after {int(timeout)}s "
                                  f"({n} of {n} held); not running the suite")
            if now - said >= PROGRESS_EVERY_S:
                said = now
                _say(f"suite gate: waiting for a suite slot ({n} slot(s), "
                     f"{queue_ahead(d, ticket, alive, started)} waiter(s) ahead, "
                     f"{int(now - begin)}s of {int(timeout)}s)")
            sleep(POLL_S)
    finally:
        drop_ticket(ticket)


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


def resolve_exe(cmd, cwd):
    """v14 (KIT-13 carry-over): Windows CreateProcess does not find a RELATIVE
    executable path such as env/py312/Scripts/python.exe (WinError 2), so a
    relative path-like command word is anchored to cwd when the file exists
    there (with .exe tried on Windows). Bare names still resolve on PATH.
    v15 (EW 1955): on Windows a BARE name whose PATH hit is a .cmd/.bat shim
    (npm -> npm.cmd) is replaced by that full path, since CreateProcess finds
    only .exe from a bare name (WinError 2); any other hit is left as given."""
    if not cmd:
        return list(cmd)
    w = cmd[0]
    if "/" not in w and "\\" not in w and not Path(w).is_absolute():
        if sys.platform == "win32":
            hit = shutil.which(w)
            if hit and hit.lower().endswith((".cmd", ".bat")):
                return [hit, *cmd[1:]]
        return list(cmd)
    if Path(w).is_absolute():
        return list(cmd)
    for cand in (Path(cwd) / w, Path(cwd) / (w + ".exe")):
        if cand.is_file():
            return [str(cand), *cmd[1:]]
    return list(cmd)


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
    check_straddle(cwd, owner, dirty)
    d = Path(d) if d else gate_dir()
    clock = kw.get("clock", time.time)
    tree, chash = tree_name(cwd), cmd_hash(cmd)
    lane = lane_index(n) is not None and lane_eligible(d, tree, chash)
    asked = clock()
    k, raw = acquire(d, n, timeout, lane=lane, **kw)
    got = clock()
    rc = None
    try:
        check_straddle(cwd, owner, dirty)
        env = dict(os.environ, FLEET_SUITE_SLOT=str(k))
        runner = runner or (lambda c, e: subprocess.run(c, cwd=str(cwd), env=e,
                                                        **gitlock.quiet_inherit()).returncode)
        rc = runner(resolve_exe(cmd, cwd), env)
        return rc
    finally:
        release(d, k, raw)
        hold = clock() - got
        line = {"ts": round(got, 3), "tree": tree, "cmd": chash, "slot": k,
                "lane": k == lane_index(n), "wait_s": round(got - asked, 3),
                "hold_s": round(hold, 3), "exit": rc}
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
