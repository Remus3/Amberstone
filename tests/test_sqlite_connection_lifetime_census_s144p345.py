"""S144-P-345 - every production ``sqlite3.connect`` whose close is not visible in its own function is a named, reasoned site.

A sqlite3 connection has no owner but the code that opened it. ``with sqlite3.connect(p) as conn:`` only COMMITS on exit and
never closes (measured on Python 3.14 / SQLite 3.50: ResourceWarning "unclosed database", and on Windows the file handle
lives as long as the connection object, so the database cannot be removed or replaced). A connection returned from a helper
or parked on ``self`` / a thread-local is closed by someone else, or by nobody. S144-P-338..344 pinned the other
process-wide hazards; this is the database-handle half. Measured 2026-11-07 by AST over every tracked production ``.py``
(outside ``tests/``, ``docs/``, any ``/tests/`` directory, ``test_*.py`` files and the vendored ``ops/fleet_kit/``): 130
``sqlite3.connect`` calls, of which 83 close their connection in the function that opened it and 8 sit under
``contextlib.closing`` (both safe, not listed). The other 39 are listed in ``_OPEN_SITES`` by (file, scope, kind):

- ``with-as`` (5 calls in 3 files): the commit-only context manager, the one shape that LEAKS. A ceiling, not an exact set:
  a new one fails; a fixed one passes, so a lane that converts a site to ``contextlib.closing`` (``db_migrate_kda`` is fixed
  on a lane branch not yet landed) does not break the merge. When a row is fixed, drop it here.
- ``factory`` (34 calls in 32 files): a connection that is ``return``-ed, or stored for later use, with no ``.close()`` on it in
  the same function. The CALLER (or the thread / process lifetime) owns the close. Each row says whether the opener is
  read-only (``ro``: the function builds a ``mode=ro`` URI) or write-capable (``rw``); the ``ro`` / ``rw`` tag is checked
  against the function source, so a read-only opener that quietly becomes write-capable fails.
- ``unclosed`` (a one-shot script that never closes) is a ``factory``-shaped row with its own reason.

The factory set is exact: a new unclosed opener fails until it is added with a reason.

Detector: a call to ``sqlite3.connect`` (``import sqlite3`` is the only spelling in the tree; ``from sqlite3 import connect``
and ``connect = sqlite3.connect`` are absent today, so they are a named blind spot, not a live gap). Kind comes from the
call's parent node: a ``with`` item -> ``with-as``; an argument of a call named ``closing`` -> safe; a ``return`` ->
``factory``; an assignment to a name or attribute whose ``<name>.close()`` appears anywhere in the enclosing function ->
safe, else ``factory``; anything else -> ``other`` (must be listed, zero today).

Named blind spots: a ``.close()`` that exists but is skipped on a failure path (no try / finally check), a close in a
DIFFERENT function than the opener for a connection stored on a long-lived object, a connection passed to a callee that
closes it, ``sqlite3.connect`` through an alias, and a file that fails to parse (skipped, as in the sibling censuses).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

_RO_MARKERS = ("mode=ro", "_ro_uri(")

# (file, scope) -> number of with-as calls. A ceiling: may only be lowered.
_WITH_AS_CEILING = {
    ("agents/agent2_backend/db_migrate_kda.py", "ensure_kda_columns"): 1,
    ("agents/agent4_coach_mentor/analyzer.py", "main"): 1,
    ("coaches/adaptation_hint_temporal.py", "day_of_week_analysis"): 1,
    ("coaches/adaptation_hint_temporal.py", "duration_analysis"): 1,
    ("coaches/adaptation_hint_temporal.py", "time_of_day_analysis"): 1,
}

_RO_OPEN = "read-only opener; the caller closes it"
_RO_DB = "read-only opener of the rewind DB; the caller closes it (a missing or locked file answers None)"

# (file, scope) -> (calls, "ro" | "rw", why nobody closes it here).
_FACTORIES = {
    ("agents/agent2_backend/backfill_kda.py", "_open_rewind"): (1, "ro", _RO_DB),
    ("agents/agent2_backend/migration_rewind.py", "_open_rewind"): (1, "ro", _RO_DB),
    ("coaches/adaptation_hint_session.py", "_connect"): (1, "rw", "opener for the session digest; the caller owns the connection, no write is issued through it"),
    ("coaches/champ_pool_recommender.py", "_open"): (1, "rw", "plain-path opener of the rewind DB (a read-only URI would be tighter); the caller closes it, a failure answers None"),
    ("core/draft_elo_db.py", "open_ro"): (1, "ro", _RO_OPEN),
    ("core/duration_winrate.py", "_open_ro"): (1, "ro", _RO_DB),
    ("core/match_db.py", "MatchDB._conn"): (1, "rw", "one connection per thread kept on a thread-local for the process lifetime; the database is the app's own match store"),
    ("core/op_score_curve.py", "_open_ro"): (1, "ro", _RO_DB),
    ("core/ops_panels.py", "_ro_conn"): (1, "ro", _RO_OPEN),
    ("core/patch_impact.py", "_open_ro"): (1, "ro", _RO_DB),
    ("core/perf_curve.py", "_open_ro"): (1, "ro", _RO_DB),
    ("core/personal_build_wr.py", "_connect_ro"): (1, "ro", _RO_OPEN),
    ("core/playstyle_labels.py", "_open_ro"): (1, "ro", _RO_DB),
    ("core/riot_api_cache.py", "RiotApiCache._connect"): (1, "rw", "the cache's own connection, parked on the instance for its lifetime (autocommit, explicit transactions)"),
    ("core/session_hygiene.py", "_open_ro"): (1, "ro", _RO_DB),
    ("core/snowball_elasticity.py", "_open_ro"): (1, "ro", _RO_DB),
    ("dashboard/_context.py", "ro_conn"): (1, "ro", "cached per thread in DB_CONN_LOCAL and reused until the file vanishes; the cache owns the close"),
    ("dashboard/routes_item_wpa.py", "_open_rewind_db_ro"): (1, "ro", _RO_DB),
    ("dashboard/routes_lobby_aux.py", "_connect_rewind_ro"): (1, "ro", _RO_DB),
    ("dashboard/routes_post_game_wpa.py", "_open_rewind_db_ro"): (1, "ro", _RO_DB),
    ("dashboard/routes_replay_events.py", "_open_rewind_db_ro"): (1, "ro", _RO_DB),
    ("dashboard/routes_rune_wpa.py", "_open_rewind_db_ro"): (1, "ro", _RO_DB),
    ("dashboard/routes_skill_wpa.py", "_open_rewind_db_ro"): (1, "ro", _RO_DB),
    ("dashboard/routes_summspell_wpa.py", "_open_rewind_db_ro"): (1, "ro", _RO_DB),
    ("lcu/lcu_postgame_collector.py", "_get_conn"): (1, "rw", "write-capable WAL connection for the collector, shared across threads under _db_lock; closed by the collector's own lifetime"),
    ("lib/rewind_live_writer.py", "_open_db"): (1, "rw", "write-capable WAL connection for the live writer; the caller closes it"),
    ("scripts/build_spell_cast_rates.py", "main"): (1, "rw", "one-shot script: a single read pass, then the process exits; the connection never outlives it"),
    ("scripts/rewind_catchup.py", "open_db"): (1, "rw", "write-capable WAL connection for the catch-up batch job; the caller closes it"),
    ("scripts/rewind_catchup.py", "open_db_readonly"): (1, "ro", _RO_DB),
    ("scripts/rewind_scraper.py", "get_conn"): (1, "rw", "write-capable WAL connection for the scraper batch job; the caller closes it"),
    ("tools/gated_lx01_draft_check.py", "_ro"): (1, "ro", "read-only opener for a one-shot check script"),
    ("tools/gated_lx05_tape_check.py", "_ro"): (1, "ro", "read-only opener for a one-shot check script"),
    ("tools/replay_laning_verdict_validate.py", "_connect_readonly"): (2, "ro", "read-only first, with a documented plain-path fallback for a path a URI cannot name; the caller closes it"),
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _scan(source: str) -> list[tuple[str, str, str]]:
    """``[(scope, kind, access)]`` for each ``sqlite3.connect`` in one module.

    kind is ``with-as`` / ``factory`` / ``other`` for a site that needs a row, ``safe`` for one that closes itself.
    access is ``ro`` when the enclosing function builds a read-only URI, else ``rw``.
    """
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_fn(node: ast.AST) -> ast.AST | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def scope_of(node: ast.AST) -> str:
        names: list[str] = []
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
        return ".".join(reversed(names)) or "module"

    out: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _dotted(node.func) == "sqlite3.connect"):
            continue
        fn = enclosing_fn(node)
        text = ast.get_source_segment(source, fn if fn is not None else node) or ""
        access = "ro" if any(m in text for m in _RO_MARKERS) else "rw"
        parent = parents.get(node)
        if isinstance(parent, ast.withitem):
            kind = "with-as"
        elif isinstance(parent, ast.Call) and (_dotted(parent.func) or "").rsplit(".", 1)[-1] == "closing":
            kind = "safe"
        elif isinstance(parent, ast.Return):
            kind = "factory"
        elif isinstance(parent, ast.Assign) and isinstance(parent.targets[0], (ast.Name, ast.Attribute)):
            name = _dotted(parent.targets[0])
            scope_root = fn if fn is not None else tree
            closed = any(
                isinstance(c, ast.Call) and _dotted(c.func) == f"{name}.close" for c in ast.walk(scope_root)
            )
            kind = "safe" if closed else "factory"
        else:
            kind = "other"
        out.append((scope_of(node), kind, access))
    return sorted(out)


def _production_files():
    return [
        p for p in repo_files(REPO_ROOT, ("*.py",))
        if not relative_posix(p).startswith(_SKIP_PREFIXES)
        and "/tests/" not in relative_posix(p)
        and not p.name.startswith("test_")
    ]


def _measure():
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    rows: dict[tuple[str, str, str, str], int] = {}
    total = 0
    for p in files:
        rel = relative_posix(p)
        try:
            found = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for scope, kind, access in found:
            total += 1
            if kind == "safe":
                continue
            key = (rel, scope, kind, access)
            rows[key] = rows.get(key, 0) + 1
    return rows, total


def test_with_as_connections_never_grow_past_the_ceiling():
    rows, total = _measure()
    assert total > 80, "the walk saw almost no sqlite3.connect, so an empty difference proves nothing"
    found: dict[tuple[str, str], int] = {}
    for (rel, scope, kind, _access), n in rows.items():
        if kind == "with-as":
            found[(rel, scope)] = found.get((rel, scope), 0) + n
    assert found, "no with-as site seen; the detector is blind or every leak was fixed (then retire this test)"
    grew = sorted((k, _WITH_AS_CEILING.get(k, 0), n) for k, n in found.items() if n > _WITH_AS_CEILING.get(k, 0))
    assert not grew, (
        "a `with sqlite3.connect(...) as conn` only commits and never closes: use contextlib.closing "
        f"(key, ceiling, found): {grew}"
    )


def test_every_unclosed_opener_is_a_named_factory():
    rows, _ = _measure()
    found = {(rel, scope): (n, access) for (rel, scope, kind, access), n in rows.items() if kind == "factory"}
    assert len(found) >= 20, "the walk saw almost no factory, so an empty difference proves nothing"
    want = {k: (n, access) for k, (n, access, _why) in _FACTORIES.items()}
    new = sorted(k for k in found if k not in want)
    gone = sorted(k for k in want if k not in found)
    changed = sorted((k, want[k], found[k]) for k in want if k in found and want[k] != found[k])
    assert not new, f"new sqlite3.connect with no close in its function (add it to _FACTORIES with a reason, or close it): {new}"
    assert not gone, f"stale _FACTORIES entry (drop it): {gone}"
    assert not changed, f"call count or ro / rw access moved (key, listed, found): {changed}"


def test_no_connection_is_opened_in_an_unclassified_way():
    rows, _ = _measure()
    other = sorted(k for k in rows if k[2] == "other")
    assert not other, f"sqlite3.connect used in a shape this census cannot classify (assign it to a name and close it): {other}"


def test_every_factory_carries_a_reason_and_a_valid_access_tag():
    assert all(n >= 1 and access in ("ro", "rw") and len(why) > 30 for n, access, why in _FACTORIES.values())
    assert all(n >= 1 for n in _WITH_AS_CEILING.values())


def test_the_detector_flags_each_shape():
    src = (
        "import sqlite3\n"
        "from contextlib import closing\n"
        "def leak(p):\n    with sqlite3.connect(p) as c:\n        c.execute('x')\n"
        "def safe_with(p):\n    with closing(sqlite3.connect(p)) as c:\n        c.execute('x')\n"
        "def safe_close(p):\n    c = sqlite3.connect(p)\n    try:\n        c.execute('x')\n    finally:\n        c.close()\n"
        "def fac(p):\n    return sqlite3.connect(p)\n"
        "def fac_ro(p):\n    return sqlite3.connect('file:' + p + '?mode=ro', uri=True)\n"
        "def parked(self, p):\n    self.c = sqlite3.connect(p)\n"
        "class K:\n    def m(self, p):\n        c = sqlite3.connect(p)\n        return c\n"
        "def other(p):\n    use(sqlite3.connect(p))\n"
    )
    got = {(s, k, a) for s, k, a in _scan(src)}
    assert got == {
        ("leak", "with-as", "rw"),
        ("safe_with", "safe", "rw"),
        ("safe_close", "safe", "rw"),
        ("fac", "factory", "rw"),
        ("fac_ro", "factory", "ro"),
        ("parked", "factory", "rw"),
        ("K.m", "factory", "rw"),
        ("other", "other", "rw"),
    }


def test_the_detector_ignores_look_alikes():
    clean = (
        "import sqlite3, socket\n"
        "x = sqlite3.Row\n"
        "def f(c):\n    return c.connect('h')\n"
        "s = socket.create_connection(('h', 1))\n"
        "t = 'sqlite3.connect(p)'\n"
        "def g(conn: sqlite3.Connection):\n    conn.close()\n"
    )
    assert _scan(clean) == []
