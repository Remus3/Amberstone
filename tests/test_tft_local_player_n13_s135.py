"""S135 N13 / N14: RC tracked the wrong TFT player in a human lobby.

Measured in the 2026-10-25 match-4 QA (gitignored
ops/runtime/tft_qa/20261025-104400/QA_REPORT.md): the standalone client's
per-round ``TFTEoGStats.json`` marked ALL 8 entries ``isInteractable`` true in
the first human lobby, so ``next(isInteractable)`` took players[0] - the
opponent who finished 8th - and RC served that player's HP, standing and board
for the whole match. The synthesized allgamedata named all 8 rows LOCAL_NAME,
so ``TftStateReader`` (it matches the local row by name, the last match wins)
read players[7]: when that player was eliminated the coach got ``HP: 0`` with
``Players alive: 1`` and answered "GAME OVER" while the operator sat 2nd on 73
HP and went on to win (N14). The true local entry is the ONE whose
``playerId`` equals the LCU summoner id.

The fixture is SYNTHETIC and anonymized (the repo is public): keyed exactly as
the measured file, every id is a fake 9000NN / zero-prefixed UUID, and the
local entry sits in the middle (neither the first nor the last row).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import pytest

from tft import local_player as lp
from tft import tft_standalone as ts

FIX = Path(__file__).parent / "fixtures" / "tft_eog_round_human_lobby_n13.json"
GID = 5000000013
LOCAL_SID = 900004
LOCAL_PUUID = "00000000-0000-4000-8000-000000000004"
LOCAL_IDX = 3
ZERO_PUUID = "00000000-0000-0000-0000-000000000000"


def _doc() -> dict:
    return json.loads(FIX.read_text(encoding="utf-8"))


def _players(doc=None) -> list:
    return (doc or _doc())["statsBlock"]["players"]


def _lcu(**over) -> dict:
    d = {"phase": "InProgress", "game_id": str(GID), "game_queue_mode": "TFT",
         "summoner_id": LOCAL_SID}
    d.update(over)
    return {k: v for k, v in d.items() if v is not None}


def _synth(lcu=None, eog=None):
    return ts.synth_allgamedata(lcu=_lcu() if lcu is None else lcu, running=True,
                                eog=_doc() if eog is None else eog, now=time.time())


def _reader():
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
    r._ocr_lock = threading.Lock()
    return r


@pytest.fixture(autouse=True)
def _clear_caches():
    ts._reset_caches_for_tests()
    yield
    ts._reset_caches_for_tests()


# -- the fixture is the measured shape ------------------------------------------

def test_fixture_is_the_measured_all_interactable_human_lobby():
    players = _players()
    assert len(players) == 8
    assert all(p["isInteractable"] is True for p in players)
    assert all(p["playerId"] for p in players), "human lobby: every playerId non-zero"
    hits = [i for i, p in enumerate(players) if p["playerId"] == LOCAL_SID]
    assert hits == [LOCAL_IDX] and 0 < LOCAL_IDX < len(players) - 1
    # anonymized: synthetic ids only, no Riot id shape anywhere
    blob = FIX.read_text(encoding="utf-8")
    assert "#" not in blob
    assert all(p["PUUID"].startswith("00000000-0000-") for p in players)


# -- the one reusable selector (tft/local_player.py) ------------------------------

def test_selector_picks_the_entry_matching_the_lcu_summoner_id():
    assert lp.local_player_index(_players(), summoner_id=LOCAL_SID) == (
        LOCAL_IDX, lp.BASIS_SUMMONER_ID)
    entry, basis = lp.local_player(_players(), summoner_id=LOCAL_SID)
    assert entry["playerId"] == LOCAL_SID and basis == lp.BASIS_SUMMONER_ID
    # the LCU snapshot may carry the id as a digit string
    assert lp.local_player_index(_players(), summoner_id=str(LOCAL_SID))[0] == LOCAL_IDX


def test_selector_matches_by_puuid_too():
    assert lp.local_player_index(_players(), puuid=LOCAL_PUUID.upper()) == (
        LOCAL_IDX, lp.BASIS_PUUID)


def test_selector_never_picks_a_stranger_when_the_lobby_is_ambiguous():
    idx, reason = lp.local_player_index(_players())
    assert idx is None and "8 entries" in reason and "isInteractable" in reason
    assert lp.local_player(_players()) == (None, reason)


def test_selector_unknown_when_the_known_id_matches_nobody():
    idx, reason = lp.local_player_index(_players(), summoner_id=123)
    assert idx is None and "matches no entry" in reason


def test_selector_unknown_when_the_id_matches_two_entries():
    players = _players()
    players[6]["playerId"] = LOCAL_SID
    idx, reason = lp.local_player_index(players, summoner_id=LOCAL_SID)
    assert idx is None and "2 entries" in reason


def _bot_lobby(local_at=1, with_ids=True):
    """Matches 1-3 shape: ONE interactable entry, non-local ids zeroed."""
    players = _players()
    for i, p in enumerate(players):
        p["isInteractable"] = i == local_at
        if i != local_at:
            p["playerId"], p["PUUID"] = 0, ZERO_PUUID
        if not with_ids:
            p.pop("playerId"), p.pop("PUUID")
    if with_ids:
        players[local_at]["playerId"] = LOCAL_SID
    return players


def test_selector_bot_lobby_by_id_and_by_the_single_interactable_flag():
    players = _bot_lobby(local_at=1)
    assert lp.local_player_index(players, summoner_id=LOCAL_SID) == (1, lp.BASIS_SUMMONER_ID)
    assert lp.local_player_index(players) == (1, lp.BASIS_INTERACTABLE)
    # a zeroed PUUID / playerId is never an identity, even when "asked" for it
    assert lp.local_player_index(players, puuid=ZERO_PUUID) == (1, lp.BASIS_INTERACTABLE)
    assert lp.local_player_index(players, summoner_id=0) == (1, lp.BASIS_INTERACTABLE)


def test_selector_falls_back_to_the_single_flag_only_when_the_file_carries_no_ids():
    players = _bot_lobby(local_at=5, with_ids=False)
    assert lp.local_player_index(players, summoner_id=LOCAL_SID) == (5, lp.BASIS_INTERACTABLE)
    # ... but a file that DOES carry ids and lacks ours names no local player
    players = _bot_lobby(local_at=5)
    idx, _ = lp.local_player_index(players, summoner_id=LOCAL_SID + 1)
    assert idx is None


@pytest.mark.parametrize("junk", [None, "x", 5, [], [None, 3, "a"]])
def test_selector_is_fail_soft(junk):
    idx, reason = lp.local_player_index(junk, summoner_id=LOCAL_SID)
    assert idx is None and isinstance(reason, str)


def test_selector_keeps_list_positions_across_non_dict_rows():
    players = [None, "junk"] + _players()
    assert lp.local_player_index(players, summoner_id=LOCAL_SID)[0] == LOCAL_IDX + 2
    assert lp.local_player_index(players, summoner_id=True)[0] is None  # bool is no id


# -- tft_standalone: the live source ------------------------------------------------

def test_round_state_serves_the_local_entry_not_players0():
    rs = ts._round_state(_lcu(), _doc(), time.time())
    assert rs["local"]["health"] == 73
    assert rs["local"]["standing"] == 2
    assert len(rs["local"]["board"]) == 10
    assert rs["local_index"] == LOCAL_IDX and rs["local_basis"] == lp.BASIS_SUMMONER_ID


def test_synth_names_exactly_one_local_row_the_matched_one():
    raw = _synth()
    rows = raw["allPlayers"]
    mine = [i for i, p in enumerate(rows) if p["summonerName"] == ts.LOCAL_NAME]
    assert mine == [LOCAL_IDX]
    assert rows[LOCAL_IDX]["health"] == 73 and rows[LOCAL_IDX]["isDead"] is False
    assert rows[0]["summonerName"] == "opponent-0"
    assert raw["activePlayer"]["currentHP"] == 73
    blob = json.dumps(raw)
    assert "TestPlayer" not in blob and "00000000-0000-4000" not in blob


def test_liveclient_summary_serves_the_local_board_hp_and_standing():
    lc = ts._summary_from_raw(_synth())
    assert lc["hp"] == 73 and lc["standing"] == 2 and lc["board_size"] == 10
    # the 8th-place stranger's board RC served in the match
    assert "Warwick*3" not in lc["board_str"]


def test_poller_hp_pct_is_the_local_players():
    from game_reader import GameReader
    gr = GameReader.__new__(GameReader)
    state = gr._process_game(_synth())
    assert state["hp_pct"] == 73


def test_state_reader_reads_local_hp_and_the_lobby_n14():
    """N14: the reader took the LAST LOCAL_NAME row (an eliminated player) -
    health 0, is_dead, alive_others 0, total_players 1 - so the coach said
    GAME OVER at 2nd on 73 HP."""
    out = _reader()._parse(_synth())
    assert out["health"] == 73 and out["is_dead"] is False
    assert out["alive_others"] == 2 and out["dead_others"] == 5
    assert out["total_players"] == 8
    assert out["standing"] == 2 and out["board_size"] == 10


def test_unknown_local_is_withheld_never_a_stranger_and_logged_once(caplog):
    lcu = _lcu(summoner_id=None)
    with caplog.at_level(logging.INFO, logger="rc.tft.standalone"):
        for _ in range(3):
            raw = _synth(lcu=lcu)
    st = raw["rc_standalone"]
    assert st["local"] == {} and st["local_index"] is None
    assert "isInteractable" in st["local_basis"]
    assert all(p["summonerName"] != ts.LOCAL_NAME for p in raw["allPlayers"])
    assert "currentHP" not in raw["activePlayer"]
    lc = ts._summary_from_raw(raw)
    assert "hp" not in lc and "standing" not in lc and "board_str" not in lc
    lines = [r for r in caplog.records if "local player unknown" in r.getMessage()]
    assert len(lines) == 1, "one line per game and reason, not one per tick"
    assert "TestPlayer" not in lines[0].getMessage()


def test_unknown_local_reader_counts_the_lobby_once():
    out = _reader()._parse(_synth(lcu=_lcu(summoner_id=None)))
    assert out["total_players"] == 8          # not 1 + 8
    assert out["alive_others"] == 2           # 3 alive, one of them is us
    assert out["is_dead"] is False and out["health"] != 0


def test_known_id_matching_nobody_is_withheld():
    raw = _synth(lcu=_lcu(summoner_id=123))
    assert raw["rc_standalone"]["local"] == {}
    assert "matches no entry" in raw["rc_standalone"]["local_basis"]


def test_bot_lobby_single_interactable_still_works_without_an_id():
    doc = _doc()
    doc["statsBlock"]["players"] = _bot_lobby(local_at=6)
    rs = ts._round_state(_lcu(summoner_id=None), doc, time.time())
    assert rs["local"]["health"] == 45 and rs["local_basis"] == lp.BASIS_INTERACTABLE


def test_start_of_game_sentinel_is_not_an_elimination_n14():
    """N14 beyond N13: for ~20 s at game start the file carries health -1 /
    ffaStanding -1 for every player; ``isDead = hp <= 0`` read that as
    eliminated, so the coach got HP 0 ("HP=0 is impossible at Stage 1-2")."""
    doc = _doc()
    for p in doc["statsBlock"]["players"]:
        p["health"], p["ffaStanding"], p["boardPieces"] = -1, -1, []
    raw = _synth(eog=doc)
    assert all(p["isDead"] is False for p in raw["allPlayers"])
    out = _reader()._parse(raw)
    assert out["is_dead"] is False and out["health"] != 0
    # a real elimination (scored standing, HP <= 0) is still dead
    rows = _synth()["allPlayers"]
    assert rows[0]["isDead"] is True and rows[7]["isDead"] is True


# -- siblings sharing the root cause -----------------------------------------------

def test_scouting_round_file_excludes_only_the_local_entry():
    from tft import tft_scouting as sc
    ids = sc.identities_from_round_file(_doc(), LOCAL_PUUID)
    names = [i.riot_id for i in ids]
    assert len(ids) == 7 and "TestPlayer4#TST4" not in names
    by_sid = sc.identities_from_round_file(_doc(), self_summoner_id=LOCAL_SID)
    assert [i.riot_id for i in by_sid] == names
    # no self id and every entry interactable: self cannot be told apart, so
    # nothing is scouted from this source (the watcher falls to the session)
    assert sc.identities_from_round_file(_doc()) == []


def test_scouting_watcher_passes_its_summoner_id_to_the_round_file():
    from tft import tft_scouting as sc

    class _Scouter:
        def __init__(self):
            self.started = None

        def start(self, ids, **kw):
            self.started = (ids, kw)

        def write_status(self, *a, **k):
            pass

    session = {"phase": "InProgress",
               "gameData": {"gameId": GID, "queue": {"id": 1090, "gameMode": "TFT"},
                            "teamOne": [], "teamTwo": []},
               "map": {"gameMode": "TFT"}}
    routes = {"/lol-gameflow/v1/gameflow-phase": "InProgress",
              "/lol-gameflow/v1/session": session,
              "/lol-summoner/v1/current-summoner": {"puuid": "11111111-2222-4333-8444-555555555555",
                                                    "summonerId": LOCAL_SID}}
    scouter = _Scouter()
    w = sc.ScoutingWatcher(scouter, lambda path: routes.get(path), round_file=_doc)
    assert w.tick() == "started"
    ids, kw = scouter.started
    assert kw["identity_source"] == "tft_round_file"
    assert len(ids) == 7 and "TestPlayer4#TST4" not in [i.riot_id for i in ids]


def test_gameclient_eog_block_picks_the_local_entry_by_summoner_id():
    from tft import tft_placement as tp
    rec = tp.parse_gameclient_eog(_doc(), local_summoner_id=LOCAL_SID)
    assert rec["local_placement"] == 2 and rec["local_hp"] == 73
    assert sum(1 for p in rec["players"] if p["is_local"]) == 1
    assert [p["placement"] for p in rec["players"] if p["is_local"]] == [2]
    unknown = tp.parse_gameclient_eog(_doc())
    assert unknown["local_placement"] is None and unknown["local_hp"] is None
    assert not any(p["is_local"] for p in unknown["players"])


def test_postgame_gameclient_fallback_resolves_the_summoner(tmp_path, monkeypatch):
    import lcu.lcu_postgame_collector as pgc
    from tests.test_postgame_tft_capture_rm616 import _collector
    from tft import tft_placement as tp
    monkeypatch.setattr(pgc, "_DB_PATH", tmp_path / "pg.db")
    monkeypatch.setattr(tp, "_STORE_DIR", tmp_path / "tft_matches")
    pgc._ensure_schema()
    session = {"phase": "PreEndOfGame",
               "gameData": {"gameId": GID, "queue": {"id": 1090, "gameMode": "TFT"}},
               "map": {"gameMode": "TFT"}}
    c = _collector(pgc, {tp.GAMECLIENT_EOG_PATH: _doc(),
                         "/lol-gameflow/v1/session": session,
                         "/lol-summoner/v1/current-summoner": {"summonerId": LOCAL_SID}})
    assert c._capture_tft_eog() is True
    rec = tp.load(GID)
    assert rec["local_placement"] == 2 and rec["local_hp"] == 73


def test_cv_accuracy_oracle_keys_p1_by_id_and_refuses_an_ambiguous_lobby():
    import importlib
    acc = importlib.import_module("tools.tft_cv_accuracy")
    assert acc.eog_file_players(_doc()) == {}
    keyed = acc.eog_file_players(_doc(), summoner_id=LOCAL_SID)
    assert keyed["P1"]["hp"] == 73 and len(keyed["P1"]["board"]) == 10
    assert len(keyed) == 8


# -- verifier round (4b / 4e): ONE alive rule, unknown served as unknown ----------

def _start_file() -> dict:
    """The measured start-of-game write: health -1 / ffaStanding -1 for all."""
    doc = _doc()
    for p in doc["statsBlock"]["players"]:
        p["health"], p["ffaStanding"], p["boardPieces"] = -1, -1, []
    return doc


def test_one_alive_rule_player_status_and_count_alive():
    assert lp.player_status({"health": 73, "ffaStanding": 2}) == lp.ALIVE
    assert lp.player_status({"health": 5, "ffaStanding": -1}) == lp.ALIVE
    assert lp.player_status({"health": -9, "ffaStanding": 8}) == lp.ELIMINATED
    assert lp.player_status({"health": 0, "ffaStanding": 4}) == lp.ELIMINATED
    assert lp.player_status({"health": -1, "ffaStanding": -1}) is None
    assert lp.player_status({"ffaStanding": 3}) is None
    assert lp.player_status("junk") is None
    assert lp.count_alive(_players()) == 3
    assert lp.count_alive(_players(_start_file())) is None, "not knowable"
    assert lp.count_alive([]) is None
    assert lp.lobby_counts(_players(), LOCAL_IDX) == {
        "players_alive": 3, "alive_others": 2, "dead_others": 5}
    # local unknown: the lobby-wide counts still hold (we are one of the alive)
    assert lp.lobby_counts(_players(), None) == {
        "players_alive": 3, "alive_others": 2, "dead_others": 5}
    assert lp.lobby_counts(_players(_start_file()), LOCAL_IDX) == {
        "players_alive": None, "alive_others": None, "dead_others": None}


@pytest.mark.parametrize("sid", [None, LOCAL_SID])
def test_start_file_prompt_makes_no_elimination_claim_4b(sid):
    """Verifier 4b: unknown local + the all -1 / -1 start file put
    "Players alive: 1 (8 eliminated)" in the prompt - the match-4 GAME OVER
    input. The count is not knowable there, and the prompt must say so."""
    from tft.tft_coach_engine import _build_prompt
    raw = _synth(lcu=_lcu(summoner_id=sid), eog=_start_file())
    assert raw["rc_standalone"]["players_alive"] is None
    out = _reader()._parse(raw)
    assert out["alive_others"] is None and out["dead_others"] is None
    assert out["total_players"] == 8
    assert out["is_dead"] is False and out["health"] != 0
    prompt = _build_prompt(out)
    alive_line = [ln for ln in prompt.splitlines() if ln.startswith("Players alive")]
    assert alive_line and "unknown" in alive_line[0]
    assert "eliminated" not in prompt
    assert "HP: 0" not in prompt and "HP: None" not in prompt
    # the frozen TftSnapshot factory int()s these counts: unknown must not
    # cost the envelope its update
    from tft.tft_state_reader import TftStateReader
    assert TftStateReader.to_tft_snapshot(out) is not None


def test_prompt_counts_come_from_the_same_rule_mid_game():
    """A regression pin against the PRE-N13 code, not a red-first test of
    the 4b change: on 3d190082a this prompt read "Players alive: 1 (0
    eliminated)" with HP 0 (measured, verifier round 2); 445559f8f already
    fixed it, so it passed when it was added in 1fb367bb1."""
    from tft.tft_coach_engine import _build_prompt
    out = _reader()._parse(_synth())
    assert "Players alive: 3 (5 eliminated)" in _build_prompt(out)


def test_start_file_serves_unknown_as_null_to_poller_and_dashboard_4e():
    raw = _synth(eog=_start_file())
    assert raw["rc_standalone"]["local_index"] == LOCAL_IDX
    assert "currentHP" not in raw["activePlayer"], "no -1 HP for the poller"
    from game_reader import GameReader
    gr = GameReader.__new__(GameReader)
    assert gr._process_game(raw)["hp_pct"] != -1
    lc = ts._summary_from_raw(raw)
    assert lc["hp"] is None and lc["standing"] is None
    assert "players_alive" in lc and lc["players_alive"] is None


def test_eliminated_local_hp_is_clamped_to_zero_and_flagged_4e():
    doc = _doc()
    me = doc["statsBlock"]["players"][LOCAL_IDX]
    me["health"], me["ffaStanding"] = -11, 6
    raw = _synth(eog=doc)
    local = raw["rc_standalone"]["local"]
    assert local["health"] == 0 and local["eliminated"] is True
    assert local["standing"] == 6
    assert raw["activePlayer"]["currentHP"] == 0
    lc = ts._summary_from_raw(raw)
    assert lc["hp"] == 0 and lc["eliminated"] is True
    out = _reader()._parse(raw)
    assert out["health"] == 0 and out["is_dead"] is True
    assert out["alive_others"] == 2 and out["dead_others"] == 5
    # an alive local carries eliminated=False
    assert ts._summary_from_raw(_synth())["eliminated"] is False


# -- verifier round 2 -----------------------------------------------------------------

def test_no_round_file_yet_counts_are_unknown_not_one_alive():
    """Round 2 item 1: before the first per-round write the standalone source
    sends no player rows, so the reader's own count said "Players alive: 1
    (0 eliminated)". No file = the lobby counts are unknown."""
    from tft.tft_coach_engine import _build_prompt
    from tft.tft_state_reader import TftStateReader
    raw = ts.synth_allgamedata(lcu=_lcu(), running=True, eog=None, now=time.time())
    assert raw is not None and raw["rc_standalone"]["eog"] is False
    out = _reader()._parse(raw)
    assert out["alive_others"] is None and out["dead_others"] is None
    assert out["total_players"] is None and out["players_alive"] is None
    alive_line = [ln for ln in _build_prompt(out).splitlines()
                  if ln.startswith("Players alive")]
    assert alive_line == ["Players alive: unknown (lobby HP not readable yet)"]
    assert TftStateReader.to_tft_snapshot(out) is not None


def test_eliminated_local_is_not_counted_alive_in_the_prompt():
    """Round 2 item 2: the prompt added 1 for the local player always, so an
    eliminated local with 2 players alive printed "Players alive: 3"."""
    from tft.tft_coach_engine import _build_prompt
    doc = _doc()
    me = doc["statsBlock"]["players"][LOCAL_IDX]
    me["health"], me["ffaStanding"] = -11, 6
    out = _reader()._parse(_synth(eog=doc))
    assert "Players alive: 2 (6 eliminated)" in _build_prompt(out)
    # a Live Client (:2999) state carries no lobby-wide count: +1 for the
    # local player only when it is known alive
    base = {"alive_others": 2, "dead_others": 5}
    assert "Players alive: 2 (6 eliminated)" in _build_prompt(dict(base, is_dead=True))
    assert "Players alive: 3 (5 eliminated)" in _build_prompt(dict(base, is_dead=False))


def test_rating_takes_no_placement_from_unknown_alive_others(tmp_path, monkeypatch):
    """Round 2 item 3: a None alive_others (counts unknown when the game
    ended) became 7 -> rated 8th. No source = no rating (the N8 rule)."""
    import performance_tracker as pt
    monkeypatch.setattr(pt, "_match_db", None)
    live = {"last_round_result": "", "stage_round": "5-1", "level": 8,
            "traits_active": [], "board_units": [], "augments": []}
    coach = {"variant": "standard", "alive_others": None, "stage": 5,
             "game_time_s": 1500, "level": 8}
    assert pt.save_tft_rating(str(tmp_path), dict(live), dict(coach)) == ("", [])
    assert not (tmp_path / "data").exists(), "nothing rated, nothing written"


# -- S136 T5: the LCU snapshot carries the summoner id across a reconnect -----------
# lcu/snapshot_shape.py stamped ``summoner_id`` only inside its mastery block:
# that block's phase list had no Reconnect, and it stamped only when the mastery
# GET answered a list. A TFT reconnect therefore served a snapshot with no id,
# and in a human lobby (all 8 entries isInteractable) the local player read as
# unknown - HP, standing and board withheld for the rest of the match.

_PHASE_PATH = "/lol-gameflow/v1/gameflow-phase"
_CURRENT_PATH = "/lol-summoner/v1/current-summoner"
_MASTERY_PATH = "/lol-champion-mastery/v1/local-player/champion-mastery"


def _shaped(monkeypatch, phase, *, mastery=True) -> dict:
    """lcu/snapshot_shape.shape_snapshot at ``phase`` over a fake LCU serving
    this fixture's game (TFT queue) and the local summoner id; unknown paths
    answer (None, "404") as LCU does."""
    from lcu import snapshot_shape as ss
    monkeypatch.setattr(ss._draft_log, "note_game_id", lambda gid: None)
    monkeypatch.setattr(ss._draft_log, "observe_phase", lambda ph: None)
    routes = {
        _PHASE_PATH: phase,
        "/lol-gameflow/v1/session": {"gameData": {
            "gameId": GID, "queue": {"id": 1090, "gameMode": "TFT"}}},
        _CURRENT_PATH: {"summonerId": LOCAL_SID},
    }
    if mastery:
        routes[_MASTERY_PATH] = [{"championId": 1, "championLevel": 3,
                                  "championPoints": 1000}]

    def request(method, path, body=None):
        assert method == "GET"
        return (routes[path], None) if path in routes else (None, "404")
    ss._reset_mastery_cache_for_tests()
    try:
        return ss.shape_snapshot(request, {}, enrich=False)
    finally:
        ss._reset_mastery_cache_for_tests()


def test_reconnect_snapshot_carries_the_in_progress_summoner_id_t5(monkeypatch):
    live = _shaped(monkeypatch, "InProgress")
    rec = _shaped(monkeypatch, "Reconnect")
    assert live["summoner_id"] == LOCAL_SID
    assert rec["phase"] == "Reconnect"
    assert rec.get("summoner_id") == live["summoner_id"]


def test_reconnect_snapshot_resolves_the_local_tft_player_t5(monkeypatch):
    rec = _shaped(monkeypatch, "Reconnect")
    assert ts.lcu_tft_verdict(rec) is True
    rs = ts._round_state(rec, _doc(), time.time())
    assert rs["local_index"] == LOCAL_IDX
    assert rs["local_basis"] == lp.BASIS_SUMMONER_ID
    assert rs["local"]["health"] == 73 and rs["local"]["standing"] == 2
    raw = _synth(lcu=rec)
    mine = [i for i, p in enumerate(raw["allPlayers"])
            if p["summonerName"] == ts.LOCAL_NAME]
    assert mine == [LOCAL_IDX]


@pytest.mark.parametrize("phase", ["GameStart", "InProgress", "Reconnect",
                                   "WaitingForStats", "PreEndOfGame", "EndOfGame"])
def test_summoner_id_is_stamped_without_a_mastery_answer_t5(monkeypatch, phase):
    """The id is the local player's identity, not a mastery by-product: a
    mastery GET that answers no list must not cost the TFT local player, in
    the live phases or in the post-game ones the final-board read runs in."""
    snap = _shaped(monkeypatch, phase, mastery=False)
    assert "mastery" not in snap
    assert snap.get("summoner_id") == LOCAL_SID


@pytest.mark.parametrize("phase", ["None", ""])
def test_idle_or_unknown_phase_stamps_no_summoner_id_t5(monkeypatch, phase):
    snap = _shaped(monkeypatch, phase)
    assert "summoner_id" not in snap and "mastery" not in snap


def test_end_of_game_snapshot_lets_the_per_round_file_name_the_local_entry_t5(
        monkeypatch):
    """tft/tft_final_board.per_round_record reads the relay snapshot's id at
    the lifecycle game-end rating, when the LCU phase is already post-game."""
    from tft import tft_final_board as fb
    doc = _doc()
    players = doc["statsBlock"]["players"]
    for i, p in enumerate(players):  # the local entry won: everyone else is out
        if i != LOCAL_IDX and p["health"] > 0:
            p["health"] = 0
    players[LOCAL_IDX]["ffaStanding"] = 1
    snap = _shaped(monkeypatch, "EndOfGame")
    monkeypatch.setattr(ts, "relay_lcu_snapshot", lambda: snap)
    monkeypatch.setattr(ts, "read_eog", lambda now=None, max_age_s=None: doc)
    rec = fb.per_round_record(now=time.time())
    assert rec is not None
    assert rec["per_round_final"] is True
