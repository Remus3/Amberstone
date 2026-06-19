"""Tests for core.replay_narrative_shadow.log_replay_narrative.

The do-not-flip-blind replay-narrative validation writer. Mirrors the
test_det_coach_shadow pattern: each test uses its own tmp_path so the
module-level per-path dedup cache is isolated (it keys on str(target_path)).
Pins: atomic append, per-match dedup, fail-soft on empty/missing fields, and no
leftover .tmp sibling after a write.
"""

from __future__ import annotations

import json

from core.replay_narrative_shadow import log_replay_narrative

_NOW = "2026-06-19T00:00:00+00:00"


def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def _sample_narrative():
    return {
        "ok": True,
        "summary": "Lux (MID) WIN in 30 min on patch 16.12 (CLASSIC).",
        "key_moments": [
            {
                "clock": "25:00",
                "event_type": "ELITE_MONSTER_KILL",
                "impact": 85.0,
                "text": "25:00 - Baron taken by your team",
            }
        ],
        "lessons": ["Good vision score - your warding gave the team map control."],
        "grade": {
            "role": "MID",
            "total_score": 64.0,
            "components": {"kda": 12.0},
            "percentile_grade": "B",
        },
    }


def test_writes_one_record(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"
    narrative = _sample_narrative()

    rec = log_replay_narrative(
        "NA1_TEST_1", narrative, path=target, now_iso=_NOW
    )

    assert rec is not None
    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["ts"] == _NOW
    assert row["match_id"] == "NA1_TEST_1"
    assert row["ok"] is True
    assert row["summary"] == narrative["summary"]
    assert row["key_moments"] == narrative["key_moments"]
    assert row["lessons"] == narrative["lessons"]
    assert row["grade"] == narrative["grade"]
    assert row["native"] == {}
    assert "engine_version" in row


def test_records_native_alongside_deterministic(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"
    native = {"ok": True, "summary": "haiku summary", "key_moments": ["m1"]}

    rec = log_replay_narrative(
        "NA1_TEST_1", _sample_narrative(), native=native,
        path=target, now_iso=_NOW,
    )

    assert rec is not None
    row = json.loads(_read_lines(target)[0])
    assert row["native"] == native
    # Deterministic surface is distinct from the native one.
    assert row["summary"] != native["summary"]


def test_atomic_append_no_leftover_tmp(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"

    log_replay_narrative("NA1_A", _sample_narrative(), path=target, now_iso=_NOW)
    log_replay_narrative("NA1_B", _sample_narrative(), path=target, now_iso=_NOW)

    # Two distinct matches -> two lines, appended (not overwritten).
    assert len(_read_lines(target)) == 2
    matches = [json.loads(l)["match_id"] for l in _read_lines(target)]
    assert matches == ["NA1_A", "NA1_B"]
    # No leftover atomic-write tmp sibling.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_dedup_same_match_writes_once(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"

    first = log_replay_narrative(
        "NA1_DUP", _sample_narrative(), path=target, now_iso=_NOW
    )
    second = log_replay_narrative(
        "NA1_DUP", _sample_narrative(), path=target, now_iso=_NOW
    )

    assert first is not None
    assert second is None
    assert len(_read_lines(target)) == 1


def test_distinct_match_writes_twice(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"

    log_replay_narrative("NA1_X", _sample_narrative(), path=target, now_iso=_NOW)
    log_replay_narrative("NA1_Y", _sample_narrative(), path=target, now_iso=_NOW)

    assert len(_read_lines(target)) == 2


def test_failsoft_blank_match_id(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"

    rec = log_replay_narrative("", _sample_narrative(), path=target, now_iso=_NOW)

    assert rec is None
    assert not target.exists()


def test_failsoft_none_narrative_coerces(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"

    rec = log_replay_narrative("NA1_NONE", None, path=target, now_iso=_NOW)

    assert rec is not None
    row = json.loads(_read_lines(target)[0])
    assert row["ok"] is False
    assert row["summary"] == ""
    assert row["key_moments"] == []
    assert row["lessons"] == []
    assert row["grade"] == {}


def test_failsoft_non_dict_narrative_does_not_raise(tmp_path):
    target = tmp_path / "replay_narrative_shadow.jsonl"

    rec = log_replay_narrative("NA1_STR", "garbage", path=target, now_iso=_NOW)

    assert rec is not None
    row = json.loads(_read_lines(target)[0])
    assert row["ok"] is False
