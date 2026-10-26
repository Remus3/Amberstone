"""True-audit (s134 lane 8) of tft/engine/milestones.py.

Findings pinned here, one test group each:
  F1 records_from_store claimed "fail-soft" but a truthy non-list field in a
     store row (rounds / players / unit_obs / shop_refresh / gt_board, the
     match list, final_boards or one board) raised TypeError and lost EVERY
     record, not just the bad one.
  F2 number_stats raised OverflowError on an int beyond float range and let
     NaN / inf poison the median and quartiles, so one junk gold value raised
     out of aggregate() and milestones_by_comp() - the whole engine model build.
  F3 compare_to_average rated a NaN gold / HP "same" as the median.
  F4 aggregate() raised on a mined row that was not a Mapping or lacked a key.
  F5 mine_match took a negative HP and an out-of-int64 gold / HP as a checkpoint.
  F6 _board_rows kept a negative star, split an itemNames string into one item
     per character, and let a null "star" hide "starLevel".
  F7 records_from_store attributed EVERY player's unit_obs and gt_board rows to
     the operator when the match had no local player (the real store keys every
     such row by player_key), took is_local "0" as local, and picked the first of
     two local players. The sibling dashboard/routes_tft.py _store_record already
     refuses: no local player = no unit attributed.
"""
from __future__ import annotations

import math

import pytest

from tests.test_tft_engine_synthetic import SYNTH_DOC, timeline_record
from tft.engine import comps, milestones

INT64_MAX = 2 ** 63 - 1


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


class _Store:
    """A TFT-01 read API double: one match, get_match returns `detail`."""

    def __init__(self, detail, matches=None):
        self.detail = detail
        self.matches = matches if matches is not None else [{"match_id": "m1", "placement": 1}]

    def list_matches(self, set_id=None, queue_kind=None, top4_only=False):
        return self.matches

    def get_match(self, match_id, *, rounds=True):
        return self.detail


_LOCAL = {"players": [{"player_key": "k-me", "is_local": 1}]}


# ------------------------------------------------------------------ F1

@pytest.mark.parametrize("field", ["rounds", "players", "player", "unit_obs", "units", "shop_refresh",
                                   "shop_refreshes", "gt_board"])
def test_f1_a_non_list_detail_field_keeps_the_record(field):
    recs = milestones.records_from_store(_Store(dict(_LOCAL, **{field: 5})))
    assert [r["match_id"] for r in recs] == ["m1"]


def test_f1_a_non_list_match_list_is_no_records():
    assert milestones.records_from_store(_Store({}, matches=5)) == []


@pytest.mark.parametrize("boards", [5, {"m1": 5}, {"m1": "abc"}, [{"match_id": "m1", "board": 5}]])
def test_f1_a_junk_final_board_falls_back_to_ground_truth(boards):
    detail = dict(_LOCAL, gt_board=[{"player_key": "k-me", "source": "lcu_mh", "champion_api": "A"}])
    (rec,) = milestones.records_from_store(_Store(detail), final_boards=boards)
    assert [u["champion_api"] for u in rec["final_board"]] == ["A"]


def test_f1_one_bad_match_does_not_lose_the_others():
    class Two(_Store):
        def get_match(self, match_id, *, rounds=True):
            return {"rounds": 7} if match_id == "bad" else _LOCAL

    store = Two(None, matches=[{"match_id": "bad", "placement": 2}, {"match_id": "good", "placement": 1}])
    assert sorted(r["match_id"] for r in milestones.records_from_store(store)) == ["bad", "good"]


# ------------------------------------------------------------------ F2

def test_f2_number_stats_drops_ints_beyond_int64_instead_of_raising():
    assert milestones.number_stats([10 ** 400, 10 ** 400 + 2])["n"] == 0
    assert milestones.number_stats([4, 10 ** 400, 6]) == {"median": 5.0, "q1": 4, "q3": 6, "iqr": 2, "n": 2}


def test_f2_number_stats_keeps_the_int64_edge():
    assert milestones.number_stats([INT64_MAX])["n"] == 1
    assert milestones.number_stats([INT64_MAX + 1])["n"] == 0


@pytest.mark.parametrize("junk", [float("nan"), float("inf"), float("-inf")])
def test_f2_number_stats_ignores_non_finite_values(junk):
    stats = milestones.number_stats([1, junk, 3, 4])
    assert stats == {"median": 3.0, "q1": 1, "q3": 4, "iqr": 3, "n": 3}


def test_f2_one_huge_gold_value_never_breaks_the_comp_build(sd):
    good = timeline_record("g", 1, {"2-1": 4}, gold={"3-2": 30, "4-1": 50})
    bad = timeline_record("b", 2, {"2-1": 4}, gold={"3-2": 10 ** 400, "4-1": 10 ** 400 + 2})
    cat = comps.build_catalogue([good, bad], sd)
    out = milestones.milestones_by_comp([good, bad], cat, sd)
    gold = [c["gold_at"]["3-2"] for c in out["comps"].values() if c["games"]]
    assert gold and all(g["n"] == 1 and g["median"] == 30.0 for g in gold)


# ------------------------------------------------------------------ F3

@pytest.mark.parametrize("junk", [float("nan"), float("inf")])
def test_f3_compare_skips_a_non_finite_value(junk):
    agg = {"gold_at": {"3-2": {"median": 30}}, "hp_at": {"4-1": {"median": junk}}}
    mined = {"gold_at": {"3-2": junk}, "hp_at": {"4-1": 60}}
    assert milestones.compare_to_average(mined, agg) == []


def test_f3_compare_still_rates_finite_values():
    rows = milestones.compare_to_average({"gold_at": {"3-2": 20}}, {"gold_at": {"3-2": {"median": 30.0}}})
    assert [(r["milestone"], r["verdict"]) for r in rows] == [("gold_at_3-2", "lower")]


# ------------------------------------------------------------------ F4

def test_f4_aggregate_skips_rows_that_are_not_mined_matches(sd):
    real = milestones.mine_match(timeline_record("a", 1, {"2-1": 4, "3-1": 6}), sd)
    junk = [None, 5, "x", {"rounds": 3}, {"rounds": 3, "level_at": None, "rolldowns": [None, 4],
                                           "has_unit_obs": True, "star_ups": None, "opener": 7},
            {"rounds": 3, "level_at": {"2-1": "x", "zz": 3, "3-1": float("nan")}, "rolldowns": []}]
    agg = milestones.aggregate([real] + junk)
    clean = milestones.aggregate([real])
    assert agg["level_reached"] == clean["level_reached"]
    assert agg["level_curve"] == clean["level_curve"]
    assert agg["games"] == 4             # the Mapping rows only


def test_f4_aggregate_tolerates_junk_key_units(sd):
    real = milestones.mine_match(timeline_record("a", 1, {"2-1": 4}), sd)
    agg = milestones.aggregate([real], key_units=["U_Cora", None, 5, "U_Cora"])
    assert sorted(agg["star_ups"]) == ["U_Cora"]


# ------------------------------------------------------------------ F5

def test_f5_negative_hp_is_not_a_checkpoint(sd):
    m = milestones.mine_match(timeline_record("h", 1, {"2-1": 4}, hp={"4-1": -40}), sd)
    assert m["hp_at"] == {}


def test_f5_out_of_int64_gold_and_hp_are_not_checkpoints(sd):
    rec = timeline_record("h", 1, {"2-1": 4}, gold={"3-2": INT64_MAX + 1, "4-1": 40}, hp={"4-1": 10 ** 30})
    m = milestones.mine_match(rec, sd)
    assert m["gold_at"] == {"4-1": 40} and m["hp_at"] == {}


def test_f5_zero_and_normal_hp_still_count(sd):
    assert milestones.mine_match(timeline_record("h", 1, {"2-1": 4}, hp={"4-1": 0}), sd)["hp_at"] == {"4-1": 0}
    assert milestones.mine_match(timeline_record("h", 1, {"2-1": 4}, hp={"4-1": 64}), sd)["hp_at"] == {"4-1": 64}


# ------------------------------------------------------------------ F6

def _board(row):
    (rec,) = milestones.records_from_store(_Store(_LOCAL), final_boards={"m1": [row]})
    return rec["final_board"]


def test_f6_board_star_is_at_least_one():
    assert _board({"champion_api": "X", "star": -3})[0]["star"] == 1
    assert _board({"champion_api": "X", "star": 0})[0]["star"] == 1


def test_f6_null_star_does_not_hide_star_level():
    assert _board({"champion_api": "X", "star": None, "starLevel": 3})[0]["star"] == 3


@pytest.mark.parametrize("names", ["abc", 5, {"a": 1}])
def test_f6_item_names_must_be_a_list(names):
    assert _board({"champion_api": "X", "itemNames": names})[0]["items"] == []


def test_f6_item_names_list_still_read():
    assert _board({"champion_api": "X", "itemNames": ["I_A", "I_B"]})[0]["items"] == ["I_A", "I_B"]


# ------------------------------------------------------------------ F7

_TWO_PLAYERS = {
    "unit_obs": [{"player_key": "k-me", "champion_api": "A"}, {"player_key": "k-them", "champion_api": "B"}],
    "gt_board": [{"player_key": "k-me", "source": "lcu_mh", "champion_api": "A"},
                 {"player_key": "k-them", "source": "lcu_mh", "champion_api": "B"}],
}


def _attributed(players):
    (rec,) = milestones.records_from_store(_Store(dict(_TWO_PLAYERS, players=players)))
    return [u["champion_api"] for u in rec["units"]], [u["champion_api"] for u in rec["final_board"]]


def test_f7_no_local_player_attributes_no_keyed_row():
    players = [{"player_key": "k-me", "is_local": 0}, {"player_key": "k-them", "is_local": 0}]
    assert _attributed(players) == ([], [])
    assert _attributed([]) == ([], [])


@pytest.mark.parametrize("flag", ["0", "false", "1", 1.0])
def test_f7_a_non_int_is_local_is_not_local(flag):
    players = [{"player_key": "k-me", "is_local": flag}, {"player_key": "k-them", "is_local": 0}]
    assert _attributed(players) == ([], [])


def test_f7_two_local_players_is_ambiguous():
    players = [{"player_key": "k-them", "is_local": 1}, {"player_key": "k-me", "is_local": True}]
    assert _attributed(players) == ([], [])


def test_f7_one_local_player_still_attributed():
    players = [{"player_key": "k-me", "is_local": True}, {"player_key": "k-them", "is_local": 0}]
    assert _attributed(players) == (["A"], ["A"])
    players = [{"player_key": "k-me", "is_local": 1}, {"player_key": "k-me", "is_local": 1}]
    assert _attributed(players) == (["A"], ["A"])


def test_f7_a_store_that_keys_no_row_by_player_keeps_its_rows():
    detail = {"unit_obs": [{"champion_api": "A"}], "gt_board": [{"source": "lcu_mh", "champion_api": "A"}]}
    (rec,) = milestones.records_from_store(_Store(detail))
    assert [u["champion_api"] for u in rec["units"]] == ["A"]
    assert [u["champion_api"] for u in rec["final_board"]] == ["A"]


def test_number_stats_median_is_finite_for_int64_pairs():
    stats = milestones.number_stats([INT64_MAX, INT64_MAX - 2])
    assert stats["n"] == 2 and math.isfinite(stats["median"])


# ------------------------------------------------------- F7 sibling (live path)

def test_f7_sibling_dashboard_gt_board_needs_the_local_player():
    """dashboard/routes_tft.py _store_record (the live engine build) took every
    player's gt_board rows as the operator's final board when no local player
    was known, though its own unit rule two lines up refuses that case."""
    from dashboard import routes_tft

    doc = {"gt_board": [{"player_key": "k-me", "source": "lcu_mh", "champion_api": "A"},
                        {"player_key": "k-them", "source": "lcu_mh", "champion_api": "B"}]}
    assert routes_tft._gt_local_board(doc, None) == []
    assert [r["champion_api"] for r in routes_tft._gt_local_board(doc, "k-me")] == ["A"]
