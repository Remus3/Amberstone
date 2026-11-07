"""Tests for tools/gated_lx05_tape_check.py - the lane-9 read-only reader of one
game's live item tape (LX-05, RM-607). The tape rows are produced by the REAL
core.live_item_tape diff engine and written by the REAL
core.live_item_tape_store.persist_tape into a temp database built from the
shared rewind schema, so the shapes cannot drift from the writer. Item ids are
real DDragon ids from the tracked catalog; players and game ids are synthetic
(RM-906). No test touches data/.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from core import live_item_tape as lit
from core import live_item_tape_store as store
from scripts.rewind_scraper import SCHEMA
from tools import gated_lx05_tape_check as g

GID = "9000000005"
MID = "NA1_" + GID
LONG_SWORD, CAULFIELD, POTION, WARD = 1036, 3133, 2003, 3340
MANAMUNE, MURAMANA, TEAR = 3004, 3042, 3070
VOID_IMMOLATION = 223069          # Mayhem / Arena augment reward (a grant)


def _p(n, items, team=None):
    return {"riotIdGameName": f"TapeP{n}", "riotIdTagLine": "TST",
            "team": team or ("ORDER" if n < 2 else "CHAOS"),
            "items": [{"itemID": i, "count": c, "slot": s,
                       "consumable": i == POTION} for i, c, s in items]}


# (game_time, [player 1 items, player 2 items]) - (id, count, slot)
_TICKS = [
    (5.0, [[(WARD, 1, 6)], [(WARD, 1, 6)]]),
    (30.0, [[(LONG_SWORD, 1, 0), (LONG_SWORD, 1, 1), (POTION, 2, 2), (WARD, 1, 6)],
            [(TEAR, 1, 0), (WARD, 1, 6)]]),
    (60.0, [[(CAULFIELD, 1, 0), (POTION, 1, 2), (WARD, 1, 6)],
            [(TEAR, 1, 0), (CAULFIELD, 1, 1), (LONG_SWORD, 1, 2), (WARD, 1, 6)]]),
    (90.0, [[(CAULFIELD, 1, 0), (VOID_IMMOLATION, 1, 1), (WARD, 1, 6)],
            [(MANAMUNE, 1, 0), (WARD, 1, 6)]]),
    (120.0, [[(CAULFIELD, 1, 0), (VOID_IMMOLATION, 1, 1), (WARD, 1, 6)],
             [(MURAMANA, 1, 0), (WARD, 1, 6)]]),
]


def _final_players():
    return [_p(n + 1, items) for n, items in enumerate(_TICKS[-1][1])]


@pytest.fixture
def cat():
    c = lit.load_default_catalog()
    for iid in (LONG_SWORD, CAULFIELD, POTION, WARD, MANAMUNE, MURAMANA, TEAR,
                VOID_IMMOLATION):
        assert c.has(iid), f"catalog lost item {iid}"
    assert VOID_IMMOLATION in lit.build_exclusions(c)
    return c


@pytest.fixture
def db(tmp_path, cat):
    path = tmp_path / "rewind.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    tape = lit.LiveItemTape(cat)
    for gt, invs in _TICKS:
        tape.ingest([_p(n + 1, items) for n, items in enumerate(invs)], gt)
    res = store.persist_tape(conn, MID, tape.drain())
    assert res["status"] == "written"
    conn.close()
    return path


def _eog_db(tmp_path, players):
    path = tmp_path / "postgame.db"
    conn = sqlite3.connect(str(path))
    items = ", ".join(f"item{i}_id INTEGER" for i in range(7))
    conn.execute("CREATE TABLE aram_player_stats (match_id TEXT, game_name TEXT, "
                 f"tag_line TEXT, team_id INTEGER, {items})")
    for name, team_id, raw_ids in players:
        ids = (list(raw_ids) + [0] * 7)[:7]
        conn.execute("INSERT INTO aram_player_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (GID, name, "TST", team_id, *ids))
    conn.commit()
    conn.close()
    return path


_GOOD_EOG = [("TapeP1", 100, [CAULFIELD, VOID_IMMOLATION, 0, 0, 0, 0, WARD]),
             ("TapeP2", 200, [MURAMANA, 0, 0, 0, 0, 0, WARD])]


def _check(path, cat, final=None, flagged=frozenset()):
    conn = g._ro(path)
    try:
        return g.check(conn, MID, cat, final, flagged)
    finally:
        conn.close()


def test_real_tape_folds_to_eog_final_with_every_diff_explained(tmp_path, db, cat):
    econn = g._ro(_eog_db(tmp_path, _GOOD_EOG))
    final = g.final_from_eog(econn, GID, "aram")
    econn.close()
    s = _check(db, cat, final)
    assert s["source_column"] is True
    assert s["non_tape_item_rows"] == 0
    assert s["rows_by_type"]["ITEM_COMBINED"] == 2      # Caulfield, Manamune
    assert "ITEM_GRANTED" not in s["rows_by_type"]       # never persisted
    assert s["combine_recipe_bad"] == []
    assert s["grant_ids_persisted"] == []
    f = s["fold"]
    assert f["players_compared"] == 2 and f["unexplained_diffs"] == 0
    assert f["fold_match"] is True
    why = {p["label"]: (p["tape_extra"], p["final_extra"]) for p in f["players"]}
    # the grant and the trinket are in the final only; the potions were bought
    # (persisted) then drunk (CONSUMABLE_USED, not persisted); Muramana is a
    # transform of the persisted Manamune combine
    assert why["p1"][0][str(POTION)] == {"count": 2, "explained": "consumable"}
    assert why["p2"][1][str(MURAMANA)]["explained"] == "transform"
    kinds = {v["explained"] for t, fe in why.values() for v in {**t, **fe}.values()}
    assert kinds == {"consumable", "grant", "trinket", "transform"}


def test_an_unexplained_final_item_fails_the_fold(tmp_path, db, cat):
    bad = [("TapeP1", 100, [CAULFIELD, VOID_IMMOLATION, 1038, 0, 0, 0, WARD]),
           _GOOD_EOG[1]]
    econn = g._ro(_eog_db(tmp_path, bad))
    s = _check(db, cat, g.final_from_eog(econn, GID, "aram"))
    econn.close()
    assert s["fold"]["fold_match"] is False
    assert s["fold"]["unexplained_diffs"] == 1
    p1 = s["fold"]["players"][0]
    assert p1["final_extra"]["1038"] == {"count": 1, "explained": None}


def test_a_missing_player_fails_the_fold_even_with_no_item_diff(tmp_path, db, cat):
    econn = g._ro(_eog_db(tmp_path, [_GOOD_EOG[0]]))
    s = _check(db, cat, g.final_from_eog(econn, GID, "aram"))
    econn.close()
    assert s["fold"]["players_tape_only"] == 1
    assert s["fold"]["fold_match"] is False


def test_grant_typed_as_purchase_and_bad_combine_are_reported(tmp_path, cat):
    path = tmp_path / "rewind.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    store.ensure_source_column(conn)
    raw = json.dumps({"riot_id": "TapeP1#TST", "team": "ORDER"})
    bad_comb = json.dumps({"riot_id": "TapeP1#TST", "team": "ORDER",
                           "components": [POTION]})
    conn.executemany(
        "INSERT INTO timeline_events (match_id, timestamp_ms, event_type, item_id, "
        "team_id, raw_json, source) VALUES (?,?,?,?,?,?,?)",
        [(MID, 1000, "ITEM_PURCHASED", VOID_IMMOLATION, 100, raw, "live_tape"),
         (MID, 2000, "ITEM_COMBINED", CAULFIELD, 100, bad_comb, "live_tape")])
    conn.commit()
    conn.close()
    s = _check(path, cat)
    assert s["grant_ids_persisted"] == [VOID_IMMOLATION]
    assert s["combine_recipe_bad"] == [CAULFIELD]
    assert s["fold"] is None
    assert s["participant_id_null"] == 2


def test_db_without_the_source_column_reads_zero_tape_rows(tmp_path, cat):
    path = tmp_path / "rewind.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO timeline_events (match_id, timestamp_ms, event_type, "
                 "item_id) VALUES (?,?,?,?)", (MID, 1000, "ITEM_PURCHASED", 1036))
    conn.commit()
    conn.close()
    s = _check(path, cat)
    assert s["source_column"] is False
    assert s["tape_rows"] == 0 and s["non_tape_item_rows"] == 1


def test_session_final_source_reads_the_last_allplayers(tmp_path, db, cat):
    sess = tmp_path / f"{GID}.jsonl"
    hdr = {"kind": "header", "schema": 1, "config_key": "unknown", "patch": "25.21",
           "ENGINE_VERSION": "9.9", "mode_key": "aram"}
    frames = [{"kind": "frame", "seq": 0, "captured_at": 1.0, "game_time": 120.0,
               "snapshot": {"allPlayers": _final_players(),
                            "gameData": {"gameTime": 120.0}}},
              {"kind": "frame", "seq": 1, "captured_at": 2.0, "game_time": 121.0,
               "snapshot": {"gameData": {"gameTime": 121.0}}}]
    sess.write_text("".join(json.dumps(x) + "\n" for x in [hdr, *frames]),
                    encoding="utf-8")
    final, flagged = g.final_from_session(sess)
    assert final[("TapeP2#TST", 200)] == Counter({MURAMANA: 1, WARD: 1})
    assert WARD in flagged[("TapeP2#TST", 200)]
    assert _check(db, cat, final, flagged)["fold"]["fold_match"] is True


def test_flagged_ids_are_per_player_never_pooled(cat):
    # verifier c23 pass 2 defect 3: an id flagged for one player explains
    # nothing for another
    a, b = ("TapeP1#TST", 100), ("TapeP2#TST", 200)
    odd = 999001                       # not in the catalog
    f = g.compare({a: Counter(), b: Counter()},
                  {a: Counter({odd: 1}), b: Counter({odd: 1})}, cat,
                  flagged={a: {odd}})
    assert f["players"][0]["final_extra"][str(odd)]["explained"] == "consumable"
    assert f["players"][1]["final_extra"][str(odd)]["explained"] is None
    assert f["fold_match"] is False


def test_sold_transform_target_consumes_its_source(cat):
    # verifier c23 pass 2 defect 1: Manamune bought, transformed (tape-only),
    # then Muramana sold - the fold must end empty, not keep a Manamune
    raw = json.dumps({"riot_id": "TapeP1#TST", "team": "ORDER"})
    rows = [(1000, "ITEM_PURCHASED", None, MANAMUNE, 100, raw),
            (2000, "ITEM_SOLD", None, MURAMANA, 100, raw)]
    stats: dict = {}
    assert g.fold_rows(rows, cat, stats) == {("TapeP1#TST", 100): Counter()}
    assert stats["implicit_transforms"] == 1
    # without the catalog the old behaviour stays visible (no hidden rule)
    assert g.fold_rows(rows) == {("TapeP1#TST", 100): Counter({MANAMUNE: 1})}
    # an unrelated sale never consumes a held item
    rows2 = [(1000, "ITEM_PURCHASED", None, MANAMUNE, 100, raw),
             (2000, "ITEM_SOLD", None, LONG_SWORD, 100, raw)]
    assert g.fold_rows(rows2, cat) == {("TapeP1#TST", 100): Counter({MANAMUNE: 1})}


def test_transform_pairs_one_copy_for_one_copy(cat):
    # verifier c23 defect 1: two Manamunes against one Muramana must leave one
    # Manamune unexplained, never explain the whole count away
    k = ("TapeP2#TST", 200)
    f = g.compare({k: Counter({MANAMUNE: 2})}, {k: Counter({MURAMANA: 1})}, cat)
    assert f["unexplained_diffs"] == 1 and f["fold_match"] is False
    te = f["players"][0]["tape_extra"]
    assert te[str(MANAMUNE)] == {"count": 1, "explained": "transform"}
    assert te[f"{MANAMUNE}+"] == {"count": 1, "explained": None}
    one = g.compare({k: Counter({MANAMUNE: 1})}, {k: Counter({MURAMANA: 1})}, cat)
    assert one["fold_match"] is True
    # an unrelated pair is never a transform
    assert g.is_transform(LONG_SWORD, MURAMANA, cat) is False


def test_fold_clamps_after_every_row_like_the_writer():
    # verifier c23 defect 2: a sale the tape never saw bought cannot cancel a
    # later purchase (core.live_item_tape.fold clamps per event)
    raw = json.dumps({"riot_id": "TapeP1#TST", "team": "ORDER"})
    rows = [(1000, "ITEM_SOLD", None, LONG_SWORD, 100, raw),
            (2000, "ITEM_PURCHASED", None, LONG_SWORD, 100, raw)]
    assert g.fold_rows(rows) == {("TapeP1#TST", 100): Counter({LONG_SWORD: 1})}
    evs = [lit.TapeEvent(1.0, "TapeP1#TST", "ORDER", lit.EV_SOLD, LONG_SWORD),
           lit.TapeEvent(2.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, LONG_SWORD)]
    assert lit.fold(evs)[("TapeP1#TST", "ORDER")] == Counter({LONG_SWORD: 1})


def test_zero_players_never_match(cat):
    assert g.compare({}, {}, cat)["fold_match"] is False


def test_eog_source_grades_only_the_players_it_names(tmp_path, db, capsys):
    # verifier c23 defect 3: stored KIWI EOG blocks hold ONE player row
    eog = _eog_db(tmp_path, [_GOOD_EOG[0]])
    assert g.main(["--game-id", GID, "--platform", "NA1", "--db", str(db),
                   "--eog-db", str(eog), "--json"]) == 0
    f = json.loads(capsys.readouterr().out)["fold"]
    assert f["all_players"] is False
    assert f["players_compared"] == 1 and f["players_tape_only"] == 1
    assert f["fold_match"] is True
    (tmp_path / "bad").mkdir()
    bad = _eog_db(tmp_path / "bad", [("TapeP1", 100, [1038])])
    assert g.main(["--game-id", GID, "--platform", "NA1", "--db", str(db),
                   "--eog-db", str(bad), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["fold"]["fold_match"] is False


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_main_is_read_only_and_redacts_ids(tmp_path, db, capsys):
    eog = _eog_db(tmp_path, _GOOD_EOG)
    nosrc = tmp_path / "nosrc.db"
    c = sqlite3.connect(str(nosrc))
    c.executescript(SCHEMA)
    c.close()
    before = {p: _sha(p) for p in (db, eog, nosrc)}
    assert g.main(["--game-id", GID, "--platform", "NA1", "--db", str(db),
                   "--eog-db", str(eog), "--json"]) == 0
    out = capsys.readouterr().out
    s = json.loads(out)
    assert s["fold"]["fold_match"] is True
    assert "TapeP" not in out and GID not in out
    assert g.main(["--game-id", GID, "--platform", "NA1", "--db", str(nosrc),
                   "--no-final"]) == 0
    assert "source_column=False" in capsys.readouterr().out
    assert {p: _sha(p) for p in (db, eog, nosrc)} == before
    c = sqlite3.connect(str(nosrc))
    assert "source" not in [r[1] for r in c.execute("PRAGMA table_info(timeline_events)")]
    c.close()


def test_main_show_id_prints_ids(tmp_path, db, capsys):
    eog = _eog_db(tmp_path, _GOOD_EOG)
    assert g.main(["--game-id", GID, "--platform", "NA1", "--db", str(db),
                   "--eog-db", str(eog), "--show-id"]) == 0
    out = capsys.readouterr().out
    assert "TapeP1#TST" in out and f"match_id={MID}" in out


def test_ro_uri_survives_url_metacharacters_in_the_path(tmp_path, db, cat):
    odd = tmp_path / "a #b %c"
    odd.mkdir()
    copy = odd / "rewind.db"
    copy.write_bytes(db.read_bytes())
    assert _check(copy, cat)["tape_rows"] > 0


def test_main_exit_2_on_missing_db_or_bad_id(tmp_path, capsys):
    assert g.main(["--game-id", GID, "--platform", "NA1",
                   "--db", str(tmp_path / "nope.db"), "--no-final"]) == 2
    assert g.main(["--game-id", "not-digits", "--platform", "NA1"]) == 2
    err = capsys.readouterr().err
    assert "nope" not in err
