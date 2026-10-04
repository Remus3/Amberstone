"""RM-613 (directive X-13, external reference I) - opening-tendency metrics.

All timelines here are SYNTHETIC (hand-built dicts or an in-memory sqlite
DB with the rewind_history.db column subset). No real Riot IDs, no
captured payloads. Positions are Match-V5 map units; the expected
district for each is asserted against core.minimap_districts so a grid
change shows up here as a fixture failure, not a silent drift.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core import opening_tendency as ot
from core.minimap_districts import district_of
from core.smoothed_rates import laplace_rate

# --- synthetic positions (Match-V5 units, y-up, blue base bottom-left) ------

BLUE_TOP_JG = (3800, 7900)     # blue topside jungle, own half
BLUE_BOT_JG = (7800, 4000)     # blue botside jungle, own half
RED_HALF_TOP = (8241, 10299)   # red half, upper river - a blue invade
RED_TOP_JG = (7100, 10900)     # red topside jungle, own half for red
TOP_LANE = (1500, 10000)
MID_LANE = (6500, 6500)      # blue half of the base-to-base corridor
BOT_LANE = (10000, 1000)
CENTRE_RIVER = (5920, 8880)   # off-corridor centre: the real river
BOT_KILL = (11000, 1500)
TOP_KILL = (1200, 11000)

JG = "puuid-synthetic-jungler"
LANER = "puuid-synthetic-laner"


def _frac(p):
    return ot.to_frac(p[0], p[1])


def test_fixture_positions_land_in_expected_districts():
    assert district_of(*_frac(BLUE_TOP_JG), "sr") == "jungle_top_blue"
    assert district_of(*_frac(BLUE_BOT_JG), "sr") == "jungle_bot_red"
    assert district_of(*_frac(RED_HALF_TOP), "sr") == "top_river"
    assert district_of(*_frac(TOP_LANE), "sr") == "top_lane"
    assert district_of(*_frac(MID_LANE), "sr") == "bot_river"
    assert district_of(*_frac(CENTRE_RIVER), "sr") == "mid_lane"
    assert district_of(*_frac(BOT_LANE), "sr") == "bot_lane"
    assert district_of(*_frac(BOT_KILL), "sr") == "bot_lane"


def _game(mid, *, jg_1=BLUE_TOP_JG, jg_2=BLUE_TOP_JG, jg_team=100,
          laner_1=MID_LANE, kills=(), queue_id=420, map_id=11,
          has_timeline=True, frames=True, jg_position="JUNGLE"):
    parts = [
        {"participant_id": 2, "team_id": jg_team, "puuid": JG,
         "team_position": jg_position, "summoner1_id": 4,
         "summoner2_id": 11},
        {"participant_id": 3, "team_id": 100, "puuid": LANER,
         "team_position": "MIDDLE", "summoner1_id": 4, "summoner2_id": 14},
        {"participant_id": 7, "team_id": 200, "puuid": "puuid-synth-enemy",
         "team_position": "BOTTOM", "summoner1_id": 4, "summoner2_id": 7},
    ]
    fr = []
    if frames:
        fr = [
            {"timestamp_ms": 60011, "participant_id": 2,
             "pos_x": jg_1[0], "pos_y": jg_1[1]},
            {"timestamp_ms": 120020, "participant_id": 2,
             "pos_x": jg_2[0], "pos_y": jg_2[1]},
            {"timestamp_ms": 60011, "participant_id": 3,
             "pos_x": laner_1[0], "pos_y": laner_1[1]},
        ]
    return {"match_id": mid, "queue_id": queue_id, "map_id": map_id,
            "has_timeline": has_timeline, "participants": parts,
            "frames": fr, "kills": list(kills)}


def _kill(ts, killer, assists, pos):
    return {"timestamp_ms": ts, "killer_id": killer, "assists": assists,
            "pos_x": pos[0], "pos_y": pos[1]}


# --- per-game classification ---------------------------------------------------

def test_classify_jungle_start_side_top_and_bot():
    top = ot.classify_game(_game("m1"), JG)
    assert top["jungler"] is True
    assert top["start_side"] == "top"
    bot = ot.classify_game(_game("m2", jg_1=BLUE_BOT_JG, jg_2=BLUE_BOT_JG), JG)
    assert bot["start_side"] == "bot"


def test_legacy_corridor_districts_bucket_as_mid_not_river():
    # Pins the measured grid semantics: the grid's *_river ids are the
    # base-to-base corridor (real mid lane); its mid_lane square is river.
    assert ot._bucket("top_river") == "mid"
    assert ot._bucket("bot_river") == "mid"
    assert ot._bucket("mid_lane") == "river"
    assert ot._SIDE_BY_DISTRICT.get("top_river") is None
    river = ot.classify_game(_game("m1", laner_1=CENTRE_RIVER), LANER)
    assert river["level1_lane"] == "river"


def test_start_side_falls_back_to_two_minute_frame():
    # 1:00 frame in the mid square (no side) -> the 2:00 frame decides.
    obs = ot.classify_game(_game("m1", jg_1=MID_LANE, jg_2=BLUE_BOT_JG), JG)
    assert obs["start_side"] == "bot"


def test_invade_flag_is_team_relative():
    blue_inv = ot.classify_game(_game("m1", jg_1=RED_HALF_TOP), JG)
    assert blue_inv["invade"] is True
    blue_home = ot.classify_game(_game("m2"), JG)
    assert blue_home["invade"] is False
    # The same red-half spot is HOME for a red jungler.
    red_home = ot.classify_game(_game("m3", jg_1=RED_TOP_JG, jg_team=200), JG)
    assert red_home["invade"] is False
    red_inv = ot.classify_game(_game("m4", jg_1=BLUE_TOP_JG, jg_team=200), JG)
    assert red_inv["invade"] is True


def test_first_gank_lane_is_first_jungler_kill_or_assist_before_five():
    kills = [
        _kill(150000, 7, [], TOP_KILL),          # jungler not involved
        _kill(200000, 3, [2], BOT_KILL),         # jungler assist -> bot
        _kill(240000, 2, [], TOP_KILL),          # later, ignored
    ]
    obs = ot.classify_game(_game("m1", kills=kills), JG)
    assert obs["first_gank_lane"] == "bot"
    killer = ot.classify_game(_game("m2", kills=[_kill(100000, 2, [], TOP_KILL)]), JG)
    assert killer["first_gank_lane"] == "top"


def test_first_gank_none_when_only_after_five_minutes():
    obs = ot.classify_game(_game("m1", kills=[_kill(300000, 2, [], BOT_KILL)]), JG)
    assert obs["first_gank_lane"] == "none"


def test_level1_lane_from_one_minute_frame():
    obs = ot.classify_game(_game("m1"), LANER)
    assert obs["jungler"] is False
    assert obs["level1_lane"] == "mid"
    top = ot.classify_game(_game("m2", laner_1=TOP_LANE), LANER)
    assert top["level1_lane"] == "top"
    jg = ot.classify_game(_game("m3"), JG)
    assert jg["level1_lane"] == "jungle"


def test_smite_identifies_jungler_without_team_position():
    obs = ot.classify_game(_game("m1", jg_position=""), JG)
    assert obs["jungler"] is True


# --- exclusions ---------------------------------------------------------------------

def test_event_mode_queue_2400_excluded():
    assert ot.classify_game(_game("m1", queue_id=2400), JG) is None


def test_game_without_timeline_excluded():
    assert ot.classify_game(_game("m1", has_timeline=False), JG) is None
    assert ot.classify_game(_game("m2", frames=False), JG) is None


def test_non_rift_map_excluded():
    assert ot.classify_game(_game("m1", map_id=12), JG) is None


# --- aggregation: shrinkage + thin-sample sentinel ---------------------------------

def test_shrinkage_applied_not_raw_share():
    games = [_game(f"m{i}") for i in range(4)]  # 4/4 top, 0/4 invade
    out = ot.tendencies_from_games(games, [JG])[JG]
    side = out["jungle_start_side"]
    assert side["mode"] == "top"
    assert side["top_rate"] == round(laplace_rate(4, 4), 3)
    assert side["top_rate"] < 1.0
    assert out["invade_rate"] == round(laplace_rate(0, 4), 3)
    assert out["invade_rate"] > 0.0


def test_thin_sample_returns_dash_sentinel():
    games = [_game("m1"), _game("m2")]
    out = ot.tendencies_from_games(games, [JG])[JG]
    assert out["jungle_start_side"] == "-"
    assert out["invade_rate"] == "-"
    assert out["first_gank_lane"] == "-"
    assert out["level1_lane"] == "-"
    assert out["games"] == 2


def test_unknown_puuid_all_dash():
    out = ot.tendencies_from_games([_game("m1")], ["puuid-nobody"])
    assert out["puuid-nobody"]["jungle_start_side"] == "-"
    assert out["puuid-nobody"]["games"] == 0


def test_event_mode_games_do_not_count_toward_sample():
    games = [_game(f"m{i}") for i in range(2)]
    games += [_game(f"e{i}", queue_id=2400) for i in range(5)]
    out = ot.tendencies_from_games(games, [JG])[JG]
    assert out["games"] == 2
    assert out["jungle_start_side"] == "-"


def test_first_gank_distribution_shrunk_and_moded():
    games = [_game(f"m{i}", kills=[_kill(200000, 2, [], BOT_KILL)])
             for i in range(3)]
    games.append(_game("m9"))  # no gank before 5:00
    out = ot.tendencies_from_games(games, [JG])[JG]
    fg = out["first_gank_lane"]
    assert fg["mode"] == "bot"
    assert fg["n"] == 4
    assert fg["rates"]["bot"] == round(laplace_rate(3, 4), 3)
    assert fg["rates"]["none"] == round(laplace_rate(1, 4), 3)


def test_laner_has_level1_but_jungle_metrics_dash():
    games = [_game(f"m{i}", laner_1=TOP_LANE) for i in range(3)]
    out = ot.tendencies_from_games(games, [LANER])[LANER]
    assert out["level1_lane"]["mode"] == "top"
    assert out["jungle_start_side"] == "-"


# --- sqlite loader (in-memory, rewind_history.db column subset) --------------------

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
            c.execute("INSERT INTO timeline_events (match_id, timestamp_ms,"
                      " event_type, killer_id, assisting_ids_json,"
                      " kill_pos_x, kill_pos_y) VALUES (?,?,?,?,?,?,?)",
                      (g["match_id"], k["timestamp_ms"], "CHAMPION_KILL",
                       k["killer_id"], json.dumps(k["assists"]),
                       k["pos_x"], k["pos_y"]))
    c.commit()
    return c


def test_sqlite_loader_round_trip_and_event_mode_exclusion():
    games = [_game(f"m{i}", kills=[_kill(200000, 3, [2], BOT_KILL)])
             for i in range(3)]
    games += [_game(f"e{i}", queue_id=2400) for i in range(3)]
    games.append(_game("nt", has_timeline=False))
    conn = _mk_db(games)
    loaded = ot.load_games(conn, [JG])
    ids = {g["match_id"] for g in loaded}
    assert ids == {"m0", "m1", "m2"}
    out = ot.tendencies_from_games(loaded, [JG])[JG]
    assert out["games"] == 3
    assert out["jungle_start_side"]["mode"] == "top"
    assert out["first_gank_lane"]["mode"] == "bot"


def test_opening_tendencies_missing_db_fails_soft(tmp_path):
    out = ot.opening_tendencies([JG], db_path=tmp_path / "absent.db")
    assert out[JG]["jungle_start_side"] == "-"
    assert out[JG]["games"] == 0


def test_trinket_timing_documented_as_not_derivable():
    doc = ot.__doc__ or ""
    assert "WARD_PLACED" in doc and "not derivable" in doc


@pytest.mark.parametrize("bad", [None, "x", float("nan")])
def test_to_frac_garbage_does_not_raise(bad):
    ot.to_frac(bad, bad)


def _write_db_file(path, games):
    mem = _mk_db(games)
    disk = sqlite3.connect(str(path))
    mem.backup(disk)
    disk.close()
    mem.close()


def test_opening_tendencies_reads_file_db_and_caches(tmp_path, monkeypatch):
    ot._reset_cache_for_tests()
    db = tmp_path / "rh.db"
    _write_db_file(db, [_game(f"m{i}") for i in range(3)])
    first = ot.opening_tendencies([JG], db_path=db)
    assert first[JG]["games"] == 3
    assert first[JG]["jungle_start_side"]["mode"] == "top"

    def _boom(*_a, **_k):
        raise AssertionError("cache miss - DB re-read")

    monkeypatch.setattr(ot, "load_games", _boom)
    again = ot.opening_tendencies([JG], db_path=db)
    assert again == first
    ot._reset_cache_for_tests()


def test_each_puuid_scored_over_its_own_games_only(tmp_path, monkeypatch):
    """Per-puuid load: a roster-mate's recent games must not inflate this
    player's sample past PER_PUUID_LIMIT (no union of the roster)."""
    ot._reset_cache_for_tests()
    db = tmp_path / "rh.db"
    _write_db_file(db, [_game(f"m{i}") for i in range(3)])
    real = ot.load_games
    calls = []

    def _spy(conn, puuids, *a, **k):
        calls.append(list(puuids))
        return real(conn, puuids, *a, **k)

    monkeypatch.setattr(ot, "load_games", _spy)
    out = ot.opening_tendencies([JG, LANER], db_path=db)
    assert calls == [[JG], [LANER]]
    assert out[JG]["games"] == 3
    assert out[LANER]["games"] == 3
    ot._reset_cache_for_tests()
