"""S134: map 22 is the STANDARD TFT map, not Double Up; and the set-aware
gameTime table accessor other modules read.

EVIDENCE
--------
Both live Set 18 QA games (ops/runtime/tft_qa/20261025-070350 and
20261025-081234, QA_REPORT.md line 3) were queue 1090 NORMAL_TFT on map 22,
and the LCU inventory (ops/runtime/tft_qa/LCU_TFT_INVENTORY.md, "Queue /
mode" row) reads gameflow session gameData.queue = id 1090, gameMode TFT,
mapId 22, type NORMAL_TFT. Double Up is its own queue, 1160 (lol-game-queues;
assetMutator "TFT_PAIRS"). tft/tft_state_reader.py detect_variant returned
"double_up" for every mapNumber 22 game, so a normal game's coach prompt
carried "MODE: DOUBLE UP" and partner-HP / donation lines.

RM-615 (core/tft_stage_gate.py) reads tft_state_reader._TIME_TO_ROUND at
runtime: that name stays (the legacy Set 17 table); time_table(set) is the
set-aware accessor (Set 18 -> _TIME_TO_ROUND_SET18).

Names used, cited at the fix tree: tft/tft_state_reader.py
`TftStateReader.detect_variant`, `DOUBLE_UP_QUEUES`, `time_table`,
`_time_table`, `_TIME_TO_ROUND`, `_TIME_TO_ROUND_SET18`; tft/tft_set.py
`resolve_set`.
"""
from __future__ import annotations

import pytest

from tft import tft_set
from tft import tft_state_reader as tsr

detect = tsr.TftStateReader.detect_variant


@pytest.mark.parametrize("gd", [
    {"gameMode": "TFT", "mapNumber": 22},
    {"gameMode": "TFT", "mapNumber": 22, "mapName": "Map22", "queueId": 1090},
    {"gameMode": "TFT", "mapNumber": 22, "queueId": 1100},
    {"gameMode": "TFT", "mapName": "map22"},
])
def test_map_22_alone_is_a_standard_game(gd):
    assert detect(gd) == "standard"


@pytest.mark.parametrize("gd", [
    {"gameMode": "TFT", "mapNumber": 22, "queueId": 1160},
    {"gameMode": "TFT", "mapNumber": 22, "queueId": "1160"},
    {"gameMode": "PAIRS"},
    {"gameMode": "TFT", "mapTerrain": "DoubleUp"},
])
def test_double_up_needs_its_own_signal(gd):
    assert detect(gd) == "double_up"


def test_hyper_roll_still_detected():
    assert detect({"gameMode": "TFT", "mapNumber": 22, "mapTerrain": "Turbo"}) == "hyper_roll"


def test_double_up_queue_is_the_measured_one():
    assert tsr.DOUBLE_UP_QUEUES == frozenset({1160})


def test_time_table_accessor_is_set_aware(monkeypatch):
    assert tsr.time_table(18) is tsr._TIME_TO_ROUND_SET18
    assert tsr.time_table(17) is tsr._TIME_TO_ROUND
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 18)
    assert tsr.time_table() is tsr._TIME_TO_ROUND_SET18
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 17)
    assert tsr.time_table() is tsr._TIME_TO_ROUND


def test_legacy_table_name_is_kept_for_its_readers():
    """core/tft_stage_gate.py (RM-615) reads this name at runtime."""
    assert isinstance(tsr._TIME_TO_ROUND, list) and tsr._TIME_TO_ROUND[0] == (0, 1, 1)
