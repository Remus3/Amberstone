"""Tests for core/ds_scaling_hint.py - scaling power-curve coach hint generator.

TDD: these tests are written before the implementation and drive the design.
All assertions are on verdict/stage/keys, not brittle exact floats.
"""

from __future__ import annotations

import pytest

from core.ds_scaling_hint import build_scaling_hint

REQUIRED_KEYS = {
    "my_champion",
    "mode",
    "my_early",
    "my_mid",
    "my_late",
    "my_slope",
    "scaling_score",
    "enemy_count",
    "enemy_avg_late",
    "enemy_avg_slope",
    "stage",
    "verdict",
    "hint",
}


# (a) hyperscaler vs early-game enemies -> outscale
def test_hyperscaler_vs_early_bullies_outscale():
    """Kayle (FORM_SPIKE LATE + ITEM_RELIANT) should outscale Draven/Renekton/LeeSin."""
    result = build_scaling_hint(
        "Kayle",
        ["Draven", "Renekton", "LeeSin"],
        mode="SR",
    )
    assert result["verdict"] == "outscale", (
        f"Expected outscale, got {result['verdict']}; "
        f"my_late={result['my_late']}, enemy_avg_late={result['enemy_avg_late']}"
    )
    assert result["hint"], "Hint must be non-empty"


def test_vayne_vs_early_bullies_outscale():
    """Vayne (RATIO_HYPERSCALE LATE) should outscale Draven/Renekton/Pantheon."""
    result = build_scaling_hint(
        "Vayne",
        ["Draven", "Renekton", "Pantheon"],
        mode="SR",
    )
    assert result["verdict"] == "outscale", (
        f"Expected outscale, got {result['verdict']}; "
        f"my_late={result['my_late']}, enemy_avg_late={result['enemy_avg_late']}"
    )
    assert result["hint"], "Hint must be non-empty"


def test_veigar_vs_early_bullies_outscale():
    """Veigar (INFINITE_STACK EARLY) should outscale Draven/Renekton/LeeSin."""
    result = build_scaling_hint(
        "Veigar",
        ["Draven", "Renekton", "LeeSin"],
        mode="SR",
    )
    assert result["verdict"] == "outscale", (
        f"Expected outscale, got {result['verdict']}; "
        f"my_late={result['my_late']}, enemy_avg_late={result['enemy_avg_late']}"
    )
    assert result["hint"], "Hint must be non-empty"


# (b) early-frontload champ vs hyperscalers -> falloff
def test_renekton_vs_hyperscalers_falloff():
    """Renekton (EARLY_FRONTLOAD) should fall off vs Kayle/Veigar/Vayne."""
    result = build_scaling_hint(
        "Renekton",
        ["Kayle", "Veigar", "Vayne"],
        mode="SR",
    )
    assert result["verdict"] == "falloff", (
        f"Expected falloff, got {result['verdict']}; "
        f"my_late={result['my_late']}, enemy_avg_late={result['enemy_avg_late']}"
    )
    assert result["hint"], "Hint must be non-empty"


# (c) game_time_s stage mapping
@pytest.mark.parametrize(
    "game_time_s, expected_stage",
    [
        (300.0, "EARLY"),
        (1000.0, "MID"),
        (2000.0, "LATE"),
        (None, ""),
    ],
)
def test_stage_from_game_time(game_time_s, expected_stage):
    result = build_scaling_hint("Kayle", [], game_time_s=game_time_s)
    assert result["stage"] == expected_stage, (
        f"game_time_s={game_time_s} -> expected stage {expected_stage!r}, "
        f"got {result['stage']!r}"
    )


# (d) blank my_champion -> even, no raise
def test_blank_my_champion_even_no_raise():
    result = build_scaling_hint("", ["Kayle", "Veigar"])
    assert result["verdict"] == "even"
    assert result["hint"] == "Even power curve; win on tempo and lane state."


def test_none_enemy_list_no_raise():
    result = build_scaling_hint("Kayle", None)  # type: ignore[arg-type]
    assert result["verdict"] in ("outscale", "even", "falloff")


# (e) all required keys present
def test_all_required_keys_present():
    result = build_scaling_hint("Vayne", ["Draven", "Renekton"], game_time_s=500.0)
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"Missing keys: {missing}"


def test_all_required_keys_blank_champion():
    result = build_scaling_hint("", [])
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"Missing keys: {missing}"


# extra: enemy_count reflects non-blank entries
def test_enemy_count_correct():
    result = build_scaling_hint("Vayne", ["Draven", "", "Renekton"])
    # blank enemy should be skipped -> count 2
    assert result["enemy_count"] == 2


def test_no_enemies_even_or_outscale():
    """With no enemies, enemy_avg_late=0 so a hyperscaler can outscale."""
    result = build_scaling_hint("Vayne", [])
    assert result["enemy_count"] == 0
    assert result["verdict"] in ("outscale", "even", "falloff")


def test_float_fields_are_rounded():
    """Round-4 fields should be floats."""
    result = build_scaling_hint("Kayle", ["Draven"], game_time_s=300.0)
    for key in ("my_early", "my_mid", "my_late", "my_slope", "scaling_score",
                "enemy_avg_late", "enemy_avg_slope"):
        assert isinstance(result[key], float), f"{key} must be float"


def test_mode_passthrough():
    result = build_scaling_hint("Vayne", ["Draven"], mode="ARAM")
    assert result["mode"] == "ARAM"


def test_my_champion_passthrough():
    result = build_scaling_hint("Kayle", [])
    assert result["my_champion"] == "Kayle"
