"""RM-603 (external reference F): live unspent skill-point tracker.

Synthetic, name-scrubbed fixtures only. The tracker is a pure step function
over consecutive readings; game time is the clock.
"""
from __future__ import annotations

import pytest

from core import skill_point_tracker as spt


def _rd(level, q=0, w=0, e=0, r=0):
    """Normalizer-shaped reading (game_reader/snapshot_normalizer.py
    my_abilities: {slot: {name, level}})."""
    return {"level": level, "my_abilities": {
        "q": {"name": "Q", "level": q}, "w": {"name": "W", "level": w},
        "e": {"name": "E", "level": e}, "r": {"name": "R", "level": r}}}


def _run(seq, champion="Annie"):
    """seq: [(t_s, src_or_None)] -> (final_state, all events)."""
    st = spt.TrackerState()
    out = []
    for t, src in seq:
        st, ev = spt.step(st, spt.read_skill_snapshot(src), t, champion)
        out.extend(ev)
    return st, out


# ------------------------------------------------------------ reading

def test_reads_normalizer_shape():
    r = spt.read_skill_snapshot(_rd(3, q=2, w=1))
    assert r.level == 3 and r.ranks == {"q": 2, "w": 1, "e": 0, "r": 0}


def test_reads_raw_active_player_shape_and_zero_is_zero():
    ap = {"level": 2, "abilities": {
        "Passive": {"displayName": "P"},
        "Q": {"abilityLevel": 1}, "W": {"abilityLevel": 0},
        "E": {"abilityLevel": 0}, "R": {"abilityLevel": 0}}}
    r = spt.read_skill_snapshot(ap)
    assert r.ranks == {"q": 1, "w": 0, "e": 0, "r": 0}


def test_reads_liveclient_summary_shape():
    r = spt.read_skill_snapshot({"level": 4, "ability_ranks":
                                 {"q": 2, "w": 1, "e": 1, "r": 0}})
    assert r.level == 4 and sum(r.ranks.values()) == 4


@pytest.mark.parametrize("src", [
    None, {}, {"level": None, "my_abilities": {}},
    _rd(None), {"level": 3, "my_abilities": {"q": {"level": 1}}},
    {"level": 3, "my_abilities": {"q": {"level": None}, "w": {"level": 0},
                                  "e": {"level": 0}, "r": {"level": 0}}},
    {"level": "x", "ability_ranks": {"q": 0, "w": 0, "e": 0, "r": 0}},
    {"level": 0, "ability_ranks": {"q": 0, "w": 0, "e": 0, "r": 0}},
    {"level": float("inf"), "ability_ranks": {"q": 0, "w": 0, "e": 0, "r": 0}},
    {"level": float("nan"), "ability_ranks": {"q": 0, "w": 0, "e": 0, "r": 0}},
    {"level": 3, "ability_ranks": {"q": float("-inf"), "w": 0, "e": 0,
                                   "r": 0}},
    {"level": 2, "ability_ranks": {"q": -1, "w": 0, "e": 0, "r": 0}},
    {"level": 2, "ability_ranks": {"q": True, "w": 0, "e": 0, "r": 0}},
])
def test_incomplete_reading_is_none(src):
    assert spt.read_skill_snapshot(src) is None


# ------------------------------------------------------------ unspent

def test_unspent_is_level_minus_ranks():
    assert spt.unspent(spt.read_skill_snapshot(_rd(4, q=2, w=1)), "Annie") == 1


def test_r_only_at_6_11_16():
    # level 5, Q3 W1 -> 1 unspent, basics can take it (W/E).
    rd = spt.read_skill_snapshot(_rd(5, q=3, w=1))
    assert spt.spendable(rd, "Annie") == 1
    # Level 5 with only R open would not light: all basics capped for level.
    assert spt.slot_open(rd, "Annie", "r") is False
    assert spt.slot_open(spt.read_skill_snapshot(_rd(6, q=3, w=2, e=1)),
                         "Annie", "r") is True
    assert spt.slot_open(spt.read_skill_snapshot(
        _rd(10, q=5, w=3, e=1, r=1)), "Annie", "r") is False
    assert spt.slot_open(spt.read_skill_snapshot(
        _rd(11, q=5, w=4, e=1, r=1)), "Annie", "r") is True


def test_capped_ability_never_lights():
    # Level 18 standard kit fully ranked: 5+5+5+3 = 18, nothing open.
    rd = spt.read_skill_snapshot(_rd(18, q=5, w=5, e=5, r=3))
    assert spt.spendable(rd, "Annie") == 0
    # Above the cap (mode allows level > 18): points exist, no slot takes one.
    rd = spt.read_skill_snapshot(_rd(20, q=5, w=5, e=5, r=3))
    assert spt.unspent(rd, "Annie") == 2
    assert spt.spendable(rd, "Annie") == 0


def test_basic_rank_gate_is_half_level():
    # level 3: a basic may hold rank 2 at most (rank k needs level 2k-1).
    rd = spt.read_skill_snapshot(_rd(3, q=2, w=0))
    assert spt.slot_open(rd, "Annie", "q") is False
    assert spt.slot_open(rd, "Annie", "w") is True


# ------------------------------------------------------------ step / events

def test_first_sight_emits_nothing_even_with_a_point_held():
    st, ev = _run([(10.0, _rd(2, q=1))])
    assert ev == []
    assert st.seen is True and len(st.since) == 1


def test_none_never_transitions():
    st0, _ = _run([(10.0, _rd(1, q=1))])
    st1, ev = spt.step(st0, None, 50.0, "Annie")
    assert ev == [] and st1 == st0
    # A None between two identical readings changes nothing either.
    _, ev = _run([(10.0, _rd(1, q=1)), (20.0, None), (30.0, _rd(1, q=1)),
                  (40.0, {"level": 2, "my_abilities": {}})])
    assert ev == []


def test_synthetic_level_sequence_held_for():
    seq = [
        (5.0, _rd(1, q=1)),            # first sight: state only
        (90.0, _rd(2, q=1)),           # level 2 -> point appears
        (97.5, _rd(2, q=1, w=1)),      # spent after 7.5 s
        (150.0, _rd(3, q=1, w=1)),     # level 3 -> point
        (160.0, _rd(4, q=1, w=1)),     # level 4 -> second point held
        (190.0, _rd(4, q=2, w=1)),     # oldest spent: 40 s
        (200.0, _rd(4, q=2, w=1, e=1)),  # next: 40 s (held since 160)
    ]
    _, ev = _run(seq)
    kinds = [e["kind"] for e in ev]
    assert kinds == ["skill_point", "skill_spent", "skill_point",
                     "skill_point", "skill_spent", "skill_spent"]
    spent = [e["held_for"] for e in ev if e["kind"] == "skill_spent"]
    assert spent == [7.5, 40.0, 40.0]
    assert ev[0]["unspent"] == 1 and ev[3]["unspent"] == 2


def test_two_points_spent_in_one_tick_emit_two_spent_events():
    seq = [(1.0, _rd(1, q=1)), (60.0, _rd(3, q=1)),
           (70.0, _rd(3, q=2, w=1))]
    _, ev = _run(seq)
    spent = [e for e in ev if e["kind"] == "skill_spent"]
    assert [e["held_for"] for e in spent] == [10.0, 10.0]


def test_level_drop_is_a_new_game_and_first_sight_again():
    seq = [(1.0, _rd(1, q=1)), (900.0, _rd(9, q=5, w=2, e=1, r=1)),
           (3.0, _rd(1))]
    st, ev = _run(seq)
    # Game 2 first sight emits nothing, even though a point is held.
    assert all(e["t_s"] != 3.0 for e in ev)
    assert st.level == 1 and len(st.since) == 1


# ------------------------------------------------------------ special kits

def _fence(champion, seq):
    """No skill_point event and no toast when every reading is fully spent."""
    st = spt.TrackerState()
    for t, src in seq:
        st, ev = spt.step(st, spt.read_skill_snapshot(src), t, champion)
        assert [e for e in ev if e["kind"] == "skill_point"] == [], (
            champion, t, src)
        assert spt.skill_point_callout(st, t + 600.0) is None, (champion, t)


def test_fence_udyr_r_at_level_one_four_basic_like_slots():
    _fence("Udyr", [(1.0, _rd(1, r=1)), (90.0, _rd(2, q=1, r=1)),
                    (150.0, _rd(3, q=1, r=2)), (900.0, _rd(11, q=6, r=5)),
                    (1500.0, _rd(18, q=6, w=6, r=6))])
    # Udyr R rank 2 at level 3 is legal (basic-like), and R rank 6 is legal.
    rd = spt.read_skill_snapshot(_rd(3, q=1, r=1))
    assert spt.slot_open(rd, "Udyr", "r") is True


@pytest.mark.parametrize("champion", ["Elise", "Nidalee", "Karma"])
def test_fence_free_r_rank_kits(champion):
    # R rank 1 is granted at level 1 without a point: level 1 + Q1 + R1 is
    # fully spent, not "-1 unspent" and not a phantom point later.
    _fence(champion, [(1.0, _rd(1, q=1, r=1)), (90.0, _rd(2, q=1, w=1, r=1)),
                      (400.0, _rd(6, q=3, w=1, e=1, r=2)),
                      (1600.0, _rd(16, q=5, w=5, e=3, r=4))])
    rd = spt.read_skill_snapshot(_rd(2, q=1, r=1))
    assert spt.unspent(rd, champion) == 1


def test_fence_jayce_real_frames_r_stays_one():
    # Jayce starts with Transform (R rank 1, free) and can never rank it;
    # every level point goes to a basic, which ranks to 6.
    _fence("Jayce", [(1.0, _rd(1, q=1, r=1)), (90.0, _rd(2, q=1, w=1, r=1)),
                     (400.0, _rd(6, q=3, w=2, e=1, r=1)),
                     (900.0, _rd(11, q=6, w=4, e=1, r=1)),
                     (1600.0, _rd(16, q=6, w=6, e=4, r=1)),
                     (2000.0, _rd(18, q=6, w=6, e=6, r=1))])
    rd = spt.read_skill_snapshot(_rd(2, q=1, r=1))
    assert spt.unspent(rd, "Jayce") == 1


@pytest.mark.parametrize("frame", [
    _rd(6, q=3, w=2, e=1, r=1),
    _rd(11, q=6, w=4, e=1, r=1),
    _rd(16, q=6, w=6, e=4, r=1),
])
def test_jayce_r_never_opens_at_6_11_16(frame):
    # The level-6/11/16 R unlock that every other kit gets does not exist
    # for Jayce: with basics placed legally and R=1, nothing is held and R
    # is not an open slot, so no nag can fire.
    rd = spt.read_skill_snapshot(frame)
    assert spt.unspent(rd, "Jayce") == 0
    assert spt.spendable(rd, "Jayce") == 0
    assert spt.slot_open(rd, "Jayce", "r") is False
    st, ev = spt.step(spt.TrackerState(), rd, 10.0, "Jayce")
    st, ev = spt.step(st, rd, 500.0, "Jayce")
    assert ev == [] and spt.skill_point_callout(st, 900.0) is None


def test_jayce_basics_rank_six():
    rd = spt.read_skill_snapshot(_rd(11, q=5, w=5, e=1, r=1))
    assert spt.slot_open(rd, "Jayce", "q") is True
    assert spt.slot_open(rd, "Elise", "q") is False


def test_fence_aphelios_never_nags():
    # No normal ability ranks: whatever the reading, no event, no toast.
    _fence("Aphelios", [(1.0, _rd(1)), (90.0, _rd(2)), (400.0, _rd(6, r=0)),
                        (900.0, _rd(11, q=3, r=1))])
    assert spt.unspent(spt.read_skill_snapshot(_rd(6)), "Aphelios") is None


def test_unknown_champion_uses_standard_rules():
    rd = spt.read_skill_snapshot(_rd(2, q=1))
    assert spt.spendable(rd, "") == 1


# ------------------------------------------------------------ toast producer

def test_callout_after_threshold_only():
    st, _ = _run([(1.0, _rd(1, q=1)), (90.0, _rd(2, q=1))])
    n = spt.NAG_AFTER_S
    assert spt.skill_point_callout(st, 90.0 + n - 0.5) is None
    co = spt.skill_point_callout(st, 90.0 + n)
    assert co["kind"] == "skill_point" and co["eta_s"] is None
    assert co["tag"] == "skill_point" and isinstance(co["line"], str)
    assert co["line"].isascii()
    # Spent -> gone.
    st, _ = spt.step(st, spt.read_skill_snapshot(_rd(2, q=1, w=1)), 200.0,
                     "Annie")
    assert spt.skill_point_callout(st, 400.0) is None


def test_callout_none_on_empty_or_bad_time():
    assert spt.skill_point_callout(spt.TrackerState(), 100.0) is None
    st, _ = _run([(1.0, _rd(1, q=1)), (90.0, _rd(2, q=1))])
    assert spt.skill_point_callout(st, None) is None
