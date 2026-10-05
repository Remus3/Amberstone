# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit - secret references, never literals (since kit v5).

Configuration holds a REFERENCE to a secret, never the secret:

    {"env": "NAME"}                 an environment variable
    {"file": "<path>"}              the first line of a file (keep such paths in
                                    gitignored config - a path can name an account)
    {"command": ["exe", "arg"]}     the stdout of a command, argv list only

resolve(ref) returns the value at use time. Errors name the REFERENCE
("env:NAME", "file:<basename>", "command:<exe basename>") and never the value
or a full path; no error chains a subprocess exception (a timeout or failed
command carries the child's stdout, which is the secret).

AcceptedTokens holds the tokens a local server ACCEPTS in two (or more)
slots, so a token rotates without a restart: write the new token to the second
slot, move clients, retire the first. Slots are re-read every reread_s, a slot
shorter than min_len or that fails to resolve is ignored, zero usable slots
accept nothing (fail closed), and comparison is hmac.compare_digest on UTF-8
bytes against every slot.

This module never logs and never prints. Pure stdlib. No machine path,
account id or repo name appears in this file.
"""

import hmac
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

KINDS = ("env", "file", "command")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
# An injected runner may raise anything; it must never chain (see resolve).
ANY_FAILURE = (Exception,)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class SecretMissing(Exception):
    """The reference is well formed but yields no secret. Names the ref only."""


class SecretRefInvalid(ValueError):
    """The reference itself is malformed. Names keys and types, never values."""


def _norm(path):
    return os.path.normcase(os.path.realpath(path))


def _find_on_path(name, environ=None):
    """Resolve a bare executable name on PATH. Empty, relative and cwd-equal
    PATH entries are skipped: never an executable from the working directory."""
    env = os.environ if environ is None else environ
    here = _norm(Path.cwd())
    exts = [""]
    if sys.platform == "win32":
        exts = [""] + [e for e in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for entry in env.get("PATH", "").split(os.pathsep):
        d = entry.strip().strip('"')
        if not d or not Path(d).is_absolute() or _norm(d) == here:
            continue
        for ext in exts:
            p = Path(d) / (name + ext)
            if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
                return str(p)
    return None


def _default_runner(argv, timeout):
    """(returncode, stdout text). Any failure to run -> (None, ""). No
    exception escapes, so nothing carrying the child's output can chain."""
    failed = False
    out = b""
    rc = None
    try:
        done = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout, creationflags=_NO_WINDOW)
        rc, out = done.returncode, done.stdout or b""
    except (subprocess.SubprocessError, OSError, ValueError):
        failed = True
    if failed:
        return None, ""
    return rc, out.decode("utf-8", errors="replace")


def _kind(ref):
    if not isinstance(ref, dict):
        raise SecretRefInvalid(f"secret ref must be a dict, got {type(ref).__name__}")
    keys = sorted(str(k) for k in ref)
    if len(keys) != 1 or keys[0] not in KINDS:
        raise SecretRefInvalid(f"secret ref needs exactly one of {list(KINDS)}; got keys {keys}")
    return keys[0]


def _first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _resolve_env(name, environ):
    if not isinstance(name, str) or not _ENV_NAME.match(name):
        raise SecretRefInvalid("env ref needs a variable name")
    env = os.environ if environ is None else environ
    value = str(env.get(name) or "").strip()
    if not value:
        raise SecretMissing(f"secret ref env:{name} is unset or empty")
    return value


def _resolve_file(path):
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise SecretRefInvalid("file ref needs a path")
    label = f"file:{Path(path).name}"
    failed = False
    text = ""
    try:
        text = Path(path).read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        failed = True
    if failed:
        raise SecretMissing(f"secret ref {label} is missing or unreadable")
    value = _first_line(text)
    if not value:
        raise SecretMissing(f"secret ref {label} is empty")
    return value


def _resolve_command(argv, runner, timeout, environ):
    if isinstance(argv, (str, bytes)):
        raise TypeError("command ref must be an argument list, not a string")
    if not isinstance(argv, (list, tuple)) or not argv:
        raise SecretRefInvalid("command ref needs a non-empty argument list")
    if not all(isinstance(a, str) for a in argv):
        raise TypeError("command ref arguments must all be str")
    exe = argv[0]
    if not exe:
        raise SecretRefInvalid("command ref has an empty executable")
    label = f"command:{Path(exe).name}"
    if Path(exe).is_absolute():
        resolved = exe
    elif any(sep in exe for sep in ("/", "\\")):
        raise SecretRefInvalid("command ref executable must be absolute or a bare name")
    else:
        resolved = _find_on_path(exe, environ)
        if resolved is None:
            raise SecretMissing(
                f"secret ref {label} not found on PATH (working directory excluded)")
    run = runner or _default_runner
    failed = False
    rc, out = None, ""
    try:
        rc, out = run([resolved, *argv[1:]], timeout)
    except ANY_FAILURE:  # never chain: the exception may carry stdout
        failed = True
    if failed or rc is None:
        raise SecretMissing(f"secret ref {label} did not run to completion")
    if rc != 0:
        raise SecretMissing(f"secret ref {label} exited {rc}")
    value = _first_line(out or "")
    if not value:
        raise SecretMissing(f"secret ref {label} printed nothing")
    return value


def resolve(ref, environ=None, runner=None, timeout=10):
    """The secret a reference points at. Raises SecretMissing (ref named, value
    never) or SecretRefInvalid / TypeError for a malformed ref."""
    kind = _kind(ref)
    if kind == "env":
        return _resolve_env(ref["env"], environ)
    if kind == "file":
        return _resolve_file(ref["file"])
    return _resolve_command(ref["command"], runner, timeout, environ)


class AcceptedTokens:
    """Tokens a server accepts, from one or more refs (rotation slots)."""

    def __init__(self, refs, min_len=16, reread_s=300, clock=time.monotonic,
                 environ=None, runner=None):
        self._refs = list(refs)
        self._min_len = int(min_len)
        self._reread_s = float(reread_s)
        self._clock = clock
        self._environ = environ
        self._runner = runner
        self._slots = []
        self._loaded_at = None
        self._mutex = threading.Lock()

    def __repr__(self):
        return f"AcceptedTokens(refs={len(self._refs)})"

    __str__ = __repr__

    def _reload_if_stale(self):
        with self._mutex:
            now = self._clock()
            if self._loaded_at is not None and now - self._loaded_at < self._reread_s:
                return
            slots = []
            for ref in self._refs:
                try:
                    value = resolve(ref, environ=self._environ, runner=self._runner)
                except (SecretMissing, SecretRefInvalid, TypeError):
                    continue
                if len(value) >= self._min_len:
                    slots.append(value.encode("utf-8"))
            self._slots = slots
            self._loaded_at = now

    def usable(self):
        """How many slots currently hold a usable token."""
        self._reload_if_stale()
        return len(self._slots)

    def check(self, presented):
        """True when presented equals any usable slot. Constant-time per slot,
        every slot compared; empty, None or non-str presented is False."""
        if not isinstance(presented, str) or not presented:
            return False
        self._reload_if_stale()
        given = presented.encode("utf-8")
        ok = False
        for slot in self._slots:
            ok = hmac.compare_digest(given, slot) or ok
        return ok
