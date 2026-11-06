"""s144 true-audit of core/opening_tendency.py (RM-1839..RM-1846).

Every regression here is a measured weakness of the per-puuid opening
metrics behind POST /api/scouting: junk timeline rows read as a real map
location, one bad row dropping a whole game, a non-sqlite error escaping
the "never raises" entry point, a non-positive min_games fabricating a
mode out of zero games, and the result cache handing callers its own
mutable dicts. All data is SYNTHETIC (no real Riot ids or payloads).
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core import opening_tendency as ot

BLUE_TOP_JG = (3800, 7900)
BOT_KILL = (11000, 1500)
MID_LANE = (6500, 6500)

JG = "puuid-synthetic-jungler"
LANER = "puuid-synthetic-laner"


def _game(mid, *, jg_1=BLUE_TOP_JG, kills=(), extra_frames=(),
          participants=None):
    parts = participants if participants is not None else [
        {"participant_id": 2, "team_id": 100, "puuid": JG,
         "team_position": "JUNGLE", "summoner1_id": 4, "summoner2_id": 11},
        {"participant_id": 3, "team_id": 100, "puuid": LANER,
         "team_position": "MIDDLE", "summoner1_id": 4, "summoner2_id": 14},
    ]
    frames = list(extra_frames) + [
        {"timestamp_ms": 60011, "participant_id": 2,
         "pos_x": jg_1[0], "pos_y": jg_1[1]},
        {"timestamp_ms": 120020, "participant_id": 2,
         "pos_x": BLUE_TOP_JG[0], "pos_y": BLUE_TOP_JG[1]},
        {"timestamp_ms": 60011, "participant_id": 3,
         "pos_x": MID_LANE[0], "pos_y": MID_LANE[1]},
    ]
    return {"match_id": mid, "queue_id": 420, "map_id": 11,
            "has_timeline": True, "participants": parts,
            "frames": frames, "kills": list(kills)}


def _kill(ts, killer, assists, pos):
    return {"timestamp_ms": ts, "killer_id": killer, "assists": assists,
            "pos_x": pos[0], "pos_y": pos[1]}


# --- RM-1839: to_frac really never raises ----------------------------------

@pytest.mark.parametrize("bad", [10 ** 400, -(10 ** 400)],
                         ids=["huge", "neg-huge"])
def test_to_frac_huge_int_does_not_raise(bad):
    x, y = ot.to_frac(bad, bad)
    assert x != x and y != y  # nan, nan


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), True, b"12"])
def test_to_frac_non_finite_or_non_number_is_nan(bad):
    x, y = ot.to_frac(bad, 100)
    assert x != x and y != y


# --- RM-1840: a junk 1:00 position is not a real location ------------------

@pytest.mark.parametrize("junk", ["abc", float("inf"), float("nan"), True,
                                  b"\x00", 10 ** 400],
                         ids=["str", "inf", "nan", "bool", "bytes", "huge"])
def test_junk_one_minute_position_is_no_observation(junk):
    """Before: a junk position fell to district_of's fallback (blue_base),
    so the game counted as a real level-1 'base' observation."""
    g = _game("m1", jg_1=(junk, 7900))
    # With no other 1:00 frame for the player the game is excluded.
    g["frames"] = [f for f in g["frames"]
                   if not (f["participant_id"] == 2
                           and f["timestamp_ms"] == 120020)]
    assert ot.classify_game(g, JG) is None


def test_junk_frame_is_skipped_for_a_clean_one_in_tolerance():
    g = _game("m1", extra_frames=[
        {"timestamp_ms": 60000, "participant_id": 2,
         "pos_x": "abc", "pos_y": 7900}])
    obs = ot.classify_game(g, JG)
    assert obs is not None
    assert obs["start_side"] == "top"
    assert obs["level1_lane"] == "jungle"


def test_junk_kill_position_buckets_as_other_not_base():
    g = _game("m1", kills=[_kill(200000, 2, [], ("abc", float("inf")))])
    assert ot.classify_game(g, JG)["first_gank_lane"] == "other"


# --- RM-1841: one bad row drops that row, never the whole game -------------

@pytest.mark.parametrize("ts", [float("inf"), float("-inf"), 10 ** 400],
                         ids=["inf", "neg-inf", "huge"])
def test_overflowing_frame_timestamp_skips_only_that_frame(ts):
    g = _game("m1", extra_frames=[
        {"timestamp_ms": ts, "participant_id": 2,
         "pos_x": BLUE_TOP_JG[0], "pos_y": BLUE_TOP_JG[1]}])
    obs = ot.classify_game(g, JG)
    assert obs is not None and obs["start_side"] == "top"


@pytest.mark.parametrize("ts", [float("inf"), 10 ** 400],
                         ids=["inf", "huge"])
def test_overflowing_kill_timestamp_skips_only_that_kill(ts):
    g = _game("m1", kills=[_kill(ts, 2, [], BOT_KILL),
                           _kill(200000, 2, [], BOT_KILL)])
    obs = ot.classify_game(g, JG)
    assert obs is not None and obs["first_gank_lane"] == "bot"


def test_non_dict_frame_kill_and_participant_rows_are_skipped():
    g = _game("m1", kills=[None, "x", _kill(200000, 2, [], BOT_KILL)],
              extra_frames=[None, 7, "frame"])
    g["participants"] = [None, "p"] + g["participants"]
    obs = ot.classify_game(g, JG)
    assert obs is not None
    assert obs["start_side"] == "top"
    assert obs["first_gank_lane"] == "bot"


def test_string_assists_does_not_drop_the_game():
    """Before: `pid in "23"` raised TypeError and the game was lost."""
    g = _game("m1", kills=[_kill(200000, 9, "23", BOT_KILL)])
    obs = ot.classify_game(g, JG)
    assert obs is not None
    assert obs["first_gank_lane"] == "none"


def test_missing_participant_id_is_no_observation():
    """Before: pid None matched a frame with participant_id None and any
    kill with a NULL killer counted as this player's gank."""
    parts = [{"participant_id": None, "team_id": 100, "puuid": JG,
              "team_position": "JUNGLE", "summoner1_id": 4,
              "summoner2_id": 11}]
    g = _game("m1", participants=parts,
              kills=[_kill(200000, None, [], BOT_KILL)])
    g["frames"].append({"timestamp_ms": 60011, "participant_id": None,
                        "pos_x": BLUE_TOP_JG[0], "pos_y": BLUE_TOP_JG[1]})
    assert ot.classify_game(g, JG) is None


# --- RM-1842: min_games is a positive int, or the default ------------------

@pytest.mark.parametrize("mg", [0, -5])
def test_non_positive_min_games_never_fabricates_a_mode_from_zero(mg):
    """Before: min_games=0 on an empty sample reported mode 'top' with
    n=0 and an invade_rate of 0.5 out of zero games."""
    out = ot.aggregate([], mg)
    assert out["level1_lane"] == "-"
    assert out["jungle_start_side"] == "-"
    assert out["invade_rate"] == "-"
    assert out["first_gank_lane"] == "-"


@pytest.mark.parametrize("mg", ["3", None, 2.5, True, [3]])
def test_wrong_type_min_games_falls_back_to_default(mg):
    games = [_game(f"m{i}") for i in range(2)]
    out = ot.tendencies_from_games(games, [JG], mg)[JG]
    assert out["jungle_start_side"] == "-"  # 2 < MIN_GAMES
    games.append(_game("m9"))
    out = ot.tendencies_from_games(games, [JG], mg)[JG]
    assert out["jungle_start_side"]["mode"] == "top"


def test_opening_tendencies_unhashable_min_games_does_not_raise(tmp_path):
    ot._reset_cache_for_tests()
    out = ot.opening_tendencies([JG], db_path=tmp_path / "absent.db",
                                min_games=[3])
    assert out[JG]["games"] == 0
    ot._reset_cache_for_tests()


def test_aggregate_tolerates_malformed_observations():
    good = ot.classify_game(_game("m1"), JG)
    bad = [None, "x", {"jungler": True}, {"level1_lane": ["unhashable"]}]
    out = ot.aggregate(bad + [good, good, good])
    assert out["games"] == 5
    assert out["level1_lane"]["n"] == 5
    assert out["level1_lane"]["mode"] == "jungle"
    assert ot.aggregate(None)["games"] == 0


# --- sqlite layer --------------------------------------------------------------

def _mk_db(games):
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER,
            map_id INTEGER, has_timeline INTEGER, game_creation_ts INTEGER);
        CREATE TABLE participants (id INTEGER PRIMARY KEY, match_id TEXT,
            participant_id INTEGER, team_id INTEGER, puuid TEXT,
            team_position TEXT, summoner1_id INTEGER, summoner2_id INTEGER);
        CREATE TABLE timeline_frames (id INTEGER PRIMARY KEY, match_id TEXT,
            timestamp_ms INTEGER, participant_id INTEGER, pos_x INTEGER,
            pos_y INTEGER);
        CREATE TABLE timeline_events (id INTEGER PRIMARY KEY, match_id TEXT,
            timestamp_ms INTEGER, event_type TEXT, killer_id INTEGER,
            victim_id INTEGER, assisting_ids_json TEXT, kill_pos_x INTEGER,
            kill_pos_y INTEGER);
    """)
    for i, g in enumerate(games):
        c.execute("INSERT INTO matches VALUES (?,?,?,?,?)",
                  (g["match_id"], g["queue_id"], g["map_id"],
                   1 if g["has_timeline"] else 0, 1000 + i))
        for p in g["participants"]:
            c.execute("INSERT INTO participants (match_id, participant_id,"
                      " team_id, puuid, team_position, summoner1_id,"
                      " summoner2_id) VALUES (?,?,?,?,?,?,?)",
                      (g["match_id"], p["participant_id"], p["team_id"],
                       p["puuid"], p["team_position"], p["summoner1_id"],
                       p["summoner2_id"]))
        for f in g["frames"]:
            c.execute("INSERT INTO timeline_frames (match_id, timestamp_ms,"
                      " participant_id, pos_x, pos_y) VALUES (?,?,?,?,?)",
                      (g["match_id"], f["timestamp_ms"], f["participant_id"],
                       f["pos_x"], f["pos_y"]))
        for k in g["kills"]:
            raw = k["assists"]
            c.execute("INSERT INTO timeline_events (match_id, timestamp_ms,"
                      " event_type, killer_id, assisting_ids_json,"
                      " kill_pos_x, kill_pos_y) VALUES (?,?,?,?,?,?,?)",
                      (g["match_id"], k["timestamp_ms"], "CHAMPION_KILL",
                       k["killer_id"],
                       raw if isinstance(raw, str) else json.dumps(raw),
                       k["pos_x"], k["pos_y"]))
    c.commit()
    return c


def _write_db_file(path, games):
    mem = _mk_db(games)
    disk = sqlite3.connect(str(path))
    mem.backup(disk)
    disk.close()
    mem.close()


class _DeletingConn:
    """A connection whose match row vanishes between the roster query and
    the per-match read - a concurrent downloader pruning the DB."""

    def __init__(self, real, victim):
        self._real = real
        self._victim = victim

    def execute(self, sql, params=()):
        if sql.startswith("SELECT queue_id, map_id, has_timeline"):
            if params and params[0] == self._victim:
                self._real.execute("DELETE FROM matches WHERE match_id = ?",
                                   (self._victim,))
        return self._real.execute(sql, params)


def test_load_games_skips_a_match_that_vanished_mid_read():
    """RM-1843. Before: fetchone() None -> TypeError escaped
    opening_tendencies and the route dropped opening for the roster."""
    conn = _mk_db([_game(f"m{i}") for i in range(4)])
    loaded = ot.load_games(_DeletingConn(conn, "m2"), [JG])
    assert {g["match_id"] for g in loaded} == {"m0", "m1", "m3"}


def test_load_games_deeply_nested_assists_json_does_not_raise():
    """RM-1844. Before: RecursionError (not ValueError) escaped."""
    deep = "[" * 200000 + "]" * 200000
    conn = _mk_db([_game(f"m{i}", kills=[_kill(200000, 2, deep, BOT_KILL)])
                   for i in range(3)])
    loaded = ot.load_games(conn, [JG])
    assert len(loaded) == 3
    assert all(k["assists"] == [] for g in loaded for k in g["kills"])
    out = ot.tendencies_from_games(loaded, [JG])[JG]
    assert out["first_gank_lane"]["mode"] == "bot"


def test_load_games_junk_rows_in_db_do_not_cost_the_sample():
    games = [_game(f"m{i}", extra_frames=[
        {"timestamp_ms": 60000, "participant_id": 2,
         "pos_x": "abc", "pos_y": 1e999}],
        kills=[_kill(200000, 2, "not json", BOT_KILL)]) for i in range(3)]
    loaded = ot.load_games(_mk_db(games), [JG])
    out = ot.tendencies_from_games(loaded, [JG])[JG]
    assert out["games"] == 3
    assert out["jungle_start_side"]["mode"] == "top"
    assert out["level1_lane"]["mode"] == "jungle"


# --- RM-1845: the cache never hands out its own dicts -----------------------

def test_mutating_a_result_does_not_poison_the_cache(tmp_path):
    ot._reset_cache_for_tests()
    db = tmp_path / "rh.db"
    _write_db_file(db, [_game(f"m{i}") for i in range(3)])
    first = ot.opening_tendencies([JG], db_path=db)
    first[JG]["games"] = -1
    first[JG]["jungle_start_side"]["mode"] = "poisoned"
    again = ot.opening_tendencies([JG], db_path=db)
    assert again[JG]["games"] == 3
    assert again[JG]["jungle_start_side"]["mode"] == "top"
    again[JG]["level1_lane"]["rates"].clear()
    third = ot.opening_tendencies([JG], db_path=db)
    assert third[JG]["level1_lane"]["rates"]
    ot._reset_cache_for_tests()


def test_duplicate_puuids_load_once(tmp_path, monkeypatch):
    ot._reset_cache_for_tests()
    db = tmp_path / "rh.db"
    _write_db_file(db, [_game(f"m{i}") for i in range(3)])
    real = ot.load_games
    calls = []

    def _spy(conn, puuids, *a, **k):
        calls.append(list(puuids))
        return real(conn, puuids, *a, **k)

    monkeypatch.setattr(ot, "load_games", _spy)
    out = ot.opening_tendencies([JG, JG, JG], db_path=db)
    assert calls == [[JG]]
    assert list(out) == [JG]
    ot._reset_cache_for_tests()


# --- RM-1846: an absent DB is not cached as a real empty sample -------------

def test_absent_db_is_not_cached_so_a_new_db_is_read_at_once(tmp_path):
    ot._reset_cache_for_tests()
    db = tmp_path / "rh.db"
    first = ot.opening_tendencies([JG], db_path=db)
    assert first[JG]["games"] == 0
    _write_db_file(db, [_game(f"m{i}") for i in range(3)])
    again = ot.opening_tendencies([JG], db_path=db)
    assert again[JG]["games"] == 3
    ot._reset_cache_for_tests()


def test_well_formed_results_unchanged_through_the_db(tmp_path):
    """Characterization: the hardening changes nothing for clean rows."""
    ot._reset_cache_for_tests()
    db = tmp_path / "rh.db"
    _write_db_file(db, [_game(f"m{i}", kills=[_kill(200000, 2, [3],
                                                      BOT_KILL)])
                        for i in range(4)])
    out = ot.opening_tendencies([JG, LANER], db_path=db)
    assert out[JG] == {
        "games": 4, "jungle_games": 4,
        "level1_lane": {"n": 4, "mode": "jungle", "rates": {"jungle": 0.833}},
        "jungle_start_side": {"n": 4, "mode": "top", "top_rate": 0.833,
                              "bot_rate": 0.167},
        "invade_rate": 0.167,
        "first_gank_lane": {"n": 4, "mode": "bot", "rates": {"bot": 0.833}},
    }
    assert out[LANER]["level1_lane"]["mode"] == "mid"
    assert out[LANER]["jungle_start_side"] == "-"
    ot._reset_cache_for_tests()
