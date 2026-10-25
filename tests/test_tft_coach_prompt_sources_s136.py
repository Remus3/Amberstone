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


# -- verifier round 1: a previous game's per-round file ------------------------
# The per-round file was matched to the current game only by the LCU game id
# (tft/tft_standalone.py _round_state) plus the 300 s file-age limit, never
# against the current game's start: with no current game id (LCU snapshot
# without one, or no LCU at all) a 120 s old file from the PREVIOUS game put
# "Board units: Krug*3 [Sparring Gloves], Warwick*2" and "HP: 37" into the
# live prompt (verifier probe s136-verify-T9 leak_probe2). Rule: the file's
# board / HP enter a prompt ONLY on a POSITIVE match - its game id equals the
# current LCU game id, and it was written after the current game started
# where that start is known; otherwise they are "unknown", never stale.

_PREV_PIECES = [
    {"championName": "DA_18_Krug", "itemNames": ["DA_SparringGloves"], "starLevel": 3},
    {"championName": "DA_18_Warwick", "itemNames": [], "starLevel": 2},
]


def _prev_game_doc(now: float, *, only_local_interactable=False) -> dict:
    doc = _doc(game_len=1900, pieces=_PREV_PIECES, hp=37)
    doc["_mtime"] = now - 120
    if only_local_interactable:
        for i, p in enumerate(doc["statsBlock"]["players"]):
            p["isInteractable"] = i == LOCAL_IDX
    return doc


def _stale_state(lcu, doc, now):
    raw = ts.synth_allgamedata(lcu=lcu, running=True, eog=doc, now=now)
    assert raw is not None
    return _reader()._parse(raw)


_LEAK_SHAPES = {
    # LCU in game with the summoner id but no game id (session GET failed)
    "lcu_without_game_id": (
        {"phase": "InProgress", "game_queue_mode": "TFT", "summoner_id": LOCAL_SID},
        False),
    # no LCU at all (relay stale) + a lobby with ONE interactable entry
    "no_lcu_single_interactable": (None, True),
}


@pytest.mark.parametrize("shape", sorted(_LEAK_SHAPES))
def test_previous_game_file_board_and_hp_never_reach_the_prompt(shape, _pin):
    _pin["doc"] = {}  # the verifier probe's setup: no vision file
    lcu, single = _LEAK_SHAPES[shape]
    now = time.time()
    state = _stale_state(lcu, _prev_game_doc(now, only_local_interactable=single), now)
    assert state["eog_match"] is False
    prompt = eng._build_prompt(state)
    for ghost in ("Krug", "Warwick", "Sparring Gloves"):
        assert ghost not in prompt, (shape, ghost)
    hp_line = _line(prompt, "HP:")
    assert hp_line.startswith("HP: unknown"), hp_line
    assert "37" not in hp_line


@pytest.mark.parametrize("shape", sorted(_LEAK_SHAPES))
def test_previous_game_file_hp_never_reaches_the_payload(shape, tmp_path, monkeypatch):
    from unittest.mock import patch
    lcu, single = _LEAK_SHAPES[shape]
    now = time.time()
    state = _stale_state(lcu, _prev_game_doc(now, only_local_interactable=single), now)
    with patch("core.anthropic_key.read_anthropic_key", return_value=""):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            engine = eng.TftCoachEngine(tmp_path / "tft_coaching_data.json")
    monkeypatch.setattr(engine, "_vision_hp", lambda loader=None: None)
    assert engine._resolve_hp(state) == 100  # the default, never the stale 37


def test_file_written_before_the_current_game_started_is_not_a_match(monkeypatch, _pin):
    _pin["doc"] = {}
    now = time.time()
    lcu = {"phase": "InProgress", "game_id": str(GID), "game_queue_mode": "TFT",
           "summoner_id": LOCAL_SID}
    # same game id (a reconnect), but this process started AFTER the write
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 60)
    state = _stale_state(lcu, _prev_game_doc(now), now)
    assert state["eog_match"] is False
    prompt = eng._build_prompt(state)
    assert "Krug" not in prompt and "HP: 37" not in prompt
    # written after the start: a positive match, the board is served
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 600)
    state = _stale_state(lcu, _prev_game_doc(now), now)
    assert state["eog_match"] is True
    prompt = eng._build_prompt(state)
    assert _line(prompt, "Board units:") == (
        "Board units: Krug*3 [Sparring Gloves], Warwick*2")
    assert "HP: 37" in _line(prompt, "HP:")


def test_positive_match_needs_both_game_ids():
    doc = _doc()
    assert ts.eog_matches_game(doc, str(GID)) is True
    assert ts.eog_matches_game(doc, "") is False
    assert ts.eog_matches_game(doc, None) is False
    assert ts.eog_matches_game(doc, "999") is False
    no_id = dict(doc)
    no_id.pop("gameId", None)
    assert ts.eog_matches_game(no_id, str(GID)) is False
    doc["_mtime"] = 100.0
    assert ts.eog_matches_game(doc, str(GID), game_start=200.0) is False
    assert ts.eog_matches_game(doc, str(GID), game_start=50.0) is True
    assert ts.eog_matches_game(doc, str(GID), game_start=None) is True


# -- level placeholder ---------------------------------------------------------

def test_placeholder_level_renders_unknown():
    state = _d1_state(ocr={})  # OCR read nothing: level is the reader's default 1
    assert state["level"] == 1 and state["level_known"] is False
    prompt = eng._build_prompt(state)
    assert _line(prompt, "=== Stage").count("Level unknown") == 1
    assert "Level 1" not in prompt
    # no XP / roll-odds lines built on a level nobody read
    assert not _line(prompt, "XP to Lv") and not _line(prompt, "Roll odds")
    read = _d1_state(ocr={"level": 3, "gold": 10, "stage_round": "2-2"})
    assert read["level_known"] is True
    assert "| Level 3 |" in _line(eng._build_prompt(read), "=== Stage")


# -- verifier round 2: every field the file feeds ------------------------------
# Round 1 gated the prompt's board / HP only; the same previous-game file still
# set the game clock (tft/tft_standalone.py _synth_allgamedata game_time from
# the file's gameLengthSeconds -> tft/tft_state_reader.py _parse round clock,
# so the prompt said "Stage 5-7" in a game 200 s old) and still fed /api/state
# (dashboard/_state_builder.py standalone_liveclient_summary -> _summary_from_raw
# hp / standing / board / lobby / as_of / game id, tft_coach_for_standalone,
# tft_live_status). The gate now sits where the file is read for the live
# source (_round_state): a file that is not POSITIVELY this game's is no file.

_FILE_FIELDS = ("hp", "standing", "eliminated", "board_size", "board_str",
                "board", "players", "players_alive", "as_of")


@pytest.mark.parametrize("shape", sorted(_LEAK_SHAPES))
def test_previous_game_file_sets_no_stage(shape, _pin, monkeypatch):
    _pin["doc"] = {}
    lcu, single = _LEAK_SHAPES[shape]
    now = time.time()
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 200)
    state = _stale_state(lcu, _prev_game_doc(now, only_local_interactable=single), now)
    assert state["game_time_s"] == pytest.approx(200, abs=5)  # the process clock
    assert (state["stage"], state["stage_round"]) == (2, "2-1")
    header = _line(eng._build_prompt(state), "=== Stage")
    assert header.startswith("=== Stage 2-1 |"), header


@pytest.mark.parametrize("shape", sorted(_LEAK_SHAPES))
def test_previous_game_file_feeds_no_api_state_field(shape, monkeypatch):
    lcu, single = _LEAK_SHAPES[shape]
    now = time.time()
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 200)
    doc = _prev_game_doc(now, only_local_interactable=single)
    # /api/state liveclient (dashboard/_state_builder.py build_state)
    lc = ts.standalone_liveclient_summary(lcu, running=True, eog=copy.deepcopy(doc))
    assert lc and lc["source"] == ts.SOURCE_TAG
    leaked = {k: lc[k] for k in _FILE_FIELDS if k in lc}
    assert leaked == {}, (shape, leaked)
    assert lc["game_time_s"] == pytest.approx(200, abs=5)
    assert lc["game_id"] != str(GID)  # never the previous game's id
    # coach.tft_live and the coach fill from lc
    assert ts.tft_live_status(lcu, running=True, eog=copy.deepcopy(doc))["eog"] is False
    from dashboard._state_builder import tft_coach_for_standalone
    coach = tft_coach_for_standalone({}, "", lc)
    for k in ("health", "hp", "standing", "board_str", "tft_board",
              "tft_players", "tft_as_of", "players_alive"):
        assert k not in coach, (shape, k)
    # the poller's hp_pct reads activePlayer.currentHP / allPlayers health
    raw = ts.synth_allgamedata(lcu=lcu, running=True, eog=copy.deepcopy(doc), now=now)
    assert "currentHP" not in raw["activePlayer"]
    assert all("health" not in p for p in raw["allPlayers"])


def test_positive_match_still_feeds_the_live_fields(monkeypatch):
    now = time.time()
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 2100)
    lcu = {"phase": "InProgress", "game_id": str(GID), "game_queue_mode": "TFT",
           "summoner_id": LOCAL_SID}
    lc = ts.standalone_liveclient_summary(lcu, running=True, eog=_prev_game_doc(now))
    assert lc["hp"] == 37 and lc["board_str"] == "Krug*3, Warwick*2"
    assert lc["game_id"] == str(GID) and lc["players"]
    state = _stale_state(lcu, _prev_game_doc(now), now)
    assert state["eog_match"] is True and state["game_time_s"] > 1900
