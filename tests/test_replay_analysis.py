"""Thin end-to-end slice: does the pipeline answer one real coaching question?

Question under test: before a drake, did the tracked jungler path to the wrong
side of the map, and how late were they?

Everything here runs on a NEUTRAL shape (Timeline) so the same derivations can
later be fed by live `:2999` snapshots instead of a replay timeline. That is the
point of the slice - not the drake verdict itself.
"""
from __future__ import annotations

from core import replay_analysis as ra

# One synthetic timeline, hand-built so every assertion has a known answer.
# Frames are 60 s apart, matching the measured Match-V5 frameInterval.
_RAW = {
    "info": {
        "frameInterval": 60000,
        "frames": [
            {"timestamp": 0, "participantFrames": {}, "events": []},
            {   # t=60s: jungler top side, far from the drake pit
                "timestamp": 60000,
                "participantFrames": {
                    "7": {"participantId": 7, "position": {"x": 4000, "y": 11000},
                          "totalGold": 1200, "xp": 900, "level": 3,
                          "minionsKilled": 0, "jungleMinionsKilled": 12},
                },
                "events": [],
            },
            {   # t=120s: jungler has rotated bot side, near the pit
                "timestamp": 120000,
                "participantFrames": {
                    "7": {"participantId": 7, "position": {"x": 9500, "y": 4600},
                          "totalGold": 2000, "xp": 1600, "level": 5,
                          "minionsKilled": 2, "jungleMinionsKilled": 24},
                },
                "events": [
                    {"type": "ELITE_MONSTER_KILL", "timestamp": 125000,
                     "killerId": 7, "monsterType": "DRAGON",
                     "position": {"x": 9866, "y": 4414}},
                ],
            },
        ],
    }
}


def _tl():
    return ra.normalize_timeline(_RAW)


# ------------------------------------------------------------- normalisation

def test_normalize_pulls_frames_and_events_into_one_neutral_shape():
    tl = _tl()
    assert tl.frame_interval_ms == 60000
    assert len(tl.frames) == 2          # the empty t=0 frame carries no players
    assert len(tl.events) == 1


def test_a_frame_sample_carries_position_and_economy():
    tl = _tl()
    first = [f for f in tl.frames if f.t_ms == 60000][0]
    assert (first.x, first.y) == (4000, 11000)
    assert first.participant_id == 7
    assert first.total_gold == 1200
    assert first.jungle_cs == 12


def test_events_keep_their_own_sub_second_timestamp_not_the_frame_bucket():
    # The whole value of the event stream is that it is NOT quantised to 60 s.
    tl = _tl()
    assert tl.events[0].t_ms == 125000
    assert tl.events[0].t_ms % 60000 != 0


def test_objective_events_filter_by_monster_type():
    tl = _tl()
    assert [e.t_ms for e in ra.objective_events(tl, "DRAGON")] == [125000]
    assert ra.objective_events(tl, "BARON_NASHOR") == []


# --------------------------------------------------------- position sampling

def test_position_at_returns_the_nearest_frame_and_reports_its_age():
    # 60 s sampling means a lookup is ALWAYS an approximation; the caller must
    # be able to see how stale the sample is or the verdict is unfalsifiable.
    tl = _tl()
    sample = ra.position_at(tl, 7, 125000)
    assert (sample.x, sample.y) == (9500, 4600)
    assert sample.age_s == 5.0


def test_position_at_is_none_for_an_unknown_participant():
    assert ra.position_at(_tl(), 99, 60000) is None


def test_position_at_flags_a_sample_older_than_the_frame_interval():
    sample = ra.position_at(_tl(), 7, 300000)
    assert sample.stale is True


# ------------------------------------------------------------- the derivation

def test_approach_reports_distance_at_each_lead_time():
    tl = _tl()
    ap = ra.objective_approach(tl, participant_id=7, event=tl.events[0],
                               leads_s=(5, 65))
    by_lead = {a.lead_s: a for a in ap}
    # 5 s before the kill the nearest sample is the bot-side one, close in.
    assert by_lead[5].distance < 1000
    # 65 s before, the nearest sample is the top-side one, far away.
    assert by_lead[65].distance > 8000


def test_approach_marks_the_wrong_side_of_the_map():
    tl = _tl()
    ap = ra.objective_approach(tl, participant_id=7, event=tl.events[0],
                               leads_s=(65,))
    assert ap[0].same_half is False


def test_approach_at_the_objective_is_the_right_side():
    tl = _tl()
    ap = ra.objective_approach(tl, participant_id=7, event=tl.events[0],
                               leads_s=(5,))
    assert ap[0].same_half is True


def test_the_verdict_is_late_when_the_jungler_was_far_at_the_lead():
    tl = _tl()
    v = ra.drake_pathing_verdict(tl, participant_id=7, lead_s=65)
    assert v[0].verdict == "LATE"
    assert "drake" in v[0].coaching.lower()


def test_the_verdict_carries_provenance_not_just_a_number():
    # A coaching line built on a 60 s sample must say so, per the metric
    # provenance rule - otherwise it reads as a measurement it is not.
    tl = _tl()
    v = ra.drake_pathing_verdict(tl, participant_id=7, lead_s=65)
    assert v[0].source == "match_v5_timeline"
    assert v[0].sample_age_s >= 0


def test_no_objectives_yields_no_verdicts_rather_than_a_default():
    empty = ra.normalize_timeline({"info": {"frameInterval": 60000, "frames": []}})
    assert ra.drake_pathing_verdict(empty, participant_id=7) == []


def test_pit_coordinates_are_named_constants_not_magic_numbers():
    assert ra.DRAGON_PIT == (9866, 4414)
    assert ra.MAP_MAX > 14000
