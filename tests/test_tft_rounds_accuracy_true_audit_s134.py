"""s134 true-audit (lane 8, cycle 16): tft/rounds/accuracy.py.

accuracy.py is oracle B (docs/TFT_PROGRAM.md section 3.4): it grades the
store's last resolved round against the post-match ground truth and writes the
per-field accuracy rows the SHOW / MARK / HIDE gates read. The spec defines
coverage as "rounds with a value at or above the gate", and the module header
says "A row below `min_conf` counts as not answered". Each finding below was
measured at HEAD before the fix:

  F1 a board row below min_conf was dropped from the board instead of making
     it unanswered: a 2-unit board with one weak unit graded as an ANSWERED,
     WRONG 1-unit board (the gate lowered accuracy instead of coverage), and a
     last round whose rows were all weak made the grader reach back to an
     OLDER round's board and grade that against the final truth.
  F2 the same for final_level / final_gold: a weak last-round value fell back
     to an older round's value (graded correct by accident at HEAD).
  F3 two players flagged is_local graded the first one's level, gold and
     placement as the operator's (milestones._local_key already treats two
     local keys as ambiguous).
  F4 write_final_accuracy returned the rows as "written" when the store
     refused them (put_accuracy False), so the ground-truth sync counted
     accuracy_rows that never reached the store.
  F5 a malformed document raised AttributeError / TypeError (a non-dict
     player, gt or unit row, a non-list section, an unhashable src,
     champion_api or player_key), losing the grade of the whole match.
  F6 a bool confidence (True) passed the gate as 1.0.
"""
from __future__ import annotations

import math

import pytest

from tft.rounds import accuracy as acc
from tft.rounds.store import RoundStore


def _u(api, star=1, conf=0.9, src="icon", key="P1", phase="planning_end", items=()):
    return {"zone": "board", "phase": phase, "player_key": key, "champion_api": api,
            "star": star, "items": list(items), "conf": conf, "src": src}


def _gtb(key="P1", source="lcu_eog"):
    return [{"player_key": key, "source": source, "champion_api": "A", "star": 2, "items": []},
            {"player_key": key, "source": source, "champion_api": "B", "star": 1, "items": []}]


def _doc(rounds, *, players=None, gt_player=None, gt_board=None, match=None):
    return {
        "match": match if match is not None else {"placement": 1, "placement_src": "lcu"},
        "players": players if players is not None else [{"player_key": "P1", "is_local": 1}],
        "gt_player": gt_player if gt_player is not None else
        [{"player_key": "P1", "level": 8, "gold_left": 10, "placement": 1}],
        "gt_board": gt_board if gt_board is not None else _gtb(),
        "rounds": rounds,
    }


def _rows(rows):
    return {r["field"]: (r["n"], r["correct"], r["coverage"]) for r in rows}


GOOD_BOARD = [_u("A", 2), _u("B", 1)]


# ------------------------------------------------------------------ baseline

def test_baseline_good_board_and_values_grade_correct():
    rounds = [{"round_seq": 30, "units": GOOD_BOARD, "level": 8, "level_src": "ocr",
               "level_conf": 0.9, "gold_end": 10, "gold_end_src": "ocr", "gold_end_conf": 0.9}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    for field in acc.BOARD_FIELDS:
        assert got[field] == (1, 1, 1.0)
    assert got["final_level"] == (1, 1, 1.0)
    assert got["final_gold"] == (1, 1, 1.0)


# ------------------------------------------------------------------ F1

def test_f1_one_board_row_below_the_gate_leaves_the_board_unanswered():
    rounds = [{"round_seq": 30, "units": [_u("A", 2, conf=0.9), _u("B", 1, conf=0.3)]}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    for field in acc.BOARD_FIELDS:
        assert got[field] == (1, 0, 0.0)          # not answered, never answered-and-wrong


def test_f1_a_weak_last_board_never_falls_back_to_an_older_round():
    rounds = [{"round_seq": 10, "units": [_u("A", 2), _u("B", 1)]},
              {"round_seq": 30, "units": [_u("A", 2, conf=0.3), _u("C", 1, conf=0.3)]}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    for field in acc.BOARD_FIELDS:
        assert got[field] == (1, 0, 0.0)


def test_f1_the_gate_still_answers_a_strong_last_board():
    rounds = [{"round_seq": 10, "units": [_u("A", 2, conf=0.3)]},
              {"round_seq": 30, "units": GOOD_BOARD}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    assert got["final_board_units"] == (1, 1, 1.0)


def test_f1_an_oracle_row_in_the_last_round_does_not_hide_the_graded_board():
    # eog_file rows are oracles: they are not a prediction, so the latest
    # GRADED board is still the one graded.
    rounds = [{"round_seq": 30, "units": GOOD_BOARD + [_u("Z", 3, src="eog_file")]},
              {"round_seq": 31, "units": [_u("Z", 3, src="eog_file")]}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    assert got["final_board_units"] == (1, 1, 1.0)


def test_f1_a_conf_exactly_at_the_gate_is_answered():
    # section 3.4: coverage counts values AT or above the gate
    rounds = [{"round_seq": 30, "units": [_u("A", 2, conf=0.5), _u("B", 1, conf=0.5)],
               "level": 8, "level_src": "ocr", "level_conf": 0.5}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    assert got["final_board_units"] == (1, 1, 1.0)
    assert got["final_level"] == (1, 1, 1.0)


def test_f1_none_conf_counts_as_answered():
    rounds = [{"round_seq": 30, "units": [_u("A", 2, conf=None), _u("B", 1, conf=None)]}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    assert got["final_board_units"] == (1, 1, 1.0)


# ------------------------------------------------------------------ F2

@pytest.mark.parametrize("name,gt_field,field", [("level", "level", "final_level"),
                                                 ("gold_end", "gold_left", "final_gold")])
def test_f2_a_weak_last_value_never_falls_back_to_an_older_round(name, gt_field, field):
    truth = {"level": 8, "gold_left": 10}[gt_field]
    rounds = [{"round_seq": 10, name: truth, name + "_src": "ocr", name + "_conf": 0.9},
              {"round_seq": 30, name: truth + 1, name + "_src": "ocr", name + "_conf": 0.3}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    assert got[field] == (1, 0, 0.0)


def test_f2_a_strong_last_value_is_graded():
    rounds = [{"round_seq": 10, "level": 7, "level_src": "ocr", "level_conf": 0.3},
              {"round_seq": 30, "level": 8, "level_src": "ocr", "level_conf": 0.9}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.5))
    assert got["final_level"] == (1, 1, 1.0)


def test_f2_a_weak_placement_is_not_answered():
    match = {"placement": 1, "placement_src": "ocr", "placement_conf": 0.3}
    got = _rows(acc.final_accuracy(_doc([], match=match), min_conf=0.5))
    assert got["placement"] == (1, 0, 0.0)
    match = dict(match, placement_conf=0.9)
    assert _rows(acc.final_accuracy(_doc([], match=match), min_conf=0.5))["placement"] == (1, 1, 1.0)


# ------------------------------------------------------------------ F3

def test_f3_two_local_players_grade_no_local_field():
    rounds = [{"round_seq": 30, "units": GOOD_BOARD, "level": 8, "level_src": "ocr",
               "level_conf": 0.9}]
    players = [{"player_key": "P1", "is_local": 1}, {"player_key": "P2", "is_local": 1}]
    match = {"placement": 1, "placement_src": "ocr"}
    got = _rows(acc.final_accuracy(_doc(rounds, players=players, match=match)))
    assert "final_level" not in got and "final_gold" not in got and "placement" not in got
    assert got["final_board_units"] == (1, 1, 1.0)       # boards are per player, still graded


@pytest.mark.parametrize("flag", ["1", "0", 2, 1.0, None], ids=["str1", "str0", "two", "float", "none"])
def test_f3_only_an_exact_local_flag_is_local(flag):
    rounds = [{"round_seq": 30, "level": 8, "level_src": "ocr", "level_conf": 0.9}]
    got = _rows(acc.final_accuracy(_doc(rounds, players=[{"player_key": "P1", "is_local": flag}])))
    assert "final_level" not in got


@pytest.mark.parametrize("flag", [1, True])
def test_f3_one_local_player_is_graded(flag):
    rounds = [{"round_seq": 30, "level": 8, "level_src": "ocr", "level_conf": 0.9}]
    players = [{"player_key": "P1", "is_local": flag}, {"player_key": "P2", "is_local": 0}]
    got = _rows(acc.final_accuracy(_doc(rounds, players=players)))
    assert got["final_level"] == (1, 1, 1.0)


def test_f3_the_same_local_key_twice_is_still_one_player():
    rounds = [{"round_seq": 30, "level": 8, "level_src": "ocr", "level_conf": 0.9}]
    players = [{"player_key": "P1", "is_local": 1}, {"player_key": "P1", "is_local": 1}]
    assert _rows(acc.final_accuracy(_doc(rounds, players=players)))["final_level"] == (1, 1, 1.0)


# ------------------------------------------------------------------ F4

class _StubStore:
    def __init__(self, doc, accept):
        self.doc, self.accept, self.calls = doc, accept, []

    def get_match(self, match_id):
        return self.doc

    def put_accuracy(self, match_id, rows):
        self.calls.append((match_id, list(rows)))
        return self.accept


def test_f4_a_refused_write_returns_no_rows():
    store = _StubStore(_doc([{"round_seq": 30, "units": GOOD_BOARD}]), accept=False)
    assert acc.write_final_accuracy(store, "m1", computed_at=1.0) == []
    assert len(store.calls) == 1


def test_f4_an_accepted_write_returns_its_rows():
    store = _StubStore(_doc([{"round_seq": 30, "units": GOOD_BOARD}]), accept=True)
    rows = acc.write_final_accuracy(store, "m1", extractor_version="v", computed_at=1.0)
    assert {r["field"] for r in rows} == {r["field"] for r in store.calls[0][1]}
    assert all(r["extractor_version"] == "v" and r["computed_at"] == 1.0 for r in rows)


def test_f4_nothing_to_grade_writes_nothing():
    store = _StubStore(None, accept=True)
    assert acc.write_final_accuracy(store, "m1") == []
    assert store.calls == []


def test_f4_the_real_store_refusing_a_nan_stamp_returns_no_rows(tmp_path, monkeypatch):
    store = RoundStore.open(tmp_path / "tft" / "tft_rounds.db")
    try:
        mid = store.begin_match({"match_id": "m1"})
        assert mid == "m1" and store.flush()
        monkeypatch.setattr(store, "get_match",
                            lambda match_id, **kw: _doc([{"round_seq": 30, "units": GOOD_BOARD}]))
        assert acc.write_final_accuracy(store, mid, computed_at=math.nan) == []
        rows = acc.write_final_accuracy(store, mid, computed_at=5.0)       # positive control
        assert len(rows) == 3 + 2
        assert store.flush()
    finally:
        store.close()


# ------------------------------------------------------------------ F5

_JUNK_DOCS = {
    "player-none": lambda: _doc([], players=[None]),
    "players-int": lambda: _doc([], players=5),
    "gt-board-none": lambda: _doc([], gt_board=[None]),
    "gt-board-int": lambda: _doc([], gt_board=7),
    "gt-player-str": lambda: _doc([], gt_player=["x"]),
    "gt-board-key-list": lambda: _doc([], gt_board=[{"player_key": ["P1"], "source": "lcu_eog"}]),
    "gt-board-source-list": lambda: _doc([], gt_board=[{"player_key": "P1", "source": ["x"]}]),
    "rounds-int": lambda: _doc(5),
    "rounds-str": lambda: _doc("abc"),
    "round-none": lambda: _doc([None]),
    "units-int": lambda: _doc([{"round_seq": 1, "units": 5}]),
    "unit-src-list": lambda: _doc([{"round_seq": 1, "units": [_u("A", src=["icon"])]}]),
    "unit-api-list": lambda: _doc([{"round_seq": 1, "units": [_u(["A"]), _u("B")]}]),
    "unit-key-list": lambda: _doc([{"round_seq": 1, "units": [_u("A", key=["P1"])]}]),
    "unit-star-dict": lambda: _doc([{"round_seq": 1, "units": [_u("A", star={}), _u("B")]}]),
    "unit-phase-list": lambda: _doc([{"round_seq": 1, "units": [dict(_u("A"), phase=["x"])]}]),
    "placement-src-list": lambda: _doc([], match={"placement": 1, "placement_src": ["ocr"]}),
    "level-src-list": lambda: _doc([{"round_seq": 1, "level": 8, "level_src": ["ocr"]}]),
    "local-key-list": lambda: _doc([], players=[{"player_key": ["P1"], "is_local": 1}]),
}


@pytest.mark.parametrize("name", sorted(_JUNK_DOCS))
def test_f5_a_malformed_document_never_raises(name):
    rows = acc.final_accuracy(_JUNK_DOCS[name](), min_conf=0.5)
    assert isinstance(rows, list)
    for r in rows:
        assert 0.0 <= r["coverage"] <= 1.0 and 0 <= r["correct"] <= r["n"]


def test_f5_one_junk_unit_makes_that_board_wrong_not_the_match_lost():
    rounds = [{"round_seq": 30, "units": [_u(["A"], 2), _u("B", 1)]}]
    got = _rows(acc.final_accuracy(_doc(rounds)))
    assert got["final_board_units"] == (1, 0, 1.0)         # answered, never equal to the truth


def test_f5_a_junk_gt_row_skips_that_row_only():
    gt_board = _gtb() + [None, {"player_key": None, "source": "lcu_eog", "champion_api": "A"}]
    got = _rows(acc.final_accuracy(_doc([{"round_seq": 30, "units": GOOD_BOARD}], gt_board=gt_board)))
    assert got["final_board_units"] == (1, 1, 1.0)


def test_f5_non_dict_doc_is_empty():
    assert acc.final_accuracy(None) == []
    assert acc.final_accuracy({"match": None}) == []
    assert acc.final_accuracy([1, 2]) == []


# ------------------------------------------------------------------ F6

@pytest.mark.parametrize("conf", [True, False, math.nan, math.inf, "0.9", 10 ** 400],
                         ids=["true", "false", "nan", "inf", "str", "int-past-float"])
def test_f6_a_non_numeric_or_non_finite_conf_is_not_answered(conf):
    rounds = [{"round_seq": 30, "units": [_u("A", 2, conf=conf), _u("B", 1, conf=conf)]}]
    got = _rows(acc.final_accuracy(_doc(rounds), min_conf=0.0))
    assert got["final_board_units"] == (1, 0, 0.0)
