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

def _discarded_journal_pragmas(source: str) -> list[int]:
    """Line numbers of statement-level calls whose journal_mode answer is dropped."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Expr):
            continue
        for sub in ast.walk(node.value):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "execute" and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)
                    and _JOURNAL_RE.search(sub.args[0].value)):
                hits.append(node.lineno)
                break
    return hits


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


def test_no_module_discards_the_journal_mode_answer():
    _repo_walk.self_check()
    offenders = []
    checked_sites = 0
    for path in _repo_walk.iter_repo_files():
        rel = _repo_walk.relative_posix(path)
        if "tests" in rel.split("/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "journal_mode" not in text:
            continue
        checked_sites += len(_JOURNAL_RE.findall(text))
        try:
            lines = _discarded_journal_pragmas(text)
        except SyntaxError:
            continue
        offenders.extend(f"{rel}:{n}" for n in lines)
    # Anchor: the RM-233 site plus the eight RM-413 sites must be in the scan.
    assert checked_sites >= 9, f"scan reached only {checked_sites} journal_mode sites"
    assert offenders == [], f"journal_mode result discarded at: {offenders}"
