"""Lane 8 (true-audit) s144 cycle 179: core/metric_streamer.py.

MetricStreamer decides WHEN a live coach tick becomes match_metrics rows
(core.live_metrics.stream() calls on_state() on every sr / aram / arena /
brawl coaching write when live metrics are enabled). The module had no test
file at all. These tests pin the documented cadence and the hardening:

  - a missing / bool / NaN / infinite / negative / string game clock is
    UNKNOWN: it never raises and is never recorded as 0:00 (the old code
    stored a fabricated game_time_s=0 and raised on NaN / infinity);
  - a NaN / infinite level or an unhashable event never raises; a bare
    string event is one event, not a sequence of characters;
  - a milestone snapshot consumes the 60 s periodic bucket, so the next tick
    does not write a near-duplicate periodic row (the "avoids double-writes"
    comment was only true for the same tick);
  - a time mark more than one periodic interval stale (a late-joined
    streamer after an RC restart, or a stalled coach) is consumed without a
    mislabelled snapshot, and level milestones already passed on the FIRST
    tick are consumed; several level milestones crossed in one later tick
    snapshot only the highest;
  - close() flushes outside the cadence lock, so a slow DB write in close()
    does not block a concurrent on_state().

A fake recorder stands in for core.match_metrics.recorder, so no test opens
a database.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from core import metric_streamer as ms
from tests._timing_budget import fleet_test_guard

_REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeRecorder:
    """Records every snapshot call; returns ROWS rows per snapshot."""

    ROWS = 2

    def __init__(self) -> None:
        self.snaps: list[dict] = []
        self.flushes = 0
        self.flush_hook = None

    def record_state_snapshot(self, payload, **kw):
        self.snaps.append(dict(kw))
        return self.ROWS

    def flush(self):
        self.flushes += 1
        if self.flush_hook is not None:
            self.flush_hook(self.flushes)
        return 0


@pytest.fixture
def rec(monkeypatch):
    fake = _FakeRecorder()
    monkeypatch.setattr(ms, "recorder", fake)
    return fake


def _tags(rec):
    return [s["milestone_tag"] for s in rec.snaps]


def _streamer(**kw):
    kw.setdefault("match_id", "M-SYNTH-1")
    return ms.MetricStreamer(**kw)


# ---------- characterization: the documented cadence -----------------------

def test_first_tick_fires_game_start_and_flushes(rec):
    s = _streamer()
    rows = s.on_state({"game_time_s": 0, "level": 1})
    assert _tags(rec) == ["game_start"]
    assert rec.snaps[0]["game_time_s"] == 0
    assert rows == _FakeRecorder.ROWS
    assert rec.flushes == 1


def test_quiet_tick_buffers_nothing_and_does_not_flush(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    flushes = rec.flushes
    assert s.on_state({"game_time_s": 30}) == 0
    assert rec.snaps == []
    assert rec.flushes == flushes


def test_periodic_sample_every_60s_once_per_bucket(rec):
    s = _streamer()
    for gt in (0, 30, 60, 61, 119, 120, 179):
        s.on_state({"game_time_s": gt})
    assert _tags(rec) == ["game_start", None, None]
    assert [x["game_time_s"] for x in rec.snaps] == [0, 60, 120]


def test_level_milestone_fires_once_on_transition(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0, "level": 5})
    s.on_state({"game_time_s": 10, "level": 6})
    s.on_state({"game_time_s": 20, "level": 6})
    s.on_state({"game_time_s": 30, "level": 7})
    assert _tags(rec) == ["game_start", "l6_spike"]


def test_time_mark_fires_once_on_time_and_consumes_its_bucket(rec):
    # Not pure characterization: the old code also wrote a periodic row at
    # 605 (same 60 s bucket as the mark) - the duplicate this audit fixed.
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s.on_state({"game_time_s": 601})
    s.on_state({"game_time_s": 605})
    assert _tags(rec) == ["10min_mark"]


def test_events_single_fire_and_multi_fire(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s.on_state({"game_time_s": 5}, events=["first_blood", "kill", "bogus"])
    s.on_state({"game_time_s": 6}, events=["first_blood", "kill"])
    s.on_state({"game_time_s": 7}, events=["drake_lost"])
    assert _tags(rec) == ["first_blood", "kill", "kill",
                          "drake_contested_loss"]


def test_game_end_fires_once(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s.on_state({"game_time_s": 900}, game_end=True)
    s.on_state({"game_time_s": 901}, game_end=True)
    assert _tags(rec).count("game_end") == 1


def test_non_dict_payload_is_a_noop(rec):
    s = _streamer()
    for bad in (None, [], "x", 3):
        assert s.on_state(bad) == 0
    assert rec.snaps == [] and rec.flushes == 0


def test_identity_fields_and_payload_fallbacks(rec):
    s = _streamer(session_id="S1")
    s.on_state({"game_time_s": 0, "champion": "Vayne", "game_mode": "ARAM"})
    snap = rec.snaps[0]
    assert snap["match_id"] == "M-SYNTH-1"
    assert snap["session_id"] == "S1"
    assert snap["champion"] == "Vayne"
    assert snap["mode"] == "ARAM"
    assert snap["provenance"] == "source_truth"
    rec.snaps.clear()
    s2 = _streamer(champion="Trist", mode="sr")
    s2.on_state({"game_time_s": 0, "champion": "Vayne", "game_mode": "ARAM"})
    assert rec.snaps[0]["champion"] == "Trist"
    assert rec.snaps[0]["mode"] == "sr"


def test_flush_error_propagates_and_cadence_state_is_kept(rec):
    def boom(n):
        raise RuntimeError("database is locked")
    rec.flush_hook = boom
    s = _streamer()
    with pytest.raises(RuntimeError):
        s.on_state({"game_time_s": 0})
    rec.flush_hook = None
    s.on_state({"game_time_s": 1})
    assert _tags(rec) == ["game_start"]


def test_close_flushes(rec):
    s = _streamer()
    s.close()
    assert rec.flushes == 1


# ---------- hardening: the game clock -------------------------------------

@pytest.mark.parametrize("clock", [
    None, True, False, "600", float("nan"), float("inf"), float("-inf"),
    -5, -0.5,
])
def test_unknown_clock_never_raises_and_is_never_recorded_as_zero(rec, clock):
    s = _streamer()
    payload = {"level": 1}
    if clock is not None:
        payload["game_time_s"] = clock
    s.on_state(payload)
    assert _tags(rec) == ["game_start"]
    assert rec.snaps[0]["game_time_s"] is None


def test_unknown_clock_fires_no_time_mark_and_no_periodic(rec):
    s = _streamer()
    s.on_state({"game_time_s": float("inf")})
    s.on_state({"game_time_s": float("nan")})
    s.on_state({"game_time_s": -1e9})
    assert _tags(rec) == ["game_start"]


def test_float_clock_truncates_to_whole_seconds(rec):
    s = _streamer()
    s.on_state({"game_time_s": 59.9})
    assert rec.snaps[0]["game_time_s"] == 59


# ---------- hardening: level and events -----------------------------------

@pytest.mark.parametrize("level", [float("nan"), float("inf"), -3, True,
                                   "11", None])
def test_bad_level_never_raises_and_fires_no_level_milestone(rec, level):
    s = _streamer()
    s.on_state({"game_time_s": 0, "level": 1})
    s.on_state({"game_time_s": 1, "level": level})
    assert _tags(rec) == ["game_start"]
    # a bad reading does not reset progress: the real transition still fires
    s.on_state({"game_time_s": 2, "level": 6})
    assert _tags(rec) == ["game_start", "l6_spike"]


def test_unhashable_or_non_str_event_is_skipped_not_raised(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s.on_state({"game_time_s": 5}, events=[["kill"], {"k": 1}, 7, None,
                                            "death"])
    assert _tags(rec) == ["death"]


def test_bare_string_event_is_one_event(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s.on_state({"game_time_s": 5}, events="death")
    assert _tags(rec) == ["death"]


@pytest.mark.parametrize("events", [{"death": 1}, 7, object()])
def test_non_sequence_events_are_ignored(rec, events):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    assert s.on_state({"game_time_s": 5}, events=events) == 0
    assert rec.snaps == []


# ---------- hardening: duplicate and mislabelled snapshots -----------------

def test_milestone_consumes_the_periodic_bucket(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    s.on_state({"game_time_s": 595})
    rec.snaps.clear()
    s.on_state({"game_time_s": 600})   # 10min_mark
    s.on_state({"game_time_s": 601})   # same 60 s bucket: nothing
    s.on_state({"game_time_s": 660})   # next bucket: periodic
    assert _tags(rec) == ["10min_mark", None]


def test_mid_game_first_tick_consumes_its_periodic_bucket(rec):
    s = _streamer()
    s.on_state({"game_time_s": 125})
    s.on_state({"game_time_s": 126})
    s.on_state({"game_time_s": 180})
    assert _tags(rec) == ["game_start", None]
    assert rec.snaps[1]["game_time_s"] == 180


def test_late_join_does_not_backfill_stale_marks_or_passed_levels(rec):
    # RC restarted mid-game: the first tick is at 25:30, level 12.
    s = _streamer()
    s.on_state({"game_time_s": 1530, "level": 12})
    assert _tags(rec) == ["game_start", "25min_mark"]
    rec.snaps.clear()
    s.on_state({"game_time_s": 1531, "level": 13})
    s.on_state({"game_time_s": 1800, "level": 16})
    # level milestones are evaluated before time marks within a tick
    assert _tags(rec) == ["l16_spike", "30min_mark"]


def test_stalled_coach_skips_the_stale_mark(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    s.on_state({"game_time_s": 590})
    rec.snaps.clear()
    s.on_state({"game_time_s": 950})   # 10min mark 350 s stale; 15min fresh
    assert _tags(rec) == ["15min_mark"]
    s.on_state({"game_time_s": 951})
    assert _tags(rec) == ["15min_mark"]


def test_mark_exactly_one_interval_late_is_stale(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s.on_state({"game_time_s": 600 + ms._PERIODIC_INTERVAL_S - 1})
    assert _tags(rec) == ["10min_mark"]
    s2 = _streamer()
    rec.snaps.clear()
    s2.on_state({"game_time_s": 0})
    rec.snaps.clear()
    s2.on_state({"game_time_s": 600 + ms._PERIODIC_INTERVAL_S})
    assert _tags(rec) == [None]


def test_late_join_with_no_level_on_the_first_tick_still_seeds(rec):
    # The first tick of a mid-game join carries no level; the first level
    # reading (12) must not mislabel level-12 data as l6 / l11.
    s = _streamer()
    s.on_state({"game_time_s": 1530})
    rec.snaps.clear()
    s.on_state({"game_time_s": 1540, "level": 12})
    assert _tags(rec) == []
    s.on_state({"game_time_s": 1700, "level": 16})
    assert _tags(rec) == ["l16_spike"]


def test_level_jump_in_one_tick_snapshots_only_the_highest(rec):
    # Arena levels move by several per round.
    s = _streamer()
    s.on_state({"game_time_s": 0, "level": 5})
    rec.snaps.clear()
    s.on_state({"game_time_s": 10, "level": 12})
    assert _tags(rec) == ["l11_spike"]
    s.on_state({"game_time_s": 20, "level": 13})
    assert _tags(rec) == ["l11_spike"]


def test_normal_start_at_level_one_still_fires_every_level_spike(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0, "level": 1})
    for gt, lvl in ((100, 6), (200, 11), (300, 16)):
        s.on_state({"game_time_s": gt, "level": lvl})
    assert _tags(rec) == ["game_start", "l6_spike", "l11_spike", "l16_spike"]


# ---------- hardening: close() does not hold the cadence lock --------------

def test_close_flush_does_not_block_a_concurrent_on_state(rec):
    s = _streamer()
    s.on_state({"game_time_s": 0})
    entered = threading.Event()
    release = threading.Event()

    def hook(n):
        if n == 2:              # the close() flush
            entered.set()
            release.wait(5)
    rec.flush_hook = hook
    closer = threading.Thread(target=s.close, name="close-test", daemon=True)
    closer.start()
    assert entered.wait(fleet_test_guard.budget(5))
    done = threading.Event()

    def tick():
        s.on_state({"game_time_s": 60})
        done.set()
    ticker = threading.Thread(target=tick, name="tick-test", daemon=True)
    ticker.start()
    finished = done.wait(2)
    release.set()
    closer.join(5)
    ticker.join(5)
    assert finished, "on_state blocked behind close()'s flush"


# ---------- end to end against a real recorder in tmp_path -----------------

def test_real_recorder_stores_unknown_clock_as_null(monkeypatch, tmp_path):
    import sqlite3

    from core import match_metrics as mm
    monkeypatch.setattr(mm, "DB_PATH", tmp_path / "match_metrics.db")
    real = mm.Recorder()
    monkeypatch.setattr(ms, "recorder", real)
    s = _streamer()
    assert s.on_state({"digest_state": "hot", "game_time_s": float("nan")}) == 1
    s.on_state({"digest_state": "hot", "game_time_s": 600})
    conn = sqlite3.connect(tmp_path / "match_metrics.db")
    try:
        got = conn.execute(
            "SELECT milestone_tag, recorded_at_game_time_s FROM match_metrics "
            "ORDER BY id").fetchall()
    finally:
        conn.close()
    assert got == [("game_start", None), ("10min_mark", 600)]
    assert real.buffered() == 0


# ---------- hygiene -------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "core/metric_streamer.py",
    "tests/test_metric_streamer_true_audit_s144.py",
])
def test_ascii_lf_only(rel):
    raw = (_REPO_ROOT / rel).read_bytes()
    assert b"\r" not in raw
    assert all(b < 127 for b in raw)
