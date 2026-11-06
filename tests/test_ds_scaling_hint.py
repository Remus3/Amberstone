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


# ---------------------------------------------------------------------------
# S144-T true-audit (cycle 157): junk input never raises, an unknown curve is
# never read as a verdict, and an empty comparison set is never an "outscale".
# ---------------------------------------------------------------------------

EVEN_HINT = "Even power curve; win on tempo and lane state."


@pytest.mark.parametrize("junk", [5, 3.5, True, ["Kayle"], {"k": 1}, b"Kayle", object()])
def test_non_string_my_champion_never_raises(junk):
    result = build_scaling_hint(junk, ["Draven"])  # type: ignore[arg-type]
    assert result["my_champion"] == ""
    assert result["verdict"] == "even"
    assert result["hint"] == EVEN_HINT
    assert not REQUIRED_KEYS - result.keys()


@pytest.mark.parametrize("junk", [5, None, ["Vayne"], {"k": 1}, b"Vayne", 0.0])
def test_non_string_enemy_entry_is_skipped_not_raised(junk):
    result = build_scaling_hint("Vayne", ["Draven", junk, "Renekton"])  # type: ignore[list-item]
    assert result["enemy_count"] == 2


def test_bare_string_enemy_list_is_one_enemy_not_its_letters():
    result = build_scaling_hint("Kayle", "Draven")  # type: ignore[arg-type]
    assert result["enemy_count"] == 1
    assert result == build_scaling_hint("Kayle", ["Draven"]) | {"enemy_count": 1}


@pytest.mark.parametrize("junk", [5, {"Draven": 1}, object()])
def test_non_list_enemy_container_reads_as_no_enemies(junk):
    result = build_scaling_hint("Kayle", junk)  # type: ignore[arg-type]
    assert result["enemy_count"] == 0


def test_tuple_enemy_list_is_accepted():
    assert build_scaling_hint("Kayle", ("Draven",))["enemy_count"] == 1  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "game_time_s",
    ["300", float("nan"), float("inf"), float("-inf"), -5.0, True, False, [300], object()],
)
def test_junk_game_time_is_unknown_stage_never_raises(game_time_s):
    result = build_scaling_hint("Kayle", [], game_time_s=game_time_s)  # type: ignore[arg-type]
    assert result["stage"] == ""


@pytest.mark.parametrize(
    "game_time_s, expected",
    [(0, "EARLY"), (839.9, "EARLY"), (840, "MID"), (1500, "LATE"), (10**400, "LATE")],
)
def test_stage_boundaries_and_int_seconds(game_time_s, expected):
    assert build_scaling_hint("Kayle", [], game_time_s=game_time_s)["stage"] == expected


@pytest.mark.parametrize("junk", [5, None, "", "   ", ["SR"]])
def test_junk_or_blank_mode_falls_back_to_sr(junk):
    assert build_scaling_hint("Kayle", [], mode=junk)["mode"] == "SR"  # type: ignore[arg-type]


def test_mode_is_stripped():
    assert build_scaling_hint("Kayle", [], mode=" ARAM ")["mode"] == "ARAM"


def test_padded_champion_ids_are_stripped():
    padded = build_scaling_hint(" Kayle ", [" Draven ", "Renekton\t"])
    clean = build_scaling_hint("Kayle", ["Draven", "Renekton"])
    assert padded == clean
    assert padded["my_champion"] == "Kayle"


def test_no_enemies_is_never_a_decisive_verdict():
    """An empty comparison set is not an outscale ("late 0.76 vs 0.00")."""
    result = build_scaling_hint("Vayne", [])
    assert result["my_late"] > 0.4  # Vayne alone would clear SCALING_MARGIN vs 0
    assert result["verdict"] == "even"
    assert result["hint"] == EVEN_HINT


def test_unknown_my_champion_is_not_a_falloff():
    """A registry miss has no curve; it must not read as "You fall off late (0.00 vs ...)"."""
    result = build_scaling_hint("NotAChampion", ["Kayle", "Vayne"])
    assert result["verdict"] == "even"
    assert result["hint"] == EVEN_HINT


def test_unknown_enemy_does_not_drag_the_average_down():
    """A registry miss is excluded from the enemy average, not averaged in as zero."""
    with_unknown = build_scaling_hint("Vayne", ["NotAChampion", "Unknown", "Draven"])
    known_only = build_scaling_hint("Vayne", ["Draven"])
    assert with_unknown["enemy_avg_late"] == known_only["enemy_avg_late"]
    assert with_unknown["enemy_avg_slope"] == known_only["enemy_avg_slope"]
    assert with_unknown["verdict"] == known_only["verdict"]
    assert with_unknown["enemy_count"] == 1
    assert with_unknown["enemy_unknown"] == 2
    assert known_only["enemy_unknown"] == 0


def test_only_unknown_enemies_is_even():
    result = build_scaling_hint("Vayne", ["NotAChampion", "Unknown"])
    assert result["enemy_count"] == 0
    assert result["enemy_unknown"] == 2
    assert result["verdict"] == "even"


def test_known_verdicts_unchanged_by_hardening():
    assert build_scaling_hint("Kayle", ["Draven", "Renekton", "LeeSin"])["verdict"] == "outscale"
    assert build_scaling_hint("Renekton", ["Kayle", "Veigar", "Vayne"])["verdict"] == "falloff"


def test_result_is_json_serialisable_on_junk():
    import json

    result = build_scaling_hint(object(), [object(), "Draven"], mode=object(), game_time_s=object())  # type: ignore[arg-type]
    json.dumps(result)


def test_module_is_ascii_and_lf():
    from pathlib import Path

    import core.ds_scaling_hint as mod

    raw = Path(mod.__file__).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw
