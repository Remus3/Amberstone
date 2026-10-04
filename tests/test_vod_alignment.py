"""RM-637 (directive X-37, ADR-016): pure VOD alignment tracker.

Synthetic sequences only (no live payloads). Behaviour observed in external
references C/E/G/H, re-implemented clean-room:
  - alignment is PROVEN only on polls where gameTime advanced;
  - a frozen 0 during loading, and a pause, are ignored;
  - markers seen before proof are provisional and rewritten at finalize;
  - video_time is clamped to >= 0;
  - a game that ends before proof falls back to 1:1.

Convention: video_time = game_time + offset, where video_time is seconds since
the recording started.
"""
from __future__ import annotations

import pytest

from core.vod_alignment import AlignmentTracker, Poll

REC = 1000.0  # synthetic record-start wall stamp


def _feed(tr, seq):
    for wall, gt in seq:
        tr.observe(Poll(wall=REC + wall, game_time=gt))


def test_frozen_zero_loading_is_not_proof():
    tr = AlignmentTracker(record_start_wall=REC)
    # 40 s of loading screen: gameTime reads 0 every poll.
    _feed(tr, [(t, 0.0) for t in range(0, 41, 2)])
    assert tr.proven is False
    # First advance proves: video 42 s, game 1.0 s -> offset 41.
    tr.observe(Poll(wall=REC + 42.0, game_time=1.0))
    assert tr.proven is True
    assert tr.video_time_for(1.0) == pytest.approx(42.0)
    assert tr.resolve()["game_time_offset_s"] == pytest.approx(41.0)


def test_first_poll_alone_is_never_proof():
    tr = AlignmentTracker(record_start_wall=REC)
    tr.observe(Poll(wall=REC + 5.0, game_time=300.0))
    assert tr.proven is False


def test_pause_is_ignored_and_post_pause_reanchors():
    tr = AlignmentTracker(record_start_wall=REC)
    # Loading 10 s, then play: video 10 = game 0.
    _feed(tr, [(0, 0.0), (10, 0.0)])
    _feed(tr, [(10 + s, float(s)) for s in range(1, 101)])  # game 1..100
    assert tr.video_time_for(50.0) == pytest.approx(60.0)
    # Pause for 30 s at game 100: frozen polls do not move the offset.
    _feed(tr, [(110 + s, 100.0) for s in range(1, 31)])
    assert tr.video_time_for(50.0) == pytest.approx(60.0)
    # Resume: game 101 at video 141 -> new anchor offset 40 for game >= 101.
    tr.observe(Poll(wall=REC + 141.0, game_time=101.0))
    assert tr.video_time_for(50.0) == pytest.approx(60.0)
    assert tr.video_time_for(120.0) == pytest.approx(160.0)
    res = tr.resolve()
    assert res["proven"] is True
    assert len(res["anchors"]) == 2


def test_jitter_within_tolerance_does_not_add_anchors():
    tr = AlignmentTracker(record_start_wall=REC)
    _feed(tr, [(0, 0.0), (5, 0.0)])
    for s in range(1, 200):
        jitter = 0.1 if s % 2 else -0.1
        tr.observe(Poll(wall=REC + 5 + s + jitter, game_time=float(s)))
    assert len(tr.resolve()["anchors"]) == 1


def test_reconnect_starting_at_600():
    tr = AlignmentTracker(record_start_wall=REC)
    # Recording starts while the client reconnects; first reads are a
    # frozen 600, then play resumes at 600.5 when video is 20 s in.
    _feed(tr, [(0, 600.0), (5, 600.0), (10, 600.0)])
    assert tr.proven is False
    tr.observe(Poll(wall=REC + 20.0, game_time=600.5))
    assert tr.proven is True
    res = tr.resolve()
    assert res["game_time_offset_s"] == pytest.approx(-580.5)
    assert tr.video_time_for(610.0) == pytest.approx(29.5)
    # A game time before the recording began clamps to 0, never negative.
    assert tr.video_time_for(100.0) == 0.0


def test_provisional_markers_rewritten_at_finalize():
    tr = AlignmentTracker(record_start_wall=REC)
    _feed(tr, [(0, 0.0)])
    m = tr.mark(game_time=0.0, wall=REC + 3.0, key="1", label="GameStart")
    assert m["provisional"] is True
    _feed(tr, [(10, 0.0), (12, 2.0)])  # proof: offset 10
    tr.mark(game_time=5.0, wall=REC + 15.0, key="2", label="FirstBlood")
    res = tr.resolve()
    by_key = {x["key"]: x for x in res["markers"]}
    assert by_key["1"]["provisional"] is False
    assert by_key["1"]["video_time"] == pytest.approx(10.0)
    assert by_key["2"]["video_time"] == pytest.approx(15.0)
    assert all(x["provisional"] is False for x in res["markers"])


def test_game_ends_before_proof_falls_back_one_to_one():
    tr = AlignmentTracker(record_start_wall=REC)
    _feed(tr, [(0, 0.0), (5, 0.0), (9, 0.0)])
    tr.mark(game_time=0.0, wall=REC + 9.0, key="x", label="GameEnd")
    res = tr.resolve()
    assert res["proven"] is False
    assert res["method"] == "fallback_1to1"
    assert res["game_time_offset_s"] == 0.0
    assert res["markers"][0]["video_time"] == 0.0
    assert res["markers"][0]["provisional"] is False


def test_video_time_clamped_non_negative_everywhere():
    tr = AlignmentTracker(record_start_wall=REC)
    _feed(tr, [(0, 900.0), (2, 901.0)])  # offset = 2 - 901
    m = tr.mark(game_time=10.0, wall=REC - 50.0, key="k")
    assert m["video_time"] >= 0.0
    assert all(x["video_time"] >= 0.0 for x in tr.resolve()["markers"])


def test_garbage_polls_are_ignored():
    tr = AlignmentTracker(record_start_wall=REC)
    for bad in (None, {"game_time": "x", "wall": REC}, Poll(wall=REC, game_time=float("nan"))):
        tr.observe(bad)
    assert tr.proven is False
    tr.observe({"wall": REC + 1.0, "game_time": 0.0})
    tr.observe({"wall": REC + 3.0, "game_time": 1.0})
    assert tr.proven is True


def test_game_time_drop_resets_baseline_without_proof():
    tr = AlignmentTracker(record_start_wall=REC)
    _feed(tr, [(0, 50.0), (1, 51.0)])
    n = len(tr.resolve()["anchors"])
    # A drop is not an advance and must not create an anchor by itself.
    tr.observe(Poll(wall=REC + 2.0, game_time=10.0))
    assert len(tr.resolve()["anchors"]) == n
