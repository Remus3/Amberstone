"""since_ts time-window filter for compute_gpi (player-snapshot card, spec 5.1).

The recent-set that axes are scored over is filtered to games at or after
since_ts; the percentile baseline stays the full history. game_creation_ts is
Unix milliseconds (schema comment; routes_personal_vs.py:122).
"""
import sqlite3

from core import player_gpi


def _seed(conn, rows):
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, game_duration_s INTEGER,"
        " game_creation_ts INTEGER, has_stats INTEGER, map_id INTEGER,"
        " tracked_champion_id INTEGER, tracked_team_id INTEGER);"
        "CREATE TABLE participants (match_id TEXT, champion_id INTEGER, team_id INTEGER,"
        " total_minions_killed INTEGER, neutral_minions_killed INTEGER, vision_score INTEGER,"
        " gold_earned INTEGER, total_damage_dealt_to_champs INTEGER, deaths INTEGER,"
        " kills INTEGER, assists INTEGER, dragon_kills INTEGER, baron_kills INTEGER,"
        " turret_takedowns INTEGER, inhibitor_takedowns INTEGER, win INTEGER);"
    )
    for r in rows:
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,1,11,?,100)",
            (r["mid"], 1800, r["ts"], r["champ"]),
        )
        dmg = r.get("dmg", 18000)
        vis = r.get("vis", 30)
        conn.execute(
            "INSERT INTO participants VALUES (?,?,100,180,20,?,12000,?,?,?,?,?,?,?,?,?)",
            (r["mid"], r["champ"], vis, dmg, r["deaths"], r["kills"], r["assists"],
             r["drag"], 0, 0, 0, r["win"]),
        )
    conn.commit()


def _rows(n, base_ts):
    # n games, one per hour going back from base_ts, alternating deaths so the
    # window subset differs measurably from the full history.
    out = []
    for i in range(n):
        out.append({"mid": f"M{i}", "ts": base_ts - i * 3600_000, "champ": 64,
                    "deaths": 2 if i % 2 else 8, "kills": 6, "assists": 4,
                    "drag": 1, "win": 1 if i % 2 else 0})
    return out


def test_since_ts_filters_recent_set_but_not_baseline():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    # Window = last 3h -> only the 3 newest games are in the recent set.
    # +1ms so the inclusive since_ts >= boundary does not land exactly on a
    # sample's timestamp (games are spaced exactly 1h apart in _rows).
    since = now - 3 * 3600_000 + 1
    out = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=since)
    assert out["ok"] is True
    assert out["window_n"] == 3            # exactly the 3 games inside 3h
    assert out["n_games"] == 20            # baseline unchanged (full history)
    # A survival axis exists and was scored over the 3-game window, not all 20.
    axes = {a["key"]: a for a in out["axes"]}
    assert axes["survival"]["sample_n"] == 3


def test_since_ts_none_is_unchanged_behavior():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    _seed(conn, _rows(20, now))
    out = player_gpi.compute_gpi(mode="sr", conn=conn)   # no since_ts
    assert out["window_n"] == min(player_gpi.DEFAULT_WINDOW, 20)
    assert out["n_games"] == 20


def test_win_streak_winrate_kp_strongest():
    now = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    # 15-game baseline. The 3 newest are skewed HIGH damage / LOW vision, so over
    # a 3h window aggression reads strongest and vision weakest vs the full
    # baseline. Newest 3 are wins (streak). Single participant with assists=0 ->
    # team_kills == operator kills and K-P == kills/team_kills == 100%.
    rows = []
    for i in range(15):
        newest = i < 3
        rows.append({"mid": f"M{i}", "ts": now - i * 3600_000, "champ": 64,
                     "deaths": 3, "kills": 5, "assists": 0,
                     "dmg": 30000 if newest else 8000,
                     "vis": 5 if newest else 40,
                     "drag": 1, "win": 1 if newest else 0})
    _seed(conn, rows)
    # +1ms excludes the boundary game i=3 (Task 1's inclusive >= fix), so the
    # window is exactly the 3 newest.
    out = player_gpi.compute_gpi(mode="sr", conn=conn, since_ts=now - 3 * 3600_000 + 1)
    assert out["window_n"] == 3
    assert out["win_streak"] == {"kind": "win", "n": 3}
    assert out["win_rate"] == 1.0
    assert out["kp_pct"] == 100.0           # kills=5, assists=0, team_kills=5
    assert out["kda_mean"] is not None
    assert out["strongest_axis"] == "aggression"   # window skews high-damage
    assert out["weakest_axis"] == "vision"         # window skews low-vision
