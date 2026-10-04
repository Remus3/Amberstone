"""RM-454: the own-history cache key must track CONTENT, survive close and
reopen, and include the database path.

The (mtime, size, row count) key served stale history for same-count
writes inside one mtime tick (pinned by the two former xfails in
tests/test_rm450_core_residuals.py, now plain tests). Two metadata keys
were refuted in RM-450 (stat memo; raw SQLite header token). The row's
first alternative, ``PRAGMA data_version`` on a persistent read
connection, was measured and REJECTED here: on Windows an open SQLite
handle blocks ``os.unlink`` of the database (WinError 32), so it would pin
the live match_history.db and break delete-and-recreate. The shipped key is
a digest of exactly the rows the scan consumes, plus the path.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from core import augment_recommender as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_rm450_core_residuals import _history_db, _raw, _recreate  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    ar.reset_cache()
    yield
    ar.reset_cache()


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_close_and_reopen_same_content_is_a_cache_hit(journal, tmp_path, monkeypatch):
    db = _history_db(tmp_path, journal)
    first = ar.load_own_history("mayhem", db_path=db)
    # A writer opens and closes with no change: the cached object is served.
    sqlite3.connect(db).close()
    scans = []
    real = ar._scan_own_history_checked
    monkeypatch.setattr(ar, "_scan_own_history_checked",
                        lambda m, p: scans.append(p) or real(m, p))
    assert ar.load_own_history("mayhem", db_path=db) is first
    assert scans == []


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_close_and_reopen_with_same_count_update_invalidates(journal, tmp_path):
    db = _history_db(tmp_path, journal)
    assert ar.load_own_history("mayhem", db_path=db).games == {101: 1}
    w = sqlite3.connect(db)
    w.execute("UPDATE matches SET raw_data = ? WHERE id = 1", (_raw(202),))
    w.commit()
    w.close()
    assert ar.load_own_history("mayhem", db_path=db).games == {202: 1}


def test_two_databases_identical_stats_do_not_share_a_key(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _history_db(tmp_path / "a")
    b = tmp_path / "b" / "match_history.db"
    _recreate(b, "delete", [202])
    assert ar.load_own_history("mayhem", db_path=a).games == {101: 1}
    assert ar.load_own_history("mayhem", db_path=b).games == {202: 1}
    assert ar.load_own_history("mayhem", db_path=a).games == {101: 1}


def test_key_includes_the_path(tmp_path):
    db = _history_db(tmp_path)
    assert ar._history_key(db)[0] == str(db)


def test_delete_and_recreate_not_blocked(tmp_path):
    # The cache must not hold the database open (Windows would refuse the
    # unlink inside _recreate).
    db = _history_db(tmp_path)
    ar.load_own_history("mayhem", db_path=db)
    _recreate(db, "delete", [303])
    assert ar.load_own_history("mayhem", db_path=db).games == {303: 1}
