"""Postgame collector: the gameflow phase route (D5) and the TFT branch (RM-616).

D5, MEASURED (s134 post-match QA, QA_REPORT.md section 1 D5, and re-measured
by a passive GET in Lobby this session): `GET /lol-gameflow/v1/phase` answers
404 "Invalid URI format"; `GET /lol-gameflow/v1/gameflow-phase` answers 200
with the phase string ("PreEndOfGame" after the TFT match, "Lobby" now). So
`PostgameCollector._get_gameflow_phase` (lcu/lcu_postgame_collector.py) never
saw EndOfGame and every capture fell through to the match-history fallback,
and `LcuPregame.get_gameflow_phase` (lcu/lcu_pregame.py) could only fail.

TFT, MEASURED: eog-stats-block and champion-mastery-updates 404 for TFT. The
TFT document is `/lol-end-of-game/v1/tft-eog-stats`, served in PreEndOfGame /
EndOfGame only (404 in Lobby, LCU_TFT_INVENTORY.md section 2); the TFT
match-history route answers in any phase. The standalone TFT client gives RC
no Live Client feed (QA D1), so the lifecycle game-end trigger may never fire
for a TFT game: the collector's idle tick watches the LCU itself.

N4 (match-2 QA, ops/runtime/tft_qa/20261025-081234/QA_REPORT.md):
`/lol-end-of-game/v1/gameclient-eog-stats-block` DOES serve TFT post-game (the
listener saw it Created at game end with statsBlock.players n=8; a live GET in
PreEndOfGame answered 200 with the game's id) - the collector asked for the
misspelled `game-client-eog-stats-block`, which 404s "Invalid URI format". Its
shape is the per-round TFTEoGStats.json document (docs/TFT_PROGRAM.md section
0 item 2: statsBlock.players[] with isInteractable = local, ffaStanding,
health, boardPieces {championName, starLevel, itemNames, price}). With the
spelling fixed, a TFT block reached through the LoL path must go to the TFT
store, never be saved as a Summoner's Rift match.

Every LCU call here is stubbed; the stubs record the paths requested, and the
tests assert GET routes only by those paths (the collector has no non-GET
code path - `_lcu_get` builds a urllib Request without a method).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tests import _repo_walk
from tft import tft_placement as tp

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
EOG_DOC = json.loads((FIX / "tft_eog_stats_set18.json").read_text(encoding="utf-8"))
HIST_DOC = json.loads((FIX / "tft_match_history_set18.json").read_text(encoding="utf-8"))
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"
GID = 1000000001

SESSION_TFT = {"phase": "PreEndOfGame",
               "gameData": {"gameId": GID, "queue": {"id": 1090, "gameMode": "TFT"}},
               "map": {"gameMode": "TFT"}}


@pytest.fixture
def pgc(tmp_path, monkeypatch):
    import lcu.lcu_postgame_collector as mod
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "pg.db")
    monkeypatch.setattr(tp, "_STORE_DIR", tmp_path / "tft_matches")
    mod._ensure_schema()
    return mod


class _Lcu:
    """Path -> body router; records every path requested."""

    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls: list[str] = []

    def __call__(self, path):
        self.calls.append(path)
        for prefix, body in self.routes.items():
            if path == prefix or path.startswith(prefix):
                return body() if callable(body) else body
        return None


def _collector(mod, routes):
    c = mod.PostgameCollector.__new__(mod.PostgameCollector)
    c._trigger_at = None
    c._POLL_INTERVAL = 0.0
    c._FETCH_DELAY = 0.0
    c._lcu_get = _Lcu(routes)
    return c


def _history_route():
    return f"/lol-match-history/v1/products/tft/{LOCAL_PUUID}/matches"


# -- D5: the phase route -----------------------------------------------------

def test_collector_polls_the_measured_gameflow_phase_route(pgc):
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "PreEndOfGame"})
    assert c._get_gameflow_phase() == "PreEndOfGame"
    assert c._lcu_get.calls == ["/lol-gameflow/v1/gameflow-phase"]


def test_collector_phase_non_string_is_empty(pgc):
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": {"x": 1}})
    assert c._get_gameflow_phase() == ""


_DEAD_ROUTE = re.compile(r"^/lol-gameflow/v1/phase(?![-\w])")


def _route_literals(src: str):
    """String constants (f-string segments included) that BEGIN with a
    route - a request literal, never prose in a comment or docstring."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_route_literal_scan_has_a_positive_control():
    src = 'x = f"https://{h}:{p}/lol-gameflow/v1/phase"\n"""doc /lol-gameflow/v1/phase"""\n'
    hits = [v for v in _route_literals(src) if _DEAD_ROUTE.match(v)]
    assert hits == ["/lol-gameflow/v1/phase"]
    assert not _DEAD_ROUTE.match("/lol-gameflow/v1/gameflow-phase")


def test_no_python_file_requests_the_404_phase_route():
    """Sibling sweep: every request literal of the dead route, over every
    tracked Python file outside tests (the repo walk is the git index)."""
    hits, scanned = [], set()
    for path in _repo_walk.repo_files(patterns=("*.py",)):
        rel = _repo_walk.relative_posix(path)
        if rel.startswith("tests/"):
            continue
        try:
            vals = list(_route_literals(path.read_text(encoding="utf-8")))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        scanned.add(rel)
        if any(_DEAD_ROUTE.match(v) for v in vals):
            hits.append(rel)
    # Anchor: an empty enumeration must not pass as clean.
    assert {"lcu/lcu_postgame_collector.py", "lcu/lcu_pregame.py"} <= scanned
    assert hits == []


# -- TFT EOG fast path ---------------------------------------------------------

def test_tft_capture_reads_the_tft_route_and_persists_the_game(pgc):
    c = _collector(pgc, {tp.EOG_PATH: EOG_DOC,
                         "/lol-gameflow/v1/session": SESSION_TFT})
    assert c._capture("TFT") is True
    assert tp.EOG_PATH in c._lcu_get.calls
    for lol in ("/lol-end-of-game/v1/eog-stats-block",
                "/lol-match-history/v1/products/lol/"):
        assert not any(p.startswith(lol) for p in c._lcu_get.calls), lol
    rec = tp.load(GID)
    assert rec["sources"] == ["eog"]
    assert rec["local_placement"] == 1 and rec["local_hp"] == 100
    assert len(rec["players"]) == 8


def test_tft_capture_retains_the_raw_eog_document(pgc, tmp_path):
    import sqlite3

    from core import raw_documents as rd
    c = _collector(pgc, {tp.EOG_PATH: EOG_DOC,
                         "/lol-gameflow/v1/session": SESSION_TFT})
    assert c._capture("TFT") is True
    conn = sqlite3.connect(str(tmp_path / "pg.db"))
    try:
        assert rd.kinds_for(conn, str(GID)) == ["eog"]
        kept = rd.load(conn, str(GID), "eog")
    finally:
        conn.close()
    # Scrubbed: boards survive, identities do not (the db is local but the
    # store contract is "nothing identifying", s134 verifier finding).
    assert kept["players"][0]["boardPieces"][0]["championId"] == "DA_Draven18"
    _assert_no_identity(kept)


def _assert_no_identity(doc):
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    found = set(keys(doc)) & set(tp.IDENTITY_KEYS)
    assert not found, found
    blob = json.dumps(doc)
    assert "player1" not in blob and LOCAL_PUUID not in blob


def test_history_backfill_retains_a_scrubbed_match_document(pgc, tmp_path):
    import sqlite3

    from core import raw_documents as rd
    c = _collector(pgc, {"/lol-summoner/v1/current-summoner": {"puuid": LOCAL_PUUID},
                         _history_route(): HIST_DOC})
    assert c._tft_history_backfill() == 1
    conn = sqlite3.connect(str(tmp_path / "pg.db"))
    try:
        kept = rd.load(conn, str(GID), "match")
    finally:
        conn.close()
    assert kept["json"]["participants"][0]["units"]
    assert "participants" not in kept["metadata"]
    _assert_no_identity(kept)


def test_backfill_is_retried_when_the_first_read_fails(pgc):
    me = {"v": None}
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "Lobby",
                         "/lol-summoner/v1/current-summoner": lambda: me["v"],
                         _history_route(): HIST_DOC})
    c._idle_tick()                    # summoner not readable yet
    assert c._tft_state()["backfilled"] is False
    assert tp.has_record(GID) is False
    me["v"] = {"puuid": LOCAL_PUUID}
    c._tft_state()["history_next_at"] = 0.0     # the 60 s throttle elapsed
    c._idle_tick()
    assert c._tft_state()["backfilled"] is True
    assert tp.has_record(GID, tp.SOURCE_HISTORY)


def test_a_failing_store_write_warns_once_per_game(pgc, monkeypatch, caplog):
    import logging

    def boom(rec, store_dir=None):
        raise OSError("disk full")
    monkeypatch.setattr(tp, "persist", boom)
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "PreEndOfGame",
                         "/lol-gameflow/v1/session": SESSION_TFT,
                         tp.EOG_PATH: EOG_DOC})
    with caplog.at_level(logging.DEBUG, logger="rc.postgame"):
        for _ in range(3):
            c._idle_tick()
    warn = [r for r in caplog.records if r.levelno == logging.WARNING
            and "not stored" in r.getMessage()]
    assert len(warn) == 1


def test_tft_capture_refuses_a_previous_games_document(pgc):
    """The EOG document still holds the PREVIOUS game until the new one is
    ready - matched on the gameflow session gameId (QA section 4)."""
    stale = dict(SESSION_TFT, gameData={"gameId": GID + 1,
                                        "queue": {"gameMode": "TFT"}})
    c = _collector(pgc, {tp.EOG_PATH: EOG_DOC, "/lol-gameflow/v1/session": stale})
    assert c._capture_from_eog("TFT") is False
    assert tp.has_record(GID) is False


def test_tft_capture_without_eog_falls_back_to_history(pgc):
    c = _collector(pgc, {"/lol-summoner/v1/current-summoner": {"puuid": LOCAL_PUUID},
                         _history_route(): HIST_DOC,
                         "/lol-gameflow/v1/session": SESSION_TFT})
    assert c._capture("TFT") is True
    rec = tp.load(GID)
    assert rec["sources"] == ["history"]
    assert rec["players"][0]["level"] == 9


def test_lol_capture_is_unchanged_for_classic(pgc):
    """A CLASSIC capture never touches the TFT routes."""
    c = _collector(pgc, {})
    c._fetch_eog_stats_block = lambda: None
    c._capture_via_history = lambda mode: False
    assert c._capture("CLASSIC") is False
    assert not any("tft" in p for p in c._lcu_get.calls)


# -- the trigger loop ------------------------------------------------------------

def test_loop_keeps_polling_eog_in_pre_end_of_game_before_history(pgc):
    """D5 consequence: with the phase route fixed, PreEndOfGame is seen. A
    document that is not ready on the first poll must be retried, not given up
    on in favour of a history fallback that may still hold the previous game."""
    seq = iter([None, None, EOG_DOC])
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "PreEndOfGame",
                         tp.EOG_PATH: lambda: next(seq, EOG_DOC),
                         "/lol-gameflow/v1/session": SESSION_TFT})
    c._EOG_TIMEOUT_S = 30
    c._stop = __import__("threading").Event()
    hist = []
    c._capture_history_fallback = lambda mode: hist.append(mode) or False
    c._capture_after_trigger("TFT")
    assert c._lcu_get.calls.count(tp.EOG_PATH) == 3
    assert hist == []
    assert tp.has_record(GID, tp.SOURCE_EOG)


def test_loop_falls_back_to_history_at_the_deadline(pgc):
    import threading
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "InProgress"})
    c._EOG_TIMEOUT_S = 0
    c._stop = threading.Event()
    hist = []
    c._capture_history_fallback = lambda mode: hist.append(mode) or True
    c._capture_after_trigger("CLASSIC")
    assert hist == ["CLASSIC"]


# -- the idle tick (no lifecycle trigger: standalone TFT client, QA D1) ---------

def test_idle_tick_captures_a_tft_post_game_without_a_trigger(pgc):
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "PreEndOfGame",
                         "/lol-gameflow/v1/session": SESSION_TFT,
                         tp.EOG_PATH: EOG_DOC})
    c._idle_tick()
    assert tp.has_record(GID, tp.SOURCE_EOG)
    calls = list(c._lcu_get.calls)
    c._idle_tick()                    # already stored: no second EOG read
    assert c._lcu_get.calls[len(calls):].count(tp.EOG_PATH) == 0


def test_idle_tick_ignores_a_lol_post_game(pgc):
    lol = {"phase": "EndOfGame", "gameData": {"gameId": 77, "queue": {"gameMode": "CLASSIC"}},
           "map": {"gameMode": "CLASSIC"}}
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "EndOfGame",
                         "/lol-gameflow/v1/session": lol, tp.EOG_PATH: EOG_DOC})
    c._idle_tick()
    assert tp.EOG_PATH not in c._lcu_get.calls
    assert tp.has_record(GID) is False
    n = len(c._lcu_get.calls)
    c._idle_tick()                    # same post-game screen: phase read only
    assert c._lcu_get.calls[n:] == ["/lol-gameflow/v1/gameflow-phase"]


def test_idle_tick_with_the_lcu_down_makes_one_call(pgc):
    c = _collector(pgc, {})
    c._idle_tick()
    assert c._lcu_get.calls == ["/lol-gameflow/v1/gameflow-phase"]


def test_idle_tick_backfills_history_once_outside_post_game(pgc):
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": "Lobby",
                         "/lol-summoner/v1/current-summoner": {"puuid": LOCAL_PUUID},
                         _history_route(): HIST_DOC})
    c._idle_tick()
    assert tp.has_record(GID, tp.SOURCE_HISTORY)
    n = len(c._lcu_get.calls)
    c._idle_tick()                    # nothing awaited: no second history read
    assert not any(p.startswith(_history_route()) for p in c._lcu_get.calls[n:])


def test_eog_capture_arms_a_history_merge_after_post_game(pgc):
    phase = {"v": "PreEndOfGame"}
    c = _collector(pgc, {"/lol-gameflow/v1/gameflow-phase": lambda: phase["v"],
                         "/lol-gameflow/v1/session": SESSION_TFT,
                         tp.EOG_PATH: EOG_DOC,
                         "/lol-summoner/v1/current-summoner": {"puuid": LOCAL_PUUID},
                         _history_route(): HIST_DOC})
    c._idle_tick()                    # post-game: EOG fast path
    assert tp.load(GID)["sources"] == ["eog"]
    phase["v"] = "Lobby"
    c._idle_tick()                    # back in Lobby: the durable route merges in
    rec = tp.load(GID)
    assert rec["sources"] == ["eog", "history"]
    assert rec["players"][0]["level"] == 9 and rec["local_hp"] == 100


def test_idle_tick_never_raises(pgc):
    c = _collector(pgc, {})

    def boom(path):
        raise RuntimeError("lcu exploded")
    c._lcu_get = boom
    c._idle_tick_guarded()            # must not raise


# -- N4: the gameclient EOG block ----------------------------------------------

def gameclient_block(game_id=GID):
    """SYNTHETIC, keyed exactly as measured: the listener's shape of the
    gameclient-eog-stats-block Create event at the match-2 end (top level
    gameId / gameMode / isRanked / queueId / queueType / statsBlock;
    statsBlock customAugmentContainer / gameLengthSeconds / players /
    setCoreName; player keys incl. PUUID, playerId, riotIdGameName,
    riotIdTagLine, summonerName, summonerIconID, companion*), with the
    boardPieces keys from docs/TFT_PROGRAM.md section 0 item 2."""
    def player(standing, local, pieces):
        return {"PUUID": LOCAL_PUUID if local else "00000000-0000-0000-0000-000000000000",
                "augments": [], "boardPieces": pieces,
                "companionContentId": "c", "companionName": "pet", "companionSkinId": 1,
                "eventPVEData": [], "eventSkillDeltas": [], "ffaStanding": standing,
                "health": 96 if local else 0, "isInteractable": local,
                "partnerGroupId": 0, "playbookItemId": 0, "playerId": 12345 + standing,
                "riotIdGameName": f"player{standing - 1}", "riotIdTagLine": "TAG",
                "summonerIconID": 7, "summonerName": f"player{standing - 1}"}
    me = [{"championName": "DA_Draven18", "starLevel": 2, "price": 5,
           "itemNames": ["DA_ThiefsGloves", "DA_18_EmblemFloraFatalis"]},
          {"championName": "DA_18_Yorick", "starLevel": 2, "price": 1, "itemNames": []}]
    other = [{"championName": "DA_18_Rakan", "starLevel": 1, "price": 2, "itemNames": []}]
    return {"gameId": game_id, "gameMode": "TFT", "isRanked": False, "queueId": 1090,
            "queueType": "NORMAL_TFT",
            "statsBlock": {"customAugmentContainer": "", "gameLengthSeconds": 2050,
                           "setCoreName": "TFTSet18",
                           "players": [player(2, False, other), player(1, True, me)]}}


def test_eog_block_route_is_spelled_as_the_live_client_serves_it(pgc):
    c = _collector(pgc, {})
    assert c._fetch_eog_stats_block() is None
    assert "/lol-end-of-game/v1/gameclient-eog-stats-block" in c._lcu_get.calls
    assert not any("game-client-eog" in p for p in c._lcu_get.calls)


def test_no_python_file_requests_the_misspelled_eog_route():
    hits = []
    for path in _repo_walk.repo_files(patterns=("*.py",)):
        rel = _repo_walk.relative_posix(path)
        if rel.startswith("tests/"):
            continue
        try:
            vals = list(_route_literals(path.read_text(encoding="utf-8")))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if any("game-client-eog-stats-block" in v for v in vals):
            hits.append(rel)
    assert hits == []


def test_a_tft_block_on_the_lol_path_goes_to_the_tft_store_not_sr(pgc, tmp_path):
    """The standalone client gives no game state, so the trigger hint can be
    CLASSIC for a TFT game. The fixed route then answers with TFT data."""
    import sqlite3
    block = gameclient_block()
    c = _collector(pgc, {"/lol-end-of-game/v1/gameclient-eog-stats-block": block,
                         "/lol-gameflow/v1/session": SESSION_TFT})
    pins = []
    c._publish_game_end_pin = lambda *a, **k: pins.append(a)
    assert c._capture_from_eog("CLASSIC") is True
    assert pins == [], "a TFT game must not pin the LoL rewind writer"
    conn = sqlite3.connect(str(tmp_path / "pg.db"))
    try:
        n = conn.execute("SELECT COUNT(*) FROM sr_matches").fetchone()[0]
    finally:
        conn.close()
    assert n == 0, "a TFT game was saved as a Summoner's Rift match"
    rec = tp.load(GID)
    assert rec["local_placement"] == 1 and rec["local_hp"] == 96


def test_tft_capture_falls_back_to_the_gameclient_block(pgc, tmp_path):
    import sqlite3

    from core import raw_documents as rd
    c = _collector(pgc, {"/lol-end-of-game/v1/gameclient-eog-stats-block": gameclient_block(),
                         "/lol-gameflow/v1/session": SESSION_TFT})
    assert c._capture_tft_eog() is True
    calls = c._lcu_get.calls
    assert calls.index(tp.EOG_PATH) < calls.index(
        "/lol-end-of-game/v1/gameclient-eog-stats-block")
    rec = tp.load(GID)
    assert rec["players"][0]["board"][0]["name"] == "Draven"
    assert rec["source_route"] == tp.GAMECLIENT_EOG_PATH
    conn = sqlite3.connect(str(tmp_path / "pg.db"))
    try:
        kept = rd.load(conn, str(GID), "eog")
    finally:
        conn.close()
    _assert_no_identity(kept)


def test_run_loop_idle_wait_is_short():
    import lcu.lcu_postgame_collector as mod
    assert 0 < mod.PostgameCollector._IDLE_WAIT_S <= 10
