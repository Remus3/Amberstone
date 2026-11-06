# arch: s144 true-audit - core/skill_point_tracker.py hardening | section=tests | frozen=no
"""s144 lane 8 (true-audit) - `core/skill_point_tracker.py` hardening.

`dashboard/_liveclient.py` calls `read_skill_snapshot` on every
`liveclient_summary` build (the raw :2999 `activePlayer`) and echoes the
ranks into /api/state `ability_ranks`; `core/event_patterns.py` calls
`kit_rules` post-game; `step` / `skill_point_callout` are the public live
half the RM-604 deriver will drive once a tick. Every defect below was
measured on the pre-fix module by calling the real functions:

  K1  `step` caught TypeError / ValueError only: a long-int clock (10**400)
      raised OverflowError out of `step`.
  K2  `step` took any float(): NaN, inf and the str "nan" were stamped into
      `since` and into the emitted events' `t_s` (a JSON NaN / Infinity),
      and bool True read as game time 1.0.
  K3  `skill_point_callout` raised ValueError / OverflowError on a NaN /
      inf / long-int `now_s`, and on a NaN stamp left by K2 it raised on
      EVERY later call; a non-number `nag_after_s` raised TypeError and a
      NaN one fired the nag at once.
  K4  No magnitude bound: a rank of 99 or 1e300 and a level of 10**400 were
      a valid reading, so a 301-digit rank reached /api/state
      `ability_ranks` (JSON.parse reads it as Infinity).
  K5  A str rank went through int(), so "1_0" read as 10, " 3\\n" as 3, an
      Arabic-Indic digit as 3 and "+5" as 5.
  K6  A non-str champion became str(container) in `step`, so a list
      champion read as a DIFFERENT champion than the stored one and reset
      the tracker (a "new game"), silently dropping every held point; and
      a tick with no champion fell back to the STANDARD kit, so a Jayce /
      Elise / Nidalee / Karma state (free R rank) emitted a phantom
      skill_spent on that tick and a phantom skill_point on the next.
  K7  A hand-built `SkillReading` missing a slot, or carrying a str / float
      / bool / out-of-range level or rank, raised KeyError / TypeError out
      of `unspent` / `spendable` / `slot_open` / `step` (a float level made
      `step` build `[t] * 2.0`) instead of reading as "no reading".

Synthetic, name-scrubbed fixtures only.
"""
from __future__ import annotations

import json
import math

import pytest

from core import skill_point_tracker as spt


def _src(level, q=0, w=0, e=0, r=0):
    return {"level": level, "ability_ranks": {"q": q, "w": w, "e": e,
                                              "r": r}}


def _rd(level, q=0, w=0, e=0, r=0):
    return spt.read_skill_snapshot(_src(level, q, w, e, r))


def _held_state():
    """A tracker holding one spendable point stamped at game time 50.0."""
    st, _ = spt.step(spt.TrackerState(), _rd(1, q=1), 1.0, "Annie")
    st, ev = spt.step(st, _rd(2, q=1), 50.0, "Annie")
    assert [e["kind"] for e in ev] == ["skill_point"]
    assert st.since == (50.0,)
    return st


# ------------------------------------------------------------ K1 / K2 clock

@pytest.mark.parametrize("bad", [
    pytest.param(10 ** 400, id="int400"), float("nan"), float("inf"),
    float("-inf"), "nan", "60", 1e300, -1e300, 1e6 + 1,
    True, False, None, [1.0], complex(1, 0),
])
def test_step_bad_clock_never_transitions_and_never_raises(bad):
    st = _held_state()
    # A spend at a junk clock is no reading: nothing moves, nothing fires.
    st2, ev = spt.step(st, _rd(2, q=1, w=1), bad, "Annie")
    assert ev == [] and st2 == st
    # A new point at a junk clock is not stamped either.
    st3, ev = spt.step(st, _rd(3, q=1), bad, "Annie")
    assert ev == [] and st3 == st


def test_step_bad_clock_on_first_sight_seeds_nothing():
    st, ev = spt.step(spt.TrackerState(), _rd(2, q=1), float("nan"), "Annie")
    assert ev == [] and st == spt.TrackerState()


def test_step_events_are_strict_json_after_a_nan_tick():
    st = _held_state()
    st, _ = spt.step(st, _rd(3, q=1), float("nan"), "Annie")
    st, ev = spt.step(st, _rd(3, q=1), 60.0, "Annie")
    assert ev and all(math.isfinite(e["t_s"]) for e in ev)
    assert all(math.isfinite(t) for t in st.since)
    json.dumps(ev, allow_nan=False)


def test_clock_bound_admits_a_long_game():
    st = _held_state()
    assert spt.skill_point_callout(st, spt._MAX_GAME_TIME_S)["line"] == (
        "1 skill point unspent for 999950s")
    st2, ev = spt.step(st, _rd(2, q=1, w=1), 7200.0, "Annie")
    assert ev[0]["held_for"] == 7150.0


def test_step_int_and_float_clock_still_work():
    st = _held_state()
    st2, ev = spt.step(st, _rd(2, q=1, w=1), 57, "Annie")
    assert ev[0]["kind"] == "skill_spent" and ev[0]["held_for"] == 7.0
    assert st2.since == ()


# ------------------------------------------------------------ K3 callout

@pytest.mark.parametrize("bad", [
    float("nan"), float("inf"), float("-inf"),
    pytest.param(10 ** 400, id="int400"), True, "100",
    None, 1e300, 1e6 + 1,
])
def test_callout_bad_now_is_none_not_a_raise(bad):
    assert spt.skill_point_callout(_held_state(), bad) is None


def test_callout_on_a_poisoned_stamp_is_none_not_a_raise():
    # A state carrying a non-finite stamp (a pre-fix tick, or a hand-built
    # state) must never raise out of the toast producer.
    for stamp in (float("nan"), float("inf"), float("-inf"), "x", None,
                  -1e300, 1e6 + 1):
        st = spt.TrackerState(seen=True, level=2, since=(stamp,),
                              champion="Annie")
        assert spt.skill_point_callout(st, 100.0) is None


@pytest.mark.parametrize("bad_nag", [float("nan"), float("inf"), "x", None,
                                     -5.0, True])
def test_callout_bad_nag_threshold_uses_the_default(bad_nag):
    st = _held_state()
    n = spt.NAG_AFTER_S
    assert spt.skill_point_callout(st, 50.0 + n - 0.5, bad_nag) is None
    co = spt.skill_point_callout(st, 50.0 + n, bad_nag)
    assert co is not None and co["kind"] == "skill_point"


def test_callout_custom_nag_still_honoured():
    st = _held_state()
    assert spt.skill_point_callout(st, 52.0, 5.0) is None
    assert spt.skill_point_callout(st, 55.0, 5.0)["line"] == (
        "1 skill point unspent for 5s")
    assert spt.skill_point_callout(st, 50.0, 0) is not None


# ------------------------------------------------------------ K4 bounds

@pytest.mark.parametrize("src", [
    _src(3, q=99), _src(3, q=1e300), _src(3, q=10 ** 400),
    _src(3, q=11), _src(10 ** 400, q=1), _src(1e300, q=1), _src(101, q=1),
])
def test_out_of_range_reading_is_none(src):
    assert spt.read_skill_snapshot(src) is None


def test_bounds_admit_every_real_kit_and_level():
    # Udyr / Jayce rank a slot to 6; a mode levels past 18.
    assert max(k.basic_max for k in spt.SPECIAL_KITS.values()) <= spt._MAX_RANK
    assert max(k.r_max for k in spt.SPECIAL_KITS.values()) <= spt._MAX_RANK
    rd = spt.read_skill_snapshot(_src(spt._MAX_LEVEL, q=spt._MAX_RANK))
    assert rd is not None and rd.ranks["q"] == spt._MAX_RANK
    rd = spt.read_skill_snapshot(_src(18.0, q=6.0, w=6.0, e=6.0, r=0))
    assert rd is not None and rd.level == 18 and rd.ranks["q"] == 6


# ------------------------------------------------------------ K5 str ranks

@pytest.mark.parametrize("bad", ["1_0", " 3\n", "\u0663", "+5", "-0", "",
                                 "3.0", "0x3"])
def test_non_canonical_str_rank_is_none(bad):
    assert spt.read_skill_snapshot(_src(20, q=bad)) is None
    assert spt.read_skill_snapshot(_src(bad, q=0)) is None


def test_canonical_decimal_str_still_reads():
    rd = spt.read_skill_snapshot(_src("4", q="2", w="1", e="1", r="0"))
    assert rd is not None and rd.level == 4
    assert rd.ranks == {"q": 2, "w": 1, "e": 1, "r": 0}


# ------------------------------------------------------------ K6 champion

@pytest.mark.parametrize("bad", [["Annie"], {"x": 1}, 7, b"Annie"])
def test_non_str_champion_never_resets_the_tracker(bad):
    st = _held_state()
    st2, ev = spt.step(st, _rd(2, q=1), 60.0, bad)
    # Same level, same point held: no "new game", the stamp survives.
    assert ev == [] and st2.since == (50.0,)
    assert st2.champion == "Annie"


def test_non_str_champion_reads_standard_kit():
    for bad in (["Jayce"], {"Jayce": 1}, 7, b"Jayce", None):
        assert spt.kit_rules(bad) is spt.STANDARD


def test_a_champion_less_tick_keeps_the_stored_kit():
    # Jayce at level 2 with Q 1 and the free R 1 holds one point under his
    # own rules and none under the standard kit. One tick with no champion
    # must not flip to the standard kit (a phantom spend, then a phantom new
    # point on the next tick).
    st, _ = spt.step(spt.TrackerState(), _rd(2, q=1, r=1), 10.0, "Jayce")
    assert st.since == (10.0,)
    for missing in (None, "", ["Jayce"]):
        st2, ev = spt.step(st, _rd(2, q=1, r=1), 20.0, missing)
        assert ev == [] and st2.since == (10.0,) and st2.champion == "Jayce"
    st3, ev = spt.step(st, _rd(2, q=1, w=1, r=1), 30.0, None)
    assert [e["kind"] for e in ev] == ["skill_spent"]
    assert ev[0]["held_for"] == 20.0 and ev[0]["champion"] == "Jayce"


def test_real_champion_change_is_still_a_new_game():
    st = _held_state()
    st2, ev = spt.step(st, _rd(2, q=1), 60.0, "Karma")
    assert ev == [] and st2.champion == "Karma" and st2.since == (60.0,)


# ------------------------------------------------------------ K7 reading

@pytest.mark.parametrize("bad", [
    spt.SkillReading(level=3, ranks={}),
    spt.SkillReading(level=3, ranks={"q": 1, "w": 0, "e": 0}),
    spt.SkillReading(level=3, ranks={"q": "x", "w": 0, "e": 0, "r": 0}),
    spt.SkillReading(level=3, ranks={"q": -1, "w": 0, "e": 0, "r": 0}),
    spt.SkillReading(level=0, ranks={"q": 0, "w": 0, "e": 0, "r": 0}),
    spt.SkillReading(level=float("nan"),
                     ranks={"q": 0, "w": 0, "e": 0, "r": 0}),
    spt.SkillReading(level=3, ranks=None),
    spt.SkillReading(level="5", ranks={"q": 1, "w": 1, "e": 1, "r": 0}),
    spt.SkillReading(level=5, ranks={"q": "1", "w": 1, "e": 1, "r": 0}),
    spt.SkillReading(level=5.0, ranks={"q": 1, "w": 1, "e": 1, "r": 0}),
    spt.SkillReading(level=5, ranks={"q": 1.0, "w": 1, "e": 1, "r": 0}),
    spt.SkillReading(level=True, ranks={"q": 0, "w": 0, "e": 0, "r": 0}),
    spt.SkillReading(level=101, ranks={"q": 1, "w": 1, "e": 1, "r": 0}),
    spt.SkillReading(level=5, ranks={"q": 11, "w": 1, "e": 1, "r": 0}),
    {"level": 3},
])
def test_malformed_reading_is_no_reading(bad):
    assert spt.unspent(bad, "Annie") is None
    assert spt.spendable(bad, "Annie") == 0
    assert spt.slot_open(bad, "Annie", "q") is False
    st = _held_state()
    assert spt.step(st, bad, 60.0, "Annie") == (st, [])


@pytest.mark.parametrize("extra", ["x", None, [1], float("nan"), 1.5, 7])
def test_an_extra_rank_key_is_ignored(extra):
    # Only Q/W/E/R are level points; a stray key in a hand-built reading
    # must neither raise nor move the count (it used to be summed).
    ranks = {"q": 1, "w": 1, "e": 1, "r": 0, "z": extra}
    rd = spt.SkillReading(level=5, ranks=ranks)
    assert spt.unspent(rd, "Annie") == 2
    assert spt.spendable(rd, "Annie") == 2
    st, ev = spt.step(spt.TrackerState(), rd, 10.0, "Annie")
    assert ev == [] and st.since == (10.0, 10.0)
    st2, ev = spt.step(st, rd, 20.0, "Annie")
    assert ev == [] and st2.since == (10.0, 10.0)


def test_slot_open_unknown_slot_is_false():
    assert spt.slot_open(_rd(3, q=1), "Annie", "x") is False
    assert spt.slot_open(_rd(3, q=1), "Annie", "w") is True
