"""s144 lane 8 (true-audit) cycle 95 - core/summoner_spell_wpa.py hardening.

One test (or one small group) per audited weakness (F1-F11), each written
RED against the pre-fix module. Synthetic data only: hand-written match
ids, an in-memory or tmp sqlite DB (never the live corpus).

F1  sqlite3.Error inside the per-match loop was swallowed, so a locked
    DB served a silently partial corpus as ok=True (RM-1262, summoner
    spell half).
F2  a match that failed after its first participant was counted stayed
    half-counted; observations now merge only for a cleanly read match.
F3  the per-match catch was ``except Exception``, so a programming error
    was logged once per match and answered ok=True.
F4  a NULL (or out-of-range, or non-numeric) participants.win was read
    as a LOSS (or as a 2-win) and biased observed_winrate (RM-1331,
    summoner spell half).
F5  one non-numeric summoner1_id / summoner2_id raised out of
    _participant_spells and dropped EVERY participant of its match; a
    fractional id was truncated onto a real spell. Now only that spell
    is skipped.
F6  a spell stored in both slots of one participant counted twice; now
    once per participant (the rune_wpa F10 sibling).
F7  load_spell_catalog raised on a wrong-shape catalog despite its
    fail-soft promise, and a bool ``key`` was read as spell 1 (Cleanse).
F8  elapsed_ms came from the wall clock (negative on a clock step).
F9  compute_summoner_spell_wpa_from_db built its read-only URI with an
    f-string, so a '#' in the path opened the wrong file (RM-1260).
F10 compute_summoner_spell_wpa_from_db treated a DIRECTORY as a present
    DB and raised, instead of the documented "missing" dict.
F11 min_n was never validated (None / bool / negative / str / float).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from core import summoner_spell_wpa as ssw
from tests.test_summspell_wpa import FLASH, IGNITE, TELEPORT, _add_match, _build_db


def _n(result: dict, spell: int) -> int:
    for it in result["items"]:
        if it["spell_id"] == spell:
            return it["n"]
    return 0


def _row(result: dict, spell: int) -> dict | None:
    for it in result["items"]:
        if it["spell_id"] == spell:
            return it
    return None


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
        _add_match(conn, f"TEST_SS_95{i}", team100_gold=5000, team200_gold=0,
                   team100_win=1, spells={1: (FLASH, IGNITE)})
    return conn


# -- F1: sqlite3.Error propagates out of the sweep --------------------------

def test_f1_locked_db_mid_sweep_raises_instead_of_partial_ok():
    proxy = _Proxy(_three_matches(), 2,
                   sqlite3.OperationalError("database is locked"))
    with pytest.raises(sqlite3.OperationalError):
        ssw.compute_summoner_spell_wpa(proxy, min_n=1)


def test_f1_route_answers_503_and_caches_nothing(tmp_path):
    from dashboard import routes_summspell_wpa as rss
    from tests.test_routes_summspell_wpa_audit_s144 import _one, _seed, _serve

    db = _seed(tmp_path / "rh.db")
    real_open = rss._open_rewind_db_ro

    class _Wrap:
        def __init__(self):
            self._p = _Proxy(real_open(), 2,
                             sqlite3.OperationalError("database is locked"))

        def execute(self, sql, *a):
            return self._p.execute(sql, *a)

        def close(self):
            self._p._conn.close()

    rss._CACHE.clear()
    try:
        with mock.patch.object(rss, "_open_rewind_db_ro", _Wrap):
            status, payload = _one(_serve("/api/summspell-wpa?min_n=1", db))
        assert status == 503, payload
        assert payload["ok"] is False
        assert rss._CACHE == {}
    finally:
        rss._CACHE.clear()


# -- F2: a match skipped half-way contributes nothing -----------------------

def test_f2_match_failing_after_first_participant_is_rolled_back_whole():
    conn = _build_db()
    _add_match(conn, "TEST_SS_960", team100_gold=0, team200_gold=0,
               team100_win=1, spells={1: (FLASH, IGNITE), 6: (FLASH, IGNITE)})
    real = ssw._expected_win_for_team
    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("malformed frame value")
        return real(*a, **kw)

    with mock.patch.object(ssw, "_expected_win_for_team", _flaky):
        out = ssw.compute_summoner_spell_wpa(conn, min_n=0)
    assert calls["n"] == 2
    assert out["ok"] is True
    assert _n(out, FLASH) == 0, out["items"]
    assert _n(out, IGNITE) == 0, out["items"]


# -- F3: a defect surfaces instead of a per-match log line ------------------

def test_f3_programming_error_surfaces():
    conn = _three_matches()
    with mock.patch.object(ssw, "_expected_win_for_team",
                           side_effect=RuntimeError("defect")):
        with pytest.raises(RuntimeError):
            ssw.compute_summoner_spell_wpa(conn, min_n=1)


def test_f3_data_error_still_skips_the_match(caplog):
    conn = _three_matches()
    real = ssw._expected_win_for_team
    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("bad frame row")
        return real(*a, **kw)

    with caplog.at_level(logging.WARNING, logger="rc.summoner_spell_wpa"), \
         mock.patch.object(ssw, "_expected_win_for_team", _flaky):
        out = ssw.compute_summoner_spell_wpa(conn, min_n=1)
    assert out["ok"] is True
    assert _n(out, FLASH) == 2
    assert any("skipped" in r.getMessage() for r in caplog.records)


# -- F4: an unknown outcome is not a loss -----------------------------------

@pytest.mark.parametrize("bad_win", [None, 2, -1, "x"])
def test_f4_unknown_win_contributes_no_sample(bad_win):
    conn = _build_db()
    _add_match(conn, "TEST_SS_970", team100_gold=0, team200_gold=0,
               team100_win=1, spells={1: (FLASH, IGNITE), 2: (TELEPORT, 0)})
    conn.execute("UPDATE participants SET win=? WHERE match_id='TEST_SS_970' "
                 "AND participant_id=1", (bad_win,))
    conn.commit()
    out = ssw.compute_summoner_spell_wpa(conn, min_n=0)
    assert _n(out, FLASH) == 0, out["items"]
    assert _n(out, IGNITE) == 0, out["items"]
    assert _n(out, TELEPORT) == 1, out["items"]


def test_f4_a_real_loss_still_counts():
    conn = _build_db()
    _add_match(conn, "TEST_SS_971", team100_gold=0, team200_gold=0,
               team100_win=0, spells={1: (FLASH, IGNITE)})
    out = ssw.compute_summoner_spell_wpa(conn, min_n=0)
    row = _row(out, FLASH)
    assert row is not None and row["n"] == 1
    assert row["observed_winrate"] == 0.0


# -- F5: a bad spell column skips that spell only ---------------------------

@pytest.mark.parametrize("bad_spell", ["garbage", 4.5, b"\x04"])
def test_f5_bad_spell_column_skips_that_spell_only(bad_spell):
    conn = _build_db()
    _add_match(conn, "TEST_SS_980", team100_gold=0, team200_gold=0,
               team100_win=1, spells={1: (FLASH, IGNITE), 2: (TELEPORT, IGNITE)})
    conn.execute("UPDATE participants SET summoner1_id=? WHERE match_id="
                 "'TEST_SS_980' AND participant_id=1", (bad_spell,))
    conn.commit()
    out = ssw.compute_summoner_spell_wpa(conn, min_n=0)
    assert _n(out, FLASH) == 0, out["items"]
    assert _n(out, IGNITE) == 2, out["items"]
    assert _n(out, TELEPORT) == 1, out["items"]


def test_f5_integral_float_spell_id_is_that_spell():
    conn = _build_db()
    _add_match(conn, "TEST_SS_981", team100_gold=0, team200_gold=0,
               team100_win=1, spells={1: (FLASH, IGNITE)})
    conn.execute("UPDATE participants SET summoner1_id=4.0 WHERE match_id="
                 "'TEST_SS_981' AND participant_id=1")
    conn.commit()
    out = ssw.compute_summoner_spell_wpa(conn, min_n=0)
    assert _n(out, FLASH) == 1, out["items"]


# -- F6: one participant counts a spell once --------------------------------

def test_f6_spell_in_both_slots_counts_once():
    conn = _build_db()
    _add_match(conn, "TEST_SS_985", team100_gold=0, team200_gold=0,
               team100_win=1, spells={1: (FLASH, FLASH), 2: (FLASH, IGNITE)})
    out = ssw.compute_summoner_spell_wpa(conn, min_n=0)
    assert _n(out, FLASH) == 2, out["items"]
    assert _n(out, IGNITE) == 1, out["items"]


# -- F7: load_spell_catalog is fail-soft on a wrong shape -------------------

@pytest.mark.parametrize("doc", [
    {"data": [1, 2]},
    {"data": "SummonerFlash"},
    {"data": 7},
    [1, 2],
    "x",
])
def test_f7_wrong_shape_catalog_is_empty_not_a_raise(tmp_path, doc):
    p = tmp_path / "summoner.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert ssw.load_spell_catalog(p) == {}


def test_f7_wrong_shape_catalog_does_not_crash_the_sweep(tmp_path):
    p = tmp_path / "summoner.json"
    p.write_text(json.dumps({"data": [1]}), encoding="utf-8")
    out = ssw.compute_summoner_spell_wpa(_three_matches(), min_n=0,
                                         summoner_json=p)
    assert out["ok"] is True and out["items"] == []


def test_f7_bool_key_is_not_spell_one(tmp_path):
    p = tmp_path / "summoner.json"
    p.write_text(json.dumps({"data": {
        "SummonerBoost": {"key": True, "name": "Cleanse", "id": "SummonerBoost"},
        "SummonerFlash": {"key": "4", "name": "Flash", "id": "SummonerFlash"},
    }}), encoding="utf-8")
    cat = ssw.load_spell_catalog(p)
    assert 1 not in cat
    assert cat[4] == ("Flash", "SummonerFlash")


# -- F8: elapsed_ms is monotonic --------------------------------------------

def test_f8_elapsed_ms_never_negative_on_a_wall_clock_step():
    clock = iter(range(10**9, 0, -1000))
    with mock.patch.object(ssw.time, "time",
                           side_effect=lambda: float(next(clock))):
        out = ssw.compute_summoner_spell_wpa(_build_db(), min_n=1)
    assert out["elapsed_ms"] >= 0


# -- F9 / F10: the from_db wrapper ------------------------------------------

def _seed_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mem = _build_db()
    _add_match(mem, "TEST_SS_990", team100_gold=5000, team200_gold=0,
               team100_win=1, spells={1: (FLASH, IGNITE)})
    disk = sqlite3.connect(str(path))
    try:
        mem.backup(disk)
    finally:
        disk.close()
        mem.close()
    return path


def test_f9_hash_in_the_db_path_opens_the_right_file(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    out = ssw.compute_summoner_spell_wpa_from_db(
        db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert out["ok"] is True, out
    assert _n(out, FLASH) == 1


def test_f9_connect_uri_is_percent_encoded(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    seen: list[str] = []
    real = sqlite3.connect

    def _spy(database, *a, **kw):
        seen.append(database)
        return real(database, *a, **kw)

    with mock.patch.object(ssw.sqlite3, "connect", _spy):
        ssw.compute_summoner_spell_wpa_from_db(
            db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert seen and seen[0].startswith("file:///"), seen
    assert "#" not in seen[0] and seen[0].endswith("?mode=ro"), seen


def test_f9_no_stray_file_is_created_beside_a_hash_path(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    before = sorted(p.name for p in tmp_path.iterdir())
    ssw.compute_summoner_spell_wpa_from_db(
        db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_f10_directory_db_path_is_the_missing_dict(tmp_path):
    d = tmp_path / "rewind_history.db"
    d.mkdir()
    assert ssw.compute_summoner_spell_wpa_from_db(d) == {
        "ok": False, "error": "rewind_history.db missing"}


# -- F11: min_n validation --------------------------------------------------

@pytest.mark.parametrize("bad", [None, True, False, -1, "20", 1.5])
def test_f11_bad_min_n_is_a_value_error(bad):
    with pytest.raises(ValueError):
        ssw.compute_summoner_spell_wpa(_build_db(), min_n=bad)


def test_f11_min_n_zero_is_accepted():
    out = ssw.compute_summoner_spell_wpa(_three_matches(), min_n=0)
    assert out["min_n"] == 0
    assert _n(out, FLASH) == 3
