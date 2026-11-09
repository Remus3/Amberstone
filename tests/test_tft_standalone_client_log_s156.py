"""S156 S7: a TFT match on the standalone client while League idles.

Measured live 2026-11-08: the Riot Client now launches the TFT client
directly (install ``Teamfight Tactics/Live``, client 18.6.0, its own lobby
and queue). The League client stays up but idle: gameflow phase ``None``, no
session, nothing on :2999. ``lcu_tft_verdict`` read every non-game phase as
"no TFT match", and the idle string ``None`` is one, so a standalone match
read as not-in-game for its whole length.

The client's own Unreal log (``TFT.log`` beside the per-round file) names the
match state: ``Entering LobbyState[ETFTLobbyState::InGame]`` when the match
starts, a remote ``UEngine::Browse`` to the game server, the gsm
``IN_PROGRESS`` push carrying the game id, then ``Bootstrap?closed`` and
``EndOfGame*`` lobby states when it ends. The lines below are TEMPLATED from
the measured shapes (ids, addresses and keys replaced).
"""
from __future__ import annotations

import json
import os
import time

import pytest

from tft import tft_standalone as ts

GAME_ID = 1000000911
SID = 2000000000000077

HEADER = "Log file open, 11/08/26 19:58:51\n"
STARTUP = [
    '[2026.11.09-01.58.55:635][  0]LogGlobalStatus: UEngine::Browse Started '
    'Browse: "/Mode_Bootstrap/Bootstrap?Name=Player"',
    '[2026.11.09-01.59.00:924][  2]LogGlobalStatus: UEngine::Browse Started '
    'Browse: "/Game/Maps/Empty?GameModeName=Frontend_ChonccsTreasure18Halloween"',
]
QUEUE = [
    "[2026.11.08-20.28.04:950][403]TFT: [Standalone] TFTLobbySubsystem_21: "
    "Entering LobbyState[ETFTLobbyState::SoloMode]",
    "[2026.11.08-20.28.19:430][100]TFT: [Standalone] TFTLobbySubsystem_21: "
    "Entering LobbyState[ETFTLobbyState::Matchmaking]",
]
GSM_ESCAPED = (
    "[2026.11.08-20.31.32:460][987]RGIOPRiotGamesApiInternal: "
    "riot-messaging-service: Got message '{\"payload\":{\"resource\":"
    "\"lol-gsm-server/v1/gsm/game-update/IN_PROGRESS\",\"service\":\"gsm\","
    "\"payload\":\"{\\\"id\\\":%d,\\\"gameState\\\":\\\"IN_PROGRESS\\\","
    "\\\"playerCredentials\\\":{\\\"gameId\\\":%d,\\\"queueId\\\":1090,"
    "\\\"playerId\\\":%d,\\\"puuid\\\":\\\"p-uuid\\\"}}\"}}'"
)
GSM_PLAIN = (
    "[2026.11.08-20.31.32:468][987]RGIOPRms: Received RMS message ID 'x' for "
    "resource 'lol-gsm-server/v1/gsm/game-update/IN_PROGRESS' service 'gsm' "
    "payload '{\"id\":%d,\"gameState\":\"IN_PROGRESS\",\"playerCredentials\":"
    "{\"gameId\":%d,\"queueId\":1090,\"playerId\":%d,\"puuid\":\"p-uuid\"}}'"
)
REMOTE_BROWSE = (
    '[2026.11.08-20.31.32:476][988]LogGlobalStatus: UEngine::Browse Started '
    'Browse: "192.0.2.50:7377/Mode_Bootstrap/Bootstrap?PlayerKey="a2V5==""'
)
IN_GAME = ("[2026.11.08-20.31.35:600][300]TFT: [Standalone] TFTLobbySubsystem_21: "
           "Entering LobbyState[ETFTLobbyState::InGame]")
GAME_OVER = [
    '[2026.11.08-20.59.12:970][655]LogGlobalStatus: UEngine::Browse Started '
    'Browse: "/Mode_Bootstrap/Bootstrap?closed"',
    "[2026.11.08-20.59.15:301][691]TFT: [Standalone] TFTLobbySubsystem_21: "
    "Exiting LobbyState[ETFTLobbyState::InGame]",
    "[2026.11.08-20.59.15:301][691]TFT: [Standalone] TFTLobbySubsystem_21: "
    "Entering LobbyState[ETFTLobbyState::EndOfGameInterstitial]",
    "[2026.11.08-20.59.15:302][691]TFT: [Standalone] TFTLobbySubsystem_21: "
    "Entering LobbyState[ETFTLobbyState::EndOfGameSummary]",
]
NOISE = "[2026.11.08-20.40.00:000][  1]LogTemp: unrelated line " + "x" * 80


def _match_lines(gsm=GSM_PLAIN, game_id=GAME_ID, sid=SID):
    return STARTUP + QUEUE + [gsm % (game_id, game_id, sid), REMOTE_BROWSE,
                              IN_GAME]


def _eog(game_id=GAME_ID, local_hp=61):
    # a human lobby: every entry carries isInteractable (S135 N13), the client
    # zeroes the OTHER players' ids, the local entry carries its own
    return {
        "gameId": game_id, "gameMode": "TFT", "queueId": 1090,
        "statsBlock": {"gameLengthSeconds": 650, "setCoreName": "TFTSet18",
                       "players": [
                           {"isInteractable": True, "playerId": 0,
                            "health": 80, "ffaStanding": 3, "boardPieces": []},
                           {"isInteractable": True, "playerId": SID,
                            "health": local_hp, "ffaStanding": 2,
                            "boardPieces": [{"championName": "DA_18_Yorick",
                                             "starLevel": 2, "itemNames": []}]},
                           {"isInteractable": True, "playerId": 0,
                            "health": 0, "ffaStanding": 8, "boardPieces": []},
                       ]},
    }


@pytest.fixture(autouse=True)
def _clear_caches():
    ts._reset_caches_for_tests()
    yield
    ts._reset_caches_for_tests()


@pytest.fixture
def logs(tmp_path, monkeypatch):
    """A Saved/Logs dir: the per-round file and TFT.log side by side."""
    eog = tmp_path / "TFTEoGStats.json"
    monkeypatch.setattr(ts, "eog_stats_path", lambda: eog)
    log = tmp_path / "TFT.log"

    class _Logs:
        path = log
        eog_path = eog

        def write(self, lines, header=HEADER):
            log.write_bytes((header + "\n".join(lines) + "\n").encode("ascii"))

        def append(self, lines):
            with open(log, "ab") as fh:
                fh.write(("\n".join(lines) + "\n").encode("ascii"))

        def write_eog(self, **kw):
            eog.write_text(json.dumps(_eog(**kw)), encoding="utf-8")

    return _Logs()


def _state(**kw):
    kw.setdefault("force", True)
    return ts.client_log_state(**kw)


# -- the reported defect -------------------------------------------------------

def test_league_idle_phase_none_standalone_match_reads_in_game(logs):
    """THE DEFECT: League idle (phase 'None') while a standalone match runs.
    Before the fix lcu_tft_verdict returned False and synth returned None."""
    logs.write(_match_lines())
    logs.write_eog()
    idle = {"phase": "None"}
    assert ts.lcu_tft_verdict(idle) is True
    assert ts.standalone_in_game(idle, running=True) is True
    raw = ts.synth_allgamedata(lcu=idle, running=True)
    assert raw is not None
    assert raw["gameData"]["gameMode"] == "TFT"
    st = raw["rc_standalone"]
    # the game id comes from the client log, so the per-round file is
    # POSITIVELY this game's and its round state is served
    assert st["game_id"] == str(GAME_ID)
    assert st["eog"] is True
    # the local player by the log's own player id (the idle LCU carries none)
    assert st["local"]["health"] == 61
    assert st["local_basis"] == "summoner_id"


def test_no_league_at_all_log_in_game_reads_in_game(logs):
    """Riot Client + TFT only: no LCU snapshot at all."""
    logs.write(_match_lines(gsm=GSM_ESCAPED))
    logs.write_eog()
    assert ts.lcu_tft_verdict(None) is True
    assert ts.synth_allgamedata(lcu=None, running=True) is not None


def test_process_still_required(logs):
    """A log left at InGame by a crashed client is not a live match."""
    logs.write(_match_lines())
    logs.write_eog()
    assert ts.standalone_in_game({"phase": "None"}, running=False) is False
    assert ts.synth_allgamedata(lcu={"phase": "None"}, running=False) is None


def test_post_game_lobby_is_not_in_game_even_with_fresh_file(logs):
    """The per-round file stays fresh for EOG_MAX_AGE_S after a match; the
    client log says the lobby, so no LCU is no longer 'trust the file'."""
    logs.write(_match_lines() + GAME_OVER)
    logs.write_eog()
    assert _state()["verdict"] is False
    assert _state()["lobby_state"] == "EndOfGameSummary"
    assert ts.lcu_tft_verdict(None) is False
    assert ts.lcu_tft_verdict({"phase": "None"}) is False
    assert ts.synth_allgamedata(lcu=None, running=True) is None


def test_idle_league_without_client_log_stays_false(logs):
    """No TFT.log: the old verdict stands (a League idle phase is False)."""
    logs.write_eog()
    assert not logs.path.exists()
    assert ts.lcu_tft_verdict({"phase": "None"}) is False
    assert ts.lcu_tft_verdict(None) is None


# -- the League-launched path is unchanged ------------------------------------

def test_league_launched_tft_in_progress_unchanged(logs):
    logs.write_eog()
    lcu = {"phase": "InProgress", "game_id": str(GAME_ID),
           "game_queue_mode": "TFT"}
    assert ts.lcu_tft_verdict(lcu) is True
    raw = ts.synth_allgamedata(lcu=lcu, running=True)
    assert raw["rc_standalone"]["game_id"] == str(GAME_ID)


def test_league_in_game_with_other_queue_beats_the_log(logs):
    """An SR game in progress: a lingering TFT log never makes it TFT."""
    logs.write(_match_lines())
    lcu = {"phase": "InProgress", "game_queue_mode": "CLASSIC"}
    assert ts.lcu_tft_verdict(lcu) is False


# -- the log reader -------------------------------------------------------------

@pytest.mark.parametrize("lines, verdict, lobby", [
    (STARTUP[:1], None, ""),
    (STARTUP, False, ""),
    (STARTUP + QUEUE, False, "Matchmaking"),
    (STARTUP + QUEUE + [REMOTE_BROWSE], True, "Matchmaking"),
    (STARTUP + QUEUE + [REMOTE_BROWSE, IN_GAME], True, "InGame"),
    (STARTUP + QUEUE + [REMOTE_BROWSE, IN_GAME] + GAME_OVER[:1], False, "InGame"),
    (STARTUP + QUEUE + [REMOTE_BROWSE, IN_GAME] + GAME_OVER, False,
     "EndOfGameSummary"),
])
def test_log_state_machine(logs, lines, verdict, lobby):
    logs.write(lines)
    st = _state()
    assert st["verdict"] is verdict
    assert st["lobby_state"] == lobby


@pytest.mark.parametrize("gsm", [GSM_PLAIN, GSM_ESCAPED])
def test_game_id_and_player_id_from_both_gsm_shapes(logs, gsm):
    logs.write(_match_lines(gsm=gsm))
    st = _state()
    assert st["game_id"] == str(GAME_ID)
    assert st["summoner_id"] == SID


def test_incremental_append_and_rotation(logs):
    logs.write(STARTUP + QUEUE)
    assert _state()["verdict"] is False
    logs.append([GSM_PLAIN % (GAME_ID, GAME_ID, SID), REMOTE_BROWSE, IN_GAME])
    assert _state()["verdict"] is True
    logs.append(GAME_OVER)
    assert _state()["verdict"] is False
    # a relaunch rotates the log: a new header restarts the state
    logs.write(STARTUP[:1], header="Log file open, 11/09/26 09:00:00\n")
    st = _state()
    assert st["verdict"] is None
    assert st["game_id"] == ""


def test_partial_last_line_waits_for_its_newline(logs):
    logs.write(STARTUP + QUEUE)
    with open(logs.path, "ab") as fh:
        fh.write(IN_GAME[:60].encode("ascii"))
    assert _state()["lobby_state"] == "Matchmaking"
    with open(logs.path, "ab") as fh:
        fh.write((IN_GAME[60:] + "\n").encode("ascii"))
    assert _state()["lobby_state"] == "InGame"


def test_stale_log_cannot_say_in_game(logs):
    logs.write(_match_lines())
    old = time.time() - ts.CLIENT_LOG_MAX_AGE_S - 60
    os.utime(logs.path, (old, old))
    assert _state()["verdict"] is None
    assert ts.lcu_tft_verdict({"phase": "None"}) is False


def test_bounded_catch_up(logs, monkeypatch):
    """A big log is read at most CLIENT_LOG_READ_CAP per call and is
    'unknown' until caught up - never a verdict from half a file."""
    monkeypatch.setattr(ts, "CLIENT_LOG_READ_CAP", 4096)
    logs.write(STARTUP + QUEUE + [NOISE] * 200 + [REMOTE_BROWSE, IN_GAME])
    size = logs.path.stat().st_size
    seen = []
    for _ in range(size // 4096 + 3):
        seen.append(_state()["verdict"])
    assert seen[0] is None
    assert seen[-1] is True
    assert ts._client_log["offset"] == size


def test_throttle_serves_the_cached_state(logs):
    logs.write(_match_lines())
    assert ts.client_log_state()["verdict"] is True
    logs.append(GAME_OVER)
    # within CLIENT_LOG_MIN_INTERVAL_S the cached state is served
    assert ts.client_log_state()["verdict"] is True
    assert ts.client_log_state(force=True)["verdict"] is False


def test_never_raises_on_junk(logs):
    logs.path.write_bytes(b"\xff\xfe\x00junk\n" * 50 + b"\n")
    assert _state()["verdict"] is None
    logs.path.unlink()
    logs.path.mkdir()
    assert _state()["verdict"] is None


def test_identity_never_logged(logs, caplog):
    caplog.set_level("DEBUG", logger="rc.tft.standalone")
    logs.write(_match_lines())
    logs.write_eog()
    ts.synth_allgamedata(lcu={"phase": "None"}, running=True)
    assert str(SID) not in caplog.text
    assert "p-uuid" not in caplog.text


def test_suite_reads_no_real_client_log():
    """conftest points eog_stats_path at a path that never exists, so the
    log beside it never exists either: no test sees the operator's log."""
    assert not ts.client_log_path().exists()
    assert ts.client_log_state(force=True)["verdict"] is None
