"""DSP9 G7 comp-harness hermetic tests - pure helpers only (no engine, no network).

The g7_comp_harness lives under ops/audit/lolmath_ds_sweep/ (an audit tool, not an
installed package), so it is loaded by path. Only the pure helpers are exercised here;
the full per-champion engine sweep in ``main()`` is a standalone probe (the g2/g5 probe
precedent), never run under pytest.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HARNESS = Path(__file__).resolve().parent.parent / "ops" / "audit" / "lolmath_ds_sweep" / "g7_comp_harness.py"
_spec = importlib.util.spec_from_file_location("g7_comp_harness", _HARNESS)
g7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g7)


def test_lolmath_comp_is_four_squishy_one_tank():
    # gen_md.py methodology: lolmath's constant default enemy comp =
    # Jayce / Sejuani / Annie / Lucian / Thresh = 4 squishy + 1 tank.
    comp = g7.LOLMATH_COMP
    assert len(comp) == 5
    durs = [d for _, d in comp]
    assert durs.count("tank") == 1
    assert durs.count("squishy") == 4
    assert [c for c, d in comp if d == "tank"] == ["Sejuani"]


def test_classify_comp_lolmath_is_burst_heavy():
    # 4 squishy + 1 tank -> a glass-leaning comp -> the burst_heavy DS variant,
    # NOT the static `mixed` variant gen_md.py blindly compares against.
    assert g7.classify_comp(g7.LOLMATH_COMP) == "burst_heavy"


def test_classify_comp_frontline_wall():
    wall = [("A", "tank"), ("B", "tank"), ("C", "tank"), ("D", "bruiser"), ("E", "squishy")]
    assert g7.classify_comp(wall) == "frontline_heavy"


def test_classify_comp_poke():
    poke = [("A", "poke"), ("B", "poke"), ("C", "poke"), ("D", "squishy"), ("E", "tank")]
    assert g7.classify_comp(poke) == "poke"


def test_classify_comp_balanced_is_mixed():
    bal = [("A", "tank"), ("B", "bruiser"), ("C", "squishy"), ("D", "squishy"), ("E", "poke")]
    assert g7.classify_comp(bal) == "mixed"


def test_classify_comp_returns_known_bucket():
    assert g7.classify_comp(g7.LOLMATH_COMP) in g7.DS_COMP_ARCHETYPES


def test_resolve_comp_target_keys_and_positive():
    t = g7.resolve_comp_target(g7.LOLMATH_COMP, level=11)
    for k in ("target_armor", "target_mr", "target_max_hp", "target_bonus_hp"):
        assert k in t
        assert t[k] > 0.0


def test_resolve_comp_target_monotonic_in_level():
    lo = g7.resolve_comp_target(g7.LOLMATH_COMP, level=1)
    hi = g7.resolve_comp_target(g7.LOLMATH_COMP, level=18)
    # resists scale with level; HP terms are level-independent representatives.
    assert hi["target_armor"] > lo["target_armor"]
    assert hi["target_mr"] > lo["target_mr"]


def test_resolve_comp_target_tankier_comp_is_more_durable():
    all_tank = [("A", "tank")] * 5
    tank_t = g7.resolve_comp_target(all_tank, level=11)
    glass_t = g7.resolve_comp_target(g7.LOLMATH_COMP, level=11)
    assert tank_t["target_armor"] > glass_t["target_armor"]
    assert tank_t["target_mr"] > glass_t["target_mr"]
    assert tank_t["target_max_hp"] > glass_t["target_max_hp"]


def test_resolve_comp_target_lolmath_squishier_than_mixed_on_hp():
    # The whole G7 point: the lolmath comp is squishier than DS's static `mixed`
    # neutral target (max_hp 2400), so comparing against `mixed` understates parity.
    t = g7.resolve_comp_target(g7.LOLMATH_COMP, level=11)
    assert t["target_max_hp"] < 2400.0


def test_score_overlap_counts_shared_non_boots():
    lm = ["Infinity Edge", "The Collector", "Berserker's Greaves", "No Item"]
    ds = ["Infinity Edge", "The Collector", "Lord Dominik's Regards", "Plated Steelcaps"]
    # IE + Collector shared; boots + "No Item" excluded.
    assert g7.score_overlap(lm, ds) == 2


def test_score_overlap_empty():
    assert g7.score_overlap([], ["Infinity Edge"]) == 0
    assert g7.score_overlap(["Infinity Edge"], []) == 0


def test_score_overlap_boots_never_count():
    assert g7.score_overlap(["Berserker's Greaves"], ["Berserker's Greaves"]) == 0
