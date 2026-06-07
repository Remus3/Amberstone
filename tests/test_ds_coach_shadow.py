"""Tests for core/ds_coach_shadow.py - fail-soft shadow log writer.

Dependency-injected builders only; sibling modules (core.ds_antitank_hint,
core.ds_scaling_hint) are NOT imported here - they may be absent in this slice.
"""

import json
import pytest


# ---------------------------------------------------------------------------
# Fake builders injected in every test - sibling modules are never touched
# ---------------------------------------------------------------------------

def _fake_antitank(champ, enemies, mode):
    return {"applies": True, "hint": "x"}


def _fake_scaling(champ, enemies, mode, game_time_s):
    return {"verdict": "even"}


def _raising_builder(*args, **kwargs):
    raise RuntimeError("builder exploded intentionally")


# ---------------------------------------------------------------------------
# Import subject under test
# ---------------------------------------------------------------------------

from core.ds_coach_shadow import log_coach_hints, SHADOW_PATH  # noqa: E402


# ---------------------------------------------------------------------------
# (a) Successful call writes exactly one jsonl line; keys + values match
# ---------------------------------------------------------------------------

def test_success_writes_one_line(tmp_path):
    out = tmp_path / "shadow.jsonl"
    result = log_coach_hints(
        "ARAM",
        "Jinx",
        ["Malphite", "Leona"],
        game_time_s=300.0,
        antitank_builder=_fake_antitank,
        scaling_builder=_fake_scaling,
        path=out,
    )
    assert result is not None
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["mode"] == "ARAM"
    assert record["my_champion"] == "Jinx"
    assert record["enemy_champions"] == ["Malphite", "Leona"]
    assert record["game_time_s"] == 300.0
    assert record["antitank"] == {"applies": True, "hint": "x"}
    assert record["scaling"] == {"verdict": "even"}
    assert "ts" in record
    assert "engine_version" in record


# ---------------------------------------------------------------------------
# (b) now_iso injection appears verbatim in ts
# ---------------------------------------------------------------------------

def test_now_iso_injected(tmp_path):
    out = tmp_path / "shadow.jsonl"
    fixed_ts = "2026-06-06T00:00:00+00:00"
    result = log_coach_hints(
        "SR",
        "Jinx",
        [],
        now_iso=fixed_ts,
        antitank_builder=_fake_antitank,
        scaling_builder=_fake_scaling,
        path=out,
    )
    assert result is not None
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert record["ts"] == fixed_ts


# ---------------------------------------------------------------------------
# (c) Second call appends -> 2 lines
# ---------------------------------------------------------------------------

def test_second_call_appends(tmp_path):
    out = tmp_path / "shadow.jsonl"
    log_coach_hints(
        "ARAM", "Jinx", [],
        antitank_builder=_fake_antitank,
        scaling_builder=_fake_scaling,
        path=out,
    )
    log_coach_hints(
        "SR", "Caitlyn", [],
        antitank_builder=_fake_antitank,
        scaling_builder=_fake_scaling,
        path=out,
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["mode"] == "ARAM"
    assert json.loads(lines[1])["mode"] == "SR"


# ---------------------------------------------------------------------------
# (d) Raising builder -> returns None, does NOT raise
# ---------------------------------------------------------------------------

def test_raising_builder_returns_none(tmp_path):
    out = tmp_path / "shadow.jsonl"
    result = log_coach_hints(
        "ARAM",
        "Jinx",
        ["Malphite"],
        antitank_builder=_raising_builder,
        scaling_builder=_fake_scaling,
        path=out,
    )
    assert result is None  # fail-soft: must not raise


# ---------------------------------------------------------------------------
# (e) enemy_champions=None is tolerated
# ---------------------------------------------------------------------------

def test_none_enemy_champions_tolerated(tmp_path):
    out = tmp_path / "shadow.jsonl"
    result = log_coach_hints(
        "ARAM",
        "Jinx",
        None,  # type: ignore[arg-type]
        antitank_builder=_fake_antitank,
        scaling_builder=_fake_scaling,
        path=out,
    )
    assert result is not None
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert record["enemy_champions"] == []


# ---------------------------------------------------------------------------
# (f) SHADOW_PATH default is data/ds_coach_hints_shadow.jsonl under project root
# ---------------------------------------------------------------------------

def test_shadow_path_default():
    assert SHADOW_PATH.name == "ds_coach_hints_shadow.jsonl"
    assert SHADOW_PATH.parent.name == "data"
