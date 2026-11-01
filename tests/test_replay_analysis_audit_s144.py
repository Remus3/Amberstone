"""Lane 8 true-audit (s144 cycle 98) of core/replay_analysis.py.

One test group per confirmed finding (F1-F11). Every fixture is synthetic:
participant ids only, no Riot ids, no names, no real match ids.

The real-corpus measurements quoted below were taken read-only over the
3005-match timeline corpus on 2026-10-31 (counts, never ids).
"""
from __future__ import annotations

import math

import pytest

from core import replay_analysis as ra


def _frame(ts, pfs=None, events=None):
    out = {"participantFrames": pfs if pfs is not None else {},
           "events": events if events is not None else []}
    if ts is not None:
        out["timestamp"] = ts
    return out


def _pf(pid, x=9500, y=4600, **extra):
    d = {"participantId": pid, "position": {"x": x, "y": y},
         "totalGold": 500, "xp": 300, "level": 2,
         "minionsKilled": 3, "jungleMinionsKilled": 4}
    d.update(extra)
    return d


def _drake(ts=125000, team=200, pos=True, monster="DRAGON", **extra):
    ev = {"type": "ELITE_MONSTER_KILL", "timestamp": ts, "killerId": 7,
          "killerTeamId": team, "monsterType": monster}
    if pos:
        ev["position"] = {"x": 9866, "y": 4414}
    ev.update(extra)
    return ev


def _raw(frames, interval=60000):
    return {"info": {"frameInterval": interval, "frames": frames}}


def _basic(events=None):
    return ra.normalize_timeline(_raw([
        _frame(0),
        _frame(60000, {"7": _pf(7, 4000, 11000)}),
        _frame(120000, {"7": _pf(7)},
               events if events is not None else [_drake()]),
    ]))


# ---------------------------------------------- F1 WARD_PLACED actor is lost
# Measured: 593706 of 593706 WARD_PLACED events carry creatorId and neither
# killerId nor participantId, so every ward normalised to actor_id 0.

def test_f1_ward_placed_actor_is_the_creator():
    tl = ra.normalize_timeline(_raw([_frame(60000, events=[
        {"type": "WARD_PLACED", "timestamp": 61000, "creatorId": 4,
         "wardType": "YELLOW_TRINKET"}])]))
    assert tl.events[0].actor_id == 4
    assert tl.events[0].ward_type == "YELLOW_TRINKET"


def test_f1_kill_actor_is_still_the_killer():
    tl = ra.normalize_timeline(_raw([_frame(60000, events=[
        {"type": "CHAMPION_KILL", "timestamp": 61000, "killerId": 3,
         "victimId": 8}])]))
    assert (tl.events[0].actor_id, tl.events[0].victim_id) == (3, 8)


def test_f1_item_actor_is_still_the_participant():
    tl = ra.normalize_timeline(_raw([_frame(60000, events=[
        {"type": "ITEM_PURCHASED", "timestamp": 61000, "participantId": 9,
         "itemId": 1055}])]))
    assert (tl.events[0].actor_id, tl.events[0].item_id) == (9, 1055)


def test_f1_killer_zero_is_no_champion_not_a_fallthrough():
    # killerId 0 = executed / minion kill. It is not a cue to read a
    # different field as the actor.
    tl = ra.normalize_timeline(_raw([_frame(60000, events=[
        {"type": "BUILDING_KILL", "timestamp": 61000, "killerId": 0,
         "participantId": 5}])]))
    assert tl.events[0].actor_id == 0


# ---------------------------------------------------- F2 team_of non-seat

@pytest.mark.parametrize("bad", [0, 11, -1, True, False, None, "7", 7.5,
                                 math.nan])
def test_f2_team_of_refuses_a_non_seat(bad):
    with pytest.raises(ValueError):
        ra.team_of(bad)


def test_f2_team_of_accepts_an_integral_float_seat():
    assert ra.team_of(6.0) == 200


@pytest.mark.parametrize("bad", [0, 11, True])
def test_f2_drake_verdict_refuses_a_non_seat(bad):
    with pytest.raises(ValueError):
        ra.drake_pathing_verdict(_basic(), participant_id=bad)


# ------------------------------------- F3 unknown killer team is not "enemy"

@pytest.mark.parametrize("team", [300, 0, None, "200", True])
def test_f3_drake_with_unknown_killer_team_gets_no_verdict(team):
    tl = _basic([_drake(team=team)])
    assert ra.drake_pathing_verdict(tl, participant_id=7) == []


def test_f3_known_killer_teams_still_attribute():
    assert ra.drake_pathing_verdict(_basic([_drake(team=200)]),
                                    participant_id=7)[0].secured is True
    v = ra.drake_pathing_verdict(_basic([_drake(team=100)]), participant_id=7)
    assert v[0].secured is False and "enemy took it" in v[0].coaching


# ------------------------------------------ F4 pit fallback is per monster

def test_f4_baron_without_a_position_measures_from_the_baron_pit():
    tl = ra.normalize_timeline(_raw([
        _frame(120000, {"7": _pf(7, 5007, 10471)},
               [_drake(monster="BARON_NASHOR", pos=False)])]))
    ap = ra.objective_approach(tl, 7, tl.events[0], leads_s=(5,))
    assert ap[0].distance == 0.0
    assert ap[0].same_half is True


@pytest.mark.parametrize("monster", ["RIFTHERALD", "HORDE"])
def test_f4_top_side_monsters_fall_back_to_the_baron_pit(monster):
    tl = ra.normalize_timeline(_raw([
        _frame(120000, {"7": _pf(7, 5007, 10471)},
               [_drake(monster=monster, pos=False)])]))
    assert ra.objective_approach(tl, 7, tl.events[0],
                                 leads_s=(5,))[0].distance == 0.0


def test_f4_dragon_without_a_position_still_uses_the_dragon_pit():
    tl = ra.normalize_timeline(_raw([
        _frame(120000, {"7": _pf(7, 9866, 4414)}, [_drake(pos=False)])]))
    assert ra.objective_approach(tl, 7, tl.events[0],
                                 leads_s=(5,))[0].distance == 0.0


def test_f4_unknown_monster_without_a_position_yields_nothing():
    tl = ra.normalize_timeline(_raw([
        _frame(120000, {"7": _pf(7)}, [_drake(monster="ATAKHAN", pos=False)])]))
    assert ra.objective_approach(tl, 7, tl.events[0], leads_s=(5,)) == []


def test_f4_explicit_pit_and_event_position_still_win():
    tl = _basic()
    ap = ra.objective_approach(tl, 7, tl.events[0], leads_s=(5,),
                               pit=ra.BARON_PIT)
    assert ap[0].distance > 5000
    ap = ra.objective_approach(tl, 7, tl.events[0], leads_s=(5,))
    assert ap[0].distance < 1000


# ------------------------------------------------ F5 lead / time validation

@pytest.mark.parametrize("bad", [-30, -0.5, math.nan, -math.inf, True,
                                 "30", None])
def test_f5_drake_verdict_refuses_a_bad_lead(bad):
    with pytest.raises(ValueError):
        ra.drake_pathing_verdict(_basic(), participant_id=7, lead_s=bad)


@pytest.mark.parametrize("bad", [-30, math.nan, True, "30"])
def test_f5_bad_lead_is_refused_even_with_no_drakes(bad):
    # The refusal is the verdict function's own, not a side effect of the
    # first drake reaching objective_approach.
    with pytest.raises(ValueError):
        ra.drake_pathing_verdict(_basic([]), participant_id=7, lead_s=bad)


def test_f5_drake_verdict_still_refuses_a_long_lead_by_name():
    with pytest.raises(ValueError, match="calibrated support"):
        ra.drake_pathing_verdict(_basic(), participant_id=7, lead_s=math.inf)


@pytest.mark.parametrize("ok", [0, 0.0, 15.5, 30])
def test_f5_drake_verdict_accepts_a_supported_lead(ok):
    assert len(ra.drake_pathing_verdict(_basic(), participant_id=7,
                                        lead_s=ok)) == 1


@pytest.mark.parametrize("bad", [-5, math.nan, math.inf, True, "5"])
def test_f5_objective_approach_refuses_a_bad_lead(bad):
    tl = _basic()
    with pytest.raises(ValueError):
        ra.objective_approach(tl, 7, tl.events[0], leads_s=(bad,))


@pytest.mark.parametrize("bad", [math.nan, math.inf, True, "60000", None])
def test_f5_position_at_refuses_a_bad_time(bad):
    with pytest.raises(ValueError):
        ra.position_at(_basic(), 7, bad)


# ------------------------------------------- F6 wrong-shape containers

@pytest.mark.parametrize("raw", [
    None, [], "x", 5,
    {"info": []}, {"info": "x"},
    {"info": {"frames": {"a": 1}}}, {"info": {"frames": "abc"}},
    {"info": {"frames": [None, 5, "x"]}},
    {"info": {"frames": [{"timestamp": 0, "participantFrames": [1, 2]}]}},
    {"info": {"frames": [{"timestamp": 0, "participantFrames": {"1": 5}}]}},
    {"info": {"frames": [{"timestamp": 0, "participantFrames": {
        "1": {"participantId": 1, "position": [1, 2]}}}]}},
    {"info": {"frames": [{"timestamp": 0, "events": {"a": 1}}]}},
    {"info": {"frames": [{"timestamp": 0, "events": [None, 3, "x"]}]}},
    {"info": {"frames": [{"timestamp": 0, "events": [
        {"type": "ELITE_MONSTER_KILL", "timestamp": 5, "position": "x"}]}]}},
])
def test_f6_wrong_shape_input_does_not_raise(raw):
    tl = ra.normalize_timeline(raw)
    assert isinstance(tl, ra.Timeline)


def test_f6_one_bad_frame_does_not_drop_the_good_ones():
    tl = ra.normalize_timeline(_raw([None, _frame(60000, {"7": _pf(7)}),
                                     "junk"]))
    assert [f.t_ms for f in tl.frames] == [60000]


# ------------------------------------------------ F7 strict scalar reading

@pytest.mark.parametrize("bad", ["abc", math.nan, math.inf, {"a": 1}, [1]])
def test_f7_malformed_economy_field_does_not_raise(bad):
    tl = ra.normalize_timeline(_raw([_frame(60000, {"7": _pf(7, totalGold=bad,
                                                              xp=bad)})]))
    assert tl.frames[0].total_gold == 0 and tl.frames[0].xp == 0


@pytest.mark.parametrize("bad", [True, 3.7, "12", -5])
def test_f7_bool_fraction_string_or_negative_is_not_a_value(bad):
    tl = ra.normalize_timeline(_raw([_frame(60000, {"7": _pf(7, level=bad,
                                                              minionsKilled=bad)})]))
    assert tl.frames[0].level == 0 and tl.frames[0].cs == 0


def test_f7_integral_float_is_read():
    tl = ra.normalize_timeline(_raw([_frame(60000.0, {"7": _pf(7.0,
                                                               totalGold=1200.0)})]))
    f = tl.frames[0]
    assert (f.t_ms, f.participant_id, f.total_gold) == (60000, 7, 1200)


@pytest.mark.parametrize("bad", [{"a": 1}, 5, ["DRAGON"]])
def test_f7_non_string_type_is_empty_not_a_repr(bad):
    tl = ra.normalize_timeline(_raw([_frame(60000, events=[
        {"type": bad, "timestamp": 61000, "monsterType": bad,
         "wardType": bad}])]))
    ev = tl.events[0]
    assert (ev.type, ev.monster_type, ev.ward_type) == ("", "", "")


@pytest.mark.parametrize("bad", ["x", math.nan, True, 1.5])
def test_f7_malformed_event_ids_read_as_none(bad):
    tl = ra.normalize_timeline(_raw([_frame(60000, events=[
        {"type": "CHAMPION_KILL", "timestamp": 61000, "killerId": bad,
         "victimId": bad, "itemId": bad, "killerTeamId": bad,
         "position": {"x": bad, "y": bad}}])]))
    ev = tl.events[0]
    assert (ev.actor_id, ev.victim_id, ev.item_id, ev.killer_team_id,
            ev.x, ev.y) == (0, 0, 0, 0, 0, 0)


# ------------------------------------ F8 a missing time is not 0 ms

@pytest.mark.parametrize("bad", [None, "x", -1, math.nan, True])
def test_f8_frame_without_a_valid_time_contributes_no_samples(bad):
    tl = ra.normalize_timeline(_raw([_frame(bad, {"7": _pf(7)})]))
    assert tl.frames == []


@pytest.mark.parametrize("bad", ["missing", "x", -1, math.nan, True])
def test_f8_event_without_a_valid_time_is_skipped(bad):
    ev = _drake()
    if bad == "missing":
        del ev["timestamp"]
    else:
        ev["timestamp"] = bad
    tl = ra.normalize_timeline(_raw([_frame(120000, {"7": _pf(7)}, [ev])]))
    assert tl.events == []


def test_f8_events_of_an_untimed_frame_keep_their_own_time():
    tl = ra.normalize_timeline(_raw([_frame(None, {"7": _pf(7)}, [_drake()])]))
    assert [e.t_ms for e in tl.events] == [125000]


def test_f8_frame_zero_is_still_a_real_time():
    tl = ra.normalize_timeline(_raw([_frame(0, {"7": _pf(7)})]))
    assert [f.t_ms for f in tl.frames] == [0]


# ------------------------------------ F9 a sample with no seat is nobody's

@pytest.mark.parametrize("bad", ["missing", None, 0, -2, True, "x", 2.5])
def test_f9_participant_frame_without_a_valid_id_is_skipped(bad):
    pf = _pf(7)
    if bad == "missing":
        del pf["participantId"]
    else:
        pf["participantId"] = bad
    tl = ra.normalize_timeline(_raw([_frame(60000, {"7": pf})]))
    assert tl.frames == []


def test_f9_arena_seats_beyond_ten_still_normalise():
    # normalize is mode-neutral; only team_of is SR-specific.
    tl = ra.normalize_timeline(_raw([_frame(60000, {"16": _pf(16)})]))
    assert [f.participant_id for f in tl.frames] == [16]


# --------------------------- F10 a missing position is not the map origin

@pytest.mark.parametrize("pos", ["missing", None, {}, {"x": 5}, {"x": "a", "y": 3},
                                 {"x": math.nan, "y": 1}, {"x": -1, "y": 4}])
def test_f10_sample_without_a_valid_position_is_not_positioned(pos):
    pf = _pf(7)
    if pos == "missing":
        del pf["position"]
    else:
        pf["position"] = pos
    tl = ra.normalize_timeline(_raw([_frame(60000, {"7": pf})]))
    assert tl.frames[0].has_position is False
    assert tl.frames[0].total_gold == 500      # economy is still kept
    assert ra.position_at(tl, 7, 60000) is None


def test_f10_position_at_skips_an_unpositioned_sample_for_a_real_one():
    pf = _pf(7)
    del pf["position"]
    tl = ra.normalize_timeline(_raw([
        _frame(60000, {"7": _pf(7, 4000, 11000)}),
        _frame(120000, {"7": pf}, [_drake()])]))
    s = ra.position_at(tl, 7, 120000)
    assert (s.x, s.y, s.t_ms) == (4000, 11000, 60000)


def test_f10_drake_verdict_never_measures_from_the_origin():
    pf = _pf(7)
    del pf["position"]
    tl = ra.normalize_timeline(_raw([_frame(120000, {"7": pf}, [_drake()])]))
    assert ra.drake_pathing_verdict(tl, participant_id=7) == []


def test_f10_default_frame_sample_is_positioned():
    assert ra.FrameSample(t_ms=0, participant_id=1, x=1, y=2).has_position


# ------------------------------------------- F11 frame interval validation

@pytest.mark.parametrize("bad", [-60000, 0, True, "abc", math.nan, math.inf,
                                 None, 1.5])
def test_f11_bad_frame_interval_falls_back_to_sixty_seconds(bad):
    tl = ra.normalize_timeline(_raw([_frame(60000, {"7": _pf(7)})],
                                    interval=bad))
    assert tl.frame_interval_ms == 60000


def test_f11_negative_interval_no_longer_marks_a_fresh_sample_stale():
    tl = ra.normalize_timeline(_raw([_frame(60000, {"7": _pf(7)})],
                                    interval=-60000))
    assert ra.position_at(tl, 7, 60000).stale is False


def test_f11_a_real_interval_is_kept():
    tl = ra.normalize_timeline(_raw([], interval=30000))
    assert tl.frame_interval_ms == 30000
