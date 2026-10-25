"""S134-Q (research filing RM-888): `performance_tracker._get_db` serves the
database of the root it is ASKED for, never the first caller's.

`_get_db(sd)` bound the module global `_match_db` once and ignored every later
`sd`, so after one call with root A, `save_tft_rating` / `save_rating` with
root B wrote B's row into A's `data/match_history.db`. In a test process the
first caller can be a test that passes the real repo root, and every later
tmp-root test then writes into the live history (the live TFT history was
measured 99 percent synthetic: 114 `Test Comp` rows, 7816 placement-8 rows).

Acceptance (a): the cache is keyed by the resolved database path, so a second
root gets its own database and the first root's database never sees its row.
Acceptance (b): `tests/conftest.py` redirects the database, not only the
ratings dir, when a test hands over the real repo root, so the live path is
never opened by a test.

The consumer artifact is diffed here: the rows that land in each root's
`match_history.db`, read back with sqlite3, not the cache's locals.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import performance_tracker as pt

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COACH = {"stage": 4, "game_time_s": 1800, "alive_others": 2}


def _live(trait: str) -> dict:
    return {"level": 8, "stage_round": "4-2", "last_round_result": "3rd",
            "board_units": ["Jinx 2-star", "Vi"], "traits_active": [f"{trait} 3"],
            "augments": []}


def _tft_comps(root: Path) -> list:
    db = root / "data" / "match_history.db"
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        return [r[0] for r in con.execute(
            "SELECT tft_comp FROM matches WHERE mode = 'TFT' ORDER BY id")]
    finally:
        con.close()


@pytest.fixture
def fresh_cache(monkeypatch):
    monkeypatch.delenv("RC_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(pt, "_match_db", None)
    monkeypatch.setattr("tft.placement_aggregator.update_heatmap", lambda: None)
    yield
    db = pt._match_db
    if db is not None:
        db.close()


def test_second_root_writes_its_own_database(tmp_path, fresh_cache):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    grade_a, _ = pt.save_tft_rating(str(root_a), _live("Alpha"), dict(_COACH))
    grade_b, _ = pt.save_tft_rating(str(root_b), _live("Beta"), dict(_COACH))
    assert grade_a and grade_b, "fixture produced no rating - nothing under test"
    assert _tft_comps(root_a) == ["Alpha 3"]
    assert _tft_comps(root_b) == ["Beta 3"]


def test_cache_is_keyed_by_the_resolved_path(tmp_path, fresh_cache):
    root_a = tmp_path / "a"
    (root_a / "x").mkdir(parents=True)
    root_b = tmp_path / "b"
    root_b.mkdir()
    db_a = pt._get_db(str(root_a))
    assert db_a is not None
    # Same database spelled differently: still the cached instance.
    assert pt._get_db(str(root_a / "x" / "..")) is db_a
    db_b = pt._get_db(str(root_b))
    assert db_b is not None and db_b is not db_a
    assert Path(db_b._path).resolve() == (root_b / "data" / "match_history.db").resolve()
    # A caller that swaps the global directly (the save/restore idiom in
    # tests/test_performance_tracker_lane8_cycle23.py) must not be served
    # root A's instance for root B.
    pt._match_db = db_a
    db_b2 = pt._get_db(str(root_b))
    assert db_b2 is not db_a
    assert Path(db_b2._path).resolve() == (root_b / "data" / "match_history.db").resolve()


def test_conftest_never_opens_the_live_database_for_the_real_root(monkeypatch, fresh_cache):
    live = (_REPO_ROOT / "data" / "match_history.db").resolve()
    opened = []

    class _Recorder:
        def __init__(self, path):
            opened.append(Path(path).resolve())
            self._path = Path(path)

        def close(self):
            pass

    monkeypatch.setattr("core.match_db.MatchDB", _Recorder)
    db = pt._get_db(str(_REPO_ROOT))
    assert db is not None and opened, "no database was constructed - nothing under test"
    assert live not in opened, opened
