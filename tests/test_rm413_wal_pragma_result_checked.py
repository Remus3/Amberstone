"""RM-413: every ``PRAGMA journal_mode=WAL`` site must READ the mode SQLite
adopted and WARN (never raise) when it is not ``wal``.

THE DEFECT
----------
``PRAGMA journal_mode=WAL`` is a query: SQLite answers with the journal mode
it actually settled on. Eight sites discarded that row, so a database that
silently fell back to rollback journalling (network share, read-only dir, no
shared-memory support) broke each module's concurrency claim with no signal.
RM-233 fixed the same root cause in core/match_db.py; this row carries its
shape - read the row, compare case-insensitively to ``wal``, log a WARNING -
to the remaining eight.

WHAT IS PROVEN HERE, AND WHAT IS NOT
------------------------------------
* The EMIT branch is exercised against REAL SQLite on every OS: an in-memory
  database answers ``memory`` to the pragma, a genuinely non-WAL answer. That
  is not the network-share fallback itself (no such filesystem exists in CI),
  but it is the same code path fed a real non-``wal`` row.
* The NON-emit branch is exercised against a real on-disk database, which is
  what keeps the emit assertion from being satisfiable by an always-warn site.
* A proxied connection feeds ``WAL`` (upper case - must NOT warn), ``delete``
  and a missing row (both must warn), pinning the comparison itself.
* A static guard fails on any non-test module that executes a journal_mode
  pragma as a bare statement, with a positive control proving it detects one.
* RM-457 made that matcher stricter: a journal_mode pragma through
  ``executescript`` (which returns no rows at all), one built as an f-string,
  and one assigned only to ``_`` are all findings. The real-tree scan keeps its
  site floor, and a control proves an EMPTY enumeration fails it.
* RM-468 added five more: a ``for`` target that binds only ``_``, a walrus into
  ``_`` in an ``if`` / ``while`` test, an f-string replacement under an
  IDENTITY conversion or format spec, a replacement built by ``+``, and SQL
  concatenated with ``+``. Every fold was measured against the project
  interpreter first; a conversion or spec that could change the text, and a
  ``+`` with a non-str operand, are REFUSED rather than modelled.
"""
from __future__ import annotations

import ast
import logging
import re
import sqlite3
from pathlib import Path

import pytest

import agents.agent2_backend.db_schema as a2_schema
import core.riot_api_cache as riot_api_cache
import lcu.lcu_postgame_collector as postgame
import lib.rewind_live_writer as rewind_live_writer
import modules.cache_engine as cache_engine
import scripts.rewind_catchup as rewind_catchup
import scripts.rewind_scraper as rewind_scraper
from tests import _repo_walk

_REAL_CONNECT = sqlite3.connect
_JOURNAL_RE = re.compile(r"journal_mode\s*=", re.IGNORECASE)


# -- the eight sites -------------------------------------------------------------

def _open_riot_api_cache(monkeypatch, db):
    return riot_api_cache.RiotApiCache(db_path=db)._connect()


def _open_rewind_live_writer(monkeypatch, db):
    monkeypatch.setattr(rewind_live_writer, "DB_PATH", db)
    return rewind_live_writer._open_db()


def _open_a2_open_db(monkeypatch, db):
    monkeypatch.setattr(a2_schema, "db_path", lambda mode: db)
    return a2_schema.open_db("aram")


def _open_a2_init_mode(monkeypatch, db):
    monkeypatch.setattr(a2_schema, "db_path", lambda mode: db)
    a2_schema.init_mode("aram")
    return None


def _open_postgame(monkeypatch, db):
    monkeypatch.setattr(postgame, "_DB_PATH", db)
    return postgame._get_conn()


def _open_cache_engine(monkeypatch, db):
    cache_engine.CacheEngine(db)
    return None


def _open_rewind_catchup(monkeypatch, db):
    monkeypatch.setattr(rewind_catchup, "DB_PATH", db)
    return rewind_catchup.open_db()


def _open_rewind_scraper(monkeypatch, db):
    monkeypatch.setattr(rewind_scraper, "DB_PATH", db)
    return rewind_scraper.get_conn()


SITES = [
    ("core/riot_api_cache", _open_riot_api_cache),
    ("lib/rewind_live_writer", _open_rewind_live_writer),
    ("agent2_backend/db_schema.open_db", _open_a2_open_db),
    ("agent2_backend/db_schema.init_mode", _open_a2_init_mode),
    ("lcu/lcu_postgame_collector", _open_postgame),
    ("modules/cache_engine", _open_cache_engine),
    ("scripts/rewind_catchup", _open_rewind_catchup),
    ("scripts/rewind_scraper", _open_rewind_scraper),
]
_IDS = [name for name, _ in SITES]
_OPENERS = [fn for _, fn in SITES]


_PER_OPERATION_MODULES = (riot_api_cache, postgame, cache_engine)


@pytest.fixture(autouse=True)
def _reset_wal_warned():
    """Per-operation openers warn once per db path per process; start clean."""
    for mod in _PER_OPERATION_MODULES:
        seen = getattr(mod, "_WAL_WARNED", None)
        if seen is not None:
            seen.clear()
    yield
    for mod in _PER_OPERATION_MODULES:
        seen = getattr(mod, "_WAL_WARNED", None)
        if seen is not None:
            seen.clear()


def _journal_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING and "journal_mode" in r.getMessage()]


def _close(conn) -> None:
    if conn is not None:
        conn.close()


# -- real SQLite -----------------------------------------------------------------

@pytest.mark.parametrize("opener", _OPENERS, ids=_IDS)
def test_real_non_wal_answer_warns_and_does_not_raise(monkeypatch, caplog, opener):
    """``:memory:`` answers 'memory' on every OS - a real non-WAL row."""
    caplog.set_level(logging.WARNING)
    _close(opener(monkeypatch, Path(":memory:")))
    warnings = _journal_warnings(caplog)
    assert len(warnings) >= 1, "non-wal journal mode was not reported"
    assert all("'memory'" in w for w in warnings), warnings


@pytest.mark.parametrize("opener", _OPENERS, ids=_IDS)
def test_real_wal_answer_is_silent(tmp_path, monkeypatch, caplog, opener):
    """An on-disk database really adopts WAL - the site must NOT warn."""
    caplog.set_level(logging.WARNING)
    db = tmp_path / "probe.db"
    _close(opener(monkeypatch, db))
    probe = _REAL_CONNECT(db)
    try:
        adopted = probe.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        probe.close()
    assert adopted.lower() == "wal", "precondition: this filesystem must support WAL"
    assert _journal_warnings(caplog) == []


# -- per-operation openers: warn ONCE per db path, not on every call ----------------

def _twice_riot_api_cache(monkeypatch, db):
    cache = riot_api_cache.RiotApiCache(db_path=db)
    for _ in range(2):
        cache._connect().close()


def _twice_postgame(monkeypatch, db):
    monkeypatch.setattr(postgame, "_DB_PATH", db)
    for _ in range(2):
        postgame._get_conn().close()


def _twice_cache_engine(monkeypatch, db):
    engine = cache_engine.CacheEngine(db)  # construction opens once already
    for _ in range(2):
        engine._conn().close()


@pytest.mark.parametrize("twice", [_twice_riot_api_cache, _twice_postgame, _twice_cache_engine],
                         ids=["core/riot_api_cache", "lcu/lcu_postgame_collector",
                              "modules/cache_engine"])
def test_per_operation_opener_warns_once_per_db(monkeypatch, caplog, twice):
    caplog.set_level(logging.WARNING)
    twice(monkeypatch, Path(":memory:"))
    assert len(_journal_warnings(caplog)) == 1, _journal_warnings(caplog)


# -- proxied answers: pin the comparison -------------------------------------------

class _Rows:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _PragmaProxy:
    """Real in-memory connection whose journal_mode pragma answers ``row``."""

    def __init__(self, real, row, fired):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_row", row)
        object.__setattr__(self, "_fired", fired)

    def execute(self, sql, *args):
        if _JOURNAL_RE.search(sql):
            self._fired.append(sql)
            return _Rows(self._row)
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


@pytest.mark.parametrize("row, should_warn, shown", [
    (("WAL",), False, None),
    (("delete",), True, "'delete'"),
    (None, True, "'unknown'"),
], ids=["WAL-uppercase", "delete", "no-row"])
@pytest.mark.parametrize("opener", _OPENERS, ids=_IDS)
def test_answer_comparison(tmp_path, monkeypatch, caplog, opener, row, should_warn, shown):
    fired: list[str] = []

    def _connect(*args, **kwargs):
        kwargs.pop("check_same_thread", None)
        return _PragmaProxy(_REAL_CONNECT(":memory:", check_same_thread=False, **kwargs),
                            row, fired)

    monkeypatch.setattr(sqlite3, "connect", _connect)
    caplog.set_level(logging.WARNING)
    _close(opener(monkeypatch, tmp_path / "unused.db"))
    assert fired, "journal_mode pragma never reached the proxy - test would be vacuous"
    warnings = _journal_warnings(caplog)
    if should_warn:
        assert warnings and all(shown in w for w in warnings), warnings
    else:
        assert warnings == []


# -- static guard: no discarded journal_mode result anywhere ------------------------

# ``executescript`` never yields the pragma's answer at all, so ANY statement
# using it for a journal_mode pragma is a discard, not only a bare one (RM-457).
_EXECUTE_ATTRS = frozenset({"execute", "executescript"})


def _literal_sql(arg: ast.expr) -> str | None:
    """The SQL text of a string literal, or of an f-string's literal parts.

    An f-string is reduced to its constant fragments joined with a placeholder,
    so ``f"PRAGMA journal_mode={mode}"`` still reads ``journal_mode=``.

    RM-468: a ``+`` of two str-yielding operands is folded, because CPython
    concatenates them at run time with no other effect - MEASURED on the
    project interpreter, ``'PRAGMA ' + 'journal_mode=WAL'`` is exactly
    ``'PRAGMA journal_mode=WAL'``. If EITHER operand is not str-yielding the
    expression is refused (``None``), never guessed: CPython raises
    ``TypeError`` there, and a matcher that invented a value would be modelling
    something the interpreter never produces. ``*`` and every other operator
    stay refused for the same reason.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr):
        return "".join(_fstring_part(v) for v in arg.values)
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        left = _literal_sql(arg.left)
        right = _literal_sql(arg.right)
        if left is not None and right is not None:
            return left + right
    return None


# RM-468: ``!s`` on a str is ``str(x)`` - the value itself. ``-1`` is "no
# conversion". ``!r`` (114) and ``!a`` (97) both wrap the text in quotes, so
# they are NOT foldable and stay out of this set.
_IDENTITY_CONVERSIONS = frozenset({-1, ord("s")})


def _spec_is_identity(spec: ast.expr | None) -> bool:
    """True when a format spec cannot change a str value's text.

    MEASURED on CPython 3.14.4: ``format('journal_mode', '')`` and
    ``format('journal_mode', 's')`` both return ``'journal_mode'`` unchanged,
    while ``format('journal_mode', '>20')`` pads it. Only the first two are
    treated as identity; anything else - including a spec built from a runtime
    value - is refused.
    """
    if spec is None:
        return True
    if not isinstance(spec, ast.JoinedStr):
        return False
    text = ""
    for piece in spec.values:
        if not (isinstance(piece, ast.Constant) and isinstance(piece.value, str)):
            return False
        text += piece.value
    return text in ("", "s")


def _fstring_part(part: ast.expr) -> str:
    """One f-string component as SQL text.

    RM-465: a replacement field that formats a string CONSTANT (or a nested
    f-string) with no conversion and no format spec contributes its own text,
    so ``f"PRAGMA {'journal_mode'}=WAL"`` reads ``journal_mode=``. Anything
    else is a placeholder, as before.

    RM-468: that also holds under an IDENTITY conversion or format spec
    (``!s``, ``:s``, ``:``), each measured to reproduce the value verbatim, and
    for a value built by ``+`` from constants. A conversion or spec that could
    change the text stays a placeholder.
    """
    if isinstance(part, ast.Constant) and isinstance(part.value, str):
        return part.value
    if (isinstance(part, ast.FormattedValue)
            and part.conversion in _IDENTITY_CONVERSIONS
            and _spec_is_identity(part.format_spec)):
        inner = _literal_sql(part.value)
        if inner is not None:
            return inner
    return "?"


def _binds_only_underscore(target: ast.expr) -> bool:
    """True when every name the target binds is ``_`` (RM-465: ``_, = ...``,
    ``[_] = ...``, ``*_, = ...``)."""
    if isinstance(target, ast.Name):
        return target.id == "_"
    if isinstance(target, ast.Starred):
        return _binds_only_underscore(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return bool(target.elts) and all(_binds_only_underscore(e) for e in target.elts)
    return False


def _is_discard_statement(node: ast.AST) -> ast.expr | None:
    """The value expression of a statement that throws its result away.

    A bare expression statement, or an assignment whose every target binds only
    ``_`` (RM-457: ``_ = conn.execute(...)`` names the result only to drop it;
    RM-465: the annotated ``_: T = ...`` and unpacking ``_, = ...`` spellings).

    RM-468 adds two statement positions that never bind the answer either: a
    ``for`` whose target binds only ``_``, and an ``if`` / ``while`` whose test
    is a walrus into ``_``. Only the iterated / tested expression is returned,
    so nothing in the loop or branch BODY is attributed to this statement. The
    bare ``(_ := ...)`` statement needs no rule of its own - it is an
    ``ast.Expr`` and the first branch above already reports it.
    """
    if isinstance(node, ast.Expr):
        return node.value
    if (isinstance(node, ast.Assign) and node.targets
            and all(_binds_only_underscore(t) for t in node.targets)):
        return node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None and _binds_only_underscore(node.target):
        return node.value
    if isinstance(node, ast.For) and _binds_only_underscore(node.target):
        return node.iter
    if (isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.NamedExpr)
            and _binds_only_underscore(node.test.target)):
        return node.test.value
    return None


def _journal_pragma_call(sub: ast.AST) -> bool:
    if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in _EXECUTE_ATTRS and sub.args):
        return False
    sql = _literal_sql(sub.args[0])
    return sql is not None and bool(_JOURNAL_RE.search(sql))


def _discarded_journal_pragmas(source: str) -> list[int]:
    """Line numbers of statements whose journal_mode answer is dropped."""
    hits: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        # executescript returns no rows (measured: fetchall() == []), so a
        # journal_mode pragma through it is a discard however it is spelled.
        if _journal_pragma_call(node) and node.func.attr == "executescript":
            hits.add(node.lineno)
            continue
        value = _is_discard_statement(node)
        if value is None:
            continue
        if any(_journal_pragma_call(sub) for sub in ast.walk(value)):
            hits.add(node.lineno)
    return sorted(hits)


def test_guard_positive_control():
    bad = (
        "conn.execute('PRAGMA journal_mode=WAL')\n"
        "conn.execute(\"PRAGMA JOURNAL_MODE = wal\").fetchone()\n"
    )
    assert _discarded_journal_pragmas(bad) == [1, 2]
    good = (
        "row = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n"
        "conn.execute('PRAGMA synchronous=NORMAL')\n"
        "conn.execute('SELECT journal_mode FROM t')\n"
    )
    assert _discarded_journal_pragmas(good) == []


# RM-457: three call shapes the RM-413 matcher did not see. Each positive
# control below is paired with a negative control that differs only in that the
# answer is actually kept, so a matcher that flags everything cannot pass.
@pytest.mark.parametrize("bad, good", [
    (
        "conn.executescript('PRAGMA journal_mode=WAL;')\n",
        "row = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
    ),
    (
        "cur = conn.executescript('PRAGMA journal_mode=WAL;')\n",
        "cur = conn.execute('PRAGMA journal_mode=WAL')\n",
    ),
    (
        "conn.execute(f'PRAGMA journal_mode={mode}')\n",
        "row = conn.execute(f'PRAGMA journal_mode={mode}').fetchone()\n",
    ),
    (
        "_ = conn.execute('PRAGMA journal_mode=WAL')\n",
        "jm = conn.execute('PRAGMA journal_mode=WAL')\n",
    ),
    (
        "_ = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
        "jm_row = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
    ),
], ids=["executescript-bare", "executescript-assigned", "f-string",
        "underscore-cursor", "underscore-row"])
def test_guard_positive_control_rm457_shapes(bad, good):
    assert _discarded_journal_pragmas(bad) == [1], bad
    assert _discarded_journal_pragmas(good) == [], good


# RM-465: three more shapes the RM-457 matcher did not see - an annotated
# discard, a tuple / list / starred target that binds only ``_``, and a pragma
# NAME built inside an f-string from constant parts. Each positive control is
# paired with a negative control that keeps the answer.
_RM465_SHAPES = [
    (
        "_: object = conn.execute('PRAGMA journal_mode=WAL')\n",
        "jm: object = conn.execute('PRAGMA journal_mode=WAL')\n",
    ),
    (
        "_: tuple = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
        "row: tuple = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
    ),
    (
        "_, = conn.execute('PRAGMA journal_mode=WAL')\n",
        "mode, = conn.execute('PRAGMA journal_mode=WAL')\n",
    ),
    (
        "(_,) = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
        "(mode,) = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
    ),
    (
        "[_] = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
        "[mode] = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
    ),
    (
        "*_, = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
        "*modes, = conn.execute('PRAGMA journal_mode=WAL').fetchone()\n",
    ),
    (
        "conn.execute(f\"PRAGMA {'journal_mode'}=WAL\")\n",
        "row = conn.execute(f\"PRAGMA {'journal_mode'}=WAL\").fetchone()\n",
    ),
    (
        "conn.execute(f\"PRAGMA journal{'_mode'} = {mode}\")\n",
        "row = conn.execute(f\"PRAGMA journal{'_mode'} = {mode}\").fetchone()\n",
    ),
    (
        "conn.execute(f\"PRAGMA {f'{\"journal\"}_mode'}=WAL\")\n",
        "row = conn.execute(f\"PRAGMA {f'{\"journal\"}_mode'}=WAL\").fetchone()\n",
    ),
]
_RM465_IDS = ["annotated-cursor", "annotated-row", "tuple-target", "paren-tuple-target", "list-target",
              "starred-target", "fstring-name", "fstring-split-name", "fstring-nested-name"]


@pytest.mark.parametrize("bad, good", _RM465_SHAPES, ids=_RM465_IDS)
def test_guard_positive_control_rm465_shapes(bad, good):
    assert _discarded_journal_pragmas(bad) == [1], bad
    assert _discarded_journal_pragmas(good) == [], good


@pytest.mark.parametrize("bad", [b for b, _ in _RM465_SHAPES], ids=_RM465_IDS)
def test_scan_reports_each_rm465_shape_through_the_real_path(bad):
    padding = [(f"core/pad{i}.py", "row = c.execute('PRAGMA journal_mode=WAL').fetchone()\n")
               for i in range(_SITE_FLOOR)]
    sites, offenders = _scan([*padding, ("core/seeded.py", bad)])
    assert offenders == ["core/seeded.py:1"]
    with pytest.raises(AssertionError, match="discarded at"):
        _assert_scan(sites, offenders)


def test_scan_prefilter_is_case_blind():
    """RM-465: a file that spells the pragma only in upper case is scanned."""
    padding = [(f"core/pad{i}.py", "row = c.execute('PRAGMA journal_mode=WAL').fetchone()\n")
               for i in range(_SITE_FLOOR)]
    sites, offenders = _scan([*padding, ("core/upper.py", "conn.execute('PRAGMA JOURNAL_MODE=WAL')\n")])
    assert offenders == ["core/upper.py:1"]


def test_guard_rm465_negative_controls_stay_clean():
    """A partly-kept target, an annotation with no value and a non-journal
    f-string pragma name are not findings."""
    clean = (
        "_, mode = conn.execute('PRAGMA journal_mode=WAL').fetchone(), 1\n"
        "_: object\n"
        "_: object = conn.execute(f\"PRAGMA {'synchronous'}=NORMAL\")\n"
        "(_, _), mode = ((1, 2), conn.execute('PRAGMA journal_mode=WAL').fetchone())\n"
    )
    assert _discarded_journal_pragmas(clean) == []


@pytest.mark.parametrize("src", [
    "() = conn.execute('PRAGMA journal_mode=WAL')\n",
    "[] = conn.execute('PRAGMA journal_mode=WAL').fetchall()\n",
], ids=["empty-tuple-target", "empty-list-target"])
def test_guard_rm465_empty_unpacking_target_is_not_a_discard(src):
    """An EMPTY target binds no name at all, so it is not an all-``_`` target.
    Unpacking a row into it raises ValueError at run time - loud, not a silent
    discard. Pins the ``bool(target.elts)`` check: without it ``all([])`` is
    True and these read as discards."""
    assert _discarded_journal_pragmas(src) == []


def test_guard_rm457_negative_controls_stay_clean():
    """Non-journal pragmas and non-pragma f-strings are not findings."""
    clean = (
        "conn.executescript('PRAGMA synchronous=NORMAL; CREATE TABLE t(x);')\n"
        "_ = conn.execute(f'PRAGMA synchronous={level}')\n"
        "conn.execute(f'SELECT {col} FROM t')\n"
    )
    assert _discarded_journal_pragmas(clean) == []


# RM-468: five more shapes the RM-465 matcher did not see - a loop target that
# binds only ``_``, a walrus into ``_`` in an ``if`` / ``while`` test, an
# f-string replacement carrying an identity conversion or format spec, a
# replacement that concatenates constants, and SQL built by ``+`` outright.
# Each positive control is paired with a negative control that keeps the answer.
#
# The bare-statement walrus ``(_ := conn.execute(...))`` is NOT listed: it is an
# ``ast.Expr`` and the RM-413 matcher already reports it (measured). Only the
# test-position spellings were missed.
_RM468_SHAPES = [
    (
        "for _ in conn.execute('PRAGMA journal_mode=WAL'):\n    pass\n",
        "for mode in conn.execute('PRAGMA journal_mode=WAL'):\n    pass\n",
    ),
    (
        "for (_,) in conn.execute('PRAGMA journal_mode=WAL'):\n    pass\n",
        "for (mode,) in conn.execute('PRAGMA journal_mode=WAL'):\n    pass\n",
    ),
    (
        "if (_ := conn.execute('PRAGMA journal_mode=WAL')):\n    pass\n",
        "if (mode := conn.execute('PRAGMA journal_mode=WAL').fetchone()):\n    pass\n",
    ),
    (
        "while (_ := conn.execute('PRAGMA journal_mode=WAL')):\n    pass\n",
        "while (mode := conn.execute('PRAGMA journal_mode=WAL')):\n    pass\n",
    ),
    (
        "conn.execute(f\"PRAGMA {'journal_mode'!s}=WAL\")\n",
        "row = conn.execute(f\"PRAGMA {'journal_mode'!s}=WAL\").fetchone()\n",
    ),
    (
        "conn.execute(f\"PRAGMA {'journal_mode':s}=WAL\")\n",
        "row = conn.execute(f\"PRAGMA {'journal_mode':s}=WAL\").fetchone()\n",
    ),
    (
        "conn.execute(f\"PRAGMA {'journal_mode':}=WAL\")\n",
        "row = conn.execute(f\"PRAGMA {'journal_mode':}=WAL\").fetchone()\n",
    ),
    (
        "conn.execute(f\"PRAGMA {'journal' + '_mode'}=WAL\")\n",
        "row = conn.execute(f\"PRAGMA {'journal' + '_mode'}=WAL\").fetchone()\n",
    ),
    (
        "conn.execute('PRAGMA ' + 'journal_mode=WAL')\n",
        "row = conn.execute('PRAGMA ' + 'journal_mode=WAL').fetchone()\n",
    ),
    (
        "conn.execute('PRAGMA ' + 'journal' + '_mode=WAL')\n",
        "row = conn.execute('PRAGMA ' + 'journal' + '_mode=WAL').fetchone()\n",
    ),
]
_RM468_IDS = ["for-target", "for-tuple-target", "walrus-if", "walrus-while",
              "conversion-s", "spec-s", "spec-empty", "fstring-concat",
              "sql-concat", "sql-concat-chain"]


@pytest.mark.parametrize("bad, good", _RM468_SHAPES, ids=_RM468_IDS)
def test_guard_positive_control_rm468_shapes(bad, good):
    assert _discarded_journal_pragmas(bad) == [1], bad
    assert _discarded_journal_pragmas(good) == [], good


def test_guard_rm468_unfoldable_conversion_or_spec_stays_a_placeholder():
    """A conversion or format spec that CHANGES the text is refused, not folded.

    MEASURED on CPython 3.14.4 (the project interpreter), each printed verbatim:

    * ``f"PRAGMA {'journal_mode'!r}=WAL"`` -> ``PRAGMA 'journal_mode'=WAL``
    * ``f"PRAGMA {'journal_mode'!a}=WAL"`` -> ``PRAGMA 'journal_mode'=WAL``
    * ``f"PRAGMA {'journal_mode':>20}=WAL"`` -> ``PRAGMA         journal_mode=WAL``

    None of the three is the text the matcher would have inlined, so the
    replacement stays a placeholder. The guard refuses rather than models a
    value it cannot reproduce exactly.
    """
    clean = (
        "conn.execute(f\"PRAGMA {'journal_mode'!r}=WAL\")\n"
        "conn.execute(f\"PRAGMA {'journal_mode'!a}=WAL\")\n"
        "conn.execute(f\"PRAGMA {'journal_mode':>20}=WAL\")\n"
    )
    assert _discarded_journal_pragmas(clean) == []


def test_guard_rm468_non_string_concatenation_is_refused():
    """Only a ``+`` whose BOTH sides yield str text is folded.

    READ WHAT EACH LINE ACTUALLY PINS - three of the four do NOT discriminate a
    fold POLICY, and an earlier draft of this docstring claimed they did.
    ``'PRAGMA ' + journal_mode_name``, ``f"PRAGMA {'journal' + 1}=WAL"`` and
    ``'PRAGMA journal' * 2`` carry no spelling of ``journal_mode=``, and NO fold
    policy over them - refusing, inlining a guess, or dropping the operand -
    produces text the ``_JOURNAL_RE`` would match. So what they pin is that the
    matcher REACHES A VERDICT on an expression it cannot reproduce: it returns
    cleanly instead of raising, and instead of crediting the file on the strength
    of the bare word ``journal`` that got it past the pre-filter. They kill a
    matcher that crashes or that goes SQL-blind, not one whose arithmetic is
    wrong.

    The fourth line, ``'PRAGMA ' + 'synchronous=NORMAL'``, is the one that pins
    the policy itself: both operands are str, so the RM-468 fold DOES fire, and
    the folded text must still read as a non-journal pragma. It is the paired
    negative control for the ``sql-concat`` positive above.

    The refusal is nonetheless the correct behaviour, MEASURED on CPython 3.14.4:
    ``'a' + 1`` raises ``TypeError: can only concatenate str (not "int") to
    str``, and ``'PRAGMA journal' * 2`` yields ``'PRAGMA journalPRAGMA
    journal'``. Neither is a value the matcher may invent - it just happens that
    inventing one here would not change this row's verdict.
    """
    clean = (
        "conn.execute('PRAGMA ' + journal_mode_name)\n"
        "conn.execute(f\"PRAGMA {'journal' + 1}=WAL\")\n"
        "conn.execute('PRAGMA journal' * 2)\n"
        "conn.execute('PRAGMA ' + 'synchronous=NORMAL')\n"
    )
    assert _discarded_journal_pragmas(clean) == []


def test_guard_rm468_partly_kept_loop_and_walrus_targets_stay_clean():
    """A loop target that binds a real name alongside ``_``, and a walrus that
    binds a real name, both keep the answer - neither is a finding."""
    clean = (
        "for _, mode in conn.execute('PRAGMA journal_mode=WAL'):\n    pass\n"
        "if (row := conn.execute('PRAGMA journal_mode=WAL').fetchone()):\n    pass\n"
        "for _ in conn.execute('PRAGMA synchronous=NORMAL'):\n    pass\n"
    )
    assert _discarded_journal_pragmas(clean) == []


_SITE_FLOOR = 9  # the RM-233 site plus the eight RM-413 sites


def _scan(files) -> tuple[int, list[str]]:
    """(journal_mode sites reached, offenders) over ``(rel, text)`` pairs."""
    offenders = []
    checked_sites = 0
    for rel, text in files:
        if "tests" in rel.split("/"):
            continue
        # RM-465: the pre-filter is case-blind and needs only "journal", so a
        # file spelling JOURNAL_MODE or splitting the name across f-string
        # fields still reaches the matcher.
        if "journal" not in text.lower():
            continue
        checked_sites += len(_JOURNAL_RE.findall(text))
        try:
            lines = _discarded_journal_pragmas(text)
        except SyntaxError:
            continue
        offenders.extend(f"{rel}:{n}" for n in lines)
    return checked_sites, offenders


def _assert_scan(checked_sites: int, offenders: list[str]) -> None:
    assert checked_sites >= _SITE_FLOOR, (
        f"scan reached only {checked_sites} journal_mode sites")
    assert offenders == [], f"journal_mode result discarded at: {offenders}"


def test_scan_floor_bites_on_an_empty_enumeration():
    """An empty universe must FAIL the guard, not pass it vacuously."""
    with pytest.raises(AssertionError, match="scan reached only 0"):
        _assert_scan(*_scan([]))


@pytest.mark.parametrize("src", [
    "conn.executescript('PRAGMA journal_mode=WAL;')\n",
    "conn.execute(f'PRAGMA journal_mode={m}')\n",
    "_ = conn.execute('PRAGMA journal_mode=WAL')\n",
], ids=["executescript", "f-string", "underscore"])
def test_scan_reports_each_rm457_shape_through_the_real_path(src):
    """A seeded file carrying the shape reaches offenders via _scan itself."""
    padding = [(f"core/pad{i}.py", "row = c.execute('PRAGMA journal_mode=WAL').fetchone()\n")
               for i in range(_SITE_FLOOR)]
    sites, offenders = _scan([*padding, ("core/seeded.py", src)])
    assert offenders == ["core/seeded.py:1"]
    with pytest.raises(AssertionError, match="discarded at"):
        _assert_scan(sites, offenders)


@pytest.mark.parametrize("bad", [b for b, _ in _RM468_SHAPES], ids=_RM468_IDS)
def test_scan_reports_each_rm468_shape_through_the_real_path(bad):
    padding = [(f"core/pad{i}.py", "row = c.execute('PRAGMA journal_mode=WAL').fetchone()\n")
               for i in range(_SITE_FLOOR)]
    sites, offenders = _scan([*padding, ("core/seeded.py", bad)])
    assert offenders == ["core/seeded.py:1"]
    with pytest.raises(AssertionError, match="discarded at"):
        _assert_scan(sites, offenders)


def test_no_module_discards_the_journal_mode_answer():
    _repo_walk.self_check()
    rels = ((_repo_walk.relative_posix(p), p) for p in _repo_walk.iter_repo_files())
    files = ((rel, p.read_text(encoding="utf-8", errors="replace"))
             for rel, p in rels if "tests" not in rel.split("/"))
    _assert_scan(*_scan(files))
