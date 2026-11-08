"""S144-P-337 - every ThreadPoolExecutor in production code is bounded and is either scoped by `with` or a named module pool.

S144-P-336 left ThreadPoolExecutor out of the daemon census because the interpreter joins pool workers at exit. That
join is also the hazard: a pool that is never shut down keeps its workers (and a hung task) alive until exit, and a pool
built with no ``max_workers`` defaults to ``min(32, cpu + 4)`` threads. Measured 2026-11-07 over every tracked production
``.py``: 7 pools. Five are the context expression of a ``with`` block (``core/vision_tesseract.py``,
``tft/cv/ocr_fields.py``, ``tools/ddragon_mirror_refresh.py``, ``ops/loop/repo_review.py``,
``ops/loop/drain_waves_2_3.py``), so the block's exit shuts them down. Two are long-lived module-level pools that are
deliberately never shut down (their callers are request threads that live as long as the process):
``dashboard/_state_builder.py`` ``_RELAY_POOL`` (4 workers) and ``tools/ds_matchdb_mcp_server.py`` ``_DISPATCH_POOL``
(8 workers); both carry a ``thread_name_prefix`` so a stack dump names the owner. All seven pass ``max_workers``.

Detector (AST over every tracked ``.py`` outside ``tests/``, ``docs/`` and the vendored ``ops/fleet_kit/``; a call in a
string, comment or docstring never counts). A call to ``ThreadPoolExecutor`` (bare or qualified) is flagged when:
- it passes no ``max_workers`` (keyword or first positional argument), or
- it is not a ``with`` item and is not a module-level ``NAME = ThreadPoolExecutor(..., thread_name_prefix=...)`` whose
  ``(file, NAME)`` is in ``_OWNED_POOLS``.

A new pool therefore starts guarded: use ``with``, or add a module pool here with a prefix and the reason it never shuts
down. The owned set is exact (a pool that goes away must be dropped from it).

Named blind spots (measured absent from the tree 2026-11-07, so not a live gap): a pool reached through an ``as`` alias or
``getattr``, a ``ThreadPoolExecutor`` subclass, and ``asyncio.to_thread`` / ``run_in_executor`` (the loop's default pool).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

# (file, module-level name) of the long-lived pools that are never shut down on purpose: only request / dispatch threads
# that live as long as the process submit to them.
_OWNED_POOLS = {
    ("dashboard/_state_builder.py", "_RELAY_POOL"),
    ("tools/ds_matchdb_mcp_server.py", "_DISPATCH_POOL"),
}


def _is_pool_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
    return name == "ThreadPoolExecutor"


def _scan(source: str) -> list[tuple[int, str, str | None]]:
    """``(lineno, problem, owned_name)`` per pool; ``problem`` is "" for a clean one.

    ``owned_name`` is the module-level assignment target when the pool is a module pool (clean or not).
    """
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if not _is_pool_call(node):
            continue
        problems: list[str] = []
        none_kw = any(k.arg == "max_workers" and isinstance(k.value, ast.Constant) and k.value.value is None
                      for k in node.keywords)
        if none_kw or (not node.args and not any(k.arg == "max_workers" for k in node.keywords)):
            problems.append("no max_workers")
        parent = parents.get(node)
        module_name: str | None = None
        if isinstance(parent, ast.withitem):
            pass
        elif (isinstance(parent, ast.Assign) and len(parent.targets) == 1
              and isinstance(parent.targets[0], ast.Name) and isinstance(parents.get(parent), ast.Module)):
            module_name = parent.targets[0].id
            if not any(k.arg == "thread_name_prefix" for k in node.keywords):
                problems.append("module pool without thread_name_prefix")
        else:
            problems.append("not a with item or a module-level named pool")
        out.append((node.lineno, "; ".join(problems), module_name))
    return sorted(out)


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def test_every_production_thread_pool_is_bounded_and_scoped_or_owned():
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits: list[str] = []
    owned_found: set[tuple[str, str]] = set()
    pools = 0
    for p in files:
        rel = relative_posix(p)
        try:
            src = p.read_text(encoding="utf-8")
            found = _scan(src)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for lineno, problem, name in found:
            pools += 1
            flagged = problem
            if name is not None:
                if (rel, name) in _OWNED_POOLS:
                    owned_found.add((rel, name))
                else:
                    flagged = "; ".join(x for x in (problem, "module pool not in _OWNED_POOLS") if x)
            if flagged:
                hits.append(f"{rel}:{lineno} {flagged}")
    assert pools >= 7, "the walk saw almost no pool, so an empty hit list proves nothing"
    assert not hits, f"unbounded or unscoped ThreadPoolExecutor (use `with`, or own it here): {hits}"
    assert owned_found == _OWNED_POOLS, f"stale _OWNED_POOLS entry (drop it): {_OWNED_POOLS - owned_found}"


def test_the_detector_flags_each_bad_shape():
    cases = {
        "import concurrent.futures as cf\np = cf.ThreadPoolExecutor()\n":
            [(2, "no max_workers; module pool without thread_name_prefix", "p")],
        "import concurrent.futures as cf\ncf.ThreadPoolExecutor(max_workers=2).submit(f)\n":
            [(2, "not a with item or a module-level named pool", None)],
        "from concurrent.futures import ThreadPoolExecutor\nwith ThreadPoolExecutor() as ex:\n    pass\n":
            [(2, "no max_workers", None)],
        "from concurrent.futures import ThreadPoolExecutor\nP = ThreadPoolExecutor(max_workers=2)\n":
            [(2, "module pool without thread_name_prefix", "P")],
        "from concurrent.futures import ThreadPoolExecutor\n"
        "def f():\n    ex = ThreadPoolExecutor(max_workers=2)\n    return ex\n":
            [(3, "not a with item or a module-level named pool", None)],
        "from concurrent.futures import ThreadPoolExecutor\n"
        "class C:\n    def __init__(self):\n        self.p = ThreadPoolExecutor(max_workers=2)\n":
            [(4, "not a with item or a module-level named pool", None)],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_accepts_each_scoped_or_named_shape():
    clean = (
        "import concurrent.futures as cf\n"
        "from concurrent.futures import ThreadPoolExecutor\n"
        "with ThreadPoolExecutor(max_workers=4) as ex:\n    pass\n"
        "with cf.ThreadPoolExecutor(3) as ex:\n    pass\n"
        "P = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix='x')\n"
        "doc = 'ThreadPoolExecutor()'\n"
        "# ThreadPoolExecutor()\n"
    )
    assert [(n, prob) for n, prob, _ in _scan(clean)] == [(3, ""), (5, ""), (7, "")]
