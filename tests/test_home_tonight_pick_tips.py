"""Item 281: deterministic Good/Bad/Ugly tips on the Home Tonight's Pick.

The tips are derived purely from the local this_week match-history
aggregate - no Claude/Haiku, no Riot API. These tests pin the contract
of `_home_tonight_pick`'s new `tips` key and the empty-state behavior.
"""
from dashboard.builders_home import _home_tonight_pick


def _entry(**over):
    """A realistic this_week row; override fields per-test."""
    base = {
        "champion": "Lux",
        "games": 5,
        "avg_kda": 3.2,
        "kills": 20,
        "deaths": 8,
        "assists": 30,
        "cs_total": 400,
        "cs_per_min": 6.5,
        "best_grade": "A",
        "modes": ["ARAM"],
    }
    base.update(over)
    return base


def test_tips_structure():
    pick = _home_tonight_pick([_entry()])
    assert pick is not None
    tips = pick["tips"]
    assert isinstance(tips, dict)
    assert set(tips.keys()) == {"good", "bad", "ugly"}
    for v in tips.values():
        assert isinstance(v, str)
        assert v != ""


def test_empty_state_returns_none():
    assert _home_tonight_pick([]) is None


def test_tips_are_ascii():
    pick = _home_tonight_pick([_entry()])
    for v in pick["tips"].values():
        assert all(ord(c) < 128 for c in v), repr(v)


def test_small_sample_ugly_branch():
    pick = _home_tonight_pick([_entry(games=1)])
    assert "Small sample" in pick["tips"]["ugly"]


def test_small_sample_suppresses_good_and_bad():
    """R30 design review: 1-2 games is too small a sample to present
    per-game rollups - a single strong game reads as great avg KDA AND
    terrible deaths-per-game at once (the contradiction the operator flagged
    live: '3.7 avg KDA' next to '10 deaths per game' over 1 game). Suppress
    Good + Bad to empty so Tonight's Pick shows only the honest caveat; the
    pick `reason` line already carries the KDA justification."""
    pick = _home_tonight_pick([_entry(games=1, avg_kda=3.7, deaths=10)])
    tips = pick["tips"]
    assert tips["good"] == "", tips
    assert tips["bad"] == "", tips
    assert "Small sample" in tips["ugly"], tips
    # games=2 is still a small sample.
    pick2 = _home_tonight_pick([_entry(games=2, avg_kda=4.0, deaths=6)])
    assert pick2["tips"]["good"] == "" and pick2["tips"]["bad"] == ""


def test_full_sample_keeps_good_and_bad():
    """>=3 games: the per-game rollups are reliable enough to surface."""
    pick = _home_tonight_pick([_entry(games=4, avg_kda=4.1, deaths=12)])
    tips = pick["tips"]
    assert "avg KDA" in tips["good"], tips
    assert "deaths per game" in tips["bad"], tips
