"""Lane 8 deep audit of ``core/riot_api_cache.py`` - the SQLite cache in front
of the Riot API.

Selected by risk criterion 1 (it persists external API bodies), criterion 2
(it sits on the API-key path), criterion 3 (SQLite, WAL, threads) and
criterion 4 (**zero** LEDGER mentions across 1181 entries - never audited).
Recorded expectation before reading: the Riot API key leaking into a cache
key or a log line, plus SQLite lifetime/threading issues.

**EXPECTATION REFUTED, and the design is deliberately right - recorded so the
next audit does not re-spend on it.** Cache keys carry
``core.riot_api._key_fingerprint()``, a TRUNCATED SHA256 whose own docstring
says "never the key itself - the cache DB is not a secret store". It exists
for a real reason: PUUIDs are a per-API-key encryption of the same account,
so a key rotation would otherwise poison immutable rows forever. Measured on
the live 12,305-row DB: zero keys contain ``RGAPI`` or ``api_key``.

**FINDING 1 - a deleted DB file makes the cache a PERMANENT silent no-op.**
``_ensure_schema`` short-circuits on ``self._initialized``, which is process
state, not file state. If the DB file goes away under a long-lived process
(rotation, a cleanup pass, disk trouble), SQLite happily recreates an EMPTY
file on the next connect, the schema is never re-run, and every operation
fails on "no such table" - caught, logged at WARNING, returning None/False.
Callers cannot tell that from a cache miss, so RC silently re-fetches from
the Riot API forever, burning rate limit, until the process restarts.
Measured before the fix::

    set/get on a fresh cache      -> True / {'a': 1}
    <delete the .db file>
    set                          -> False       (forever)
    get                          -> None        (forever)
    _initialized                 -> still True

**FINDING 2 - three docstring claims that are not true of the code.** The
module docstring says the connection uses "a ``BEGIN IMMEDIATE`` transaction
to avoid the dashboard request thread racing the priority-2 background
scheduler". ``BEGIN IMMEDIATE`` appears exactly ONCE in the file - in that
sentence. The connection is ``isolation_level=None`` (autocommit) and every
write is a single-statement ``INSERT OR REPLACE``, which is atomic on its own,
so the CODE is fine and the SENTENCE is not. Separately
``purge_expired_ttl`` says it is "called opportunistically by the rate-limit
prune" and ``stats`` says it is "for the dashboard / metrics endpoint" -
**both have zero callers anywhere in the tree.**

**NOT FIXED HERE, filed as RM-153.** The immutable table never expires by
design, and the live DB has reached **3.33 GB** across 12,305 rows (freelist
0, so it is all live data, not bloat). Nothing caps it, nothing evicts, and
the only introspection - uncalled ``stats()`` - reports ROW COUNTS, never
bytes. So the one function that could surface this is blind to the dimension
that matters. Adding eviction is a policy decision about RC's match corpus,
not a lane-8 unilateral call; making the size observable is, and is done
below.
"""
from __future__ import annotations

import logging
import sqlite3
import threading

import pytest

from core.riot_api_cache import RiotApiCache


@pytest.fixture()
def cache(tmp_path):
    return RiotApiCache(db_path=tmp_path / "c.db")


class TestSurvivesDbFileLoss:
    """A vanished DB file must cost one call, not the process lifetime."""

    def _delete_db(self, tmp_path):
        for f in tmp_path.glob("c.db*"):
            f.unlink()

    def test_immutable_recovers_after_db_file_is_deleted(self, cache, tmp_path, caplog):
        assert cache.set_immutable("k1", {"a": 1}) is True
        assert cache.get_immutable("k1") == {"a": 1}

        self._delete_db(tmp_path)
        with caplog.at_level(logging.WARNING):
            cache.set_immutable("k2", {"b": 2})

        # The cache must be usable again rather than dead for the process.
        assert cache.set_immutable("k3", {"c": 3}) is True, (
            "cache is still a no-op after losing its file - _initialized was "
            "never cleared, so the schema is never recreated")
        assert cache.get_immutable("k3") == {"c": 3}

    def test_ttl_recovers_after_db_file_is_deleted(self, cache, tmp_path):
        assert cache.set_ttl("t1", {"a": 1}, 300) is True
        self._delete_db(tmp_path)
        cache.set_ttl("t2", {"b": 2}, 300)
        assert cache.set_ttl("t3", {"c": 3}, 300) is True
        assert cache.get_ttl("t3") == {"c": 3}

    def test_get_on_a_missing_db_does_not_poison_later_writes(self, cache, tmp_path):
        """A READ is what usually notices the loss first."""
        cache.set_immutable("k1", {"a": 1})
        self._delete_db(tmp_path)
        assert cache.get_immutable("k1") is None      # genuinely gone
        assert cache.set_immutable("k1", {"a": 1}) is True
        assert cache.get_immutable("k1") == {"a": 1}

    def test_normal_operation_is_unchanged(self, cache):
        """Positive control - the recovery path must not cost the hot path."""
        assert cache.set_immutable("x", {"v": 1}) is True
        assert cache.get_immutable("x") == {"v": 1}
        assert cache.get_immutable("missing") is None
        assert cache.set_ttl("y", {"v": 2}, 300) is True
        assert cache.get_ttl("y") == {"v": 2}

    def test_expired_ttl_row_still_reads_as_a_miss(self, cache):
        """Positive control - expiry semantics must survive the change."""
        assert cache.set_ttl("z", {"v": 3}, 0) is True
        assert cache.get_ttl("z") is None


class TestDocstringMatchesCode:
    """Claims in this module must be true of this module."""

    def _module_src(self) -> str:
        import core.riot_api_cache as _mod
        from pathlib import Path
        return Path(_mod.__file__).read_text(encoding="utf-8")

    def test_no_begin_immediate_claim_without_begin_immediate(self):
        """The claim must be backed by EXECUTABLE code, not by a mention.

        The first version of this test computed `opens` over everything after
        the module docstring, which includes every method docstring - so
        re-adding the false promise while merely MENTIONING the phrase in any
        later docstring kept it green (measured by the verifier: 11 passed).
        A guard that accepts prose as proof of code is the
        `feedback_guard_on_nondefault_call_path_is_untested` shape. Docstrings
        are now stripped via ast before looking for the statement.
        """
        import ast
        src = self._module_src()
        tree = ast.parse(src)
        doc_spans = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    doc_spans.append((body[0].lineno, body[0].end_lineno))

        claims = "BEGIN IMMEDIATE" in ast.get_docstring(tree, clean=False)
        lines = src.splitlines()
        code_only = [
            ln for i, ln in enumerate(lines, start=1)
            if not any(a <= i <= b for a, b in doc_spans)
            and not ln.lstrip().startswith("#")
        ]
        opens = any("BEGIN IMMEDIATE" in ln for ln in code_only)
        assert not (claims and not opens), (
            "the module docstring promises a BEGIN IMMEDIATE transaction that "
            "the code never opens - the connection is autocommit and relies on "
            "single-statement atomicity instead")

    def test_uncalled_helpers_do_not_claim_callers(self):
        """purge_expired_ttl and stats each named a caller that does not exist.

        Pinned by reading the docstrings off disk rather than restating them.
        """
        src = self._module_src()
        assert "called opportunistically by the rate-limit prune" not in src, \
            "purge_expired_ttl still claims a caller that does not exist"
        assert "for the dashboard / metrics endpoint" not in src, \
            "stats still claims a consumer that does not exist"


class TestStatsReportsSize:
    """RM-153 makes the 3.33 GB growth observable rather than invisible."""

    def test_stats_reports_bytes_not_only_rows(self, cache):
        cache.set_immutable("k", {"payload": "x" * 500})
        s = cache.stats()
        assert "immutable_rows" in s and "ttl_live_rows" in s, \
            "existing keys must survive - callers may depend on them"
        assert s["immutable_bytes"] >= 500, (
            "stats() reports row counts only; the live cache is 3.33 GB and "
            "nothing anywhere surfaces that")
        assert s["db_file_bytes"] > 0

    def test_stats_on_a_missing_db_is_still_safe(self, cache, tmp_path):
        cache.set_immutable("k", {"a": 1})
        for f in tmp_path.glob("c.db*"):
            f.unlink()
        s = cache.stats()
        assert set(s) >= {"immutable_rows", "ttl_live_rows",
                          "immutable_bytes", "db_file_bytes"}


def test_concurrent_writers_do_not_corrupt_or_raise(cache):
    """Threading claim in the docstring, exercised rather than trusted."""
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(20):
                cache.set_immutable(f"t{n}:{i}", {"n": n, "i": i})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, f"concurrent writes raised: {errors[:2]}"
    assert cache.stats()["immutable_rows"] == 80


def test_purge_expired_ttl_actually_purges(cache):
    """It has no caller, but it is public and must do what it says."""
    cache.set_ttl("live", {"a": 1}, 300)
    cache.set_ttl("dead", {"b": 2}, 0)
    assert cache.purge_expired_ttl() == 1
    assert cache.get_ttl("live") == {"a": 1}
    conn = sqlite3.connect(str(cache._db_path))
    try:
        rows = conn.execute("SELECT key FROM cache_ttl").fetchall()
    finally:
        conn.close()
    assert rows == [("live",)]
