"""scripts/repair_tft_match_rows.py - the s134 N8 backfill, run on a COPY.

Shape of the live data it repairs (survey of a scratch COPY, session 135):
data/match_history.db held 8,211 mode='TFT' rows, every one game_id 0:

  * 7,816 "Dark Star Vertical" / 8th / F / level 0 / stage 0 / 0 s
    (2026-05-10 .. 2026-09-11) - the stale-planner fabricated 8th;
  * 114 "Test Comp" and 225 comp-less rows, both B / 4th / level 8 /
    stage 4 / 1800 s (2026-07-19 .. 2026-09-11) - a test literal;
  * 54 REAL games (2026-04-08 .. 2026-04-15: varied comps, placements and
    float game lengths), 11 of them written twice (bit-identical game
    length, same comp, <= 1 s apart);
  * the game-end rows of two QA-recorded games (09:28:52 F / 8, and
    11:19:17 S / 1 with the stale comp).

s134 filed "8,209 junk rows" = every game_id-0 row before the first QA
game, which would have quarantined the 54 real games. The repair classifies
by SIGNATURE instead; this test builds that shape in tmp (real rows, a real
"Dark Star Vertical" game, test literals, a duplicate pair, a QA game-end
row, an unmatched later row) and checks quarantine (never delete), in-place
correction, store backfill, last_tft.json, the backup, the refusals and that
a second apply writes nothing.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import performance_tracker as pt
from core.match_db import MatchDB
from tft import tft_placement as tp

REPO = Path(__file__).resolve().parent.parent
EOG_DOC = json.loads((REPO / "tests" / "fixtures" / "tft_eog_stats_set18.json")
                     .read_text(encoding="utf-8"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "repair_tft_match_rows", REPO / "scripts" / "repair_tft_match_rows.py")
rep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rep)

G1, G2 = 2000000001, 2000000002
JUNK = 5 + 2 + 3          # stale-planner 8ths + "Test Comp" + comp-less literal
DUPS = 1
QUARANTINE = JUNK + DUPS

_LITERAL = {"grade": "B", "tft_placement": 4, "tft_level": 8, "tft_stage": 4,
            "game_time_s": 1800}


def _eog(gid):
    d = json.loads(json.dumps(EOG_DOC))
    d["gameId"] = gid
    return d


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "-"


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "data" / "meta").mkdir(parents=True)
    shutil.copy(REPO / "data" / "meta" / "tft_set18_cdragon.json",
                root / "data" / "meta" / "tft_set18_cdragon.json")
    monkeypatch.setattr(pt, "_match_db", None)
    t0 = datetime.now().replace(microsecond=0) - timedelta(hours=3)
    m1 = (t0, t0 + timedelta(minutes=35))
    m2 = (t0 + timedelta(minutes=60), t0 + timedelta(minutes=95))
    db = MatchDB(root / "data" / "match_history.db")
    # Real games (kept): one played twice-written, one real Dark Star game.
    db.save_match({"mode": "TFT", "champion": "Rogue 3 / Meeple 3", "grade": "S",
                   "tft_placement": 1, "tft_level": 8, "tft_stage": 7,
                   "game_time_s": 2110.85595703125, "tft_comp": "Rogue 3 / Meeple 3",
                   "timestamp": "2026-04-09 23:44:47"})
    for ts in ("2026-04-10 20:45:19", "2026-04-10 20:45:20"):
        db.save_match({"mode": "TFT", "champion": "Vanguard 4", "grade": "D",
                       "tft_placement": 3, "tft_level": 8, "tft_stage": 7,
                       "game_time_s": 1894.4007568359375, "tft_comp": "Vanguard 4",
                       "timestamp": ts})
    db.save_match({"mode": "TFT", "champion": "Dark Star Vertical", "grade": "A",
                   "tft_placement": 2, "tft_level": 8, "tft_stage": 6,
                   "game_time_s": 1900.5, "tft_comp": "Dark Star Vertical",
                   "timestamp": "2026-05-01 20:00:00"})
    # Junk.
    for i in range(5):
        db.save_match({"mode": "TFT", "champion": "Dark Star Vertical", "grade": "F",
                       "tft_placement": 8, "tft_comp": "Dark Star Vertical",
                       "timestamp": f"2026-09-11 11:19:4{i}"})
    for i in range(2):
        db.save_match(dict(_LITERAL, mode="TFT", champion="Test Comp", tft_comp="Test Comp",
                           timestamp=f"2026-08-01 10:00:0{i}"))
    for i in range(3):
        db.save_match(dict(_LITERAL, mode="TFT", champion="", tft_comp="",
                           timestamp=f"2026-08-01 10:00:1{i}"))
    db.save_match({"mode": "SR", "champion": "Ahri", "grade": "B",
                   "timestamp": "2026-09-10 10:00:00"})
    end_row_ts = (m2[1] + timedelta(seconds=8)).strftime("%Y-%m-%d %H:%M:%S")
    db.save_match({"mode": "TFT", "champion": "Dark Star Vertical", "grade": "F",
                   "tft_placement": 8, "tft_comp": "Dark Star Vertical",
                   "timestamp": end_row_ts})
    # A later game-id-less row that no QA game explains: kept, reported.
    late_ts = (m2[1] + timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    db.save_match({"mode": "TFT", "champion": "Dark Star Vertical", "grade": "F",
                   "tft_placement": 8, "tft_comp": "Dark Star Vertical",
                   "timestamp": late_ts})
    db.close()
    # The pre-N8 game-end file: no game id, minute stamp of match 2's end.
    ratings = root / "data" / "ratings"
    ratings.mkdir(parents=True)
    (ratings / "last_tft.json").write_text(json.dumps(
        {"rating": "F", "tft_placement": 8, "tft_comp": "Dark Star Vertical",
         "timestamp": (m2[1] + timedelta(seconds=8)).strftime("%Y-%m-%d %H:%M")}),
        encoding="utf-8")
    # Match 2 = "match 3" of the live day: its EOG record is already stored.
    store = root / "data" / "tft_matches"
    assert tp.persist(tp.parse_eog(_eog(G2), now=(m2[1] + timedelta(seconds=60)).timestamp()),
                      store_dir=store)
    lines = []
    for n, (gid, (s, e)) in enumerate(((G1, m1), (G2, m2)), start=1):
        d = tmp_path / "qa" / f"m{n}"
        d.mkdir(parents=True)
        (d / "eog_raw.json").write_text(json.dumps(_eog(gid)), encoding="utf-8")
        lines.append(json.dumps({"match": f"m{n}", "dir": str(d), "placement": 1,
                                 "game_id": gid,
                                 "start_iso": s.astimezone().isoformat(),
                                 "end_iso": e.astimezone().isoformat()}))
    qa = tmp_path / "qa" / "matches.jsonl"
    qa.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr("tft.placement_aggregator.update_heatmap", lambda *a, **k: 0)
    return root, qa


def _rows(root, table="matches"):
    c = sqlite3.connect(str(root / "data" / "match_history.db"))
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY id")]
    finally:
        c.close()


def _files(root):
    d = root / "data"
    return {p: _sha(d / p) for p in ("match_history.db", "match_history.db-wal",
                                     "ratings/last_tft.json", "placement_heatmap.json")}


def _quiet(*_a, **_k):
    return None


def test_dry_run_plans_by_signature_and_changes_no_byte(world):
    root, qa = world
    before = _files(root)
    r = rep.run(root, qa, out=_quiet)
    assert r["junk_rows"] == JUNK
    assert r["junk_by_class"] == {rep.CLASS_STALE_8TH: 5, rep.CLASS_TEST_LITERAL: 5}
    assert r["dup_rows"] == DUPS
    assert r["quarantine_rows"] == QUARANTINE
    assert r["store_add"] == [G1]
    assert list(r["stamp_rows"].values()) == [G2]
    assert r["rating_plan"] == {G1: "insert", G2: "update"}
    assert r["last_tft_plan"] == G2
    assert len(r["unmatched_rows"]) == 1
    assert r["kept_tft_rows"] == 4          # 3 real games + the unmatched later row
    assert _files(root) == before           # not one byte, WAL included
    assert not tp.has_record(G1, store_dir=root / "data" / "tft_matches")


def test_real_games_are_never_junk(world):
    root, qa = world
    r = rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, skip_live_check=True,
                out=_quiet)
    kept = {(x["champion"], x["timestamp"]) for x in _rows(root) if x["mode"] == "TFT"
            and x["game_id"] == 0}
    assert ("Rogue 3 / Meeple 3", "2026-04-09 23:44:47") in kept
    assert ("Vanguard 4", "2026-04-10 20:45:19") in kept          # the dup's first id
    assert ("Vanguard 4", "2026-04-10 20:45:20") not in kept
    assert ("Dark Star Vertical", "2026-05-01 20:00:00") in kept  # a real DSV game
    assert len(kept) == 4
    q = _rows(root, rep.QUARANTINE_TABLE)
    assert len(q) == QUARANTINE == r["quarantined"]
    reasons = {x["quarantine_reason"].split(":")[0] for x in q}
    assert reasons == {"s134-N8 junk", "s134-N8 duplicate"}


def test_apply_refuses_a_wrong_quarantine_count(world):
    root, qa = world
    before = _files(root)
    with pytest.raises(SystemExit, match="refused"):
        rep.run(root, qa, apply=True, expect_quarantine=JUNK, skip_live_check=True,
                out=_quiet)
    with pytest.raises(SystemExit, match="refused"):
        rep.run(root, qa, apply=True, skip_live_check=True, out=_quiet)
    assert _files(root) == before


def test_apply_quarantines_corrects_backfills_and_reads_back(world):
    root, qa = world
    end_row = [r for r in _rows(root) if r["mode"] == "TFT"][-2]
    last_before = (root / "data" / "ratings" / "last_tft.json").read_bytes()
    r = rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, skip_live_check=True,
                out=_quiet)
    # Backup BEFORE any write: the db as it was, last_tft.json byte-identical.
    bdir = Path(r["backup"])
    assert bdir.is_dir()
    bak = sqlite3.connect(str(bdir / "match_history.db"))
    try:
        assert bak.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT'").fetchone()[0] == 16
    finally:
        bak.close()
    assert (bdir / "last_tft.json").read_bytes() == last_before
    manifest = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["last_tft.json"] == hashlib.sha256(last_before).hexdigest()
    rows = _rows(root)
    assert [x["champion"] for x in rows if x["mode"] == "SR"] == ["Ahri"]
    tft = {x["game_id"]: x for x in rows if x["mode"] == "TFT" and x["game_id"]}
    assert set(tft) == {G1, G2}
    assert tft[G2]["id"] == end_row["id"]                  # corrected in place
    assert tft[G2]["timestamp"] == end_row["timestamp"]
    assert all(x["tft_placement"] == 1 and x["grade"] == "S" for x in tft.values())
    assert "Dark Star" not in tft[G2]["tft_comp"]
    assert tp.has_record(G1, tp.SOURCE_EOG, store_dir=root / "data" / "tft_matches")
    last = json.loads((root / "data" / "ratings" / "last_tft.json").read_text(encoding="utf-8"))
    assert (last["tft_game_id"], last["rating"], last["tft_placement"]) == (G2, "S", 1)
    rb = r["read_back"]
    assert rb["tft_rows"] == 6 and rb["tft_rows_game_id_0"] == 4


def test_second_apply_writes_nothing(world):
    root, qa = world
    rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, skip_live_check=True,
            out=_quiet)
    first = _files(root)
    first_rows = _rows(root)
    r = rep.run(root, qa, apply=True, expect_quarantine=0, skip_live_check=True, out=_quiet)
    assert r["junk_rows"] == 0 and r["dup_rows"] == 0
    assert r["stamp_rows"] == {} and r["store_add"] == []
    assert r["rating_plan"] == {G1: "ok", G2: "ok"} and r["last_tft_plan"] is None
    assert "backup" not in r and r["nothing_to_do"] is True
    assert _files(root) == first
    assert _rows(root) == first_rows
    assert len(_rows(root, rep.QUARANTINE_TABLE)) == QUARANTINE


def test_restart_before_backfill_supersedes_the_old_game_end_rows(world):
    """The merger may restart RC on the fixed code first: its collector then
    rates G2 into a row with G2's id, beside the old game-id-less game-end
    row. And a game whose end was written twice has two such rows. One game
    keeps ONE row: the newest window row is stamped when the game has no row
    of its own, every other window row is quarantined as superseded."""
    root, qa = world
    store = root / "data" / "tft_matches"
    end_row = [x for x in _rows(root) if x["mode"] == "TFT"][-2]["id"]
    assert pt.rate_tft_game(root, G2, store_dir=store)[0] == "S"
    m1_end = [json.loads(x) for x in qa.read_text(encoding="utf-8").splitlines()][0]["end_iso"]
    end1 = rep._iso_local(m1_end)
    db = MatchDB(root / "data" / "match_history.db")
    for s in (5, 6):
        db.save_match({"mode": "TFT", "champion": "Dark Star Vertical", "grade": "F",
                       "tft_placement": 8, "timestamp": rep._ts(end1 + timedelta(seconds=s))})
    db.close()
    by_ts = {x["timestamp"]: x["id"] for x in _rows(root) if x["mode"] == "TFT"
             and x["game_id"] == 0}
    older, newer = (by_ts[rep._ts(end1 + timedelta(seconds=s))] for s in (5, 6))
    r = rep.run(root, qa, out=_quiet)
    assert r["stamp_rows"] == {newer: G1}
    assert r["superseded_rows"] == {older: G1, end_row: G2}
    assert r["rating_plan"] == {G1: "update", G2: "ok"}
    n = QUARANTINE + 2
    assert r["quarantine_rows"] == n
    rep.run(root, qa, apply=True, expect_quarantine=n, skip_live_check=True, out=_quiet)
    tft = [x for x in _rows(root) if x["mode"] == "TFT" and x["game_id"]]
    assert sorted(x["game_id"] for x in tft) == [G1, G2]
    assert next(x for x in tft if x["game_id"] == G1)["id"] == newer
    q = {x["id"]: x["quarantine_reason"] for x in _rows(root, rep.QUARANTINE_TABLE)}
    assert q[older].startswith("s134-N8 superseded")
    r2 = rep.run(root, qa, apply=True, expect_quarantine=0, skip_live_check=True, out=_quiet)
    assert r2["nothing_to_do"] is True


def _tree(root: Path) -> dict:
    """Every file under root: relative name -> (size, sha256)."""
    return {str(p.relative_to(root)): (p.stat().st_size, _sha(p))
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_dry_run_with_a_live_wal_writer_changes_no_byte(world):
    """The live state: RC holds the database open in WAL mode with frames not
    yet checkpointed (-wal and -shm on disk). A `mode=ro` open rewrote bytes
    of the -shm (verifier, s135). The dry run must leave every file of the
    root - names, sizes and bytes, sidecars included - as it found them, and
    still see the uncheckpointed rows."""
    root, qa = world
    writer = sqlite3.connect(str(root / "data" / "match_history.db"))
    try:
        assert writer.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("INSERT INTO matches (mode, champion, grade, timestamp) "
                       "VALUES ('SR', 'Lux', 'A', '2026-09-12 10:00:00')")
        writer.commit()
        wal = root / "data" / "match_history.db-wal"
        assert wal.exists() and wal.stat().st_size > 0
        assert (root / "data" / "match_history.db-shm").exists()
        before = _tree(root)
        r = rep.run(root, qa, out=_quiet)
        assert _tree(root) == before
        assert r["before"]["by_mode"]["SR"] == 2          # the WAL-only row was read
        assert r["quarantine_rows"] == QUARANTINE
    finally:
        writer.close()


def test_apply_replans_inside_the_write_transaction(world, monkeypatch):
    """The fixed collector inserts G2's own row after the plan was read (its
    first history read after a restart). The apply re-plans inside BEGIN
    IMMEDIATE, sees the plan changed, and refuses with nothing quarantined or
    stamped - never two rows for one game. A re-run plans the new shape."""
    root, qa = world
    store = root / "data" / "tft_matches"

    def collector_insert():
        assert pt.rate_tft_game(root, G2, store_dir=store)[0] == "S"

    monkeypatch.setattr(rep, "_BEFORE_WRITE_LOCK", collector_insert)
    with pytest.raises(SystemExit, match="changed since the plan"):
        rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, skip_live_check=True,
                out=_quiet)
    rows = _rows(root)
    assert len([x for x in rows if x["game_id"] == G2]) == 1
    assert len([x for x in rows if x["mode"] == "TFT"]) == 17   # 16 + the collector's row
    c = sqlite3.connect(str(root / "data" / "match_history.db"))
    try:
        tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        c.close()
    assert (rep.QUARANTINE_TABLE,) not in tables
    assert not (root / "ops" / "runtime" / "backups").exists()   # refused before the backup
    assert "changed since the plan" in (root / "logs" / rep.LOG_NAME).read_text(encoding="utf-8")
    monkeypatch.setattr(rep, "_BEFORE_WRITE_LOCK", None)
    r = rep.run(root, qa, out=_quiet)
    assert r["quarantine_rows"] == QUARANTINE + 1            # + the superseded end row
    rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE + 1, skip_live_check=True,
            out=_quiet)
    tft = [x for x in _rows(root) if x["mode"] == "TFT" and x["game_id"]]
    assert sorted(x["game_id"] for x in tft) == [G1, G2]


def test_apply_refuses_while_rc_is_running(world, monkeypatch):
    import os
    root, qa = world
    (root / "ops" / "runtime").mkdir(parents=True)
    (root / "ops" / "runtime" / "health.json").write_text(
        json.dumps({"app": "riot-commander", "pid": os.getpid(), "alive": True}),
        encoding="utf-8")
    monkeypatch.setattr(rep, "live_game_reason", lambda _root: "")
    before = _files(root)
    with pytest.raises(SystemExit, match="stop RC") as exc:
        rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, out=_quiet)
    assert "supervisor" in str(exc.value).lower()
    assert _files(root) == before
    r = rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, allow_rc_running=True,
                out=_quiet)
    assert r["quarantined"] == QUARANTINE


def test_a_rating_that_does_not_land_fails_the_apply_and_is_logged(world, monkeypatch):
    """The re-rate runs after the commit; a write that does not land (the
    db write swallowed, the rating returned a grade anyway) must not pass
    as repaired: the read-back fails the run and the reason is in logs/."""
    root, qa = world
    monkeypatch.setattr(pt, "rate_tft_game", lambda *a, **k: ("S", []))
    with pytest.raises(SystemExit, match="read-back"):
        rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, skip_live_check=True,
                out=_quiet)
    log = root / "logs" / "repair_tft_match_rows.log"
    assert log.exists() and "read-back" in log.read_text(encoding="utf-8")


def test_store_input_for_another_game_is_refused(world, tmp_path):
    root, qa = world
    bad = tmp_path / "qa" / "m1" / "eog_raw.json"
    bad.write_text(json.dumps(_eog(G1 + 99)), encoding="utf-8")
    before = _files(root)
    with pytest.raises(SystemExit, match="store inputs unusable"):
        rep.run(root, qa, apply=True, expect_quarantine=QUARANTINE, skip_live_check=True,
                out=_quiet)
    assert _files(root) == before


def test_cli_dry_run_flag_and_exclusive_modes(world, capsys):
    root, qa = world
    before = _files(root)
    assert rep.main(["--root", str(root), "--qa-matches", str(qa), "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert _files(root) == before
    with pytest.raises(SystemExit) as exc:
        rep.main(["--root", str(root), "--qa-matches", str(qa), "--dry-run", "--apply"])
    assert exc.value.code == 2
