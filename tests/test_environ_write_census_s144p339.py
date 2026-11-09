"""S144-P-339 - every production write to ``os.environ`` is a named, reasoned site.

``os.environ[...] = ...`` changes the environment of the whole process and of every child it starts afterwards, so a
library function that sets one hands a hidden input to every later reader (the RM-907 BLAS case and the "env read from a
process, called a machine fact" memory are the same family). S144-P-338 left it as a named blind spot because the set was
unmeasured. Measured 2026-11-07 by AST over every tracked production ``.py`` (outside ``tests/``, ``docs/`` and the
vendored ``ops/fleet_kit/``): 5 sites in 5 files, listed in ``_SITES`` with the scope they sit in and why they are safe.

Detector: a write through the dotted name ``os.environ`` (or ``from os import environ`` / ``import os as _os`` spelled,
resolved through the file's own imports, or a plain local alias ``env = os.environ`` in the same file): a subscript
assignment, augmented assignment or ``del``, a ``|=`` merge, or a call of ``setdefault`` / ``update`` / ``pop`` /
``popitem`` / ``clear`` / ``__setitem__`` / ``__delitem__``. A hit is keyed ``(file, scope, key)``: scope is ``"module"`` or
the enclosing function's dotted qualname; key is the string literal when the write names one, else ``"<dynamic>"``. The set
is exact: a new site fails until it is added with a reason, and a site that goes away must be dropped.

Not a write, so not counted: ``os.environ.copy()`` / ``dict(os.environ)`` handed to a child (the per-child env is the
intended pattern), ``os.environ.get``, and reads. ``os.putenv`` / ``os.unsetenv`` stay in the S144-P-338 census.

Named blind spots (measured absent from the tree 2026-11-07, so not a live gap): the environment mapping passed into a
function and written there under another name, an alias made by tuple-unpack or ``getattr``, ``setattr(os, "environ", ...)``
or a rebind of ``os.environ`` itself, and a file that fails to parse (skipped, as in the sibling censuses).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

_WRITE_METHODS = frozenset({"setdefault", "update", "pop", "popitem", "clear", "__setitem__", "__delitem__"})

# (file, scope, key) -> why this environment write is safe where it is.
_SITES = {
    ("agents/agent3_testing/suite/conftest.py", "module", "RC_PHASE3_LOG_DIR"):
        "pytest conftest, not shipped runtime: points the Phase 3 agent log dir at a mkdtemp dir removed at exit when the caller set none",
    ("conftest.py", "module", "<dynamic>"):
        "pytest root conftest, not shipped runtime: setdefault of the three BLAS thread-count vars to 1 (an explicit caller value wins), RM-907",
    ("main.py", "_load_api_key", "ANTHROPIC_API_KEY"):
        "frozen entry point: promotes the key read from the gitignored key file so the SDK clients find it; only a sk-ant- prefixed value is set",
    ("ops/loop/drain_waves_2_3.py", "run", "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"):
        "one-shot drain launcher: bounds the background-wait ceiling for this process and the headless children it starts only",
    ("tools/inbox_responder_runner.py", "module", "RC_RESPONDER_REAL_SPAWN"):
        "under if __name__ == '__main__' only: the one site that arms real spawns, so an import (a test) never arms them",
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


def _environ_names(tree: ast.AST, aliases: dict[str, str]) -> set[str]:
    """Dotted names that stand for ``os.environ`` in this file: itself plus ``name = os.environ`` locals."""
    names = {"os.environ"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            d = _dotted(node.value)
            if d is not None and _resolve(d, aliases) == "os.environ":
                names.add(node.targets[0].id)
    return names


def _key_of(node: ast.AST | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else "<dynamic>"


def _scan(source: str) -> list[tuple[int, str, str]]:
    """``(lineno, scope, key)`` per ``os.environ`` write; scope is "module" or a function qualname."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    envs = _environ_names(tree, aliases)

    def is_env(node: ast.AST) -> bool:
        d = _dotted(node)
        return (d is not None and _resolve(d, aliases) in envs) or d in envs

    hits: list[tuple[int, str, str]] = []

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            s = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = [*scope, child.name]
            where = ".".join(s) or "module"
            if isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for tg in targets:
                    if isinstance(tg, ast.Subscript) and is_env(tg.value):
                        hits.append((child.lineno, where, _key_of(tg.slice)))
                    elif isinstance(child, ast.AugAssign) and is_env(tg):
                        hits.append((child.lineno, where, "<dynamic>"))
            elif isinstance(child, ast.Delete):
                for tg in child.targets:
                    if isinstance(tg, ast.Subscript) and is_env(tg.value):
                        hits.append((child.lineno, where, _key_of(tg.slice)))
            elif isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Attribute) and f.attr in _WRITE_METHODS and is_env(f.value):
                    first = child.args[0] if child.args else None
                    key = _key_of(first) if f.attr in {"setdefault", "pop", "__setitem__", "__delitem__"} else "<dynamic>"
                    hits.append((child.lineno, where, key))
            visit(child, s)

    visit(tree, [])
    return sorted(hits)


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def test_every_production_environ_write_is_a_named_site():
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    found: set[tuple[str, str, str]] = set()
    for p in files:
        rel = relative_posix(p)
        try:
            hits = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        found.update((rel, scope, key) for _line, scope, key in hits)
    assert len(found) >= 3, "the walk saw almost no site, so an empty difference proves nothing"
    new = sorted(found - set(_SITES))
    gone = sorted(set(_SITES) - found)
    assert not new, f"new os.environ write (add it to _SITES with a reason, or pass an env= to the child instead): {new}"
    assert not gone, f"stale _SITES entry (drop it): {gone}"


def test_every_site_carries_a_reason():
    assert all(len(why) > 20 for why in _SITES.values())


def test_the_detector_flags_each_shape():
    cases = {
        "import os\nos.environ['A'] = '1'\n": [(2, "module", "A")],
        "import os\ndef f(k):\n    os.environ[k] = '1'\n": [(3, "f", "<dynamic>")],
        "import os\nos.environ.setdefault('A', '1')\n": [(2, "module", "A")],
        "import os\nos.environ.update({'A': '1'})\n": [(2, "module", "<dynamic>")],
        "import os\ndef f():\n    os.environ.pop('A', None)\n": [(3, "f", "A")],
        "import os\ndel os.environ['A']\n": [(2, "module", "A")],
        "import os\nos.environ |= {'A': '1'}\n": [(2, "module", "<dynamic>")],
        "import os\nos.environ.clear()\n": [(2, "module", "<dynamic>")],
        "import os as _o\ndef f():\n    _o.environ['A'] = '1'\n": [(3, "f", "A")],
        "from os import environ\nenviron['A'] = '1'\n": [(2, "module", "A")],
        "from os import environ as E\nE.setdefault('A', '1')\n": [(2, "module", "A")],
        "import os\nclass C:\n    def m(self):\n        os.environ['A'] = '1'\n": [(4, "C.m", "A")],
        "import os\nenv = os.environ\nenv['A'] = '1'\n": [(3, "module", "A")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_ignores_reads_copies_and_look_alikes():
    clean = (
        "import os\n"
        "doc = 'os.environ[\"A\"] = 1'\n"
        "# os.environ['A'] = '1'\n"
        "a = os.environ.get('A')\n"
        "b = os.environ['A']\n"
        "c = os.environ.copy()\n"
        "c['A'] = '1'\n"
        "d = dict(os.environ, A='1')\n"
        "e = {}\n"
        "e['A'] = '1'\n"
        "e.setdefault('A', '1')\n"
        "'A' in os.environ\n"
    )
    assert _scan(clean) == []
