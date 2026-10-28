"""RM-893: the TFT engine's placement histogram, games floor and ordered-pair
delta (tft/engine/comps.py placement_hist / pair_delta / pair_stats, plus the
hist and insufficient keys on every catalogue comp; tft/engine/recommend.py
planner_choices skips a comp under the floor).

Before RM-893 a comp carried only avg_placement / top4_rate, the catalogue had
no games floor, and planner_choices offered a comp seen once at 1st as
"1 games, avg 1.0, top-4 100%". Every fixture here is hand-written (never a
captured Riot payload); the pair worked example is the 2026-07-30 teardown's
F1 cross-page arithmetic (BACKLOG RM-893 acceptance (b)).
"""
from __future__ import annotations

import builtins
import random

import pytest

from tests.test_tft_engine_synthetic import SYNTH_DOC, SYNTH_SET_ID, board_a, board_b, synth_history
from tft.engine import comps, recommend


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


def _hist_mean(hist):
    return round(sum((i + 1) * c for i, c in enumerate(hist)) / sum(hist), 2)


def _rec(mid, place, board, queue_kind="ranked"):
    return {"match_id": mid, "set_id": SYNTH_SET_ID, "queue_kind": queue_kind,
            "placement": place, "final_board": board}


# ---------------------------------------------------------- placement_hist

def test_placement_hist_counts_buckets_and_ignores_non_placements():
    out = comps.placement_hist([1, 2, 3, 6, 4, 0, 9, 4.5, "x", None, True])
    assert out == {"count": 5, "hist": [1, 1, 1, 1, 0, 1, 0, 0], "mean": 3.2, "top4": 4, "won": 1}
    assert comps.placement_hist([]) == {"count": 0, "hist": [0] * 8, "mean": None, "top4": 0, "won": 0}
    assert comps.placement_hist(None)["count"] == 0
    edge = comps.placement_hist([4, 5, 5, 8])                 # the top-4 edge: 4th counts, 5th does not
    assert edge["hist"] == [0, 0, 0, 1, 2, 0, 0, 1] and edge["top4"] == 1 and edge["won"] == 0


# --------------------------------------------------- acceptance (a): comps

def test_every_comp_hist_sums_to_its_placed_games_and_carries_its_mean(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    a, b = cat["comps"]
    assert a["hist"] == [1, 1, 1, 1, 0, 1, 0, 0]          # A placements 1, 2, 3, 6, 4
    assert b["hist"] == [0, 1, 0, 0, 1, 0, 1, 1]          # B placements 5, 7, 2, 8
    for comp in cat["comps"]:
        assert len(comp["hist"]) == 8 and sum(comp["hist"]) == comp["placed_games"]
        assert _hist_mean(comp["hist"]) == comp["avg_placement"]
        assert sum(comp["hist"][:4]) == comp["top4_games"]
    assert cat["min_games"] == comps.MIN_GAMES


def test_an_unplaced_game_counts_as_a_game_but_not_in_the_hist(sd):
    rows = [_rec(f"m-{i}", p, board_a(i)) for i, p in enumerate([1, 2, None, 3])]
    (comp,) = comps.build_catalogue(rows, sd)["comps"]
    assert comp["games"] == 4 and comp["placed_games"] == 3
    assert comp["hist"] == [1, 1, 1, 0, 0, 0, 0, 0]


# ------------------------------------------- acceptance (d): queue kinds

def test_an_excluded_queue_kind_never_mixes_into_a_solo_comp_hist(sd):
    base = comps.build_catalogue(synth_history(), sd)["comps"][0]
    extra = [_rec(f"m-du{i}", 8, board_a(i), "double_up") for i in range(4)]
    extra += [_rec(f"m-hr{i}", 8, board_a(i), "hyper_roll") for i in range(4)]
    with_du = comps.build_catalogue(synth_history() + extra, sd)["comps"][0]
    assert with_du["comp_id"] == base["comp_id"]
    # neither synth_history's own m-du (Double Up, 1st) nor the eight 8ths above is counted
    assert with_du["hist"] == base["hist"] == [1, 1, 1, 1, 0, 1, 0, 0]


# -------------------------------------------- acceptance (c): games floor

def test_a_comp_under_the_floor_is_flagged_and_never_ranked_above_a_sufficient_one(sd):
    # A: two games, both 1st (two top-4 games, so it would sort FIRST by top-4 count);
    # B: four games 5, 7, 2, 8 (one top-4 game).
    rows = [_rec("m-a0", 1, board_a(0)), _rec("m-a1", 1, board_a(1))]
    rows += [_rec(f"m-b{i}", p, board_b(i)) for i, p in enumerate([5, 7, 2, 8])]
    cat = comps.build_catalogue(rows, sd)
    first, last = cat["comps"]
    assert first["match_ids"][0].startswith("m-b") and first["insufficient"] is False
    assert last["match_ids"] == ["m-a0", "m-a1"] and last["insufficient"] is True
    assert last["top4_games"] == 2 > first["top4_games"] == 1
    assert last["hist"] == [2, 0, 0, 0, 0, 0, 0, 0]       # flagged, its numbers still shown


def test_the_floor_counts_placed_games_not_games(sd):
    rows = [_rec(f"m-{i}", p, board_a(i)) for i, p in enumerate([1, None, None, None])]
    (comp,) = comps.build_catalogue(rows, sd)["comps"]
    assert comp["games"] == 4 and comp["placed_games"] == 1 < comps.MIN_GAMES
    assert comp["insufficient"] is True


def test_planner_never_offers_a_comp_under_the_floor(sd):
    # A single 1st-place game used to be offered as "1 games, avg 1.0, top-4 100%".
    one = comps.build_catalogue([_rec("m-a0", 1, board_a(0))], sd)
    assert one["comps"][0]["insufficient"] is True
    assert recommend.planner_choices(one, None, sd)["choices"] == []

    rows = [_rec("m-a0", 1, board_a(0)), _rec("m-a1", 1, board_a(1))]
    rows += [_rec(f"m-b{i}", p, board_b(i)) for i, p in enumerate([5, 7, 2, 8])]
    cat = comps.build_catalogue(rows, sd)
    out = recommend.planner_choices(cat, None, sd)
    assert [c["comp_id"] for c in out["choices"]] == [cat["comps"][0]["comp_id"]]
    assert all(c["comp_id"] != cat["comps"][1]["comp_id"] for c in out["choices"])


def test_planner_reads_the_floor_from_placed_games_when_a_row_lies_or_lacks_the_flag(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    good = cat["comps"][0]
    lying = dict(good, comp_id="c-lying", insufficient=False, placed_games=1)
    no_flag = {k: v for k, v in good.items() if k != "insufficient"}
    junk_count = dict(good, comp_id="c-junk", insufficient=None, placed_games="many")
    out = recommend.planner_choices(dict(cat, comps=[lying, no_flag, junk_count]), None, sd)
    assert [c["comp_id"] for c in out["choices"]] == [good["comp_id"]]


def test_nearest_comps_never_break_a_tie_on_an_under_floor_top4_rate(sd):
    # Two comps the board fits equally well: the under-floor one has the better
    # (one-game) top-4 rate and the smaller id, so before RM-893 it was listed first.
    shape = {"core": [{"api": "U_Gale"}], "flex": [], "signature": [], "item_freq": {}}
    thin = dict(shape, comp_id="c-a", games=1, placed_games=1, top4_rate=1.0, insufficient=True)
    seen = dict(shape, comp_id="c-b", games=6, placed_games=6, top4_rate=0.5, insufficient=False)
    cat = {"comps": [thin, seen]}
    rows = recommend.nearest_comps({"board": [{"champion_api": "U_Gale", "star": 1}]}, cat, sd)
    assert [r["comp_id"] for r in rows] == ["c-b", "c-a"]
    assert rows[0]["score"] == rows[1]["score"]
    assert [r["insufficient"] for r in rows] == [False, True]
    assert rows[1]["top4_rate"] == 1.0                      # still shown, never ranked on


# ------------------------------------------- acceptance (b): pair deltas

def test_pair_delta_reproduces_the_teardown_worked_example():
    # self base 4.64, partner base 4.88, pair place 5.01 -> delta 0.13 / delta2 0.37
    assert comps.pair_delta(5.01, 4.64, 4.88) == (0.13, 0.37)
    # roles swapped, the other page's sample (pair place 5.00) -> delta 0.36 / delta2 0.12
    assert comps.pair_delta(5.00, 4.88, 4.64) == (0.36, 0.12)
    assert comps.pair_delta(None, 4.0, 4.0) == (None, None)
    assert comps.pair_delta(4.0, float("nan"), 4.0) == (None, None)


def _lobby():
    """Six solo lobby rows (one per player board), worked by hand below."""
    return [
        {"placement": 1, "units": ["U_X", "U_Y"]},
        {"placement": 2, "units": ["U_X", "U_Y", "U_X"]},   # a duplicate unit counts once
        {"placement": 3, "units": ["U_X", "U_Y", "U_Z"]},
        {"placement": 6, "units": ["U_X"]},
        {"placement": 8, "units": ["U_Y"]},
        {"placement": 4, "units": ["U_Z"]},
    ]


def test_pair_stats_on_a_hand_worked_lobby():
    out = comps.pair_stats(_lobby())
    assert out["rows"] == 6 and out["min_count"] == comps.MIN_GAMES
    units = out["units"]
    # X: 1, 2, 3, 6 -> 3.0; Y: 1, 2, 3, 8 -> 3.5; Z: 3, 4 -> 3.5 (two rows, under the floor)
    assert units["U_X"] == {"count": 4, "hist": [1, 1, 1, 0, 0, 1, 0, 0], "mean": 3.0, "top4": 3,
                            "won": 1, "insufficient": False}
    assert units["U_Y"]["mean"] == 3.5 and units["U_Y"]["insufficient"] is False
    assert units["U_Z"]["count"] == 2 and units["U_Z"]["insufficient"] is True
    for row in units.values():
        assert sum(row["hist"]) == row["count"] and _hist_mean(row["hist"]) == row["mean"]

    pairs = {(p["self"], p["partner"]): p for p in out["pairs"]}
    # X with Y: rows 1, 2, 3 -> place 2.0. delta is against the PARTNER's base,
    # delta2 against the unit's OWN, so the two directions differ.
    xy, yx = pairs[("U_X", "U_Y")], pairs[("U_Y", "U_X")]
    assert (xy["count"], xy["place"], xy["delta"], xy["delta2"]) == (3, 2.0, -1.5, -1.0)
    assert (yx["count"], yx["place"], yx["delta"], yx["delta2"]) == (3, 2.0, -1.0, -1.5)
    assert xy["rank"] == 1 and yx["rank"] == 2
    assert xy["insufficient"] is False and yx["insufficient"] is False

    # X with Z and Y with Z co-occur once: flagged, never ranked, listed after every ranked pair.
    for key in (("U_X", "U_Z"), ("U_Z", "U_X"), ("U_Y", "U_Z"), ("U_Z", "U_Y")):
        assert pairs[key]["count"] == 1 and pairs[key]["insufficient"] is True
        assert pairs[key]["rank"] is None
    ranks = [p["rank"] for p in out["pairs"]]
    assert ranks == [1, 2, None, None, None, None]
    assert len(out["pairs"]) == 6


def test_pair_stats_skip_junk_rows_and_are_order_independent():
    junk = [None, "row", {"placement": 9, "units": ["U_X", "U_Y"]},
            {"placement": None, "units": ["U_X", "U_Y"]}, {"placement": 2, "units": "U_X"},
            {"placement": 2, "units": [None, 7, ""]}, {"placement": 2.5, "units": ["U_X"]}]
    want = comps.pair_stats(_lobby())
    rows = _lobby() + junk
    random.Random(893).shuffle(rows)
    assert comps.pair_stats(rows) == want
    assert comps.pair_stats(None) == comps.pair_stats([]) == {"rows": 0, "min_count": comps.MIN_GAMES,
                                                             "units": {}, "pairs": []}


def test_pair_stats_min_count_is_a_parameter():
    out = comps.pair_stats(_lobby(), min_count=1)
    assert all(p["rank"] is not None for p in out["pairs"])
    assert out["units"]["U_Z"]["insufficient"] is False
    assert comps.pair_stats(_lobby(), min_count=0) == comps.pair_stats(_lobby(), min_count=-5) == out
    default = comps.pair_stats(_lobby())
    for junk in ("junk", "1", 1.0, 2.5, True, None, float("nan")):   # only a real int sets the floor
        assert comps.pair_stats(_lobby(), min_count=junk) == default, junk


def test_double_up_lobbies_aggregate_separately_from_solo_lobbies():
    solo = _lobby()
    du = [{"placement": 8, "units": ["U_X", "U_Y"], "queue_kind": "double_up"} for _ in range(3)]
    mixed = solo + du
    assert comps.pair_stats(mixed) == comps.pair_stats(solo)        # solo by default
    only_du = comps.pair_stats(mixed, queue_kinds={"double_up"})
    assert only_du["rows"] == 3
    assert only_du["units"]["U_X"]["hist"] == [0, 0, 0, 0, 0, 0, 0, 3]
    (xy,) = [p for p in only_du["pairs"] if (p["self"], p["partner"]) == ("U_X", "U_Y")]
    assert (xy["count"], xy["place"], xy["delta"], xy["delta2"]) == (3, 8.0, 0.0, 0.0)
    for spelled in ("double_up", ["double_up"], ("double_up",), frozenset({"double_up"}),
                    (k for k in ["double_up"]), {"double_up": 1}.keys()):
        assert comps.pair_stats(mixed, queue_kinds=spelled) == only_du
    for nothing in ([], 7):                                             # no kind asked, no row
        assert comps.pair_stats(mixed, queue_kinds=nothing)["rows"] == 0


# ------------------------------------------- acceptance (e): pure functions

def test_placement_stats_do_no_file_io(monkeypatch, sd):
    def boom(*_a, **_k):
        raise AssertionError("RM-893 placement stats must do no file I/O")

    monkeypatch.setattr(builtins, "open", boom)
    comps.placement_hist([1, 2, 3])
    comps.pair_stats(_lobby())
    comps.build_catalogue(synth_history(), sd)
