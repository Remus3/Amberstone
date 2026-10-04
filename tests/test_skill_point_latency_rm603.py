"""RM-603 post-game half: Match-V5 LEVEL_UP paired with SKILL_LEVEL_UP into a
``skill_point_latency`` Finding, and its place in the PGR decision view.

Synthetic timelines only (no real ids, no names).
"""
from __future__ import annotations

from core import event_patterns as ep
from core import pgr_event_report as pgr
from core import skill_point_tracker as spt


def _match(champ="Annie", pid=1):
    parts = []
    for i in range(1, 11):
        parts.append({"participantId": i,
                      "teamPosition": "MIDDLE" if i in (3, 8) else "TOP",
                      "championName": champ if i == pid else "Annie",
                      "win": i <= 5})
    return {"info": {"participants": parts}}


def _tl(events):
    return {"info": {"frames": [{"timestamp": 0, "events": events}]}}


def _lv(t, pid, level):
    return {"type": "LEVEL_UP", "timestamp": t, "participantId": pid,
            "level": level}


def _sk(t, pid, slot=1, kind="NORMAL"):
    return {"type": "SKILL_LEVEL_UP", "timestamp": t, "participantId": pid,
            "skillSlot": slot, "levelUpType": kind}


def _rift_events(pid=1):
    return [
        _sk(9000, pid),            # level-1 point: starting, not measured
        _lv(90000, pid, 2), _sk(92000, pid, 2),        # held 2 s
        _lv(150000, pid, 3),
        _lv(170000, pid, 4),
        _sk(200000, pid, 1),       # pairs with level 3: held 50 s
        _sk(201000, pid, 3),       # pairs with level 4: held 31 s
        _sk(205000, pid, 4, kind="EVOLVE"),   # not a level point
        _lv(300000, 2, 5), _sk(300500, 2),    # another participant
    ]


def test_pairs_fifo_and_held_ms():
    f = ep.skill_point_latency(_match(), _tl(_rift_events()), 1)
    assert len(f) == 1
    d = f[0].detail
    assert [p["held_ms"] for p in d["pairs"]] == [2000, 50000, 31000]
    assert [p["level"] for p in d["pairs"]] == [2, 3, 4]
    assert d["n"] == 3
    assert d["max_held_ms"] == 50000
    assert d["median_held_ms"] == 31000
    assert d["held_over_nag"] == 2          # 50 s and 31 s >= 15 s
    assert f[0].criterion == "skill_point_latency"
    assert f[0].value == 31.0               # median, seconds
    assert f[0].t_ms == 150000              # the longest hold's level-up
    assert f[0].role == "TOP"


def test_aram_start_burst_is_starting_credit_not_a_hold():
    ev = [_lv(500, 1, 2), _lv(500, 1, 3),
          _sk(18000, 1, 1), _sk(18100, 1, 2), _sk(18200, 1, 3),
          _lv(80000, 1, 4), _sk(81000, 1, 1)]
    f = ep.skill_point_latency(_match(), _tl(ev), 1)
    assert [p["held_ms"] for p in f[0].detail["pairs"]] == [1000]


def test_unspent_level_at_game_end_is_reported_not_paired():
    ev = [_sk(1000, 1), _lv(90000, 1, 2), _sk(91000, 1), _lv(150000, 1, 3)]
    f = ep.skill_point_latency(_match(), _tl(ev), 1)
    assert [p["held_ms"] for p in f[0].detail["pairs"]] == [1000]
    assert f[0].detail["unspent_at_end"] == 1


def test_evolve_does_not_spend_a_queued_point():
    ev = [_sk(1000, 1), _lv(90000, 1, 2), _sk(91000, 1, 2, kind="EVOLVE"),
          _sk(99000, 1, 1)]
    f = ep.skill_point_latency(_match(), _tl(ev), 1)
    assert [p["held_ms"] for p in f[0].detail["pairs"]] == [9000]


def test_aphelios_is_fenced_out():
    ev = _rift_events() + [_sk(400000, 1), _sk(401000, 1)]
    assert ep.skill_point_latency(_match("Aphelios"), _tl(ev), 1) == []


def test_free_r_kit_pairs_normally():
    # Free level-1 R rank emits no SKILL_LEVEL_UP (probe), so pairing is
    # unchanged for Jayce / Elise / Nidalee / Karma.
    for champ in ("Jayce", "Elise", "Nidalee", "Karma", "Udyr"):
        f = ep.skill_point_latency(_match(champ), _tl(_rift_events()), 1)
        assert [p["held_ms"] for p in f[0].detail["pairs"]] == [
            2000, 50000, 31000], champ


def test_no_level_ups_is_empty():
    assert ep.skill_point_latency(_match(), _tl([_sk(1000, 1)]), 1) == []
    assert ep.skill_point_latency(_match(), _tl([]), 1) == []


def test_registered_and_in_pgr_decision_criteria():
    assert ep.CRITERIA["skill_point_latency"] is ep.skill_point_latency
    assert "skill_point_latency" in pgr.DECISION_CRITERIA
    # Existing decision criteria are kept (additive only).
    for name in ("skill_order", "objective_participation",
                 "kill_participation", "plate_share"):
        assert name in pgr.DECISION_CRITERIA


def test_pgr_win_view_carries_the_latency_line():
    lines = pgr.decision_pattern(_match(), _tl(_rift_events()), 1)
    lat = [ln for ln in lines if ln["criterion"] == "skill_point_latency"]
    assert len(lat) == 1
    assert lat[0]["validated"] is False
    assert lat[0]["detail"]["max_held_ms"] == 50000


def test_nag_threshold_is_shared_with_live():
    f = ep.skill_point_latency(_match(), _tl(_rift_events()), 1)
    assert f[0].detail["nag_after_s"] == spt.NAG_AFTER_S
