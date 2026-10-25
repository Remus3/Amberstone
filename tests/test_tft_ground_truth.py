"""TFT-08 (docs/TFT_PROGRAM.md section 7): post-match ground truth.

The RM-616 placement store (tft/tft_placement.py, data/tft_matches/) already
holds the LCU post-game record of every finished TFT game: placement, final
boards, traits, level, gold left and last round for all 8 players, no
identities. TFT-08 does NOT add a second LCU collector; it BRIDGES those
records into the per-round store's match / player / gt_board / gt_player
tables (tft/rounds/ground_truth.py), idempotent by game id, exposes
`final_boards(set_id)` for the tft/engine comp catalogue, grades the store's vision rows
against the ground truth (tft/rounds/accuracy.py), and lets the CV accuracy
harness read an RM-616 record as its `--lcu-eog` oracle (the LCU document
itself 404s once the client is back in Lobby, section 8 item 13).

Fixtures (repo is PUBLIC, all sanitised):
  tests/fixtures/tft_eog_stats_set18.json + tft_match_history_set18.json
      the RM-616 pair (game 1000000001, EOG + history of the same game).
  tests/fixtures/tft_ground_truth/rm616_eog_set18_live.json
      a REAL RM-616 record of a later s134 game, copied from the live
      data/tft_matches/ store: the Riot game id replaced by 1000000002 and the
      capture instant by a placeholder; everything else as RM-616 wrote it
      (it never stored a name, puuid, icon or companion).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

import tools.tft_cv_accuracy as cv
from tft import tft_placement as tp
from tft.engine import comps, milestones
from tft.rounds import accuracy as gacc
from tft.rounds import ground_truth as gt
from tft.rounds import store as st
from tft.rounds.store import Env, RoundStore

FIX = Path(__file__).resolve().parent / "fixtures"
LIVE_FIXTURE = FIX / "tft_ground_truth" / "rm616_eog_set18_live.json"
EOG_FIXTURE = FIX / "tft_eog_stats_set18.json"
HIST_FIXTURE = FIX / "tft_match_history_set18.json"
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"   # the RM-616 history placeholder
LIVE_GID = 1000000002
PAIR_GID = 1000000001
SALT = b"tft08-synthetic-salt-0123456789ab"
KEY12 = re.compile(r"[0-9a-f]{12}")


def _live_record() -> dict:
    return json.loads(LIVE_FIXTURE.read_text(encoding="ascii"))


def _local(rec: dict) -> dict:
    return next(p for p in rec["players"] if p["is_local"])


@pytest.fixture
def rm616_dir(tmp_path):
    d = tmp_path / "tft_matches"
    d.mkdir()
    return d


@pytest.fixture
def store(tmp_path):
    s = RoundStore.open(tmp_path / "tft" / "tft_rounds.db")
    try:
        yield s
    finally:
        s.close()


def _put_live(rm616_dir):
    shutil.copyfile(LIVE_FIXTURE, rm616_dir / f"{LIVE_GID}.eog.json")


def _put_pair(rm616_dir, *, history=True):
    eog = tp.parse_eog(json.loads(EOG_FIXTURE.read_text(encoding="utf-8")), now=1_700_002_200.0)
    assert tp.persist(eog, store_dir=rm616_dir)
    if history:
        (hist,) = tp.parse_history(json.loads(HIST_FIXTURE.read_text(encoding="utf-8")),
                                   LOCAL_PUUID, now=1_700_003_000.0)
        assert tp.persist(hist, store_dir=rm616_dir)


def _sync(store, rm616_dir):
    out = gt.sync(store, store_dir=rm616_dir, salt=SALT)
    assert store.flush()
    return out


def _match_by_gid(store, gid):
    rows = [m for m in store.list_matches() if m["game_id"] == gid]
    assert len(rows) == 1, rows
    return store.get_match(rows[0]["match_id"])


# ------------------------------------------------------------- the fixture

def test_live_fixture_is_ascii_lf_and_identity_free():
    raw = LIVE_FIXTURE.read_bytes()
    assert all(b < 128 for b in raw) and b"\r\n" not in raw
    rec = _live_record()
    assert rec["schema"] == tp.SCHEMA_VERSION and rec["source"] == tp.SOURCE_EOG
    assert rec["game_id"] == LIVE_GID
    assert rec["captured_at"] == "2026-01-01 00:00:00"

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)

    assert not set(keys(rec)) & tp.IDENTITY_KEYS

    # every VALUE passes the store's identity guard; the only keys it refuses
    # are the game-data display `name`s (unit / item / trait), which the bridge
    # never hands to the store
    def drop_names(o):
        if isinstance(o, dict):
            return {k: drop_names(v) for k, v in o.items() if k != "name"}
        if isinstance(o, list):
            return [drop_names(v) for v in o]
        return o

    assert st.identity_violations(drop_names(rec)) == []
    places = sorted(p["placement"] for p in rec["players"])
    assert places == list(range(1, 9))
    assert sum(p["is_local"] for p in rec["players"]) == 1


# ------------------------------------------------------------- the bridge

def test_bridge_loads_the_real_match_into_the_round_store(store, rm616_dir):
    _put_live(rm616_dir)
    counts = _sync(store, rm616_dir)
    assert counts["added"] == 1 and counts["games"] == 1
    rec = _live_record()
    doc = _match_by_gid(store, LIVE_GID)
    m = doc["match"]
    assert (m["set_id"], m["set_core_name"], m["queue_id"], m["queue_kind"]) == (18, "TFTSet18", 1090, "normal")
    assert (m["placement"], m["placement_conf"], m["placement_src"]) == (1, 1.0, "lcu")
    assert m["gt_status"] == "partial" and m["gt_sources"] == ["lcu_eog"]
    assert m["ended_at"] == pytest.approx(rec["captured_at_unix"])
    assert m["started_at"] == pytest.approx(rec["captured_at_unix"] - rec["game_length_s"])
    players = doc["players"]
    assert len(players) == 8
    assert all(KEY12.fullmatch(p["player_key"]) for p in players)
    local = [p for p in players if p["is_local"]]
    assert len(local) == 1 and local[0]["slot"] == 1 and local[0]["final_standing"] == 1
    assert sorted(p["final_standing"] for p in players) == list(range(1, 9))
    assert sorted(p["slot"] for p in players) == list(range(1, 9))
    # every unit of all 8 final boards, nothing else
    assert len(doc["gt_board"]) == sum(len(p["board"]) for p in rec["players"]) == 52
    assert {r["source"] for r in doc["gt_board"]} == {"lcu_eog"}
    mine = [r for r in doc["gt_board"] if r["player_key"] == local[0]["player_key"]]
    want = Counter((u["character_id"], u["star"], u["cost"], tuple(sorted(i["name_id"] for i in u["items"])))
                   for u in _local(rec)["board"])
    got = Counter((r["champion_api"], r["star"], r["cost"], tuple(sorted(r["items"]))) for r in mine)
    assert got == want and len(mine) == 10
    gplayers = doc["gt_player"]
    assert [p["placement"] for p in gplayers] == list(range(1, 9))
    assert all(p["level"] is None and p["gold_left"] is None for p in gplayers)  # EOG carries neither


def test_bridge_is_idempotent_by_game_id(store, rm616_dir):
    _put_live(rm616_dir)
    first = _sync(store, rm616_dir)
    second = _sync(store, rm616_dir)
    assert first["added"] == 1
    assert second["unchanged"] == 1 and second["added"] == second["updated"] == 0
    doc = _match_by_gid(store, LIVE_GID)
    assert len(store.list_matches()) == 1
    assert len(doc["players"]) == 8 and len(doc["gt_board"]) == 52 and len(doc["gt_player"]) == 8


def test_history_arriving_later_completes_the_same_match(store, rm616_dir):
    _put_pair(rm616_dir, history=False)
    assert _sync(store, rm616_dir)["added"] == 1
    assert _match_by_gid(store, PAIR_GID)["match"]["gt_status"] == "partial"
    (hist,) = tp.parse_history(json.loads(HIST_FIXTURE.read_text(encoding="utf-8")), LOCAL_PUUID,
                               now=1_700_003_000.0)
    assert tp.persist(hist, store_dir=rm616_dir)
    assert _sync(store, rm616_dir)["updated"] == 1
    doc = _match_by_gid(store, PAIR_GID)
    assert len(store.list_matches()) == 1                       # still ONE match row
    m = doc["match"]
    assert m["gt_status"] == "full" and m["gt_sources"] == ["lcu_eog", "lcu_mh"]
    assert m["set_id"] == 18
    assert m["ended_at"] == pytest.approx(hist["ended_at_unix"])  # history's end time wins
    by_place = {p["placement"]: p for p in hist["players"]}
    for row in doc["gt_player"]:
        h = by_place[row["placement"]]
        assert (row["level"], row["gold_left"], row["last_round"]) == (h["level"], h["gold_left"], h["last_round"])
        assert row["eliminated_at"] == pytest.approx(h["time_eliminated_s"])
    local = next(p for p in doc["gt_player"] if p["placement"] == 1)
    assert (local["level"], local["gold_left"], local["last_round"]) == (9, 32, 33)  # hist fixture, local row
    per_source = Counter(r["source"] for r in doc["gt_board"])
    assert per_source == {"lcu_eog": 50, "lcu_mh": 50}            # 9 + 6 x 6 + 5 units, per source
    assert sum(len(p["board"]) for p in hist["players"]) == 50
    assert len(doc["players"]) == 8


def test_bridge_joins_a_match_the_live_capture_already_opened(store, rm616_dir):
    """A match TFT-07 opened live (same game id, real store keys) is completed
    in place: no second match row, the local player keeps its live key."""
    live_local = st.player_key("live-local-synthetic", SALT)
    live_second = st.player_key("live-second-synthetic", SALT)
    mid = store.begin_match({"match_id": "20260101-000000-live", "game_id": LIVE_GID, "set_id": 18,
                             "queue_id": 1090, "started_at": 1_767_000_000.0})
    store.upsert_player(mid, live_local, slot=1, is_local=True)
    store.upsert_player(mid, live_second, slot=2, final_standing=Env(2, 0.7, "ocr"))
    assert store.flush()
    _put_live(rm616_dir)
    assert _sync(store, rm616_dir)["updated"] == 1
    assert len(store.list_matches()) == 1
    doc = store.get_match(mid)
    keys = {p["player_key"] for p in doc["players"]}
    assert len(keys) == 8 and {live_local, live_second} <= keys
    assert doc["match"]["started_at"] == 1_767_000_000.0          # live meta untouched
    second = next(p for p in doc["players"] if p["player_key"] == live_second)
    assert (second["final_standing"], second["final_standing_src"]) == (2, "ocr")  # live read kept
    local_rows = [r for r in doc["gt_board"] if r["player_key"] == live_local]
    assert len(local_rows) == 10
    assert {r["player_key"] for r in doc["gt_player"] if r["placement"] == 2} == {live_second}


def test_sync_writes_per_field_accuracy_for_every_bridged_match(store, rm616_dir):
    """Oracle B lands as gt_* rows PLUS per-field accuracy (TFT-08 row). A
    bridge-only match has no vision rows, so every field it has truth for is
    written with coverage 0 (the HIDE gate), and placement - whose only
    source is the lcu oracle itself - is never graded."""
    _put_pair(rm616_dir)
    counts = _sync(store, rm616_dir)
    assert counts["added"] == 1
    doc = _match_by_gid(store, PAIR_GID)
    stored = {r["field"]: r for r in doc["accuracy"]}
    assert set(stored) == {"final_board_units", "final_board_stars", "final_board_items",
                           "final_level", "final_gold"}
    assert counts["accuracy_rows"] == 5
    assert all(r["coverage"] == 0.0 and r["correct"] == 0 for r in stored.values())
    assert stored["final_board_units"]["n"] == 8 and stored["final_level"]["n"] == 1
    again = _sync(store, rm616_dir)
    assert again["unchanged"] == 1 and again["accuracy_rows"] == 0
    assert len(_match_by_gid(store, PAIR_GID)["accuracy"]) == 5


def test_sync_regrades_a_live_match_when_ground_truth_lands(store, rm616_dir):
    """A match the live capture opened (vision rows already in) is graded
    the moment its ground truth is bridged."""
    _put_pair(rm616_dir, history=False)
    _sync(store, rm616_dir)
    doc = _match_by_gid(store, PAIR_GID)
    mid = _vision_last_round(store, doc, local_level=9, local_gold=32)
    (hist,) = tp.parse_history(json.loads(HIST_FIXTURE.read_text(encoding="utf-8")), LOCAL_PUUID,
                               now=1_700_003_000.0)
    assert tp.persist(hist, store_dir=rm616_dir)
    counts = _sync(store, rm616_dir)
    assert counts["updated"] == 1 and counts["accuracy_rows"] == 5
    stored = {r["field"]: r for r in store.get_match(mid)["accuracy"]}
    assert (stored["final_board_units"]["correct"], stored["final_board_units"]["coverage"]) == (2, 2 / 8)
    assert (stored["final_level"]["correct"], stored["final_gold"]["correct"]) == (1, 1)


def test_bridge_skips_unusable_records_and_never_raises(store, rm616_dir):
    _put_live(rm616_dir)
    (rm616_dir / "1234567.eog.json").write_text('{"schema": 99}', encoding="ascii")
    (rm616_dir / "7654321.eog.json").write_text("not json", encoding="ascii")
    (rm616_dir / "notes.txt").write_text("x", encoding="ascii")
    counts = _sync(store, rm616_dir)
    assert counts["games"] == 3 and counts["added"] == 1 and counts["skipped"] == 2
    assert counts["dropped"] == 0
    assert gt.sync(store, store_dir=rm616_dir / "missing", salt=SALT)["games"] == 0


def test_a_bad_unit_never_drops_the_rest_of_the_board(store, rm616_dir):
    rec = _live_record()
    rec["players"][0]["board"][0]["star"] = 9          # outside gt_board's 1..4
    rec["players"][0]["board"][1]["cost"] = -3         # outside 0..10
    (rm616_dir / f"{LIVE_GID}.eog.json").write_text(json.dumps(rec), encoding="ascii")
    _sync(store, rm616_dir)
    doc = _match_by_gid(store, LIVE_GID)
    assert len(doc["gt_board"]) == 52
    assert store.stats()["invalid"] == 0


def test_bridged_match_exports_a_scrubbed_fixture(store, rm616_dir, tmp_path):
    _put_live(rm616_dir)
    _sync(store, rm616_dir)
    mid = store.list_matches()[0]["match_id"]
    out = store.export_fixture(mid, tmp_path / "fx", name="tft08_live")
    fx = json.loads(out.read_text(encoding="ascii"))
    assert st.scrub_violations(fx) == []
    assert sorted({r["player_key"] for r in fx["gt_board"]}) == [f"P{i}" for i in range(1, 9)]
    assert next(p for p in fx["players"] if p["is_local"])["player_key"] == "P1"
    assert str(LIVE_GID) not in out.read_text(encoding="ascii")


# ------------------------------------------------------------- final_boards

def test_final_boards_is_the_local_board_per_match_for_the_engine(store, rm616_dir):
    _put_live(rm616_dir)
    _put_pair(rm616_dir)
    _sync(store, rm616_dir)
    boards = gt.final_boards(store, set_id=18)
    assert len(boards) == 2
    by_gid = {m["game_id"]: m["match_id"] for m in store.list_matches()}
    live = boards[by_gid[LIVE_GID]]
    assert Counter(r["champion_api"] for r in live) == Counter(u["character_id"] for u in _local(_live_record())["board"])
    assert {r["source"] for r in live} == {"lcu_eog"}
    pair = boards[by_gid[PAIR_GID]]
    assert {r["source"] for r in pair} == {"lcu_eog"}            # lcu_eog preferred over lcu_mh
    assert len(pair) == 9
    assert gt.final_boards(store, set_id=17) == {}


# ------------------------------------------- tft/engine on the REAL store

def test_records_from_store_reads_the_real_store(store, rm616_dir):
    _put_live(rm616_dir)
    _sync(store, rm616_dir)
    (rec,) = milestones.records_from_store(store, set_id=18)
    assert (rec["set_id"], rec["queue_kind"], rec["placement"], rec["placement_src"]) == (18, "normal", 1, "lcu")
    assert Counter(u["champion_api"] for u in rec["final_board"]) == Counter(
        u["character_id"] for u in _local(_live_record())["board"])
    # the same record whichever way the board arrives
    (rec2,) = milestones.records_from_store(store, set_id=18, final_boards=gt.final_boards(store, set_id=18))
    assert Counter(u["champion_api"] for u in rec2["final_board"]) == Counter(
        u["champion_api"] for u in rec["final_board"])
    sd = comps.load_set_data(18)
    cat = comps.build_catalogue([rec], sd)
    (comp,) = cat["comps"]
    assert comp["games"] == 1 and comp["avg_placement"] == 1.0
    carry = comp["carry"]
    assert carry and carry["api"] in {u["character_id"] for u in _local(_live_record())["board"] if u["items"]}
    assert cat["assignments"][rec["match_id"]] == comp["comp_id"]


def _round_bundle_match(store):
    """A synthetic match written through the real writer API: 3 labelled
    rounds, local + one opponent board in round 2, 3 rerolls in round 3."""
    me, other = st.player_key("synthetic-local", SALT), st.player_key("synthetic-other", SALT)
    mid = store.begin_match({"match_id": "20260101-000000-rb", "game_id": 5550000001, "set_id": 18,
                             "queue_id": 1090, "started_at": 1_767_000_000.0})
    store.upsert_player(mid, me, slot=1, is_local=True)
    store.upsert_player(mid, other, slot=2)
    for seq, label, level in ((1, "2-1", 3), (2, "2-2", 4), (3, "2-3", 5)):
        store.upsert_round(mid, seq, label=label, level=Env(level, 0.95, "ocr"),
                           gold_start=Env(30, 0.95, "ocr"))
    store.put_units(mid, 2, "planning_start", me, [
        {"zone": "board", "champion_api": "DA_18_Yorick", "star": 2, "items": ["TFT_Item_BFSword"],
         "cost": 1, "conf": 0.9, "src": "icon"}])
    store.put_units(mid, 2, "planning_start", other, [
        {"zone": "board", "champion_api": "DA_18_Leona", "star": 1, "items": [], "cost": 1,
         "conf": 0.9, "src": "icon"}])
    for idx in range(3):
        store.put_shop_refresh(mid, 3, idx, cause="reroll", ts=1_767_000_100.0 + idx,
                               gold_before=30 - 2 * idx, gold_after=28 - 2 * idx, conf=0.9, src="ocr")
    store.end_match(mid, Env(3, 1.0, "lcu"), ended_at=1_767_002_000.0)
    assert store.flush()
    return mid, me


def test_records_from_store_flattens_the_real_round_bundles(store):
    """The real read API nests unit_obs and shop_refresh rows inside each
    round bundle (store.iter_rounds / get_match["rounds"]); the engine must
    find them there, local player only."""
    mid, _me = _round_bundle_match(store)
    (rec,) = milestones.records_from_store(store, set_id=18)
    assert rec["match_id"] == mid and len(rec["rounds"]) == 3
    assert [u["champion_api"] for u in rec["units"]] == ["DA_18_Yorick"]          # local only
    assert len(rec["shop_refreshes"]) == 3
    mined = milestones.mine_match(rec, comps.load_set_data(18))
    assert mined["has_unit_obs"] is True
    assert mined["first_rolldown"] == "2-3"
    assert mined["level_reached"]["4"] == "2-2" and mined["level_reached"]["5"] == "2-3"


# ------------------------------------------------------------- accuracy

def _vision_last_round(store, doc, local_level, local_gold):
    """A synthetic last resolved round: vision rows for P1 (exact), P2 (one
    star wrong) and an eog_file row for P3 (an oracle source, never graded)."""
    mid = doc["match"]["match_id"]
    by_place = {p["placement"]: p["player_key"] for p in doc["gt_player"]}
    rows = {}
    for r in doc["gt_board"]:
        if r["source"] == "lcu_eog":
            rows.setdefault(r["player_key"], []).append(r)
    store.upsert_round(mid, 30, label="6-2", level=Env(local_level, 0.9, "ocr"),
                       gold_end=Env(local_gold, 0.9, "ocr"))

    def units(key, src, bump_first=False):
        out = []
        for i, r in enumerate(rows[key]):
            star = r["star"] % 3 + 1 if bump_first and i == 0 else r["star"]   # 1->2, 2->3, 3->1
            out.append({"zone": "board", "champion_api": r["champion_api"], "star": star,
                        "items": list(r["items"]), "cost": r["cost"], "conf": 0.9, "src": src})
        return out

    store.put_units(mid, 30, "planning_end", by_place[1], units(by_place[1], "icon"))
    store.put_units(mid, 30, "planning_end", by_place[2], units(by_place[2], "icon", bump_first=True))
    store.put_units(mid, 30, "planning_end", by_place[3], units(by_place[3], "eog_file"))
    assert store.flush()
    return mid


def test_final_accuracy_grades_vision_rows_against_ground_truth(store, rm616_dir):
    _put_pair(rm616_dir)
    _sync(store, rm616_dir)
    doc = _match_by_gid(store, PAIR_GID)
    mid = _vision_last_round(store, doc, local_level=9, local_gold=31)   # gt: level 9, gold 32
    rows = {r["field"]: r for r in gacc.write_final_accuracy(store, mid, extractor_version="t08")}
    assert store.flush()
    assert rows["final_board_units"]["n"] == 8
    assert rows["final_board_units"]["correct"] == 2
    assert rows["final_board_units"]["coverage"] == pytest.approx(2 / 8)
    assert rows["final_board_stars"]["correct"] == 1                   # P2's bumped star
    assert rows["final_board_items"]["correct"] == 2
    assert (rows["final_level"]["n"], rows["final_level"]["correct"], rows["final_level"]["coverage"]) == (1, 1, 1.0)
    assert (rows["final_gold"]["n"], rows["final_gold"]["correct"]) == (1, 0)
    assert "placement" not in rows       # the match placement IS the lcu oracle: never graded against itself
    stored = {r["field"]: r for r in store.get_match(mid)["accuracy"]}
    assert set(stored) == set(rows)
    assert stored["final_board_units"]["extractor_version"] == "t08"
    assert stored["final_board_units"]["correct"] == 2


def test_final_accuracy_without_vision_rows_answers_nothing(store, rm616_dir):
    _put_live(rm616_dir)
    _sync(store, rm616_dir)
    mid = store.list_matches()[0]["match_id"]
    rows = {r["field"]: r for r in gacc.final_accuracy(store.get_match(mid))}
    assert rows["final_board_units"]["n"] == 8 and rows["final_board_units"]["coverage"] == 0.0
    assert "final_level" not in rows                                      # EOG-only: no level truth
    assert gacc.final_accuracy(None) == []


# --------------------------------------- backfill: recorder EoG + dry run

def _raw_eog_dir(root, gid=PAIR_GID):
    """A recorder match dir (ops/runtime/tft_qa/<stamp>/eog_raw.json shape):
    the sanitised raw tft-eog-stats fixture, re-numbered to `gid`."""
    raw = json.loads(EOG_FIXTURE.read_text(encoding="utf-8"))
    raw["gameId"] = gid
    d = root / f"2026010{gid % 10}-000000"
    d.mkdir(parents=True)
    (d / "eog_raw.json").write_text(json.dumps(raw), encoding="utf-8")
    return d


def _tree_digest(root):
    if not root.exists():
        return None
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _history_only(rm616_dir):
    (hist,) = tp.parse_history(json.loads(HIST_FIXTURE.read_text(encoding="utf-8")), LOCAL_PUUID,
                               now=1_700_003_000.0)
    assert tp.persist(hist, store_dir=rm616_dir)
    return hist


def test_import_eog_raw_fills_the_missing_rm616_eog_record_once(rm616_dir, tmp_path):
    """The recorder kept the raw tft-eog-stats document of games whose RM-616
    EOG record was never written (the collector was not running yet). The
    import parses it with RM-616's own parser and persists it append-only:
    identity-free, captured_at = the raw file's mtime, never overwritten."""
    qa = tmp_path / "tft_qa"
    d = _raw_eog_dir(qa)
    _history_only(rm616_dir)
    (qa / "notes").mkdir()
    (qa / "notes" / "eog_raw.json").write_text('{"queueType": "NORMAL_TFT"}', encoding="ascii")
    first = gt.import_eog_raw([qa], store_dir=rm616_dir)
    assert first == {"files": 2, "imported": 1, "present": 0, "unusable": 1}
    rec = json.loads((rm616_dir / f"{PAIR_GID}.eog.json").read_text(encoding="utf-8"))
    assert rec["source"] == tp.SOURCE_EOG and rec["game_id"] == PAIR_GID
    assert rec["captured_at_unix"] == pytest.approx((d / "eog_raw.json").stat().st_mtime)
    blob = json.dumps(rec)
    assert "summonerName" not in blob and "puuid" not in blob.lower() and "riotId" not in blob
    before = _tree_digest(rm616_dir)
    again = gt.import_eog_raw([d / "eog_raw.json"], store_dir=rm616_dir)
    assert again == {"files": 1, "imported": 0, "present": 1, "unusable": 0}
    assert _tree_digest(rm616_dir) == before


def test_import_eog_raw_refuses_a_non_tft_document(rm616_dir, tmp_path):
    raw = json.loads(EOG_FIXTURE.read_text(encoding="utf-8"))
    raw["queueType"] = "ARAM"
    raw.pop("gameMode", None)
    p = tmp_path / "eog_raw.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    assert gt.import_eog_raw([p], store_dir=rm616_dir)["unusable"] == 1
    assert list(rm616_dir.iterdir()) == []


def test_backfill_dry_run_writes_nothing_and_predicts_the_real_run(tmp_path, rm616_dir):
    qa = tmp_path / "tft_qa"
    _raw_eog_dir(qa)
    _history_only(rm616_dir)
    _put_live(rm616_dir)
    db = tmp_path / "tft" / "tft_rounds.db"
    salt = tmp_path / "tft" / ".salt"
    rm616_before = _tree_digest(rm616_dir)
    dry = gt.backfill(db_path=db, store_dir=rm616_dir, eog_raw=[qa], salt_path=salt, dry_run=True)
    assert not (tmp_path / "tft").exists()                     # no db, no salt, no dir
    assert _tree_digest(rm616_dir) == rm616_before             # RM-616 store untouched
    assert dry["dry_run"] is True
    assert dry["eog_raw"] == {"files": 1, "imported": 1, "present": 0, "unusable": 0}
    assert dry["sync"]["games"] == 2 and dry["sync"]["added"] == 2
    real = gt.backfill(db_path=db, store_dir=rm616_dir, eog_raw=[qa], salt_path=salt)
    assert real["dry_run"] is False
    assert {k: real[k] for k in ("eog_raw", "sync", "store")} == {k: dry[k] for k in ("eog_raw", "sync", "store")}
    assert real["store"]["matches"] == 2 and real["store"]["full"] == 1
    assert db.exists() and salt.exists()
    # the paired game is complete: both LCU sources, history fields beside EOG boards
    reader = RoundStore.open(db, readonly=True)
    doc = _match_by_gid(reader, PAIR_GID)
    reader.close()
    assert doc["match"]["gt_sources"] == ["lcu_eog", "lcu_mh"] and doc["match"]["gt_status"] == "full"
    assert len(doc["accuracy"]) == 5
    # idempotent: a second real run changes nothing, and its dry run says so
    again_dry = gt.backfill(db_path=db, store_dir=rm616_dir, eog_raw=[qa], salt_path=salt, dry_run=True)
    assert again_dry["sync"]["unchanged"] == 2 and again_dry["eog_raw"]["present"] == 1
    assert again_dry["sync"]["added"] == again_dry["sync"]["updated"] == 0
    again = gt.backfill(db_path=db, store_dir=rm616_dir, eog_raw=[qa], salt_path=salt)
    assert again["sync"]["unchanged"] == 2 and again["sync"]["accuracy_rows"] == 0
    assert again["store"] == real["store"]


def _folder_digest(d):
    """{name: (size, sha256)} of every file in one folder (db, -wal, -shm, salt)."""
    import hashlib
    return {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(d.iterdir()) if p.is_file()}


def test_backfill_dry_run_leaves_the_source_db_folder_byte_identical(tmp_path, rm616_dir):
    """A dry run against an EXISTING store never touches the store's folder:
    no -wal / -shm created beside a closed db (a mode=ro open does that), and
    nothing changed while a writer holds the db open in WAL mode with
    uncheckpointed frames - which the dry run must still see."""
    import sqlite3

    _put_live(rm616_dir)
    folder = tmp_path / "tft"
    db, salt = folder / "tft_rounds.db", folder / ".salt"
    gt.backfill(db_path=db, store_dir=rm616_dir, salt_path=salt)
    # the real run checkpoints on close: the db file ALONE carries every row
    assert sorted(_folder_digest(folder)) == [".salt", "tft_rounds.db"]
    alone = tmp_path / "alone.db"
    shutil.copyfile(db, alone)
    conn = sqlite3.connect(str(alone))
    try:
        assert conn.execute("SELECT COUNT(*) FROM gt_board").fetchone()[0] == 52
    finally:
        conn.close()
    before = _folder_digest(folder)
    dry = gt.backfill(db_path=db, store_dir=rm616_dir, salt_path=salt, dry_run=True)
    assert _folder_digest(folder) == before
    assert dry["sync"]["unchanged"] == 1
    # WAL mode, writer open, rows only in the -wal
    _put_pair(rm616_dir)
    live = RoundStore.open(db)
    try:
        assert gt.sync(live, store_dir=rm616_dir, salt=salt.read_bytes())["added"] == 1
        assert live.flush()
        assert (folder / "tft_rounds.db-wal").stat().st_size > 0
        before = _folder_digest(folder)
        dry = gt.backfill(db_path=db, store_dir=rm616_dir, salt_path=salt, dry_run=True)
        assert _folder_digest(folder) == before
        assert dry["sync"]["unchanged"] == 2 and dry["sync"]["added"] == 0   # WAL rows reached the copy
    finally:
        live.close()


def test_backfill_cli_dry_run_json(tmp_path, rm616_dir, capsys):
    _put_live(rm616_dir)
    db = tmp_path / "tft" / "tft_rounds.db"
    rc = gt.main(["--store-dir", str(rm616_dir), "--db", str(db), "--salt", str(tmp_path / "tft" / ".salt"),
                  "--dry-run", "--json"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["dry_run"] is True and out["sync"]["added"] == 1
    assert out["store"]["gt_board"] == 52
    assert not (tmp_path / "tft").exists()


# ------------------------------------------------- the CV harness hand-off

def test_cv_harness_reads_an_rm616_record_as_its_lcu_eog_oracle():
    raw = json.loads(EOG_FIXTURE.read_text(encoding="utf-8"))
    rec = tp.parse_eog(raw, now=1_700_002_200.0)
    from_raw = cv.lcu_eog_ground_truth(raw)
    from_rec = cv.lcu_eog_ground_truth(rec)
    assert from_rec["placement"] == from_raw["placement"] == 1
    assert from_rec["players"]["P1"] == from_raw["players"]["P1"]

    def boards(gtdoc):
        return Counter(json.dumps(p["board"], sort_keys=True) for p in gtdoc["players"].values())

    assert len(from_rec["players"]) == 8 and boards(from_rec) == boards(from_raw)
    # a merged record (tft_placement.load) reads the same way
    merged = tp.merge(rec, None)
    assert cv.lcu_eog_ground_truth(merged) == from_rec
    live = cv.lcu_eog_ground_truth(_live_record())
    assert live["placement"] == 1 and len(live["players"]["P1"]["board"]) == 10
    assert live["players"]["P1"]["hp"] == _live_record()["local_hp"]
