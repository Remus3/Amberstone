"""P2-5 - runtime sqlite stores in their states: absent / empty-but-valid
(schema, zero rows) / populated, plus a 0-byte file and a header-only file
with no tables (both are valid empty sqlite databases to the library, and a
crash between create and schema can leave either).

For each reader the READ result is asserted per state, and a WRITE is asserted
to round-trip (write, re-read, the row lands) from every state. States are
declared once per store via tests/_store_states.py; every file is in tmp_path.

Symbols used (file:line at time of writing):
  core/match_db.py:84 _SCHEMA, :134 MatchDB, :204 save_match, :280 get_recent,
    :340 get_tft_streak, :360 get_mode_stats, :379 close
  core/augment_recommender.py:138 _scan_own_history_checked, :220 _lcu_row_count,
    :248 load_own_history (OwnHistory.n_matches :82, .games :76), :394 reset_cache
  core/draft_elo_db.py:55 _resolve_db_path (RC_REWIND_DB), :68 open_ro,
    :91 solo_winrate, :122 pair_winrate
  core/patch_impact.py:41 _REWIND_DB, :54 _open_ro, :113 _played_champions,
    :202 compute_patch_impact, :313 _empty
  scripts/rewind_scraper.py:86 SCHEMA (the production rewind_history.db DDL)
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core import augment_recommender as R
from core import draft_elo_db
from core import match_db
from core import patch_impact as pi
from tests._store_states import (
    ABSENT,
    EMPTY,
    NO_TABLES,
    POPULATED,
    SQLITE_STATES_ALL,
    ZERO_BYTE,
    parametrize_states,
    sqlite_store,
)

_BROKEN = (ZERO_BYTE, NO_TABLES)  # a file is present but carries no schema

# ---------------------------------------------------------------------------
# match_history.db - writer core.match_db.MatchDB; readers MatchDB itself and
# core.augment_recommender (own augment history).
# ---------------------------------------------------------------------------

_TP = "tracked-puuid-p25"


def _raw_kiwi(augs, won):
    stats = {"win": bool(won)}
    for i, a in enumerate(augs, 1):
        stats[f"playerAugment{i}"] = a
    return json.dumps({
        "tracked_puuid": _TP,
        "lcu_match_detail": {
            "gameMode": "KIWI", "queueId": 2400,
            "participantIdentities": [{"participantId": 1, "player": {"puuid": _TP}}],
            "participants": [{"participantId": 1, "stats": stats}],
        },
    })


def _seed_match_history(conn):
    conn.execute(
        "INSERT INTO matches (timestamp, mode, champion, grade, kills, "
        "game_id, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-10-01 12:00:00", "ARAM", "Jinx", "A", 7, 111,
         _raw_kiwi([10, 20], True)))


MATCH_HISTORY = sqlite_store("match_history", "data/match_history.db",
                             schema=lambda: match_db._SCHEMA,
                             seed=_seed_match_history)


def _prior_rows(state):
    return 1 if state == POPULATED else 0


@pytest.fixture
def opened():
    """Close every MatchDB a test opens, so tmp_path cleanup is not blocked."""
    dbs = []

    def open_db(path):
        db = match_db.MatchDB(path)
        dbs.append(db)
        return db
    yield open_db
    for db in dbs:
        db.close()


@parametrize_states(SQLITE_STATES_ALL)
def test_match_db_read_per_state(tmp_path, opened, state):
    path = MATCH_HISTORY.build(tmp_path, state)
    db = opened(path)
    recent = db.get_recent()
    assert len(recent) == _prior_rows(state)
    if state == POPULATED:
        assert recent[0]["game_id"] == 111
        assert db.get_mode_stats("ARAM")["games"] == 1
    else:
        assert db.get_mode_stats("ARAM") == {}
    assert db.get_tft_streak() == {}


@parametrize_states(SQLITE_STATES_ALL)
def test_match_db_save_round_trips_from_each_state(tmp_path, opened, state):
    path = MATCH_HISTORY.build(tmp_path, state)
    assert opened(path).save_match(
        {"mode": "SR", "champion": "Ahri", "grade": "S", "kills": 9,
         "game_id": 222}) is True
    rows = opened(path).get_recent(limit=50)  # a fresh handle re-reads disk
    assert len(rows) == _prior_rows(state) + 1
    saved = [r for r in rows if r["game_id"] == 222]
    assert len(saved) == 1 and saved[0]["champion"] == "Ahri"
    assert saved[0]["kills"] == 9


@pytest.fixture
def fresh_reco_cache():
    R.reset_cache()
    yield
    R.reset_cache()


@parametrize_states(SQLITE_STATES_ALL)
def test_augment_own_history_read_per_state(tmp_path, fresh_reco_cache, state):
    path = MATCH_HISTORY.build(tmp_path, state)
    hist = R.load_own_history("mayhem", db_path=path)
    assert hist.n_matches == _prior_rows(state)
    if state == POPULATED:
        assert hist.games == {10: 1, 20: 1}


@parametrize_states(SQLITE_STATES_ALL)
def test_augment_own_history_sees_a_save_from_each_state(
        tmp_path, opened, fresh_reco_cache, state):
    path = MATCH_HISTORY.build(tmp_path, state)
    before = R.load_own_history("mayhem", db_path=path)
    assert before.n_matches == _prior_rows(state)
    # The real writer lands a new augment-bearing game ...
    assert opened(path).save_match(
        {"mode": "ARAM", "raw_data": _raw_kiwi([30], False)}) is True
    # ... and the very next read must see it (no stale cached empty state).
    after = R.load_own_history("mayhem", db_path=path)
    assert after.n_matches == _prior_rows(state) + 1
    assert after.games.get(30) == 1


# ---------------------------------------------------------------------------
# rewind_history.db - production DDL scripts/rewind_scraper.py SCHEMA; readers
# core.draft_elo_db and core.patch_impact (both read-only consumers).
# ---------------------------------------------------------------------------

def _rewind_schema():
    from scripts.rewind_scraper import SCHEMA
    return SCHEMA


def _insert_rewind_game(conn, match_id, champ=222, win=1):
    conn.execute(
        "INSERT INTO matches (match_id, queue_id, map_id, game_duration_s, "
        "tracked_champion_id, tracked_win) VALUES (?, 450, 12, 1200, ?, ?)",
        (match_id, champ, win))
    conn.execute(
        "INSERT INTO participants (match_id, participant_id, team_id, "
        "champion_id, win) VALUES (?, 1, 100, ?, ?)",
        (match_id, champ, win))


def _seed_rewind(conn):
    for i in range(5):  # 5 = patch_impact DEFAULT_MIN_GAMES
        _insert_rewind_game(conn, f"NA1_{i}", win=1 if i < 3 else 0)


REWIND = sqlite_store("rewind_history", "data/rewind_history.db",
                      schema=_rewind_schema, seed=_seed_rewind)


def _write_rewind_game(path, match_id):
    """Stand-in for the out-of-core writer: ensure schema, insert one game."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_rewind_schema())
        _insert_rewind_game(conn, match_id)
        conn.commit()
    finally:
        conn.close()


def _solo(path):
    conn = draft_elo_db.open_ro(path)
    try:
        return draft_elo_db.solo_winrate(conn, 222, [450])
    finally:
        conn.close()


@parametrize_states(SQLITE_STATES_ALL)
def test_draft_elo_read_per_state(tmp_path, monkeypatch, state):
    path = REWIND.build(tmp_path, state)
    monkeypatch.setenv("RC_REWIND_DB", str(path))
    if state == ABSENT:
        # The route maps this to 503 "rewind history unavailable".
        with pytest.raises(sqlite3.OperationalError):
            draft_elo_db.open_ro()
        assert not path.exists(), "a read-only open must never create the db"
        return
    conn = draft_elo_db.open_ro()  # resolved through RC_REWIND_DB
    try:
        if state in _BROKEN:
            with pytest.raises(sqlite3.OperationalError):
                draft_elo_db.solo_winrate(conn, 222, [450])
            return
        wins, games, smoothed = draft_elo_db.solo_winrate(conn, 222, [450])
        pair = draft_elo_db.pair_winrate(conn, 222, 64, [450])
    finally:
        conn.close()
    if state == EMPTY:
        assert (wins, games, smoothed) == (0, 0, 0.5)
    else:
        assert (wins, games) == (3, 5) and 0.5 < smoothed < 1.0
    assert pair == (0, 0, 0.5)


@parametrize_states(SQLITE_STATES_ALL)
def test_draft_elo_sees_a_written_game_from_each_state(tmp_path, state):
    path = REWIND.build(tmp_path, state)
    prior = 5 if state == POPULATED else 0
    _write_rewind_game(path, "NA1_new")
    assert _solo(path)[1] == prior + 1


def _report():
    return {"sections": {"champions": {"changed": [
        {"id": "Jinx", "fields": {"stats.attackdamage": [59, 57]}}]}}}


_KEY_MAP = {222: {"id": "Jinx", "name": "Jinx"}}


def _impact():
    return pi.compute_patch_impact(
        mode="aram", diff_fn=lambda *a, **k: _report(),
        patches=["16.13.1", "16.14.1"], key_map=_KEY_MAP)


@pytest.fixture
def rewind_at(tmp_path, monkeypatch):
    def build(state):
        path = REWIND.build(tmp_path, state)
        monkeypatch.setattr(pi, "_REWIND_DB", path)
        return path
    return build


@parametrize_states(SQLITE_STATES_ALL)
def test_patch_impact_read_per_state(rewind_at, state):
    path = rewind_at(state)
    out = _impact()
    assert out["ok"] is True
    if state == POPULATED:
        assert [c["champion"] for c in out["champions"]] == ["Jinx"]
        assert out["n_matches"] == 5 and out["reason"] is None
        return
    assert out["champions"] == [] and out["n_matches"] == 0
    if state == EMPTY:
        # A valid corpus with no games yet: the panel's own "-" copy applies.
        assert out["reason"] is None
    else:
        # No usable db at all must be SAID, not rendered as "no games yet"
        # (module docstring: a missing db returns "a stated reason").
        assert out["reason"] and "match history" in out["reason"]
    if state == ABSENT:
        assert not path.exists(), "a read-only open must never create the db"


@parametrize_states(SQLITE_STATES_ALL)
def test_patch_impact_sees_written_games_from_each_state(rewind_at, state):
    path = rewind_at(state)
    for i in range(5):
        _write_rewind_game(path, f"NA1_w{i}")
    out = _impact()
    expected = 10 if state == POPULATED else 5
    assert out["n_matches"] == expected and out["reason"] is None
    assert out["champions"][0]["games"] == expected
