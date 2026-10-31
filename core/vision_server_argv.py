"""Is this argv a :8889 vision-server process? One structural predicate.

Two killers ask it before they kill: vision_server/_reap.py (a fresh server
reaping orphaned instances before it binds) and dashboard/_vision_watchdog.py
(RC taskkilling a hung :8889 holder). Both used a SUBSTRING test over the
space-joined command line, which matched anything that merely MENTIONED the
name - an editor with the file open, a grep for it, a shell running a launch
string, every `python -m vision_server_<x>`. Cycle 75 of the s144 true-audit
lane replaced the reap's test; cycle 76 moved it here so the watchdog asks the
SAME question without importing vision_server into the RC process (its
_config resolves the vision token and configures logging at import).

Dependency-free on purpose: only `re`. Nothing from RC, nothing from psutil.

The rule: argv[0] is a Python interpreter, and its first non-option argument
is a script named moon_vision_server.py / .pyw (any directory, any case), or
its module option is exactly `-m vision_server`. The file form is the real
launch (dashboard/_vision_watchdog.spawn_vision runs [sys.executable,
<app>/moon_vision_server.py]). The module form is matched for safety only:
the package has no __main__.py, so `-m vision_server` cannot start a server.
The `py.exe` launcher is deliberately NOT matched: it only waits on a real
interpreter child, which is matched itself.
"""
from __future__ import annotations

import re

# The script name of the file-path launch, and the module of the `-m` form.
SCRIPT_NAMES = frozenset({"moon_vision_server.py", "moon_vision_server.pyw"})
MODULE = "vision_server"

# python.exe, pythonw.exe, python3, python3.14.exe, the free-threaded
# python3.14t.exe and the debug python_d.exe (never py.exe, see above).
_INTERPRETER_RE = re.compile(r"\Apythonw?(\d+(\.\d+)*)?t?(_d)?(\.exe)?\Z",
                             re.IGNORECASE)

# Short options that take an argument (glued, "-Xutf8", or as the next token).
_OPTS_WITH_ARG = frozenset("XWQ")


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def is_vision_server_argv(argv) -> bool:
    """True when `argv` (a list of strings) launches a vision server.

    argv[0] must be a Python interpreter; the first non-option argument must
    be moon_vision_server.py / .pyw (any directory, any case), or the module
    option must be exactly ``-m vision_server``. Anything else - a non-list,
    an empty list, a non-string element, ``-c`` code - is False. Never raises.
    """
    if not isinstance(argv, (list, tuple)) or not argv:
        return False
    if not all(isinstance(a, str) for a in argv):
        return False
    if not _INTERPRETER_RE.match(_basename(argv[0])):
        return False
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok == "--check-hash-based-pycs":
            i += 2          # the one long option that takes a separate value
            continue
        if tok == "-":
            return False    # the program is stdin; what follows is ITS argv
        if tok == "--":
            # Option parsing ends; the next token is the script, dash or not.
            return (i + 1 < len(argv)
                    and _basename(argv[i + 1]).lower() in SCRIPT_NAMES)
        if tok.startswith("--"):
            i += 1          # any other long option (--help, --version ...)
            continue
        if not tok.startswith("-"):
            return _basename(tok).lower() in SCRIPT_NAMES
        # A short-option cluster, e.g. "-B", "-Xutf8", "-Im", "-Bmvision_server".
        consumed_next = False
        for j, ch in enumerate(tok[1:], start=1):
            rest = tok[j + 1:]
            if ch == "m":
                target = rest if rest else (argv[i + 1] if i + 1 < len(argv) else "")
                return target == MODULE
            if ch == "c":
                return False
            if ch in _OPTS_WITH_ARG:
                consumed_next = not rest
                break
        i += 2 if consumed_next else 1
    return False
