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


# --- CHAMPION_SPECIAL_KILL (first blood / multikill / ace) -------------------
#
# Shape verified live against rewind_history.db (63505 rows): the type lives in
# raw_json as {"killType": ...}, KILL_MULTI additionally carries
# "multiKillLength", killer_id is populated and victim_id is always NULL - the
# companion CHAMPION_KILL row at the same timestamp carries the victim. So a
# special-kill line names the killer and the feat, never a victim.


def _special_kill_blob(raw_json, killer_id=1, timestamp_ms=800000):
    """The synthetic blob plus ONE CHAMPION_SPECIAL_KILL row.

    raw_json is passed through verbatim so the tests can cover the str form the
    db actually stores, the already-parsed dict form, and malformed values.
    """
    blob = _synthetic_blob()
    blob["events"].append(
        {
            "event_type": "CHAMPION_SPECIAL_KILL",
            "timestamp_ms": timestamp_ms,
            "killer_id": killer_id,
            "victim_id": None,
            "raw_json": raw_json,
        }
    )
    return blob


def _only_special(result):
    return [m for m in result["key_moments"]
            if m["event_type"] == "CHAMPION_SPECIAL_KILL"]


def test_special_kill_is_a_candidate_moment():
    result = build_narrative(_special_kill_blob('{"killType": "KILL_FIRST_BLOOD"}'))
    assert len(_only_special(result)) == 1


def test_first_blood_text_names_the_feat():
    # Killer is the operator (participant 1).
    result = build_narrative(_special_kill_blob('{"killType": "KILL_FIRST_BLOOD"}'))
    text = _only_special(result)[0]["text"]
    assert "First Blood" in text
    assert "you" in text


def test_first_blood_text_names_another_champion():
    # participant 2 is LeeSin in the synthetic blob.
    result = build_narrative(
        _special_kill_blob('{"killType": "KILL_FIRST_BLOOD"}', killer_id=2))
    text = _only_special(result)[0]["text"]
    assert "First Blood" in text
    assert "LeeSin" in text


def test_multikill_names_scale_with_length():
    expected = {2: "Double Kill", 3: "Triple Kill",
                4: "Quadra Kill", 5: "Penta Kill"}
    for length, name in expected.items():
        blob = _special_kill_blob(
            f'{{"killType": "KILL_MULTI", "multiKillLength": {length}}}',
            killer_id=2)
        text = _only_special(build_narrative(blob))[0]["text"]
        assert name in text, f"length {length} did not render {name}: {text}"
        assert "LeeSin" in text


def test_multikill_impact_increases_with_length():
    impacts = []
    for length in (2, 3, 4, 5):
        blob = _special_kill_blob(
            f'{{"killType": "KILL_MULTI", "multiKillLength": {length}}}',
            killer_id=2)
        impacts.append(_only_special(build_narrative(blob))[0]["impact"])
    assert impacts == sorted(impacts)
    assert len(set(impacts)) == 4


def test_penta_kill_clears_the_epic_monster_floor():
    # A pentakill is the headline of any game it happens in and must clear the
    # 60-point epic-monster base. It does NOT have to outrank the fixture's
    # Baron, which the operator took: operator credit is worth +25 and this
    # narrative is deliberately operator-centric, so an objective the operator
    # personally secured outranking someone else's penta is correct.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 5}', killer_id=2)
    penta = _only_special(build_narrative(blob))[0]
    assert penta["impact"] > 60.0
    assert "Penta Kill" in penta["text"]


def test_penta_kill_outranks_an_uncredited_baron():
    # Same comparison with the operator credit removed from both sides: the
    # penta must come out on top.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 5}', killer_id=2)
    for ev in blob["events"]:
        if ev.get("event_type") == "ELITE_MONSTER_KILL":
            ev["killer_id"] = 2
    result = build_narrative(blob)
    assert result["key_moments"][0]["event_type"] == "CHAMPION_SPECIAL_KILL"
    assert "Penta Kill" in result["key_moments"][0]["text"]


def test_double_kill_does_not_outrank_baron():
    # The other side of the scale: a double kill is a moment, not the headline.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 2}', killer_id=2)
    result = build_narrative(blob)
    assert result["key_moments"][0]["event_type"] == "ELITE_MONSTER_KILL"


def test_ace_text_and_rank():
    blob = _special_kill_blob('{"killType": "KILL_ACE"}', killer_id=2)
    moments = _only_special(build_narrative(blob))
    assert len(moments) == 1
    assert "ace" in moments[0]["text"].lower()


def _ace_row(timestamp_ms, killer_id=2):
    return {
        "event_type": "CHAMPION_SPECIAL_KILL",
        "timestamp_ms": timestamp_ms,
        "killer_id": killer_id,
        "victim_id": None,
        "raw_json": '{"killType": "KILL_ACE"}',
    }


def test_ace_suppressed_when_it_coincides_with_a_multikill():
    # A multikill that also aces emits both rows at the SAME timestamp with the
    # same killer, and rendering both describes one feat twice. Measured over
    # the 63505 special-kill rows in rewind_history.db, this is sharply
    # bimodal: 5202 aces sit at EXACTLY 0 ms from a same-killer multikill and
    # every other ace is 6 s or more away. So coincidence is exact-timestamp,
    # not a window - the multikill is the more specific description and wins.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 5}',
        killer_id=2, timestamp_ms=900000)
    blob["events"].append(_ace_row(900000, killer_id=2))
    texts = [m["text"] for m in _only_special(build_narrative(blob))]
    assert len(texts) == 1
    assert "Penta Kill" in texts[0]


def test_standalone_ace_survives():
    blob = _special_kill_blob('{"killType": "KILL_ACE"}', killer_id=2)
    assert len(_only_special(build_narrative(blob))) == 1


def test_ace_at_a_different_instant_is_not_suppressed():
    # The far mode of the measured distribution: a later ace by the same player
    # is a separate feat.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 2}',
        killer_id=2, timestamp_ms=900000)
    blob["events"].append(_ace_row(1000000, killer_id=2))
    assert len(_only_special(build_narrative(blob))) == 2


def test_ace_by_a_different_killer_is_not_suppressed():
    # One player multikills while a team-mate lands the ace: two feats.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 2}',
        killer_id=2, timestamp_ms=900000)
    blob["events"].append(_ace_row(900000, killer_id=1))
    assert len(_only_special(build_narrative(blob))) == 2


def test_first_blood_and_multikill_at_same_instant_both_survive():
    # A first-blood double kill puts KILL_FIRST_BLOOD and KILL_MULTI on the
    # same timestamp with the same killer - 2 real occurrences in the corpus.
    # These are two genuinely different facts, so unlike the ace case both are
    # kept, and the dedup key must carry the type or one silently eats the
    # other.
    blob = _special_kill_blob(
        '{"killType": "KILL_MULTI", "multiKillLength": 2}',
        killer_id=2, timestamp_ms=900000)
    blob["events"].append(
        {
            "event_type": "CHAMPION_SPECIAL_KILL",
            "timestamp_ms": 900000,
            "killer_id": 2,
            "victim_id": None,
            "raw_json": '{"killType": "KILL_FIRST_BLOOD"}',
        }
    )
    texts = [m["text"] for m in _only_special(build_narrative(blob))]
    assert len(texts) == 2
    assert any("Double Kill" in t for t in texts)
    assert any("First Blood" in t for t in texts)


def test_multikill_streak_collapses_to_its_terminal_rung():
    # Riot emits one row per RUNG as a streak grows, so a pentakill arrives as
    # double -> triple -> quadra -> penta, four rows for one feat. Verified on
    # NA1_5094273204: a 14:42 Quadra and a 14:46 Penta by the same player are
    # the same streak. Only the terminal rung is a moment.
    blob = _synthetic_blob()
    for offset, length in ((0, 2), (3000, 3), (7000, 4), (11000, 5)):
        blob["events"].append(
            {
                "event_type": "CHAMPION_SPECIAL_KILL",
                "timestamp_ms": 800000 + offset,
                "killer_id": 2,
                "victim_id": None,
                "raw_json":
                    f'{{"killType": "KILL_MULTI", "multiKillLength": {length}}}',
            }
        )
    texts = [m["text"] for m in _only_special(build_narrative(blob))]
    assert len(texts) == 1
    assert "Penta Kill" in texts[0]


def test_separate_multikill_streaks_both_survive():
    # Two Double Kills minutes apart are two feats, not one streak.
    blob = _synthetic_blob()
    for ts in (400000, 900000):
        blob["events"].append(
            {
                "event_type": "CHAMPION_SPECIAL_KILL",
                "timestamp_ms": ts,
                "killer_id": 2,
                "victim_id": None,
                "raw_json": '{"killType": "KILL_MULTI", "multiKillLength": 2}',
            }
        )
    assert len(_only_special(build_narrative(blob))) == 2


def test_concurrent_streaks_by_different_players_do_not_collapse():
    # Two players each getting a Double Kill in the same teamfight are two
    # feats. Collapsing must be per-killer, not global.
    blob = _synthetic_blob()
    for killer in (1, 2):
        blob["events"].append(
            {
                "event_type": "CHAMPION_SPECIAL_KILL",
                "timestamp_ms": 800000 + killer * 1000,
                "killer_id": killer,
                "victim_id": None,
                "raw_json": '{"killType": "KILL_MULTI", "multiKillLength": 2}',
            }
        )
    assert len(_only_special(build_narrative(blob))) == 2


def test_raw_json_accepts_already_parsed_dict():
    blob = _special_kill_blob(
        {"killType": "KILL_MULTI", "multiKillLength": 3}, killer_id=2)
    assert "Triple Kill" in _only_special(build_narrative(blob))[0]["text"]


def test_failsoft_malformed_special_kill_raw_json():
    for bad in (None, "", "not json", "[]", 42, '{"killType": null}',
                '{"killType": "KILL_MULTI"}'):
        result = build_narrative(_special_kill_blob(bad, killer_id=2))
        assert result["ok"] is True
        moments = _only_special(result)
        # It still renders as a moment; it must never raise and never emit a
        # None-shaped label.
        assert len(moments) == 1
        assert moments[0]["text"]
        assert "None" not in moments[0]["text"]
