"""Characterization: operator gold-share from the post-game roster.

Pins core.carry_share.gold_share_pct - the DISPLAY-only carry-efficiency
metric that fills the gap flagged in the R2 competitor-lift triage
(gold_share had 0 producers repo-wide; kill_participation already existed).
Pure read of the enriched last-match roster (is_me / team_id / gold), no
match_metrics grade change.
"""
from __future__ import annotations

from core.carry_share import gold_share_pct


def _roster():
    # Operator on team 100 with 10k of a 40k team total; enemies on team 200.
    return [
        {"is_me": True,  "team_id": 100, "gold": 10000},
        {"is_me": False, "team_id": 100, "gold": 8000},
        {"is_me": False, "team_id": 100, "gold": 7000},
        {"is_me": False, "team_id": 100, "gold": 9000},
        {"is_me": False, "team_id": 100, "gold": 6000},
        {"is_me": False, "team_id": 200, "gold": 99999},
    ]


def test_operator_share_of_team_gold():
    assert gold_share_pct(_roster()) == 25.0  # 10000 / 40000


def test_enemy_gold_excluded():
    r = _roster()
    r[-1]["gold"] = 500000  # enemy spikes; operator share must not move
    assert gold_share_pct(r) == 25.0


def test_no_operator_row_returns_none():
    assert gold_share_pct([{"is_me": False, "team_id": 100, "gold": 5000}]) is None


def test_zero_team_gold_returns_none():
    r = [{"is_me": True, "team_id": 100, "gold": 0},
         {"is_me": False, "team_id": 100, "gold": 0}]
    assert gold_share_pct(r) is None


def test_solo_team_is_full_share():
    assert gold_share_pct([{"is_me": True, "team_id": 100, "gold": 12345}]) == 100.0


def test_empty_and_none_roster():
    assert gold_share_pct([]) is None
    assert gold_share_pct(None) is None


def test_missing_gold_keys_default_zero():
    r = [{"is_me": True, "team_id": 100, "gold": 5000},
         {"is_me": False, "team_id": 100}]  # teammate missing gold -> 0
    assert gold_share_pct(r) == 100.0


def test_rounding_one_decimal():
    r = [{"is_me": True, "team_id": 100, "gold": 1000},
         {"is_me": False, "team_id": 100, "gold": 2000}]  # 1000/3000 = 33.33
    assert gold_share_pct(r) == 33.3
