"""Lane 8 (true-audit) session 134 cycle 7: tft/tft_final_board.py.

The module turns the ended TFT game's own record into the end-of-game rating
inputs (performance_tracker._tft_final / plan_tft_rating). Five weaknesses,
each pinned by a test that was red before the fix:

  1. resolve_final ignored a digit-string game_id (store_final accepts one,
     through tft_placement.load), so a known game fell back to "the current
     game" and, with none, rated nothing.
  2. final_from_record passed a NaN / inf / negative end stamp through as
     ended_at_unix; plan_tft_rating hands it to datetime.fromtimestamp,
     which raises (ValueError / OverflowError / OSError on Windows).
  3. per_round_record logged every failure at DEBUG and set_number_of
     swallowed a tft_set failure silently: a broken reader killed the
     per-round fallback invisibly. Now one WARNING per failure (the module
     runs once per game end, never per tick).
  4. One malformed board entry (a non-string name, a non-list items field)
     raised TypeError out of final_from_record, so the whole real record was
     lost and the rating fell back to the legacy blank inputs (the N8 class).
  5. resolve_final read the per-round file and the relay LCU snapshot even
     when the caller named the game and the store already held it.
"""
from __future__ import annotations

import json
import logging
import math
import shutil
import time
from pathlib import Path

import pytest

from tft import tft_final_board as fb
from tft import tft_placement as tp
from tft import tft_set
from tft import tft_standalone

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
EOG_DOC = json.loads((FIX / "tft_eog_stats_set18.json").read_text(encoding="utf-8"))
GID = 1000000001


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A tmp root with Set 18 data, an isolated store, no per-round file and
    NO current game (nothing names the game but the caller)."""
    r = tmp_path / "root"
    (r / "data" / "meta").mkdir(parents=True)
    shutil.copy(REPO / "data" / "meta" / "tft_set18_cdragon.json",
                r / "data" / "meta" / "tft_set18_cdragon.json")
    store = r / "data" / "tft_matches"
    monkeypatch.setattr(tp, "_STORE_DIR", store)
    monkeypatch.setattr(tft_standalone, "eog_stats_path",
                        lambda: tmp_path / "no_such_TFTEoGStats.json")
    monkeypatch.setattr(tft_standalone, "relay_lcu_snapshot", lambda: {"phase": "EndOfGame"})
    tft_standalone._reset_caches_for_tests()
    yield r
    tft_standalone._reset_caches_for_tests()


def _store_eog():
    rec = tp.parse_eog(EOG_DOC, now=time.time())
    assert tp.persist(rec)
    return rec


def _record(**over):
    rec = {"game_id": GID, "local_placement": 3, "set_core_name": "TFTSet18",
           "queue_id": 1090, "sources": ["eog"], "captured_at_unix": 1761400000.0,
           "players": [{"is_local": True, "level": 8, "last_round": 30,
                        "board": [{"name": "Ashe", "star": 2, "cost": 5,
                                   "items": [{"name": "Infinity Edge"}]}],
                        "traits": [{"name": "Lunar", "units": 3}],
                        "augments": ["Augment A"]}]}
    rec.update(over)
    return rec


# -- 1. a digit-string game id names the game ---------------------------------------

def test_digit_string_game_id_finds_the_store_record(root):
    _store_eog()
    fin = fb.resolve_final(root, game_id=str(GID))
    assert fin is not None
    assert fin["game_id"] == GID
    assert fin["placement"] == 1
    assert fin["source"] == fb.SOURCE_STORE


def test_padded_digit_string_game_id_is_the_same_game(root):
    _store_eog()
    fin = fb.resolve_final(root, game_id=f" {GID} ")
    assert fin is not None and fin["game_id"] == GID


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "", "\u00b2", "1\u00b2", True, 0, -3, 1.5])
def test_non_game_ids_name_no_game(root, bad):
    _store_eog()
    # Nothing else names the game (no current game, no file), so a rejected
    # id must rate nothing - never some other record.
    assert fb.resolve_final(root, game_id=bad) is None


# -- 2. the end stamp is a usable timestamp or None ----------------------------------

@pytest.mark.parametrize("stamp", [float("nan"), float("inf"), float("-inf"), -5.0, 0, 0.0,
                                   10 ** 400, 1e300, 4102444800.0])
def test_unusable_end_stamp_is_none(stamp):
    fin = fb.final_from_record(_record(ended_at_effective_unix=stamp, captured_at_unix=None))
    assert fin is not None
    assert fin["ended_at_unix"] is None


def test_real_end_stamp_is_kept():
    fin = fb.final_from_record(_record(ended_at_effective_unix=1761400123))
    assert fin["ended_at_unix"] == 1761400123.0
    assert isinstance(fin["ended_at_unix"], float)


def test_captured_stamp_is_the_fallback_end():
    fin = fb.final_from_record(_record())
    assert fin["ended_at_unix"] == 1761400000.0
    assert math.isfinite(fin["ended_at_unix"])


# -- 3. a broken reader is a WARNING, not a silent DEBUG line -------------------------

def test_per_round_reader_failure_warns(root, monkeypatch, caplog):
    def _boom(**_k):
        raise RuntimeError("reader renamed")
    monkeypatch.setattr(tft_standalone, "read_eog", _boom)
    with caplog.at_level(logging.DEBUG, logger="rc.tft.final_board"):
        assert fb.per_round_record(now=time.time(), game_id=GID) is None
    warned = [r for r in caplog.records
              if r.name == "rc.tft.final_board" and r.levelno >= logging.WARNING]
    assert warned, "a per-round reader failure must log a WARNING"
    assert "RuntimeError" in warned[0].getMessage()


def test_set_parser_failure_warns_and_falls_back(monkeypatch, caplog):
    def _boom(_v):
        raise RuntimeError("parser broke")
    monkeypatch.setattr(tft_set, "parse_set_id", _boom)
    with caplog.at_level(logging.DEBUG, logger="rc.tft.final_board"):
        n = fb.set_number_of({"set_core_name": "TFTSet18", "set_number": 18})
    assert n == 18
    assert any(r.name == "rc.tft.final_board" and r.levelno >= logging.WARNING
               for r in caplog.records)


def test_set_number_parses_the_core_name():
    assert fb.set_number_of({"set_core_name": "TFTSet18"}) == 18
    assert fb.set_number_of({"set_number": 17}) == 17
    assert fb.set_number_of("nope") is None


# -- 4. one malformed board entry never loses the whole record -----------------------

def test_malformed_board_entries_are_dropped_not_fatal():
    board = [{"name": ["not", "a", "name"], "star": 3},
             {"name": "Ashe", "star": 2, "cost": 5, "items": 5},
             {"name": "Diana", "star": 1, "cost": 3, "items": "Infinity Edge"},
             {"name": "Yorick", "star": 2, "cost": 4,
              "items": [{"name": "Lunar Emblem"}, "junk", {"name": 7}]},
             "junk"]
    rec = _record()
    rec["players"][0]["board"] = board
    rec["players"][0]["traits"] = []          # force the board-derived trait count
    fin = fb.final_from_record(rec)
    assert fin is not None
    assert fin["placement"] == 3
    names = [u["name"] for u in fin["board"]]
    assert names == ["Ashe", "Yorick", "Diana"]
    by = {u["name"]: u for u in fin["board"]}
    assert by["Ashe"]["items"] == []
    assert by["Diana"]["items"] == []
    assert by["Yorick"]["items"] == ["Lunar Emblem"]


def test_unnamed_items_still_count_toward_the_carry_order():
    # tft_placement._eog_items emits {"name_id": ..., "name": ""} when the EOG
    # block has an id but no display name; the order counts held items, as
    # before this audit (verifier REFUTE round 1), while the shown item list
    # keeps named ones only.
    rec = _record()
    rec["players"][0]["board"] = [
        {"name": "Ashe", "star": 2, "cost": 4, "items": [{"name": "Infinity Edge"}]},
        {"name": "Yorick", "star": 2, "cost": 4,
         "items": [{"name_id": "TFT_Item_A", "name": ""},
                   {"name_id": "TFT_Item_B", "name": ""}]}]
    fin = fb.final_from_record(rec)
    assert fin["units"] == ["Yorick 2-star", "Ashe 2-star"]
    assert [u["items"] for u in fin["board"]] == [[], ["Infinity Edge"]]


def test_trait_counts_skip_unhashable_names_and_bad_items():
    counts = fb.trait_counts_from_board(
        [{"name": {"x": 1}}, {"name": "Ashe", "items": 5},
         {"name": "Ashe"}, {"name": "Yorick", "items": [{"name": "Lunar Emblem"}]}],
        {"Ashe": ["Sniper"], "Yorick": ["Lunar"]})
    assert counts == [{"name": "Lunar", "units": 1}, {"name": "Sniper", "units": 1}]


def test_non_list_players_and_traits_do_not_raise():
    assert fb.final_from_record(_record(players="junk"))["board"] == []
    rec = _record()
    # Two Set 18 Hunters (data/meta/tft_set18_cdragon.json: Hunter 2/3/4/5).
    rec["players"][0]["board"].append({"name": "Caitlyn", "star": 1, "cost": 1, "items": []})
    rec["players"][0]["traits"] = "junk"
    rec["players"][0]["augments"] = "junk"
    fin = fb.final_from_record(rec)
    assert fin["augments"] == []
    assert fin["traits"] == ["Hunter 2"]       # derived from the board instead
    assert fin["comp"] == "Hunter 2"


def test_non_list_sources_are_empty():
    assert fb.final_from_record(_record(sources="eog"))["sources"] == []
    assert fb.final_from_record(_record(sources=["eog", 3]))["sources"] == ["eog"]


# -- 5. a named game found in the store reads nothing else ---------------------------

def test_named_game_in_store_skips_the_per_round_read(root, monkeypatch):
    _store_eog()
    calls = []
    monkeypatch.setattr(fb, "per_round_record", lambda **k: calls.append(k))
    fin = fb.resolve_final(root, game_id=GID)
    assert fin is not None and fin["placement"] == 1
    assert calls == []


def test_named_game_missing_from_store_still_reads_the_per_round_file(root, monkeypatch):
    calls = []
    monkeypatch.setattr(fb, "per_round_record", lambda **k: calls.append(k))
    assert fb.resolve_final(root, game_id=GID) is None
    assert len(calls) == 1 and calls[0]["game_id"] == GID
