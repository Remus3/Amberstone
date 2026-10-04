"""Tests for core/self_cast_log.py (RM-606, directive X-06, external reference F).

All sequences are synthetic. No captured payloads, no real Riot IDs.
"""
from __future__ import annotations

import pytest

from core import self_cast_log as scl

# Synthetic per-rank cost table in the shape load_cost_table returns:
# slot -> (resource, per-rank costs). Values are invented for the tests.
MANA_COSTS = {
    "Q": ("MANA", (50.0, 60.0, 70.0, 80.0, 90.0)),
    "W": ("MANA", (30.0, 30.0, 30.0, 30.0, 30.0)),
    "E": ("MANA", (85.0, 85.0, 85.0, 85.0, 85.0)),
    "R": ("MANA", (100.0, 100.0, 100.0)),
}
ENERGY_COSTS = {
    "Q": ("ENERGY", (75.0, 70.0, 65.0, 60.0, 55.0)),
    "W": ("ENERGY", (40.0, 35.0, 30.0, 25.0, 20.0)),
    "E": ("ENERGY", (50.0, 50.0, 50.0, 50.0, 50.0)),
    "R": (None, None),
}
RANKS = {"Q": 1, "W": 1, "E": 1, "R": 0}


def rd(t, value, maximum=500.0, rtype="MANA", ranks=None):
    return scl.Reading(t=t, value=value, maximum=maximum, rtype=rtype,
                       ranks=dict(ranks or RANKS))


def run(det, readings):
    out = []
    for r in readings:
        out.extend(det.feed(r))
    return out


# -- hold-confirm vs revert ---------------------------------------------------

def test_fall_that_holds_is_emitted_once_on_the_confirming_poll():
    det = scl.SelfCastDetector(MANA_COSTS)
    # 400 -> 350 (Q rank 1 = 50) then holds at 351 (regen 1).
    assert det.feed(rd(10.0, 400.0)) == []
    assert det.feed(rd(10.5, 350.0)) == []  # candidate only
    ev = det.feed(rd(11.0, 351.0))
    assert len(ev) == 1
    e = ev[0]
    assert set(e) == {"t", "slot_guess", "cost", "confidence", "span"}
    assert e["t"] == 10.5
    assert e["slot_guess"] == "Q"
    assert e["cost"] == pytest.approx(50.0)
    assert e["span"] is None
    assert e["confidence"] >= 0.8


def test_fall_that_reverts_on_next_poll_is_dropped():
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(10.0, 400.0), rd(10.5, 350.0), rd(11.0, 400.0), rd(11.5, 401.0)]
    assert run(det, seq) == []


def test_small_fall_below_threshold_is_not_a_candidate():
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(10.0, 400.0), rd(10.5, 400.0 - scl.FALL_THRESHOLD + 0.5),
           rd(11.0, 399.0 - scl.FALL_THRESHOLD)]
    assert run(det, seq) == []


def test_duplicate_reading_same_game_time_is_not_a_new_poll():
    det = scl.SelfCastDetector(MANA_COSTS)
    # The relay can hand the same frame to two polls; that must not confirm.
    seq = [rd(10.0, 400.0), rd(10.5, 350.0), rd(10.5, 350.0)]
    assert run(det, seq) == []
    assert len(det.feed(rd(11.0, 351.0))) == 1


def test_back_to_back_casts_each_confirmed():
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(1.0, 400.0), rd(1.5, 350.0), rd(2.0, 320.0), rd(2.5, 321.0)]
    ev = run(det, seq)
    assert [e["slot_guess"] for e in ev] == ["Q", "W"]
    assert [e["cost"] for e in ev] == [pytest.approx(50.0), pytest.approx(30.0)]


# -- level-up rejection -------------------------------------------------------

def test_fall_coinciding_with_resource_max_change_is_rejected():
    det = scl.SelfCastDetector(MANA_COSTS)
    # Max changes on the same poll the value falls (item sold / form swap):
    # never a cast.
    seq = [rd(1.0, 400.0, 500.0), rd(1.5, 340.0, 440.0), rd(2.0, 341.0, 440.0)]
    assert run(det, seq) == []


def test_level_up_adds_to_max_and_value_and_is_not_a_cast():
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(1.0, 400.0, 500.0), rd(1.5, 440.0, 540.0), rd(2.0, 441.0, 540.0)]
    assert run(det, seq) == []


def test_level_up_on_the_confirming_poll_still_confirms_a_real_cast():
    det = scl.SelfCastDetector(MANA_COSTS)
    # Cast 400->350, then a level-up adds 60 to both on the next poll. Raw
    # 411 is above the baseline; net of the max delta it is 351 and holds.
    seq = [rd(1.0, 400.0, 500.0), rd(1.5, 350.0, 500.0), rd(2.0, 411.0, 560.0)]
    ev = run(det, seq)
    assert len(ev) == 1 and ev[0]["slot_guess"] == "Q"


# -- gap span floor -----------------------------------------------------------

def test_fall_across_poll_gap_is_emitted_once_with_span_and_floor():
    det = scl.SelfCastDetector(MANA_COSTS)
    # 3 s gap: regen hid part of an 85 E. Observed fall 70 is a FLOOR.
    seq = [rd(1.0, 400.0), rd(4.0, 330.0), rd(4.5, 331.0), rd(5.0, 332.0)]
    ev = run(det, seq)
    assert len(ev) == 1
    e = ev[0]
    assert e["span"] == (1.0, 4.0)
    assert e["cost"] == pytest.approx(70.0)
    # Floor matching: Q rank1=50 is below the floor, so it cannot be it;
    # the smallest cost at or above the floor is E=85.
    assert e["slot_guess"] == "E"
    assert e["confidence"] <= scl.CONF_GAP


def test_gap_fall_larger_than_any_cost_has_no_slot_guess():
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(1.0, 400.0), rd(5.0, 200.0), rd(5.5, 201.0)]
    ev = run(det, seq)
    assert len(ev) == 1
    assert ev[0]["slot_guess"] is None
    assert ev[0]["span"] == (1.0, 5.0)


# -- slot matching by rank cost ----------------------------------------------

def test_slot_matching_is_scoped_by_current_rank():
    # Q at rank 3 costs 70. Rank 1 (50) must not be considered.
    det = scl.SelfCastDetector(MANA_COSTS)
    ranks = {"Q": 3, "W": 1, "E": 1, "R": 0}
    seq = [rd(1.0, 400.0, ranks=ranks), rd(1.5, 330.0, ranks=ranks),
           rd(2.0, 331.0, ranks=ranks)]
    ev = run(det, seq)
    assert ev[0]["slot_guess"] == "Q"
    assert ev[0]["cost"] == pytest.approx(70.0)


def test_unlearned_slot_is_never_guessed():
    # R has rank 0; a 100 fall cannot be R.
    det = scl.SelfCastDetector(MANA_COSTS)
    ev = run(det, [rd(1.0, 400.0), rd(1.5, 300.0), rd(2.0, 301.0)])
    assert len(ev) == 1
    assert ev[0]["slot_guess"] is None


def test_rank_one_cost_rejected_when_slot_is_rank_three():
    s, c, conf = scl.match_slot(50.0, {"Q": 3, "W": 1, "E": 1, "R": 0},
                                MANA_COSTS, "MANA")
    assert s is None


def test_ambiguous_equal_cost_slots_yield_no_guess():
    costs = dict(MANA_COSTS)
    costs["W"] = ("MANA", (50.0,) * 5)
    s, c, conf = scl.match_slot(50.0, RANKS, costs, "MANA")
    assert s is None
    assert conf == pytest.approx(scl.CONF_AMBIGUOUS)


def test_slot_with_other_resource_is_not_a_match():
    costs = dict(MANA_COSTS)
    costs["W"] = ("CURRENT_HEALTH", (30.0,) * 5)
    s, _c, _conf = scl.match_slot(30.0, RANKS, costs, "MANA")
    assert s is None


# -- regen / potion partial-cost tolerance -----------------------------------

def test_regen_partial_cost_within_tolerance_matches():
    # E costs 85; regen + potion hid 8 inside the poll: observed 77.
    s, c, conf = scl.match_slot(77.0, RANKS, MANA_COSTS, "MANA")
    assert s == "E"
    assert scl.CONF_PARTIAL <= conf < scl.CONF_EXACT


def test_partial_cost_beyond_tolerance_does_not_match():
    # Only E is learned. Hiding more than the documented tolerance of its
    # cost must not match.
    hidden = scl.partial_tolerance(85.0) + 5.0
    s, _c, _conf = scl.match_slot(85.0 - hidden, {"Q": 0, "W": 0, "E": 1, "R": 0},
                                  MANA_COSTS, "MANA")
    assert s is None


def test_partial_tolerance_is_documented_and_bounded():
    assert scl.partial_tolerance(100.0) == pytest.approx(
        max(scl.PARTIAL_ABS, scl.PARTIAL_REL * 100.0))
    assert scl.partial_tolerance(20.0) == pytest.approx(scl.PARTIAL_ABS)


def test_fall_slightly_above_cost_beyond_rounding_does_not_match():
    s, _c, _conf = scl.match_slot(50.0 + scl.OVER_TOL + 3.0,
                                  {"Q": 1, "W": 0, "E": 0, "R": 0}, MANA_COSTS, "MANA")
    assert s is None


# -- energy champion ----------------------------------------------------------

def test_energy_champion_works_the_same_way():
    det = scl.SelfCastDetector(ENERGY_COSTS)
    ranks = {"Q": 1, "W": 2, "E": 1, "R": 0}
    seq = [rd(1.0, 200.0, 200.0, "ENERGY", ranks),
           rd(1.5, 125.0, 200.0, "ENERGY", ranks),
           rd(2.0, 130.0, 200.0, "ENERGY", ranks),
           rd(2.5, 95.0, 200.0, "ENERGY", ranks),
           rd(3.0, 100.0, 200.0, "ENERGY", ranks)]
    ev = run(det, seq)
    assert [e["slot_guess"] for e in ev] == ["Q", "W"]


# -- excluded resource types -------------------------------------------------

@pytest.mark.parametrize("rtype", ["NONE", "RAGE", "FURY", "HEAT", "FLOW",
                                   "SHIELD", "BLOODWELL", "FEROCITY", "GNARFURY",
                                   "WIND", "BATTLEFURY", "DRAGONFURY",
                                   "CRIMSONRUSH", "OTHER", "", "SOMETHING_NEW"])
def test_non_mana_non_energy_resource_types_are_excluded(rtype):
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(1.0, 100.0, 100.0, rtype), rd(1.5, 0.0, 100.0, rtype),
           rd(2.0, 0.0, 100.0, rtype)]
    assert run(det, seq) == []
    assert det.excluded_reason is not None
    assert not scl.is_tracked_resource(rtype)


def test_tracked_resource_types_are_exactly_mana_and_energy():
    assert scl.TRACKED_RESOURCES == frozenset({"MANA", "ENERGY"})
    assert scl.is_tracked_resource("mana") and scl.is_tracked_resource("Energy")


def test_resource_type_change_mid_game_resets_without_emitting():
    det = scl.SelfCastDetector(MANA_COSTS)
    seq = [rd(1.0, 400.0), rd(1.5, 350.0), rd(2.0, 0.0, 100.0, "HEAT")]
    assert run(det, seq) == []


# -- snapshot parsing ---------------------------------------------------------

def _agd(t=100.0, value=300.0, maximum=500.0, rtype="MANA",
         ranks=(1, 1, 1, 0), champ="Synthchamp"):
    return {
        "activePlayer": {
            "riotIdGameName": "Player1",
            "summonerName": "Player1#TST",
            "abilities": {
                "Passive": {"displayName": "p"},
                "Q": {"abilityLevel": ranks[0]},
                "W": {"abilityLevel": ranks[1]},
                "E": {"abilityLevel": ranks[2]},
                "R": {"abilityLevel": ranks[3]},
            },
            "championStats": {"resourceValue": value, "resourceMax": maximum,
                              "resourceType": rtype},
        },
        "allPlayers": [{"riotIdGameName": "Player1", "championName": champ}],
        "gameData": {"gameTime": t},
    }


def test_reading_from_allgamedata_probes_the_live_keys():
    r = scl.reading_from_allgamedata(_agd(ranks=(2, 1, 0, 1)))
    assert r == scl.Reading(t=100.0, value=300.0, maximum=500.0, rtype="MANA",
                            ranks={"Q": 2, "W": 1, "E": 0, "R": 1})


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("activePlayer"),
    lambda d: d["activePlayer"].pop("championStats"),
    lambda d: d["activePlayer"]["championStats"].pop("resourceValue"),
    lambda d: d["activePlayer"]["championStats"].update(resourceMax=True),
    lambda d: d["gameData"].pop("gameTime"),
])
def test_reading_from_allgamedata_fails_soft(mutate):
    d = _agd()
    mutate(d)
    assert scl.reading_from_allgamedata(d) is None


def test_active_champion_name_from_allplayers():
    assert scl.active_champion_name(_agd(champ="Synthchamp")) == "Synthchamp"
    assert scl.active_champion_name({"activePlayer": {}}) is None


def test_detect_from_frames_offline():
    frames = [_agd(t=10.0, value=400.0), _agd(t=10.5, value=350.0),
              _agd(t=11.0, value=351.0), {"junk": 1}]
    ev = scl.detect_from_frames(frames, MANA_COSTS)
    assert [e["slot_guess"] for e in ev] == ["Q"]


def test_game_time_going_backwards_resets_state():
    det = scl.SelfCastDetector(MANA_COSTS)
    run(det, [rd(500.0, 400.0), rd(500.5, 350.0)])
    # New game starts: earlier game time must not confirm the stale candidate.
    assert det.feed(rd(1.0, 300.0)) == []
    assert det.feed(rd(1.5, 301.0)) == []
    # And the new game is tracked from its own baseline.
    ev = run(det, [rd(2.0, 251.0), rd(2.5, 252.0)])
    assert [e["slot_guess"] for e in ev] == ["Q"]


# -- DS champion data probe ---------------------------------------------------

def test_load_cost_table_reads_ds_per_rank_costs():
    table = scl.load_cost_table("Ahri")
    # The DS champion data is tracked, so an empty table is a defect, not an
    # absent environment capability (tests/test_skip_condition_hygiene.py).
    assert table, "DS champion_abilities.json did not load for Ahri"
    res, costs = table["Q"]
    assert res == "MANA"
    assert len(costs) == 5
    assert set(table) <= {"Q", "W", "E", "R"}


def test_load_cost_table_unknown_champion_is_empty():
    assert scl.load_cost_table("NotAChampionXyz") == {}


# -- offline validator vs Match-V5 -------------------------------------------

def _ev(slot, conf=0.9):
    return {"t": 0.0, "slot_guess": slot, "cost": 50.0, "confidence": conf,
            "span": None}


def test_per_slot_totals_counts_unattributed():
    ev = [_ev("Q"), _ev("Q"), _ev("W"), _ev(None)]
    assert scl.per_slot_totals(ev) == {"Q": 2, "W": 1, "E": 0, "R": 0,
                                       "unattributed": 1}


def test_per_slot_totals_min_confidence_filter():
    ev = [_ev("Q", 0.9), _ev("Q", 0.2)]
    assert scl.per_slot_totals(ev, min_confidence=0.5)["Q"] == 1


def test_validator_passes_within_tolerance_snake_case_columns():
    ev = [_ev("Q")] * 40 + [_ev("W")] * 10 + [_ev("E")] * 20 + [_ev("R")] * 5
    row = {"spell1_casts": 42, "spell2_casts": 11, "spell3_casts": 21,
           "spell4_casts": 5}
    v = scl.validate_against_match_v5(ev, row, MANA_COSTS)
    assert v["pass"] is True
    assert v["slots"]["Q"] == {"log": 40, "truth": 42, "diff": -2,
                               "allowed": scl.match_tolerance(42),
                               "within": True, "compared": True}


def test_validator_fails_outside_tolerance_camel_case_columns():
    ev = [_ev("Q")] * 10
    row = {"spell1Casts": 60, "spell2Casts": 0, "spell3Casts": 0,
           "spell4Casts": 0}
    v = scl.validate_against_match_v5(ev, row, MANA_COSTS)
    assert v["pass"] is False
    assert v["slots"]["Q"]["within"] is False


def test_validator_skips_costless_slots():
    # Energy table: R has no cost, so R casts are invisible to the log and
    # must not count against it.
    ev = [_ev("Q")] * 10
    row = {"spell1_casts": 10, "spell2_casts": 0, "spell3_casts": 0,
           "spell4_casts": 7}
    v = scl.validate_against_match_v5(ev, row, ENERGY_COSTS)
    assert v["slots"]["R"]["compared"] is False
    assert v["pass"] is True


def test_validator_missing_truth_is_not_a_pass():
    v = scl.validate_against_match_v5([_ev("Q")], {}, MANA_COSTS)
    assert v["pass"] is False


def test_match_tolerance_documented_formula():
    assert scl.match_tolerance(0) == scl.MATCH_ABS_TOL
    assert scl.match_tolerance(100) == max(
        scl.MATCH_ABS_TOL, int(round(scl.MATCH_REL_TOL * 100)))


# -- flag + listener ---------------------------------------------------------

def test_flag_default_off(monkeypatch):
    monkeypatch.delenv(scl.FLAG_ENV, raising=False)
    assert scl.is_enabled() is False
    assert scl.is_enabled({scl.FLAG_ENV: "0"}) is False
    assert scl.is_enabled({scl.FLAG_ENV: "garbage"}) is False
    for v in ("1", "true", "yes", "on", "TRUE"):
        assert scl.is_enabled({scl.FLAG_ENV: v}) is True


def test_install_if_enabled_respects_flag(monkeypatch):
    from core import liveclient_cache as lc
    added = []
    monkeypatch.setattr(lc, "add_listener", lambda fn: added.append(fn))
    monkeypatch.setattr(scl, "_LISTENER_INSTALLED", False)
    monkeypatch.delenv(scl.FLAG_ENV, raising=False)
    assert scl.install_if_enabled() is False
    assert added == []
    monkeypatch.setenv(scl.FLAG_ENV, "1")
    assert scl.install_if_enabled() is True
    assert added == [scl.on_snapshot]
    assert scl.install_if_enabled() is False  # idempotent


def test_liveclient_cache_start_calls_optional_taps(monkeypatch):
    from core import liveclient_cache as lc
    called = []
    monkeypatch.setattr(scl, "install_if_enabled", lambda: called.append(1))
    lc._install_optional_taps()
    assert called == [1]


def test_on_snapshot_live_adapter_emits_and_is_fail_soft(monkeypatch):
    scl.reset()
    monkeypatch.setattr(scl, "load_cost_table", lambda champ: MANA_COSTS)

    class _S:
        def __init__(self, data):
            self.data = data

    assert scl.on_snapshot(_S(None)) == 0
    assert scl.on_snapshot(object()) == 0
    scl.on_snapshot(_S(_agd(t=10.0, value=400.0)))
    scl.on_snapshot(_S(_agd(t=10.5, value=350.0)))
    assert scl.on_snapshot(_S(_agd(t=11.0, value=351.0))) == 1
    assert [e["slot_guess"] for e in scl.events()] == ["Q"]
    scl.reset()
    assert scl.events() == []
