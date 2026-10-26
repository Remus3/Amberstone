"""s134 true-audit of tft/rounds/ground_truth.py (the TFT-08 bridge).

Each test names one weakness found by the audit; every one was RED against
the module as it stood before this cycle.

  F1 final_boards took the FIRST is_local player row, so a match with two
     local rows handed another player's board to the engine comp catalogue
     (RM-938).
  F2 the bridge took the FIRST is_local RM-616 entry as the local player and
     wrote every flagged entry as a local row, so a record with two flagged
     entries put two local rows (and one guessed placement) in the store.
  F3 the store's own local key was the FIRST truthy is_local row, so a match
     already holding two local rows got the RM-616 local board attributed to
     one of them, and a third local row could be added.
  F4 ingest_game said "never raises on bad data" but raised on a record whose
     players lack the RM-616 keys tp.merge reads.
  F5 sync said "never raises" but an int past the float range (game length)
     raised OverflowError, and a deeply nested record raised RecursionError.
  F6 a value the store refuses (NaN / inf stamp, int past 64 bits, lone
     surrogate text, negative set number) passed the bridge's own filters, so
     the store dropped the WHOLE write it rode in: the match row, or every
     board and player row of that source - not just the one bad value.
  F7 a unit whose items field is not a list raised TypeError and skipped the
     whole game instead of keeping the unit with no items.
  F8 import_eog_raw said "never raises" but a deeply nested raw file raised
     RecursionError out of backfill.
  F9 a 19-digit file name past the 64-bit range was taken as a game id, and
     every write for it was refused by the store (counted as dropped).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from tft.rounds import ground_truth as gt
from tft.rounds import store as st
from tft.rounds.store import RoundStore

FIX = Path(__file__).resolve().parent / "fixtures"
LIVE_FIXTURE = FIX / "tft_ground_truth" / "rm616_eog_set18_live.json"
LIVE_GID = 1000000002
SALT = b"tft08-synthetic-salt-0123456789ab"
DEEP = "[" * 100000 + "]" * 100000


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


def _rec() -> dict:
    return json.loads(LIVE_FIXTURE.read_text(encoding="ascii"))


def _put(rm616_dir, rec, gid=LIVE_GID):
    (rm616_dir / f"{gid}.eog.json").write_text(json.dumps(rec), encoding="ascii")


def _sync(store, rm616_dir):
    out = gt.sync(store, store_dir=rm616_dir, salt=SALT)
    assert store.flush()
    return out


def _doc(store, gid=LIVE_GID):
    rows = [m for m in store.list_matches() if m["game_id"] == gid]
    assert len(rows) == 1, rows
    return store.get_match(rows[0]["match_id"])


def _two_local_match(store):
    a = st.player_key("live-local-a", SALT)
    b = st.player_key("live-local-b", SALT)
    mid = store.begin_match({"match_id": "20260101-000000-two", "game_id": LIVE_GID,
                             "set_id": 18, "queue_id": 1090, "started_at": 1_767_000_000.0})
    store.upsert_player(mid, a, slot=1, is_local=True)
    store.upsert_player(mid, b, slot=2, is_local=True)
    assert store.flush()
    return mid, a, b


# ------------------------------------------------------------- F1 final_boards

def test_f1_final_boards_skips_a_match_with_two_local_rows(store):
    mid, a, b = _two_local_match(store)
    store.attach_ground_truth(mid, "lcu_eog",
                              [{"player_key": a, "champion_api": "DA_18_Alune", "star": 2,
                                "items": [], "cost": 5},
                               {"player_key": b, "champion_api": "DA_18_Other", "star": 1,
                                "items": [], "cost": 1}], [])
    assert store.flush()
    assert gt.final_boards(store) == {}


def test_f1_final_boards_still_reads_the_one_local_row(store):
    mid, a, _ = _two_local_match(store)
    other = st.player_key("live-other", SALT)
    store.upsert_player(mid, other, slot=3)
    # demote b: exactly one local row left
    store.upsert_player(mid, st.player_key("live-local-b", SALT), is_local=False)
    store.attach_ground_truth(mid, "lcu_eog",
                              [{"player_key": a, "champion_api": "DA_18_Alune", "star": 2,
                                "items": [], "cost": 5}], [])
    assert store.flush()
    assert [r["champion_api"] for r in gt.final_boards(store)[mid]] == ["DA_18_Alune"]


# ------------------------------------------------------------- F2 / F3 bridge local

def test_f2_two_flagged_rm616_entries_write_no_local_row_and_no_placement(store, rm616_dir):
    rec = _rec()
    rec["players"][1]["is_local"] = True             # placement 2 flagged too
    _put(rm616_dir, rec)
    assert _sync(store, rm616_dir)["added"] == 1
    doc = _doc(store)
    assert [p for p in doc["players"] if p["is_local"]] == []
    assert doc["match"]["placement"] is None
    assert len(doc["gt_board"]) == 52                # the boards still land
    assert gt.final_boards(store) == {}


def test_f3_store_with_two_local_rows_gets_no_board_on_either_and_no_third_local(store, rm616_dir):
    mid, a, b = _two_local_match(store)
    _put(rm616_dir, _rec())
    assert _sync(store, rm616_dir)["updated"] == 1
    doc = store.get_match(mid)
    assert {p["player_key"] for p in doc["players"] if p["is_local"]} == {a, b}
    assert [r for r in doc["gt_board"] if r["player_key"] in (a, b)] == []
    assert len(doc["gt_board"]) == 52


def test_f3_two_local_rows_with_standings_are_not_joined_by_standing(store, rm616_dir):
    mid, a, b = _two_local_match(store)
    store.upsert_player(mid, a, final_standing=st.Env(1, 0.7, "ocr"))
    store.upsert_player(mid, b, final_standing=st.Env(2, 0.7, "ocr"))
    assert store.flush()
    _put(rm616_dir, _rec())
    _sync(store, rm616_dir)
    doc = store.get_match(mid)
    assert {p["player_key"] for p in doc["players"] if p["is_local"]} == {a, b}
    assert [r for r in doc["gt_board"] if r["player_key"] in (a, b)] == []


def test_f3_store_with_one_local_row_still_joins_it(store, rm616_dir):
    a = st.player_key("live-local-a", SALT)
    mid = store.begin_match({"match_id": "20260101-000000-one", "game_id": LIVE_GID,
                             "set_id": 18, "queue_id": 1090, "started_at": 1_767_000_000.0})
    store.upsert_player(mid, a, slot=1, is_local=True)
    assert store.flush()
    _put(rm616_dir, _rec())
    _sync(store, rm616_dir)
    doc = store.get_match(mid)
    assert [p["player_key"] for p in doc["players"] if p["is_local"]] == [a]
    assert len([r for r in doc["gt_board"] if r["player_key"] == a]) == 10


# ------------------------------------------------------------- F4 / F5 never raises

def test_f4_ingest_game_never_raises_on_a_record_tp_merge_cannot_read(store, rm616_dir):
    _put(rm616_dir, {"schema": 1, "source": "eog", "game_id": LIVE_GID,
                     "players": [{"placement": 1, "is_local": True}]})
    assert gt.ingest_game(store, LIVE_GID, store_dir=rm616_dir, salt=SALT) == "skipped"


def test_f5_sync_never_raises_on_a_game_length_past_the_float_range(store, rm616_dir):
    rec = _rec()
    rec["game_length_s"] = 10 ** 400
    _put(rm616_dir, rec)
    counts = _sync(store, rm616_dir)
    assert counts["added"] == 1 and counts["dropped"] == 0
    m = _doc(store)["match"]
    assert m["started_at"] == pytest.approx(rec["captured_at_unix"])


def test_f5_sync_never_raises_on_a_deeply_nested_record(store, rm616_dir):
    shutil.copyfile(LIVE_FIXTURE, rm616_dir / f"{LIVE_GID}.eog.json")
    (rm616_dir / "1234567.eog.json").write_text(DEEP, encoding="ascii")
    counts = _sync(store, rm616_dir)
    assert counts["added"] == 1 and counts["skipped"] == 1 and counts["dropped"] == 0


def test_f5_a_deeply_nested_second_source_never_costs_the_good_one(store, rm616_dir):
    shutil.copyfile(LIVE_FIXTURE, rm616_dir / f"{LIVE_GID}.eog.json")
    (rm616_dir / f"{LIVE_GID}.history.json").write_text(DEEP, encoding="ascii")
    assert set(gt.source_records(LIVE_GID, rm616_dir)) == {"eog"}
    assert _sync(store, rm616_dir)["added"] == 1
    assert len(_doc(store)["gt_board"]) == 52


# ------------------------------------------------------------- F6 one bad value, one row

def _assert_whole(store, counts, boards=52, players=8):
    assert counts["dropped"] == 0 and store.stats()["invalid"] == 0
    doc = _doc(store)
    assert len(doc["gt_board"]) == boards and len(doc["gt_player"]) == players
    return doc


def test_f6_nan_end_stamp_keeps_the_match(store, rm616_dir):
    rec = _rec()
    rec["captured_at_unix"] = float("nan")
    _put(rm616_dir, rec)
    doc = _assert_whole(store, _sync(store, rm616_dir))
    # no stamp from the record: the store's own defaults (now), never NaN
    assert all(math.isfinite(doc["match"][k]) for k in ("started_at", "ended_at"))


def test_f6_infinite_elimination_time_drops_that_value_only(store, rm616_dir):
    rec = _rec()
    rec["players"][3]["time_eliminated_s"] = float("inf")
    _put(rm616_dir, rec)
    doc = _assert_whole(store, _sync(store, rm616_dir))
    assert all(p["eliminated_at"] is None for p in doc["gt_player"])


@pytest.mark.parametrize("field", ["last_round", "gold_left"])
def test_f6_int_past_64_bits_drops_that_value_only(store, rm616_dir, field):
    rec = _rec()
    rec["players"][3][field] = 2 ** 63
    _put(rm616_dir, rec)
    _assert_whole(store, _sync(store, rm616_dir))


def test_f6_queue_id_past_64_bits_keeps_the_match(store, rm616_dir):
    rec = _rec()
    rec["queue_id"] = 2 ** 63
    _put(rm616_dir, rec)
    doc = _assert_whole(store, _sync(store, rm616_dir))
    assert doc["match"]["queue_id"] is None


def test_f6_negative_set_number_falls_back_to_the_set_core_name(store, rm616_dir):
    rec = _rec()
    rec["set_number"] = -5
    _put(rm616_dir, rec)
    doc = _assert_whole(store, _sync(store, rm616_dir))
    assert doc["match"]["set_id"] == 18


def test_f6_lone_surrogate_champion_drops_that_unit_only(store, rm616_dir):
    rec = _rec()
    rec["players"][0]["board"][0]["character_id"] = "\ud800"
    _put(rm616_dir, rec)
    _assert_whole(store, _sync(store, rm616_dir), boards=51)


def test_f6_lone_surrogate_item_drops_that_item_only(store, rm616_dir):
    rec = _rec()
    rec["players"][0]["board"][0]["items"] = [{"name_id": "\ud800"}, {"name_id": "DA_Good"}]
    _put(rm616_dir, rec)
    doc = _assert_whole(store, _sync(store, rm616_dir))
    assert ["DA_Good"] in [r["items"] for r in doc["gt_board"] if r["champion_api"] == "DA_18_Alune"]


# ------------------------------------------------------------- F7 items not a list

@pytest.mark.parametrize("items", [5, 2.5, True])
def test_f7_non_list_items_keep_the_unit_with_no_items(store, rm616_dir, items):
    rec = _rec()
    rec["players"][0]["board"][0]["items"] = items
    _put(rm616_dir, rec)
    doc = _assert_whole(store, _sync(store, rm616_dir))
    assert [] in [r["items"] for r in doc["gt_board"] if r["champion_api"] == "DA_18_Alune"]


# ------------------------------------------------------------- F8 raw EoG import

def test_f8_import_eog_raw_never_raises_on_a_deeply_nested_file(tmp_path, rm616_dir):
    raw = tmp_path / "raw" / "20260101-000000"
    raw.mkdir(parents=True)
    (raw / gt.EOG_RAW_NAME).write_text(DEEP, encoding="ascii")
    counts = gt.import_eog_raw([tmp_path / "raw"], store_dir=rm616_dir)
    assert counts == {"files": 1, "imported": 0, "present": 0, "unusable": 1}


# ------------------------------------------------------------- F9 game id range

def test_f9_game_id_past_64_bits_is_skipped_not_dropped(store, rm616_dir):
    big = 2 ** 63 + 7                                # 19 digits, matches the file pattern
    rec = _rec()
    rec["game_id"] = big
    _put(rm616_dir, rec, gid=big)
    assert gt.game_ids(rm616_dir) == []
    counts = _sync(store, rm616_dir)
    assert counts["dropped"] == 0 and counts["added"] == 0
    assert store.list_matches() == []
