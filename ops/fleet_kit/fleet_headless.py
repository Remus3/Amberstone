# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit - the ONLY path that starts a headless `claude` in any repo here.

Vendored byte-for-byte into every repo at ops/fleet_kit/ and pinned by
MANIFEST.json. Do NOT edit a vendored copy: report the defect to MAIN, which
ships a new kit version to every repo at once.

What it enforces (FLEET-COMMON item 10):
- the second-account proxy, read from the user variable CLAUDE_HEADLESS_BASE_URL
  (registry first, so deleting the variable stops even a long-lived process),
- fail closed: unset / non-loopback / unpinned / unreachable -> Refused, never a
  fallback; any --fallback-model or auto-fallback flag is refused at the door,
- at most RUNS_CAP runs started per rolling WINDOW_S, counted under a lock; an
  unreadable budget file refuses (fail closed) and is never reset,
- never spawn on this repo's own notes, or on notes marked TERMINAL / no-reply
  (marker LINES and whole name tokens only; ORDER / FIX / RULING never damped),
- lean flags (strict MCP + project settings, or --bare - refused when the caller
  says its floors live in hooks), sonnet unless the work writes code, effort low
  for acknowledgements,
- no visible console window, the claude executable never taken from the working
  directory, and a timeout kills the whole process tree,
- one usage line per run, and the live status file the lane widget reads, never
  left reading "running" after the run ends however it ends.

v4 adds OPTIONAL keyword parameters to spawn() (v3 behaviour when omitted):
cwd, stdin, return_stderr, persist / session_id / resume, model, effort,
setting_sources, floors_in_hooks, pin, log_path (streamed stream-json log),
halt_file; plus write_progress() for ops/loop/control/progress/<task>.json.

v5 adds sibling kit files (this file's API is unchanged by them):
fleet_watch.py (watcher primitive), fleet_secrets.py (secret references) and
tokens.json + tokens.css (shared dashboard design tokens).

v6 adds fleet_lanes.py (per-repo lanes, one worktree each, under the 3-slot
machine governor) and OPTIONAL spawn(governor=...): None (default) takes no
slot, exactly as v5; "queued" or "interactive" holds one governor slot for the
run, waiting in the fair queue (status "backoff" while it waits) and refusing
on governor_timeout. One slot per executor call: never also hold slots.hold()
around a governed spawn. Ruling: inbox acknowledgements stay outside the slots.

v7 adds fleet_checklist.py (FLEET-COMMON item 13, the session checklist) and
an OPTIONAL write_progress(..., checklist=[{id, task, state, eta_s}]) field;
without it the progress file is byte-for-byte the v6 shape.

v8 adds fleet_inbox.py (FLEET-COMMON item 14, inbox cost discipline: triage on
sonnet/low, mechanical acks, an outbound cap, a hop limit, the build-vs-inbox
cost split) and an OPTIONAL spawn(kind=build|inbox|triage). The usage line
gains "kind": the explicit value, else inferred by run_kind() (a channel-note
name is inbox, an empty note unattributed, any other label build).
Kind "inbox" is a run that DOES the work a note orders (an ORDER / FIX /
RULING lane); "triage" is the cheap classification look; "build" is the rest.

v10 (backward compatible; every new parameter is optional):
- a block-quoted line (`> TERMINAL`) is never a marker: quoting a note is not
  marking this one (RSC 1540 gap 1);
- the usage line carries "is_error" and "subtype" from the claude result, and
  spawn's return adds "receipt", the full result event (RSC gap 2, LW 1258 A);
- the run budget lock is an OS byte-range lock on a file that is never
  unlinked, so a dead holder frees it at once (RSC gap 3);
- halt_file halts on ANY entry at the path, a dangling symlink included
  (RSC gap 4);
- a POSIX timeout kills the child's whole process group (RC 1915);
- _run passes a literal creationflags= to Popen (LW 1258 B), and launch() is
  its public name (RC 2220 d);
- spawn(stdin_data=...) keeps the prompt in argv and feeds stdin_data on
  stdin (RC 2220 e); a custom run= that accepts on_start gets it, and the
  usage line records "child_marked" (RSC 0523 item 6);
- an OSError before the run starts is a Refused, never a raw escape;
- _atomic_write retries a briefly locked target and never orphans its tmp
  (RSC 0523 item 2);
- status task names are the MAIN 0915 basic set only (TASKS; CS 1234);
- a command-line entry: `python fleet_headless.py spawn ...` (CS 0224).

v11:
- the command line gains ONE pass-through, `--permission-mode MODE`, its
  value limited to the CLI's own modes (PERMISSION_MODES), mapped to
  extra=("--permission-mode", MODE) and screened by check_door like any
  extra (ruling R2). There is no generic --extra on the command line;
- a governor SlotTimeout is reported as a fixed kit message built from
  numbers, never str(exc) (CS 1623 item 6).

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

KIT_VERSION = 11
VAR = "CLAUDE_HEADLESS_BASE_URL"
RUNS_CAP = 120
WINDOW_S = 86400
STATUS_REL = Path("ops/loop/control/inbox_status.json")
BUDGET_REL = Path("ops/loop/control/headless_budget.json")
USAGE_REL = Path("ops/loop/control/headless_usage.jsonl")
PROGRESS_REL = Path("ops/loop/control/progress")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
PLACEHOLDER_KEY = "fleet-proxy-placeholder"
STRIP_EXACT = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
STRIP_PREFIX = ("CLAUDE_CODE_USE_",)
KEEP_EXACT = {"CLAUDE_CODE_USE_POWERSHELL_TOOL"}
ACK_MARKERS = ("INFORMATION", "ACK", "TERMINAL", "CORRECTION-ACCEPTED",
               "POLL-ANSWER", "RECEIVED", "NO-REPLY", "NOREPLY")
NEVER_DAMP = ("ORDER", "FIX", "RULING")
STATES = ("idle", "running", "limit", "halted", "backoff", "refused")
PROGRESS_STATES = ("running", "done", "failed")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
SOURCES = ("user", "project", "local")
DEFAULT_SOURCES = "project,local"
ARGV_PROMPT_MAX = 30000
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_SENDER = re.compile(r"(?:^|[-_])(?i:from)-([A-Z]+)-")
_TITLE = re.compile(r"^#+\s*(?i:from)\s+([A-Z]+)\b(?:\s*-\s*([A-Z]+))?")
_CLASS = re.compile(r"(?:^|[-_])(?i:from)-[A-Z]+-([A-Za-z]+)")
_MARK = r"(?:TERMINAL|NO[-_ ]?REPLY)"
_MARKER_LINE = re.compile(r"^(?:CLASS\s+)?" + _MARK + r"(?:\s*[-.,:;/]?\s*" + _MARK +
                          r")*\s*[.!]?$")
_MODEL = re.compile(r"^(?:opus|sonnet|haiku|claude-[a-z0-9][a-z0-9.-]*)(?:\[1m\])?$")
_TOKEN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHECK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$")
CHECKLIST_MAX = 20
ATOMIC_TRIES = 8
KINDS = ("build", "inbox", "triage")
# MAIN 0915 section 1: the BASIC status task names, the operator's words.
TASKS = ("Idle", "Checking Inbox", "Waiting for Slot", "Running Session",
         "Delivering Notes", "Committing", "Backing Off", "Halted", "Turn Limit Reached")
REFUSED_TASK = "Idle"  # a refused start runs nothing; state "refused" says why
_NOTE_SENDER = re.compile(r"(?:^|[-_])(?i:from)-[A-Z]+-")
_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone(_dt.timedelta(0)))


class Refused(Exception):
    """A spawn the kit will not start. str() is the logged reason."""


class BudgetUnreadable(Refused):
    """The budget file exists but cannot be read or parsed: fail closed."""


# ---------------------------------------------------------------- proxy URL

def _registry_value():
    """(found, value). found=False only when the user store cannot be opened."""
    try:
        import winreg
    except ImportError:
        return False, None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                value, _ = winreg.QueryValueEx(key, VAR)
                return True, str(value)
            except FileNotFoundError:
                return True, None
    except OSError:
        return False, None


def base_url(registry=_registry_value, environ=None):
    """The pinned proxy URL, or None. A readable registry WITHOUT the value wins
    over a stale inherited environment copy: that is the fleet kill switch."""
    found, value = registry()
    if found:
        return value or None
    env = os.environ if environ is None else environ
    return env.get(VAR) or None


def _parse_pin(pin):
    if isinstance(pin, (tuple, list)) and len(pin) == 2:
        host, port = str(pin[0]), pin[1]
    else:
        host, _, port = str(pin).rpartition(":")
    host = host.strip("[]")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise Refused("proxy pin has no valid port") from None
    if host not in LOOPBACK or not 0 < port < 65536:
        raise Refused("proxy pin is not a loopback host:port")
    return host, port


def check_url(url, pin=None):
    """Raise Refused unless url is plain http to a loopback host:port - and,
    when pin ("host:port" or (host, port)) is given, to exactly that one."""
    if not url:
        raise Refused(VAR + " is unset")
    if any(c in url for c in "@\\ \t\r\n"):
        raise Refused("proxy URL has a forbidden character")
    parts = urlsplit(url)
    if parts.scheme != "http":
        raise Refused("proxy URL is not plain http")
    if parts.hostname not in LOOPBACK:
        raise Refused("proxy URL host is not loopback")
    try:
        port = parts.port
    except ValueError:
        raise Refused("proxy URL port is invalid") from None
    if not port:
        raise Refused("proxy URL has no port")
    if pin is not None and (parts.hostname, port) != _parse_pin(pin):
        raise Refused("proxy URL is not the pinned host:port")
    return parts.hostname, port


def probe(host, port, timeout=2.0, connect=socket.create_connection):
    try:
        connect((host, port), timeout=timeout).close()
    except OSError as exc:
        raise Refused(f"proxy unreachable: {exc.__class__.__name__}") from None


def child_env(url, bare=False, parent=None):
    """The child's environment: provider switches and credentials removed, the
    proxy URL set. CLAUDE_CODE_USE_POWERSHELL_TOOL is a tool switch, not a
    provider switch, and is kept. --bare reads no OAuth, so it gets a
    placeholder key that the proxy replaces with the pinned account."""
    env = dict(os.environ if parent is None else parent)
    for k in list(env):
        if k in KEEP_EXACT:
            continue
        if k in STRIP_EXACT or k.startswith(STRIP_PREFIX) or (
                k.startswith("ANTHROPIC_") and k.endswith("BASE_URL")):
            del env[k]
    env["ANTHROPIC_BASE_URL"] = url
    # v10: SUBAGENT-FIRST guards an operator's interactive main thread; a
    # headless run has no agent_id and no operator, so it is always exempt.
    env["FLEET_SUBAGENT_FIRST"] = "off"
    if bare:
        env["ANTHROPIC_API_KEY"] = PLACEHOLDER_KEY
    return env


# ---------------------------------------------------------------- note rules

def _base(name):
    return Path(str(name or "")).name


def _tokens(text):
    return [t for t in re.split(r"[^A-Z0-9]+", text.upper()) if t]


def _has_marker(tokens, marker):
    joined = "-" + "-".join(tokens) + "-"
    return "-" + marker + "-" in joined


def _title(head):
    for line in (head or "").splitlines():
        if line.strip():
            return _TITLE.match(line.strip())
    return None


def note_sender(name, head=""):
    """Sender code from the name (`...-from-XX-...` or `from-XX-...`), else from
    the title line (`# From XX - ...`), else None."""
    m = _SENDER.search(_base(name))
    if m:
        return m.group(1)
    t = _title(head)
    return t.group(1) if t else None


def note_class(name, head=""):
    """The word after the sender (ORDER, FIX, ANSWER, ...), upper-cased, or None."""
    m = _CLASS.search(_base(name))
    if m:
        return m.group(1).upper()
    t = _title(head)
    return t.group(2).upper() if t and t.group(2) else None


def _never_damped(name, head):
    cls = note_class(name, head)
    t = _title(head)
    title_cls = t.group(2).upper() if t and t.group(2) else None
    return cls in NEVER_DAMP or title_cls in NEVER_DAMP


def _marked_terminal(name, head):
    tokens = _tokens(_base(name))
    if "TERMINAL" in tokens or "NOREPLY" in tokens or _has_marker(tokens, "NO-REPLY"):
        return True
    for line in (head or "").splitlines():
        if line.lstrip().startswith(">"):
            continue  # a quoted marker belongs to the quoted note, not this one
        text = line.strip().lstrip("#*- \t").rstrip("* \t").upper()
        if text and _MARKER_LINE.match(text):
            return True
    return False


def should_skip(name, own_code, head=""):
    """'self', 'terminal' or None. head = the note's first few hundred chars.
    Terminal means a whole TERMINAL / NOREPLY / NO-REPLY token in the name or a
    line that is only such a marker; a body sentence that mentions the rule is
    not a marker. ORDER, FIX and RULING notes are never damped."""
    if note_sender(name, head) == own_code:
        return "self"
    if _never_damped(name, head):
        return None
    return "terminal" if _marked_terminal(name, head) else None


def pick_effort(name, effort=None):
    """Explicit effort (low|medium|high) wins; else low for acknowledgement
    tokens (whole tokens only - TRACK and BACKOFF are not ACK), medium otherwise,
    and never low for ORDER / FIX / RULING."""
    if effort is not None:
        if effort not in EFFORTS:
            raise Refused(f"effort {effort!r} not in {EFFORTS}")
        return effort
    if note_class(name) in NEVER_DAMP:
        return "medium"
    tokens = _tokens(_base(name))
    return "low" if any(_has_marker(tokens, m) for m in ACK_MARKERS) else "medium"


def pick_model(writes_code, model=None):
    """Explicit model alias or exact id wins; else opus for code, sonnet otherwise."""
    if model is not None:
        if not isinstance(model, str) or not _MODEL.match(model):
            raise Refused(f"model {model!r} is not an alias or a claude-* id")
        return model
    return "opus" if writes_code else "sonnet"


# ---------------------------------------------------------------- argv

def _norm(path):
    return os.path.normcase(os.path.realpath(path))


def _find_on_path(name, environ=None, cwd=None):
    """Like shutil.which, but never answers from the working directory: empty,
    relative and cwd-equal PATH entries are skipped."""
    env = os.environ if environ is None else environ
    here = _norm(cwd or Path.cwd())
    exts = [""]
    if sys.platform == "win32":
        exts = [e for e in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for entry in env.get("PATH", "").split(os.pathsep):
        d = entry.strip().strip('"')
        if not d or not Path(d).is_absolute() or _norm(d) == here:
            continue
        for ext in exts:
            p = Path(d) / (name + ext)
            if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
                return str(p)
    return None


def claude_exe(which=None, environ=None, cwd=None):
    """The real claude executable, never one in the working directory. The npm
    shim claude.CMD would run under cmd.exe; prefer the binary it wraps so no
    console host is involved."""
    path = which("claude") if which else _find_on_path("claude", environ, cwd)
    if not path:
        raise Refused("claude not found on PATH (working directory excluded)")
    if not Path(path).is_absolute() or _norm(Path(path).parent) == _norm(cwd or Path.cwd()):
        raise Refused("claude resolved from the working directory")
    if path.lower().endswith(".cmd"):
        real = (Path(path).parent / "node_modules" / "@anthropic-ai" /
                "claude-code" / "bin" / "claude.exe")
        if real.exists():
            return str(real)
    return path


def _check_sources(sources):
    parts = [s.strip() for s in str(sources or "").split(",")]
    if not parts or any(p not in SOURCES for p in parts) or len(set(parts)) != len(parts):
        raise Refused(f"setting sources {sources!r} not a subset of {SOURCES}")
    return ",".join(parts)


def _flag(arg):
    return str(arg).split("=", 1)[0].lower()


def build_argv(exe, prompt, model, effort, bare=False, rules_file=None,
               extra=(), stdin=False, persist=False, setting_sources=DEFAULT_SOURCES,
               output_format="json", session_id=None, resume=None):
    argv = [exe, "-p"]
    if not stdin:
        argv.append(prompt)
    argv += ["--output-format", output_format]
    if output_format == "stream-json":
        argv.append("--verbose")
    resuming = any(_flag(a) in ("--session-id", "--resume", "--continue") for a in extra)
    if not (persist or session_id or resume or resuming):
        argv.append("--no-session-persistence")
    for flag, value in (("--session-id", session_id), ("--resume", resume)):
        if value is not None:
            if not _TOKEN_ID.match(str(value)):
                raise Refused(f"{flag} value is not a plain id")
            argv += [flag, str(value)]
    argv += ["--model", model, "--effort", effort]
    if bare:
        argv.append("--bare")
        if rules_file:
            argv += ["--append-system-prompt-file", str(rules_file)]
    else:
        argv += ["--strict-mcp-config", "--setting-sources", _check_sources(setting_sources)]
    return argv + list(extra)


def check_door(bare=False, extra=(), floors_in_hooks=False):
    """Refuse what must never reach the CLI: any fallback flag, ever; --bare
    smuggled through extra (use bare=); --bare when floors live in hooks."""
    flags = [_flag(a) for a in extra]
    if any("fallback" in f for f in flags):
        raise Refused("fallback flags are refused - fail closed, no fallback ever")
    if "--bare" in flags:
        raise Refused("--bare goes through bare=, not extra")
    if bare and floors_in_hooks:
        raise Refused("--bare refused: this tree's floors live in hooks, which --bare skips")


# ---------------------------------------------------------------- budget

def _try_os_lock(fd):
    """Non-blocking exclusive lock on byte 0 of fd. True = held."""
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _os_unlock(fd):
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


class RunBudget:
    """Runs started per rolling window, persisted as epoch seconds. A missing
    file is zero runs; a file that exists but cannot be read or parsed REFUSES
    every start until a person repairs or removes it (fail closed). Starts are
    counted under an exclusive lock file next to the budget file."""

    def __init__(self, path, cap=RUNS_CAP, window=WINDOW_S, clock=time.time,
                 lock_wait=10.0, lock_stale=120.0):
        self.path, self.cap, self.window, self.clock = Path(path), cap, window, clock
        self.lock_wait, self.lock_stale = lock_wait, lock_stale

    def _load(self):
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise BudgetUnreadable(f"budget file unreadable: {exc.__class__.__name__}") from None
        try:
            starts = json.loads(text)["starts"]
        except (ValueError, KeyError, TypeError):
            raise BudgetUnreadable("budget file corrupt - repair or remove it") from None
        if not isinstance(starts, list):
            raise BudgetUnreadable("budget file corrupt - repair or remove it")
        floor = self.clock() - self.window
        return sorted(s for s in starts if isinstance(s, (int, float))
                      and not isinstance(s, bool) and s > floor)

    def readable(self):
        try:
            self._load()
        except BudgetUnreadable:
            return False
        return True

    def used(self):
        try:
            return len(self._load())
        except BudgetUnreadable:
            return self.cap

    def can_start(self):
        try:
            return len(self._load()) < self.cap
        except BudgetUnreadable:
            return False

    def frees_at(self):
        """Epoch when the count next drops, or None when nothing is counted."""
        try:
            starts = self._load()
        except BudgetUnreadable:
            return None
        return starts[0] + self.window if starts else None

    @contextlib.contextmanager
    def _lock(self):
        """v10: an OS byte-range lock on <budget>.lock, a file that is never
        unlinked. The OS frees the lock when its holder's handle closes, so a
        dead holder frees it at once; no stale timer, no unlink race (RSC 1540
        gap 3). lock_stale is kept for the signature and is unused."""
        lock = self.path.with_name(self.path.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_wait
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise Refused(f"budget lock unopenable: {exc.__class__.__name__}") from None
        try:
            while not _try_os_lock(fd):
                if time.monotonic() >= deadline:
                    raise Refused("budget lock busy")
                time.sleep(0.05)
            try:
                yield
            finally:
                _os_unlock(fd)
        finally:
            os.close(fd)

    def start(self):
        """Count one start under the lock. True = counted; False = cap reached.
        Raises Refused (BudgetUnreadable, or lock busy) - fail closed."""
        with self._lock():
            starts = self._load()
            if len(starts) >= self.cap:
                return False
            _atomic_write(self.path, json.dumps({"starts": [*starts, self.clock()]}))
            return True

    def try_start(self):
        try:
            return self.start()
        except Refused:
            return False

    def record(self):
        """v3 name: count a start unconditionally (still under the lock, and
        still refusing on an unreadable file)."""
        with self._lock():
            starts = [*self._load(), self.clock()]
            _atomic_write(self.path, json.dumps({"starts": starts}))


# ---------------------------------------------------------------- status/usage

def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="ascii", newline="\n")
        for attempt in range(ATOMIC_TRIES):
            try:
                tmp.replace(path)
                return
            except PermissionError:  # Windows: a reader holds the target briefly
                if attempt == ATOMIC_TRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _iso(epoch):
    if not epoch or epoch <= 0:
        return None
    try:
        return _dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return (_EPOCH + _dt.timedelta(seconds=epoch)).isoformat(timespec="seconds")


def write_status(root, code, state, task, task_started, budget, task_eta_s=None,
                 next_tick=None, clock=time.time):
    """Schema 1 of ops/loop/control/inbox_status.json (MAIN 0915 section 1).
    state is one of STATES."""
    doc = {
        "schema": 1, "kit": KIT_VERSION, "code": code,
        "updated": _iso(clock()), "state": state, "task": task[:24],
        "task_started": _iso(task_started), "task_eta_s": task_eta_s,
        "next_tick": _iso(next_tick), "runs_in_window": budget.used(),
        "runs_cap": budget.cap, "window_s": budget.window,
        "cap_frees_at": _iso(budget.frees_at()),
    }
    _atomic_write(Path(root) / STATUS_REL, json.dumps(doc, indent=1))
    return doc


def _status_quietly(root, code, state, task, budget, started=None):
    with contextlib.suppress(OSError):
        write_status(root, code, state, task, started, budget)


def _checklist_rows(checklist):
    """FLEET-COMMON item 13 d: the remaining tasks as [{id, task, state, eta_s}]."""
    if not isinstance(checklist, (list, tuple)):
        raise ValueError("checklist must be a list of {id, task, state, eta_s}")
    rows = []
    for r in checklist[:CHECKLIST_MAX]:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) \
                or not _CHECK_ID.match(r["id"]) or not isinstance(r.get("task"), str) \
                or not r["task"].strip():
            raise ValueError(f"bad checklist row {r!r}")
        state, eta = r.get("state"), r.get("eta_s")
        if state is not None and not isinstance(state, str):
            raise ValueError(f"bad checklist state {state!r}")
        rows.append({"id": r["id"], "task": " ".join(r["task"].split())[:120],
                     "state": None if state is None else " ".join(state.split())[:40],
                     "eta_s": None if eta is None else max(0, int(eta))})
    return rows


def write_progress(root, task, pct, step, eta_s, status, clock=time.time, checklist=None):
    """FLEET-COMMON item 12: ops/loop/control/progress/<task>.json with
    {task, pct, step, eta_s, status: running|done|failed, updated}, plus
    "checklist" (item 13 d, remaining tasks) when one is passed."""
    if not isinstance(task, str) or not _TASK.match(task):
        raise ValueError(f"task name {task!r} must be a plain file stem")
    if status not in PROGRESS_STATES:
        raise ValueError(f"status {status!r} not in {PROGRESS_STATES}")
    doc = {"task": task, "pct": max(0, min(100, int(pct))), "step": str(step)[:200],
           "eta_s": None if eta_s is None else max(0, int(eta_s)),
           "status": status, "updated": _iso(clock())}
    if checklist is not None:
        doc["checklist"] = _checklist_rows(checklist)
    _atomic_write(Path(root) / PROGRESS_REL / (task + ".json"), json.dumps(doc))
    return doc


def run_kind(note, kind=None):
    """build | inbox | triage as given; else inbox for a channel-note name,
    unattributed for an empty note, build for any other label (v8)."""
    if kind is not None:
        if kind not in KINDS:
            raise Refused(f"kind {kind!r} not in {KINDS}")
        return kind
    base = _base(note)
    if not base:
        return "unattributed"
    return "inbox" if _NOTE_SENDER.search(base) else "build"


def usage_line(result, code, note, model, effort, bare, rc, duration_s, error=None,
               kind=None):
    r = result if isinstance(result, dict) else {}
    u = r.get("usage") if isinstance(r.get("usage"), dict) else {}
    return {
        "ts": _iso(time.time()), "kit": KIT_VERSION, "code": code, "note": note,
        "model": model, "effort": effort, "bare": bare, "rc": rc,
        "duration_s": round(duration_s, 1),
        "input_tokens": u.get("input_tokens"),
        "cache_creation": u.get("cache_creation_input_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cost_usd": r.get("total_cost_usd"),
        "num_turns": r.get("num_turns"),
        "is_error": r.get("is_error") if isinstance(r.get("is_error"), bool) else None,
        "subtype": r.get("subtype") if isinstance(r.get("subtype"), str) else None,
        "error": error,
        "kind": run_kind(note, kind),
    }


# ---------------------------------------------------------------- provenance

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(top, *args, git=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    exe = git or _find_on_path("git")
    if not exe:
        raise OSError("git not found on PATH (working directory excluded)")
    return subprocess.run([exe, "--no-replace-objects", "-C", str(top), *args],
                          capture_output=True, check=True, timeout=60, env=env,
                          creationflags=_NO_WINDOW).stdout


def verify_main(note_path, main_outbox, rel=None, git=None):
    """True only when MAIN's COMMITTED copy of this note is byte-identical:
    the HEAD blob at <outbox>/<rel> (replace refs ignored) hashes to the note's
    SHA-256 and MAIN's index names the same object. A working-tree copy alone
    proves nothing (assume-unchanged, skip-worktree, restored mtimes). rel is
    the path inside the outbox (default: the note's file name; a bundle file is
    "<bundle dir>/<file>"). Any git error = False (fail closed)."""
    note = Path(note_path)
    rel = Path(rel) if rel else Path(note.name)
    if not note.is_file() or rel.is_absolute() or ".." in rel.parts:
        return False
    try:
        top = Path(_git(main_outbox, "rev-parse", "--show-toplevel", git=git)
                   .decode("utf-8").strip())
        path = (Path(main_outbox).resolve() / rel).relative_to(top.resolve()).as_posix()
        blob = _git(top, "cat-file", "blob", "HEAD:" + path, git=git)
        head_oid = _git(top, "rev-parse", "--verify", "HEAD:" + path, git=git).split()
        staged = _git(top, "ls-files", "-s", "--", path, git=git).split()
        want = sha256_file(note)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    if len(head_oid) != 1 or len(staged) < 2 or staged[1] != head_oid[0]:
        return False
    return hashlib.sha256(blob).hexdigest() == want


# ---------------------------------------------------------------- conformance

KIT_REL = Path("ops/fleet_kit")
BEGIN, END = "<!-- FLEET-COMMON BEGIN -->\n", "<!-- FLEET-COMMON END -->"


def conformance(root):
    """Problems with this repo's copy of the kit; [] = conforms. Every repo runs
    `assert conformance(repo_root) == []` in its own suite, so a local edit to a
    kit file, or to the FLEET-COMMON block in CLAUDE.md, fails that repo's CI.
    (Editing a file AND the manifest together passes here; MAIN's drift sweep
    compares the manifest against MAIN's and catches that.)"""
    root = Path(root)
    kit = root / KIT_REL
    try:
        man = json.loads((kit / "MANIFEST.json").read_text(encoding="ascii"))
    except (OSError, ValueError):
        return ["kit manifest missing or unreadable"]
    problems = []
    if man.get("version") != KIT_VERSION:
        problems.append(f"manifest v{man.get('version')} != kit v{KIT_VERSION}")
    for name, want in sorted(man.get("files", {}).items()):
        f = kit / name
        if not f.is_file() or sha256_file(f) != want:
            problems.append(f"kit file missing or edited: {name}")
    try:
        text = (root / "CLAUDE.md").read_bytes().decode("ascii")
    except (OSError, UnicodeDecodeError):
        return [*problems, "CLAUDE.md missing or not ASCII"]
    i, j = text.find(BEGIN), text.find(END)
    if "\r\n" in text:
        problems.append("CLAUDE.md is CRLF; the fleet rule is LF")
    elif i < 0 or j < i:
        problems.append("CLAUDE.md lacks the FLEET-COMMON markers")
    elif hashlib.sha256(text[i + len(BEGIN):j].encode("ascii")).hexdigest() != \
            man.get("common_block_sha256"):
        problems.append("CLAUDE.md FLEET-COMMON block edited")
    return problems


# ---------------------------------------------------------------- spawn

def _kill_tree(proc, grace=5.0):
    """Kill the child and everything it started. Windows: taskkill /T /F.
    POSIX (v10, RC 1915): the child leads its own session (launch() starts it
    with start_new_session=True), so SIGTERM its process group, wait `grace`
    seconds, then SIGKILL the group. proc.kill() stays the last resort."""
    if sys.platform == "win32":
        sysroot = os.environ.get("SYSTEMROOT")
        tk = str(Path(sysroot) / "System32" / "taskkill.exe") if sysroot else \
            _find_on_path("taskkill")
        if tk:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run([tk, "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                               timeout=30, creationflags=_NO_WINDOW)
    else:
        import signal
        with contextlib.suppress(OSError):
            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid:  # only a group the child leads, never ours
                with contextlib.suppress(OSError):
                    os.killpg(pgid, signal.SIGTERM)
                with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                    proc.wait(timeout=grace)
                with contextlib.suppress(OSError):
                    os.killpg(pgid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _run(argv, input=None, timeout=None, capture_output=False, stdin=None, on_start=None,
         creationflags=_NO_WINDOW, **kw):
    """subprocess.run, except stdin defaults to DEVNULL, no console window opens
    (a literal creationflags= at Popen, v10) and a timeout kills the whole
    process tree (claude's own children included) before re-raising.
    on_start(pid) is called once the child exists (v6: the governor slot)."""
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        stdin = subprocess.PIPE
    elif stdin is None:
        stdin = subprocess.DEVNULL
    if sys.platform != "win32":
        kw.setdefault("start_new_session", True)
    with subprocess.Popen(argv, stdin=stdin, creationflags=creationflags, **kw) as proc:
        if on_start is not None:
            with contextlib.suppress(Exception):
                on_start(proc.pid)
        try:
            out, err = proc.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
                proc.communicate(timeout=30)
            raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


launch = _run  # v10 public name (RC 2220 d); same object, same behaviour


def _accepts_on_start(fn):
    import inspect
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "on_start" or p.kind is p.VAR_KEYWORD for p in params)


def _json_or_none(text):
    try:
        return json.loads(text) if text else None
    except (ValueError, TypeError):
        return None


def _result_from_log(log_path):
    """The last {"type": "result"} event of a stream-json log, or None."""
    found = None
    with contextlib.suppress(OSError), Path(log_path).open(encoding="utf-8",
                                                          errors="replace") as fh:
        for line in fh:
            ev = _json_or_none(line.strip())
            if isinstance(ev, dict) and ev.get("type") == "result":
                found = ev
    return found


def _lanes():
    """The sibling kit module fleet_lanes.py, loaded by path (ops/fleet_kit is
    not a package in every tree)."""
    name = f"fleet_kit_lanes_v{KIT_VERSION}"
    if name in sys.modules:
        return sys.modules[name]
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("fleet_lanes.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _governor(root, code, governor, governor_timeout, governor_root, budget, note,
              since=None):
    """The slot context for one run: a no-op when governor is None."""
    if governor is None:
        return contextlib.nullcontext(None)
    lanes = _lanes()
    if governor not in lanes.PRIORITIES:
        raise Refused(f"governor {governor!r} not None or one of {lanes.PRIORITIES}")
    return lanes.governor_slot(
        code, note or "spawn", governor, governor_root, timeout=governor_timeout,
        since=since,
        on_wait=lambda: _status_quietly(root, code, "backoff", "Waiting for Slot", budget))


def _finish(root, code, budget, line):
    log = Path(root) / USAGE_REL
    with contextlib.suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="ascii", newline="\n") as fh:
            fh.write(json.dumps(line) + "\n")
    _status_quietly(root, code, "idle", "Idle", budget, time.time())


def _secs(value):
    """A timeout rendered from numbers only for a Refused message; anything
    that is not a number reads 'the default wait'."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "the default wait"
    return f"{value:g}s"


def spawn(root, code, prompt, note="", writes_code=False, bare=False,
          rules_file=None, timeout=3600, extra=(), run=None,
          url_source=base_url, connect=socket.create_connection,
          exe_source=claude_exe, cwd=None, stdin=False, return_stderr=False,
          persist=False, session_id=None, resume=None, model=None, effort=None,
          setting_sources=DEFAULT_SOURCES, floors_in_hooks=False, pin=None,
          log_path=None, halt_file=None, governor=None, governor_timeout=None,
          governor_root=None, governor_since=None, kind=None, stdin_data=None):
    """Start ONE headless run and wait for it. Returns the usage line (dict)
    plus "result" (and "stderr" when return_stderr). Raises Refused, before
    anything starts, when the fleet rules forbid it; the status file then reads
    refused / halted / limit. A timeout returns a line with error "timeout" and
    rc None after the process tree is killed. Budget, status and usage files
    live under root; the child runs in cwd (default root). governor="queued" or
    "interactive" holds one machine-wide slot for the run (v6); a slot not won
    within governor_timeout seconds raises Refused and nothing starts; a caller
    that retries passes governor_since (its first ask) so it keeps its age. A
    lane run inside fleet_lanes.run_lane takes its ONE slot here, nowhere else.
    kind (v8) labels the run build / inbox / triage in the usage line.
    stdin_data (v10) keeps the prompt in argv and feeds this text on stdin
    (it cannot be combined with stdin=True). An OSError before the run starts
    (unreadable registry, unwritable status dir, ...) is raised as Refused."""
    root = Path(root)
    budget = RunBudget(root / BUDGET_REL)
    run = _run if run is None else run
    if halt_file and os.path.lexists(halt_file):  # any entry halts, dangling links too
        _status_quietly(root, code, "halted", "Halted", budget)
        raise Refused("halt file present")
    try:
        check_door(bare, extra, floors_in_hooks)
        run_kind(note, kind)  # an unknown kind refuses before anything starts
        model, effort = pick_model(writes_code, model), pick_effort(note, effort)
        if stdin and stdin_data is not None:
            raise Refused("stdin=True and stdin_data both feed stdin - pick one")
        if not stdin and len(prompt) > ARGV_PROMPT_MAX:
            raise Refused(f"prompt over {ARGV_PROMPT_MAX} chars in argv - pass stdin=True")
        url = url_source()
        host, port = check_url(url, pin)
        probe(host, port, connect=connect)
        argv = build_argv(exe_source(), prompt, model, effort, bare, rules_file, extra,
                          stdin=stdin, persist=persist, setting_sources=setting_sources,
                          output_format="stream-json" if log_path else "json",
                          session_id=session_id, resume=resume)
        slot_cm = _governor(root, code, governor, governor_timeout, governor_root,
                            budget, note, governor_since)
    except Refused:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise
    except OSError as exc:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise Refused(f"start failed: {exc.__class__.__name__}") from None
    with contextlib.ExitStack() as slot_stack:
        try:
            slot = slot_stack.enter_context(slot_cm)
        except _lanes().SlotTimeout:
            _status_quietly(root, code, "backoff", "Backing Off", budget)
            raise Refused(f"no governor slot within {_secs(governor_timeout)}") from None
        return _spawn_slotted(root, code, prompt, note, bare, budget, run, url, argv,
                              model, effort, cwd, stdin, timeout, log_path,
                              return_stderr, slot, kind, stdin_data)


def _spawn_slotted(root, code, prompt, note, bare, budget, run, url, argv, model,
                   effort, cwd, stdin, timeout, log_path, return_stderr, slot,
                   kind=None, stdin_data=None):
    """The v5 run body, entered only once a governor slot (if any) is held."""
    try:
        counted = budget.start()
    except Refused:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise
    except OSError as exc:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise Refused(f"budget write failed: {exc.__class__.__name__}") from None
    if not counted:
        _status_quietly(root, code, "limit", "Turn Limit Reached", budget)
        raise Refused(f"run budget exhausted ({budget.used()}/{budget.cap})")
    started = time.time()
    _status_quietly(root, code, "running", "Running Session", budget, started)
    kw = {"cwd": str(Path(cwd) if cwd else root), "env": child_env(url, bare),
          "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout,
          "creationflags": _NO_WINDOW}
    if stdin:
        kw["input"] = prompt
    elif stdin_data is not None:
        kw["input"] = stdin_data
    marked = {"ok": None}
    if slot and (run is _run or _accepts_on_start(run)):
        marked["ok"] = False

        def _mark(pid):
            _lanes().mark_child(slot, pid)
            marked["ok"] = True
        kw["on_start"] = _mark
    proc, error = None, None
    try:
        with contextlib.ExitStack() as stack:
            if log_path:
                Path(log_path).parent.mkdir(parents=True, exist_ok=True)
                kw["stdout"] = stack.enter_context(
                    Path(log_path).open("w", encoding="utf-8", newline="\n"))
                kw["stderr"] = subprocess.PIPE
            else:
                kw["capture_output"] = True
            proc = run(argv, **kw)
    except subprocess.TimeoutExpired:
        error = "timeout"
    except BaseException as exc:
        _finish(root, code, budget, usage_line(None, code, note, model, effort, bare, None,
                                               time.time() - started, type(exc).__name__,
                                               kind))
        raise
    if log_path:
        result = _result_from_log(log_path)
    else:
        result = _json_or_none(getattr(proc, "stdout", None))
    rc = getattr(proc, "returncode", None) if proc is not None else None
    line = usage_line(result, code, note, model, effort, bare, rc,
                      time.time() - started, error, kind)
    line["governor_slot"] = Path(slot).name if slot else None
    line["child_marked"] = marked["ok"]
    _finish(root, code, budget, line)
    line["result"] = result.get("result") if isinstance(result, dict) else None
    line["receipt"] = result if isinstance(result, dict) else None
    if return_stderr:
        line["stderr"] = getattr(proc, "stderr", None) if proc is not None else None
    return line


# ---------------------------------------------------------------- CLI (v10)

CLI_OK, CLI_USAGE, CLI_REFUSED, CLI_TIMEOUT = 0, 2, 3, 4
PERMISSION_MODES = ("acceptEdits", "bypassPermissions", "default", "dontAsk", "plan")


def main(argv=None, spawn_fn=None, stdin=None, stdout=None):
    """`python fleet_headless.py spawn --root R --code C --note N [options]`
    for callers that are not Python (CS 0224). v11: --permission-mode MODE
    (one of PERMISSION_MODES) is the only pass-through flag. The prompt comes from
    --prompt-file, else stdin. Prints the usage line as one JSON line. Exit
    0 ran, 2 bad arguments, 3 Refused, 4 timeout. Every fleet rule applies
    exactly as for spawn(); no flag or variable bypasses the proxy or the door."""
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_headless.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("spawn")
    sp.add_argument("--root", required=True)
    sp.add_argument("--code", required=True)
    sp.add_argument("--note", required=True)
    sp.add_argument("--kind", choices=KINDS)
    sp.add_argument("--effort", choices=EFFORTS)
    sp.add_argument("--model")
    sp.add_argument("--writes-code", action="store_true")
    sp.add_argument("--timeout", type=int, default=3600)
    sp.add_argument("--cwd")
    sp.add_argument("--floors-in-hooks", action="store_true")
    sp.add_argument("--prompt-file")
    sp.add_argument("--permission-mode", choices=PERMISSION_MODES)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return CLI_USAGE
    out = stdout or sys.stdout
    if not args.note.strip():
        print(json.dumps({"error": "empty --note"}), file=out)
        return CLI_USAGE
    try:
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        else:
            prompt = (stdin or sys.stdin).read()
    except (OSError, UnicodeDecodeError) as exc:
        print(json.dumps({"error": f"prompt unreadable: {exc.__class__.__name__}"}), file=out)
        return CLI_USAGE
    if not prompt.strip():
        print(json.dumps({"error": "empty prompt"}), file=out)
        return CLI_USAGE
    try:
        line = (spawn_fn or spawn)(
            args.root, args.code, prompt, note=args.note, writes_code=args.writes_code,
            timeout=args.timeout, cwd=args.cwd, stdin=len(prompt) > ARGV_PROMPT_MAX,
            model=args.model, effort=args.effort, floors_in_hooks=args.floors_in_hooks,
            kind=args.kind,
            extra=("--permission-mode", args.permission_mode) if args.permission_mode else ())
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}), file=out)
        return CLI_REFUSED
    print(json.dumps(line), file=out)
    return CLI_TIMEOUT if line.get("error") == "timeout" else CLI_OK


if __name__ == "__main__":
    sys.exit(main())
