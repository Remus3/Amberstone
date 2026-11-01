"""s144 lane 8 (true-audit) cycle 94 - core/skill_wpa.py hardening.

One test per audited weakness (F1-F10), each written RED against the
pre-fix module. Synthetic data only: hand-written match ids, an in-memory
or tmp sqlite DB (never the live corpus).

F1  sqlite3.Error inside the per-match loop was swallowed, so a locked
    DB served a silently partial corpus as ok=True (RM-1262, skill half).
F2  a match that failed after its first participant was counted stayed
    half-counted; observations now merge only for a cleanly read match.
F3  the per-match catch was ``except Exception``, so a programming error
    was logged once per match and answered ok=True.
F4  a NULL (or out-of-range) participants.win was read as a LOSS and
    biased observed_winrate down (RM-1331, skill half).
F5  EVOLVE skill-ups (Kha'Zix / Kai'Sa / Viktor upgrades, stored with
    level_up_type='EVOLVE') were counted as rank points, so a max was
    dated early, put on the wrong slot or invented outright. Measured on
    the real corpus 2026-10-31: 471 of 750 such maxes mistimed, 4 on the
    wrong slot, 3 phantom.
F6  an unreadable SKILL_LEVEL_UP timestamp: NULL read as 0 (or sorted
    out of order), and a non-numeric one raised and dropped EVERY
    participant of the match; now only that participant is excluded.
F7  elapsed_ms came from the wall clock (negative on a clock step).
F8  compute_skill_wpa_from_db built its read-only URI with an f-string,
    so a '#' in the path opened the wrong file (RM-1257, skill half).
F9  compute_skill_wpa_from_db treated a DIRECTORY as a present DB and
    raised, instead of the documented "missing" dict.
F10 min_n was never validated (None / bool / negative / str / float).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from core import skill_wpa
from tests.test_skill_wpa import AHRI, SYNDRA, _add_match, _build_db

KHAZIX = 121


def _row(result: dict, champ: int, slot: int) -> dict | None:
    for it in result["items"]:
        if it["champion_id"] == champ and it["skill_slot"] == slot:
            return it
    return None


def _n(result: dict, champ: int, slot: int = 1) -> int:
    row = _row(result, champ, slot)
    return row["n"] if row else 0


class _Proxy:
    """Connection proxy that raises on the Nth participants query."""

    def __init__(self, conn, fail_on: int, exc: BaseException):
        self._conn = conn
        self._fail_on = fail_on
        self._exc = exc
        self.calls = 0

    def execute(self, sql, *args):
        if "FROM participants" in sql:
            self.calls += 1
            if self.calls == self._fail_on:
                raise self._exc
        return self._conn.execute(sql, *args)


def _three_matches() -> sqlite3.Connection:
    conn = _build_db()
    for i in range(3):
        _add_match(conn, f"TEST_SK_94{i}", team100_gold=5000, team200_gold=0,
                   team100_win=1, maxes=[(1, AHRI, 1, 300_000)])
    return conn


def _event(conn, mid, ts, pid, slot, lut=None):
    """One SKILL_LEVEL_UP row; ``lut`` is written only when given, so the
    helper also works on the fixture schema without the column."""
    cols = "match_id, timestamp_ms, event_type, participant_id, skill_slot"
    vals: tuple = (mid, ts, "SKILL_LEVEL_UP", pid, slot)
    if lut is not None:
        cols += ", level_up_type"
        vals += (lut,)
    marks = ",".join("?" * len(vals))
    conn.execute(f"INSERT INTO timeline_events ({cols}) VALUES ({marks})",
                 vals)
    conn.commit()


def _evolve_db() -> sqlite3.Connection:
    """The fixture schema plus the real corpus's level_up_type column."""
    conn = _build_db()
    conn.execute("ALTER TABLE timeline_events ADD COLUMN level_up_type TEXT")
    return conn


# -- F1: sqlite3.Error propagates out of the sweep --------------------------

def test_f1_locked_db_mid_sweep_raises_instead_of_partial_ok():
    proxy = _Proxy(_three_matches(), 2,
                   sqlite3.OperationalError("database is locked"))
    with pytest.raises(sqlite3.OperationalError):
        skill_wpa.compute_skill_wpa(proxy, min_n=1)


def test_f1_route_answers_503_and_caches_nothing(tmp_path):
    from dashboard import routes_skill_wpa as rsw
    from tests.test_routes_skill_wpa_audit_s144 import _one, _seed, _serve

    db = _seed(tmp_path / "rh.db")
    real_open = rsw._open_rewind_db_ro

    class _Wrap:
        def __init__(self):
            self._p = _Proxy(real_open(), 2,
                             sqlite3.OperationalError("database is locked"))

        def execute(self, sql, *a):
            return self._p.execute(sql, *a)

        def close(self):
            self._p._conn.close()

    rsw._CACHE.clear()
    try:
        with mock.patch.object(rsw, "_open_rewind_db_ro", _Wrap):
            status, payload = _one(_serve("/api/skill-wpa?min_n=1", db))
        assert status == 503, payload
        assert payload["ok"] is False
        assert rsw._CACHE == {}
    finally:
        rsw._CACHE.clear()


# -- F2: a match skipped half-way contributes nothing -----------------------

def test_f2_match_failing_after_first_participant_is_rolled_back_whole():
    conn = _build_db()
    _add_match(conn, "TEST_SK_950", team100_gold=0, team200_gold=0,
               team100_win=1,
               maxes=[(1, AHRI, 1, 300_000), (6, AHRI, 1, 300_000)])
    real = skill_wpa._expected_win_for_team
    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("malformed frame value")
        return real(*a, **kw)

    with mock.patch.object(skill_wpa, "_expected_win_for_team", _flaky):
        out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert calls["n"] == 2
    assert out["ok"] is True
    assert _n(out, AHRI) == 0, out["items"]


# -- F3: a defect surfaces instead of a per-match log line ------------------

def test_f3_programming_error_surfaces():
    conn = _three_matches()
    with mock.patch.object(skill_wpa, "_expected_win_for_team",
                           side_effect=RuntimeError("defect")):
        with pytest.raises(RuntimeError):
            skill_wpa.compute_skill_wpa(conn, min_n=1)


def test_f3_data_error_still_skips_the_match(caplog):
    conn = _three_matches()
    real = skill_wpa._expected_win_for_team
    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("bad frame row")
        return real(*a, **kw)

    with caplog.at_level(logging.WARNING, logger="rc.skill_wpa"), \
         mock.patch.object(skill_wpa, "_expected_win_for_team", _flaky):
        out = skill_wpa.compute_skill_wpa(conn, min_n=1)
    assert out["ok"] is True
    assert _n(out, AHRI) == 2
    assert any("skipped" in r.getMessage() for r in caplog.records)


# -- F4: an unknown outcome is not a loss -----------------------------------

@pytest.mark.parametrize("bad_win", [None, 2, -1, "x"])
def test_f4_unknown_win_contributes_no_sample(bad_win):
    conn = _build_db()
    _add_match(conn, "TEST_SK_960", team100_gold=0, team200_gold=0,
               team100_win=1,
               maxes=[(1, AHRI, 1, 300_000), (2, SYNDRA, 1, 300_000)])
    conn.execute("UPDATE participants SET win=? WHERE match_id='TEST_SK_960' "
                 "AND participant_id=1", (bad_win,))
    conn.commit()
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert _n(out, AHRI) == 0, out["items"]
    assert _n(out, SYNDRA) == 1, out["items"]


def test_f4_a_real_loss_still_counts():
    conn = _build_db()
    _add_match(conn, "TEST_SK_961", team100_gold=0, team200_gold=0,
               team100_win=0, maxes=[(1, AHRI, 1, 300_000)])
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    row = _row(out, AHRI, 1)
    assert row is not None and row["n"] == 1
    assert row["observed_winrate"] == 0.0


# -- F5: EVOLVE skill-ups are not rank points --------------------------------

def test_f5_evolve_event_does_not_date_the_max_early():
    conn = _evolve_db()
    _add_match(conn, "TEST_SK_970", team100_gold=0, team200_gold=0,
               team100_win=1, maxes=[(1, KHAZIX, 1, 300_000)])
    _event(conn, "TEST_SK_970", 50_000, 1, 1, "EVOLVE")
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    row = _row(out, KHAZIX, 1)
    assert row is not None, out["items"]
    assert row["avg_max_time_s"] == 300.0, row


def test_f5_evolve_event_does_not_invent_a_max():
    conn = _evolve_db()
    _add_match(conn, "TEST_SK_971", team100_gold=0, team200_gold=0,
               team100_win=1, maxes=[], champ_by_pid={1: KHAZIX})
    for i in range(4):
        _event(conn, "TEST_SK_971", 100_000 + i * 1000, 1, 1, "NORMAL")
    _event(conn, "TEST_SK_971", 200_000, 1, 1, "EVOLVE")
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert _n(out, KHAZIX, 1) == 0, out["items"]


def test_f5_evolve_event_does_not_move_the_max_to_another_slot():
    conn = _evolve_db()
    # W is maxed (5 NORMAL points ending 300 s); Q has only 4 NORMAL
    # points plus one EVOLVE, all before 200 s.
    _add_match(conn, "TEST_SK_972", team100_gold=0, team200_gold=0,
               team100_win=1, maxes=[(1, KHAZIX, 2, 300_000)])
    for i in range(4):
        _event(conn, "TEST_SK_972", 100_000 + i * 1000, 1, 1, "NORMAL")
    _event(conn, "TEST_SK_972", 150_000, 1, 1, "EVOLVE")
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert _n(out, KHAZIX, 1) == 0, out["items"]
    assert _n(out, KHAZIX, 2) == 1, out["items"]


def test_f5_null_level_up_type_still_counts_as_normal():
    conn = _evolve_db()
    _add_match(conn, "TEST_SK_973", team100_gold=0, team200_gold=0,
               team100_win=1, maxes=[(1, AHRI, 1, 300_000)])
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert _n(out, AHRI, 1) == 1, out["items"]


def test_f5_schema_without_the_column_still_computes():
    out = skill_wpa.compute_skill_wpa(_three_matches(), min_n=0)
    assert _n(out, AHRI, 1) == 3


# -- F6: an unreadable event timestamp excludes that participant only -------

@pytest.mark.parametrize("bad_ts", [None, "garbage"])
def test_f6_unreadable_timestamp_excludes_only_that_participant(bad_ts):
    conn = _build_db()
    _add_match(conn, "TEST_SK_980", team100_gold=0, team200_gold=0,
               team100_win=1,
               maxes=[(1, AHRI, 1, 300_000), (2, SYNDRA, 1, 300_000)])
    # Corrupt the timestamp of participant 2's LAST (fifth) Q point.
    conn.execute(
        "UPDATE timeline_events SET timestamp_ms=? WHERE match_id="
        "'TEST_SK_980' AND participant_id=2 AND timestamp_ms=300000",
        (bad_ts,))
    conn.commit()
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert _n(out, AHRI, 1) == 1, out["items"]
    assert _n(out, SYNDRA, 1) == 0, out["items"]


def test_f6_unreadable_point_on_another_slot_does_not_yield_a_wrong_max():
    conn = _build_db()
    # Participant 2 maxes W at 300 s on readable points, but also has 5 Q
    # points early - one of them unreadable. Q may well have maxed first,
    # so crediting the W max (by just dropping the bad point) is a guess.
    _add_match(conn, "TEST_SK_981", team100_gold=0, team200_gold=0,
               team100_win=1,
               maxes=[(1, AHRI, 1, 300_000), (2, SYNDRA, 2, 300_000)])
    for i in range(4):
        _event(conn, "TEST_SK_981", 100_000 + i * 1000, 2, 1)
    _event(conn, "TEST_SK_981", None, 2, 1)
    out = skill_wpa.compute_skill_wpa(conn, min_n=0)
    assert _n(out, AHRI, 1) == 1, out["items"]
    assert _n(out, SYNDRA, 1) == 0, out["items"]
    assert _n(out, SYNDRA, 2) == 0, out["items"]


# -- F7: elapsed_ms is monotonic --------------------------------------------

def test_f7_elapsed_ms_never_negative_on_a_wall_clock_step():
    clock = iter(range(10**9, 0, -1000))
    with mock.patch.object(skill_wpa.time, "time",
                           side_effect=lambda: float(next(clock))):
        out = skill_wpa.compute_skill_wpa(_build_db(), min_n=1)
    assert out["elapsed_ms"] >= 0


# -- F8 / F9: the from_db wrapper -------------------------------------------

def _seed_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mem = _build_db()
    _add_match(mem, "TEST_SK_990", team100_gold=5000, team200_gold=0,
               team100_win=1, maxes=[(1, AHRI, 1, 300_000)])
    disk = sqlite3.connect(str(path))
    try:
        mem.backup(disk)
    finally:
        disk.close()
        mem.close()
    return path


def test_f8_hash_in_the_db_path_opens_the_right_file(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    out = skill_wpa.compute_skill_wpa_from_db(
        db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert out["ok"] is True, out
    assert _n(out, AHRI, 1) == 1


def test_f8_connect_uri_is_percent_encoded(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    seen: list[str] = []
    real = sqlite3.connect

    def _spy(database, *a, **kw):
        seen.append(database)
        return real(database, *a, **kw)

    with mock.patch.object(skill_wpa.sqlite3, "connect", _spy):
        skill_wpa.compute_skill_wpa_from_db(
            db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert seen and seen[0].startswith("file:///"), seen
    assert "#" not in seen[0] and seen[0].endswith("?mode=ro"), seen


def test_f8_no_stray_file_is_created_beside_a_hash_path(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    before = sorted(p.name for p in tmp_path.iterdir())
    skill_wpa.compute_skill_wpa_from_db(
        db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_f9_directory_db_path_is_the_missing_dict(tmp_path):
    d = tmp_path / "rewind_history.db"
    d.mkdir()
    assert skill_wpa.compute_skill_wpa_from_db(d) == {
        "ok": False, "error": "rewind_history.db missing"}


# -- F10: min_n validation --------------------------------------------------

@pytest.mark.parametrize("bad", [None, True, False, -1, "20", 1.5])
def test_f10_bad_min_n_is_a_value_error(bad):
    with pytest.raises(ValueError):
        skill_wpa.compute_skill_wpa(_build_db(), min_n=bad)


def test_f10_min_n_zero_is_accepted():
    out = skill_wpa.compute_skill_wpa(_three_matches(), min_n=0)
    assert out["min_n"] == 0
    assert _n(out, AHRI, 1) == 3
