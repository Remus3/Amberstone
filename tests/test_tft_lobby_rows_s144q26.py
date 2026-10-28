"""RM-1095: the lobby-row caller for tft/engine/comps.pair_stats.

RM-893 shipped pair_stats over plain lobby rows {placement, units, queue_kind},
but nothing built those rows from the per-round store: the engine may not read
a file (tests/test_tft_engine_guards.py), so the caller lives beside
final_boards in tft/rounds/ground_truth.py. lobby_rows() reads each match's
gt_board and gt_player, joins them by player_key and keeps ONE board source
per player, the most trusted present (GT_SOURCE_ORDER), so a player both
lcu_eog and lcu_mh carry is counted once. Post-game only (RM-892).

Every id, key and unit name below is hand-written and synthetic (RM-906).
ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import pytest

from tft.engine import comps
from tft.rounds import ground_truth as gt
from tft.rounds import store as st
from tft.rounds.store import RoundStore

SALT = b"s144q26-synthetic-salt-0123456789"
UNITS = ("TFT18_Ahri", "TFT18_Brand", "TFT18_Corki", "TFT18_Diana",
         "TFT18_Ekko", "TFT18_Fiora", "TFT18_Garen", "TFT18_Hecarim")


@pytest.fixture
def store(tmp_path):
    s = RoundStore.open(tmp_path / "tft" / "tft_rounds.db")
    try:
        yield s
    finally:
        s.close()


def _key(match_tag: str, seat: int) -> str:
    return st.player_key(f"s144q26-{match_tag}-{seat}", SALT)


def _board(key: str, apis) -> list:
    return [{"player_key": key, "champion_api": a, "star": 1, "items": [], "cost": 1} for a in apis]


def _boards_of(seat: int) -> tuple:
    """Seat n (1..8) holds units n-1 and n mod 8 of UNITS: every unit in two boards."""
    return (UNITS[seat - 1], UNITS[seat % 8])


def _put_match(store, match_id: str, queue_id: int, *, set_id: int = 18) -> dict:
    """Eight players, each placed (seat n = placement n) with an lcu_eog board.
    Returns {seat: player_key}."""
    tag = match_id[-3:]
    mid = store.begin_match({"match_id": match_id, "game_id": int(tag[1:]) + 100, "set_id": set_id,
                             "queue_id": queue_id, "started_at": 1_767_000_000.0 + int(tag[1:])})
    assert mid == match_id
    keys = {n: _key(tag, n) for n in range(1, 9)}
    boards = [row for n, k in keys.items() for row in _board(k, _boards_of(n))]
    players = [{"player_key": k, "placement": n} for n, k in keys.items()]
    assert store.attach_ground_truth(mid, "lcu_eog", boards, players)
    return keys


def _expected(queue_kind: str) -> list:
    return [{"placement": n, "units": list(_boards_of(n)), "queue_kind": queue_kind}
            for n in range(1, 9)]


def test_lobby_rows_are_one_plain_row_per_placed_player(store):
    _put_match(store, "20260101-000000-a01", 1100)
    assert store.flush()
    assert gt.lobby_rows(store) == _expected("ranked")


def test_a_player_two_sources_carry_is_counted_once_from_the_most_trusted(store):
    keys = _put_match(store, "20260101-000000-a02", 1090)
    # lcu_mh carries seat 1 again with a DIFFERENT board, and is the ONLY board
    # source for a ninth key placed nowhere (no gt_player placement: skipped).
    stray = _key("a02", 9)
    assert store.attach_ground_truth("20260101-000000-a02", "lcu_mh",
                                     _board(keys[1], ("TFT18_Zed",)) + _board(stray, ("TFT18_Yone",)),
                                     [{"player_key": keys[1], "placement": 1, "level": 9}])
    assert store.flush()
    rows = gt.lobby_rows(store)
    assert rows == _expected("normal")                       # 8 rows, seat 1 once, from lcu_eog
    assert "TFT18_Zed" not in comps.pair_stats(rows)["units"]


def test_an_lcu_mh_only_player_takes_the_lcu_mh_board(store):
    mid = "20260101-000000-a03"
    store.begin_match({"match_id": mid, "game_id": 4, "set_id": 18, "queue_id": 1100,
                       "started_at": 1_767_000_000.0})
    k1, k2 = _key("a03", 1), _key("a03", 2)
    assert store.attach_ground_truth(mid, "lcu_eog", _board(k1, ("TFT18_Ahri",)),
                                     [{"player_key": k1, "placement": 1}, {"player_key": k2, "placement": 2}])
    assert store.attach_ground_truth(mid, "lcu_mh", _board(k2, ("TFT18_Brand", "TFT18_Corki")), [])
    assert store.flush()
    assert gt.lobby_rows(store) == [
        {"placement": 1, "units": ["TFT18_Ahri"], "queue_kind": "ranked"},
        {"placement": 2, "units": ["TFT18_Brand", "TFT18_Corki"], "queue_kind": "ranked"}]


def test_a_player_without_a_board_or_without_a_placement_is_skipped(store):
    mid = "20260101-000000-a04"
    store.begin_match({"match_id": mid, "game_id": 5, "set_id": 18, "queue_id": 1100,
                       "started_at": 1_767_000_000.0})
    k1, k2, k3 = _key("a04", 1), _key("a04", 2), _key("a04", 3)
    # k2 is placed with no board; k3 has a board and a gt_player row with no placement
    assert store.attach_ground_truth(mid, "lcu_eog", _board(k1, ("TFT18_Ahri",)) + _board(k3, ("TFT18_Brand",)),
                                     [{"player_key": k1, "placement": 1}, {"player_key": k2, "placement": 2},
                                      {"player_key": k3, "level": 6}])
    assert store.flush()
    assert gt.lobby_rows(store) == [{"placement": 1, "units": ["TFT18_Ahri"], "queue_kind": "ranked"}]


def test_double_up_rows_carry_their_kind_and_pair_stats_keeps_them_apart(store):
    _put_match(store, "20260101-000000-a05", 1100)
    _put_match(store, "20260101-000000-a06", 1090)
    _put_match(store, "20260101-000000-a07", 1160)
    assert store.flush()
    rows = gt.lobby_rows(store)
    assert len(rows) == 24
    kinds = [r["queue_kind"] for r in rows]
    assert (kinds.count("ranked"), kinds.count("normal"), kinds.count("double_up")) == (8, 8, 8)
    solo = comps.pair_stats(rows)
    duo = comps.pair_stats(rows, queue_kinds="double_up")
    assert (solo["rows"], duo["rows"]) == (16, 8)
    # every unit sits in two boards per match: 4 solo placements, 2 Double Up ones
    assert {u["count"] for u in solo["units"].values()} == {4}
    assert {u["count"] for u in duo["units"].values()} == {2}
    assert gt.lobby_rows(store, queue_kind="double_up") == _expected("double_up")


def test_set_filter_and_order_are_deterministic(store):
    # a09 starts later, so list_matches (newest first) yields it first
    _put_match(store, "20260101-000000-a09", 1090, set_id=17)
    _put_match(store, "20260101-000000-a08", 1100)
    assert store.flush()
    assert gt.lobby_rows(store, set_id=17) == _expected("normal")
    assert gt.lobby_rows(store, set_id=18) == _expected("ranked")
    both = gt.lobby_rows(store)
    assert both == _expected("ranked") + _expected("normal")   # match_id order, then placement
    assert gt.lobby_rows(store, set_id=16) == []


def test_an_empty_store_gives_no_rows(store):
    assert gt.lobby_rows(store) == []
    assert comps.pair_stats(gt.lobby_rows(store))["rows"] == 0
