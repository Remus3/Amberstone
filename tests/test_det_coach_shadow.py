"""Tests for core.det_coach_shadow - the B1 do-not-flip-blind validation writer.

Each test uses its own tmp_path so the module-level per-path dedup cache is
isolated between cases (the cache keys on str(target_path)).
"""

from __future__ import annotations

import json

from core.det_coach_shadow import log_det_coaching

_NOW = "2026-06-06T00:00:00+00:00"


def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_writes_one_record_replaced_true(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"
    det = {
        "choices": [{"label": "A", "text": "trade"}],
        "callouts": [{"text": "drake 30s"}],
        "lead_projection": {"verdict": "ahead"},
    }
    native = [{"label": "A", "text": "native trade"}]

    rec = log_det_coaching(
        "sr", "Ahri", ["Zed", "Syndra"],
        det=det, native_choices=native,
        game_time_s=120.0, level=6, item_count=2,
        path=target, now_iso=_NOW,
    )

    assert rec is not None
    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["replaced"] is True
    assert row["det_choices"] == det["choices"]
    assert row["native_choices"] == native
    assert row["callouts"] == det["callouts"]
    assert row["lead_projection"] == det["lead_projection"]
    assert row["ts"] == _NOW
    assert row["mode"] == "sr"
    assert row["my_champion"] == "Ahri"
    assert row["enemy_champions"] == ["Zed", "Syndra"]


def test_replaced_false_when_det_choices_empty(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"
    det = {"choices": [], "callouts": [], "lead_projection": {}}
    native = [{"label": "A", "text": "native"}]

    rec = log_det_coaching(
        "aram", "Lux", ["Brand"],
        det=det, native_choices=native,
        path=target, now_iso=_NOW,
    )

    assert rec is not None
    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["replaced"] is False
    assert row["native_choices"] == native


def test_dedup_identical_call_writes_once(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"
    det = {"choices": [{"label": "A"}], "callouts": [], "lead_projection": {}}

    first = log_det_coaching(
        "sr", "Ahri", ["Zed"],
        det=det, native_choices=[], game_time_s=100.0,
        level=5, item_count=1, path=target, now_iso=_NOW,
    )
    second = log_det_coaching(
        "sr", "Ahri", ["Zed"],
        det=det, native_choices=[], game_time_s=100.0,
        level=5, item_count=1, path=target, now_iso=_NOW,
    )

    assert first is not None
    assert second is None
    assert len(_read_lines(target)) == 1


def test_distinct_sig_on_time_bucket_writes_twice(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"
    det = {"choices": [{"label": "A"}], "callouts": [], "lead_projection": {}}

    log_det_coaching(
        "sr", "Ahri", ["Zed"],
        det=det, native_choices=[], game_time_s=100.0,
        level=5, item_count=1, path=target, now_iso=_NOW,
    )
    log_det_coaching(
        "sr", "Ahri", ["Zed"],
        det=det, native_choices=[], game_time_s=110.0,
        level=5, item_count=1, path=target, now_iso=_NOW,
    )

    assert len(_read_lines(target)) == 2


def test_failsoft_empty_champion(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"
    rec = log_det_coaching(
        "sr", "", ["Zed"],
        det={"choices": []}, native_choices=[],
        path=target, now_iso=_NOW,
    )
    assert rec is None
    assert not target.exists()


def test_failsoft_empty_enemies(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"
    rec = log_det_coaching(
        "sr", "Ahri", [],
        det={"choices": []}, native_choices=[],
        path=target, now_iso=_NOW,
    )
    assert rec is None
    assert not target.exists()


def test_failsoft_bad_det_does_not_raise(tmp_path):
    target = tmp_path / "det_coach_shadow.jsonl"

    rec_none = log_det_coaching(
        "sr", "Ahri", ["Zed"],
        det=None, native_choices=[],
        game_time_s=50.0, path=target, now_iso=_NOW,
    )
    assert rec_none is not None
    row = json.loads(_read_lines(target)[0])
    assert row["replaced"] is False
    assert row["det_choices"] == []

    # A non-dict det (string) at a distinct time bucket also coerces to {}.
    rec_str = log_det_coaching(
        "sr", "Ahri", ["Zed"],
        det="garbage", native_choices=[],
        game_time_s=200.0, path=target, now_iso=_NOW,
    )
    assert rec_str is not None
    assert len(_read_lines(target)) == 2
