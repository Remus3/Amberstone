"""Tests for core.champ_select_shadow - the do-not-flip-blind champ-select
pick-advisor shadow writer (native Haiku vs deterministic candidate)."""
from __future__ import annotations

import json

from core.champ_select_shadow import log_champ_select_advice

_STATE = {
    "is_aram": True, "queue_id": 450, "my_champion": "Ahri",
    "my_team": ["Ahri", "Zed", "Lux"], "their_team": ["Caitlyn", "Leona"],
    "bench": ["Ashe"],
}
_NATIVE = {"advice": "Stay Ahri", "swap": "", "summoners": "Flash + Heal",
           "watchout": "Caitlyn"}
_DET = {"advice": "Stay Ahri - solid into this comp.", "swap": "",
        "summoners": "Flash + Barrier", "watchout": "Watch Caitlyn (marksman)."}


def _lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_writes_record(tmp_path):
    p = tmp_path / "cs.jsonl"
    rec = log_champ_select_advice(_STATE, _NATIVE, _DET, path=p)
    assert rec is not None
    rows = _lines(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["my_champion"] == "Ahri"
    assert r["native"]["advice"] == "Stay Ahri"
    assert r["deterministic"]["summoners"] == "Flash + Barrier"
    assert "engine_version" in r and r["engine_version"]


def test_native_and_deterministic_normalized(tmp_path):
    p = tmp_path / "cs.jsonl"
    # Non-dict native/det must normalize to the empty 4-field shape, not crash.
    rec = log_champ_select_advice(_STATE, None, "garbage", path=p)
    assert rec is not None
    assert set(rec["native"]) == {"advice", "swap", "summoners", "watchout"}
    assert set(rec["deterministic"]) == {"advice", "swap", "summoners", "watchout"}
    assert all(v == "" for v in rec["native"].values())


def test_dedup_identical_state(tmp_path):
    p = tmp_path / "cs.jsonl"
    assert log_champ_select_advice(_STATE, _NATIVE, _DET, path=p) is not None
    # Same coarse pick state -> deduped (returns None, no second line).
    assert log_champ_select_advice(_STATE, _NATIVE, _DET, path=p) is None
    assert len(_lines(p)) == 1


def test_distinct_state_appends(tmp_path):
    p = tmp_path / "cs.jsonl"
    log_champ_select_advice(_STATE, _NATIVE, _DET, path=p)
    other = dict(_STATE, my_champion="Lux")
    rec = log_champ_select_advice(other, _NATIVE, _DET, path=p)
    assert rec is not None
    assert len(_lines(p)) == 2


def test_failsoft_bad_input_returns_none(tmp_path):
    p = tmp_path / "cs.jsonl"
    assert log_champ_select_advice(None, _NATIVE, _DET, path=p) is None
    assert log_champ_select_advice({}, _NATIVE, _DET, path=p) is None
    assert log_champ_select_advice({"my_team": ["Ashe"]}, _NATIVE, _DET, path=p) is None
    assert not p.exists()  # nothing written on a gate miss


def test_now_iso_passthrough(tmp_path):
    p = tmp_path / "cs.jsonl"
    rec = log_champ_select_advice(_STATE, _NATIVE, _DET, path=p,
                                  now_iso="2026-06-18T00:00:00+00:00")
    assert rec["ts"] == "2026-06-18T00:00:00+00:00"
