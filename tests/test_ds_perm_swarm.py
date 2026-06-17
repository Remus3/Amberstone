"""Hermetic tests for the DS permutation-swarm WIN-anchor harness (DSP1).

These tests build a tiny in-memory sqlite + a tiny cross-eval JSON fixture so they
NEVER touch the real 1.8GB gitignored data/rewind_history.db (clean-checkout safe;
feedback_clean_checkout_probe). The harness scores DS top-N (cross-eval comp_grid)
against per-item WIN-rate from rewind_history.db via difference-of-differences, NOT
fragile cross-item equality.
"""
import json
import sqlite3

import pytest

from ops.audit.ds_perm_swarm import (
    BucketScore,
    ChampModeWin,
    ChampScore,
    CrossEval,
    PermConfig,
    build_report,
    compute_champ_win,
    compute_win_rates,
    load_cross_eval,
    resolve_mode,
    score_champ,
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _make_db():
    """In-memory rewind-shaped sqlite. Two champs in ARAM:

    Goodpick: DS rank-1 item 1001 wins 4/4 (100%); filler 9999 loses 0/4 -> baseline 50%.
    Badpick:  DS rank-1 item 3003 loses 0/4 (0%);  filler 9999 wins 4/4   -> baseline 50%.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, queue_id INTEGER, map_id INTEGER, game_mode TEXT)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, champion_name TEXT, win INTEGER, "
        "item0 INTEGER, item1 INTEGER, item2 INTEGER, item3 INTEGER, item4 INTEGER, "
        "item5 INTEGER, item6 INTEGER)"
    )
    rows = []
    mid = 0

    def add(champ, win, item0):
        nonlocal mid
        mid += 1
        m = f"M{mid}"
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?)", (m, 450, 12, "ARAM")
        )
        rows.append((m, champ, win, item0, 0, 0, 0, 0, 0, 0))

    for w in (1, 1, 1, 1):
        add("Goodpick", w, 1001)
    for w in (0, 0, 0, 0):
        add("Goodpick", w, 9999)
    for w in (0, 0, 0, 0):
        add("Badpick", w, 3003)
    for w in (1, 1, 1, 1):
        add("Badpick", w, 9999)
    conn.executemany(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return conn


def _ce(name, top_ids):
    """Minimal cross-eval dict: one bucket bal_squishy, ARAM anchor."""
    grid = [
        {"rank": i + 1, "id": iid, "name": f"Item{iid}", "score": 1.0 - i * 0.1,
         "d_ehp": 0.0, "d_dps": 0.0, "gold": 3000}
        for i, iid in enumerate(top_ids)
    ]
    return {
        "champion": name,
        "db_name": name,
        "archetype": {"primary": "bruiser", "secondary": "tank", "source": "default"},
        "scorer": "hybrid",
        "anchor_mode": "ARAM",
        "comp_grid": {"bal_squishy": grid},
        "empirical": {
            "ARAM": {"all": {"n": 8, "wr": 50.0, "items": []}, "self": {"n": 0, "wr": None, "items": []}}
        },
        "level": 13,
    }


@pytest.fixture
def db():
    c = _make_db()
    yield c
    c.close()


@pytest.fixture
def ce_dir(tmp_path):
    (tmp_path / "Goodpick.json").write_text(
        json.dumps(_ce("Goodpick", ["1001", "7777"])), encoding="utf-8"
    )
    (tmp_path / "Badpick.json").write_text(
        json.dumps(_ce("Badpick", ["3003", "7777"])), encoding="utf-8"
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# resolve_mode
# --------------------------------------------------------------------------- #
def test_resolve_mode_maps():
    assert resolve_mode(12, "ARAM") == "ARAM"
    assert resolve_mode(11, "CLASSIC") == "SR"
    assert resolve_mode(30, "CHERRY") == "ARENA"
    assert resolve_mode(999, "WHATEVER") is None


# --------------------------------------------------------------------------- #
# win_anchor
# --------------------------------------------------------------------------- #
def test_compute_champ_win_baseline_and_item_wr(db):
    cmw = compute_champ_win(db, "Goodpick", "ARAM")
    assert isinstance(cmw, ChampModeWin)
    assert cmw.n == 8
    assert cmw.wins == 4
    assert cmw.baseline_wr == 50.0
    assert cmw.items["1001"].n == 4
    assert cmw.items["1001"].wins == 4
    assert cmw.items["1001"].wr == 100.0
    assert cmw.items["9999"].wr == 0.0
    # zero-id slots are never counted as an item
    assert "0" not in cmw.items


def test_compute_champ_win_mode_filter_isolates(db):
    # No SR rows exist -> empty / zero-game result, never a crash.
    cmw = compute_champ_win(db, "Goodpick", "SR")
    assert cmw.n == 0
    assert cmw.baseline_wr is None
    assert cmw.items == {}


def test_compute_win_rates_bulk_keys(db):
    allrates = compute_win_rates(db)
    assert ("Goodpick", "ARAM") in allrates
    assert ("Badpick", "ARAM") in allrates
    assert allrates[("Badpick", "ARAM")].items["3003"].wr == 0.0


# --------------------------------------------------------------------------- #
# perm_score - difference-of-differences (NOT fragile equality)
# --------------------------------------------------------------------------- #
def test_score_champ_lift_direction(db):
    good = score_champ(load_cross_eval_dict(_ce("Goodpick", ["1001", "7777"])),
                       compute_champ_win(db, "Goodpick", "ARAM"), PermConfig())
    bad = score_champ(load_cross_eval_dict(_ce("Badpick", ["3003", "7777"])),
                      compute_champ_win(db, "Badpick", "ARAM"), PermConfig())
    assert isinstance(good, ChampScore)
    b = good.buckets["bal_squishy"]
    assert isinstance(b, BucketScore)
    # 7777 has no win data -> overlap is just the data-backed item
    assert b.overlap_n == 1
    # DS-good lift positive, DS-bad lift negative, and good strictly beats bad
    assert good.mean_lift is not None and bad.mean_lift is not None
    assert good.mean_lift > 0 > bad.mean_lift
    assert good.mean_lift > bad.mean_lift


def test_score_champ_no_overlap_is_graceful(db):
    # DS recommends only items with zero rewind data -> no overlap, no crash, lift None.
    cs = score_champ(load_cross_eval_dict(_ce("Goodpick", ["7777", "8888"])),
                     compute_champ_win(db, "Goodpick", "ARAM"), PermConfig())
    b = cs.buckets["bal_squishy"]
    assert b.overlap_n == 0
    assert b.lift_vs_baseline is None
    assert cs.mean_lift is None


def test_min_item_n_gate_excludes_thin_samples(db):
    # With min_item_n=5 the n=4 item is excluded -> no overlap.
    cs = score_champ(load_cross_eval_dict(_ce("Goodpick", ["1001"])),
                     compute_champ_win(db, "Goodpick", "ARAM"),
                     PermConfig(min_item_n=5))
    assert cs.buckets["bal_squishy"].overlap_n == 0


# --------------------------------------------------------------------------- #
# build_report
# --------------------------------------------------------------------------- #
def test_build_report_aggregates(db, ce_dir):
    cross = {p.stem: load_cross_eval(p) for p in sorted(ce_dir.glob("*.json"))}
    win = compute_win_rates(db)
    rep = build_report(cross, win, PermConfig())
    assert rep["config"]["top_k"] == PermConfig().top_k
    agg = rep["aggregate"]
    assert agg["n_champs_scored"] == 2
    # exactly one champ (Goodpick) has positive lift
    assert agg["n_positive_lift"] == 1
    assert isinstance(rep["champs"], list) and len(rep["champs"]) == 2
    # report is json-serializable
    json.dumps(rep)


def test_build_report_anchor_match_only_excludes_cross_mode():
    """An ARAM-anchored champ with BOTH ARAM and SR win data is scored only in ARAM by
    default - its comp_grid is ARAM-built, so the SR row is apples-to-oranges. 171/172
    of the live roster anchor ARAM, so this is what drops the spurious SR divergent tail.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, queue_id INTEGER, map_id INTEGER, game_mode TEXT)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, champion_name TEXT, win INTEGER, "
        "item0 INTEGER, item1 INTEGER, item2 INTEGER, item3 INTEGER, item4 INTEGER, "
        "item5 INTEGER, item6 INTEGER)"
    )
    rows = []
    mid = 0

    def add(win, item0, mapid):
        nonlocal mid
        mid += 1
        m = f"M{mid}"
        conn.execute("INSERT INTO matches VALUES (?,?,?,?)", (m, 0, mapid, "X"))
        rows.append((m, "C", win, item0, 0, 0, 0, 0, 0, 0))

    for w in (1, 1, 1, 1):  # ARAM: item 1001 wins
        add(w, 1001, 12)
    for w in (0, 0, 0, 0):  # ARAM filler -> baseline 50%
        add(w, 9999, 12)
    for w in (0, 0, 0, 0, 0):  # SR: same item LOSES (would be a -lift row if scored)
        add(w, 1001, 11)
    conn.executemany("INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    ce = load_cross_eval_dict(_ce("C", ["1001", "7777"]))  # anchor_mode ARAM
    win = compute_win_rates(conn)
    rep = build_report({"C": ce}, win, PermConfig(min_item_n=1))
    assert rep["config"]["anchor_match_only"] is True
    assert rep["aggregate"]["n_champ_mode_considered"] == 1
    assert {r["mode"] for r in rep["champs"]} == {"ARAM"}
    # opt out -> the invalid cross-mode SR row reappears
    rep2 = build_report({"C": ce}, win, PermConfig(min_item_n=1), anchor_match_only=False)
    assert rep2["aggregate"]["n_champ_mode_considered"] == 2
    conn.close()


def test_load_cross_eval_parses_buckets_and_empirical(ce_dir):
    ce = load_cross_eval(ce_dir / "Goodpick.json")
    assert isinstance(ce, CrossEval)
    assert ce.champion == "Goodpick"
    assert ce.anchor_mode == "ARAM"
    assert ce.comp_grid["bal_squishy"][0].id == "1001"
    assert ce.comp_grid["bal_squishy"][0].rank == 1
    assert ce.empirical["ARAM"].n == 8


# helper: build a CrossEval straight from a dict (used by the scorer tests)
def load_cross_eval_dict(d):
    from ops.audit.ds_perm_swarm.cross_eval_loader import cross_eval_from_dict
    return cross_eval_from_dict(d)
