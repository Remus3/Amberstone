"""S136 T9 - the TFT coach prompt takes its facts from the state reader.

Live QA (s136 T7, match run 20261025-153652, stage 2-2): the coach said
"Krug A1 ... Warwick B3" (neither unit on the board) and "hit 50g by 2-4" at
10 gold. Root cause, read in code: tft/tft_coach_engine.py ``_build_prompt``
took gold, HP, the board and the active traits ONLY from the vision file
data/tft_live_data.json. Its writer (tft/tft_live_analysis.py ``_write``)
emits no "gold" key, so the prompt always said "Gold: unknown" while the
state reader held the OCR gold (tft/tft_state_reader.py ``_parse``); the
vision board named units the per-round EoG board (``state["board"]``, from
tft/tft_standalone.py) did not have; and the vision HP (35, every player was
at 100) won over the reader's health.

Rules pinned here:
  (a) gold / level / stage come from the state dict - the same source the
      D1 payload (data/tft_coaching_data.json) and /api/state use; the
      vision gold is a fallback only while the reader has no gold read
      (``gold_known`` False), and neither present renders "unknown", never 0.
  (b) the authoritative board (state["board"], EoG) is the prompt board,
      with each unit's items; the vision board (and the traits read off the
      same panel) is a fallback only without it, filtered to the resolved
      set's roster (a name off the roster is dropped, logged at debug).
      NOTE: "Krug" IS a Set 18 unit (DA_Krug18, cost 3, Riftbeast Brawler,
      data/meta/tft_set18_cdragon.json), so the roster filter alone would not
      have stopped the 2-2 line; the precedence rule is what does.
  (c) the prompt HP is the state reader's health; a vision HP is never shown
      as player HP (it is dropped when the reader has none). The payload /
      urgency HP (``_resolve_hp``) prefers the reader too, vision as fallback.
  Sibling (items): the board line carries each unit's EoG items, and the
      standalone "none" items default is not claimed beside that board.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from pathlib import Path

import pytest

from tft import tft_coach_engine as eng
from tft import tft_standalone as ts

FIX = Path(__file__).parent / "fixtures" / "tft_eog_round_human_lobby_n13.json"
GID = 5000000013
LOCAL_SID = 900004
LOCAL_IDX = 3

# The real 2-2 board of the QA match (states.jsonl board_str) plus the
# Sparring Gloves the live notes saw on Xayah at 2-1.
_REAL_PIECES = [
    {"championName": "DA_18_Yorick", "itemNames": [], "starLevel": 2},
    {"championName": "DA_18_Leona", "itemNames": [], "starLevel": 2},
    {"championName": "DA_18_Rakan", "itemNames": [], "starLevel": 2},
    {"championName": "DA_18_Xayah", "itemNames": ["DA_SparringGloves"], "starLevel": 1},
]

# What the vision file held at 15:41:38 (2-2): no "gold" key, a wrong HP and
# a board of units the player did not have.
_VISION_22 = {
    "mode": "tft_live", "stage_round": "2-2", "level": 4, "hp": 35,
    "board_units": ["Krug 3-star", "Ornn 1-star", "Master Yi 3-star", "Warwick 2-star"],
    "traits_active": ["Juggernaut 2", "Blossom 2", "Adaptor 1", "Defender 1"],
    "augments": [], "comp": "Juggernaut + Blossom",
}


def _doc(game_len=300, pieces=None, hp=100) -> dict:
    doc = json.loads(FIX.read_text(encoding="utf-8"))
    doc["statsBlock"]["gameLengthSeconds"] = game_len
    for p in doc["statsBlock"]["players"]:
        p["health"] = hp
    doc["statsBlock"]["players"][LOCAL_IDX]["boardPieces"] = copy.deepcopy(
        _REAL_PIECES if pieces is None else pieces)
    return doc


def _synth(doc):
    lcu = {"phase": "InProgress", "game_id": str(GID), "game_queue_mode": "TFT",
           "summoner_id": LOCAL_SID}
    return ts.synth_allgamedata(lcu=lcu, running=True, eog=doc, now=time.time())


def _reader(ocr=None):
    from tft import tft_state_reader as tsr
    r = tsr.TftStateReader.__new__(tsr.TftStateReader)
    r._ssl = None
    r._my_name = ""
    r._last_level = 1
    r._last_gold = 0
    r._confirmed_stage = 1
    r._confirmed_round = 1
    r._ocr = None
    r._ocr_cache = dict(ocr or {})
    r._ocr_lock = threading.Lock()
    return r


def _d1_state(ocr=None, doc=None) -> dict:
    """The state dict the TFT worker submits (TftStateReader._parse on the
    standalone source) - the D1 source of stage / level / gold / health."""
    return _reader(ocr)._parse(_synth(doc if doc is not None else _doc()))


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    """Set 18 (the QA match's set) and an injected vision file; never the
    repo-root data/tft_live_data.json."""
    monkeypatch.setattr(eng, "_resolved_set", lambda: 18)
    monkeypatch.setattr(eng, "_set_has_gods", lambda: False)
    monkeypatch.setattr(eng, "_meta_verified", lambda: False)
    vision = {"doc": dict(_VISION_22)}
    monkeypatch.setattr(eng, "_live_data", lambda: vision["doc"])
    return vision


def _line(prompt: str, prefix: str) -> str:
    rows = [ln for ln in prompt.splitlines() if ln.startswith(prefix)]
    assert len(rows) <= 1, rows
    return rows[0] if rows else ""


# -- (a) gold / level / stage --------------------------------------------------

def test_d1_gold_level_stage_reach_the_prompt_when_vision_has_no_gold():
    state = _d1_state(ocr={"gold": 10, "level": 3, "stage_round": "2-2"})
    assert (state["gold"], state["level"], state["stage_round"]) == (10, 3, "2-2")
    assert "gold" not in _VISION_22
    prompt = eng._build_prompt(state)
    assert _line(prompt, "=== Stage").startswith("=== Stage 2-2 | Level 3 |")
    hp_gold = _line(prompt, "HP:")
    assert "Gold: 10" in hp_gold, hp_gold
    assert "Gold: unknown" not in prompt and "Gold: 0" not in prompt
    assert "Current gold: 10g | Interest: +1g/round" in prompt


def test_plain_state_gold_wins_over_a_conflicting_vision_gold(_pin):
    _pin["doc"] = dict(_VISION_22, gold=50)
    prompt = eng._build_prompt({"stage": 2, "round": 2, "level": 3, "gold": 10})
    assert "Gold: 10" in _line(prompt, "HP:")
    assert "50g" not in prompt


def test_unread_gold_is_unknown_not_zero(_pin):
    state = _d1_state(ocr={})  # OCR has read nothing yet
    assert state["gold"] == 0 and state["gold_known"] is False
    prompt = eng._build_prompt(state)
    assert "Gold: unknown" in _line(prompt, "HP:")
    assert "Current gold" not in prompt


def test_vision_gold_is_the_fallback_while_the_reader_has_none(_pin):
    _pin["doc"] = dict(_VISION_22, gold=23)
    prompt = eng._build_prompt(_d1_state(ocr={}))
    assert "Gold: 23" in _line(prompt, "HP:")


# -- (b) board -----------------------------------------------------------------

def test_authoritative_board_replaces_the_vision_board_and_traits():
    state = _d1_state(ocr={"gold": 10, "level": 3, "stage_round": "2-2"})
    prompt = eng._build_prompt(state)
    board = _line(prompt, "Board units:")
    assert board == ("Board units: Yorick*2, Leona*2, Rakan*2, "
                     "Xayah*1 [Sparring Gloves]"), board
    for ghost in ("Krug", "Ornn", "Warwick", "Master Yi"):
        assert ghost not in prompt, ghost
    # the traits came off the same wrong vision read
    assert "Juggernaut 2" not in prompt and not _line(prompt, "Active traits:")
    # the standalone source has no item feed: its "none" is never claimed
    # beside a board that holds Sparring Gloves
    assert state["items_str"] == "none"
    assert "Your items/augments: none" not in prompt
    assert _line(prompt, "Your items/augments:").startswith("Your items/augments: unknown")


def test_vision_board_off_the_set_roster_is_dropped(_pin, caplog):
    _pin["doc"] = dict(_VISION_22, board_units=[
        "Zed 2-star", "Krug 3-star", "unknown", "empty", "Leona (2)", "Gragas"])
    caplog.set_level(logging.DEBUG, logger="rc.tft.coach")
    prompt = eng._build_prompt({"stage": 2, "round": 2, "level": 4, "board": []})
    board = _line(prompt, "Board units:")
    assert board == "Board units: Krug 3-star, Leona (2)", board
    assert "Zed" not in prompt and "Gragas" not in prompt
    assert "unknown" not in board and "empty" not in board
    dropped = " ".join(r.getMessage() for r in caplog.records)
    assert "Zed" in dropped and "Gragas" in dropped


def test_vision_board_with_no_roster_adds_no_board_line(_pin, monkeypatch):
    monkeypatch.setattr(eng, "_resolved_set", lambda: None)
    prompt = eng._build_prompt({"stage": 2, "round": 2, "level": 4})
    assert not _line(prompt, "Board units:")


# -- (c) HP --------------------------------------------------------------------

def test_vision_hp_never_shown_over_the_reader_health():
    state = _d1_state(ocr={"gold": 10, "level": 3, "stage_round": "2-2"})
    assert state["health"] == 100
    prompt = eng._build_prompt(state)
    assert "HP: 100" in _line(prompt, "HP:")
    assert "35" not in _line(prompt, "HP:")


def test_vision_hp_dropped_when_no_authoritative_hp(_pin):
    prompt = eng._build_prompt({"stage": 2, "round": 2, "level": 3, "health": None})
    hp_line = _line(prompt, "HP:")
    assert hp_line.startswith("HP: unknown"), hp_line
    assert "35" not in hp_line


def test_payload_hp_prefers_the_reader_over_vision(tmp_path, monkeypatch):
    from unittest.mock import patch
    with patch("core.anthropic_key.read_anthropic_key", return_value=""):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            engine = eng.TftCoachEngine(tmp_path / "tft_coaching_data.json")
    monkeypatch.setattr(engine, "_vision_hp", lambda loader=None: 35)
    assert engine._resolve_hp({"health": 100}) == 100
    # no reader health: vision is the fallback, then the default
    assert engine._resolve_hp({"health": None}) == 35
    monkeypatch.setattr(engine, "_vision_hp", lambda loader=None: None)
    assert engine._resolve_hp({}) == 100
