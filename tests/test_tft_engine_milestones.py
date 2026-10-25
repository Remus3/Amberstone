"""TFT engine (slice TFT-13): milestone mining over the per-round store
(tft/engine/milestones.py).

The headline case is the operator's recorded Set 18 win of 2026-10-25
(QA_REPORT section 5): Lv6 3-1, Lv7 3-6, Lv8 4-2, Lv9 5-3; roll-downs at 5-3
and 5-5; the 4-2 level-up plus 5-cost buy (57 -> 12 gold, one reroll) is NOT a
roll-down; Lv4 was already reached when capture began, so it is censored, not
invented.
"""
from __future__ import annotations

import json
import random

import pytest

from tests.test_tft_engine_synthetic import (
    SYNTH_DOC,
    SYNTH_SET_ID,
    board_a,
    obs,
    refresh_rows,
    rerolls,
    round_row,
    seq_for,
    synth_history,
    timeline_record,
    worked_example_record,
)
from tft.engine import ENGINE_NAME, ENGINE_SCHEMA, comps, milestones


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


@pytest.fixture(scope="module")
def s18():
    data = comps.load_set_data(18)
    if not data.units:
        pytest.skip("Set 18 CommunityDragon extract not ingested")
    return data


# ------------------------------------------------------------ worked example

def test_worked_example_levels_and_rolldowns(s18):
    m = milestones.mine_match(worked_example_record(), s18)
    assert m["level_reached"] == {"5": "2-5", "6": "3-1", "7": "3-6", "8": "4-2", "9": "5-3"}
    assert m["censored_levels"] == [4]
    assert [r["label"] for r in m["rolldowns"]] == ["5-3", "5-5"]
    assert m["first_rolldown"] == "5-3"
    first, second = m["rolldowns"]
    assert (first["rerolls"], first["reroll_gold"], first["gold_start"], first["gold_end"]) == (13, 26, 64, 3)
    assert (second["rerolls"], second["reroll_gold"], second["gold_end"]) == (6, 12, 0)
    assert m["gold_at"] == {"3-2": 40, "4-1": 53}
    assert m["hp_at"] == {"4-1": 100}
    assert m["first_label"] == "2-2" and m["last_label"] == "6-1" and m["rounds"] == 28
    assert m["first_slam"] is None and m["slam_censored"] is False


def test_worked_example_42_spend_is_not_a_rolldown(s18):
    m = milestones.mine_match(worked_example_record(), s18)
    assert "4-2" not in {r["label"] for r in m["rolldowns"]}


def test_rolldown_arms_three_rerolls_or_twenty_gold(sd):
    def rec(shop):
        return timeline_record("r", 1, {"2-1": 4}, shop=shop)

    three = rerolls(seq_for("3-2"), 40, 3)                  # 3 rerolls, 6 gold
    two_cheap = rerolls(seq_for("3-2"), 40, 2)              # 2 rerolls, 4 gold
    two_dear = refresh_rows(seq_for("3-2"), [("reroll", 50, 40), ("reroll", 40, 28)])  # 2, 22 gold
    locked = refresh_rows(seq_for("3-2"), [("locked", 50, 50)] * 5)
    assert milestones.mine_match(rec(three), sd)["first_rolldown"] == "3-2"
    assert milestones.mine_match(rec(two_cheap), sd)["first_rolldown"] is None
    assert milestones.mine_match(rec(two_dear), sd)["first_rolldown"] == "3-2"
    assert milestones.mine_match(rec(locked), sd)["first_rolldown"] is None


# --------------------------------------------------------------- envelopes

def test_absent_low_confidence_and_llm_values_are_not_evidence(sd):
    rec = timeline_record("g", 1, {"2-1": 4, "3-1": 6, "4-2": 8})
    by_label = {r["label"]: r for r in rec["rounds"]}
    by_label["2-3"].update(level=9, level_conf=0.3, level_src="ocr")            # below the gate
    by_label["2-4"].update(level=9, level_conf=0.5, level_src="llm_fallback")   # never an oracle
    by_label["2-5"].update(level=None, level_conf=None, level_src="absent")
    by_label["3-2"].update(gold_start=33, gold_start_conf=0.4, gold_start_src="ocr")
    m = milestones.mine_match(rec, sd)
    assert m["level_reached"] == {"5": "3-1", "6": "3-1", "7": "4-2", "8": "4-2"}
    assert "2-3" not in m["level_at"] and "2-4" not in m["level_at"] and "2-5" not in m["level_at"]
    assert m["level_at"]["2-2"] == 4
    assert "3-2" not in m["gold_at"]


def test_an_isolated_level_spike_is_not_credited(sd):
    rec = timeline_record("s", 1, {"2-1": 4, "3-3": 6})
    by_label = {r["label"]: r for r in rec["rounds"]}
    by_label["3-1"].update(level=9, level_conf=0.95)   # misread, next round says 4
    m = milestones.mine_match(rec, sd)
    assert m["level_reached"] == {"5": "3-3", "6": "3-3"}


def test_a_record_without_rounds_mines_nothing(sd):
    rec = {"match_id": "mh", "set_id": SYNTH_SET_ID, "placement": 2, "final_board": board_a(0)}
    m = milestones.mine_match(rec, sd)
    assert m["rounds"] == 0 and m["level_reached"] == {} and m["rolldowns"] == []


# ------------------------------------------------------- slams / stars / opener

def _unit_history():
    return [
        obs("2-2", "U_Cora"), obs("2-2", "U_Bolt"),
        obs("2-3", "U_Cora"), obs("2-3", "U_Bolt", items=["C_Rod"]),
        obs("2-4", "U_Cora", 2), obs("2-4", "U_Bolt", items=["I_Rage"]), obs("2-4", "U_Kite", zone="bench"),
        obs("2-7", "U_Cora", 2), obs("2-7", "U_Bolt", 2, ["I_Rage"]), obs("2-7", "U_Kite"),
        obs("4-1", "U_Cora", 3), obs("4-1", "U_Gale", 1, ["I_Staff"], conf=0.2),   # below the gate
        obs("2-6", "U_Echo", phase="carousel", zone="carousel"),                     # carousel row
    ]


def test_first_slam_star_ups_and_opener(sd):
    rec = timeline_record("u", 2, {"2-1": 4}, units=_unit_history())
    m = milestones.mine_match(rec, sd)
    assert m["first_slam"] == {"label": "2-4", "item": "I_Rage", "unit": "U_Bolt"}
    assert m["slam_censored"] is False
    assert m["star_ups"] == {"U_Bolt": {"2": "2-7"}, "U_Cora": {"2": "2-4", "3": "4-1"},
                             "U_Kite": {}}
    assert m["opener"] == ["U_Bolt", "U_Cora", "U_Kite"]


def test_a_slam_already_on_the_first_observed_round_is_censored(sd):
    units = [obs("2-2", "U_Gale", 1, ["I_Edge"]), obs("2-3", "U_Gale", 1, ["I_Edge", "I_Rage"])]
    m = milestones.mine_match(timeline_record("c", 1, {"2-1": 4}, units=units), sd)
    assert m["first_slam"] is None and m["slam_censored"] is True
    assert m["star_ups"] == {"U_Gale": {}}


# -------------------------------------------------------------- aggregation

def _three_top4_and_one_bottom():
    m1 = timeline_record("t1", 1, {"2-1": 4, "2-5": 5, "3-1": 6, "3-6": 7, "4-2": 8},
                         gold={"3-2": 30, "4-1": 50}, hp={"4-1": 80},
                         shop=rerolls(seq_for("4-2"), 40, 10))
    m2 = timeline_record("t2", 3, {"2-1": 4, "2-5": 5, "3-2": 6, "3-6": 7, "4-1": 8},
                         gold={"3-2": 40, "4-1": 20}, hp={"4-1": 60},
                         shop=rerolls(seq_for("4-1"), 30, 5))
    m3 = timeline_record("t3", 2, {"2-1": 4, "2-3": 5, "2-5": 6, "3-2": 7, "4-5": 8},
                         gold={"3-2": 50, "4-1": 60}, hp={"4-1": 90})
    m4 = timeline_record("t4", 7, {"2-1": 4, "3-1": 5, "4-1": 6}, gold={"3-2": 2})
    return [m1, m2, m3, m4]


def test_aggregate_median_and_iqr_over_top4_games(sd):
    recs = _three_top4_and_one_bottom()
    agg = milestones.aggregate([milestones.mine_match(r, sd) for r in recs[:3]])
    assert agg["games"] == 3 and agg["games_with_rounds"] == 3
    assert agg["level_reached"]["6"] == {"median": "3-1", "q1": "2-5", "q3": "3-2", "n": 3}
    assert agg["level_reached"]["8"] == {"median": "4-2", "q1": "4-1", "q3": "4-5", "n": 3}
    assert agg["level_reached"]["4"]["n"] == 0  # censored in all three
    assert agg["level_curve"]["3-2"] == {"median": 6, "n": 3}
    assert agg["first_rolldown"] == {"median": "4-1", "q1": "4-1", "q3": "4-2", "n": 2, "share": 0.667}
    assert agg["rolldown_gold_end"]["median"] == 20.0
    assert agg["gold_at"]["3-2"] == {"median": 40.0, "q1": 30, "q3": 50, "iqr": 20, "n": 3}
    assert agg["hp_at"]["4-1"]["median"] == 80.0


def test_milestones_by_comp_uses_top4_games_only(sd):
    recs = _three_top4_and_one_bottom()
    cat = comps.build_catalogue(recs, sd)
    (comp,) = cat["comps"]
    out = milestones.milestones_by_comp(recs, cat, sd)
    assert out["engine"] == ENGINE_NAME and out["schema"] == ENGINE_SCHEMA
    assert out["top4_only"] is True
    assert out["comps"][comp["comp_id"]]["games"] == 3
    every = milestones.milestones_by_comp(recs, cat, sd, top4_only=False)
    assert every["comps"][comp["comp_id"]]["games"] == 4
    assert every["comps"][comp["comp_id"]]["gold_at"]["3-2"]["n"] == 4


def test_milestones_are_order_independent(sd):
    recs = _three_top4_and_one_bottom() + synth_history()
    cat = comps.build_catalogue(recs, sd)
    want = json.dumps(milestones.milestones_by_comp(recs, cat, sd), sort_keys=True)
    rng = random.Random(7)
    for _ in range(4):
        shuffled = list(recs)
        rng.shuffle(shuffled)
        cat2 = comps.build_catalogue(shuffled, sd)
        assert json.dumps(milestones.milestones_by_comp(shuffled, cat2, sd), sort_keys=True) == want


def test_compare_to_average_reads_earlier_same_later(sd):
    recs = _three_top4_and_one_bottom()
    agg = milestones.aggregate([milestones.mine_match(r, sd) for r in recs[:3]])
    this = milestones.mine_match(recs[3], sd)
    rows = {r["milestone"]: r for r in milestones.compare_to_average(this, agg)}
    assert rows["level_5"] == {"milestone": "level_5", "this_match": "3-1", "median": "2-5", "verdict": "later"}
    assert rows["level_6"]["verdict"] == "later"
    assert rows["gold_at_3-2"] == {"milestone": "gold_at_3-2", "this_match": 2, "median": 40.0, "verdict": "lower"}
    assert "level_8" not in rows  # never reached in this match


# ------------------------------------------------------------ store adapter

class _FakeStore:
    """The TFT-01 read API as specified (docs/TFT_PROGRAM.md section 2)."""

    def __init__(self):
        self.calls = []
        rec = worked_example_record("m1")
        self._rounds = rec["rounds"]
        self._shop = rec["shop_refreshes"]

    def list_matches(self, set_id=None, queue_kind=None, top4_only=False):
        self.calls.append(("list_matches", set_id, top4_only))
        return [{"match_id": "m1", "set_id": 18, "queue_kind": "normal", "placement": 1,
                 "placement_conf": 1.0, "placement_src": "lcu"}]

    def get_match(self, match_id):
        self.calls.append(("get_match", match_id))
        return {"match_id": match_id,
                "player": [{"player_key": "k-local", "is_local": 1}, {"player_key": "k-other", "is_local": 0}],
                "shop_refresh": self._shop,
                "unit_obs": [dict(obs("2-2", "DA_18_Yorick", first="2-2"), player_key="k-local"),
                             dict(obs("2-2", "DA_18_Leona", first="2-2"), player_key="k-other")],
                "gt_board": [{"player_key": "k-local", "source": "lcu_mh", "champion_api": "DA_18_Yorick",
                              "star": 2, "items_json": "[]", "cost": 1},
                             {"player_key": "k-other", "source": "lcu_mh", "champion_api": "DA_18_Leona",
                              "star": 2, "items_json": "[]", "cost": 1}]}

    def iter_rounds(self, match_id):
        self.calls.append(("iter_rounds", match_id))
        return iter(self._rounds)


def test_records_from_store_reads_the_spec_read_api():
    store = _FakeStore()
    (rec,) = milestones.records_from_store(store, set_id=18)
    assert ("list_matches", 18, False) in store.calls
    assert rec["match_id"] == "m1" and rec["placement"] == 1 and rec["set_id"] == 18
    assert len(rec["rounds"]) == 28 and rec["shop_refreshes"]
    assert [x["champion_api"] for x in rec["units"]] == ["DA_18_Yorick"]       # local player only
    assert [x["champion_api"] for x in rec["final_board"]] == ["DA_18_Yorick"]


def test_records_from_store_prefers_final_boards_from_ground_truth():
    store = _FakeStore()
    boards = {"m1": [{"champion_api": "DA_Draven18", "star": 2, "items": []}]}
    (rec,) = milestones.records_from_store(store, set_id=18, final_boards=boards)
    assert [x["champion_api"] for x in rec["final_board"]] == ["DA_Draven18"]
    as_list = [{"match_id": "m1", "board": boards["m1"]}]
    (rec2,) = milestones.records_from_store(store, set_id=18, final_boards=as_list)
    assert rec2["final_board"] == rec["final_board"]


def test_records_from_store_survives_a_broken_store():
    class Broken:
        def list_matches(self, **_kw):
            raise OSError("db locked")

    assert milestones.records_from_store(Broken(), set_id=18) == []


def test_round_row_helper_marks_absent_values():
    row = round_row(1, "2-1")
    assert row["level"] is None and row["level_src"] == "absent"
