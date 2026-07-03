"""Characterization + regression tests for core.aram_comp_verdict.

The deterministic ARAM comp-verdict engine replaces the live Haiku call in
coaches/aram_team_analyzer.analyze() for the meaningful case (a full team is
present). It is correct-by-construction: the top-3 rubric factors (range mix /
damage-type balance / frontline) are computed from champions.json facts, not a
game-outcome prediction, so unlike the matchup engine it is validatable offline
(these tests ARE the validation - there is no stochastic outcome to be a
coin-flip against).

Champion facts used below are from data/daemon_slayer/16.11.1/champions.json:
  ranged (attackrange >= 500): Caitlyn 650, Ahri 550, Jhin 550, Soraka 550,
    Teemo 500, Lux 550, Ziggs 550, Ashe 600.
  melee (< 500): Aatrox 175, Leona 125, Malphite 125, Jax 125, Garen 175,
    Darius 175, Sett 125, Amumu 125.
  AD-lean (info.attack > info.magic): Caitlyn 8/2, Aatrox 8/3, Jhin 10/6,
    Jax, Darius, Garen, Zed.
  AP-lean (info.magic > info.attack): Ahri 3/8, Soraka 2/7, Lux, Ziggs, Brand.
  Tank tag: Leona, Malphite, Ornn, Sion.
"""
from __future__ import annotations

import pytest

from core import aram_comp_verdict as cv

_OK_RECS = {"swap", "variant", "stay"}

# Five-melee, all-AD comp (deliberately broken on range + damage).
_ALL_MELEE_AD = ["Aatrox", "Jax", "Garen", "Darius", "Sett"]
# Balanced: 3 ranged + 2 melee, mixed AD/AP, has a tank frontline.
_BALANCED = ["Caitlyn", "Ahri", "Malphite", "Aatrox", "Lux"]


def _state(my_team, *, my_champion=None, bench=None, variants=None, current_variant="default"):
    return {
        "my_team": list(my_team),
        "their_team": ["Yasuo", "Zed", "Lee Sin", "Riven", "Akali"],
        "my_champion": my_champion or my_team[0],
        "current_variant": current_variant,
        "bench": list(bench or []),
        "variants": list(variants or []),
    }


def test_output_shape_matches_analyze_contract():
    out = cv.comp_verdict(_state(_BALANCED))
    for key in ("ok", "recommendation", "swap_to", "variant_to", "reason",
                "confidence", "factors"):
        assert key in out, f"missing key {key}"
    assert out["recommendation"] in _OK_RECS
    assert out["confidence"] in {"high", "medium", "low"}
    assert isinstance(out["factors"], dict)


def test_balanced_comp_recommends_stay():
    out = cv.comp_verdict(_state(_BALANCED))
    assert out["ok"] is True
    assert out["recommendation"] == "stay"


def test_all_melee_comp_swaps_to_ranged_bench():
    # No ranged on team; a ranged bench champ exists -> swap to fix range gap.
    out = cv.comp_verdict(
        _state(_ALL_MELEE_AD, bench=["Garen", "Caitlyn", "Malphite"])
    )
    assert out["ok"] is True
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Caitlyn"  # the only ranged bench option
    assert "range" in out["reason"].lower()


def test_all_melee_no_ranged_bench_cannot_fix_range_stays():
    # Range gap but no ranged bench champ and range is not variant-addressable.
    out = cv.comp_verdict(_state(_ALL_MELEE_AD, bench=["Garen", "Darius"]))
    assert out["recommendation"] == "stay"
    assert out["swap_to"] in ("", "none", None) or not out["swap_to"]


def test_mono_ad_prefers_ap_variant_over_swap():
    # 3 ranged so range is fine; team is all-AD; my champ has an AP variant.
    team = ["Caitlyn", "Jhin", "Ashe", "Aatrox", "Jax"]  # all AD-lean, 3 ranged
    variants = [
        {"key": "default", "label": "Crit", "summary": "standard AD crit"},
        {"key": "ap-burst", "label": "AP Burst", "summary": "full AP magic damage"},
    ]
    out = cv.comp_verdict(
        _state(team, my_champion="Jhin", bench=["Ahri"], variants=variants)
    )
    # A variant fixes the damage gap with zero risk -> prefer it over the swap.
    assert out["recommendation"] == "variant"
    assert out["variant_to"] == "ap-burst"


def test_mono_ad_swaps_to_ap_bench_when_no_ap_variant():
    team = ["Caitlyn", "Jhin", "Ashe", "Aatrox", "Jax"]  # all AD, 3 ranged
    variants = [{"key": "default", "label": "Crit", "summary": "AD crit"}]
    out = cv.comp_verdict(
        _state(team, my_champion="Jhin", bench=["Soraka", "Darius"], variants=variants)
    )
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Soraka"  # the AP-lean bench option


def test_mono_ad_swap_reason_labels_comp_as_ad():
    # Regression (LGS2 / OQ22): the reason must name the comp's EXCESS type, not
    # the deficit. A mono-AD comp lacks AP, so the deficit is "ap" - but the
    # human-readable label must read "All-AD comp" (the excess), never "All-AP".
    team = ["Caitlyn", "Jhin", "Ashe", "Aatrox", "Jax"]  # all AD-lean, 3 ranged
    variants = [{"key": "default", "label": "Crit", "summary": "AD crit"}]
    out = cv.comp_verdict(
        _state(team, my_champion="Jhin", bench=["Soraka", "Darius"], variants=variants)
    )
    assert out["recommendation"] == "swap"
    assert "All-AD comp" in out["reason"], out["reason"]
    assert "All-AP" not in out["reason"], out["reason"]


def test_mono_ap_swap_reason_labels_comp_as_ap():
    # Mirror regression: a mono-AP comp lacks AD (deficit "ad"); the swap-to-AD
    # reason must read "All-AP comp" (the excess), never the inverted "All-AD".
    team = ["Lux", "Ziggs", "Brand"]  # all AP-lean, 3 ranged, no frontline
    out = cv.comp_verdict(
        _state(team, my_champion="Lux", bench=["Garen"])
    )
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Garen"
    assert "All-AP comp" in out["reason"], out["reason"]
    assert "All-AD" not in out["reason"], out["reason"]


def test_mono_ap_variant_reason_labels_comp_as_ap():
    # The variant-path reason has the same label; a mono-AP comp taking an AD
    # variant must read "All-AP comp ... adds physical damage".
    team = ["Lux", "Ziggs", "Brand"]  # all AP-lean, 3 ranged
    variants = [{"key": "ad-onhit", "label": "On-Hit", "summary": "on-hit AD bruiser"}]
    out = cv.comp_verdict(
        _state(team, my_champion="Lux", bench=[], variants=variants)
    )
    assert out["recommendation"] == "variant"
    assert "All-AP comp" in out["reason"], out["reason"]
    assert "physical" in out["reason"], out["reason"]
    assert "All-AD" not in out["reason"], out["reason"]


def test_no_frontline_swaps_to_tank_bench():
    # 3 ranged, mixed damage, but zero frontline; a tank sits on the bench.
    team = ["Caitlyn", "Ahri", "Ashe", "Lux", "Jhin"]  # 5 ranged, no tank
    out = cv.comp_verdict(
        _state(team, my_champion="Lux", bench=["Malphite", "Brand"])
    )
    assert out["recommendation"] == "swap"
    assert out["swap_to"] == "Malphite"
    assert "frontline" in out["reason"].lower() or "tank" in out["reason"].lower()


@pytest.mark.parametrize("bad", [None, {}, {"my_team": "notalist"}, {"my_team": []},
                                 {"my_team": ["Caitlyn"], "bench": None}])
def test_failsoft_never_raises(bad):
    out = cv.comp_verdict(bad)
    assert isinstance(out, dict)
    assert out["recommendation"] in _OK_RECS


def test_recommendation_targets_are_valid():
    # swap_to must be a bench champ; variant_to must be a provided variant key.
    variants = [{"key": "ap-burst", "label": "AP", "summary": "magic"}]
    out = cv.comp_verdict(
        _state(_ALL_MELEE_AD, my_champion="Aatrox",
               bench=["Caitlyn", "Lux"], variants=variants)
    )
    if out["recommendation"] == "swap":
        assert out["swap_to"] in ("Caitlyn", "Lux")
    if out["recommendation"] == "variant":
        assert out["variant_to"] == "ap-burst"


@pytest.mark.parametrize("ranged,expect", [
    (["Caitlyn", "Ahri", "Lux"], 3),
    (["Aatrox", "Jax"], 0),
    (["Caitlyn", "Aatrox"], 1),
])
def test_factor_ranged_count_is_data_driven(ranged, expect):
    f = cv.compute_factors(ranged)
    assert f["ranged_count"] == expect


def test_factor_damage_lean_known_champs():
    f = cv.compute_factors(["Caitlyn", "Jhin", "Aatrox"])  # all AD
    assert f["ad_count"] >= 3 and f["ap_count"] == 0
    g = cv.compute_factors(["Ahri", "Soraka", "Lux"])  # all AP
    assert g["ap_count"] >= 3 and g["ad_count"] == 0


# --- analyze() wiring: deterministic-first retires the Haiku call ----------
# These prove the live aram_team_analyzer.analyze() entry point no longer needs
# a Claude call for the meaningful case (a full team is present).

def test_analyze_serves_deterministic_without_api_key():
    """With api_key=None the OLD code returned ok=False '(API key missing)'.
    The deterministic-first path now serves a real verdict with NO key - so no
    Haiku call is even possible. This IS the Haiku-elimination proof."""
    from coaches import aram_team_analyzer as ata
    state = _state(_BALANCED, bench=["Malphite", "Soraka"])
    out = ata.analyze(state, api_key=None)
    assert out["ok"] is True
    assert out.get("source") == "deterministic"
    assert out["recommendation"] in _OK_RECS


def test_analyze_deterministic_ignores_spend_gate(monkeypatch):
    """Free deterministic coaching serves even when the Anthropic spend-gate is
    disabled (no spend to gate). The verdict must NOT be '(champ-select coach
    disabled)'."""
    from coaches import aram_team_analyzer as ata

    class _Gate:
        def gate_disabled(self, _name):
            return True

    monkeypatch.setattr("core.cost_tracker.get_tracker", lambda: _Gate())
    state = _state(_ALL_MELEE_AD, my_champion="Aatrox", bench=["Caitlyn", "Lux"])
    out = ata.analyze(state, api_key=None)
    assert out["ok"] is True
    assert out.get("source") == "deterministic"
    assert out["reason"] != "(champ-select coach disabled)"


def test_analyze_failsoft_no_champion():
    from coaches import aram_team_analyzer as ata
    out = ata.analyze({"my_team": []}, api_key=None)
    assert out["ok"] is False
    assert "champion" in out["reason"].lower()
