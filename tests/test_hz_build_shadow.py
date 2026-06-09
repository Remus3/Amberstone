"""HZ-C2 - core.hz_build_shadow fail-soft writer tests.

Pins the gate (operator champ required, coverage-miss still recorded), the
coarse-state dedup, the record shape, and the never-raises contract. Writes to
a tmp path (test seam), never the live data/hz_build_shadow.jsonl.
"""
from __future__ import annotations

import json

from core import hz_build_shadow as hbs


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_writes_covered_record(tmp_path):
    p = tmp_path / "build.jsonl"
    rec = hbs.log_precomputed_build(
        "sr", "Ahri", ["Malphite", "Ornn", "Sion"],
        lean="anti_tank",
        choices=[{"key": "A", "label": "Build anti-tank"}],
        covered=True, item_count=1, game_time_s=600.0, path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["my_champion"] == "Ahri"
    assert r["enemy_comp"] == ["Malphite", "Ornn", "Sion"]
    assert r["lean"] == "anti_tank"
    assert r["covered"] is True
    assert len(r["choices"]) == 1
    assert r["engine_version"]


def test_captures_native_coach_signal(tmp_path):
    p = tmp_path / "build.jsonl"
    rec = hbs.log_precomputed_build(
        "sr", "Ahri", ["Malphite"], lean="anti_tank",
        choices=[{"key": "A", "label": "Build anti-tank"}], covered=True,
        native_action="Rush Void Staff vs their tanks",
        native_choices=[{"key": "A", "label": "Void Staff"}], path=p,
    )
    assert rec is not None
    r = _read(p)[0]
    assert r["native_action"] == "Rush Void Staff vs their tanks"
    assert r["native_choices"] == [{"key": "A", "label": "Void Staff"}]


def test_coverage_miss_still_recorded(tmp_path):
    p = tmp_path / "build.jsonl"
    rec = hbs.log_precomputed_build(
        "sr", "Yasuo", ["Malphite"], lean=None, choices=[], covered=False, path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert rows[0]["covered"] is False
    assert rows[0]["lean"] is None
    assert rows[0]["choices"] == []


def test_gate_requires_champion(tmp_path):
    p = tmp_path / "build.jsonl"
    assert hbs.log_precomputed_build("sr", "", [], lean=None, choices=[], path=p) is None
    assert not p.exists()


def test_dedup_same_state(tmp_path):
    p = tmp_path / "build.jsonl"
    kw = dict(lean="anti_tank", choices=[], covered=True, item_count=1,
              game_time_s=601.0, path=p)
    first = hbs.log_precomputed_build("sr", "Ahri", ["Malphite"], **kw)
    kw2 = dict(kw)
    kw2["game_time_s"] = 603.0  # same 5s bucket
    second = hbs.log_precomputed_build("sr", "Ahri", ["Malphite"], **kw2)
    assert first is not None and second is None
    assert len(_read(p)) == 1


def test_dedup_breaks_on_item_count(tmp_path):
    p = tmp_path / "build.jsonl"
    kw = dict(lean="anti_tank", choices=[], covered=True, item_count=1,
              game_time_s=601.0, path=p)
    hbs.log_precomputed_build("sr", "Ahri", ["Malphite"], **kw)
    kw2 = dict(kw)
    kw2["item_count"] = 2
    rec = hbs.log_precomputed_build("sr", "Ahri", ["Malphite"], **kw2)
    assert rec is not None
    assert len(_read(p)) == 2


def test_never_raises_on_bad_path(tmp_path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    bad = tmp_path / "f.txt" / "build.jsonl"
    assert hbs.log_precomputed_build("sr", "Ahri", ["Malphite"],
                                     lean="anti_tank", choices=[], path=bad) is None
