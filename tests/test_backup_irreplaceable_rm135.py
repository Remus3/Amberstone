"""RM-135: backup of irreplaceable single-copy data, restore EXERCISED.

All against a tmp data dir - never the live data/ (hermetic).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools import backup_irreplaceable as bk


def _db(path: Path, rows: int) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE matches (id INTEGER PRIMARY KEY, raw TEXT)")
    conn.executemany("INSERT INTO matches (raw) VALUES (?)",
                     [(f"r{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


@pytest.fixture()
def data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    _db(d / "rewind_history.db", 5)
    _db(d / "match_history.db", 3)
    _db(d / "riot_api_cache.db", 9)
    (d / "mirror.json").write_text("{}", encoding="utf-8")
    return d


def test_classification_keeps_caches_and_mirrors_out(data):
    c = bk.classify(data)
    assert c["irreplaceable"] == ["match_history.db", "rewind_history.db"]
    assert c["regenerable"] == ["riot_api_cache.db"]


def test_backup_then_verify_restores_and_checks(data, tmp_path):
    root = tmp_path / "backups"
    snap = bk.backup(data, root, keep=3, now=1_000_000)
    assert sorted(p.name for p in snap.iterdir()) == [
        "manifest.json", "match_history.db", "rewind_history.db"]
    assert bk.verify(snap) == []


def test_verify_catches_a_corrupted_copy(data, tmp_path):
    snap = bk.backup(data, tmp_path / "backups", now=1_000_000)
    with (snap / "rewind_history.db").open("r+b") as fh:
        fh.seek(200)
        fh.write(b"\xff" * 64)
    assert any("rewind_history.db" in p for p in bk.verify(snap))


def test_restore_round_trip_and_refuses_to_overwrite(data, tmp_path):
    snap = bk.backup(data, tmp_path / "backups", now=1_000_000)
    dest = tmp_path / "restored.db"
    bk.restore(snap, "rewind_history.db", dest)
    conn = sqlite3.connect(dest)
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 5
    conn.close()
    with pytest.raises(FileExistsError):
        bk.restore(snap, "rewind_history.db", dest)


def test_retention_keeps_newest_complete_snapshots(data, tmp_path):
    root = tmp_path / "backups"
    for t in (1_000_000, 1_000_100, 1_000_200):
        bk.backup(data, root, keep=2, now=t)
    assert len(bk.snapshots(root)) == 2


def test_backup_target_is_inside_the_repo_and_excluded_from_rollback():
    assert bk.BACKUP_ROOT.is_relative_to(bk.ROOT)
    assert bk.BACKUP_ROOT.parts[-3:-1] == ("ops", "backups")
