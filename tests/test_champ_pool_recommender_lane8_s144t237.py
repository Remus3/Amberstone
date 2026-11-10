"""Lane 8 (true-audit) s144 cycle 237: coaches/champ_pool_recommender.py.

Each test pins one finding of the audit; the defect it guards is named in
the test. Every database here is a synthetic rewind_history.db subset in
tmp_path (synthetic ids only, RM-906); nothing reads the live store.

Measured on the live rewind DB before the fix (read-only probe):
  * 60 of the operator's 2845 seats (all Arena / CHERRY) have no ``teams``
    row, so the inner JOIN dropped every one of them (S144-T-94);
  * the assist LIKE matched 63137 kill events where the exact id match
    finds 53867 (participant 1 matched "[10, 3]");
  * 22 champions carry an internal ``champion_name`` (Kaisa, Chogath, ...)
    that differs from the display name a caller passes, so enemy-comp
    overlap never matched them.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from coaches import champ_pool_recommender as M

ME = "SYNTH-PUUID-ME"
ANNIE, OLAF, KAISA, CHOGATH = 1, 2, 145, 31
NAMES = {
    "annie": ANNIE, "olaf": OLAF,
    "kai'sa": KAISA, "kaisa": KAISA,
    "cho'gath": CHOGATH, "chogath": CHOGATH,
}
DISPLAY = {ANNIE: "Annie", OLAF: "Olaf", KAISA: "Kai'Sa", CHOGATH: "Cho'Gath"}

_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY, game_mode TEXT, game_duration_s INTEGER,
    tracked_champion_id INTEGER);
CREATE TABLE participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
    participant_id INTEGER, team_id INTEGER, puuid TEXT,
    champion_id INTEGER, champion_name TEXT, win INTEGER,
    game_ended_in_early_surrender INTEGER);
CREATE TABLE teams (match_id TEXT, team_id INTEGER, win INTEGER);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, event_type TEXT,
    killer_id INTEGER, victim_id INTEGER, assisting_ids_json TEXT);
"""


def _db(path: Path, games, *, teams_rows: bool = True) -> Path:
    """games: (match_id, my_champ, win, [(enemy_id, enemy_internal_name)])."""
    c = sqlite3.connect(str(path))
    c.executescript(_SCHEMA)
    for mid, champ, win, enemies in games:
        c.execute("INSERT INTO matches VALUES (?,?,?,?)",
                  (mid, "CLASSIC", 1800, champ))
        c.execute("INSERT INTO participants (match_id, participant_id,"
                  " team_id, puuid, champion_id, champion_name, win,"
                  " game_ended_in_early_surrender) VALUES (?,?,?,?,?,?,?,0)",
                  (mid, 1, 100, ME, champ, DISPLAY.get(champ, "X"), win))
        for i, (eid, ename) in enumerate(enemies):
            c.execute("INSERT INTO participants (match_id, participant_id,"
                      " team_id, puuid, champion_id, champion_name, win,"
                      " game_ended_in_early_surrender)"
                      " VALUES (?,?,?,?,?,?,?,0)",
                      (mid, 6 + i, 200, f"SYNTH-PUUID-E{mid}{i}", eid, ename,
                       1 - win))
        if teams_rows:
            c.execute("INSERT INTO teams VALUES (?,?,?)", (mid, 100, win))
            c.execute("INSERT INTO teams VALUES (?,?,?)", (mid, 200, 1 - win))
    c.commit()
    c.close()
    return path


@pytest.fixture
def mod(tmp_path, monkeypatch):
    """The module with every cache reset and every path in tmp_path."""
    monkeypatch.setattr(M, "_user_puuid", None)
    monkeypatch.setattr(M, "_name_to_id", dict(NAMES))
    monkeypatch.setattr(M, "_id_to_name", dict(DISPLAY))
    monkeypatch.setattr(M, "_KDA_FILE", tmp_path / "absent_champ_kda.json")
    monkeypatch.setattr(M, "_kda_materialized", None)
    monkeypatch.setattr(M, "_kda_mtime", 0.0)
    monkeypatch.setattr(M, "_REWIND_DB", tmp_path / "rewind_history.db")
    return M


# -- F1: a seat with no teams row (Arena) is counted, not dropped ---------

def test_seat_without_teams_row_still_counts(mod, tmp_path):
    _db(mod._REWIND_DB, [("SYN_A1", ANNIE, 1, [(OLAF, "Olaf")]),
                         ("SYN_A2", ANNIE, 0, [(OLAF, "Olaf")])],
        teams_rows=False)
    out = mod.recommend(["Annie"], ["Olaf"])
    assert len(out) == 1, out
    assert out[0]["total_games_on_champ"] == 2
    assert (out[0]["games"], out[0]["wins"]) == (2, 1)


def test_teams_row_win_still_wins_over_participant_win(mod):
    """Where both exist the team row stays the authority (no behaviour
    change for the 2785 seats the inner join already kept)."""
    _db(mod._REWIND_DB, [("SYN_B1", ANNIE, 1, [(OLAF, "Olaf")])])
    c = sqlite3.connect(str(mod._REWIND_DB))
    c.execute("UPDATE participants SET win = 0 WHERE puuid = ?", (ME,))
    c.commit()
    c.close()
    out = mod.recommend(["Annie"], ["Olaf"])
    assert out[0]["wins"] == 1


# -- F2: the live assist count matches the id, not a substring ------------

def _kill_events(path: Path, rows) -> None:
    c = sqlite3.connect(str(path))
    for killer, victim, assists in rows:
        c.execute("INSERT INTO timeline_events (match_id, event_type,"
                  " killer_id, victim_id, assisting_ids_json)"
                  " VALUES ('SYN_K1', 'CHAMPION_KILL', ?, ?, ?)",
                  (killer, victim, assists))
    c.commit()
    c.close()


def test_live_assists_do_not_substring_match_participant_ids(mod):
    _db(mod._REWIND_DB, [("SYN_K1", ANNIE, 1, [(OLAF, "Olaf")])])
    _kill_events(mod._REWIND_DB, [
        (2, 6, "[10, 3]"),   # participant 1 is NOT in it
        (2, 7, "[1]"),       # it is
        (3, 8, "[4, 1, 5]"),  # it is
        (2, 9, "[21]"),      # it is not
        (2, 6, None),        # no assists at all
    ])
    c = mod._open()
    try:
        kk, dd, aa, games = mod._kda_for(c, ME, ANNIE)
    finally:
        c.close()
    assert aa == 2
    assert games == 1


def test_builder_assists_do_not_substring_match(tmp_path, monkeypatch):
    """Sibling of the same root cause: scripts/build_champ_kda.py wrote
    the over-counted assists into the materialized champ_kda.json."""
    import scripts.build_champ_kda as B
    db = _db(tmp_path / "rewind_history.db",
             [("SYN_K1", ANNIE, 1, [(OLAF, "Olaf")])])
    _kill_events(db, [(2, 6, "[10, 3]"), (2, 7, "[1]"), (2, 9, "[11, 21]")])
    out = tmp_path / "champ_kda.json"
    monkeypatch.setattr(B, "REWIND_DB", db)
    monkeypatch.setattr(B, "OUT", out)
    monkeypatch.setattr(B, "DDR", tmp_path / "absent_ddragon.json")
    assert B.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["champions"][str(ANNIE)]["assists"] == 1


# -- F3: enemy comp matches by champion id, not by internal name ----------

def test_enemy_comp_matches_display_names_by_id(mod):
    comp = [(KAISA, "Kaisa"), (CHOGATH, "Chogath")]
    _db(mod._REWIND_DB, [(f"SYN_C{i}", ANNIE, 1, comp) for i in range(3)]
        + [("SYN_C9", ANNIE, 0, [(OLAF, "Olaf")])])
    out = mod.recommend(["Annie"], ["Kai'Sa", "Cho'Gath"], min_games=3)
    assert out[0]["sample"] == "vs comp", out
    assert out[0]["games"] == 3


def test_unknown_enemy_name_still_matches_by_name(mod):
    """A name the champion index cannot resolve keeps the old name match."""
    comp = [(900, "Newchamp"), (OLAF, "Olaf")]
    _db(mod._REWIND_DB, [(f"SYN_U{i}", ANNIE, 1, comp) for i in range(3)])
    out = mod.recommend(["Annie"], ["Newchamp", "Olaf"], min_games=3)
    assert out[0]["sample"] == "vs comp", out


# -- F4: the rewind DB is opened read-only ---------------------------------

def test_open_is_read_only(mod):
    _db(mod._REWIND_DB, [("SYN_R1", ANNIE, 1, [(OLAF, "Olaf")])])
    c = mod._open()
    try:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("DELETE FROM matches")
    finally:
        c.close()


def test_open_missing_db_answers_none_and_creates_nothing(mod):
    assert mod._open() is None
    assert not mod._REWIND_DB.exists()


# -- F5: a broken database degrades to [] instead of raising ---------------

def test_corrupt_db_degrades_to_empty(mod, caplog):
    mod._REWIND_DB.write_bytes(b"not a sqlite database at all" * 64)
    with caplog.at_level(logging.WARNING, logger="rc.champ_pool_recommender"):
        assert mod.recommend(["Annie"], ["Olaf"]) == []
    assert any("recommend" in r.getMessage() for r in caplog.records)


def test_missing_table_degrades_to_empty(mod):
    _db(mod._REWIND_DB, [("SYN_M1", ANNIE, 1, [(OLAF, "Olaf")])])
    c = sqlite3.connect(str(mod._REWIND_DB))
    c.execute("DROP TABLE timeline_events")
    c.commit()
    c.close()
    assert mod.recommend(["Annie"], ["Olaf"]) == []


# -- F6: a junk materialized KDA file falls back to live SQL ---------------

@pytest.mark.parametrize("champions", [
    {str(ANNIE): {"kills": "x", "deaths": 1, "assists": 1}},
    {str(ANNIE): {"kills": None, "deaths": 1, "assists": 1}},
    {str(ANNIE): ["not", "a", "dict"]},
    [{"kills": 1}],
    {str(ANNIE): {"kills": True, "deaths": 1, "assists": 1}},
    {str(ANNIE): {"kills": -5, "deaths": 1, "assists": 1}},
])
def test_junk_materialized_kda_falls_back(mod, tmp_path, champions):
    _db(mod._REWIND_DB, [("SYN_K1", ANNIE, 1, [(OLAF, "Olaf")])])
    _kill_events(mod._REWIND_DB, [(1, 6, None), (2, 7, "[1]")])
    kda = tmp_path / "champ_kda.json"
    kda.write_text(json.dumps({"champions": champions}), encoding="utf-8")
    mod._KDA_FILE = kda
    c = mod._open()
    try:
        assert mod._kda_for(c, ME, ANNIE) == (1, 0, 1, 1)
    finally:
        c.close()


def test_valid_materialized_kda_is_used(mod, tmp_path):
    _db(mod._REWIND_DB, [("SYN_K1", ANNIE, 1, [(OLAF, "Olaf")])])
    kda = tmp_path / "champ_kda.json"
    kda.write_text(json.dumps({"champions": {str(ANNIE): {
        "games": 4, "kills": 9, "deaths": 3, "assists": 6}}}),
        encoding="utf-8")
    mod._KDA_FILE = kda
    c = mod._open()
    try:
        assert mod._kda_for(c, ME, ANNIE) == (9, 3, 6, 4)
    finally:
        c.close()


# -- F7: junk DDragon shapes never raise ------------------------------------

@pytest.mark.parametrize("payload", [
    [1, 2, 3],
    {"data": [1, 2]},
    {"data": {"Annie": "not a dict", "Olaf": {"key": "2", "name": 7}}},
])
def test_junk_ddragon_shapes_do_not_raise(tmp_path, monkeypatch, payload):
    p = tmp_path / "ddragon_champions.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(M, "_DDR_CHAMPS", p)
    monkeypatch.setattr(M, "_name_to_id", {})
    monkeypatch.setattr(M, "_id_to_name", {})
    M._load_champ_index()
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        # the bad display name falls back to the slug
        assert M._name_to_id.get("olaf") == 2
        assert M._id_to_name[2] == "Olaf"


# -- F8: bare strings and junk members are not iterated per character ------

def test_bare_string_pool_and_comp_are_one_name(mod):
    _db(mod._REWIND_DB, [("SYN_S1", ANNIE, 1, [(OLAF, "Olaf")])])
    out = mod.recommend("Annie", "Olaf")
    assert [r["champion"] for r in out] == ["Annie"]


def test_junk_enemy_members_do_not_raise(mod):
    _db(mod._REWIND_DB, [("SYN_J1", ANNIE, 1, [(OLAF, "Olaf")])])
    out = mod.recommend(["Annie", None, 7], ["Olaf", 123, None, ""])
    assert [r["champion"] for r in out] == ["Annie"]


def test_duplicate_pool_entries_give_one_row(mod):
    _db(mod._REWIND_DB, [("SYN_D1", ANNIE, 1, [(OLAF, "Olaf")])])
    out = mod.recommend(["Annie", "annie", "ANNIE"], ["Olaf"])
    assert len(out) == 1


# -- F9: min_games below 1 cannot label an empty sample "vs comp" ----------

@pytest.mark.parametrize("bad", [0, -2, "3", None, True])
def test_min_games_junk_never_yields_empty_vs_comp(mod, bad):
    _db(mod._REWIND_DB, [("SYN_G1", ANNIE, 1, [(OLAF, "Olaf")]),
                         ("SYN_G2", ANNIE, 1, [(OLAF, "Olaf")])])
    out = mod.recommend(["Annie"], ["Kai'Sa", "Cho'Gath"], min_games=bad)
    assert out[0]["sample"] == "vs any", out
    assert out[0]["games"] == 2
