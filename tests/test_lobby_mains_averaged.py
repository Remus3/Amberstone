"""
tests/test_lobby_mains_averaged.py
R30 LOBBY design review: wire the MAINS "AVG / Match" stat grid.

The Pre-Game Lobby YOUR MAINS table renders a 6-cell AVG/Match grid
(KP% / Vision / CS / AVG5 / Dmg / CS-per-min) from each champ's
`averaged` dict. The frontend (_mcAveragedHtml) reads keys
kp/cs/vision/dmg/cs_per_min/avg5, but the builder only emitted
cs_pm/vision_pm/dmg_pm - a key mismatch, so every cell showed "-".
These tests pin the builder emitting the keys the frontend consumes,
computed from the existing rewind_history.db participants aggregate.

Hermetic: builds a minimal temp sqlite (only the columns the builder
touches) so it never depends on the gitignored real rewind_history.db
(would pass on dev / fail on a clean checkout - reference_clean_checkout_probe).
"""
import sqlite3

import pytest

from dashboard.routes_lobby_aux import _avg5_grade, _query_mains_for_puuid

_PARTICIPANT_COLS = (
    "match_id", "team_id", "puuid", "champion_name", "win",
    "kills", "deaths", "assists", "total_minions_killed",
    "neutral_minions_killed", "vision_score",
    "total_damage_dealt_to_champs", "time_played",
)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    cols = ", ".join(f"{n} INTEGER" if n not in ("puuid", "champion_name")
                     else f"{n} TEXT" for n in _PARTICIPANT_COLS)
    c.execute(f"CREATE TABLE participants ({cols})")
    c.execute("CREATE TABLE matches (match_id TEXT, game_creation_ts INTEGER)")
    return c


def _ins(c, **row):
    full = {n: 0 for n in _PARTICIPANT_COLS}
    full.update(row)
    cols = ", ".join(full)
    c.execute(f"INSERT INTO participants ({cols}) VALUES "
              f"({', '.join('?' for _ in full)})", tuple(full.values()))


def _seed_jinx(c):
    # 2 Jinx games for puuid P; a teammate (T) on the same team sets the
    # per-match team-kill total that KP% divides into.
    # m1: P 10/2/5, team kills 20 -> KP (10+5)/20 = 75%. cs200 vis20 dmg20000 30m
    # m2: P 6/4/4,  team kills 12 -> KP (6+4)/12 = 83.3%. cs150 vis10 dmg15000 25m
    _ins(c, match_id="m1", team_id=100, puuid="P", champion_name="Jinx",
         win=1, kills=10, deaths=2, assists=5, total_minions_killed=200,
         vision_score=20, total_damage_dealt_to_champs=20000, time_played=1800)
    _ins(c, match_id="m1", team_id=100, puuid="T", champion_name="Lux",
         kills=10)
    _ins(c, match_id="m2", team_id=100, puuid="P", champion_name="Jinx",
         win=0, kills=6, deaths=4, assists=4, total_minions_killed=150,
         vision_score=10, total_damage_dealt_to_champs=15000, time_played=1500)
    _ins(c, match_id="m2", team_id=100, puuid="T", champion_name="Lux",
         kills=6)
    c.execute("INSERT INTO matches VALUES ('m1', 1000)")
    c.execute("INSERT INTO matches VALUES ('m2', 2000)")
    c.commit()


def test_averaged_emits_frontend_keys():
    c = _conn()
    _seed_jinx(c)
    rows = _query_mains_for_puuid(c, "P", 8)
    assert len(rows) == 1, rows
    av = rows[0]["averaged"]
    # The 6 keys _mcAveragedHtml reads - present, no longer the dead cs_pm set.
    assert set(av) >= {"kp", "cs", "vision", "dmg", "cs_per_min", "avg5"}, av
    assert "cs_pm" not in av, "dead per-minute key still emitted"


def test_averaged_values_per_game():
    c = _conn()
    _seed_jinx(c)
    av = _query_mains_for_puuid(c, "P", 8)[0]["averaged"]
    assert av["cs"] == 175, av           # (200+150)/2
    assert av["vision"] == 15.0, av      # (20+10)/2
    assert av["dmg"] == 17500, av        # (20000+15000)/2
    assert av["cs_per_min"] == 6.4, av   # 350 / ((1800+1500)/60) = 6.36 -> 6.4


def test_averaged_kill_participation():
    c = _conn()
    _seed_jinx(c)
    av = _query_mains_for_puuid(c, "P", 8)[0]["averaged"]
    # avg of per-match KP: (75.0 + 83.33) / 2 = 79.2 (1dp)
    assert av["kp"] == pytest.approx(79.2, abs=0.2), av["kp"]


def test_avg5_grade_from_kda():
    # k=16 d=6 a=9 over the 2 games -> (16+9)/6 = 4.17 -> S
    c = _conn()
    _seed_jinx(c)
    av = _query_mains_for_puuid(c, "P", 8)[0]["averaged"]
    assert av["avg5"] == "S", av["avg5"]


def test_avg5_grade_helper_bands():
    mk = lambda k, d, a: [(1, k, d, a, 0)]  # noqa: E731 - one win row shape
    assert _avg5_grade(mk(4, 1, 0)) == "S"   # (4+0)/1 = 4.0
    assert _avg5_grade(mk(3, 1, 0)) == "A"   # 3.0
    assert _avg5_grade(mk(5, 2, 0)) == "B"   # 2.5
    assert _avg5_grade(mk(3, 2, 0)) == "C"   # 1.5
    assert _avg5_grade(mk(0, 5, 0)) == "D"   # 0.0
    assert _avg5_grade([]) is None


def test_no_em_dashes():
    from pathlib import Path
    raw = Path(__file__).read_bytes()
    assert not [b for b in raw if b > 0x7F]
