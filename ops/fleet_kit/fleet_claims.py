# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v14 - RACE GUARDS: the per-tree file-claim registry and its hooks
(FLEET-COMMON item 16).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: agents running at the same time in one tree had no per-file ownership -
"disjoint file lists" was a prompt convention only - so two agents could edit
one file, and one agent's `git add -A` could sweep up another's half-made edit.

    python fleet_claims.py hook            PreToolUse command hook
    python fleet_claims.py release-hook    SubagentStop command hook
    python fleet_claims.py list [ROOT]     live owners and their paths
    python fleet_claims.py release --owner OWNER [ROOT]

Registry: <main checkout>/ops/loop/control/claims/<owner>.json, one file per
owner, written temp + rename under a short mutex. <main checkout> is the tree's
main working tree even when the file is in a linked worktree (git common dir,
resolved file-only). owner = <session_id>.<agent_id> from the hook input
("main" when the call is in the main thread). An owner is LIVE while its file
was refreshed within TTL_S (env FLEET_CLAIM_TTL_S); every hook call by an owner
refreshes it, a dead owner's file is reaped by the next hook call in that tree,
and SubagentStop releases the finished agent's claims at once.

v14 release and reap (KIT-14: a finished agent's claims lived until the TTL):
  * release-hook takes the agent id from `agent_id`, else from the
    `agent_transcript_path` file name (agent-<id>.jsonl), and releases that
    owner in the project tree, the payload cwd's tree AND every other tree it
    claimed in (a small per-owner index of main checkouts,
    <index dir>/<owner>.txt; index dir = env FLEET_CLAIMS_INDEX, else
    %LOCALAPPDATA%/fleet/claims-index, POSIX ~/.cache/fleet/claims-index;
    written only for a claim outside the project tree);
  * an owner file records the hook's ancestor Claude Code process (pid and
    start time). An owner whose session process is dead or reused is reaped
    at once, not after the TTL; without a recorded process the TTL rules;
  * info runs of pytest (--version, -V, -h/--help, --co/--collect-only,
    --fixtures, --markers) are not whole-suite runs (RC 0001 sec 9a).

Hook decisions (PreToolUse):
  * Edit / Write / NotebookEdit / MultiEdit on a file inside a git tree: the
    file is auto-claimed for the caller; DENY when a different live owner holds
    it. Files outside every git tree, and EXEMPT paths, are never claimed.
  * Bash / PowerShell (best-effort): DENY a redirect, tee, Set-Content /
    Add-Content / Out-File, or `git add` whose target is held by another live
    owner (a directory target or `git add -A` counts every claim under it);
    DENY a bare `git commit` / `git push` not run through fleet_gitlock.py;
    DENY a whole-suite pytest (no test FILE named) not run through
    fleet_suite_gate.py; DENY fleet_gitlock.py / fleet_suite_gate.py `run`
    without `--owner <the caller's own owner id>` (the reason gives it).
    The owner id is ALWAYS `<session_id>.<agent_id>` (`<session_id>.main` in
    the main thread) - the one rule for --owner on both helpers.

v13 shell parsing (KIT-13): segments split on ; & | && || and newlines only
OUTSIDE quotes; heredoc bodies (<<WORD ... WORD) and PowerShell here-strings
are dropped before parsing unless they feed a shell (sh, bash, pwsh, ...);
a segment that runs a read-only search (grep, rg, findstr, Select-String,
git grep, ...) never counts as a suite, commit, push or helper run, so search
TEXT such as "pytest tests/" or "fleet_gitlock.py run" is never matched.
Reasons are one line, name the path relative to its tree, never an account,
email or owner of the other agent.

Mode (first match wins): env FLEET_CLAIMS = off | log | deny, file
<project>/ops/loop/control/claims.mode (first word), default deny. `log` never
denies. Non-allow decisions append one JSONL line to
<project>/ops/loop/control/claims.jsonl. Stdout carries only the JSON decision.
Never fails closed: any exception -> exit 0, no output.

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import contextlib
import fnmatch
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

CLAIMS_REL = Path("ops/loop/control/claims")
MODE_REL = Path("ops/loop/control/claims.mode")
LOG_REL = Path("ops/loop/control/claims.jsonl")
ENV_MODE = "FLEET_CLAIMS"
ENV_TTL = "FLEET_CLAIM_TTL_S"
ENV_OWNER = "FLEET_CLAIM_OWNER"
MODES = ("off", "log", "deny")
TTL_S = 2700.0
MUTEX = ".mutex"
MUTEX_STALE_S = 10.0
MUTEX_WAIT_S = 5.0
EDIT_TOOLS = frozenset(("Edit", "Write", "NotebookEdit", "MultiEdit"))
SHELL_TOOLS = frozenset(("Bash", "PowerShell"))
HOOK_MATCHER = "Edit|Write|NotebookEdit|MultiEdit|Bash|PowerShell"
# Shared targets nobody owns: append-only ledgers, each agent's own progress
# file (one name per writer, ruling 2026-10-08-lane-progress-location), and the
# guards' own state. Globs on the tree-relative posix path, lower case.
EXEMPT = ("*.jsonl", "ops/loop/control/progress/*", "ops/loop/control/claims/*",
          "ops/loop/control/locks/*", "ops/loop/control/claims.mode")
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
WIN = sys.platform == "win32"


# ---------------------------------------------------------------- owners / trees

def owner_id(payload):
    """<session>.<agent|main>; None when the input carries no session id."""
    session = _SAFE.sub("", str(payload.get("session_id") or ""))[:64]
    if not session:
        return None
    agent = _SAFE.sub("", str(payload.get("agent_id") or ""))[:64] or "main"
    return f"{session}.{agent}"


def _gitdir_of(top):
    """(gitdir, main checkout) for a worktree top; None when top has no .git."""
    dotgit = top / ".git"
    if dotgit.is_dir():
        return dotgit, top
    if not dotgit.is_file():
        return None
    try:
        raw = dotgit.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.startswith("gitdir:"):
        return None
    gitdir = Path(raw.split(":", 1)[1].strip())
    gitdir = (gitdir if gitdir.is_absolute() else top / gitdir).resolve()
    main = gitdir.parents[2] if gitdir.parent.name == "worktrees" else top
    return gitdir, main


def tree_of(path):
    """(worktree top, gitdir, main checkout) holding path, or None outside git.
    File-only: walks up from path; never runs git."""
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        p = Path(os.path.abspath(str(p)))
    for top in (p, *p.parents):
        found = _gitdir_of(top)
        if found:
            return top, found[0], found[1]
    return None


def norm(path):
    s = os.path.abspath(str(path)).replace("\\", "/")
    return s.lower() if WIN else s


def rel_in(path, top):
    """path relative to top, posix; the absolute norm when outside."""
    p, t = norm(path), norm(top).rstrip("/") + "/"
    return p[len(t):] if p.startswith(t) else p


def exempt(rel):
    rel = rel.lower()
    return any(fnmatch.fnmatchcase(rel, g) for g in EXEMPT)


def ttl(env=None):
    env = os.environ if env is None else env
    try:
        v = float(env.get(ENV_TTL) or TTL_S)
    except ValueError:
        v = TTL_S
    return v if v > 0 else TTL_S


# ---------------------------------------------------------------- session process (v14)

def _win_procs():
    """{pid: (parent pid, exe name lower)} from a toolhelp snapshot."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return {}
    out = {}
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32First(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            out[int(e.th32ProcessID)] = (int(e.th32ParentProcessID),
                                         e.szExeFile.decode("ascii", "replace").lower())
            ok = k32.Process32Next(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(wintypes.HANDLE(snap))
    return out


def _proc_started(pid):
    if not WIN:
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    try:
        t = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
            return None
        return ((t[0].dwHighDateTime << 32) | t[0].dwLowDateTime) / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(h)


def session_process(pid=None, procs=None, depth=8, started=None):
    """(pid, started) of the nearest ancestor whose image name starts with
    'claude' - the Claude Code process the hook runs under - else None."""
    try:
        procs = procs if procs is not None else (_win_procs() if WIN else {})
    except (OSError, AttributeError, ValueError):
        return None
    started = started or _proc_started
    cur = os.getpid() if pid is None else pid
    for _ in range(depth):
        row = procs.get(cur)
        if not row:
            return None
        parent = row[0]
        prow = procs.get(parent)
        if prow and prow[1].startswith("claude"):
            return parent, started(parent)
        cur = parent
    return None


def session_alive(pid, started=None):
    """True while pid runs (a pid we cannot query counts as alive) and, when
    both start times are known, it is the same process."""
    if not WIN:
        return True
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return k32.GetLastError() != 87
    try:
        code = ctypes.c_ulong()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:
            return False
    finally:
        k32.CloseHandle(h)
    have = _proc_started(pid)
    if started is not None and have is not None:
        try:
            return abs(float(started) - have) <= 1.0
        except (TypeError, ValueError):
            return True
    return True


# ---------------------------------------------------------------- cross-tree index (v14)

def index_dir(env=None):
    env = os.environ if env is None else env
    if env.get("FLEET_CLAIMS_INDEX"):
        return Path(env["FLEET_CLAIMS_INDEX"])
    if env.get("LOCALAPPDATA"):
        return Path(env["LOCALAPPDATA"]) / "fleet" / "claims-index"
    return Path.home() / ".cache" / "fleet" / "claims-index"


def index_add(me, main, env=None):
    """Record that owner me holds claims in the tree whose main checkout is main."""
    with contextlib.suppress(OSError):
        f = index_dir(env) / f"{me}.txt"
        have = f.read_text(encoding="utf-8").splitlines() if f.is_file() else []
        if str(main) not in have:
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(str(main) + "\n")


def index_pop(me, env=None):
    """The main checkouts recorded for owner me; the index entry is removed."""
    f = index_dir(env) / f"{me}.txt"
    try:
        mains = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []
    with contextlib.suppress(OSError):
        f.unlink()
    return mains


# ---------------------------------------------------------------- registry

def claims_dir(main):
    return Path(main) / CLAIMS_REL


def _read(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="ascii"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _write(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(doc, sort_keys=True), encoding="ascii", newline="\n")
        for i in range(20):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


@contextlib.contextmanager
def _mutex(d, clock=time.time, sleep=time.sleep):
    """A short exclusive-create mutex over one registry; a mutex older than
    MUTEX_STALE_S is broken. Gives up after MUTEX_WAIT_S and proceeds."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    m = d / MUTEX
    held = False
    end = clock() + MUTEX_WAIT_S
    while True:
        try:
            fd = os.open(str(m), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            held = True
            break
        except OSError:
            try:
                if clock() - m.stat().st_mtime > MUTEX_STALE_S:
                    m.unlink()
                    continue
            except OSError:
                continue
            if clock() > end:
                break
            sleep(0.02)
    try:
        yield
    finally:
        if held:
            with contextlib.suppress(OSError):
                m.unlink()


def owners(main):
    """{owner: doc} for every readable owner file in the registry."""
    out = {}
    d = claims_dir(main)
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return out
    for f in files:
        doc = _read(f)
        if doc is not None:
            out[f.stem] = doc
    return out


def live(doc, now, ttl_s, alive=None):
    """Live = refreshed within the TTL and, when the doc names its session
    process, that process still runs as the same process (v14)."""
    try:
        fresh = now - float(doc.get("updated", 0)) <= ttl_s
    except (TypeError, ValueError):
        return False
    if not fresh:
        return False
    pid = doc.get("session_pid")
    if pid is None:
        return True
    alive = alive or session_alive
    return alive(pid, doc.get("session_started"))


def reap(main, now=None, ttl_s=None):
    """Delete dead owners' files (ephemeral state). Returns the reaped owners."""
    now = time.time() if now is None else now
    ttl_s = ttl() if ttl_s is None else ttl_s
    gone = []
    for owner, doc in owners(main).items():
        if not live(doc, now, ttl_s):
            with contextlib.suppress(OSError):
                (claims_dir(main) / f"{owner}.json").unlink()
                gone.append(owner)
    return gone


def holders(main, paths, me=None, now=None, ttl_s=None):
    """[(path, age_s)] for each normed path held by a LIVE owner other than me.
    A path that is a directory prefix matches every claim under it."""
    now = time.time() if now is None else now
    ttl_s = ttl() if ttl_s is None else ttl_s
    want = [norm(p) for p in paths]
    hits = []
    for owner, doc in owners(main).items():
        if owner == me or not live(doc, now, ttl_s):
            continue
        claimed = doc.get("paths") if isinstance(doc.get("paths"), dict) else {}
        for c, at in claimed.items():
            for w in want:
                if c == w or c.startswith(w.rstrip("/") + "/"):
                    try:
                        age = max(0.0, now - float(at))
                    except (TypeError, ValueError):
                        age = 0.0
                    hits.append((c, age))
    return hits


def claim(main, me, path, now=None, meta=None):
    now = time.time() if now is None else now
    f = claims_dir(main) / f"{me}.json"
    doc = _read(f) or {"owner": me, "started": now, "paths": {}}
    if not isinstance(doc.get("paths"), dict):
        doc["paths"] = {}
    doc["paths"].setdefault(norm(path), now)
    doc["updated"] = now
    for k, v in (meta or {}).items():
        doc[k] = v
    _write(f, doc)
    return doc


def heartbeat(main, me, now=None):
    f = claims_dir(main) / f"{me}.json"
    doc = _read(f)
    if doc is None:
        return False
    doc["updated"] = time.time() if now is None else now
    _write(f, doc)
    return True


def release(main, me):
    with contextlib.suppress(OSError):
        (claims_dir(main) / f"{me}.json").unlink()
        return True
    return False


def foreign_claims(paths, me=None, now=None, ttl_s=None):
    """[(path, age_s)] over absolute paths in any trees, held by another live
    owner. Used by fleet_gitlock and fleet_suite_gate."""
    by_main = {}
    for p in paths:
        t = tree_of(p)
        if t is None or exempt(rel_in(p, t[0])):
            continue
        by_main.setdefault(str(t[2]), []).append(p)
    hits = []
    for main, ps in by_main.items():
        hits += holders(main, ps, me, now, ttl_s)
    return hits


# ---------------------------------------------------------------- shell parsing

_TARGET = r"""("[^"]+"|'[^']+'|[^\s;&|<>()]+)"""
_REDIR = re.compile(r"(?<![<>&])\d?>>?\s*(?!&)" + _TARGET)
_TEE = re.compile(r"\btee\s+(?:-a\s+|--append\s+)?" + _TARGET)
_PS_WRITE = re.compile(r"\b(?:Set-Content|Add-Content|Out-File)\b\s+"
                       r"(?:-(?:Path|FilePath|LiteralPath)\s+)?" + _TARGET, re.I)
_SINKS = {"/dev/null", "$null", "nul", "null", "/dev/stderr", "/dev/stdout"}
_GITLOCK = "fleet_gitlock.py"
_GATE = "fleet_suite_gate.py"


def _unquote(s):
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def _words(segment):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _git_verb(words):
    """(verb, args, -C dir) for a `git ...` word list, else None."""
    if not words or not re.search(r"(?:^|[/\\])git(?:\.exe)?$", words[0], re.I):
        return None
    i, cdir = 1, None
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            cdir = words[i + 1]
            i += 2
        elif words[i] == "-c" and i + 1 < len(words):
            i += 2
        else:
            i += 1
    if i >= len(words):
        return None
    return words[i], words[i + 1:], cdir


_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_HERESTRING = re.compile(r"@(['\"])[ \t]*\r?\n.*?\r?\n\1@", re.S)
_SHELLS = frozenset(("sh", "bash", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"))
_SEARCH = frozenset(("grep", "egrep", "fgrep", "rg", "ag", "ack", "findstr",
                     "select-string", "sls"))


def _base(word):
    w = re.split(r"[/\\]", word or "")[-1].lower()
    return w[:-4] if w.endswith(".exe") else w


def strip_heredocs(command):
    """The command with heredoc bodies and here-strings removed, except a
    body fed to a shell (that body is code and stays parsed)."""
    text = _HERESTRING.sub("@''@", command or "")
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in _HEREDOC.finditer(line):
            head = line[:m.start()]
            seg = re.split(r"&&|\|\||[;|&]", head)[-1].split()
            if seg and _base(seg[0]) in _SHELLS:
                continue
            tag, dash = m.group(3), m.group(1)
            while i < len(lines):
                body = lines[i]
                i += 1
                if (body.lstrip("\t") if dash else body).rstrip("\r") == tag:
                    break
    return "\n".join(out)


def _split_unquoted(command):
    """Split on ; & | && || and newlines that sit outside quotes."""
    out, cur, q, i, n = [], [], None, 0, len(command)
    while i < n:
        c = command[i]
        if q:
            cur.append(c)
            if c == q:
                q = None
            elif c == "\\" and q == '"' and i + 1 < n:
                cur.append(command[i + 1])
                i += 1
        elif c in "'\"":
            q = c
            cur.append(c)
        elif c in ";&|\n":
            out.append("".join(cur))
            cur = []
            if i + 1 < n and command[i + 1] == c and c in "&|":
                i += 1
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def _segments(command):
    return [s.strip() for s in _split_unquoted(strip_heredocs(command)) if s.strip()]


def read_only_search(words):
    """True when the segment runs a search tool (its text is a pattern)."""
    if not words:
        return False
    b = _base(words[0])
    if b in _SEARCH:
        return True
    g = _git_verb(words)
    return bool(g and g[0] == "grep")


def write_targets(command):
    """Best-effort file targets a shell command writes (redirect, tee, PS)."""
    out = []
    command = strip_heredocs(command)
    for rx in (_REDIR, _TEE, _PS_WRITE):
        for m in rx.finditer(command or ""):
            t = _unquote(m.group(1))
            if t and t.lower() not in _SINKS and not t.startswith(("$", "&")):
                out.append(t)
    return out


def git_add_targets(command):
    """[(cdir, [paths])] for each `git add` in the command; `-A`/`--all`/no
    path means the whole tree ('.')."""
    out = []
    for seg in _segments(command):
        g = _git_verb(_words(seg))
        if not g or g[0] != "add":
            continue
        paths, whole = [], False
        for a in g[1]:
            if a in ("-A", "--all", "-u", "--update"):
                whole = True
            elif a == "--" or a.startswith("-"):
                continue
            else:
                paths.append(a)
        out.append((g[2], paths if paths and not whole else ["."]))
    return out


def bare_git_write(command):
    """'commit' / 'push' when the command runs one NOT through fleet_gitlock."""
    for seg in _segments(command):
        if _GITLOCK in seg:
            continue
        words = _words(seg)
        if read_only_search(words):
            continue
        g = _git_verb(words)
        if g and g[0] in ("commit", "push"):
            return g[0]
    return None


_PYTEST_INFO = frozenset(("--version", "-V", "-h", "--help", "--co", "--collect-only",
                          "--fixtures", "--markers", "--fixtures-per-test"))
_PYTEST_WORD = re.compile(r"(?:^|[/\\])(?:py\.test|pytest)(?:\.exe)?$", re.I)


def _pytest_at(words):
    """Index of the pytest word when the segment RUNS pytest, else None."""
    for k, w in enumerate(words):
        if not _PYTEST_WORD.search(w):
            continue
        if k == 0 or words[k - 1] in ("-m", "run", "exec", "&"):
            return k
    return None


def bare_whole_suite(command):
    """True when a segment runs pytest naming no test FILE, not via the gate."""
    for seg in _segments(command):
        if _GATE in seg:
            continue
        words = _words(seg)
        if read_only_search(words):
            continue
        i = _pytest_at(words)
        if i is None:
            continue
        rest = words[i + 1:]
        if any(w in _PYTEST_INFO for w in rest):
            continue
        named = [w for w in rest if not w.startswith("-") and (".py" in w or "::" in w)]
        if not named and "-k" not in rest:
            return True
    return False


def owner_flag_missing(command, me):
    """The helper name when a gitlock/gate `run` lacks `--owner <me>`."""
    for seg in _segments(command):
        for helper in (_GITLOCK, _GATE):
            if helper not in seg:
                continue
            words = _words(seg)
            if read_only_search(words):
                continue
            at = [j for j, w in enumerate(words[:4])
                  if w.replace("\\", "/").endswith(helper)]
            if at and at[0] + 1 < len(words) and words[at[0] + 1] == "run":
                given = None
                for k, w in enumerate(words):
                    if w == "--":
                        break
                    if w == "--owner" and k + 1 < len(words):
                        given = words[k + 1]
                    elif w.startswith("--owner="):
                        given = w.split("=", 1)[1]
                if me and given != me:
                    return helper
    return None


# ---------------------------------------------------------------- hook

def project_root(payload, env):
    return Path(env.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())


def mode(root, env):
    v = (env.get(ENV_MODE) or "").strip().lower()
    if v in MODES:
        return v
    try:
        words = (root / MODE_REL).read_text(encoding="ascii", errors="replace").split()
    except OSError:
        words = []
    return words[0].lower() if words and words[0].lower() in MODES else "deny"


def _abs(p, cwd):
    p = Path(os.path.expandvars(os.path.expanduser(str(p))))
    return p if p.is_absolute() else Path(cwd) / p


def _held_reason(path, top, age):
    return (f"CLAIMS: {rel_in(path, top)} is held by another live agent "
            f"(claimed {int(age // 60)}m ago); leave it to that agent or wait for it to finish")


def decide_edit(payload, me, now, ttl_s):
    """(decision, reason) for an edit tool; claims the path on allow."""
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = ti.get("file_path") or ti.get("notebook_path")
    if not target or not me:
        return "allow", ""
    path = _abs(target, payload.get("cwd") or os.getcwd())
    t = tree_of(path)
    if t is None or exempt(rel_in(path, t[0])):
        return "allow", ""
    d = claims_dir(t[2])
    with _mutex(d):
        reap(t[2], now, ttl_s)
        hit = holders(t[2], [path], me, now, ttl_s)
        if hit:
            return "deny", _held_reason(hit[0][0], t[0], hit[0][1])
        meta = {"agent_type": payload.get("agent_type") or None}
        if not (claims_dir(t[2]) / f"{me}.json").is_file():
            sp = session_process()
            if sp:
                meta["session_pid"], meta["session_started"] = sp
        claim(t[2], me, path, now, meta)
    proj = tree_of(project_root(payload, os.environ))
    if proj is None or norm(proj[2]) != norm(t[2]):
        index_add(me, t[2])
    return "allow", ""


def decide_shell(payload, me, now, ttl_s):
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    command = str(ti.get("command") or "")
    cwd = payload.get("cwd") or os.getcwd()
    t = tree_of(cwd)
    if t is not None and me:
        heartbeat(t[2], me, now)
    verb = bare_git_write(command)
    if verb:
        return "deny", ("GITLOCK: run `git {}` through fleet_gitlock.py: "
                        "python <kit>/fleet_gitlock.py run --owner {} -- git {} ...".format(verb, me or "<owner>", verb))
    helper = owner_flag_missing(command, me)
    if helper:
        return "deny", ("CLAIMS: pass your own owner id to {}: run --owner {} -- ...".format(helper, me))
    if bare_whole_suite(command):
        return "deny", ("SUITE-GATE: run whole suites through fleet_suite_gate.py: "
                        "python <kit>/fleet_suite_gate.py run --owner %s -- <suite cmd>"
                        % (me or "<owner>"))
    targets = [_abs(p, cwd) for p in write_targets(command)]
    for cdir, paths in git_add_targets(command):
        base = _abs(cdir, cwd) if cdir else Path(cwd)
        for p in paths:
            targets.append(base if p == "." else _abs(p, base))
    for p in targets:
        tt = tree_of(p)
        if tt is None or exempt(rel_in(p, tt[0])):
            continue
        hit = holders(tt[2], [p], me, now, ttl_s)
        if hit:
            return "deny", _held_reason(hit[0][0], tt[0], hit[0][1])
    return "allow", ""


def decide(payload, env=None, now=None):
    env = os.environ if env is None else env
    now = time.time() if now is None else now
    tool = payload.get("tool_name") or ""
    me = owner_id(payload)
    ttl_s = ttl(env)
    if tool in EDIT_TOOLS:
        return decide_edit(payload, me, now, ttl_s)
    if tool in SHELL_TOOLS:
        return decide_shell(payload, me, now, ttl_s)
    return "allow", ""


def deny_output(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def log(root, row):
    try:
        path = root / LOG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="ascii", errors="replace", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    except OSError:
        pass


def run_hook(stdin_text, env=None, now=None):
    """The PreToolUse hook body. Returns stdout text ('' = no decision)."""
    env = os.environ if env is None else env
    payload = json.loads(stdin_text or "{}")
    if not isinstance(payload, dict):
        return ""
    root = project_root(payload, env)
    m = mode(root, env)
    if m == "off":
        return ""
    decision, reason = decide(payload, env, now)
    if decision == "allow":
        return ""
    log(root, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": payload.get("tool_name"),
               "thread": "sub" if payload.get("agent_id") else "main",
               "decision": decision if m == "deny" else "would-deny", "mode": m,
               "reason": reason})
    return json.dumps(deny_output(reason)) if m == "deny" else ""


_AGENT_FILE = re.compile(r"agent-([A-Za-z0-9_-]+)\.jsonl$")


def stop_agent_id(payload):
    """The finished agent's id: agent_id, else from agent_transcript_path."""
    if payload.get("agent_id"):
        return payload["agent_id"]
    m = _AGENT_FILE.search(str(payload.get("agent_transcript_path") or "").replace("\\", "/"))
    return m.group(1) if m else None


def run_release_hook(stdin_text, env=None):
    """SubagentStop: drop the finished agent's claims in the project tree, the
    payload cwd's tree and every tree in its cross-tree index (v14)."""
    env = os.environ if env is None else env
    payload = json.loads(stdin_text or "{}")
    if not isinstance(payload, dict):
        return ""
    agent = stop_agent_id(payload)
    if not agent:
        return ""
    me = owner_id(dict(payload, agent_id=agent))
    if not me:
        return ""
    mains = {norm(m): m for m in index_pop(me, env)}
    for where in (project_root(payload, env), payload.get("cwd")):
        t = tree_of(where) if where else None
        if t is not None:
            mains.setdefault(norm(t[2]), str(t[2]))
    for m in mains.values():
        release(m, me)
    return ""


def _cli(argv):
    if argv[:1] == ["list"]:
        t = tree_of(argv[1] if len(argv) > 1 else os.getcwd())
        if t is None:
            print("not in a git tree")
            return 2
        now, ttl_s = time.time(), ttl()
        for owner, doc in owners(t[2]).items():
            state = "live" if live(doc, now, ttl_s) else "dead"
            paths = doc.get("paths") if isinstance(doc.get("paths"), dict) else {}
            print(f"{owner} {state} {len(paths)} path(s)")
            for p in sorted(paths):
                print("  " + rel_in(p, t[2]))
        return 0
    if argv[:1] == ["release"] and "--owner" in argv:
        k = argv.index("--owner")
        rest = [a for i, a in enumerate(argv[1:], 1) if i not in (k, k + 1)]
        t = tree_of(rest[0] if rest else os.getcwd())
        if t is None or k + 1 >= len(argv):
            return 2
        print("released" if release(t[2], argv[k + 1]) else "no such owner")
        return 0
    print(__doc__)
    return 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["hook"], ["release-hook"]):
        try:
            text = sys.stdin.read()
            out = run_hook(text) if argv[0] == "hook" else run_release_hook(text)
        except Exception:  # never fail closed
            return 0
        if out:
            sys.stdout.write(out + "\n")
        return 0
    return _cli(argv)


if __name__ == "__main__":
    sys.exit(main())
