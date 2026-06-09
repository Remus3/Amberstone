"""HZ-C1 - core.precomputed_laning_coach reader characterization tests.

Pins the live-state -> table-key mapping, the A/B choice shaping from one
precomputed laning cell, enemy coverage resolution, and the fail-soft empties.
Pure - operates on a synthetic in-memory payload (no table file, no network).
"""
from __future__ import annotations

import pytest

from core.coach_choices import CoachChoice
from core import precomputed_laning_coach as plc


# --------------------------------------------------------------------------- #
# Synthetic HZ-A payload (matches laning_scenarios/v2 leaf shape)
# --------------------------------------------------------------------------- #
def _cell(verdict, swing, recall, *, my_rm=0.3, en_rm=0.6, spike="first_item",
          gold=1300.0):
    return {
        "verdict": verdict,
        "net_swing": swing,
        "pct_my_removed": my_rm,
        "pct_enemy_removed": en_rm,
        "my_can_full_combo": True,
        "sequence": ["Q", "W", "E", "R"],
        "manaless": False,
        "economy": {
            "recall": recall,
            "next_spike": spike,
            "spike_eta_s": 30.0,
            "gold_at_band": gold,
        },
    }


def _payload():
    return {
        "schema": "laning_scenarios/v2",
        "scenarios": {
            "Annie": {
                "Caitlyn": {
                    "L6": {
                        "full": {"all_up": _cell("all_in", 0.25, "recall_now")},
                        "low": {"all_up": _cell("back_off", -0.3, "hold")},
                    },
                    "L11": {
                        "full": {"no_ult": _cell("even", 0.0, "back_soon")},
                    },
                },
            },
        },
    }


# --------------------------------------------------------------------------- #
# band_for_level
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("level,band", [
    (1, "L2"), (2, "L2"), (3, "L2"),
    (4, "L6"), (6, "L6"), (8, "L6"),
    (9, "L11"), (11, "L11"), (13, "L11"),
    (14, "L16"), (16, "L16"), (18, "L16"),
    (None, "L2"), ("garbage", "L2"),
])
def test_band_for_level(level, band):
    assert plc.band_for_level(level) == band


# --------------------------------------------------------------------------- #
# mana_state_for / cd_state_for
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("frac,state", [
    (None, "full"), (1.0, "full"), (0.6, "full"), (0.5, "full"),
    (0.49, "low"), (0.0, "low"), ("nope", "full"),
])
def test_mana_state_for(frac, state):
    assert plc.mana_state_for(frac) == state


@pytest.mark.parametrize("ult,state", [
    (None, "all_up"), (True, "all_up"), (False, "no_ult"),
])
def test_cd_state_for(ult, state):
    assert plc.cd_state_for(ult) == state


# --------------------------------------------------------------------------- #
# precomputed_choices - covered cell shapes 2 A/B choices
# --------------------------------------------------------------------------- #
def test_covered_cell_returns_two_choices():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert len(out) == 2
    assert all(isinstance(c, CoachChoice) for c in out)
    assert out[0].key == "A" and out[1].key == "B"
    assert all(c.source_tag == plc.SOURCE_TAG for c in out)


def test_all_in_verdict_labels_combat_a():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert "All-in" in out[0].label
    assert "Caitlyn" in out[0].label
    # net_swing 0.25 -> high confidence band
    assert out[0].confidence == "high"
    # combat outcome carries the DS-backed swing + removal percents
    assert "net swing" in out[0].expected_outcome
    assert "60%" in out[0].expected_outcome  # pct_enemy_removed 0.6


def test_recall_now_economy_drives_choice_b():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert out[1].label == "Recall now"


def test_next_item_folds_into_recall_outcome():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(), next_item=("Luden's Companion", 2900),
    )
    assert "Luden's Companion" in out[1].expected_outcome
    assert "2900" in out[1].expected_outcome


def test_low_mana_routes_to_low_cell():
    # mana_fraction 0.2 -> "low" state -> back_off verdict cell.
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=0.2, ult_up=True,
        payload=_payload(),
    )
    assert "Back off" in out[0].label
    # hold recall (not recall_now/back_soon) -> B is the prudent combat alt
    assert out[1].label == "Force a short trade"


def test_no_ult_routes_to_no_ult_cell():
    # L11 only has a no_ult cell; ult_up=False selects it.
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 11, mana_fraction=1.0, ult_up=False,
        payload=_payload(),
    )
    assert len(out) == 2
    assert out[1].label == "Back soon"  # economy back_soon


# --------------------------------------------------------------------------- #
# fail-soft empties
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("champ,enemy,level", [
    ("Annie", "Zed", 6),       # enemy not in table
    ("Yasuo", "Caitlyn", 6),   # champ not in table
    ("", "Caitlyn", 6),        # empty champ
    ("Annie", "", 6),          # empty enemy
])
def test_uncovered_or_empty_returns_empty(champ, enemy, level):
    out = plc.precomputed_choices(
        champ, enemy, level, payload=_payload(),
    )
    assert out == []


def test_missing_band_cell_returns_empty():
    # L16 band is absent for Annie/Caitlyn -> no cell -> [].
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 16, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert out == []


# --------------------------------------------------------------------------- #
# resolve_enemy - coverage-first lane-opponent pick
# --------------------------------------------------------------------------- #
def test_resolve_enemy_first_covered():
    enemy = plc.resolve_enemy(
        "Annie", ["Zed", "Caitlyn", "Lux"], payload=_payload(),
    )
    assert enemy == "Caitlyn"


def test_resolve_enemy_none_when_uncovered():
    assert plc.resolve_enemy(
        "Annie", ["Zed", "Yorick"], payload=_payload(),
    ) is None


def test_resolve_enemy_empty_inputs():
    assert plc.resolve_enemy("Annie", [], payload=_payload()) is None
    assert plc.resolve_enemy("", ["Caitlyn"], payload=_payload()) is None
