# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v12 - RACE GUARDS: the per-tree commit/push lock (FLEET-COMMON 16).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: nothing serialized commits in a tree's main checkout. An interactive
session, an inbox responder, /done and lane landings could commit at the same
moment, and no tree handled a leftover .git/index.lock.

    python fleet_gitlock.py run [--owner OWNER] [--timeout S] -- git commit ...
    python fleet_gitlock.py run [--owner OWNER] -- git push ...
    python fleet_gitlock.py status [DIR]

`run`:
  1. acquires <main checkout>/ops/loop/control/locks/git.lock (main checkout =
     the git common dir's parent, so every worktree of a tree shares one lock)
     by exclusive create, holder {pid, pid_started, owner, verb, start}. A
     holder whose pid is dead, provably reused, or older than STALE_MIN
     minutes is broken ONCE per acquire and the break is logged to
     ops/loop/control/gitlock.jsonl; otherwise it waits up to --timeout
     (default 300 s) with a progress line on stderr, then fails (exit 3);
  2. checks the worktree's index.lock: removed only when no git process is
     alive and it is older than 60 s; otherwise waited for, then exit 3;
  3. for `commit`: refuses (exit 3) when the staged set - plus the tracked
     modifications for -a/--all and any pathspec - holds a path claimed in
     fleet_claims by a live owner other than --owner (env FLEET_CLAIM_OWNER);
  4. runs the git command, releases the lock, exits with git's code.

Python callers (e.g. a lane landing) use `with git_lock(dir, owner): ...`.
Messages name a path relative to its tree, never an account or email.
Pure stdlib plus the sibling kit file fleet_claims.py.
"""

import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

LOCKS_REL = Path("ops/loop/control/locks")
LOG_REL = Path("ops/loop/control/gitlock.jsonl")
LOCK_NAME = "git.lock"
STALE_MIN = 15.0
WAIT_S = 300.0
INDEX_LOCK_AGE_S = 60.0
INDEX_WAIT_S = 90.0
HALF_WRITTEN_GRACE_S = 30.0
PROGRESS_EVERY_S = 15.0
POLL_S = 0.25
VERBS = ("commit", "push")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class LockRefused(RuntimeError):
    """The lock, the index.lock or the claim check refused the run."""


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


# ---------------------------------------------------------------- processes

def pid_alive(pid):
    """True if pid is live; a pid we cannot query counts as ALIVE."""
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
    """Process creation time (epoch s) or None when it cannot be read."""
    if sys.platform != "win32":
        return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
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
        return ((t[0].dwHighDateTime << 32) | t[0].dwLowDateTime) / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(h)


def holder_gone(rec, now, stale_min=STALE_MIN, alive=pid_alive, started=proc_started):
    """Why a lock holder record is stale ('' = it is not)."""
    pid = rec.get("pid")
    if not alive(pid):
        return "holder pid dead"
    want, have = rec.get("pid_started"), started(pid)
    if want is not None and have is not None and abs(float(want) - have) > 1.0:
        return "holder pid reused"
    try:
        if now - float(rec.get("start", now)) > stale_min * 60.0:
            return f"holder older than {int(stale_min)} min"
    except (TypeError, ValueError):
        return "holder record unreadable"
    return ""


def git_alive():
    """True when any git process is running on the box."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq git.exe", "/NH", "/FO", "CSV"],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=_NO_WINDOW).stdout
            return "git.exe" in out.lower()
        out = subprocess.run(["pgrep", "-x", "git"], capture_output=True, text=True,
                             timeout=10).stdout
        return bool(out.strip())
    except (OSError, subprocess.SubprocessError):
        return True


# ---------------------------------------------------------------- paths

def tree(cwd):
    t = claims.tree_of(cwd)
    if t is None:
        raise LockRefused("GITLOCK: not inside a git tree")
    return t


def lock_path(cwd):
    return Path(tree(cwd)[2]) / LOCKS_REL / LOCK_NAME


def _log(main, row):
    try:
        p = Path(main) / LOG_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="ascii", errors="replace", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _say(msg):
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


# ---------------------------------------------------------------- the lock

def _create(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return None
    raw = json.dumps(rec, sort_keys=True).encode("ascii")
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    return raw


def _raw(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def acquire(cwd, owner=None, verb="", timeout=WAIT_S, stale_min=STALE_MIN,
            clock=time.time, sleep=time.sleep, alive=pid_alive, started=proc_started,
            pid=None):
    """Take the tree's git lock. Returns (path, raw) for release()."""
    path = lock_path(cwd)
    main = tree(cwd)[2]
    pid = os.getpid() if pid is None else pid
    rec = {"pid": pid, "pid_started": started(pid), "owner": owner or "", "verb": verb,
           "start": clock()}
    begin, broke, said = clock(), False, clock()
    while True:
        rec["start"] = clock()
        raw = _create(path, rec)
        if raw is not None:
            return path, raw
        held = _raw(path)
        try:
            doc = json.loads(held) if held else None
        except ValueError:
            doc = None
        now = clock()
        if isinstance(doc, dict):
            why = holder_gone(doc, now, stale_min, alive, started)
        else:
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            why = (f"unreadable lock older than {int(HALF_WRITTEN_GRACE_S)}s"
                   if age > HALF_WRITTEN_GRACE_S else "")
        if why and not broke:
            broke = True
            if _raw(path) == held:
                with contextlib.suppress(OSError):
                    path.unlink()
                _log(main, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "stale-break",
                            "why": why, "by_pid": pid,
                            "holder_pid": doc.get("pid") if isinstance(doc, dict) else None})
                _say("gitlock: broke a stale lock ({})".format(why))
            continue
        if now - begin >= timeout:
            hp = doc.get("pid") if isinstance(doc, dict) else "?"
            raise LockRefused(f"GITLOCK: lock still held after {int(timeout)}s "
                              f"(holder pid {hp}); not running git")
        if now - said >= PROGRESS_EVERY_S:
            said = now
            _say(f"gitlock: waiting for the tree's git lock "
                 f"({int(now - begin)}s of {int(timeout)}s)")
        sleep(POLL_S)


def release(path, raw):
    """Unlink the lock only while it still holds our own bytes."""
    if raw is not None and _raw(path) == raw:
        with contextlib.suppress(OSError):
            path.unlink()


@contextlib.contextmanager
def git_lock(cwd, owner=None, verb="", **kw):
    path, raw = acquire(cwd, owner, verb, **kw)
    try:
        yield path
    finally:
        release(path, raw)


def clear_index_lock(cwd, clock=time.time, sleep=time.sleep, alive_git=git_alive,
                     wait=INDEX_WAIT_S, min_age=INDEX_LOCK_AGE_S):
    """Make sure no leftover index.lock blocks the run. Returns 'none',
    'removed' or 'cleared' (it went away while we waited)."""
    top, gitdir, main = tree(cwd)
    il = Path(gitdir) / "index.lock"
    begin, seen = clock(), False
    while True:
        try:
            age = clock() - il.stat().st_mtime
        except OSError:
            return "cleared" if seen else "none"
        seen = True
        if age >= min_age and not alive_git():
            try:
                il.unlink()
            except OSError:
                pass
            else:
                _log(main, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "event": "index-lock-removed", "age_s": int(age)})
                return "removed"
        if clock() - begin >= wait:
            raise LockRefused(f"GITLOCK: index.lock present for {int(age)}s and a git "
                              f"process is alive or it is younger than {int(min_age)}s; "
                              "not running git")
        sleep(1.0)


# ---------------------------------------------------------------- claim check

def _git_out(top, *args):
    git = os.environ.get("FLEET_GIT") or "git"
    r = subprocess.run([git, "-C", str(top), *args], capture_output=True, text=True,
                       timeout=60, creationflags=_NO_WINDOW)
    return [ln for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []


def commit_paths(top, commit_args, lister=None):
    """Absolute paths the commit would record."""
    lister = lister or (lambda *a: _git_out(top, *a))
    rel = list(lister("diff", "--cached", "--name-only"))
    if any(a in ("-a", "--all") or (re.fullmatch(r"-[A-Za-z]+", a) and "a" in a)
           for a in commit_args if a.startswith("-")):
        rel += list(lister("diff", "--name-only"))
    if "--" in commit_args:
        rel += commit_args[commit_args.index("--") + 1:]
    return [Path(top) / r for r in rel]


def check_claims(top, commit_args, owner, lister=None, now=None):
    hits = claims.foreign_claims(commit_paths(top, commit_args, lister), owner, now)
    if hits:
        raise LockRefused("GITLOCK: {} is claimed by another live agent; unstage it "
                          "(git restore --staged <path>) or wait for that agent".format(claims.rel_in(hits[0][0], top)))


# ---------------------------------------------------------------- CLI

def parse(argv):
    if "--" not in argv:
        raise LockRefused("GITLOCK: usage: run [--owner O] [--timeout S] -- git commit|push ...")
    k = argv.index("--")
    opts, cmd = argv[:k], argv[k + 1:]
    owner, timeout = os.environ.get(claims.ENV_OWNER) or None, WAIT_S
    i = 0
    while i < len(opts):
        if opts[i] == "--owner" and i + 1 < len(opts):
            owner, i = opts[i + 1], i + 2
        elif opts[i].startswith("--owner="):
            owner, i = opts[i].split("=", 1)[1], i + 1
        elif opts[i] == "--timeout" and i + 1 < len(opts):
            timeout, i = float(opts[i + 1]), i + 2
        else:
            raise LockRefused("GITLOCK: unknown option {}".format(opts[i]))
    g = claims._git_verb(cmd)
    if g is None or g[0] not in VERBS:
        raise LockRefused("GITLOCK: the command must be git commit or git push")
    return owner, timeout, cmd, g


def run(argv, cwd=None, runner=None, **kw):
    cwd = Path(cwd or os.getcwd())
    owner, timeout, cmd, (verb, args, cdir) = parse(argv)
    where = (cwd / cdir) if cdir and not Path(cdir).is_absolute() else Path(cdir or cwd)
    runner = runner or (lambda c: subprocess.run(c, cwd=str(cwd)).returncode)
    with git_lock(where, owner, verb, timeout=timeout, **kw):
        clear_index_lock(where)
        if verb == "commit":
            check_claims(tree(where)[0], args, owner)
        return runner(cmd)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["run"]:
            return run(argv[1:])
        if argv[:1] == ["status"]:
            p = lock_path(argv[1] if len(argv) > 1 else os.getcwd())
            raw = _raw(p)
            print("free" if raw is None else "held " + raw.decode("ascii", "replace"))
            return 0
    except LockRefused as exc:
        _say(str(exc))
        return 3
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
