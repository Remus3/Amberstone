"""Fleet kit - the ONLY path that starts a headless `claude` in any repo here.

Vendored byte-for-byte into every repo at ops/fleet_kit/ and pinned by
MANIFEST.json. Do NOT edit a vendored copy: report the defect to MAIN, which
ships a new kit version to every repo at once.

What it enforces (FLEET-COMMON item 10):
- the second-account proxy, read from the user variable CLAUDE_HEADLESS_BASE_URL
  (registry first, so deleting the variable stops even a long-lived process),
- fail closed: unset / non-loopback / unreachable -> Refused, never a fallback,
- at most RUNS_CAP runs started per rolling WINDOW_S,
- never spawn on this repo's own notes, or on TERMINAL / no-reply notes,
- lean flags (strict MCP + project settings, or --bare), sonnet unless the work
  writes code, effort low for acknowledgements,
- no visible console window,
- one usage line per run, and the live status file the lane widget reads.

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

KIT_VERSION = 3
VAR = "CLAUDE_HEADLESS_BASE_URL"
RUNS_CAP = 120
WINDOW_S = 86400
STATUS_REL = Path("ops/loop/control/inbox_status.json")
BUDGET_REL = Path("ops/loop/control/headless_budget.json")
USAGE_REL = Path("ops/loop/control/headless_usage.jsonl")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
PLACEHOLDER_KEY = "fleet-proxy-placeholder"
STRIP_EXACT = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
STRIP_PREFIX = ("CLAUDE_CODE_USE_",)
ACK_MARKERS = ("INFORMATION", "ACK", "TERMINAL", "CORRECTION-ACCEPTED",
               "POLL-ANSWER", "RECEIVED", "NO-REPLY")
_SENDER = re.compile(r"-from-([A-Z]+)-")


class Refused(Exception):
    """A spawn the kit will not start. str() is the logged reason."""


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


def check_url(url):
    """Raise Refused unless url is plain http to a loopback host:port."""
    if not url:
        raise Refused(VAR + " is unset")
    if any(c in url for c in "@\\ \t\r\n"):
        raise Refused("proxy URL has a forbidden character")
    parts = urlsplit(url)
    if parts.scheme != "http":
        raise Refused("proxy URL is not plain http")
    if parts.hostname not in LOOPBACK:
        raise Refused("proxy URL host is not loopback")
    if not parts.port:
        raise Refused("proxy URL has no port")
    return parts.hostname, parts.port


def probe(host, port, timeout=2.0, connect=socket.create_connection):
    try:
        connect((host, port), timeout=timeout).close()
    except OSError as exc:
        raise Refused("proxy unreachable: %s" % exc.__class__.__name__)


def child_env(url, bare=False, parent=None):
    """The child's environment: provider switches and credentials removed, the
    proxy URL set. --bare reads no OAuth, so it gets a placeholder key that the
    proxy replaces with the pinned account."""
    env = dict(os.environ if parent is None else parent)
    for k in list(env):
        if k in STRIP_EXACT or k.startswith(STRIP_PREFIX) or (
                k.startswith("ANTHROPIC_") and k.endswith("BASE_URL")):
            del env[k]
    env["ANTHROPIC_BASE_URL"] = url
    if bare:
        env["ANTHROPIC_API_KEY"] = PLACEHOLDER_KEY
    return env


# ---------------------------------------------------------------- note rules

def note_sender(name):
    m = _SENDER.search(name)
    return m.group(1) if m else None


def should_skip(name, own_code, head=""):
    """'self', 'terminal' or None. head = the note's first few hundred chars."""
    if note_sender(name) == own_code:
        return "self"
    text = (name + " " + head).upper()
    if "TERMINAL" in text or "NO-REPLY" in text or "NO REPLY" in text:
        return "terminal"
    return None


def pick_effort(name):
    up = name.upper()
    return "low" if any(m in up for m in ACK_MARKERS) else "medium"


def pick_model(writes_code):
    return "opus" if writes_code else "sonnet"


# ---------------------------------------------------------------- argv

def claude_exe(which=shutil.which):
    """The real claude executable. The npm shim claude.CMD would run under
    cmd.exe; prefer the binary it wraps so no console host is involved."""
    path = which("claude")
    if not path:
        raise Refused("claude not found on PATH")
    if path.lower().endswith(".cmd"):
        real = (Path(path).parent / "node_modules" / "@anthropic-ai" /
                "claude-code" / "bin" / "claude.exe")
        if real.exists():
            return str(real)
    return path


def build_argv(exe, prompt, model, effort, bare=False, rules_file=None,
               extra=()):
    argv = [exe, "-p", prompt, "--output-format", "json",
            "--no-session-persistence", "--model", model, "--effort", effort]
    if bare:
        argv.append("--bare")
        if rules_file:
            argv += ["--append-system-prompt-file", str(rules_file)]
    else:
        argv += ["--strict-mcp-config", "--setting-sources", "project,local"]
    return argv + list(extra)


# ---------------------------------------------------------------- budget

class RunBudget(object):
    """Runs started per rolling window, persisted as epoch seconds."""

    def __init__(self, path, cap=RUNS_CAP, window=WINDOW_S, clock=time.time):
        self.path, self.cap, self.window, self.clock = Path(path), cap, window, clock

    def _load(self):
        try:
            starts = json.loads(self.path.read_text(encoding="utf-8"))["starts"]
        except (OSError, ValueError, KeyError, TypeError):
            starts = []
        floor = self.clock() - self.window
        return sorted(s for s in starts if isinstance(s, (int, float)) and s > floor)

    def used(self):
        return len(self._load())

    def can_start(self):
        return self.used() < self.cap

    def frees_at(self):
        """Epoch when the count next drops, or None when nothing is counted."""
        starts = self._load()
        return starts[0] + self.window if starts else None

    def record(self):
        starts = self._load() + [self.clock()]
        _atomic_write(self.path, json.dumps({"starts": starts}))


# ---------------------------------------------------------------- status/usage

def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="ascii", newline="\n")
    os.replace(str(tmp), str(path))


def _iso(epoch):
    if not epoch or epoch <= 0:
        return None
    return _dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def write_status(root, code, state, task, task_started, budget, task_eta_s=None,
                 next_tick=None, clock=time.time):
    """Schema 1 of ops/loop/control/inbox_status.json (MAIN 0915 section 1)."""
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


def usage_line(result, code, note, model, effort, bare, rc, duration_s):
    u = (result or {}).get("usage") or {}
    return {
        "ts": _iso(time.time()), "kit": KIT_VERSION, "code": code, "note": note,
        "model": model, "effort": effort, "bare": bare, "rc": rc,
        "duration_s": round(duration_s, 1),
        "input_tokens": u.get("input_tokens"),
        "cache_creation": u.get("cache_creation_input_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cost_usd": (result or {}).get("total_cost_usd"),
        "num_turns": (result or {}).get("num_turns"),
    }


# ---------------------------------------------------------------- provenance

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_main(note_path, main_outbox):
    """True when MAIN's outbox holds a byte-identical copy of this note."""
    twin = Path(main_outbox) / Path(note_path).name
    return twin.is_file() and sha256_file(twin) == sha256_file(note_path)


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
        problems.append("manifest v%s != kit v%s" % (man.get("version"), KIT_VERSION))
    for name, want in sorted(man.get("files", {}).items()):
        f = kit / name
        if not f.is_file() or sha256_file(f) != want:
            problems.append("kit file missing or edited: %s" % name)
    try:
        text = (root / "CLAUDE.md").read_bytes().decode("ascii")
    except (OSError, UnicodeDecodeError):
        return problems + ["CLAUDE.md missing or not ASCII"]
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

def spawn(root, code, prompt, note="", writes_code=False, bare=False,
          rules_file=None, timeout=3600, extra=(), run=subprocess.run,
          url_source=base_url, connect=socket.create_connection,
          exe_source=claude_exe):
    """Start ONE headless run and wait for it. Returns the usage line (dict).
    Raises Refused, before anything starts, when the fleet rules forbid it."""
    root = Path(root)
    budget = RunBudget(root / BUDGET_REL)
    url = url_source()
    host, port = check_url(url)
    probe(host, port, connect=connect)
    if not budget.can_start():
        write_status(root, code, "limit", "Turn Limit Reached", None, budget)
        raise Refused("run budget exhausted (%d/%d)" % (budget.used(), budget.cap))
    model, effort = pick_model(writes_code), pick_effort(note)
    argv = build_argv(exe_source(), prompt, model, effort, bare, rules_file, extra)
    budget.record()
    started = time.time()
    write_status(root, code, "running", "Running Session", started, budget)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = run(argv, cwd=str(root), env=child_env(url, bare), capture_output=True,
               text=True, timeout=timeout, creationflags=flags)
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        result = None
    line = usage_line(result, code, note, model, effort, bare, proc.returncode,
                      time.time() - started)
    log = root / USAGE_REL
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="ascii", newline="\n") as fh:
        fh.write(json.dumps(line) + "\n")
    write_status(root, code, "idle", "Idle", time.time(), budget)
    line["result"] = (result or {}).get("result")
    return line
