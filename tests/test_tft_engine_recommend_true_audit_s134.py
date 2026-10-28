"""s134 true-audit (lane 8, cycle 13): tft/engine/recommend.py.

The live state reaches recommend() from the round store (dashboard/routes_tft.py
_live_state): the round label is free text up to 16 characters and the level
is whatever envelope a source wrote. The per-comp aggregates and catalogue rows
are read the junk-tolerant way everywhere else in the module; these tests pin
the sites that were not:

  F1 level_advice looked the top-4 curve up under the RAW label, so a label
     parse_label accepts (" 3-2", "3-02") missed data that exists.
  F2 level_advice took an impossible level (0, negative, 12+) as a reading and
     answered "behind" / "ahead" with "Lv-4" in the message. Level 11 is real
     (tft/tft_data.py TIER_ODDS has the row), and shop odds keep reading the
     odds bundle's own levels.
  F3 level_advice raised on an aggregate row without a numeric median or with
     a level / rolldown label that does not parse.
  F4 _milestone_line raised on a non-numeric or non-finite gold median, which
     takes planner_choices (and so the whole engine model build) down.
  F5 nearest_comps / item_slams sort keys raised on a non-numeric top4_rate or
     item count.
  F6 _summary printed "avg nan" / "avg inf" for a non-finite placement.
"""
from __future__ import annotations

import math

import pytest

from tests.test_tft_engine_recommend import _consts, _history
from tests.test_tft_engine_synthetic import SYNTH_DOC, u
from tft import tft_roll_odds
from tft.engine import comps, milestones, recommend


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


@pytest.fixture(scope="module")
def built(sd):
    recs = _history()
    cat = comps.build_catalogue(recs, sd)
    ms = milestones.milestones_by_comp(recs, cat, sd)
    comp_a = cat["comps"][0]
    assert comp_a["label"] == "Mage / Blade - Gale"
    return cat, ms, comp_a


def _agg(built):
    cat, ms, comp_a = built
    return ms["comps"][comp_a["comp_id"]]


# ------------------------------------------------------------------ F1

@pytest.mark.parametrize("label", ["3-02", " 3-2", "3-2 ", "03-2"])
def test_f1_level_advice_reads_the_curve_under_the_canonical_label(built, label):
    agg = _agg(built)
    assert agg["level_curve"]["3-2"]["median"] == 6
    out = recommend.level_advice({"label": label, "level": 6}, agg)
    assert out["status"] == "on_curve"
    assert out["message"] == "Lv6 at 3-2; your top-4 median is Lv6 at 3-2"


def test_f1_unknown_round_message_names_the_canonical_label(built):
    out = recommend.level_advice({"label": "06-06", "level": 9}, _agg(built))
    assert out["status"] == "unknown"
    assert out["message"] == "No top-4 level data at 6-6 yet"


# ------------------------------------------------------------------ F2

@pytest.mark.parametrize("level", [0, -4, 12, 99, 10 ** 30])
def test_f2_impossible_level_is_not_a_reading(built, level):
    out = recommend.level_advice({"label": "3-2", "level": level}, _agg(built))
    assert out["status"] == "unknown"
    assert out["next"] is None
    assert f"Lv{level}" not in out["message"]


@pytest.mark.parametrize("level,status", [(1, "behind"), (11, "ahead")])
def test_f2_level_bounds_are_inclusive(built, level, status):
    out = recommend.level_advice({"label": "3-2", "level": level}, _agg(built))
    assert out["status"] == status
    assert out["message"].startswith(f"Lv{level} at 3-2")


def test_f2_level_domain_is_the_tft_one():
    assert (recommend.LEVEL_MIN, recommend.LEVEL_MAX) == (1, 11)
    assert recommend.LEVEL_MAX >= max(milestones.LEVELS)
    # The default odds bundle is the measured level domain: advice must never
    # call a level the odds table knows a misread.
    assert recommend.LEVEL_MAX >= max(tft_roll_odds.default_constants().tier_odds)


def test_f2_level_11_advice_reads_the_curve():
    out = recommend.level_advice({"label": "5-1", "level": 11}, {"level_curve": {"5-1": {"median": 10, "n": 5}}})
    assert out["status"] == "ahead"
    assert out["message"] == "Lv11 at 5-1; your top-4 median is Lv10 at 5-1"


def test_f2_shop_odds_read_the_odds_bundle_levels_not_the_advice_bound(sd, built):
    _cat, _ms, comp_a = built
    base = _consts()
    level = recommend.LEVEL_MAX + 1
    consts = tft_roll_odds.SetConstants(
        source="test", set_number=base.set_number, verified_in_client=True,
        tier_odds={level: {1: 0.2, 2: 0.2, 3: 0.2, 4: 0.2, 5: 0.2}},
        pool_sizes=base.pool_sizes, units_per_cost=base.units_per_cost)
    out = recommend.shop_picks({"level": level, "board": [u("U_Bolt")]}, comp_a, sd, consts=consts)
    assert out["wanted"]
    assert all(w["p_shop"] is not None for w in out["wanted"] if w["cost"] is not None)


# ------------------------------------------------------------------ F3

@pytest.mark.parametrize("curve_row", [{"median": None, "n": 1}, {"n": 1}, {"median": "six"},
                                       {"median": True}, {"median": float("nan")}, "6", None, 6])
def test_f3_curve_row_without_a_numeric_median_is_no_data(curve_row):
    out = recommend.level_advice({"label": "3-2", "level": 6}, {"level_curve": {"3-2": curve_row}})
    assert out["status"] == "unknown"
    assert out["message"] == "No top-4 level data at 3-2 yet"


def test_f3_unparseable_level_reached_median_is_skipped(built):
    agg = dict(_agg(built), level_reached={"7": {"median": "zz", "n": 3}, "8": {"median": "4-2", "n": 3}})
    out = recommend.level_advice({"label": "3-2", "level": 6}, agg)
    assert out["next"] == {"level": 8, "label": "4-2", "games": 3, "insufficient": False}


@pytest.mark.parametrize("bad", [{"7": "3-6"}, {"7": ["3-6"]}, ["x"], "x", {"7": {"median": 7}}])
def test_f3_junk_level_reached_never_raises(built, bad):
    agg = dict(_agg(built), level_reached=bad)
    out = recommend.level_advice({"label": "3-2", "level": 6}, agg)
    assert out["next"] is None
    assert out["status"] == "on_curve"


@pytest.mark.parametrize("roll", [{"n": 2, "q1": None, "q3": "4-1", "median": "4-1"},
                                  {"n": 2, "q1": "3-1", "q3": "zz", "median": "4-1"},
                                  {"n": 2, "q1": "3-1", "q3": "4-1"},
                                  {"n": 2, "q1": "3-1", "q3": "4-1", "median": 41},
                                  {"n": "2", "q1": "3-1", "q3": "4-1", "median": "4-1"},
                                  ["4-1"], "4-1"])
def test_f3_malformed_first_rolldown_gives_no_roll(roll):
    out = recommend.level_advice({"label": "3-2", "level": 6}, {"first_rolldown": roll})
    assert out["roll"] is None


def test_f3_roll_window_still_answers_on_good_rows(built):
    out = recommend.level_advice({"label": "4-1", "level": 8}, _agg(built))
    assert out["roll"] is not None and out["roll"]["label"] == _agg(built)["first_rolldown"]["median"]


@pytest.mark.parametrize("key", ["level_curve", "level_reached", "first_rolldown", "rolldown_gold_end"])
@pytest.mark.parametrize("junk", [[], "x", 3, [{"median": 1}]])
def test_f3_any_non_mapping_section_never_raises(built, key, junk):
    agg = dict(_agg(built), **{key: junk})
    out = recommend.level_advice({"label": "4-1", "level": 8}, agg)
    assert out["status"] in ("behind", "ahead", "on_curve", "unknown", "insufficient")


def test_f3_recommend_survives_a_junk_aggregate(sd, built):
    cat, ms, comp_a = built
    junk = {"comps": {comp_a["comp_id"]: {"level_curve": {"3-2": {"n": 1}},
                                          "first_rolldown": {"n": 1, "q1": None, "q3": None}}}}
    out = recommend.recommend({"label": "3-2", "level": 6, "board": [u("U_Bolt")],
                               "target_comp_id": comp_a["comp_id"]}, cat, junk, sd, consts=_consts())
    assert out["level"]["status"] == "unknown"
    assert out["target"]["comp_id"] == comp_a["comp_id"]


# ------------------------------------------------------------------ F4

@pytest.mark.parametrize("gold", ["x", float("nan"), float("inf"), True, [3], {"g": 1}])
def test_f4_milestone_line_drops_a_bad_gold_median(gold):
    line = recommend._milestone_line({"first_rolldown": {"median": "4-1", "n": 3},
                                      "rolldown_gold_end": {"median": gold, "n": 3}})
    assert line == "roll at 4-1"


def test_f4_milestone_line_keeps_a_good_gold_median():
    line = recommend._milestone_line({"first_rolldown": {"median": "4-1", "n": 3},
                                      "rolldown_gold_end": {"median": 12.6, "n": 3}})
    assert line == "roll at 4-1 to ~13g"


@pytest.mark.parametrize("junk", [{"level_reached": ["x"]}, {"level_reached": {"6": "3-2"}},
                                  {"first_rolldown": ["4-1"]}, {"first_slam": "4-1"},
                                  {"rolldown_gold_end": 12, "first_rolldown": {"median": "4-1", "n": 3}},
                                  {"first_rolldown": {"median": 41, "n": 3}}, {"first_slam": {"median": ["x"], "n": 3}}])
def test_f4_milestone_line_never_raises_on_junk_sections(junk):
    line = recommend._milestone_line(junk)
    assert line is None or isinstance(line, str)


def test_f4_planner_choices_survive_a_non_finite_gold_median(sd, built):
    cat, ms, comp_a = built
    # n = 3 (MIN_GAMES) on both rows so the RM-1098 floor lets the roll through and the gold reaches _number.
    bad = {"comps": {cid: dict(agg, first_rolldown=dict(agg["first_rolldown"], n=3),
                               rolldown_gold_end={"median": float("nan"), "n": 3})
                     for cid, agg in ms["comps"].items()}, "top4_only": True}
    out = recommend.planner_choices(cat, bad, sd)
    assert out["choices"]
    assert any("roll at" in line for choice in out["choices"] for line in choice["digest"])
    for choice in out["choices"]:
        assert all("nan" not in line for line in choice["digest"])


# ------------------------------------------------------------------ F5

def test_f5_nearest_comps_ranks_a_non_numeric_top4_rate_as_zero(sd, built):
    cat, _ms, comp_a = built
    other = cat["comps"][1]
    junk_cat = {"comps": [dict(comp_a, top4_rate="z"), dict(other, top4_rate=0.5)]}
    rows = recommend.nearest_comps({"board": [u("U_Bolt"), u("U_Cora")]}, junk_cat, sd, limit=5)
    assert [r["comp_id"] for r in rows][0] == comp_a["comp_id"]
    assert all(isinstance(r["score"], float) for r in rows)


@pytest.mark.parametrize("rate", [float("nan"), True, None, [1]])
def test_f5_nearest_comps_never_raises_on_junk_top4_rate(sd, built, rate):
    cat, _ms, comp_a = built
    rows = recommend.nearest_comps({"board": [u("U_Bolt")]}, {"comps": [dict(c, top4_rate=rate) for c in cat["comps"]]}, sd)
    assert rows


def test_f5_item_slams_count_a_junk_item_frequency_as_zero(sd, built):
    _cat, _ms, comp_a = built
    comp = dict(comp_a, item_freq={"I_Plate": "x", "I_Staff": 2},
                carry={"api": "U_Bolt", "item_freq": {"I_Plate": [1], "I_Staff": float("nan")}})
    rows = recommend.item_slams(["C_Vest", "C_Vest", "C_Rod", "C_Rod"], comp, sd)
    by_item = {r["item"]: r for r in rows}
    assert by_item["I_Plate"]["comp_games"] == 0 and by_item["I_Plate"]["carry_games"] == 0
    assert by_item["I_Staff"]["carry_games"] == 0 and by_item["I_Staff"]["comp_games"] == 2
    assert rows[0]["item"] == "I_Staff"


def test_f5_item_slams_keep_digit_string_counts(sd, built):
    _cat, _ms, comp_a = built
    comp = dict(comp_a, item_freq={"I_Plate": "3"}, carry={})
    rows = recommend.item_slams(["C_Vest", "C_Vest"], comp, sd)
    assert rows[0]["item"] == "I_Plate" and rows[0]["comp_games"] == 3


# ------------------------------------------------------------------ F6

@pytest.mark.parametrize("avg", [float("nan"), float("inf"), -math.inf])
def test_f6_summary_non_finite_placement_is_no_placement(avg):
    assert recommend._summary({"games": 4, "avg_placement": avg, "top4_rate": 0.5}) == "4 games, no placement yet"


@pytest.mark.parametrize("rate", [float("nan"), float("inf")])
def test_f6_summary_non_finite_rate_reads_zero(rate):
    assert recommend._summary({"games": 4, "avg_placement": 3.5, "top4_rate": rate}) == "4 games, avg 3.5, top-4 0%"


def test_f6_summary_good_row_unchanged():
    assert recommend._summary({"games": 4, "avg_placement": 3.25, "top4_rate": 0.75}) == "4 games, avg 3.2, top-4 75%"


def test_f6_summary_float_overflowing_placement_is_no_placement():
    assert recommend._summary({"games": 2, "avg_placement": 10 ** 400}) == "2 games, no placement yet"


# ------------------------------------------------------- shared readers

@pytest.mark.parametrize("gold", ["x", float("nan"), True, [12]])
def test_roll_advice_to_gold_is_a_number_or_none(built, gold):
    agg = dict(_agg(built), rolldown_gold_end={"median": gold})
    out = recommend.level_advice({"label": "4-1", "level": 8}, agg)
    assert out["roll"] is not None and out["roll"]["to_gold"] is None


def test_item_slams_negative_count_reads_zero(sd, built):
    _cat, _ms, comp_a = built
    rows = recommend.item_slams(["C_Vest", "C_Vest"], dict(comp_a, item_freq={"I_Plate": -3}, carry={}), sd)
    assert rows[0]["comp_games"] == 0


# Every row carries n = 3 (MIN_GAMES) so the RM-1098 floor passes and the label parse is what drops it.
@pytest.mark.parametrize("agg", [{"first_rolldown": {"median": "zz", "n": 3}}, {"first_rolldown": {"median": 41, "n": 3}},
                                 {"level_reached": {"6": {"median": "late", "n": 3}}},
                                 {"first_slam": {"median": 7, "n": 3}}, {"first_slam": {"median": "4-x", "n": 3}}])
def test_f4_milestone_line_prints_only_parseable_labels(agg):
    assert recommend._milestone_line(agg) is None


def test_f4_milestone_line_canonicalises_labels():
    agg = {"level_reached": {"6": {"median": "3-02", "n": 3}}, "first_slam": {"median": " 2-5", "n": 3}}
    assert recommend._milestone_line(agg) == "Lv6 by 3-2, first slam 2-5"
