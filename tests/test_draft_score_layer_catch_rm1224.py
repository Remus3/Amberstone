"""RM-1224: one non-sqlite pair-query failure must not discard all five
draft_score layers.

Before the fix the per-layer catches in core/draft_score.py caught only
sqlite3.Error, so an OverflowError from an out-of-range bind (ally id
10**30) escaped to the assemble catch, which blanked every layer, including
the corpus-free damage_balance one, and still returned ok=True.
"""
from __future__ import annotations

import sqlite3

import pytest

from core import draft_score
from core.draft_score import compute_draft_score
from tests.test_draft_score import build_fixture_db_in_memory

_HUGE = 10 ** 30


def _conn():
    conn = sqlite3.connect(":memory:")
    build_fixture_db_in_memory(conn)
    return conn


def _dmg(cid):
    return "physical" if cid % 2 else "magical"


def _layers(out):
    return {ly["name"]: ly for ly in out["layers"]}


def test_overflow_bind_keeps_corpus_free_layers():
    out = compute_draft_score([_HUGE, 1, 2, 3, 4], enemy_ids=[5, 6, 7, 8, 9],
                              conn=_conn(), damage_class_resolver=_dmg,
                              scaling_resolver=lambda c: 0.5)
    assert out["ok"] is True
    layers = _layers(out)
    assert layers["damage_balance"]["sub_score"] is not None
    assert layers["scaling"]["sub_score"] is not None


def test_overflow_bind_skips_only_the_bad_champion():
    out = compute_draft_score([_HUGE, 64, 22, 3, 4], enemy_ids=[22, 64, 7, 8, 9],
                              conn=_conn())
    layers = _layers(out)
    # base_wr still averages the four in-range champions.
    assert layers["base_wr"]["sub_score"] is not None
    assert layers["matchup"]["sub_score"] is not None
    assert layers["synergy"]["sub_score"] is not None


def test_matchup_layer_absorbs_overflow():
    out = draft_score._matchup_layer(_conn(), [_HUGE], [1], None)
    assert out["sub_score"] is None


def test_synergy_layer_absorbs_overflow():
    out = draft_score._synergy_layer(_conn(), [_HUGE, 1], None, None, None)
    assert out["sub_score"] is None


def test_base_wr_layer_absorbs_overflow():
    out = draft_score._base_wr_layer(_conn(), [_HUGE], None)
    assert out["sub_score"] is None


def test_unexpected_error_type_is_not_swallowed_by_a_layer(monkeypatch):
    # The catch is narrowed to the expected types, never Exception: a
    # programming error in a primitive still reaches the assemble guard.
    from core import draft_elo_db

    def boom(*_a, **_k):
        raise KeyError("bug")

    monkeypatch.setattr(draft_elo_db, "solo_winrate", boom)
    with pytest.raises(KeyError):
        draft_score._base_wr_layer(_conn(), [1], None)
