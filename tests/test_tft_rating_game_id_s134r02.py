"""S134-Q (research filing RM-889, acceptance 4): the TFT match_history row
carries the game's Riot gameId, or says unknown (0, the column's schema
DEFAULT at core/match_db.py) - never a silent 0 because nobody asked.

`performance_tracker.save_tft_rating` built its `db.save_match({...})` dict
with no `game_id` key, while the other-modes writer `save_rating` derives one
(item 211). Measured read-only 2026-10-25: all 8209 mode='TFT' rows in the
live data/match_history.db hold game_id 0, so no TFT row can be joined to the
RM-616 placement store (`data/tft_matches/<gameId>.*.json`) or to anything
else keyed on the game.

The frozen caller (app/_game_lifecycle.py on_game_end) hands over only the
two TFT data files, and neither writer stamps a game id. The id that IS on
disk at game end is the standalone client's per-round `TFTEoGStats.json`
(`tft.tft_standalone.read_eog`: fresh within EOG_MAX_AGE_S and a TFT game, or
None), whose top-level `gameId` is the same id the RM-616 store keys on.

The consumer artifact is diffed: the row read back from the tmp root's
match_history.db with sqlite3, through the real MatchDB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

import performance_tracker as pt
from tft import tft_standalone

_COACH = {"stage": 4, "game_time_s": 1800, "alive_others": 2}
_LIVE = {"level": 8, "stage_round": "4-2", "last_round_result": "3rd",
         "board_units": ["Jinx 2-star", "Vi"], "traits_active": ["Rebel 3"],
         "augments": []}
_GID = 1000000911


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("RC_ACCOUNT_ID", raising=False)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(pt, "_match_db", None)
    monkeypatch.setattr("tft.placement_aggregator.update_heatmap", lambda: None)
    yield tmp_path
    db = pt._match_db
    if db is not None:
        try:
            db.close()
        except Exception:  # noqa: BLE001 - teardown only
            pass


def _round_file(tmp_path, monkeypatch, doc, age_s=0.0):
    p = tmp_path / "TFTEoGStats.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    monkeypatch.setattr(tft_standalone, "eog_stats_path", lambda: p)
    return p


def _tft_game_ids(root) -> list:
    pt._match_db.close()
    con = sqlite3.connect(str(root / "data" / "match_history.db"))
    try:
        return [r[0] for r in con.execute(
            "SELECT game_id FROM matches WHERE mode = 'TFT'")]
    finally:
        con.close()


def _rate(root):
    grade, _ = pt.save_tft_rating(str(root), dict(_LIVE), dict(_COACH))
    assert grade, "fixture produced no rating - nothing under test"
    return _tft_game_ids(root)


def test_row_carries_the_game_id_from_a_fresh_round_file(root, monkeypatch):
    _round_file(root, monkeypatch, {"gameId": _GID, "gameMode": "TFT"})
    assert _rate(root) == [_GID]


def test_a_string_game_id_is_carried_as_the_integer(root, monkeypatch):
    _round_file(root, monkeypatch, {"gameId": str(_GID), "gameMode": "TFT"})
    assert _rate(root) == [_GID]


def test_the_save_match_dict_says_unknown_explicitly_without_a_round_file(
        root, monkeypatch):
    """No per-round file (the conftest seam points at a path that never
    exists): the row says unknown with an EXPLICIT 0 in the dict handed to
    save_match - not a key nobody set that the schema default papers over."""
    rows = []

    class _Db:
        def save_match(self, row):
            rows.append(dict(row))

    monkeypatch.setattr(pt, "_get_db", lambda sd: _Db())
    grade, _ = pt.save_tft_rating(str(root), dict(_LIVE), dict(_COACH))
    assert grade
    assert len(rows) == 1
    assert "game_id" in rows[0]
    assert rows[0]["game_id"] == 0


def test_a_stale_round_file_is_another_game_and_reads_unknown(root, monkeypatch):
    _round_file(root, monkeypatch, {"gameId": _GID, "gameMode": "TFT"},
                age_s=tft_standalone.EOG_MAX_AGE_S + 60)
    assert _rate(root) == [0]


def test_a_non_tft_round_file_reads_unknown(root, monkeypatch):
    _round_file(root, monkeypatch, {"gameId": _GID, "gameMode": "CLASSIC"})
    assert _rate(root) == [0]


@pytest.mark.parametrize("bad", [0, "0", "", None, -5, "-5", "abc", True, 1.5,
                                 [1], "1_000", chr(0xFF15)])
def test_an_unusable_game_id_reads_unknown(root, monkeypatch, bad):
    _round_file(root, monkeypatch, {"gameId": bad, "gameMode": "TFT"})
    assert _rate(root) == [0]


@pytest.mark.parametrize("huge", [2**63, "99999999999999999999"])
def test_an_id_past_sqlite_integer_reads_unknown_and_keeps_the_row(
        root, monkeypatch, huge):
    """S134 verifier: an id >= 2**63 raised OverflowError inside save_match,
    which logged "Match save failed" and wrote NO row - worse than the old
    code, which always wrote one. The row must survive with the id unknown."""
    _round_file(root, monkeypatch, {"gameId": huge, "gameMode": "TFT"})
    assert _rate(root) == [0]


def test_the_largest_sqlite_integer_is_still_an_id(root, monkeypatch):
    _round_file(root, monkeypatch, {"gameId": 2**63 - 1, "gameMode": "TFT"})
    assert _rate(root) == [2**63 - 1]


def test_a_raising_round_file_reader_never_costs_the_row(root, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("reader exploded")

    monkeypatch.setattr(tft_standalone, "read_eog", _boom)
    assert _rate(root) == [0]
