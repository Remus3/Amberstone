"""T2 event derivations. Headless, synthetic fixtures with known answers."""
from __future__ import annotations

from core import event_patterns as ep


def _match():
    return {"info": {"participants": [
        {"participantId": i, "teamId": 100 if i <= 5 else 200,
         "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(i - 1) % 5],
         "win": i > 5}
        for i in range(1, 11)]}}


def _tl(events, frames=None):
    fr = [{"timestamp": 0, "participantFrames": frames or {}, "events": events}]
    return {"info": {"frameInterval": 60000, "frames": fr}}


def _kill(t, killer, victim, assists=(), bounty=300, shutdown=0, x=100, y=200):
    return {"type": "CHAMPION_KILL", "timestamp": t, "killerId": killer,
            "victimId": victim, "assistingParticipantIds": list(assists),
            "bounty": bounty, "shutdownBounty": shutdown,
            "position": {"x": x, "y": y}}


# ------------------------------------------------------------------ basics

def test_seat_to_team_matches_the_verified_convention():
    assert ep.team_of(1) == 100 and ep.team_of(5) == 100
    assert ep.team_of(6) == 200 and ep.team_of(10) == 200


def test_role_and_win_are_read_from_the_match_blob():
    m = _match()
    assert ep.role_of(m, 2) == "JUNGLE"
    assert ep.role_of(m, 7) == "JUNGLE"
    assert ep.won(m, 7) is True
    assert ep.won(m, 2) is False


# ------------------------------------------------------------------ deaths

def test_death_cost_is_bounty_plus_shutdown():
    tl = _tl([_kill(60000, 7, 2, bounty=300, shutdown=450)])
    f = ep.deaths_by_cost(_match(), tl, 2)
    assert len(f) == 1
    assert f[0].magnitude_gold == 750
    assert f[0].criterion == "death_cost"
    assert f[0].tier == "T2"


def test_a_kill_the_player_made_is_not_counted_as_their_death():
    tl = _tl([_kill(60000, 2, 7)])
    assert ep.deaths_by_cost(_match(), tl, 2) == []
    assert len(ep.deaths_by_cost(_match(), tl, 7)) == 1


def test_shutdowns_given_selects_only_deaths_that_paid_one():
    tl = _tl([_kill(1000, 7, 2, shutdown=0), _kill(2000, 7, 2, shutdown=300)])
    f = ep.shutdowns_given(_match(), tl, 2)
    assert len(f) == 1 and f[0].t_ms == 2000


def test_each_death_subset_carries_its_OWN_criterion_label():
    # Every subset derives from deaths_by_cost. If they keep that label, a
    # consumer grouping by criterion counts one death once per subset it falls
    # into - death_cost inflates and every subset reads zero. Measured on a
    # real match: one death appeared three times.
    tl = _tl([_kill(1000, 7, 2, shutdown=300, assists=[])])
    assert {f.criterion for f in ep.shutdowns_given(_match(), tl, 2)} == {"shutdowns_given"}
    assert {f.criterion for f in ep.early_deaths(_match(), tl, 2)} == {"early_deaths"}
    assert {f.criterion for f in ep.solo_deaths(_match(), tl, 2)} == {"solo_deaths"}
    assert {f.criterion for f in ep.deaths_by_cost(_match(), tl, 2)} == {"death_cost"}


def test_analyse_labels_one_death_under_each_matching_subset_exactly_once():
    tl = _tl([_kill(1000, 7, 2, shutdown=300, assists=[])])
    got = [f.criterion for f in ep.analyse(_match(), tl, 2)]
    for name in ("death_cost", "shutdowns_given", "early_deaths", "solo_deaths"):
        assert got.count(name) == 1, name


def test_early_deaths_use_the_eight_minute_boundary():
    tl = _tl([_kill(ep.EARLY_GAME_MS - 1, 7, 2),
              _kill(ep.EARLY_GAME_MS + 1, 7, 2)])
    f = ep.early_deaths(_match(), tl, 2)
    assert len(f) == 1 and f[0].t_ms == ep.EARLY_GAME_MS - 1


def test_solo_deaths_require_no_assists():
    tl = _tl([_kill(1000, 7, 2, assists=[8]), _kill(2000, 7, 2, assists=[])])
    f = ep.solo_deaths(_match(), tl, 2)
    assert len(f) == 1 and f[0].t_ms == 2000


# ------------------------------------------------------------- objectives

def _monster(t, killer, team, mtype="DRAGON", assists=()):
    return {"type": "ELITE_MONSTER_KILL", "timestamp": t, "killerId": killer,
            "killerTeamId": team, "monsterType": mtype,
            "assistingParticipantIds": list(assists),
            "position": {"x": 9866, "y": 4414}}


def test_objective_participation_is_team_relative():
    tl = _tl([_monster(1000, 7, 200), _monster(2000, 8, 200, assists=[7]),
              _monster(3000, 9, 200), _monster(4000, 2, 100)])
    f = ep.objective_participation(_match(), tl, 7)
    assert len(f) == 1
    # 2 of the 3 the team took; the enemy one must not count.
    assert f[0].detail == {"participated": 2, "team_took": 3}
    assert round(f[0].value, 3) == 0.667


def test_no_team_objectives_yields_no_finding_rather_than_a_zero():
    # A zero here would be indistinguishable from "took none of many".
    tl = _tl([_monster(1000, 2, 100)])
    assert ep.objective_participation(_match(), tl, 7) == []


def test_kill_participation_counts_only_own_team_kills():
    tl = _tl([_kill(1000, 7, 2), _kill(2000, 8, 3, assists=[7]),
              _kill(3000, 2, 7)])
    f = ep.kill_participation(_match(), tl, 7)
    assert f[0].detail == {"participated": 2, "team_kills": 2}


# ------------------------------------------------------------------ plates

def test_plate_share_counts_plates_taken_from_the_enemy():
    ev = [{"type": "TURRET_PLATE_DESTROYED", "timestamp": 100,
           "killerId": 7, "teamId": 100, "laneType": "MID_LANE"},
          {"type": "TURRET_PLATE_DESTROYED", "timestamp": 200,
           "killerId": 8, "teamId": 100, "laneType": "MID_LANE"},
          {"type": "TURRET_PLATE_DESTROYED", "timestamp": 300,
           "killerId": 2, "teamId": 200, "laneType": "TOP_LANE"}]
    f = ep.plate_share(_match(), _tl(ev), 7)
    # teamId is the team that LOST the plate, so the third belongs to the enemy.
    assert f[0].detail == {"plates": 1, "team_plates": 2}
    assert f[0].value == 0.5


# ------------------------------------------------------------- build order

def test_skill_order_is_the_first_six_points_in_order():
    ev = [{"type": "SKILL_LEVEL_UP", "timestamp": i * 100,
           "participantId": 7, "skillSlot": s}
          for i, s in enumerate([1, 3, 1, 2, 1, 4, 1])]
    f = ep.skill_order(_match(), _tl(ev), 7)
    assert f[0].detail["order"] == [1, 3, 1, 2, 1, 4]
    assert f[0].detail["signature"] == "131214"


def test_item_order_removes_an_undone_purchase():
    ev = [{"type": "ITEM_PURCHASED", "timestamp": 100, "participantId": 7,
           "itemId": 1055},
          {"type": "ITEM_PURCHASED", "timestamp": 200, "participantId": 7,
           "itemId": 2003},
          {"type": "ITEM_UNDO", "timestamp": 250, "participantId": 7,
           "beforeId": 2003, "afterId": 0}]
    f = ep.item_order(_match(), _tl(ev), 7)
    assert [i for _, i in f[0].detail["purchases"]] == [1055]


def test_item_order_ignores_another_players_purchases():
    ev = [{"type": "ITEM_PURCHASED", "timestamp": 100, "participantId": 2,
           "itemId": 1055}]
    assert ep.item_order(_match(), _tl(ev), 7) == []


# --------------------------------------------------------------- economy

def _frames_for(gold_by_pid):
    return {str(p): {"participantId": p, "totalGold": g}
            for p, g in gold_by_pid.items()}


def test_gold_deficit_profile_detects_a_recovery():
    def frame(ts, blue, red):
        return {"timestamp": ts, "events": [],
                "participantFrames": _frames_for(
                    {**{i: blue for i in range(1, 6)},
                     **{i: red for i in range(6, 11)}})}
    tl = {"info": {"frameInterval": 60000, "frames": [
        frame(0, 500, 500), frame(60000, 900, 500), frame(120000, 800, 1200)]}}
    f = ep.gold_deficit_profile(_match(), tl, 7)   # pid 7 is on team 200
    d = f[0].detail
    assert d["frames"] == 3
    assert d["frames_behind"] == 1        # only the middle frame
    assert d["recovered"] is True
    assert f[0].tier == "T1"              # frames, not events - must say so


def test_gold_deficit_profile_on_an_empty_timeline_is_empty():
    assert ep.gold_deficit_profile(_match(), _tl([]), 7) == []


# --------------------------------------------------------------- registry

def test_analyse_runs_every_registered_criterion():
    tl = _tl([_kill(60000, 7, 2, shutdown=100), _monster(70000, 7, 200)])
    names = {f.criterion for f in ep.analyse(_match(), tl, 7)}
    assert "objective_participation" in names
    assert "kill_participation" in names


def test_every_registry_entry_is_callable_with_the_same_signature():
    tl = _tl([])
    for name, fn in ep.CRITERIA.items():
        assert isinstance(fn(_match(), tl, 7), list), name
