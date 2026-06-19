"""Tests for core.augment_shadow - arena augment-select do-not-flip-blind
validation writer + offline agreement report.

Mirrors the contract pinned for core.champ_select_shadow / core.hz_choice_shadow:
fail-soft capture (never raises), coarse-state dedup, native-vs-deterministic
record shape, plus a name-normalized top-1 agreement summary the laning report
analog gives the laning lane.
"""
from __future__ import annotations

import json

import pytest

from core import augment_shadow as aug


def _det(top="Blade Waltz", ranked=None):
    """A reco_fields-shaped deterministic block (see arena_coach._augment_recommendation)."""
    if ranked is None:
        ranked = [
            {"id": 1, "name": "Blade Waltz", "score": 0.61, "conf": 0.4},
            {"id": 2, "name": "Goliath", "score": 0.55, "conf": 0.3},
            {"id": 3, "name": "Tank It Or Leave It", "score": 0.50, "conf": 0.0},
        ]
    return {
        "aug_reco": ranked,
        "aug_reco_top": top,
        "aug_reco_top_score": ranked[0]["score"] if ranked else None,
        "aug_reco_conf": ranked[0]["conf"] if ranked else None,
        "aug_reco_mode": "arena",
        "aug_reco_stage": None,
        "aug_reco_n_matches": 12,
        "aug_reco_external": True,
    }


def _state(offered=None, picked=None, champ="Jinx"):
    return {
        "mode": "arena",
        "champion": champ,
        "round": 2,
        "stage": None,
        "offered": offered if offered is not None else ["Blade Waltz", "Goliath", "Tank It Or Leave It"],
        "picked": picked if picked is not None else [],
    }


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_writes_record_with_both_surfaces(tmp_path):
    p = tmp_path / "aug.jsonl"
    rec = aug.log_augment_advice(
        _state(),
        {"take": "Blade Waltz", "why": "scales", "plan": "all-in"},
        _det(),
        path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["mode"] == "arena"
    assert r["champion"] == "Jinx"
    assert r["offered"] == ["Blade Waltz", "Goliath", "Tank It Or Leave It"]
    assert r["native"]["take"] == "Blade Waltz"
    assert r["deterministic"]["top"] == "Blade Waltz"
    assert [x["name"] for x in r["deterministic"]["ranked"]] == [
        "Blade Waltz", "Goliath", "Tank It Or Leave It"
    ]
    assert "engine_version" in r and "ts" in r


def test_dedups_identical_offer_state(tmp_path):
    p = tmp_path / "aug.jsonl"
    n = {"take": "Goliath", "why": "", "plan": ""}
    assert aug.log_augment_advice(_state(), n, _det(), path=p) is not None
    # Same offer + picked + champ + mode -> deduped.
    assert aug.log_augment_advice(_state(), n, _det(), path=p) is None
    # Different picked set -> a new distinct state writes again.
    assert aug.log_augment_advice(_state(picked=["Blade Waltz"]), n, _det(), path=p) is not None
    assert len(_read(p)) == 2


def test_gate_no_offered(tmp_path):
    p = tmp_path / "aug.jsonl"
    assert aug.log_augment_advice(_state(offered=[]), {"take": "x"}, _det(), path=p) is None
    assert not p.exists()


def test_gate_no_deterministic_ranking(tmp_path):
    p = tmp_path / "aug.jsonl"
    # Empty reco_fields (recommender had nothing usable) -> nothing to validate.
    assert aug.log_augment_advice(_state(), {"take": "x"}, {}, path=p) is None
    assert aug.log_augment_advice(_state(), {"take": "x"}, {"aug_reco": []}, path=p) is None
    assert not p.exists()


def test_fail_soft_on_bad_input(tmp_path):
    p = tmp_path / "aug.jsonl"
    # Non-dict args must not raise.
    assert aug.log_augment_advice(None, None, None, path=p) is None
    assert aug.log_augment_advice("nope", 5, [], path=p) is None


def test_summarize_top1_agreement_and_rank():
    rows = [
        # Haiku agrees with det top.
        {"native": {"take": "Blade Waltz"}, "deterministic": {"ranked": [
            {"name": "Blade Waltz"}, {"name": "Goliath"}]}},
        # Haiku takes the det #2.
        {"native": {"take": "Goliath"}, "deterministic": {"ranked": [
            {"name": "Blade Waltz"}, {"name": "Goliath"}]}},
        # Haiku's take is not in the det ranking -> rank None.
        {"native": {"take": "Mystery Aug"}, "deterministic": {"ranked": [
            {"name": "Blade Waltz"}, {"name": "Goliath"}]}},
    ]
    s = aug.summarize_agreement(rows)
    assert s["n"] == 3
    assert s["n_with_native_take"] == 3
    assert s["top1_agree"] == 1
    assert s["take_rank_dist"]["1"] == 1
    assert s["take_rank_dist"]["2"] == 1
    assert s["take_rank_dist"]["none"] == 1


def test_summarize_name_normalization():
    # "Take:" prefix / case / punctuation should still match the det name.
    rows = [
        {"native": {"take": "blade  waltz!"}, "deterministic": {"ranked": [{"name": "Blade Waltz"}]}},
    ]
    s = aug.summarize_agreement(rows)
    assert s["top1_agree"] == 1


def test_summarize_reads_jsonl_path(tmp_path):
    p = tmp_path / "aug.jsonl"
    aug.log_augment_advice(
        _state(),
        {"take": "Blade Waltz"},
        _det(),
        path=p,
    )
    s = aug.summarize_agreement(p)
    assert s["n"] == 1
    assert s["top1_agree"] == 1


def test_summarize_empty():
    s = aug.summarize_agreement([])
    assert s["n"] == 0
    assert s["top1_agree"] == 0
    assert s["top1_agree_pct"] == 0.0
