"""S144-P-324 - every execute() whose SQL text is built IN the call is a REVIEWED site, and no function parameter reaches one unreviewed.

``ruff.toml`` does not select S608 (hard-coded SQL expression), so a new ``conn.execute(f"... {x} ...")`` lands
unseen. Measured 2026-11-07 over every tracked non-test ``.py``: 96 S608 hits, and an AST scan finds 80-odd
``execute`` / ``executemany`` / ``executescript`` calls whose first argument is an f-string with a placeholder, a
``+`` / ``%`` concatenation or a ``.format()``. Each was read: what is interpolated is a module constant (a column
list, ``QUARANTINE_TABLE``, ``SOURCE_COLUMN``, ``BUSY_TIMEOUT_MS``), a ``",".join("?" * n)`` placeholder run, a clause
built by a sibling helper from constants (``_exclude_clause``), or a table name taken from an allowlist
(``_mode_table_prefix``). None carries a request or file value into the SQL text; every value is a ``?`` parameter.

Two ratchets, both with a positive control:

1. ``_DYNAMIC_SITES`` pins the NUMBER of dynamic ``execute`` calls per file. A new dynamic statement (or a new file
   with one) fails until its interpolations are read and the count is raised here with the reason; a statement made
   static (parameterised) fails until the count is lowered, so the pin only ever tracks the real tree.
2. A function PARAMETER interpolated into SQL text is the one shape that can carry a caller's string into a
   statement, so each is named in ``_PARAM_INTERPOLATION`` with the proof that every caller passes a literal.

SCOPE: only a call whose FIRST ARGUMENT is itself dynamic (an f-string, a ``+`` / ``%`` chain or ``"...".format()``).
SQL assigned to a variable first (``sql = f"..."; conn.execute(sql)``, about 34 sites in core/draft_elo_db.py,
core/player_gpi.py, scripts/postmortem_analyze.py, tools/rofl_archiver.py, two in tft/rounds/store.py) and SQL built by
a helper (``_upsert_sql``) are NOT seen here; the independent verifier measured them and they are filed as a follow-up.

Nothing here changes behaviour. Fix a hit by binding a ``?`` parameter; only widen a pin after reading the site.
"""
from __future__ import annotations

import ast
import functools
from collections import Counter
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_EXEC = frozenset({"execute", "executemany", "executescript"})

# file -> number of execute calls whose SQL text is built at run time (all read 2026-11-07, none injectable).
_DYNAMIC_SITES = {
    "agents/agent2_backend/backfill_kda.py": 1,
    "agents/agent2_backend/db_migrate_kda.py": 2,
    "agents/agent2_backend/migration_rewind.py": 1,
    "agents/agent2_backend/win_reconcile.py": 1,
    "agents/agent4_coach_mentor/analyzer.py": 1,
    "coaches/adaptation_hint_session.py": 2,
    "coaches/adaptation_hint_temporal.py": 3,
    "coaches/champ_pool_recommender.py": 1,
    "core/ds_calibration_agreement.py": 1,
    "core/live_item_tape_store.py": 6,
    "core/match_db.py": 1,
    "core/pro_match_index.py": 1,
    "core/resolved_wr.py": 1,
    "core/riot_api_cache.py": 1,
    "core/rofl_stats_backfill.py": 2,
    "core/skill_wpa.py": 1,
    "dashboard/builders.py": 1,
    "dashboard/builders_home.py": 3,
    "dashboard/builders_last_match.py": 2,
    "dashboard/routes_adaptive_summoners.py": 1,
    "dashboard/routes_pickban.py": 6,
    "dashboard/routes_replay_events.py": 2,
    "lcu/draft_log.py": 2,
    "lcu/lcu_postgame_collector.py": 3,
    "ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py": 4,
    "scripts/audit_ddragon_items.py": 1,
    "scripts/prune_synthetic_matches.py": 4,
    "scripts/repair_match_db_column_types.py": 3,
    "scripts/repair_tft_match_rows.py": 6,
    "scripts/rewind_dedup_children.py": 6,
    "scripts/rewind_scraper.py": 1,
    "tft/rounds/store.py": 7,
    "tools/backup_irreplaceable.py": 1,
    "tools/ds_cross_eval/probe_champion.py": 2,
    "tools/gated_lx05_tape_check.py": 4,
}

# (file, function, parameter): a parameter interpolated into SQL text, with the proof every caller passes a literal.
_PARAM_INTERPOLATION = {
    # db_migrate_kda._existing_columns: the only caller passes the literal "matches".
    ("agents/agent2_backend/db_migrate_kda.py", "_existing_columns", "table"),
    # win_reconcile._lookup_postgame_result: pg_table comes from the _MODE_TO_POSTGAME_TABLE lookup (None is skipped).
    ("agents/agent2_backend/win_reconcile.py", "_lookup_postgame_result", "pg_table"),
    # resolved_wr._cols: callers pass the literals "matches" and "participants".
    ("core/resolved_wr.py", "_cols", "table"),
    # routes_pickban._query_performance_band: having_sql is the literal "games >= ?" from its one caller.
    ("dashboard/routes_pickban.py", "_query_performance_band", "having_sql"),
    # rewind_dedup_children._cols / _counts: callers pass literals or the EXACT_DEDUP_TABLES / DEDUP_TABLES constants.
    ("scripts/rewind_dedup_children.py", "_cols", "table"),
    ("scripts/rewind_dedup_children.py", "_counts", "table"),
}


def _is_dynamic_sql(arg: ast.expr) -> bool:
    """True when the SQL text is assembled at run time rather than being one literal."""
    if isinstance(arg, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in arg.values)
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):
        # 'a' + 'b' is still one literal; anything with a non-constant operand is built at run time.
        return any(not isinstance(n, ast.Constant) and not isinstance(n, (ast.BinOp, ast.operator))
                   for n in ast.walk(arg))
    return (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format"
            and isinstance(arg.func.value, (ast.Constant, ast.JoinedStr)))


def _names(arg: ast.expr) -> set[str]:
    return {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}


def scan(source: str) -> tuple[int, set[tuple[str, str]]]:
    """(dynamic execute calls, {(function, parameter)} interpolated into the SQL text) for one module."""
    tree = ast.parse(source)
    count = 0
    params: set[tuple[str, str]] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        own = {a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)} - {"self", "cls"}
        # a nested def is visited on its own turn; its own calls must not be charged to the outer function
        nested = {id(c) for n in ast.walk(fn) if n is not fn
                  and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for c in ast.walk(n)}
        for node in ast.walk(fn):
            if id(node) in nested or not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr in _EXEC and node.args):
                continue
            if _is_dynamic_sql(node.args[0]):
                count += 1
                params.update((fn.name, p) for p in sorted(_names(node.args[0]) & own))
    # module-level and class-body statements are not inside a function; count them too
    inner = {id(c) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             for c in ast.walk(n)}
    for node in ast.walk(tree):
        if (id(node) not in inner and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _EXEC and node.args and _is_dynamic_sql(node.args[0])):
            count += 1
    return count, params


def _is_test_code(rel: str) -> bool:
    return (rel.startswith("tests/") or "/tests/" in rel or rel.startswith("agents/agent3_testing/")
            or rel.rsplit("/", 1)[-1].startswith("test_"))


def _production_files() -> list[str]:
    rels = sorted({relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))})
    return [r for r in rels if not _is_test_code(r)]


@functools.lru_cache(maxsize=1)
def _measure() -> tuple[Counter, frozenset[tuple[str, str, str]]]:
    counts: Counter = Counter()
    params: set[tuple[str, str, str]] = set()
    for rel in _production_files():
        try:
            n, ps = scan((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if n:
            counts[rel] = n
        params.update((rel, fn, p) for fn, p in ps)
    return counts, frozenset(params)


def test_the_walk_sees_the_production_tree():
    files = _production_files()
    assert len(files) > 800, "the tracked-file walk returned almost nothing"
    assert "core/match_db.py" in files and not any(_is_test_code(f) for f in files)
    assert _is_test_code("agents/agent3_testing/suite/test_win_reconcile.py")


def test_dynamic_sql_sites_are_the_reviewed_set():
    counts, _ = _measure()
    new = {f: n for f, n in counts.items() if n > _DYNAMIC_SITES.get(f, 0)}
    gone = {f: (_DYNAMIC_SITES[f], counts.get(f, 0)) for f in _DYNAMIC_SITES if counts.get(f, 0) < _DYNAMIC_SITES[f]}
    assert not new, (
        "a dynamic execute() site is not in the reviewed set: read what it interpolates (a constant, a "
        f"'?' run or an allowlisted name, never a caller's string) and raise the pin: {new}"
    )
    assert not gone, f"a pinned site is now static or removed: lower the pin to the measured count: {gone}"


def test_a_function_parameter_reaches_sql_text_only_where_reviewed():
    _, params = _measure()
    unreviewed = sorted(params - _PARAM_INTERPOLATION)
    stale = sorted(_PARAM_INTERPOLATION - params)
    assert not unreviewed, (
        f"a function parameter is interpolated into SQL text: bind a '?' parameter, or prove every caller passes "
        f"a literal and name it in _PARAM_INTERPOLATION: {unreviewed}"
    )
    assert not stale, f"a reviewed parameter interpolation no longer exists: drop it: {stale}"


# -- positive controls: the scanner must fire on each dynamic shape and stay quiet on a static one --------------------

@pytest.mark.parametrize("source, want", [
    ("def f(c, t):\n    c.execute(f'SELECT 1 FROM {t}')\n", (1, {("f", "t")})),
    ("def f(c, t):\n    c.execute('SELECT 1 FROM ' + t)\n", (1, {("f", "t")})),
    ("def f(c, t):\n    c.execute('SELECT 1 FROM %s' % t)\n", (1, {("f", "t")})),
    ("def f(c, t):\n    c.executemany('SELECT 1 FROM {}'.format(t), [])\n", (1, {("f", "t")})),
    ("def f(c, t):\n    c.executescript(f'DROP TABLE {t}')\n", (1, {("f", "t")})),
    ("async def f(c, t):\n    c.execute(f'SELECT {t}')\n", (1, {("f", "t")})),
    ("T = 'x'\n\n\ndef f(c):\n    c.execute(f'SELECT 1 FROM {T}')\n", (1, set())),
    ("def f(c):\n    c.execute(\"SELECT 1\" + \" FROM t\")\n", (0, set())),
    ("def f(c, t):\n    c.execute('SELECT ? FROM t', (t,))\n", (0, set())),
    ("def f(c):\n    c.execute(f'SELECT 1')\n", (0, set())),
    ("class K:\n    def m(self, c, t):\n        c.execute(f'SELECT {t}')\n", (1, {("m", "t")})),
])
def test_scanner_positive_and_negative_controls(source, want):
    assert scan(source) == want


def test_a_nested_function_is_charged_once_to_itself():
    src = ("def outer(c, a):\n    def inner(c, b):\n        c.execute(f'SELECT {b}')\n    inner(c, 1)\n")
    assert scan(src) == (1, {("inner", "b")})


def test_the_pins_name_real_tracked_files():
    tracked = set(_production_files())
    assert sorted(f for f in _DYNAMIC_SITES if f not in tracked) == []
    assert sorted(f for f, _, _ in _PARAM_INTERPOLATION if f not in tracked) == []
    assert all(isinstance(Path(f), Path) for f in _DYNAMIC_SITES)
