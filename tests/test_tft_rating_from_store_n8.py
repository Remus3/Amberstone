"""Session 134 defect N8: the TFT end-of-game rating said 8th / F / "Dark Star
Vertical" for a 1st-place Set 18 game.

Ground truth (ops/runtime/tft_qa/20261025-085349/QA_REPORT.md N8, re-read
this session against the live files):
  - 09:28:52 local "TFT rating: placement=8 ... grade=F"; data/ratings/
    last_tft.json and data/match_history.db row 8677 hold F / 8 / stage 0 /
    level 0 / game_id 0 / comp "Dark Star Vertical".
  - At that moment data/tft_live_data.json was the blank vision payload
    (stage_round "", level 0, no last_round_result) and
    data/tft_coaching_data.json the declared blank, which has NO alive_others
    key; performance_tracker.py:339 defaulted alive_others to 7 and :347 made
    that placement 8.
  - The comp came from data/comp_state.json "selected" (2026-09-03, a Set 17
    comp), used at :393 although the Set 18 meta has no such comp; :388-389
    also replaced the board with that comp's meta units.
  - The real record: data/tft_matches/<gameId>.eog.json (placement 1), and
    the standalone client's per-round file held standing 1 at game end.

Fixtures: tests/fixtures/tft_eog_stats_set18.json + tft_match_history_set18.json
(the RM-616 sanitised copies of the same s134 Set 18 game, gameId 1000000001,
local placement 1, level 9, last_round 33). Set 18 trait breakpoints are the
tracked data/meta/tft_set18_cdragon.json, copied into each tmp root.
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
from tft import tft_standalone

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
EOG_DOC = json.loads((FIX / "tft_eog_stats_set18.json").read_text(encoding="utf-8"))
HIST_DOC = json.loads((FIX / "tft_match_history_set18.json").read_text(encoding="utf-8"))
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"
GID = 1000000001

# The two game-end inputs exactly as they were at 09:28:52 (live files read
# this session): the blank vision payload and the declared coaching blank.
BLANK_LIVE = {"mode": "tft_live", "stage_round": "", "level": 0, "hp": 0,
              "board_units": [], "bench_units": [], "shop_units": [],
              "traits_active": [], "augments": [], "augment_select": False,
              "comp": "", "build": "", "buy": "", "sell": "", "keep": "",
              "augment_play": "", "loss": "", "unit_placement": "", "unit_swap": ""}
BLANK_COACH = {"mode": "tft", "action": "", "board": "", "econ": "", "rolldown": "",
               "items": "", "god_pick": "", "placement": "", "upgrade": "", "risk": ""}
STALE_COMP_STATE = {"selected": "Dark Star Vertical", "ignore_emblems": False,
                    "pbe": False, "built_items": {}}


def _per_round_doc(gid=GID, standing=1, health=96, others_alive=0):
    """A per-round TFTEoGStats.json document (statsBlock shape, the
    gameclient-eog-stats-block twin; tft/tft_standalone.py:295-325).
    Default = the match-3 final write: standing 1, 96 HP, nobody else alive."""
    players = [{"isInteractable": True, "ffaStanding": standing, "health": health,
                "partnerGroupId": 0,
                "boardPieces": [
                    {"championName": "TFT18_Ashe", "starLevel": 2, "price": 5,
                     "itemNames": ["TFT_Item_InfinityEdge"]},
                    {"championName": "TFT18_Diana", "starLevel": 2, "price": 3,
                     "itemNames": []}]}]
    for i in range(7):
        players.append({"isInteractable": False, "ffaStanding": i + 2,
                        "health": 30 if i < others_alive else 0,
                        "partnerGroupId": 0, "boardPieces": []})
    return {"gameId": gid, "gameMode": "TFT", "queueId": 1090, "queueType": "NORMAL_TFT",
            "isRanked": False,
            "statsBlock": {"gameLengthSeconds": 2081, "setCoreName": "TFTSet18",
                           "players": players}}


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A tmp script root with the tracked Set 18 game data, an isolated store,
    a fresh match db and NO per-round file."""
    r = tmp_path / "root"
    (r / "data" / "meta").mkdir(parents=True)
    shutil.copy(REPO / "data" / "meta" / "tft_set18_cdragon.json",
                r / "data" / "meta" / "tft_set18_cdragon.json")
    shutil.copy(REPO / "data" / "meta" / "tft_set18_meta.json",
                r / "data" / "meta" / "tft_set18_meta.json")
    store = r / "data" / "tft_matches"
    monkeypatch.setattr(tp, "_STORE_DIR", store)
    monkeypatch.setattr(pt, "_match_db", None)
    monkeypatch.setattr(tft_standalone, "eog_stats_path",
                        lambda: tmp_path / "no_such_TFTEoGStats.json")
    monkeypatch.setattr("tft.placement_aggregator.update_heatmap", lambda *a, **k: None)
    return r


def _write_per_round(tmp_path, monkeypatch, doc):
    p = tmp_path / "TFTEoGStats.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(tft_standalone, "eog_stats_path", lambda: p)
    return p


def _rows(root):
    db = root / "data" / "match_history.db"
    if not db.exists():
        return []
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute("SELECT * FROM matches ORDER BY id")]
    finally:
        c.close()


def _last(root):
    p = root / "data" / "ratings" / "last_tft.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _seed_comp_state(root, state=STALE_COMP_STATE):
    (root / "data" / "comp_state.json").write_text(json.dumps(state), encoding="utf-8")


def _store_eog(store_dir=None, now=None):
    rec = tp.parse_eog(EOG_DOC, now=now if now is not None else time.time())
    assert tp.persist(rec, store_dir=store_dir)
    return rec


def _store_history(store_dir=None, now=None):
    recs = tp.parse_history(HIST_DOC, LOCAL_PUUID, now=now if now is not None else time.time())
    assert recs and tp.persist(recs[0], store_dir=store_dir)
    return recs[0]


# -- the N8 reproduction ------------------------------------------------------------

def test_n8_game_end_inputs_rate_the_real_first_not_a_default_eighth(root, tmp_path, monkeypatch):
    """Match 3 as it happened: blank live + blank coaching + the stale
    comp_state, the per-round file holding standing 1, no store record yet."""
    _seed_comp_state(root)
    _write_per_round(tmp_path, monkeypatch, _per_round_doc())
    grade, notes = pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH))
    assert grade == "S"
    assert notes and notes[0].startswith("1st place")
    last = _last(root)
    assert last["tft_placement"] == 1 and last["rating"] == "S"
    assert last["label"].startswith("1ST")
    assert last["tft_game_id"] == GID
    assert last["tft_placement_source"] == fb.SOURCE_PER_ROUND
    assert "Dark Star" not in last["tft_comp"] and "Dark Star" not in last["champion"]
    assert last["tft_units"][:2] == ["Ashe 2-star", "Diana 2-star"]
    rows = [r for r in _rows(root) if r["mode"] == "TFT"]
    assert len(rows) == 1
    assert rows[0]["tft_placement"] == 1 and rows[0]["grade"] == "S"
    assert rows[0]["game_id"] == GID


def test_store_record_wins_and_names_the_comp_from_set18_breakpoints(root, tmp_path, monkeypatch):
    """EOG + history in the store for the per-round file's game: placement,
    level, stage and the board come from the store; active traits follow the
    Set 18 breakpoints (one-unit Brawler / Hunter / ... are NOT active)."""
    _seed_comp_state(root)
    _store_eog()
    _store_history()
    # The per-round file is a mid-game write of the same game (standing 3):
    # the store wins.
    _write_per_round(tmp_path, monkeypatch, _per_round_doc(standing=3, health=40,
                                                           others_alive=2))
    grade, _notes = pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH))
    last = _last(root)
    assert grade == "S" and last["tft_placement"] == 1
    assert last["tft_placement_source"] == fb.SOURCE_STORE
    assert last["tft_level"] == 9            # history participant level
    assert last["tft_stage"] == 6            # last_round 33 = 6-1
    assert last["tft_set"] == 18
    rec = tp.load(GID)
    me = fb.local_player(rec)
    bps = fb.trait_breakpoints(18, root)
    for t in fb.classify_traits(me["traits"], bps):
        name = f"{t['name']} {t['units']}"
        assert (name in last["tft_traits"]) == t["active"], name
    assert last["tft_comp"] and "Dark Star" not in last["tft_comp"]
    assert last["tft_comp"] == fb.comp_name(fb.classify_traits(me["traits"], bps))
    assert len(last["tft_units"]) == len(me["board"])


def test_no_placement_source_writes_no_rating_at_all(root):
    """Nothing holds the game: no rating file, no row - never a fabricated 8th."""
    grade, notes = pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH))
    assert (grade, notes) == ("", [])
    assert _last(root) is None
    assert _rows(root) == []


def test_alive_others_contradicted_by_live_hp_is_not_a_placement(root):
    """The pre-RM-292d reset literal (health 100, alive_others 7): an alive
    local player with seven others alive has not finished - not 8th."""
    coach = dict(BLANK_COACH, health=100, alive_others=7)
    assert pt.save_tft_rating(str(root), dict(BLANK_LIVE), coach) == ("", [])


def test_alive_others_still_rates_a_measured_elimination(root):
    coach = dict(BLANK_COACH, health=0, alive_others=4)
    grade, _ = pt.save_tft_rating(str(root), dict(BLANK_LIVE), coach)
    assert grade == pt._TFT_GRADE[5]


def test_stale_comp_state_from_another_set_never_names_the_game(root):
    """A vision-path rating (no store, no per-round file) with the planner
    selection from Set 17: the Set 18 meta has no such comp, so the selection
    is ignored and the observed traits name the comp."""
    _seed_comp_state(root)
    live = dict(BLANK_LIVE, last_round_result="3rd", stage_round="5-2", level=8,
                traits_active=["Lunar 3", "Blossom 3"], board_units=["Ashe 2-star"])
    grade, _ = pt.save_tft_rating(str(root), live, dict(BLANK_COACH))
    last = _last(root)
    assert grade == "A"
    assert "Dark Star" not in last["tft_comp"]
    assert last["tft_units"] == ["Ashe 2-star"]      # not replaced by meta units


def test_rate_tft_game_enriches_the_game_end_row_in_place(root, tmp_path, monkeypatch):
    """The capture lands AFTER the game-end rating (match 3 order: rating
    09:28:52, EOG record 09:29:44): the per-round file gave the placement but
    no level / stage; the store record fills them into the SAME row (same id,
    same timestamp, same game id) and last_tft.json follows."""
    _write_per_round(tmp_path, monkeypatch, _per_round_doc())
    assert pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH))[0] == "S"
    before = [r for r in _rows(root) if r["mode"] == "TFT"]
    assert len(before) == 1 and before[0]["tft_level"] == 0
    _store_eog()
    _store_history()
    grade, _ = pt.rate_tft_game(str(root), GID)
    assert grade == "S"
    after = [r for r in _rows(root) if r["mode"] == "TFT"]
    assert len(after) == 1
    assert after[0]["id"] == before[0]["id"]
    assert after[0]["timestamp"] == before[0]["timestamp"]
    assert after[0]["game_id"] == GID
    assert (after[0]["tft_placement"], after[0]["tft_level"], after[0]["tft_stage"]) == (1, 9, 6)
    last = _last(root)
    assert (last["tft_level"], last["tft_placement_source"]) == (9, fb.SOURCE_STORE)


def test_unfinished_per_round_file_is_not_a_placement(root, tmp_path, monkeypatch):
    """A per-round write where the local player is alive and others are too is
    a mid-game standing, not a result: no rating until the store record."""
    _write_per_round(tmp_path, monkeypatch, _per_round_doc(standing=2, health=40,
                                                           others_alive=3))
    assert pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH)) == ("", [])
    assert _rows(root) == []
    _store_eog()
    assert pt.rate_tft_game(str(root), GID)[0] == "S"
    rows = [r for r in _rows(root) if r["mode"] == "TFT"]
    assert [(r["game_id"], r["tft_placement"]) for r in rows] == [(GID, 1)]


def test_eliminated_per_round_standing_is_final(root, tmp_path, monkeypatch):
    _write_per_round(tmp_path, monkeypatch, _per_round_doc(standing=6, health=0,
                                                           others_alive=5))
    grade, _ = pt.save_tft_rating(str(root), dict(BLANK_LIVE), dict(BLANK_COACH))
    assert grade == pt._TFT_GRADE[6]
    assert _last(root)["tft_placement"] == 6


def test_rate_tft_game_older_game_inserts_a_row_but_keeps_the_newest_last_file(root):
    newer = _store_eog(now=time.time())
    pt.rate_tft_game(str(root), GID)
    assert _last(root)["tft_game_id"] == GID
    old_doc = json.loads(json.dumps(EOG_DOC))
    old_doc["gameId"] = GID + 7
    for p in old_doc["players"]:
        if p.get("isLocalPlayer"):
            p["ffaStanding"] = 4
            p["rank"] = 4
    old = tp.parse_eog(old_doc, now=newer["captured_at_unix"] - 3600)
    assert tp.persist(old)
    grade, _ = pt.rate_tft_game(str(root), GID + 7)
    assert grade == "B"
    assert _last(root)["tft_game_id"] == GID                # newest kept
    by_gid = {r["game_id"]: r for r in _rows(root) if r["mode"] == "TFT"}
    assert set(by_gid) == {GID, GID + 7}
    assert by_gid[GID + 7]["tft_placement"] == 4
    # Re-rating is idempotent: still one row per game.
    pt.rate_tft_game(str(root), GID + 7)
    assert len([r for r in _rows(root) if r["mode"] == "TFT"]) == 2


def test_rate_tft_game_without_a_record_is_a_no_op(root):
    assert pt.rate_tft_game(str(root), GID) == ("", [])
    assert _rows(root) == [] and _last(root) is None


def test_plan_tft_rating_is_the_rating_without_any_write(root):
    """The backfill's dry run plans with this: same grade / row / newest
    decision as rate_tft_game, and nothing on disk changes."""
    _store_eog()
    plan = pt.plan_tft_rating(str(root), GID)
    assert plan["grade"] == "S" and plan["game_id"] == GID
    assert plan["row"]["game_id"] == GID and plan["row"]["tft_placement"] == 1
    assert plan["newest"] is True
    assert _rows(root) == [] and _last(root) is None
    assert pt.plan_tft_rating(str(root), GID + 5) is None
    assert pt.plan_tft_rating(str(root), "x") is None
    assert pt.rate_tft_game(str(root), GID)[0] == plan["grade"]
    assert _last(root)["tft_game_id"] == GID


def test_per_round_file_of_another_game_is_not_used(root, tmp_path, monkeypatch):
    _write_per_round(tmp_path, monkeypatch, _per_round_doc(gid=GID + 1))
    assert fb.resolve_final(root, game_id=GID) is None
    assert fb.resolve_final(root)["game_id"] == GID + 1


def test_legacy_last_file_without_game_id_is_replaced_only_by_a_newer_game(root):
    """The live last_tft.json written at 09:28 carries no game id: a store
    record that ended earlier (match 1 / 2) must not replace it."""
    ratings = root / "data" / "ratings"
    ratings.mkdir(parents=True)
    legacy = {"rating": "F", "tft_placement": 8, "timestamp": "2026-10-25 09:28"}
    (ratings / "last_tft.json").write_text(json.dumps(legacy), encoding="utf-8")
    legacy_ts = time.mktime(time.strptime("2026-10-25 09:28", "%Y-%m-%d %H:%M"))
    _store_eog(now=legacy_ts - 3000)
    pt.rate_tft_game(str(root), GID)
    assert _last(root)["rating"] == "F"
    newer_doc = json.loads(json.dumps(EOG_DOC))
    newer_doc["gameId"] = GID + 2
    assert tp.persist(tp.parse_eog(newer_doc, now=legacy_ts + 100))
    pt.rate_tft_game(str(root), GID + 2)
    assert _last(root)["tft_game_id"] == GID + 2


# -- units -----------------------------------------------------------------------

@pytest.mark.parametrize("last_round,stage", [
    (None, 0), (0, 0), (1, 1), (4, 1), (5, 2), (11, 2), (12, 3), (32, 5), (33, 6),
])
def test_stage_from_last_round(last_round, stage):
    assert fb.stage_from_last_round(last_round) == stage


def test_set18_breakpoints_are_the_games_own_and_skip_bad_entries(root):
    bps = fb.trait_breakpoints(18, root)
    assert bps["Lunar"] == [2, 3, 4, 5] and bps["Flora Fatalis"] == [1, 2]
    assert bps["Rival"] == [1, 2]            # [1, 1, 2] deduplicated
    assert "Eclipse" not in bps              # [None]
    assert fb.trait_breakpoints(17, root) == {}   # not ingested here: no fallback


def test_comp_name_orders_by_breakpoint_share_and_drops_uniques():
    bps = {"Flora Fatalis": [1, 2], "Lunar": [2, 3, 4, 5], "Blossom": [3, 5, 7, 9, 11],
           "Executioner": [2, 3, 4], "Attuned": [1], "Hunter": [2, 3, 4, 5]}
    traits = [{"name": n, "units": u} for n, u in (
        ("Blossom", 3), ("Lunar", 3), ("Executioner", 2), ("Flora Fatalis", 2),
        ("Attuned", 1), ("Hunter", 1))]
    cl = fb.classify_traits(traits, bps)
    assert {t["name"] for t in cl if t["active"]} == {
        "Blossom", "Lunar", "Executioner", "Flora Fatalis", "Attuned"}
    assert fb.comp_name(cl) == "Flora Fatalis 2 / Lunar 3 / Executioner 2"


# -- the collector re-rates when a record lands --------------------------------------

class _Lcu:
    def __init__(self, routes):
        self.routes = dict(routes)

    def __call__(self, path):
        for prefix, body in self.routes.items():
            if path == prefix or path.startswith(prefix):
                return body
        return None


@pytest.fixture
def collector(root, tmp_path, monkeypatch):
    import lcu.lcu_postgame_collector as mod
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "pg.db")
    monkeypatch.setattr(mod, "_RATING_ROOT", root)
    mod._ensure_schema()

    def make(routes):
        c = mod.PostgameCollector.__new__(mod.PostgameCollector)
        c._trigger_at = None
        c._lcu_get = _Lcu(routes)
        return c
    return make


_SESSION = {"phase": "PreEndOfGame",
            "gameData": {"gameId": GID, "queue": {"id": 1090, "gameMode": "TFT"}},
            "map": {"gameMode": "TFT"}}


def test_collector_eog_capture_rates_the_game(root, collector):
    c = collector({tp.EOG_PATH: EOG_DOC, "/lol-gameflow/v1/session": _SESSION})
    assert c._capture_tft_eog() is True
    last = _last(root)
    assert (last["tft_game_id"], last["tft_placement"], last["rating"]) == (GID, 1, "S")
    assert [(r["game_id"], r["tft_placement"]) for r in _rows(root)] == [(GID, 1)]


def test_collector_history_record_enriches_the_same_row(root, collector):
    c = collector({tp.EOG_PATH: EOG_DOC, "/lol-gameflow/v1/session": _SESSION,
                   "/lol-summoner/v1/current-summoner": {"puuid": LOCAL_PUUID},
                   f"/lol-match-history/v1/products/tft/{LOCAL_PUUID}/matches": HIST_DOC})
    assert c._capture_tft_eog() is True
    assert c._tft_history_backfill() == 1
    rows = _rows(root)
    assert len(rows) == 1
    assert (rows[0]["tft_level"], rows[0]["tft_stage"]) == (9, 6)


def test_first_history_read_catches_up_records_an_older_build_stored(root, collector,
                                                                    monkeypatch):
    """The records are already in the store (written while a build without
    the re-rate hook ran - the live state after 09:31), and no rating row
    exists: the process's first history read rates them once; later reads
    re-rate only what they add."""
    _store_eog()
    _store_history()
    calls = []
    real = pt.rate_tft_game
    monkeypatch.setattr(pt, "rate_tft_game",
                        lambda sd, gid, **k: calls.append(gid) or real(sd, gid, **k))
    c = collector({"/lol-summoner/v1/current-summoner": {"puuid": LOCAL_PUUID},
                   f"/lol-match-history/v1/products/tft/{LOCAL_PUUID}/matches": HIST_DOC})
    assert c._tft_history_backfill() == 0
    assert calls == [GID]
    rows = _rows(root)
    assert [(r["game_id"], r["tft_placement"], r["tft_level"]) for r in rows] == [(GID, 1, 9)]
    assert c._tft_history_backfill() == 0
    assert calls == [GID]


def test_collector_rating_failure_never_costs_the_capture(root, collector, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("rating down")
    monkeypatch.setattr(pt, "rate_tft_game", boom)
    c = collector({tp.EOG_PATH: EOG_DOC, "/lol-gameflow/v1/session": _SESSION})
    assert c._capture_tft_eog() is True
    assert tp.has_record(GID, tp.SOURCE_EOG)


# -- the db seams ------------------------------------------------------------------

def test_match_db_upsert_by_game_id_inserts_then_updates(tmp_path):
    from core.match_db import MatchDB
    db = MatchDB(tmp_path / "m.db")
    assert db.upsert_by_game_id({"mode": "TFT", "game_id": 5, "grade": "F",
                                 "tft_placement": 8, "timestamp": "2026-10-25 09:28:52"}) == "inserted"
    assert db.upsert_by_game_id({"mode": "TFT", "game_id": 5, "grade": "S",
                                 "tft_placement": 1, "tft_traits": ["Lunar 3"]}) == "updated"
    rows = db.get_recent("TFT", 10)
    assert len(rows) == 1
    assert rows[0]["grade"] == "S" and rows[0]["tft_placement"] == 1
    assert rows[0]["timestamp"] == "2026-10-25 09:28:52"
    assert json.loads(rows[0]["tft_traits"]) == ["Lunar 3"]
    assert db.upsert_by_game_id({"mode": "TFT", "game_id": 0}) == "failed"


def test_get_db_follows_the_script_root(tmp_path, monkeypatch):
    """The pollution vector behind the junk rows: _get_db cached the FIRST
    root it saw, so every later save in the process - whatever root it was
    handed - wrote that first database."""
    monkeypatch.setattr(pt, "_match_db", None)
    a, b = tmp_path / "a", tmp_path / "b"
    db_a = pt._get_db(str(a))
    db_b = pt._get_db(str(b))
    assert db_a is not None and db_b is not None
    assert Path(db_b._path) == b / "data" / "match_history.db"
    assert Path(db_a._path) == a / "data" / "match_history.db"
