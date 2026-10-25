"""S134 P0: RC was blind to TFT games on the standalone Unreal TFT client.

Measured live 2026-10-25 (gameId-scoped evidence in the gitignored
ops/runtime/tft_qa/TFT_CLIENT_PROBE.md): TFT now runs as its own process
``TFTClient-Win64-Shipping.exe`` (launcher ``TFTClient.exe``), nothing listens
on :2999, the LCU still reports gameflow ``InProgress`` with a TFT queue, and
the client rewrites ``%LOCALAPPDATA%/TFT/Saved/Logs/TFTEoGStats.json`` once per
round (all 8 players: health, standing, board pieces). Before this fix RC fell
back to mode ``client`` and served Summoner's Rift callouts, and the vision
foreground gate refused every frame because it only knew League's image name.

These tests pin the standalone source, its routing into the existing TFT
pipeline (no frozen file touched), the vision gate, and the dashboard mode.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from tft import tft_standalone as ts

LOCAL_IMAGE = "TFTClient-Win64-Shipping.exe"


def _eog(game_id=1000000911, length=828, local_hp=74, mode="TFT"):
    return {
        "gameId": game_id,
        "gameMode": mode,
        "isRanked": False,
        "queueId": 1090,
        "queueType": "NORMAL_TFT",
        "statsBlock": {
            "gameLengthSeconds": length,
            "setCoreName": "TFTSet18",
            "players": [
                {"isInteractable": False, "health": 92, "ffaStanding": 3,
                 "boardPieces": [{"championName": "DA_18_Rakan",
                                  "starLevel": 2, "itemNames": []}],
                 "summonerName": "someone-else"},
                {"isInteractable": True, "health": local_hp, "ffaStanding": 2,
                 "boardPieces": [
                     {"championName": "DA_18_Yorick", "starLevel": 2,
                      "itemNames": ["TFT_Item_A", "TFT_Item_B"]},
                     {"championName": "DA_Karma18", "starLevel": 1,
                      "itemNames": []},
                     {"championName": "DA_Gromp18_AP", "starLevel": 1,
                      "itemNames": []},
                 ],
                 "summonerName": "operator-name"},
                {"isInteractable": False, "health": 0, "ffaStanding": 8,
                 "boardPieces": [], "summonerName": "out"},
            ],
        },
    }


@pytest.fixture
def eog_file(tmp_path, monkeypatch):
    p = tmp_path / "TFTEoGStats.json"
    p.write_text(json.dumps(_eog()), encoding="utf-8")
    monkeypatch.setattr(ts, "eog_stats_path", lambda: p)
    return p


@pytest.fixture(autouse=True)
def _clear_caches():
    ts._reset_caches_for_tests()
    yield
    ts._reset_caches_for_tests()


# -- process detection -------------------------------------------------------

def test_standalone_images_cover_game_and_launcher():
    assert "tftclient-win64-shipping.exe" in ts.STANDALONE_IMAGES
    assert "tftclient.exe" in ts.STANDALONE_IMAGES


def test_running_true_for_shipping_process():
    assert ts.standalone_client_running(names=["explorer.exe", LOCAL_IMAGE])


def test_running_false_for_league_only():
    assert not ts.standalone_client_running(
        names=["League of Legends.exe", "LeagueClientUx.exe"])


def test_running_false_for_launcher_only_without_game_binary():
    # The launcher alone is not the game window; detection keys on the
    # Unreal shipping binary, the process that owns the "TFT" window.
    assert not ts.standalone_client_running(names=["TFTClient.exe"])


def test_suite_never_sees_the_real_tft_client():
    """tests/conftest.py ``_no_live_standalone_tft`` is in force: even while
    the operator plays TFT on this host, the suite reads no client."""
    assert ts._process_snapshot() == {}
    assert ts.standalone_client_running() is False
    assert ts._game_create_time() is None


def test_running_probe_failure_reads_not_running(monkeypatch):
    def boom():
        raise OSError("no process list")
    monkeypatch.setattr(ts, "_process_snapshot", boom)
    assert ts.standalone_client_running() is False


def test_one_cached_walk_serves_running_and_create_time(monkeypatch):
    calls = []

    def snap():
        calls.append(1)
        return {"tftclient-win64-shipping.exe": 1000.0, "explorer.exe": 5.0}
    monkeypatch.setattr(ts, "_process_snapshot", snap)
    assert ts.standalone_client_running() is True
    assert ts._game_create_time() == 1000.0
    assert ts.standalone_client_running() is True
    assert len(calls) == 1  # cached: no second walk inside the TTL


# -- queue / phase verdict ---------------------------------------------------------

@pytest.mark.parametrize("lcu,verdict", [
    (None, None),
    ({}, None),
    ({"phase": "Lobby"}, False),
    ({"phase": "InProgress"}, True),  # older LCU agent: phase alone
    ({"phase": "InProgress", "game_queue_mode": "TFT",
      "game_queue_id": 1090}, True),
    ({"phase": "GameStart", "game_queue_mode": "ARAM",
      "game_queue_id": 450}, False),
    ({"phase": "InProgress", "game_queue_mode": "CLASSIC",
      "game_queue_id": 420}, False),
    ({"phase": "InProgress", "game_queue_id": 1100}, True),
    ({"phase": "InProgress", "game_queue_id": 450}, False),
    ({"phase": "InProgress", "game_queue_id": 999999}, True),  # unmapped id
])
def test_lcu_tft_verdict(lcu, verdict):
    assert ts.lcu_tft_verdict(lcu) is verdict


def test_aram_loading_with_lingering_tft_binary_is_not_tft(eog_file, monkeypatch):
    """Verifier risk 3: the TFT binary still running while an ARAM game loads
    (phase GameStart, :2999 not up yet) must not route to TFT."""
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    lcu = {"phase": "GameStart", "game_queue_mode": "ARAM",
           "game_queue_id": 450}
    assert ts.synth_allgamedata(lcu=lcu) is None
    assert sb.resolve_mode_key(dict(_HEALTH_CLIENT), lcu)[0] != "tft"


def _no_scan(monkeypatch):
    def boom(**kw):
        raise AssertionError("process walk on a no-TFT tick")
    monkeypatch.setattr(ts, "standalone_client_running", boom)


def test_lobby_status_and_synth_never_scan(eog_file, monkeypatch):
    """Verifier finding 1: a TFT lobby pre-flips mode_key to tft, and the
    tft_live status / synth must decide from the LCU phase alone."""
    _no_scan(monkeypatch)
    st = ts.tft_live_status({"phase": "Lobby"})
    assert st["source"] == "none"
    assert ts.synth_allgamedata(lcu={"phase": "Lobby"}) is None
    assert ts.standalone_liveclient_summary({"phase": "Lobby"}) == {}


def test_no_lcu_and_no_fresh_file_never_scans(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "eog_stats_path", lambda: tmp_path / "none.json")
    _no_scan(monkeypatch)
    assert ts.synth_allgamedata(lcu=None) is None


def test_snapshot_shape_stamps_the_in_game_queue(monkeypatch):
    from lcu import snapshot_shape
    # the draft recorder may persist a pending draft under the game id
    monkeypatch.setattr(snapshot_shape._draft_log, "note_game_id",
                        lambda gid: None)
    monkeypatch.setattr(snapshot_shape, "_maybe_refresh_mastery",
                        lambda request: None)

    def request(method, path):
        assert method == "GET"
        if path == "/lol-gameflow/v1/gameflow-phase":
            return "InProgress", None
        if path == "/lol-gameflow/v1/session":
            return {"gameData": {"gameId": 1000000911,
                                 "queue": {"id": 1090, "gameMode": "TFT"}}}, None
        return None, None
    state = snapshot_shape.shape_snapshot(request, {}, enrich=False)
    assert state["game_queue_id"] == 1090
    assert state["game_queue_mode"] == "TFT"
    assert ts.lcu_tft_verdict(state) is True


# -- name cleanup ------------------------------------------------------------

@pytest.mark.parametrize("raw,clean", [
    ("DA_18_Yorick", "Yorick"),
    ("DA_Karma18", "Karma"),
    ("DA_Gromp18_AP", "Gromp"),
    ("DA_18_RekSai", "RekSai"),
    ("", ""),
    (None, ""),
])
def test_clean_unit_name(raw, clean):
    assert ts.clean_unit_name(raw) == clean


# -- EoG reader ----------------------------------------------------------------

def test_read_eog_fresh(eog_file):
    d = ts.read_eog(now=time.time())
    assert d is not None and d["gameId"] == 1000000911


def test_read_eog_stale_is_none(eog_file):
    old = time.time() - 3600
    os.utime(eog_file, (old, old))
    assert ts.read_eog(now=time.time()) is None


def test_read_eog_non_tft_is_none(eog_file):
    eog_file.write_text(json.dumps(_eog(mode="CLASSIC")), encoding="utf-8")
    assert ts.read_eog(now=time.time()) is None


def test_read_eog_garbage_is_none(eog_file):
    eog_file.write_text("{not json", encoding="utf-8")
    assert ts.read_eog(now=time.time()) is None


def test_read_eog_missing_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "eog_stats_path", lambda: tmp_path / "nope.json")
    assert ts.read_eog(now=time.time()) is None


# -- synthesized allgamedata ------------------------------------------------------

def _synth(**kw):
    kw.setdefault("running", True)
    kw.setdefault("lcu", {"phase": "InProgress", "game_id": "1000000911"})
    return ts.synth_allgamedata(**kw)


def test_synth_none_when_client_not_running(eog_file):
    assert _synth(running=False) is None


@pytest.mark.parametrize("phase", ["Lobby", "None", "EndOfGame",
                                   "WaitingForStats", "ChampSelect", ""])
def test_synth_none_outside_in_game_phases(eog_file, phase):
    assert _synth(lcu={"phase": phase}) is None


@pytest.mark.parametrize("phase", ["GameStart", "InProgress", "Reconnect"])
def test_synth_present_in_game_phases(eog_file, phase):
    raw = _synth(lcu={"phase": phase, "game_id": "1000000911"})
    assert raw is not None
    assert raw["gameData"]["gameMode"] == "TFT"


def test_synth_carries_eog_round_state(eog_file):
    raw = _synth()
    assert raw["rc_source"] == ts.SOURCE_TAG
    st = raw["rc_standalone"]
    assert st["live_api"] is False
    assert st["local"]["health"] == 74
    assert st["local"]["standing"] == 2
    assert [u["name"] for u in st["local"]["board"]] == ["Yorick", "Karma", "Gromp"]
    assert st["local"]["board"][0]["star"] == 2
    assert st["players_alive"] == 2
    # game clock = EoG game length + time since the per-round rewrite
    assert raw["gameData"]["gameTime"] >= 828
    # the local player is the active player; no real names are carried
    me = [p for p in raw["allPlayers"] if p["summonerName"] == ts.LOCAL_NAME]
    assert len(me) == 1 and me[0]["health"] == 74
    assert raw["activePlayer"]["summonerName"] == ts.LOCAL_NAME
    blob = json.dumps(raw)
    assert "operator-name" not in blob and "someone-else" not in blob


def test_synth_ignores_eog_from_another_game(eog_file):
    raw = _synth(lcu={"phase": "InProgress", "game_id": "111"})
    assert raw is not None
    assert raw["rc_standalone"]["local"] == {}
    assert raw["rc_standalone"]["eog"] is False


def test_synth_without_lcu_needs_fresh_eog(eog_file):
    assert _synth(lcu=None) is not None
    old = time.time() - 3600
    os.utime(eog_file, (old, old))
    assert _synth(lcu=None) is None


def test_synth_minimal_without_eog(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "eog_stats_path", lambda: tmp_path / "none.json")
    raw = _synth()
    assert raw is not None
    assert raw["gameData"]["gameMode"] == "TFT"
    assert raw["rc_standalone"]["eog"] is False


def test_standalone_in_game_from_lcu_snapshot(eog_file):
    assert ts.standalone_in_game({"phase": "InProgress"}, running=True)
    assert not ts.standalone_in_game({"phase": "Lobby"}, running=True)
    assert not ts.standalone_in_game({"phase": "InProgress"}, running=False)


# -- routing into the existing TFT pipeline (no frozen edits) --------------------

def test_synth_routes_to_mode_tft_through_normalizer(eog_file):
    from core.game_snapshot import MODE_TFT, mode_from_game_mode_string
    from game_reader import GameReader
    gr = GameReader.__new__(GameReader)
    state = gr._process_game(_synth())
    assert state is not None
    assert state["champion"] == "TFT"
    assert mode_from_game_mode_string(state["game_mode"]) == MODE_TFT
    assert state["hp_pct"] == 74


def test_read_game_falls_back_to_standalone_on_relay_404(eog_file, monkeypatch):
    from game_reader import GameReader
    gr = GameReader.__new__(GameReader)

    def relay_404():
        gr._relay_says_no_game = True
        return None
    monkeypatch.setattr(gr, "_try_relay", relay_404, raising=False)
    raw = _synth()  # built BEFORE the patch (the patch replaces synth itself)
    monkeypatch.setattr(ts, "synth_allgamedata", lambda **kw: raw)
    state = gr.read_game()
    assert state is not None and state["champion"] == "TFT"
    assert gr.is_in_game is True


def test_read_game_still_none_without_standalone(monkeypatch):
    from game_reader import GameReader
    gr = GameReader.__new__(GameReader)

    def relay_404():
        gr._relay_says_no_game = True
        return None
    monkeypatch.setattr(gr, "_try_relay", relay_404, raising=False)
    monkeypatch.setattr(ts, "synth_allgamedata", lambda **kw: None)
    assert gr.read_game() is None
    assert gr.is_in_game is False


def test_tft_state_reader_uses_standalone_when_2999_is_down(eog_file, monkeypatch):
    from tft import tft_state_reader as tsr
    r = tsr.TftStateReader.__new__(tsr.TftStateReader)
    r._ssl = None
    r._my_name = ""
    r._last_level = 1
    r._last_gold = 0
    r._confirmed_stage = 1
    r._confirmed_round = 1
    r._ocr = None
    r._ocr_cache = {}
    import threading
    r._ocr_lock = threading.Lock()

    def down(*a, **k):
        raise OSError("connection refused :2999")
    monkeypatch.setattr(tsr.urllib.request, "urlopen", down)
    raw = _synth()  # built BEFORE the patch (the patch replaces synth itself)
    monkeypatch.setattr(ts, "synth_allgamedata", lambda **kw: raw)
    state = r.read()
    assert state is not None
    assert state["health"] == 74
    assert state["board_size"] == 3
    assert "Yorick" in state["board_str"]
    assert state["data_source"] == ts.SOURCE_TAG


# -- vision gate -------------------------------------------------------------------

def test_vision_gate_accepts_tft_client(monkeypatch):
    from vision_server import _frame
    assert "tftclient-win64-shipping.exe" in _frame._GAME_CONTENT_IMAGES
    monkeypatch.setattr(_frame, "_foreground_image",
                        lambda: "tftclient-win64-shipping.exe")
    assert _frame._league_foreground() is True


# -- dashboard mode resolution -----------------------------------------------------

_HEALTH_CLIENT = {"mode": "client", "has_game": False, "aram_mode": False,
                  "arena_mode": False, "tft_mode": False}


def test_resolve_mode_key_standalone_tft(monkeypatch):
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    mk, pre = sb.resolve_mode_key(dict(_HEALTH_CLIENT), {"phase": "InProgress"})
    # a running game, not a lobby pre-flip: B4 live suppression must apply
    assert (mk, pre) == ("tft", False)


def test_standalone_mirror_raises_tft_mode_and_live_gate(monkeypatch):
    from core.live_game_gate import is_live_game
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    h = sb.apply_standalone_tft_mirror(dict(_HEALTH_CLIENT),
                                       {"phase": "InProgress"})
    assert h["tft_mode"] is True
    assert is_live_game(h, False) is True
    assert _HEALTH_CLIENT["tft_mode"] is False  # copy, not mutate
    # lobby / no client: untouched
    assert sb.apply_standalone_tft_mirror(
        dict(_HEALTH_CLIENT), {"phase": "Lobby"})["tft_mode"] is False
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: False)
    assert sb.apply_standalone_tft_mirror(
        dict(_HEALTH_CLIENT), {"phase": "InProgress"})["tft_mode"] is False


def test_standalone_mirror_never_overrides_another_live_flag(monkeypatch):
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    h = dict(_HEALTH_CLIENT, has_game=True)
    assert sb.apply_standalone_tft_mirror(h, {"phase": "InProgress"}) is h


def test_lobby_phase_never_scans_processes(monkeypatch):
    from dashboard import _state_builder as sb

    def boom(**kw):
        raise AssertionError("process scan outside an in-game phase")
    monkeypatch.setattr(ts, "standalone_client_running", boom)
    assert sb.standalone_tft_live({"phase": "Lobby"}) is False
    assert sb.standalone_tft_live(None) is False


def test_resolve_mode_key_not_tft_when_client_absent(monkeypatch):
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: False)
    mk, _ = sb.resolve_mode_key(dict(_HEALTH_CLIENT), {"phase": "InProgress"})
    assert mk == "client"


def test_resolve_mode_key_not_tft_in_lobby(monkeypatch):
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    mk, _ = sb.resolve_mode_key(dict(_HEALTH_CLIENT), {"phase": "Lobby"})
    assert mk == "client"


def test_resolve_mode_key_live_flags_still_win(monkeypatch):
    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    h = dict(_HEALTH_CLIENT, aram_mode=True)
    assert sb.resolve_mode_key(h, {"phase": "InProgress"}) == ("aram", False)


def test_standalone_liveclient_summary_is_honest(eog_file):
    lc = ts.standalone_liveclient_summary(
        {"phase": "InProgress", "game_id": "1000000911"}, running=True)
    assert lc["source"] == ts.SOURCE_TAG
    assert lc["live_api"] is False
    assert lc["game_mode"] == "TFT"
    assert lc["hp"] == 74
    assert "champion" not in lc  # no SR champion field to mislead SR consumers
    assert ts.standalone_liveclient_summary({"phase": "Lobby"}, running=True) == {}


def test_tft_live_status_lines(eog_file):
    st = ts.tft_live_status({"phase": "InProgress", "game_id": "1000000911"},
                            running=True, live_api=False)
    assert st["source"] == ts.SOURCE_TAG
    assert st["live_api"] is False
    assert "vision" in st["line"].lower()
    off = ts.tft_live_status({"phase": "InProgress"}, running=False,
                             live_api=True)
    assert off["source"] == "live_client"


# -- end to end through build_state (the recorder's measured scenario) ----------

def test_build_state_standalone_tft_serves_no_rift_text(eog_file, monkeypatch):
    """Replays the S134 recorder evidence: health says client (no :2999), the
    LCU says InProgress, the TFT game binary runs. Pre-fix /api/state served
    mode_key client + "Drake spawns 5:00"; now it must be an honest TFT state."""
    from unittest import mock

    from dashboard import _state_builder as sb
    monkeypatch.setattr(ts, "standalone_client_running", lambda **kw: True)
    health = {"alive": True, "mode": "client", "has_game": False,
              "aram_mode": False, "arena_mode": False, "tft_mode": False}
    rift_coach = {"mode": "client", "action": "", "immediate": "",
                  "fight_rule": "", "risk": "", "choices": []}

    def _read_json(p):
        return health if "health" in str(p) else dict(rift_coach)

    lcu = {"phase": "InProgress", "game_id": "1000000911"}
    with mock.patch.object(sb, "read_json", side_effect=_read_json), \
            mock.patch.object(sb, "lcu_summary", return_value=lcu), \
            mock.patch.object(sb, "liveclient_summary", return_value={}), \
            mock.patch.object(sb, "get_team_context", return_value=None), \
            mock.patch.object(sb, "validate_coaching_payload",
                              lambda *_a, **_kw: None):
        state = sb.build_state()
    assert state["mode_key"] == "tft"
    assert state["coach_source"].endswith("tft_coaching_data.json")
    assert state["health"]["tft_mode"] is True
    assert state["callouts"] == []
    blob = json.dumps(state)
    assert "Drake" not in blob and "Herald" not in blob
    lc = state["liveclient"]
    assert lc["source"] == ts.SOURCE_TAG and lc["live_api"] is False
    assert lc["hp"] == 74
    assert state["coach"]["tft_live"]["source"] == ts.SOURCE_TAG
    assert "vision" in state["coach"]["tft_live"]["line"].lower()
