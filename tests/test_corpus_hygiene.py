"""Corpus hygiene: which matches are fit to mine rules from."""
from __future__ import annotations

import json

from core import corpus_hygiene as ch


def _match(duration=1600, early=False):
    return {"info": {"gameDuration": duration,
                     "participants": [{"participantId": 1,
                                       "gameEndedInEarlySurrender": early}]}}


def test_a_normal_match_is_included():
    assert ch.judge(_match()).include is True


def test_a_remake_is_excluded():
    v = ch.judge(_match(duration=70))
    assert v.include is False
    assert "remake" in v.reason


def test_the_remake_boundary_is_five_minutes():
    assert ch.judge(_match(duration=ch.REMAKE_MAX_SECONDS - 1)).include is False
    assert ch.judge(_match(duration=ch.REMAKE_MAX_SECONDS)).include is True


def test_an_early_surrender_is_excluded():
    assert ch.judge(_match(early=True)).include is False


def test_a_missing_duration_does_not_exclude_the_match():
    # Absent data must not masquerade as a remake.
    assert ch.judge({"info": {"participants": []}}).include is True


# ------------------------------------------------------- sidecar ground truth

def _sidecar(tmp_path, rows):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"players": rows}), encoding="utf-8")
    return p


def test_sidecar_afk_excludes_a_match_that_looks_fine_to_the_api(tmp_path):
    # THE CASE THAT MOTIVATES THIS MODULE: 6 of 9 AFK games in the corpus ran
    # full length and are invisible to Match-V5.
    sc = _sidecar(tmp_path, [{"WAS_AFK": "1"}, {"WAS_AFK": "0"}])
    assert ch.judge(_match()).include is True
    v = ch.judge(_match(), sc)
    assert v.include is False
    assert "afk" in v.reason


def test_the_string_zero_is_not_treated_as_afk(tmp_path):
    # Every sidecar value is a STRING, and "0" is truthy in Python - a truthy
    # check would mark every player in the corpus as AFK.
    sc = _sidecar(tmp_path, [{"WAS_AFK": "0"}, {"WAS_LEAVER": "0"}])
    assert ch.sidecar_has_afk(sc) is False
    assert ch.judge(_match(), sc).include is True


def test_a_leaver_also_excludes(tmp_path):
    sc = _sidecar(tmp_path, [{"WAS_LEAVER": "1"}])
    assert ch.sidecar_has_afk(sc) is True


def test_a_missing_or_unreadable_sidecar_does_not_exclude(tmp_path):
    assert ch.sidecar_has_afk(tmp_path / "nope.json") is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ch.sidecar_has_afk(bad) is False


def test_a_non_numeric_afk_value_does_not_crash(tmp_path):
    sc = _sidecar(tmp_path, [{"WAS_AFK": "yes"}])
    assert ch.sidecar_has_afk(sc) is False


# ------------------------------------------------------------------ partition

def test_partition_splits_and_keeps_the_reason():
    keep, drop = ch.partition([(_match(), None), (_match(duration=70), None)])
    assert len(keep) == 1
    assert len(drop) == 1 and "remake" in drop[0][1]


def test_the_undetectable_rate_is_the_measured_one():
    # 6 of 407 corpus games carried an AFK invisible to Match-V5.
    assert 0.01 < ch.UNDETECTABLE_AFK_RATE < 0.02
