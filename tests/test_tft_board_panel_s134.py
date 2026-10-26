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
import re
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


# RM-946: every id below except the last four is a REAL itemNames entry of
# a recorded Set 18 per-round file (ops/runtime/tft_qa, 2026-10-25 runs). The
# display form is a readable approximation of the in-game names (the set's
# CommunityDragon data is itself inconsistent: "Hand Of Justice" beside
# "Radiant Hand of Justice") in the repo's "<Trait> Emblem" convention
# (tft/tft_placement.display_from_id, tft/engine/comps.EMBLEM_SUFFIX): the
# client's category token (Component_ / Artifact_) is dropped, a _Radiant
# suffix leads, and interior connectors read lower case. Apostrophes and
# "B.F." are NOT restored: that needs the set's item-name data, not a string
# rule.
_REAL_ITEM_IDS = [
    ("DA_18_EmblemFloraFatalis", "Flora Fatalis Emblem"),
    ("DA_18_EmblemFae", "Fae Emblem"),
    ("DA_SteadfastHeart", "Steadfast Heart"),
    ("DA_InfinityEdge", "Infinity Edge"),
    ("DA_Evenshroud", "Evenshroud"),
    ("DA_Component_BFSword", "BF Sword"),
    ("DA_Component_NeedlesslyLargeRod", "Needlessly Large Rod"),
    ("DA_Component_TearOfTheGoddess", "Tear of the Goddess"),
    ("DA_Component_Spatula", "Spatula"),
    ("DA_Artifact_AegisOfDawn", "Aegis of Dawn"),
    ("DA_Artifact_TheIndomitable", "The Indomitable"),
    ("DA_Artifact_NavoriFlickerblade", "Navori Flickerblade"),
    ("DA_GiantSlayer_Radiant", "Radiant Giant Slayer"),
    ("DA_ThiefsGlovesRadiant", "Radiant Thiefs Gloves"),
    ("DA_KrakensFury_Radiant", "Radiant Krakens Fury"),
    ("DA_HandOfJustice", "Hand of Justice"),
    ("DA_SpearOfShojin", "Spear of Shojin"),
    ("DA_EdgeOfNight", "Edge of Night"),
    ("DA_GuinsoosRageblade", "Guinsoos Rageblade"),
]


@pytest.mark.parametrize("raw,clean", _REAL_ITEM_IDS + [
    ("TFT_Item_GuinsoosRageblade", "Guinsoos Rageblade"),
    # a bare category or modifier word is a name, never emptied
    ("DA_Component", "Component"),
    ("DA_Radiant", "Radiant"),
    ("", ""),
    (None, ""),
    (7, ""),
])
def test_clean_item_name(raw, clean):
    assert ts.clean_item_name(raw) == clean


def test_clean_item_names_fit_the_board_chip_clip():
    """The dashboard board chip clips each item name (active_match.js
    _amTftBoard, `_amText(i, N)`): every real id must survive it whole. The
    pre-fix "Component Needlessly Large Rod" (30) painted as
    "Component Needlessly Large R"."""
    js = (Path(__file__).resolve().parent.parent / "web" / "js" / "panels"
          / "active_match.js").read_text(encoding="utf-8")
    m = re.search(r"\.map\(\(i\) => _amText\(i, (\d+)\)\)", js)
    assert m, "board chip item clip not found in active_match.js"
    clip = int(m.group(1))
    for raw, _ in _REAL_ITEM_IDS:
        assert len(ts.clean_item_name(raw)) <= clip, raw


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


def _start_of_game(eog_file):
    """Match 3 QA N10: for ~20 s after the game starts the client writes
    health -1 / ffaStanding -1 for every player (measured live)."""
    d = _fixture()
    d["statsBlock"]["gameLengthSeconds"] = 0
    for p in d["statsBlock"]["players"]:
        p["health"] = -1
        p["ffaStanding"] = -1
        p["boardPieces"] = []
    eog_file.write_text(json.dumps(d), encoding="ascii")


def test_start_of_game_sentinels_are_served_as_unknown(eog_file):
    _start_of_game(eog_file)
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    assert lc["hp"] is None
    assert lc["standing"] is None
    assert lc["players_alive"] is None
    assert "players" not in lc       # no lobby of -1s / zeros
    assert "as_of" not in lc         # game clock 0 is not a real round
    blob = json.dumps(lc)
    assert "-1" not in blob


def test_start_of_game_never_marks_players_dead(eog_file):
    _start_of_game(eog_file)
    raw = ts.synth_allgamedata(lcu=LCU, running=True)
    assert raw is not None
    assert all(p["isDead"] is False for p in raw["allPlayers"])
    assert all("health" not in p for p in raw["allPlayers"])
    assert "currentHP" not in raw["activePlayer"]
    from game_reader import GameReader
    gr = GameReader.__new__(GameReader)
    state = gr._process_game(raw)
    assert state["hp_pct"] == 100  # the Live Client default, not -1 / 0


def test_tft_state_reader_health_is_unknown_not_dead_at_start(eog_file, monkeypatch):
    import threading

    from tft import tft_state_reader as tsr
    _start_of_game(eog_file)
    raw = ts.synth_allgamedata(lcu=LCU, running=True)
    r = tsr.TftStateReader.__new__(tsr.TftStateReader)
    r._my_name, r._last_level, r._last_gold = "", 1, 0
    r._confirmed_stage, r._confirmed_round = 1, 1
    r._ocr, r._ocr_cache, r._ocr_lock = None, {}, threading.Lock()
    state = r._parse(raw)
    assert state["is_dead"] is False
    assert state["health"] is None  # unknown -> OCR fallback, none here


def test_partial_lobby_is_not_served(eog_file):
    # The start-of-game placeholder is health -1 AND ffaStanding -1 (QA N10):
    # unknown, so no lobby and no count. A negative HP on a SCORED entry is an
    # elimination instead (tft/local_player.player_status, S135 N13).
    d = _fixture()
    d["statsBlock"]["players"][3]["health"] = -1
    d["statsBlock"]["players"][3]["ffaStanding"] = -1
    eog_file.write_text(json.dumps(d), encoding="ascii")
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    assert "players" not in lc
    assert lc["players_alive"] is None


def test_as_of_labels_the_round_file(eog_file):
    """Match 3 QA N11: the file is rewritten at combat start / eliminations
    only; board / HP / placement carry the write's game clock + age."""
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    a = lc["as_of"]
    assert a["game_s"] == _fixture()["statsBlock"]["gameLengthSeconds"]
    assert a["clock"] == "12:21"
    assert a["age_s"] >= 0
    assert a["basis"] == "combat_start"
    from dashboard import _state_builder as sb
    out = sb.tft_coach_for_standalone({"mode": "tft"}, "x.json", lc)
    assert out["tft_as_of"] == a


def test_two_marked_players_and_no_id_name_no_local_player(eog_file):
    """S135 N13 (reconciled at the s135 landing): two isInteractable entries
    with no LCU id to tell them apart is the human-lobby ambiguity, so the
    local player is UNKNOWN - never the first flagged entry. The lobby still
    renders (every status is known) with no "you" row; no local HP, standing
    or board is served and the synthesized allgamedata names no local row."""
    d = _fixture()
    for p in d["statsBlock"]["players"][:2]:
        p["isInteractable"] = True
    eog_file.write_text(json.dumps(d), encoding="ascii")
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    assert lc["players"] and sum(1 for r in lc["players"] if r["you"]) == 0
    assert "hp" not in lc and "board" not in lc
    raw = ts.synth_allgamedata(lcu=LCU, running=True)
    assert [p for p in raw["allPlayers"] if p["summonerName"] == ts.LOCAL_NAME] == []
    assert raw["rc_standalone"]["local"] == {}
    assert "currentHP" not in raw["activePlayer"]


def test_engine_written_board_rows_win_over_the_file(eog_file):
    from dashboard import _state_builder as sb
    lc = ts.standalone_liveclient_summary(LCU, running=True)
    mine = [{"name": "Engine", "star": 3, "items": []}]
    out = sb.tft_coach_for_standalone({"tft_board": mine}, "x.json", lc)
    assert out["tft_board"] == mine
    empty = sb.tft_coach_for_standalone({"tft_board": []}, "x.json", lc)
    assert empty["tft_board"] == lc["board"]  # an empty list is blank
