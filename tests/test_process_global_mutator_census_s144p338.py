"""S144-P-338 - every production write to process-global interpreter state is a named, reasoned site.

A call such as ``os.chdir`` or ``signal.signal`` changes the whole process, not the caller: a library module that does it
at import time moves the cwd of every thread and every test that imports it, and a handler installed from a non-main
thread raises. Nothing in the tree forced such a site to be written down. Measured 2026-11-07 by AST over every tracked
production ``.py`` (outside ``tests/``, ``docs/`` and the vendored ``ops/fleet_kit/``): 17 sites in 11 files, listed in
``_SITES`` with the scope they sit in and why they are safe.

Detector: a call whose dotted name (``os.chdir``, or a ``from os import chdir`` / ``import os as _os`` spelling resolved
through the file's own imports) is in ``_MUTATOR_CALLS``, or an assignment to a dotted target in ``_MUTATOR_ASSIGNS``
(``sys.stdout``, ``sys.excepthook`` ...). A hit is keyed ``(file, dotted name, scope)``, scope being ``"module"`` or the
enclosing function's dotted qualname. The set is exact: a new site fails until it is added with a reason, and a site that
goes away must be dropped.

Named blind spots (measured absent from the tree 2026-11-07, so not a live gap): a mutator reached through ``getattr`` or
a decorator (``@atexit.register`` is not a call node), a tuple-unpack assignment
(``sys.stdout, sys.stderr = a, b``), ``loop.add_signal_handler`` (loop-scoped, one use in agents/supervisor.py), a file
that fails to parse (skipped, as in the sibling censuses),
a variable holding the function, an ``os.environ[...] = ...`` write (the environment is a separate, much larger census),
and a ``setattr(sys, "stdout", ...)`` spelling. ``warnings.catch_warnings()`` scoped filters are not process-global and
sit behind the ``warnings.simplefilter`` row only because the call name is the same; that one row says so.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

_MUTATOR_CALLS = frozenset({
    "os.chdir", "os.umask", "os.putenv", "os.unsetenv", "os.add_dll_directory",
    "signal.signal", "signal.setitimer", "signal.alarm",
    "atexit.register",
    "socket.setdefaulttimeout",
    "sys.setrecursionlimit", "sys.setswitchinterval", "sys.settrace", "sys.setprofile", "sys.addaudithook",
    "threading.settrace", "threading.setprofile", "threading.stack_size",
    "warnings.filterwarnings", "warnings.simplefilter",
    "logging.disable", "logging.captureWarnings", "logging.setLoggerClass", "logging.setLogRecordFactory",
    "locale.setlocale", "mimetypes.add_type", "faulthandler.enable", "gc.disable", "gc.set_threshold",
    "random.seed", "asyncio.set_event_loop", "tracemalloc.start",
})

_MUTATOR_ASSIGNS = frozenset({
    "sys.stdout", "sys.stderr", "sys.stdin", "sys.excepthook", "sys.unraisablehook", "threading.excepthook",
    "ssl._create_default_https_context", "socket.socket", "socket.getaddrinfo", "time.sleep", "sys.modules",
})

# (file, dotted name, scope) -> why this process-global write is safe where it is.
_SITES = {
    ("core/log_setup.py", "sys.excepthook", "setup"):
        "frozen: setup() installs the one crash hook, logging an uncaught main-thread exception to crash.txt",
    ("core/log_setup.py", "threading.excepthook", "setup"):
        "frozen: setup() installs the matching hook for an uncaught exception in a non-main thread",
    ("core/resource_manager.py", "atexit.register", "ResourceManager.__init__"):
        "one ResourceManager per process; shutdown() is idempotent",
    ("core/resource_manager.py", "signal.signal", "ResourceManager.__init__"):
        "wrapped in try/except: a non-main-thread construction raises ValueError and is swallowed",
    ("ops/launcher/service_host.py", "signal.signal", "_install_signals"):
        "service host main thread only; ValueError / OSError from a non-main thread is caught",
    ("tools/build_rank_baselines.py", "sys.stdout", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/build_rank_baselines.py", "sys.stderr", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/ds_matchdb_mcp_server.py", "os.chdir", "module"):
        "HTTP MCP server script launched by a scheduled task with an arbitrary cwd; pins the project root before its core.* imports",
    ("tools/gated_tls_2999_probe.py", "warnings.simplefilter", "relay_context"):
        "NOT global: sits inside warnings.catch_warnings(), restored on exit",
    ("tools/ladder_role_scout.py", "sys.stdout", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/ladder_role_scout.py", "sys.stderr", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/replay_roster_pull.py", "sys.stdout", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/replay_roster_pull.py", "sys.stderr", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/start_daemon_slayer.py", "os.chdir", "module"):
        "launcher script run as __main__ from a scheduled task whose cwd is the system directory",
    ("tools/start_ds_matchdb_mcp.py", "os.chdir", "module"):
        "launcher script run as __main__ from a scheduled task whose cwd is the system directory",
    ("tools/timeline_ingest.py", "sys.stdout", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
    ("tools/timeline_ingest.py", "sys.stderr", "main"):
        "CLI entry: --log-file redirects the run's own output, set inside main()",
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _aliases(tree: ast.AST) -> dict[str, str]:
    """local name -> the dotted module path it stands for, from this file's own imports."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _resolve(name: str, aliases: dict[str, str]) -> str:
    head, _, rest = name.partition(".")
    real = aliases.get(head, head)
    return f"{real}.{rest}" if rest else real


def _scan(source: str) -> list[tuple[str, int, str]]:
    """``(dotted name, lineno, scope)`` per process-global write; scope is "module" or a function qualname."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    hits: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, scope: list[str], fn: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            s, f = scope, fn
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                s, f = [*scope, child.name], [*fn, child.name]
            elif isinstance(child, ast.ClassDef):
                s = [*scope, child.name]
            where = ".".join(f and s or []) or "module"
            if isinstance(child, ast.Call):
                d = _dotted(child.func)
                if d is not None:
                    d = _resolve(d, aliases)
                    if d in _MUTATOR_CALLS:
                        hits.append((d, child.lineno, where))
            elif isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for tg in targets:
                    d = _dotted(tg)
                    if d is not None:
                        d = _resolve(d, aliases)
                        if d in _MUTATOR_ASSIGNS:
                            hits.append((d, child.lineno, where))
            visit(child, s, f)

    visit(tree, [], [])
    return sorted(hits, key=lambda h: (h[1], h[0]))


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def test_every_production_process_global_write_is_a_named_site():
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    found: set[tuple[str, str, str]] = set()
    for p in files:
        rel = relative_posix(p)
        try:
            hits = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        found.update((rel, name, scope) for name, _line, scope in hits)
    assert len(found) >= 10, "the walk saw almost no site, so an empty difference proves nothing"
    new = sorted(found - set(_SITES))
    gone = sorted(set(_SITES) - found)
    assert not new, f"new process-global write (add it to _SITES with a reason, or scope it): {new}"
    assert not gone, f"stale _SITES entry (drop it): {gone}"


def test_every_site_carries_a_reason():
    assert all(len(why) > 20 for why in _SITES.values())


def test_the_detector_flags_each_shape():
    cases = {
        "import os\nos.chdir('x')\n": [("os.chdir", 2, "module")],
        "import os as _o\ndef f():\n    _o.umask(0)\n": [("os.umask", 3, "f")],
        "from os import chdir\ndef f():\n    chdir('x')\n": [("os.chdir", 3, "f")],
        "import signal\nclass C:\n    def m(self):\n        signal.signal(2, h)\n": [("signal.signal", 4, "C.m")],
        "import sys\nsys.stdout = open('x', 'w')\n": [("sys.stdout", 2, "module")],
        "import sys\ndef main():\n    sys.excepthook = h\n": [("sys.excepthook", 3, "main")],
        "import warnings\nwarnings.simplefilter('ignore')\n": [("warnings.simplefilter", 2, "module")],
        "import atexit\n@atexit.register\ndef f():\n    pass\n": [],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_ignores_strings_comments_and_reads():
    clean = (
        "import os, sys\n"
        "doc = 'os.chdir(x)'\n"
        "# signal.signal(2, h)\n"
        "cwd = os.getcwd()\n"
        "out = sys.stdout\n"
        "sys.stdout.write('x')\n"
        "def chdir(p):\n    return p\n"
        "chdir('x')\n"
    )
    assert _scan(clean) == []
