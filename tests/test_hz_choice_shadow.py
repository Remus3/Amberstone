"""HZ-C1 - core.hz_choice_shadow fail-soft writer tests.

Pins the gate (operator champ required, coverage-miss still recorded), the
coarse-state dedup, the record shape, and the never-raises contract. Writes to
a tmp path (the test seam), never the live data/hz_choice_shadow.jsonl.
"""
from __future__ import annotations

import json

from core import hz_choice_shadow as hzs


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_writes_covered_record(tmp_path):
    p = tmp_path / "shadow.jsonl"
    rec = hzs.log_precomputed_choices(
        "sr", "Annie", "Caitlyn",
        choices=[{"key": "A", "label": "All-in Caitlyn"}],
        band="L6", mana_state="full", cd_state="all_up", covered=True,
        level=6, item_count=1, game_time_s=300.0, path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["my_champion"] == "Annie"
    assert r["enemy"] == "Caitlyn"
    assert r["covered"] is True
    assert r["band"] == "L6"
    assert len(r["choices"]) == 1
    assert r["engine_version"]  # stamped


def test_coverage_miss_still_recorded(tmp_path):
    p = tmp_path / "shadow.jsonl"
    rec = hzs.log_precomputed_choices(
        "sr", "Yasuo", None,
        choices=[], covered=False, level=6, path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["covered"] is False
    assert rows[0]["enemy"] is None
    assert rows[0]["choices"] == []


def test_gate_requires_champion(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert hzs.log_precomputed_choices("sr", "", None, choices=[], path=p) is None
    assert hzs.log_precomputed_choices("sr", None, None, choices=[], path=p) is None
    assert not p.exists()


def test_dedup_same_coarse_state(tmp_path):
    p = tmp_path / "shadow.jsonl"
    kw = dict(choices=[], band="L6", mana_state="full", cd_state="all_up",
              covered=True, level=6, item_count=1, game_time_s=301.0, path=p)
    first = hzs.log_precomputed_choices("sr", "Annie", "Caitlyn", **kw)
    # same 5s bucket (301 -> 303) -> dedup skip
    kw2 = dict(kw)
    kw2["game_time_s"] = 303.0
    second = hzs.log_precomputed_choices("sr", "Annie", "Caitlyn", **kw2)
    assert first is not None
    assert second is None
    assert len(_read(p)) == 1


def test_dedup_breaks_on_state_change(tmp_path):
    p = tmp_path / "shadow.jsonl"
    kw = dict(choices=[], band="L6", mana_state="full", cd_state="all_up",
              covered=True, level=6, item_count=1, game_time_s=301.0, path=p)
    hzs.log_precomputed_choices("sr", "Annie", "Caitlyn", **kw)
    # item_count change -> new sig -> writes
    kw2 = dict(kw)
    kw2["item_count"] = 2
    rec = hzs.log_precomputed_choices("sr", "Annie", "Caitlyn", **kw2)
    assert rec is not None
    assert len(_read(p)) == 2


def test_never_raises_on_bad_path(tmp_path):
    # A path whose parent cannot be created should fail-soft to None, not raise.
    bad = tmp_path / "f.txt" / "shadow.jsonl"  # f.txt is a file-like leaf
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    assert hzs.log_precomputed_choices("sr", "Annie", "Caitlyn",
                                       choices=[], path=bad) is None
