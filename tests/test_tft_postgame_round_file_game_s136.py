"""S136 T10 - the post-game TFT readers take the per-round file only when it
is POSITIVELY the game that just ended.

T9 (tft/tft_standalone.py ``eog_matches_game`` / ``_round_state``) closed the
live path: the coach prompt and /api/state serve the standalone client's
per-round TFTEoGStats.json only when its ``gameId`` equals the current LCU
game id. Two POST-GAME readers still took ANY fresh file (read in code at
9d3acac79):

  - tft/tft_final_board.py ``per_round_record`` (read_eog at :326) and
    ``resolve_final`` (:363-375): with no caller game id - the lifecycle
    game-end rating (app/_game_lifecycle.py on_game_end ->
    performance_tracker.save_tft_rating) passes none - the file's OWN gameId
    became "the game": its store record, or its final standing, was rated
    as the game that just ended.
  - performance_tracker.py ``_tft_game_id`` (read_eog at :378): the legacy
    (vision / coaching) rating row was stamped with the file's gameId, and
    ``_tft_db_write`` upserts BY game id - so another game's id meant another
    game's row overwritten.

What the post-game reader has in hand (ground truth): the frozen caller passes
no game id; data/tft_live_data.json and data/tft_coaching_data.json carry
none; the relay LCU snapshot carries ``game_id`` only in GameStart /
InProgress / Reconnect (lcu/snapshot_shape.py, the gameflow-session block),
so at the game-end rating (phase WaitingForStats / PreEndOfGame / EndOfGame)
it has none either. The id the process DID know is the LCU game id the live
path served during the game (``_round_state``), now remembered
(``tft_standalone.current_game_id``: the snapshot's id, else that live id
when seen within EOG_MAX_AGE_S). Match rule = T9's: equal ids, a missing id
on either side is no match.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

import performance_tracker as pt
from tft import tft_final_board as fb
from tft import tft_placement as tp
from tft import tft_standalone as ts

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
EOG_DOC = json.loads((FIX / "tft_eog_stats_set18.json").read_text(encoding="utf-8"))
CUR = 1000000001      # the game that just ended
OTHER = 1000000077    # an earlier game whose per-round file is still fresh

BLANK_LIVE = {"mode": "tft_live", "stage_round": "", "level": 0, "hp": 0,
              "board_units": [], "traits_active": [], "augments": []}
BLANK_COACH = {"mode": "tft", "action": ""}
# A legacy (vision) placement: rated without the store / per-round record.
VISION_3RD = {"mode": "tft_live", "stage_round": "5-2", "level": 8,
              "last_round_result": "3rd", "board_units": ["Ashe 2-star"],
              "traits_active": ["Lunar 3"], "augments": []}


def _doc(gid=CUR, standing=1, health=96, others_alive=0):
    """A per-round document; default = a finished game won by the local
    (single isInteractable) entry. ``gid=None`` = no gameId key at all."""
    players = [{"isInteractable": True, "ffaStanding": standing, "health": health,
                "partnerGroupId": 0,
                "boardPieces": [{"championName": "TFT18_Ashe", "starLevel": 2,
                                 "itemNames": ["TFT_Item_InfinityEdge"]}]}]
    for i in range(7):
        players.append({"isInteractable": False, "ffaStanding": i + 2,
                        "health": 30 if i < others_alive else 0,
                        "partnerGroupId": 0, "boardPieces": []})
    doc = {"gameMode": "TFT", "queueId": 1090, "queueType": "NORMAL_TFT",
           "statsBlock": {"gameLengthSeconds": 2081, "setCoreName": "TFTSet18",
                          "players": players}}
    if gid is not None:
        doc["gameId"] = gid
    return doc


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "root"
    (r / "data" / "meta").mkdir(parents=True)
    shutil.copy(REPO / "data" / "meta" / "tft_set18_cdragon.json",
                r / "data" / "meta" / "tft_set18_cdragon.json")
    monkeypatch.setattr(tp, "_STORE_DIR", r / "data" / "tft_matches")
    monkeypatch.setattr(pt, "_match_db", None)
    monkeypatch.setattr("tft.placement_aggregator.update_heatmap", lambda *a, **k: None)
    monkeypatch.setattr(ts, "eog_stats_path", lambda: tmp_path / "absent.json")
    # Post-game LCU snapshot: the phase has left the game, so no game_id
    # (lcu/snapshot_shape.py stamps it in GameStart / InProgress / Reconnect).
    monkeypatch.setattr(ts, "relay_lcu_snapshot", lambda: {"phase": "EndOfGame"})
    ts._reset_caches_for_tests()
    yield r
    ts._reset_caches_for_tests()
    db = pt._match_db
    if db is not None:
        try:
            db.close()
        except Exception:  # noqa: BLE001 - teardown only
            pass


def _file(tmp_path, monkeypatch, doc):
    p = tmp_path / "TFTEoGStats.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(ts, "eog_stats_path", lambda: p)
    return p


def _live_game(gid, monkeypatch, now=None):
    """The game the live path served: one in-game synth tick with the LCU id
    (the same call the poller makes at 2 Hz during the match)."""
    now = time.time() if now is None else now
    lcu = {"phase": "InProgress", "game_id": str(gid), "game_queue_mode": "TFT"}
    ts.synth_allgamedata(lcu=lcu, running=True, eog=None, now=now)


def _store(gid, standing=4):
    doc = json.loads(json.dumps(EOG_DOC))
    doc["gameId"] = gid
    for p in doc["players"]:
        if p.get("isLocalPlayer"):
            p["ffaStanding"] = standing
            p["rank"] = standing
    assert tp.persist(tp.parse_eog(doc, now=time.time() - 3600))


def _rows(root):
    db = root / "data" / "match_history.db"
    if pt._match_db is not None:
        pt._match_db.close()
        pt._match_db = None
    if not db.exists():
        return []
    c = sqlite3.connect(str(db))
    try:
        return [r[0] for r in c.execute("SELECT game_id FROM matches WHERE mode='TFT'")]
    finally:
        c.close()


# -- the shared rule (tft_standalone) ----------------------------------------------

def test_current_game_id_is_the_lcu_id_else_the_live_game_seen_recently(root, monkeypatch):
    assert ts.current_game_id() == ""                       # nothing known
    _live_game(CUR, monkeypatch)
    assert ts.current_game_id() == str(CUR)                 # post-game snapshot has no id
    monkeypatch.setattr(ts, "relay_lcu_snapshot",
                        lambda: {"phase": "InProgress", "game_id": "42"})
    assert ts.current_game_id() == "42"                     # the LCU's own id wins
    monkeypatch.setattr(ts, "relay_lcu_snapshot", lambda: None)
    assert ts.current_game_id(now=time.time() + ts.EOG_MAX_AGE_S + 5) == ""


def test_eog_for_game_is_a_positive_match_only(root):
    assert ts.eog_for_game(_doc(CUR), CUR) is not None
    assert ts.eog_for_game(_doc(CUR), str(CUR)) is not None
    assert ts.eog_for_game(_doc(OTHER), CUR) is None
    assert ts.eog_for_game(_doc(None), CUR) is None         # file names no game
    assert ts.eog_for_game(_doc(CUR), "") is None           # no current game
    assert ts.eog_for_game(_doc(CUR), None) is None


# -- reader 1: tft_final_board (per_round_record / resolve_final) --------------------

def test_another_games_fresh_file_is_not_the_ended_game(root, tmp_path, monkeypatch):
    """The ended game is CUR; the fresh, final file is OTHER's and the store
    holds OTHER's record: neither may be rated as the game that just ended."""
    _live_game(CUR, monkeypatch)
    _store(OTHER)
    _file(tmp_path, monkeypatch, _doc(OTHER))
    assert fb.per_round_record(now=time.time()) is None
    assert fb.resolve_final(root) is None
    assert pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH)) == ("", [])
    assert _rows(root) == []


def test_the_ended_games_own_file_is_still_rated(root, tmp_path, monkeypatch):
    """No over-gating: the file IS the ended game's -> rated at game end."""
    _live_game(CUR, monkeypatch)
    _file(tmp_path, monkeypatch, _doc(CUR))
    fin = fb.resolve_final(root)
    assert fin and fin["game_id"] == CUR and fin["source"] == fb.SOURCE_PER_ROUND
    grade, _ = pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH))
    assert grade == "S"
    assert _rows(root) == [CUR]


def test_the_ended_games_store_record_is_found_through_its_file(root, tmp_path, monkeypatch):
    _live_game(CUR, monkeypatch)
    _store(CUR, standing=2)
    _file(tmp_path, monkeypatch, _doc(CUR, standing=3, health=40, others_alive=2))
    fin = fb.resolve_final(root)
    assert fin["source"] == fb.SOURCE_STORE and fin["game_id"] == CUR


def test_the_lcu_snapshot_id_also_names_the_game(root, tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "relay_lcu_snapshot",
                        lambda: {"phase": "InProgress", "game_id": str(CUR)})
    _file(tmp_path, monkeypatch, _doc(CUR))
    assert fb.resolve_final(root)["game_id"] == CUR
    _file(tmp_path, monkeypatch, _doc(OTHER))
    assert fb.resolve_final(root) is None


def test_a_file_without_a_game_id_is_no_match(root, tmp_path, monkeypatch):
    _live_game(CUR, monkeypatch)
    _file(tmp_path, monkeypatch, _doc(None))
    assert fb.per_round_record(now=time.time()) is None
    assert fb.resolve_final(root) is None


def test_no_current_game_id_is_no_match(root, tmp_path, monkeypatch):
    """Nothing names the ended game (no LCU id, no live game this process
    served): the file's own id is not taken as the answer."""
    _file(tmp_path, monkeypatch, _doc(CUR))
    assert fb.per_round_record(now=time.time()) is None
    assert fb.resolve_final(root) is None


def test_a_live_game_seen_long_ago_names_nothing(root, tmp_path, monkeypatch):
    _live_game(CUR, monkeypatch, now=time.time() - ts.EOG_MAX_AGE_S - 60)
    _file(tmp_path, monkeypatch, _doc(CUR))
    assert fb.resolve_final(root) is None


def test_an_explicit_caller_id_still_decides(root, tmp_path, monkeypatch):
    _live_game(OTHER, monkeypatch)
    _file(tmp_path, monkeypatch, _doc(CUR))
    assert fb.resolve_final(root, game_id=CUR)["game_id"] == CUR
    assert fb.resolve_final(root, game_id=OTHER) is None


# -- reader 2: performance_tracker._tft_game_id (the legacy row's id) --------------

def test_legacy_row_never_takes_another_games_id(root, tmp_path, monkeypatch):
    """The legacy rating of CUR must not carry OTHER's id: the DB write
    upserts by game id, so it would overwrite OTHER's row."""
    _live_game(CUR, monkeypatch)
    _file(tmp_path, monkeypatch, _doc(OTHER, standing=2, health=40, others_alive=3))
    assert pt._tft_game_id() == 0
    grade, _ = pt.save_tft_rating(str(root), dict(VISION_3RD), dict(BLANK_COACH))
    assert grade == "A"
    assert _rows(root) == [0]


def test_legacy_row_takes_the_ended_games_id_from_its_own_file(root, tmp_path, monkeypatch):
    _live_game(CUR, monkeypatch)
    _file(tmp_path, monkeypatch, _doc(CUR, standing=2, health=40, others_alive=3))
    assert pt._tft_game_id() == CUR
    pt.save_tft_rating(str(root), dict(VISION_3RD), dict(BLANK_COACH))
    assert _rows(root) == [CUR]


def test_legacy_row_id_unknown_without_a_file_game_id_or_a_current_game(
        root, tmp_path, monkeypatch):
    _file(tmp_path, monkeypatch, _doc(CUR, standing=2, health=40, others_alive=3))
    assert pt._tft_game_id() == 0                           # no current game
    _live_game(CUR, monkeypatch)
    _file(tmp_path, monkeypatch, _doc(None, standing=2, health=40, others_alive=3))
    assert pt._tft_game_id() == 0                           # file names no game
