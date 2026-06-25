"""Tests for core.precomputed_anvil_advisor - the deterministic substrate that
ranks each offered item-anvil choice against recompute_arena_build's ideal path.

The substrate never serves anything live (the anvil_advice field stays Haiku);
these tests pin the rank-against-ideal-path contract + the fail-soft behavior
when the rule-based build DB has nothing for the champion. recompute_arena_build
is monkeypatched to a known return so the test is data-independent + hermetic.
"""
from __future__ import annotations

import pytest

from core import precomputed_anvil_advisor as adv


@pytest.fixture
def _patch_recompute(monkeypatch):
    """Return a helper that pins recompute_arena_build to a fixed ideal path."""
    def _install(path):
        monkeypatch.setattr(adv, "recompute_arena_build", lambda *a, **k: list(path))
    return _install


def test_offered_item_early_in_ideal_path(_patch_recompute):
    _patch_recompute(["Kraken Slayer", "Infinity Edge", "Bloodthirster"])
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=["Bloodthirster", "Kraken Slayer"],
        alive_opponents=[],
        hp_pct=100,
    )
    # Kraken Slayer ranks #1 in the ideal path, so it wins over Bloodthirster (#3).
    assert out["take"] == "Kraken Slayer"
    assert out["take_rank"] == 1
    assert out["conf"] == "ok"
    assert out["n_matches"] == 2
    assert out["ideal_path"] == ["Kraken Slayer", "Infinity Edge", "Bloodthirster"]


def test_ranked_block_carries_per_choice_rank(_patch_recompute):
    _patch_recompute(["Kraken Slayer", "Infinity Edge", "Bloodthirster"])
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=["Bloodthirster", "Kraken Slayer"],
        alive_opponents=[],
        hp_pct=100,
    )
    by_name = {r["name"]: r for r in out["ranked"]}
    assert by_name["Kraken Slayer"]["rank"] == 1
    assert by_name["Kraken Slayer"]["in_ideal_path"] is True
    assert by_name["Bloodthirster"]["rank"] == 3
    assert by_name["Bloodthirster"]["in_ideal_path"] is True


def test_no_offered_item_in_ideal_path(_patch_recompute):
    _patch_recompute(["Kraken Slayer", "Infinity Edge"])
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=["Warmog's Armor", "Sunfire Aegis"],
        alive_opponents=[],
        hp_pct=100,
    )
    assert out["take"] is None
    assert out["take_rank"] is None
    assert out["n_matches"] == 0
    assert out["conf"] == "low"
    # Every offered choice still appears, just with no rank.
    assert {r["name"] for r in out["ranked"]} == {"Warmog's Armor", "Sunfire Aegis"}
    assert all(r["rank"] is None and r["in_ideal_path"] is False for r in out["ranked"])


def test_champ_not_in_build_db_fail_soft(_patch_recompute):
    # recompute returns [] (champ absent / all owned) -> low-conf, never raises.
    _patch_recompute([])
    out = adv.compute_anvil_pick(
        champion="NotARealChamp",
        current_items=[],
        anvil_choices=["Kraken Slayer", "Bloodthirster"],
        alive_opponents=[],
        hp_pct=100,
    )
    assert out["take"] is None
    assert out["n_matches"] == 0
    assert out["conf"] == "low"
    assert out["ideal_path"] == []
    assert {r["name"] for r in out["ranked"]} == {"Kraken Slayer", "Bloodthirster"}


def test_recompute_raises_fail_soft(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("build DB exploded")
    monkeypatch.setattr(adv, "recompute_arena_build", _boom)
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=["Kraken Slayer"],
        alive_opponents=[],
        hp_pct=100,
    )
    assert out["take"] is None
    assert out["conf"] == "low"
    assert out["ideal_path"] == []
    assert [r["name"] for r in out["ranked"]] == ["Kraken Slayer"]


def test_name_variant_matching_tolerates_display_forms(_patch_recompute):
    # Ideal path uses the bare canonical name; the offered choice carries
    # punctuation / spacing variance. Normalized matching must still bind them.
    _patch_recompute(["Kraken Slayer", "Infinity Edge"])
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=["kraken  slayer!"],
        alive_opponents=[],
        hp_pct=100,
    )
    assert out["take"] == "kraken  slayer!"
    assert out["take_rank"] == 1
    assert out["n_matches"] == 1
    assert out["conf"] == "ok"


def test_empty_anvil_choices_fail_soft(_patch_recompute):
    _patch_recompute(["Kraken Slayer"])
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=[],
        alive_opponents=[],
        hp_pct=100,
    )
    assert out["take"] is None
    assert out["n_matches"] == 0
    assert out["conf"] == "low"
    assert out["ranked"] == []


def test_earliest_rank_wins_on_ties(_patch_recompute):
    # Two offered items both in the path; the one with the lower (earlier)
    # rank must be the take regardless of offer order.
    _patch_recompute(["A Item", "B Item", "C Item"])
    out = adv.compute_anvil_pick(
        champion="Jinx",
        current_items=[],
        anvil_choices=["C Item", "A Item"],
        alive_opponents=[],
        hp_pct=100,
    )
    assert out["take"] == "A Item"
    assert out["take_rank"] == 1
