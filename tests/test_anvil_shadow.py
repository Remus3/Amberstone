"""Tests for core.anvil_shadow - arena item-anvil do-not-flip-blind validation
writer + offline agreement report.

Mirrors the contract pinned for core.augment_shadow: fail-soft capture (never
raises), coarse-state dedup, native-vs-deterministic record shape, plus a
name-normalized top-1 agreement summary + a take-rank distribution. The anvil
panel is shown once per anvil event, so dedup keys on the offered + owned set
to write at most one record per distinct offer situation.

A no-match substrate result is still a real validation signal, so (unlike the
augment writer) a low-conf deterministic block does NOT gate the write - only a
missing offer or a non-dict deterministic block does.
"""
from __future__ import annotations

import json

import pytest

from core import anvil_shadow as anv


def _det(take="Kraken Slayer", take_rank=1, ranked=None, n_matches=2, conf="ok"):
    """A compute_anvil_pick-shaped deterministic block."""
    if ranked is None:
        ranked = [
            {"name": "Kraken Slayer", "rank": 1, "in_ideal_path": True},
            {"name": "Bloodthirster", "rank": 3, "in_ideal_path": True},
        ]
    return {
        "take": take,
        "take_rank": take_rank,
        "n_matches": n_matches,
        "conf": conf,
        "ranked": ranked,
        "ideal_path": ["Kraken Slayer", "Infinity Edge", "Bloodthirster"],
    }


def _state(offered=None, owned=None, champ="Jinx"):
    return {
        "mode": "arena",
        "champion": champ,
        "round": 3,
        "offered": offered if offered is not None else ["Kraken Slayer", "Bloodthirster"],
        "owned": owned if owned is not None else [],
    }


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


@pytest.fixture(autouse=True)
def _reset_sig():
    """The module dedups via a process-level _LAST_SIG; clear it per case so
    tests do not bleed signatures into each other."""
    anv._LAST_SIG.clear()
    yield
    anv._LAST_SIG.clear()


def test_writes_record_with_both_surfaces(tmp_path):
    p = tmp_path / "anv.jsonl"
    rec = anv.log_anvil_advice(
        _state(),
        {"take": "Kraken Slayer", "why": "scales"},
        _det(),
        path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["mode"] == "arena"
    assert r["champion"] == "Jinx"
    assert r["offered"] == ["Kraken Slayer", "Bloodthirster"]
    assert r["native"]["take"] == "Kraken Slayer"
    assert r["native"]["why"] == "scales"
    assert r["deterministic"]["take"] == "Kraken Slayer"
    assert r["deterministic"]["take_rank"] == 1
    assert r["deterministic"]["conf"] == "ok"
    assert [x["name"] for x in r["deterministic"]["ranked"]] == [
        "Kraken Slayer", "Bloodthirster"
    ]
    assert "engine_version" in r and "ts" in r


def test_dedups_identical_offer_state(tmp_path):
    p = tmp_path / "anv.jsonl"
    n = {"take": "Bloodthirster", "why": ""}
    assert anv.log_anvil_advice(_state(), n, _det(), path=p) is not None
    # Same offer + owned + champ + mode -> deduped.
    assert anv.log_anvil_advice(_state(), n, _det(), path=p) is None
    # Different owned set -> a new distinct state writes again.
    assert anv.log_anvil_advice(_state(owned=["Kraken Slayer"]), n, _det(), path=p) is not None
    assert len(_read(p)) == 2


def test_gate_no_offered(tmp_path):
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state(offered=[]), {"take": "x"}, _det(), path=p) is None
    assert not p.exists()


def test_low_conf_substrate_still_logs(tmp_path):
    # A no-match substrate (conf="low", n_matches=0) is a real validation
    # signal, so it MUST still be written - unlike the augment writer.
    p = tmp_path / "anv.jsonl"
    det = _det(take=None, take_rank=None, ranked=[
        {"name": "Warmog's Armor", "rank": None, "in_ideal_path": False},
    ], n_matches=0, conf="low")
    rec = anv.log_anvil_advice(
        _state(offered=["Warmog's Armor"]),
        {"take": "Warmog's Armor", "why": "tanky"},
        det,
        path=p,
    )
    assert rec is not None
    assert _read(p)[0]["deterministic"]["conf"] == "low"


def test_gate_non_dict_deterministic(tmp_path):
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state(), {"take": "x"}, None, path=p) is None
    assert anv.log_anvil_advice(_state(), {"take": "x"}, "nope", path=p) is None
    assert not p.exists()


def test_fail_soft_on_bad_input(tmp_path):
    p = tmp_path / "anv.jsonl"
    # Non-dict args must not raise.
    assert anv.log_anvil_advice(None, None, None, path=p) is None
    assert anv.log_anvil_advice("nope", 5, [], path=p) is None


def test_summarize_top1_agreement_and_rank():
    rows = [
        # Haiku agrees with the substrate take.
        {"native": {"take": "Kraken Slayer"}, "deterministic": {
            "take": "Kraken Slayer", "ranked": [
                {"name": "Kraken Slayer", "rank": 1},
                {"name": "Bloodthirster", "rank": 3}]}},
        # Haiku takes a different item that the substrate ranked #3.
        {"native": {"take": "Bloodthirster"}, "deterministic": {
            "take": "Kraken Slayer", "ranked": [
                {"name": "Kraken Slayer", "rank": 1},
                {"name": "Bloodthirster", "rank": 3}]}},
        # Haiku's take is not in the substrate ranking -> rank None.
        {"native": {"take": "Mystery Item"}, "deterministic": {
            "take": "Kraken Slayer", "ranked": [
                {"name": "Kraken Slayer", "rank": 1}]}},
    ]
    s = anv.summarize_agreement(rows)
    assert s["n"] == 3
    assert s["n_with_native_take"] == 3
    assert s["top1_agree"] == 1
    assert s["take_rank_dist"]["1"] == 1
    assert s["take_rank_dist"]["3"] == 1
    assert s["take_rank_dist"]["none"] == 1


def test_summarize_name_normalization():
    rows = [
        {"native": {"take": "kraken  slayer!"}, "deterministic": {
            "take": "Kraken Slayer", "ranked": [{"name": "Kraken Slayer", "rank": 1}]}},
    ]
    s = anv.summarize_agreement(rows)
    assert s["top1_agree"] == 1


def test_summarize_reads_jsonl_path(tmp_path):
    p = tmp_path / "anv.jsonl"
    anv.log_anvil_advice(
        _state(),
        {"take": "Kraken Slayer"},
        _det(),
        path=p,
    )
    s = anv.summarize_agreement(p)
    assert s["n"] == 1
    assert s["top1_agree"] == 1


def test_summarize_empty():
    s = anv.summarize_agreement([])
    assert s["n"] == 0
    assert s["top1_agree"] == 0
    assert s["top1_agree_pct"] == 0.0
