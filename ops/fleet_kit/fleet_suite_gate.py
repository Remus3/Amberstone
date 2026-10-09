# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v12 - RACE GUARDS: the machine-wide whole-suite gate (FLEET-COMMON 16).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: whole test suites from several trees ran at once on one box. Four
concurrent suites lost xdist workers, and timing tests flaked under the load:
the number graded was the sibling load, not the code.

    python fleet_suite_gate.py run [--owner O] [--slots N] [--timeout S] -- <suite cmd>
    python fleet_suite_gate.py status

`run`:
  1. refuses (exit 3) while the tree holds uncommitted edits to a path claimed
     in fleet_claims by a live owner other than --owner (env FLEET_CLAIM_OWNER):
     a run straddling an edit says nothing;
  2. takes one of N machine-wide slots - N = --slots, else env
     FLEET_SUITE_SLOTS, default 1, at most MAX_SLOTS - as
     <dir>/slot-<k>.lock by exclusive create, holder {pid, pid_started, start};
     <dir> = env FLEET_SUITE_DIR, else %LOCALAPPDATA%/fleet/suite (POSIX:
     ~/.cache/fleet/suite). A slot whose pid is dead or provably reused is
     broken. While waiting it prints a progress line to stderr every 30 s;
     after --timeout (default 3600 s) it FAILS CLOSED (exit 3) without running;
  3. re-checks 1 inside the slot, runs the suite (env FLEET_SUITE_SLOT=k),
     releases the slot, exits with the suite's code.
Pure stdlib plus the sibling kit files fleet_claims.py and fleet_gitlock.py.
"""

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ENV_DIR = "FLEET_SUITE_DIR"
ENV_SLOTS = "FLEET_SUITE_SLOTS"
DEFAULT_SLOTS = 1
MAX_SLOTS = 2
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


def held(d, alive=None, started=None):
    """Indices of live slots (stale slot files are removed on the way)."""
    out = []
    for k in range(MAX_SLOTS):
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
    if len(held(d, alive, started)) >= n:
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
        if len(held(d, alive, started)) > n:  # a wider runner raced us
            release(d, k, raw)
            return None
        return k, raw
    return None


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


def acquire(d, n, timeout=WAIT_S, clock=time.time, sleep=time.sleep, **kw):
    begin = said = clock()
    while True:
        got = try_slot(d, n, clock=clock, **kw)
        if got:
            return got
        now = clock()
        if now - begin >= timeout:
            raise GateRefused(f"SUITE-GATE: no suite slot free after {int(timeout)}s "
                              f"({n} of {n} held); not running the suite")
        if now - said >= PROGRESS_EVERY_S:
            said = now
            _say(f"suite gate: waiting for a suite slot ({n} of {n} held, "
                 f"{int(now - begin)}s of {int(timeout)}s)")
        sleep(POLL_S)


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


def check_straddle(cwd, owner, dirty=dirty_paths, now=None):
    t = claims.tree_of(cwd)
    hits = claims.foreign_claims(dirty(cwd), owner, now)
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


def run(argv, cwd=None, runner=None, dirty=dirty_paths, d=None, **kw):
    cwd = Path(cwd or os.getcwd())
    owner, n, timeout, cmd = parse(argv)
    check_straddle(cwd, owner, dirty)
    d = Path(d) if d else gate_dir()
    k, raw = acquire(d, n, timeout, **kw)
    try:
        check_straddle(cwd, owner, dirty)
        env = dict(os.environ, FLEET_SUITE_SLOT=str(k))
        runner = runner or (lambda c, e: subprocess.run(c, cwd=str(cwd), env=e).returncode)
        return runner(cmd, env)
    finally:
        release(d, k, raw)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["run"]:
            return run(argv[1:])
        if argv[:1] == ["status"]:
            d = gate_dir()
            print(f"{len(held(d))} of {slots()} slot(s) held")
            return 0
    except GateRefused as exc:
        _say(str(exc))
        return 3
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
