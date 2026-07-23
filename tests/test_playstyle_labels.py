"""Tests for core.playstyle_labels - deterministic per-champion playstyle
fingerprint.

TDD-first. Every fixture is a synthetic tmp_path sqlite db so the suite is
clean-checkout safe (data/rewind_history.db is gitignored). The one real-db
test asserts STRUCTURE only (keys present, WR bounded), never exact values,
because the corpus changes.

WR math is asserted against the SAME laplace_rate the module uses (imported
from core.smoothed_rates), never a hand-written float, so the test cannot
drift from the primitive. Label thresholds are imported from the module for
the same reason.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core import playstyle_labels as pl
from core.smoothed_rates import laplace_rate


def _make_db(tmp_path: Path, rows) -> Path:
    """rows: iterable of (champ_id, champ_name, win, k, d, a, kp[, queue]).

    Builds a minimal matches table matching the real schema's relevant
    columns. kp may be None. queue defaults to 450 (ARAM).
    """
    db = tmp_path / "playstyle_test.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE matches ("
        "tracked_champion_id INTEGER, tracked_champion_name TEXT,"
        "tracked_win INTEGER, tracked_kills INTEGER, tracked_deaths INTEGER,"
        "tracked_assists INTEGER, tracked_kp INTEGER, queue_id INTEGER)"
    )
    for r in rows:
        cid, cname, win, k, d, a, kp = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        queue = r[7] if len(r) > 7 else 450
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
            (cid, cname, win, k, d, a, kp, queue),
        )
    conn.commit()
    conn.close()
    return db


def _game(cid, cname, win, k, d, a, kp=50, queue=450):
    return (cid, cname, win, k, d, a, kp, queue)


def _tag_set(champ):
    return {lab["tag"] for lab in champ["labels"]}


def _by_id(payload, cid):
    return next(c for c in payload["champions"] if c["champion_id"] == cid)


# --------------------------------------------------------------------------
# empty / degenerate corpus
# --------------------------------------------------------------------------

def test_absent_db_is_well_formed(tmp_path):
    out = pl.compute_playstyle_labels(db_path=tmp_path / "nope.db")
    assert out["ok"] is True
    assert out["n"] == 0
    assert out["champions"] == []
    assert out["baseline"]["deaths"] is None
    # neutral laplace baseline on an empty corpus.
    assert out["overall_wr"] == round(laplace_rate(0, 0), 4)


def test_empty_matches_table_is_well_formed(tmp_path):
    db = _make_db(tmp_path, [])
    out = pl.compute_playstyle_labels(db_path=db)
    assert out["ok"] is True
    assert out["n"] == 0
    assert out["champions"] == []


# --------------------------------------------------------------------------
# grouping + WR math
# --------------------------------------------------------------------------

def test_groups_by_champion_and_counts(tmp_path):
    rows = [_game(1, "Aatrox", 1, 5, 5, 5) for _ in range(4)]
    rows += [_game(2, "Ahri", 0, 5, 5, 5) for _ in range(3)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    assert out["n"] == 7
    a = _by_id(out, 1)
    b = _by_id(out, 2)
    assert (a["games"], a["wins"]) == (4, 4)
    assert (b["games"], b["wins"]) == (3, 0)
    # widest evidence first.
    assert out["champions"][0]["champion_id"] == 1


def test_wr_uses_laplace_primitive(tmp_path):
    rows = [_game(1, "Aatrox", 1, 5, 5, 5) for _ in range(4)]
    rows += [_game(1, "Aatrox", 0, 5, 5, 5) for _ in range(2)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    a = _by_id(out, 1)
    assert a["wr"] == round(laplace_rate(4, 6), 4)


def test_thin_champion_has_no_display_wr_or_labels(tmp_path):
    # champ 2 has fewer than min_games -> wr None, labels empty, means kept.
    rows = [_game(1, "Aatrox", 1, 3, 10, 2) for _ in range(6)]
    rows += [_game(2, "Ahri", 0, 20, 1, 20)]  # extreme but thin
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows),
                                      min_games=5)
    thin = _by_id(out, 2)
    assert thin["games"] == 1
    assert thin["wr"] is None
    assert thin["labels"] == []
    assert thin["means"]["kills"] == 20.0


# --------------------------------------------------------------------------
# self-relative directional labels
# --------------------------------------------------------------------------

def test_death_prone_and_death_averse_are_self_relative(tmp_path):
    # baseline deaths = mean(10x6, 2x6) = 6. champ1 (10) >= 6*1.2 -> prone;
    # champ2 (2) <= 6*0.8 -> averse.
    rows = [_game(1, "Aatrox", 1, 3, 10, 2) for _ in range(6)]
    rows += [_game(2, "Ahri", 0, 8, 2, 5) for _ in range(6)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    assert out["baseline"]["deaths"] == 6.0
    assert "death-prone" in _tag_set(_by_id(out, 1))
    assert "death-averse" in _tag_set(_by_id(out, 2))


def test_kill_focused_and_low_kill_are_self_relative(tmp_path):
    # baseline kills = mean(3x6, 8x6) = 5.5. champ1 (3) low, champ2 (8) high.
    rows = [_game(1, "Aatrox", 1, 3, 10, 2) for _ in range(6)]
    rows += [_game(2, "Ahri", 0, 8, 2, 5) for _ in range(6)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    assert "low-kill" in _tag_set(_by_id(out, 1))
    assert "kill-focused" in _tag_set(_by_id(out, 2))


def test_no_directional_label_inside_band(tmp_path):
    # every champ identical to baseline -> zero deviation -> no rel labels.
    rows = [_game(1, "Aatrox", 1, 5, 5, 5) for _ in range(6)]
    rows += [_game(2, "Ahri", 0, 5, 5, 5) for _ in range(6)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    for cid in (1, 2):
        tags = _tag_set(_by_id(out, cid))
        assert "death-prone" not in tags
        assert "death-averse" not in tags
        assert "kill-focused" not in tags
        assert "low-kill" not in tags


def test_rel_threshold_is_honored(tmp_path):
    # champ1 deaths 10 vs baseline 6 -> +66%. At rel=0.8 (need +80%) it must
    # NOT fire; at the default 0.2 it does.
    rows = [_game(1, "Aatrox", 1, 3, 10, 2) for _ in range(6)]
    rows += [_game(2, "Ahri", 0, 8, 2, 5) for _ in range(6)]
    db = _make_db(tmp_path, rows)
    loose = pl.compute_playstyle_labels(db_path=db, rel_threshold=0.8)
    assert "death-prone" not in _tag_set(_by_id(loose, 1))
    tight = pl.compute_playstyle_labels(db_path=db, rel_threshold=0.2)
    assert "death-prone" in _tag_set(_by_id(tight, 1))


# --------------------------------------------------------------------------
# consistency (CV) labels
# --------------------------------------------------------------------------

def test_identical_games_read_consistent(tmp_path):
    # every game the same ratio -> CV 0 -> consistent.
    rows = [_game(1, "Aatrox", 1, 5, 5, 5) for _ in range(6)]
    # a second champ so champ1 is not the whole baseline (labels still fire).
    rows += [_game(2, "Ahri", 0, 5, 5, 5) for _ in range(6)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    a = _by_id(out, 1)
    assert a["kda_cv"] == 0.0
    assert "consistent" in _tag_set(a)


def test_wildly_varying_games_read_high_variance(tmp_path):
    # ratios swing from ~0 to large -> CV above CV_HIGH.
    rows = [
        _game(1, "Aatrox", 1, 20, 1, 10),   # ratio 30
        _game(1, "Aatrox", 0, 0, 12, 0),    # ratio 0
        _game(1, "Aatrox", 1, 18, 1, 8),    # ratio 26
        _game(1, "Aatrox", 0, 0, 10, 1),    # ratio 0.1
        _game(1, "Aatrox", 1, 15, 2, 5),    # ratio 10
        _game(1, "Aatrox", 0, 0, 9, 0),     # ratio 0
    ]
    rows += [_game(2, "Ahri", 0, 5, 5, 5) for _ in range(6)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    a = _by_id(out, 1)
    assert a["kda_cv"] >= pl.CV_HIGH
    assert "high-variance" in _tag_set(a)


# --------------------------------------------------------------------------
# kp null handling + queue filter
# --------------------------------------------------------------------------

def test_null_kp_dropped_from_kp_mean_not_from_game(tmp_path):
    rows = [_game(1, "Aatrox", 1, 5, 5, 5, kp=None) for _ in range(3)]
    rows += [_game(1, "Aatrox", 0, 5, 5, 5, kp=40) for _ in range(3)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    a = _by_id(out, 1)
    assert a["games"] == 6          # all six games counted
    assert a["means"]["kp"] == 40.0  # only the kp-bearing games in the kp mean


def test_all_null_kp_yields_none_kp_mean(tmp_path):
    rows = [_game(1, "Aatrox", 1, 5, 5, 5, kp=None) for _ in range(6)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows))
    a = _by_id(out, 1)
    assert a["means"]["kp"] is None
    assert out["baseline"]["kp"] is None


def test_queue_filter(tmp_path):
    rows = [_game(1, "Aatrox", 1, 5, 5, 5, queue=450) for _ in range(4)]
    rows += [_game(2, "Ahri", 0, 5, 5, 5, queue=420) for _ in range(4)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows),
                                      queue_ids=[450])
    assert out["n"] == 4
    assert {c["champion_id"] for c in out["champions"]} == {1}


def test_empty_queue_filter_returns_empty(tmp_path):
    rows = [_game(1, "Aatrox", 1, 5, 5, 5) for _ in range(4)]
    out = pl.compute_playstyle_labels(db_path=_make_db(tmp_path, rows),
                                      queue_ids=[])
    assert out["n"] == 0
    assert out["champions"] == []


# --------------------------------------------------------------------------
# real-db smoke (structure only; skipped on a clean checkout)
# --------------------------------------------------------------------------

def test_real_db_structure_only():
    if not pl.DEFAULT_DB.exists():
        pytest.skip("no local rewind_history.db (clean checkout)")
    out = pl.compute_playstyle_labels()
    assert out["ok"] is True
    assert out["n"] >= 0
    assert 0.0 <= out["overall_wr"] <= 1.0
    for c in out["champions"]:
        assert set(("champion_id", "games", "wins", "wr", "wr_blended",
                    "means", "kda_cv", "labels")) <= set(c.keys())
        if c["wr"] is not None:
            assert 0.0 <= c["wr"] <= 1.0
        assert 0.0 <= c["wr_blended"] <= 1.0
        for lab in c["labels"]:
            assert set(("tag", "verdict", "basis")) <= set(lab.keys())
