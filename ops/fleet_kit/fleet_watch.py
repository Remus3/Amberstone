# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit - the watcher primitive (since kit v5).

A short scheduled script checks ONE source for item ids it has not seen and
hands the new ones to an injected delivery function. Five rules:

a. BASELINE FIRST - the first successful run for a source records every id
   that exists and delivers nothing: history is not news.
b. ADVANCE ONLY AFTER DELIVERY - the seen-set grows only when deliver()
   returns a dict whose "delivered" is exactly True; anything else (False,
   a truthy non-dict, an exception) re-offers the same items next run.
c. ONE RUN AT A TIME - watch_lock() is a directory holding the holder's pid,
   created atomically (temp dir + rename). A lock whose pid is dead is taken
   over at once; liveness is judged by the pid, never by an mtime.
d. ROT ALERTS ONCE - consecutive fetch failures are counted per source; when
   the count reaches alert_after exactly one alert is delivered; the next
   successful fetch resets the count.
e. QUIET WHEN NOTHING CHANGED - no new ids, no deliver() call.

v10 keyword-only extensions (LW 0135, all off by default, so a v9 call is
unchanged): partial=True lets deliver() return {"delivered": [ids]} and
advances exactly those ids; confirm_arg=True calls deliver(items, confirm)
and confirm(ids) persists those ids at once (a long delivery that dies after
one item never re-sends it); baseline=False treats a STATE-shaped source's
first run as work, not history; persist=False writes nothing (dry run).
FlatSeenState reads and writes a legacy {"seen": [...]} file for one source;
`{}` there is CORRUPT, never "seen nothing".

Callers check their own HALT file before calling run_source. A state file that
exists but cannot be parsed raises WatchStateCorrupt and is never rewritten,
because a silent reset would replay history as news.

v11 (CS 1623 item 6): no exception text reaches a message, an alert() payload
or a run detail with a path in it - an OSError renders as its class, errno and
strerror only (never its filename), and any other text has absolute paths
replaced by <path> (_safe_reason).

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import contextlib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

SCHEMA = 1
MAX_SEEN = 5000
OUTCOMES = ("baseline", "nothing-new", "delivered", "deliver-failed", "fetch-failed",
            "deliver-partial")
# fetch / deliver / alert are INJECTED callables: whatever they raise is an
# outcome of the run (rot, failed send), never a crash of the watcher. Named
# once here so every such handler is deliberate and greppable.
ANY_FAILURE = (Exception,)


# A Windows drive path, a UNC path, or a POSIX absolute path of 2+ parts.
_PATHLIKE = re.compile(r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\|(?<![\w.:/])/(?=[^/\s]+/))"
                       r"[^\s'\"<>|,;]*")
# Any remaining token with a backslash in it (the tail of a path with spaces).
_BACKSLASHED = re.compile(r"[^\s'\"]*\\[^\s'\"]*")


def _safe_reason(exc):
    """One line describing exc with no path in it: an OSError is its errno and
    strerror only (its filename attributes are never rendered); any other
    exception's first line has absolute paths, and any token holding a
    backslash, replaced by <path>."""
    if isinstance(exc, OSError) and (exc.errno is not None or exc.strerror):
        text = f"[Errno {exc.errno}] {exc.strerror or ''}".strip()
    else:
        lines = str(exc).strip().splitlines()
        text = lines[0] if lines else ""
    text = _BACKSLASHED.sub("<path>", _PATHLIKE.sub("<path>", text))
    return text[:200] or type(exc).__name__


class WatchStateCorrupt(Exception):
    """The state file exists but is not a valid watch state. Left untouched."""


class LockBusy(Exception):
    """Another live run holds the watch lock."""


# ---------------------------------------------------------------- state

def _valid_source(rec):
    return (isinstance(rec, dict)
            and isinstance(rec.get("seen", []), list)
            and all(isinstance(i, str) for i in rec.get("seen", []))
            and isinstance(rec.get("failures", 0), int)
            and isinstance(rec.get("baselined", False), bool)
            and isinstance(rec.get("alerted", False), bool))


class WatchState:
    """Per-source seen ids, baseline flag, failure count and alert flag, kept
    in one JSON file written atomically (temp file + os.replace), ASCII + LF."""

    def __init__(self, path, max_seen=MAX_SEEN):
        self.path = Path(path)
        self.max_seen = int(max_seen)
        self._data = {"schema": SCHEMA, "sources": {}}
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise WatchStateCorrupt(f"unreadable watch state: {_safe_reason(exc)}") from None
            if not (isinstance(doc, dict) and isinstance(doc.get("sources"), dict)
                    and all(_valid_source(r) for r in doc["sources"].values())):
                raise WatchStateCorrupt("watch state has the wrong shape")
            self._data = doc

    def _src(self, source):
        return self._data["sources"].setdefault(
            source, {"baselined": False, "seen": [], "failures": 0, "alerted": False})

    def seen(self, source):
        return list(self._src(source)["seen"])

    def baselined(self, source):
        return bool(self._src(source)["baselined"])

    def failures(self, source):
        return int(self._src(source)["failures"])

    def alerted(self, source):
        return bool(self._src(source)["alerted"])

    def _add_seen(self, source, ids):
        rec = self._src(source)
        rec["seen"] = (rec["seen"] + list(ids))[-self.max_seen:]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="ascii", newline="\n") as f:
                f.write(json.dumps(self._data, indent=1, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()


class FlatSeenState:
    """A legacy single-source seen file, {"seen": [ids]}, behind the WatchState
    interface run_source uses. A missing file is a fresh, un-baselined source;
    a file that is not exactly {"seen": [str, ...]} (`{}` included) raises
    WatchStateCorrupt and is never rewritten. Failure counts and the alert
    flag live in memory only (the legacy file has no room for them)."""

    def __init__(self, path, max_seen=MAX_SEEN):
        self.path = Path(path)
        self.max_seen = int(max_seen)
        self._rec = {"baselined": False, "seen": [], "failures": 0, "alerted": False}
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise WatchStateCorrupt(f"unreadable seen file: {_safe_reason(exc)}") from None
            if not (isinstance(doc, dict) and isinstance(doc.get("seen"), list)
                    and all(isinstance(i, str) for i in doc["seen"])):
                raise WatchStateCorrupt("seen file is not {\"seen\": [ids]}")
            self._rec["seen"], self._rec["baselined"] = list(doc["seen"]), True

    def _src(self, source):
        return self._rec

    def seen(self, source=None):
        return list(self._rec["seen"])

    def baselined(self, source=None):
        return bool(self._rec["baselined"])

    def _add_seen(self, source, ids):
        self._rec["seen"] = (self._rec["seen"] + list(ids))[-self.max_seen:]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="ascii", newline="\n") as f:
                f.write(json.dumps({"seen": self._rec["seen"]}, indent=1) + "\n")
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()


# ---------------------------------------------------------------- lock

def default_pid_alive(pid):
    """True when a process with this pid exists. On Windows this asks
    OpenProcess + GetExitCodeProcess (os.kill there TERMINATES the process);
    elsewhere it sends signal 0."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        if pid > 0xFFFFFFFF:
            return False
        handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied = exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_pid(lock_dir):
    try:
        return int((Path(lock_dir) / "pid").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _side(lock, tag):
    return lock.with_name(f".{lock.name}.{tag}.{uuid.uuid4().hex}")


def _remove_dir(path):
    shutil.rmtree(path, ignore_errors=True)


def _try_acquire(lock, pid):
    """Create the lock atomically WITH its pid: build a temp dir holding the
    pid file, then rename it onto the lock path (fails if the lock exists)."""
    tmp = _side(lock, "new")
    tmp.mkdir()
    try:
        (tmp / "pid").write_text(f"{pid}\n", encoding="ascii", newline="\n")
        tmp.rename(lock)
        return True
    except FileExistsError:
        return False
    except OSError:
        if lock.exists():
            return False
        raise
    finally:
        if tmp.exists():
            _remove_dir(tmp)


@contextlib.contextmanager
def watch_lock(path, pid=None, pid_alive=default_pid_alive, attempts=3):
    """Hold the watch lock for the duration of the block, or raise LockBusy.
    A lock whose pid is dead (or that holds no readable pid) is taken over by
    renaming it aside - only one taker can win that rename - then acquiring
    again. Release removes the lock only while it still holds OUR pid."""
    lock = Path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    me = os.getpid() if pid is None else int(pid)
    for _ in range(max(1, int(attempts))):
        if _try_acquire(lock, me):
            break
        holder = _read_pid(lock)
        if holder is not None and pid_alive(holder):
            raise LockBusy(f"watch lock held by live pid {holder}")
        grave = _side(lock, "stale")
        try:
            lock.rename(grave)
        except OSError:
            continue  # another taker won the rename; try again
        moved = _read_pid(grave)
        if moved != holder and moved is not None and pid_alive(moved):
            # the lock we moved was a live winner's, not the dead one we judged
            with contextlib.suppress(OSError):
                grave.rename(lock)
            if grave.exists():
                _remove_dir(grave)
            raise LockBusy(f"watch lock taken over by live pid {moved}")
        _remove_dir(grave)
    else:
        raise LockBusy("watch lock contended")
    try:
        yield lock
    finally:
        if _read_pid(lock) == me:
            grave = _side(lock, "done")
            try:
                lock.rename(grave)
            except OSError:
                pass
            else:
                _remove_dir(grave)


# ---------------------------------------------------------------- run

def _norm_ids(ids):
    out, seen = [], set()
    for i in ids:
        s = str(i)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _delivered(answer):
    return isinstance(answer, dict) and answer.get("delivered") is True


def _first_line(exc):
    return f"{type(exc).__name__}: {_safe_reason(exc)}"[:200]


def run_source(state, source, fetch, deliver, alert, alert_after=5, describe=None, *,
               partial=False, confirm_arg=False, baseline=True, persist=True):
    """One pass over one source. Returns {"source", "outcome", "new", "detail"};
    outcome is one of OUTCOMES. Never raises for a fetch, deliver or alert
    failure (those are outcomes); state is saved once, after delivery (and at
    each confirm() when confirm_arg). Keyword extensions: see the module doc."""
    rec = state._src(source)
    save = state.save if persist else (lambda: None)
    try:
        ids = _norm_ids(fetch())
    except ANY_FAILURE as exc:  # every fetch failure is rot
        detail = _first_line(exc)
        rec["failures"] = int(rec["failures"]) + 1
        if rec["failures"] >= int(alert_after) and not rec["alerted"]:
            try:
                ok = _delivered(alert(source, rec["failures"], detail))
            except ANY_FAILURE:  # an alert sink never breaks the run
                ok = False
            rec["alerted"] = ok
        save()
        return {"source": source, "outcome": "fetch-failed", "new": [], "detail": detail}
    rec["failures"], rec["alerted"] = 0, False
    if not rec["baselined"]:
        rec["baselined"] = True
        if baseline:
            state._add_seen(source, ids)
            save()
            return {"source": source, "outcome": "baseline", "new": [],
                    "detail": f"baseline {len(ids)} ids"}
    known = set(rec["seen"])
    new = [i for i in ids if i not in known]
    if not new:
        save()
        return {"source": source, "outcome": "nothing-new", "new": [], "detail": ""}
    confirmed = []

    def confirm(ids):
        got = [i for i in _norm_ids(ids) if i in new and i not in confirmed]
        if got:
            confirmed.extend(got)
            state._add_seen(source, got)
            save()
        return got
    try:
        answer = deliver(list(new), confirm) if confirm_arg else deliver(list(new))
        detail = str(answer.get("detail", "")) if isinstance(answer, dict) else ""
    except ANY_FAILURE as exc:  # a failed send is an outcome
        answer, detail = None, _first_line(exc)
    if not _delivered(answer):
        part = []
        if partial and isinstance(answer, dict) and isinstance(answer.get("delivered"), list):
            part = [i for i in _norm_ids(answer["delivered"]) if i in new and i not in confirmed]
            state._add_seen(source, part)
        done = confirmed + part
        save()
        if done:
            return {"source": source, "outcome": "deliver-partial", "new": done,
                    "detail": detail or f"{len(done)} of {len(new)} delivered"}
        return {"source": source, "outcome": "deliver-failed", "new": new,
                "detail": detail or "not delivered"}
    new_rest = [i for i in new if i not in confirmed]
    state._add_seen(source, new_rest)
    save()
    label = ", ".join(describe(i) for i in new) if describe else f"{len(new)} new"
    return {"source": source, "outcome": "delivered", "new": new, "detail": label}
