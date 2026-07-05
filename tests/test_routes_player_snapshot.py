"""Contract tests for /api/player-snapshot and its helpers (player-snapshot card)."""
from dashboard import routes_player_snapshot as rps


def _gpi(strongest, weakest, versat=70.0, consist=40.0):
    axes = [
        {"key": "aggression", "score": 80.0, "scoring": "relative"},
        {"key": "farming", "score": 30.0, "scoring": "relative"},
        {"key": "vision", "score": 50.0, "scoring": "relative"},
        {"key": "objectives", "score": 55.0, "scoring": "relative"},
        {"key": "survival", "score": 45.0, "scoring": "relative"},
        {"key": "tempo", "score": 60.0, "scoring": "relative"},
        {"key": "versatility", "score": versat, "scoring": "absolute"},
        {"key": "consistency", "score": consist, "scoring": "absolute"},
    ]
    return {"axes": axes, "strongest_axis": strongest, "weakest_axis": weakest}


def test_tags_are_three_with_correct_tones_and_words():
    tags = rps._derive_snapshot_tags(_gpi("aggression", "farming"))
    assert len(tags) == 3
    assert tags[0] == {"label": "Aggressive", "tone": "strong"}
    assert tags[2] == {"label": "Weak Farm", "tone": "weak"}
    # neutral slot is the shape axis (versatility 70 > consistency 40) high word.
    assert tags[1] == {"label": "Generalist", "tone": "neutral"}


def test_neutral_slot_uses_consistency_when_it_dominates():
    tags = rps._derive_snapshot_tags(_gpi("tempo", "vision", versat=20.0, consist=85.0))
    assert tags[1] == {"label": "Consistent", "tone": "neutral"}
