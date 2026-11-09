"""S144-P-277 - a production docstring never cites ``package.module.symbol`` for a symbol the module no longer defines.

S144-P-273 keeps a cite of a MISSING module out. This is its sibling for a module that still exists but lost (or never
had) the named function: a dotted cite such as ``core.rofl_archive.parse_riot_id`` reads as a pointer to working code, and
the next reader greps for a name that is nowhere (measured 2026-11-06 over the tracked production tree: two real dangling
dotted cites - ``core.rofl_archive.parse_riot_id`` in core/replay_roster.py, where the function is ``parse_account``, and
``agents.agent2_backend.game_ingest.ingest`` plus a stale line range in agents/supervisor.py, where it is
``ingest_game_summary``). Both are fixed with this guard.

Scope, deliberately narrow so a hit is a fact and not a guess: tracked ``.py`` outside tests/ (and any nested ``/tests/``), docs/ and the
vendored fleet kit; the cite must start with a repo top-level package, must resolve (longest prefix) to a TRACKED NON-``__init__``
module, and must have at least one component left over; that first leftover component is the symbol. The symbol counts
as defined when ANY of these names it in the module's AST: a def / class, an assignment target, an import alias, an
argument. A package ``__init__`` resolution is skipped (``lcu.phase`` style cites name dict keys, not modules), as is a
git-config style dotted key (``core.hooksPath``) that never resolves to a module. ``_ALLOWED`` only shrinks.
"""
from __future__ import annotations

import ast
import re
import subprocess

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_TOP = (
    "core", "coaches", "modes", "dashboard", "tools", "app", "lcu", "ops", "agents", "scripts",
    "vision_server", "coach_integration", "lib", "tft", "mc",
)
_CITE_RE = re.compile(rf"(?<![\w.])((?:{'|'.join(_TOP)})(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_OUT_OF_SCOPE_PREFIXES = ("tests/", "ops/fleet_kit/", "docs/")

# (file, dotted cite) -> why it is not a dangling pointer. Only shrinks.
_ALLOWED: set[tuple[str, str]] = set()


def defined_names(src: str) -> set[str] | None:
    """Every name a module's AST defines, binds, imports or takes as an argument; None when it does not parse."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
                names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def resolve(dotted: str, tracked: frozenset[str]) -> tuple[str, list[str]] | None:
    """(module path, leftover components) for the longest tracked non-__init__ module prefix, else None."""
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i]) + ".py"
        if cand in tracked:
            return (cand, parts[i:]) if parts[i:] else None
        if "/".join(parts[:i]) + "/__init__.py" in tracked:
            return None
    return None


def docstrings(src: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                out.append((getattr(node, "lineno", 1), doc))
    return out


def scan_source(
    src: str, tracked: frozenset[str], names_of
) -> list[tuple[int, str]]:
    """(docstring line, dotted cite) of every cite whose symbol its module does not define."""
    hits: list[tuple[int, str]] = []
    for lineno, doc in docstrings(src):
        for m in _CITE_RE.finditer(doc):
            dotted = m.group(1)
            hit = resolve(dotted, tracked)
            if hit is None:
                continue
            module, rest = hit
            if rest[0] == "py":
                continue
            defined = names_of(module)
            if defined is not None and rest[0] not in defined:
                hits.append((lineno, dotted))
    return hits


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    cache: dict[str, set[str] | None] = {}

    def names_of(module: str) -> set[str] | None:
        if module not in cache:
            try:
                cache[module] = defined_names((REPO_ROOT / module).read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                cache[module] = None
        return cache[module]

    found: set[tuple[str, str]] = set()
    for path in repo_files(patterns=("*.py",)):
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE_PREFIXES) or "/tests/" in rel or rel not in tracked:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for _line, dotted in scan_source(src, tracked, names_of):
            found.add((rel, dotted))
    return found


def test_no_docstring_cites_an_undefined_symbol():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "docstring cites package.module.symbol but the module defines no such name "
        f"(fix the name, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a dangling cite - drop them: {stale}"


def test_scanner_is_live():
    tracked = frozenset({"core/real.py", "core/pkg/__init__.py", "core/pkg/sub.py"})
    mods = {
        "core/real.py": {"present", "Klass"},
        "core/pkg/sub.py": {"here"},
    }
    names_of = mods.get

    def scan(doc: str):
        return scan_source(f'"""{doc}"""\n', tracked, names_of)

    # a symbol the module does not define is reported, with its line
    assert scan("see core.real.gone for it") == [(1, "core.real.gone")]
    # a defined function / class, and a deeper attribute under a defined name, are accepted
    assert scan("see core.real.present and core.real.Klass.method") == []
    # a submodule resolves to its own file, not the package __init__
    assert scan("see core.pkg.sub.here") == []
    assert scan("see core.pkg.sub.nope") == [(1, "core.pkg.sub.nope")]
    # a package-only or untracked-module cite names no module symbol, so it is out of this guard's scope
    assert scan("see core.pkg.anything and core.nothere.fn") == []
    # a bare module cite and a ``.py`` suffix leave no symbol to check
    assert scan("see core.real and core.real.py") == []


def test_defined_names_counts_every_binding_form():
    src = (
        "import os.path as osp\nfrom a import b as c\nX = 1\nclass K:\n    attr = 2\n"
        "def f(arg):\n    self.late = 3\n"
    )
    names = defined_names(src)
    assert names is not None
    assert {"osp", "path", "c", "b", "X", "K", "attr", "f", "arg", "late"} <= names
    assert defined_names("def (:\n") is None
