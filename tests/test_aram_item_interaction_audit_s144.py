"""s144 lane 8 (true-audit) cycle 96 - core/aram_item_interaction.py hardening.

One group per audited weakness (F1-F13), each written RED against the
pre-fix module. Synthetic data only: hand-written match ids, an in-memory or
tmp sqlite DB, tmp catalogs (never the live corpus).

F1  sqlite3.Error was swallowed - in the match select (an empty ok=True
    corpus) and inside the per-match loop (a partial ok=True corpus). The
    only producer, tools/aram_item_interaction_precompute.py, writes that
    result over the TRACKED snapshot (RM-1262, aram half).
F2  a match that failed half-way kept the purchases counted before the
    failure.
F3  the per-match catch was ``except Exception``: a defect was logged once
    per match and the sweep still answered ok=True.
F4  one malformed event row dropped the rest of its match; a NULL purchase
    time was counted as a purchase at 0:00; a fractional item id was
    truncated onto a real item.
F5  a NULL win was counted as a loss and an out-of-range win (2) as two
    wins; a participant id listed twice was accepted.
F6  an empty champion catalog bucketed every purchase as "mixed/fl_none" and
    an empty item catalog gave zero cells, both as ok=True - a garbage or
    empty snapshot instead of a refusal.
F7  an enemy team with no resolvable champion got the fabricated shape
    "mixed/fl_none".
F8  champion_names_by_id cached a FAILED load forever (the RM-439 class) and
    raised on a wrong-shape catalog; a bool / fractional key or an empty
    name was accepted.
F9  champion_names_by_id published its "loaded" flag before the load, so a
    concurrent caller got an empty catalog.
F10 a non-finite gold value produced inf / NaN in the payload.
F11 min_n / champion_id / pressure_window_s were never validated.
F12 elapsed_ms came from the wall clock.
F13 the from-db helper built its read-only URI with an f-string ('#' in the
    path opened another file) and treated a directory as a present DB;
    comp_shape raised on a non-numeric id instead of skipping it.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import types

import pytest

from core import aram_item_interaction as aii
from core.failed_load_gate import FailedLoadGate
from tests.test_aram_item_interaction import (
    AD_TEAM,
    BLUE_TEAM,
    IE,
    RABADON,
    _add_match,
    _corpus,
    _schema,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    return conn


def _one_match(purchases, *, red=AD_TEAM, mid="TEST_AII_960"):
    conn = _conn()
    _add_match(conn, mid, blue_champs=BLUE_TEAM, red_champs=red,
               blue_win=True, purchases=purchases)
    conn.commit()
    return conn


def _cells(out, item=None):
    return [c for c in out["cells"] if item is None or c["item_id"] == item]


class _Proxy:
    """Connection proxy that raises on the Nth query matching ``needle``."""

    def __init__(self, conn, needle, fail_on, exc):
        self._conn = conn
        self._needle = needle
        self._fail_on = fail_on
        self._exc = exc
        self.calls = 0

    def execute(self, sql, *args):
        if self._needle in sql:
            self.calls += 1
            if self.calls == self._fail_on:
                raise self._exc
        return self._conn.execute(sql, *args)


@pytest.fixture
def fresh_names(monkeypatch):
    """Isolate the champion-name memo (pre- and post-fix attribute names)."""
    monkeypatch.setattr(aii, "_champ_names_loaded", False, raising=False)
    monkeypatch.setattr(aii, "_champ_names_by_id", {}, raising=False)
    monkeypatch.setattr(aii, "_CHAMP_NAMES", None, raising=False)
    monkeypatch.setattr(aii, "_CHAMP_NAMES_GATE", FailedLoadGate(),
                        raising=False)


def _plant_catalog(ds_dir, patch="9.99.1", data=None):
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "current.txt").write_text(patch, encoding="utf-8")
    pdir = ds_dir / patch
    pdir.mkdir(exist_ok=True)
    if data is None:
        data = {"data": {
            "Annie": {"key": "1", "name": "Annie"},
            "Ashe": {"key": "22", "name": "Ashe"},
        }}
    (pdir / "champions.json").write_text(json.dumps(data), encoding="utf-8")


# -- F1: sqlite3.Error propagates -------------------------------------------

def test_f1_locked_db_mid_sweep_raises_instead_of_partial_ok():
    conn = _corpus(3)
    proxy = _Proxy(conn, "FROM timeline_events", 2,
                   sqlite3.OperationalError("database is locked"))
    with pytest.raises(sqlite3.OperationalError):
        aii.compute_aram_item_interaction(proxy, min_n=1)


def test_f1_locked_match_select_raises_instead_of_empty_ok():
    conn = _corpus(3)
    proxy = _Proxy(conn, "FROM matches", 1,
                   sqlite3.OperationalError("database is locked"))
    with pytest.raises(sqlite3.OperationalError):
        aii.compute_aram_item_interaction(proxy, min_n=1)


# -- F2: a match skipped half-way contributes nothing -----------------------

def test_f2_match_failing_half_way_is_rolled_back_whole(monkeypatch):
    conn = _one_match([(1, IE, 600_000), (2, RABADON, 650_000)])
    calls = {"n": 0}

    def fake_swing(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("bad frame value")
        return 100.0

    monkeypatch.setattr(aii, "_gold_swing", fake_swing)
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert calls["n"] == 2
    assert out["ok"] is True
    assert out["cells"] == []
    assert out["matches"] == 0


# -- F3: the catch is narrowed to data errors -------------------------------

def test_f3_a_defect_propagates_instead_of_being_logged_per_match(
        monkeypatch):
    conn = _one_match([(1, IE, 600_000)])

    def broken(*a, **k):
        raise RuntimeError("defect")

    monkeypatch.setattr(aii, "_gold_swing", broken)
    with pytest.raises(RuntimeError):
        aii.compute_aram_item_interaction(conn, min_n=1)


# -- F4: per-row event validation -------------------------------------------

def test_f4_malformed_item_row_skips_that_row_only():
    conn = _one_match([(1, "junk", 300_000), (1, IE, 600_000)])
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    cells = _cells(out, IE)
    assert len(cells) == 1 and cells[0]["n"] == 1
    assert out["matches"] == 1


def test_f4_null_purchase_time_is_not_a_purchase_at_zero():
    conn = _one_match([(1, IE, None)])
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert out["cells"] == []
    assert out["matches"] == 0


def test_f4_fractional_item_id_is_not_truncated_onto_a_real_item():
    conn = _one_match([(1, IE + 0.5, 600_000)])
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert out["cells"] == []


def test_f4_integral_float_item_id_is_that_item():
    conn = _one_match([(1, float(IE), 600_000)])
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert [c["n"] for c in _cells(out, IE)] == [1]


# -- F5: win and roster validation ------------------------------------------

@pytest.mark.parametrize("bad_win", [None, 2, -1, "x"])
def test_f5_unknown_or_out_of_range_win_is_not_counted(bad_win):
    conn = _one_match([(1, IE, 600_000)])
    conn.execute("UPDATE participants SET win=? WHERE participant_id=1",
                 (bad_win,))
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert out["cells"] == []


def test_f5_a_real_loss_still_counts():
    conn = _one_match([(1, IE, 600_000)])
    conn.execute("UPDATE participants SET win=0 WHERE team_id=100")
    conn.execute("UPDATE participants SET win=1 WHERE team_id=200")
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    cells = _cells(out, IE)
    assert len(cells) == 1 and cells[0]["winrate"] == 0.0


def test_f5_participant_listed_twice_skips_the_match():
    conn = _one_match([(1, IE, 600_000)])
    conn.execute("INSERT INTO participants VALUES (?,?,?,?,?)",
                 ("TEST_AII_960", 1, 200, 22, 0))
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert out["cells"] == []
    assert out["matches"] == 0


# -- F6: an empty catalog is a refusal, not an ok=True payload ---------------

def test_f6_empty_champion_catalog_is_not_ok(monkeypatch):
    conn = _corpus(3)
    monkeypatch.setattr(aii, "champion_names_by_id", dict)
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert out["ok"] is False
    assert "champion catalog" in out["error"]
    assert "cells" not in out


def test_f6_empty_item_catalog_is_not_ok(tmp_path):
    conn = _corpus(3)
    out = aii.compute_aram_item_interaction(
        conn, min_n=1, items_json=tmp_path / "absent_items.json")
    assert out["ok"] is False
    assert "item catalog" in out["error"]
    assert "cells" not in out


# -- F7: no fabricated enemy shape ------------------------------------------

def test_f7_enemy_team_with_no_known_champion_gives_no_cell():
    conn = _one_match([(1, IE, 600_000), (6, IE, 600_000)])
    conn.execute("UPDATE participants SET champion_id=NULL WHERE team_id=200")
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    # Only red's purchase (enemy = the fully-known blue team) is counted.
    cells = _cells(out, IE)
    assert len(cells) == 1 and cells[0]["n"] == 1
    assert out["matches"] == 1


# -- F8: champion_names_by_id fail-soft, failure not cached ------------------

def test_f8_failed_name_load_is_not_cached(tmp_path, monkeypatch,
                                           fresh_names):
    import core.failed_load_gate as flg

    now = {"t": 1000.0}
    monkeypatch.setattr(flg.time, "monotonic", lambda: now["t"])
    ds = tmp_path / "ds"
    monkeypatch.setattr(aii, "_DS_DIR", ds)
    assert aii.champion_names_by_id() == {}
    _plant_catalog(ds)
    now["t"] += 60.0
    assert aii.champion_names_by_id() == {1: "Annie", 22: "Ashe"}


def test_f8_success_is_cached(tmp_path, monkeypatch, fresh_names):
    ds = tmp_path / "ds"
    _plant_catalog(ds)
    monkeypatch.setattr(aii, "_DS_DIR", ds)
    first = aii.champion_names_by_id()
    (ds / "9.99.1" / "champions.json").unlink()
    assert aii.champion_names_by_id() == first == {1: "Annie", 22: "Ashe"}


@pytest.mark.parametrize("raw", [[1, 2], "text", 5, {"data": [1]},
                                 {"data": "x"}])
def test_f8_wrong_shape_catalog_is_fail_soft(tmp_path, monkeypatch,
                                             fresh_names, raw):
    ds = tmp_path / "ds"
    _plant_catalog(ds, data=raw)
    monkeypatch.setattr(aii, "_DS_DIR", ds)
    assert aii.champion_names_by_id() == {}


def test_f8_bad_entries_are_skipped(tmp_path, monkeypatch, fresh_names):
    ds = tmp_path / "ds"
    _plant_catalog(ds, data={"data": {
        "A": {"key": True, "name": "BoolKey"},
        "B": {"key": 3.5, "name": "Fractional"},
        "C": {"key": "4", "name": ""},
        "D": {"key": "5", "name": None},
        "E": {"key": 22.0, "name": "Ashe"},
        "F": {"key": " 7 ", "name": "Leblanc"},
        "G": "not-a-dict",
    }})
    monkeypatch.setattr(aii, "_DS_DIR", ds)
    # No entry carries id 1 or 3: a bool key read as 1 or 3.5 truncated to
    # 3 would show up here.
    assert aii.champion_names_by_id() == {22: "Ashe", 7: "Leblanc"}


# -- F9: no concurrent caller sees a half-loaded catalog ---------------------

def test_f9_concurrent_caller_never_sees_an_empty_catalog(
        tmp_path, monkeypatch, fresh_names):
    ds = tmp_path / "ds"
    _plant_catalog(ds)
    monkeypatch.setattr(aii, "_DS_DIR", ds)
    seen: list = []
    real_loads = json.loads

    def other_caller():
        seen.append(dict(aii.champion_names_by_id()))

    state = {"started": None}

    def slow_loads(text, *a, **k):
        if state["started"] is None:
            t = threading.Thread(target=other_caller, daemon=True)
            state["started"] = t
            t.start()
            t.join(0.3)
        return real_loads(text, *a, **k)

    monkeypatch.setattr(aii, "json", types.SimpleNamespace(loads=slow_loads))
    mine = aii.champion_names_by_id()
    state["started"].join(5.0)
    assert mine == {1: "Annie", 22: "Ashe"}
    assert seen == [{1: "Annie", 22: "Ashe"}]


# -- F10: non-finite gold never reaches the payload --------------------------

def test_f10_infinite_gold_gives_finite_strict_json():
    conn = _one_match([(1, IE, 600_000)])
    conn.execute(
        "UPDATE timeline_frames SET total_gold=? "
        "WHERE participant_id=6 AND timestamp_ms>=?",
        (float("inf"), 660_000),
    )
    conn.commit()
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    json.dumps(out, allow_nan=False)
    for cell in out["cells"]:
        for v in cell.values():
            if isinstance(v, float):
                assert math.isfinite(v)


def test_f10_non_finite_model_probability_is_not_counted(monkeypatch):
    conn = _one_match([(1, IE, 600_000)])
    monkeypatch.setattr(aii, "predict_prob", lambda *a, **k: float("nan"))
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    json.dumps(out, allow_nan=False)
    assert out["cells"] == []


# -- F11: argument validation ------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"min_n": -1}, {"min_n": True}, {"min_n": "5"}, {"min_n": None},
    {"min_n": 1.5},
    {"champion_id": True}, {"champion_id": 0}, {"champion_id": "86"},
    {"champion_id": -3},
    {"pressure_window_s": 0}, {"pressure_window_s": -60},
    {"pressure_window_s": True}, {"pressure_window_s": 1.5},
])
def test_f11_bad_arguments_raise_value_error(kwargs):
    conn = _corpus(1)
    with pytest.raises(ValueError):
        aii.compute_aram_item_interaction(conn, **kwargs)


def test_f11_min_n_zero_and_int_champion_id_are_accepted():
    conn = _corpus(2)
    out = aii.compute_aram_item_interaction(conn, min_n=0,
                                            champion_id=BLUE_TEAM[0])
    assert out["ok"] is True and out["cells"]


# -- F12: elapsed_ms is monotonic -------------------------------------------

def test_f12_wall_clock_step_back_never_gives_negative_elapsed(monkeypatch):
    conn = _corpus(1)
    clock = iter([1_000_000.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr(aii.time, "time", lambda: next(clock, 10.0))
    out = aii.compute_aram_item_interaction(conn, min_n=1)
    assert out["elapsed_ms"] >= 0


# -- F13: from-db path handling and comp_shape -------------------------------

@pytest.mark.parametrize("dirname", ["a#b", "a%41b"])
def test_f13_from_db_opens_the_named_file(tmp_path, dirname):
    d = tmp_path / dirname
    d.mkdir()
    db = d / "rh.db"
    seed = sqlite3.connect(str(db))
    _schema(seed)
    for i in range(2):
        _add_match(seed, f"TEST_AII_97{i}", blue_champs=BLUE_TEAM,
                   red_champs=AD_TEAM, blue_win=True,
                   purchases=[(1, IE, 600_000)])
    seed.commit()
    seed.close()
    out = aii.compute_aram_item_interaction_from_db(db, min_n=1)
    assert out["ok"] is True
    assert out["matches"] == 2


def test_f13_directory_db_path_is_missing(tmp_path):
    out = aii.compute_aram_item_interaction_from_db(tmp_path, min_n=1)
    assert out == {"ok": False, "error": "rewind_history.db missing"}


def test_f13_comp_shape_skips_unparseable_ids():
    good = aii.comp_shape(AD_TEAM)
    assert aii.comp_shape(list(AD_TEAM) + ["x", None, 2.5]) == good


def test_f13_comp_shape_never_reads_a_bool_as_champion_one():
    # Three AP mages read "mixed"; a fourth AP (True read as id 1, Annie)
    # would tip the bucket to "ap_heavy".
    three_ap = [103, 99, 134]  # Ahri, Lux, Syndra
    names = aii.champion_names_by_id()
    assert 1 in names, "catalog must carry id 1 for this test to bite"
    base = aii.comp_shape(three_ap)
    assert base.startswith("mixed/")
    assert aii.comp_shape(three_ap + [1]).startswith("ap_heavy/")
    assert aii.comp_shape(three_ap + [True]) == base
