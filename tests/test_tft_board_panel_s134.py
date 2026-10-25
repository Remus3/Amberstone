"""S134 follow-up: the TFT panel's board + lobby payload.

Live check M3 (2026-10-25) showed HP / standing / board reaching /api/state but
the opponents' HP missing, and the dashboard TFT panel rendering only STAGE /
LEVEL / HP / GOLD. The backend now serves the local board as structured rows
(``coach.tft_board``) and every player's placement + HP (``coach.tft_players``,
opponents anonymous) from the standalone client's per-round stats file.

Fixture: tests/fixtures/tft_eog_round_s134.json is a SANITISED copy of a real
mid-match TFTEoGStats.json (round at 741 s, queue 1090, Set 18): identity
fields dropped, game id replaced.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tft import tft_standalone as ts

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tft_eog_round_s134.json"
LCU = {"phase": "InProgress", "game_id": "1000000001",
       "game_queue_id": 1090, "game_queue_mode": "TFT"}


@pytest.fixture
def eog_file(tmp_path, monkeypatch):
    p = tmp_path / "TFTEoGStats.json"
    p.write_text(FIXTURE.read_text(encoding="ascii"), encoding="ascii")
    monkeypatch.setattr(ts, "eog_stats_path", lambda: p)
    ts._reset_caches_for_tests()
    return p


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


def test_fixture_is_sanitised():
    blob = FIXTURE.read_text(encoding="ascii")
    for key in ("PUUID", "puuid", "riotId", "summonerName", "playerId",
                "companion", "tagLine"):
        assert key not in blob
    d = _fixture()
    players = d["statsBlock"]["players"]
    assert len(players) == 8
    assert sum(1 for p in players if p["isInteractable"]) == 1


@pytest.mark.parametrize("raw,clean", [
    ("DA_18_EmblemFloraFatalis", "Emblem Flora Fatalis"),
    ("DA_SteadfastHeart", "Steadfast Heart"),
    ("DA_InfinityEdge", "Infinity Edge"),
    ("DA_Evenshroud", "Evenshroud"),
    ("TFT_Item_GuinsoosRageblade", "Guinsoos Rageblade"),
    ("", ""),
    (None, ""),
    (7, ""),
])
def test_clean_item_name(raw, clean):
    assert ts.clean_item_name(raw) == clean


def test_summary_carries_board_rows_and_the_whole_lobby(eog_file):
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    d = _fixture()
    players = d["statsBlock"]["players"]
    local = next(p for p in players if p["isInteractable"])
    # local board, structured, item names readable
    assert [u["name"] for u in lc["board"]] == [
        ts.clean_unit_name(bp["championName"]) for bp in local["boardPieces"]]
    assert all(set(u) == {"name", "star", "items"} for u in lc["board"])
    for u in lc["board"]:
        assert all(not i.startswith("DA_") for i in u["items"])
    # every player: placement + HP, sorted by placement, one "you", no names
    rows = lc["players"]
    assert len(rows) == 8
    assert sorted(r["health"] for r in rows) == sorted(
        max(0, p["health"]) for p in players)
    assert [r["standing"] for r in rows] == sorted(r["standing"] for r in rows)
    assert sum(1 for r in rows if r["you"]) == 1
    you = next(r for r in rows if r["you"])
    assert you["health"] == local["health"]
    assert you["standing"] == local["ffaStanding"]
    assert all(set(r) == {"standing", "health", "you", "board_size"} for r in rows)


def test_opponent_hp_reaches_the_payload(eog_file):
    """Live check M3: opponents' HP was missing (tft_standalone summary)."""
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    opp = [r["health"] for r in lc["players"] if not r["you"]]
    assert len(opp) == 7


def test_no_lobby_or_board_without_a_same_game_file(eog_file):
    lc = ts.standalone_liveclient_summary(dict(LCU, game_id="42"), running=True)
    assert "players" not in lc and "board" not in lc


def test_build_state_fills_tft_board_and_players(eog_file, monkeypatch):
    from unittest import mock

    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    monkeypatch.setattr(sb, "_coach_file_mtime", lambda rel: time.time())
    health = {"alive": True, "mode": "client", "has_game": False,
              "aram_mode": False, "arena_mode": False, "tft_mode": False}
    # coach.board is the TFT engine's advice TEXT - it must survive untouched
    coach = {"mode": "tft", "board": "Hold the frontline", "stage_round": "3-5"}

    def _read_json(p):
        if "health" in str(p):
            return dict(health)
        return dict(coach) if "coaching_data" in str(p) else {}

    with mock.patch.object(sb, "read_json", side_effect=_read_json), \
            mock.patch.object(sb, "lcu_summary", return_value=dict(LCU)), \
            mock.patch.object(sb, "liveclient_summary", return_value={}), \
            mock.patch.object(sb, "get_team_context", return_value=None), \
            mock.patch.object(sb, "validate_coaching_payload",
                              lambda *_a, **_kw: None):
        state = sb.build_state()
    c = state["coach"]
    assert state["mode_key"] == "tft"
    assert c["board"] == "Hold the frontline"
    assert c["stage_round"] == "3-5"
    assert len(c["tft_players"]) == 8
    assert sum(1 for r in c["tft_players"] if r["you"]) == 1
    assert c["tft_board"] and all("name" in u for u in c["tft_board"])
    blob = json.dumps(state)
    assert all(ord(ch) < 128 for ch in blob)


def test_engine_written_board_rows_win_over_the_file(eog_file):
    from dashboard import _state_builder as sb
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    mine = [{"name": "Engine", "star": 3, "items": []}]
    out = sb.tft_coach_for_standalone({"tft_board": mine}, "x.json", lc)
    assert out["tft_board"] == mine
    empty = sb.tft_coach_for_standalone({"tft_board": []}, "x.json", lc)
    assert empty["tft_board"] == lc["board"]  # an empty list is blank
