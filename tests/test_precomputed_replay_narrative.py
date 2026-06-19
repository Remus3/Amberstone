"""Tests for core.precomputed_replay_narrative.build_narrative.

The deterministic replay-narrative substrate builds a summary + impact-ranked
key-moments list + rubric-component lessons from a rewind_history.db blob (the
shape coaches/replay_coach._load_match returns). These tests pin: expected
output keys, impact ordering, and fail-soft behaviour on empty/missing fields.
"""

from __future__ import annotations

from core.precomputed_replay_narrative import build_narrative


def _synthetic_blob():
    """A minimal but complete rewind_history.db blob for the operator's match.

    Operator = participant_id 1, champion_id 99 (Lux), team 100, MID. Built so
    the timeline has a clear impact ordering: a Baron > a building > a plain
    enemy kill > a turret plate.
    """
    match = {
        "match_id": "NA1_TEST_1",
        "game_mode": "CLASSIC",
        "patch": "16.12",
        "game_duration_s": 1800,  # 30 min
        "tracked_champion_id": 99,
        "tracked_champion_name": "Lux",
        "tracked_team_id": 100,
        "tracked_win": 1,
        "tracked_kills": 8,
        "tracked_deaths": 3,
        "tracked_assists": 12,
        "tracked_lane": "MIDDLE",
    }
    participants = [
        {
            "participant_id": 1,
            "team_id": 100,
            "puuid": "PUUID_OP",
            "champion_id": 99,
            "champion_name": "Lux",
            "team_position": "MIDDLE",
            "kills": 8,
            "deaths": 3,
            "assists": 12,
            "total_minions_killed": 200,
            "neutral_minions_killed": 7,
            "vision_score": 30,
            "total_damage_dealt_to_champs": 28000,
            "dragon_kills": 1,
            "baron_kills": 1,
            "objectives_stolen": 0,
            "objectives_stolen_assists": 0,
            "first_tower_kill": 1,
            "first_tower_assist": 0,
            "turret_takedowns": 4,
            "challenges_json": "{}",
        },
        {
            "participant_id": 2,
            "team_id": 100,
            "puuid": "PUUID_ALLY",
            "champion_id": 64,
            "champion_name": "LeeSin",
            "team_position": "JUNGLE",
            "kills": 4,
            "deaths": 5,
            "assists": 10,
            "total_minions_killed": 50,
            "neutral_minions_killed": 120,
            "vision_score": 25,
            "total_damage_dealt_to_champs": 15000,
            "dragon_kills": 2,
            "baron_kills": 0,
            "objectives_stolen": 0,
            "objectives_stolen_assists": 0,
            "first_tower_kill": 0,
            "first_tower_assist": 1,
            "turret_takedowns": 2,
            "challenges_json": "{}",
        },
    ]
    events = [
        {
            "event_type": "TURRET_PLATE_DESTROYED",
            "timestamp_ms": 600000,
            "participant_id": 1,
        },
        {
            "event_type": "CHAMPION_KILL",
            "timestamp_ms": 720000,
            "killer_id": 1,
            "victim_id": 6,
            "bounty": 300,
            "shutdown_bounty": 0,
        },
        {
            "event_type": "BUILDING_KILL",
            "timestamp_ms": 1200000,
            "building_type": "TOWER_BUILDING",
            "tower_type": "INNER_TURRET",
            "killer_id": 2,
        },
        {
            "event_type": "ELITE_MONSTER_KILL",
            "timestamp_ms": 1500000,
            "monster_type": "BARON_NASHOR",
            "killer_id": 1,
        },
        # A non-moment event that must be filtered out of key_moments.
        {
            "event_type": "LEVEL_UP",
            "timestamp_ms": 60000,
            "participant_id": 1,
        },
    ]
    return {"match": match, "participants": participants, "events": events}


def test_returns_expected_top_level_keys():
    result = build_narrative(_synthetic_blob())
    assert set(result.keys()) == {"ok", "summary", "key_moments", "lessons", "grade"}
    assert result["ok"] is True
    assert isinstance(result["summary"], str) and result["summary"]
    assert isinstance(result["key_moments"], list)
    assert isinstance(result["lessons"], list)
    assert isinstance(result["grade"], dict)


def test_summary_mentions_champion_result_and_grade():
    result = build_narrative(_synthetic_blob())
    summary = result["summary"]
    assert "Lux" in summary
    assert "WIN" in summary
    assert "30 min" in summary
    assert "8/3/12" in summary
    # The rubric grade bucket is one of the documented buckets.
    assert any(b in summary for b in ("S+", "S", "A", "B", "C", "D"))


def test_key_moments_impact_ordering():
    result = build_narrative(_synthetic_blob())
    moments = result["key_moments"]
    # The LEVEL_UP event must be filtered out (4 candidate moments remain).
    assert len(moments) == 4
    # Each moment carries the documented keys.
    for m in moments:
        assert set(m.keys()) == {"clock", "event_type", "impact", "text"}
    # Impact is sorted strictly non-increasing.
    impacts = [m["impact"] for m in moments]
    assert impacts == sorted(impacts, reverse=True)
    # The Baron (operator killer + epic monster) is the highest-impact moment.
    assert moments[0]["event_type"] == "ELITE_MONSTER_KILL"
    assert "Baron" in moments[0]["text"]
    # The turret plate (lowest base impact, no operator involvement credit) is
    # last.
    assert moments[-1]["event_type"] == "TURRET_PLATE_DESTROYED"


def test_lessons_are_strings_and_present():
    result = build_narrative(_synthetic_blob())
    lessons = result["lessons"]
    assert lessons  # non-empty: rubric components yield at least one lesson
    assert all(isinstance(s, str) and s for s in lessons)


def test_grade_has_rubric_shape():
    result = build_narrative(_synthetic_blob())
    grade = result["grade"]
    assert set(grade.keys()) == {
        "role",
        "total_score",
        "components",
        "percentile_grade",
    }
    assert grade["role"] == "MID"
    assert 0.0 <= grade["total_score"] <= 100.0


def test_failsoft_none_blob():
    result = build_narrative(None)
    assert result["ok"] is False
    assert result["summary"] == ""
    assert result["key_moments"] == []
    assert result["lessons"] == []
    assert result["grade"] == {}


def test_failsoft_empty_dict():
    result = build_narrative({})
    assert result["ok"] is False
    assert result["key_moments"] == []


def test_failsoft_missing_match():
    result = build_narrative({"participants": [], "events": []})
    assert result["ok"] is False
    assert result["summary"] == ""


def test_failsoft_missing_participants_and_events():
    # Only a matches row - falls back to tracked_* fields, still produces a
    # summary, with no key moments.
    blob = {
        "match": {
            "match_id": "NA1_TEST_2",
            "game_mode": "CLASSIC",
            "patch": "16.12",
            "game_duration_s": 900,
            "tracked_champion_name": "Ahri",
            "tracked_win": 0,
            "tracked_kills": 2,
            "tracked_deaths": 7,
            "tracked_assists": 3,
            "tracked_lane": "MIDDLE",
        }
    }
    result = build_narrative(blob)
    assert result["ok"] is True
    assert "Ahri" in result["summary"]
    assert "LOSS" in result["summary"]
    assert result["key_moments"] == []


def test_failsoft_malformed_event_rows_do_not_raise():
    blob = _synthetic_blob()
    # Inject malformed event rows; build_narrative must skip them, not raise.
    blob["events"].extend([None, "garbage", {"event_type": None}, 42])
    result = build_narrative(blob)
    assert result["ok"] is True
    # Still exactly the 4 valid candidate moments.
    assert len(result["key_moments"]) == 4


def test_deterministic_repeat_calls_match():
    blob = _synthetic_blob()
    first = build_narrative(blob)
    second = build_narrative(blob)
    assert first == second
