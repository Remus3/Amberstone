"""s144 true-audit cycle 113 - core/match_metrics.py.

Each class pins one finding of the lane-8 audit (RM-1448 .. RM-1452).
Every test points DB_PATH at tmp_path, so nothing here reads or writes the
live data/match_metrics.db.
"""
from __future__ import annotations

import logging
import math
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import core.match_metrics as mm

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def rec(monkeypatch, tmp_path):
    monkeypatch.setattr(mm, "DB_PATH", tmp_path / "match_metrics.db")
    return mm.Recorder()


def _rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT match_id, champion, mode, metric_key, metric_value, "
            "metric_type, recorded_at_game_time_s, milestone_tag, provenance "
            "FROM match_metrics ORDER BY id").fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RM-1448 - importing the module must not touch the database
# ---------------------------------------------------------------------------

class TestImportHasNoDbSideEffect:
    def test_import_opens_no_connection(self):
        """Pre-fix the module-level ``recorder = Recorder()`` ran init_db()
        at import: every importer (and every test) created and migrated the
        LIVE data/match_metrics.db, and a locked or corrupt DB raised out of
        the import itself. The child replaces sqlite3.connect with a raiser
        before importing, so a connection at import time fails the import."""
        code = (
            "import sqlite3\n"
            "def _boom(*a, **k):\n"
            "    raise sqlite3.OperationalError('database is locked')\n"
            "sqlite3.connect = _boom\n"
            "import core.match_metrics as m\n"
            "print('IMPORT_OK', m.recorder.buffered())\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=str(_REPO_ROOT), env=env,
            capture_output=True, text=True, timeout=120, creationflags=flags,
            check=False)
        assert proc.returncode == 0, proc.stderr
        assert "IMPORT_OK 0" in proc.stdout

    def test_constructor_opens_no_connection(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mm, "DB_PATH", tmp_path / "match_metrics.db")
        mm.Recorder()
        assert not (tmp_path / "match_metrics.db").exists()

    def test_first_flush_creates_the_schema(self, rec):
        rec.record(match_id="m1", key="k", value=1)
        assert rec.flush() == 1
        assert len(_rows(mm.DB_PATH)) == 1

    def test_schema_follows_a_moved_db_path(self, rec, monkeypatch, tmp_path,
                                            caplog):
        """The schema latch is keyed on the path, not a bare flag, so a
        recorder whose DB_PATH changes initialises the new file up front -
        not through the missing-schema heal (no heal warning)."""
        rec.record(match_id="m1", key="k", value=1)
        rec.flush()
        other = tmp_path / "sub" / "other.db"
        monkeypatch.setattr(mm, "DB_PATH", other)
        rec.record(match_id="m2", key="k", value=2)
        with caplog.at_level(logging.WARNING, logger="rc.match_metrics"):
            assert rec.flush() == 1
        assert [r[0] for r in _rows(other)] == ["m2"]
        assert not [r for r in caplog.records
                    if "re-initialising" in r.getMessage()]


# ---------------------------------------------------------------------------
# RM-1449 - one bad row must not poison the whole buffer
# ---------------------------------------------------------------------------

class TestPoisonRow:
    @pytest.mark.parametrize("bad", [None, "", 0.5, True, ["m"]])
    def test_bad_match_id_refused_at_record(self, rec, bad):
        with pytest.raises(ValueError):
            rec.record(match_id=bad, key="k", value=1)
        assert rec.buffered() == 0

    @pytest.mark.parametrize("bad", [None, "", 3, {"k": 1}])
    def test_bad_key_refused_at_record(self, rec, bad):
        with pytest.raises(ValueError):
            rec.record(match_id="m1", key=bad, value=1)
        assert rec.buffered() == 0

    def test_integer_match_id_is_kept_as_text(self, rec):
        rec.record(match_id=123, key="k", value=1)
        rec.flush()
        assert _rows(mm.DB_PATH)[0][0] == "123"

    def test_unbindable_champion_does_not_stall_good_rows(self, rec):
        """Pre-fix a dict champion reached executemany, which raised
        ProgrammingError for the WHOLE batch; the batch was re-queued at
        the front and every later flush failed the same way, so no row was
        ever written again."""
        payload = {"champion": {"name": "Ahri"}, "game_mode": ["CLASSIC"],
                   "kda": "1/2/3"}
        assert rec.record_state_snapshot(payload, match_id="m1") == 1
        rec.record(match_id="m1", key="k2", value="v")
        assert rec.flush() == 2
        rows = _rows(mm.DB_PATH)
        assert [r[3] for r in rows] == ["kda_string", "k2"]
        assert rows[0][1] is None and rows[0][2] is None

    def test_unbindable_metadata_fields_become_null(self, rec):
        rec.record(match_id="m1", key="k", value=1, metric_type=["x"],
                   milestone_tag={"t": 1}, session_id=object(),
                   champion="Ahri", mode="ARAM")
        assert rec.flush() == 1
        row = _rows(mm.DB_PATH)[0]
        assert row[1:3] == ("Ahri", "ARAM")
        assert row[5] == "text"     # metric_type falls back to its default
        assert row[7] is None       # milestone_tag


# ---------------------------------------------------------------------------
# RM-1450 - a vanished DB file or directory heals on the next flush
# ---------------------------------------------------------------------------

class TestVanishedDbHeals:
    def test_deleted_db_file_heals(self, rec):
        """Pre-fix the schema was created once (import time); deleting the
        file made sqlite3.connect create an EMPTY database and every flush
        raise "no such table" forever, re-queueing until the cap."""
        rec.record(match_id="m1", key="k", value=1)
        rec.flush()
        Path(mm.DB_PATH).unlink()
        rec.record(match_id="m2", key="k", value=2)
        assert rec.flush() == 1
        assert rec.buffered() == 0
        assert [r[0] for r in _rows(mm.DB_PATH)] == ["m2"]

    def test_deleted_data_dir_heals(self, monkeypatch, tmp_path):
        db = tmp_path / "data" / "match_metrics.db"
        monkeypatch.setattr(mm, "DB_PATH", db)
        r = mm.Recorder()
        r.record(match_id="m1", key="k", value=1)
        r.flush()
        db.unlink()
        db.parent.rmdir()
        r.record(match_id="m2", key="k", value=2)
        assert r.flush() == 1
        assert [x[0] for x in _rows(db)] == ["m2"]

    def test_a_locked_db_still_requeues_and_raises(self, rec, monkeypatch,
                                                    caplog):
        """Negative control: the heal retry is for a missing schema only. A
        locked DB is transient - the rows go back on the buffer and the
        error propagates, exactly as before, with no re-initialise."""
        rec.record(match_id="m1", key="k", value=1)
        rec.flush()
        rec.record(match_id="m2", key="k", value=2)

        def _locked(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(mm.sqlite3, "connect", _locked)
        with caplog.at_level(logging.WARNING, logger="rc.match_metrics"):
            with pytest.raises(sqlite3.OperationalError):
                rec.flush()
        assert rec.buffered() == 1
        assert not [r for r in caplog.records
                    if "re-initialising" in r.getMessage()]

    def test_heal_is_logged(self, rec, caplog):
        rec.record(match_id="m1", key="k", value=1)
        rec.flush()
        Path(mm.DB_PATH).unlink()
        rec.record(match_id="m2", key="k", value=2)
        with caplog.at_level(logging.WARNING, logger="rc.match_metrics"):
            rec.flush()
        assert [r for r in caplog.records
                if "re-initialising" in r.getMessage()]


# ---------------------------------------------------------------------------
# RM-1451 - game clock, non-finite values and overrides are validated
# ---------------------------------------------------------------------------

class TestInputValidation:
    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_payload_clock_does_not_raise(self, rec, bad):
        """Pre-fix int(nan) raised ValueError / int(inf) OverflowError out
        of record_state_snapshot."""
        n = rec.record_state_snapshot(
            {"game_time_s": bad, "kda": "1/0/0"}, match_id="m1")
        assert n == 1
        rec.flush()
        assert _rows(mm.DB_PATH)[0][6] is None

    @pytest.mark.parametrize("bad", ["12", True, -5, math.nan, [1]])
    def test_record_junk_game_time_stored_as_null(self, rec, bad):
        rec.record(match_id="m1", key="k", value=1, game_time_s=bad)
        rec.flush()
        assert _rows(mm.DB_PATH)[0][6] is None

    def test_record_float_game_time_truncates_to_int(self, rec):
        rec.record(match_id="m1", key="k", value=1, game_time_s=125.9)
        rec.flush()
        row = _rows(mm.DB_PATH)[0]
        assert row[6] == 125 and isinstance(row[6], int)

    def test_non_finite_metric_values_are_skipped(self, rec):
        """NO FABRICATION: a NaN is not a measurement. Pre-fix it was
        persisted as the text 'nan'."""
        payload = {"cs": math.nan, "gold": math.inf, "level": 7}
        assert rec.record_state_snapshot(payload, match_id="m1") == 1
        rec.flush()
        assert [r[3:5] for r in _rows(mm.DB_PATH)] == [("level_current", "7")]

    def test_non_dict_overrides_are_ignored(self, rec):
        """Pre-fix a list here raised AttributeError ('.get')."""
        n = rec.record_state_snapshot(
            {"kda": "1/0/0"}, match_id="m1",
            provenance_overrides=["inferred_tight"])
        assert n == 1
        rec.flush()
        assert _rows(mm.DB_PATH)[0][8] == "source_truth"

    def test_dict_overrides_still_apply(self, rec):
        """Negative control for the override path."""
        rec.record_state_snapshot(
            {"kda": "1/0/0", "cs": 40}, match_id="m1",
            provenance_overrides={"cs_current": "inferred_tight"})
        rec.flush()
        prov = {r[3]: r[8] for r in _rows(mm.DB_PATH)}
        assert prov == {"kda_string": "source_truth",
                        "cs_current": "inferred_tight"}


# ---------------------------------------------------------------------------
# RM-1452 - capped drops are logged; integrity_check reports corruption
# ---------------------------------------------------------------------------

class TestDropLoggingAndIntegrity:
    def test_requeue_cap_drop_is_logged(self, rec, monkeypatch, caplog):
        monkeypatch.setattr(mm, "_REQUEUE_MAX", 2)
        for i in range(5):
            rec.record(match_id="m1", key=f"k{i}", value=i)

        def _locked(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(mm.sqlite3, "connect", _locked)
        with caplog.at_level(logging.WARNING, logger="rc.match_metrics"):
            with pytest.raises(sqlite3.OperationalError):
                rec.flush()
        assert rec.buffered() == 2
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "rc.match_metrics"]
        assert any("dropped 3" in m for m in msgs), msgs

    def test_no_drop_no_warning(self, rec, monkeypatch, caplog):
        """Negative control: a failed flush under the cap logs no drop."""
        rec.record(match_id="m1", key="k", value=1)

        def _locked(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(mm.sqlite3, "connect", _locked)
        with caplog.at_level(logging.WARNING, logger="rc.match_metrics"):
            with pytest.raises(sqlite3.OperationalError):
                rec.flush()
        assert not [r for r in caplog.records
                    if r.name == "rc.match_metrics" and "dropped" in r.getMessage()]

    def test_integrity_check_reports_a_corrupt_file(self, monkeypatch, tmp_path):
        """Pre-fix PRAGMA integrity_check on a non-database file raised
        DatabaseError, so retrofill_match_metrics crashed with a traceback
        instead of taking its clean ABORT branch."""
        bad = tmp_path / "match_metrics.db"
        bad.write_bytes(b"this is not a sqlite database at all" * 64)
        monkeypatch.setattr(mm, "DB_PATH", bad)
        ok, msg = mm.integrity_check()
        assert ok is False
        assert msg

    def test_integrity_check_and_row_count_on_missing_db(
            self, monkeypatch, tmp_path):
        """With the import-time init gone, the retrofill pre-flight must
        still work on a first run: both helpers create the schema."""
        monkeypatch.setattr(mm, "DB_PATH", tmp_path / "fresh" / "mm.db")
        assert mm.integrity_check() == (True, "ok")
        assert mm.row_count() == 0

    def test_row_count_alone_on_missing_db(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mm, "DB_PATH", tmp_path / "fresh2" / "mm.db")
        assert mm.row_count() == 0

    def test_integrity_check_ok_on_good_db(self, rec):
        rec.record(match_id="m1", key="k", value=1)
        rec.flush()
        assert mm.integrity_check() == (True, "ok")
        assert mm.row_count() == 1
