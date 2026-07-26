"""The :2999 replay seek sampler - second producer for the neutral Timeline.

Transport is injected, so every case here runs headless. Live verification
needs a replay actually playing with EnableReplayApi=1; see the module docstring.
"""
from __future__ import annotations

import pytest

from core import replay_analysis as ra
from core import replay_seek as rs

_ALLGAME = {
    "gameData": {"gameMode": "CLASSIC", "gameTime": 600.0},
    "allPlayers": [
        {"summonerName": "A", "championName": "Vi", "level": 11,
         "position": "JUNGLE", "team": "ORDER",
         "scores": {"kills": 3, "deaths": 1, "assists": 7, "creepScore": 112},
         "items": [{"itemID": 6692}, {"itemID": 3111}]},
        {"summonerName": "B", "championName": "Lux", "level": 12,
         "position": "MIDDLE", "team": "CHAOS",
         "scores": {"kills": 5, "deaths": 2, "assists": 3, "creepScore": 140},
         "items": [{"itemID": 6655}]},
    ],
}


class _FakeClient:
    """Records seeks and serves a canned state, with gameTime following seeks."""

    def __init__(self, fail_seek=False):
        self.seeks = []
        self.fail_seek = fail_seek

    def post_playback(self, t_s):
        if self.fail_seek:
            raise OSError("connection refused")
        self.seeks.append(t_s)

    def get_allgamedata(self):
        blob = dict(_ALLGAME)
        blob["gameData"] = dict(_ALLGAME["gameData"])
        blob["gameData"]["gameTime"] = self.seeks[-1] if self.seeks else 0.0
        return blob


# ------------------------------------------------------------------ sampling

def test_sample_at_seeks_then_reads():
    c = _FakeClient()
    s = rs.sample_at(c, 600.0)
    assert c.seeks == [600.0]
    assert s.t_s == 600.0
    assert len(s.players) == 2


def test_a_player_state_carries_items_level_and_scores():
    s = rs.sample_at(_FakeClient(), 600.0)
    vi = [p for p in s.players if p.champion == "Vi"][0]
    assert vi.level == 11
    assert vi.item_ids == [6692, 3111]
    assert vi.cs == 112
    assert (vi.kills, vi.deaths, vi.assists) == (3, 1, 7)


def test_the_role_string_is_kept_as_a_role_never_as_a_coordinate():
    # :2999 `position` is 'JUNGLE'/'MIDDLE'/... - a role, NOT map coords.
    s = rs.sample_at(_FakeClient(), 600.0)
    vi = [p for p in s.players if p.champion == "Vi"][0]
    assert vi.role == "JUNGLE"
    assert not hasattr(vi, "x")


def test_sample_series_seeks_each_requested_time_in_order():
    c = _FakeClient()
    out = rs.sample_series(c, [0.0, 30.0, 60.0])
    assert c.seeks == [0.0, 30.0, 60.0]
    assert [s.t_s for s in out] == [0.0, 30.0, 60.0]


def test_a_failed_seek_is_reported_not_silently_skipped():
    with pytest.raises(rs.SeekError):
        rs.sample_at(_FakeClient(fail_seek=True), 600.0)


def test_sample_series_survives_one_bad_seek_and_records_it():
    class _Flaky(_FakeClient):
        def post_playback(self, t_s):
            if t_s == 30.0:
                raise OSError("nope")
            self.seeks.append(t_s)

    c = _Flaky()
    out, failed = rs.sample_series_lenient(c, [0.0, 30.0, 60.0])
    assert [s.t_s for s in out] == [0.0, 60.0]
    assert failed == [30.0]


# ----------------------------------------------- bridging to the neutral shape

def test_samples_convert_into_the_same_timeline_shape_the_derivations_use():
    c = _FakeClient()
    tl = rs.to_timeline(rs.sample_series(c, [0.0, 30.0]))
    assert isinstance(tl, ra.Timeline)
    assert len(tl.frames) == 4                 # 2 players x 2 samples
    assert tl.frame_interval_ms == 30000       # inferred from the seek spacing


def test_the_timeline_from_a_seek_sampler_declares_it_has_no_positions():
    # THE GUARD THAT MATTERS. :2999 exposes no coordinates, so frames carry
    # x=y=0. Without this flag a distance derivation would happily measure
    # from the map origin and return confident nonsense.
    tl = rs.to_timeline(rs.sample_series(_FakeClient(), [0.0, 30.0]))
    assert tl.positions_available is False


def test_a_match_v5_timeline_does_declare_positions():
    tl = ra.normalize_timeline({"info": {"frameInterval": 60000, "frames": [
        {"timestamp": 0, "participantFrames": {
            "1": {"participantId": 1, "position": {"x": 5, "y": 6}}}, "events": []}]}})
    assert tl.positions_available is True


def test_position_at_refuses_a_timeline_that_has_no_positions():
    tl = rs.to_timeline(rs.sample_series(_FakeClient(), [0.0, 30.0]))
    with pytest.raises(ValueError, match="no position data"):
        ra.position_at(tl, 1, 0)


def test_the_drake_verdict_refuses_a_positionless_timeline_too():
    tl = rs.to_timeline(rs.sample_series(_FakeClient(), [0.0, 30.0]))
    tl.events.append(ra.TimelineEvent(t_ms=1000, type="ELITE_MONSTER_KILL",
                                      monster_type="DRAGON", killer_team_id=200))
    with pytest.raises(ValueError, match="no position data"):
        ra.drake_pathing_verdict(tl, participant_id=7)


def test_item_state_is_the_thing_this_producer_uniquely_gives():
    # Sub-minute inventory at an arbitrary timestamp, which is the whole
    # reason the seek lane exists for event modes.
    tl = rs.to_timeline(rs.sample_series(_FakeClient(), [600.0]))
    assert tl.frames[0].item_ids == [6692, 3111]
