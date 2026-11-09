"""S144-P-368 - an in-process TTL cache stamps and ages its entries on ``time.monotonic()``, not the wall clock.

``dashboard/routes_personal_vs.py`` and ``dashboard/routes_post_game_rubric.py`` keep ``_CACHE[key] = (stamp,
payload)`` and drop an entry once ``now - stamp > _CACHE_TTL_S``. Both read ``time.time()`` at both ends, so a
system clock step (NTP correction, manual change, VM resume) moves every entry's age at once: a forward step
expires the whole cache early (a burst of rewind-DB queries), a backward step keeps a stale entry alive for the
size of the step. The stamp never leaves the process, so the wall clock buys nothing; ``time.monotonic()`` cannot
step. (S144-P-363 / S144-P-364 made the same change for wait loops.)

Part 1 is behavioural: the clock is stepped under each cache and the TTL must not notice. Part 2 is a census:
an AST walk over every tracked non-test ``*.py`` for a subscript assignment whose value is a tuple led by a
``time.time()`` call (``_CACHE[key] = (time.time(), payload)``), the shape of a stamped in-process cache entry.
Measured 2026-11-08: TWO sites, both converted here, so the named-row table is empty. Stated limits: a stamp bound
to a variable first, an attribute store (``self._x = time.time()``) and a dict-literal stamp
(``{"ts": time.time()}``) are not seen; a stamp that is persisted, shown or compared with a file mtime is wall
time by design and is exactly what this shape excludes.
"""
from __future__ import annotations

import ast
import time

import pytest

from dashboard import routes_personal_vs as rpv
from dashboard import routes_post_game_rubric as rub
from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "ops/launcher/", "agents/agent3_testing/suite/", "docs/_archive/")

# (file, enclosing function) -> why a wall-clock stamp is the design. Empty: both sites were converted.
_ROWS: dict[tuple[str, str], str] = {}

_CACHES = (
    pytest.param(rpv, ("k",), id="personal_vs"),
    pytest.param(rub, "m1", id="post_game_rubric"),
)


@pytest.fixture(autouse=True)
def _clean_caches():
    rpv._CACHE.clear()
    rub._CACHE.clear()
    yield
    rpv._CACHE.clear()
    rub._CACHE.clear()


@pytest.mark.parametrize(("mod", "key"), _CACHES)
def test_a_forward_wall_clock_step_does_not_expire_a_fresh_entry(mod, key, monkeypatch):
    mod._cache_put(key, {"v": 1})
    real = time.time
    monkeypatch.setattr(mod.time, "time", lambda: real() + 3600.0)
    assert mod._cache_get(key) == {"v": 1}


@pytest.mark.parametrize(("mod", "key"), _CACHES)
def test_a_backward_wall_clock_step_does_not_keep_an_expired_entry(mod, key, monkeypatch):
    mod._cache_put(key, {"v": 1})
    real_mono, real_wall = time.monotonic, time.time
    monkeypatch.setattr(mod.time, "monotonic", lambda: real_mono() + mod._CACHE_TTL_S + 1.0)
    monkeypatch.setattr(mod.time, "time", lambda: real_wall() - 3600.0)
    assert mod._cache_get(key) is None


@pytest.mark.parametrize(("mod", "key"), _CACHES)
def test_the_stamp_is_monotonic(mod, key):
    before = time.monotonic()
    mod._cache_put(key, {"v": 1})
    stamp, _payload = mod._CACHE[key]
    assert before <= stamp <= time.monotonic()


def _is_time_time(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "time"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "time")


def scan_source(src: str) -> list[tuple[int, str]]:
    """``(line, enclosing function)`` of every ``X[...] = (time.time(), ...)`` store in ``src``."""
    tree = ast.parse(src)
    out: list[tuple[int, str]] = []

    def walk(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if (isinstance(child, ast.Assign) and isinstance(child.value, ast.Tuple) and child.value.elts
                    and _is_time_time(child.value.elts[0])
                    and any(isinstance(t, ast.Subscript) for t in child.targets)):
                out.append((child.lineno, fn))
            walk(child, name)

    walk(tree, "<module>")
    return sorted(out)


def test_scanner_is_live():
    """The stamped-entry shape is reported and the neighbouring safe shapes stay quiet."""
    hit = "import time\n_C = {}\ndef put(k, v):\n    _C[k] = (time.time(), v)\n"
    assert scan_source(hit) == [(4, "put")]
    quiet = (
        "import time\n_C = {}\ndef put(k, v):\n    _C[k] = (time.monotonic(), v)\n",
        "import time\ndef f():\n    t = (time.time(), 1)\n    return t\n",
        "import time\n_C = {}\ndef put(k, v):\n    _C[k] = (v, time.time())\n",
        "import time\n_C = {}\ndef put(k, v):\n    _C[k] = {'ts': time.time()}\n",
    )
    for src in quiet:
        assert scan_source(src) == [], src


def _tree_hits() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in repo_files():
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel or not rel.endswith(".py"):
            continue
        try:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            hits = scan_source(src)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        found.update((rel, fn) for _line, fn in hits)
    return found


def test_no_wall_clock_stamped_cache_entry():
    new = _tree_hits() - set(_ROWS)
    assert not new, f"in-process cache entries stamped with time.time() (use time.monotonic()): {sorted(new)}"


def test_rows_are_exact():
    stale = set(_ROWS) - _tree_hits()
    assert not stale, f"rows that no longer offend, drop them: {sorted(stale)}"


def test_scan_reaches_the_converted_files():
    seen = {relative_posix(p) for p in repo_files()}
    for rel in ("dashboard/routes_personal_vs.py", "dashboard/routes_post_game_rubric.py"):
        assert rel in seen, rel
