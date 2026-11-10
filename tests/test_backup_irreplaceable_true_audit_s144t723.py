"""S144-T-723: true-audit of tools/backup_irreplaceable.py (RM-135 data backup).

Every case here was RED against the pre-audit module (measured 2026-11-09):

1. The read-only SQLite URI was built by string concatenation, so a '#' in the
   path cut it (the fragment) and a '%41' decoded to 'A': the tool opened a
   DIFFERENT file and backed up / counted an empty database without an error.
2. A data dir with no irreplaceable database produced an empty snapshot that
   verify() called VERIFIED, and its prune() then rotated out a real snapshot.
3. A WAL-mode source (four of the five live data/*.db are WAL) left
   `<name>-wal` / `<name>-shm` sidecars inside the snapshot dir, because the
   snapshot was re-opened read-only to count rows; verify() did the same.
4. restore() checked neither the manifest nor the SHA-256 (a corrupted or
   unlisted file was restored silently), accepted a name that walks out of
   the snapshot, and wrote the destination in place (a failed copy left a
   half-written file that then blocked every retry as "exists").
5. verify() raised a traceback on a missing / junk manifest or a file SQLite
   cannot read, instead of reporting a problem.
6. A table name holding a double quote broke the row count (bad quoting).
7. backup(now=0.0) ignored the given clock (falsy test).
8. main() let every expected failure escape as a traceback.

All against tmp dirs - never the live data/ (hermetic).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools import backup_irreplaceable as bk


def _db(path: Path, rows: int, *, wal: bool = False, table: str = "matches") -> None:
    conn = sqlite3.connect(path)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        quoted = '"' + table.replace('"', '""') + '"'
        conn.execute(f"CREATE TABLE {quoted} (id INTEGER PRIMARY KEY, raw TEXT)")
        conn.executemany(f"INSERT INTO {quoted} (raw) VALUES (?)",
                         [(f"r{i}",) for i in range(rows)])
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    _db(d / "rewind_history.db", 5)
    _db(d / "match_history.db", 3)
    return d


# 1. URI quoting ------------------------------------------------------------

@pytest.mark.parametrize("dirname", ["dir #frag", "dir%41pct", "dir with space"])
def test_paths_with_uri_metacharacters_open_the_right_file(tmp_path, dirname):
    d = tmp_path / dirname
    d.mkdir()
    _db(d / "rewind_history.db", 4)
    assert bk._table_counts(d / "rewind_history.db") == {"matches": 4}
    snap = bk.backup(d, tmp_path / "bk", now=1_700_000_000)
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["rewind_history.db"]["tables"] == {"matches": 4}
    assert bk.verify(snap) == []


def test_a_missing_source_raises_instead_of_reading_another_path(tmp_path):
    d = tmp_path / "a#b"
    d.mkdir()
    (tmp_path / "a").mkdir()
    with pytest.raises(sqlite3.OperationalError):
        bk._table_counts(d / "nope.db")


# 2. empty data dir ---------------------------------------------------------

def test_backup_refuses_a_data_dir_with_no_irreplaceable_db(tmp_path, data):
    root = tmp_path / "bk"
    good = bk.backup(data, root, keep=1, now=1_700_000_000)
    empty = tmp_path / "empty"
    empty.mkdir()
    _db(empty / "riot_api_cache.db", 2)  # a cache only - nothing irreplaceable
    with pytest.raises(RuntimeError, match="no irreplaceable"):
        bk.backup(empty, root, keep=1, now=1_700_000_100)
    assert bk.snapshots(root) == [good]  # the real snapshot survived
    assert not any(p.name.endswith(".partial") for p in root.iterdir())


def test_verify_flags_a_manifest_that_lists_no_database(tmp_path):
    snap = tmp_path / "20260101T000000Z"
    snap.mkdir()
    (snap / "manifest.json").write_text('{"files": {}}', encoding="utf-8")
    problems = bk.verify(snap)
    assert problems and "no database" in problems[0]


# 3. WAL sidecars -----------------------------------------------------------

def test_a_wal_source_leaves_no_sidecar_in_the_snapshot(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    _db(d / "rewind_history.db", 6, wal=True)
    live = sqlite3.connect(d / "rewind_history.db")  # a live writer holds it
    try:
        snap = bk.backup(d, tmp_path / "bk", now=1_700_000_000)
        assert bk.verify(snap) == []
    finally:
        live.close()
    names = sorted(p.name for p in snap.iterdir())
    assert names == ["manifest.json", "rewind_history.db"]
    dest = tmp_path / "restored.db"
    bk.restore(snap, "rewind_history.db", dest)
    assert dest.read_bytes()[18:20] == b"\x02\x02"  # the WAL mode survives restore
    assert bk._table_counts(dest) == {"matches": 6}


def test_a_copy_that_leaves_a_wal_behind_is_refused(tmp_path, data, monkeypatch):
    real = bk._online_copy

    def leaky(src, dest, **kw):
        real(src, dest, **kw)
        Path(str(dest) + "-wal").write_bytes(b"uncheckpointed pages")

    monkeypatch.setattr(bk, "_online_copy", leaky)
    root = tmp_path / "bk"
    with pytest.raises(RuntimeError, match="not self-contained"):
        bk.backup(data, root, now=1_700_000_000)
    assert bk.snapshots(root) == []
    assert list(root.iterdir()) == []  # the scratch dir went with the failure


# 4. restore ----------------------------------------------------------------

def test_restore_refuses_a_corrupted_snapshot_file(tmp_path, data):
    snap = bk.backup(data, tmp_path / "bk", now=1_700_000_000)
    with (snap / "match_history.db").open("r+b") as fh:
        fh.seek(200)
        fh.write(b"\xff" * 16)
    dest = tmp_path / "out.db"
    with pytest.raises(ValueError, match="sha256"):
        bk.restore(snap, "match_history.db", dest)
    assert not dest.exists()


def test_restore_refuses_a_name_the_manifest_does_not_list(tmp_path, data):
    snap = bk.backup(data, tmp_path / "bk", now=1_700_000_000)
    _db(snap / "extra.db", 1)
    with pytest.raises(ValueError, match="manifest"):
        bk.restore(snap, "extra.db", tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()


@pytest.mark.parametrize("name", ["../data/rewind_history.db", "sub/x.db", "", ".."])
def test_restore_refuses_a_name_that_is_not_a_bare_file_name(tmp_path, data, name):
    snap = bk.backup(data, tmp_path / "bk", now=1_700_000_000)
    with pytest.raises(ValueError):
        bk.restore(snap, name, tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()


def test_a_failed_restore_copy_leaves_no_half_written_destination(tmp_path, data, monkeypatch):
    snap = bk.backup(data, tmp_path / "bk", now=1_700_000_000)
    real = bk._online_copy

    def torn(src, dest, **kw):
        real(src, dest, **kw)
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(bk, "_online_copy", torn)
    dest = tmp_path / "out" / "rewind_history.db"
    dest.parent.mkdir()
    with pytest.raises(sqlite3.OperationalError):
        bk.restore(snap, "rewind_history.db", dest)
    assert list(dest.parent.iterdir()) == []
    monkeypatch.setattr(bk, "_online_copy", real)
    bk.restore(snap, "rewind_history.db", dest)  # a retry is not blocked
    assert bk._table_counts(dest) == {"matches": 5}


# 5. verify on junk ---------------------------------------------------------

@pytest.mark.parametrize("body", [None, "", "{not json", "[]", '{"files": []}',
                                  '{"files": {"x.db": 3}}',
                                  '{"files": {"x.db": {"sha256": 1}}}'])
def test_verify_reports_a_missing_or_junk_manifest(tmp_path, body):
    snap = tmp_path / "20260101T000000Z"
    snap.mkdir()
    if body is not None:
        (snap / "manifest.json").write_text(body, encoding="utf-8")
    problems = bk.verify(snap)
    assert problems and all(isinstance(p, str) for p in problems)


def test_verify_flags_a_manifest_name_that_walks_out_of_the_snapshot(tmp_path, data):
    snap = bk.backup(data, tmp_path / "bk", now=1_700_000_000)
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["../../data/rewind_history.db"] = manifest["files"]["rewind_history.db"]
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    problems = bk.verify(snap)
    assert any("not a bare file name" in p for p in problems)


def test_verify_reports_a_file_sqlite_cannot_read(tmp_path):
    snap = tmp_path / "20260101T000000Z"
    snap.mkdir()
    junk = b"this is not a database" * 50
    (snap / "x.db").write_bytes(junk)
    manifest = {"files": {"x.db": {"sha256": hashlib.sha256(junk).hexdigest(),
                                   "size": len(junk), "tables": {}}}}
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    problems = bk.verify(snap)
    assert problems and problems[0].startswith("x.db:")


# 6. quoting ----------------------------------------------------------------

def test_a_table_name_with_a_double_quote_is_counted(tmp_path):
    db = tmp_path / "q.db"
    _db(db, 2, table='we"ird')
    assert bk._table_counts(db) == {'we"ird': 2}


# 7. clock ------------------------------------------------------------------

def test_backup_honours_now_zero(tmp_path, data):
    snap = bk.backup(data, tmp_path / "bk", now=0.0)
    assert snap.name == "19700101T000000Z"


# 8. main -------------------------------------------------------------------

def test_main_reports_expected_failures_without_a_traceback(tmp_path, data, capsys):
    assert bk.main(["verify", str(tmp_path / "nope")]) == 1
    snap = bk.backup(data, tmp_path / "bk", now=1_700_000_000)
    taken = tmp_path / "taken.db"
    taken.write_bytes(b"live")
    assert bk.main(["restore", str(snap), "rewind_history.db", str(taken)]) == 2
    assert taken.read_bytes() == b"live"
    assert bk.main(["restore", str(snap), "../x.db", str(tmp_path / "o.db")]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "exists" in err
