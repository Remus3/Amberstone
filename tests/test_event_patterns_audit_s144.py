"""Lane 8 true-audit (s144 cycle 97) of core/event_patterns.py.

One test group per confirmed finding (F1-F11). Every fixture is synthetic:
participant ids only, no Riot ids, no names, no real match ids.

The corpus miner (tools/mine_event_patterns.py) catches only OSError and
JSONDecodeError per file, so any other exception out of ``analyse`` aborts the
WHOLE mine. That is why the shape findings (F3, F4) assert "no raise" and not
merely "a sensible value".
"""
from __future__ import annotations

import math

import pytest

from core import event_patterns as ep

_POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def _match(win_team=200, champ="Annie"):
    return {"info": {"participants": [
        {"participantId": i, "teamId": 100 if i <= 5 else 200,
         "teamPosition": _POS[(i - 1) % 5], "championName": champ,
         "win": (i > 5) == (win_team == 200)}
        for i in range(1, 11)]}}


def _tl(events, frames=None):
    return {"info": {"frames": [
        {"timestamp": 0, "participantFrames": frames or {},
         "events": events}]}}


def _sk(t, pid, slot, kind=None):
    e = {"type": "SKILL_LEVEL_UP", "timestamp": t, "participantId": pid,
         "skillSlot": slot}
    if kind is not None:
        e["levelUpType"] = kind
    return e


def _lv(t, pid, level):
    return {"type": "LEVEL_UP", "timestamp": t, "participantId": pid,
            "level": level}


def _kill(t, killer, victim, assists=(), bounty=300, shutdown=0):
    return {"type": "CHAMPION_KILL", "timestamp": t, "killerId": killer,
            "victimId": victim, "assistingParticipantIds": list(assists),
            "bounty": bounty, "shutdownBounty": shutdown,
            "position": {"x": 1, "y": 2}}


def _buy(t, pid, item):
    return {"type": "ITEM_PURCHASED", "timestamp": t, "participantId": pid,
            "itemId": item}


def _plate(t, killer, lost_team):
    e = {"type": "TURRET_PLATE_DESTROYED", "timestamp": t,
         "killerId": killer}
    if lost_team is not _MISSING:
        e["teamId"] = lost_team
    return e


_MISSING = object()


def _pf(pid, gold):
    return {"participantId": pid, "totalGold": gold}


# ------------------------------------------------- F1: EVOLVE in skill_order

def test_f1_skill_order_skips_evolve_skill_ups():
    ev = [_sk(1000, 1, 1, "NORMAL"), _sk(2000, 1, 2, "NORMAL"),
          _sk(3000, 1, 3, "NORMAL"), _sk(3500, 1, 4, "EVOLVE"),
          _sk(4000, 1, 1, "NORMAL"), _sk(5000, 1, 4, "NORMAL"),
          _sk(6000, 1, 1, "NORMAL")]
    f = ep.skill_order(_match(), _tl(ev), 1)
    assert f[0].detail["order"] == [1, 2, 3, 1, 4, 1]
    assert f[0].detail["signature"] == "123141"


def test_f1_skill_order_without_level_up_type_key_is_unchanged():
    ev = [_sk(1000 * i, 1, s) for i, s in enumerate([1, 2, 3, 1, 1, 4], 1)]
    f = ep.skill_order(_match(), _tl(ev), 1)
    assert f[0].detail["order"] == [1, 2, 3, 1, 1, 4]


def test_f1_only_evolve_skill_ups_is_no_finding():
    ev = [_sk(1000, 1, 1, "EVOLVE"), _sk(2000, 1, 2, "EVOLVE")]
    assert ep.skill_order(_match(), _tl(ev), 1) == []


# ----------------------------------------- F2: invalid skillSlot in skill_order

@pytest.mark.parametrize("slot", [None, 0, 5, -1, True, 2.5, "2", "x"])
def test_f2_invalid_skill_slot_is_skipped_not_slot_zero(slot):
    ev = [_sk(1000, 1, 1), _sk(2000, 1, slot), _sk(3000, 1, 2)]
    f = ep.skill_order(_match(), _tl(ev), 1)
    assert f[0].detail["order"] == [1, 2]


def test_f2_integral_float_slot_is_accepted():
    ev = [_sk(1000, 1, 3.0)]
    assert ep.skill_order(_match(), _tl(ev), 1)[0].detail["order"] == [3]


# ------------------------------------------- F3: wrong container shapes

_BAD_TIMELINES = [
    None, [], "x", {"info": None}, {"info": []}, {"info": {"frames": None}},
    {"info": {"frames": "abc"}}, {"info": {"frames": [None, 3, "f"]}},
    {"info": {"frames": [{"events": None}]}},
    {"info": {"frames": [{"events": [None, 1, "e", []]}]}},
    {"info": {"frames": [{"events": "abc"}]}},
    {"info": {"frames": [{"participantFrames": [1, 2]}]}},
    {"info": {"frames": [{"participantFrames": {"1": None, "2": 5}}]}},
]


@pytest.mark.parametrize("tl", _BAD_TIMELINES)
def test_f3_wrong_shape_timeline_does_not_raise(tl):
    out = ep.analyse(_match(), tl, 1)
    # plate_share is the one criterion that emits on an empty timeline (0 of
    # 0 plates; filed, not changed here), so it is the only finding left.
    assert [f.criterion for f in out] == ["plate_share"]
    assert out[0].detail == {"plates": 0, "team_plates": 0}


_BAD_MATCHES = [None, [], "x", {"info": None}, {"info": {"participants":
                None}}, {"info": {"participants": "abc"}},
                {"info": {"participants": [None, 1, "p"]}}]


@pytest.mark.parametrize("m", _BAD_MATCHES)
def test_f3_wrong_shape_match_does_not_raise(m):
    tl = _tl([_kill(60000, 7, 1), _sk(1000, 1, 1), _buy(2000, 1, 1055)])
    out = ep.analyse(m, tl, 1)
    assert {f.criterion for f in out} >= {"death_cost", "skill_order",
                                          "item_order"}
    assert all(f.role == "" for f in out)
    assert ep.won(m, 1) is False
    assert ep.role_of(m, 1) == ""


def test_f3_non_list_assists_does_not_raise():
    e = _kill(60000, 7, 1)
    e["assistingParticipantIds"] = 5
    out = ep.deaths_by_cost(_match(), _tl([e]), 1)
    assert out[0].detail["assists"] == 0
    assert ep.kill_participation(_match(), _tl([e]), 7)[0].value == 1.0


@pytest.mark.parametrize("assists", [5, 2.0, None])
def test_f3_non_list_assists_on_a_teammate_kill_does_not_raise(assists):
    # The killer is a teammate, so the assist list IS read for seat 7.
    e = _kill(60000, 8, 1)
    e["assistingParticipantIds"] = assists
    kp = ep.kill_participation(_match(), _tl([e]), 7)[0]
    assert kp.detail == {"participated": 0, "team_kills": 1}
    o = {"type": "ELITE_MONSTER_KILL", "timestamp": 1, "killerId": 8,
         "killerTeamId": 200, "assistingParticipantIds": assists}
    op = ep.objective_participation(_match(), _tl([o]), 7)[0]
    assert op.detail == {"participated": 0, "team_took": 1}


# ------------------------------------------- F4: strict numeric coercion

@pytest.mark.parametrize("bad", ["x", float("nan"), float("inf"), [], {}])
def test_f4_malformed_bounty_does_not_raise(bad):
    ev = [_kill(60000, 7, 1, bounty=bad, shutdown=bad)]
    out = ep.deaths_by_cost(_match(), _tl(ev), 1)
    assert out[0].magnitude_gold == 0
    assert out[0].detail["shutdown"] == 0


def test_f4_fractional_bounty_is_not_truncated_into_a_value():
    ev = [_kill(60000, 7, 1, bounty=299.7, shutdown=True)]
    out = ep.deaths_by_cost(_match(), _tl(ev), 1)
    assert out[0].magnitude_gold == 0


def test_f4_negative_bounty_is_not_a_refund():
    ev = [_kill(60000, 7, 1, bounty=-300, shutdown=450)]
    assert ep.deaths_by_cost(_match(), _tl(ev), 1)[0].magnitude_gold == 450


def test_f4_integral_float_bounty_is_accepted():
    ev = [_kill(60000, 7, 1, bounty=300.0, shutdown=0)]
    assert ep.deaths_by_cost(_match(), _tl(ev), 1)[0].magnitude_gold == 300


@pytest.mark.parametrize("bad", ["x", float("nan"), float("inf"), 1.5])
def test_f4_malformed_gold_does_not_raise_or_fabricate(bad):
    frames = {str(i): _pf(i, 1000) for i in range(1, 11)}
    frames["3"] = _pf(3, bad)
    out = ep.gold_deficit_profile(_match(), _tl([], frames), 1)
    assert out == []


@pytest.mark.parametrize("bad", ["x", float("nan"), 1.5, [], True])
def test_f4_malformed_level_does_not_raise(bad):
    ev = [_sk(1000, 1, 1), _lv(90000, 1, bad), _sk(92000, 1, 2)]
    out = ep.skill_point_latency(_match(), _tl(ev), 1)
    assert out[0].detail["pairs"][0]["held_ms"] == 2000


# --------------------------------------- F5: missing / invalid timestamps

@pytest.mark.parametrize("ts", [_MISSING, None, -5, "x", float("nan"), 1.5])
def test_f5_death_without_a_valid_time_is_not_an_early_death(ts):
    e = _kill(0, 7, 1)
    if ts is _MISSING:
        del e["timestamp"]
    else:
        e["timestamp"] = ts
    assert ep.early_deaths(_match(), _tl([e]), 1) == []
    assert ep.deaths_by_cost(_match(), _tl([e]), 1) == []


@pytest.mark.parametrize("ts", [_MISSING, None, -5, "x", float("inf")])
def test_f5_purchase_without_a_valid_time_is_skipped(ts):
    e = _buy(0, 1, 1055)
    if ts is _MISSING:
        del e["timestamp"]
    else:
        e["timestamp"] = ts
    ev = [e, _buy(30000, 1, 3006)]
    out = ep.item_order(_match(), _tl(ev), 1)
    assert out[0].detail["purchases"] == [(30000, 3006)]


@pytest.mark.parametrize("ts", [_MISSING, None, "x", float("nan")])
def test_f5_spend_without_a_valid_time_consumes_but_is_not_measured(ts):
    bad = _sk(0, 1, 2)
    if ts is _MISSING:
        del bad["timestamp"]
    else:
        bad["timestamp"] = ts
    ev = [_sk(1000, 1, 1), _lv(90000, 1, 2), bad,
          _lv(150000, 1, 3), _sk(160000, 1, 3)]
    out = ep.skill_point_latency(_match(), _tl(ev), 1)
    pairs = out[0].detail["pairs"]
    # Level 2 was spent at an unknown time: no fabricated 0 ms hold, and it
    # does NOT shift the level-3 point onto the wrong spend.
    assert [(p["level"], p["held_ms"]) for p in pairs] == [(3, 10000)]


@pytest.mark.parametrize("ts", [_MISSING, None, "x"])
def test_f5_level_up_without_a_valid_time_is_unmeasured(ts):
    bad = _lv(0, 1, 2)
    if ts is _MISSING:
        del bad["timestamp"]
    else:
        bad["timestamp"] = ts
    ev = [_sk(1000, 1, 1), bad, _sk(92000, 1, 2),
          _lv(150000, 1, 3), _sk(160000, 1, 3)]
    out = ep.skill_point_latency(_match(), _tl(ev), 1)
    pairs = out[0].detail["pairs"]
    assert [(p["level"], p["held_ms"]) for p in pairs] == [(3, 10000)]


# --------------------------------------- F6: plate with no losing team

@pytest.mark.parametrize("lost", [_MISSING, None, 0, 300, "100", True])
def test_f6_plate_without_a_valid_losing_team_counts_for_nobody(lost):
    ev = [_plate(60000, 1, 200), _plate(61000, 1, lost)]
    blue = ep.plate_share(_match(), _tl(ev), 1)[0]
    red = ep.plate_share(_match(), _tl(ev), 6)[0]
    assert blue.detail == {"plates": 1, "team_plates": 1}
    assert red.detail == {"plates": 0, "team_plates": 0}


# --------------------------------------- F7: gold frames

def test_f7_participant_frame_without_an_id_is_not_team_100_gold():
    frames = {str(i): _pf(i, 1000) for i in range(1, 11)}
    frames["x"] = {"totalGold": 50000}
    out = ep.gold_deficit_profile(_match(), _tl([], frames), 1)
    assert out[0].detail["final_diff"] == 0
    assert out[0].value == 0.0


def test_f7_frame_missing_one_team_is_not_a_full_lead():
    frames = {str(i): _pf(i, 1000) for i in range(1, 6)}
    assert ep.gold_deficit_profile(_match(), _tl([], frames), 6) == []


@pytest.mark.parametrize("bad_pid", [0, 11, -1, True, "3", 2.5])
def test_f7_invalid_frame_participant_id_is_skipped(bad_pid):
    frames = {str(i): _pf(i, 1000) for i in range(1, 11)}
    frames["z"] = _pf(bad_pid, 99999)
    out = ep.gold_deficit_profile(_match(), _tl([], frames), 6)
    assert out[0].detail["final_diff"] == 0


def test_f7_duplicate_participant_in_a_frame_is_not_counted_twice():
    frames = {str(i): _pf(i, 1000) for i in range(1, 11)}
    frames["dup"] = _pf(3, 1000)
    assert ep.gold_deficit_profile(_match(), _tl([], frames), 6) == []


# --------------------------------------- F8: seat validation

@pytest.mark.parametrize("bad", [0, -1, 11, 16, True, False, None, "1", 1.5])
def test_f8_team_of_refuses_an_invalid_seat(bad):
    with pytest.raises(ValueError):
        ep.team_of(bad)


def test_f8_team_of_valid_seats():
    assert [ep.team_of(i) for i in range(1, 11)] == [100] * 5 + [200] * 5


@pytest.mark.parametrize("bad", [0, 11, True, None, "1"])
def test_f8_criteria_with_an_invalid_pid_return_nothing(bad):
    ev = [_kill(60000, 7, 1), _plate(60000, 1, 200), _sk(1000, 1, 1),
          {"type": "ELITE_MONSTER_KILL", "timestamp": 1, "killerId": 1,
           "killerTeamId": 100, "assistingParticipantIds": []}]
    frames = {str(i): _pf(i, 1000 + i) for i in range(1, 11)}
    assert ep.analyse(_match(), _tl(ev, frames), bad) == []


@pytest.mark.parametrize("killer", [11, 16, -3, True, "7"])
def test_f8_kill_by_an_invalid_seat_is_not_a_team_kill(killer):
    ev = [_kill(60000, 7, 1), _kill(61000, killer, 2)]
    out = ep.kill_participation(_match(), _tl(ev), 6)
    assert out[0].detail == {"participated": 0, "team_kills": 1}


# --------------------------------------- F9: win / participant lookup

@pytest.mark.parametrize("raw", ["False", "false", 1, "1", None, [1]])
def test_f9_won_is_true_only_for_a_real_true(raw):
    m = _match()
    m["info"]["participants"][0]["win"] = raw
    assert ep.won(m, 1) is False


def test_f9_bool_participant_id_does_not_match_seat_one():
    m = {"info": {"participants": [
        {"participantId": True, "teamPosition": "TOP", "win": True,
         "championName": "Annie"}]}}
    assert ep.won(m, 1) is False
    assert ep.role_of(m, 1) == ""


def test_f9_bool_victim_or_assist_ids_do_not_match_seat_one():
    ev = [_kill(60000, 7, True), _kill(61000, 2, 8, assists=[True])]
    assert ep.deaths_by_cost(_match(), _tl(ev), 1) == []
    kp = ep.kill_participation(_match(), _tl(ev), 1)[0]
    assert kp.detail == {"participated": 0, "team_kills": 1}


def test_f9_bool_participant_id_on_an_event_is_not_seat_one():
    ev = [{"type": "SKILL_LEVEL_UP", "timestamp": 1, "participantId": True,
           "skillSlot": 1}, _buy(2, True, 1055)]
    assert ep.skill_order(_match(), _tl(ev), 1) == []
    assert ep.item_order(_match(), _tl(ev), 1) == []


def test_f9_objective_assist_list_with_bool_is_not_seat_one():
    ev = [{"type": "ELITE_MONSTER_KILL", "timestamp": 1, "killerId": 2,
           "killerTeamId": 100, "assistingParticipantIds": [True]}]
    out = ep.objective_participation(_match(), _tl(ev), 1)
    assert out[0].detail == {"participated": 0, "team_took": 1}


# --------------------------------------- F10: item ids

@pytest.mark.parametrize("item", [_MISSING, None, 0, -1, "1055", 1055.5,
                                  True, float("nan")])
def test_f10_purchase_without_a_valid_item_id_is_skipped(item):
    e = _buy(1000, 1, 0)
    if item is _MISSING:
        del e["itemId"]
    else:
        e["itemId"] = item
    out = ep.item_order(_match(), _tl([e, _buy(2000, 1, 3006)]), 1)
    assert out[0].detail["purchases"] == [(2000, 3006)]


def test_f10_integral_float_item_id_is_accepted():
    out = ep.item_order(_match(), _tl([_buy(2000, 1, 3006.0)]), 1)
    assert out[0].detail["purchases"] == [(2000, 3006)]
    assert isinstance(out[0].detail["purchases"][0][1], int)


@pytest.mark.parametrize("before", ["3006", 3006.5, True])
def test_f10_undo_with_a_malformed_before_id_removes_nothing(before):
    ev = [_buy(1000, 1, 1), _buy(2000, 1, 3006),
          {"type": "ITEM_UNDO", "timestamp": 2500, "participantId": 1,
           "beforeId": before, "afterId": 0}]
    out = ep.item_order(_match(), _tl(ev), 1)
    assert out[0].detail["purchases"] == [(1000, 1), (2000, 3006)]


# --------------------------------------- F11: non-finite never leaks

def test_f11_every_value_is_finite_on_adversarial_input():
    nan, inf = float("nan"), float("inf")
    ev = [_kill(nan, 7, 1, bounty=inf), _kill(60000, 7, 1, bounty=nan),
          _sk(inf, 1, 1), _lv(nan, 1, 2), _buy(nan, 1, inf),
          _plate(nan, 1, 200)]
    frames = {str(i): _pf(i, nan if i == 2 else 1000) for i in range(1, 11)}
    for f in ep.analyse(_match(), _tl(ev, frames), 1):
        assert math.isfinite(f.value)
        assert isinstance(f.t_ms, int) and not isinstance(f.t_ms, bool)
        assert isinstance(f.magnitude_gold, int)
